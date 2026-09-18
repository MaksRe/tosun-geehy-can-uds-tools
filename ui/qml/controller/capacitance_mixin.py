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
    DEFAULT_FUEL_EPS,
    REFERENCE_CAP_PF,
    counts_text,
    counts_to_pf,
    decimal_text,
    difference_text,
    parasitic_from_points,
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
        # Проницаемость топлива, на котором калибруют: нужна, чтобы отделить
        # постоянную часть ёмкости от самого датчика. В прибор не пишется.
        self._capacitance_fuel_eps = DEFAULT_FUEL_EPS

    def _capacitance_set_fuel_eps(self, text: str):
        """Задаёт проницаемость топлива, по которой делится ёмкость контура."""
        try:
            value = float(str(text).replace(",", ".").strip())
        except ValueError:
            self._capacitance_set_status(
                "Проницаемость топлива: в поле не число. Для дизельного топлива это около 2,35.",
                self.CAPACITANCE_COLOR_WARN,
            )
            return
        if not (1.05 <= value <= 10.0):
            self._capacitance_set_status(
                f"Проницаемость топлива {decimal_text(value, 2)} вне разумного: ждём от 1,05 до 10.",
                self.CAPACITANCE_COLOR_WARN,
            )
            return
        self._capacitance_fuel_eps = value
        self._capacitance_set_status(
            f"Проницаемость топлива принята равной {decimal_text(value, 2)}.",
            self.CAPACITANCE_COLOR_IDLE,
        )

    # ------------------------------------------------------------------ окна показаний

    def _capacitance_window_s(self) -> float:
        """Окно захвата, общее для обоих контуров."""
        window = getattr(self, "_calibration_recent_window_sec", None)
        return float(window) if window else 4.0

    def _capacitance_reference_points(self, key: str) -> tuple:
        """Две опорные точки контура: в воздухе и в топливе, в отсчётах."""
        if key == "main":
            # Отметки бака сняты в тех же двух положениях: 0 % это сухой датчик.
            air = self._calibration_level_0 if self._calibration_level_0_known else None
            fuel = self._calibration_level_100 if self._calibration_level_100_known else None
            return air, fuel, "отметкам 0 % и 100 %"
        return self._media_wizard_air, self._media_wizard_cal, "точкам «воздух» и «топливо»"

    def _capacitance_split(self, key: str) -> dict:
        """Постоянная часть ёмкости контура и чувствительность самого датчика."""
        air, fuel, source = self._capacitance_reference_points(key)
        split = parasitic_from_points(air, fuel, self._capacitance_fuel_eps)

        view = {
            "parasiticText": "—",
            "strayText": "",
            "sensitivityText": "",
            "sourceText": "",
        }
        if split is None:
            view["sourceText"] = (
                f"Постоянная часть считается по {source}. "
                "Прочитайте их из прибора, и в топливе ёмкость должна быть выше, чем в воздухе."
            )
            return view

        stray = float(split["stray_pf"])
        view["parasiticText"] = (
            f"{int(round(float(split['parasitic_counts'])))} отсч. "
            f"· {decimal_text(float(split['parasitic_pf']), 1)} пФ"
        )
        if stray > 0.0:
            view["strayText"] = (
                f"это образцовый конденсатор {int(REFERENCE_CAP_PF)} пФ и ещё "
                f"{decimal_text(stray, 1)} пФ на кабель, разъём, плату и вход"
            )
        else:
            # Постоянная часть ниже одного образцового конденсатора физически
            # невозможна, если номиналы контура те же, что в расчёте. Значит,
            # у этого контура другой заряжающий резистор или другой образцовый
            # конденсатор, и пикофарады по нему считать нельзя.
            view["strayText"] = (
                f"это меньше образцового конденсатора {int(REFERENCE_CAP_PF)} пФ, значит у контура "
                "другие номиналы, чем в расчёте: отсчётам верьте, пикофарадам нет"
            )
        view["sensitivityText"] = (
            f"датчик даёт {decimal_text(float(split['sensitivity_pf']), 1)} пФ на единицу проницаемости"
        )
        view["sourceText"] = (
            f"Посчитано по {source} при проницаемости топлива "
            f"{decimal_text(float(self._capacitance_fuel_eps), 2)}."
        )
        return view

    def _capacitance_circuit(self, key: str, now: float) -> dict:
        """Ёмкость одного контура: эффективное значение, текущее, плавание и состав."""
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
            "effectiveNote": "",
            "swingText": "нет данных",
            "spreadText": "",
            "offsetText": "",
            "warn": False,
        }
        view.update(self._capacitance_split(key))

        if stats is None:
            view["swingText"] = "показаний ещё нет: опрос идёт после «Начать калибровку»"
            return view

        effective = float(stats["effective"])
        view["effectiveCounts"] = counts_text(effective)
        view["effectivePf"] = pf_text(effective)
        view["effectiveNote"] = (
            f"среднее за {decimal_text(window, 0)} с, то же число, что в «Захват, среднее»"
        )

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
            "fuelEpsText": decimal_text(float(self._capacitance_fuel_eps), 2),
            "note": (
                "Отсчёт контура - это время между порогами компараторов, оно прямо пропорционально "
                f"ёмкости: {decimal_text(1.0 / counts_to_pf(1.0), 1)} отсчёта на пикофараду при заряде "
                "через 270 кОм и отношении порогов 8,2. В пикофарадах показана вся ёмкость контура: "
                f"датчик, образцовый конденсатор {int(REFERENCE_CAP_PF)} пФ, кабель и плата."
            ),
        }
