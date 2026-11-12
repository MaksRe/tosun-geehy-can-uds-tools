"""Итоги прогона в камере: таблицы по узлам и этапам для окна программы, сайта и мини-приложения.

09.11.2026: оператору нужна сводка, по которой сразу видно, удался ли прогон, - без скачивания файлов.
Модуль строит её из точек журнала одной платы:

- «Покрытие узлов» - по каждому узлу сетки: снят ли первый этап (плата с эталонами), сухая трубка
  и «жидкость», и насколько температура трубки отошла от узла;
- «Этап 1» - плата без трубки: показания в узлах, ёмкость, изменение относительно +25 °C;
- «Этап 2» - изделие в сборе, сухая трубка: каждая точка «воздух», засчитана ли она в узел;
- «Погружение» - точки «жидкость» и размах (полная минус сухая трубка);
- сводные показатели: сколько узлов снято, наибольший уход, наибольший разброс.

Таблица - простые строки: столбцы (заголовок, единица, подсказка) и ячейки уже отформатированы,
поэтому окно и страница рисуют её одинаково. Подсказки к столбцам объясняют, что значит число и от
чего считается процент. Ёмкость - оценка по номиналам схемы (capacitance.py), отсчёты - измерение.
"""

from __future__ import annotations

import chamber_fit
from ui.qml.capacitance import COUNTS_PER_PF

TOLERANCE_C = chamber_fit.NODE_TOLERANCE_X10 / 10.0
REFERENCE_C = chamber_fit.REFERENCE_X10 / 10.0

# Подсказки к столбцам: одно и то же понятие объясняется одинаково во всех таблицах.
TIPS = {
    "node": "Узел температурной сетки прибора. В профиле прибора поправка задаётся для каждого из 7 узлов: "
            "−40, −20, 0, +25, +50, +70, +85 °C.",
    "air": "Температура воздуха в камере в момент точки (по датчику камеры).",
    "board": "Температура платы по её собственному датчику, среднее за окно усреднения.",
    "tube": "Температура трубки (датчик топлива прибора), среднее за окно усреднения. По ней точки второго "
            "этапа относятся к узлам - так же их применяет прибор.",
    "board_dev": "Температура платы минус температура узла. Точка первого этапа идёт в таблицу узла, если "
                 f"отклонение не больше ±{TOLERANCE_C:.0f} °C.",
    "tube_dev": "Температура трубки минус температура ближайшего узла. Точка идёт в таблицу узла, если "
                f"отклонение не больше ±{TOLERANCE_C:.0f} °C.",
    "status": f"«Засчитана» - точка в допуске ±{TOLERANCE_C:.0f} °C и вошла в расчёт строки узла. "
              "«Вне допуска» - точка записана в журнал, но в расчёт не вошла: узел остаётся без данных.",
    "measurement_status": "Состояние отдельной записи: температура распознанной рабочей точки попала в допуск "
                          "±3 °C к узлу или находится вне него. Попадание в допуск не подтверждает готовность "
                          "таблиц и использование точки в расчёте. Пробы и неизвестные пометки не подтверждают "
                          "рабочую калибровку.",
    "note": "Что было подключено к входам прибора: номинал эталона основного контура / контура вида топлива, "
            "пФ. «0/0» - к входам ничего не подключено (своя ёмкость платы).",
    "counts": "Период контура - число отсчётов таймера 72 МГц за время перезаряда датчика, среднее за окно "
              "усреднения. Чем больше ёмкость, тем больше отсчётов.",
    "pf": f"Полная ёмкость контура, оценка по номиналам схемы: {COUNTS_PER_PF:.1f} отсчёта = 1 пФ. Включает "
          "образцовый конденсатор 100 пФ, кабель, разъём и плату. Отсчёты - измерение, пикофарады - оценка.",
    "change": "Изменение показания относительно точки при +25 °C того же этапа (и той же пометки): "
              "показание в узле минус показание при +25 °C, в отсчётах. «опора» - сама точка при +25 °C.",
    "pct": "То же изменение в процентах от показания при +25 °C: "
           "(показание − показание при +25 °C) / показание при +25 °C × 100 %.",
    "change_pf": "То же изменение в пикофарадах (оценка): изменение в отсчётах / 40,9.",
    "samples": "Сколько показаний прибора усреднено в эту точку (окно усреднения). Журналы до 09.11.2026 "
               "этого не хранят - там «—».",
    "spread": "Разброс показаний в окне усреднения: наибольшее минус наименьшее, в отсчётах. Показывает шум "
              "измерения: у спокойного контура это единицы отсчётов. «—» - журнал до 09.11.2026.",
    "when": "Дата и время записи точки. Дата есть у точек с 09.11.2026.",
    "span": "Размах - показание с трубкой в топливе минус показание сухой трубки при той же температуре. "
            "По нему прибор пересчитывает показание в уровень.",
    "stage1": "Первый этап: плата без трубки, к входам подключены эталоны (или ничего - «0/0»). Даёт таблицу "
              "поправки самой платы по температуре.",
    "stage2": "Второй этап: изделие в сборе, трубка сухая (пометка «воздух»). Даёт строки трубки по температуре.",
    "liquid": "Трубка погружена в топливо (пометка «жидкость»). Снимается при комнатной температуре; вместе "
              "с сухой трубкой даёт размах.",
}


