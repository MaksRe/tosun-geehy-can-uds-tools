"""Проверки мастера калибровки контура вида топлива.

Живое показание плоского конденсатора и его среднее за несколько секунд это
единственный способ понять, что конденсатор погружён и число устоялось. Точка
записывается так же, как отметка основного контура: захват переносится в поле и
сохраняется, записанное сверяется чтением.

Тесты закрепляют: захват это скользящее среднее, как у основного контура; точка
пишется из поля, а без него текущее показание; точка «топливо» не ниже точки
«воздух» не пишется; опрос плоского конденсатора идёт вместе с основным
контуром и не замирает после неудачной записи.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller.calibration_mixin import AppControllerCalibrationMixin
from ui.qml.controller.media_wizard_mixin import AppControllerMediaWizardMixin
from uds.data_identifiers import UdsData

DID_AIR = int(UdsData.fuel_media_flatcap_air_count.pid) & 0xFFFF
DID_CAL = int(UdsData.fuel_media_flatcap_cal_count.pid) & 0xFFFF
DID_FLATCAP = int(UdsData.fuel_media_flatcap_raw.pid) & 0xFFFF
RX_ID = 0x18DAF16A


class _Signal:
    """Заглушка сигнала Qt: считает вызовы вместо реальной рассылки."""

    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _FakeTimer:
    """Таймер Qt без Qt: помнит, запущен ли он и с каким интервалом."""

    def __init__(self):
        self.running = False
        self.interval = None

    def start(self, interval=None):
        self.running = True
        self.interval = interval

    def stop(self):
        self.running = False


class _WizardStub(AppControllerMediaWizardMixin):
    """Логика мастера без Qt и без CAN: запросы только записываются."""

    def __init__(self):
        self.mediaWizardChanged = _Signal()
        self.capacitanceChanged = _Signal()
        self._media_wizard_watching = False
        self._media_wizard_busy = False
        self._media_wizard_action = ""
        self._media_wizard_status = ""
        self._media_wizard_status_color = ""
        self._media_wizard_pending = None
        self._media_wizard_live_raw = None
        self._media_wizard_recent = []
        self._media_wizard_captured = None
        self._media_wizard_captured_spread = None
        self._media_wizard_air = None
        self._media_wizard_cal = None
        self._media_wizard_enabled = None
        self._media_wizard_written = None
        self._media_wizard_gap_timer = _FakeTimer()
        self._media_wizard_timeout_timer = _FakeTimer()
        # Калибровка запущена: иначе мастер не пустит к записи точки.
        self._calibration_active = True
        self._calibration_session_ready = True
        self.requests = []

    def _media_wizard_request(self, action, var, value=None):
        self.requests.append((action, int(var.pid) & 0xFFFF, value))
        self._media_wizard_pending = (action, var, value)
        return True

    def _calibration_log_event(self, text):
        """Журнала калибровки в заглушке нет: событие никуда не пишется."""

    def _is_calibration_response_identifier(self, identifier):
        return identifier == RX_ID

    # Учёт свежести проверяется отдельно, здесь он не мешает.
    def _live_note_value(self, key, value):
        pass

    def _live_age_due(self, key):
        return False


def _frame(body):
    return [len(body)] + list(body) + [0x00] * (7 - len(body))


def _u16(value):
    return [value & 0xFF, (value >> 8) & 0xFF]


# ------------------------------------------------------------------ захват

def test_capture_is_a_moving_average_like_the_main_circuit():
    stub = _WizardStub()
    stub._media_wizard_note_sample(2380, now=100.0)
    assert stub._media_wizard_captured is None, "по одному показанию среднего ещё нет"

    stub._media_wizard_note_sample(2384, now=101.0)
    assert stub._media_wizard_captured == 2382
    assert stub._media_wizard_captured_spread == 4

    # Прошло больше окна: старые показания выпали, одного нового для среднего мало.
    stub._media_wizard_note_sample(2500, now=106.0)
    assert stub._media_wizard_captured is None


def test_every_live_answer_feeds_the_capture():
    stub = _WizardStub()
    stub._media_wizard_watching = True
    for value in (2380, 2384):
        # Ответ пришёл сразу: пауза между фоновыми запросами уже прошла.
        stub._uds_background_tx_s = 0.0
        stub._on_media_wizard_gap_timeout()
        assert stub.requests[-1] == ("watch", DID_FLATCAP, None)
        stub._handle_media_wizard_frame(RX_ID, _frame([0x62, 0x00, 0x36] + _u16(value)))

    assert stub._media_wizard_live_raw == 2384
    assert stub._media_wizard_captured == 2382


# ------------------------------------------------------------------ запись точки

def test_point_is_saved_from_the_field_and_verified():
    stub = _WizardStub()
    stub._media_wizard_save("air", "2382")
    assert stub.requests[-1] == ("write_air", DID_AIR, 2382)
    assert stub._media_wizard_busy is True

    stub._handle_media_wizard_frame(RX_ID, _frame([0x6E, 0x00, 0x2F]))
    assert stub.requests[-1] == ("verify_air", DID_AIR, None)
    stub._handle_media_wizard_frame(RX_ID, _frame([0x62, 0x00, 0x2F] + _u16(2382)))

    assert stub._media_wizard_busy is False
    assert stub._media_wizard_air == 2382
    assert stub._media_wizard_status_color == stub.MEDIA_WIZARD_COLOR_OK
    assert "2382" in stub._media_wizard_status


def test_empty_field_saves_the_current_reading():
    stub = _WizardStub()
    stub._media_wizard_save("air", "")
    assert stub.requests == [], "без показания записывать нечего"
    assert "ещё нет" in stub._media_wizard_status

    stub._media_wizard_live_raw = 2390
    stub._media_wizard_save("air", "")
    assert stub.requests[-1] == ("write_air", DID_AIR, 2390)


def test_fuel_point_must_be_above_the_air_point():
    stub = _WizardStub()
    stub._media_wizard_air = 2380
    stub._media_wizard_save("liquid", "2300")
    assert stub.requests == []
    assert stub._media_wizard_status_color == stub.MEDIA_WIZARD_COLOR_BAD

    stub._media_wizard_save("liquid", "3610")
    assert stub.requests[-1] == ("write_cal", DID_CAL, 3610)


def test_point_is_not_saved_without_write_access():
    stub = _WizardStub()
    stub._calibration_active = False
    stub._media_wizard_save("air", "2382")
    assert stub.requests == []
    assert "Начать калибровку" in stub._media_wizard_status


# ------------------------------------------------------------------ живое показание

def test_live_readings_continue_after_a_failed_point():
    """Неудачная запись точки не должна останавливать обновление отсчётов."""
    stub = _WizardStub()
    stub._media_wizard_watching = True
    stub._media_wizard_save("air", "2382")
    stub._on_media_wizard_timeout()

    assert stub._media_wizard_busy is False
    assert "не ответил" in stub._media_wizard_status
    assert stub._media_wizard_gap_timer.running, "живое показание обязано продолжиться"
    assert stub._media_wizard_gap_timer.interval == stub.MEDIA_WIZARD_WATCH_GAP_MS


def test_live_watch_stays_silent_while_a_point_is_written():
    stub = _WizardStub()
    stub._media_wizard_watching = True
    stub._media_wizard_busy = True
    stub._on_media_wizard_gap_timeout()
    assert stub.requests == []


def test_live_readings_stay_stopped_when_calibration_is_not_running():
    stub = _WizardStub()
    stub._media_wizard_watching = False
    stub._media_wizard_busy = True
    stub._media_wizard_finish("Готово.", stub.MEDIA_WIZARD_COLOR_OK)

    assert stub._media_wizard_gap_timer.running is False


class _FakeCan:
    is_connect = True
    is_trace = True


class _PollTimer:
    """Таймер опроса калибровки без Qt."""

    def __init__(self):
        self.active = False
        self._interval = 0

    def interval(self):
        return self._interval

    def setInterval(self, value):
        self._interval = value

    def isActive(self):
        return self.active

    def start(self):
        self.active = True

    def stop(self):
        self.active = False


class _CalibrationWatchStub(AppControllerCalibrationMixin, _WizardStub):
    def __init__(self):
        _WizardStub.__init__(self)
        self._can = _FakeCan()
        self._calibration_poll_timer = _PollTimer()
        self._calibration_poll_interval_ms = 1000


def test_flatcap_is_polled_together_with_the_main_circuit():
    """Отдельной кнопки нет: опрос плоского конденсатора идёт, пока идёт опрос основного контура."""
    stub = _CalibrationWatchStub()
    stub._start_calibration_poll_timer()
    assert stub._calibration_poll_timer.active and stub._media_wizard_watching
    assert stub.requests == [], "первый запрос ждёт паузу, чтобы не столкнуться с чтением основного контура"
    assert stub._media_wizard_gap_timer.interval == stub.MEDIA_WIZARD_WATCH_START_MS

    stub._stop_calibration_poll_timer()
    assert not stub._calibration_poll_timer.active
    assert stub._media_wizard_watching is False
    assert stub._media_wizard_gap_timer.running is False


def test_flatcap_watch_and_capture_use_the_main_circuit_settings():
    stub = _CalibrationWatchStub()
    stub._calibration_poll_interval_ms = 700
    stub._calibration_recent_window_sec = 2.0
    stub._media_wizard_watching = True
    stub._media_wizard_busy = True
    stub._media_wizard_finish("Готово.", stub.MEDIA_WIZARD_COLOR_OK)
    assert stub._media_wizard_gap_timer.interval == 700
    assert stub._media_wizard_capture_window_s() == 2.0


def test_resumed_watch_asks_the_device_again():
    """После паузы наблюдение шлёт очередной запрос, а не молчит."""
    stub = _WizardStub()
    stub._media_wizard_watching = True
    stub._media_wizard_busy = True
    stub._media_wizard_finish("Прибор отказал.", stub.MEDIA_WIZARD_COLOR_BAD)
    stub.requests.clear()

    stub._on_media_wizard_gap_timeout()

    assert stub.requests == [("watch", DID_FLATCAP, None)]
