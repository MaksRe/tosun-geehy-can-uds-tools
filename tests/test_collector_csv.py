"""Проверки журнала коллектора.

Коллектор наблюдает за шиной и пишет всё, что передают узлы. Журнал разбирают
потом, иногда через недели, и переснять его нельзя, поэтому ошибка в записи
стоит дороже любой другой.

Тесты закрепляют три вещи: в журнал попадают все величины узла; заголовок
совпадает с данными по числу колонок; при появлении нового узла файл
переписывается без потери и без задвоения строк.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.collector_csv_manager import CollectorCombinedCsvManager, CollectorCsvManager


def _read_rows(path: Path) -> list[list[str]]:
    """Читает журнал целиком, сохраняя порядок строк."""
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.reader(file, delimiter=";"))


def _node_snapshot(node_hex: str, period: int, media: int, fuel_temp: float, board_temp: float) -> dict:
    """Собирает снимок узла так же, как его формирует коллектор."""
    return {
        node_hex: {
            "period": period,
            "fuel": 47.3,
            "fuelJ1939": 47.2,
            "fuelJ1939Known": True,
            "temperature": fuel_temp,
            "boardTemperature": board_temp,
            "boardTemperatureKnown": True,
            "mediaRaw": media,
            "mediaRawKnown": True,
            "fuelPeriodX10": 473,
            "emptyPeriod": 4820,
            "fullPeriod": 9640,
            "emptyKnown": True,
            "fullKnown": True,
        }
    }


def test_node_csv_records_everything_needed_for_calibration(tmp_path: Path):
    """В журнале обязаны быть оба контура и обе температуры."""
    manager = CollectorCsvManager("0x2a", tmp_path)
    manager.append_metric(
        measurement_time="12:00:01.500",
        period_ticks=7100,
        temperature_c=21.3,
        fuel_percent=47.3,
        board_temperature_c=29.8,
        media_ticks=2415,
        fuel_j1939_percent=47.2,
        fuel_from_period_x10=473,
        empty_ticks=4820,
        full_ticks=9640,
        empty_known=True,
        full_known=True,
    )

    rows = _read_rows(tmp_path / "0x2a.csv")
    header = rows[-2]
    data = rows[-1]

    assert header[:5] == [
        "Время", "Период основного контура", "Период контура вида топлива",
        "Температура топлива (°C)", "Температура платы (°C)",
    ]
    assert data[1] == "7100"
    assert data[2] == "2415"
    assert data[3] == "21,3"
    assert data[4] == "29,8"


def test_node_csv_header_matches_data_width(tmp_path: Path):
    """Заголовок и строки данных обязаны иметь одинаковое число колонок."""
    manager = CollectorCsvManager("0x2a", tmp_path)
    manager.append_metric(
        measurement_time="12:00:01.500", period_ticks=7100, temperature_c=21.3,
        fuel_percent=47.3, board_temperature_c=29.8, media_ticks=2415,
        empty_ticks=4820, full_ticks=9640,
        empty_known=True, full_known=True,
    )

    rows = _read_rows(tmp_path / "0x2a.csv")
    widths = {len(row) for row in rows}
    assert len(widths) == 1, f"строки журнала разной ширины: {sorted(widths)}"


def test_missing_values_leave_empty_cells(tmp_path: Path):
    """Пока прибор не ответил, ячейка пустая, а не ноль: ноль спутали бы с измерением."""
    manager = CollectorCsvManager("0x2a", tmp_path)
    manager.append_metric(
        measurement_time="12:00:01.500", period_ticks=7100, temperature_c=21.3,
        fuel_percent=47.3, board_temperature_c=None, media_ticks=None,
        empty_ticks=4820, full_ticks=9640,
        empty_known=True, full_known=True,
    )

    data = _read_rows(tmp_path / "0x2a.csv")[-1]
    assert data[2] == ""
    assert data[4] == ""


def test_combined_csv_keeps_rows_when_new_node_appears(tmp_path: Path):
    """Появление второго узла переписывает файл, и прежние строки терять нельзя."""
    manager = CollectorCombinedCsvManager(tmp_path)
    manager.append_snapshot("12:00:01.5", _node_snapshot("0x2a", 7100, 2415, 21.3, 29.8))

    snapshot = _node_snapshot("0x2a", 7104, 2402, -38.7, -35.1)
    snapshot.update(_node_snapshot("0x2b", 7050, 2390, -38.5, -35.0))
    manager.append_snapshot("12:00:03.5", snapshot)

    rows = _read_rows(tmp_path / "all_nodes.csv")
    times = [row[0] for row in rows if row and row[0].startswith("12:")]
    assert times == ["12:00:01.5", "12:00:03.5"]


def test_combined_csv_does_not_duplicate_header(tmp_path: Path):
    """Строка колонок при перезаписи не должна попасть в файл ещё раз как данные."""
    manager = CollectorCombinedCsvManager(tmp_path)
    manager.append_snapshot("12:00:01.5", _node_snapshot("0x2a", 7100, 2415, 21.3, 29.8))

    snapshot = _node_snapshot("0x2a", 7104, 2402, -38.7, -35.1)
    snapshot.update(_node_snapshot("0x2b", 7050, 2390, -38.5, -35.0))
    manager.append_snapshot("12:00:03.5", snapshot)

    rows = _read_rows(tmp_path / "all_nodes.csv")
    header_rows = [row for row in rows
                   if len(row) > 1 and row[1].strip().casefold() == "период основного контура"]
    assert len(header_rows) == 1, "строка колонок записана больше одного раза"


def test_combined_csv_columns_are_aligned(tmp_path: Path):
    """Заголовки групп и строка калибровки обязаны совпадать по ширине с данными."""
    manager = CollectorCombinedCsvManager(tmp_path)
    snapshot = _node_snapshot("0x2a", 7100, 2415, 21.3, 29.8)
    snapshot.update(_node_snapshot("0x2b", 7050, 2390, 21.1, 29.5))
    manager.append_snapshot("12:00:01.5", snapshot)

    rows = _read_rows(tmp_path / "all_nodes.csv")
    data_width = len([row for row in rows if row and row[0].startswith("12:")][0])
    for row in rows:
        assert len(row) == data_width, f"строка другой ширины: {row[:3]}"