def _fmt(value, digits=1, sign=True, unit=""):
    if value is None:
        return "—"
    text = f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"
    return text.replace(".", ",").replace("-", "−") + unit


def _int(value, sign=False):
    if value is None:
        return "—"
    text = f"{int(value):+d}" if sign else str(int(value))
    return text.replace("-", "−")


def _pct(change, base):
    if change is None or not base:
        return None
    return change / float(base) * 100.0


def _when(point):
    date = str(point.get("date", "") or "")
    if len(date) == 10:
        return f"{date[8:10]}.{date[5:7]} {point.get('time', '')}"
    return str(point.get("time", ""))


def _column(key, title, tip_key=None, align="right", width=0):
    """Столбец таблицы; width - ширина в пикселях окна, 0 - по длине заголовка."""
    return {"key": key, "title": title, "tip": TIPS.get(tip_key or key, ""), "align": align, "width": width}


def _is_stage1(point):
    refs = chamber_fit.parse_references(point.get("note", ""))
    return refs["main"] is not None or refs["media"] is not None


def _note(point):
    return str(point.get("note", "")).strip().casefold()


def _channel_cells(prefix, value, base, is_base=False):
    change = None if value is None or base is None else value - base
    return {
        f"{prefix}": _int(value),
        f"{prefix}Pf": _fmt(None if value is None else value / COUNTS_PER_PF, 1, sign=False),
        f"{prefix}Change": "опора" if is_base else _int(change, sign=True),
        f"{prefix}Pct": _fmt(_pct(change, base), 2, unit=" %"),
        f"{prefix}ChangePf": _fmt(None if change is None else change / COUNTS_PER_PF, 2),
    }


def _spread(point):
    main, media = point.get("main_spread"), point.get("media_spread")
    if main is None and media is None:
        return "—"
    return f"{_int(main)} / {_int(media)}"


