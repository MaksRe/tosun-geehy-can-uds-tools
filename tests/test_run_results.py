"""Итоги прогона в программе и архив всех файлов одной кнопкой (09.11.2026).

Тесты закрепляют:
- журнал хранит дату точки и статистику окна усреднения, а старые журналы (7 и 8 столбцов) читаются;
- итоги платы: покрытие узлов по этапам, точка вне допуска названа с отклонением, опора +25 °C,
  изменение в отсчётах, процентах от показания при +25 °C и пикофарадах;
- у каждого столбца есть подсказка, проценты объяснены;
- сводка по платам и текст итогов для архива;
- архив прогона: журналы и профили всех плат, ход прогона, журнал камеры, отчёт, настройки, итоги.
"""

from __future__ import annotations

import sys
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_chamber_run import _ChamberStub  # noqa: E402
from ui.qml.chamber_results import board_results, overview_table, results_text  # noqa: E402


def _p(note, board_c, fuel_c, main, media, air_c=None, **extra):
    point = {"time": "12:00:00", "note": note, "main": main, "media": media,
             "board_temp_x10": int(round(board_c * 10)), "fuel_temp_x10": int(round(fuel_c * 10))}
    if air_c is not None:
        point["chamber_temp_x10"] = int(round(air_c * 10))
    point.update(extra)
    return point


# Журнал П6 с прогона 20.10 (этап 1) и 06-07.11.2026 на Zundar (этап 2).
P6 = [
    _p("0/0", 25.5, 22.8, 4533, 4433, 20.4), _p("0/0", -20.6, -22.5, 4532, 4429, -28.7),
    _p("0/0", -39.1, -40.1, 4530, 4427, -55.1), _p("0/0", -0.1, -2.5, 4533, 4431, -5.6),
    _p("0/0", 50.9, 48.1, 4533, 4435, 45.4), _p("0/0", 70.9, 67.8, 4534, 4441, 64.4),
    _p("0/0", 86.1, 82.7, 4537, 4449, 77.7),
    _p("воздух", 28.4, 25.8, 15468, 11092, 25.0, samples=9, main_spread=2, media_spread=1),
    _p("воздух", -16.2, -16.8, 15413, 10886, -20.0), _p("воздух", -32.2, -32.5, 15402, 10882, -40.0),
    _p("воздух", 2.7, 0.7, 15431, 10936, 0.0), _p("воздух", 54.9, 51.6, 15591, 11347, 50.0),
    _p("воздух", 77.0, 73.2, 15718, 11319, 70.0),
    _p("воздух", 95.0, 91.1, 15907, 11337, 84.9, samples=9, main_spread=24, media_spread=6),
]


def _cells(table, column, value):
    return next(row for row in table["rows"] if row["cells"].get(column) == value)


def test_journal_keeps_date_and_window_statistics(tmp_path: Path):
    stub = _ChamberStub()
    stub._chamber_points = [dict(P6[7], date="2026-11-06")]
    path = tmp_path / "j.csv"
    assert stub._chamber_write_csv(str(path)) is None
    header = path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.endswith("Дата;Показаний в среднем;Разброс основного (отсч.);Разброс вида топлива (отсч.)")
    back = stub._chamber_parse_journal(path.read_text(encoding="utf-8-sig"))[0]
    assert (back["date"], back["samples"], back["main_spread"], back["media_spread"]) == ("2026-11-06", 9, 2, 1)
    old = ("Время;Что подключено;Период основного контура;Период контура вида топлива;"
           "Температура топлива (°C);Температура платы (°C);Режим;Температура камеры (°C)\n"
           "18:18:29;воздух;15468;11092;25,8;28,4;;25,0\n")
    points = stub._chamber_parse_journal(old)
    assert len(points) == 1 and "samples" not in points[0] and points[0]["chamber_temp_x10"] == 250
    assert stub._chamber_parse_journal("Время;Что-то другое\n1;2\n") is None


