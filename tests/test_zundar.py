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
