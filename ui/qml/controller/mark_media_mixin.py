"""Показание вида топлива в момент отметок 0 % и 100 %.

ЗАЧЕМ
Модель расчёта уровня по двум контурам (параметр 0x0053 = 1) помнит, что
показывал контур вида топлива в момент каждой отметки бака: параметры 0x0054 и
0x0055. Без них модель уровень не считает. Раньше эти числа можно было вписать
только вручную в разделе параметров, и ничто не гарантировало, что они сняты в
том же состоянии датчика, что и сама отметка.

ЧТО ДЕЛАЕТ МОДУЛЬ
Когда отметка записана и сверена, модуль сразу снимает короткую серию показаний
плоского конденсатора (0x0036), проверяет, что они устоялись, читает точку
«воздух» (0x002F), пишет среднее в 0x0054 или 0x0055 и читает обратно. Датчик в
эту секунду стоит там же, где снималась отметка, поэтому пара «отметка и вид
топлива» относится к одному состоянию.

Серия снимается, только если записанная отметка совпадает с тем, что прибор
показывает сейчас. Значение, введённое вручную не по месту, к текущему показанию
вида топлива отношения не имеет: тогда модуль ничего не пишет и объясняет почему.

Обмен идёт цепочкой: следующий запрос уходит только после ответа на прежний.
Прибор держит один канал ISO-TP и затёр бы запрос, пришедший раньше ответа.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer

from colors import RowColor
from uds.data_identifiers import UdsData
from uds.services.read_data_by_id import ServiceReadDataById
from uds.services.write_data_by_id import ServiceWriteDataById

from .contract import AppControllerContract


class AppControllerMarkMediaMixin(AppControllerContract):
    # Серия показаний плоского конденсатора: сколько и с каким шагом, мс.
    MARK_MEDIA_SAMPLES = 6
    MARK_MEDIA_SAMPLE_GAP_MS = 120
    MARK_MEDIA_TIMEOUT_MS = 800

    # Разброс серии, выше которого показание считается неустоявшимся, отсчёты.
    MARK_MEDIA_STABLE_SPREAD = 40

    # Насколько записанная отметка может отличаться от показания прибора, чтобы
    # считаться снятой по месту, отсчёты. Шум периода на столе в пределах пары десятков.
    MARK_MEDIA_LIVE_TOLERANCE = 50

    # Наименьшая разность показаний вида топлива и воздуха, при которой прошивка
    # принимает отметку в модель по двум контурам (FUEL_TANK_MIN_MEDIA_DELTA).
    MARK_MEDIA_MIN_DELTA = 10

    MARK_MEDIA_COLOR_OK = "#16a34a"
    MARK_MEDIA_COLOR_WARN = "#d97706"
    MARK_MEDIA_COLOR_BAD = "#dc2626"
    MARK_MEDIA_COLOR_IDLE = "#64748b"

    # ------------------------------------------------------------------ состояние

    def _init_mark_media_state(self):
        """Готовит модуль к работе. Вызывается один раз при создании контроллера."""
        self._mark_media_read_service = ServiceReadDataById()
        self._mark_media_read_service.set_byte_order("big")
        self._mark_media_write_service = ServiceWriteDataById()
        self._mark_media_write_service.set_byte_order("big")

        # Для каждой записанной отметки: снята ли она по месту. Заполняется при отправке записи.
        self._mark_media_intent = {}
        self._mark_media_active = False
        self._mark_media_mark_did = None
        self._mark_media_pending = None
        self._mark_media_samples = []
        self._mark_media_value = None
        self._mark_media_air = None
        self._mark_media_status = ""
        self._mark_media_status_color = self.MARK_MEDIA_COLOR_IDLE

        self._mark_media_gap_timer = QTimer(self)
        self._mark_media_gap_timer.setSingleShot(True)
        self._mark_media_gap_timer.timeout.connect(self._on_mark_media_gap_timeout)

        self._mark_media_timeout_timer = QTimer(self)
        self._mark_media_timeout_timer.setSingleShot(True)
        self._mark_media_timeout_timer.timeout.connect(self._on_mark_media_timeout)

    # ------------------------------------------------------------------ подписи

    @staticmethod
    def _mark_media_target(mark_did: int):
        """Параметр вида топлива, который относится к отметке, и её подпись."""
        if int(mark_did) == int(UdsData.empty_fuel_tank.pid):
            return UdsData.fuel_tank_zero_media_count, "0 %"
        return UdsData.fuel_tank_full_media_count, "100 %"

    def _mark_media_set_status(self, text: str, color: str, log_color=None):
        """Показывает итог в разделе и дублирует его в журнал."""
        self._mark_media_status = str(text)
        self._mark_media_status_color = str(color)
        self.markMediaChanged.emit()
        if log_color is not None:
            self._append_log(f"Калибровка: {text}", log_color)

    # ------------------------------------------------------------------ вход из калибровки

    def _mark_media_note_intent(self, mark_did: int, value: int):
        """Запоминает при отправке отметки, снята ли она по месту.

        Сравнение идёт с усреднённым захватом, а если его нет, с последним
        прочитанным периодом: именно их оператор видит в строке «Текущий» и «Захват».
        """
        reference = None
        if self._calibration_captured_available:
            reference = int(self._calibration_captured_level)
        elif int(self._calibration_current_level or 0) > 0:
            reference = int(self._calibration_current_level)

        live = reference is not None and abs(int(value) - reference) <= self.MARK_MEDIA_LIVE_TOLERANCE
        self._mark_media_intent[int(mark_did)] = {"live": live, "value": int(value), "reference": reference}

    def _mark_media_forget_intent(self, mark_did: int):
        """Отметка не прошла сверку: вид топлива к ней не пишется."""
        self._mark_media_intent.pop(int(mark_did), None)

    def _mark_media_on_mark_verified(self, mark_did: int):
        """Отметка записана и сверена: снимаем к ней показание вида топлива."""
        intent = self._mark_media_intent.pop(int(mark_did), None)
        if intent is None:
            # Отметку записал не оператор кнопкой (например, возврат копии): вид топлива не трогаем.
            return

        media_var, label = self._mark_media_target(mark_did)
        did_text = f"0x{int(media_var.pid) & 0xFFFF:04X}"

        if not intent["live"]:
            reference = intent["reference"]
            now_text = "прибор ещё не прислал показание" if reference is None else f"прибор показывает {reference}"
            self._mark_media_set_status(
                f"вид топлива для отметки {label} не записан в {did_text}: отметка {intent['value']} "
                f"введена не по месту, а {now_text}. Для модели по двум контурам снимайте отметку "
                "кнопкой захвата в том положении датчика, где она должна быть.",
                self.MARK_MEDIA_COLOR_WARN, RowColor.yellow,
            )
            return

        if self._mark_media_active:
            self._mark_media_set_status(
                f"вид топлива для отметки {label} не записан: ещё идёт запись к предыдущей отметке. "
                "Запишите отметку ещё раз через пару секунд.",
                self.MARK_MEDIA_COLOR_WARN, RowColor.yellow,
            )
            return

        self._mark_media_active = True
        self._mark_media_mark_did = int(mark_did)
        self._mark_media_samples = []
        self._mark_media_value = None
        self._mark_media_air = None
        self._mark_media_set_status(
            f"снимаю вид топлива для отметки {label}...", self.MARK_MEDIA_COLOR_IDLE)
        self._mark_media_request("sample", UdsData.fuel_media_flatcap_raw)

    # ------------------------------------------------------------------ обмен

    def _mark_media_request(self, action: str, var, value=None) -> bool:
        """Отправляет один запрос цепочки и ждёт ответа."""
        self._mark_media_pending = (action, var, value)
        try:
            if value is None:
                sent = self._mark_media_read_service.read_data_by_identifier(
                    self._build_calibration_tx_identifier(), var)
            else:
                self._mark_media_write_service.set_expected_pid(int(var.pid) & 0xFFFF)
                sent = self._mark_media_write_service.write_data(
                    var, int(value), tx_identifier=self._build_calibration_tx_identifier())
        except Exception:
            sent = False

        if not sent:
            self._mark_media_finish("вид топлива к отметке не записан: запрос не ушёл в шину.",
                                    self.MARK_MEDIA_COLOR_BAD, RowColor.red)
            return False

        self._mark_media_timeout_timer.start(self.MARK_MEDIA_TIMEOUT_MS)
        return True

    def _mark_media_finish(self, text: str, color: str, log_color):
        """Завершает цепочку любым исходом и освобождает шину."""
        self._mark_media_active = False
        self._mark_media_pending = None
        self._mark_media_samples = []
        self._mark_media_gap_timer.stop()
        self._mark_media_timeout_timer.stop()
        self._mark_media_set_status(text, color, log_color)

    def _on_mark_media_gap_timeout(self):
        if self._mark_media_active and self._mark_media_pending is None:
            self._mark_media_request("sample", UdsData.fuel_media_flatcap_raw)

    def _on_mark_media_timeout(self):
        if self._mark_media_pending is None:
            return
        _action, var, _value = self._mark_media_pending
        self._mark_media_finish(
            f"вид топлива к отметке не записан: прибор не ответил на DID 0x{int(var.pid) & 0xFFFF:04X}.",
            self.MARK_MEDIA_COLOR_BAD, RowColor.red,
        )

    def _handle_mark_media_frame(self, identifier: int, payload):
        """Разбирает ответ прибора на запрос цепочки."""
        if self._mark_media_pending is None:
            return
        if not isinstance(payload, (list, tuple)) or len(payload) < 4:
            return
        if not self._is_calibration_response_identifier(identifier):
            return
        if ((int(payload[0]) >> 4) & 0x0F) != 0x00:
            return
        body_length = int(payload[0]) & 0x0F
        if body_length < 3 or body_length > (len(payload) - 1):
            return
        body = [int(item) & 0xFF for item in payload[1:1 + body_length]]

        action, var, value = self._mark_media_pending
        is_write = action == "write"

        if body[0] == 0x7F:
            # Отказ относится к цепочке, только если он на её службу: чтение 0x22 или запись 0x2E.
            if body[1] != (0x2E if is_write else 0x22):
                return
            if len(body) > 2 and body[2] == 0x78:
                return
            self._mark_media_finish(
                f"вид топлива к отметке не записан: прибор отказал на DID 0x{int(var.pid) & 0xFFFF:04X}, "
                f"код 0x{body[2]:02X}.",
                self.MARK_MEDIA_COLOR_BAD, RowColor.red,
            )
            return

        if ((body[1] << 8) | body[2]) != (int(var.pid) & 0xFFFF):
            return

        if body[0] == 0x62 and not is_write and len(body) >= 4:
            raw = 0
            for shift, byte_value in enumerate(body[3:]):
                raw |= byte_value << (8 * shift)
            self._mark_media_timeout_timer.stop()
            self._mark_media_pending = None
            self._mark_media_on_value(action, int(raw))
            return

        if body[0] == 0x6E and is_write:
            self._mark_media_timeout_timer.stop()
            self._mark_media_pending = None
            self._mark_media_request("verify", var)

    # ------------------------------------------------------------------ шаги

    def _mark_media_on_value(self, action: str, value: int):
        media_var, label = self._mark_media_target(self._mark_media_mark_did)
        did_text = f"0x{int(media_var.pid) & 0xFFFF:04X}"

        if action == "sample":
            self._mark_media_samples.append(int(value))
            if len(self._mark_media_samples) < self.MARK_MEDIA_SAMPLES:
                self._mark_media_gap_timer.start(self.MARK_MEDIA_SAMPLE_GAP_MS)
                return

            samples = list(self._mark_media_samples)
            spread = max(samples) - min(samples)
            if spread > self.MARK_MEDIA_STABLE_SPREAD:
                self._mark_media_finish(
                    f"вид топлива для отметки {label} не записан: показание гуляло на {spread} отсч. "
                    f"при допуске {self.MARK_MEDIA_STABLE_SPREAD}. Дайте датчику успокоиться и запишите отметку ещё раз.",
                    self.MARK_MEDIA_COLOR_WARN, RowColor.yellow,
                )
                return
            average = int(round(sum(samples) / float(len(samples))))
            if average <= 0:
                self._mark_media_finish(
                    f"вид топлива для отметки {label} не записан: контур вида топлива не даёт измерения.",
                    self.MARK_MEDIA_COLOR_BAD, RowColor.red,
                )
                return
            self._mark_media_value = average
            self._mark_media_request("air", UdsData.fuel_media_flatcap_air_count)
            return

        if action == "air":
            self._mark_media_air = int(value)
            self._mark_media_request("write", media_var, self._mark_media_value)
            return

        if action == "verify":
            written = self._mark_media_value
            if int(value) != int(written):
                self._mark_media_finish(
                    f"вид топлива для отметки {label}: прибор подтвердил запись {written} в {did_text}, "
                    f"но хранит {int(value)}. Запишите отметку ещё раз.",
                    self.MARK_MEDIA_COLOR_BAD, RowColor.red,
                )
                return

            text = f"вид топлива для отметки {label} записан в {did_text}: {written} отсч."
            air = self._mark_media_air
            if air is None or air <= 0:
                self._mark_media_finish(
                    text + " Точка «воздух» (0x002F) в приборе не записана: без неё модель по двум "
                    "контурам уровень не посчитает. Снимите её в разделе «Вид топлива».",
                    self.MARK_MEDIA_COLOR_WARN, RowColor.yellow,
                )
                return
            delta = int(written) - int(air)
            if delta < self.MARK_MEDIA_MIN_DELTA:
                self._mark_media_finish(
                    text + f" Это почти показание на воздухе ({air}): плоский конденсатор в момент отметки "
                    "сухой. Прежней модели это не мешает, а модель по двум контурам в текущей прошивке "
                    "такую отметку не примет.",
                    self.MARK_MEDIA_COLOR_WARN, RowColor.yellow,
                )
                return
            self._mark_media_finish(text + f" Выше воздуха на {delta} отсч.",
                                    self.MARK_MEDIA_COLOR_OK, RowColor.green)
