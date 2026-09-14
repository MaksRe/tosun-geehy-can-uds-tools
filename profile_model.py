"""Предсказание того, что прибор посчитает по записанному профилю.

ЗАЧЕМ
Пробная калибровка проверяет не только то, что профиль записался, но и то, что
прибор применяет его правильно. Для этого нужно заранее знать, какой период
прибор обязан выдать при данной температуре. Здесь построчный перенос расчёта
из прошивки, src/app/fuel_temp_comp.c: обе ступени компенсации и подгонка нуля,
теми же целыми числами и тем же округлением.

Расхождение с прибором больше пары отсчётов означает одно из двух: либо прибор
применяет таблицы не так, как задумано, либо перенос разошёлся с прошивкой. Оба
случая надо разбирать до выезда в камеру.

Одиночные коэффициенты ступени платы (параметры 0x0043..0x004A) здесь считаются
нулевыми: программа их не пишет, а при заполненной таблице прибор их не
использует вовсе.
"""

from __future__ import annotations

POINTS = 7

GAIN_UNITY = 1_000_000
GAIN_MIN = 500_000
GAIN_MAX = 2_000_000

TUBE_REF_X10 = 250
TUBE_MIN_SPAN = 100
TUBE_GAIN_MIN_X1000 = 500
TUBE_GAIN_MAX_X1000 = 2000

ZERO_TRIM_MIN = -4000
ZERO_TRIM_MAX = 4000

# Биты состояния профиля, как в fuel_profile.h.
STATUS_FILLED = 0x01
STATUS_CRC_OK = 0x02
STATUS_ALGO_OK = 0x04
STATUS_TRUSTED = 0x08

# Биты источника поправки, как в fuel_temp_comp.c.
MODE_MAIN_LUT = 0x01
MODE_MEDIA_LUT = 0x02
MODE_NODES_BAD = 0x04
MODE_TUBE_MAIN = 0x08
MODE_TUBE_MEDIA = 0x10


def c_div(numerator: int, denominator: int) -> int:
    """Целое деление с усечением к нулю, как в C."""
    quotient = abs(numerator) // abs(denominator)
    return -quotient if (numerator < 0) != (denominator < 0) else quotient


