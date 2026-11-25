"""Расчёт прибавки ёмкости после установки трубок по журналу первого этапа."""

from bisect import bisect_left
from collections import defaultdict
from statistics import fmean

import chamber_fit


CHANNELS = {"media": "Вид топлива", "main": "Основной"}


def bare_board_curves(points: list[dict]) -> dict[str, list[tuple[int, float]]]:
    """Для базы берёт только рабочие точки без нагрузки на обоих входах."""
    groups = {key: defaultdict(list) for key in CHANNELS}
    for point in points:
        if point.get("rehearsal") or chamber_fit.parse_references(point["note"]) != {"main": 0, "media": 0}:
            continue
        for key in CHANNELS:
            value = point.get(key)
            if value is not None and 0 < value <= 0xFFFF:
                groups[key][point["board_temp_x10"]].append(value)
    return {key: sorted((temp, fmean(values)) for temp, values in temperatures.items())
            for key, temperatures in groups.items()}


def bare_at_temperature(curve: list[tuple[int, float]], temp_x10: float) -> tuple[float, tuple[int, ...]] | None:
    """Подбирает базу по температуре платы, интерполируя только между измеренными точками."""
    if not curve:
        return None
    index = bisect_left(curve, temp_x10, key=lambda point: point[0])
    if index < len(curve) and curve[index][0] == temp_x10:
        temperature, value = curve[index]
        return value, (temperature,)
    if 0 < index < len(curve):
        low, a = curve[index - 1]
        high, b = curve[index]
        return a + (b - a) * (temp_x10 - low) / (high - low), (low, high)
    temperature, value = curve[0] if index == 0 else curve[-1]
    if abs(temperature - temp_x10) <= chamber_fit.NODE_TOLERANCE_X10:
        return value, (temperature,)
    return None


def dry_reference_points(points: list[dict]) -> list[dict]:
    """Выбирает рабочие замеры собранного изделия на воздухе."""
    return [point for point in points if not point.get("rehearsal")
            and point["note"].strip().casefold() == chamber_fit.AIR_NOTE
            and any(point.get(key) is not None and 0 < point[key] <= 0xFFFF for key in CHANNELS)]


def nearest_dry_point(points: list[dict], board_x10: float, fuel_x10: float | None) -> dict | None:
    """Подбирает прошлый замер только при близких температурах платы и трубки."""
    if fuel_x10 is None:
        return None
    limit = chamber_fit.NODE_TOLERANCE_X10
    candidates = [point for point in points if abs(point["board_temp_x10"] - board_x10) <= limit
                  and abs(point["fuel_temp_x10"] - fuel_x10) <= limit]
    return min(candidates, key=lambda point: abs(point["board_temp_x10"] - board_x10)
               + abs(point["fuel_temp_x10"] - fuel_x10), default=None)
