"""Команды Zundar из списка в окне: выбрать, вписать значение, «Отправить», ответ словами.

Тесты закрепляют:
- строка собирается по каталогу: °C, % и °C/мин переводятся в единицы регистра (×10), со знаком;
  значения вне пределов и не числа не уходят;
- ответ расшифровывается по карте команды: у панели и контроллера по одному адресу разное;
  запись в панель помечена «принимает, но не выполняет»;
- несколько записей через «;» идут по очереди (сброс аварии импульсом 1 → 0);
- запись во время прогона - только на паузе, уставка - в пределах уставки из настроек;
- в окне для Zundar - этот список, у каждой команды подпись, раздел и шаблон.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from tests.test_zundar import _Az1000, _driver, controller  # noqa: F401 - фикстура
from ui.qml.climate_chamber import (ZUNDAR_COMMANDS, ChamberError, build_zundar_command, describe_zundar_answer)


def test_lines_are_built_in_register_units():
    assert build_zundar_command("p_block") == "r 0000 18"
    assert build_zundar_command("a_setpoint", {"temp": "25,5"}) == "w 002E 255"
    assert build_zundar_command("a_setpoint", {"temp": "-40"}) == "w 002E -400"
    assert build_zundar_command("a_tr_rate", {"rate": "1"}) == "w 0026 10"
    assert build_zundar_command("a_humidity", {}) == "w 002F 0"
    with pytest.raises(ChamberError, match="от -100 до 200"):
        build_zundar_command("a_setpoint", {"temp": "500"})
    with pytest.raises(ChamberError, match="не число"):
        build_zundar_command("a_setpoint", {"temp": "abc"})
    with pytest.raises(ChamberError, match="нет такой команды"):
        build_zundar_command("nope")


def test_answers_are_explained_by_the_command_map():
    panel = describe_zundar_answer("panel", "r 0000 18",
                                   "0000=3 0001=0 000C=48 000D=247 000E=950 000F=300 0010=0 0011=300")
    assert "состояние работа" in panel and "температура в камере +24,7 °C" in panel
    assert "рабочая уставка +30,0 °C" in panel and "уставка, введённая на пульте +30,0 °C" in panel
    controller_text = describe_zundar_answer("az1000", "r 0001 28",
                                             "0001=2 0002=1 0003=1 0004=65136 0006=65136 001C=9999")
    assert "состояние работа" in controller_text and "AZ1000-TH" in controller_text
    assert "режим постоянный" in controller_text and "температура в камере -40,0 °C" in controller_text
    assert "авария нет" in controller_text
    written = describe_zundar_answer("az1000", "w 002E -400", "002E <- -400: записано", read_only=True)
    assert "уставка температуры постоянного режима = -40,0 °C записано" in written
    assert "не выполняет" in written
    assert describe_zundar_answer("az1000", "r 0100 2", "0100=1 0101=2") == ""


def test_several_writes_go_in_order(controller):  # noqa: F811
    driver = _driver(controller)
    answer = driver.raw("w 001D 1; w 001D 0")
    assert answer == "001D <- 1: записано; 001D <- 0: записано"
    writes = [frame for frame in controller.frames if frame[7] == 6]
    assert [frame[-2:] for frame in writes] == [b"\x00\x01", b"\x00\x00"]
    driver.close()


def _zundar_stub(tmp_path):
    from tests.test_climate_supervisor import _SupStub, _feed

    stub = _SupStub(tmp_path)
    stub._climate_settings["driver"] = "zundar_az1000"
    _feed(stub, time.monotonic())
    return stub


def test_window_sends_and_explains(tmp_path: Path):
    stub = _zundar_stub(tmp_path)
    commands = stub._climate_view()["commands"]
    assert [item["key"] for item in commands] == [item["key"] for item in ZUNDAR_COMMANDS]
    assert all(item["title"] and item["group"] and item["command"] for item in commands)
    setpoint = next(item for item in commands if item["key"] == "a_setpoint")
    assert setpoint["setting"] and setpoint["params"][0]["scale"] == 10
    assert stub._climate_send_espec("p_temp", "")
    assert stub._climate_link.commands[-1] == ("raw", "r 000D 1")
    stub._climate_queue_state({"kind": "raw", "ok": True, "sent": "r 000D 1", "text": "000D=247"})
    stub._climate_take_incoming(time.monotonic())
    assert stub._climate_raw_log[0]["explain"] == "температура в камере +24,7 °C"
    assert stub._climate_send_espec("a_setpoint", '{"temp": "30"}')
    assert stub._climate_link.commands[-1] == ("raw", "w 002E 300")


def test_writes_respect_limits_and_the_run(tmp_path: Path):
    stub = _zundar_stub(tmp_path)
    stub._climate_settings["min_c"], stub._climate_settings["max_c"] = -40.0, 85.0
    sent = len(stub._climate_link.commands)
    assert not stub._climate_send_espec("a_setpoint", '{"temp": "120"}')
    assert "вне допустимых пределов" in stub._climate_command_status
    stub._climate_run_stage = "settle"
    assert not stub._climate_send_espec("a_start", "")
    assert "Идёт автоматический прогон" in stub._climate_command_status
    assert stub._climate_send_espec("p_block", ""), "чтение во время прогона можно"
    assert len(stub._climate_link.commands) == sent + 1
