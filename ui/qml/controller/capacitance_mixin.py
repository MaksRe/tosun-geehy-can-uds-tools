"""Ёмкость контуров в отсчётах и пикофарадах и её плавание.

ЗАЧЕМ
Отсчёты контура это время между порогами компараторов, и по ним не видно, какая
ёмкость получилась на самом деле. Пока число не переведено в пикофарады, нельзя
ни сверить его с расчётом по геометрии датчика, ни заметить, что к контуру
подключено не то. Поэтому рядом с отсчётами показывается ёмкость, а вместе с ней
- насколько показание плавает вокруг своего эффективного значения.

ЧТО СЧИТАЕТСЯ ЭФФЕКТИВНЫМ ЗНАЧЕНИЕМ
То же среднее по окну захвата, которое оператор переносит в отметку кнопкой
«Взять захват». Плавание считается по тому же окну: размах показывает полную
ширину дрожания, а наибольшее отклонение - насколько может соврать одно
показание, взятое наугад.

ТОЧКА «ПОЛНОЕ ПОГРУЖЕНИЕ»
Плоский конденсатор подключён к плате коаксиальным кабелем, и длина кабеля равна
длине трубки основного датчика. Значит, при погружении меняется не только
ёмкость самого плоского конденсатора, но и ёмкость кабеля, и в опорные точки эта
добавка входит незаметно. Чтобы её увидеть, здесь снимается ещё одна точка. В
прибор она не пишется и ни на что не влияет: она живёт только в программе и
нужна для отладки.
"""

from __future__ import annotations

import time

from ..capacitance import (
    REFERENCE_CAP_PF,
    counts_text,
    counts_to_pf,
    decimal_text,
    difference_text,
    pf_text,
    swing_percent,
    window_stats,
    window_values,
)
from .contract import AppControllerContract


