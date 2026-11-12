"""Назначение журналов платам, замечания испытаний 10-12.11.2026 и монитор отклонений.

Тесты закрепляют:
- «Журналы первого этапа всем платам»: журнал, где кроме первого этапа есть «воздух» прошлого
  прогона и стендовые точки, не открывается как есть - плате заводится новый журнал только с
  первым этапом, исходный файл не меняется; чистый журнал первого этапа открывается как есть;
- таблица «какой журнал у какой платы» считается по самим платам: файл, состав, откуда взят;
- список журналов помечает, у каких плат файл открыт сейчас, - у всех плат, а не только у той,
  в чьём поле посчитан кэш списка;
- один файл не открывается у двух плат; журнал открывается своей плате без показа её в ленте;
- расчёт таблиц: точки одного состояния в узле из разных условий - замечание; снятая на столе
  «жидкость» с размахом не как заданный вручную заменяется на воздух + размах (без излома);
- итоги: при заданном размахе отсутствие погружения - не недостаток;
- размах у каждой платы свой и помнится в списке плат;
- монитор: опора сама при +25 °C трубки, отклонение уровня от опоры по узлам, оценка по ±1 %,
  прошивка без параметров монитора - понятное состояние.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_fit
from tests.test_multiboard import BOARDS, _MbStub, _stub, _with_control
from ui.qml.chamber_results import board_results
from ui.qml.controller.chamber_mixin import journal_makeup, stage1_nodes
from ui.qml.controller.chamber_monitor_mixin import AppControllerChamberMonitorMixin

ALL = [node / 10 for node in chamber_fit.NODES_X10]


def _journal(stub, path: Path, temps, stamp: float, air=(), liquid=()):
    """Журнал: первый этап «0/0» в узлах temps и точки трубки (температура, основной, вид, дата)."""
    lines = [";".join(stub.CHAMBER_COLUMNS)]
    for index, temp in enumerate(temps):
        value = f"{temp:.1f}".replace(".", ",")
        lines.append(f"11:{index:02d}:00;0/0;4535;4459;{value};{value};;{value}")
    for note, rows in (("воздух", air), ("жидкость", liquid)):
        for index, (temp, main, media, day) in enumerate(rows):
            value = f"{temp:.1f}".replace(".", ",")
            lines.append(f"19:{index:02d}:00;{note};{main};{media};{value};{value};;{value};{day};9;1;0")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    os.utime(path, (stamp, stamp))
    return path


def _air_run(day: str, shift: int = 0):
    return [(temp, 15480 + shift + int(temp), 10724 + shift, day) for temp in ALL]


def test_stage1_button_starts_clean_journal_when_old_run_points_are_inside(tmp_path: Path):
    stub = _with_control(_stub(tmp_path))
    own = stub._chamber_autosave_directory()
    now = time.time()
    # П1 (0x80): журнал прошлого прогона - первый этап, «воздух» двух дней и стендовая «жидкость».
    mixed = _journal(stub, own / "chamber_20261110_повтор_П1_0x80.csv", ALL, now - 3600,
                     air=_air_run("2026-11-10") + _air_run("2026-11-11", 31),
                     liquid=[(25.4, 27264, 14523, "2026-11-11")])
    before = mixed.read_bytes()
    # П2 (0x81): чистый журнал первого этапа.
    clean = _journal(stub, own / "chamber_20261028_114806_П2_0x81.csv", ALL, now - 7200)
    # П3 (0x82): журнала нет.
    ok, text, _details = stub._control_do_journal_stage1({}, {})
    assert not ok and "журнала первого этапа с адресом 0x82 на диске нет" in text

    with stub._mb_context(0x80):
        name = Path(stub._chamber_file_path).name
        makeup = journal_makeup(stub._chamber_points)
        assert name != mixed.name and name.endswith("_0x80.csv"), name
        assert makeup["stage1"] == 7 and makeup["air"] == 0 and makeup["liquid"] == 0
        assert stub._chamber_journal_origin["source"] == mixed.name
        assert stub._chamber_journal_origin["dropped"] == 15
    assert mixed.read_bytes() == before, "исходный журнал прошлого прогона не меняется"
    with stub._mb_context(0x81):
        assert Path(stub._chamber_file_path).name == clean.name, "чистый журнал открывается как есть"

    report = {entry["sa"]: entry for entry in stub._mb_stage1_report}
    assert report[0x80]["ok"] and report[0x80]["dropped"] == 15 and "исходный файл не изменён" in report[0x80]["text"]
    assert report[0x81]["ok"] and report[0x81]["how"] == "по адресу в имени файла"
    assert not report[0x82]["ok"] and report[0x82]["how"] == "не найден"

    # Второе нажатие: у П1 теперь чистый журнал первого этапа - он не трогается.
    stub._control_do_journal_stage1({}, {})
    report = {entry["sa"]: entry for entry in stub._mb_stage1_report}
    assert report[0x80]["how"] == "уже был открыт"

    rows = {row["sa"]: row for row in stub._mb_journal_assignments()}
    assert rows["0x80"]["state"] == "в порядке" and rows["0x80"]["stage1"] == "7 из 7"
    assert "не перенесено точек: 15" in rows["0x80"]["origin"] or rows["0x80"]["origin"].startswith("уже был открыт")
    assert rows["0x82"]["state"] == "журнала нет" and rows["0x82"]["tone"] == "bad"
    table = stub._mb_journals_table()
    assert [column["key"] for column in table["columns"]][:2] == ["label", "file"]
    assert len(table["rows"]) == len(BOARDS)


def test_journal_list_marks_owners_of_all_boards(tmp_path: Path):
    stub = _with_control(_stub(tmp_path))
    own = stub._chamber_autosave_directory()
    for sa, name, *_rest in BOARDS:
        _journal(stub, own / f"chamber_20261028_114806_{name}_0x{sa:02X}.csv", ALL, time.time())
    assert stub._mb_open_stage1_journals()[0]
    listed = {item["name"]: item for item in stub._chamber_journals(fresh=True)}
    for sa, name, *_rest in BOARDS:
        item = listed[f"chamber_20261028_114806_{name}_0x{sa:02X}.csv"]
        assert item["openSa"] == [f"0x{sa:02X}"], item
        assert item["openBy"].startswith(f"0x{sa:02X}")
        # «Открыт» у показанной платы - только её журнал.
        assert item["current"] == (sa == stub._mb_active_sa)


def test_one_file_is_not_opened_by_two_boards_and_opens_for_its_board(tmp_path: Path):
    stub = _with_control(_stub(tmp_path))
    own = stub._chamber_autosave_directory()
    shared = _journal(stub, own / "chamber_20261020_011249.csv", ALL, time.time())
    assert stub._mb_active_sa == 0x80
    ok, text = stub._chamber_open_journal(str(shared))
    assert ok, text
    with stub._mb_context(0x81):
        ok, text = stub._chamber_open_journal(str(shared))
    assert not ok and "уже открыт у платы 0x80 (П1)" in text

    # Журнал с адресом платы в имени открывается ей без показа в ленте.
    other = _journal(stub, own / "chamber_20261028_114806_П3_0x82.csv", ALL, time.time())
    ok, text, _name = stub._control_do_journal_open({}, {"path": str(other), "sa": "0x82"})
    assert ok and text.startswith("0x82 (П3): открыт журнал"), text
    assert stub._mb_active_sa == 0x80
    with stub._mb_context(0x82):
        assert Path(stub._chamber_file_path).name == other.name
        assert stub._chamber_journal_origin["how"] == "открыт из списка"


def _pt(note, main, media, temp_x10):
    return {"time": "x", "note": note, "main": main, "media": media, "fuel_temp_x10": temp_x10,
            "board_temp_x10": temp_x10, "rehearsal": False}


def _stage1_and_air(air_shift=0):
    points = [_pt("0/0", 4535, 4459, node) for node in chamber_fit.NODES_X10]
    points += [_pt("воздух", 15480 + air_shift + node // 10, 10724 + air_shift, node) for node in chamber_fit.NODES_X10]
    return points


def test_bench_points_in_tube_rows_are_reported_and_liquid_is_not_kinked():
    # Стендовый «воздух» в узле +25 °C рядом с камерным: замечание, таблицу так писать нельзя.
    points = _stage1_and_air() + [_pt("воздух", 15480 - 25 + 25, 10724 - 92, 245)]
    result = chamber_fit.compute_tables(points, extend_liquid=True, span_main=11880, span_media=3865,
                                        single_model=chamber_fit.SINGLE_GAIN)
    problems = " | ".join(result["замечания"])
    assert "в узле +25 °C точки «воздух» расходятся: основной на 25 отсчётов" in problems
    assert "вид топлива на 92 отсчётов" in problems

    # Стендовая «жидкость» в узле +25 °C при заданном размахе: строка - воздух + размах, без излома.
    points = _stage1_and_air() + [_pt("жидкость", 15505 + 11785, 10724 + 3798, 255)]
    result = chamber_fit.compute_tables(points, extend_liquid=True, span_main=11785, span_media=3959,
                                        single_model=chamber_fit.SINGLE_GAIN)
    tube = result["ступень_трубки"]
    spans = [full - air for full, air in zip(tube["full_media"], tube["air_media"])]
    assert spans == [3959] * 7, spans
    assert any("заменены на воздух + размах" in item and "+25 °C (3798 против 3959)" in item
               for item in result["сведения"])
    assert not result["замечания"]
    # Основной контур: снятая жидкость в пределах 1 % размаха - остаётся снятой.
    main_spans = [full - air for full, air in zip(tube["full_main"], tube["air_main"])]
    assert main_spans.count(11785) == 7

    # Без заданного размаха снятая «жидкость» - опора размаха и не заменяется.
    result = chamber_fit.compute_tables(points, extend_liquid=True, single_model=chamber_fit.SINGLE_GAIN)
    spans = [full - air for full, air in zip(result["ступень_трубки"]["full_media"], result["ступень_трубки"]["air_media"])]
    assert spans == [3798] * 7


def test_results_do_not_ask_for_immersion_when_span_is_given():
    points = _stage1_and_air()
    assert "погружение не снято" in board_results(points)["verdict"]
    result = board_results(points, span_known=True)
    assert result["tone"] == "ok", result["verdict"]
    assert any(item["value"] == "не нужно: размах задан" for item in result["summary"])


def test_span_is_kept_per_board_and_saved(tmp_path: Path):
    stub = _stub(tmp_path)
    assert stub._mb_active_sa == 0x80
    assert stub._chamber_set_span("main", "11880") and stub._chamber_set_span("media", "3865")
    assert stub._mb_activate(0x81)
    assert stub._chamber_span_main is None, "у другой платы свой размах"
    assert stub._chamber_set_span("main", "11785")
    assert stub._mb_activate(0x80)
    assert (stub._chamber_span_main, stub._chamber_span_media) == (11880, 3865)
    saved = json.loads(stub._mb_config_path().read_text(encoding="utf-8"))
    spans = {board["sa"]: (board.get("span_main"), board.get("span_media")) for board in saved["boards"]}
    assert spans[0x80] == (11880, 3865) and spans[0x81] == (11785, None)

    # После перезапуска размах платы возвращается из списка плат.
    again = _MbStub(tmp_path)
    with again._mb_context(0x81, notify=False):
        assert again._chamber_span_main == 11785


# ------------------------------------------------------------------ монитор

class _MonStub(AppControllerChamberMonitorMixin, _MbStub):
    pass


def _mon_stub(tmp_path: Path) -> _MonStub:
    stub = _MonStub(tmp_path)
    for sa, name, _offset, _main in BOARDS:
        assert stub._mb_add_board(f"0x{sa:02X}", name)[0]
    assert stub._mb_set_enabled(True)[0]
    return stub


def _monitor_feed(stub, sa, now, tube_c, level_pct, comp):
    with stub._mb_context(sa, notify=False):
        for shift in (2.0, 1.0, 0.0):
            stamp = now - shift
            stub._chamber_live_note("board_temp", int(round(tube_c * 10)), stamp)
            stub._chamber_live_note("fuel_temp", int(round(tube_c * 10)), stamp)
            stub._chamber_live_note("main", 15480, stamp)
            stub._chamber_live_note("level", int(round(level_pct * 10)), stamp)
            stub._chamber_live_note("comp", comp, stamp)


def test_monitor_tracks_level_deviation_by_node(tmp_path: Path):
    stub = _mon_stub(tmp_path)
    assert ("level" in stub.CHAMBER_LIVE_ORDER and "comp" in stub.CHAMBER_LIVE_ORDER)
    assert {key for key, _var, _signed in stub._chamber_live_vars()} >= {"level", "comp", "main", "media"}
    start = time.monotonic()
    # Плёнка на холоде: +0,3 % у 0x80 при -40 °C, у 0x81 -1,4 % при +85 °C.
    plan = [(25.0, {0x80: 0.2, 0x81: 0.1, 0x82: 0.0}),
            (-40.0, {0x80: 0.5, 0x81: 0.1, 0x82: 0.0}),
            (85.0, {0x80: 0.1, 0x81: -1.3, 0x82: 0.0})]
    for step, (tube, levels) in enumerate(plan):
        now = start + step * 100.0
        for sa, level in levels.items():
            _monitor_feed(stub, sa, now, tube, level, 15509)
        stub._chamber_monitor_tick(now)

    with stub._mb_context(0x80, notify=False):
        assert stub._chamber_monitor_ref["auto"] and stub._chamber_monitor_ref["level"] == 2.0
        assert len(stub._chamber_monitor_history) == 3
    view = stub._chamber_monitor_view()
    rows = {row["cells"]["label"]: row for row in view["now"]["rows"]}
    assert rows["0x80 (П1)"]["cells"]["worst"].startswith("+0,30 при −40,0 °C")
    assert rows["0x80 (П1)"]["tone"] == "ok"
    assert rows["0x81 (П2)"]["tone"] == "bad" and rows["0x81 (П2)"]["cells"]["status"] == "вне допуска"
    assert rows["0x81 (П2)"]["cells"]["dev"] == "−1,40"
    nodes = {row["cells"]["label"]: row for row in view["nodes"]["rows"]}
    assert nodes["0x80 (П1)"]["cells"]["-400"] == "+0,30 (1)"
    assert nodes["0x81 (П2)"]["cells"]["850"] == "−1,40 (1)" and nodes["0x81 (П2)"]["tone"] == "bad"
    assert view["worst"] == "1,40" and view["tone"] == "bad"

    # Опора по кнопке и сброс.
    ok, text = stub._chamber_monitor_set_reference()
    assert ok and "0x80 (П1)" in text
    with stub._mb_context(0x81, notify=False):
        assert stub._chamber_monitor_ref["auto"] is False and stub._chamber_monitor_ref["tube"] == 850
    stub._chamber_monitor_reset()
    for sa, *_rest in BOARDS:
        with stub._mb_context(sa, notify=False):
            assert stub._chamber_monitor_ref is None and stub._chamber_monitor_history == []


def test_monitor_names_missing_firmware_parameters(tmp_path: Path):
    stub = _mon_stub(tmp_path)
    now = time.monotonic()
    _monitor_feed(stub, 0x80, now, 25.0, 0.2, 15509)
    with stub._mb_context(0x80, notify=False):
        stub._chamber_live_missing.add("level")
    view = stub._chamber_monitor_view()
    row = next(row for row in view["now"]["rows"] if row["cells"]["label"] == "0x80 (П1)")
    assert row["cells"]["status"] == "прошивка не отдаёт уровень или итог периода" and row["tone"] == "bad"


def test_silent_boards_are_polled_rarely_outside_a_run(tmp_path: Path):
    stub = _stub(tmp_path)
    now = time.monotonic()
    # _stub кормит все платы: они на шине и не пропускаются.
    assert not any(stub._mb_skip_silent(sa, now) for sa, *_rest in BOARDS)
    # Плата, молчащая дольше минуты, спрашивается раз в MB_SILENT_EVERY своих очередей.
    later = now + stub.MB_PRESENT_S + 5.0
    asked = [not stub._mb_skip_silent(0x82, later) for _turn in range(3 * stub.MB_SILENT_EVERY)]
    assert asked.count(True) == 3 and asked[0], asked


# ------------------------------------------------------------------ проверка профиля

def test_check_scenario_never_writes_a_profile():
    from ui.qml import climate_scenario as cs

    scenario = cs.check_scenario()
    clean, problems = cs.normalize(scenario)
    assert problems == [] and clean["check_only"] is True and clean["auto_write"] is False
    assert clean["labels"] == ["воздух"] and clean["board_only"] is False and len(clean["steps"]) == 7
    assert "проверка профиля" in cs.summary(clean)
    # Даже если в файле автозапись включена, проверка профиль не пишет.
    clean, _problems = cs.normalize(dict(scenario, auto_write=True, board_only=True))
    assert clean["auto_write"] is False and clean["board_only"] is False


def test_check_run_starts_without_stage1_journals(tmp_path: Path):
    stub = _with_control(_stub(tmp_path))
    assert stub._climate_scenario_new("check")
    stub._climate_scenario_apply_chamber()
    assert stub._chamber_check_only is True and stub._chamber_auto_write is False
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert checks["stage2"]["ok"] and "журналы первого этапа не нужны" in checks["stage2"]["text"]
    assert checks["auto_write"]["ok"] and "не пишется" in checks["auto_write"]["text"]
    assert not any("журнал первого этапа" in text.lower() for text in stub._climate_auto_blockers())

    # Обычный второй этап без журналов по-прежнему не стартует.
    assert stub._climate_scenario_new("assembly")
    stub._climate_scenario_apply_chamber()
    assert stub._chamber_check_only is False
    assert any("Журналы первого этапа всем платам" in text for text in stub._climate_auto_blockers())


def test_check_run_gets_its_own_journals_and_no_tables(tmp_path: Path):
    stub = _with_control(_stub(tmp_path))
    own = stub._chamber_autosave_directory()
    stage1 = _journal(stub, own / "chamber_20261028_114806_П1_0x80.csv", ALL, time.time())
    before = stage1.read_bytes()
    assert stub._chamber_open_journal(str(stage1))[0]
    stub._chamber_check_only = True
    stub._chamber_check_begin()
    with stub._mb_context(0x80):
        assert stub._chamber_points == [] and stub._chamber_file_path == ""
        assert stub._chamber_journal_origin["how"] == "журнал проверки профиля"
        stub._chamber_label = "воздух"
        stub._chamber_append_point({"main": 15480, "media": 10724, "fuel_temp_x10": 255, "board_temp_x10": 268})
        name = Path(stub._chamber_file_path).name
        assert "_проверка_" in name and name.endswith("_0x80.csv"), name
        assert "Проверка профиля: таблицы не считаются" in stub._chamber_tables_text
        assert stub._chamber_tables_complete is False
    assert stage1.read_bytes() == before, "журнал первого этапа не тронут"
    result = board_results([_pt("воздух", 15480, 10724, node) for node in chamber_fit.NODES_X10], check=True)
    assert result["tone"] == "ok" and result["verdict"].startswith("Проверка профиля")
