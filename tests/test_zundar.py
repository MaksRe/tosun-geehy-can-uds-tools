"""Камера Zundar EEXTH1000U (контроллер AZ1000) по Modbus TCP: драйвер против имитатора контроллера.

Имитатор - настоящий сервер Modbus TCP на локальном порту, как в инструкции контроллера
(раздел 5.3): станция 0, функции 03/06, регистры 0x0001...0x001C, 0x002E, 0x002F, 0x00E0, 0x00EB.
Тесты закрепляют:
- кадры совпадают с примерами инструкции: чтение 16 регистров с 0x0001, уставка +80,0 °C -
  запись 0x002E = 800, пуск - запись 0x0001 = 2;
- температура со знаком (-40,0 °C), номер аварии 9999 - аварии нет;
- перед уставкой камера переводится в фиксированный режим (0x0003 = 1), при пуске влажность
  выключается (0x002F = 0); уставка и пуск сверяются чтением;
- на пульте «только сенсорное управление» - камера отвечает ошибкой, программа говорит, что переключить;
- проверка перед прогоном: управление по сети запрещено - запрет; пределы аварии не охватывают узлы;
- строки «r 0001 28» и «w 002E 800» для проверки на месте.
"""

from __future__ import annotations

import socket
import struct
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from ui.qml.climate_chamber import ChamberError, ZundarChamber, make_driver


class _Az1000:
    """Контроллер AZ1000: регистры и сервер Modbus TCP (одно соединение за раз)."""

    def __init__(self):
        self.regs = {address: 0 for address in range(0x0000, 0x0200)}
        self.regs[0x0001] = 1          # ожидание
        self.regs[0x0002] = 1          # AZ1000-TH
        self.regs[0x0003] = 0          # программа
        self.regs[0x0004] = 230        # +23,0 °C
        self.regs[0x0006] = 900
        self.regs[0x0007] = 100
        self.regs[0x002F] = 500        # влажность 50 %
        self.regs[0x001C] = 9999       # аварии нет
        self.regs[0x00E0] = 1          # управление по сети разрешено
        for address, value in zip(range(0x00EB, 0x00EF), (1600, (-750) & 0xFFFF, 1700, (-800) & 0xFFFF)):
            self.regs[address] = value
        self.frames: list[bytes] = []
        self.touch_only = False
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self._stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self._stop:
            try:
                conn, _addr = self.server.accept()
            except OSError:
                return
            with conn:
                while True:
                    header = conn.recv(7)
                    if len(header) < 7:
                        break
                    transaction, _protocol, length, unit = struct.unpack(">HHHB", header)
                    pdu = conn.recv(length - 1)
                    self.frames.append(header + pdu)
                    answer = self._answer(pdu)
                    conn.sendall(struct.pack(">HHHB", transaction, 0, len(answer) + 1, unit) + answer)

    def _answer(self, pdu: bytes) -> bytes:
        function = pdu[0]
        if function == 3:
            address, count = struct.unpack(">HH", pdu[1:5])
            values = [self.regs.get(address + index, 0) & 0xFFFF for index in range(count)]
            return bytes([3, 2 * count]) + struct.pack(f">{count}H", *values)
        if function == 6:
            address, value = struct.unpack(">HH", pdu[1:5])
            if self.touch_only:
                return bytes([0x86, 4])
            self._write(address, value)
            return pdu[:5]
        return bytes([function | 0x80, 1])

    def _write(self, address: int, value: int):
        self.regs[address] = value
        if address == 0x002E and self.regs[0x0003] == 1:
            self.regs[0x0006] = value
        if address == 0x0001:
            self.regs[0x0001] = value

    def close(self):
        self._stop = True
        self.server.close()


@pytest.fixture()
def controller():
    fake = _Az1000()
    yield fake
    fake.close()


def _driver(fake):
    return make_driver({"driver": "zundar_az1000", "zundar_host": "127.0.0.1", "zundar_port": fake.port,
                        "zundar_unit": 0})


