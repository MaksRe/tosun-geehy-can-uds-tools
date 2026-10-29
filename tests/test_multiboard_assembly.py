"""Второй этап нескольких плат: изделие в сборе, сухая трубка, на имитаторе камеры.

Первый этап - настоящие журналы пяти плат прогона 28.10.2026 (только плата,
своя ёмкость «0/0», 7 узлов). Второй этап дописывается в журнал каждой платы:
- сценарий «Изделие в сборе»: «Только плата» выключено, пометка «воздух»;
- проверка перед прогоном требует у каждой платы журнал первого этапа;
- прогон по 7 узлам снимает сухую трубку у всех плат, каждую - в её журнал;
- «жидкость» вне камеры снимается только у показанной платы;
- таблица платы по одной ёмкости считается и под трубкой, строки трубки - после
  поправки именно этой платы, достроенные строки «в жидкости» запись не держат;
- профиль ставится в очередь записи у всех пяти плат.
"""

from __future__ import annotations

import csv
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_fit
from tests.test_multiboard import _MbStub
from ui.qml import climate_scenario as cs

# Копии журналов первого этапа с ноутбука (папка v1.0.20, logs\chamber), по 7 точек у каждой платы.
STAGE1 = Path(__file__).resolve().parent / "data" / "stage1_2026-10-28"
# Адрес, имя и сдвиг температуры платы от средней (как в прогоне 28.10: П3 холоднее остальных).
BOARDS = ((0x81, "П1", 0.6), (0x82, "П2", 0.9), (0x83, "П3", -1.8), (0x84, "П4", 0.3), (0x85, "П5", 0.0))
# Сухая трубка добавляет к своей ёмкости платы, отсчётов; трубка уходит с температурой топлива.
TUBE_MAIN, TUBE_MEDIA, TUBE_DRIFT = 60, 20, 0.1
# Погружение в топливо: размах трубки, отсчётов.
SPAN_MAIN, SPAN_MEDIA = 400, 150


def _journal(sa: int) -> Path:
    found = sorted(STAGE1.glob(f"chamber_*_0x{sa:02X}.csv"))
    assert found, f"нет журнала первого этапа платы 0x{sa:02X} в {STAGE1}"
    return found[0]


def _stage1(path: Path) -> list[tuple[float, int, int]]:
    """Точки первого этапа: температура платы, периоды обоих контуров."""
    rows = list(csv.reader(path.open(encoding="utf-8-sig"), delimiter=";"))[1:]
    return sorted((float(row[5].replace(",", ".")), int(row[2]), int(row[3])) for row in rows)


def _raw(points, board_c: float, index: int) -> float:
    """Период своей ёмкости платы при температуре платы - как в первом этапе (линейно между точками)."""
    if board_c <= points[0][0]:
        return points[0][index]
    for left, right in zip(points, points[1:]):
        if board_c <= right[0]:
            share = (board_c - left[0]) / (right[0] - left[0])
            return left[index] + (right[index] - left[index]) * share
    return points[-1][index]