def test_board_results_show_coverage_and_drift():
    result = board_results(P6, "П6", "0x86")
    assert result["stage1"] == "7/7" and result["stage2"] == "3/7" and not result["liquid"]
    assert result["tone"] == "warn" and "сухая трубка - нет узлов -40 °C, -20 °C, +70 °C, +85 °C" in result["verdict"]
    coverage, stage1, stage2 = result["tables"][:3]
    assert _cells(coverage, "node", "-40 °C")["cells"]["stage2"] == "вне допуска (+7,5 °C)"
    assert _cells(coverage, "node", "+25 °C")["cells"]["stage2"] == "засчитана"
    assert _cells(stage1, "node", "+25 °C")["cells"]["mainChange"] == "опора"
    hot = _cells(stage1, "node", "+85 °C")["cells"]
    assert (hot["mediaChange"], hot["mediaPct"]) == ("+16", "+0,36 %")
    last = stage2["rows"][-1]
    assert last["tone"] == "warn" and last["cells"]["status"] == "вне допуска ±3 °C"
    assert (last["cells"]["mainChange"], last["cells"]["mainPct"], last["cells"]["mainChangePf"]) == \
        ("+439", "+2,84 %", "+10,73")
    assert last["cells"]["spread"] == "24 / 6" and stage2["rows"][1]["cells"]["spread"] == "—"
    labels = {item["label"]: item["value"] for item in result["summary"]}
    assert labels["Наибольший разброс в окне усреднения"] == "24 отсч."
    assert labels["Этап 2: наибольший уход основного контура"].startswith("+439 отсч. (+2,84 %, +10,7 пФ)")


def test_every_column_is_explained():
    for table in board_results(P6, "П6", "0x86")["tables"]:
        assert table["tip"]
        for column in table["columns"]:
            assert column["tip"] or column["key"] in ("points", "verdict"), (table["id"], column["key"])
    pct = next(column for column in board_results(P6)["tables"][1]["columns"] if column["key"] == "mainPct")
    assert "от показания при +25 °C" in pct["tip"]


def test_overview_and_text_for_the_archive():
    boards = [board_results(P6, "П6", "0x86"), board_results(P6[:7], "П1", "0x81")]
    overview = overview_table(boards)
    assert [row["cells"]["stage2"] for row in overview["rows"]] == ["3/7", "—"]
    assert overview["rows"][1]["tone"] == "ok", "только первый этап и он полный"
    text = results_text({"boards": boards, "overview": overview, "time": "09.11.2026 10:00"})
    assert "Сводка по платам" in text and "=== 0x86 (П6)" in text and "ПОЯСНЕНИЯ К СТОЛБЦАМ" in text
    assert "| вне допуска ±3 °C" in text


def test_run_bundle_has_all_boards(tmp_path: Path):
    from tests.test_multiboard import BOARDS, _MbStub
    from ui.qml.controller.climate_control_mixin import AppControllerClimateControlMixin

    class _BundleStub(AppControllerClimateControlMixin, _MbStub):
        pass

    stub = _BundleStub(tmp_path)
    for sa, name, _offset, _main in BOARDS:
        assert stub._mb_add_board(f"0x{sa:02X}", name)[0]
    assert stub._mb_set_enabled(True)[0]
    stub._mb_working_boards = lambda now=None: list(stub._mb_boards)
    logs = stub._climate_logs_directory()
    logs.mkdir(parents=True, exist_ok=True)
    for sa, name, _offset, _main in BOARDS:
        with stub._mb_context(sa, notify=False):
            journal = logs / f"chamber_x_{name}_0x{sa:02X}.csv"
            stub._chamber_points = list(P6)
            assert stub._chamber_write_csv(str(journal)) is None
            journal.with_name(journal.stem + "_profile.json").write_text("{}", encoding="utf-8")
            stub._chamber_file_path = str(journal)
    (logs / f"chamber_{date.today().isoformat()}.log").write_text("журнал", encoding="utf-8")
    stub._climate_trace_path = logs / "run_20261106_174952.csv"
    stub._climate_trace_path.write_text("ход", encoding="utf-8")
    stub._climate_save_report = lambda: ""
    path = stub._control_run_bundle()
    assert path and Path(path).name.startswith("архив_прогона_")
    names = zipfile.ZipFile(path).namelist()
    for sa, name, _offset, _main in BOARDS:
        assert f"журналы_плат/chamber_x_{name}_0x{sa:02X}.csv" in names
        assert f"журналы_плат/chamber_x_{name}_0x{sa:02X}_profile.json" in names
    assert "ход_прогона/run_20261106_174952.csv" in names and "итоги_прогона.txt" in names
    assert f"журнал_камеры/chamber_{date.today().isoformat()}.log" in names
    summary = zipfile.ZipFile(path).read("итоги_прогона.txt").decode("utf-8-sig")
    assert "Сводка по платам" in summary
    ok, text, _detail = stub._control_do_send_file({"id": ""}, {"which": "bundle"})
    assert ok and "архив_прогона_" in text, "с сайта без Telegram архив готов к скачиванию"


