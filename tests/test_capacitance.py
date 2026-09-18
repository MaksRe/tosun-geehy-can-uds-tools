"""Проверки перевода отсчётов в ёмкость и показа её плавания.

Коэффициент перевода выведен из схемы: заряд через 270 кОм, отношение порогов
8,2, таймер 72 МГц без делителя. Он же назван в прошивке - около 40,9 отсчёта на
пикофараду. Если коэффициент однажды разъедется с прошивкой, все пикофарады в
программе станут враньём, поэтому он закреплён тестом.

Отдельно закреплена тестовая точка «полное погружение»: она нужна только для
оценки вклада коаксиального кабеля, живёт в программе и в прибор не пишется.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.capacitance import (
    COUNTS_PER_PF,
    counts_to_pf,
    difference_text,
    pf_to_counts,
    swing_percent,
    window_stats,
    window_values,
)
from ui.qml.controller.capacitance_mixin import AppControllerCapacitanceMixin


class _Signal:
    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _CapStub(AppControllerCapacitanceMixin):
    """Показ ёмкости без Qt и без шины: окна показаний задаются прямо в тесте."""

    def __init__(self):
        self.capacitanceChanged = _Signal()
        self.events = []
        self._init_capacitance_state()
        self._calibration_recent_window_sec = 4.0
        self._calibration_recent_samples = []
        self._calibration_current_level = 0
        self._media_wizard_recent = []
        self._media_wizard_live_raw = None
        self._media_wizard_captured = None
        self._media_wizard_captured_spread = None
        self._media_wizard_air = None
        self._media_wizard_cal = None

    def _calibration_log_event(self, text):
        self.events.append(text)


def _window(now, values):
    """Окно показаний: пары (время, число) с шагом в десятую долю секунды."""
    return [(now - 0.1 * (len(values) - index), value) for index, value in enumerate(values)]


# ------------------------------------------------------------------ перевод

def test_counts_per_picofarad_matches_the_firmware():
    """40,9 отсчёта на пикофараду: то же число названо в fuel_timer.c прошивки."""
    assert round(COUNTS_PER_PF, 1) == 40.9


def test_conversion_goes_both_ways():
    assert round(counts_to_pf(pf_to_counts(296.5)), 6) == 296.5


def test_capacitance_of_a_real_reading_is_hundreds_of_picofarads():
    """Отметка основного контура около 12130 отсчётов это примерно 296 пФ."""
    assert 290.0 < counts_to_pf(12130) < 300.0


def test_difference_is_shown_with_a_sign_in_both_units():
    assert difference_text(1220) == "+1220 отсч. (+29,8 пФ)"
    assert difference_text(-50) == "-50 отсч. (-1,2 пФ)"
    assert difference_text(None) == "—"


# ------------------------------------------------------------------ окно захвата

def test_single_reading_says_nothing_about_floating():
    assert window_stats([4000]) is None
    assert window_stats([]) is None


def test_effective_value_and_floating_come_from_the_window():
    stats = window_stats([3600, 3604, 3602, 3598])
    assert stats["count"] == 4
    assert stats["effective"] == 3601.0
    assert stats["spread"] == 6.0
    # Наибольшее отклонение от среднего: одно показание может соврать на столько.
    assert stats["swing"] == 3.0
    assert round(swing_percent(stats), 4) == round(3.0 * 100.0 / 3601.0, 4)


def test_old_readings_leave_the_window():
    now = time.monotonic()
    samples = [(now - 10.0, 5000), (now - 1.0, 3600), (now - 0.5, 3602)]
    assert window_values(samples, now, 4.0) == [3600, 3602]


# ------------------------------------------------------------------ показ контуров

def test_circuit_without_readings_explains_itself():
    stub = _CapStub()
    view = stub._capacitance_view()["main"]
    assert view["hasData"] is False
    assert "Начать калибровку" in view["swingText"]


def test_circuit_shows_effective_capacitance_and_floating():
    stub = _CapStub()
    now = time.monotonic()
    stub._calibration_recent_samples = _window(now, [12128, 12130, 12132, 12130])
    stub._calibration_current_level = 12134
    view = stub._capacitance_view()["main"]

    assert view["effectiveCounts"] == "12130 отсч."
    assert view["effectivePf"] == "296,5 пФ"
    assert view["swingText"].startswith("±2 отсч.")
    assert "по 4 показаниям" in view["spreadText"]
    assert view["offsetText"] == "текущее отличается на +4 отсч. (+0,1 пФ)"
    assert view["warn"] is False


def test_wildly_floating_circuit_is_marked():
    stub = _CapStub()
    now = time.monotonic()
    stub._media_wizard_recent = _window(now, [3600, 3700, 3620, 3680])
    view = stub._capacitance_view()["media"]
    assert view["warn"] is True


# ------------------------------------------------------------------ тестовая точка

def test_test_point_is_taken_from_the_capture_and_is_not_written_to_the_device():
    stub = _CapStub()
    stub._media_wizard_captured = 4120
    stub._media_wizard_captured_spread = 5
    stub._capacitance_save_test_point("")

    point = stub._capacitance_view()["testPoint"]
    assert point["has"] is True
    assert point["countsText"] == "4120 отсч."
    assert point["pfText"] == "100,7 пФ"
    assert "размах захвата 5" in point["spreadText"]
    assert "не записана" in point["statusText"]
    # В журнале калибровки это событие видно, а в приборе от него ничего нет.
    assert stub.events == ["снята тестовая точка «полное погружение»: 4120 отсч."]


def test_test_point_shows_what_the_cable_added():
    """Разница с точкой «топливо» и есть вклад погружённого коаксиального кабеля."""
    stub = _CapStub()
    stub._media_wizard_air = 2380
    stub._media_wizard_cal = 3640
    stub._capacitance_save_test_point("4120")

    point = stub._capacitance_view()["testPoint"]
    assert point["vsAirText"] == "к точке «воздух»: +1740 отсч. (+42,5 пФ)"
    assert point["vsFuelText"] == "к точке «топливо»: +480 отсч. (+11,7 пФ)"


def test_test_point_without_a_capture_says_so():
    stub = _CapStub()
    stub._capacitance_save_test_point("")
    assert stub._capacitance_view()["testPoint"]["has"] is False
    assert "захвата ещё нет" in stub._capacitance_status


def test_nonsense_in_the_field_is_refused():
    stub = _CapStub()
    stub._capacitance_save_test_point("ой")
    assert stub._capacitance_test_point is None
    assert "не число" in stub._capacitance_status

    stub._capacitance_save_test_point("70000")
    assert stub._capacitance_test_point is None
    assert "вне допустимого диапазона" in stub._capacitance_status


def test_forgetting_the_point_leaves_no_trace():
    stub = _CapStub()
    stub._capacitance_save_test_point("4120")
    stub._capacitance_clear_test_point()
    view = stub._capacitance_view()["testPoint"]
    assert view["has"] is False
    assert view["statusText"] == ""
