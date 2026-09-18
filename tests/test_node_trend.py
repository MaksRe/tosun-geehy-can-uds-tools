"""Проверки истории живых чисел: графики, экстремумы и два разных сброса.

Главное, что закрепляют тесты: экстремумы считаются по всем пришедшим данным, а
не по точкам, оставшимся в истории. Иначе вытеснение старых точек тихо забывало
бы рекорд, и график врал бы ровно там, где на него смотрят - при разборе выброса.

Отдельно закреплено прореживание миниатюры: она обязана сохранять выбросы, иначе
дрожание на ней исчезает и картинка успокаивает вместо того, чтобы показывать.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller.node_trend_mixin import (
    AppControllerNodeTrendMixin,
    NODE_TREND_SERIES,
    thin_points,
)


class _Signal:
    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _TrendStub(AppControllerNodeTrendMixin):
    """История без Qt: показания кладутся прямо вызовом."""

    def __init__(self):
        self.nodeTrendChanged = _Signal()
        self._init_node_trend_state()


def _fill(stub, key, values, start=100.0, step=1.0):
    for index, value in enumerate(values):
        stub._node_trend_note(key, value, start + index * step)


# ------------------------------------------------------------------ накопление

def test_history_keeps_what_came_and_remembers_the_extremes():
    stub = _TrendStub()
    _fill(stub, "main_raw", [12100, 12500, 11900, 12300])

    card = stub._node_trend_view()["main_raw"]
    assert card["hasData"] is True
    assert card["countText"] == "точек 4"
    assert card["lastText"] == "12300 отсч."
    assert card["minShort"] == "11900 отсч."
    assert card["maxShort"] == "12500 отсч."


def test_level_is_shown_in_percent():
    """Уровень приходит в промилле: на графике он обязан быть процентами."""
    stub = _TrendStub()
    _fill(stub, "level", [505, 1000])
    card = stub._node_trend_view()["level"]
    assert card["lastText"] == "100,0 %"
    assert card["minShort"] == "50,5 %"


def test_oldest_points_are_pushed_out_but_the_record_stays():
    stub = _TrendStub()
    stub.NODE_TREND_MAX_POINTS = 5
    _fill(stub, "media", [9000, 3600, 3601, 3602, 3603, 3604, 3605])

    track = stub._node_trend["media"]
    assert len(track["points"]) == 5
    # Выброс 9000 уже вытеснен из истории, но как рекорд он остаётся.
    assert [value for _moment, value in track["points"]] == [3601, 3602, 3603, 3604, 3605]
    assert track["max"] == 9000


def test_unknown_key_and_empty_value_are_ignored():
    stub = _TrendStub()
    stub._node_trend_note("нет такого", 5)
    stub._node_trend_note("media", None)
    assert stub._node_trend_view()["media"]["hasData"] is False


# ------------------------------------------------------------------ сбросы

def test_clearing_a_graph_starts_the_filling_over():
    stub = _TrendStub()
    _fill(stub, "media", [3600, 3700])
    stub._node_trend_clear("media")

    card = stub._node_trend_view()["media"]
    assert card["hasData"] is False
    assert card["minShort"] == "—"
    assert stub._node_trend_series_points("media") == []


def test_clearing_extremes_keeps_the_graph():
    stub = _TrendStub()
    _fill(stub, "media", [3600, 3900, 3700])
    stub._node_trend_clear_extremes("media")

    card = stub._node_trend_view()["media"]
    assert card["countText"] == "точек 3", "история осталась на месте"
    # Рекорды начинаются с последней точки, а не с пустоты.
    assert card["minShort"] == "3700 отсч."
    assert card["maxShort"] == "3700 отсч."


def test_empty_key_touches_every_graph():
    stub = _TrendStub()
    _fill(stub, "level", [500])
    _fill(stub, "media", [3600])
    stub._node_trend_clear("")
    assert all(not card["hasData"] for card in stub._node_trend_view().values())


# ------------------------------------------------------------------ отдача точек

def test_full_series_counts_seconds_from_the_first_point():
    stub = _TrendStub()
    _fill(stub, "main_raw", [12100, 12200, 12300], start=1000.0, step=2.0)
    points = stub._node_trend_series_points("main_raw")
    assert [point["x"] for point in points] == [0.0, 2.0, 4.0]
    assert [point["y"] for point in points] == [12100.0, 12200.0, 12300.0]


def test_miniature_keeps_the_outliers_while_thinning():
    source = [(float(index), 100.0) for index in range(1000)]
    source[500] = (500.0, 999.0)
    thinned = thin_points(source, 120)

    assert len(thinned) <= 130, "миниатюра не должна тащить всю историю"
    assert any(value == 999.0 for _moment, value in thinned), "выброс обязан остаться"
    assert thinned[-1] == source[-1], "последняя точка всегда на месте"


def test_short_history_is_not_thinned():
    source = [(float(index), float(index)) for index in range(10)]
    assert thin_points(source, 120) == source


def test_every_series_has_a_place_in_the_view():
    stub = _TrendStub()
    view = stub._node_trend_view()
    assert set(view) == {key for key, *_rest in NODE_TREND_SERIES}
    for key, title, unit, _scale, _digits, color in NODE_TREND_SERIES:
        assert view[key]["title"] == title
        assert view[key]["unit"] == unit
        assert view[key]["color"] == color