def _stage1_table(points):
    rows, worst, covered = [], None, set()
    notes = []
    for point in points:
        if point.get("rehearsal") or not _is_stage1(point):
            continue
        if point["note"] not in notes:
            notes.append(point["note"])
    for note in notes:
        same = [p for p in points if not p.get("rehearsal") and p["note"] == note]
        by_node = {}
        for point in same:
            node = chamber_fit.nearest_node(point["board_temp_x10"])
            if node is not None:
                by_node[node] = point  # последняя точка узла
        base = by_node.get(chamber_fit.REFERENCE_X10)
        for node in chamber_fit.NODES_X10:
            point = by_node.get(node)
            if point is None:
                rows.append({"tone": "bad", "cells": {"node": chamber_fit.node_text(node), "note": note,
                                                      "status": "нет точки"}})
                continue
            covered.add(node)
            cells = {"node": chamber_fit.node_text(node), "note": note, "status": "снята",
                     "air": _fmt(None if point.get("chamber_temp_x10") is None else point["chamber_temp_x10"] / 10),
                     "board": _fmt(point["board_temp_x10"] / 10),
                     "boardDev": _fmt((point["board_temp_x10"] - node) / 10),
                     "samples": _int(point.get("samples")), "spread": _spread(point), "when": _when(point)}
            cells |= _channel_cells("main", point["main"], None if base is None else base["main"], point is base)
            cells |= _channel_cells("media", point["media"], None if base is None else base["media"], point is base)
            for key, value, ref in (("main", point["main"], base and base["main"]),
                                    ("media", point["media"], base and base["media"])):
                if value is None or not ref:
                    continue
                change = value - ref
                if worst is None or abs(_pct(change, ref)) > abs(worst[1]):
                    worst = (change, _pct(change, ref), key, node)
            rows.append({"tone": "ok", "cells": cells})
    columns = [
        _column("node", "Узел", align="center"), _column("note", "Эталоны осн./вид, пФ", "note", "center"),
        _column("status", "Точка", "stage1", "center"),
        _column("air", "Воздух, °C"), _column("board", "Плата, °C"), _column("boardDev", "Плата − узел, °C", "board_dev"),
        _column("main", "Осн. контур, отсч.", "counts"), _column("mainPf", "Осн., пФ", "pf"),
        _column("mainChange", "Δ осн. от +25 °C, отсч.", "change"), _column("mainPct", "Δ осн., %", "pct"),
        _column("media", "Вид топлива, отсч.", "counts"), _column("mediaPf", "Вид, пФ", "pf"),
        _column("mediaChange", "Δ вида от +25 °C, отсч.", "change"), _column("mediaPct", "Δ вида, %", "pct"),
        _column("samples", "Показаний"), _column("spread", "Разброс осн./вид, отсч.", "spread", "center"),
        _column("when", "Дата, время", align="center"),
    ]
    return {"id": "stage1", "title": "Этап 1. Плата без трубки", "tip": TIPS["stage1"],
            "columns": columns, "rows": rows}, covered, worst, bool(notes)


def _tube_points(points, note):
    return [p for p in points if not p.get("rehearsal") and _note(p) == note]


def _stage2_table(points):
    air = _tube_points(points, chamber_fit.AIR_NOTE)
    counted = {}
    for point in air:
        node = chamber_fit.nearest_node(point["fuel_temp_x10"])
        if node is not None:
            counted[node] = point
    base = counted.get(chamber_fit.REFERENCE_X10)
    rows, worst = [], None
    for point in air:
        tube = point["fuel_temp_x10"]
        nearest = min(chamber_fit.NODES_X10, key=lambda node: abs(node - tube))
        inside = abs(nearest - tube) <= chamber_fit.NODE_TOLERANCE_X10
        cells = {"when": _when(point),
                 "air": _fmt(None if point.get("chamber_temp_x10") is None else point["chamber_temp_x10"] / 10),
                 "tube": _fmt(tube / 10), "nearest": chamber_fit.node_text(nearest),
                 "tubeDev": _fmt((tube - nearest) / 10),
                 "status": "засчитана" if inside else f"вне допуска ±{TOLERANCE_C:.0f} °C",
                 "board": _fmt(point["board_temp_x10"] / 10),
                 "samples": _int(point.get("samples")), "spread": _spread(point)}
        cells |= _channel_cells("main", point["main"], None if base is None else base["main"], point is base)
        cells |= _channel_cells("media", point["media"], None if base is None else base["media"], point is base)
        if base is not None and base["main"]:
            change = point["main"] - base["main"]
            if worst is None or abs(change) > abs(worst[0]):
                worst = (change, _pct(change, base["main"]), tube)
        rows.append({"tone": "ok" if inside else "warn", "cells": cells})
    columns = [
        _column("when", "Дата, время", align="center"), _column("air", "Воздух, °C"), _column("tube", "Трубка, °C"),
        _column("nearest", "Ближайший узел", "node", "center"), _column("tubeDev", "Трубка − узел, °C", "tube_dev"),
        _column("status", "Зачёт в узел", "status", "center", 150), _column("board", "Плата, °C"),
        _column("main", "Осн. контур, отсч.", "counts"), _column("mainPf", "Осн., пФ", "pf"),
        _column("mainChange", "Δ осн. от +25 °C, отсч.", "change"), _column("mainPct", "Δ осн., %", "pct"),
        _column("mainChangePf", "Δ осн., пФ", "change_pf"),
        _column("media", "Вид топлива, отсч.", "counts"), _column("mediaPf", "Вид, пФ", "pf"),
        _column("mediaChange", "Δ вида от +25 °C, отсч.", "change"), _column("mediaPct", "Δ вида, %", "pct"),
        _column("samples", "Показаний"), _column("spread", "Разброс осн./вид, отсч.", "spread", "center"),
    ]
    return {"id": "stage2", "title": "Этап 2. Изделие в сборе, сухая трубка", "tip": TIPS["stage2"],
            "columns": columns, "rows": rows}, counted, worst, bool(air)


