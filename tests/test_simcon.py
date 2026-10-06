"""Проверки драйвера камеры Weiss WK1-600/70 с контроллером SIMCON/32.

Протокол взят из инструкции на пульт «Touchpanel», приложение «Interface
protocol», раздел ASCII-2. Строки ниже - примеры прямо из инструкции.
Тесты закрепляют:
- ответ на «$xxI» разбирается по порядку полей инструкции;
- строка «$xxE» собирается по образцу инструкции и не трогает влажность,
  вентилятор и цифровые каналы, которые программа менять не должна;
- пуск и остановка - это только канал 1 «Старт»;
- между строками выдерживается пауза 5 с, которую требует инструкция;
- молчание камеры называется словами, с подсказкой что проверить;
- контрольная сумма ASCII-1 совпадает с примером инструкции.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from ui.qml.climate_chamber import (
    ChamberError,
    ChamberLink,
    SimconAscii2Chamber,
    build_simcon_setpoints,
    make_driver,
    parse_simcon_state,
    simcon_ascii1_checksum,
    simcon_number,
)

# Ответ на «$00I» из инструкции (раздел 2.4.2).
MANUAL_ANSWER = ("0023.0 0020.5 0050.0 0041.0 0080.0 0080.0 0000.0 0020.1 0000.0 0020.2 "
                 "0000.0 0020.3 0000.0 0020.4 01101010101010101010101010101010")


def test_manual_answer_is_parsed():
    state = parse_simcon_state(MANUAL_ANSWER)
    assert state.temp_setpoint == 23.0
    assert state.temp_actual == 20.5
    assert state.humidity_setpoint == 50.0
    assert state.humidity_actual == 41.0
    assert state.fan_setpoint == 80.0
    assert state.pt100 == [20.1, 20.2, 20.3, 20.4]
    assert state.running is True


def test_negative_temperature_is_parsed():
    state = parse_simcon_state(MANUAL_ANSWER.replace("0020.5", "-039.8", 1))
    assert state.temp_actual == -39.8


def test_garbage_is_named():
    with pytest.raises(ChamberError, match="непонятно"):
        parse_simcon_state("ERROR 17")


def test_setpoint_string_matches_the_manual():
    # Образец из инструкции (раздел 2.5): $00E 0023.0 0050.0 0080.0 0000.0 0000.0 0000.0 0000.0 011...
    line = build_simcon_setpoints(0, 23.0, 50.0, 80.0, "0110")
    assert line == "$00E 0023.0 0050.0 0080.0 0000.0 0000.0 0000.0 0000.0 0110\r"


def test_numbers_keep_six_characters():
    assert simcon_number(-40) == "-040.0"
    assert simcon_number(85) == "0085.0"
    assert simcon_number(-5.25) == "-005.2" or simcon_number(-5.25) == "-005.3"


def test_ascii1_checksum_matches_the_manual():
    # Пример инструкции: STX "1?" -> "8E".
    assert simcon_ascii1_checksum("\x021?") == "8E"


class _FakeSimcon:
    """Контроллер SIMCON/32 на другом конце кабеля RS-232."""

    def __init__(self, **_kwargs):
        self.state = parse_simcon_state(MANUAL_ANSWER)
        self.sent = []
        self.answer = b""
        self.silent = False

    def reset_input_buffer(self):
        self.answer = b""

    def write(self, data):
        line = data.decode("ascii")
        self.sent.append(line)
        if self.silent:
            return
        if line[3] == "I":
            s = self.state
            numbers = [s.temp_setpoint, s.temp_actual, s.humidity_setpoint, s.humidity_actual,
                       s.fan_setpoint, s.fan_actual, 0, s.pt100[0], 0, s.pt100[1], 0, s.pt100[2], 0, s.pt100[3]]
            self.answer = (" ".join(simcon_number(n) for n in numbers) + " " + s.digital + "\r").encode("ascii")
        elif line[3] == "E":
            fields = line[4:].split()
            self.state.temp_setpoint = float(fields[0])
            self.state.humidity_setpoint = float(fields[1])
            self.state.fan_setpoint = float(fields[2])
            self.state.digital = fields[7]
            self.answer = b"0\r"

    def read_until(self, terminator):
        data, self.answer = self.answer, b""
        return data

    def close(self):
        pass


def _driver(port, clock=None, sleeps=None):
    times = clock if clock is not None else [0.0]
    pauses = sleeps if sleeps is not None else []

    def sleep(seconds):
        pauses.append(seconds)
        times[0] += seconds

    return SimconAscii2Chamber("COM4", 9600, 0, serial_factory=lambda **kwargs: port,
                               sleep=sleep, clock=lambda: times[0])


def test_driver_reads_and_sets_only_the_temperature():
    port = _FakeSimcon()
    driver = _driver(port)

    reading = driver.read()
    assert reading.actual_c == 20.5 and reading.setpoint_c == 23.0 and reading.running is True
    assert port.sent[0] == "$00I\r"

    driver.set_setpoint(-40.0)
    assert port.sent[-1] == "$00E -040.0 0050.0 0080.0 0000.0 0000.0 0000.0 0000.0 01101010101010101010101010101010\r"
    # Влажность, вентилятор и каналы остались как были.
    assert port.state.humidity_setpoint == 50.0
    assert port.state.digital == "01101010101010101010101010101010"


def test_start_and_stop_touch_only_channel_one():
    port = _FakeSimcon()
    driver = _driver(port)
    driver.read()
    driver.set_running(False)
    assert port.state.digital == "00101010101010101010101010101010"
    driver.read()
    driver.set_running(True)
    assert port.state.digital == "01101010101010101010101010101010"


def test_five_seconds_between_strings():
    """Инструкция: не чаще одной строки в 5 с, иначе страдает регулирование камеры."""
    port = _FakeSimcon()
    clock = [100.0]
    pauses = []
    driver = _driver(port, clock, pauses)
    driver.read()
    clock[0] += 1.0
    driver.set_setpoint(-20.0)
    assert pauses == [pytest.approx(4.0)]


def test_silent_chamber_is_named():
    port = _FakeSimcon()
    port.silent = True
    driver = _driver(port)
    with pytest.raises(ChamberError, match="нуль-модем"):
        driver.read()


def test_raw_string_is_sent_as_is():
    port = _FakeSimcon()
    driver = _driver(port)
    answer = driver.raw("$00I")
    assert port.sent[-1] == "$00I\r"
    assert answer.startswith("0023.0")


def test_driver_is_made_from_settings_with_its_own_address():
    driver = make_driver({"driver": "simcon_ascii2", "weiss_port": "COM7", "weiss_baud": 19200,
                          "simcon_address": 3, "unit": 1})
    assert isinstance(driver, SimconAscii2Chamber)
    assert driver.address == 3 and driver.baudrate == 19200 and driver.port == "COM7"


def test_link_never_polls_faster_than_the_chamber_allows():
    driver = SimconAscii2Chamber("COM4", 9600, 0, serial_factory=lambda **kwargs: _FakeSimcon())
    link = ChamberLink(driver, 1.0, lambda state: None)
    try:
        assert link.poll_s == 5.0
    finally:
        link.close()
