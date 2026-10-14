"""Проверки прогона по разбору стенда 13-14.10.2026 (ESPEC MC-811P, одна плата 0/0).

Что случилось на стенде и что тесты закрепляют:
- шаг -40 °C: после трёх доводок (уставка до -56,3) плата стояла на -38,6...-39,6
  (шум датчика), правило «устоялась» три часа не выполнялось, прогон висел -
  теперь при малой скорости три окна подряд плата считается устоявшейся;
- плата так и не устаивается - по истечении «предупредить, если не устоялась за»
  решение принимается по текущему среднему, прогон не висит;
- шаг +85 °C: датчик платы (шкала прошивки была -40...+85) упёрся в +85,0, и
  это сочлось попаданием - теперь показание на пределе шкалы попаданием не
  считается, уставка уводится внутрь шкалы, цель у края - на 0,5 °C внутрь;
- шкала прошивки расширена до -55...+125: узлы -40 и +85 внутри, цель - сам узел;
- конец прогона: камеру остановили сразу после уставки +25, и она остывала сама
  часами - теперь сначала выход на +25, потом остановка;
- ход прогона по времени пишется в CSV для разбора.
"""

from __future__ import annotations

import csv
import io
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_climate_supervisor import _ready, _walk


def _run(tmp_path: Path, nodes: str, **settings):
    stub = _ready(tmp_path, nodes)
    stub._project_root_directory = tmp_path
    stub._climate_settings.update({"min_c": -70.0, "max_c": 120.0})
    stub._climate_settings.update(settings)
    return stub


def _with_sensor(stub, noise_c=0.0, wave_c=0.0, wave_min=20.0, seed=3, scale=(-55.0, 125.0)):
    """Датчик платы прибора: шкала прошивки (по умолчанию -55...+125), шум и медленные колебания."""
    rnd = random.Random(seed)
    stub.BOARD_SENSOR_RANGE_C = scale
    original = stub.sim.read

    def read():
        reading = original()
        value = reading.product_c + rnd.uniform(-noise_c, noise_c)
        value += wave_c * math.sin(2 * math.pi * stub.clock[0] / (wave_min * 60.0))
        reading.product_c = round(min(scale[1], max(scale[0], value)), 1)
        return reading
    stub.sim.read = read


def _boards(stub):
    return [point["board_temp_x10"] / 10.0 for point in stub._chamber_points]


def test_noisy_board_does_not_hang_the_run(tmp_path: Path):
    stub = _run(tmp_path, "25, -40", settle_timeout_min=600.0)
    stub.sim.self_heating_c = 1.0
    _with_sensor(stub, noise_c=0.6)
    assert stub._climate_run_start()
    _walk(stub, limit=20000)
    boards = _boards(stub)
    assert len(boards) == 2 and abs(boards[1] - (-40.0)) <= 1.2, boards
    texts = [text for _level, text in stub.events]
    assert any("колеблется" in text and "в среднем стоит" in text for text in texts), texts


def test_board_that_never_settles_is_decided_by_timeout(tmp_path: Path):
    stub = _run(tmp_path, "25, -20", settle_timeout_min=30.0, board_max_shift_c=0.0)
    _with_sensor(stub, wave_c=1.5, wave_min=12.0)
    assert stub._climate_run_start()
    _walk(stub, limit=20000)
    assert len(stub._chamber_points) == 2
    assert any("не устоялась за 30 мин" in text for _level, text in stub.events)


def test_clamped_sensor_at_plus_85_is_not_a_hit(tmp_path: Path):
    """Прошивка до расширения таблиц: шкала -40...+85, узел +85 на самом краю."""
    stub = _run(tmp_path, "25, 85")
    stub.sim.self_heating_c = 7.0
    _with_sensor(stub, scale=(-40.0, 85.0))
    assert stub._climate_run_start()
    _walk(stub, limit=20000)
    boards = _boards(stub)
    assert boards[-1] < 85.0 and abs(boards[-1] - 84.5) <= 1.0, boards
    texts = [text for _level, text in stub.events]
    assert any("упёрся в предел шкалы" in text for text in texts) or any(
        text.startswith("упреждение") and "+84,5 °C" in text for text in texts), texts


def test_chamber_is_stopped_only_after_reaching_the_finish_setpoint(tmp_path: Path):
    stub = _run(tmp_path, "25, 85", finish_setpoint=25.0, finish_stop=True)
    air_at_stop = []
    original = stub._climate_link.command

    def command(name, value=None):
        if name == "run" and value is False:
            air_at_stop.append(stub.sim.air_c)
        return original(name, value)
    stub._climate_link.command = command
    assert stub._climate_run_start()
    _walk(stub, limit=20000)
    assert air_at_stop and abs(air_at_stop[0] - 25.0) <= 1.5, air_at_stop
    assert any("возвращаю камеру к +25,0 °C" in text for _level, text in stub.events)
    assert "Камера вышла на +25,0 °C" in stub._climate_run_status and "Камера остановлена" in stub._climate_run_status


def test_run_trace_is_written(tmp_path: Path):
    stub = _run(tmp_path, "25, -20")
    assert stub._climate_run_start()
    _walk(stub, limit=20000)
    traces = list((tmp_path / "logs" / "chamber").glob("run_*.csv"))
    assert len(traces) == 1
    rows = list(csv.reader(io.StringIO(traces[0].read_text(encoding="utf-8-sig")), delimiter=";"))
    assert rows[0][:4] == ["Время", "Шаг", "Температура шага (°C)", "Этап"] and len(rows) > 20
    assert {row[3] for row in rows[1:]} >= {"reach", "settle"}


def test_step_left_by_hand_keeps_its_own_time(tmp_path: Path):
    """Шаг -40 оставлен кнопкой «следующий шаг» через 6:47: это время - не шагу -20 и не в оценку остатка."""
    stub = _run(tmp_path, "25, -40, -20")
    assert stub._climate_run_start()
    stub._climate_auto_durations = [(25.0, 1860.0)]
    stub._climate_run_index = 1
    stub._climate_auto_node_start = 1000.0
    stub._climate_auto_on_node_left(-40.0, 1000.0 + 6 * 3600 + 47 * 60, "Max")
    assert stub._climate_auto_skipped == [(-40.0, 24420.0)] and stub._climate_auto_node_start == 1000.0 + 24420.0
    assert any("оставлен без точки через 6:47 (Max)" in text for text in stub._climate_auto_problems)
    assert "Без точки (оставлены вручную): -40,0 °C - 6:47" in stub._climate_auto_nodes_text()
    stub._climate_run_index = 2
    assert stub._climate_auto_eta(stub._climate_auto_node_start) == 1860.0
