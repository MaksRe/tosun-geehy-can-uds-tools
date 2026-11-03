"""Камера, которая почти не охлаждает (Vötsch VT 7100, 02.11.2026), на имитаторе.

Тот прогон: уставка -20 °C принята, а воздух шёл вниз 0,14...0,02 °C/мин и встал около 0 °C;
«не идёт к уставке» не сработало (за 20 мин приближение всё ещё больше 1 °C), узлы пропускал
человек, а в конце камера 2 часа остывала сама с +77 °C без единого предупреждения.

Тесты закрепляют:
- на узле - прямое сообщение «камера почти не охлаждает» с её скоростью за 15 мин и тем, что
  проверить, задолго до «не вышла на уставку за 120 мин»;
- то же - на возврате камеры в конце прогона;
- исправная камера таких сообщений не даёт;
- правило «пропустить узел, если камера не вышла на него за N мин»: узел без точки, прогон
  идёт дальше и доходит до конца; в итоге узел - в списке «без точки»;
- по умолчанию (0) прогон ждёт, как раньше, и правило есть в сценарии.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_climate_supervisor import _ready, _walk
from ui.qml import climate_scenario as cs


def _broken(stub, ramp=0.1, floor=0.0):
    """Холодильник почти не работает: охлаждение не быстрее ramp и не ниже floor."""
    stub.sim.cool_ramp_c_per_min = ramp
    stub.sim.cooling_floor_c = floor


def _texts(stub, word):
    """События с этим словом; сводки (в них открытые проблемы повторяются целиком) - не в счёт."""
    return [text for _level, text in stub.events if word in text and not text.startswith("сводка")]


def test_weak_cooling_is_named_long_before_the_reach_timeout(tmp_path: Path):
    stub = _ready(tmp_path, "25, -20")
    _broken(stub)
    assert stub._climate_run_start(), stub._climate_run_status
    try:
        _walk(stub, limit=400)  # 400 x 30 с = 3 ч 20 мин: узел -20 так и не пройден
    except AssertionError:
        pass
    alerts = _texts(stub, "почти не охлаждает")
    assert len(alerts) == 1, stub.events
    assert "узел -20,0 °C" in alerts[0] and "холодильн" in alerts[0] and "-0,1" in alerts[0]
    # Сообщение пришло намного раньше, чем «не вышла на уставку за 120 мин».
    events = [text for _level, text in stub.events]
    first_alert = events.index(alerts[0])
    timeout = [index for index, text in enumerate(events) if "не вышла на" in text]
    assert timeout and first_alert < timeout[0]
    assert stub._climate_run_stage == "reach" and stub._climate_run_index == 1, "по умолчанию прогон ждёт"


def test_healthy_chamber_gives_no_such_alerts(tmp_path: Path):
    stub = _ready(tmp_path, "25, -40, 85")
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    assert not _texts(stub, "почти не охлаждает") and not _texts(stub, "почти не греет"), stub.events


def test_unreached_node_is_skipped_by_the_rule_and_the_run_finishes(tmp_path: Path):
    stub = _ready(tmp_path, "25, -20, 50")
    stub._climate_settings["skip_unreached_min"] = 60.0
    _broken(stub, ramp=0.1, floor=0.0)
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    skipped = _texts(stub, "пропущен без точки")
    assert len(skipped) == 1 and "-20,0 °C" in skipped[0] and "за 60 мин" in skipped[0], stub.events
    assert [node for node, _seconds in stub._climate_auto_skipped] == [-20.0]
    assert any("50,0" in text and "пройден" in text for _level, text in stub.events), "узел +50 снят после пропуска"
    summary = [text for _level, text in stub.events if text.startswith("ИТОГ")]
    assert summary and "Без точки" in summary[0] and "-20,0 °C" in summary[0]


def test_weak_cooling_on_the_return_at_the_end_is_named(tmp_path: Path):
    stub = _ready(tmp_path, "25, 85")
    stub._climate_settings["finish_setpoint"] = 25.0
    assert stub._climate_run_start(), stub._climate_run_status
    original = stub._climate_run_finish

    def finish(now=None):
        # Холодильник отказал к концу прогона: возврат к +25 идёт сам, как 03.11.2026.
        _broken(stub, ramp=0.15, floor=None)
        original(now)

    stub._climate_run_finish = finish
    _walk(stub)
    alerts = _texts(stub, "почти не охлаждает")
    assert len(alerts) == 1 and "возврат камеры в конце прогона" in alerts[0], stub.events


def test_skip_rule_is_in_the_scenario_and_waits_by_default():
    clean, problems = cs.normalize(cs.board_cycle_scenario())
    assert problems == [] and clean["skip_unreached_min"] == 0.0
    clean, problems = cs.normalize({"name": "проба", "skip_unreached_min": "90", "steps": [{"temp": 25}]})
    assert problems == [] and clean["skip_unreached_min"] == 90.0
    assert any(key == "skip_unreached_min" for key, _title, _unit in cs.DIFF_GENERAL)
