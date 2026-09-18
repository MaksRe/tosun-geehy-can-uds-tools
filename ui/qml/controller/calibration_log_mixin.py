"""Запись журнала калибровки в CSV.

ЗАЧЕМ
Калибровка идёт руками: подняли датчик, долили топливо, записали отметку. Что
именно при этом показывал прибор, потом не вспомнить. Журнал пишет каждое
изменение любого показания узла в один файл, поэтому разбор ведётся по цифрам, а
не по памяти.

КОГДА ПОЯВЛЯЕТСЯ СТРОКА
Когда прибор прислал значение, отличное от прошлого: стоящее на месте число файл
не раздувает. Кроме того, отдельной строкой отмечаются события оператора -
запись отметки, запись опорной точки, снятие тестовой точки, - и по ним в файле
видно, в какой момент что было сделано.

ЧТО ЖУРНАЛ ДЕЛАЕТ С ОПРОСОМ
Пока идёт запись, опрос текущих данных узла не выключается при уходе из своего
раздела: иначе оператор перешёл бы к отметкам, а журнал молча опустел бы.
"""

from __future__ import annotations

import time
from pathlib import Path

from ..calibration_log_csv import CalibrationCsvLog
from ..capacitance import counts_to_pf
from .contract import AppControllerContract
from .eeprom_commit_mixin import decode_eeprom_state

# (ключ, заголовок колонки, множитель, знаков после запятой)
# Ключи те же, что у текущих данных узла, кроме расчётных: они помечены ниже.
CALIBRATION_LOG_COLUMNS = (
    ("level", "Уровень топлива, %", 0.1, 1),
    ("j1939", "Уровень J1939, %", 1.0, 1),
    ("main_raw", "Основной контур, отсч.", 1.0, 0),
    ("main_pf", "Основной контур, пФ", 1.0, 2),
    ("main_comp", "Итоговый период основного, отсч.", 1.0, 0),
    ("media", "Контур вида топлива, отсч.", 1.0, 0),
    ("media_pf", "Контур вида топлива, пФ", 1.0, 2),
    ("fuel_t", "Температура топлива, °C", 0.1, 1),
    ("board_t", "Температура платы, °C", 0.1, 1),
    ("emul", "Эмуляция температуры, °C", 0.1, 1),
    ("rf", "Коэффициент среды", 0.001, 3),
    ("age_main", "Возраст измерения основного, мс", 1.0, 0),
    ("age_media", "Возраст измерения вида топлива, мс", 1.0, 0),
    ("media_state", "Состояние поправки, биты", 1.0, 0),
    ("media_enable", "Поправка включена", 1.0, 0),
    ("rf_rejected", "Отбраковано коэффициентов", 1.0, 0),
    ("empty", "Отметка 0 %, отсч.", 1.0, 0),
    ("full", "Отметка 100 %, отсч.", 1.0, 0),
    ("zero_trim", "Подгонка нуля, отсч.", 1.0, 0),
    ("tank_model", "Модель уровня", 1.0, 0),
    ("main_spread", "Размах серии основного, отсч.", 1.0, 0),
    ("main_overrun", "Перезахваты основного", 1.0, 0),
    ("media_spread", "Размах серии вида топлива, отсч.", 1.0, 0),
    ("media_overrun", "Перезахваты вида топлива", 1.0, 0),
    ("board_stage", "Период после ступени платы, отсч.", 1.0, 0),
    ("stage_mode", "Режим ступеней, биты", 1.0, 0),
    ("profile_status", "Профиль, биты", 1.0, 0),
    ("eeprom_pending", "Память: осталось записать", 1.0, 0),
    ("eeprom_errors", "Память: ошибок с включения", 1.0, 0),
)

# Названия показаний для колонки «Что изменилось».
CALIBRATION_LOG_TITLES = {key: title for key, title, _scale, _digits in CALIBRATION_LOG_COLUMNS}

# Показания, которые приходят не из текущих данных узла, а из других разборщиков.
CALIBRATION_LOG_DERIVED = ("j1939", "main_pf", "media_pf", "age_main", "age_media",
                           "eeprom_pending", "eeprom_errors")


