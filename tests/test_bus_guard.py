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


class _PollStub(AppControllerCalibrationMixin):
    def __init__(self):
        self._calibration_active = True
        self._can = _FakeCan()
        self._source_address_busy = False
        self._programming_active = False
        self._chamber_busy = False
        self.polls = 0

    def _request_calibration_runtime_snapshot(self):
        self.polls += 1

    def _stop_calibration_poll_timer(self):
        pass


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
