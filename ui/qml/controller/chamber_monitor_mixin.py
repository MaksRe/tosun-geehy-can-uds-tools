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

ЧТО ПОКАЗЫВАЕТСЯ (13.11.2026 - простыми словами, все платы сразу)
- погрешность уровня: уровень прибора минус настоящий уровень. Настоящий известен по пометке
  точки: «воздух» (сухая трубка) - 0 %, «жидкость» (трубка в топливе) - 100 %;
- сдвиг от +25 °C: уровень сейчас минус уровень этой же платы при +25 °C трубки - то, что внесла
  температура и не убрал профиль. Уровень при +25 °C запоминается сам, когда трубка впервые
  оказывается в узле +25 °C (±3 °C), или по кнопке «Считать сдвиг от текущего».
Требование к уровню ±1 % (10.11.2026): до 0,5 % - в норме, 0,5-1 - на грани, больше 1 - вне допуска.
В коде «ref» - это и есть запомненное показание при +25 °C.

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
            "truth": self._chamber_monitor_truth(),
        }

    def _chamber_monitor_truth(self) -> float | None:
        """Настоящий уровень, %, по пометке точек платы: сухая трубка - 0, в топливе - 100, иначе неизвестен."""
        label = str(getattr(self, "_chamber_label", "") or "").strip().casefold()
        if label == chamber_fit.AIR_NOTE:
            return 0.0
        if label == chamber_fit.LIQUID_NOTE:
            return 100.0
        return None

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
            # Уровень при +25 °C запоминается сам: первое показание при +25 °C трубки.
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
        """«Считать сдвиг от текущего»: сдвиг каждой платы считается от её показания сейчас, а не при +25 °C."""
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
            return False, "прибор ещё не отдал уровень, итог периода и температуры - считать сдвиг не от чего"
        text = "сдвиг теперь считается от текущего показания: " + ", ".join(done)
        if missing:
            text += "; нет данных у " + ", ".join(missing)
        return True, text

    def _chamber_monitor_reset(self):
        """«Сбросить наблюдение»: история и показание при +25 °C у всех плат забываются."""
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

    @staticmethod
    def _chamber_monitor_error(sample: dict) -> float | None:
        """Погрешность уровня записи, %: уровень прибора минус настоящий (если он известен)."""
        truth = sample.get("truth")
        return None if truth is None else sample["level"] / 10.0 - float(truth)

    def _chamber_monitor_board(self, label: str, now: float) -> dict:
        """Сводка монитора одной платы (в её поле): уровень сейчас, погрешность, сдвиг от +25 °C, узлы."""
        missing = set(self._chamber_live_missing or set())
        current = self._chamber_monitor_current(now)
        ref = self._chamber_monitor_ref
        history = list(self._chamber_monitor_history or [])
        stats: dict[int, dict] = {}
        worst_shift = worst_error = None
        for sample in history:
            node = chamber_fit.nearest_node(sample["tube"])
            shift = None if ref is None else (sample["level"] - ref["level"]) / 10.0
            error = self._chamber_monitor_error(sample)
            if node is not None:
                bucket = stats.setdefault(node, {"shift": [], "error": []})
                if shift is not None:
                    bucket["shift"].append(shift)
                if error is not None:
                    bucket["error"].append(error)
            if shift is not None and (worst_shift is None or abs(shift) > abs(worst_shift[0])):
                worst_shift = (shift, sample["tube"], sample["clock"])
            if error is not None and (worst_error is None or abs(error) > abs(worst_error[0])):
                worst_error = (error, sample["tube"], sample["clock"])
        shift = None if current is None or ref is None else (current["level"] - ref["level"]) / 10.0
        error = None if current is None else self._chamber_monitor_error(current)
        comp_shift = None if current is None or ref is None else current["comp"] - ref["comp"]
        # Худшее за прогон - по погрешности, если настоящий уровень известен, иначе по сдвигу от +25 °C.
        worst = worst_error or worst_shift
        judged = [value for value in (error, shift, None if worst is None else worst[0]) if value is not None]

        if "level" in missing or "comp" in missing:
            state, tone = "прошивка не отдаёт уровень", "bad"
        elif current is None:
            state, tone = "жду показания", "info"
        elif not judged:
            state, tone = "ждём +25 °C трубки", "info"
        else:
            tone = self._chamber_monitor_tone(max(judged, key=abs))
            state = {"ok": "в норме", "warn": "на грани", "bad": "вне допуска"}.get(tone, "")

        def at(item):
            return "—" if item is None else f"{_pp(item[0])} % при {_pp(item[1] / 10.0, 1)} °C"

        live = {
            "label": label,
            "tube": "—" if current is None else _pp(current["tube"] / 10.0, 1),
            "level": "—" if current is None else _pp(current["level"] / 10.0, 2, sign=False),
            "err": _pp(error),
            "dev": _pp(shift),
            "worst": at(worst),
            "status": state,
        }
        detail = {
            "label": label,
            "comp": "—" if current is None else str(current["comp"]),
            "compDev": "—" if comp_shift is None else f"{comp_shift:+d}".replace("-", "−"),
            "ref": "—" if ref is None else (f"{_pp(ref['level'] / 10.0, 2, sign=False)} % при "
                                            f"{_pp(ref['tube'] / 10.0, 1)} °C, {ref['clock']}"
                                            + ("" if ref.get("auto") else " (кнопкой)")),
            "worstShift": "—" if worst_shift is None else f"{at(worst_shift)}, {worst_shift[2]}",
            "worstErr": "—" if worst_error is None else f"{at(worst_error)}, {worst_error[2]}",
            "samples": str(len(history)),
        }
        cells, node_tone = {}, "info"
        rank = {"info": 0, "ok": 1, "warn": 2, "bad": 3}
        for node in chamber_fit.NODES_X10:
            values = (stats.get(node) or {}).get("shift") or []
            if not values:
                cells[str(node)] = "—"
                continue
            mean = sum(values) / len(values)
            cells[str(node)] = f"{_pp(mean)} ({len(values)})"
            node_tone = max(node_tone, self._chamber_monitor_tone(mean), key=lambda item: rank[item])
        cells["label"] = label
        return {"row": live, "detail": detail, "tone": tone, "nodeCells": cells, "nodeTone": node_tone,
                "deviation": shift, "error": error, "worst": None if worst is None else worst[0],
                "stats": stats, "history": history, "ref": ref, "label": label, "state": state}

    def _chamber_monitor_collect(self) -> list[dict]:
        """Сводки монитора всех плат (или одной)."""
        now = time.monotonic()
        boards = []
        multi = getattr(self, "_mb_on", None)
        if multi is not None and multi():
            for board in self._mb_working_boards(now) or self._mb_polled_boards():
                sa = int(board["sa"])
                with self._mb_context(sa, notify=False):
                    boards.append(dict(self._chamber_monitor_board(self._mb_label(sa), now), sa=sa))
        else:
            target = getattr(self, "_resolve_calibration_target_sa", None)
            sa = int(target()) & 0xFF if callable(target) else None
            label = f"0x{sa:02X}" if sa is not None else "плата"
            boards.append(dict(self._chamber_monitor_board(label, now), sa=sa))
        return boards

    TOLERANCE_TIP = "Требование к уровню ±1 %: до 0,5 % - в норме, 0,5-1 % - на грани, больше 1 % - вне допуска."

    def _chamber_monitor_view(self) -> dict:
        """Монитор для окна, сайта, мини-приложения и бота: все платы сразу, коротко; подробности - отдельно."""
        boards = self._chamber_monitor_collect()

        def column(key, title, tip, width, align="right"):
            return {"key": key, "title": title, "tip": tip, "width": width, "align": align}

        now_table = {
            "id": "monitor-now",
            "title": "Уровень топлива сейчас",
            "tip": ("Что выдаёт сам прибор по записанному профилю - у всех плат сразу, обновляется каждые пару "
                    "секунд. Погрешность - уровень прибора минус настоящий: у сухой трубки («воздух») настоящий "
                    "0 %, в топливе («жидкость») 100 %. Сдвиг от +25 °C - насколько уровень ушёл от показания этой "
                    "же платы при +25 °C: это ошибка от температуры, которую профиль не убрал. " + self.TOLERANCE_TIP),
            "columns": [
                column("label", "Плата", "Адрес узла на шине и подпись платы", 120, "left"),
                column("tube", "Трубка, °C", "Температура топлива (датчик трубки)", 76),
                column("level", "Уровень, %", "Уровень, который выдаёт сам прибор", 80),
                column("err", "Погрешность, %", "Уровень прибора минус настоящий (сухая трубка - 0 %, в топливе - "
                       "100 %). «—» - настоящий уровень неизвестен", 96),
                column("dev", "Сдвиг от +25 °C, %", "Уровень сейчас минус уровень этой же платы при +25 °C трубки", 100),
                column("worst", "Худшее за прогон", "Наибольшая по модулю погрешность (или сдвиг от +25 °C, если "
                       "настоящий уровень неизвестен) и при какой температуре трубки", 170, "left"),
                column("status", "Итог", "В норме / на грани / вне допуска - по худшему из погрешности и сдвига", 100,
                       "center"),
            ],
            "rows": [{"tone": board["tone"], "cells": board["row"]} for board in boards],
        }
        detail_table = {
            "id": "monitor-detail",
            "title": "Подробности",
            "tip": "Для разбора: итоговый период прибора, показание при +25 °C, от которого считается сдвиг, и "
                   "худшие значения со временем.",
            "columns": [
                column("label", "Плата", "Адрес узла на шине и подпись платы", 120, "left"),
                column("comp", "Итог периода", "Период после температурной компенсации и подгонки нуля (0x0062): у "
                       "сухой трубки должен стоять на месте при любой температуре", 90),
                column("compDev", "Его сдвиг от +25 °C, отсч.", "Итог периода сейчас минус при +25 °C", 100),
                column("ref", "Показание при +25 °C", "От него считается сдвиг: запоминается само при первом "
                       "попадании трубки в +25 °C; «кнопкой» - задано кнопкой «Считать сдвиг от текущего»", 220, "left"),
                column("worstErr", "Худшая погрешность", "Наибольшая по модулю погрешность, температура и время", 220,
                       "left"),
                column("worstShift", "Худший сдвиг", "Наибольший по модулю сдвиг от +25 °C, температура и время", 220,
                       "left"),
                column("samples", "Записей", "Записей в истории: одна в 20 с", 64),
            ],
            "rows": [{"tone": board["tone"], "cells": board["detail"]} for board in boards],
        }
        nodes_table = {
            "id": "monitor-nodes",
            "title": "Сдвиг от +25 °C по узлам",
            "tip": ("Средний сдвиг уровня от показания при +25 °C, %, пока трубка была в узле (±3 °C); в скобках - "
                    "сколько записей. Видно, при какой температуре профиль не дотягивает."),
            "columns": [column("label", "Плата", "Адрес узла на шине и подпись платы", 120, "left")]
                       + [column(str(node), chamber_fit.node_text(node),
                                 f"Трубка в узле {chamber_fit.node_text(node)} ±3 °C", 96, "center")
                          for node in chamber_fit.NODES_X10],
            "rows": [{"tone": board["nodeTone"], "cells": board["nodeCells"]} for board in boards],
        }
        worst = max((abs(board["worst"]) for board in boards if board["worst"] is not None), default=None)
        live = [{"label": board["label"], "tone": board["tone"], **board["row"]} for board in boards]
        return {"now": now_table, "detail": detail_table, "nodes": nodes_table, "live": live,
                "worst": None if worst is None else _pp(worst, 2, sign=False),
                "tone": self._chamber_monitor_tone(worst) if worst is not None else "info",
                "everyS": int(self.CHAMBER_MONITOR_EVERY_S), "tip": now_table["tip"]}