def test_driver_is_made_from_settings(controller):
    driver = _driver(controller)
    assert isinstance(driver, ZundarChamber) and driver.client.unit == 0 and driver.port == controller.port
    driver.close()


def test_reading_matches_the_manual(controller):
    controller.regs[0x0004] = (-400) & 0xFFFF
    driver = _driver(controller)
    reading = driver.read()
    driver.close()
    # Кадр чтения - как в примере инструкции (там 16 регистров, здесь весь блок до номера аварии).
    assert controller.frames[0][6:] == bytes.fromhex("00 03 00 01 00 1c")
    assert reading.actual_c == -40.0 and reading.setpoint_c == 90.0 and reading.running is False
    assert reading.alarm is None, "9999 - аварии нет"
    assert reading.details["humidity_on"] is True and reading.details["lan_control"] is True
    assert reading.details["high_c"] == 160.0 and reading.details["low_c"] == -75.0
    assert reading.details["type"] == "AZ1000-TH"


def test_setpoint_switches_to_fixed_mode_and_is_verified(controller):
    driver = _driver(controller)
    driver.read()
    driver.set_setpoint(80.0)
    driver.set_setpoint(-40.0)
    driver.close()
    writes = [frame[6:] for frame in controller.frames if frame[7] == 6]
    assert writes[0] == bytes.fromhex("00 06 00 03 00 01"), "сначала фиксированный режим"
    assert writes[1] == bytes.fromhex("00 06 00 2e 03 20"), "уставка +80,0 - как в примере инструкции"
    assert writes[2] == bytes.fromhex("00 06 00 2e fe 70"), "-40,0 - со знаком"
    assert controller.regs[0x0006] == (-400) & 0xFFFF


def test_start_turns_humidity_off_and_stop(controller):
    driver = _driver(controller)
    driver.read()
    driver.set_running(True)
    assert controller.regs[0x002F] == 0 and controller.regs[0x0001] == 2 and controller.regs[0x0003] == 1
    assert driver.read().running is True
    driver.set_running(False)
    assert controller.regs[0x0001] == 1 and driver.read().running is False
    driver.close()
    writes = [frame[6:] for frame in controller.frames if frame[7] == 6]
    assert bytes.fromhex("00 06 00 01 00 02") in writes, "пуск - как в примере инструкции"


def test_setpoint_not_taken_is_named(controller):
    driver = _driver(controller)
    driver.read()
    controller.regs[0x0003] = 1
    driver.read()
    original = controller._write
    controller._write = lambda address, value: None if address == 0x002E else original(address, value)
    with pytest.raises(ChamberError, match="не приняла уставку"):
        driver.set_setpoint(30.0)
    driver.close()


def test_touch_only_mode_tells_what_to_switch(controller):
    controller.touch_only = True
    driver = _driver(controller)
    driver.read()
    with pytest.raises(ChamberError, match="«Оба» или «Только LAN»"):
        driver.set_setpoint(30.0)
    driver.close()


def test_alarm_number_is_passed_on(controller):
    controller.regs[0x001C] = 12
    driver = _driver(controller)
    assert driver.read().alarm == 12
    driver.close()


def test_raw_strings_for_checking_on_site(controller):
    driver = _driver(controller)
    assert driver.raw("r 0001 3") == "0001=1 0002=1 0003=0"
    assert "записано" in driver.raw("w 002F 0") and controller.regs[0x002F] == 0
    with pytest.raises(ChamberError, match="r 0001 28"):
        driver.raw("что-то")
    driver.close()


