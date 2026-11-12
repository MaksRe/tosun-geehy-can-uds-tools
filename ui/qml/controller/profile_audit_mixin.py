"""Проверка профиля и калибровки плат перед проверочным прогоном.

ЗАЧЕМ
Прогон «Проверка профиля» сам ничего не считает и ничего не пишет: он смотрит, как плата с уже
записанным профилем и калибровкой 0 %/100 % держит уровень по температуре. Если в плате профиль
пустой, не применяется, без строк трубки или без калибровки, сутки в камере пройдут впустую -
отклонения будут от того, чего в плате нет. Поэтому перед стартом программа сама читает из
каждой платы на шине состояние профиля, его таблицы и калибровку и не даёт начать, пока у
какой-нибудь платы чего-то не хватает (12.11.2026).

ЧТО ЧИТАЕТСЯ
- состояние профиля (0x0060): заполнен, сумма сходится, алгоритм тот, таблицы применяются;
  сумма (0x005E) - для протокола;
- таблицы: сетка узлов, плата (основной и вид топлива), строки трубки на воздухе и в жидкости;
- калибровка: период 0 % (0x0012) и 100 % (0x0013) - прошивка считает уровень, только если
  0 % меньше 100 %;
- поправка по виду топлива (0x002E) с её эталонами (0x002F, 0x0030) и модель по двум контурам
  (0x0053) с её отметками (0x0054, 0x0055): включённая без своих данных - тоже недостаток.

КАК ОБМЕНИВАЕТСЯ
Таблицы длиннее одного кадра, поэтому чтение идёт той же машинерией окна параметров (мультипакет),
по одному параметру за такт живого опроса камеры и только когда шина свободна. Ответы приходят
сюда по признаку происхождения запроса «audit_».
"""

from __future__ import annotations

import struct
import time

from uds.options_catalog import get_option_by_did

from .bus_guard import background_request_recent, uds_exchange_busy
from .contract import AppControllerContract

AUDIT_ORIGIN_PREFIX = "audit_"

# (имя, DID, обязателен ли): необязательных может не быть в старой прошивке - это не недостаток.
AUDIT_ITEMS = (
    ("status", 0x0060, True),
    ("crc", 0x005E, True),
    ("nodes", 0x004B, True),
    ("board_main", 0x004C, True),
    ("board_media", 0x004D, True),
    ("tube_air_main", 0x004F, True),
    ("tube_full_main", 0x0050, True),
    ("tube_air_media", 0x0051, True),
    ("tube_full_media", 0x0052, True),
    ("empty", 0x0012, True),
    ("full", 0x0013, True),
    ("media_on", 0x002E, False),
    ("media_air", 0x002F, False),
    ("media_cal", 0x0030, False),
    ("two_contour", 0x0053, False),
    ("two_empty", 0x0054, False),
    ("two_full", 0x0055, False),
)
AUDIT_TABLES = {"nodes": 7, "board_main": 14, "board_media": 14, "tube_air_main": 7, "tube_full_main": 7,
                "tube_air_media": 7, "tube_full_media": 7}
AUDIT_SIGNED = {"empty": False, "full": False, "media_air": False, "media_cal": False, "two_empty": False,
                "two_full": False, "crc": False}

# Биты состояния профиля - как в прошивке (fuel_profile.h).
STATUS_FILLED, STATUS_CRC_OK, STATUS_ALGO_OK, STATUS_TRUSTED = 0x01, 0x02, 0x04, 0x08

REFERENCE_X10 = 250
# Сколько прочитанное считается свежим, с: профиль за это время могли переписать.
AUDIT_FRESH_S = 15 * 60
# Неудачное чтение повторяется само не чаще, с.
AUDIT_RETRY_S = 30.0
# Ответ потерян, если его нет столько, с (у окна параметров свой предел - это страховка).
AUDIT_LOST_S = 6.0
# Отметка 0 %/100 % дальше от строки трубки при +25 °C, чем столько процентов уровня, - предупреждение:
# калибровка снята не с этим профилем, и уровень сдвинут уже при +25 °C. Сходимости отводится 0,5 % из ±1 %.
AUDIT_MARK_PP = 0.5

