"""Проверка работоспособности измерительных контуров и датчиков температуры.

ЗАЧЕМ ОТДЕЛЬНЫЙ ИНСТРУМЕНТ
Окно параметров умеет прочитать любой DID, но выдаёт голое число. Чтобы понять,
исправен ли прибор, оператору пришлось бы держать в голове полтора десятка
допусков. Здесь те же величины опрашиваются по кругу и сразу переводятся в
понятный вердикт: норма, внимание или отказ, с короткой подсказкой что делать.

ЧТО ПРОВЕРЯЕТСЯ
- контур уровня топлива: период, дрожание, дребезг компараторов, симметрия;
- контур вида топлива: то же плюс коэффициент среды и состояние коррекции;
- два датчика температуры и разница между ними.

КАК УСТРОЕН ОПРОС
Постоянные величины (границы калибровки, пределы, настройки) читаются один раз
при запуске. Меняющиеся - по кругу, по одному запросу за раз, с таймаутом. Все
ответы умещаются в один кадр, сборка мультипакета здесь не нужна.

ВЫБОР УЗЛА
Общий с окном калибровки: тот же список и тот же адрес назначения. Так оператор
не выбирает прибор дважды и не путает узлы.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer

from uds.data_identifiers import UdsData
from uds.services.read_data_by_id import ServiceReadDataById

from .contract import AppControllerContract


class AppControllerDiagnosticsMixin(AppControllerContract):
    # Пауза между запросами и таймаут ответа, мс.
    DIAGNOSTICS_REQUEST_GAP_MS = 60
    DIAGNOSTICS_TIMEOUT_MS = 700

    # Цвета вердиктов. Совпадают с палитрой остальных карточек.
    DIAGNOSTICS_COLOR_OK = "#16a34a"
    DIAGNOSTICS_COLOR_WARN = "#d97706"
    DIAGNOSTICS_COLOR_BAD = "#dc2626"
    DIAGNOSTICS_COLOR_IDLE = "#64748b"

    # Отсчётов таймера на пикофараду для измерительного тракта этой платы.
    DIAGNOSTICS_COUNTS_PER_PF = 40.9

    # Пороги дрожания измерения, отсчёты. 24 отсчёта это примерно 0,6 пФ.
    DIAGNOSTICS_SPREAD_GOOD = 12
    DIAGNOSTICS_SPREAD_WARN = 24
    DIAGNOSTICS_SPREAD_BAD = 48

    # Пороги асимметрии половин заряда и разряда, отсчёты.
    DIAGNOSTICS_HALF_DELTA_GOOD = 20
    DIAGNOSTICS_HALF_DELTA_WARN = 60

    # Разбег температур бака и платы, выше которого показываем предупреждение, 0.1 °C.
    DIAGNOSTICS_TEMP_DELTA_WARN_X10 = 150

    # Границы таблицы NTC в прошивке, 0.1 °C. За ними показание недостоверно.
    DIAGNOSTICS_TEMP_MIN_X10 = -400
    DIAGNOSTICS_TEMP_MAX_X10 = 800

    def _diagnostics_static_vars(self):
        """Возвращает величины, которые читаются один раз за сеанс проверки."""
        return (
            ("empty_period", UdsData.empty_fuel_tank, False),
            ("full_period", UdsData.full_fuel_tank, False),
            ("media_enable", UdsData.fuel_media_comp_enable, False),
            ("media_air", UdsData.fuel_media_flatcap_air_count, False),
            ("media_cal", UdsData.fuel_media_flatcap_cal_count, False),
            ("media_rf_min", UdsData.fuel_media_rf_min_x1000, False),
            ("media_rf_max", UdsData.fuel_media_rf_max_x1000, False),
            ("media_freeze_pct", UdsData.fuel_media_freeze_level_pct, False),
            ("temp_source", UdsData.fuel_temp_comp_source, False),
        )

    def _diagnostics_cycle_vars(self):
        """Возвращает величины, читаемые по кругу. True означает знаковое значение."""
        return (
            ("cur_period", UdsData.curr_fuel_tank, False),
            ("raw_level", UdsData.raw_fuel_level, True),
            ("fuel_temp", UdsData.raw_temperature, True),
            ("board_temp", UdsData.raw_board_temperature, True),
            ("board_adc", UdsData.board_temperature_adc, False),
            ("main_spread", UdsData.cap_main_burst_spread, False),
            ("main_spread_max", UdsData.cap_main_spread_max, False),
            ("main_half_delta", UdsData.cap_main_half_delta, True),
            ("main_overrun", UdsData.cap_main_overrun_cnt, False),
            ("media_raw", UdsData.fuel_media_flatcap_raw, False),
            ("media_rf", UdsData.fuel_media_rf_x1000, False),
            ("media_state", UdsData.fuel_media_state, False),
            ("media_rejected", UdsData.fuel_media_rejected_cnt, False),
            ("media_spread_max", UdsData.cap_media_spread_max, False),
            ("media_overrun", UdsData.cap_media_overrun_cnt, False),
        )

    # ------------------------------------------------------------------ состояние

    def _init_diagnostics_state(self):
        """Готовит диагностику к работе. Вызывается один раз при создании контроллера."""
        self._diagnostics_read_service = ServiceReadDataById()
        # Для этого МК номер DID в запросе 0x22 всегда идёт в стандартном порядке.
        self._diagnostics_read_service.set_byte_order("big")

        self._diagnostics_running = False
        self._diagnostics_status = "Проверка не запущена."
        self._diagnostics_values = {}
        self._diagnostics_missing = set()
        self._diagnostics_queue = []
        self._diagnostics_pending = None
        self._diagnostics_cycles_done = 0
        self._diagnostics_counter_prev = {}
        self._diagnostics_counter_growing = {}
        self._diagnostics_rows = []
        self._diagnostics_summary_text = "Нажмите «Начать проверку»."
        self._diagnostics_summary_color = self.DIAGNOSTICS_COLOR_IDLE

        self._diagnostics_gap_timer = QTimer(self)
        self._diagnostics_gap_timer.setSingleShot(True)
        self._diagnostics_gap_timer.setInterval(self.DIAGNOSTICS_REQUEST_GAP_MS)
        self._diagnostics_gap_timer.timeout.connect(self._on_diagnostics_gap_timeout)

        self._diagnostics_timeout_timer = QTimer(self)
        self._diagnostics_timeout_timer.setSingleShot(True)
        self._diagnostics_timeout_timer.setInterval(self.DIAGNOSTICS_TIMEOUT_MS)
        self._diagnostics_timeout_timer.timeout.connect(self._on_diagnostics_timeout)

        self._rebuild_diagnostics_rows()

    # ------------------------------------------------------------------ управление

    def _start_diagnostics_poll(self) -> bool:
        """Запускает круговой опрос. Возвращает False, если запуск сейчас невозможен."""
        if self._diagnostics_running:
            return True

        if not self._can.is_connect:
            self.infoMessage.emit("Проверка прибора", "Сначала подключите CAN-адаптер.")
            return False

        if not self._can.is_trace:
            self.infoMessage.emit("Проверка прибора", "Сначала включите трассировку CAN.")
            return False

        # Калибровка ведёт собственный обмен теми же сервисами, параллельно нельзя.
        if self._calibration_active:
            self.infoMessage.emit(
                "Проверка прибора",
                "Идёт сценарий калибровки. Завершите его и повторите проверку.",
            )
            return False

        self._diagnostics_values = {}
        self._diagnostics_missing = set()
        self._diagnostics_counter_prev = {}
        self._diagnostics_counter_growing = {}
        self._diagnostics_cycles_done = 0
        self._diagnostics_pending = None
        # Сначала настройки и границы, затем первый круг меняющихся величин.
        self._diagnostics_queue = list(self._diagnostics_static_vars()) + list(self._diagnostics_cycle_vars())
        self._diagnostics_running = True
        self._diagnostics_status = "Читаем настройки прибора..."
        self._rebuild_diagnostics_rows()

        return self._send_next_diagnostics_request()

    def _stop_diagnostics_poll(self, status_text: str):
        """Останавливает опрос и записывает причину остановки."""
        self._diagnostics_running = False
        self._diagnostics_pending = None
        self._diagnostics_queue = []
        self._diagnostics_gap_timer.stop()
        self._diagnostics_timeout_timer.stop()
        self._diagnostics_status = str(status_text)
        self._rebuild_diagnostics_rows()

    # ------------------------------------------------------------------ обмен

    @staticmethod
    def _diagnostics_to_signed(value: int, size_bytes: int) -> int:
        """Переводит беззнаковое поле в знаковое по разрядности параметра."""
        bits = max(8, int(size_bytes) * 8)
        limit = 1 << bits
        raw = int(value) & (limit - 1)
        return raw - limit if raw >= (limit >> 1) else raw

    def _send_next_diagnostics_request(self) -> bool:
        """Отправляет следующий запрос из очереди. Пустая очередь начинает новый круг."""
        if not self._diagnostics_running:
            return False

        if not self._diagnostics_queue:
            self._diagnostics_cycles_done += 1
            self._diagnostics_queue = list(self._diagnostics_cycle_vars())

        key, var, signed = self._diagnostics_queue.pop(0)
        self._diagnostics_pending = (key, var, signed)

        try:
            sent = self._diagnostics_read_service.read_data_by_identifier(
                self._build_calibration_tx_identifier(), var
            )
        except Exception:
            sent = False

        if not sent:
            self._stop_diagnostics_poll("Не удалось отправить запрос. Проверьте подключение к шине.")
            return False

        self._diagnostics_timeout_timer.start(self.DIAGNOSTICS_TIMEOUT_MS)
        return True

    def _on_diagnostics_gap_timeout(self):
        """Пауза между запросами вышла, отправляем следующий."""
        self._send_next_diagnostics_request()

    def _on_diagnostics_timeout(self):
        """Прибор не ответил на запрос за отведённое время."""
        if (not self._diagnostics_running) or (self._diagnostics_pending is None):
            return

        key, var, _signed = self._diagnostics_pending
        self._diagnostics_pending = None

        # Параметра может не быть в старой прошивке. Это не отказ прибора, идём дальше.
        self._diagnostics_missing.add(key)
        self._diagnostics_values.pop(key, None)
        self._diagnostics_status = (
            f"Нет ответа на DID 0x{int(var.pid) & 0xFFFF:04X}. Возможно, в приборе старая прошивка."
        )
        self._rebuild_diagnostics_rows()
        self._diagnostics_gap_timer.start(self.DIAGNOSTICS_REQUEST_GAP_MS)

    def _handle_diagnostics_frame(self, identifier: int, payload):
        """Разбирает ответ прибора на запрос диагностики."""
        if (not self._diagnostics_running) or (self._diagnostics_pending is None):
            return
        if not isinstance(payload, (list, tuple)) or len(payload) < 4:
            return
        if not self._is_calibration_response_identifier(identifier):
            return

        key, var, signed = self._diagnostics_pending
        expected_did = int(var.pid) & 0xFFFF

        # Ответ короткий, поэтому ждём одиночный кадр ISO-TP.
        if ((int(payload[0]) >> 4) & 0x0F) != 0x00:
            return

        body_length = int(payload[0]) & 0x0F
        if body_length < 3 or body_length > (len(payload) - 1):
            return

        body = [int(value) & 0xFF for value in payload[1:1 + body_length]]

        # Отрицательный ответ: параметр не поддержан либо закрыт в текущей сессии.
        if body[0] == 0x7F:
            self._diagnostics_timeout_timer.stop()
            self._diagnostics_pending = None
            self._diagnostics_missing.add(key)
            self._diagnostics_values.pop(key, None)
            code = body[2] if len(body) > 2 else 0
            self._diagnostics_status = f"DID 0x{expected_did:04X}: прибор ответил отказом (код 0x{code:02X})."
            self._rebuild_diagnostics_rows()
            self._diagnostics_gap_timer.start(self.DIAGNOSTICS_REQUEST_GAP_MS)
            return

        if body[0] != 0x62 or len(body) < 4:
            return

        # Номер DID принимаем в обоих порядках байтов: сборки прошивки отвечают по-разному.
        answer_big = (body[1] << 8) | body[2]
        answer_little = (body[2] << 8) | body[1]
        if expected_did not in (answer_big, answer_little):
            return

        raw = 0
        shift = 0
        for byte_value in body[3:]:
            raw |= byte_value << shift
            shift += 8

        value = self._diagnostics_to_signed(raw, var.size) if signed else raw

        self._diagnostics_timeout_timer.stop()
        self._diagnostics_pending = None
        self._diagnostics_missing.discard(key)

        # Счётчики важны не значением, а тем, растут ли они между кругами опроса.
        if key in ("main_overrun", "media_overrun", "media_rejected"):
            previous = self._diagnostics_counter_prev.get(key)
            if previous is not None:
                self._diagnostics_counter_growing[key] = int(value) != int(previous)
            self._diagnostics_counter_prev[key] = int(value)

        self._diagnostics_values[key] = int(value)
        self._diagnostics_status = f"Опрос идёт, круг {self._diagnostics_cycles_done + 1}."
        self._rebuild_diagnostics_rows()
        self._diagnostics_gap_timer.start(self.DIAGNOSTICS_REQUEST_GAP_MS)

    # ------------------------------------------------------------------ вердикты

    def _diagnostics_value(self, key: str):
        """Возвращает прочитанное значение или None, если его ещё нет."""
        return self._diagnostics_values.get(key)

    @classmethod
    def _diagnostics_spread_verdict(cls, spread):
        """Переводит размах серии измерений в вердикт с подсказкой."""
        if spread is None:
            return "-", cls.DIAGNOSTICS_COLOR_IDLE, "Значение ещё не прочитано"

        spread = int(spread)
        picofarad = spread / cls.DIAGNOSTICS_COUNTS_PER_PF
        if spread <= cls.DIAGNOSTICS_SPREAD_GOOD:
            return "Отлично", cls.DIAGNOSTICS_COLOR_OK, f"Дрожание {picofarad:.2f} пФ, тракт чистый"
        if spread <= cls.DIAGNOSTICS_SPREAD_WARN:
            return "Норма", cls.DIAGNOSTICS_COLOR_OK, f"Дрожание {picofarad:.2f} пФ, в допуске"
        if spread <= cls.DIAGNOSTICS_SPREAD_BAD:
            return "Внимание", cls.DIAGNOSTICS_COLOR_WARN, f"Дрожание {picofarad:.2f} пФ, стоит усилить фильтр захвата"
        return "Плохо", cls.DIAGNOSTICS_COLOR_BAD, f"Дрожание {picofarad:.2f} пФ, нужен гистерезис на компараторах"

    @classmethod
    def _diagnostics_half_delta_verdict(cls, delta):
        """Переводит асимметрию половин заряда и разряда в вердикт."""
        if delta is None:
            return "-", cls.DIAGNOSTICS_COLOR_IDLE, "Значение ещё не прочитано"

        magnitude = abs(int(delta))
        if magnitude <= cls.DIAGNOSTICS_HALF_DELTA_GOOD:
            return "Норма", cls.DIAGNOSTICS_COLOR_OK, "Заряд и разряд симметричны"
        if magnitude <= cls.DIAGNOSTICS_HALF_DELTA_WARN:
            return "Внимание", cls.DIAGNOSTICS_COLOR_WARN, "Небольшая асимметрия, проследите за динамикой"
        return "Проверить датчик", cls.DIAGNOSTICS_COLOR_BAD, "Похоже на утечку: вода в топливе или грязь на электродах"

    def _diagnostics_counter_verdict(self, key: str, growing_text: str, growing_hint: str):
        """Переводит счётчик событий в вердикт по факту его роста между кругами."""
        if self._diagnostics_value(key) is None:
            return "-", self.DIAGNOSTICS_COLOR_IDLE, "Значение ещё не прочитано"

        growing = self._diagnostics_counter_growing.get(key)
        if growing is None:
            return "Измеряется", self.DIAGNOSTICS_COLOR_IDLE, "Нужен ещё один круг опроса"
        if growing:
            return growing_text, self.DIAGNOSTICS_COLOR_WARN, growing_hint
        return "Не растёт", self.DIAGNOSTICS_COLOR_OK, "За круг опроса новых событий не было"

    def _diagnostics_period_verdict(self, period, empty, full):
        """Проверяет, попадает ли период измерения в рабочий диапазон калибровки."""
        if period is None:
            return "-", self.DIAGNOSTICS_COLOR_IDLE, "Значение ещё не прочитано"

        period = int(period)
        if period >= 0xFFFF:
            return "Отказ контура", self.DIAGNOSTICS_COLOR_BAD, "Прошивка отдаёт аварийный признак вместо измерения"
        if period == 0:
            return "Нет измерения", self.DIAGNOSTICS_COLOR_BAD, "Контур ни разу не выдал результат"
        if empty is None or full is None or int(full) <= int(empty):
            return "Нет калибровки", self.DIAGNOSTICS_COLOR_WARN, "Границы пустого и полного бака не заданы"

        empty, full = int(empty), int(full)
        percent = (period - empty) * 100.0 / (full - empty)
        if -10.0 <= percent <= 110.0:
            return "Норма", self.DIAGNOSTICS_COLOR_OK, f"Соответствует уровню {percent:.1f} %"
        if percent < -10.0:
            return "Ниже диапазона", self.DIAGNOSTICS_COLOR_BAD, "Похоже на обрыв датчика"
        return "Выше диапазона", self.DIAGNOSTICS_COLOR_BAD, "Похоже на замыкание датчика"

    def _diagnostics_temperature_verdict(self, temperature_x10):
        """Проверяет достоверность показания датчика температуры."""
        if temperature_x10 is None:
            return "-", self.DIAGNOSTICS_COLOR_IDLE, "Значение ещё не прочитано"

        temperature_x10 = int(temperature_x10)
        if temperature_x10 <= self.DIAGNOSTICS_TEMP_MIN_X10 or temperature_x10 >= self.DIAGNOSTICS_TEMP_MAX_X10:
            return "На краю шкалы", self.DIAGNOSTICS_COLOR_BAD, "Обрыв, замыкание или датчик не подключён"
        return "Норма", self.DIAGNOSTICS_COLOR_OK, "Показание в рабочем диапазоне таблицы NTC"

    def _diagnostics_media_state_verdict(self, state):
        """Расшифровывает слово состояния коррекции по виду топлива."""
        if state is None:
            return "-", self.DIAGNOSTICS_COLOR_IDLE, "Значение ещё не прочитано"

        state = int(state)
        if state & 0x08:
            return "Отказ контура", self.DIAGNOSTICS_COLOR_BAD, "Контур вида топлива не выдаёт данных"
        if state & 0x02:
            return "Данные устарели", self.DIAGNOSTICS_COLOR_BAD, "Контур молчит дольше допустимого"
        if state & 0x01:
            return "Коррекция работает", self.DIAGNOSTICS_COLOR_OK, "Шкала пересчитывается под текущее топливо"
        if state & 0x04:
            return "Заморожено", self.DIAGNOSTICS_COLOR_WARN, "Уровень ниже порога погружения либо значение отбраковано"
        return "Выключена", self.DIAGNOSTICS_COLOR_IDLE, "Коррекция по виду топлива не включена"

    def _diagnostics_rf_verdict(self, rf, rf_min, rf_max):
        """Проверяет коэффициент среды на попадание в заданный коридор."""
        if rf is None:
            return "-", self.DIAGNOSTICS_COLOR_IDLE, "Значение ещё не прочитано"

        rf = int(rf)
        if rf_min is not None and rf_max is not None and int(rf_min) < int(rf_max):
            if rf < int(rf_min) or rf > int(rf_max):
                return "Вне коридора", self.DIAGNOSTICS_COLOR_BAD, "Проверьте плоский конденсатор и его калибровку"
        if rf == 1000:
            return "Нейтраль", self.DIAGNOSTICS_COLOR_IDLE, "Шкала не растянута, коэффициент равен единице"
        return "Норма", self.DIAGNOSTICS_COLOR_OK, f"Шкала растянута в {rf / 1000.0:.3f} раза"

    # ------------------------------------------------------------------ таблица

    @staticmethod
    def _diagnostics_row(group, label, value_text, verdict, color, hint):
        """Собирает одну строку таблицы проверки."""
        return {
            "group": str(group),
            "label": str(label),
            "value": str(value_text),
            "verdict": str(verdict),
            "color": str(color),
            "hint": str(hint),
        }

    @staticmethod
    def _diagnostics_text(value, suffix: str = "", scale: float = 1.0, digits: int = 0) -> str:
        """Форматирует значение для показа, прочерк если оно ещё не прочитано."""
        if value is None:
            return "-"
        if scale == 1.0 and digits == 0:
            return f"{int(value)}{suffix}"
        return f"{float(value) * scale:.{digits}f}{suffix}"

    def _rebuild_diagnostics_rows(self):
        """Пересобирает таблицу и общий вердикт по последним прочитанным значениям."""
        rows = []

        empty = self._diagnostics_value("empty_period")
        full = self._diagnostics_value("full_period")

        # --- Контур уровня топлива ---
        group = "Контур уровня топлива"

        period = self._diagnostics_value("cur_period")
        verdict, color, hint = self._diagnostics_period_verdict(period, empty, full)
        rows.append(self._diagnostics_row(
            group, "Период датчика", self._diagnostics_text(period, " отсч."), verdict, color, hint,
        ))

        rows.append(self._diagnostics_row(
            group, "Границы калибровки",
            f"{self._diagnostics_text(empty)} ... {self._diagnostics_text(full)}",
            "Справочно", self.DIAGNOSTICS_COLOR_IDLE, "Периоды, снятые для пустого и полного бака",
        ))

        rows.append(self._diagnostics_row(
            group, "Уровень топлива",
            self._diagnostics_text(self._diagnostics_value("raw_level"), " %", 0.1, 1),
            "Справочно", self.DIAGNOSTICS_COLOR_IDLE, "Значение, которое прибор отдаёт в шину",
        ))

        spread_max = self._diagnostics_value("main_spread_max")
        verdict, color, hint = self._diagnostics_spread_verdict(spread_max)
        rows.append(self._diagnostics_row(
            group, "Дрожание измерения", self._diagnostics_text(spread_max, " отсч."), verdict, color, hint,
        ))

        rows.append(self._diagnostics_row(
            group, "Размах последней серии",
            self._diagnostics_text(self._diagnostics_value("main_spread"), " отсч."),
            "Справочно", self.DIAGNOSTICS_COLOR_IDLE, "Мгновенное значение, максимум за окно строкой выше",
        ))

        half_delta = self._diagnostics_value("main_half_delta")
        verdict, color, hint = self._diagnostics_half_delta_verdict(half_delta)
        rows.append(self._diagnostics_row(
            group, "Симметрия заряда и разряда", self._diagnostics_text(half_delta, " отсч."), verdict, color, hint,
        ))

        verdict, color, hint = self._diagnostics_counter_verdict(
            "main_overrun", "Дребезг есть", "Компараторы дребезжат, усильте фильтр захвата",
        )
        rows.append(self._diagnostics_row(
            group, "Дребезг компараторов",
            self._diagnostics_text(self._diagnostics_value("main_overrun")), verdict, color, hint,
        ))

        # --- Контур вида топлива ---
        group = "Контур вида топлива"

        media_raw = self._diagnostics_value("media_raw")
        air = self._diagnostics_value("media_air")
        cal = self._diagnostics_value("media_cal")
        if media_raw is None:
            verdict, color, hint = "-", self.DIAGNOSTICS_COLOR_IDLE, "Значение ещё не прочитано"
        elif int(media_raw) == 0:
            verdict, color, hint = "Нет измерения", self.DIAGNOSTICS_COLOR_BAD, "Контур ни разу не выдал результат"
        elif air is not None and int(air) > 0 and int(media_raw) <= int(air):
            verdict, color, hint = "Датчик сухой", self.DIAGNOSTICS_COLOR_WARN, "Показание не выше значения в воздухе"
        else:
            verdict, color, hint = "Норма", self.DIAGNOSTICS_COLOR_OK, "Контур измеряет"
        rows.append(self._diagnostics_row(
            group, "Плоский конденсатор", self._diagnostics_text(media_raw, " отсч."), verdict, color, hint,
        ))

        if air is None or cal is None:
            verdict, color, hint = "-", self.DIAGNOSTICS_COLOR_IDLE, "Значения ещё не прочитаны"
        elif int(cal) > int(air) > 0:
            verdict, color, hint = (
                "Откалиброван", self.DIAGNOSTICS_COLOR_OK,
                "Точка в воздухе и точка в жидкости сняты и различаются правильно",
            )
        else:
            verdict, color, hint = (
                "Не откалиброван", self.DIAGNOSTICS_COLOR_WARN,
                "Снимите точку в воздухе и точку в эталонной жидкости",
            )
        rows.append(self._diagnostics_row(
            group, "Калибровка контура",
            f"{self._diagnostics_text(air)} / {self._diagnostics_text(cal)}",
            verdict, color, hint,
        ))

        enable = self._diagnostics_value("media_enable")
        if enable is None:
            enable_text = "-"
            verdict, color, hint = "-", self.DIAGNOSTICS_COLOR_IDLE, "Значение ещё не прочитано"
        elif int(enable) == 0:
            enable_text = "выключена"
            verdict, color, hint = (
                "Не используется", self.DIAGNOSTICS_COLOR_IDLE,
                "Прибор работает по обычной шкале, без поправки на вид топлива",
            )
        elif air is not None and cal is not None and not (int(cal) > int(air) > 0):
            enable_text = "включена"
            verdict, color, hint = (
                "Нет калибровки", self.DIAGNOSTICS_COLOR_BAD,
                "Поправка считается по чужим числам, выключите её или откалибруйте контур",
            )
        else:
            enable_text = "включена"
            verdict, color, hint = "Норма", self.DIAGNOSTICS_COLOR_OK, "Поправка на вид топлива разрешена"
        rows.append(self._diagnostics_row(
            group, "Поправка по виду топлива", enable_text, verdict, color, hint,
        ))

        rf = self._diagnostics_value("media_rf")
        verdict, color, hint = self._diagnostics_rf_verdict(
            rf, self._diagnostics_value("media_rf_min"), self._diagnostics_value("media_rf_max"),
        )
        rows.append(self._diagnostics_row(
            group, "Коэффициент среды", self._diagnostics_text(rf, "", 0.001, 3), verdict, color, hint,
        ))

        state = self._diagnostics_value("media_state")
        verdict, color, hint = self._diagnostics_media_state_verdict(state)
        rows.append(self._diagnostics_row(
            group, "Состояние коррекции",
            "-" if state is None else f"0x{int(state) & 0xFF:02X}", verdict, color, hint,
        ))

        media_spread = self._diagnostics_value("media_spread_max")
        verdict, color, hint = self._diagnostics_spread_verdict(media_spread)
        rows.append(self._diagnostics_row(
            group, "Дрожание измерения", self._diagnostics_text(media_spread, " отсч."), verdict, color, hint,
        ))

        verdict, color, hint = self._diagnostics_counter_verdict(
            "media_overrun", "Дребезг есть", "Компараторы дребезжат, усильте фильтр захвата",
        )
        rows.append(self._diagnostics_row(
            group, "Дребезг компараторов",
            self._diagnostics_text(self._diagnostics_value("media_overrun")), verdict, color, hint,
        ))

        verdict, color, hint = self._diagnostics_counter_verdict(
            "media_rejected", "Растёт", "Коэффициент среды отбраковывается: вода, грязь или неверная калибровка",
        )
        rows.append(self._diagnostics_row(
            group, "Отбраковка значений",
            self._diagnostics_text(self._diagnostics_value("media_rejected")), verdict, color, hint,
        ))

        # --- Температура ---
        group = "Температура"

        fuel_temp = self._diagnostics_value("fuel_temp")
        verdict, color, hint = self._diagnostics_temperature_verdict(fuel_temp)
        rows.append(self._diagnostics_row(
            group, "Датчик в топливе", self._diagnostics_text(fuel_temp, " °C", 0.1, 1), verdict, color, hint,
        ))

        board_temp = self._diagnostics_value("board_temp")
        verdict, color, hint = self._diagnostics_temperature_verdict(board_temp)
        rows.append(self._diagnostics_row(
            group, "Датчик на плате", self._diagnostics_text(board_temp, " °C", 0.1, 1), verdict, color, hint,
        ))

        if fuel_temp is None or board_temp is None:
            delta_text = "-"
            verdict, color, hint = "-", self.DIAGNOSTICS_COLOR_IDLE, "Значения ещё не прочитаны"
        else:
            delta = int(fuel_temp) - int(board_temp)
            delta_text = f"{delta / 10.0:+.1f} °C"
            if abs(delta) <= self.DIAGNOSTICS_TEMP_DELTA_WARN_X10:
                verdict, color, hint = "Норма", self.DIAGNOSTICS_COLOR_OK, "Датчики согласованы между собой"
            else:
                verdict, color, hint = (
                    "Большая разница", self.DIAGNOSTICS_COLOR_WARN,
                    "Это нормально, если зонд в топливе, а плата греется снаружи",
                )
        rows.append(self._diagnostics_row(group, "Разница датчиков", delta_text, verdict, color, hint))

        rows.append(self._diagnostics_row(
            group, "Код АЦП датчика платы",
            self._diagnostics_text(self._diagnostics_value("board_adc")),
            "Справочно", self.DIAGNOSTICS_COLOR_IDLE, "Нужен, если показание температуры выглядит странно",
        ))

        source = self._diagnostics_value("temp_source")
        if source is None:
            source_text = "-"
            verdict, color, hint = "-", self.DIAGNOSTICS_COLOR_IDLE, "Значение ещё не прочитано"
        elif int(source) == 1:
            source_text = "датчик платы"
            verdict, color, hint = (
                "Новый режим", self.DIAGNOSTICS_COLOR_OK,
                "Компенсация тракта считается по температуре платы",
            )
        else:
            source_text = "датчик топлива"
            verdict, color, hint = (
                "Прежний режим", self.DIAGNOSTICS_COLOR_IDLE,
                "Коэффициенты K1 сняты по датчику в топливе, менять источник без пересчёта нельзя",
            )
        rows.append(self._diagnostics_row(group, "Источник компенсации", source_text, verdict, color, hint))

        self._diagnostics_rows = rows
        self._rebuild_diagnostics_summary(rows)
        self.diagnosticsChanged.emit()

    def _rebuild_diagnostics_summary(self, rows):
        """Формирует общий вердикт: берётся худший из вердиктов таблицы."""
        if (not self._diagnostics_running) and (not self._diagnostics_values):
            self._diagnostics_summary_text = "Нажмите «Начать проверку»."
            self._diagnostics_summary_color = self.DIAGNOSTICS_COLOR_IDLE
            return

        for row in rows:
            if row.get("color") == self.DIAGNOSTICS_COLOR_BAD:
                self._diagnostics_summary_text = f"Есть отказ: {row['group']}, {row['label']}"
                self._diagnostics_summary_color = self.DIAGNOSTICS_COLOR_BAD
                return

        for row in rows:
            if row.get("color") == self.DIAGNOSTICS_COLOR_WARN:
                self._diagnostics_summary_text = f"Требует внимания: {row['group']}, {row['label']}"
                self._diagnostics_summary_color = self.DIAGNOSTICS_COLOR_WARN
                return

        if self._diagnostics_cycles_done < 1:
            self._diagnostics_summary_text = "Идёт первый круг опроса, подождите."
            self._diagnostics_summary_color = self.DIAGNOSTICS_COLOR_IDLE
            return

        self._diagnostics_summary_text = "Все контуры и датчики в норме."
        self._diagnostics_summary_color = self.DIAGNOSTICS_COLOR_OK

    def _diagnostics_node_caption(self) -> str:
        """Возвращает подпись выбранного узла так же, как её видит оператор."""
        try:
            index = int(self._selected_calibration_node_index)
            if 0 <= index < len(self._calibration_node_options):
                return str(self._calibration_node_options[index])
        except Exception:
            pass
        return f"Узел 0x{int(self._resolve_calibration_target_sa()) & 0xFF:02X}"

    def _build_diagnostics_report(self) -> str:
        """Собирает текстовый отчёт о проверке, пригодный для отправки коллегам."""
        lines = [
            "Проверка топливозаборника",
            f"Прибор: {self._diagnostics_node_caption()}",
            f"Итог: {self._diagnostics_summary_text}",
            "",
        ]

        current_group = ""
        for row in self._diagnostics_rows:
            group = str(row.get("group", ""))
            if group != current_group:
                current_group = group
                lines.append(group)
            lines.append(
                f"  {row.get('label', '')}: {row.get('value', '')}"
                f"  [{row.get('verdict', '')}]  {row.get('hint', '')}"
            )

        if self._diagnostics_missing:
            lines.append("")
            lines.append("Прибор не ответил на часть параметров, возможно в нём старая прошивка.")

        return "\n".join(lines)
