"""Проверки драйвера камеры ESPEC MC-811P.

Протокол взят из руководства ESPEC «Network Guide RS-485, RS-232C, GPIB»
(4000104005420, 2017). Строки ниже - примеры прямо из руководства.
Тесты закрепляют:
- команда уходит как «адрес,команда» с выбранным концом строки;
- ответы TEMP? и MON? разбираются, в том числе у камеры без влажности;
- уставка, пуск и стоп - это «TEMP, S...», «MODE, CONSTANT» и «MODE, STANDBY»;
- отказ «NA:...» называется словами с подсказкой, что сделать;
- между командами выдерживаются паузы руководства: 0,3 с после запроса и 0,5 с после настройки;
- протокол OLD с эхом (сначала «OK:команда», затем данные) тоже понимается;
- раздел программы показывает выбранную камеру и подсказывает режим прогона.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from ui.qml.climate_chamber import (
    ChamberError,
    EspecChamber,
    make_driver,
    parse_espec_mon,
    parse_espec_temp,
    serial_open_error,
)


def test_manual_answers_are_parsed():
    assert parse_espec_temp("23.0, 85.0, 105.0, -45.0") == (23.0, 85.0)
    assert parse_espec_mon("23.0,  85,  CONSTANT,  0") == (23.0, "CONSTANT", 0)
    # У камеры только с температурой влажности в ответе нет.
    assert parse_espec_mon("-39.8, STANDBY, 2") == (-39.8, "STANDBY", 2)
    assert parse_espec_mon("25.1, RMT  RUN  PAUSE, 0") == (25.1, "RMT RUN PAUSE", 0)


def test_garbage_is_named():
    with pytest.raises(ChamberError, match="непонятно"):
        parse_espec_temp("hello")
    with pytest.raises(ChamberError, match="непонятно"):
        parse_espec_mon("23.0")


class _FakeEspec:
    """Камера ESPEC на другом конце RS-485."""

    def __init__(self, delimiter=b"\r\n", echo=False):
        self.delimiter = delimiter
        self.echo = echo
        self.sent = []
        self.answer = b""
        self.actual = 24.8
        self.setpoint = 25.0
        self.mode = "STANDBY"
        self.alarms = []
        self.protect = False
        self.silent = False

    def reset_input_buffer(self):
        self.answer = b""

    def write(self, data):
        line = data.decode("ascii")
        self.sent.append(line)
        if self.silent:
            return
        address, _, command = line.strip().partition(",")
        assert address == "1"
        command = command.strip().upper()
        if command == "MON?":
            reply = f"{self.actual:.1f}, {self.mode}, {len(self.alarms)}"
        elif command == "TEMP?":
            reply = f"{self.actual:.1f}, {self.setpoint:.1f}, 190.0, -90.0"
        elif command == "ALARM?":
            reply = ", ".join(str(x) for x in [len(self.alarms)] + self.alarms)
        elif command.startswith("TEMP, S"):
            if self.protect:
                reply = "NA:PROTECT ON"
            else:
                self.setpoint = float(command[7:])
                reply = f"OK:{line.strip()}"
        elif command.startswith("MODE, "):
            self.mode = command[6:]
            reply = f"OK:{line.strip()}"
        else:
            reply = "NA:CMD_ERR"
        if self.echo and command.endswith("?"):
            reply = f"OK:{command}" + self.delimiter.decode() + reply
        self.answer = (reply + self.delimiter.decode()).encode("ascii")

    def read_until(self, terminator):
        index = self.answer.find(terminator)
        if index < 0:
            data, self.answer = self.answer, b""
            return data
        data, self.answer = self.answer[:index + 1], self.answer[index + 1:]
        return data

    def close(self):
        pass


def _driver(port, delimiter="CRLF", clock=None, sleeps=None):
    times = clock if clock is not None else [0.0]
    pauses = sleeps if sleeps is not None else []

    def sleep(seconds):
        pauses.append(round(seconds, 3))
        times[0] += seconds

    return EspecChamber("COM5", 9600, 1, delimiter, serial_factory=lambda **kwargs: port,
                        sleep=sleep, clock=lambda: times[0])


def test_reading_sends_address_and_delimiter():
    port = _FakeEspec()
    reading = _driver(port).read()
    assert port.sent == ["1,MON?\r\n", "1,TEMP?\r\n"]
    assert reading.actual_c == 24.8 and reading.setpoint_c == 25.0
    assert reading.running is False and reading.alarm == 0


def test_setpoint_start_and_stop():
    port = _FakeEspec()
    driver = _driver(port)
    driver.set_setpoint(-40.0)
    driver.set_running(True)
    assert port.sent == ["1,TEMP, S-40.0\r\n", "1,MODE, CONSTANT\r\n"]
    assert driver.read().running is True
    driver.set_running(False)
    assert port.mode == "STANDBY"


def test_alarm_number_is_reported():
    port = _FakeEspec()
    port.alarms = [7, 12]
    assert _driver(port).read().alarm == 7


def test_refusal_is_explained():
    port = _FakeEspec()
    port.protect = True
    with pytest.raises(ChamberError, match="защита от удалённого управления"):
        _driver(port).set_setpoint(-40.0)


def test_pauses_from_the_manual():
    port = _FakeEspec()
    clock = [100.0]
    pauses = []
    driver = _driver(port, clock=clock, sleeps=pauses)
    driver.set_setpoint(-20.0)
    driver.read()
    # После настройки 0,5 с, между двумя запросами 0,3 с.
    assert pauses == [0.5, 0.3]


def test_old_protocol_with_echo_is_understood():
    port = _FakeEspec(echo=True)
    assert _driver(port).read().actual_c == 24.8


def test_other_delimiter():
    port = _FakeEspec(delimiter=b"\r")
    driver = _driver(port, delimiter="CR")
    assert driver.read().setpoint_c == 25.0
    assert port.sent[0] == "1,MON?\r"


def test_silent_chamber_is_named():
    port = _FakeEspec()
    port.silent = True
    with pytest.raises(ChamberError, match="4-проводное"):
        _driver(port).read()


def test_raw_command_gets_the_address_once():
    port = _FakeEspec()
    driver = _driver(port)
    assert driver.raw("TEMP?").startswith("24.8")
    assert driver.raw("1,MON?").startswith("24.8")
    assert port.sent == ["1,TEMP?\r\n", "1,MON?\r\n"]


def test_driver_from_settings():
    driver = make_driver({"driver": "espec", "espec_port": "COM9", "espec_baud": 19200, "espec_address": 3,
                          "espec_delimiter": "LF"})
    assert isinstance(driver, EspecChamber)
    assert (driver.port, driver.baudrate, driver.address, driver.delimiter) == ("COM9", 19200, 3, "\n")


def test_port_errors_are_readable():
    assert "не найден" in str(serial_open_error("COM5", Exception(
        "could not open port 'COM5': FileNotFoundError(2, 'x')")))
    assert "занят" in str(serial_open_error("COM5", Exception(
        "could not open port 'COM5': PermissionError(13, 'Access is denied.')")))


# ------------------------------------------------------------------ раздел программы

def test_section_names_the_chamber_and_hints_the_mode(tmp_path: Path):
    from tests.test_climate_run import _ClimateStub

    stub = _ClimateStub(tmp_path)
    stub._climate_link = None
    stub._chamber_board_only = False

    assert stub._climate_set("driver", "espec")
    view = stub._climate_view()
    assert view["chamber"]["name"] == "ESPEC MC-811P"
    assert "COM5" in view["chamber"]["summary"] and "адрес 1" in view["chamber"]["summary"]
    assert "Только плата" in view["modeHint"] and "включите" in view["modeHint"]

    stub._chamber_board_only = True
    assert stub._climate_view()["modeHint"] == ""

    assert stub._climate_set("driver", "simcon_ascii2")
    view = stub._climate_view()
    assert view["chamber"]["name"] == "Weiss WK1-600/70"
    assert "выключите" in view["modeHint"]


def test_espec_settings_are_checked(tmp_path: Path):
    from tests.test_climate_run import _ClimateStub

    stub = _ClimateStub(tmp_path)
    stub._climate_link = None
    assert not stub._climate_set("espec_address", "20")
    assert not stub._climate_set("espec_delimiter", "TAB")
    assert stub._climate_set("espec_delimiter", "cr")
    assert stub._climate_settings["espec_delimiter"] == "CR"
