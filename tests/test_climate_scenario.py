"""Проверки сценария автоматического прогона.

Сценарий - файл, по которому прогон идёт без человека. Тесты закрепляют:
- готовый сценарий «Испытание платы, один цикл»: 7 узлов, первым +25 °C, «только плата»;
- неверные поля файла заменяются значениями по умолчанию с замечанием, файл не роняет программу;
- сохранение и загрузка дают тот же сценарий, имя файла безопасно для Windows;
- прежние настройки прогона переходят в сценарий без потерь;
- прогон идёт по шагам: свой допуск и окно шага, выдержка, шаг без точки, конец из сценария;
- форма: правка, новый, сохранение, загрузка, список файлов, запрет правки во время прогона,
  текущий сценарий переживает перезапуск.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_climate_supervisor import _feed, _SupStub, _walk
from ui.qml import climate_scenario as cs
from ui.qml.controller.climate_scenario_mixin import AppControllerClimateScenarioMixin


class _ScnStub(AppControllerClimateScenarioMixin, _SupStub):
    """Прогон, сторож и сценарий без Qt."""

    def __init__(self, root: Path):
        from tests.test_climate_run import _ClimateStub

        _ClimateStub.__init__(self, root)
        self._climate_scenario_init()
        self._climate_auto_init()


# ------------------------------------------------------------------ модуль сценария

def test_board_cycle_scenario():
    scenario = cs.board_cycle_scenario()
    clean, problems = cs.normalize(scenario)
    assert problems == []
    assert [step["temp"] for step in clean["steps"]] == [25.0, -20.0, -40.0, 0.0, 50.0, 70.0, 85.0]
    assert [step["hold_min"] for step in clean["steps"]] == [0.0, 0.0, 15.0, 0.0, 0.0, 0.0, 15.0]
    assert (clean["settle_min"], clean["settle_rate"], clean["board_max_shift_c"], clean["board_attempts"]) ==         (12.0, 0.03, 25.0, 4.0)
    assert clean["board_only"] is True and clean["labels"] == ["0/0"] and clean["auto_write"] is True
    assert clean["finish_setpoint"] == 25.0
    assert cs.summary(clean).startswith("7 шагов (+25 → -20 → -40 → +0 → +50 → +70 → +85 °C), точки в 7")


def test_bad_fields_are_replaced_with_notes():
    clean, problems = cs.normalize({
        "name": "проверка", "single_model": "непонятно", "settle_min": "-3",
        "steps": [{"temp": "abc"}, {"temp": "-40", "hold_min": -5, "settle_rate": "0,02", "capture": False},
                  {"temp": 25, "settle_min": ""}],
    })
    assert [step["temp"] for step in clean["steps"]] == [-40.0, 25.0]
    assert clean["steps"][0]["hold_min"] == 0.0 and clean["steps"][0]["settle_rate"] == 0.02
    assert clean["steps"][0]["capture"] is False and clean["steps"][1]["settle_min"] is None
    assert clean["single_model"] == "растяжение" and clean["settle_min"] == 12.0
    text = " | ".join(problems)
    assert "шаг 1, температура" in text and "выдержка" in text and "модель ухода" in text and "settle_min" in text


def test_empty_or_alien_file_is_named():
    clean, problems = cs.normalize({"format": "profile", "steps": []})
    assert any("не похож на сценарий" in text for text in problems)
    assert any("ни одного годного шага" in text for text in problems)
    assert cs.normalize("строка")[1] == ["сценарий не прочитан: ожидался объект JSON"]


def test_save_and_load(tmp_path: Path):
    scenario = cs.board_cycle_scenario()
    scenario["steps"][1]["hold_min"] = 30.0
    path = cs.save(scenario, tmp_path / "дир" / "испытание")
    assert path.name == "испытание.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == "climate_scenario" and data["version"] == 2
    loaded, problems = cs.load(path)
    assert problems == [] and loaded == cs.normalize(scenario)[0]
    assert cs.file_name('Плата: цикл "А"/Б') == "Плата_цикл_А_Б.json"


def test_from_old_settings():
    scenario = cs.from_settings({"run_nodes": "25, -40; 85", "run_labels": "0/0; 150/47", "settle_min": 7.0,
                                 "finish_setpoint": 20.0, "finish_stop": True}, board_only=True, single_model="сдвиг")
    assert [step["temp"] for step in scenario["steps"]] == [25.0, -40.0, 85.0]
    # Одна плата: пометка всегда «0/0», что бы ни было в старых настройках.
    assert scenario["labels"] == ["0/0"] and scenario["settle_min"] == 7.0
    assert scenario["finish_setpoint"] == 20.0 and scenario["finish_stop"] is True
    assert scenario["board_only"] is True and scenario["single_model"] == "сдвиг"


def test_step_value_falls_back_to_general():
    scenario = cs.empty_scenario()
    step = cs.new_step(-40)
    assert cs.step_value(scenario, step, "settle_min") == 12.0
    step["settle_min"] = 20.0
    assert cs.step_value(scenario, step, "settle_min") == 20.0


# ------------------------------------------------------------------ прогон по сценарию

def _scenario_stub(tmp_path, steps, **general):
    stub = _ScnStub(tmp_path)
    scenario = cs.empty_scenario("тест")
    scenario["labels"] = ["0/0"]
    scenario["steps"] = steps
    scenario.update(general)
    stub._climate_scenario_set(scenario, dirty=True)
    stub._chamber_label = "0/0"
    _feed(stub, time.monotonic())
    return stub


def test_run_follows_scenario_steps(tmp_path: Path):
    hold = cs.new_step(30.0)
    hold["hold_min"] = 10.0
    transit = cs.new_step(35.0)
    transit["capture"] = False
    stub = _scenario_stub(tmp_path, [cs.new_step(25.0), hold, transit], finish_setpoint=20.0)
    assert stub._climate_run_start()
    _walk(stub)

    boards = [point["board_temp_x10"] for point in stub._chamber_points]
    assert len(boards) == 2 and abs(boards[0] - 250) <= 2 and abs(boards[1] - 300) <= 2
    texts = " | ".join(stub.kinds())
    assert "выдержка 10 мин" in texts and "точка на этом шаге не снимается" in texts
    setpoints = [value for name, value in stub._climate_link.commands if name == "setpoint"]
    assert setpoints[:3] == [25.0, 30.0, 35.0] and setpoints[-1] == 20.0
    assert len(stub._climate_auto_durations) == 3


def test_step_overrides_settle_window(tmp_path: Path):
    slow = cs.new_step(25.0)
    slow["settle_min"] = 30.0
    stub = _scenario_stub(tmp_path, [slow])
    assert stub._climate_run_start()
    assert stub._climate_run_param("settle_min") == 30.0
    assert stub._climate_run_param("settle_rate") == 0.03


def test_start_applies_scenario_to_the_chamber_run(tmp_path: Path):
    stub = _scenario_stub(tmp_path, [cs.new_step(25.0)], auto_write=False)
    stub._chamber_label = "что-то"
    stub._chamber_auto_write = True
    assert stub._climate_run_start()
    assert stub._chamber_label == "0/0" and stub._chamber_auto_write is False


# ------------------------------------------------------------------ форма и файлы

def test_folder_is_seeded_with_board_cycle(tmp_path: Path):
    stub = _ScnStub(tmp_path)
    names = [item["name"] for item in stub._climate_scenario_view()["files"]]
    assert names == ["Испытание платы, один цикл"]


def test_edit_save_load_cycle(tmp_path: Path):
    stub = _ScnStub(tmp_path)
    scenario = cs.board_cycle_scenario()
    scenario["name"] = "Мой цикл"
    scenario["steps"][0]["hold_min"] = 15
    revision = stub._climate_scenario_revision
    assert stub._climate_scenario_update(json.dumps(scenario))
    view = stub._climate_scenario_view()
    assert view["dirty"] is True and view["revision"] == revision, "правка не перечитывает форму"

    assert stub._climate_scenario_save()
    view = stub._climate_scenario_view()
    assert view["dirty"] is False and view["fileName"] == "Мой_цикл.json"
    assert "Мой цикл" in [item["name"] for item in view["files"]]

    stub._climate_scenario_new("empty")
    assert stub._climate_scenario["name"] == "Новый сценарий"
    assert stub._climate_scenario_load(view["path"])
    assert stub._climate_scenario["name"] == "Мой цикл" and stub._climate_scenario["steps"][0]["hold_min"] == 15.0
    assert stub._climate_scenario_revision > revision


def test_scenario_is_locked_during_a_run(tmp_path: Path):
    stub = _scenario_stub(tmp_path, [cs.new_step(25.0)])
    assert stub._climate_run_start()
    assert not stub._climate_scenario_new("empty")
    assert not stub._climate_scenario_update(json.dumps(cs.empty_scenario()))
    assert "Идёт прогон" in stub._climate_scenario_status
    assert stub._climate_scenario_view()["locked"] is True


def test_current_scenario_survives_restart(tmp_path: Path):
    stub = _ScnStub(tmp_path)
    scenario = cs.empty_scenario("Несохранённый")
    stub._climate_scenario_update(json.dumps(scenario))
    again = _ScnStub(tmp_path)
    assert again._climate_scenario["name"] == "Несохранённый" and again._climate_scenario_dirty is True


def test_bad_file_does_not_break_loading(tmp_path: Path):
    stub = _ScnStub(tmp_path)
    broken = tmp_path / "сломанный.json"
    broken.write_text("{не json", encoding="utf-8")
    assert not stub._climate_scenario_load(str(broken))
    assert "не загрузился" in stub._climate_scenario_status


def test_labels_kept_only_with_references():
    with_refs, _ = cs.normalize({"board_only": False, "labels": "0/0; 150/47", "steps": [{"temp": 25}]})
    assert with_refs["labels"] == ["0/0", "150/47"]
    board, _ = cs.normalize({"board_only": True, "labels": "68/22", "steps": [{"temp": 25}]})
    assert board["labels"] == ["0/0"]


def test_old_scenario_is_upgraded_but_own_values_stay():
    """Сценарий версии 1: прежние значения по умолчанию -> новые, свои значения и свои шаги - как есть."""
    old = cs.board_cycle_scenario()
    old.update({"version": 1, "settle_min": 5.0, "settle_rate": 0.05, "board_max_shift_c": 20.0, "board_attempts": 3.0})
    old["steps"] = [cs.new_step(temp) for temp in (25.0, -40.0, -20.0, 0.0, 50.0, 70.0, 85.0)]
    clean, problems = cs.normalize(old)
    assert (clean["settle_min"], clean["settle_rate"], clean["board_max_shift_c"], clean["board_attempts"]) == \
        (12.0, 0.03, 25.0, 4.0)
    assert [step["temp"] for step in clean["steps"]] == [25.0, -20.0, -40.0, 0.0, 50.0, 70.0, 85.0]
    assert clean["version"] == 2 and any("обновлён" in text for text in problems)
    # Свои значения и свои шаги не трогаются.
    own = dict(old, settle_min=8.0, board_attempts=5.0, steps=[cs.new_step(25.0), cs.new_step(-40.0)])
    clean, _problems = cs.normalize(own)
    assert clean["settle_min"] == 8.0 and clean["board_attempts"] == 5.0 and clean["settle_rate"] == 0.03
    assert [step["temp"] for step in clean["steps"]] == [25.0, -40.0]
    # Сценарий текущей версии со значением, равным старому по умолчанию, - выбор человека, не трогается.
    current = dict(cs.board_cycle_scenario(), settle_min=5.0)
    assert cs.normalize(current)[0]["settle_min"] == 5.0
