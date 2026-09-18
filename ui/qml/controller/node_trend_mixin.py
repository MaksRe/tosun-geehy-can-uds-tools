"""История живых чисел узла: графики и экстремумы.

ЗАЧЕМ
Одно число на экране не отвечает на главные вопросы наладки: растёт показание
или падает, дёргается или стоит, каким оно было минуту назад и до каких границ
доходило. Поэтому уровень топлива и оба контура пишутся в историю, а рядом с
числом показывается миниатюрный график. Он же разворачивается в полноразмерный,
когда нужно рассмотреть дрожание подробно.

ЧТО ЗАПОМИНАЕТСЯ
Пара «время, значение» на каждый пришедший ответ прибора, не больше
NODE_TREND_MAX_POINTS штук: дальше самые старые вытесняются. Отдельно живут
экстремумы - наименьшее и наибольшее значение с момента запуска, со временем,
когда они случились. Экстремумы считаются по всем пришедшим данным, а не по
оставшимся в истории: иначе вытеснение старых точек тихо «забывало» бы рекорд.

ДВА РАЗНЫХ СБРОСА
Сброс графика очищает и историю, и экстремумы: заполнение начинается заново.
Сброс экстремумов оставляет график как есть и обнуляет только рекорды - это
нужно, когда рекорд поставлен случайным выбросом при подключении датчика, а
смотреть на график дальше хочется без разрыва.
"""

from __future__ import annotations

import time

from .contract import AppControllerContract

# Ключ истории: параметр узла, подпись, единица и цвет линии.
NODE_TREND_SERIES = (
    ("level", "Уровень топлива", "%", 0.1, 1, "#16a34a"),
    ("main_raw", "Основной контур", "отсч.", 1.0, 0, "#0284c7"),
    ("media", "Контур вида топлива", "отсч.", 1.0, 0, "#0f766e"),
)

# Сколько точек хранится на каждый параметр: при ответе раз в секунду это час работы.
NODE_TREND_MAX_POINTS = 3600

# Сколько точек уходит в миниатюру: больше не разглядеть даже на широком окне.
NODE_TREND_SPARK_POINTS = 120


