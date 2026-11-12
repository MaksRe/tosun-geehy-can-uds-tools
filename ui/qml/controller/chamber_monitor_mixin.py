"""Монитор отклонений в камере: что показывает сам прибор по записанному профилю, в реальном времени.

ЗАЧЕМ
Проверочный прогон после записи профиля (12.11.2026) приходилось разбирать после камеры: журнал
пишет сырой период, а уровень, который выдаёт прибор, считался потом скриптом по профилю и
отметкам. Отклонение по ходу прогона не было видно, и плёнку дизеля на трубках заметили только
в архиве. Теперь раздел прямо во время прогона читает у каждой платы её собственный итог.

ЧТО ЧИТАЕТСЯ
- 0x0018 - уровень, который считает прибор, в десятых долях процента: сухая трубка должна давать 0 %;
- 0x0062 - итоговый период после температурной компенсации и подгонки нуля: у сухой трубки он
  при любой температуре должен стоять на месте.
Оба параметра идут в общий круг опроса прогона (chamber_live_mixin): если прошивка их не знает,
после двух отказов они больше не спрашиваются, и монитор пишет, что данных нет.

ОТ ЧЕГО СЧИТАЕТСЯ ОТКЛОНЕНИЕ
Опора - показание этой же платы при +25 °C трубки: берётся само, когда трубка впервые оказывается
в узле +25 °C (±3 °C), или по кнопке «Опора - сейчас». Отклонение уровня от опоры в процентных
пунктах - это температурная ошибка уровня, которую профиль не убрал. Требование к уровню ±1 %
(10.11.2026): до 0,5 п.п. - в норме, 0,5-1 - на грани, больше 1 - вне допуска.

История - одна запись в 20 с у каждой платы, по ней таблица «по узлам»: среднее отклонение в
каждом узле температуры трубки. Плата своя у каждой: поля монитора входят в BOARD_ATTRS.
"""

from __future__ import annotations

import time
from datetime import datetime

import chamber_fit
from uds.data_identifiers import UdsData

from .contract import AppControllerContract


def _pp(value: float | None, digits: int = 2, sign: bool = True) -> str:
    """Процентные пункты с запятой и настоящим минусом."""
    if value is None:
        return "—"
    text = f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"
    return text.replace(".", ",").replace("-", "−")


