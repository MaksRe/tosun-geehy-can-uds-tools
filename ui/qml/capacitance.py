"""Перевод отсчётов ёмкостного контура в ёмкость и оценка плавания показаний.

ОТКУДА БЕРЁТСЯ КОЭФФИЦИЕНТ
Контур меряет не саму ёмкость, а время, за которое напряжение на датчике
проходит между двумя порогами компараторов. Оба порога сняты с одного делителя,
их отношение постоянно и равно 8,2, поэтому время равно R * C * ln(8,2) и от
напряжения питания не зависит. Заряд идёт через 270 кОм, время считает таймер на
72 МГц без делителя. Отсюда

    отсчётов на фараду = 72 000 000 * 270 000 * ln(8,2) = 4,09e13,
    то есть 40,9 отсчёта на пикофараду.

То же число названо в прошивке: src/app/timers/fuel_timer.h (схемотехника обоих
контуров) и src/app/timers/cap_channel.h (принцип измерения).

ЧТО ВХОДИТ В ИЗМЕРЕННУЮ ЁМКОСТЬ
Кроме самого датчика, параллельно ему постоянно включён образцовый конденсатор
100 пФ, а к ним добавляется ёмкость кабеля, разъёма и платы. Поэтому число в
пикофарадах - это полная ёмкость контура, а не ёмкость одного датчика.
Осмысленны прежде всего разности: постоянная часть в них сокращается.

ЭФФЕКТИВНОЕ ЗНАЧЕНИЕ И ПЛАВАНИЕ
Эффективным считается среднее по окну захвата - то же число, которое оператор
переносит в отметку кнопкой «Взять захват». Плавание - насколько отдельные
показания в этом окне отходят от среднего. Размах (max - min) показывает полную
ширину дрожания, а наибольшее отклонение - насколько может соврать одно
показание, взятое наугад.
"""

from __future__ import annotations

import math

# Схемотехника обоих контуров платы LLC_CH2V1_R1.
TIMER_HZ = 72_000_000.0
CHARGE_RESISTOR_OHM = 270_000.0
THRESHOLD_RATIO = 8.2

# Сколько отсчётов таймера даёт одна фарада и одна пикофарада.
COUNTS_PER_FARAD = TIMER_HZ * CHARGE_RESISTOR_OHM * math.log(THRESHOLD_RATIO)
COUNTS_PER_PF = COUNTS_PER_FARAD * 1e-12

# Образцовый конденсатор, постоянно включённый параллельно датчику, пФ.
REFERENCE_CAP_PF = 100.0


def counts_to_pf(counts: float) -> float:
    """Ёмкость контура в пикофарадах по отсчётам таймера."""
    return float(counts) / COUNTS_PER_PF


def pf_to_counts(picofarads: float) -> float:
    """Отсчёты таймера по ёмкости в пикофарадах: обратная сторона той же формулы."""
    return float(picofarads) * COUNTS_PER_PF


def decimal_text(value: float, digits: int = 1) -> str:
    """Число с запятой вместо точки: так его читают в остальной программе."""
    return f"{float(value):.{digits}f}".replace(".", ",")


def pf_text(counts, digits: int = 1) -> str:
    """Ёмкость словами по отсчётам: «296,4 пФ» или «—», если числа нет."""
    if counts is None:
        return "—"
    return decimal_text(counts_to_pf(counts), digits) + " пФ"


def counts_text(counts) -> str:
    """Отсчёты словами: «12130 отсч.» или «—», если числа нет."""
    if counts is None:
        return "—"
    return f"{int(round(float(counts)))} отсч."


def window_values(samples, now: float, window_s: float) -> list[int]:
    """Показания из окна захвата: пары (время, число), не старше окна."""
    limit = float(now) - float(window_s)
    values = []
    for item in samples or []:
        try:
            sample_ts, sample_value = item
        except (TypeError, ValueError):
            continue
        if float(sample_ts) >= limit:
            values.append(int(sample_value))
    return values


def window_stats(values) -> dict | None:
    """Эффективное значение и плавание по показаниям окна.

    Возвращает None, пока показаний меньше двух: по одному числу о плавании
    говорить нечего, а по нулю нечего и усреднять.
    """
    numbers = [float(value) for value in values or []]
    if len(numbers) < 2:
        return None

    effective = sum(numbers) / float(len(numbers))
    minimum = min(numbers)
    maximum = max(numbers)
    swing = max(abs(maximum - effective), abs(effective - minimum))

    return {
        "count": len(numbers),
        "effective": effective,
        "minimum": minimum,
        "maximum": maximum,
        # Полная ширина дрожания показаний в окне.
        "spread": maximum - minimum,
        # Насколько от среднего может отойти одно показание, взятое наугад.
        "swing": swing,
    }


def swing_percent(stats: dict | None) -> float | None:
    """Плавание в процентах от эффективной ёмкости контура."""
    if not stats:
        return None
    effective = float(stats["effective"])
    if abs(effective) < 1e-9:
        return None
    return float(stats["swing"]) * 100.0 / effective


def signed_decimal_text(value: float, digits: int = 1) -> str:
    """Число со знаком и запятой: «+76,3», «-4,2»."""
    text = f"{float(value):+.{digits}f}".replace(".", ",")
    # Знак минус у нуля только путает: -0,0 это тот же ноль.
    if text.startswith("-") and float(text[1:].replace(",", ".")) == 0.0:
        return "+" + text[1:]
    return text


def difference_text(counts_delta) -> str:
    """Разность двух точек в отсчётах и пикофарадах: «+3120 отсч. (+76,3 пФ)»."""
    if counts_delta is None:
        return "—"
    delta = float(counts_delta)
    return f"{int(round(delta)):+d} отсч. ({signed_decimal_text(counts_to_pf(delta), 1)} пФ)"