def _decimal(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def thin_points(points, limit: int) -> list:
    """Прореживает историю до limit точек, сохраняя первую, последнюю и крайние.

    Простой шаг «каждая N-я» съедает одиночные выбросы, а именно они на графике
    и важны. Поэтому история делится на корзины, и из каждой берутся наименьшая
    и наибольшая точка: линия остаётся той же высоты, что и полная.
    """
    source = list(points)
    if limit <= 0 or len(source) <= limit:
        return source

    bucket = len(source) / float(max(1, limit // 2))
    result = []
    index = 0.0
    while int(index) < len(source):
        start = int(index)
        end = min(len(source), int(index + bucket))
        if end <= start:
            end = start + 1
        chunk = source[start:end]
        lowest = min(chunk, key=lambda item: item[1])
        highest = max(chunk, key=lambda item: item[1])
        first, second = (lowest, highest) if lowest[0] <= highest[0] else (highest, lowest)
        result.append(first)
        if second is not first:
            result.append(second)
        index += bucket

    if result and result[-1] is not source[-1]:
        result.append(source[-1])
    return result


class AppControllerNodeTrendMixin(AppControllerContract):
    NODE_TREND_MAX_POINTS = NODE_TREND_MAX_POINTS
    NODE_TREND_SPARK_POINTS = NODE_TREND_SPARK_POINTS

    def _init_node_trend_state(self):
        """Готовит историю живых чисел. Вызывается один раз при создании контроллера."""
        self._node_trend = {
            key: {"points": [], "min": None, "max": None, "min_at": None, "max_at": None, "started": None}
            for key, _title, _unit, _scale, _digits, _color in NODE_TREND_SERIES
        }

    # ------------------------------------------------------------------ накопление

    def _node_trend_note(self, key: str, value, now: float | None = None):
        """Кладёт очередное показание в историю и обновляет экстремумы."""
        track = self._node_trend.get(str(key))
        if track is None or value is None:
            return

        moment = time.monotonic() if now is None else float(now)
        number = float(value)

        if track["started"] is None:
            track["started"] = moment

        track["points"].append((moment, number))
        if len(track["points"]) > self.NODE_TREND_MAX_POINTS:
            del track["points"][:len(track["points"]) - self.NODE_TREND_MAX_POINTS]

        if track["min"] is None or number < track["min"]:
            track["min"] = number
            track["min_at"] = moment
        if track["max"] is None or number > track["max"]:
            track["max"] = number
            track["max_at"] = moment

        self.nodeTrendChanged.emit()

    def _node_trend_clear(self, key: str = ""):
        """Сбрасывает график: историю и экстремумы. Пустой ключ - все графики."""
        for track_key, track in self._node_trend.items():
            if key and track_key != str(key):
                continue
            track["points"] = []
            track["min"] = None
            track["max"] = None
            track["min_at"] = None
            track["max_at"] = None
            track["started"] = None
        self.nodeTrendChanged.emit()

    def _node_trend_clear_extremes(self, key: str = ""):
        """Сбрасывает только экстремумы, график остаётся. Пустой ключ - все графики."""
        for track_key, track in self._node_trend.items():
            if key and track_key != str(key):
                continue
            points = track["points"]
            if points:
                # Рекорды начинают отсчёт с последней точки, а не с пустоты:
                # иначе до следующего ответа прибора показывать было бы нечего.
                last_at, last_value = points[-1]
                track["min"] = last_value
                track["max"] = last_value
                track["min_at"] = last_at
                track["max_at"] = last_at
            else:
                track["min"] = None
                track["max"] = None
                track["min_at"] = None
                track["max_at"] = None
        self.nodeTrendChanged.emit()

    # ------------------------------------------------------------------ показ

    @staticmethod
    def _node_trend_value_text(value, scale: float, digits: int, unit: str) -> str:
        if value is None:
            return "—"
        return _decimal(float(value) * float(scale), int(digits)) + (" " + unit if unit else "")

    def _node_trend_series_points(self, key: str) -> list:
        """Полная история одного графика для развёрнутого окна: секунды и значение."""
        track = self._node_trend.get(str(key))
        if track is None or not track["points"]:
            return []
        scale = next((item[3] for item in NODE_TREND_SERIES if item[0] == str(key)), 1.0)
        started = float(track["points"][0][0])
        return [
            {"x": float(moment) - started, "y": float(value) * float(scale)}
            for moment, value in track["points"]
        ]

    def _node_trend_card(self, key: str, title: str, unit: str, scale: float, digits: int, color: str) -> dict:
        """Данные одного графика: миниатюра, экстремумы и подписи."""
        track = self._node_trend[key]
        points = track["points"]
        now = time.monotonic()

        spark = []
        if points:
            started = float(points[0][0])
            spark = [
                {"x": float(moment) - started, "y": float(value) * float(scale)}
                for moment, value in thin_points(points, self.NODE_TREND_SPARK_POINTS)
            ]

        span_text = ""
        if len(points) >= 2:
            span_text = "за " + _decimal((float(points[-1][0]) - float(points[0][0])) / 60.0, 1) + " мин"
        elif points:
            span_text = "первая точка"

        def extreme_text(value, moment):
            text = self._node_trend_value_text(value, scale, digits, unit)
            if value is None or moment is None:
                return text
            return text + f", {_decimal(now - float(moment), 0)} с назад"

        return {
            "key": key,
            "title": title,
            "unit": unit,
            "color": color,
            "hasData": len(points) > 0,
            "points": spark,
            "countText": f"точек {len(points)}",
            "spanText": span_text,
            "lastText": self._node_trend_value_text(points[-1][1] if points else None, scale, digits, unit),
            "minText": extreme_text(track["min"], track["min_at"]),
            "maxText": extreme_text(track["max"], track["max_at"]),
            # Короткие подписи для миниатюры: в одну строку карточки длинные не влезают.
            "minShort": self._node_trend_value_text(track["min"], scale, digits, unit),
            "maxShort": self._node_trend_value_text(track["max"], scale, digits, unit),
            "minValue": None if track["min"] is None else float(track["min"]) * float(scale),
            "maxValue": None if track["max"] is None else float(track["max"]) * float(scale),
        }

    def _node_trend_view(self) -> dict:
        """Графики по ключам: то, что показывают карточки раздела."""
        return {
            key: self._node_trend_card(key, title, unit, scale, digits, color)
            for key, title, unit, scale, digits, color in NODE_TREND_SERIES
        }
