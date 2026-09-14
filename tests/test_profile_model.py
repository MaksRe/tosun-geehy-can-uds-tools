"""Проверки предсказания расчёта прибора по профилю.

Пробная калибровка сверяет то, что прибор выдал, с тем, что он обязан был
выдать. Если само предсказание ошибается, проверка на столе будет ругать
исправный прибор или, хуже, пропустит неисправный. Поэтому предсказание
закреплено здесь числами, посчитанными вручную по формулам прошивки.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import profile_model as model

NODES = [-400, -200, 0, 250, 500, 700, 850]

# Та же таблица, что в проверочном скрипте прошивки tools/verify_board_stage_lut.py.
PAIRS = [(-30, -1200), (-18, -700), (-6, -200), (0, 0), (9, 400), (17, 800), (22, 1100)]


def test_empty_table_changes_nothing():
    """Пустая таблица обязана пропускать период без единого изменения."""
    empty = [(0, 0)] * model.POINTS
    for temperature in (-450, -400, -123, 0, 250, 611, 850, 900):
        for period in (0, 1, 4820, 9640, 65535):
            got, applied = model.board_stage(period, temperature, empty, NODES)
            assert got == period
            assert not applied


def test_board_stage_at_the_hottest_node():
    """+85 °C: сдвиг 22, растяжение 1100 ppm. Посчитано вручную: 5000 -> 5016."""
    got, applied = model.board_stage(5000, 850, PAIRS, NODES)
    assert got == 5016
    assert applied


def test_board_stage_at_the_coldest_node():
    """-40 °C: сдвиг -30, растяжение -1200 ppm. Посчитано вручную: 5000 -> 4976."""
    got, _ = model.board_stage(5000, -400, PAIRS, NODES)
    assert got == 4976


def test_board_stage_between_nodes():
    """-30 °C, середина между -40 и -20: сдвиг -24, растяжение -950 ppm. 5000 -> 4981."""
    got, _ = model.board_stage(5000, -300, PAIRS, NODES)
    assert got == 4981


def test_untrusted_profile_is_not_applied():
    """Недоверенный профиль прибор не применяет, и предсказание обязано это повторять."""
    got, applied = model.board_stage(5000, 850, PAIRS, NODES, trusted=False)
    assert got == 5000
    assert not applied


def test_failed_board_sensor_disables_the_board_stage():
    """При отказе датчика платы ступень платы выключается целиком."""
    got, applied = model.board_stage(5000, 850, PAIRS, NODES, temperature_ok=False)
    assert got == 5000
    assert not applied


def test_tube_stage_is_identity_at_constant_span():
    """Если размах одинаков при любой температуре, приведение только сдвигает ноль."""
    air = [4700, 4750, 4800, 4800, 4850, 4900, 4950]
    full = [9500, 9550, 9600, 9600, 9650, 9700, 9750]
    got, applied = model.tube_normalize(7200, air, full, -400, NODES)
    assert applied
    assert got == 7300


def test_tube_stage_with_different_span():
    """-40 °C, размах 4700 против 4800 опорного. Посчитано вручную: 7200 -> 7353."""
    air = [4700, 4750, 4800, 4800, 4850, 4900, 4950]
    full = [9400, 9550, 9600, 9600, 9650, 9700, 9750]
    got, applied = model.tube_normalize(7200, air, full, -400, NODES)
    assert applied
    assert got == 7353


def test_tube_stage_refuses_a_small_span():
    """Размах меньше 100 отсчётов прибор не применяет."""
    air = [4800] * 7
    full = [4850] * 7
    got, applied = model.tube_normalize(7200, air, full, 250, NODES)
    assert got == 7200
    assert not applied


def test_full_chain_with_zero_trim():
    """Вся цепочка: ступень платы 5000 -> 5016, трубка пустая, подгонка нуля +10."""
    profile = {
        "nodes": NODES,
        "board_main": [value for pair in PAIRS for value in pair],
        "tube_air_main": [0] * 7,
        "tube_full_main": [0] * 7,
    }
    result = model.predict_main(5000, profile, board_temp_x10=850, tube_temp_x10=850,
                                trusted=True, zero_trim=10)
    assert result["board_stage"] == 5016
    assert result["compensated"] == 5026
    assert result["mode_main"] == model.MODE_MAIN_LUT


def test_zero_trim_is_clamped_like_the_device():
    """Подгонка нуля ограничена ±4000, как в прошивке."""
    profile = {"nodes": NODES, "board_main": [0] * 14,
               "tube_air_main": [0] * 7, "tube_full_main": [0] * 7}
    result = model.predict_main(5000, profile, board_temp_x10=250, tube_temp_x10=250,
                                trusted=True, zero_trim=9000)
    assert result["compensated"] == 9000


def test_test_profile_shows_corrections_everywhere():
    """Проверочный профиль обязан давать заметную поправку в каждом узле, иначе он бесполезен."""
    profile = model.build_test_profile()
    for node in NODES:
        result = model.predict_main(7000, profile, board_temp_x10=node, tube_temp_x10=node, trusted=True)
        assert result["board_applied"]
        assert result["tube_applied"]
        assert abs(result["compensated"] - 7000) >= 20, f"в узле {node / 10:+.0f} °C поправка почти нулевая"


def test_test_profile_is_valid_for_the_profile_window():
    """Проверочный профиль обязан проходить те же правила, что и настоящий."""
    profile = model.build_test_profile()
    assert model.nodes_are_valid(profile["nodes"])
    for name in ("board_main", "board_media"):
        assert len(profile[name]) == 14
    for name in ("tube_air_main", "tube_full_main", "tube_air_media", "tube_full_media"):
        assert len(profile[name]) == 7
    for air, full in zip(profile["tube_air_main"], profile["tube_full_main"]):
        assert full - air >= model.TUBE_MIN_SPAN
