"""Проверки связи с климатической камерой.

Документации на камеру ещё нет, поэтому всё, что от неё не зависит, должно
работать заранее и без ошибок: протокол Modbus, перевод регистров в градусы,
имитатор камеры и поток связи. Тесты закрепляют:
- кадры Modbus TCP и RTU собираются и разбираются по стандарту, ошибки камеры
  называются словами;
- числа из регистров переводятся в градусы при любом типе и порядке слов;
- имитатор ведёт себя как камера: воздух идёт к уставке с ограниченной
  скоростью, изделие отстаёт;
- поток связи выполняет команды и не падает, когда камера молчит.
"""

from __future__ import annotations

import socket
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from ui.qml.climate_chamber import (
    ChamberError,
    ChamberLink,
    ModbusChamber,
    ModbusMap,
    ModbusRtuClient,
    ModbusTcpClient,
    RegisterSpec,
    SimulatedChamber,
    decode_registers,
    encode_registers,
    make_driver,
    modbus_crc,
)


# ------------------------------------------------------------------ числа

def test_crc_matches_the_standard_example():
    # Пример из описания Modbus RTU: 01 03 00 00 00 0A -> CRC C5CD, младший байт первым.
    assert modbus_crc(bytes.fromhex("01030000000A")) == 0xCDC5


@pytest.mark.parametrize("spec, registers, expected", [
    (RegisterSpec(value_type="int16", scale=0.1), [0xFE70], -40.0),
    (RegisterSpec(value_type="uint16", scale=0.1), [850], 85.0),
    (RegisterSpec(value_type="int32", scale=0.01), [0xFFFF, 0xF060], -40.0),
    (RegisterSpec(value_type="float32", scale=1.0), [0xC220, 0x0000], -40.0),
    (RegisterSpec(value_type="float32", scale=1.0, high_word_first=False), [0x0000, 0xC220], -40.0),
])
def test_registers_become_degrees(spec, registers, expected):
    assert decode_registers(spec, registers) == pytest.approx(expected)
    assert decode_registers(spec, encode_registers(spec, expected)) == pytest.approx(expected)


def test_too_big_value_is_refused():
    with pytest.raises(ChamberError):
        encode_registers(RegisterSpec(value_type="int16", scale=0.001), 85.0)


def test_register_spec_reads_flags_written_as_words():
    spec = RegisterSpec.from_dict({"enabled": "false", "address": "12", "value_type": "что-то"})
    assert spec.enabled is False
    assert spec.address == 12
    assert spec.value_type == "int16"


# ------------------------------------------------------------------ Modbus TCP

class _FakeTcpChamber:
    """Камера по Modbus TCP: хранит регистры и отвечает по стандарту."""

    def __init__(self):
        self.registers = {0: 0xFE70, 1: 0xFE70, 2: 0}
        self.coils = {0: False}
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.server.accept()
        except OSError:
            return
        with conn:
            while True:
                header = conn.recv(7)
                if len(header) < 7:
                    return
                transaction, _protocol, length, unit = struct.unpack(">HHHB", header)
                pdu = conn.recv(length - 1)
                function = pdu[0]
                if function in (3, 4):
                    address, count = struct.unpack(">HH", pdu[1:5])
                    if address > 50:
                        answer = bytes([function | 0x80, 2])
                    else:
                        values = [self.registers.get(address + index, 0) for index in range(count)]
                        answer = bytes([function, 2 * count]) + b"".join(struct.pack(">H", v) for v in values)
                elif function == 6:
                    address, value = struct.unpack(">HH", pdu[1:5])
                    self.registers[address] = value
                    answer = pdu
                elif function == 5:
                    address, value = struct.unpack(">HH", pdu[1:5])
                    self.coils[address] = value == 0xFF00
                    answer = pdu
                elif function == 1:
                    address, _count = struct.unpack(">HH", pdu[1:5])
                    answer = bytes([1, 1, 1 if self.coils.get(address) else 0])
                else:
                    answer = bytes([function | 0x80, 1])
                conn.sendall(struct.pack(">HHHB", transaction, 0, len(answer) + 1, unit) + answer)

    def close(self):
        self.server.close()


@pytest.fixture
def tcp_chamber():
    chamber = _FakeTcpChamber()
    yield chamber
    chamber.close()


def _register_map():
    return ModbusMap.from_dict({
        "actual": {"table": "input", "address": 0, "value_type": "int16", "scale": 0.1},
        "setpoint": {"table": "holding", "address": 1, "value_type": "int16", "scale": 0.1},
        "run": {"enabled": True, "table": "coil", "address": 0},
        "alarm": {"enabled": True, "table": "holding", "address": 2, "value_type": "uint16", "scale": 1.0},
    })


def test_tcp_chamber_reads_and_writes(tcp_chamber):
    chamber = ModbusChamber(ModbusTcpClient("127.0.0.1", tcp_chamber.port, 1), _register_map(), "test")
    try:
        reading = chamber.read()
        assert reading.actual_c == pytest.approx(-40.0)
        assert reading.running is False and reading.alarm == 0

        chamber.set_setpoint(-20.5)
        chamber.set_running(True)
        reading = chamber.read()
        assert reading.setpoint_c == pytest.approx(-20.5)
        assert reading.running is True
    finally:
        chamber.close()


def test_modbus_error_is_named(tcp_chamber):
    register_map = _register_map()
    register_map.actual.address = 60
    chamber = ModbusChamber(ModbusTcpClient("127.0.0.1", tcp_chamber.port, 1), register_map, "test")
    try:
        with pytest.raises(ChamberError, match="нет такого адреса"):
            chamber.read()
    finally:
        chamber.close()


