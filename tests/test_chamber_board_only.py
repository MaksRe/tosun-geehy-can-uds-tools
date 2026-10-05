"""Проверки прогона одной платы: своя ёмкость, без эталонов и без трубки.

Пока отдельной платы с эталонами нет, в камеру кладут одну плату прибора, и в
каждом узле снимается только её собственная ёмкость («0/0»). Тесты закрепляют:
- по одной ёмкости таблица платы считается и растяжением, и сдвигом, а
  показание при этой ёмкости после поправки равно опорному в каждом узле;
- без включённого режима одна ёмкость по-прежнему считается недостатком данных;
- разные ёмкости в разных узлах и пропущенные узлы называются;
- отсутствие трубки в этом режиме не мешает считать таблицы полными, а ряды
  трубки в профиле не затираются;
- копия расчёта в репозитории прошивки даёт те же числа.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import chamber_fit
from tests.test_chamber_run import _ChamberStub

_FIRMWARE_COPY = Path(__file__).resolve().parents[3] / "_Embedded" / "Embedded_git" / \
    "apm32f103cbt7_fuel_intake_iar" / "tools" / "chamber_fit.py"


def _board_run(gain_per_c=80e-6, offset_per_c=0.3, nodes=chamber_fit.NODES_X10):
    """Точки «0/0» одной платы: показание уходит с температурой растяжением и сдвигом."""
    points = []
    for node in nodes:
        delta = (node - chamber_fit.REFERENCE_X10) / 10.0
        points.append({
            "time": "12:00:00", "note": "0/0",
            "main": int(round(5000 * (1 + gain_per_c * delta) + offset_per_c * delta)),
            "media": int(round(4500 * (1 - gain_per_c * delta) - offset_per_c * delta)),
            "fuel_temp_x10": node, "board_temp_x10": node, "rehearsal": False,
        })
    return points


@pytest.mark.parametrize("model", chamber_fit.SINGLE_MODELS)
def test_single_capacitance_returns_every_node_to_the_reference(model):
    points = _board_run()
    result = chamber_fit.compute_tables(points, single_model=model, board_only=True)

    assert result["замечания"] == []
    assert result["одна_ёмкость"] == model and result["только_плата"] is True
    for channel, key in (("main", "ступень_платы"), ("media", "ступень_платы_вида")):
        table = result[key]
        reference = next(p[channel] for p in points if p["board_temp_x10"] == chamber_fit.REFERENCE_X10)
        for point in points:
            corrected = chamber_fit.apply_board_table(point[channel], table, point["board_temp_x10"])
            assert abs(corrected - reference) <= 1.0
        # Растяжение не трогает сдвиг, сдвиг не трогает растяжение.
        index = 0 if model == chamber_fit.SINGLE_GAIN else 1  # пара: (сдвиг, растяжение)
        assert all(pair[index] == 0 for pair in table)


def test_single_capacitance_is_not_enough_without_the_mode():
    result = chamber_fit.compute_tables(_board_run())
    assert result["ступень_платы"] == []
    assert any("нужно минимум 2" in item for item in result["замечания"])
    assert any("сухой трубки" in item for item in result["замечания"])


def test_missing_nodes_are_named():
    points = _board_run(nodes=[-400, 0, 250])
    result = chamber_fit.compute_tables(points, single_model=chamber_fit.SINGLE_GAIN, board_only=True)
    assert any("нет точки в узлах" in item and "+85 °C" in item for item in result["замечания"])


def test_different_capacitance_in_a_node_is_named():
    points = _board_run()
    points[0]["note"] = "68/22"
    result = chamber_fit.compute_tables(points, single_model=chamber_fit.SINGLE_GAIN, board_only=True)
    assert any("одна и та же во всех узлах" in item for item in result["замечания"])


def test_two_capacitances_win_over_the_single_mode():
    """Если в узлах уже по две ёмкости, считается честная прямая, а не допущение."""
    points = _board_run()
    for point in list(points):
        extra = dict(point, note="150/47", main=point["main"] + 6000, media=point["media"] + 2000)
        points.append(extra)
    result = chamber_fit.compute_tables(points, single_model=chamber_fit.SINGLE_GAIN, board_only=True)
    assert result["замечания"] == []
    assert any(pair[0] != 0 for pair in result["ступень_платы"])


def test_firmware_copy_computes_the_same_single_table():
    if not _FIRMWARE_COPY.is_file():
        pytest.skip("репозиторий прошивки рядом не найден")
    spec = importlib.util.spec_from_file_location("firmware_chamber_fit_single", _FIRMWARE_COPY)
    firmware = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(firmware)
    points = _board_run()
    for model in chamber_fit.SINGLE_MODELS:
        for module in (chamber_fit, firmware):
            report = []
            stage = module.group_stage1(points, "main")
            table, _used = module.build_board_table(stage, report, "основной контур", single_model=model)
            if module is chamber_fit:
                expected = (table, report)
            else:
                assert (table, report) == expected


# ------------------------------------------------------------------ окно прогона

class _Stub(_ChamberStub):
    def __init__(self):
        super().__init__()
        self._chamber_board_only = False
        self._chamber_single_model = chamber_fit.SINGLE_GAIN


def test_board_only_mode_gives_complete_tables_and_keeps_tube_rows():
    stub = _Stub()
    stub._chamber_points = _board_run()
    stub._chamber_set_board_only(True)

    assert stub._chamber_tables_complete
    assert "ступень_трубки" not in stub.applied
    assert stub.applied["ступень_платы"]


def test_switching_on_sets_the_label_and_coverage():
    stub = _Stub()
    stub._chamber_set_board_only(True)
    assert stub._chamber_label == "0/0"

    stub._chamber_points = _board_run(nodes=[250])
    rows = stub._chamber_coverage_rows()
    reference = rows[chamber_fit.NODES_X10.index(chamber_fit.REFERENCE_X10)]
    assert reference["capsOk"] and reference["tubeOk"] and reference["caps"] == "плата снята"
    assert not rows[0]["capsOk"] and rows[0]["tube"] == "не нужна"


def test_model_choice_is_checked_and_recomputes():
    stub = _Stub()
    stub._chamber_points = _board_run()
    stub._chamber_set_board_only(True)
    gain_table = stub.applied["ступень_платы"]

    assert not stub._chamber_set_single_model("как-нибудь")
    assert stub._chamber_set_single_model(chamber_fit.SINGLE_OFFSET)
    assert stub.applied["ступень_платы"] != gain_table
    assert all(pair[1] == 0 for pair in stub.applied["ступень_платы"])


def test_bench_walk_with_simulated_drift_passes_in_board_only_mode(tmp_path: Path):
    """Репетиция на столе: обход узлов с имитацией ухода, одна плата, сверка проходит."""
    from tests.test_chamber_test_mode import _TestStub, _drive

    stub = _TestStub(tmp_path)
    stub._chamber_board_only = False
    stub._chamber_single_model = chamber_fit.SINGLE_GAIN
    stub.open_access()
    stub._chamber_test_drift_on = True
    stub._profile_apply_chamber_format = lambda payload: True
    stub._chamber_set_board_only(True)

    stub._chamber_test_walk_start()
    _drive(stub, main=5000, media=4500)

    assert len(stub._chamber_points) == len(chamber_fit.NODES_X10)
    assert stub._chamber_tables_complete
    assert "одна ёмкость" in stub._chamber_test_check_text and "пройдена" in stub._chamber_test_check_text
