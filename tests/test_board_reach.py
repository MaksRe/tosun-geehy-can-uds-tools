"""Проверки доводки платы до температуры шага.

Плата греется сама и устаивается не там, где воздух камеры: при -40 °C в
камере она может стоять на -34 °C, и точка тогда не попадает в узел -40.
Тесты закрепляют:
- плата с самонагревом доводится сдвигом уставки камеры, и точки сняты у
  температуры шага в пределах допуска;
- сторож прогона не считает сдвинутую уставку ошибкой и не «возвращает» её;
- если сдвиг ограничен и попытки не помогли, предупреждение уходит в события и
  журнал действий, точка снимается при текущих условиях, прогон идёт дальше;
- шаг без точки не доводится.
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_climate_supervisor import _ready, _walk
from ui.qml.control_log import ControlLog


def _boards(stub) -> list[float]:
    return [point["board_temp_x10"] / 10.0 for point in stub._chamber_points]


def _run(tmp_path: Path, nodes: str, heating: float, **settings):
    stub = _ready(tmp_path, nodes)
    stub._control_log = ControlLog(tmp_path / "control")
    stub.sim.self_heating_c = heating
    # Пределы уставки шире, чем нужно доводке: упор в предел проверяется отдельно.
    stub._climate_settings.update({"min_c": -60.0, "max_c": 120.0})
    stub._climate_settings.update(settings)
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub, limit=12000)
    return stub


def test_self_heated_board_is_brought_to_the_step(tmp_path: Path):
    stub = _run(tmp_path, "-40, 25", heating=6.0)
    boards = _boards(stub)
    assert boards, "точки должны быть сняты"
    assert all(abs(board - (-40.0)) <= 1.0 for board in boards[:1]), boards
    assert all(abs(board - 25.0) <= 1.0 for board in boards[-1:]), boards
    setpoints = [value for name, value in stub._climate_link.commands if name == "setpoint"]
    # Сдвиг - на разницу «шаг минус плата»: около -6 °C при самонагреве +6 °C.
    assert any(-47.0 <= value <= -45.5 for value in setpoints) and any(18.0 <= value <= 20.0 for value in setpoints), setpoints
    texts = [text for _level, text in stub.events]
    assert any("довожу" in text and "-40,0 °C → -4" in text for text in texts), texts
    assert not any("задаю узел снова" in text for text in texts), "сторож не должен возвращать уставку к узлу"
    assert not any("не дошла" in text for text in texts)


def test_limited_shift_warns_and_captures_as_is(tmp_path: Path):
    stub = _run(tmp_path, "-40, 25", heating=6.0, board_max_shift_c=3.0)
    boards = _boards(stub)
    assert any(abs(board - (-37.0)) <= 0.7 for board in boards), boards
    texts = [text for _level, text in stub.events]
    missed = [text for text in texts if "плата не дошла до шага -40,0 °C" in text]
    assert missed and "уставку двигать некуда" in missed[0] and "Точка снимается" in missed[0]
    assert any("плата не дошла" in problem for problem in stub._climate_auto_problems)
    assert not stub._climate_run_stage, "прогон должен дойти до конца"
    rows = list(csv.reader(io.StringIO(Path(stub._control_log.current_path).read_text(encoding="utf-8-sig")),
                           delimiter=";"))[1:]
    assert any(row[3] == "доводка платы" and row[5].startswith("не выполнено") for row in rows)
    assert any(row[3] == "доводка платы" and "довожу" in row[5] for row in rows)


def test_setpoint_limit_stops_the_shift(tmp_path: Path):
    """Уставку некуда двигать (предел камеры): предупреждение и точка при текущих условиях."""
    stub = _run(tmp_path, "-40, 25", heating=6.0, min_c=-45.0)
    setpoints = [value for name, value in stub._climate_link.commands if name == "setpoint"]
    assert min(setpoints) == -45.0
    missed = [text for _level, text in stub.events if "плата не дошла до шага -40,0 °C" in text]
    assert missed and "пределах уставки -45...+120 °C" in missed[0], missed


def test_step_without_point_is_not_brought(tmp_path: Path):
    stub = _ready(tmp_path, "-40, 25")
    stub.sim.self_heating_c = 6.0
    assert stub._climate_run_start()
    stub._climate_run_steps[0]["capture"] = False
    _walk(stub, limit=12000)
    setpoints = [value for name, value in stub._climate_link.commands if name == "setpoint"]
    assert min(setpoints) == -40.0, setpoints
