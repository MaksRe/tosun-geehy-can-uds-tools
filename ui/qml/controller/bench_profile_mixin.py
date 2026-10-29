"""Проверка на столе: профиль, снятый в камере, лежит в плате и применяется правильно.

ЗАЧЕМ
После прогона в камере в каждую плату записан свой температурный профиль. Перед сборкой
плат в корпус с трубками нужно убедиться на столе, без камеры, что профиль в плате тот
самый и прибор считает по нему так, как задумано. Пробная калибровка для этого не
годится: она пишет в прибор свой проверочный профиль, а здесь в прибор не пишется ничего.

ЧТО ДЕЛАЕТ (для каждой платы по очереди)
1. Открывает доступ на запись (сеанс и Security Access): без него прибор не принимает
   эмуляцию температуры. В память прибора ничего не пишется, эмуляция живёт только в ОЗУ.
2. Читает из платы весь профиль и сверяет его с файлом профиля из камеры
   (chamber_..._0x<адрес>_profile.json): все семь таблиц и контрольную сумму.
3. Проверяет, что прибор взял таблицы в работу (бит «таблицы применяются»).
4. При настоящей температуре и при десяти эмулированных (-40...+85 °C) читает сырой
   период, период после ступени платы и итоговый и сверяет их с расчётом по формулам
   прошивки (profile_model) с профилем, прочитанным из самой платы.
5. Выключает эмуляцию и проверяет, что она выключилась.

ЧЕГО НЕ ПОКАЗЫВАЕТ
На столе температура платы одна, поэтому ровность компенсированного периода при
настоящем нагреве здесь не видна: эмуляция сдвигает поправку, а сырой период остаётся
комнатным. Это проверяется следующим прогоном в камере.
"""

from __future__ import annotations

import json
import pathlib
import time

from PySide6.QtCore import QTimer

import profile_model
from uds.data_identifiers import UdsData

from .contract import AppControllerContract


