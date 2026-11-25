"""Поиск плат запросами UDS в заданном диапазоне без изменения адресов и режима Tx."""

from __future__ import annotations

import time

from .bus_guard import background_request_recent, note_background_request, uds_exchange_busy
from .contract import AppControllerContract


SCAN_IDENTITY = (0x0011, "address", 1, False, 1)
SCAN_VALUES = ((0x003B, "boardTemp", 2, True, 10),
               (0x0019, "fuelTemp", 2, True, 10),
               (0x0018, "level", 2, True, 10))


def scan_address(text: str) -> int | None:
    """Для одинакового ввода адресов разбирает шестнадцатеричные формы 81, 0x81 и 81h."""
    raw = str(text or "").strip().lower()
    raw = raw.removeprefix("0x").removesuffix("h")
    try:
        return int(raw, 16) if 0 < len(raw) <= 2 else None
    except ValueError:
        return None


class AppControllerBoardScanMixin(AppControllerContract):
    ADDR_SCAN_WAIT_S = 0.6
    ADDR_SCAN_MAX_WAIT_S = 3.0
    ADDR_SCAN_ATTEMPTS = 2
    ADDR_SCAN_REPEAT_S = 2.0

    def _addr_scan_init(self):
        """Для безопасного первого запуска задаёт диапазон и пустое состояние поиска до старта таймера."""
        self._addr_scan = {"active": False, "stopping": False, "start": 0x80, "end": 0x8F,
                           "repeat": False, "auto": False, "auto_wait": False, "auto_try": 0.0,
                           "addresses": [], "index": 0, "queue": [], "pending": None,
                           "rows": {}, "cycle": 0, "next_cycle": 0.0,
                           "status": "Задайте диапазон и нажмите «Найти платы».", "tone": "normal"}

    def _addr_scan_load(self, payload: dict):
        """Для повторного открытия раздела возвращает сохранённые границы и настройки поиска."""
        saved = payload.get("scan")
        if not isinstance(saved, dict):
            return
        start, end = saved.get("start"), saved.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= 0xFD:
            self._addr_scan.update(start=start, end=end)
        for key in ("repeat", "auto"):
            if isinstance(saved.get(key), bool):
                self._addr_scan[key] = saved[key]

    def _addr_scan_configure(self, start_text: str, end_text: str, repeat: bool, auto: bool) -> tuple[bool, str]:
        """Для управляемого поиска проверяет диапазон и сохраняет его без запросов к платам."""
        scan = self._addr_scan
        if scan["active"]:
            return False, "Сначала остановите поиск, чтобы изменить диапазон."
        start, end = scan_address(start_text), scan_address(end_text)
        if start is None or end is None or not 0 <= start <= end <= 0xFD:
            scan.update(status="Укажите диапазон HEX от 00 до FD: начальный адрес не больше конечного.", tone="bad")
            self._addr_changed()
            return False, scan["status"]
        settings = {"start": start, "end": end, "repeat": bool(repeat), "auto": bool(auto)}
        changed = any(scan[key] != value for key, value in settings.items())
        scan.update(settings)
        if not auto:
            scan["auto_wait"] = False
        if changed:
            self._addr_save_settings()
        self._addr_changed()
        return True, "Диапазон сохранён."

    def _addr_scan_start(self, start_text: str, end_text: str, repeat=False, auto=False, *, one_pass=False) -> tuple[bool, str]:
        """Для обнаружения молчащих плат начинает последовательный опрос только командами чтения."""
        scan = self._addr_scan
        if scan["active"]:
            return False, "Поиск уже идёт."
        ok, text = self._addr_scan_configure(start_text, end_text, repeat, auto)
        if not ok:
            return ok, text
        can = getattr(self, "_can", None)
        reason = ""
        if can is not None and (not getattr(can, "is_connect", False) or not getattr(can, "is_trace", False)):
            reason = "Подключите адаптер CAN и включите трассировку."
        elif self._addr_active or self._addr_comm is not None or self._addr_comm_queue:
            reason = "Дождитесь завершения мастера адресов или команды трафика."
        elif getattr(self, "_climate_run_stage", ""):
            reason = "Поиск доступен до или после прогона в камере."
        else:
            busy = uds_exchange_busy(self, ignore=("board_addressing",))
            if busy:
                reason = f"Дождитесь завершения обмена в другом разделе ({busy})."
        addresses = [sa for sa in range(scan["start"], scan["end"] + 1) if sa not in self._addr_tester_sas()]
        if not addresses:
            reason = "В диапазоне только адрес самой программы. Выберите адреса плат."
        if reason:
            scan.update(status=reason, tone="warn")
            self._addr_changed()
            return False, reason
        scan.update(active=True, stopping=False, one_pass=one_pass, before_scan=None, addresses=addresses, index=0, queue=[], pending=None,
                    rows={}, cycle=1, next_cycle=0.0, auto_wait=False,
                    status="Ищу платы запросами. Передача Tx и адреса не меняются.", tone="normal")
        self._addr_changed()
        return True, scan["status"]

    def _addr_scan_stop(self, reason="Поиск остановлен."):
        """Чтобы не прервать чужой ответ, завершает текущий запрос перед освобождением шины."""
        scan = self._addr_scan
        scan["auto_wait"] = False
        scan["stopping"] = True
        scan["status"] = reason
        if scan["pending"] is None:
            scan.update(active=False, stopping=False, queue=[])
        self._addr_changed()

    def _addr_scan_auto_tick(self, now: float):
        """Для поиска после перезапуска ждёт открытия раздела и подключения адаптера без частых попыток."""
        scan = self._addr_scan
        if (not scan["auto_wait"] or not self._addr_visible or scan["active"] or self._addr_active
                or now - scan["auto_try"] < 1):
            return
        scan["auto_try"] = now
        self._addr_scan_start(f"{scan['start']:02X}", f"{scan['end']:02X}", scan["repeat"], scan["auto"])

    def _addr_scan_send(self, pending: dict, now: float):
        """Для правильного ожидания ответа отмечает запрос до отправки и ограничивает число повторов."""
        pending["sent"] = now
        pending["attempt"] += 1
        note_background_request(self)
        did = pending["spec"][0]
        if not self._addr_send(pending["sa"], [0x22, did >> 8, did & 0xFF]):
            self._addr_scan["pending"] = None
            self._addr_scan["tone"] = "bad"
            self._addr_scan_stop("Поиск остановлен: не удалось отправить запрос через адаптер CAN.")

    def _addr_scan_tick(self, now: float):
        """Для поиска без блокировки окна ведёт один запрос за такт, таймауты и повторные проходы."""
        scan = self._addr_scan
        can = getattr(self, "_can", None)
        if can is not None and (not getattr(can, "is_connect", False) or not getattr(can, "is_trace", False)):
            scan["pending"] = None
            scan["tone"] = "bad"
            self._addr_scan_stop("Поиск остановлен: связь с адаптером CAN потеряна.")
            return
        pending = scan["pending"]
        if pending is not None:
            if now - pending["sent"] < self.ADDR_SCAN_WAIT_S and now - pending["started"] < self.ADDR_SCAN_MAX_WAIT_S:
                return
            if scan["stopping"]:
                scan["pending"] = None
                self._addr_scan_stop(scan["status"])
                return
            maximum = self.ADDR_SCAN_ATTEMPTS if pending["spec"] == SCAN_IDENTITY else 1
            if (not scan["stopping"] and pending["attempt"] < maximum
                    and now - pending["started"] < self.ADDR_SCAN_MAX_WAIT_S):
                self._addr_scan_send(pending, now)
                return
            self._addr_scan_missing(pending, "нет ответа")
            scan["pending"] = None
        if scan["stopping"]:
            self._addr_scan_stop(scan["status"])
            return
        # Старые запросы карточек и присутствия сначала получают время на свой ответ.
        if self._addr_info_sa is not None:
            if now - self._addr_info_sent_s < self.ADDR_INFO_WAIT_S:
                return
            self._addr_info_sa = None
            self._addr_info_current = None
        if any(now - sent < self.ADDR_PING_ANSWER_S for sent in self._addr_ping_wait.values()):
            return
        busy = uds_exchange_busy(self, ignore=("board_addressing",))
        if busy:
            status = f"Поиск ждёт завершения обмена в другом разделе ({busy})."
            if scan["status"] != status:
                scan.update(status=status, tone="warn")
                self._addr_changed()
            return
        if background_request_recent(self):
            return
        if scan["next_cycle"]:
            if now < scan["next_cycle"]:
                return
            scan.update(index=0, cycle=scan["cycle"] + 1, next_cycle=0.0)
            for row in scan["rows"].values():
                row["present"] = None
        if scan["queue"]:
            sa, spec = scan["queue"].pop(0)
        elif scan["index"] < len(scan["addresses"]):
            sa = scan["addresses"][scan["index"]]
            scan["index"] += 1
            spec = SCAN_IDENTITY
        else:
            count = sum(row["present"] is True for row in scan["rows"].values())
            scan.update(status=f"Проход {scan['cycle']} завершён. Ответили адресов: {count}.", tone="ok")
            if scan["repeat"] and not scan["one_pass"]:
                scan["next_cycle"] = now + self.ADDR_SCAN_REPEAT_S
            else:
                scan["active"] = False
            self._addr_changed()
            return
        pending = {"sa": sa, "spec": spec, "attempt": 0, "started": now, "sent": now}
        scan["pending"] = pending
        scan.update(status=f"Проверяю 0x{sa:02X}: {scan['index']} из {len(scan['addresses'])} адресов.", tone="normal")
        self._addr_scan_send(pending, now)
        self._addr_changed()

    def _addr_scan_missing(self, pending: dict, reason: str):
        """Чтобы отсутствие ответа не выдавалось за нулевое измерение, отмечает недоступные данные."""
        sa, spec = pending["sa"], pending["spec"]
        row = self._addr_scan["rows"].get(sa)
        if spec == SCAN_IDENTITY:
            self._addr_scan.setdefault("missed_at", {})[sa] = self._addr_clock()
            self._addr_misses[sa] = self.ADDR_PING_MISSES
            if row is not None:
                row["present"] = False
        elif row is not None:
            row[spec[1]] = None
            self._addr_info.setdefault(sa, {})[spec[1]] = None
            row.setdefault("errors", {})[spec[1]] = reason
        self._addr_changed()

    def _addr_scan_answer(self, src: int, body: list[int], now: float) -> bool:
        """Чтобы не принять чужой ответ, сверяет адрес, SID, DID и размер данных текущего запроса."""
        scan = self._addr_scan
        pending = scan["pending"]
        if not scan["active"] or pending is None or src != pending["sa"]:
            return False
        if body[0] == 0x7F and len(body) >= 3 and body[1] == 0x22:
            if body[2] == 0x78:
                pending["sent"] = now
            else:
                self._addr_scan_missing(pending, f"отказ 0x{body[2]:02X}")
                scan["pending"] = None
            return True
        did, key, size, signed, divider = pending["spec"]
        if body[0] != 0x62 or len(body) != 3 + size or body[1:3] != [did >> 8, did & 0xFF]:
            return False
        raw = int.from_bytes(bytes(body[3:]), "little", signed=signed)
        if pending["spec"] == SCAN_IDENTITY and raw != src:
            self._addr_scan_missing(pending, "адрес в ответе не совпадает")
            scan["pending"] = None
            return True
        scan["pending"] = None
        if scan["stopping"]:
            return True
        if pending["spec"] == SCAN_IDENTITY:
            if self._mb_board(src) is None:
                ok, reason = self._mb_add_board(f"0x{src:02X}")
                if not ok:
                    self._addr_scan_stop("Не удалось добавить найденную плату: " + reason)
                    return True
            row = scan["rows"].setdefault(src, {})
            row.update(present=True, errors={}, identified_at=now)
            scan["queue"] += [(src, field) for field in SCAN_VALUES]
        else:
            row = scan["rows"][src]
            value = raw / divider
            row[key] = value
            row["readAt"] = time.strftime("%H:%M:%S")
            self._addr_info.setdefault(src, {}).update({key: value, "readAt": row["readAt"]})
            # Для списка участников камеры передаёт прочитанные значения в поля именно этой платы.
            live_key = {"boardTemp": "board_temp", "fuelTemp": "fuel_temp", "level": "level"}[key]
            with self._mb_live_context(src):
                self._chamber_live_note(live_key, raw, time.monotonic())
        self._addr_answered[src] = now
        self._addr_misses[src] = 0
        self._addr_changed()
        return True

    def _addr_scan_view(self) -> dict:
        """Для раздела адресов готовит диапазон, ход поиска и фактические показания найденных плат."""
        scan = self._addr_scan
        rows = []
        found = 0
        can = getattr(self, "_can", None)
        listening = can is None or (getattr(can, "is_connect", False) and getattr(can, "is_trace", False))
        for sa, row in sorted(scan["rows"].items()):
            # Для отсутствующих величин показывает прочерк, сохраняя знак отрицательного уровня и температуры.
            def value(key):
                return "—" if row.get(key) is None else f"{row[key]:+.1f}".replace(".", ",").replace("-", "−")
            present = row["present"]
            if not listening:
                present = None
            elif not scan["active"]:
                present = self._addr_shown_present(sa, self._addr_clock())
            found += present is True
            state = ("отвечает" if present is True else "нет ответа" if present is False else
                     "проверяется" if scan["active"] else "нет свежих данных")
            if present is True and row.get("errors"):
                state += "; часть данных недоступна"
            tone = "warn" if present is True and row.get("errors") else "ok" if present is True else "bad" if present is False else "normal"
            rows.append({"tone": tone,
                         "cells": {"sa": f"0x{sa:02X}", "name": self._mb_board(sa)["name"] if self._mb_board(sa) else "",
                                   "board": value("boardTemp"), "tube": value("fuelTemp"), "level": value("level"),
                                   "state": state, "time": row.get("readAt", "—")}})
        columns = [{"key": key, "title": title, "width": width, "align": "left", "tip": tip}
                   for key, title, width, tip in (
                       ("sa", "Адрес", 80, "Адрес, подтвердивший запрос UDS"), ("name", "Плата", 120, "Имя в списке плат"),
                       ("board", "Плата, °C", 90, "Температура платы"), ("tube", "Трубка, °C", 90, "Температура внешнего датчика"),
                       ("level", "Уровень, %", 100, "Показание прибора; прочерк означает отсутствие данных. Ноль сам по себе не подтверждает калибровку"),
                       ("state", "Состояние", 235, "Ответы последнего прохода поиска"), ("time", "Прочитано", 90, "Время чтения"))]
        return {"active": scan["active"], "stopping": scan["stopping"], "startText": f"0x{scan['start']:02X}",
                "endText": f"0x{scan['end']:02X}", "repeat": scan["repeat"], "auto": scan["auto"],
                "status": scan["status"], "tone": scan["tone"], "total": len(scan["addresses"]),
                "checked": scan["index"], "found": found,
                "table": {"id": "board-discovery", "title": "Найдены запросами", "columns": columns, "rows": rows}}
