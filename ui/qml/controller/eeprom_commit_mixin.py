"""Контроль сохранения в память прибора.

ЗАЧЕМ
Прибор отвечает «запись выполнена», как только принял значение в оперативную
память. В микросхему памяти оно уходит позже, фоновой задачей. Если питание
пропадёт раньше, после включения значение окажется прежним, хотя программа
показала успех. Чтение параметра сразу после записи этого не ловит: оно
возвращает то, что лежит в оперативной памяти.

ЧТО ДЕЛАЕТ МОДУЛЬ
После любой подтверждённой записи в выбранный прибор, из любого раздела, модуль
читает состояние памяти (параметр 0x0063), пока прибор не запишет всё в
микросхему и не проверит запись чтением из неё. Итог виден в шапке окна
калибровки: «записываю», «всё сохранено» или «не сохранилось».

Заодно модуль сообщает, если при последнем включении прибор нашёл память
повреждённой и сбросил часть параметров к заводским значениям.

КАК НЕ МЕШАЕТ ДРУГИМ
Запросы уходят только когда шину не занимает другой раздел: длинную запись
посторонний запрос обрывает. Пока другой раздел ещё пишет, отсчёт ожидания
не идёт.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer

from uds.data_identifiers import UdsData
from uds.services.read_data_by_id import ServiceReadDataById

from .bus_guard import background_request_recent, note_background_request, uds_exchange_busy
from .contract import AppControllerContract

EEPROM_STATE_DID = 0x0063
EEPROM_FLAG_SPI_ERROR = 0x01
EEPROM_FLAG_VERIFY_ERROR = 0x02
EEPROM_FLAG_BOOT_PARTIAL = 0x04
EEPROM_FLAG_BOOT_DEFAULTS = 0x08

# Эти параметры живут только в оперативной памяти прибора: после их записи ждать нечего.
RAM_ONLY_DIDS = frozenset({0x0061})


def decode_eeprom_state(data) -> dict | None:
    """Раскладывает 4 байта состояния: не записано, флаги, сброшено при включении, ошибки записи."""
    values = [int(item) & 0xFF for item in (data or [])]
    if len(values) < 4:
        return None
    return {"pending": values[0], "flags": values[1], "damaged": values[2], "errors": values[3]}


def eeprom_boot_warning(state: dict | None) -> str:
    """Предупреждение о сбросе памяти при включении прибора или пустая строка."""
    if not state:
        return ""
    if state["flags"] & EEPROM_FLAG_BOOT_DEFAULTS:
        return ("При включении прибор не узнал карту памяти и записал все параметры заводскими значениями. "
                "Калибровку нужно выполнить заново.")
    if state["flags"] & EEPROM_FLAG_BOOT_PARTIAL:
        return (f"При включении прибор нашёл повреждённые параметры и сбросил их к заводским: "
                f"{state['damaged']}. Проверьте калибровку и профиль.")
    return ""


class AppControllerEepromCommitMixin(AppControllerContract):
    EEPROM_COMMIT_POLL_MS = 150
    EEPROM_COMMIT_TIMEOUT_S = 5.0
    EEPROM_COMMIT_ANSWER_TIMEOUT_S = 0.6
    EEPROM_COMMIT_PROBE_LIMIT = 3

    EEPROM_COLOR_IDLE = "#64748b"
    EEPROM_COLOR_RUN = "#0f6ab4"
    EEPROM_COLOR_OK = "#16a34a"
    EEPROM_COLOR_WARN = "#d97706"
    EEPROM_COLOR_FAIL = "#dc2626"

    # ------------------------------------------------------------------ состояние

    def _init_eeprom_commit_state(self):
        """Готовит контроль сохранения. Вызывается один раз при создании контроллера."""
        self._eeprom_commit_read = ServiceReadDataById()
        self._eeprom_commit_read.set_byte_order("big")
        self._eeprom_commit_node = None
        self._eeprom_commit_reset()

        self._eeprom_commit_timer = QTimer(self)
        self._eeprom_commit_timer.setInterval(self.EEPROM_COMMIT_POLL_MS)
        self._eeprom_commit_timer.timeout.connect(self._on_eeprom_commit_tick)
        self._eeprom_commit_timer.start()

    def _eeprom_commit_reset(self):
        """Забывает всё о приборе: после перезапуска или смены прибора состояние чужое."""
        # idle - записей не было, saving - ждём записи в микросхему, saved, failed, unsupported
        self._eeprom_commit_phase = "idle"
        self._eeprom_commit_detail = ""
        self._eeprom_commit_warn = False
        self._eeprom_commit_state: dict | None = None
        self._eeprom_commit_deadline = 0.0
        self._eeprom_commit_errors_before: int | None = None
        self._eeprom_commit_request_s = 0.0
        self._eeprom_commit_probes = 0
        self._eeprom_commit_boot_warned = False

    # ------------------------------------------------------------------ разбор ответов

    def _handle_eeprom_commit_frame(self, identifier: int, payload):
        """Замечает подтверждённые записи и ответы с состоянием памяти, кто бы их ни запросил."""
        if not isinstance(payload, (list, tuple)) or len(payload) < 4:
            return
        if not self._is_calibration_response_identifier(identifier):
            return
        if ((int(payload[0]) >> 4) & 0x0F) != 0x00:
            return
        length = int(payload[0]) & 0x0F
        if length < 2 or length > (len(payload) - 1):
            return
        body = [int(value) & 0xFF for value in payload[1:1 + length]]

        if body[0] == 0x51:
            # Прибор перезапускается: признаки прошлого включения больше не действуют.
            self._eeprom_commit_reset()
            self.eepromCommitChanged.emit()
            return

        if len(body) < 3:
            return
        did = (body[1] << 8) | body[2]

        if body[0] == 0x6E:
            if did not in RAM_ONLY_DIDS:
                self._eeprom_commit_on_write()
            return

        if body[0] == 0x62 and did == EEPROM_STATE_DID:
            self._eeprom_commit_on_state(body[3:])
            return

        # Отказ чтения сразу после нашего запроса: в прошивке нет состояния памяти.
        if body[0] == 0x7F and body[1] == 0x22 and body[2] == 0x31 and self._eeprom_commit_request_s > 0.0:
            if time.monotonic() - self._eeprom_commit_request_s <= self.EEPROM_COMMIT_ANSWER_TIMEOUT_S:
                self._eeprom_commit_on_unsupported()

    def _eeprom_commit_on_write(self):
        """Прибор подтвердил запись: ждём, пока он запишет её в микросхему."""
        if self._eeprom_commit_phase == "unsupported":
            return
        if self._eeprom_commit_phase != "saving" and self._eeprom_commit_state is not None:
            self._eeprom_commit_errors_before = int(self._eeprom_commit_state["errors"])
        self._eeprom_commit_phase = "saving"
        self._eeprom_commit_warn = False
        self._eeprom_commit_deadline = time.monotonic() + self.EEPROM_COMMIT_TIMEOUT_S
        self._eeprom_commit_detail = "Прибор принял запись, жду, пока он запишет её в память..."
        self.eepromCommitChanged.emit()

    def _eeprom_commit_on_state(self, data):
        self._eeprom_commit_request_s = 0.0
        state = decode_eeprom_state(data)
        if state is None:
            return
        self._eeprom_commit_state = state
        self._eeprom_commit_probes = 0

        warning = eeprom_boot_warning(state)
        if warning and not self._eeprom_commit_boot_warned:
            self._eeprom_commit_boot_warned = True
            self.infoMessage.emit("Память прибора", warning)

        if self._eeprom_commit_phase != "saving":
            if self._eeprom_commit_errors_before is None:
                self._eeprom_commit_errors_before = int(state["errors"])
            self.eepromCommitChanged.emit()
            return

        if state["flags"] & EEPROM_FLAG_SPI_ERROR:
            self._eeprom_commit_finish(
                "failed",
                "Микросхема памяти прибора не отвечает: записанное пропадёт при выключении. "
                "Не отключайте прибор и повторите запись.")
            return

        if state["pending"] > 0:
            self._eeprom_commit_detail = f"Записываю в память прибора, осталось параметров: {state['pending']}..."
            self.eepromCommitChanged.emit()
            return

        baseline = self._eeprom_commit_errors_before
        extra = int(state["errors"]) - int(baseline) if baseline is not None else 0
        if extra > 0:
            self._eeprom_commit_finish(
                "saved",
                f"Сохранено в памяти прибора, но микросхема подтвердила запись не с первого раза "
                f"(повторов: {extra}). Проверьте питание платы.",
                warn=True)
        else:
            self._eeprom_commit_finish(
                "saved", "Всё записанное сохранено в памяти прибора и проверено чтением из неё.")
        self._eeprom_commit_errors_before = int(state["errors"])

    def _eeprom_commit_on_unsupported(self):
        self._eeprom_commit_request_s = 0.0
        self._eeprom_commit_finish(
            "unsupported",
            "Прошивка прибора не сообщает о записи в память (нет параметра 0x0063): "
            "сохранение подтверждается только перезагрузкой прибора.",
            warn=True)

    def _eeprom_commit_finish(self, phase: str, detail: str, warn: bool = False):
        self._eeprom_commit_phase = phase
        self._eeprom_commit_detail = detail
        self._eeprom_commit_warn = bool(warn)
        self.eepromCommitChanged.emit()

    # ------------------------------------------------------------------ опрос

    def _eeprom_commit_bus_busy(self) -> bool:
        """Занята ли шина другим разделом: посторонний запрос затёр бы его обмен."""
        return bool(uds_exchange_busy(self, ignore=("eeprom_commit",))) or background_request_recent(self)

    def _on_eeprom_commit_tick(self):
        now = time.monotonic()

        node = int(self._resolve_calibration_target_sa()) & 0xFF
        if node != self._eeprom_commit_node:
            self._eeprom_commit_node = node
            self._eeprom_commit_reset()
            self.eepromCommitChanged.emit()

        if self._eeprom_commit_request_s > 0.0 and now - self._eeprom_commit_request_s > self.EEPROM_COMMIT_ANSWER_TIMEOUT_S:
            self._eeprom_commit_request_s = 0.0

        probe = (self._eeprom_commit_phase == "idle" and self._eeprom_commit_state is None
                 and self._eeprom_commit_probes < self.EEPROM_COMMIT_PROBE_LIMIT
                 and bool(self._calibration_active) and bool(self._calibration_session_ready))
        if self._eeprom_commit_phase != "saving" and not probe:
            return

        if self._eeprom_commit_bus_busy():
            if self._eeprom_commit_phase == "saving":
                self._eeprom_commit_deadline = max(self._eeprom_commit_deadline, now + self.EEPROM_COMMIT_TIMEOUT_S)
            return

        if self._eeprom_commit_phase == "saving" and now > self._eeprom_commit_deadline:
            left = self._eeprom_commit_state["pending"] if self._eeprom_commit_state else None
            self._eeprom_commit_finish(
                "failed",
                f"За {self.EEPROM_COMMIT_TIMEOUT_S:.0f} с прибор не подтвердил запись в память"
                + (f": не записано параметров {left}" if left else "")
                + ". Не отключайте прибор, повторите запись и проверьте её перезагрузкой.")
            return

        if self._eeprom_commit_request_s > 0.0:
            return
        if not self._can.is_connect or not self._can.is_trace:
            return

        try:
            sent = self._eeprom_commit_read.read_data_by_identifier(
                self._build_calibration_tx_identifier(), UdsData.eeprom_state)
        except Exception:
            sent = False
        if sent:
            self._eeprom_commit_request_s = now
            note_background_request(self)
            if probe:
                self._eeprom_commit_probes += 1

    # ------------------------------------------------------------------ показ

    def _eeprom_commit_view(self) -> dict:
        """Подпись и цвет для шапки окна калибровки."""
        warning = eeprom_boot_warning(self._eeprom_commit_state)
        phase = self._eeprom_commit_phase

        if phase == "saving":
            text, color = self._eeprom_commit_detail, self.EEPROM_COLOR_RUN
        elif phase == "saved":
            text = self._eeprom_commit_detail
            color = self.EEPROM_COLOR_WARN if self._eeprom_commit_warn else self.EEPROM_COLOR_OK
        elif phase == "failed":
            text, color = self._eeprom_commit_detail, self.EEPROM_COLOR_FAIL
        elif phase == "unsupported":
            text, color = self._eeprom_commit_detail, self.EEPROM_COLOR_WARN
        elif self._eeprom_commit_state is not None:
            text, color = ("Память прибора в порядке, после его включения программа в неё не записывала.",
                           self.EEPROM_COLOR_IDLE)
        else:
            text, color = "Память прибора: состояние появится после запуска калибровки.", self.EEPROM_COLOR_IDLE

        if warning:
            text, color = warning + " " + text, self.EEPROM_COLOR_FAIL
        return {"text": text, "color": color, "phase": phase}
