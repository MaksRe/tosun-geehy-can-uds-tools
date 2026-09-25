"""Модель таблицы окна параметров UDS.

ЗАЧЕМ ОТДЕЛЬНАЯ МОДЕЛЬ
Таблица обновляется часто: при массовом чтении каждая строка меняет состояние
по два-три раза. Если отдавать её в QML простым списком, каждое обновление
пересоздаёт все строки, и прокрутка прыгает в начало. Модель Qt сообщает только
о тех строках, что изменились, поэтому оператор спокойно листает таблицу, пока
она заполняется.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt

# Поля строки таблицы. Порядок задаёт номера ролей.
OPTIONS_TABLE_FIELDS: tuple[str, ...] = (
    "didInt",
    "did",
    "name",
    "group",
    "sizeText",
    "access",
    "canRead",
    "canWrite",
    "hasValue",
    "value",
    "status",
    "statusColor",
    "time",
    "details",
    "note",
)

_FIRST_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class OptionsTableModel(QAbstractListModel):
    """Строки таблицы параметров. Каждая строка - словарь с полями OPTIONS_TABLE_FIELDS."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict[str, object]] = []

    def rowCount(self, parent=QModelIndex()):  # noqa: N802 - имя из Qt
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index, role=int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        field_index = int(role) - _FIRST_ROLE
        if not (0 <= field_index < len(OPTIONS_TABLE_FIELDS)):
            return None
        return self._rows[index.row()].get(OPTIONS_TABLE_FIELDS[field_index])

    def roleNames(self):  # noqa: N802 - имя из Qt
        return {
            _FIRST_ROLE + number: QByteArray(name.encode("ascii"))
            for number, name in enumerate(OPTIONS_TABLE_FIELDS)
        }

    def rows(self) -> list[dict[str, object]]:
        """Текущие строки. Для экспорта и проверок."""
        return list(self._rows)

    def set_rows(self, rows: list[dict[str, object]]):
        """Заменяет строки, по возможности сообщая только об изменившихся.

        Если набор параметров тот же и в том же порядке (обновились значения),
        модель сообщает об изменении отдельных строк, и прокрутка остаётся на
        месте. Если набор другой (сменился фильтр), таблица перестраивается.
        """
        new_rows = [dict(row) for row in rows]
        same_layout = (
            len(new_rows) == len(self._rows)
            and all(new["didInt"] == old["didInt"] for new, old in zip(new_rows, self._rows))
        )

        if not same_layout:
            self.beginResetModel()
            self._rows = new_rows
            self.endResetModel()
            return

        for number, (new, old) in enumerate(zip(new_rows, self._rows)):
            if new != old:
                self._rows[number] = new
                model_index = self.index(number, 0)
                self.dataChanged.emit(model_index, model_index)
