"""Камера со своей программой на пульте (Zundar через сенсорную панель): прогон следует за ней.

06.11.2026 у Zundar EEXTH1000U по сети отвечает только сенсорная панель: читать можно, а уставку
и пуск она молча не принимает. Шаги задают на пульте, а прогон узнаёт узел по рабочей уставке
камеры, ждёт устаивания платы, снимает точки и говорит, когда шаг можно пропустить.

Тесты закрепляют:
- карта панели: температура 000D, рабочая уставка 0011, состояние 0000 (3 - работа); только чтение;
  «Найти камеру» берёт панель с пометкой «только чтение»;
- прогон по программе пульта: каждый узел - по уставке камеры, точки сняты, в камеру ничего не пишется,
  «узел снят - можно переводить дальше», в конце камера не останавливается;
- камера ушла с узла раньше точки - узел без точки и совет увеличить выдержку, прогон идёт дальше;
- шаг пульта, которого нет в сценарии, пропускается; узел, которого нет в программе камеры, - без точки;
- плата не дошла до шага - вместо сдвига уставки подсказка, что поставить на пульте;
- проверка перед стартом не запрещает прогон, а в окне - программа для пульта.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from tests.test_climate_supervisor import _ready, _walk
from tests.test_zundar import _Az1000
from ui.qml.climate_chamber import ChamberError, ZundarChamber


def _texts(stub, word):
    return [text for _level, text in stub.events if word in text and not text.startswith("сводка")]


def _follow(tmp_path, nodes, program, **sim):
    stub = _ready(tmp_path, nodes)
    for key, value in sim.items():
        setattr(stub.sim, key, value)
    stub.sim.use_program(program)
    assert stub._climate_run_start(), stub._climate_run_status
    assert stub._climate_run_follow
    return stub


# ---------------------------------------------------------------- карта панели

@pytest.fixture()
def panel():
    fake = _Az1000()
    for address in range(0x0000, 0x0200):
        fake.regs[address] = 0
    # Как ответила панель 05.11.2026 у камеры: ожидание, 22,7 °C, введено 30,0, рабочая 23,0.
    fake.regs.update({0x0000: 2, 0x000C: 48, 0x000D: 227, 0x000E: 1000, 0x000F: 300, 0x0011: 230, 0x001C: 35})
    yield fake
    fake.close()


def test_panel_map_is_read_and_is_read_only(panel):
    driver = ZundarChamber("127.0.0.1", panel.port, 0)
    reading = driver.read()
    assert reading.actual_c == 22.7 and reading.setpoint_c == 23.0 and reading.running is False
    assert reading.alarm is None and reading.details["panel"] and reading.details["entered_c"] == 30.0
    assert driver.read_only and not driver.can_set and not driver.can_run
    with pytest.raises(ChamberError, match="только читается"):
        driver.set_setpoint(30.0)
    panel.regs[0x0000] = 3
    panel.regs[0x0011] = 300
    reading = driver.read()
    assert reading.running is True and reading.setpoint_c == 30.0
    driver.close()


def test_scan_takes_the_panel_as_read_only(panel):
    driver = ZundarChamber("127.0.0.1", 502, 0)
    driver.RELEASE_WAIT_S = 0.05
    driver.SCAN_PORTS = (panel.port,)
    found = driver.scan()
    assert found is not None and found["port"] == panel.port and "только чтение" in found["text"], driver.scan_hint


# ---------------------------------------------------------------- прогон за камерой

def test_run_follows_the_chamber_program(tmp_path: Path):
    stub = _follow(tmp_path, "25, -20, 50", [(25.0, 180.0), (-20.0, 240.0), (50.0, 240.0)])
    _walk(stub)
    assert stub._climate_run_done == [25.0, -20.0, 50.0], stub.events
    assert not [command for command in stub._climate_link.commands if command[0] in ("setpoint", "run")], \
        "в камеру ничего не пишется"
    assert len(_texts(stub, "камера по своей программе на уставке")) == 3
    done = _texts(stub, "снят: точки записаны")
    assert len(done) == 3 and "к следующему шагу (-20,0 °C)" in done[0] and "последний узел" in done[-1]
    assert _texts(stub, "программу камеры на пульте можно остановить")
    assert not stub._climate_run_paused and not _texts(stub, "пропущен без точки")


def test_chamber_leaving_a_node_too_early_is_named(tmp_path: Path):
    stub = _follow(tmp_path, "25, -20", [(25.0, 3.0), (-20.0, 240.0)])
    _walk(stub)
    left = _texts(stub, "пропущен без точки")
    assert len(left) == 1 and "+25,0 °C" in left[0] and "увеличьте выдержку" in left[0], stub.events
    assert stub._climate_run_done == [-20.0]
    assert [node for node, _seconds in stub._climate_auto_skipped] == [25.0]


def test_extra_chamber_step_and_missing_node(tmp_path: Path):
    # На пульте лишний шаг +10 (его нет в сценарии), а узла 0 нет в программе камеры.
    stub = _follow(tmp_path, "25, 0, -20", [(25.0, 180.0), (10.0, 30.0), (-20.0, 240.0)])
    _walk(stub)
    assert _texts(stub, "камера держит +10,0 °C: такого узла среди оставшихся нет"), stub.events
    skipped = _texts(stub, "пропущены без точек")
    assert len(skipped) == 1 and "+0,0 °C" in skipped[0]
    assert stub._climate_run_done == [25.0, -20.0]


def test_board_off_the_node_gets_a_hint_for_the_panel(tmp_path: Path):
    stub = _follow(tmp_path, "25, -20", [(25.0, 240.0), (-20.0, 300.0)], self_heating_c=4.0)
    _walk(stub)
    hints = _texts(stub, "поставьте этот шаг на пульте")
    assert hints and "плата не дошла до шага" in hints[0], stub.events
    assert not _texts(stub, "довожу - уставка камеры"), "уставку программа не двигает"


def test_checks_and_plan_for_the_panel(tmp_path: Path):
    stub = _ready(tmp_path, "25, -40, 85")
    stub.sim.use_program([(25.0, 60.0)])
    stub._climate_settings["warm_ramp_c_min"] = 1.0
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert not checks["can_set"]["ok"] and checks["can_set"]["level"] == "warn"
    assert "программе для пульта" in checks["can_set"]["text"]
    view = stub._climate_view()["run"]
    assert view["follow"] and view["followPlan"][0] == "Шаг 1: +25,0 °C, выдержка 150 мин"
    assert any("TR: Вкл, 1 °C/мин" in row for row in view["followPlan"])
    assert any("пропустить на пульте" in row for row in view["followPlan"])


def test_resumed_run_still_follows(tmp_path: Path):
    """Перезапуск программы посреди прогона: прогон снова следует за камерой, в камеру не пишет."""
    from tests.test_climate_supervisor import _SupStub, _feed

    stub = _follow(tmp_path, "25, -20", [(25.0, 180.0), (-20.0, 240.0)])
    now = time.monotonic()
    stub._climate_auto_save(now)
    again = _SupStub(tmp_path)
    again.sim.use_program([(25.0, 180.0), (-20.0, 240.0)])
    _feed(again, now)
    assert again._climate_auto_resume_now(now)
    assert again._climate_run_follow
    again._climate_run_tick(now + 1)
    assert again._climate_run_stage == "follow" and not again._climate_link.commands
