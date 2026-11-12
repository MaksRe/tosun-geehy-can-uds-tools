"""Уровень топлива у всех плат сразу и итоговый отчёт PDF (13.11.2026).

Тесты закрепляют:
- погрешность уровня считается от настоящего уровня по пометке («воздух» - 0 %, «жидкость» - 100 %),
  сдвиг - от показания этой же платы при +25 °C; слова «опора» в том, что видит человек, нет;
- монитор отдаёт короткий список всех плат (live) для мини-приложения и бота;
- бот: /level и строка уровня в /status;
- отчёт PDF собирается из данных прогона: вывод против ±1 %, узлы, графики - файл PDF.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_journal_assign_monitor import BOARDS, _mon_stub, _monitor_feed
from ui.qml import run_report_pdf, telegram_reports
from ui.qml.controller.run_report_mixin import AppControllerRunReportMixin


def _run(stub):
    """Сухая трубка: +25 °C, -40 °C (плёнка у 0x80 +0,6 %), +85 °C."""
    for sa, *_rest in BOARDS:
        with stub._mb_context(sa, notify=False):
            stub._chamber_label = "воздух"
    start = time.monotonic()
    plan = [(25.0, {0x80: 0.1, 0x81: 0.0, 0x82: -0.1}),
            (-40.0, {0x80: 0.7, 0x81: 0.2, 0x82: -0.1}),
            (85.0, {0x80: 0.1, 0x81: -0.2, 0x82: -1.3})]
    for step, (tube, levels) in enumerate(plan):
        now = start + step * 100.0
        for sa, level in levels.items():
            _monitor_feed(stub, sa, now, tube, level, 15509)
        stub._chamber_monitor_tick(now)


def test_level_error_and_shift_for_all_boards(tmp_path: Path):
    stub = _mon_stub(tmp_path)
    _run(stub)
    view = stub._chamber_monitor_view()
    live = {row["label"]: row for row in view["live"]}
    assert set(live) == {"0x80 (П1)", "0x81 (П2)", "0x82 (П3)"}
    # Погрешность - от 0 % сухой трубки, сдвиг - от показания при +25 °C.
    assert live["0x82 (П3)"]["err"] == "−1,30" and live["0x82 (П3)"]["dev"] == "−1,20"
    assert live["0x82 (П3)"]["tone"] == "bad" and live["0x82 (П3)"]["status"] == "вне допуска"
    assert live["0x80 (П1)"]["worst"].startswith("+0,70 % при −40,0 °C") and live["0x80 (П1)"]["tone"] == "warn"
    assert live["0x81 (П2)"]["tone"] == "ok"
    titles = [column["title"] for column in view["now"]["columns"]] + [column["title"] for column in view["detail"]["columns"]]
    texts = " ".join(titles) + view["now"]["tip"] + view["nodes"]["tip"] + view["detail"]["tip"]
    assert "опор" not in texts.lower() and "Погрешность, %" in titles and "Сдвиг от +25 °C, %" in titles


def test_bot_shows_level_of_all_boards(tmp_path: Path):
    stub = _mon_stub(tmp_path)
    _run(stub)
    snapshot = {"monitor": stub._chamber_monitor_view()}
    text = telegram_reports.level_report(snapshot)
    assert "Уровень топлива" in text and "П3" in text and "−1,30" in text and "✗" in text
    assert "Уровень топлива" in telegram_reports.status_report(snapshot)
    assert "Данных пока нет" in telegram_reports.level_report({})


class _ReportStub(AppControllerRunReportMixin):
    pass


def test_pdf_report_is_written(tmp_path: Path):
    stub = _mon_stub(tmp_path)
    stub.__class__ = type("_ReportMonStub", (AppControllerRunReportMixin, stub.__class__), {})
    _run(stub)
    stub._climate_scenario = dict(stub._climate_scenario or {}, name="Проверка профиля: сухая трубка", check_only=True)
    stub._remote_events = [{"time": "10:00:00", "text": "узел +25 °C пройден", "level": "info"}]
    data = stub._run_report_data()
    assert data["title"].endswith("проверка профиля")
    assert data["verdict"]["tone"] == "bad" and "0x82 (П3)" in data["verdict"]["title"]
    # У 0x80 холод +0,6 %, жар 0 - подсказка про плёнку; у остальных её нет.
    film = [line for line in data["verdict"]["lines"] if "плёнку" in line]
    assert len(film) == 1 and film[0].startswith("0x80 (П1)")
    assert [row["label"] for row in data["nodes"]["rows"]] == ["0x80 (П1)", "0x81 (П2)", "0x82 (П3)"]
    assert data["nodes"]["rows"][0]["-400"] == "+0,70 / +0,60"
    assert len(data["charts"]) == 3
    path = stub._run_report_write()
    assert path and Path(path).is_file() and Path(path).name.startswith("отчёт_прогона_")
    body = Path(path).read_bytes()
    assert body.startswith(b"%PDF") and len(body) > 20000
    html = run_report_pdf.build_html(data)
    assert "Вне допуска ±1 %" in html and "Средние по узлам" in html and "События прогона" in html


def test_film_hint_when_cold_nodes_are_high():
    board = {"stats": {-400: {"shift": [0.45]}, -200: {"shift": [0.4]}, 850: {"shift": [0.02]}, 700: {"shift": [-0.05]}}}
    assert "плёнку" in AppControllerRunReportMixin._run_report_film_hint(board)
    assert AppControllerRunReportMixin._run_report_film_hint({"stats": {-400: {"shift": [0.1]}, 850: {"shift": [0.0]}}}) == ""
