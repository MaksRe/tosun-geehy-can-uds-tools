"""Проверки видимости процентов и точной сводки за весь прогон."""

import time

import pytest

from tests.test_journal_assign_monitor import BOARDS, _mon_stub, _monitor_feed
from ui.qml import climate_scenario
from ui.qml.controller.run_report_mixin import AppControllerRunReportMixin
from ui.qml.telegram_reports import level_report, status_report
from tests.test_level_results import AIR


@pytest.mark.parametrize("scenario", [climate_scenario.board_cycle_scenario, climate_scenario.assembly_scenario])
def test_training_hides_percentages_and_accuracy_in_report(tmp_path, scenario):
    """Чтобы обучение не давало ложную точность, скрывает проценты в обоих этапах и отчёте."""
    stub = _mon_stub(tmp_path)
    stub.__class__ = type("TrainingReportStub", (AppControllerRunReportMixin, stub.__class__), {})
    stub._climate_scenario = scenario()
    now = time.monotonic()
    for sa, *_ in BOARDS:
        _monitor_feed(stub, sa, now, 25, 77.7, 15000)
    stub._chamber_monitor_tick(now, force=True)
    view = stub._chamber_monitor_view()
    assert view["levelEnabled"] is False and view["checkMode"] is False
    assert "77,70" not in level_report({"monitor": view})
    assert "77,70" not in status_report({"monitor": view})
    report = stub._run_report_data()
    assert report["verdict"]["tone"] == "info"
    assert report["boards"] == report["charts"] == report["nodes"]["rows"] == []


def test_check_needs_verified_profile_and_calibration_for_every_board(tmp_path):
    """Чтобы не выдавать неподтверждённый уровень за точность, требует профиль и 0/100 у каждой платы."""
    stub = _mon_stub(tmp_path)
    assert stub._chamber_monitor_level_context()["levelEnabled"]
    audit = stub._profile_audit["results"][BOARDS[-1][0]]
    audit["values"]["full"] = 0
    assert not stub._chamber_monitor_level_context()["levelEnabled"]
    audit["values"]["full"] = 27000
    audit["problems"] = ["поправка по виду топлива включена без эталонов"]
    assert not stub._chamber_monitor_level_context()["levelEnabled"]
    stub._profile_audit = {}
    assert not stub._chamber_monitor_level_context()["levelEnabled"]


def test_training_hides_fuel_columns_in_all_results(tmp_path):
    """Чтобы сводка и архив не показывали ложную погрешность, скрывает её и в таблицах измерений."""
    stub = _mon_stub(tmp_path)
    stub._climate_scenario = climate_scenario.assembly_scenario()
    for sa, *_ in BOARDS:
        with stub._mb_context(sa):
            stub._chamber_points = [dict(point) for point in AIR]
    view = stub._chamber_results_view()
    tables = [view["combined"], view["overview"]]
    for board in view["boards"]:
        assert board["levelTable"] is None
        assert not any(item["label"].startswith("Уровень") for item in board["summary"])
        tables.extend(board["tables"])
    assert all(column["key"] not in ("level", "levelErr") for table in tables if table for column in table["columns"])


def test_summary_keeps_exact_extrema_and_delta_after_appending(tmp_path):
    """Для краткой сводки проверяет минимум, максимум и изменение по исходным записям, включая короткий выброс."""
    stub = _mon_stub(tmp_path)
    now = time.monotonic()
    sa = BOARDS[0][0]
    with stub._mb_context(sa):
        stub._chamber_label = "воздух"
    for offset, value in enumerate((.4, -1.2, .1, .8)):
        _monitor_feed(stub, sa, now + offset * 6, 25, value, 15000)
        stub._chamber_monitor_tick(now + offset * 6, force=True)
    row = next(row for row in stub._chamber_monitor_view()["summary"] if row["key"] == str(sa))
    assert row["min"] == -1.2 and row["max"] == .8
    assert row["span"] == 2 and row["worst"] == 1.2
    assert row["delta"] == pytest.approx(.4)
    assert row["mean"] == pytest.approx(row["sum"] / row["count"])