class AppControllerCalibrationLogMixin(AppControllerContract):
    CALIBRATION_LOG_COLOR_OK = "#16a34a"
    CALIBRATION_LOG_COLOR_BAD = "#dc2626"
    CALIBRATION_LOG_COLOR_IDLE = "#64748b"

    def _init_calibration_log_state(self):
        """Готовит журнал калибровки. Вызывается один раз при создании контроллера."""
        self._calibration_log = None
        self._calibration_log_started = 0.0
        self._calibration_log_last: dict = {}
        self._calibration_log_status = "Журнал не пишется."
        self._calibration_log_status_color = self.CALIBRATION_LOG_COLOR_IDLE

    # ------------------------------------------------------------------ включение

    def _calibration_log_directory(self) -> Path:
        """Каталог журналов калибровки рядом с остальными логами программы.

        Если туда писать нельзя (собранная программа лежит в каталоге только для
        чтения), журнал уходит в рабочий каталог: лучше файл не там, чем никакого.
        """
        try:
            folder = Path(self._project_root_directory) / "logs" / "calibration"
            folder.mkdir(parents=True, exist_ok=True)
            return folder
        except Exception:
            folder = Path.cwd() / "logs" / "calibration"
            folder.mkdir(parents=True, exist_ok=True)
            return folder

    def _calibration_log_start(self):
        """Открывает новый файл журнала и включает запись."""
        if self._calibration_log is not None:
            return
        columns = ["Время", "Секунд от начала"]
        columns += [title for _key, title, _scale, _digits in CALIBRATION_LOG_COLUMNS]
        columns.append("Что изменилось")
        try:
            self._calibration_log = CalibrationCsvLog(self._calibration_log_directory(), columns)
        except Exception as error:
            self._calibration_log = None
            self._calibration_log_set_status(
                f"Журнал не открылся: {error}", self.CALIBRATION_LOG_COLOR_BAD)
            return

        self._calibration_log_started = time.monotonic()
        self._calibration_log_last = {}
        self._append_log(f"Журнал калибровки: пишется в {self._calibration_log.path}", "#0f6ab4")
        self._calibration_log_set_status("Журнал пишется.", self.CALIBRATION_LOG_COLOR_OK)
        # Данные узла нужны журналу и тогда, когда открыт другой раздел.
        self._node_live_apply_enabled()
        self._calibration_log_event("начало записи журнала")

    def _calibration_log_stop(self):
        """Закрывает журнал. Файл остаётся на диске со всем, что успело записаться."""
        if self._calibration_log is None:
            return
        self._calibration_log_event("конец записи журнала")
        rows = int(self._calibration_log.rows)
        path = self._calibration_log.path
        self._calibration_log = None
        self._append_log(f"Журнал калибровки закрыт: строк {rows}, файл {path}", "#0f6ab4")
        self._calibration_log_set_status(
            f"Журнал закрыт: строк {rows}. Файл {path.name}", self.CALIBRATION_LOG_COLOR_IDLE)
        self._node_live_apply_enabled()

    def _calibration_log_set_status(self, text: str, color: str):
        self._calibration_log_status = str(text)
        self._calibration_log_status_color = str(color)
        self.calibrationLogChanged.emit()

    @property
    def _calibration_log_recording(self) -> bool:
        return self._calibration_log is not None

    # ------------------------------------------------------------------ сбор строки

    def _calibration_log_value(self, key: str):
        """Значение одного показания для строки журнала, ещё без множителя."""
        if key in CALIBRATION_LOG_DERIVED:
            if key == "j1939":
                return self._node_live_j1939
            if key == "main_pf":
                raw = self._node_live.get("main_raw")
                return None if raw is None else counts_to_pf(raw)
            if key == "media_pf":
                raw = self._node_live.get("media")
                return None if raw is None else counts_to_pf(raw)
            if key == "age_main":
                return self._live_age["main_ms"]
            if key == "age_media":
                return self._live_age["media_ms"]
            state = decode_eeprom_state(self._node_live.get("eeprom"))
            if state is None:
                return None
            return state["pending"] if key == "eeprom_pending" else state["errors"]
        return self._node_live.get(key)

    @staticmethod
    def _calibration_log_cell(value, scale: float, digits: int) -> str:
        """Ячейка журнала: пусто, если числа нет; запятая вместо точки."""
        if value is None:
            return ""
        number = float(value) * float(scale)
        if int(digits) <= 0:
            return str(int(round(number)))
        return f"{number:.{int(digits)}f}".replace(".", ",")

    def _calibration_log_write_row(self, reason: str):
        """Дописывает в журнал строку со всеми текущими значениями."""
        log = self._calibration_log
        if log is None:
            return
        seconds = time.monotonic() - float(self._calibration_log_started)
        row = [time.strftime("%H:%M:%S"), f"{seconds:.1f}".replace(".", ",")]
        for key, _title, scale, digits in CALIBRATION_LOG_COLUMNS:
            row.append(self._calibration_log_cell(self._calibration_log_value(key), scale, digits))
        row.append(str(reason))
        try:
            log.append(row)
        except Exception as error:
            self._calibration_log = None
            self._calibration_log_set_status(
                f"Запись прервана: {error}", self.CALIBRATION_LOG_COLOR_BAD)
            return
        self.calibrationLogChanged.emit()

    def _calibration_log_note(self, key: str):
        """Показание пришло: строка появится, только если оно изменилось."""
        if self._calibration_log is None:
            return
        value = self._calibration_log_value(str(key))
        if value is None:
            return
        if str(key) in self._calibration_log_last and self._calibration_log_last[str(key)] == value:
            return
        self._calibration_log_last[str(key)] = value
        self._calibration_log_write_row(CALIBRATION_LOG_TITLES.get(str(key), str(key)))

    def _calibration_log_event(self, text: str):
        """Действие оператора отдельной строкой: по ней видно, когда что сделано."""
        if self._calibration_log is None:
            return
        self._calibration_log_write_row(str(text))

    # ------------------------------------------------------------------ показ

    def _calibration_log_view(self) -> dict:
        """Состояние журнала для раздела текущих данных узла."""
        log = self._calibration_log
        return {
            "recording": log is not None,
            "rowsText": "строк нет" if log is None else f"строк {int(log.rows)}",
            "fileText": "" if log is None else log.path.name,
            "pathText": "" if log is None else str(log.path),
            "statusText": str(self._calibration_log_status),
            "statusColor": str(self._calibration_log_status_color),
        }