class _Rig:
    """Пять плат в корпусах: показания каждой - её первый этап плюс трубка."""

    def __init__(self, tmp_path: Path):
        self.stub = _MbStub(tmp_path)
        self.stage1 = {}
        self.files = {}
        self.dipped: int | None = None
        # Изделие вынуто из камеры и остыло: температура вне камеры.
        self.room_c: float | None = None
        for sa, name, _offset in BOARDS:
            assert self.stub._mb_add_board(f"0x{sa:02X}", name)[0]
            source = _journal(sa)
            target = tmp_path / source.name
            shutil.copy2(source, target)
            self.stage1[sa] = _stage1(source)
            self.files[sa] = target
        assert self.stub._mb_set_enabled(True)[0]
        self.stub._chamber_auto_write = True

    def feed(self, now: float):
        stub = self.stub
        reading = stub.sim.read()
        stub._climate_reading = reading
        stub._climate_last_ok_s = now
        product = reading.product_c if reading.product_c is not None else 25.0
        if self.room_c is not None:
            product = self.room_c
        for sa, _name, offset in BOARDS:
            board_c = product + offset
            fuel_c = product
            main = _raw(self.stage1[sa], board_c, 1) + TUBE_MAIN + TUBE_DRIFT * (fuel_c - 25.0)
            media = _raw(self.stage1[sa], board_c, 2) + TUBE_MEDIA
            if sa == self.dipped:
                main, media = main + SPAN_MAIN, media + SPAN_MEDIA
            with stub._mb_context(sa):
                for shift in (2.0, 1.0, 0.0):
                    stamp = now - shift
                    stub._chamber_live_note("board_temp", int(round(board_c * 10)), stamp)
                    stub._chamber_live_note("fuel_temp", int(round(fuel_c * 10)), stamp)
                    stub._chamber_live_note("main", int(round(main)), stamp)
                    stub._chamber_live_note("media", int(round(media)), stamp)

    def walk(self, limit=40000, step_s=30.0) -> float:
        stub = self.stub
        start = time.monotonic()
        for step in range(limit):
            now = start + step * step_s
            stub.clock[0] = step * step_s
            self.feed(now)
            stub._climate_note_board(now)
            if stub._climate_run_stage:
                stub._climate_run_tick(now)
            stub._climate_auto_tick(now)
            if not stub._climate_run_stage and not stub._climate_auto_finishing:
                return now
        raise AssertionError("прогон не закончился")

    def open_stage1(self):
        for sa, *_rest in BOARDS:
            with self.stub._mb_context(sa):
                assert self.stub._chamber_load_file(str(self.files[sa])), sa
                assert len(self.stub._chamber_points) == 7

    def checks(self) -> dict:
        return {item["key"]: item for item in self.stub._climate_auto_checks()}


def _assembly(rig: _Rig):
    stub = rig.stub
    assert stub._climate_scenario_new("assembly")
    scenario = stub._climate_scenario
    assert scenario["board_only"] is False and scenario["labels"] == ["воздух"]
    assert [step["temp"] for step in scenario["steps"]] == list(cs.BOARD_CYCLE_TEMPS)
    stub._chamber_set_board_only(False)
    stub._chamber_label = "воздух"
    stub._chamber_extend_liquid = True


def test_assembly_scenario_is_valid():
    clean, problems = cs.normalize(cs.assembly_scenario())
    assert problems == [] and clean["board_only"] is False and clean["labels"] == ["воздух"]
    assert clean["name"] == cs.ASSEMBLY_NAME


def test_stage2_needs_stage1_journal_of_every_board(tmp_path: Path):
    rig = _Rig(tmp_path)
    _assembly(rig)
    rig.feed(time.monotonic())
    check = rig.checks()["stage2"]
    assert not check["ok"] and check["level"] == "block" and "журнал первого этапа не открыт" in check["text"]
    rig.open_stage1()
    check = rig.checks()["stage2"]
    assert check["ok"] and "у всех 5 плат" in check["text"], check["text"]
    assert rig.checks()["stage2_liquid"]["ok"]
    rig.stub._chamber_set_board_only(True)
    assert not rig.checks()["stage2"]["ok"], "трубка при «Только плата» в профиль не попадёт"