class AppControllerChamberMonitorMixin(AppControllerContract):
    # Как часто класть запись в историю монитора у каждой платы, с.
    CHAMBER_MONITOR_EVERY_S = 20.0
    # Сколько записей держать у платы: 6000 по 20 с - больше суток прогона.
    CHAMBER_MONITOR_KEEP = 6000
    # Границы отклонения уровня, процентные пункты: половина допуска и весь допуск ±1 %.
    CHAMBER_MONITOR_OK_PP = 0.5
    CHAMBER_MONITOR_BAD_PP = 1.0

    def _chamber_monitor_vars(self):
        """Величины монитора: читаются в том же круге опроса, что и точки прогона."""
        return (
            ("comp", UdsData.fuel_compensated_period, False),
            ("level", UdsData.raw_fuel_level, True),
        )

    # ------------------------------------------------------------------ накопление

    def _chamber_monitor_tone(self, deviation_pp: float | None) -> str:
        if deviation_pp is None:
            return "info"
        size = abs(float(deviation_pp))
        if size <= self.CHAMBER_MONITOR_OK_PP:
            return "ok"
        return "warn" if size <= self.CHAMBER_MONITOR_BAD_PP else "bad"

    def _chamber_monitor_current(self, now: float) -> dict | None:
        """Средние монитора у платы в её поле: уровень, итог, температуры. None - данных ещё нет."""
        values = {}
        for key in ("level", "comp", "fuel_temp", "board_temp"):
            if not self._chamber_live_fresh(key, now):
                return None
            stats = self._chamber_live_stats(key, now)
            if stats is None:
                return None
            values[key] = float(stats["mean"])
        main = self._chamber_live_stats("main", now)
        return {
            "wall": time.time(), "clock": datetime.now().strftime("%d.%m %H:%M"),
            "tube": int(round(values["fuel_temp"])), "board": int(round(values["board_temp"])),
            "level": round(values["level"], 1), "comp": int(round(values["comp"])),
            "main": None if main is None else int(round(main["mean"])),
        }

    def _chamber_monitor_sample_here(self, now: float, force: bool = False) -> dict | None:
        """Запись в историю монитора платы, поле которой сейчас на месте."""
        if not force and now - float(self._chamber_monitor_last_s or 0.0) < self.CHAMBER_MONITOR_EVERY_S:
            return None
        sample = self._chamber_monitor_current(now)
        if sample is None:
            return None
        self._chamber_monitor_last_s = now
        history = list(self._chamber_monitor_history or [])
        history.append(sample)
        self._chamber_monitor_history = history[-self.CHAMBER_MONITOR_KEEP:]
        if self._chamber_monitor_ref is None and chamber_fit.nearest_node(sample["tube"]) == chamber_fit.REFERENCE_X10:
            # Опора берётся сама: первое показание при +25 °C трубки.
            self._chamber_monitor_ref = dict(sample, auto=True)
        return sample

    def _chamber_monitor_boards(self) -> list[int | None]:
        """Чьи поля обходить: несколько плат - каждую из опрашиваемых, одна плата - текущее поле (None)."""
        multi = getattr(self, "_mb_on", None)
        if multi is not None and multi():
            return [int(board["sa"]) for board in self._mb_polled_boards()]
        return [None]

    def _chamber_monitor_tick(self, now: float):
        """Такт опроса: у каждой платы раз в 20 с - запись в историю монитора."""
        # Обход полей плат - не каждый такт опроса (90-150 мс), а раз в пару секунд.
        if now - float(getattr(self, "_chamber_monitor_tick_s", 0.0) or 0.0) < 2.0:
            return
        self._chamber_monitor_tick_s = now
        for sa in self._chamber_monitor_boards():
            if sa is None:
                self._chamber_monitor_sample_here(now)
                continue
            with self._mb_context(sa, notify=False):
                self._chamber_monitor_sample_here(now)

    def _chamber_monitor_set_reference(self) -> tuple[bool, str]:
        """«Опора - сейчас»: текущее показание каждой платы становится опорой отклонений."""
        now = time.monotonic()
        done, missing = [], []
        for sa in self._chamber_monitor_boards():
            def apply():
                sample = self._chamber_monitor_sample_here(now, force=True)
                if sample is None:
                    return False
                self._chamber_monitor_ref = dict(sample, auto=False)
                return True
            if sa is None:
                ok = apply()
                who = "плата"
            else:
                with self._mb_context(sa, notify=False):
                    ok = apply()
                who = self._mb_label(sa)
            (done if ok else missing).append(who)
        self.chamberLiveChanged.emit()
        if not done:
            return False, "опора не задана: прибор ещё не отдал уровень, итог периода и температуры"
        text = "опора отклонений - текущее показание: " + ", ".join(done)
        if missing:
            text += "; нет данных у " + ", ".join(missing)
        return True, text

    def _chamber_monitor_reset(self):
        """«Сбросить наблюдение»: история и опора всех плат забываются."""
        multi = getattr(self, "_mb_on", None)
        boards = [int(board["sa"]) for board in self._mb_boards] if multi is not None and multi() else [None]
        for sa in boards:
            if sa is None:
                self._chamber_monitor_ref = None
                self._chamber_monitor_history = []
                self._chamber_monitor_last_s = 0.0
                continue
            with self._mb_context(sa, notify=False):
                self._chamber_monitor_ref = None
                self._chamber_monitor_history = []
                self._chamber_monitor_last_s = 0.0
        self.chamberLiveChanged.emit()

    # ------------------------------------------------------------------ показ

    def _chamber_monitor_board(self, label: str, now: float) -> dict:
        """Сводка монитора одной платы (в её поле): строка таблицы «сейчас» и ячейки «по узлам»."""
        missing = set(self._chamber_live_missing or set())
        current = self._chamber_monitor_current(now)
        ref = self._chamber_monitor_ref
        history = list(self._chamber_monitor_history or [])
        nodes: dict[int, list[float]] = {}
        worst = None
        if ref is not None:
            for sample in history:
                deviation = (sample["level"] - ref["level"]) / 10.0
                node = chamber_fit.nearest_node(sample["tube"])
                if node is not None:
                    nodes.setdefault(node, []).append(deviation)
                if worst is None or abs(deviation) > abs(worst[0]):
                    worst = (deviation, sample["tube"], sample["clock"])
        deviation = None if current is None or ref is None else (current["level"] - ref["level"]) / 10.0
        comp_shift = None if current is None or ref is None else current["comp"] - ref["comp"]

        if "level" in missing or "comp" in missing:
            state, tone = "прошивка не отдаёт уровень или итог периода", "bad"
        elif current is None:
            state, tone = "жду показания", "info"
        elif ref is None:
            state, tone = "опоры нет: трубка ещё не была при +25 °C", "info"
        else:
            tone = self._chamber_monitor_tone(deviation if worst is None or abs(worst[0]) < abs(deviation)
                                              else worst[0])
            state = {"ok": "в норме", "warn": "на грани", "bad": "вне допуска"}.get(tone, "")

        row = {
            "label": label,
            "tube": "—" if current is None else _pp(current["tube"] / 10.0, 1),
            "level": "—" if current is None else _pp(current["level"] / 10.0, 2, sign=False),
            "dev": _pp(deviation),
            "comp": "—" if current is None else str(current["comp"]),
            "compDev": "—" if comp_shift is None else f"{comp_shift:+d}".replace("-", "−"),
            "worst": "—" if worst is None else f"{_pp(worst[0])} при {_pp(worst[1] / 10.0, 1)} °C ({worst[2]})",
            "ref": "—" if ref is None else (f"{_pp(ref['level'] / 10.0, 2, sign=False)} % при "
                                            f"{_pp(ref['tube'] / 10.0, 1)} °C, {ref['clock']}"
                                            + (" (сама)" if ref.get("auto") else " (кнопкой)")),
            "samples": str(len(history)),
            "status": state,
        }
        cells, node_tone = {}, "info"
        rank = {"info": 0, "ok": 1, "warn": 2, "bad": 3}
        for node in chamber_fit.NODES_X10:
            values = nodes.get(node)
            if not values:
                cells[str(node)] = "—"
                continue
            mean = sum(values) / len(values)
            cells[str(node)] = f"{_pp(mean)} ({len(values)})"
            node_tone = max(node_tone, self._chamber_monitor_tone(mean), key=lambda item: rank[item])
        cells["label"] = label
        return {"row": row, "tone": tone, "nodeCells": cells, "nodeTone": node_tone,
                "deviation": deviation, "worst": None if worst is None else worst[0]}

    def _chamber_monitor_view(self) -> dict:
        """Монитор для окна, сайта и мини-приложения: таблица «сейчас» и таблица «по узлам»."""
        now = time.monotonic()
        boards = []
        multi = getattr(self, "_mb_on", None)
        if multi is not None and multi():
            for board in self._mb_working_boards(now) or self._mb_polled_boards():
                sa = int(board["sa"])
                with self._mb_context(sa, notify=False):
                    boards.append(self._chamber_monitor_board(self._mb_label(sa), now))
        else:
            target = getattr(self, "_resolve_calibration_target_sa", None)
            label = f"0x{int(target()) & 0xFF:02X}" if callable(target) else "плата"
            boards.append(self._chamber_monitor_board(label, now))

        def column(key, title, tip, width, align="right"):
            return {"key": key, "title": title, "tip": tip, "width": width, "align": align}

        now_table = {
            "id": "monitor-now",
            "title": "Монитор отклонений: сейчас",
            "tip": ("Уровень и итоговый период считает сам прибор по записанному профилю и отметкам 0/100 %. "
                    "С сухой трубкой уровень должен быть около 0 % при любой температуре. Отклонение - от опоры: "
                    "показания этой же платы при +25 °C трубки. Требование ±1 %: до 0,5 п.п. - в норме, "
                    "0,5-1 - на грани, больше 1 - вне допуска."),
            "columns": [
                column("label", "Плата", "Адрес узла на шине и подпись платы", 120, "left"),
                column("tube", "Трубка, °C", "Температура топлива (датчик трубки), среднее за окно", 80),
                column("level", "Уровень прибора, %", "Уровень, который выдаёт сам прибор (0x0018)", 100),
                column("dev", "От опоры, п.п.", "Уровень сейчас минус уровень в опоре: температурная ошибка, "
                       "которую профиль не убрал", 92),
                column("comp", "Итог периода", "Период после температурной компенсации и подгонки нуля (0x0062): "
                       "у сухой трубки при любой температуре должен стоять на месте", 92),
                column("compDev", "От опоры, отсч.", "Итог периода сейчас минус итог в опоре", 90),
                column("worst", "Наибольшее отклонение", "Наибольшее по модулю отклонение уровня от опоры за "
                       "наблюдение, при какой температуре трубки и когда", 230, "left"),
                column("ref", "Опора", "Уровень и температура трубки в опоре; «сама» - взята при первом "
                       "попадании трубки в +25 °C, «кнопкой» - «Опора - сейчас»", 230, "left"),
                column("samples", "Записей", "Записей в истории монитора: одна в 20 с", 64),
                column("status", "Состояние", "В норме / на грани / вне допуска - по наибольшему отклонению", 150,
                       "center"),
            ],
            "rows": [{"tone": board["tone"], "cells": board["row"]} for board in boards],
        }
        nodes_table = {
            "id": "monitor-nodes",
            "title": "Монитор отклонений: по узлам",
            "tip": ("Среднее отклонение уровня от опоры (п.п.) по записям, когда трубка была в узле (±3 °C); "
                    "в скобках - сколько записей. По этой таблице видно, где профиль не дотягивает."),
            "columns": [column("label", "Плата", "Адрес узла на шине и подпись платы", 120, "left")]
                       + [column(str(node), chamber_fit.node_text(node),
                                 f"Трубка в узле {chamber_fit.node_text(node)} ±3 °C", 96, "center")
                          for node in chamber_fit.NODES_X10],
            "rows": [{"tone": board["nodeTone"], "cells": board["nodeCells"]} for board in boards],
        }
        worst = max((abs(board["worst"]) for board in boards if board["worst"] is not None), default=None)
        return {"now": now_table, "nodes": nodes_table,
                "worst": None if worst is None else _pp(worst, 2, sign=False),
                "tone": self._chamber_monitor_tone(worst) if worst is not None else "info",
                "everyS": int(self.CHAMBER_MONITOR_EVERY_S)}