class AppControllerBenchProfileMixin(AppControllerContract):
    # Такт хода проверки (переключение плат и ожидание доступа), мс.
    BENCH_TICK_MS = 300
    # Сколько ждать доступа на запись в плату, с.
    BENCH_ACCESS_WAIT_S = 25.0
    # Сколько ждать, пока плату можно будет показать (другой обмен закончится), с.
    BENCH_SWITCH_WAIT_S = 30.0
    # Расхождение итогового периода при настоящей температуре, после которого - замечание, отсчёты.
    # Прибор и программа читают температуру в разные мгновения, поэтому допуск шире, чем при эмуляции.
    BENCH_LIVE_TOLERANCE = 12

    BENCH_STATUS = {
        "pending": ("в очереди", "#64748b"),
        "running": ("идёт проверка", "#0f6ab4"),
        "pass": ("профиль работает", "#16a34a"),
        "warn": ("есть замечания", "#d97706"),
        "fail": ("не пройдено", "#dc2626"),
        "skip": ("не проверено", "#94a3b8"),
    }

    # ------------------------------------------------------------------ состояние

    def _init_bench_state(self):
        """Цель функции в подготовке проверки профиля на столе, затем она ждёт кнопки в разделе пробной калибровки."""
        self._bench_active = False
        self._bench_queue: list[int] = []
        self._bench_current: int | None = None
        self._bench_stage = ""
        self._bench_stage_since = 0.0
        # Калибровку открывала сама проверка: в конце её нужно закрыть.
        self._bench_opened = False
        # Калибровка уже запускалась для текущей платы: второй раз не запускается.
        self._bench_board_opened = False
        self._bench_stop_requested = False
        self._bench_switch_since: float | None = None
        # Итог по каждой плате: {"status", "summary", "detail"}; порядок - как в очереди.
        self._bench_results: dict[int, dict] = {}
        self._bench_order: list[int] = []
        self._bench_timer = QTimer(self)
        self._bench_timer.setInterval(self.BENCH_TICK_MS)
        self._bench_timer.timeout.connect(self._bench_tick)

    def _bench_multi(self) -> bool:
        multi = getattr(self, "_mb_on", None)
        return bool(multi()) if multi is not None else False

    def _bench_board_name(self, sa: int) -> str:
        if self._bench_multi():
            return self._mb_name(sa)
        return f"0x{int(sa) & 0xFF:02X}"

    # ------------------------------------------------------------------ запуск и остановка

    def _bench_refusal(self) -> str:
        """Цель функции в причине, по которой проверку сейчас начать нельзя, затем пустая строка - можно."""
        if self._bench_active:
            return "проверка профиля уже идёт"
        if not self._can.is_connect:
            return "сначала подключите CAN-адаптер"
        if not self._can.is_trace:
            return "сначала включите трассировку CAN"
        if self._trial_busy or self._trial_auto_active:
            return "идёт пробная калибровка, дождитесь её конца"
        if bool(getattr(self, "_profile_busy", False)) or bool(getattr(self, "_chamber_busy", False)) \
                or bool(getattr(self, "_chamber_chain_stage", "")):
            return "идёт обмен с прибором (профиль или снятие точки), дождитесь его конца"
        busy_profiles = getattr(self, "_mb_profiles_busy", None)
        if busy_profiles is not None and busy_profiles():
            return "профили пишутся в платы, дождитесь конца"
        return ""

    def _bench_start(self, all_boards: bool) -> tuple[bool, str]:
        """Цель функции в запуске проверки профиля, затем платы проверяются по очереди без записи в память.

        all_boards - все платы списка «Платы в камере» (режим нескольких плат), иначе - только
        показанная плата (или выбранная в шапке окна, если плата одна).
        """
        problem = self._bench_refusal()
        if problem:
            self._trial_status = f"Проверка профиля не начата: {problem}."
            self._trial_status_color = self.COLOR_FAIL
            self.trialChanged.emit()
            return False, problem

        if self._bench_multi():
            boards = [int(board["sa"]) for board in self._mb_boards]
            if not all_boards:
                shown = self._mb_active_sa
                boards = [int(shown)] if shown is not None else boards[:1]
        else:
            boards = [int(self._resolve_calibration_target_sa()) & 0xFF]

        self._bench_queue = list(boards)
        self._bench_order = list(boards)
        self._bench_results = {sa: {"status": "pending", "summary": "", "detail": ""} for sa in boards}
        self._bench_current = None
        self._bench_stage = ""
        self._bench_opened = False
        self._bench_stop_requested = False
        self._bench_switch_since = None
        self._bench_active = True

        names = ", ".join(f"«{self._bench_board_name(sa)}»" for sa in boards)
        self._trial_log_add("step", "Профиль из камеры: проверка на столе")
        self._trial_log_add(
            "info",
            f"Платы: {names}. В память приборов ничего не пишется: профиль читается, сверяется с файлом "
            "из камеры, а применение проверяется эмуляцией температуры, которая живёт только в ОЗУ прибора.")
        self._trial_status = f"Проверяю профиль: {names}..."
        self._trial_status_color = self.COLOR_RUN
        self.trialChanged.emit()
        self._bench_timer.start()
        self._bench_tick()
        return True, ""

    def _bench_stop(self):
        """Цель функции в остановке проверки, затем текущая плата доводится до конца (эмуляция выключится)."""
        if not self._bench_active:
            return
        self._bench_stop_requested = True
        self._bench_queue = []
        self._trial_log_add("warn", "Проверка профиля остановлена: плата, которая проверяется сейчас, будет доведена до конца.")
        if self._bench_current is not None and self._bench_stage == "access":
            self._bench_set_result(self._bench_current, "skip", "проверка остановлена до начала обмена", "")
            self._bench_current = None
        self.trialChanged.emit()
        if self._bench_current is None:
            self._bench_finish()

    # ------------------------------------------------------------------ ход

    def _bench_tick(self):
        """Цель функции в ходе проверки по тактам, затем она переключает платы, ждёт доступа и запускает обмен."""
        if not self._bench_active:
            self._bench_timer.stop()
            return
        if self._trial_busy:
            return
        now = time.monotonic()

        if self._bench_current is None:
            if not self._bench_queue:
                self._bench_finish()
                return
            sa = self._bench_queue[0]
            if self._bench_multi():
                if self._bench_switch_since is None:
                    self._bench_switch_since = now
                ready = self._mb_calibration_free_for(sa, now) and self._mb_activate(sa)
                if not ready:
                    if now - self._bench_switch_since > self.BENCH_SWITCH_WAIT_S:
                        self._bench_queue.pop(0)
                        self._bench_switch_since = None
                        self._bench_set_result(
                            sa, "fail", "плату не удалось выбрать: другой обмен не закончился за "
                            f"{self.BENCH_SWITCH_WAIT_S:.0f} с", "")
                    return
            self._bench_switch_since = None
            self._bench_queue.pop(0)
            self._bench_current = sa
            self._bench_stage = "access"
            self._bench_stage_since = now
            self._bench_board_opened = False
            self._bench_set_result(sa, "running", "открываю доступ на запись...", "")
            self._trial_log_add("step", f"Плата «{self._bench_board_name(sa)}» (0x{sa:02X})")
            return

        sa = self._bench_current
        if self._bench_stage == "access":
            if self._trial_write_ready():
                self._bench_stage = "ops"
                self._bench_set_result(sa, "running", "читаю профиль и прохожу температуры...", "")
                if not self._trial_start_ops(self._bench_ops(), "_bench_ops_done"):
                    self._bench_board_done(sa, "fail", "обмен не запустился: проверьте адаптер и трассировку", "")
                return
            if not bool(self._calibration_active) and not bool(getattr(self, "_calibration_waiting_session", False)):
                if self._bench_board_opened:
                    self._bench_board_done(sa, "fail", "калибровка не запустилась: плата не открыла сеанс", "")
                    return
                # Та же операция, что кнопка «Начать калибровку»: сеанс и доступ на запись.
                self.startCalibration()
                self._bench_board_opened = True
                self._bench_opened = True
            if now - self._bench_stage_since > self.BENCH_ACCESS_WAIT_S:
                if not bool(self._calibration_active):
                    reason = "калибровка не запустилась"
                elif not bool(self._calibration_session_ready):
                    reason = "прибор не подтвердил сессию"
                else:
                    reason = "Security Access открыт не для этой платы"
                self._bench_board_done(
                    sa, "fail", f"доступ на запись не открылся за {self.BENCH_ACCESS_WAIT_S:.0f} с: {reason}", "")

    def _bench_ops(self) -> list[dict]:
        """Цель функции в очереди обмена одной платы, затем по её ответам выносится итог."""
        ops = [
            self._op_call("profile_started", "_trial_backup_profile_call"),
            self._op_await("await_profile", "profile_read", self.TRIAL_PROFILE_TIMEOUT_MS),
            self._trial_emulation_op("emul_off", None),
            self._op_wait(self.TRIAL_SETTLE_MS),
            self._op_read("status", UdsData.fuel_thermal_profile_status),
            self._op_read("zero_trim", UdsData.fuel_zero_trim_count, signed=True),
            # Настоящая температура: прибор считает по своим датчикам.
            self._op_read("now_board_t", UdsData.raw_board_temperature, signed=True),
            self._op_read("now_fuel_t", UdsData.raw_temperature, signed=True),
            self._op_read("now_raw_a", UdsData.curr_fuel_tank),
            self._op_read("now_board", UdsData.fuel_board_stage_period),
            self._op_read("now_comp", UdsData.fuel_compensated_period),
            self._op_read("now_raw_b", UdsData.curr_fuel_tank),
        ]
        for index, temperature in enumerate(self.TRIAL_APPLY_TEMPS_X10):
            ops += [
                self._trial_emulation_op(f"w{index}", temperature),
                self._op_wait(self.TRIAL_SETTLE_MS),
                self._op_read(f"raw_a{index}", UdsData.curr_fuel_tank),
                self._op_read(f"board{index}", UdsData.fuel_board_stage_period),
                self._op_read(f"comp{index}", UdsData.fuel_compensated_period),
                self._op_read(f"raw_b{index}", UdsData.curr_fuel_tank),
                self._op_read(f"mode{index}", UdsData.fuel_board_stage_mode),
            ]
        ops += [
            self._trial_emulation_op("emul_off_end", None),
            self._op_wait(self.TRIAL_SETTLE_MS),
            self._op_read("emul_after", UdsData.temperature_emulation_x10, signed=True),
        ]
        return ops

    # ------------------------------------------------------------------ итог платы

    def _bench_profile_file(self, sa: int) -> pathlib.Path | None:
        """Цель функции в поиске файла профиля платы из камеры, затем с ним сверяется профиль в плате.

        Файл пишется рядом с журналом платы: chamber_<время>_<имя>_0x<адрес>_profile.json.
        Берётся самый свежий по времени изменения во всех папках журналов (своя, прошлые версии).
        """
        tail = f"_0x{int(sa) & 0xFF:02x}_profile.json"
        found = []
        for folder in self._chamber_journal_dirs():
            try:
                files = list(folder.rglob("chamber_*_profile.json"))
            except OSError:
                continue
            for path in files:
                if not path.name.lower().endswith(tail):
                    continue
                try:
                    found.append((path.stat().st_mtime, path))
                except OSError:
                    continue
        if not found:
            return None
        return max(found, key=lambda item: item[0])[1]

    def _bench_compare_file(self, sa: int, device: dict, device_crc) -> tuple[list[str], list[str], str]:
        """Цель функции в сверке профиля платы с файлом из камеры, затем итог: (расхождения, замечания, строка).

        Сверяются все семь таблиц и контрольная сумма. Нет файла - замечание, а не отказ:
        файл мог остаться на другом компьютере.
        """
        path = self._bench_profile_file(sa)
        if path is None:
            return [], ["файл профиля этой платы из камеры не найден - сверено только с самим прибором"], ""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            tables = payload["таблицы"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            return [], [f"файл профиля {path.name} не прочитался: {error}"], ""
        differ = []
        for name, _did, title, _width in self.PROFILE_TABLES:
            expected = [int(value) for value in (tables.get(name) or [])]
            if expected != [int(value) for value in device.get(name, [])]:
                differ.append(title.lower())
        problems = []
        if differ:
            problems.append(f"в плате не тот профиль, что снят в камере: отличаются таблицы ({', '.join(differ)})")
        file_crc = payload.get("контрольная_сумма")
        if not differ and device_crc is not None and file_crc is not None and int(file_crc) != int(device_crc):
            problems.append(f"сумма профиля в плате 0x{int(device_crc):04X}, в файле 0x{int(file_crc):04X}")
        return problems, [], f"Файл из камеры: {path.name}" + ("" if problems else " - все таблицы совпали.")

    def _bench_ops_done(self, res: dict):
        """Цель функции в итоге одной платы по ответам, затем проверка переходит к следующей."""
        sa = self._bench_current
        if sa is None:
            return
        if res.get("profile_started") is not True or res.get("profile_read") is not True \
                or str(self._profile_status).startswith("Операция прервана"):
            emulation = "" if res.get("emul_off_end") is True else " Эмуляция могла остаться включённой."
            self._bench_board_done(sa, "fail", f"профиль из платы не прочитался: {self._profile_status}{emulation}", "")
            return

        device = {name: list(values) for name, values in self._profile_values.items()}
        problems: list[str] = []
        notes: list[str] = []
        lines: list[str] = []

        empty = profile_model.lut_is_empty(profile_model.pairs_from_flat(device.get("board_main", [])))
        if empty:
            problems.append("таблица платы основного контура в приборе пустая: профиль из камеры не записан")

        file_problems, file_notes, file_line = self._bench_compare_file(sa, device, self._profile_device_crc)
        problems += file_problems
        notes += file_notes
        if file_line:
            lines.append(file_line)

        crc, crc_actual = self._profile_device_crc, getattr(self, "_profile_device_crc_actual", None)
        if crc is not None and crc_actual is not None and int(crc) != int(crc_actual):
            problems.append(f"сумма профиля в плате не сходится: записана 0x{int(crc):04X}, "
                            f"прибор насчитал 0x{int(crc_actual):04X}")

        # Настоящая температура: итог прибора против расчёта по его же профилю.
        status = self._trial_value(res, "status")
        trusted = bool((status or 0) & profile_model.STATUS_TRUSTED)
        zero_trim = self._trial_value(res, "zero_trim") or 0
        now_values = [self._trial_value(res, key) for key in
                      ("now_board_t", "now_fuel_t", "now_raw_a", "now_board", "now_comp", "now_raw_b")]
        if None not in now_values:
            board_t, fuel_t, raw_a, board, comp, raw_b = now_values
            expected = [profile_model.predict_main(raw, device, board_temp_x10=board_t, tube_temp_x10=fuel_t,
                                                   trusted=trusted, zero_trim=zero_trim)["compensated"]
                        for raw in (raw_a, raw_b)]
            lines.append(
                f"Сейчас, плата {self._trial_temp_text(board_t)}: сырой {raw_a}, после платы {board}, итог {comp} "
                f"(по расчёту {expected[0]}), поправка {comp - raw_a:+d}")
            if not (min(expected) - self.BENCH_LIVE_TOLERANCE <= comp <= max(expected) + self.BENCH_LIVE_TOLERANCE):
                notes.append(f"при настоящей температуре итог {comp}, а по расчёту {expected[0]}")
        else:
            notes.append("показания при настоящей температуре прибор отдал не все")

        # Эмулированные температуры: та же сверка, что в пробной калибровке, но с профилем самой платы.
        sweep_problems, sweep_lines = self._trial_apply_compare(res, profile=device)
        problems += sweep_problems
        corrections = []
        for index, temperature in enumerate(self.TRIAL_APPLY_TEMPS_X10):
            raw, comp = self._trial_value(res, f"raw_a{index}"), self._trial_value(res, f"comp{index}")
            if raw is not None and comp is not None:
                corrections.append((temperature, comp - raw))
        lines += sweep_lines

        if res.get("emul_off_end") is not True or self._trial_value(res, "emul_after") not in (None, -32768):
            problems.append("эмуляция после проверки не выключилась - нажмите «Выключить эмуляцию»")

        if problems:
            status_key, summary = "fail", "; ".join(problems)
        else:
            if corrections:
                low = min(value for _t, value in corrections)
                high = max(value for _t, value in corrections)
                span = f"поправка от {low:+d} до {high:+d} отсчётов при -40...+85 °C"
            else:
                span = "поправка не измерена"
            summary = f"профиль из камеры в плате, прибор считает по нему точно как по расчёту; {span}"
            status_key = "warn" if notes else "pass"
            if notes:
                summary += "; замечания: " + "; ".join(notes)
        self._bench_board_done(sa, status_key, summary, "\n".join(lines))

    def _bench_set_result(self, sa: int, status: str, summary: str, detail: str):
        self._bench_results[int(sa)] = {"status": status, "summary": str(summary), "detail": str(detail)}
        self.trialChanged.emit()

    def _bench_board_done(self, sa: int, status: str, summary: str, detail: str):
        """Цель функции в итоге платы в журнале и таблице, затем такт возьмёт следующую плату."""
        self._bench_set_result(sa, status, summary, detail)
        word, _color = self.BENCH_STATUS.get(status, self.BENCH_STATUS["pending"])
        level = {"pass": "ok", "warn": "warn", "fail": "fail"}.get(status, "info")
        text = f"«{self._bench_board_name(sa)}»: {word}. {summary[:1].upper() + summary[1:]}."
        self._trial_log_add(level, "\n".join([text] + ([detail] if detail else [])))
        self._bench_current = None
        self._bench_stage = ""
        self.trialChanged.emit()
        if self._bench_stop_requested or not self._bench_queue:
            self._bench_finish()

    def _bench_finish(self):
        """Цель функции в завершении проверки, затем калибровка закрывается, если её открыла проверка."""
        if not self._bench_active:
            return
        self._bench_active = False
        self._bench_timer.stop()
        for sa, result in self._bench_results.items():
            if result["status"] in ("pending", "running"):
                result.update(status="skip", summary="проверка остановлена")
        if self._bench_opened or self._bench_multi():
            close = getattr(self, "_mb_calibration_close", None)
            if close is not None:
                close()
            elif bool(self._calibration_active):
                self.stopCalibration()
        statuses = [result["status"] for result in self._bench_results.values()]
        good = sum(1 for status in statuses if status == "pass")
        warned = sum(1 for status in statuses if status == "warn")
        failed = sum(1 for status in statuses if status == "fail")
        text = (f"Проверка профиля на столе закончена: работает у {good + warned} из {len(statuses)} плат"
                + (f", с замечаниями - {warned}" if warned else "") + (f", не пройдено - {failed}" if failed else "")
                + ".")
        level, color = ("fail", self.COLOR_FAIL) if failed else (("warn", self.COLOR_WARN) if warned or good < len(statuses)
                                                                  else ("ok", self.COLOR_OK))
        self._trial_log_add(level, text)
        self._trial_status = text
        self._trial_status_color = color
        self.trialChanged.emit()

    # ------------------------------------------------------------------ для окна

    def _bench_view(self) -> dict:
        """Цель функции в данных для окна, затем раздел показывает плитку итога каждой платы."""
        rows = []
        for sa in self._bench_order:
            result = self._bench_results.get(sa, {"status": "pending", "summary": "", "detail": ""})
            word, color = self.BENCH_STATUS.get(result["status"], self.BENCH_STATUS["pending"])
            rows.append({
                "sa": int(sa), "saText": f"0x{int(sa):02X}", "name": self._bench_board_name(sa),
                "status": result["status"], "statusText": word, "color": color,
                "summary": result["summary"], "detail": result["detail"],
                "current": sa == self._bench_current,
            })
        return {"active": bool(self._bench_active), "multi": self._bench_multi(), "rows": rows,
                "stopping": bool(self._bench_stop_requested)}
