"""Проверки индикатора свежести живых чисел.

На плате число в окне стояло на месте, и было непонятно: прибор не отвечает,
отвечает тем же числом или сам контур перестал мерить. Период в 0x0014
фильтрованный и при остановке контура застывает, поэтому по одному числу этого
не узнать.

Тесты закрепляют: три случая называются по-разному; возраст измерения из 0x0064
разбирается младшим байтом вперёд; опрос изредка спрашивает его вместо числа;
прошивка без 0x0064 не ломает опрос, а после трёх запросов без ответа его больше
не спрашивают.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller import live_freshness_mixin as lf
from ui.qml.controller.calibration_mixin import AppControllerCalibrationMixin
from ui.qml.controller.media_wizard_mixin import AppControllerMediaWizardMixin
from uds.data_identifiers import UdsData

RX_ID = 0x18DAF16A
DID_LEVEL = int(UdsData.curr_fuel_tank.pid)
DID_AGE = int(UdsData.measurement_age.pid)
DID_FLATCAP = int(UdsData.fuel_media_flatcap_raw.pid)


class _Signal:
    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _FakeTimer:
    def __init__(self):
        self.running = False

    def start(self, interval=None):
        self.running = True

    def stop(self):
        self.running = False


# ------------------------------------------------------------------ тексты

def test_three_cases_read_differently():
    track = lf.LiveTrack()
    assert lf.response_view(track, 100.0, 1.0) == (lf.COLOR_IDLE, "ответов ещё не было")

    track.update(12128, 100.0)
    color, text = lf.response_view(track, 100.4, 1.0)
    assert color == lf.COLOR_OK and text == "ответ 0,4 с назад"

    color, text = lf.response_view(track, 104.0, 1.0)
    assert color == lf.COLOR_WARN, "опрос запаздывает, но ответ ещё не потерян"

    color, text = lf.response_view(track, 115.0, 1.0)
    assert color == lf.COLOR_BAD and text == "нет ответа 15 с"


def test_same_number_is_named_only_while_answers_arrive():
    track = lf.LiveTrack()
    for second in range(0, 26):
        track.update(12128, 100.0 + second)
    color, text = lf.response_view(track, 125.5, 1.0)
    assert color == lf.COLOR_OK
    assert "число то же 25 с" in text

    track.update(12130, 126.0)
    assert "то же" not in lf.response_view(track, 126.5, 1.0)[1], "число изменилось, отсчёт заново"


def test_device_side_view():
    assert lf.device_view(None, None, False, 10.0)[1] == "прошивка не сообщает, мерит ли контур"
    assert lf.device_view(None, None, None, 10.0)[0] == lf.COLOR_IDLE
    assert lf.device_view(180, 9.5, True, 10.0) == (lf.COLOR_OK, "контур мерит")

    color, text = lf.device_view(3400, 9.0, True, 10.0)
    assert color == lf.COLOR_BAD and text == "контур не мерит 4,4 с"

    assert lf.device_view(0xFFFF, 9.0, True, 10.0) == (lf.COLOR_BAD, "контур не мерит больше 65 с")
    assert lf.device_view(180, 0.0, True, 30.0)[0] == lf.COLOR_IDLE, "старые сведения о контуре не выдаются за свежие"


# ------------------------------------------------------------------ учёт в контроллере

class _FreshStub(lf.AppControllerLiveFreshnessMixin):
    def __init__(self):
        self.liveFreshnessChanged = _Signal()
        self._live_tracks = {"level": lf.LiveTrack(), "flatcap": lf.LiveTrack()}
        self._live_age = {"main_ms": None, "media_ms": None, "received_s": None, "supported": None, "misses": 0}
        self._live_age_counters = {"level": 0, "flatcap": 0}

    def _is_calibration_response_identifier(self, identifier):
        return identifier == RX_ID


def test_age_answer_is_parsed_little_endian():
    stub = _FreshStub()
    stub._handle_live_age_frame(RX_ID, [0x07, 0x62, 0x00, 0x64, 0xB4, 0x00, 0x88, 0x13])

    assert stub._live_age["main_ms"] == 180
    assert stub._live_age["media_ms"] == 5000
    assert stub._live_age["supported"] is True
    assert stub._live_freshness_view("level", 1.0)["deviceText"] == "контур мерит"
    assert stub._live_freshness_view("flatcap", 0.25)["deviceColor"] == lf.COLOR_BAD


def test_foreign_frames_are_ignored():
    stub = _FreshStub()
    stub._handle_live_age_frame(RX_ID, [0x05, 0x62, 0x00, 0x14, 0x60, 0x2F, 0, 0])
    stub._handle_live_age_frame(0x18DAF199, [0x07, 0x62, 0x00, 0x64, 0, 0, 0, 0])
    assert stub._live_age["received_s"] is None


def test_firmware_without_age_is_asked_three_times_only():
    stub = _FreshStub()
    for _ in range(lf.DEVICE_AGE_MISSES_LIMIT):
        stub._live_age_note_request()
    assert stub._live_age["supported"] is False
    assert not any(stub._live_age_due("level") for _ in range(20))

    # Ответ всё же пришёл: значит, прошивка знает возраст.
    stub._handle_live_age_frame(RX_ID, [0x07, 0x62, 0x00, 0x64, 0x10, 0x00, 0x10, 0x00])
    assert stub._live_age["supported"] is True and stub._live_age["misses"] == 0


def test_refresh_tick_runs_only_when_there_is_something_to_age():
    stub = _FreshStub()
    stub._on_live_freshness_tick()
    assert stub.liveFreshnessChanged.count == 0
    stub._live_note_value("level", 12128)
    stub._on_live_freshness_tick()
    assert stub.liveFreshnessChanged.count == 1


# ------------------------------------------------------------------ опросы разделов

class _FakeCan:
    is_connect = True
    is_trace = True


class _FakeRead:
    def __init__(self):
        self.dids = []

    def read_data_by_identifier(self, tx_identifier, var):
        self.dids.append(int(var.pid) & 0xFFFF)
        return True


class _LevelPollStub(AppControllerCalibrationMixin, _FreshStub):
    def __init__(self):
        _FreshStub.__init__(self)
        self._can = _FakeCan()
        self._calibration_read_service = _FakeRead()

    def _configure_calibration_uds_services(self):
        pass

    def _build_calibration_tx_identifier(self):
        return 0x18DA6AF1


def test_level_poll_asks_the_age_every_fourth_time():
    stub = _LevelPollStub()
    for _ in range(8):
        stub._request_calibration_runtime_snapshot()
    assert stub._calibration_read_service.dids == [DID_LEVEL, DID_LEVEL, DID_LEVEL, DID_AGE] * 2

    stub._live_age["supported"] = False
    stub._calibration_read_service.dids.clear()
    for _ in range(8):
        stub._request_calibration_runtime_snapshot()
    assert stub._calibration_read_service.dids == [DID_LEVEL] * 8, "без 0x0064 опрос читает только число"


class _WatchStub(AppControllerMediaWizardMixin, _FreshStub):
    def __init__(self):
        _FreshStub.__init__(self)
        self.mediaWizardChanged = _Signal()
        self._media_wizard_watching = True
        self._media_wizard_busy = False
        self._media_wizard_action = ""
        self._media_wizard_status = ""
        self._media_wizard_status_color = ""
        self._media_wizard_pending = None
        self._media_wizard_live_raw = None
        self._media_wizard_recent = []
        self._media_wizard_captured = None
        self._media_wizard_captured_spread = None
        self._media_wizard_gap_timer = _FakeTimer()
        self._media_wizard_timeout_timer = _FakeTimer()
        self.requests = []

    def _media_wizard_request(self, action, var, value=None):
        self.requests.append((action, int(var.pid) & 0xFFFF))
        self._media_wizard_pending = (action, var, value)
        return True


def test_watch_keeps_going_when_old_firmware_refuses_the_age():
    stub = _WatchStub()
    stub._live_age_counters["flatcap"] = stub.LIVE_AGE_EVERY["flatcap"] - 1
    stub._on_media_wizard_gap_timeout()
    assert stub.requests[-1] == ("age", DID_AGE)

    stub._handle_media_wizard_frame(RX_ID, [0x03, 0x7F, 0x22, 0x31, 0, 0, 0, 0])
    assert stub._media_wizard_watching is True, "отказ на возраст не выключает живое показание"
    assert stub._media_wizard_gap_timer.running


def test_watch_notes_each_flatcap_answer():
    stub = _WatchStub()
    stub._on_media_wizard_gap_timeout()
    assert stub.requests[-1] == ("watch", DID_FLATCAP)
    stub._handle_media_wizard_frame(RX_ID, [0x05, 0x62, 0x00, 0x36, 0x4C, 0x09, 0, 0])
    assert stub._live_tracks["flatcap"].value == 2380
    assert stub._media_wizard_gap_timer.running
