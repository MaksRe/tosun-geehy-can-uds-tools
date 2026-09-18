"""Проверки журнала калибровки в CSV.

Журнал нужен, чтобы разбирать калибровку по цифрам, а не по памяти. Тесты
закрепляют три вещи, без которых он бесполезен: строка появляется на каждое
изменение и не появляется на повторе того же числа; действия оператора попадают
в файл отдельной строкой; пока журнал пишется, опрос узла не выключается, иначе
в файле окажется дыра ровно на время работы в другом разделе.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller.calibration_log_mixin import (
    CALIBRATION_LOG_COLUMNS,
    AppControllerCalibrationLogMixin,
)


class _Signal:
    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _LogStub(AppControllerCalibrationLogMixin):
    """Журнал без Qt: значения узла подставляются прямо в тесте."""

    def __init__(self, root: Path):
        self.calibrationLogChanged = _Signal()
        self.logs = []
        self.polling_applied = 0
        self._project_root_directory = root
        self._init_calibration_log_state()
        self._node_live = {key: None for key, _title, _scale, _digits in CALIBRATION_LOG_COLUMNS}
        self._node_live.update({"level": None, "main_raw": None, "media": None, "eeprom": None})
        self._node_live_j1939 = None
        self._live_age = {"main_ms": None, "media_ms": None}

    def _append_log(self, text, color):
        self.logs.append(text)

    def _node_live_apply_enabled(self):
        self.polling_applied += 1


def _rows(stub) -> list[list[str]]:
    with stub._calibration_log.path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.reader(file, delimiter=";"))


def _saved_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.reader(file, delimiter=";"))


def _column(rows, title: str) -> int:
    return rows[0].index(title)


# ------------------------------------------------------------------ включение

def test_starting_opens_a_file_with_a_header_and_one_event_row(tmp_path):
    stub = _LogStub(tmp_path)
    stub._calibration_log_start()

    rows = _rows(stub)
    assert rows[0][0] == "Время"
    assert rows[0][-1] == "Что изменилось"
    assert "Уровень топлива, %" in rows[0]
    assert rows[1][-1] == "начало записи журнала"
    assert stub._calibration_log.path.name.startswith("calibration_")
    assert stub._calibration_log.path.suffix == ".csv"
    # Опрос узла обязан включиться сам: иначе журналу нечего писать.
    assert stub.polling_applied >= 1


def test_stopping_closes_the_file_and_reports_the_count(tmp_path):
    stub = _LogStub(tmp_path)
    stub._calibration_log_start()
    path = stub._calibration_log.path
    stub._calibration_log_stop()

    assert stub._calibration_log is None
    assert _saved_rows(path)[-1][-1] == "конец записи журнала"
    assert "строк" in stub._calibration_log_status
    assert stub._calibration_log_view()["recording"] is False


def test_nothing_is_written_while_the_log_is_off(tmp_path):
    stub = _LogStub(tmp_path)
    stub._node_live["main_raw"] = 12130
    stub._calibration_log_note("main_raw")
    stub._calibration_log_event("запись отметки")
    assert stub._calibration_log is None
    assert list(tmp_path.glob("**/*.csv")) == []


# ------------------------------------------------------------------ строки

def test_a_row_appears_only_when_the_value_changed(tmp_path):
    stub = _LogStub(tmp_path)
    stub._calibration_log_start()
    before = len(_rows(stub))

    stub._node_live["main_raw"] = 12130
    stub._calibration_log_note("main_raw")
    stub._calibration_log_note("main_raw")
    assert len(_rows(stub)) == before + 1, "повтор того же числа файл не раздувает"

    stub._node_live["main_raw"] = 12131
    stub._calibration_log_note("main_raw")
    assert len(_rows(stub)) == before + 2


def test_the_row_says_what_changed_and_keeps_the_rest(tmp_path):
    stub = _LogStub(tmp_path)
    stub._calibration_log_start()
    stub._node_live["media"] = 3640
    stub._calibration_log_note("media")
    stub._node_live["level"] = 505
    stub._calibration_log_note("level")

    rows = _rows(stub)
    assert rows[-1][-1] == "Уровень топлива, %"
    # В строке стоят все текущие значения, а не только изменившееся.
    assert rows[-1][_column(rows, "Контур вида топлива, отсч.")] == "3640"
    assert rows[-1][_column(rows, "Уровень топлива, %")] == "50,5"


def test_capacitance_is_written_next_to_the_counts(tmp_path):
    stub = _LogStub(tmp_path)
    stub._calibration_log_start()
    stub._node_live["main_raw"] = 12130
    stub._calibration_log_note("main_raw")

    rows = _rows(stub)
    assert rows[-1][_column(rows, "Основной контур, отсч.")] == "12130"
    assert rows[-1][_column(rows, "Основной контур, пФ")] == "296,55"


def test_operator_actions_get_their_own_row(tmp_path):
    stub = _LogStub(tmp_path)
    stub._calibration_log_start()
    stub._calibration_log_event("записана отметка 100 %: 12130 отсч.")

    assert _rows(stub)[-1][-1] == "записана отметка 100 %: 12130 отсч."


def test_values_the_device_has_not_sent_stay_empty(tmp_path):
    stub = _LogStub(tmp_path)
    stub._calibration_log_start()
    stub._node_live["media"] = 3640
    stub._calibration_log_note("media")

    rows = _rows(stub)
    assert rows[-1][_column(rows, "Температура топлива, °C")] == ""
    # Пустое значение и строки не порождает: писать нечего.
    before = len(rows)
    stub._calibration_log_note("fuel_t")
    assert len(_rows(stub)) == before


def test_j1939_level_reaches_the_log(tmp_path):
    stub = _LogStub(tmp_path)
    stub._calibration_log_start()
    stub._node_live_j1939 = 50.4
    stub._calibration_log_note("j1939")

    rows = _rows(stub)
    assert rows[-1][_column(rows, "Уровень J1939, %")] == "50,4"