def div_round(numerator: int, denominator: int) -> int:
    """Перенос fuel_board_div_round: деление с округлением к ближайшему."""
    if denominator <= 0:
        return 0
    if numerator >= 0:
        return (numerator + (denominator // 2)) // denominator
    return -(((-numerator) + (denominator // 2)) // denominator)


def nodes_are_valid(nodes) -> bool:
    """Сетка узлов обязана строго возрастать."""
    return len(nodes) == POINTS and all(nodes[i] > nodes[i - 1] for i in range(1, POINTS))


def pairs_from_flat(flat) -> list[tuple[int, int]]:
    """Раскладывает плоский ряд таблицы платы на пары сдвиг и растяжение."""
    return [(int(flat[i * 2]), int(flat[i * 2 + 1])) for i in range(POINTS)]


def lut_is_empty(pairs) -> bool:
    return all(offset == 0 and gain == 0 for offset, gain in pairs)


def row_is_empty(row) -> bool:
    return all(int(value) == 0 for value in row)


def lut_lookup(pairs, nodes, temperature_x10: int) -> tuple[int, int]:
    """Перенос fuel_board_lut_lookup."""
    if temperature_x10 <= nodes[0]:
        return pairs[0]
    for index in range(1, POINTS):
        if temperature_x10 > nodes[index]:
            continue
        span = nodes[index] - nodes[index - 1]
        position = temperature_x10 - nodes[index - 1]
        offset = pairs[index - 1][0] + div_round((pairs[index][0] - pairs[index - 1][0]) * position, span)
        gain = pairs[index - 1][1] + div_round((pairs[index][1] - pairs[index - 1][1]) * position, span)
        return offset, gain
    return pairs[POINTS - 1]


def row_value(row, nodes, temperature_x10: int) -> int:
    """Перенос fuel_tube_lut_value."""
    if temperature_x10 <= nodes[0]:
        return int(row[0])
    for index in range(1, POINTS):
        if temperature_x10 > nodes[index]:
            continue
        span = nodes[index] - nodes[index - 1]
        position = temperature_x10 - nodes[index - 1]
        return int(row[index - 1]) + div_round((int(row[index]) - int(row[index - 1])) * position, span)
    return int(row[POINTS - 1])


def clamp_u16(value: int) -> int:
    return max(0, min(0xFFFF, int(value)))


def board_stage(period: int, temperature_x10: int, pairs, nodes, *,
                trusted: bool = True, temperature_ok: bool = True) -> tuple[int, bool]:
    """Перенос fuel_temp_comp_apply_board_stage. Возвращает (период, таблица применена)."""
    use_lut = temperature_ok and trusted and nodes_are_valid(nodes) and not lut_is_empty(pairs)

    offset = 0
    gain = 0
    if use_lut:
        offset, gain = lut_lookup(pairs, nodes, temperature_x10)

    period = int(period) + offset

    if gain != 0:
        units = GAIN_UNITY + gain
        if GAIN_MIN <= units <= GAIN_MAX:
            period = c_div(period * GAIN_UNITY + (units // 2), units)

    return clamp_u16(period), use_lut


def tube_normalize(value: int, air_row, full_row, temperature_x10: int, nodes, *,
                   trusted: bool = True) -> tuple[int, bool]:
    """Перенос fuel_tube_stage_normalize. Возвращает (значение, приведение применено)."""
    if row_is_empty(air_row) and row_is_empty(full_row):
        return value, False
    if not trusted or not nodes_are_valid(nodes):
        return value, False

    air_ref = row_value(air_row, nodes, TUBE_REF_X10)
    full_ref = row_value(full_row, nodes, TUBE_REF_X10)
    air_now = row_value(air_row, nodes, temperature_x10)
    full_now = row_value(full_row, nodes, temperature_x10)

    span_ref = full_ref - air_ref
    span_now = full_now - air_now
    if span_ref < TUBE_MIN_SPAN or span_now < TUBE_MIN_SPAN:
        return value, False

    gain_x1000 = div_round(span_ref * 1000, span_now)
    if not (TUBE_GAIN_MIN_X1000 <= gain_x1000 <= TUBE_GAIN_MAX_X1000):
        return value, False

    numerator = (int(value) - air_now) * span_ref
    half = span_now // 2
    if numerator >= 0:
        scaled = (numerator + half) // span_now
    else:
        scaled = -(((-numerator) + half) // span_now)
    return air_ref + scaled, True


def predict_main(raw_period: int, profile: dict, *, board_temp_x10: int, tube_temp_x10: int,
                 trusted: bool, zero_trim: int = 0, board_temp_ok: bool = True) -> dict:
    """Предсказывает всю цепочку основного контура так, как её считает прибор.

    profile - таблицы в том же виде, что в окне профиля: nodes, board_main,
    tube_air_main, tube_full_main и остальные. trusted берётся из самого прибора,
    из бита «таблицы применяются»: так проверка не зависит от того, как именно
    прибор решает, доверять ли набору.
    """
    nodes = [int(value) for value in profile["nodes"]]
    pairs = pairs_from_flat(profile["board_main"])

    board_out, board_applied = board_stage(
        raw_period, board_temp_x10, pairs, nodes, trusted=trusted, temperature_ok=board_temp_ok)

    tube_out, tube_applied = tube_normalize(
        board_out, profile["tube_air_main"], profile["tube_full_main"], tube_temp_x10, nodes, trusted=trusted)

    trim = max(ZERO_TRIM_MIN, min(ZERO_TRIM_MAX, int(zero_trim)))
    compensated = clamp_u16(tube_out + trim)

    mode = 0
    if board_applied:
        mode |= MODE_MAIN_LUT
    if not nodes_are_valid(nodes):
        mode |= MODE_NODES_BAD
    if tube_applied:
        mode |= MODE_TUBE_MAIN

    return {
        "board_stage": board_out,
        "compensated": compensated,
        "board_applied": board_applied,
        "tube_applied": tube_applied,
        "mode_main": mode,
    }


def build_test_profile(nodes=None) -> dict:
    """Строит проверочный профиль с заведомо заметными поправками во всех узлах.

    Профиль из прогона на столе почти пустой: эталоны одни и те же при любой
    эмулируемой температуре, и поправки выходят около нуля. По такому профилю
    нельзя увидеть, применяет ли прибор таблицы. Здесь поправки заданы нарочно
    крупными и разными в каждом узле, а в опорной точке тоже не нулевыми, чтобы
    их применение было видно при любой температуре.

    Растяжение трубки задано так, чтобы размах при опорной температуре и в
    крайних узлах отличался: иначе приведение было бы тождественным.
    """
    nodes = list(nodes) if nodes is not None else [-400, -200, 0, 250, 500, 700, 850]

    # Знаки подобраны так, чтобы поправка платы не гасила поправку трубки: ниже
    # опорной точки трубка поднимает период, выше опускает, и плата делает то же.
    # Иначе в каком-то узле итог почти совпал бы с сырым, и расхождение с прибором
    # там не было бы видно. При этих числах итог отличается от сырого хотя бы на
    # 40 отсчётов при любой температуре проверки и любом периоде от 4000 до 10000.
    board_main_pairs = [(200, -1500), (140, -900), (90, -400), (80, -300), (-150, 700), (-200, 1100), (-240, 1400)]
    board_media_pairs = [(100, -800), (70, -500), (45, -200), (40, -150), (-75, 350), (-100, 550), (-120, 700)]

    def flat(pairs):
        out = []
        for offset, gain in pairs:
            out.extend([offset, gain])
        return out

    return {
        "nodes": nodes,
        "board_main": flat(board_main_pairs),
        "board_media": flat(board_media_pairs),
        "tube_air_main": [4700, 4740, 4780, 4800, 4830, 4860, 4880],
        "tube_full_main": [9380, 9460, 9540, 9600, 9690, 9760, 9810],
        "tube_air_media": [2300, 2320, 2340, 2350, 2365, 2380, 2390],
        "tube_full_media": [3500, 3530, 3560, 3580, 3610, 3635, 3655],
    }
