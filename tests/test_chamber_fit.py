"""Проверки расчёта температурных таблиц по прогону в камере.

Тот же расчёт есть в репозитории прошивки как отдельный скрипт. Программа
настройки собирается в один исполняемый файл и до соседнего репозитория не
дотянется, поэтому расчёт повторён здесь. Эти проверки закрепляют, что копия
считает то же самое: строит искусственный прогон с заранее известными
коэффициентами и убеждается, что расчёт их восстанавливает.

Ошибка тут стоит дорого: прогон в камере длится часами и не переделывается.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_fit


def _synthetic_run() -> list[dict]:
    """Строит искусственный прогон с заранее известной физикой платы и сборки."""
    random.seed(20260910)
    records: list[dict] = []

    for node in chamber_fit.NODES_X10:
        for capacitance in (0.0, 60.0, 120.0):
            for _ in range(4):
                raw = _slope_at(node) * capacitance + _intercept_at(node)
                records.append({
                    "note": f"{capacitance:g} пФ",
                    "main": raw + random.uniform(-0.4, 0.4),
                    "media": None,
                    "fuel_temp_x10": node,
                    "board_temp_x10": node + random.randint(-8, 8),
                })

    for node in chamber_fit.NODES_X10:
        for state, immersion in ((chamber_fit.AIR_NOTE, 0.0), (chamber_fit.LIQUID_NOTE, 1.0)):
            for _ in range(4):
                assembly_air = 60.0 + 0.02 * (node - chamber_fit.REFERENCE_X10) / 10.0
                assembly_span = 60.0 + 0.05 * (node - chamber_fit.REFERENCE_X10) / 10.0
                capacitance = assembly_air + assembly_span * immersion
                raw = _slope_at(node) * capacitance + _intercept_at(node)
                media = _slope_at(node) * (30.0 + 30.0 * immersion) + _intercept_at(node)
                records.append({
                    "note": state,
                    "main": raw + random.uniform(-0.4, 0.4),
                    "media": media + random.uniform(-0.4, 0.4),
                    "fuel_temp_x10": node,
                    "board_temp_x10": node + random.randint(-8, 8),
                })

    return records


def _slope_at(node_x10: int) -> float:
    """Чувствительность платы: сколько отсчётов на пикофараду при этой температуре."""
    return 40.9 * (1.0 + 0.00004 * (node_x10 - chamber_fit.REFERENCE_X10) / 10.0)


def _intercept_at(node_x10: int) -> float:
    """Собственное показание платы без внешней ёмкости при этой температуре."""
    return 4820.0 + 0.35 * (node_x10 - chamber_fit.REFERENCE_X10) / 10.0


def test_board_stage_recovers_the_coefficients_it_was_built_from():
    """Расчёт обязан вернуть ту физику, которая была заложена в искусственный прогон."""
    result = chamber_fit.compute_tables(_synthetic_run())
    board = result["ступень_платы"]
    assert len(board) == len(chamber_fit.NODES_X10)

    slope_ref = _slope_at(chamber_fit.REFERENCE_X10)
    intercept_ref = _intercept_at(chamber_fit.REFERENCE_X10)

    worst_gain = 0.0
    worst_offset = 0.0
    for index, node in enumerate(chamber_fit.NODES_X10):
        want_gain_ppm = (_slope_at(node) / slope_ref - 1.0) * 1_000_000
        want_offset = intercept_ref * (_slope_at(node) / slope_ref) - _intercept_at(node)
        got_offset, got_gain_ppm = board[index]
        worst_gain = max(worst_gain, abs(got_gain_ppm - want_gain_ppm))
        worst_offset = max(worst_offset, abs(got_offset - want_offset))

    # Шум в искусственном прогоне даёт свой предел точности, пороги с запасом.
    assert worst_gain <= 400.0, f"растяжение восстановлено с ошибкой {worst_gain:.0f} ppm"
    assert worst_offset <= 3.0, f"сдвиг восстановлен с ошибкой {worst_offset:.2f} отсчёта"


def test_reference_node_correction_is_zero_by_construction():
    """В опорной точке поправки нет: от неё отсчитываются остальные."""
    result = chamber_fit.compute_tables(_synthetic_run())
    index = chamber_fit.NODES_X10.index(chamber_fit.REFERENCE_X10)
    assert result["ступень_платы"][index] == [0, 0]


def test_full_run_leaves_no_complaints():
    """Полный прогон обязан проходить без замечаний, иначе оператор не поймёт, что не так."""
    result = chamber_fit.compute_tables(_synthetic_run())
    assert result["замечания"] == []


def test_tube_rows_grow_with_immersion():
    """Погружённая трубка обязана давать показание больше сухой, иначе размах отрицателен."""
    tube = chamber_fit.compute_tables(_synthetic_run())["ступень_трубки"]
    for air, full in zip(tube["air_main"], tube["full_main"]):
        assert full > air


def test_single_reference_per_node_is_refused():
    """По одной ёмкости сдвиг и растяжение неразличимы, расчёт обязан это сказать."""
    records = [
        {"note": "60 пФ", "main": 7274.0, "media": None,
         "fuel_temp_x10": node, "board_temp_x10": node}
        for node in chamber_fit.NODES_X10
    ]
    result = chamber_fit.compute_tables(records)
    assert any("нужно минимум" in item for item in result["замечания"])


def test_missing_reference_node_stops_the_calculation():
    """Без опорной точки не от чего отсчитывать поправку, таблица не строится."""
    records = []
    for node in chamber_fit.NODES_X10:
        if node == chamber_fit.REFERENCE_X10:
            continue
        for capacitance in (0.0, 60.0):
            records.append({
                "note": f"{capacitance:g} пФ",
                "main": _slope_at(node) * capacitance + _intercept_at(node),
                "media": None,
                "fuel_temp_x10": node,
                "board_temp_x10": node,
            })

    result = chamber_fit.compute_tables(records)
    assert result["ступень_платы"] == []
    assert any("опорной точке" in item for item in result["замечания"])


def test_points_far_from_the_grid_are_ignored():
    """Точка между узлами в расчёт не идёт: иначе она исказит ближайший узел."""
    assert chamber_fit.nearest_node(250) == 250
    assert chamber_fit.nearest_node(270) == 250
    assert chamber_fit.nearest_node(300) is None


def test_note_without_a_number_is_not_a_reference():
    """Пометки состояния трубки не должны попадать в расчёт ступени платы."""
    assert chamber_fit.parse_reference_pf("воздух") is None
    assert chamber_fit.parse_reference_pf("жидкость") is None
    assert chamber_fit.parse_reference_pf("300 пФ") == 300.0
    assert chamber_fit.parse_reference_pf("0 пФ") == 0.0


def test_result_is_accepted_by_the_profile_window():
    """Расчёт обязан отдавать ровно тот вид данных, который принимает окно профиля."""
    result = chamber_fit.compute_tables(_synthetic_run())
    assert set(result) >= {"узлы_x10", "ступень_платы", "ступень_трубки", "замечания"}
    assert set(result["ступень_трубки"]) == {"air_main", "full_main", "air_media", "full_media"}
    assert len(result["узлы_x10"]) == len(chamber_fit.NODES_X10)


def _run_without_liquid_above_room() -> list[dict]:
    """Прогон, где погружение снято только при комнатной температуре.

    Так выглядит реальный выезд, когда в камеру нельзя ставить топливо: эталоны
    и сухую трубку снимают во всех узлах, а погружение только рядом с камерой.
    """
    records = []
    for point in _synthetic_run():
        if point["note"] != chamber_fit.LIQUID_NOTE:
            records.append(point)
            continue
        if point["fuel_temp_x10"] == chamber_fit.REFERENCE_X10:
            records.append(point)
    return records


def test_air_rows_survive_when_liquid_is_missing():
    """Снятые строки «на воздухе» нельзя терять из-за того, что нет погружения."""
    result = chamber_fit.compute_tables(_run_without_liquid_above_room())
    tube = result["ступень_трубки"]

    assert all(value != 0 for value in tube["air_main"]), "строки на воздухе обнулились"
    index = chamber_fit.NODES_X10.index(chamber_fit.REFERENCE_X10)
    assert tube["full_main"][index] != 0, "измеренное погружение потерялось"
    assert sum(1 for value in tube["full_main"] if value == 0) == len(chamber_fit.NODES_X10) - 1


def test_liquid_rows_are_built_from_the_reference_span():
    """Недостающее погружение достраивается по размаху опорной точки."""
    result = chamber_fit.compute_tables(_run_without_liquid_above_room(), extend_liquid=True)
    tube = result["ступень_трубки"]

    index = chamber_fit.NODES_X10.index(chamber_fit.REFERENCE_X10)
    span = tube["full_main"][index] - tube["air_main"][index]
    assert span >= chamber_fit.TUBE_MIN_SPAN

    for position in range(len(chamber_fit.NODES_X10)):
        if position == index:
            continue
        built = tube["full_main"][position] - tube["air_main"][position]
        assert built == span, "размах достроенного узла разошёлся с опорным"


def test_built_rows_are_named_in_the_report():
    """Достройка это допущение, и она обязана быть видна оператору, а не молчать."""
    result = chamber_fit.compute_tables(_run_without_liquid_above_room(), extend_liquid=True)
    assert any("достроены по размаху" in item for item in result["замечания"])


def test_span_given_by_hand_wins_over_the_measured_one():
    """Заданный вручную размах имеет приоритет: оператор мог снять его точнее."""
    result = chamber_fit.compute_tables(
        _run_without_liquid_above_room(), extend_liquid=True, span_main=5000)
    tube = result["ступень_трубки"]

    index = chamber_fit.NODES_X10.index(chamber_fit.REFERENCE_X10)
    for position in range(len(chamber_fit.NODES_X10)):
        if position == index:
            continue
        assert tube["full_main"][position] - tube["air_main"][position] == 5000


def test_too_small_span_is_refused():
    """Прибор не примет приведение при малом размахе, и расчёт обязан предупредить."""
    result = chamber_fit.compute_tables(
        _run_without_liquid_above_room(), extend_liquid=True, span_main=50)
    assert any("меньше" in item for item in result["замечания"])
    assert all(value == 0 for value in result["ступень_трубки"]["full_main"][:3])


def test_small_span_and_missing_pair_are_told_apart():
    """«Пара не снята» и «пара снята, но размах мал» это разные причины отказа."""
    records = [point for point in _synthetic_run() if point["note"] != chamber_fit.LIQUID_NOTE]
    no_pair = chamber_fit.compute_tables(records, extend_liquid=True)
    assert any("ни в одном узле не снята пара" in item for item in no_pair["замечания"])

    small = chamber_fit.compute_tables(
        _run_without_liquid_above_room(), extend_liquid=True, span_main=50)
    assert not any("ни в одном узле не снята пара" in item for item in small["замечания"])


def test_extension_without_any_span_says_so():
    """Если размах взять неоткуда, достройка не выполняется и молчать об этом нельзя."""
    records = [point for point in _synthetic_run() if point["note"] != chamber_fit.LIQUID_NOTE]
    result = chamber_fit.compute_tables(records, extend_liquid=True)

    assert any("не достроены" in item for item in result["замечания"])
    assert all(value == 0 for value in result["ступень_трубки"]["full_main"])


def test_measured_rows_are_never_overwritten():
    """Там, где погружение снято, достройка не должна подменять измерение."""
    full_run = _synthetic_run()
    plain = chamber_fit.compute_tables(full_run)["ступень_трубки"]
    extended = chamber_fit.compute_tables(full_run, extend_liquid=True)["ступень_трубки"]

    assert plain["full_main"] == extended["full_main"]
    assert plain["full_media"] == extended["full_media"]