def test_page_has_run_subtabs_and_classic_tables():
    """«Прогон» в мини-приложении - подвкладками; таблицы - с сеткой, шапкой и строками через одну."""
    page = (Path(__file__).resolve().parents[1] / "ui" / "qml" / "telegram_miniapp.html").read_text(encoding="utf-8")
    tabs = page[page.index('<div class="subtabs" id="runTabs">'):page.index("</div>", page.index('id="runTabs"'))]
    assert [name for name in ("run", "results", "scenario", "journal", "profile") if f'data-sub="{name}"' in tabs] == \
        ["run", "results", "scenario", "journal", "profile"]
    run = page[page.index('<section class="tab" id="tab-run">'):page.index("</section>", page.index('id="tab-run"'))]
    assert run.count('class="card') == run.count("data-sub=") - 5, "каждая карточка «Прогона» - в своей подвкладке"
    assert ".tbl tr:nth-child(even) td" in page and "border: 1px solid var(--grid)" in page
    assert '<table class="tbl"><tr><th>Правило</th><th>Значение</th><th>Ед.</th></tr>' in page
    card = (Path(__file__).resolve().parents[1] / "ui" / "qml" / "components" / "ChamberCard.qml").read_text(encoding="utf-8")
    assert '"Основной, отсч.", "Вид топлива, отсч."' in card and "rowColor" in card


def test_window_run_section_is_split_into_tabs():
    """«Прогон в камере» в окне: вкладки; каждая крупная часть видна только на своей вкладке."""
    card = (Path(__file__).resolve().parents[1] / "ui" / "qml" / "components" / "ChamberCard.qml").read_text(encoding="utf-8")
    for key in ("points", "results", "profile", "journals", "boards", "test"):
        assert f'"key": "{key}"' in card and f'root.page === "{key}"' in card, key
    page = (Path(__file__).resolve().parents[1] / "ui" / "qml" / "telegram_miniapp.html").read_text(encoding="utf-8")
    assert "const swipeTo" in page and "disableVerticalSwipes" in page and 'class="tbl rsumt"' in page


def test_repeatability_names_the_board(tmp_path: Path):
    """Несколько плат: предупреждение о повторяемости называет плату (иначе шесть одинаковых не различить)."""
    from tests.test_multiboard import BOARDS, _stub

    stub = _stub(tmp_path)
    events = []
    stub._climate_event = lambda text, level="info", kind="event": events.append(text)
    stub._remote_multi = lambda: True
    sa, name = BOARDS[1][0], BOARDS[1][1]
    with stub._mb_context(sa, notify=False):
        stub._chamber_points = [_p("воздух", 28.4, 25.8, 15468, 11092)]
        stub._chamber_points.append(_p("воздух", 27.9, 25.1, 15503, 11120))
        stub._chamber_repeatability(stub._chamber_points[-1])
    assert events and events[-1].startswith(f"0x{sa:02X} ({name}): повторяемость в узле +25 °C нарушена: основной 15503 против "
                                             "15468 (+35)"), events