def _liquid_table(points, dry):
    liquid = _tube_points(points, chamber_fit.LIQUID_NOTE)
    rows = []
    for point in liquid:
        node = chamber_fit.nearest_node(point["fuel_temp_x10"])
        pair = dry.get(node) if node is not None else None
        span_main = None if pair is None else point["main"] - pair["main"]
        span_media = None if pair is None or point["media"] is None or pair["media"] is None \
            else point["media"] - pair["media"]
        rows.append({"tone": "ok" if pair is not None else "warn", "cells": {
            "when": _when(point), "tube": _fmt(point["fuel_temp_x10"] / 10),
            "nearest": "—" if node is None else chamber_fit.node_text(node),
            "main": _int(point["main"]), "media": _int(point["media"]),
            "spanMain": _int(span_main, sign=True), "spanMedia": _int(span_media, sign=True),
            "spanMainPf": _fmt(None if span_main is None else span_main / COUNTS_PER_PF, 1),
            "status": "есть пара с сухой трубкой" if pair is not None else "нет сухой трубки при этой температуре",
        }})
    columns = [
        _column("when", "Дата, время", align="center"), _column("tube", "Трубка, °C"),
        _column("nearest", "Узел", "node", "center"),
        _column("main", "Осн. контур, отсч.", "counts"), _column("media", "Вид топлива, отсч.", "counts"),
        _column("spanMain", "Размах осн., отсч.", "span"), _column("spanMainPf", "Размах осн., пФ", "span"),
        _column("spanMedia", "Размах вида, отсч.", "span"), _column("status", "Пара", "span", "center"),
    ]
    return {"id": "liquid", "title": "Погружение в топливо", "tip": TIPS["liquid"],
            "columns": columns, "rows": rows}, bool(liquid)


def _coverage_table(points, stage1_nodes, counted, has_stage1, has_air):
    air = _tube_points(points, chamber_fit.AIR_NOTE)
    liquid = _tube_points(points, chamber_fit.LIQUID_NOTE)
    rows = []
    for node in chamber_fit.NODES_X10:
        # Ближайшая к узлу точка «воздух», даже вне допуска: видно, насколько не дошла трубка.
        near = min(air, key=lambda p: abs(p["fuel_temp_x10"] - node), default=None)
        near_dev = None if near is None else (near["fuel_temp_x10"] - node) / 10
        own = near is not None and min(chamber_fit.NODES_X10,
                                       key=lambda grid: abs(grid - near["fuel_temp_x10"])) == node
        stage1 = node in stage1_nodes
        dry = node in counted
        wet = any(chamber_fit.nearest_node(p["fuel_temp_x10"]) == node for p in liquid)
        if not has_air:
            dry_text = "этап не снимался"
        elif dry:
            dry_text = "засчитана"
        elif own:
            dry_text = f"вне допуска ({_fmt(near_dev)} °C)"
        else:
            dry_text = "нет точки"
        tone = "ok" if (stage1 or not has_stage1) and (dry or not has_air) else "warn"
        rows.append({"tone": tone, "cells": {
            "node": chamber_fit.node_text(node),
            "stage1": ("снята" if stage1 else "нет точки") if has_stage1 else "этап не снимался",
            "stage2": dry_text,
            "tubeDev": _fmt(near_dev) if own or dry else "—",
            "liquid": "снята" if wet else "—",
        }})
    columns = [
        _column("node", "Узел", align="center"),
        _column("stage1", "Этап 1: плата", "stage1", "center"),
        _column("stage2", "Этап 2: сухая трубка", "status", "center", 190),
        _column("tubeDev", "Трубка − узел, °C", "tube_dev"),
        _column("liquid", "Погружение", "liquid", "center"),
    ]
    return {"id": "coverage", "title": "Покрытие узлов",
            "tip": "Что снято в каждом узле температурной сетки по этапам. Таблица профиля полная, когда в "
                   "каждом узле есть первый этап и засчитанная сухая трубка, а погружение снято хотя бы один раз.",
            "columns": columns, "rows": rows}


