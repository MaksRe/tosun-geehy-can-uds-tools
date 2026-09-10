"""Мастер калибровки контура вида топлива (плоского конденсатора).

ЗАЧЕМ ЭТО НУЖНО
Поправка на вид топлива работает от двух опорных чисел: сколько отсчётов даёт
плоский конденсатор в воздухе и сколько в эталонной жидкости. Раньше их надо
было снимать вручную: открыть окно параметров, прочитать DID 0x0036, списать
число на бумажку, вписать его в DID 0x002F или 0x0030. На каждом шаге можно
ошибиться, а неверная опора тихо искажает уровень топлива во всём диапазоне.

ЧТО ДЕЛАЕТ МАСТЕР
Сам снимает серию показаний, проверяет что они устоялись, записывает результат
в нужный параметр и читает его обратно для подтверждения. Включить поправку он
разрешает только когда точка в жидкости заметно выше точки в воздухе: иначе
опоры недостоверны.

ЧЕГО МАСТЕР НЕ ДЕЛАЕТ
Он не поднимает сессию и не открывает доступ на запись. Это делает сценарий
калибровки, и мастер просто требует, чтобы тот был запущен: так права на запись
запрашиваются в одном месте программы, а не в двух.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer

from uds.data_identifiers import UdsData
from uds.services.read_data_by_id import ServiceReadDataById
from uds.services.write_data_by_id import ServiceWriteDataById

from .contract import AppControllerContract


class AppControllerMediaWizardMixin(AppControllerContract):
    # Сколько показаний берём в серию и с каким шагом, мс.
    MEDIA_WIZARD_SAMPLES = 12
    MEDIA_WIZARD_SAMPLE_GAP_MS = 120
    MEDIA_WIZARD_TIMEOUT_MS = 800

    # Разброс серии, выше которого считаем что показание ещё не устоялось, отсчёты.
    MEDIA_WIZARD_STABLE_SPREAD = 40

    # Минимальная разница между жидкостью и воздухом, отсчёты.
    # Дизельное топливо примерно вдвое поднимает ёмкость плоского конденсатора,
    # поэтому разница в пару десятков отсчётов означает ошибку в снятии точки.
    MEDIA_WIZARD_MIN_SPAN = 200

    # Период обновления живого показания, когда мастер просто наблюдает, мс.
    MEDIA_WIZARD_WATCH_GAP_MS = 250

    MEDIA_WIZARD_COLOR_OK = "#16a34a"
    MEDIA_WIZARD_COLOR_WARN = "#d97706"
    MEDIA_WIZARD_COLOR_BAD = "#dc2626"
    MEDIA_WIZARD_COLOR_IDLE = "#64748b"

    # ------------------------------------------------------------------ состояние

    def _init_media_wizard_state(self):
        """Готовит мастер к работе. Вызывается один раз при создании контроллера."""
        self._media_wizard_read_service = ServiceReadDataById()
        self._media_wizard_read_service.set_byte_order("big")
        self._media_wizard_write_service = ServiceWriteDataById()
        self._media_wizard_write_service.set_byte_order("big")

        self._media_wizard_watching = False
        self._media_wizard_busy = False
        self._media_wizard_action = ""
        self._media_wizard_status = "Запустите калибровку, затем снимите две точки."
        self._media_wizard_status_color = self.MEDIA_WIZARD_COLOR_IDLE

        self._media_wizard_pending = None
        self._media_wizard_samples = []
        self._media_wizard_live_raw = None
        self._media_wizard_live_spread = None

        self._media_wizard_air = None
        self._media_wizard_cal = None
        self._media_wizard_enabled = None

        self._media_wizard_gap_timer = QTimer(self)
        self._media_wizard_gap_timer.setSingleShot(True)
        self._media_wizard_gap_timer.setInterval(self.MEDIA_WIZARD_SAMPLE_GAP_MS)
        self._media_wizard_gap_timer.timeout.connect(self._on_media_wizard_gap_timeout)

        self._media_wizard_timeout_timer = QTimer(self)
        self._media_wizard_timeout_timer.setSingleShot(True)
        self._media_wizard_timeout_timer.setInterval(self.MEDIA_WIZARD_TIMEOUT_MS)
        self._media_wizard_timeout_timer.timeout.connect(self._on_media_wizard_timeout)

    # ------------------------------------------------------------------ доступ на запись

    def _media_wizard_write_allowed(self) -> bool:
        """Сообщает, открыт ли сейчас доступ на запись параметров."""
        return bool(self._calibration_active) and bool(self._calibration_session_ready)

    def _media_wizard_require_write_access(self) -> bool:
        """Проверяет права на запись и объясняет оператору, чего не хватает."""
        if self._media_wizard_write_allowed():
            return True

        self._media_wizard_set_status(
            "Сначала нажмите «Начать калибровку» в шапке окна: без неё прибор запись не примет.",
            self.MEDIA_WIZARD_COLOR_WARN,
        )
        return False

    def _media_wizard_set_status(self, text: str, color: str):
        """Записывает подпись о ходе работы и её цвет."""
        self._media_wizard_status = str(text)
        self._media_wizard_status_color = str(color)
        self.mediaWizardChanged.emit()

    # ------------------------------------------------------------------ обмен

    def _media_wizard_request(self, action: str, var, value=None) -> bool:
        """Отправляет один запрос чтения или записи и включает ожидание ответа."""
        self._media_wizard_pending = (action, var, value)

        try:
            if value is None:
                sent = self._media_wizard_read_service.read_data_by_identifier(
                    self._build_calibration_tx_identifier(), var
                )
            else:
                self._media_wizard_write_service.set_expected_pid(int(var.pid) & 0xFFFF)
                sent = self._media_wizard_write_service.write_data(
                    var, int(value), tx_identifier=self._build_calibration_tx_identifier()
                )
        except Exception:
            sent = False

        if not sent:
            self._media_wizard_pending = None
            self._media_wizard_finish("Не удалось отправить запрос. Проверьте подключение к шине.",
                                      self.MEDIA_WIZARD_COLOR_BAD)
            return False

        self._media_wizard_timeout_timer.start(self.MEDIA_WIZARD_TIMEOUT_MS)
        return True

    def _media_wizard_finish(self, text: str, color: str):
        """Завершает текущую операцию мастера и снимает признак занятости."""
        self._media_wizard_busy = False
        self._media_wizard_action = ""
        self._media_wizard_pending = None
        self._media_wizard_samples = []
        self._media_wizard_gap_timer.stop()
        self._media_wizard_timeout_timer.stop()
        self._media_wizard_set_status(text, color)

    def _on_media_wizard_timeout(self):
        """Прибор не ответил вовремя."""
        if self._media_wizard_pending is None:
            return

        action, var, _value = self._media_wizard_pending
        self._media_wizard_pending = None

        if action == "watch":
            # Наблюдение не критично: пробуем ещё раз на следующем шаге.
            self._media_wizard_gap_timer.start(self.MEDIA_WIZARD_WATCH_GAP_MS)
            return

        self._media_wizard_finish(
            f"Прибор не ответил на DID 0x{int(var.pid) & 0xFFFF:04X}. Проверьте адрес узла и связь.",
            self.MEDIA_WIZARD_COLOR_BAD,
        )

    def _on_media_wizard_gap_timeout(self):
        """Пауза вышла: продолжаем серию или очередное наблюдение."""
        if self._media_wizard_busy:
            self._media_wizard_request("sample", UdsData.fuel_media_flatcap_raw)
            return

        if self._media_wizard_watching:
            self._media_wizard_request("watch", UdsData.fuel_media_flatcap_raw)

    def _handle_media_wizard_frame(self, identifier: int, payload):
        """Разбирает ответ прибора на запрос мастера."""
        if self._media_wizard_pending is None:
            return
        if not isinstance(payload, (list, tuple)) or len(payload) < 4:
            return
        if not self._is_calibration_response_identifier(identifier):
            return

        action, var, value = self._media_wizard_pending
        expected_did = int(var.pid) & 0xFFFF

        if ((int(payload[0]) >> 4) & 0x0F) != 0x00:
            return

        body_length = int(payload[0]) & 0x0F
        if body_length < 3 or body_length > (len(payload) - 1):
            return

        body = [int(item) & 0xFF for item in payload[1:1 + body_length]]

        if body[0] == 0x7F:
            self._media_wizard_timeout_timer.stop()
            self._media_wizard_pending = None
            code = body[2] if len(body) > 2 else 0
            if action == "watch":
                self._media_wizard_watching = False
                self._media_wizard_set_status(
                    f"Прибор не отдаёт показание контура (код 0x{code:02X}).", self.MEDIA_WIZARD_COLOR_BAD
                )
                return
            self._media_wizard_finish(
                self._media_wizard_refusal_text(code), self.MEDIA_WIZARD_COLOR_BAD
            )
            return

        answer_did = (body[1] << 8) | body[2]
        if answer_did != expected_did:
            return

        if body[0] == 0x62 and len(body) >= 4:
            raw = 0
            shift = 0
            for byte_value in body[3:]:
                raw |= byte_value << shift
                shift += 8
            self._media_wizard_timeout_timer.stop()
            self._media_wizard_pending = None
            self._media_wizard_on_value(action, var, int(raw))
            return

        if body[0] == 0x6E:
            self._media_wizard_timeout_timer.stop()
            self._media_wizard_pending = None
            self._media_wizard_on_write_confirmed(action, var, value)

    @staticmethod
    def _media_wizard_refusal_text(code: int) -> str:
        """Переводит код отказа прибора в понятную причину."""
        if code == 0x33:
            return "Прибор отказал: не открыт доступ на запись. Запустите калибровку заново."
        if code == 0x7F or code == 0x7E:
            return "Прибор отказал: операция недоступна в текущей сессии."
        if code == 0x31:
            return "Прибор отказал: значение вне допустимого диапазона."
        return f"Прибор отказал в операции (код 0x{code:02X})."

    # ------------------------------------------------------------------ логика шагов

    def _media_wizard_on_value(self, action: str, var, value: int):
        """Обрабатывает прочитанное значение в зависимости от текущего шага."""
        if action == "watch":
            self._media_wizard_live_raw = int(value)
            self.mediaWizardChanged.emit()
            self._media_wizard_gap_timer.start(self.MEDIA_WIZARD_WATCH_GAP_MS)
            return

        if action == "sample":
            self._media_wizard_samples.append(int(value))
            self._media_wizard_live_raw = int(value)
            self._media_wizard_live_spread = max(self._media_wizard_samples) - min(self._media_wizard_samples)
            self._media_wizard_set_status(
                f"Снимаю показание: {len(self._media_wizard_samples)} из {self.MEDIA_WIZARD_SAMPLES}.",
                self.MEDIA_WIZARD_COLOR_IDLE,
            )

            if len(self._media_wizard_samples) < self.MEDIA_WIZARD_SAMPLES:
                self._media_wizard_gap_timer.start(self.MEDIA_WIZARD_SAMPLE_GAP_MS)
                return

            self._media_wizard_apply_series()
            return

        if action in ("verify_air", "verify_cal", "verify_enable"):
            self._media_wizard_on_verified(action, int(value))

    def _media_wizard_apply_series(self):
        """Проверяет устойчивость серии и записывает её среднее в нужный параметр."""
        samples = list(self._media_wizard_samples)
        spread = max(samples) - min(samples)
        average = int(round(sum(samples) / float(len(samples))))
        self._media_wizard_live_spread = spread

        if spread > self.MEDIA_WIZARD_STABLE_SPREAD:
            self._media_wizard_finish(
                f"Показание не устоялось: разброс {spread} отсч. при допуске {self.MEDIA_WIZARD_STABLE_SPREAD}. "
                "Дайте прибору успокоиться и повторите.",
                self.MEDIA_WIZARD_COLOR_WARN,
            )
            return

        if average <= 0:
            self._media_wizard_finish(
                "Контур вида топлива не даёт измерения. Проверьте плоский конденсатор.",
                self.MEDIA_WIZARD_COLOR_BAD,
            )
            return

        if self._media_wizard_action == "air":
            self._media_wizard_samples = []
            self._media_wizard_set_status(
                f"Записываю точку в воздухе: {average} отсч.", self.MEDIA_WIZARD_COLOR_IDLE
            )
            self._media_wizard_request("write_air", UdsData.fuel_media_flatcap_air_count, average)
            return

        # Точку в жидкости не пишем, если она не выше точки в воздухе: такая
        # пара опор даёт бессмысленный коэффициент среды.
        if self._media_wizard_air is not None and average <= int(self._media_wizard_air):
            self._media_wizard_finish(
                f"Показание в жидкости {average} не выше показания в воздухе {int(self._media_wizard_air)}. "
                "Проверьте, что конденсатор действительно погружён.",
                self.MEDIA_WIZARD_COLOR_BAD,
            )
            return

        self._media_wizard_samples = []
        self._media_wizard_set_status(
            f"Записываю точку в жидкости: {average} отсч.", self.MEDIA_WIZARD_COLOR_IDLE
        )
        self._media_wizard_request("write_cal", UdsData.fuel_media_flatcap_cal_count, average)

    def _media_wizard_on_write_confirmed(self, action: str, var, value):
        """Прибор принял запись: читаем параметр обратно для подтверждения."""
        if action == "write_air":
            self._media_wizard_set_status("Точка в воздухе записана, проверяю.", self.MEDIA_WIZARD_COLOR_IDLE)
            self._media_wizard_request("verify_air", UdsData.fuel_media_flatcap_air_count)
            return

        if action == "write_cal":
            self._media_wizard_set_status("Точка в жидкости записана, проверяю.", self.MEDIA_WIZARD_COLOR_IDLE)
            self._media_wizard_request("verify_cal", UdsData.fuel_media_flatcap_cal_count)
            return

        if action == "write_enable":
            self._media_wizard_set_status("Настройка записана, проверяю.", self.MEDIA_WIZARD_COLOR_IDLE)
            self._media_wizard_request("verify_enable", UdsData.fuel_media_comp_enable)

    def _media_wizard_on_verified(self, action: str, value: int):
        """Сверяет прочитанное обратно значение с тем, что писали."""
        # Чтение уже сохранённых значений идёт цепочкой из трёх параметров.
        if self._media_wizard_action == "refresh":
            if action == "verify_air":
                self._media_wizard_air = int(value)
                self._media_wizard_request("verify_cal", UdsData.fuel_media_flatcap_cal_count)
                return
            if action == "verify_cal":
                self._media_wizard_cal = int(value)
                self._media_wizard_request("verify_enable", UdsData.fuel_media_comp_enable)
                return
            self._media_wizard_enabled = int(value)
            self._media_wizard_finish(
                f"Прочитано из прибора: воздух {self._media_wizard_air}, "
                f"жидкость {self._media_wizard_cal}, разница {self._media_wizard_span_text()}.",
                self.MEDIA_WIZARD_COLOR_IDLE,
            )
            return

        if action == "verify_air":
            self._media_wizard_air = int(value)
            self._media_wizard_finish(
                f"Точка в воздухе сохранена: {int(value)} отсч. Теперь погрузите конденсатор в топливо.",
                self.MEDIA_WIZARD_COLOR_OK,
            )
            return

        if action == "verify_cal":
            self._media_wizard_cal = int(value)
            span = None if self._media_wizard_air is None else int(value) - int(self._media_wizard_air)
            if span is not None and span < self.MEDIA_WIZARD_MIN_SPAN:
                self._media_wizard_finish(
                    f"Точка в жидкости сохранена, но разница с воздухом всего {span} отсч. "
                    f"Ожидается не меньше {self.MEDIA_WIZARD_MIN_SPAN}. Проверьте погружение и повторите.",
                    self.MEDIA_WIZARD_COLOR_WARN,
                )
                return
            self._media_wizard_finish(
                f"Точка в жидкости сохранена: {int(value)} отсч. Разница с воздухом {span} отсч. "
                "Можно включать поправку.",
                self.MEDIA_WIZARD_COLOR_OK,
            )
            return

        if action == "verify_enable":
            self._media_wizard_enabled = int(value)
            if int(value) == 1:
                self._media_wizard_finish("Поправка по виду топлива включена.", self.MEDIA_WIZARD_COLOR_OK)
            else:
                self._media_wizard_finish("Поправка по виду топлива выключена.", self.MEDIA_WIZARD_COLOR_IDLE)

    # ------------------------------------------------------------------ команды

    def _media_wizard_start_watch(self):
        """Включает живое наблюдение за показанием плоского конденсатора."""
        if self._media_wizard_watching:
            return
        if not self._can.is_connect or not self._can.is_trace:
            self._media_wizard_set_status(
                "Подключите адаптер и включите трассировку CAN.", self.MEDIA_WIZARD_COLOR_WARN
            )
            return

        self._media_wizard_watching = True
        self.mediaWizardChanged.emit()
        if not self._media_wizard_busy:
            self._media_wizard_request("watch", UdsData.fuel_media_flatcap_raw)

    def _media_wizard_stop_watch(self):
        """Выключает живое наблюдение."""
        self._media_wizard_watching = False
        if not self._media_wizard_busy:
            self._media_wizard_gap_timer.stop()
            self._media_wizard_timeout_timer.stop()
            self._media_wizard_pending = None
        self.mediaWizardChanged.emit()

    def _media_wizard_capture(self, target: str):
        """Запускает снятие серии для точки в воздухе или в жидкости."""
        if self._media_wizard_busy:
            return
        if not self._media_wizard_require_write_access():
            return

        self._media_wizard_busy = True
        self._media_wizard_action = str(target)
        self._media_wizard_samples = []
        self._media_wizard_pending = None
        place = "воздухе" if target == "air" else "топливе"
        self._media_wizard_set_status(f"Снимаю серию показаний в {place}...", self.MEDIA_WIZARD_COLOR_IDLE)
        self._media_wizard_request("sample", UdsData.fuel_media_flatcap_raw)

    def _media_wizard_set_enabled(self, enabled: bool):
        """Включает или выключает поправку по виду топлива."""
        if self._media_wizard_busy:
            return
        if not self._media_wizard_require_write_access():
            return

        if enabled and not self._media_wizard_points_are_valid():
            self._media_wizard_set_status(
                "Сначала снимите обе точки: жидкость должна быть заметно выше воздуха.",
                self.MEDIA_WIZARD_COLOR_WARN,
            )
            return

        self._media_wizard_busy = True
        self._media_wizard_action = "enable"
        self._media_wizard_set_status(
            "Включаю поправку..." if enabled else "Выключаю поправку...", self.MEDIA_WIZARD_COLOR_IDLE
        )
        self._media_wizard_request("write_enable", UdsData.fuel_media_comp_enable, 1 if enabled else 0)

    def _media_wizard_refresh_saved(self):
        """Читает из прибора уже сохранённые опорные точки и состояние поправки."""
        if self._media_wizard_busy:
            return
        self._media_wizard_busy = True
        self._media_wizard_action = "refresh"
        self._media_wizard_set_status("Читаю сохранённые точки...", self.MEDIA_WIZARD_COLOR_IDLE)
        self._media_wizard_request("verify_air", UdsData.fuel_media_flatcap_air_count)

    def _media_wizard_points_are_valid(self) -> bool:
        """Сообщает, годится ли снятая пара точек для включения поправки."""
        if self._media_wizard_air is None or self._media_wizard_cal is None:
            return False
        return (int(self._media_wizard_cal) - int(self._media_wizard_air)) >= self.MEDIA_WIZARD_MIN_SPAN

    # ------------------------------------------------------------------ тексты для окна

    def _media_wizard_span_text(self) -> str:
        """Возвращает разницу между точками словами и числом."""
        if self._media_wizard_air is None or self._media_wizard_cal is None:
            return "нужны обе точки"
        span = int(self._media_wizard_cal) - int(self._media_wizard_air)
        if span < self.MEDIA_WIZARD_MIN_SPAN:
            return f"{span} отсч., мало (нужно от {self.MEDIA_WIZARD_MIN_SPAN})"
        return f"{span} отсч., достаточно"
