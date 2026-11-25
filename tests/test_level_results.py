"""Итоговый уровень топлива в точках и на всём диапазоне температур (14.11.2026).

Оператор не видел, как ведёт себя сам уровень прибора: таблицы итогов показывали только периоды
двух контуров. Закрепляем:
- уровень прибора (0x0018) и итог периода (0x0062) пишутся в точку и в журнал и читаются обратно;
- в итогах платы - таблица «Уровень топлива в точках»: погрешность от 0 % (сухая трубка) / 100 %
  (в топливе), сдвиг от +25 °C, итог по требованию ±1 %; худшая погрешность - в показателях и сводке;
- монитор: погрешность по узлам и кривая «погрешность от температуры трубки» по 1 °C у каждой платы.
"""

from __future__ import annotations

import time
from pathlib import Path

from tests.test_chamber_run import _ChamberStub
from tests.test_journal_assign_monitor import _mon_stub, _monitor_feed
from tests.test_run_results import _p
from ui.qml.chamber_results import board_results, overview_table

AIR = [
    _p("воздух", 26.0, 25.1, 15460, 11090, level_x10=1.0, comp=15460),
    _p("воздух", -38.0, -39.6, 15400, 10880, level_x10=7.0, comp=15470),
    _p("воздух", 0.5, 0.2, 15430, 10930, level_x10=3.0, comp=15462),
    _p("воздух", 86.0, 84.8, 15900, 11330, level_x10=-12.0, comp=15440),
    _p("воздух", 50.5, 50.3, 15590, 11340),  # журнал без уровня в этой точке
]


def test_level_kept_in_journal(tmp_path: Path):
    stub = _ChamberStub()
    stub._chamber_points = [dict(AIR[0], date="2026-11-14"), dict(AIR[4], date="2026-11-14")]
    path = tmp_path / "j.csv"
    assert stub._chamber_write_csv(str(path)) is None
    text = path.read_text(encoding="utf-8-sig")
    assert ";0,10;15460" in text.splitlines()[1]
    back = stub._chamber_parse_journal(text)
    assert back[0]["level_x10"] == 1.0 and back[0]["comp"] == 15460
    assert "level_x10" not in back[1] and "comp" not in back[1]


def test_level_table_shows_error_from_zero_per_point():
    result = board_results(AIR, "П1", "0x81", check=True)
    table = result["tables"][0]
    assert table["id"] == "level" and result["levelTable"] is table
    assert len(table["rows"]) == 4  # точка без уровня в таблицу не идёт
    cold = next(row for row in table["rows"] if row["cells"]["node"] == "-40 °C")
    assert cold["cells"]["level"] == "0,70" and cold["cells"]["error"] == "+0,70"
    assert cold["cells"]["shift"] == "+0,60" and cold["cells"]["status"] == "на грани" and cold["tone"] == "warn"
    hot = next(row for row in table["rows"] if row["cells"]["node"] == "+85 °C")
    assert hot["cells"]["error"] == "−1,20" and hot["tone"] == "bad" and hot["cells"]["status"] == "вне допуска"
    worst = result["summary"][0]
    assert worst["label"] == "Уровень: наибольшая погрешность" and worst["value"].startswith("−1,20 % при трубке +84,8 °C")
    assert result["levelText"] == "−1,20 % при +84,8 °C" and result["levelTone"] == "bad"
    overview = overview_table([result])
    assert overview["rows"][0]["cells"]["level"] == "−1,20 % при +84,8 °C"
    measurements = next(t for t in result["tables"] if t["id"] == "measurements")
    assert measurements["rows"][1]["cells"]["levelErr"] == "+0,70"


def test_old_journal_without_level_says_so():
    result = board_results([dict(point) for point in AIR[4:]], "П1", "0x81", check=True)
    assert result["levelTable"] is None and result["levelText"] == "—"
    assert result["summary"][0]["label"] == "Уровень в точках"


def test_monitor_curve_over_whole_range(tmp_path: Path):
    stub = _mon_stub(tmp_path)
    sa = 0x80
    stub._chamber_label = "воздух"
    start = time.monotonic()
    for step, (tube, level) in enumerate([(25.0, 0.1), (25.2, 0.3), (-40.0, 0.6), (85.0, -1.1)]):
        _monitor_feed(stub, sa, start + step * 30.0, tube, level, 15500)
        with stub._mb_context(sa, notify=False):
            stub._chamber_label = "воздух"
            stub._chamber_monitor_sample_here(start + step * 30.0, force=True)
    view = stub._chamber_monitor_view()
    curve = view["curve"]
    assert curve["kind"] == "error" and curve["title"].startswith("Погрешность уровня")
    board = next(b for b in curve["boards"] if b["label"].startswith("0x80"))
    assert board["pts"] == [[-40, 0.6], [25, 0.2], [85, -1.1]]
    nodes = next(row for row in view["nodes"]["rows"] if row["cells"]["label"].startswith("0x80"))
    assert nodes["cells"]["-400"] == "+0,60 (1)" and nodes["cells"]["250"] == "+0,20 (2)"
