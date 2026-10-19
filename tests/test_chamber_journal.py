"""Проверки работы с журналом точек и сценария добора.

Добор точки к прошлому прогону: журнал прошлого прогона открывают из списка
(в том числе из папки прежней версии программы), убирают недостоверную точку,
дописывают новые. Тесты закрепляют:
- список журналов: своя папка с подпапками и папки прошлых версий; наружу - короткий
  ключ, а не путь на диске;
- журнал из чужой папки открывается копией в своей папке, исходный файл не меняется;
- любая точка убирается по номеру и времени, чужая (журнал сдвинулся) - нет;
- повторная точка в том же узле сверяется со старыми: расхождение больше 2 отсчётов -
  предупреждение;
- сценарий добора и проверка перед стартом учитывают точки открытого журнала.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_chamber_run import _ChamberStub
from ui.qml import climate_scenario as cs

JOURNAL = ("﻿Время;Что подключено;Период основного контура;Период контура вида топлива;"
           "Температура топлива (°C);Температура платы (°C);Режим;Температура камеры (°C)\n"
           "15:17:22;0/0;4533;4433;21,5;24,5;;17,2\n"
           "23:08:26;0/0;4532;4430;-22,2;-19,7;;-28,5\n"
           "02:39:46;0/0;4540;4456;80,0;85,0;;85,0\n")


class _Stub(_ChamberStub):
    def __init__(self, root: Path):
        super().__init__()
        self._project_root_directory = root
        self.events = []

    def _chamber_after_change(self) -> str:
        return ""

    def _climate_event(self, text, level="info", kind="event"):
        self.events.append((level, text))


def _layout(tmp_path: Path):
    """Своя папка logs/chamber с подпапкой и журнал в «прошлой версии» рядом."""
    app = tmp_path / "tool_v1.0.17"
    own = app / "logs" / "chamber"
    (own / "старые").mkdir(parents=True)
    (own / "chamber_20261015_100000.csv").write_text(JOURNAL, encoding="utf-8")
    (own / "старые" / "chamber_20261001_090000.csv").write_text(JOURNAL, encoding="utf-8")
    old = tmp_path / "tool_v1.0.16" / "_internal" / "ui" / "logs" / "chamber"
    old.mkdir(parents=True)
    source = old / "chamber_20261013_151722.csv"
    source.write_text(JOURNAL, encoding="utf-8")
    os.utime(source, (1_700_000_000, 1_700_000_000))
    (own / "run_20261015_100000.csv").write_text("не журнал точек", encoding="utf-8")
    return app, own, source


def test_journals_are_listed_from_own_folder_and_previous_versions(tmp_path: Path):
    app, _own, _source = _layout(tmp_path)
    stub = _Stub(app)
    journals = stub._chamber_journals(fresh=True)
    names = {item["name"]: item for item in journals}
    assert set(names) == {"chamber_20261015_100000.csv", "chamber_20261001_090000.csv", "chamber_20261013_151722.csv"}
    assert names["chamber_20261015_100000.csv"]["points"] == 3 and names["chamber_20261015_100000.csv"]["folder"] == ""
    assert names["chamber_20261001_090000.csv"]["folder"] == "старые"
    old = names["chamber_20261013_151722.csv"]
    assert old["external"] and old["folder"] == "прошлая версия v1.0.16" and len(old["id"]) == 12


def test_external_journal_is_opened_as_a_copy(tmp_path: Path):
    app, own, source = _layout(tmp_path)
    stub = _Stub(app)
    item = next(entry for entry in stub._chamber_journals(fresh=True) if entry["name"] == source.name)
    ok, text = stub._chamber_open_journal(item["id"])
    assert ok and "скопирован" in text and len(stub._chamber_points) == 3
    assert Path(stub._chamber_file_path) == own / source.name
    assert source.read_text(encoding="utf-8") == JOURNAL
    assert not stub._chamber_open_journal("нет такого")[0]


def test_any_point_is_removed_by_index_and_time(tmp_path: Path):
    app, own, _source = _layout(tmp_path)
    stub = _Stub(app)
    assert stub._chamber_load_file(str(own / "chamber_20261015_100000.csv"))
    ok, _text = stub._chamber_remove_point(2, "23:08:26")
    assert not ok, "время не совпало - не та точка"
    ok, text = stub._chamber_remove_point(2, "02:39:46")
    assert ok and "+85,0" not in text and len(stub._chamber_points) == 2
    rows = stub._chamber_rows()
    assert [row["index"] for row in rows] == [1, 0] and rows[0]["time"] == "23:08:26"


def test_repeat_point_is_compared_with_the_old_ones(tmp_path: Path):
    app, own, _source = _layout(tmp_path)
    stub = _Stub(app)
    assert stub._chamber_load_file(str(own / "chamber_20261015_100000.csv"))
    stub._chamber_label = "0/0"
    stub._chamber_samples = [{"main": 4534, "media": 4434, "fuel_temp": 250, "board_temp": 251}]
    stub._chamber_store_point()
    assert stub.events[-1][0] == "ok" and "в порядке" in stub.events[-1][1]
    stub._chamber_samples = [{"main": 4538, "media": 4433, "fuel_temp": 250, "board_temp": 249}]
    stub._chamber_store_point()
    level, text = stub.events[-1]
    assert level == "warn" and "нарушена" in text and "основной 4538" in text
    assert "Внимание" in stub._chamber_status


def test_refill_scenario():
    scenario, problems = cs.normalize(cs.refill_scenario())
    assert problems == [] and scenario["name"] == cs.REFILL_NAME
    assert [step["temp"] for step in scenario["steps"]] == [25.0, -20.0, -40.0, 85.0]
    assert [step["hold_min"] for step in scenario["steps"]] == [0.0, 0.0, 15.0, 15.0]
    assert scenario["board_only"] and scenario["labels"] == ["0/0"]


def test_start_checks_count_points_of_the_open_journal(tmp_path: Path):
    from tests.test_climate_scenario import _ScnStub

    stub = _ScnStub(tmp_path)
    assert stub._climate_scenario_new("refill")
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert not checks["refill"]["ok"] and checks["refill"]["level"] == "block"
    assert "Не все узлы" in checks["grid"]["text"]
    stub._chamber_points = [{"time": "t", "note": "0/0", "main": 4533, "media": 4433, "fuel_temp_x10": node,
                             "board_temp_x10": node, "rehearsal": False} for node in (250, -200, 0, 500, 700)]
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert "refill" not in checks and "5 точек" in checks["journal"]["text"]
    assert checks["grid"]["ok"] and "вместе с открытым журналом (5 точек)" in checks["grid"]["text"]
    assert "+25" in checks["repeat"]["text"] and "-20" in checks["repeat"]["text"]


def _refill_stub(tmp_path: Path, old_main: int):
    """Добор к журналу прошлого прогона на имитаторе: в журнале 5 узлов, прибор сейчас даёт 5000/4500."""
    import time as _time

    from tests.test_climate_scenario import _ScnStub
    from tests.test_climate_supervisor import _feed

    stub = _ScnStub(tmp_path)
    stub._project_root_directory = tmp_path
    stub._climate_settings.update({"min_c": -85.0, "max_c": 180.0})
    stub._chamber_label = "0/0"
    assert stub._climate_scenario_new("refill")
    # Запись профиля в прибор здесь не проверяется: у заготовки нет обмена с прибором.
    stub._climate_scenario["auto_write"] = False
    # Точки настоящие, не пробные: пробные точки повторяемость не сверяет.
    stub._chamber_test_mode = False
    folder = tmp_path / "logs" / "chamber"
    folder.mkdir(parents=True)
    stub._chamber_points = [{"time": f"0{index}:00:00", "note": "0/0", "main": old_main, "media": 4500,
                             "fuel_temp_x10": node, "board_temp_x10": node, "rehearsal": False}
                            for index, node in enumerate((250, -200, 0, 500, 700))]
    stub._chamber_file_path = str(folder / "chamber_20261013_151722.csv")
    stub._chamber_write_csv(stub._chamber_file_path)
    _feed(stub, _time.monotonic())
    return stub


def test_refill_with_changed_setup_switches_to_full_cycle_by_itself(tmp_path: Path):
    """Установка изменилась (+10 отсчётов): точка переснимается, затем прогон сам идёт полным циклом."""
    from tests.test_climate_supervisor import _walk

    stub = _refill_stub(tmp_path, old_main=4990)
    old_file = Path(stub._chamber_file_path)
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub, limit=40000)
    texts = [text for _level, text in stub.events]
    assert any("точка убрана, через 10 мин сниму её заново" in text for text in texts), texts
    assert any("Перехожу на полный цикл с новым журналом" in text for text in texts), texts
    # Прежний журнал - как до прогона: 5 старых точек, без новых.
    assert old_file.read_text(encoding="utf-8-sig").count("\n") == 6
    # Новый журнал: только точки этого прогона, все 7 узлов, по одной точке в узле.
    import chamber_fit
    nodes = sorted(chamber_fit.nearest_node(point["board_temp_x10"]) for point in stub._chamber_points)
    assert nodes == sorted(chamber_fit.NODES_X10), nodes
    assert all(point["main"] == 5000 for point in stub._chamber_points)
    assert Path(stub._chamber_file_path) != old_file and Path(stub._chamber_file_path).exists()
    assert [step["temp"] for step in stub._climate_scenario["steps"]] == [25.0, -20.0, -40.0, 0.0, 50.0, 70.0, 85.0]


def test_refill_with_same_setup_just_adds_points(tmp_path: Path):
    """Установка та же (разница в пределах допуска): добор как задуман - 4 шага, точки к прежнему журналу."""
    from tests.test_climate_supervisor import _walk

    stub = _refill_stub(tmp_path, old_main=4999)
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub, limit=40000)
    texts = [text for _level, text in stub.events]
    assert not any("полный цикл" in text for text in texts)
    assert any("повторяемость в узле +25 °C в порядке" in text for text in texts), texts
    assert len(stub._chamber_points) == 9 and stub._chamber_file_path.endswith("chamber_20261013_151722.csv")


def test_repeat_failure_only_warns_when_rule_is_off(tmp_path: Path):
    from tests.test_climate_supervisor import _walk

    stub = _refill_stub(tmp_path, old_main=4990)
    stub._climate_scenario["repeat_full_cycle"] = False
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub, limit=40000)
    texts = [text for _level, text in stub.events]
    assert any("нарушена" in text for text in texts) and not any("полный цикл с новым журналом:" in text for text in texts)
    assert len(stub._chamber_points) == 9