def test_pre_run_checks_for_zundar(tmp_path):
    """Управление по сети запрещено - запрет; пределы аварии камеры - сверка с узлами."""
    from tests.test_climate_supervisor import _SupStub
    from ui.qml.climate_chamber import ChamberReading

    stub = _SupStub(tmp_path)
    stub._climate_link = None
    assert stub._climate_set("driver", "zundar_az1000")
    assert stub._climate_set("zundar_host", "192.168.0.100")
    stub._climate_settings["run_nodes"] = "25, -40, 85"
    details = {"mode": "ожидание", "fixed": True, "humidity_on": True, "humidity_c": 40.0, "humidity_set": 50.0,
               "heater_pct": 0.0, "cooling_pct": 35.0, "lan_control": False, "high_c": 160.0, "low_c": -30.0}
    stub._climate_reading = ChamberReading(actual_c=23.0, setpoint_c=23.0, running=False, details=details)
    import time
    stub._climate_last_ok_s = time.monotonic()
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert not checks["lan_control"]["ok"] and checks["lan_control"]["level"] == "block"
    assert not checks["espec_limits"]["ok"] and "на пульте камеры" in checks["espec_limits"]["text"]
    assert checks["humidity"]["level"] == "warn"
    view = stub._climate_zundar_view(stub._climate_reading)
    assert view["visible"] and view["coolingText"] == "35 %" and "ЗАПРЕЩЕНО" in view["lanText"]
    assert view["limitsText"] == "-30,0 °C … +160,0 °C"
    assert "охлаждение 35 %" in stub._climate_auto_hardware_text()
    details["lan_control"] = True
    details["low_c"] = -75.0
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert checks["lan_control"]["ok"] and checks["espec_limits"]["ok"]
    card = stub._climate_chamber_card()
    assert card["name"] == "Zundar EEXTH1000U" and "192.168.0.100:502" in card["summary"]


def test_connection_errors_are_explained():
    """03.11.2026: «отверг запрос» на 192.168.0.100:502 - устройство есть, порт закрыт; это надо сказать прямо."""
    import socket as socket_module

    from ui.qml.climate_chamber import tcp_error_text, tcp_outcome

    refused = ConnectionRefusedError(10061, "отверг")
    assert tcp_outcome(refused) == "refused"
    assert "ответило, но порт 502 закрыт" in tcp_error_text(refused, "192.168.0.100", 502)
    assert tcp_outcome(socket_module.timeout("timed out")) == "timeout"
    assert "никто не ответил" in tcp_error_text(socket_module.timeout(), "192.168.0.100", 502)
    unreachable = OSError(10065, "недоступный узел")
    unreachable.winerror = 10065
    assert "Настроить сеть ноутбука" in tcp_error_text(unreachable, "192.168.0.100", 502)


def test_scan_finds_the_controller_on_another_port(controller):
    """На пульте порт не 502: поиск находит порт, на котором камера отвечает как Modbus, и берёт его себе."""
    driver = ZundarChamber("127.0.0.1", 502, 0)
    driver.SCAN_PORTS = (502, controller.port)
    found = driver.scan()
    assert found == {"host": "127.0.0.1", "port": controller.port, "unit": 0,
                     "text": f"камера найдена: 127.0.0.1, порт {controller.port}, станция 0"}
    assert driver.read().actual_c == 23.0, "драйвер сразу работает с найденным портом"
    driver.close()


def test_scan_releases_its_own_connection_first(controller):
    """Контроллер держит одно подключение: 05.11.2026 при «связь есть» поиск получал отказ на всех портах."""
    driver = _driver(controller)
    driver.RELEASE_WAIT_S = 0.05
    assert driver.read().actual_c == 23.0  # подключение занято опросом
    driver.SCAN_PORTS = (controller.port,)
    found = driver.scan()
    assert found is not None and found["port"] == controller.port, driver.scan_hint
    assert driver.read().actual_c == 23.0, "после поиска опрос идёт снова"
    driver.close()