def test_missing_chamber_is_named():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = ModbusTcpClient("127.0.0.1", port, 1, timeout_s=0.5)
    with pytest.raises(ChamberError, match="нет соединения"):
        client.read_registers("holding", 0, 1)


# ------------------------------------------------------------------ Modbus RTU

class _FakeSerial:
    """Порт RS-485 с камерой на другом конце."""

    def __init__(self, registers, corrupt=False, **_kwargs):
        self.registers = registers
        self.corrupt = corrupt
        self.answer = b""
        self.sent = []

    def reset_input_buffer(self):
        self.answer = b""

    def write(self, frame):
        self.sent.append(frame)
        assert modbus_crc(frame[:-2]) == struct.unpack("<H", frame[-2:])[0]
        unit, function = frame[0], frame[1]
        if function == 3:
            address, count = struct.unpack(">HH", frame[2:6])
            values = [self.registers.get(address + index, 0) for index in range(count)]
            body = bytes([unit, 3, 2 * count]) + b"".join(struct.pack(">H", v) for v in values)
        else:
            body = frame[:-2]
            address, value = struct.unpack(">HH", frame[2:6])
            self.registers[address] = value
        crc = modbus_crc(body)
        if self.corrupt:
            crc ^= 0x1
        self.answer = body + struct.pack("<H", crc)

    def read(self, size):
        data, self.answer = self.answer[:size], self.answer[size:]
        return data

    def close(self):
        pass


def test_rtu_reads_and_writes():
    port = _FakeSerial({1: 250})
    client = ModbusRtuClient("COM5", 9600, "N", 1, unit=7, serial_factory=lambda **kwargs: port)
    assert client.read_registers("holding", 1, 1) == [250]
    assert port.sent[0][0] == 7
    client.write_registers(1, [0xFE70])
    assert port.registers[1] == 0xFE70


def test_rtu_corrupted_answer_is_refused():
    port = _FakeSerial({1: 250}, corrupt=True)
    client = ModbusRtuClient("COM5", 9600, "N", 1, unit=1, serial_factory=lambda **kwargs: port)
    with pytest.raises(ChamberError, match="контрольная сумма"):
        client.read_registers("holding", 1, 1)


def test_rtu_silence_is_named():
    class Silent(_FakeSerial):
        def write(self, frame):
            self.answer = b""
    client = ModbusRtuClient("COM5", 9600, "N", 1, unit=1, serial_factory=lambda **kwargs: Silent({}))
    with pytest.raises(ChamberError, match="не ответила по RS-485"):
        client.read_registers("holding", 0, 1)


# ------------------------------------------------------------------ имитатор

def test_simulated_air_reaches_the_setpoint_no_faster_than_the_ramp():
    chamber = SimulatedChamber(clock=lambda: 0.0, seed=1)
    chamber.set_setpoint(-40.0)
    chamber.set_running(True)

    chamber.advance(10.0)
    # 63 градуса со скоростью 2 °C/мин за 10 минут не пройти.
    assert chamber.air_c > -40.0 + 20.0
    chamber.advance(60.0)
    assert chamber.air_c == pytest.approx(-40.0, abs=0.05)


def test_simulated_product_lags_behind_the_air():
    chamber = SimulatedChamber(clock=lambda: 0.0, seed=1)
    chamber.set_setpoint(-40.0)
    chamber.set_running(True)
    chamber.advance(40.0)
    assert chamber.product_c > chamber.air_c + 1.0
    chamber.advance(120.0)
    assert chamber.product_c == pytest.approx(-40.0, abs=0.05)


def test_speed_compresses_time():
    now = [0.0]
    chamber = SimulatedChamber(speed=60.0, clock=lambda: now[0], seed=1)
    chamber.set_setpoint(85.0)
    chamber.set_running(True)
    now[0] = 60.0  # одна настоящая минута - час модельного времени
    assert chamber.read().actual_c == pytest.approx(85.0, abs=0.1)


def test_stopped_chamber_returns_to_the_room():
    chamber = SimulatedChamber(clock=lambda: 0.0, seed=1)
    chamber.set_setpoint(-40.0)
    chamber.advance(30.0)
    assert chamber.air_c == pytest.approx(SimulatedChamber.AMBIENT_C, abs=0.1)


def test_driver_is_made_from_settings():
    assert make_driver({"driver": "none"}) is None
    assert isinstance(make_driver({"driver": "simulator", "sim_speed": 10}), SimulatedChamber)
    driver = make_driver({"driver": "modbus_tcp", "tcp_host": "10.0.0.5", "tcp_port": 502, "unit": 3})
    assert isinstance(driver, ModbusChamber) and driver.client.unit == 3


# ------------------------------------------------------------------ поток связи

def test_link_polls_and_runs_commands():
    states = []
    link = ChamberLink(SimulatedChamber(seed=1), 0.2, states.append)
    try:
        link.command("setpoint", -40.0)
        link.command("run", True)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            readings = [state["reading"] for state in states if state.get("kind") == "reading" and state["ok"]]
            if readings and readings[-1].running and readings[-1].setpoint_c == -40.0:
                break
            time.sleep(0.05)
        commands = [state for state in states if state["kind"] == "command"]
        assert [state["ok"] for state in commands] == [True, True]
        assert readings[-1].running is True
    finally:
        link.close()


def test_link_survives_a_silent_chamber():
    class Broken(SimulatedChamber):
        def read(self):
            raise ChamberError("камера молчит")

    states = []
    link = ChamberLink(Broken(), 0.2, states.append)
    try:
        assert _wait_for(lambda: any(not state["ok"] for state in states))
        assert "молчит" in states[0]["text"]
        assert link._thread.is_alive()
    finally:
        link.close()


def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False
