"""Проверки записи вида топлива в момент отметок бака.

Модель уровня по двум контурам берёт из 0x0054 и 0x0055, что показывал контур
вида топлива при отметках 0 % и 100 %. Если туда попадёт показание из другого
положения датчика, модель тихо посчитает неверный уровень во всём диапазоне.

Тесты закрепляют: показание пишется только к отметке, снятой по месту; серия
обязана устояться; записанное сверяется чтением; замечания зависят от того,
какая модель уровня включена в приборе; отказ прибора останавливает цепочку, а
итог прошлой записи не висит рядом со следующей отметкой.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller.bus_guard import uds_exchange_busy
from ui.qml.controller.mark_media_mixin import AppControllerMarkMediaMixin
from uds.data_identifiers import UdsData

DID_EMPTY = int(UdsData.empty_fuel_tank.pid)
DID_FULL = int(UdsData.full_fuel_tank.pid)
DID_RAW = int(UdsData.fuel_media_flatcap_raw.pid)
DID_AIR = int(UdsData.fuel_media_flatcap_air_count.pid)
DID_MODEL = int(UdsData.fuel_tank_model.pid)
DID_ZERO_MEDIA = int(UdsData.fuel_tank_zero_media_count.pid)
DID_FULL_MEDIA = int(UdsData.fuel_tank_full_media_count.pid)

# Модель расчёта уровня в приборе: 0 прежняя, 1 по двум контурам.
MODEL_OLD = 0
MODEL_TWO_CIRCUIT = 1

RX_ID = 0x18DAF16A


class _Signal:
    """Заглушка сигнала Qt: считает вызовы вместо реальной рассылки."""

    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _FakeTimer:
    """Таймер Qt без Qt: помнит, запущен ли он."""

    def __init__(self):
        self.running = False

    def start(self, interval=None):
        self.running = True

    def stop(self):
        self.running = False


class _FakeRead:
    def __init__(self, log):
        self.log = log

    def read_data_by_identifier(self, tx_identifier, var):
        self.log.append(("read", int(var.pid) & 0xFFFF, None))
        return True


class _FakeWrite:
    def __init__(self, log):
        self.log = log

    def set_expected_pid(self, pid):
        pass

    def write_data(self, var, value, tx_identifier=None):
        self.log.append(("write", int(var.pid) & 0xFFFF, int(value)))
        return True


class _MarkStub(AppControllerMarkMediaMixin):
    """Логика модуля без Qt и без CAN: запросы только записываются."""

    def __init__(self):
        self.markMediaChanged = _Signal()
        self.requests = []
        self.logs = []
        self._mark_media_read_service = _FakeRead(self.requests)
        self._mark_media_write_service = _FakeWrite(self.requests)
        self._mark_media_intent = {}
        self._mark_media_active = False
        self._mark_media_mark_did = None
        self._mark_media_pending = None
        self._mark_media_samples = []
        self._mark_media_value = None
        self._mark_media_air = None
        self._mark_media_model = None
        self._mark_media_status = ""
        self._mark_media_status_color = ""
        self._mark_media_gap_timer = _FakeTimer()
        self._mark_media_timeout_timer = _FakeTimer()
        self._calibration_captured_available = True
        self._calibration_captured_level = 12130
        self._calibration_current_level = 12128

    def _append_log(self, text, color):
        self.logs.append(text)

    def _build_calibration_tx_identifier(self):
        return 0x18DA6AF1

    def _is_calibration_response_identifier(self, identifier):
        return identifier == RX_ID


def _frame(body):
    return [len(body)] + list(body) + [0xAA] * (7 - len(body))


def _answer_read(stub, did, value):
    stub._handle_mark_media_frame(RX_ID, _frame([0x62, did >> 8, did & 0xFF, value & 0xFF, (value >> 8) & 0xFF]))


def _answer_write(stub, did):
    stub._handle_mark_media_frame(RX_ID, _frame([0x6E, did >> 8, did & 0xFF]))


def _run_series(stub, samples):
    """Отвечает на серию чтений плоского конденсатора так, как это делает прибор."""
    for index, value in enumerate(samples):
        assert stub.requests[-1] == ("read", DID_RAW, None)
        _answer_read(stub, DID_RAW, value)
        if index < len(samples) - 1:
            assert stub._mark_media_gap_timer.running
            stub._on_mark_media_gap_timeout()


def _run_to_write(stub, media_value, air_value, model):
    """Проходит цепочку до записи: серия, точка «воздух» и модель уровня прибора."""
    _run_series(stub, [media_value] * stub.MARK_MEDIA_SAMPLES)
    assert stub.requests[-1] == ("read", DID_AIR, None)
    _answer_read(stub, DID_AIR, air_value)
    assert stub.requests[-1] == ("read", DID_MODEL, None)
    _answer_read(stub, DID_MODEL, model)


def test_mark_taken_in_place_gets_the_media_reading_and_is_verified():
    stub = _MarkStub()
    stub._mark_media_note_intent(DID_FULL, 12140)
    stub._mark_media_on_mark_verified(DID_FULL)
    assert uds_exchange_busy(stub) == "mark_media", "пока идёт цепочка, фоновые опросы молчат"

    _run_series(stub, [3600, 3602, 3599, 3601, 3603, 3601])
    assert stub.requests[-1] == ("read", DID_AIR, None)
    _answer_read(stub, DID_AIR, 2380)
    _answer_read(stub, DID_MODEL, MODEL_OLD)
    assert stub.requests[-1] == ("write", DID_FULL_MEDIA, 3601)

    _answer_write(stub, DID_FULL_MEDIA)
    assert stub.requests[-1] == ("read", DID_FULL_MEDIA, None)
    _answer_read(stub, DID_FULL_MEDIA, 3601)

    assert stub._mark_media_active is False
    assert stub._mark_media_status_color == stub.MARK_MEDIA_COLOR_OK
    assert "0x0055" in stub._mark_media_status and "3601" in stub._mark_media_status
    assert uds_exchange_busy(stub) == ""


def test_manual_mark_far_from_the_device_reading_writes_nothing():
    """Отметка, вписанная вручную не по месту, к текущему виду топлива отношения не имеет."""
    stub = _MarkStub()
    stub._calibration_captured_level = 16100
    stub._mark_media_note_intent(DID_EMPTY, 12128)
    stub._mark_media_on_mark_verified(DID_EMPTY)

    assert stub.requests == []
    assert stub._mark_media_active is False
    assert "не по месту" in stub._mark_media_status
    assert stub._mark_media_status_color == stub.MARK_MEDIA_COLOR_WARN


def test_mark_without_operator_intent_is_left_alone():
    """Возврат копии пишет отметку сам: вид топлива к ней не снимается."""
    stub = _MarkStub()
    stub._mark_media_on_mark_verified(DID_EMPTY)
    assert stub.requests == []
    assert stub._mark_media_status == ""


def test_next_mark_clears_the_previous_result():
    """Итог прошлой записи не должен висеть рядом со следующей отметкой."""
    stub = _MarkStub()
    stub._mark_media_set_status("вид топлива для отметки 0 % записан.", stub.MARK_MEDIA_COLOR_OK)
    stub._mark_media_note_intent(DID_FULL, 12130)
    assert stub._mark_media_status == ""


def test_unsettled_media_reading_is_not_written():
    stub = _MarkStub()
    stub._mark_media_note_intent(DID_FULL, 12130)
    stub._mark_media_on_mark_verified(DID_FULL)
    _run_series(stub, [3500, 3600, 3550, 3580, 3520, 3590])

    assert all(kind != "write" for kind, _did, _value in stub.requests)
    assert stub._mark_media_active is False
    assert "гуляло" in stub._mark_media_status


def test_dry_flat_capacitor_matters_only_for_the_two_circuit_model():
    """При прежней модели уровня эти числа ни на что не влияют: пугать оператора нечем."""
    stub = _MarkStub()
    stub._mark_media_note_intent(DID_EMPTY, 12128)
    stub._mark_media_on_mark_verified(DID_EMPTY)
    _run_to_write(stub, 2383, 2380, MODEL_OLD)
    assert stub.requests[-1] == ("write", DID_ZERO_MEDIA, 2383)
    _answer_write(stub, DID_ZERO_MEDIA)
    _answer_read(stub, DID_ZERO_MEDIA, 2383)

    assert stub._mark_media_status_color == stub.MARK_MEDIA_COLOR_IDLE
    assert "прежняя модель" in stub._mark_media_status
    assert "не примет" not in stub._mark_media_status


def test_dry_flat_capacitor_is_a_warning_with_the_two_circuit_model():
    stub = _MarkStub()
    stub._mark_media_note_intent(DID_EMPTY, 12128)
    stub._mark_media_on_mark_verified(DID_EMPTY)
    _run_to_write(stub, 2383, 2380, MODEL_TWO_CIRCUIT)
    _answer_write(stub, DID_ZERO_MEDIA)
    _answer_read(stub, DID_ZERO_MEDIA, 2383)

    assert stub._mark_media_status_color == stub.MARK_MEDIA_COLOR_WARN
    assert "не примет" in stub._mark_media_status


def test_firmware_without_the_model_parameter_still_writes():
    """Старая прошивка не знает 0x0053: запись идёт, а модель считается прежней."""
    stub = _MarkStub()
    stub._mark_media_note_intent(DID_FULL, 12130)
    stub._mark_media_on_mark_verified(DID_FULL)
    _run_series(stub, [3600] * stub.MARK_MEDIA_SAMPLES)
    _answer_read(stub, DID_AIR, 2380)
    assert stub.requests[-1] == ("read", DID_MODEL, None)

    stub._handle_mark_media_frame(RX_ID, _frame([0x7F, 0x22, 0x31]))
    assert stub.requests[-1] == ("write", DID_FULL_MEDIA, 3600)
    assert stub._mark_media_active is True


def test_value_the_device_did_not_keep_is_reported():
    stub = _MarkStub()
    stub._mark_media_note_intent(DID_FULL, 12130)
    stub._mark_media_on_mark_verified(DID_FULL)
    _run_to_write(stub, 3600, 2380, MODEL_OLD)
    _answer_write(stub, DID_FULL_MEDIA)
    _answer_read(stub, DID_FULL_MEDIA, 0)

    assert stub._mark_media_status_color == stub.MARK_MEDIA_COLOR_BAD
    assert "хранит 0" in stub._mark_media_status


def test_refusal_on_the_write_stops_the_chain_and_foreign_refusals_are_ignored():
    stub = _MarkStub()
    stub._mark_media_note_intent(DID_FULL, 12130)
    stub._mark_media_on_mark_verified(DID_FULL)
    _run_to_write(stub, 3600, 2380, MODEL_OLD)

    # Отказ на чтение к записи цепочки не относится.
    stub._handle_mark_media_frame(RX_ID, _frame([0x7F, 0x22, 0x31]))
    assert stub._mark_media_active is True

    stub._handle_mark_media_frame(RX_ID, _frame([0x7F, 0x2E, 0x33]))
    assert stub._mark_media_active is False
    assert "0x33" in stub._mark_media_status