_NAMES = {name: (did, required) for name, did, required in AUDIT_ITEMS}


def _node_text(x10: int) -> str:
    return f"{x10 / 10:+.0f} °C".replace("+0 °C", "0 °C")


def profile_audit_verdict(values: dict) -> dict:
    """Оценка прочитанного из платы: недостатки (старт нельзя), предупреждения и краткая сводка."""
    problems: list[str] = []
    notes: list[str] = []
    status = values.get("status")
    if status is None:
        problems.append("состояние профиля не прочитано")
    elif not status & STATUS_FILLED:
        problems.append("профиль пустой: таблицы нулевые, поправки по температуре нет")
    else:
        if not status & STATUS_CRC_OK:
            problems.append("сумма профиля не сходится - профиль записан не до конца")
        if not status & STATUS_ALGO_OK:
            problems.append("номер алгоритма профиля не тот, что у прошивки - профиль не применяется")
        if not status & STATUS_TRUSTED:
            problems.append("таблицы профиля не применяются")

    nodes = list(values.get("nodes") or [])
    grid_ok = len(nodes) == 7 and all(b > a for a, b in zip(nodes, nodes[1:]))
    if not grid_ok:
        problems.append("сетка узлов профиля не задана")

    def row(name):
        data = values.get(name)
        return list(data) if data is not None else None

    def empty_nodes(data) -> list[str]:
        return [_node_text(nodes[index]) if grid_ok else str(index + 1) for index, value in enumerate(data) if value == 0]

    for name, title in (("board_main", "плата, основной"), ("board_media", "плата, вид топлива")):
        data = row(name)
        if data is not None and not any(data):
            problems.append(f"таблица «{title}» пустая - первого этапа в профиле нет")

    air_main, full_main = row("tube_air_main"), row("tube_full_main")
    for data, title in ((air_main, "трубка, основной на воздухе"), (full_main, "трубка, основной в жидкости")):
        if data is not None and any(value == 0 for value in data):
            problems.append(f"строка «{title}» не заполнена в узлах {', '.join(empty_nodes(data))} - "
                            "второго этапа в профиле нет")
    if air_main and full_main and all(air_main) and all(full_main):
        bad = [index for index, (a, f) in enumerate(zip(air_main, full_main)) if f <= a]
        if bad:
            problems.append("строка «в жидкости» не выше строки «на воздухе» в узлах "
                            + ", ".join(_node_text(nodes[index]) if grid_ok else str(index + 1) for index in bad))

    empty, full = values.get("empty"), values.get("full")
    calibrated = empty is not None and full is not None and 0 < empty < full
    if empty is None or full is None:
        problems.append("калибровка 0 %/100 % не прочитана")
    elif not calibrated:
        problems.append(f"калибровка не записана: 0 % = {empty}, 100 % = {full} (нужно 0 % меньше 100 %) - "
                        "прошивка уровень не считает")

    media_on = values.get("media_on")
    if media_on == 1:
        air, cal = values.get("media_air"), values.get("media_cal")
        if not air or not cal or air == cal:
            problems.append(f"поправка по виду топлива включена, но её эталоны не записаны (воздух {air}, "
                            f"калибровочная жидкость {cal})")
        for name, title in (("tube_air_media", "трубка, вид топлива на воздухе"),
                            ("tube_full_media", "трубка, вид топлива в жидкости")):
            data = row(name)
            if data is not None and any(value == 0 for value in data):
                problems.append(f"поправка по виду топлива включена, а строка «{title}» не заполнена в узлах "
                                + ", ".join(empty_nodes(data)))
    if values.get("two_contour") == 1:
        low, high = values.get("two_empty"), values.get("two_full")
        if not low or not high or low >= high:
            problems.append(f"модель по двум контурам включена, но её отметки не записаны (0 % = {low}, "
                            f"100 % = {high})")

    # Калибровка снята с этим профилем: в сухой трубке при +25 °C итог периода равен строке «на воздухе»
    # опорного узла, значит отметка 0 % должна лежать рядом с ней (так же 100 % - со строкой «в жидкости»).
    if calibrated and grid_ok and REFERENCE_X10 in nodes and air_main and full_main:
        index = nodes.index(REFERENCE_X10)
        span = full - empty
        for mark, ref, title in ((empty, air_main[index], "0 %"), (full, full_main[index], "100 %")):
            if not ref:
                continue
            pp = (mark - ref) * 100.0 / span
            if abs(pp) > AUDIT_MARK_PP:
                notes.append(f"отметка {title} ({mark}) отличается от строки трубки при +25 °C ({ref}) на "
                             f"{mark - ref:+d} отсч. ({pp:+.2f} % уровня) - калибровка снята не с этим профилем "
                             "или трубка была другой; уровень сдвинут уже при +25 °C")

    parts = []
    crc = values.get("crc")
    if status is not None and status & STATUS_TRUSTED:
        parts.append("профиль применяется" + (f", сумма 0x{crc:04X}" if crc is not None else ""))
    if calibrated:
        parts.append(f"0 % = {empty}, 100 % = {full} (размах {full - empty})")
    if media_on is not None:
        parts.append("поправка по виду топлива " + ("включена" if media_on == 1 else "выключена"))
    if values.get("two_contour") == 1:
        parts.append("модель по двум контурам включена")
    return {"problems": problems, "notes": notes, "summary": "; ".join(parts)}


