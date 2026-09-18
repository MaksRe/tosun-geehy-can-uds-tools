"""Проверки очерёдности обмена с прибором.

Прибор держит один канал ISO-TP: запрос, пришедший раньше ответа на прежний,
затирает его. На пробной калибровке так опрос текущего периода раз в секунду
затёр запрос замера точки. Фоновые опросы обязаны уступать шину разделам,
которые ведут обмен, и не слать запросы вплотную друг к другу.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller.bus_guard import background_request_recent, note_background_request, uds_exchange_busy
from ui.qml.controller.calibration_mixin import AppControllerCalibrationMixin


class _Ctrl:
    pass


class _FakeCan:
    is_connect = True
    is_trace = True


def test_free_bus_names_nobody():
    assert uds_exchange_busy(_Ctrl()) == ""


def test_busy_section_is_named_and_can_be_ignored():
    ctrl = _Ctrl()
    ctrl._chamber_busy = True
    assert uds_exchange_busy(ctrl) == "chamber"
    assert uds_exchange_busy(ctrl, ignore=("chamber",)) == ""


def test_live_media_request_in_flight_occupies_the_bus():
    ctrl = _Ctrl()
    ctrl._media_wizard_pending = ("watch", None, None)
    assert uds_exchange_busy(ctrl) == "media_wizard"


def test_calibration_write_check_occupies_the_bus():
    ctrl = _Ctrl()
    ctrl._calibration_write_verify_pending = {0x0012: 4820}
    assert uds_exchange_busy(ctrl) == "calibration"


def test_background_requests_keep_a_gap():
    ctrl = _Ctrl()
    assert not background_request_recent(ctrl)
    note_background_request(ctrl)
    assert background_request_recent(ctrl)
    ctrl._uds_background_tx_s = time.monotonic() - 1.0
    assert not background_request_recent(ctrl)


class _FakeTimer:
    """Таймер опроса без Qt: помнит, на сколько назначена следующая попытка."""

    def __init__(self):
        self.active = False
        self.delay = None

    def setSingleShot(self, value):
        pass

    def isActive(self):
        return self.active

    def start(self, delay=None):
        self.active = True
        self.delay = None if delay is None else int(delay)

    def stop(self):
        self.active = False


class _PollStub(AppControllerCalibrationMixin):
    def __init__(self):
        self._calibration_active = True
        self._can = _FakeCan()
        self._source_address_busy = False
        self._programming_active = False
        self._chamber_busy = False
        self._calibration_poll_interval_ms = 1000
        self._calibration_poll_timer = _FakeTimer()
        self._calibration_write_verify_pending = {}
        self._calibration_write_verify_sent_s = {}
        self._calibration_restore_active = False
        self._calibration_dump_capture_active = False
        self._calibration_sequence_waiting_action = ""
        self.polls = 0
        self.verify_reads = []
        self.logs = []

    def _request_calibration_runtime_snapshot(self):
        self.polls += 1

    def _request_calibration_write_verify_read(self, did):
        self.verify_reads.append(int(did))

    def _stop_calibration_poll_timer(self):
        pass

    def _append_log(self, text, color):
        self.logs.append(text)

    def _mark_media_forget_intent(self, did):
        pass

    def _recompute_calibration_wizard_state(self):
        pass

    def _calibration_did_label(self, did):
        return f"DID 0x{int(did):04X}"

    calibrationVerificationChanged = type("_Sig", (), {"emit": lambda self: None})()


def test_calibration_poll_yields_to_a_point_capture():
    """Этот опрос и затёр запрос замера на столе: пока идёт замер, он молчит."""
    stub = _PollStub()
    stub._chamber_busy = True
    stub._on_calibration_poll_tick()
    assert stub.polls == 0

    stub._chamber_busy = False
    stub._on_calibration_poll_tick()
    assert stub.polls == 1

    # Сразу следующий фоновый запрос не уходит: ответ на прежний ещё в пути.
    stub._on_calibration_poll_tick()
    assert stub.polls == 1


def test_busy_bus_costs_a_short_pause_and_not_a_whole_period():
    """Из-за потери целого периода опрос основного контура замирал на десятки секунд.

    Два строго периодических опроса совпадают по фазе, чужой запрос каждый раз
    уходит за мгновение до нашего, и очередь до основного контура не доходит.
    Поэтому занятая шина стоит короткой паузы, а не всего периода.
    """
    stub = _PollStub()
    stub._chamber_busy = True
    stub._on_calibration_poll_tick()
    assert stub._calibration_poll_timer.delay == stub.CALIBRATION_POLL_RETRY_MS
    assert stub._calibration_poll_timer.delay < stub._calibration_poll_interval_ms

    stub._chamber_busy = False
    stub._on_calibration_poll_tick()
    assert stub.polls == 1
    assert stub._calibration_poll_timer.delay == stub._calibration_poll_interval_ms


def test_written_value_is_read_back_by_the_poll_itself():
    """Раньше записанное значение никто не перечитывал, и ожидание держало шину."""
    stub = _PollStub()
    stub._note_calibration_write_verify(0x0013, 12130)
    stub._on_calibration_poll_tick()

    assert stub.verify_reads == [0x0013]
    assert stub.polls == 0, "пока значение не сверено, обычный опрос ждёт"


def test_lost_confirmation_does_not_block_the_bus_forever():
    """Потерянный ответ не должен останавливать опрос всех разделов насовсем."""
    stub = _PollStub()
    stub._note_calibration_write_verify(0x0013, 12130)
    assert uds_exchange_busy(stub) == "calibration"

    # Ответ так и не пришёл: ожидание старше своего срока.
    stub._calibration_write_verify_sent_s[0x0013] = time.monotonic() - stub.CALIBRATION_VERIFY_WAIT_S - 1.0
    stub._on_calibration_poll_tick()

    assert stub._calibration_write_verify_pending == {}
    assert uds_exchange_busy(stub) == ""
    assert any("не получено" in text for text in stub.logs)
