"""Журнал калибровки: CSV со всеми данными узла, которые менялись.

ЗАЧЕМ
Наладка идёт руками и глазами, а разбор потом - по цифрам. Журнал пишет каждое
изменение любого показания прибора, поэтому по нему видно, что именно происходило
в колбе: когда поехал уровень, когда дрогнул контур, в какой момент оператор
записал отметку.

КАК УСТРОЕН ФАЙЛ
Разделитель «точка с запятой», дробная часть через запятую, кодировка UTF-8 -
так же, как в журналах коллектора: файл открывается Excel без настроек. Первая
строка - заголовок с названиями колонок, дальше по строке на каждое изменение.
В колонке «Что изменилось» стоит название показания, из-за которого строка
появилась: по ней видно, кто в этот момент обновился, а кто стоит старым.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

CSV_WRITE_ENCODING = "utf-8"


class CalibrationCsvLog:
    """Пишет строки журнала калибровки в один файл."""

    def __init__(self, directory, columns, *, started_at: datetime | None = None):
        self._columns = tuple(str(column) for column in columns)
        moment = started_at or datetime.now()
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        self._path = folder / ("calibration_" + moment.strftime("%Y%m%d_%H%M%S") + ".csv")
        self._rows = 0

        with self._path.open("w", newline="", encoding=CSV_WRITE_ENCODING) as file:
            csv.writer(file, delimiter=";").writerow(self._columns)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def rows(self) -> int:
        return self._rows

    @property
    def columns(self) -> tuple[str, ...]:
        return self._columns

    def append(self, values):
        """Дописывает строку. Недостающие ячейки остаются пустыми."""
        row = [str(value) for value in values][:len(self._columns)]
        row += [""] * (len(self._columns) - len(row))
        with self._path.open("a", newline="", encoding=CSV_WRITE_ENCODING) as file:
            csv.writer(file, delimiter=";").writerow(row)
        self._rows += 1