def _measurements_table(points: list[dict]) -> dict:
    """Для проверки фактических температур сохраняет все измерения, включая точки вне допуска и пробы."""
    bases = {}
    for point in points:
        tube = _note(point) in (chamber_fit.AIR_NOTE, chamber_fit.LIQUID_NOTE)
        field = "fuel_temp_x10" if tube else "board_temp_x10"
        if (tube or _is_stage1(point)) and not point.get("rehearsal") \
                and chamber_fit.nearest_node(point[field]) == chamber_fit.REFERENCE_X10:
            bases[_note(point)] = point
    rows = []
    for point in points:
        tube = _note(point) in (chamber_fit.AIR_NOTE, chamber_fit.LIQUID_NOTE)
        field = "fuel_temp_x10" if tube else "board_temp_x10"
        node = chamber_fit.nearest_node(point[field])
        base = bases.get(_note(point))
        rehearsal = bool(point.get("rehearsal"))
        recognized = tube or _is_stage1(point)
        # Чтобы не обещать участие в расчёте, показываем только распознавание точки и допуск температуры.
        status = ("проба" if rehearsal else "пометка не распознана" if not recognized
                  else "в допуске ±3 °C" if node is not None else "вне допуска ±3 °C")
        cells = {"when": _when(point), "note": point.get("note", ""),
                 "node": chamber_fit.node_text(node) if node is not None else "—",
                 "status": status,
                 "air": _fmt(None if point.get("chamber_temp_x10") is None else point["chamber_temp_x10"] / 10),
                 "board": _fmt(point["board_temp_x10"] / 10), "tube": _fmt(point["fuel_temp_x10"] / 10),
                 "samples": _int(point.get("samples")), "spread": _spread(point)}
        for key in ("main", "media"):
            cells |= _channel_cells(key, point.get(key), None if base is None or rehearsal else base.get(key),
                                    point is base)
        rows.append({"tone": "info" if rehearsal else "ok" if recognized and node is not None else "warn",
                     "cells": cells})
    columns = [_column("when", "Дата, время", align="center"), _column("note", "Пометка", "note", "left"),
               _column("node", "Узел", align="center"),
               _column("status", "Состояние точки", "measurement_status", "left"),
               _column("board", "Плата, °C"), _column("tube", "Топливо, °C"), _column("air", "Камера, °C"),
               _column("main", "Осн., отсч.", "counts"), _column("media", "Вид, отсч.", "counts"),
               _column("mainPf", "Осн., пФ", "pf"), _column("mediaPf", "Вид, пФ", "pf"),
               _column("mainChange", "Δ осн., отсч.", "change"), _column("mainPct", "Δ осн., %", "pct"),
               _column("mediaChange", "Δ вида, отсч.", "change"), _column("mediaPct", "Δ вида, %", "pct"),
               _column("samples", "Показаний"), _column("spread", "Разброс осн./вид", "spread")]
    return {"id": "measurements", "title": "Все зафиксированные точки", "columns": columns, "rows": rows,
            "tip": "Все записи журнала с фактическими температурами. Узел первого этапа определяется по плате, "
                   "сухой трубки и погружения — по топливу. Пробы в рабочие результаты не входят. "
                   "Изменения рассчитаны от последней распознанной рабочей точки +25 °C с той же пометкой. "
                   "Состояние строки показывает допуск температуры, а готовность калибровки проверяется отдельно."}


