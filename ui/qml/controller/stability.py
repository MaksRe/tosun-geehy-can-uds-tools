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


def predict_final(samples, start: float, now: float, chunks: int = 6, min_change_c: float = 0.5,
                  max_tau_s: float = 600 * 60.0, min_fit: float = 0.6):
    """Где устоится температура, которая подходит к своему значению по экспоненте.

    Зачем: плата с большой тепловой инерцией (постоянная времени - десятки минут)
    «устаивается» по правилу скорости ещё за несколько градусов до своего предела.
    Прогноз позволяет сразу понять, куда она придёт, и не ждать часами.

    Как: показания с момента start делятся на chunks отрезков, по каждому - среднее
    (сглаживает шаг датчика 0,1 °C). У экспоненты скорость пропорциональна
    оставшемуся расстоянию: скорость = (предел - T) / τ. Прямая «скорость от
    температуры» по соседним отрезкам даёт предел (где скорость ноль) и τ.

    Возвращает (предел, °C; τ, с) или None, если данных мало, температура почти
    не менялась (прогноз был бы шумом) или кривая не похожа на подход к пределу.
    """
    points = [(float(stamp), float(value)) for stamp, value in samples
              if value is not None and start <= float(stamp) <= now]
    if len(points) < chunks * 2:
        return None
    first, last = points[0][0], points[-1][0]
    if last <= first:
        return None
    width = (last - first) / chunks
    means = []
    for index in range(chunks):
        low = first + index * width
        high = low + width if index < chunks - 1 else last + 1.0
        part = [(stamp, value) for stamp, value in points if low <= stamp < high]
        if part:
            means.append((sum(stamp for stamp, _ in part) / len(part), sum(value for _, value in part) / len(part)))
    if len(means) < 4 or abs(means[-1][1] - means[0][1]) < min_change_c:
        return None
    xs, ys = [], []
    for (t1, v1), (t2, v2) in zip(means, means[1:]):
        if t2 > t1:
            xs.append((v1 + v2) / 2.0)
            ys.append((v2 - v1) / (t2 - t1))
    count = float(len(xs))
    if count < 3:
        return None
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0.0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / sxx
    if slope >= 0.0:
        return None
    tau_s = -1.0 / slope
    if not (60.0 <= tau_s <= max_tau_s):
        return None
    # Кривизна видна только на отрезке не короче трети τ: на коротком прогноз - шум.
    if last - first < 0.3 * tau_s:
        return None
    intercept = mean_y - slope * mean_x
    final = -intercept / slope
    # Насколько точки ложатся на прямую: шумный или не экспоненциальный подход - без прогноза.
    syy = sum((y - mean_y) ** 2 for y in ys)
    if syy <= 0.0:
        return None
    fit = 1.0 - sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys)) / syy
    if fit < min_fit:
        return None
    return final, tau_s


def fit_board_model(pairs, min_span_c: float = 10.0, gain_range=(0.5, 1.2)):
    """Модель «воздух камеры → где устоится плата»: плата ≈ k × воздух + b.

    Зачем: плата отстаёт от воздуха не на постоянную величину - её тянет к комнате
    (тепло по кабелю, через оснастку) и греет собственный ток. По парам «уставка
    камеры - где устоялась плата» прогон сразу ставит уставку, при которой плата
    придёт к температуре шага.

    pairs - пары (воздух, плата), °C. Одна пара или узкий размах воздуха - только
    сдвиг (k = 1). Наклон вне разумных пределов - тоже только сдвиг: такая прямая
    скорее шум, чем свойство установки. Возвращает (k, b, число пар) или None.
    """
    points = [(float(air), float(board)) for air, board in pairs]
    if not points:
        return None
    count = float(len(points))
    mean_air = sum(air for air, _ in points) / count
    mean_board = sum(board for _, board in points) / count
    offset_only = (1.0, mean_board - mean_air, len(points))
    airs = [air for air, _ in points]
    if len(points) < 2 or max(airs) - min(airs) < min_span_c:
        return offset_only
    sxx = sum((air - mean_air) ** 2 for air in airs)
    gain = sum((air - mean_air) * (board - mean_board) for air, board in points) / sxx
    if not (gain_range[0] <= gain <= gain_range[1]):
        return offset_only
    return gain, mean_board - gain * mean_air, len(points)


def air_for_board(model, target_c: float) -> float:
    """Какой нужен воздух камеры, чтобы плата устоялась при target_c."""
    gain, offset, _count = model
    return (float(target_c) - offset) / gain
