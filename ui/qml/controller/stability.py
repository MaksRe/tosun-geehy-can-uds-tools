"""Устоялась ли температура: общее правило прогона.

Плата в корпусе с компаундом отстаёт от воздуха камеры на десятки минут, поэтому
уставка камеры для снятия точки не годится. Точку снимают, когда температура
платы за окно (обычно 5 минут) меняется медленнее порога (обычно 0,05 °C в
минуту). Этим правилом пользуются и наблюдение издалека, и автоматический прогон.
"""

from __future__ import annotations


def rate_and_spread(samples, now: float, window_s: float):
    """Скорость (°C/мин), разброс (°C) и охват окна (с) по показаниям за окно.

    samples - пары (момент в секундах, температура в °C); None среди температур
    пропускаются. Возвращает None, если показаний меньше трёх.
    """
    points = [(float(stamp), float(value)) for stamp, value in samples
              if value is not None and now - float(stamp) <= window_s]
    if len(points) < 3:
        return None
    count = float(len(points))
    mean_t = sum(stamp for stamp, _ in points) / count
    mean_v = sum(value for _, value in points) / count
    spread_t = sum((stamp - mean_t) ** 2 for stamp, _ in points)
    if spread_t <= 0.0:
        return None
    slope_per_s = sum((stamp - mean_t) * (value - mean_v) for stamp, value in points) / spread_t
    values = [value for _, value in points]
    return slope_per_s * 60.0, max(values) - min(values), points[-1][0] - points[0][0]


def is_stable(result, window_s: float, rate_limit: float, spread_limit: float) -> bool:
    """Правило «устоялась»: окно почти заполнено, скорость и разброс в пределах."""
    if result is None:
        return False
    rate, spread, covered = result
    return covered >= window_s * 0.9 and abs(rate) < rate_limit and spread < spread_limit