class AppControllerCapacitanceMixin(AppControllerContract):
    # Цвета подписи о тестовой точке. Свои, а не заимствованные у мастера точек:
    # тестовая точка в прибор не пишется и от мастера не зависит.
    CAPACITANCE_COLOR_OK = "#16a34a"
    CAPACITANCE_COLOR_WARN = "#d97706"
    CAPACITANCE_COLOR_IDLE = "#64748b"

    # Размах показаний в окне, выше которого число считается ещё не устоявшимся, отсчёты.
    CAPACITANCE_UNSETTLED_SPREAD = 40

    # Границы разумного значения точки: те же, что у опорных точек мастера.
    CAPACITANCE_POINT_MIN = 1
    CAPACITANCE_POINT_MAX = 65535

    def _init_capacitance_state(self):
        """Готовит показ ёмкости. Вызывается один раз при создании контроллера."""
        # Точка «полное погружение»: только для отладки, в прибор не пишется.
        self._capacitance_test_point = None
        self._capacitance_status = ""
        self._capacitance_status_color = "#64748b"

    # ------------------------------------------------------------------ окна показаний

    def _capacitance_window_s(self) -> float:
        """Окно захвата, общее для обоих контуров."""
        window = getattr(self, "_calibration_recent_window_sec", None)
        return float(window) if window else 4.0

    def _capacitance_circuit(self, key: str, now: float) -> dict:
        """Ёмкость одного контура: эффективное значение, текущее и плавание."""
        window = self._capacitance_window_s()
        if key == "main":
            samples = getattr(self, "_calibration_recent_samples", None) or []
            current = self._calibration_current_level if self._calibration_current_level else None
        else:
            samples = getattr(self, "_media_wizard_recent", None) or []
            current = self._media_wizard_live_raw

        stats = window_stats(window_values(samples, now, window))

        view = {
            "hasData": stats is not None,
            "currentCounts": counts_text(current),
            "currentPf": pf_text(current),
            "effectiveCounts": "—",
            "effectivePf": "—",
            "swingText": "нет данных",
            "spreadText": "",
            "offsetText": "",
            "warn": False,
        }

        if stats is None:
            view["swingText"] = "показаний ещё нет: опрос идёт после «Начать калибровку»"
            return view

        effective = float(stats["effective"])
        view["effectiveCounts"] = counts_text(effective)
        view["effectivePf"] = pf_text(effective)

        swing = float(stats["swing"])
        percent = swing_percent(stats)
        percent_text = "" if percent is None else f", это {decimal_text(percent, 3)} % ёмкости"
        view["swingText"] = (
            f"±{int(round(swing))} отсч. (±{decimal_text(counts_to_pf(swing), 2)} пФ)" + percent_text
        )
        view["spreadText"] = (
            f"размах {int(round(float(stats['spread'])))} отсч. за {decimal_text(window, 0)} с "
            f"по {int(stats['count'])} показаниям"
        )
        if current is not None:
            view["offsetText"] = "текущее отличается на " + difference_text(float(current) - effective)
        view["warn"] = float(stats["spread"]) > float(self.CAPACITANCE_UNSETTLED_SPREAD)
        return view

    # ------------------------------------------------------------------ точка «полное погружение»

    def _capacitance_set_status(self, text: str, color: str):
        """Записывает подпись о работе с тестовой точкой и её цвет."""
        self._capacitance_status = str(text)
        self._capacitance_status_color = str(color)
        self.capacitanceChanged.emit()

    def _capacitance_save_test_point(self, value_text: str):
        """Запоминает точку «полное погружение» в программе. В прибор она не пишется."""
        text = str(value_text).strip()
        if text:
            try:
                value = int(text, 0)
            except ValueError:
                self._capacitance_set_status(
                    "Точка «полное погружение»: в поле не число. Впишите отсчёты или возьмите захват.",
                    self.CAPACITANCE_COLOR_WARN,
                )
                return
            spread = None
        else:
            captured = self._media_wizard_captured
            if captured is None:
                self._capacitance_set_status(
                    "Точка «полное погружение»: захвата ещё нет. Дождитесь показаний плоского конденсатора.",
                    self.CAPACITANCE_COLOR_WARN,
                )
                return
            value = int(captured)
            spread = self._media_wizard_captured_spread

        if not (self.CAPACITANCE_POINT_MIN <= value <= self.CAPACITANCE_POINT_MAX):
            self._capacitance_set_status(
                f"Точка «полное погружение»: {value} вне допустимого диапазона "
                f"{self.CAPACITANCE_POINT_MIN}..{self.CAPACITANCE_POINT_MAX}.",
                self.CAPACITANCE_COLOR_WARN,
            )
            return

        self._capacitance_test_point = {
            "value": int(value),
            "spread": None if spread is None else int(spread),
            "at": time.strftime("%H:%M:%S"),
        }
        self._capacitance_set_status(
            f"Точка «полное погружение» снята: {value} отсч. ({pf_text(value)}). В прибор она не записана.",
            self.CAPACITANCE_COLOR_OK,
        )
        self._calibration_log_event(f"снята тестовая точка «полное погружение»: {value} отсч.")

    def _capacitance_clear_test_point(self):
        """Забывает тестовую точку: в приборе от неё всё равно ничего не было."""
        self._capacitance_test_point = None
        self._capacitance_set_status("", self.CAPACITANCE_COLOR_IDLE)

    def _capacitance_test_point_view(self) -> dict:
        """Тестовая точка и её разницы с опорными точками прибора."""
        point = self._capacitance_test_point
        view = {
            "has": point is not None,
            "countsText": "—",
            "pfText": "—",
            "atText": "",
            "spreadText": "",
            "vsAirText": "точка «воздух» в приборе не прочитана",
            "vsFuelText": "точка «топливо» в приборе не прочитана",
            "statusText": str(self._capacitance_status),
            "statusColor": str(self._capacitance_status_color),
        }
        if point is None:
            return view

        value = int(point["value"])
        view["countsText"] = counts_text(value)
        view["pfText"] = pf_text(value)
        view["atText"] = f"снята в {point['at']}"
        if point["spread"] is not None:
            view["spreadText"] = f"размах захвата {int(point['spread'])} отсч."

        air = self._media_wizard_air
        if air is not None:
            view["vsAirText"] = "к точке «воздух»: " + difference_text(value - int(air))

        fuel = self._media_wizard_cal
        if fuel is not None:
            view["vsFuelText"] = "к точке «топливо»: " + difference_text(value - int(fuel))

        return view

    # ------------------------------------------------------------------ показ

    def _capacitance_view(self) -> dict:
        """Готовит всё для карточки ёмкости раздела калибровки."""
        now = time.monotonic()
        return {
            "main": self._capacitance_circuit("main", now),
            "media": self._capacitance_circuit("media", now),
            "testPoint": self._capacitance_test_point_view(),
            "note": (
                "В пикофарадах показана вся ёмкость контура: датчик, образцовый конденсатор "
                f"{int(REFERENCE_CAP_PF)} пФ, кабель и плата. Сравнивать имеет смысл разности."
            ),
        }