def combined_table(boards: list[dict]) -> dict:
    """Для сравнения плат объединяет их измерения и рассчитанные изменения с отдельным столбцом CAN-адреса."""
    rows, columns = [], []
    for board in boards:
        table = next((item for item in board.get("tables", []) if item["id"] == "measurements"), None)
        if table is None:
            continue
        columns = table["columns"]
        for row in table["rows"]:
            rows.append({"tone": row["tone"], "cells": dict(row["cells"], sa=board["sa"], name=board["name"])})
    identity = [{"key": "sa", "title": "CAN-адрес", "tip": "Адрес SA платы на шине CAN.", "align": "left"},
                {"key": "name", "title": "Плата", "tip": "Имя платы в списке камеры.", "align": "left"}]
    return {"id": "combined", "title": "Все платы: измерения и результаты", "columns": identity + columns,
            "rows": rows, "tip": "Все записи всех плат по CAN-адресам, включая точки вне допуска. "
                                 "Для каждой платы изменения рассчитаны относительно её собственной опорной точки."}


def board_results(points, name: str = "", sa_text: str = "", span_known: bool = False) -> dict:
    """Итоги прогона одной платы: сводные показатели и таблицы.

    span_known - строки «в жидкости» достраиваются по размаху, заданному вручную: погружение в
    камере тогда не нужно, и его отсутствие не недостаток (12.11.2026: проверочный прогон с сухими
    трубками после записи профиля выдавал «Данных не хватает: погружение не снято»).
    """
    points = [p for p in points or [] if p.get("main") is not None]
    stage1, stage1_nodes, worst1, has_stage1 = _stage1_table(points)
    stage2, counted, worst2, has_air = _stage2_table(points)
    liquid, has_liquid = _liquid_table(points, counted)
    coverage = _coverage_table(points, stage1_nodes, counted, has_stage1, has_air)
    total = len(chamber_fit.NODES_X10)
    spreads = [max(p.get("main_spread") or 0, p.get("media_spread") or 0) for p in points
               if p.get("main_spread") is not None or p.get("media_spread") is not None]

    summary = []
    if has_stage1:
        summary.append({"label": "Этап 1: узлов снято", "value": f"{len(stage1_nodes)} из {total}",
                        "tone": "ok" if len(stage1_nodes) == total else "warn", "tip": TIPS["stage1"]})
    if worst1 is not None:
        change, pct, key, node = worst1
        summary.append({"label": "Этап 1: наибольший уход платы",
                        "value": f"{_int(change, sign=True)} отсч. ({_fmt(pct, 2)} %), "
                                 f"{'основной' if key == 'main' else 'вид топлива'}, {chamber_fit.node_text(node)}",
                        "tone": "info", "tip": TIPS["pct"]})
    if has_air:
        summary.append({"label": "Этап 2: узлов с сухой трубкой", "value": f"{len(counted)} из {total}",
                        "tone": "ok" if len(counted) == total else "warn", "tip": TIPS["status"]})
    if worst2 is not None:
        change, pct, tube = worst2
        summary.append({"label": "Этап 2: наибольший уход основного контура",
                        "value": f"{_int(change, sign=True)} отсч. ({_fmt(pct, 2)} %, "
                                 f"{_fmt(change / COUNTS_PER_PF, 1)} пФ) при трубке {_fmt(tube / 10)} °C",
                        "tone": "info", "tip": TIPS["pct"] + " " + TIPS["change_pf"]})
    if has_air or has_liquid:
        summary.append({"label": "Погружение в топливо",
                        "value": "снято" if has_liquid else ("не нужно: размах задан" if span_known else "не снято"),
                        "tone": "ok" if has_liquid or span_known else "warn", "tip": TIPS["liquid"]})
    summary.append({"label": "Наибольший разброс в окне усреднения",
                    "value": f"{max(spreads)} отсч." if spreads else "нет данных (журнал до 09.11.2026)",
                    "tone": "info", "tip": TIPS["spread"]})

    missing1 = [n for n in chamber_fit.NODES_X10 if n not in stage1_nodes] if has_stage1 else []
    missing2 = [n for n in chamber_fit.NODES_X10 if n not in counted] if has_air else []
    if not points:
        verdict = ("info", "Точек ещё нет")
    elif missing1 or missing2 or (has_air and not has_liquid and not span_known):
        parts = []
        if missing1:
            parts.append("этап 1 - нет узлов " + ", ".join(chamber_fit.node_text(n) for n in missing1))
        if missing2:
            parts.append("сухая трубка - нет узлов " + ", ".join(chamber_fit.node_text(n) for n in missing2))
        if has_air and not has_liquid and not span_known:
            parts.append("погружение не снято")
        verdict = ("warn", "Данных не хватает: " + "; ".join(parts))
    else:
        verdict = ("ok", "Все узлы сняты: таблицы можно считать полными")

    tables = [coverage]
    if has_stage1:
        tables.append(stage1)
    if has_air:
        tables.append(stage2)
    if has_liquid:
        tables.append(liquid)
    tables.append(_measurements_table(points))
    return {"name": name, "sa": sa_text, "points": len(points), "verdict": verdict[1], "tone": verdict[0],
            "summary": summary, "tables": tables,
            "stage1": f"{len(stage1_nodes)}/{total}" if has_stage1 else "—",
            "stage2": f"{len(counted)}/{total}" if has_air else "—",
            "liquid": has_liquid}