def test_stage2_run_of_five_boards_gives_each_its_own_tube_rows(tmp_path: Path):
    rig = _Rig(tmp_path)
    stub = rig.stub
    rig.open_stage1()
    _assembly(rig)
    rig.feed(time.monotonic())
    blockers = stub._climate_auto_blockers()
    assert not any("Второй этап" in text for text in blockers), blockers
    queued = []
    stub._mb_profile_tick = lambda now: queued.extend(stub._mb_profile_queue) or stub._mb_profile_queue.clear()
    assert stub._climate_run_start(), stub._climate_run_status
    now = rig.walk()

    for sa, name, _offset in BOARDS:
        with stub._mb_context(sa):
            assert stub._chamber_file_path == str(rig.files[sa]), "точки трубки - в журнал первого этапа платы"
            air = [point for point in stub._chamber_points if point["note"] == "воздух"]
            nodes = sorted({chamber_fit.nearest_node(point["fuel_temp_x10"]) for point in air})
            assert nodes == sorted(chamber_fit.NODES_X10), (name, nodes)
            assert len(stub._chamber_points) == 7 + len(air)
            # Погружения ещё нет: таблицы трубки неполные, профиль не записан.
            assert not stub._chamber_tables_complete
    assert not queued, "без погружения профиль в платы не пишется"

    # Вне камеры, при комнатной температуре: каждую трубку погружают по одной.
    stub._chamber_label = "жидкость"
    rig.room_c = 24.5
    for sa, name, _offset in BOARDS:
        assert stub._mb_activate(sa, force=True)
        rig.dipped = sa
        now += 30.0
        rig.feed(now)
        ok, text = stub._mb_manual_capture_start()
        assert ok and "только у показанной платы" in text, text
        stub._mb_manual_capture_tick(now)
        assert stub._mb_manual_capture is None and f"у платы «{name}»" in stub._mb_status, stub._mb_status
    rig.dipped = None

    for sa, name, _offset in BOARDS:
        with stub._mb_context(sa):
            liquid = [point for point in stub._chamber_points if point["note"] == "жидкость"]
            assert len(liquid) == 1, (name, "жидкость - только у своей платы")
            stub._chamber_auto_compute()
            assert stub._chamber_tables_complete, (name, stub._chamber_report)
            assert any("достроены по размаху" in item for item in stub._chamber_report)
            assert any("по одной своей ёмкости" in item for item in stub._chamber_report)

            result = chamber_fit.compute_tables(stub._chamber_points, extend_liquid=True,
                                                **stub._chamber_fit_mode())
            stage1 = chamber_fit.compute_tables(
                [point for point in stub._chamber_points if point["note"] == "0/0"],
                single_model=chamber_fit.SINGLE_GAIN, board_only=True)
            assert result["ступень_платы"] == stage1["ступень_платы"], (name, "таблица платы - та же, что в первом этапе")
            assert result["ступень_платы_вида"] == stage1["ступень_платы_вида"], name

            # После поправки своей платы сухая трубка - это период при +25 плюс трубка и её уход.
            ref_main = _raw(rig.stage1[sa], 25.0, 1)
            tube = result["ступень_трубки"]
            for index, node in enumerate(chamber_fit.NODES_X10):
                expected = ref_main + TUBE_MAIN + TUBE_DRIFT * (node / 10.0 - 25.0)
                assert abs(tube["air_main"][index] - expected) <= 3, (name, node, tube["air_main"][index], expected)
                assert tube["full_main"][index] - tube["air_main"][index] == pytest.approx(SPAN_MAIN, abs=2)
                assert tube["full_media"][index] - tube["air_media"][index] == pytest.approx(SPAN_MEDIA, abs=2)

    text = stub._mb_start_profiles(manual=True)
    assert sorted(stub._mb_profile_queue) == [sa for sa, *_rest in BOARDS], text


def test_coverage_shows_stage2_nodes_as_done(tmp_path: Path):
    rig = _Rig(tmp_path)
    rig.open_stage1()
    _assembly(rig)
    stub = rig.stub
    with stub._mb_context(0x81):
        rows = stub._chamber_coverage_rows()
        assert all(row["capsOk"] for row in rows), "одной своей ёмкости «0/0» хватает таблице платы"
        assert not any(row["tubeOk"] for row in rows), "трубки ещё нет"
        for point in list(stub._chamber_points):
            stub._chamber_points.append(dict(point, note="воздух"))
        stub._chamber_points.append(dict(stub._chamber_points[0], note="жидкость"))
        rows = {row["node"]: row for row in stub._chamber_coverage_rows()}
        assert all(row["tubeOk"] for row in rows.values())
        assert rows["-40 °C"]["tube"] == "сухая, погружение по размаху" and rows["+25 °C"]["tube"] == "есть"
