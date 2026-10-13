"""Проверки доводки платы до температуры шага.

Плата греется сама и устаивается не там, где воздух камеры: при -40 °C в
камере она может стоять на -34 °C, и точка тогда не попадает в узел -40.
Тесты закрепляют:
- плата с самонагревом доводится сдвигом уставки камеры, и точки сняты у
  температуры шага в пределах допуска;
- сторож прогона не считает сдвинутую уставку ошибкой и не «возвращает» её;
- если сдвиг ограничен и попытки не помогли, предупреждение уходит в события и
  журнал действий, точка снимается при текущих условиях, прогон идёт дальше;
- шаг без точки не доводится;
- у инертной платы (τ - десятки минут) предел считается по кривой заранее, и
  доводка начинается по прогнозу, не дожидаясь часами её «устаивания»;
- «плата не догоняет воздух» - только если плата почти не движется к нему;
- модель «воздух → плата» по ходу прогона: доводка ставит уставку сразу по ней
  (плата проходит лишь часть изменения воздуха), а следующие шаги начинаются с
  упреждённой уставки и доводка им не нужна.
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import math
import random

from tests.test_climate_supervisor import _ready, _walk
from ui.qml.controller.stability import air_for_board, fit_board_model, predict_final
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
    # Самонагрев 8 °C: даже при уставке -45 плата стоит около -37 - за допуском.
    stub = _run(tmp_path, "-40, 25", heating=8.0, min_c=-45.0)
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


def test_forecast_finds_where_a_slow_board_settles():
    """Экспонента с τ 80 мин и шумом датчика: через полчаса предел известен с точностью до полуградуса."""
    rnd = random.Random(1)

    def samples(minutes):
        return [(i * 10.0, round(-35 + 20 * math.exp(-i * 10.0 / 4800.0) + rnd.uniform(-0.05, 0.05), 1))
                for i in range(int(minutes * 6))]

    assert predict_final(samples(15), 0.0, 900.0) is None, "на коротком отрезке прогноз - шум"
    final, tau = predict_final(samples(35), 0.0, 35 * 60.0)
    assert abs(final - (-35.0)) <= 0.5 and 3600 <= tau <= 6000
    flat = [(i * 10.0, -40.0 + rnd.uniform(-0.05, 0.05)) for i in range(300)]
    assert predict_final(flat, 0.0, 3000.0) is None, "ровная температура - не подход к пределу"


def test_slow_board_is_brought_by_forecast(tmp_path: Path):
    stub = _ready(tmp_path, "-40, 25")
    stub._climate_settings.update({"min_c": -60.0, "max_c": 120.0})
    stub.sim.PRODUCT_TAU_MIN = 60.0
    stub.sim.self_heating_c = 5.0
    assert stub._climate_run_start()
    _walk(stub, limit=20000)
    texts = [text for _level, text in stub.events]
    assert any("по прогнозу устоится" in text and "довожу" in text for text in texts), texts
    assert all(abs(board - node) <= 1.0 for board, node in zip(_boards(stub), (-40.0, 25.0))), _boards(stub)
    assert not any("не догоняет" in text for text in texts), "инертная плата идёт к воздуху - это не беда"


def test_board_far_and_still_is_reported(tmp_path: Path):
    """Плата стоит на 15 °C теплее воздуха и не движется: предупреждение «не догоняет»."""
    stub = _ready(tmp_path, "-40, 25")
    stub._climate_settings.update({"board_max_shift_c": 0.0})
    stub.sim.self_heating_c = 15.0
    assert stub._climate_run_start()
    _walk(stub, limit=20000)
    assert any("не догоняет" in text for _level, text in stub.events)


def test_board_model_from_the_stand():
    """Числа со стенда: при +25 плата +30, при -40 около -27, при -50 - -35,7."""
    model = fit_board_model([(25.0, 30.0), (-40.0, -27.0), (-50.0, -35.7)])
    assert abs(model[0] - 0.876) < 0.01
    assert abs(air_for_board(model, -40.0) - (-54.9)) < 0.3
    single = fit_board_model([(25.0, 30.0)])
    assert single[0] == 1.0 and air_for_board(single, -40.0) == -45.0, "одна точка - только сдвиг"
    assert fit_board_model([(25.0, 30.0), (26.0, 10.0)])[0] == 1.0, "узкий размах - наклону не верим"


def test_leaky_board_needs_no_bringing_after_the_model_is_known(tmp_path: Path):
    """Плату тянет к комнате на 12 % (кабель): после первого холодного шага остальные - сразу с нужной уставкой."""
    stub = _ready(tmp_path, "25, -40, -20, 85")
    stub._climate_settings.update({"min_c": -70.0, "max_c": 120.0})
    stub.sim.leak = 0.12
    stub.sim.self_heating_c = 2.0
    assert stub._climate_run_start()
    _walk(stub, limit=30000)
    boards = _boards(stub)
    assert all(abs(board - node) <= 1.0 for board, node in zip(boards, (25.0, -40.0, -20.0, 85.0))), boards
    texts = [text for _level, text in stub.events]
    presets = [text for text in texts if text.startswith("упреждение")]
    assert any("вместо -20,0 °C" in text for text in presets) and any("вместо +85,0 °C" in text for text in presets)
    brought = [text for text in texts if "довожу" in text]
    assert not any("шаг -20,0 °C" in text or "шаг +85,0 °C" in text for text in brought), brought
    # Доводка на холодном шаге - по модели, с запасом на неполную передачу: одной попытки хватает.
    assert sum("шаг -40,0 °C" in text for text in brought) == 1, brought


def test_jittery_board_sensor_still_settles(tmp_path: Path):
    """Плата стоит на -35,7, а датчик скачет на ±0,2 °C: по средним за окно плата устоялась (так было на стенде)."""
    import time as _time

    from tests.test_climate_run import _ClimateStub
    from ui.qml.controller.stability import is_stable, rate_and_spread

    stub = _ClimateStub(tmp_path)
    rnd = random.Random(7)
    start = _time.monotonic()
    for index in range(80):
        stamp = start + index * 5.0
        for part in range(10):
            stub._chamber_live_note("board_temp", -357 + rnd.choice((-2, -1, 0, 1, 2)), stamp - 4.5 + part * 0.5)
        stub._climate_note_board(stamp)
    now = start + 79 * 5.0
    result = rate_and_spread(stub._climate_board, now, 300.0)
    assert is_stable(result, 300.0, 0.05, stub.CLIMATE_STABLE_SPREAD_C), result
    raw = [-35.7 + rnd.choice((-0.2, -0.1, 0.0, 0.1, 0.2)) for _ in range(60)]
    assert max(raw) - min(raw) >= 0.3, "по одиночным показаниям разброс не прошёл бы правило"
