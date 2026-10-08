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
- раздел программы показывает выбранную камеру и подсказывает режим прогона;
- переходник Moxa UPort 1150 находится сам, если в поле порта стоит «auto»;
- опрос по кругу читает подробности: нагреватель, холодильник, блокировку пульта;
- команды каталога собираются с проверкой параметров, ответы поясняются словами;
- поиск камеры находит адрес, скорость и конец строки, а без камеры ничего не портит;
- ручные команды не мешают автоматическому прогону и не выходят за пределы уставки.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from ui.qml.climate_chamber import (
    ESPEC_COMMANDS,
    MOXA_USB_VID,
    ChamberError,
    ChamberLink,
    ChamberReading,
    EspecChamber,
    build_espec_command,
    describe_espec_answer,
    list_serial_ports,
    make_driver,
    parse_espec_mon,
    parse_espec_temp,
    resolve_port,
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
        self.garbage = None
        # Ответы на подробные запросы: примеры из руководства для камеры без влажности.
        self.extra = {
            "%?": "1, 56.2",
            "REF?": "1, ON1",
            "SET?": "REF9",
            "KEYPROTECT?": "OFF",
            "ROM?": "JMIC -S1.00",
            "TYPE?": "T, S2, 180.0",
            "RUN PRGM MON?": "1, -12.5, 0:42, 1",
            "MODE?": "STANDBY",
        }

    def reset_input_buffer(self):
        self.answer = b""

    def write(self, data):
        line = data.decode("ascii")
        self.sent.append(line)
        if self.silent:
            return
        if self.garbage is not None:
            # Перевёрнутая пара приёма или обрыв: вместо ответа приходят эти байты.
            self.answer = self.garbage
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
        elif command in self.extra:
            reply = self.extra[command]
        elif command.startswith(("PRGM, ", "RUN PRGM, ", "KEYPROTECT, ", "SET, ", "TEMP, ")):
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
    # Первый опрос: главное (MON?, TEMP?) и один раз версия и тип контроллера.
    assert port.sent == ["1,MON?\r\n", "1,TEMP?\r\n", "1,ROM?\r\n", "1,TYPE?\r\n"]
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
    # После настройки 0,5 с, между запросами (MON?, TEMP?, ROM?, TYPE?) по 0,3 с.
    assert pauses == [0.5, 0.3, 0.3, 0.3]


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
    # Молчание - команда не доходит до камеры: подсказка про пару 1 и режим порта Moxa.
    with pytest.raises(ChamberError, match="молчит") as error:
        _driver(port).read()
    assert "клеммах 1 и 2" in str(error.value) and "RS-422" in str(error.value)


@pytest.mark.parametrize("garbage", [b"\x8f\xf3\x00\xfe\r\n", b"\xc7\x9a\x81", b"\x00\x00\x00\x00"])
def test_garbage_points_to_the_receive_pair(garbage):
    port = _FakeEspec()
    port.garbage = garbage
    with pytest.raises(ChamberError, match="непонятные байты") as error:
        _driver(port).read()
    assert "клеммах 3 RxD+ и 4 RxD−" in str(error.value)
    assert garbage[:2].hex(" ").upper() in str(error.value)


@pytest.mark.parametrize("chamber, program, wanted", [(b"\r", "CRLF", "CR"), (b"\n", "CR", "LF"), (b"\r", "LF", "CR")])
def test_other_delimiter_is_named(chamber, program, wanted):
    port = _FakeEspec(delimiter=chamber)
    with pytest.raises(ChamberError, match=f"выберите {wanted} в настройках") as error:
        _driver(port, delimiter=program).read()
    assert "24.8" in str(error.value)


def test_cut_answer_is_named():
    port = _FakeEspec()
    port.garbage = b"24.8, STAN"
    with pytest.raises(ChamberError, match="оборвался"):
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
    # По умолчанию порт «auto»: программа сама ищет переходник Moxa UPort.
    assert "Moxa UPort" in view["chamber"]["summary"] and "адрес 1" in view["chamber"]["summary"]
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


# ------------------------------------------------------------------ переходник Moxa UPort 1150

class _PortInfo:
    """Описание COM-порта, как его отдаёт pyserial."""

    def __init__(self, device, description, vid=None, manufacturer="", hwid=""):
        self.device = device
        self.description = description
        self.vid = vid
        self.manufacturer = manufacturer
        self.hwid = hwid
        self.product = ""


def _ports(*items):
    return lambda: list(items)


def test_moxa_port_is_found_first():
    comports = _ports(_PortInfo("COM4", "JLink CDC UART Port (COM4)", vid=0x1366),
                      _PortInfo("COM12", "MOXA USB Serial Port (COM12)"),
                      _PortInfo("COM1", "Последовательный порт (COM1)"),
                      _PortInfo("COM9", "USB Serial Port (COM9)", vid=MOXA_USB_VID))
    ports = list_serial_ports(comports)
    assert [item["device"] for item in ports] == ["COM9", "COM12", "COM1", "COM4"]
    assert [item["moxa"] for item in ports] == [True, True, False, False]
    assert resolve_port("auto", comports) == "COM9"
    assert resolve_port("COM4", comports) == "COM4"


def test_missing_moxa_is_named():
    with pytest.raises(ChamberError, match="Moxa UPort не найден"):
        resolve_port("auto", _ports(_PortInfo("COM4", "JLink CDC UART Port (COM4)")))


def test_driver_opens_the_moxa_port_itself():
    opened = {}
    port = _FakeEspec()

    def factory(**kwargs):
        opened.update(kwargs)
        return port

    driver = EspecChamber("auto", 9600, 1, serial_factory=factory, sleep=lambda s: None,
                          comports=_ports(_PortInfo("COM7", "MOXA USB Serial Port (COM7)")))
    assert "ищется" in driver.title
    driver.read()
    assert opened["port"] == "COM7"
    assert driver.title == "ESPEC на COM7 (Moxa UPort), адрес 1"


# ------------------------------------------------------------------ подробности опроса

def test_details_are_read_in_turn():
    port = _FakeEspec()
    driver = _driver(port)
    first = driver.read()
    assert first.details["rom"] == "JMIC -S1.00" and first.details["type"] == "T, S2, 180.0"
    assert (first.details["high_c"], first.details["low_c"]) == (190.0, -90.0)
    for _ in range(4):
        last = driver.read()
    # За четыре следующих опроса прочитаны нагреватель, холодильник, его настройка и блокировка пульта.
    assert last.details["heater_pct"] == 56.2
    assert last.details["ref_running"] is True
    assert last.details["ref_setting"] == "REF9"
    assert last.details["key_protect"] is False
    assert sum(1 for line in port.sent if line.startswith("1,MON?")) == 5


def test_remote_program_progress_is_read():
    port = _FakeEspec()
    port.mode = "RMT RUN"
    driver = _driver(port)
    reading = None
    for _ in range(6):
        reading = driver.read()
    assert reading.running is True
    assert "-12,5" in reading.details["program"] and "0:42" in reading.details["program"]


def test_refused_detail_does_not_break_the_link():
    port = _FakeEspec()
    port.extra = {}
    driver = _driver(port)
    for _ in range(3):
        reading = driver.read()
    assert reading.actual_c == 24.8 and "heater_pct" not in reading.details


def test_program_commands_wait_longer():
    port = _FakeEspec()
    pauses = []
    driver = _driver(port, sleeps=pauses)
    driver.raw("PRGM, PAUSE")
    driver.raw("TEMP?")
    driver.raw("RUN PRGM MON?")
    driver.raw("MON?")
    # По руководству: после настройки программы 1 с, после запроса о программе 0,5 с.
    assert pauses == [1.0, 0.3, 0.5]


# ------------------------------------------------------------------ каталог команд

def test_catalog_builds_commands():
    assert build_espec_command("mon") == "MON?"
    assert build_espec_command("set_temp", {"temp": "-40,5"}) == "TEMP, S-40.5"
    assert build_espec_command("set_all", {"temp": "25", "high": "100", "low": "-50"}) == "TEMP, S25.0 H100.0 L-50.0"
    assert build_espec_command("run_prgm", {"start": "25", "end": "-40", "time": "2:30"}) == \
        "RUN PRGM, TEMP25.0 GOTEMP-40.0 TIME2:30"
    assert build_espec_command("set_ref", {"ref": "0"}) == "SET, REF0"
    assert build_espec_command("relay_on", {"relays": "1;2"}) == "RELAY, ON, 1, 2"
    assert build_espec_command("set_mask", {"mask": "01110000"}) == "MASK, 01110000"
    # Без значения берётся значение по умолчанию из каталога.
    assert build_espec_command("set_temp") == "TEMP, S25.0"


@pytest.mark.parametrize("key, values, reason", [
    ("set_temp", {"temp": "холодно"}, "число"),
    ("set_ref", {"ref": "12"}, "от 0 до 9"),
    ("run_prgm", {"start": "25", "end": "0", "time": "90"}, "часы:минуты"),
    ("run_prgm", {"start": "25", "end": "0", "time": "0:00"}, "часы:минуты"),
    ("set_mask", {"mask": "0111"}, "8 цифр"),
    ("relay_on", {"relays": "a"}, "через запятую"),
    ("nothing", {}, "нет такой команды"),
])
def test_catalog_rejects_bad_values(key, values, reason):
    with pytest.raises(ChamberError, match=reason):
        build_espec_command(key, values)


def test_catalog_is_consistent():
    keys = [item["key"] for item in ESPEC_COMMANDS]
    assert len(keys) == len(set(keys))
    for item in ESPEC_COMMANDS:
        assert item["title"] and item["group"] and item.get("hint")
        # Каждая команда собирается со значениями по умолчанию (кроме даты и времени без значения).
        if not any(param["kind"] in ("date", "clock") for param in item.get("params", [])):
            build_espec_command(item["key"])


def test_answers_are_explained():
    assert describe_espec_answer("MON?", "-39.8, CONSTANT, 0") == "в камере -39,8 °C, постоянный режим, аварий нет"
    assert "уставка -40,0 °C" in describe_espec_answer("1,TEMP?", "-39.8, -40.0, 190.0, -90.0")
    assert describe_espec_answer("MODE?", "RMT RUN PAUSE") == "удалённая программа на паузе"
    assert describe_espec_answer("ALARM?", "2, 1, 7") == "аварий 2, номера: 1, 7"
    assert describe_espec_answer("%?", "1, 56.2") == "нагреватель: 56,2 %"
    assert describe_espec_answer("REF?", "0") == "холодильник стоит"
    assert describe_espec_answer("SET?", "REF9") == "холодильник: авто (REF9)"
    assert describe_espec_answer("KEYPROTECT?", "ON") == "пульт заблокирован"
    assert describe_espec_answer("SRQ?", "01000000") == "отмечено: авария"
    assert describe_espec_answer("MODE, CONSTANT", "OK:1,MODE, CONSTANT") == "принято"
    assert "защита от удалённого управления" in describe_espec_answer("TEMP, S-40.0", "NA:PROTECT ON")
    assert describe_espec_answer("SOMETHING?", "42") == ""


# ------------------------------------------------------------------ поиск камеры

class _HiddenEspec:
    """Камера с неизвестными настройками связи: отвечает только на своих адресе и скорости."""

    def __init__(self, address=3, baud=19200, delimiter=b"\r", inverted=False):
        self.address = address
        self.baud = baud
        self.delimiter = delimiter
        self.inverted = inverted
        self.opened = []
        self.sent = []

    def factory(self, **kwargs):
        self.opened.append(kwargs["baudrate"])
        return _HiddenPort(self, kwargs["baudrate"])


class _HiddenPort:
    def __init__(self, chamber, baudrate):
        self.chamber = chamber
        self.baudrate = baudrate
        self.timeout = None
        self.answer = b""

    def reset_input_buffer(self):
        self.answer = b""

    def write(self, data):
        chamber = self.chamber
        line = data.decode("ascii")
        chamber.sent.append((self.baudrate, line))
        if self.baudrate != chamber.baud:
            return
        address, _, command = line.strip("\r\n").partition(",")
        if address != str(chamber.address):
            return
        reply = "JMIC -S1.00" if command.strip() == "ROM?" else "NA:CMD_ERR"
        self.answer = reply.encode("ascii") + chamber.delimiter
        if chamber.inverted:
            # Перевёрнутая пара приёма: каждый бит ответа приходит наоборот.
            self.answer = bytes(byte ^ 0xFF for byte in self.answer)

    def read_until(self, terminator):
        index = self.answer.find(terminator)
        if index < 0:
            data, self.answer = self.answer, b""
            return data
        data, self.answer = self.answer[:index + 1], self.answer[index + 1:]
        return data

    def close(self):
        pass


def _scan_driver(chamber, address=1, baud=9600, delimiter="CRLF"):
    return EspecChamber("COM7", baud, address, delimiter, serial_factory=chamber.factory, sleep=lambda s: None)


@pytest.mark.parametrize("delimiter, name", [(b"\r", "CR"), (b"\n", "LF"), (b"\r\n", "CRLF")])
def test_scan_finds_address_speed_and_delimiter(delimiter, name):
    chamber = _HiddenEspec(address=3, baud=19200, delimiter=delimiter)
    driver = _scan_driver(chamber)
    steps = []
    found = driver.scan(progress=steps.append)
    assert found == {"baud": 19200, "address": 3, "delimiter": name, "rom": "JMIC -S1.00"}
    assert (driver.address, driver.baudrate, driver.delimiter_name) == (3, 19200, name)
    # Обычная связь сразу идёт на найденных настройках.
    assert driver.raw("ROM?") == "JMIC -S1.00"
    assert steps[0].startswith("Проверяю адрес 1, 9600 бод (1 из 48)")


def test_scan_starts_from_current_settings():
    chamber = _HiddenEspec(address=5, baud=4800)
    driver = _scan_driver(chamber, address=5, baud=4800)
    steps = []
    assert driver.scan(progress=steps.append)["address"] == 5
    assert len(steps) == 1


def test_failed_scan_keeps_old_settings():
    chamber = _HiddenEspec(address=3, baud=19200)
    chamber.baud = 115200
    driver = _scan_driver(chamber, address=2, baud=9600, delimiter="LF")
    assert driver.scan() is None
    assert (driver.address, driver.baudrate, driver.delimiter_name) == (2, 9600, "LF")
    assert driver.timeout_s == 2.0


def test_scan_can_be_stopped():
    chamber = _HiddenEspec(address=16, baud=4800)
    driver = _scan_driver(chamber)
    calls = []
    assert driver.scan(should_stop=lambda: len(calls) > 2, progress=calls.append) is None
    assert len(calls) == 3


def test_failed_scan_names_the_pair_to_check():
    # Камера отвечает, но пара приёма перевёрнута: виноваты клеммы 3 и 4.
    inverted = _HiddenEspec(address=3, baud=19200, inverted=True)
    driver = _scan_driver(inverted)
    assert driver.scan() is None
    assert "адрес 3 на 19200 бод" in driver.scan_hint and "клеммах 3 RxD+ и 4 RxD−" in driver.scan_hint
    # Камера молчит везде: виноваты клеммы 1 и 2 или режим порта.
    silent = _HiddenEspec(address=3, baud=115200)
    driver = _scan_driver(silent)
    assert driver.scan() is None
    assert "молчит на всех" in driver.scan_hint and "клеммах 1 и 2" in driver.scan_hint


def test_link_tells_why_the_scan_failed():
    import threading

    states = []
    done = threading.Event()

    class _Driver:
        title = "камера"
        scan_hint = "камера молчит на всех адресах и скоростях: проверьте клеммы 1 и 2"

        def read(self):
            return ChamberReading(actual_c=20.0)

        def scan(self, should_stop, progress):
            return None

        def close(self):
            pass

    def on_state(state):
        states.append(state)
        if state.get("kind") == "scan" and state.get("done"):
            done.set()

    link = ChamberLink(_Driver(), 60.0, on_state)
    link.command("scan")
    assert done.wait(5.0)
    link.close()
    result = [state for state in states if state["kind"] == "scan"][-1]
    assert result["ok"] is False and result["text"] == _Driver.scan_hint


def test_link_reports_scan_progress_and_result():
    import threading

    states = []
    done = threading.Event()

    class _Driver:
        title = "камера"

        def read(self):
            return ChamberReading(actual_c=20.0)

        def scan(self, should_stop, progress):
            progress("Проверяю адрес 1")
            return {"baud": 9600, "address": 1, "delimiter": "CR", "rom": "JMIC"}

        def close(self):
            pass

    def on_state(state):
        states.append(state)
        if state.get("kind") == "scan" and state.get("done"):
            done.set()

    link = ChamberLink(_Driver(), 60.0, on_state)
    link.command("scan")
    assert done.wait(5.0)
    link.close()
    scans = [state for state in states if state["kind"] == "scan"]
    assert scans[0]["done"] is False and scans[-1]["found"]["delimiter"] == "CR"


# ------------------------------------------------------------------ ручное управление в программе

class _RecLink:
    """Связь без потока: запоминает команды окна."""

    def __init__(self, driver=None):
        self.driver = driver or EspecChamber("COM7", 9600, 1)
        self.commands = []

    def command(self, name, value=None):
        self.commands.append((name, value))

    def close(self):
        pass


def _espec_stub(tmp_path):
    from tests.test_climate_run import _ClimateStub

    stub = _ClimateStub(tmp_path)
    stub._climate_settings["driver"] = "espec"
    stub._climate_link = _RecLink()
    return stub


def test_catalog_command_goes_to_the_chamber(tmp_path: Path):
    stub = _espec_stub(tmp_path)
    assert stub._climate_send_espec("set_high", '{"high": "120"}')
    assert stub._climate_send_espec("mode_standby", "")
    assert stub._climate_link.commands == [("raw", "TEMP, H120.0"), ("raw", "MODE, STANDBY")]
    assert not stub._climate_send_espec("set_ref", '{"ref": "11"}')
    assert "от 0 до 9" in stub._climate_command_status


def test_setpoint_from_catalog_respects_limits(tmp_path: Path):
    stub = _espec_stub(tmp_path)
    assert not stub._climate_send_espec("set_temp", '{"temp": "-60"}')
    assert not stub._climate_send_espec("run_prgm", '{"start": "25", "end": "120", "time": "1:00"}')
    assert "вне допустимых пределов" in stub._climate_command_status
    assert stub._climate_link.commands == []


def test_manual_control_waits_for_the_run(tmp_path: Path):
    stub = _espec_stub(tmp_path)
    stub._climate_run_stage = "settle"
    # Запросы можно всегда, менять камеру во время прогона - нельзя.
    assert stub._climate_send_espec("mon", "")
    assert not stub._climate_send_espec("mode_standby", "")
    assert not stub._climate_send_raw("MODE, OFF")
    assert "автоматический прогон" in stub._climate_command_status
    stub._climate_run_paused = True
    assert stub._climate_send_espec("mode_standby", "")
    assert stub._climate_link.commands == [("raw", "MON?"), ("raw", "MODE, STANDBY")]


def test_log_explains_answers_and_scan_saves_settings(tmp_path: Path):
    stub = _espec_stub(tmp_path)
    stub._climate_queue_state({"kind": "raw", "ok": True, "sent": "MON?", "text": "-39.8, CONSTANT, 0"})
    stub._climate_scan_active = True
    stub._climate_queue_state({"kind": "scan", "ok": True, "done": True, "text": "",
                               "found": {"baud": 19200, "address": 3, "delimiter": "CR", "rom": "JMIC -S1.00"}})
    stub._climate_take_incoming(0.0)
    assert stub._climate_raw_log[0]["explain"] == "в камере -39,8 °C, постоянный режим, аварий нет"
    assert not stub._climate_scan_active
    assert (stub._climate_settings["espec_baud"], stub._climate_settings["espec_address"],
            stub._climate_settings["espec_delimiter"]) == (19200, 3, "CR")
    assert "Камера найдена" in stub._climate_scan_status


def test_view_shows_espec_details(tmp_path: Path):
    stub = _espec_stub(tmp_path)
    stub._climate_reading = ChamberReading(actual_c=-39.8, setpoint_c=-40.0, running=True, alarm=0, details={
        "mode": "RMT RUN PAUSE", "high_c": 190.0, "low_c": -90.0, "heater_pct": 12.5,
        "ref_running": True, "ref_setting": "REF9", "key_protect": True, "rom": "JMIC -S1.00", "type": "T, S2, 180.0",
    })
    stub._climate_last_ok_s = 1e12
    view = stub._climate_view()
    espec = view["espec"]
    assert espec["modeText"] == "удалённая программа на паузе" and espec["paused"] and espec["program"]
    assert espec["highText"] == "+190,0 °C" and espec["lowText"] == "-90,0 °C"
    assert espec["heaterText"] == "12,5 %" and espec["refText"] == "работает, авто"
    assert espec["keyText"] == "заблокирован" and "JMIC" in espec["identity"]
    assert len(view["commands"]) == len(ESPEC_COMMANDS)

def test_real_mc811p_answers():
    """Ответы настоящей MC-811P (контроллер SCP220, прошивка JMIC 4.00) от 08.10.2026."""
    assert parse_espec_mon("27.0,,STANDBY,0") == (27.0, "STANDBY", 0)
    assert parse_espec_temp("27.0,50.0,185.0,-90.0") == (27.0, 50.0)
    assert describe_espec_answer("TYPE?", "T,SCP220,190.0") == "датчик T, контроллер SCP220, предел уставки +190,0 °C"
    assert describe_espec_answer("%?", "1,0.0") == "нагреватель: 0,0 %"
    assert "нет такой функции" in describe_espec_answer("RELAY?", "NA:CONT NOT READY-5")
