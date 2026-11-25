"""Проверки независимости сценария, числа плат и выбора климатической камеры."""

import time

import pytest

import chamber_fit
from tests.test_multiboard import BOARDS, _stub, _walk
from ui.qml import climate_scenario
from ui.qml.climate_chamber import (
    DRIVER_ESPEC, DRIVER_SIMCON, DRIVER_ZUNDAR, DRIVER_MODBUS_TCP, DRIVER_MODBUS_RTU,
)


CAMERAS = (DRIVER_ESPEC, DRIVER_SIMCON, DRIVER_ZUNDAR, DRIVER_MODBUS_TCP, DRIVER_MODBUS_RTU)


def _configured(tmp_path, driver, scenario="board_cycle"):
    """Для проверки без оборудования выбирает камеру и готовит три платы с нужным сценарием."""
    stub = _stub(tmp_path, temps=[node / 10 for node in chamber_fit.NODES_X10])
    stub._climate_settings["driver"] = driver
    stub._chamber_test_mode = False
    assert stub._climate_scenario_new(scenario)
    stub._climate_scenario["auto_write"] = False
    stub._chamber_auto_write = False
    # Для добора и второго этапа подготавливает журналы платы во всех температурных узлах.
    if scenario in ("refill", "assembly"):
        for sa, *_ in BOARDS:
            with stub._mb_context(sa, notify=False):
                stub._chamber_points = [
                    {"note": "0/0", "board_temp_x10": node, "fuel_temp_x10": node,
                     "main": 5000, "media": 4500, "time": "12:00:00"}
                    for node in chamber_fit.NODES_X10
                ]
    return stub


@pytest.mark.parametrize("driver", CAMERAS)
@pytest.mark.parametrize("scenario", ("board_cycle", "refill", "assembly", "check"))
def test_each_camera_starts_each_ready_scenario(tmp_path, driver, scenario):
    """Чтобы модель камеры не запрещала этап, проверяет запуск всех готовых сценариев с тремя платами."""
    stub = _configured(tmp_path, driver, scenario)
    assert not stub._climate_auto_blockers(), stub._climate_auto_blockers()
    assert stub._climate_auto_view()["canStart"]
    assert stub._climate_run_start(), stub._climate_run_status
    assert stub._mb_run_sas == [sa for sa, *_ in BOARDS]
    assert stub._chamber_board_only == stub._climate_scenario["board_only"]
    assert stub._climate_mode_hint() == ""


def test_weiss_completes_board_cycle_for_three_bare_boards(tmp_path):
    """Для случая пользователя проводит три платы без трубок через семь узлов с выбранной Weiss."""
    stub = _configured(tmp_path, DRIVER_SIMCON)
    assert stub._climate_run_start(), stub._climate_run_status
    assert stub._chamber_board_only and stub._climate_steer_key() == "board_temp"
    _walk(stub)
    files = set()
    for sa, *_ in BOARDS:
        with stub._mb_context(sa, notify=False):
            assert len(stub._chamber_points) == 7
            assert all(point["note"] == "0/0" for point in stub._chamber_points)
            assert {chamber_fit.nearest_node(point["board_temp_x10"]) for point in stub._chamber_points} == set(chamber_fit.NODES_X10)
            files.add(stub._chamber_file_path)
    assert len(files) == 3


def test_selected_scenario_overrides_previous_stage_in_preflight(tmp_path):
    """Чтобы прошлый этап не блокировал новый, проверяет второй этап при оставшемся флаге «Только плата»."""
    stub = _configured(tmp_path, DRIVER_ESPEC, "assembly")
    stub._chamber_board_only = True
    checks = {check["key"]: check for check in stub._climate_auto_checks()}
    assert checks["stage2"]["ok"], checks["stage2"]["text"]
    assert not stub._climate_auto_blockers()
    assert stub._climate_run_start()
    assert not stub._chamber_board_only and stub._climate_steer_key() == "fuel_temp"


def test_scenario_requirements_still_block_unprepared_assembly(tmp_path):
    """Чтобы разрешение любой камеры не обходило подготовку, запрещает второй этап без журналов плат."""
    stub = _configured(tmp_path, DRIVER_SIMCON, "assembly")
    for sa, *_ in BOARDS:
        with stub._mb_context(sa, notify=False):
            stub._chamber_points = []
    assert any("журнал первого этапа" in text for text in stub._climate_auto_blockers())
    assert not stub._climate_run_start()


def test_weiss_still_blocks_lost_link_and_out_of_range_plan(tmp_path):
    """Чтобы сохранить технические ограничения, проверяет запрет старта без связи и вне диапазона камеры."""
    stub = _configured(tmp_path, DRIVER_SIMCON)
    stub._climate_last_ok_s = time.monotonic() - 1000
    assert any("Нет связи с камерой" in text for text in stub._climate_auto_blockers())
    assert not stub._climate_run_start()
    stub._climate_last_ok_s = time.monotonic()
    stub._climate_scenario["steps"] = [climate_scenario.new_step(190)]
    assert any("выходит за пределы" in text for text in stub._climate_auto_blockers())
    assert not stub._climate_run_start()