class AppControllerProfileAuditMixin(AppControllerContract):
    """Чтение и оценка профиля и калибровки плат перед проверочным прогоном."""

    # ------------------------------------------------------------------ состояние

    def _audit_state(self) -> dict:
        state = getattr(self, "_profile_audit", None)
        if state is None:
            state = {"queue": [], "pending": None, "results": {}, "values": {}, "tries": {}, "started": {}}
            self._profile_audit = state
        return state

    def _profile_audit_boards(self) -> list[int]:
        """Чьи профили проверять: платы на шине (несколько плат) или плата калибровки (одна)."""
        multi = getattr(self, "_mb_on", None)
        if multi is not None and multi():
            working = self._mb_working_boards() or []
            return [int(board["sa"]) & 0xFF for board in working]
        target = getattr(self, "_resolve_calibration_target_sa", None)
        return [int(target()) & 0xFF] if callable(target) else []

    def _profile_audit_label(self, sa: int) -> str:
        label = getattr(self, "_mb_label", None)
        multi = getattr(self, "_mb_on", None)
        if label is not None and multi is not None and multi():
            return str(label(sa))
        return f"0x{int(sa) & 0xFF:02X}"

    def _profile_audit_busy(self) -> bool:
        state = self._audit_state()
        return bool(state["queue"]) or state["pending"] is not None

    def _profile_audit_start(self, sas=None, force: bool = False) -> int:
        """Ставит платы в очередь чтения. Возвращает, сколько плат поставлено."""
        state = self._audit_state()
        now = time.monotonic()
        queued = {sa for sa, _name in state["queue"]}
        if state["pending"] is not None:
            queued.add(state["pending"][0])
        added = 0
        for sa in (self._profile_audit_boards() if sas is None else [int(item) & 0xFF for item in sas]):
            if sa in queued:
                continue
            result = state["results"].get(sa)
            if not force and result is not None:
                fresh = now - result["at"] < AUDIT_FRESH_S
                failed = bool(result.get("error"))
                if (fresh and not failed) or (failed and now - result["at"] < AUDIT_RETRY_S):
                    continue
            state["values"][sa] = {}
            state["tries"].pop(sa, None)
            state["started"][sa] = now
            state["queue"].extend((sa, name) for name, _did, _required in AUDIT_ITEMS)
            added += 1
        if added:
            self._profile_audit_changed()
        return added

    def _profile_audit_changed(self):
        signal = getattr(self, "climateChanged", None)
        if signal is not None:
            try:
                signal.emit()
            except Exception:
                pass

    # ------------------------------------------------------------------ обмен

    def _profile_audit_tick(self, now: float):
        """Такт: следующий параметр очереди, если шина свободна. Вызывается из такта живого опроса."""
        state = getattr(self, "_profile_audit", None)
        if state is None:
            return
        pending = state["pending"]
        if pending is not None:
            if now - pending[2] >= AUDIT_LOST_S and not getattr(self, "_options_busy", False):
                self._profile_audit_result(False, f"{AUDIT_ORIGIN_PREFIX}{pending[0]:02X}_{pending[1]}", None,
                                           "таймаут: ответ потерян")
            return
        if not state["queue"]:
            return
        can = getattr(self, "_can", None)
        if can is None or not getattr(can, "is_connect", False):
            for sa in sorted({sa for sa, _name in state["queue"]}):
                self._profile_audit_finish(sa, "нет связи с адаптером CAN")
            return
        if uds_exchange_busy(self) or background_request_recent(self):
            return
        live = getattr(self, "_chamber_live_pending", None)
        if live is not None and now - float(getattr(self, "_chamber_live_pending_s", 0.0)) < 0.7:
            return
        sa, name = state["queue"][0]
        did = _NAMES[name][0]
        parameter = get_option_by_did(did)
        if parameter is None:
            state["queue"].pop(0)
            if _NAMES[name][1]:
                self._profile_audit_finish(sa, f"параметра 0x{did:04X} нет в каталоге программы")
            return
        origin = f"{AUDIT_ORIGIN_PREFIX}{sa:02X}_{name}"
        state["pending"] = (sa, name, now)
        started = self._start_options_read_request(parameter, request_origin=origin, append_history=False,
                                                   target_sa_override=sa)
        if not started:
            state["pending"] = None

    def _handle_profile_audit_options_result(self, *, success: bool, request_origin: str, pending_action: str,
                                             pending_did, value_bytes, message: str):
        """Ответ окна параметров на чтение проверки профиля."""
        if not str(request_origin or "").startswith(AUDIT_ORIGIN_PREFIX):
            return
        self._profile_audit_result(bool(success), str(request_origin), value_bytes, str(message))

    def _profile_audit_result(self, success: bool, origin: str, value_bytes, message: str):
        state = self._audit_state()
        pending = state["pending"]
        try:
            sa_text, name = origin[len(AUDIT_ORIGIN_PREFIX):].split("_", 1)
            sa = int(sa_text, 16)
        except ValueError:
            return
        if pending is None or pending[0] != sa or pending[1] != name:
            return
        state["pending"] = None
        if not state["queue"] or state["queue"][0] != (sa, name):
            return
        required = _NAMES[name][1]
        if success:
            state["queue"].pop(0)
            state["values"].setdefault(sa, {})[name] = self._profile_audit_decode(name, bytes(value_bytes or b""))
        else:
            timeout = "таймаут" in message.lower()
            tries = state["tries"].get((sa, name), 0) + 1
            state["tries"][(sa, name)] = tries
            if timeout and tries < 2:
                return  # тот же параметр ещё раз
            state["queue"].pop(0)
            if timeout:
                self._profile_audit_finish(sa, "плата не отвечает")
                return
            if required:
                did = _NAMES[name][0]
                self._profile_audit_finish(sa, f"прошивка не отдаёт 0x{did:04X} ({message})")
                return
        if not any(item[0] == sa for item in state["queue"]):
            self._profile_audit_finish(sa, "")

    @staticmethod
    def _profile_audit_decode(name: str, payload: bytes):
        count = AUDIT_TABLES.get(name)
        if count is not None:
            if len(payload) < count * 2:
                return None
            return list(struct.unpack(f"<{count}h", payload[:count * 2]))
        if name in ("status", "media_on", "two_contour"):
            return payload[0] if payload else None
        if len(payload) < 2:
            return payload[0] if payload else None
        return int.from_bytes(payload[:2], "little", signed=AUDIT_SIGNED.get(name, False))

    def _profile_audit_finish(self, sa: int, error: str):
        """Плата прочитана (или чтение оборвалось): оценка - в итоги, остаток её очереди - прочь."""
        state = self._audit_state()
        state["queue"] = [item for item in state["queue"] if item[0] != sa]
        if state["pending"] is not None and state["pending"][0] == sa:
            state["pending"] = None
        values = state["values"].pop(sa, {})
        verdict = {"problems": [], "notes": [], "summary": ""} if error else profile_audit_verdict(values)
        state["results"][sa] = dict(verdict, at=time.monotonic(), error=error, values=values)
        self._profile_audit_changed()

    # ------------------------------------------------------------------ проверка перед стартом и показ

    def _profile_audit_checks(self, add):
        """Строки проверки перед стартом для проверки профиля: по одной на плату с недостатками."""
        boards = self._profile_audit_boards()
        if not boards:
            add("profiles", False, "Проверка профиля: нет ни одной платы на шине - профиль проверить не у кого")
            return
        can = getattr(self, "_can", None)
        if can is None or not getattr(can, "is_connect", False):
            add("profiles", False, "Проверка профиля: нет связи с адаптером CAN - профиль и калибровку плат "
                                   "не прочитать")
            return
        self._profile_audit_start(boards)
        state = self._audit_state()
        results = state["results"]
        reading = [sa for sa in boards if sa in {item[0] for item in state["queue"]}
                   or (state["pending"] is not None and state["pending"][0] == sa)]
        if reading:
            done = len(boards) - len(reading)
            add("profiles", False, f"Читаю профиль и калибровку плат: готово {done} из {len(boards)} "
                                   f"(сейчас {self._profile_audit_label(reading[0])}). Старт - после проверки")
        good = []
        for sa in boards:
            if sa in reading:
                continue
            result = results.get(sa)
            if result is None:
                continue
            label = self._profile_audit_label(sa)
            if result["error"]:
                add(f"profile_{sa:02X}", False, f"{label}: профиль не прочитан - {result['error']}. Повторю сам "
                                                f"через {AUDIT_RETRY_S:g} с или нажмите «Перечитать профили плат»")
                continue
            if result["problems"]:
                add(f"profile_{sa:02X}", False, f"{label}: " + "; ".join(result["problems"]) + ". Проверять "
                                                "нечего - сначала запишите профиль и откалибруйте 0 %/100 %")
                continue
            for index, note in enumerate(result["notes"]):
                add(f"profile_{sa:02X}_note{index}", False, f"{label}: {note}", "warn")
            good.append(f"{label} - {result['summary']}")
        if good:
            add("profiles_ok", True, "Профиль и калибровка в порядке: " + "; ".join(good))

    def _profile_audit_view(self, check_only: bool) -> dict:
        """Для окна: показывать ли кнопку перечитывания и что сейчас идёт."""
        state = getattr(self, "_profile_audit", None)
        busy = bool(state) and self._profile_audit_busy()
        return {"visible": bool(check_only), "busy": busy}

    def _profile_audit_log_lines(self) -> list[str]:
        """Что прочитано из плат - строками для журнала событий прогона."""
        state = getattr(self, "_profile_audit", None)
        if not state:
            return []
        lines = []
        for sa in self._profile_audit_boards():
            result = state["results"].get(sa)
            if result is None:
                continue
            label = self._profile_audit_label(sa)
            if result["error"]:
                lines.append(f"плата {label}: профиль перед стартом не прочитан - {result['error']}")
            else:
                text = result["summary"] or "профиль прочитан"
                extra = result["problems"] + result["notes"]
                lines.append(f"плата {label}: {text}" + (f"; {'; '.join(extra)}" if extra else ""))
        return lines
