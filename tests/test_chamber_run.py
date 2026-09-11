"""Проверки раздела прогона в климатической камере.

Прогон длится часами и не переделывается. Если точка запишется с чужой
пометкой, потеряется при сохранении или расчёт запустится на неполных данных и
промолчит, весь выезд в камеру придётся повторять.

Тесты закрепляют: точка усредняется по нескольким замерам; журнал читается
обратно без потерь; расчёт отказывается работать молча и называет причину.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_fit
from ui.qml.controller.chamber_mixin import AppControllerChamberMixin


class _Signal:
    """Заглушка сигнала Qt: считает вызовы вместо реальной рассылки."""

    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _ChamberStub(AppControllerChamberMixin):
    """Носитель логики прогона без Qt и без CAN."""

    def __init__(self):
        self.chamberChanged = _Signal()
        self._chamber_label = ""
        self._chamber_points = []
        self._chamber_busy = False
        self._chamber_status = ""
        self._chamber_status_color = ""
        self._chamber_report = []
        self._chamber_file_path = ""
        self._chamber_samples = []
        self._chamber_samples_left = 0
        self._chamber_sample = {}
        self._chamber_pending = None
        self._chamber_queue = []
        self._profile_status = ""
        self._profile_status_color = ""

    # Профиль в этих проверках подменён: важно, что расчёт до него доходит.
    def _profile_apply_chamber_format(self, payload):
        self.applied = payload
        return True

    def _profile_calc_crc(self):
        return 0x1234

    def _profile_set_status(self, text, color):
        self._profile_status = text
        self._profile_status_color = color


def _full_run_points() -> list[dict]:
    """Полный прогон: в каждом узле две ёмкости и оба состояния трубки."""
    points = []
    for node in chamber_fit.NODES_X10:
        for note, capacitance in (("0 пФ", 0.0), ("120 пФ", 120.0)):
            points.append({
                "time": "12:00:00", "note": note,
                "main": int(round(4820 + 40.9 * capacitance)), "media": 2400,
                "fuel_temp_x10": node, "board_temp_x10": node,
            })
        for note, immersion in ((chamber_fit.AIR_NOTE, 0.0), (chamber_fit.LIQUID_NOTE, 1.0)):
            points.append({
                "time": "12:00:00", "note": note,
                "main": int(round(4820 + 40.9 * (60.0 + 60.0 * immersion))),
                "media": int(round(4820 + 40.9 * (30.0 + 30.0 * immersion))),
                "fuel_temp_x10": node, "board_temp_x10": node,
            })
    return points


def test_point_is_the_average_of_several_samples():
    """Одна точка это среднее нескольких замеров: одиночный замер слишком шумный."""
    stub = _ChamberStub()
    stub._chamber_label = "300 пФ"
    stub._chamber_samples = [
        {"main": 7100, "media": 2400, "fuel_temp": 250, "board_temp": 250},
        {"main": 7104, "media": 2402, "fuel_temp": 250, "board_temp": 250},
        {"main": 7102, "media": 2401, "fuel_temp": 250, "board_temp": 250},
    ]
    stub._chamber_store_point()

    assert len(stub._chamber_points) == 1
    point = stub._chamber_points[0]
    assert point["main"] == 7102
    assert point["media"] == 2401
    assert point["note"] == "300 пФ"


def test_point_without_period_is_not_stored():
    """Без периода точка бесполезна, и записывать её нельзя даже как частичную."""
    stub = _ChamberStub()
    stub._chamber_label = "воздух"
    stub._chamber_samples = [{"media": 2400, "board_temp": 250}]
    stub._chamber_store_point()

    assert stub._chamber_points == []
    assert "не записана" in stub._chamber_status


def test_point_far_from_the_grid_is_stored_with_a_warning():
    """Точку между узлами записываем, но сразу говорим, что в расчёт она не пойдёт."""
    stub = _ChamberStub()
    stub._chamber_label = "300 пФ"
    stub._chamber_samples = [{"main": 7100, "media": 2400, "fuel_temp": 380, "board_temp": 380}]
    stub._chamber_store_point()

    assert len(stub._chamber_points) == 1
    assert "далеко от узлов" in stub._chamber_status


def test_last_point_can_be_taken_back():
    """Пометку легко перепутать, поэтому последнюю точку надо уметь убрать."""
    stub = _ChamberStub()
    stub._chamber_points = _full_run_points()
    before = len(stub._chamber_points)

    assert stub._chamber_remove_last_point()
    assert len(stub._chamber_points) == before - 1


def test_log_round_trip_keeps_every_point(tmp_path: Path):
    """Прогон прерывают на перерыв, поэтому журнал обязан читаться обратно без потерь."""
    stub = _ChamberStub()
    stub._chamber_points = _full_run_points()
    path = tmp_path / "run.csv"

    assert stub._chamber_save_file(str(path))

    restored = _ChamberStub()
    assert restored._chamber_load_file(str(path))
    assert restored._chamber_points == stub._chamber_points


def test_alien_file_is_refused(tmp_path: Path):
    """Чужой файл не должен молча превращаться в пустой прогон."""
    path = tmp_path / "alien.csv"
    path.write_text("что-то;совсем;другое\n1;2;3\n", encoding="utf-8")

    stub = _ChamberStub()
    assert not stub._chamber_load_file(str(path))
    assert stub._chamber_points == []


def test_calculation_fills_the_profile_when_data_is_complete():
    """Полный прогон обязан посчитаться и сразу попасть в таблицы профиля."""
    stub = _ChamberStub()
    stub._chamber_points = _full_run_points()

    assert stub._chamber_compute_tables()
    assert stub._chamber_report == []
    assert "ступень_платы" in stub.applied
    assert "посчитаны" in stub._profile_status


def test_calculation_refuses_and_names_the_reason():
    """Без опорной точки расчёт обязан отказаться и сказать, чего не хватило."""
    stub = _ChamberStub()
    stub._chamber_points = [
        point for point in _full_run_points()
        if point["board_temp_x10"] != chamber_fit.REFERENCE_X10
    ]

    assert not stub._chamber_compute_tables()
    assert any("опорной точке" in item for item in stub._chamber_report)


def test_empty_run_is_refused():
    """Считать по пустому журналу нечего, и молчать об этом нельзя."""
    stub = _ChamberStub()
    assert not stub._chamber_compute_tables()
    assert "не снято" in stub._chamber_status


def test_coverage_shows_what_is_missing():
    """Сводка полноты обязана показывать, в каких узлах чего не хватает."""
    stub = _ChamberStub()
    stub._chamber_points = [
        point for point in _full_run_points()
        if point["board_temp_x10"] != chamber_fit.NODES_X10[-1]
    ]

    rows = stub._chamber_coverage_rows()
    assert len(rows) == len(chamber_fit.NODES_X10)
    assert all(row["capsOk"] and row["tubeOk"] for row in rows[:-1])
    assert not rows[-1]["capsOk"]
    assert not rows[-1]["tubeOk"]
    assert rows[-1]["tube"] == "нет обеих"


def test_coverage_tells_which_tube_state_is_missing():
    """Оператору важно знать не «нет данных», а какого именно состояния не хватает."""
    stub = _ChamberStub()
    stub._chamber_points = [
        point for point in _full_run_points()
        if point["note"] != chamber_fit.LIQUID_NOTE
    ]

    rows = stub._chamber_coverage_rows()
    assert all(row["tube"] == "нет погружённой" for row in rows)
