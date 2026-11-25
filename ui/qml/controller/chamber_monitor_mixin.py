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

История сохраняет изменения уровня и контрольную запись каждые 5 с у каждой платы.
Во время прогона измерения сразу пишутся на диск; завершённый результат больше не меняется.
"""

from __future__ import annotations

import time
from copy import deepcopy
from datetime import datetime

import chamber_fit
from ui.qml.monitor_session import MonitorSession, thin_points
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
    CHAMBER_MONITOR_EVERY_S = 5.0
    # Для наблюдения вне прогона ограничивает память; история самого прогона не обрезается.
    CHAMBER_MONITOR_KEEP = 6000
    # Границы отклонения уровня, процентные пункты: половина допуска и весь допуск ±1 %.
    CHAMBER_MONITOR_OK_PP = 0.5
    CHAMBER_MONITOR_BAD_PP = 1.0

    def _chamber_monitor_level_context(self) -> dict:
        """Чтобы обучение не выглядело проверкой точности, разрешает проценты только для подтверждённого профиля."""
        session = getattr(self, "_chamber_monitor_session", None)
        metadata = session.metadata if session is not None else {}
        scenario = metadata.get("scenario") or getattr(self, "_climate_scenario", None) or {}
        stages = metadata.get("board_stages") or {}
        checking = (any(stage["check_only"] for stage in stages.values()) if stages else
                    bool(metadata.get("check_only", scenario.get("check_only", False))))
        if not checking:
            board_only = bool(scenario.get("board_only", getattr(self, "_chamber_board_only", False)))
            return {"levelEnabled": False, "checkMode": False,
                    "levelReason": ("Первый этап: снимается температурный профиль плат без трубок. " if board_only else
                                    "Второй этап: снимается температурный профиль изделий с трубками. ")
                                   + "Уровень топлива и допуск ±1 % здесь не оцениваются."}
        audit = metadata.get("profile_audit") or getattr(self, "_profile_audit", None) or {}
        results = audit.get("results") or {}
        targets = metadata.get("boards")
        if targets is None:
            targets = self._mb_result_boards() if getattr(self, "_mb_on", lambda: False)() else [{"sa": None}]
        if stages:
            targets = [board for board in targets if stages.get(str(board["sa"]), {}).get("check_only")]
        ready = bool(targets)
        for board in targets:
            sa = board.get("sa")
            if sa is None:
                target = getattr(self, "_resolve_calibration_target_sa", None)
                sa = int(target()) & 0xFF if callable(target) else None
            result = results.get(sa) or results.get(str(sa)) or {}
            values = result.get("values") or {}
            status, empty, full = values.get("status"), values.get("empty"), values.get("full")
            ready = ready and (bool(result) and not result.get("error") and not result.get("problems")
                               and isinstance(status, int) and status & 0x0F == 0x0F
                               and isinstance(empty, (int, float)) and isinstance(full, (int, float)) and full > empty)
        return {"levelEnabled": bool(ready), "checkMode": True, "mixedStages": bool(stages),
                "levelReason": ("Проверка записанного профиля и калибровки 0 % / 100 %." if ready else
                                "Жду подтверждения записанного профиля и калибровки 0 % / 100 %. Проценты пока не оцениваются.")}

    def _chamber_monitor_begin(self, now: float):
        """Для отдельного результата начинает постоянную запись уровня всех участников прогона."""
        self._chamber_monitor_session = None
        self._chamber_monitor_frozen = None
        self._run_report_frozen = None
        self._chamber_monitor_storage_error = ""
        self._chamber_monitor_suspended = False
        self._chamber_monitor_plots_cache = None
        self._chamber_monitor_started_s = now
        self._chamber_monitor_reset()
        multi = getattr(self, "_mb_on", lambda: False)()
        if multi:
            boards = [{"sa": board["sa"], "address": board["sa"], "label": self._mb_label(board["sa"])}
                      for board in self._mb_result_boards()]
        else:
            target = getattr(self, "_resolve_calibration_target_sa", None)
            address = int(target()) & 0xFF if callable(target) else None
            boards = [{"sa": None, "address": address, "label": f"0x{address:02X}" if address is not None else "плата"}]
        stages = {str(sa): deepcopy(stage) for sa, stage in (getattr(self, "_mb_run_stages", None) or {}).items()}
        metadata = {"boards": boards, "board_stages": stages,
                    "scenario": deepcopy(getattr(self, "_climate_scenario", {}) or {}),
                    "check_only": bool(getattr(self, "_chamber_check_only", False)),
                    "conditions": ("После калибровки, без погружения. Возможна остаточная плёнка топлива; её вклад не вычитается."
                                   if getattr(self, "_chamber_check_only", False) else "Условия заданы сценарием прогона."),
                    "profile_audit": {key: deepcopy((getattr(self, "_profile_audit", {}) or {}).get(key, {}))
                                      for key in ("results", "values")}}
        try:
            self._chamber_monitor_session = MonitorSession.create(self._climate_logs_directory(), metadata)
        except (OSError, ValueError, TypeError) as error:
            self._chamber_monitor_storage_failed(error)

    def _chamber_monitor_storage_failed(self, error):
        """Чтобы потеря записи была заметна, сохраняет ошибку диска и один раз сообщает о ней."""
        text = "История уровня не сохраняется: " + str(error)
        if not getattr(self, "_chamber_monitor_storage_error", ""):
            event = getattr(self, "_climate_event", None)
            if event is not None:
                event(text, "bad")
        self._chamber_monitor_storage_error = text

    def _chamber_monitor_restore(self, folder=None):
        """Для сохранения истории после перезапуска возвращает последний или продолжаемый прогон."""
        try:
            session = (MonitorSession.load(folder) if folder else
                       MonitorSession.latest(self._climate_logs_directory()))
            if session is None:
                return
            self._chamber_monitor_session = session
            self._chamber_monitor_suspended = bool(session.metadata.get("active"))
            self._chamber_monitor_frozen = session.snapshot.get("monitor")
            self._run_report_frozen = session.snapshot.get("report")
            for board in session.metadata["boards"]:
                sa = board["sa"]
                if sa is not None and sa not in {b["sa"] for b in getattr(self, "_mb_boards", [])}:
                    continue
                if sa is None:
                    self._chamber_monitor_restore_here(session, "single")
                else:
                    with self._mb_context(sa, notify=False):
                        self._chamber_monitor_restore_here(session, str(sa))
        except (OSError, ValueError, KeyError, TypeError) as error:
            self._chamber_monitor_storage_failed(error)

    def _chamber_monitor_restore_here(self, session, key: str):
        """Для продолжения одной платы возвращает её измерения и исходное показание при +25 °C."""
        self._chamber_monitor_history = session.histories.get(key, [])
        self._chamber_monitor_ref = next((dict(sample, auto=True) for sample in self._chamber_monitor_history
                                         if chamber_fit.nearest_node(sample["tube"]) == chamber_fit.REFERENCE_X10), None)
        self._chamber_monitor_last_s = 0.0
        self._chamber_monitor_cache = {}

    def _chamber_monitor_resume(self, folder=None):
        """Для продолжения того же испытания открывает его историю и отмечает перерыв в измерениях."""
        if folder:
            self._chamber_monitor_restore(folder)
        session = getattr(self, "_chamber_monitor_session", None)
        if session is None or not session.metadata.get("active"):
            self._chamber_monitor_begin(time.monotonic())
            return
        self._chamber_monitor_suspended = False
        self._chamber_monitor_started_s = time.monotonic()
        self._chamber_monitor_frozen = None
        for board in session.metadata["boards"]:
            key = "single" if board["sa"] is None else str(board["sa"])
            try:
                session.append(key, board["label"], None, {"stage": "перезапуск программы"})
            except OSError as error:
                self._chamber_monitor_storage_failed(error)

    def _chamber_monitor_finish(self, reason: str = "конец прогона"):
        """Чтобы поздняя выгрузка не меняла результат, фиксирует историю, таблицы и отчёт прогона."""
        session = getattr(self, "_chamber_monitor_session", None)
        if session is None or not session.metadata.get("active"):
            return
        self._chamber_monitor_suspended = False
        self._chamber_monitor_tick(time.monotonic(), force=True)
        session.metadata["active"] = False
        self._chamber_monitor_frozen = None
        self._run_report_frozen = None
        self._chamber_monitor_plots_cache = None
        view = deepcopy(self._chamber_monitor_view())
        report_of = getattr(self, "_run_report_data", None)
        report = deepcopy(report_of()) if report_of is not None else {}
        self._chamber_monitor_frozen = view
        self._run_report_frozen = report or None
        try:
            session.finish(view, report, reason)
            self._chamber_monitor_frozen = session.snapshot["monitor"]
            self._run_report_frozen = session.snapshot["report"] or None
        except (OSError, ValueError, TypeError) as error:
            self._chamber_monitor_storage_failed(error)

    def _chamber_monitor_record(self, sample):
        """Для разбора по температуре записывает измерение вместе с адресом, шагом и состоянием камеры."""
        session = getattr(self, "_chamber_monitor_session", None)
        if session is None or not session.metadata.get("active"):
            return
        sa = getattr(self, "_mb_active_sa", None) if getattr(self, "_mb_on", lambda: False)() else None
        key = "single" if sa is None else str(sa)
        board = next((b for b in session.metadata["boards"] if b["sa"] == sa), None)
        if board is None:
            return
        session.histories[key] = self._chamber_monitor_history
        nodes = getattr(self, "_climate_run_nodes", [])
        index = getattr(self, "_climate_run_index", 0)
        reading = getattr(self, "_climate_reading", None)
        context = {"address": board.get("address", sa), "node": nodes[index] if 0 <= index < len(nodes) else None,
                   "stage": str(getattr(self, "_climate_run_stage", "")),
                   "chamber": getattr(reading, "actual_c", None)}
        try:
            session.append(key, board["label"], sample, context)
        except (OSError, ValueError, TypeError) as error:
            self._chamber_monitor_storage_failed(error)

    def _chamber_monitor_note_level(self, now: float):
        """Чтобы не потерять выход за допуск между тактами, сохраняет каждое изменение уровня прибора."""
        session = getattr(self, "_chamber_monitor_session", None)
        if session is None or not session.metadata.get("active") or getattr(self, "_chamber_monitor_suspended", False):
            return
        previous = (self._chamber_monitor_history or [None])[-1]
        value = self._chamber_live_last.get("level")
        if (previous is None or value != previous["level"]) and self._chamber_monitor_current(now) is not None:
            self._chamber_monitor_sample_here(now, force=True)

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
            "level": int(self._chamber_live_last["level"]), "comp": int(self._chamber_live_last["comp"]),
            "level_mean": round(values["level"], 1),
            "main": None if main is None else int(round(main["mean"])),
            "media": self._chamber_live_last.get("media"),
            "truth": self._chamber_monitor_truth(),
        }

    def _chamber_monitor_truth(self) -> float | None:
        """Настоящий уровень, %, по пометке точек платы: сухая трубка - 0, в топливе - 100, иначе неизвестен."""
        session = getattr(self, "_chamber_monitor_session", None)
        stages = session.metadata.get("board_stages") if session is not None else None
        if stages:
            stage = stages.get(str(getattr(self, "_mb_active_sa", None)), {})
            return 0.0 if stage.get("check_only") else None
        if session is not None and session.metadata.get("check_only"):
            return 0.0
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
            self._chamber_monitor_last_s = now
            # До старта время отсутствует; пропуск фиксируется после прежних данных или выдержки от известного старта.
            started = getattr(self, "_chamber_monitor_started_s", None)
            if (self._chamber_monitor_history
                    or (started is not None and now - started >= self._chamber_live_stale_s())):
                self._chamber_monitor_record(None)
            return None
        self._chamber_monitor_last_s = now
        history = self._chamber_monitor_history or []
        history.append(sample)
        session = getattr(self, "_chamber_monitor_session", None)
        self._chamber_monitor_history = (history if session is not None and session.metadata.get("active")
                                         else history[-self.CHAMBER_MONITOR_KEEP:])
        self._chamber_monitor_record(sample)
        if self._chamber_monitor_ref is None and chamber_fit.nearest_node(sample["tube"]) == chamber_fit.REFERENCE_X10:
            # Уровень при +25 °C запоминается сам: первое показание при +25 °C трубки.
            self._chamber_monitor_ref = dict(sample, auto=True)
        return sample

    def _chamber_monitor_boards(self) -> list[int | None]:
        """Чьи поля обходить: несколько плат - каждую из опрашиваемых, одна плата - текущее поле (None)."""
        session = getattr(self, "_chamber_monitor_session", None)
        if session is not None:
            return [board["sa"] for board in session.metadata["boards"]]
        multi = getattr(self, "_mb_on", None)
        if multi is not None and multi():
            return [int(board["sa"]) for board in self._mb_polled_boards()]
        return [None]

    def _chamber_monitor_tick(self, now: float, force: bool = False):
        """Для постоянной истории записывает каждую плату и отмечает отсутствие свежих показаний."""
        # Обход полей плат - не каждый такт опроса (90-150 мс), а раз в пару секунд.
        session = getattr(self, "_chamber_monitor_session", None)
        if getattr(self, "_chamber_monitor_suspended", False) or (session is not None and not session.metadata.get("active")):
            return
        if not force and now - float(getattr(self, "_chamber_monitor_tick_s", 0.0) or 0.0) < 2.0:
            return
        self._chamber_monitor_tick_s = now
        for sa in self._chamber_monitor_boards():
            if sa is None:
                self._chamber_monitor_sample_here(now, force)
                continue
            with self._mb_context(sa, notify=False):
                self._chamber_monitor_sample_here(now, force)

    def _chamber_monitor_set_reference(self) -> tuple[bool, str]:
        """«Считать сдвиг от текущего»: сдвиг каждой платы считается от её показания сейчас, а не при +25 °C."""
        if getattr(self, "_chamber_monitor_session", None) is not None:
            return False, "в прогоне сохраняется исходное показание; отклонение от 0 % не обнуляется"
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
        if getattr(self, "_chamber_monitor_session", None) is not None:
            return
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

    def _chamber_monitor_summary(self, label: str, history: list, ref: dict | None):
        """Итоги истории платы: по узлам, худший сдвиг и худшая погрешность.

        13.11.2026: история за сутки - тысячи записей у каждой платы, а окно перечитывало монитор
        на каждом обновлении показаний; полный проход по истории всех плат занимал поток окна, и
        ответы плат опаздывали («пропадает связь», программа тормозила). История меняется раз в
        5 с, поэтому итоги пересчитываются, только когда в ней новая запись или новое показание
        при +25 °C, а не на каждом обновлении.
        """
        key = (len(history), history[-1].get("wall") if history else None,
               None if ref is None else (ref.get("level"), ref.get("wall"), ref.get("auto")))
        cache = getattr(self, "_chamber_monitor_cache", None)
        if cache is None:
            cache = self._chamber_monitor_cache = {}
        cached = cache.get(label)
        if cached is not None and cached[0] == key:
            return cached[1]
        # Для длинного прогона добавляет к итогам только новые записи, пока исходное показание не менялось.
        append_only = (cached is not None and len(cached) > 4 and cached[0][2] == key[2]
                       and 0 < cached[0][0] < len(history)
                       and history[cached[0][0] - 1]["wall"] == cached[0][1])
        if append_only:
            stats, worst_shift, worst_error = cached[1]
            bins = cached[3]
            metrics = cached[4]
            new_samples = history[cached[0][0]:]
        else:
            stats = {}
            worst_shift = worst_error = None
            bins = {"error": {}, "shift": {}}
            metrics = {"count": 0, "sum": 0.0, "min": None, "max": None, "first": None, "last": None}
            new_samples = history
        for sample in new_samples:
            node = chamber_fit.nearest_node(sample["tube"])
            shift = None if ref is None else (sample["level"] - ref["level"]) / 10.0
            error = self._chamber_monitor_error(sample)
            value = error if error is not None else shift
            if value is not None:
                metrics["count"] += 1
                metrics["sum"] += value
                if metrics["first"] is None:
                    metrics["first"] = value
                metrics["last"] = value
                metrics["min"] = value if metrics["min"] is None else min(metrics["min"], value)
                metrics["max"] = value if metrics["max"] is None else max(metrics["max"], value)
            degree = int(round(sample["tube"] / 10.0))
            for kind, value in (("error", error), ("shift", shift)):
                if value is not None:
                    cell = bins[kind].setdefault(degree, [0.0, 0])
                    cell[0] += value
                    cell[1] += 1
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
        result = (stats, worst_shift, worst_error)
        curve = {kind: [[degree, round(total / count, 3)] for degree, (total, count) in sorted(cells.items())]
                 for kind, cells in bins.items()}
        cache[label] = (key, result, curve, bins, metrics)
        return result

    def _chamber_monitor_curve(self, label: str) -> dict:
        """Кривая платы из последнего расчёта итогов: {"error": [[°C, %], ...], "shift": [...]}."""
        cached = (getattr(self, "_chamber_monitor_cache", None) or {}).get(label)
        return cached[2] if cached is not None and len(cached) > 2 else {"error": [], "shift": []}

    def _chamber_monitor_board(self, label: str, now: float) -> dict:
        """Сводка монитора одной платы (в её поле): уровень сейчас, погрешность, сдвиг от +25 °C, узлы."""
        missing = set(self._chamber_live_missing or set())
        current = self._chamber_monitor_current(now)
        ref = self._chamber_monitor_ref
        history = list(self._chamber_monitor_history or [])
        session = getattr(self, "_chamber_monitor_session", None)
        if session is not None and (not session.metadata.get("active") or getattr(self, "_chamber_monitor_suspended", False)):
            current = history[-1] if history else None
        stats, worst_shift, worst_error = self._chamber_monitor_summary(label, history, ref)
        metrics = dict(self._chamber_monitor_cache[label][4])
        if metrics["count"]:
            metrics.update(delta=metrics["last"] - metrics["first"], span=metrics["max"] - metrics["min"],
                           worst=max(abs(metrics["min"]), abs(metrics["max"])), mean=metrics["sum"] / metrics["count"])
        shift = None if current is None or ref is None else (current["level"] - ref["level"]) / 10.0
        error = None if current is None else self._chamber_monitor_error(current)
        comp_shift = None if current is None or ref is None else current["comp"] - ref["comp"]
        # Худшее за прогон - по погрешности, если настоящий уровень известен, иначе по сдвигу от +25 °C.
        worst = worst_error or worst_shift
        judged = [value for value in (error if error is not None else shift,
                                      None if worst is None else worst[0]) if value is not None]

        if "level" in missing or "comp" in missing:
            state, tone = "прошивка не отдаёт уровень", "bad"
        elif current is None:
            state = "нет свежих данных"
            tone = "bad" if worst is not None and abs(worst[0]) > self.CHAMBER_MONITOR_BAD_PP else "info"
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
            # 14.11.2026: главное - погрешность от настоящего уровня (0 % у сухой трубки); сдвиг от +25 °C -
            # только если настоящий уровень неизвестен (пометка не «воздух» и не «жидкость»).
            bucket = stats.get(node) or {}
            errors, shifts = bucket.get("error") or [], bucket.get("shift") or []
            values = errors or shifts
            if not values:
                cells[str(node)] = "—"
                continue
            mean = sum(values) / len(values)
            cells[str(node)] = ("" if errors else "сдвиг ") + f"{_pp(mean)} ({len(values)})"
            node_tone = max(node_tone, self._chamber_monitor_tone(mean), key=lambda item: rank[item])
        cells["label"] = label
        return {"row": live, "detail": detail, "tone": tone, "nodeCells": cells, "nodeTone": node_tone,
                "curve": self._chamber_monitor_curve(label), "metrics": metrics,
                "deviation": shift, "error": error, "worst": None if worst is None else worst[0],
                "stats": stats, "history": history, "ref": ref, "label": label, "state": state}

    def _chamber_monitor_collect(self) -> list[dict]:
        """Сводки монитора всех плат (или одной)."""
        now = time.monotonic()
        boards = []
        multi = getattr(self, "_mb_on", None)
        if multi is not None and multi():
            session = getattr(self, "_chamber_monitor_session", None)
            participants = (session.metadata["boards"] if session is not None else self._mb_result_boards(now))
            stages = session.metadata.get("board_stages") if session is not None else None
            for board in participants:
                sa = int(board["sa"])
                if stages and not stages.get(str(sa), {}).get("check_only"):
                    continue
                with self._mb_context(sa, notify=False):
                    boards.append(dict(self._chamber_monitor_board(self._mb_label(sa), now), sa=sa))
        else:
            target = getattr(self, "_resolve_calibration_target_sa", None)
            sa = int(target()) & 0xFF if callable(target) else None
            label = f"0x{sa:02X}" if sa is not None else "плата"
            boards.append(dict(self._chamber_monitor_board(label, now), sa=sa))
        return boards

    TOLERANCE_TIP = ("Требование к уровню ±1 %: до 0,5 % - в норме, 0,5-1 % - на грани, больше 1 % - вне допуска. "
                     "После калибровки на трубке может оставаться плёнка топлива. Её вклад входит в отклонение и не вычитается. "
                     "Изменение от начального показания само по себе не отделяет плёнку от температурного дрейфа.")

    def _chamber_monitor_plots(self, boards: list) -> dict:
        """Для общего и отдельного графиков готовит линии по времени и температуре без усреднения пиков."""
        key = tuple((board["sa"], len(board["history"]),
                     board["history"][-1]["wall"] if board["history"] else None,
                     (board.get("ref") or {}).get("level")) for board in boards)
        cached = getattr(self, "_chamber_monitor_plots_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        session = getattr(self, "_chamber_monitor_session", None)
        if (cached is not None and session is not None and session.metadata.get("active")
                and time.monotonic() - cached[2] < self.CHAMBER_MONITOR_EVERY_S):
            return cached[1]
        start = min((sample["wall"] for board in boards for sample in board["history"]), default=time.time())
        plots = {"time": {"title": "Отклонение уровня по времени", "xLabel": "Часы от начала", "boards": []},
                 "temperature": {"title": "Отклонение уровня по температуре трубки", "xLabel": "Трубка, °C", "boards": []}}
        colors = ("#0284c7", "#ea580c", "#16a34a", "#9333ea", "#dc2626", "#0891b2", "#ca8a04", "#db2777")
        for index, board in enumerate(boards):
            ref = board.get("ref")
            timed, thermal = [], []
            for sample in board["history"]:
                error = self._chamber_monitor_error(sample)
                value = error if error is not None else (None if ref is None else (sample["level"] - ref["level"]) / 10)
                if value is not None:
                    timed.append([round((sample["wall"] - start) / 3600, 5), round(value, 3)])
                    thermal.append([sample["tube"] / 10, round(value, 3)])
            for mode, points in (("time", timed), ("temperature", thermal)):
                plots[mode]["boards"].append({"key": str(board["sa"]), "label": board["label"],
                                              "color": colors[index % len(colors)], "pts": thin_points(points)})
        self._chamber_monitor_plots_cache = (key, plots, time.monotonic())
        return plots

    def _chamber_monitor_view(self) -> dict:
        """Монитор для окна, сайта, мини-приложения и бота: все платы сразу, коротко; подробности - отдельно."""
        frozen = getattr(self, "_chamber_monitor_frozen", None)
        context = self._chamber_monitor_level_context()
        if frozen is not None:
            return dict(frozen, **context, storageError=getattr(self, "_chamber_monitor_storage_error", "") or "")
        boards = self._chamber_monitor_collect()

        def column(key, title, tip, width, align="right"):
            return {"key": key, "title": title, "tip": tip, "width": width, "align": align}

        now_table = {
            "id": "monitor-now",
            "title": "Уровень топлива сейчас",
            "tip": ("Что выдаёт сам прибор по записанному профилю - у всех плат сразу, обновляется каждые пару "
                    "секунд. Погрешность - уровень прибора минус настоящий: у сухой трубки («воздух») настоящий "
                    "0 %, в топливе («жидкость») 100 %. Сдвиг от +25 °C - насколько уровень ушёл от показания этой "
                    "же платы при +25 °C; он может включать изменение плёнки. " + self.TOLERANCE_TIP),
            "columns": [
                column("label", "Плата", "Адрес узла на шине и подпись платы", 120, "left"),
                column("tube", "Трубка, °C", "Температура топлива (датчик трубки)", 76),
                column("level", "Уровень, %", "Уровень, который выдаёт сам прибор", 80),
                column("err", "Погрешность, %", "Уровень прибора минус настоящий (сухая трубка - 0 %, в топливе - "
                       "100 %). «—» - настоящий уровень неизвестен", 96),
                column("dev", "Сдвиг от +25 °C, %", "Уровень сейчас минус уровень этой же платы при +25 °C трубки", 100),
                column("worst", "Худшее за прогон", "Наибольшая по модулю погрешность (или сдвиг от +25 °C, если "
                       "настоящий уровень неизвестен) и при какой температуре трубки", 170, "left"),
                column("status", "Итог", "Допуск проверяется по отклонению от 0 %, при неизвестном уровне - по сдвигу", 100,
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
                column("samples", "Записей", "Все изменения уровня и контрольная запись каждые 5 с", 64),
            ],
            "rows": [{"tone": board["tone"], "cells": board["detail"]} for board in boards],
        }
        nodes_table = {
            "id": "monitor-nodes",
            "title": "Уровень по узлам: погрешность, %",
            "tip": ("Средняя погрешность уровня, %, пока трубка была в узле (±3 °C): уровень прибора минус настоящий "
                    "(сухая трубка - 0 %, в топливе - 100 %); в скобках - сколько записей. Если "
                    "настоящий уровень неизвестен, стоит «сдвиг» - уход от показания этой платы при +25 °C. Видно, "
                    "при какой температуре профиль не дотягивает. " + self.TOLERANCE_TIP),
            "columns": [column("label", "Плата", "Адрес узла на шине и подпись платы", 120, "left")]
                       + [column(str(node), chamber_fit.node_text(node),
                                 f"Трубка в узле {chamber_fit.node_text(node)} ±3 °C", 96, "center")
                          for node in chamber_fit.NODES_X10],
            "rows": [{"tone": board["nodeTone"], "cells": board["nodeCells"]} for board in boards],
        }
        worst = max((abs(board["worst"]) for board in boards if board["worst"] is not None), default=None)
        live = [{"key": str(board["sa"]), "label": board["label"], "tone": board["tone"], **board["row"]} for board in boards]
        # 14.11.2026: как ведёт себя итоговый уровень на всём диапазоне температур - одной кривой на плату.
        kind = "error" if any(board["curve"]["error"] for board in boards) else "shift"
        curve = {
            "kind": kind,
            "title": ("Погрешность уровня от температуры трубки" if kind == "error"
                      else "Сдвиг уровня от +25 °C по температуре трубки"),
            "tip": ("Каждая линия - плата: средняя погрешность уровня (уровень прибора минус настоящий: сухая трубка - "
                    "0 %, в топливе - 100 %) на каждый градус трубки за весь прогон. Зелёная полоса - ±0,5 %, жёлтая - "
                    "±1 % (требование). Пунктир - узлы сетки профиля." if kind == "error" else
                    "Настоящий уровень неизвестен (пометка не «воздух» и не «жидкость»): линия - уход уровня от "
                    "показания этой платы при +25 °C на каждый градус трубки. Полосы - ±0,5 % и ±1 %."),
            "boards": [{"label": board["label"], "pts": board["curve"][kind]} for board in boards],
        }
        session = getattr(self, "_chamber_monitor_session", None)
        active = bool(session is not None and session.metadata.get("active"))
        gaps = session.level_gaps() if session is not None else 0
        return {**context, "now": now_table, "detail": detail_table, "nodes": nodes_table, "live": live, "curve": curve,
                "summary": [{"key": str(board["sa"]), "label": board["label"], "current": board["error"],
                             "tone": board["tone"], **board["metrics"]} for board in boards],
                "plots": self._chamber_monitor_plots(boards), "hasRun": session is not None, "active": active,
                "sessionId": session.folder.name if session is not None else "",
                "recording": ("Прогон прерван; ожидание продолжения" if getattr(self, "_chamber_monitor_suspended", False) else
                              "Показания всех плат сохраняются на диск" if active else
                              "Прогон завершён. Показан сохранённый результат" if session is not None else "Живое наблюдение"),
                "gaps": gaps, "storageError": getattr(self, "_chamber_monitor_storage_error", ""),
                "condition": "Без погружения, после калибровки. Остаточная плёнка входит в отклонение от 0 %.",
                "worst": None if worst is None else _pp(worst, 2, sign=False),
                "tone": self._chamber_monitor_tone(worst) if worst is not None else "info",
                "everyS": int(self.CHAMBER_MONITOR_EVERY_S), "tip": now_table["tip"]}
