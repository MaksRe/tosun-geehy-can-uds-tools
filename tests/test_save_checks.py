"""Проверки того, что записанное действительно сохранилось в приборе.

Прибор отвечает «запись выполнена», как только принял значение в оперативную
память, а в микросхему памяти оно уходит позже. Программа, поверившая одному
ответу, покажет успех там, где после выключения прибор вернёт прежнее значение.

Здесь закреплены все звенья проверки: ожидание записи в микросхему после любой
записи, сверка прочитанного с записанным в мастере вида топлива и в окне
параметров, сверка профиля сразу после его записи.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller.eeprom_commit_mixin import (
    AppControllerEepromCommitMixin,
    decode_eeprom_state,
    eeprom_boot_warning,
)
from ui.qml.controller.calibration_mixin import AppControllerCalibrationMixin
from ui.qml.controller.media_wizard_mixin import AppControllerMediaWizardMixin
from ui.qml.controller.options_mixin import AppControllerOptionsMixin
from ui.qml.controller.profile_mixin import AppControllerProfileMixin
from uds.data_identifiers import UdsData


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _FakeTimer:
    def start(self, *args):
        pass

    def stop(self):
        pass

    def isActive(self):
        return False


class _FakeRead:
    def __init__(self):
        self.sent = []

    def read_data_by_identifier(self, identifier, var):
        self.sent.append(int(var.pid))
        return True


class _FakeCan:
    is_connect = True
    is_trace = True


# ------------------------------------------------------------------ ожидание записи в микросхему

class _WatchStub(AppControllerEepromCommitMixin):
    def __init__(self):
        self.eepromCommitChanged = _Signal()
        self.infoMessage = _Signal()
        self._can = _FakeCan()
        self._eeprom_commit_read = _FakeRead()
        self._eeprom_commit_node = 0x2A
        self._eeprom_commit_reset()

        self._options_busy = False
        self._options_bulk_busy = False
        self._profile_busy = False
        self._chamber_busy = False
        self._trial_busy = False
        self._media_wizard_busy = False
        self._programming_active = False
        self._source_address_busy = False
        self._calibration_sequence_waiting_action = ""
        self._calibration_write_verify_pending = {}
        self._calibration_active = True
        self._calibration_session_ready = True

    def _is_calibration_response_identifier(self, identifier):
        return True

    def _build_calibration_tx_identifier(self):
        return 0x18DA2AF1

    def _resolve_calibration_target_sa(self):
        return 0x2A


def _write_ok(stub, did=0x0012):
    stub._handle_eeprom_commit_frame(0x18DAF12A, [0x03, 0x6E, (did >> 8) & 0xFF, did & 0xFF, 0, 0, 0, 0])


def _state(stub, pending=0, flags=0, damaged=0, errors=0):
    stub._handle_eeprom_commit_frame(0x18DAF12A, [0x07, 0x62, 0x00, 0x63, pending, flags, damaged, errors])


def test_state_bytes_are_decoded():
    assert decode_eeprom_state([2, 0x04, 1, 7]) == {"pending": 2, "flags": 4, "damaged": 1, "errors": 7}
    assert decode_eeprom_state([1, 2]) is None


def test_confirmed_write_is_saved_only_after_the_chip_is_written():
    """Ответ на запись это только оперативная память: «сохранено» появляется после микросхемы."""
    stub = _WatchStub()
    _state(stub)  # исходное состояние, счётчик ошибок 0
    _write_ok(stub)
    assert stub._eeprom_commit_phase == "saving"

    stub._on_eeprom_commit_tick()
    assert stub._eeprom_commit_read.sent == [0x0063]

    _state(stub, pending=2)
    assert stub._eeprom_commit_phase == "saving"
    assert "осталось параметров: 2" in stub._eeprom_commit_view()["text"]

    _state(stub, pending=0)
    view = stub._eeprom_commit_view()
    assert stub._eeprom_commit_phase == "saved"
    assert view["color"] == stub.EEPROM_COLOR_OK


def test_ram_only_write_does_not_wait_for_the_chip():
    stub = _WatchStub()
    _write_ok(stub, did=0x0061)
    assert stub._eeprom_commit_phase == "idle"


def test_watch_stays_off_the_bus_while_another_section_writes():
    """Посторонний запрос оборвал бы длинную запись, а ожидание не должно истечь из-за чужой работы."""
    stub = _WatchStub()
    _write_ok(stub)
    stub._options_busy = True
    stub._eeprom_commit_deadline = time.monotonic() - 1.0
    stub._on_eeprom_commit_tick()
    assert stub._eeprom_commit_read.sent == []
    assert stub._eeprom_commit_deadline > time.monotonic()
    assert stub._eeprom_commit_phase == "saving"


def test_write_that_never_reaches_the_chip_is_reported():
    stub = _WatchStub()
    _write_ok(stub)
    _state(stub, pending=1)
    stub._eeprom_commit_deadline = time.monotonic() - 1.0
    stub._on_eeprom_commit_tick()
    assert stub._eeprom_commit_phase == "failed"
    assert stub._eeprom_commit_view()["color"] == stub.EEPROM_COLOR_FAIL


def test_chip_error_is_a_failure():
    stub = _WatchStub()
    _write_ok(stub)
    _state(stub, flags=0x01)
    assert stub._eeprom_commit_phase == "failed"
    assert "не отвечает" in stub._eeprom_commit_detail


def test_repeated_chip_writes_are_a_warning():
    stub = _WatchStub()
    _state(stub, errors=1)
    _write_ok(stub)
    _state(stub, errors=4)
    assert stub._eeprom_commit_phase == "saved"
    assert stub._eeprom_commit_view()["color"] == stub.EEPROM_COLOR_WARN
    assert "повторов: 3" in stub._eeprom_commit_detail


def test_old_firmware_without_the_state_is_named():
    stub = _WatchStub()
    _write_ok(stub)
    stub._on_eeprom_commit_tick()
    stub._handle_eeprom_commit_frame(0x18DAF12A, [0x03, 0x7F, 0x22, 0x31, 0, 0, 0, 0])
    assert stub._eeprom_commit_phase == "unsupported"
    assert "перезагрузкой" in stub._eeprom_commit_detail


def test_memory_reset_at_power_on_is_shown_once_and_loudly():
    stub = _WatchStub()
    _state(stub, flags=0x04, damaged=3)
    _state(stub, flags=0x04, damaged=3)
    view = stub._eeprom_commit_view()
    assert view["color"] == stub.EEPROM_COLOR_FAIL
    assert "сбросил их к заводским: 3" in view["text"]
    assert len(stub.infoMessage.calls) == 1


def test_full_reset_warning_asks_for_a_new_calibration():
    assert "заново" in eeprom_boot_warning({"pending": 0, "flags": 0x08, "damaged": 0, "errors": 0})


def test_device_reset_forgets_the_old_state():
    stub = _WatchStub()
    _state(stub, flags=0x04, damaged=1)
    stub._handle_eeprom_commit_frame(0x18DAF12A, [0x02, 0x51, 0x03, 0, 0, 0, 0, 0])
    assert stub._eeprom_commit_state is None
    assert stub._eeprom_commit_phase == "idle"


def test_state_is_probed_once_the_calibration_session_opens():
    stub = _WatchStub()
    stub._on_eeprom_commit_tick()
    assert stub._eeprom_commit_read.sent == [0x0063]
    _state(stub)
    stub._on_eeprom_commit_tick()
    assert stub._eeprom_commit_read.sent == [0x0063]


def test_changing_the_device_forgets_the_state():
    stub = _WatchStub()
    _state(stub, errors=5)
    stub._resolve_calibration_target_sa = lambda: 0x2B
    stub._calibration_active = False
    stub._on_eeprom_commit_tick()
    assert stub._eeprom_commit_state is None


# ------------------------------------------------------------------ мастер вида топлива

class _WizardStub(AppControllerMediaWizardMixin):
    def __init__(self):
        self.mediaWizardChanged = _Signal()
        self._media_wizard_busy = True
        self._media_wizard_action = "air"
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
        self.requests = []

    def _media_wizard_request(self, action, var, value=None):
        self.requests.append(action)
        return True


def test_wizard_reports_a_value_that_did_not_stick():
    """Раньше мастер писал «сохранена», даже если прибор вернул другое число."""
    stub = _WizardStub()
    stub._media_wizard_on_write_confirmed("write_air", UdsData.fuel_media_flatcap_air_count, 2380)
    assert stub.requests == ["verify_air"]

    stub._media_wizard_on_verified("verify_air", 2375)
    assert stub._media_wizard_status_color == stub.MEDIA_WIZARD_COLOR_BAD
    assert "хранит 2375" in stub._media_wizard_status
    assert stub._media_wizard_air is None


def test_wizard_accepts_the_value_it_wrote():
    stub = _WizardStub()
    stub._media_wizard_on_write_confirmed("write_air", UdsData.fuel_media_flatcap_air_count, 2380)
    stub._media_wizard_on_verified("verify_air", 2380)
    assert stub._media_wizard_status_color == stub.MEDIA_WIZARD_COLOR_OK
    assert stub._media_wizard_air == 2380


# ------------------------------------------------------------------ профиль

class _ProfileStub(AppControllerProfileMixin):
    def __init__(self):
        self.profileChanged = _Signal()
        self._options_busy = False
        self._init_profile_state()
        self.reads = []
        self.writes = []
        self._start_options_read_request = (
            lambda parameter, request_origin, append_history: self.reads.append(request_origin) or True)
        self._start_options_write_multiframe_request = (
            lambda parameter, payload, request_origin, append_history: self.writes.append(request_origin) or True)


def _finish_profile_queue(stub, action):
    # Только текущая очередь: сверка, запущенная после записи, приходит новой очередью.
    for _step in range(len(stub._profile_queue)):
        name = stub._profile_queue[0][0]
        stub._handle_profile_options_result(
            success=True, request_origin=f"profile_{name}", pending_action=action,
            pending_did=0x004B, value_bytes=bytes(28), message="ok")
        stub._on_profile_step_timeout()


def test_profile_is_read_back_right_after_it_is_written():
    """Подтверждение приёма каждой таблицы не значит, что в приборе лежит записанное."""
    stub = _ProfileStub()
    stub._profile_values["board_main"][0] = 5
    assert stub._profile_write_to_device()
    _finish_profile_queue(stub, "write")

    assert stub._profile_verify is not None
    assert stub.reads and stub.reads[0] == "profile_nodes"
    assert stub._profile_busy


def test_caller_that_verifies_itself_can_skip_the_read_back():
    stub = _ProfileStub()
    stub._profile_values["board_main"][0] = 5
    assert stub._profile_write_to_device(verify=False)
    _finish_profile_queue(stub, "write")

    assert stub.reads == []
    assert stub._profile_status == "Готово."


# ------------------------------------------------------------------ окно параметров

def test_option_read_back_must_match_what_was_written():
    match = AppControllerOptionsMixin._options_stored_matches_written
    assert match(b"\x34\x12", b"\x34\x12")
    assert not match(b"\x34\x12", b"\x35\x12")
    assert match(b"AB", b"AB\x00\x00")
    assert not match(b"AB", b"ABC")
    assert not match(b"\x34\x12", b"\x34")


# ------------------------------------------------------------------ восстановление из резервной копии

def test_dump_restore_writes_marks_in_an_order_the_device_accepts():
    """Прибор отвергает 0 %, не ниже текущей 100 %: восстановление остановилось бы на первой записи."""
    order = AppControllerCalibrationMixin._calibration_restore_order
    empty, full = int(UdsData.empty_fuel_tank.pid), int(UdsData.full_fuel_tank.pid)
    assert [did for did, _value in order(12000, 16000, 9600)] == [full, empty]
    assert [did for did, _value in order(4800, 9600, 16000)] == [empty, full]
    assert [did for did, _value in order(4800, 9600, None)] == [empty, full]