def test_scan_says_the_device_is_there_but_modbus_is_not():
    """Устройство отвечает, но все порты Modbus закрыты: так и сказать, и что сделать на пульте."""
    import socket as socket_module

    probe = socket_module.socket()
    probe.bind(("127.0.0.1", 0))
    free = probe.getsockname()[1]
    probe.close()
    driver = ZundarChamber("127.0.0.1", free, 0)
    driver.SCAN_PORTS = (free,)
    assert driver.scan() is None
    assert "на связи, но ни один порт Modbus у него не открыт" in driver.scan_hint
    assert "выключите и включите камеру" in driver.scan_hint


def _panel_memory(fake):
    """05.11.2026: что ответило по 192.168.0.1, станция 255 - не AZ1000 по его карте (22,7 °C - в 000D)."""
    for address in range(0x0000, 0x0200):
        fake.regs[address] = 0
    fake.regs.update({0x0001: 1, 0x000C: 10, 0x000D: 227, 0x000E: 1000, 0x000F: 230, 0x0011: 230, 0x001C: 35})


def test_foreign_register_map_is_not_shown_as_the_chamber(controller):
    """Не та карта: ни +0,0 °C, ни «авария 35», и ничего в неё не пишется."""
    _panel_memory(controller)
    driver = _driver(controller)
    reading = driver.read()
    assert reading.actual_c is None and reading.alarm is None and reading.setpoint_c is None
    assert "не контроллер AZ1000" in reading.details["suspect"] and "пределы аварии 0 и 0" in reading.details["suspect"]
    writes = len(controller.frames)
    with pytest.raises(ChamberError, match="не отправлены"):
        driver.set_setpoint(30.0)
    with pytest.raises(ChamberError, match="не отправлены"):
        driver.set_running(False)
    assert all(frame[7] == 3 for frame in controller.frames[writes:]), "записей в чужую память нет"
    assert driver.raw("r 000D 3") == "000D=227 000E=1000 000F=230", "строка для проверки на месте работает"
    driver.close()


def test_scan_does_not_take_a_foreign_device(controller):
    _panel_memory(controller)
    driver = ZundarChamber("127.0.0.1", 502, 0)
    driver.SCAN_PORTS = (controller.port,)
    assert driver.scan() is None
    assert f"127.0.0.1:{controller.port} (станция 0)" in driver.scan_hint and "не как контроллер AZ1000" in driver.scan_hint
    assert driver.port == 502, "чужое устройство в настройки не попало"


def test_foreign_map_blocks_the_run(tmp_path):
    import time

    from tests.test_climate_supervisor import _SupStub
    from ui.qml.climate_chamber import ChamberReading

    stub = _SupStub(tmp_path)
    stub._climate_link = None
    assert stub._climate_set("driver", "zundar_az1000")
    suspect = "по 192.168.0.1:502, станция 255, отвечает не контроллер AZ1000 по своей карте регистров (...)"
    stub._climate_reading = ChamberReading(details={"suspect": suspect, "lan_control": None})
    stub._climate_last_ok_s = time.monotonic()
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert not checks["zundar_map"]["ok"] and checks["zundar_map"]["level"] == "block"
    assert "lan_control" not in checks, "«управление по сети запрещено» из чужой памяти не показывается"
    stub._climate_queue_state({"kind": "reading", "ok": True, "reading": stub._climate_reading})
    stub._climate_take_incoming(time.monotonic())
    assert stub._climate_status.startswith("Связь есть, но по 192.168.0.1")


def test_scan_result_is_saved_in_settings(tmp_path):
    from tests.test_climate_supervisor import _SupStub

    stub = _SupStub(tmp_path)
    stub._climate_link = None
    assert stub._climate_set("driver", "zundar_az1000")
    stub._climate_take_scan({"kind": "scan", "ok": True, "done": True, "text": "найдена",
                             "found": {"host": "192.168.0.123", "port": 503, "unit": 1, "text": "найдена"}})
    settings = stub._climate_settings
    assert (settings["zundar_host"], settings["zundar_port"], settings["zundar_unit"]) == ("192.168.0.123", 503, 1)
    assert "Настройки сохранены" in stub._climate_scan_status
