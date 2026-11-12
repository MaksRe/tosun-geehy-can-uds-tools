"""Сообщения карточкой и метки узлов по двум этапам (08.11.2026).

В окне копились длинные строки состояния, проверок и замечаний. Теперь сообщение - строка «значок +
заголовок», а разбор (что произошло, почему, что сделать, полный текст) - по нажатию. Цвет значка -
по важности. Метки узлов в плитке платы разделены: «плата» (первый этап) и «в сборе» (сухая трубка
по датчику трубки), отдельно - снята ли «жидкость».

Тесты закрепляют:
- разбор живых сообщений программы: короткий заголовок, совет («поставьте», «нажмите») - в «что сделать»;
- уровень по цвету строки и по слову уровня;
- замечания расчёта таблиц - с пояснением, написанным заранее;
- одинаковые сообщения в списке сливаются со счётом, уровень строки - самый тяжёлый;
- метки узлов: точка первого этапа красит «плату», «воздух» у узла - «в сборе», «воздух» мимо узла - нет.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.notices import explain_remark, level_of, make_notice, notice_list  # noqa: E402


def test_point_status_gets_a_short_title_and_a_list():
    notice = make_notice(
        "Точка «воздух» записана (среднее за 9 с по 9 показаниям, разброс 0 / 0), температура платы +95.0 °C "
        "далеко от узлов сетки, в расчёт ступени платы точка не попадёт. Всего точек: 14. "
        "Журнал сохранён: chamber_20261020_011249.csv.", "#d97706", "Журнал")
    assert notice["level"] == "warn" and notice["glyph"] == "!" and notice["kind"] == "Журнал"
    assert notice["title"] == "Точка «воздух» записана"
    assert notice["what"][0] == "Среднее за 9 с по 9 показаниям, разброс 0 / 0."
    assert any("далеко от узлов сетки" in line for line in notice["what"])
    assert notice["detail"].startswith("Точка «воздух» записана (среднее")


def test_advice_after_a_colon_goes_to_todo():
    notice = make_notice(
        "плата не дошла до шага -20,0 °C: устоялась при -16,6 °C (допуск ±1 °C), камеру ведёт программа пульта, "
        "уставку программа не двигает: чтобы плата пришла к -20,0 °C, поставьте этот шаг на пульте ≈ -23,1 °C.",
        "warn")
    assert notice["title"] == "Плата не дошла до шага -20,0 °C"
    assert notice["todo"] == ["Чтобы плата пришла к -20,0 °C, поставьте этот шаг на пульте ≈ -23,1 °C."]
    assert all("поставьте" not in line for line in notice["what"])


def test_imperative_sentence_and_semicolon_list():
    notice = make_notice(
        "Второй этап: «П2» - в журнале нет узлов -40, -20, 0; «П1» - журнал первого этапа не открыт. "
        "Нажмите «Журналы первого этапа всем платам»: программа сама откроет каждой плате её журнал", "#dc2626")
    assert notice["level"] == "error" and notice["title"] == "Второй этап"
    assert notice["what"] == ["«П2» - в журнале нет узлов -40, -20, 0.", "«П1» - журнал первого этапа не открыт."]
    assert notice["todo"][0].startswith("Нажмите «Журналы первого этапа всем платам»")


def test_levels_by_color_and_word():
    assert level_of("#dc2626") == "error" and level_of("bad") == "error" and level_of("block") == "error"
    assert level_of("#b45309") == "warn" and level_of("warn") == "warn"
    assert level_of("#16a34a") == "ok" and level_of("ok") == "ok"
    assert level_of("#64748b") == "info" and level_of("") == "info"
    assert make_notice("", "bad")["title"] == ""


def test_known_remarks_are_explained():
    dry = explain_remark("нет замера сухой трубки в узлах: -40 °C, -20 °C, +70 °C, +85 °C")
    assert dry["level"] == "warn" and dry["title"] == "Нет сухой трубки в узлах -40 °C, -20 °C, +70 °C, +85 °C"
    assert dry["why"] and len(dry["todo"]) == 2 and "3 °C" in dry["what"][0]
    span = explain_remark("строки «в жидкости» для основного контура не достроены: размах не задан и ни в одном "
                          "узле не снята пара состояний")
    assert span["title"] == "Строки «в жидкости» (основного контура) не достроены"
    assert any("жидкость" in line for line in span["todo"])
    fyi = explain_remark("к сведению: таблица платы - по одной своей ёмкости (весь уход отнесён к модели "
                         "«растяжение»): строки трубки посчитаны после неё, а при подключённой трубке такая "
                         "поправка - допущение")
    assert fyi["level"] == "info" and fyi["title"] == "Таблица платы посчитана по одной ёмкости"
    unknown = explain_remark("что-то новое: без пояснения")
    assert unknown["level"] == "warn" and unknown["title"] == "Что-то новое"


def test_list_merges_repeats_and_takes_the_worst_level():
    alerts = notice_list([
        {"text": "камера не идёт к уставке -20,0 °C: за 20 мин приблизилась на 0.9 °C, сейчас +3,9 °C", "level": "warn"},
        {"text": "камера не идёт к уставке -20,0 °C: за 20 мин приблизилась на 0.9 °C, сейчас +3,8 °C", "level": "warn"},
        {"text": "нет связи с камерой дольше 30 с.", "level": "bad"},
    ], "warn", "Прогон", "Проблемы прогона: {count}")
    assert alerts["level"] == "error" and alerts["title"] == "Проблемы прогона: 3"
    assert [(item["level"], item["count"]) for item in alerts["items"]] == [("error", 1), ("warn", 2)]
    assert alerts["what"] == [] and alerts["detail"] == ""
    single = notice_list(["нет замера сухой трубки в узлах: +85 °C"], remarks=True, kind="Таблицы",
                         title="Замечаний {count}")
    assert single["title"] == "Нет сухой трубки в узлах +85 °C" and single["items"] == []
    assert notice_list([], title="Пусто {count}")["title"] == "", "пустой список - строка скрыта"


def test_node_marks_split_board_and_assembly(tmp_path: Path):
    from tests.test_multiboard import BOARDS, _stub

    stub = _stub(tmp_path)
    sa = BOARDS[0][0]

    def point(note, board_c, fuel_c):
        return {"time": "00:00:00", "note": note, "main": 15400, "media": 11000,
                "board_temp_x10": int(board_c * 10), "fuel_temp_x10": int(fuel_c * 10)}

    with stub._mb_context(sa):
        stub._chamber_points = [
            point("0/0", 25.5, 22.8), point("0/0", -39.1, -40.1),
            # Второй этап: трубка у узла +25 - в сборе; у -40 трубка -32,5 - мимо узла.
            point("воздух", 28.4, 25.8), point("воздух", -32.2, -32.5),
        ]
        marks = {mark["short"]: mark for mark in stub._mb_node_marks()}
        stages = stub._mb_assembly_state(list(marks.values()))
    assert marks["25"]["board"] and marks["25"]["air"] == 1
    assert marks["-40"]["board"] and marks["-40"]["air"] == 0
    assert not marks["0"]["board"] and marks["0"]["air"] == 0
    assert "сухая трубка есть" in marks["25"]["tip"] and "сухая трубка нет" in marks["-40"]["tip"]
    assert stages == {"air": 1, "liquid": False, "board": 2, "total": 7}


def test_page_gets_notices():
    """Мини-приложение и сайт: те же карточки в снимке состояния (notices)."""
    from ui.qml.controller.remote_monitor_mixin import AppControllerRemoteMonitorMixin

    notices = AppControllerRemoteMonitorMixin._remote_notices({
        "run": {"status": "Таблицы пересчитаны (сумма 0xBB30), но данных хватило не везде: замечаний 1.",
                "statusColor": "#d97706", "tablesText": "", "tablesColor": "",
                "report": ["нет замера сухой трубки в узлах: +85 °C"]},
        "climate": {"ok": False, "status": "камера не ответила по RS-232: проверьте кабель (нуль-модем)",
                    "run": {"status": "", "auto": {"alerts": [{"text": "нет связи с камерой дольше 30 с.",
                                                               "level": "bad", "time": "15:37"}]}}},
        "chain": {"status": "Профиль записан в плату, сумма 0x66E8.", "color": "#16a34a"},
    })
    assert notices["journal"]["level"] == "warn" and notices["tables"]["title"] == ""
    assert notices["report"]["title"] == "Нет сухой трубки в узлах +85 °C"
    assert notices["climate"]["level"] == "error" and notices["climate"]["todo"]
    assert notices["alerts"]["title"] == "Нет связи с камерой дольше 30 с" and notices["chain"]["level"] == "ok"
    page = (Path(__file__).resolve().parents[1] / "ui" / "qml" / "telegram_miniapp.html").read_text(encoding="utf-8")
    assert "const noticeHtml" in page and "nodeRowsHtml(b)" in page and "(s.notices || {}).report" in page


def test_window_uses_notice_lines():
    """Длинные строки окна - через NoticeLine; справка - под значком «i»."""
    components = Path(__file__).resolve().parents[1] / "ui" / "qml" / "components"
    chamber = (components / "ChamberCard.qml").read_text(encoding="utf-8")
    climate = (components / "ClimateChamberCard.qml").read_text(encoding="utf-8")
    assert "Чего не хватило расчёту: замечаний {count}" in chamber and "remarks: true" in chamber
    assert chamber.count("NoticeLine {") >= 5 and climate.count("NoticeLine {") >= 15
    assert "Нужно, когда в камеру нельзя ставить топливо" in chamber.split("InfoMark {", 2)[2]
    strip = (components / "BoardsStrip.qml").read_text(encoding="utf-8")
    assert 'field: "board"' in strip and 'field: "air"' in strip