def overview_table(boards: list[dict]) -> dict:
    """Сводка по всем платам камеры: одна строка на плату."""
    rows = [{"tone": board["tone"], "cells": {
        # Плата - по адресу узла, имя - пометка: имена бывают одинаковыми, адрес на шине - нет.
        "board": f"{board['sa']} ({board['name']})" if board["sa"] else board["name"], "points": str(board["points"]),
        "stage1": board["stage1"], "stage2": board["stage2"],
        "liquid": "снято" if board["liquid"] else "не снято", "verdict": board["verdict"]}} for board in boards]
    columns = [
        _column("board", "Плата", align="left"), _column("points", "Точек"),
        _column("stage1", "Этап 1, узлов", "stage1", "center"),
        _column("stage2", "Этап 2, узлов", "status", "center"),
        _column("liquid", "Погружение", "liquid", "center"),
        _column("verdict", "Итог", align="left", width=520),
    ]
    return {"id": "overview", "title": "Сводка по платам",
            "tip": "Одна строка на плату: сколько узлов снято на каждом этапе и чего не хватает.",
            "columns": columns, "rows": rows}


def _text_table(table: dict) -> list[str]:
    """Таблица простым текстом с выравниванием столбцов - для файла итогов в архиве."""
    columns = table.get("columns") or []
    rows = [[str((row.get("cells") or {}).get(column["key"], "")) for column in columns]
            for row in table.get("rows") or []]
    titles = [column["title"] for column in columns]
    widths = [max([len(titles[i])] + [len(row[i]) for row in rows]) for i in range(len(columns))]
    line = "+".join("-" * (width + 2) for width in widths)
    out = [table.get("title", ""), line,
           "|".join(f" {titles[i]:<{widths[i]}} " for i in range(len(columns))), line]
    out += ["|".join(f" {row[i]:<{widths[i]}} " for i in range(len(columns))) for row in rows]
    out.append(line)
    return out


def results_text(view: dict) -> str:
    """Итоги прогона одним текстовым файлом: сводка по платам, показатели, таблицы и пояснения к столбцам."""
    lines = [f"ИТОГИ ПРОГОНА В КАМЕРЕ - {view.get('time', '')}", ""]
    if view.get("overview"):
        lines += _text_table(view["overview"]) + [""]
    if view.get("combined"):
        lines += _text_table(view["combined"]) + [""]
    monitor = view.get("monitor") or {}
    for key in ("now", "nodes"):
        if (monitor.get(key) or {}).get("rows"):
            lines += _text_table(monitor[key]) + [""]
    for board in view.get("boards") or []:
        lines += [f"=== {board['sa']} ({board['name']})" if board["sa"] else f"=== {board['name']}",
                  f"Итог: {board['verdict']}"]
        lines += [f"  {item['label']}: {item['value']}" for item in board.get("summary") or []]
        lines.append("")
        for table in board.get("tables") or []:
            lines += _text_table(table) + [""]
    lines += ["ПОЯСНЕНИЯ К СТОЛБЦАМ"]
    seen = set()
    for board in (view.get("boards") or [])[:1]:
        for table in board.get("tables") or []:
            for column in table["columns"]:
                if column["title"] in seen or not column.get("tip"):
                    continue
                seen.add(column["title"])
                lines.append(f"- {column['title']}: {column['tip']}")
    return "\n".join(lines) + "\n"
