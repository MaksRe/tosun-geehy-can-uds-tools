from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path

from PySide6.QtCore import QTimer, Slot
from PySide6.QtGui import QColor

from colors import RowColor
from uds.data_identifiers import UdsData
from uds.options_catalog import get_option_by_index
from uds.services.session import Session
from uds.uds_identifiers import UdsIdentifiers
from ui.qml.collector_csv_manager import CollectorCombinedCsvManager

from .contract import AppControllerContract
from .workers import UdsOptionProxy

LOGGER = logging.getLogger(__name__)

class AppControllerPublicSlotsMixin(AppControllerContract):
    @staticmethod
    def _service_session_value_for_index(index: int) -> int:
        if int(index) == 1:
            return int(Session.PROGRAMMING)
        if int(index) == 2:
            return int(Session.EXTENDED)
        return int(Session.DEFAULT)

    @staticmethod
    def _service_session_index_for_value(value: int) -> int:
        session_value = int(value) & 0xFF
        if session_value == int(Session.PROGRAMMING):
            return 1
        if session_value == int(Session.EXTENDED):
            return 2
        return 0

    def _reset_service_access_state(self, status_text: str | None = None):
        if self._service_access_timeout_timer.isActive():
            self._service_access_timeout_timer.stop()
        self._service_access_busy = False
        self._service_access_pending_action = ""
        self._service_access_target_sa = None
        self._service_security_unlocked = False
        if status_text is not None:
            self._service_access_status = str(status_text)
        self.serviceAccessChanged.emit()

    def _on_service_access_timeout(self):
        if not self._service_access_busy:
            return
        pending_action = str(self._service_access_pending_action or "")
        if pending_action == "session":
            message = "Таймаут ожидания ответа на Session Control 0x10."
        elif pending_action == "security_seed":
            message = "Таймаут ожидания seed на Security Access 0x27."
        else:
            message = "Таймаут ожидания подтверждения key на Security Access 0x27."
        self._reset_service_access_state(message)
        self._append_log(message, RowColor.red)

    def _resolve_source_address_operation_target_sa(self) -> int:
        # Keep SA read/write on the same node where 0x10/0x27 is active.
        if self._service_security_unlocked and self._service_access_target_sa is not None:
            return int(self._service_access_target_sa) & 0xFF
        return int(self._resolve_options_target_sa()) & 0xFF

    @Slot(int)
    def setSelectedServiceSessionIndex(self, index):
        try:
            parsed = int(index)
        except (TypeError, ValueError):
            return

        if parsed < 0 or parsed >= len(self._service_session_items):
            return

        if parsed == self._selected_service_session_index:
            return

        self._selected_service_session_index = parsed
        self.serviceAccessChanged.emit()

    @Slot()
    def applySelectedServiceSession(self):
        if self._service_access_busy:
            return

        if self._programming_active or self._options_busy or self._options_bulk_busy or self._source_address_busy or self._calibration_active:
            self.infoMessage.emit("Дополнительные настройки", "Завершите активную UDS операцию перед сменой сессии.")
            return

        if not self._can.is_connect or not self._can.is_trace:
            self.infoMessage.emit("Дополнительные настройки", "Сначала подключите адаптер и запустите трассировку CAN.")
            return

        session_value = self._service_session_value_for_index(self._selected_service_session_index)
        target_sa = self._resolve_options_target_sa()
        tx_identifier = self._build_options_tx_identifier(target_sa)

        self._service_access_busy = True
        self._service_access_pending_action = "session"
        self._service_access_target_sa = int(target_sa) & 0xFF
        self._service_security_unlocked = False
        self._service_access_status = f"Запрос Session 0x{int(session_value) & 0xFF:02X} для SA 0x{int(target_sa) & 0xFF:02X}..."
        self.serviceAccessChanged.emit()
        self._append_log(
            f"UDS Session: запрос 0x10 0x{int(session_value) & 0xFF:02X} для узла 0x{int(target_sa) & 0xFF:02X}.",
            RowColor.blue,
        )
        self._service_session_service.set(Session(session_value), tx_identifier)
        self._service_access_timeout_timer.start()

    @Slot()
    def requestSecurityAccess(self):
        if self._service_access_busy:
            return

        if self._programming_active or self._options_busy or self._options_bulk_busy or self._source_address_busy or self._calibration_active:
            self.infoMessage.emit("Дополнительные настройки", "Завершите активную UDS операцию перед Security Access.")
            return

        if not self._can.is_connect or not self._can.is_trace:
            self.infoMessage.emit("Дополнительные настройки", "Сначала подключите адаптер и запустите трассировку CAN.")
            return

        target_sa = self._resolve_options_target_sa()
        tx_identifier = self._build_options_tx_identifier(target_sa)

        self._service_access_busy = True
        self._service_access_pending_action = "security_seed"
        self._service_access_target_sa = int(target_sa) & 0xFF
        self._service_security_unlocked = False
        self._service_access_status = f"Запрос seed 0x27 для SA 0x{int(target_sa) & 0xFF:02X}..."
        self.serviceAccessChanged.emit()
        self._append_log(
            f"Security Access: запрос seed для узла 0x{int(target_sa) & 0xFF:02X}.",
            RowColor.blue,
        )
        self._service_security_access_service.request_seed(tx_identifier)
        self._service_access_timeout_timer.start()

    @Slot(bool)
    def setDebugEnabled(self, enabled):
        value = bool(enabled)
        if self._debug_enabled == value:
            return
        self._debug_enabled = value
        self.debugEnabledChanged.emit()
        self.infoMessage.emit("Отладка", "Режим отладки включен." if value else "Режим отладки отключен.")

    @Slot(bool)
    def setCanJournalEnabled(self, enabled):
        value = bool(enabled)
        if self._can_journal_enabled == value:
            return
        self._can_journal_enabled = value
        self.canJournalEnabledChanged.emit()

    @Slot(bool)
    def setAutoDetectEnabled(self, enabled):
        value = bool(enabled)
        if self._auto_detect_enabled == value:
            return
        self._auto_detect_enabled = value
        self.autoDetectEnabledChanged.emit()

    @Slot(bool)
    def setCollectorEnabled(self, enabled):
        value = bool(enabled)
        if bool(self._collector_enabled) == value:
            return

        self._set_collector_enabled_state(value)
        if value:
            self._append_log("Коллектор: сценарий включен.", RowColor.green)
        else:
            self._append_log("Коллектор: сценарий отключен.", RowColor.yellow)

    @Slot(bool)
    def setCollectorTrendEnabled(self, enabled):
        value = bool(enabled)
        if bool(self._collector_trend_enabled) == value:
            return
        self._collector_trend_enabled = value
        self.collectorTrendEnabledChanged.emit()
        if not value:
            self._reset_collector_trend()

    @Slot(bool)
    def setAutoResetBeforeProgramming(self, enabled):
        value = bool(enabled)
        if self._auto_reset_before_programming == value:
            return
        self._auto_reset_before_programming = value
        self.autoResetBeforeProgrammingChanged.emit()
        state_text = "включен" if value else "отключен"
        self._append_log(f"Автосброс перед программированием: {state_text}", QColor("#0ea5e9"))

    @Slot(int)
    def setTransferByteOrderIndex(self, index):
        try:
            parsed_index = int(index)
        except (TypeError, ValueError):
            parsed_index = 0

        new_index = 1 if parsed_index == 1 else 0
        if self._transfer_byte_order_index == new_index:
            return

        self._transfer_byte_order_index = new_index
        self.transferByteOrderIndexChanged.emit()

        byte_order = "little" if new_index == 1 else "big"
        self._bootloader.set_transfer_byte_order(byte_order)
        self._calibration_read_service.set_byte_order(byte_order)
        self._calibration_write_service.set_byte_order(byte_order)
        self._collector_read_service.set_byte_order(byte_order)
        self._options_read_service.set_byte_order(byte_order)
        self._options_write_service.set_byte_order(byte_order)

        label = "Little Endian" if new_index == 1 else "Big Endian"
        self._append_log(f"Выбран порядок байтов: {label}", QColor("#0ea5e9"))
        self.infoMessage.emit("Протокол", f"Выбран порядок байтов: {label}.")

    @Slot(int)
    def setSelectedCalibrationNodeIndex(self, index):
        try:
            parsed_index = int(index)
        except (TypeError, ValueError):
            return

        if parsed_index < 0 or parsed_index >= len(self._calibration_node_values):
            return

        if self._selected_calibration_node_index == parsed_index:
            return

        self._selected_calibration_node_index = parsed_index
        target_value = self._calibration_node_values[parsed_index]
        self._calibration_target_node_sa = None if target_value is None else int(target_value) & 0xFF
        self.calibrationNodeSelectionChanged.emit()

        if self._calibration_target_node_sa is None:
            self._append_log("Калибровка: выбран целевой узел Авто (по текущим UDS ID).", RowColor.blue)
        else:
            self._append_log(f"Калибровка: выбран целевой узел 0x{self._calibration_target_node_sa:02X}.", RowColor.blue)

    @Slot()
    def toggleCalibration(self):
        if self._calibration_active:
            self.stopCalibration()
            return
        self.startCalibration()

    @Slot()
    def startCalibration(self):
        if self._calibration_active or self._calibration_waiting_session:
            return

        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return

        if not self._can.is_trace:
            self.infoMessage.emit("Калибровка", "Сначала включите трассировку CAN.")
            return

        if self._programming_active:
            self.infoMessage.emit("Калибровка", "Дождитесь завершения операции программирования.")
            return

        self._configure_calibration_uds_services()
        calibration_target_sa = self._resolve_calibration_target_sa()
        if self._service_security_unlocked and self._service_access_target_sa is not None:
            access_target_sa = int(self._service_access_target_sa) & 0xFF
            if access_target_sa != calibration_target_sa:
                self._append_log(
                    (
                        f"Калибровка: текущий Security Access открыт для узла 0x{access_target_sa:02X}; "
                        f"для записи в узел 0x{calibration_target_sa:02X} потребуется отдельный 0x27."
                    ),
                    RowColor.yellow,
                )

        self._calibration_active = True
        self.calibrationStateChanged.emit()
        self._reset_calibration_wizard_state()
        self._reset_calibration_sequence_state()
        self._calibration_level_0_known = False
        self._calibration_level_100_known = False
        self._calibration_waiting_session = True
        self._start_calibration_sequence_wait("activate_session")
        self._calibration_session_service.set(Session.EXTENDED, self._build_calibration_tx_identifier())
        self._append_log(f"Калибровка: запрос расширенной сессии UDS ({self.calibrationSelectedNodeText}).", RowColor.blue)

    @Slot()
    def stopCalibration(self):
        if not self._calibration_active and not self._calibration_waiting_session:
            return

        self._calibration_active = False
        self.calibrationStateChanged.emit()
        self._stop_calibration_poll_timer()
        self._reset_calibration_sequence_state()
        self.calibrationVerificationChanged.emit()

        if not self._can.is_connect or not self._can.is_trace:
            self._finish_calibration_deactivation("Калибровка остановлена. Security Access локально закрыт.")
            return

        self._calibration_waiting_session = True
        self._start_calibration_sequence_wait("deactivate_session")
        self._calibration_session_service.set(Session.DEFAULT, self._build_calibration_tx_identifier())
        self._append_log("Калибровка: возврат в default-сессию UDS.", RowColor.blue)
        self._recompute_calibration_wizard_state()

    @Slot()
    def readCalibrationCurrentLevel(self):
        if not self._can.is_connect or not self._can.is_trace:
            return
        self._configure_calibration_uds_services()
        self._calibration_read_service.read_data_by_identifier(self._build_calibration_tx_identifier(), UdsData.curr_fuel_tank)

    @Slot()
    def readCalibrationLevel0(self):
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return
        if not self._can.is_trace:
            self.infoMessage.emit("Калибровка", "Сначала включите трассировку CAN.")
            return
        self._configure_calibration_uds_services()
        self._calibration_read_service.read_data_by_identifier(self._build_calibration_tx_identifier(), UdsData.empty_fuel_tank)
        self._append_log("Калибровка: чтение уровня 0%.", RowColor.blue)

    @Slot()
    def readCalibrationLevel100(self):
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return
        if not self._can.is_trace:
            self.infoMessage.emit("Калибровка", "Сначала включите трассировку CAN.")
            return
        self._configure_calibration_uds_services()
        self._calibration_read_service.read_data_by_identifier(self._build_calibration_tx_identifier(), UdsData.full_fuel_tank)
        self._append_log("Калибровка: чтение уровня 100%.", RowColor.blue)

    @Slot(str)
    def saveCalibrationLevel0(self, value_text):
        if not self._ensure_calibration_write_ready("запись уровня 0%"):
            return
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return
        try:
            value = self._resolve_calibration_write_value(value_text, self._calibration_current_level)
        except ValueError as exc:
            self.infoMessage.emit("Калибровка", str(exc))
            return

        if self._calibration_write_service.write_data(
            UdsData.empty_fuel_tank,
            value,
            tx_identifier=self._build_calibration_tx_identifier(),
        ):
            self._calibration_write_verify_pending[int(UdsData.empty_fuel_tank.pid)] = int(value)
            self._calibration_level0_written = True
            self._calibration_verify0_ok = False
            self.calibrationVerificationChanged.emit()
            self._recompute_calibration_wizard_state()
            self._append_log(f"Калибровка: запись уровня 0% = {value}.", RowColor.blue)

    @Slot(str)
    def saveCalibrationLevel100(self, value_text):
        if not self._ensure_calibration_write_ready("запись уровня 100%"):
            return
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return
        try:
            value = self._resolve_calibration_write_value(value_text, self._calibration_current_level)
        except ValueError as exc:
            self.infoMessage.emit("Калибровка", str(exc))
            return

        if self._calibration_write_service.write_data(
            UdsData.full_fuel_tank,
            value,
            tx_identifier=self._build_calibration_tx_identifier(),
        ):
            self._calibration_write_verify_pending[int(UdsData.full_fuel_tank.pid)] = int(value)
            self._calibration_level100_written = True
            self._calibration_verify100_ok = False
            self.calibrationVerificationChanged.emit()
            self._recompute_calibration_wizard_state()
            self._append_log(f"Калибровка: запись уровня 100% = {value}.", RowColor.blue)

    @Slot()
    def captureStableCalibrationValue(self):
        captured, sample_count = self._recompute_calibration_stable_capture()
        if captured is None:
            self.infoMessage.emit("Калибровка", "Недостаточно данных для стабильного захвата. Подождите обновление уровня.")
            return

        self._append_log(f"Калибровка: стабильный захват = {captured} (по {sample_count} точкам).", RowColor.green)

    @Slot()
    def createCalibrationBackup(self):
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return

        self._calibration_backup_pending = True
        self._calibration_backup_values_pending = {}
        self._calibration_read_service.read_data_by_identifier(self._build_calibration_tx_identifier(), UdsData.empty_fuel_tank)
        self._calibration_read_service.read_data_by_identifier(self._build_calibration_tx_identifier(), UdsData.full_fuel_tank)
        self._append_log("Калибровка: чтение значений для резервной копии.", RowColor.blue)

    @Slot()
    def restoreCalibrationBackup(self):
        if not self._calibration_backup_available:
            self.infoMessage.emit("Калибровка", "Резервная копия еще не создана.")
            return

        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return

        backup0 = int(self._calibration_backup_level_0)
        backup100 = int(self._calibration_backup_level_100)

        self._calibration_restore_active = True
        self._calibration_restore_queue = [
            (int(UdsData.empty_fuel_tank.pid), backup0),
            (int(UdsData.full_fuel_tank.pid), backup100),
        ]
        self._calibration_restore_current_did = None
        self._append_log("Калибровка: запуск восстановления из резервной копии.", RowColor.blue)
        self._send_next_calibration_restore_write()

    @Slot(str)
    def setCalibrationPollingIntervalMs(self, interval_value):
        raw_text = str(interval_value).strip()
        try:
            parsed = int(raw_text, 10)
        except ValueError:
            self.infoMessage.emit("Калибровка", "Интервал опроса должен быть целым числом в миллисекундах.")
            return

        bounded = max(100, min(parsed, 10000))
        if bounded != parsed:
            self.infoMessage.emit("Калибровка", "Интервал опроса ограничен диапазоном 100..10000 мс.")

        if self._calibration_poll_interval_ms == bounded:
            return

        self._calibration_poll_interval_ms = bounded
        self._calibration_poll_timer.setInterval(self._calibration_poll_interval_ms)
        self.calibrationPollingIntervalChanged.emit()
        self._append_log(f"Калибровка: интервал опроса {bounded} мс.", RowColor.blue)

    @Slot(str)
    def setSourceAddressText(self, text):
        value = str(text).strip()
        if self._source_address_text == value:
            return
        self._source_address_text = value
        self.sourceAddressTextChanged.emit()

    @Slot(str)
    def applySourceAddress(self, text):
        if self._source_address_busy:
            self.infoMessage.emit("Протокол", "Изменение Source Address уже выполняется.")
            return

        if self._programming_active:
            self.infoMessage.emit("Протокол", "Нельзя менять Source Address во время программирования.")
            return

        try:
            source_address = self._parse_source_address(text)
        except ValueError:
            self.infoMessage.emit("Протокол", "Некорректный Source Address. Допустимо 0..255 или 0x00..0xFF.")
            return

        target_sa = self._resolve_source_address_operation_target_sa()
        if (int(UdsIdentifiers.rx.src) & 0xFF) != target_sa:
            UdsIdentifiers.set_src(target_sa)
            self._append_log(
                f"Source Address write target synchronized to node SA 0x{target_sa:02X}.",
                RowColor.blue,
            )

        self._set_source_address_operation("write")
        self._set_source_address_busy(True)
        if not self._bootloader.write_can_source_address(source_address):
            self._set_source_address_busy(False)
            self.infoMessage.emit("Протокол", "Не удалось отправить запрос на изменение Source Address.")
            return

        self._source_address_text = f"0x{source_address:02X}"
        self.sourceAddressTextChanged.emit()

    @Slot()
    def readSourceAddress(self):
        if self._source_address_busy:
            self.infoMessage.emit("Протокол", "Операция с Source Address уже выполняется.")
            return

        if self._programming_active:
            self.infoMessage.emit("Протокол", "Нельзя читать Source Address во время программирования.")
            return

        target_sa = self._resolve_source_address_operation_target_sa()
        if (int(UdsIdentifiers.rx.src) & 0xFF) != target_sa:
            UdsIdentifiers.set_src(target_sa)
            self._append_log(
                f"Source Address read target synchronized to node SA 0x{target_sa:02X}.",
                RowColor.blue,
            )

        self._set_source_address_operation("read")
        self._set_source_address_busy(True)
        if not self._bootloader.read_can_source_address():
            self._set_source_address_busy(False)
            self.infoMessage.emit("Протокол", "Не удалось отправить запрос на чтение Source Address.")

    @Slot(int)
    def setSelectedOptionsParameterIndex(self, index):
        try:
            parsed = int(index)
        except (TypeError, ValueError):
            return

        if parsed < 0 or parsed >= len(self._options_parameters):
            return

        if parsed == self._selected_option_index:
            return

        self._selected_option_index = parsed
        self._refresh_options_selection(emit_signal=True)

    @Slot(int)
    def setSelectedOptionsTargetNodeIndex(self, index):
        try:
            parsed = int(index)
        except (TypeError, ValueError):
            return

        if parsed < 0 or parsed >= len(self._options_target_node_values):
            return

        if parsed == self._selected_options_target_node_index:
            return

        self._selected_options_target_node_index = parsed
        selected_value = self._options_target_node_values[parsed]
        self._options_target_node_sa = None if selected_value is None else int(selected_value) & 0xFF
        self.optionsTargetNodeChanged.emit()
        self._reset_service_access_state("Целевой узел изменен. При необходимости заново установите Session и Security Access.")

        if self._options_target_node_sa is None:
            self._append_log("Параметры UDS: выбран целевой узел Авто (по UDS RX ID).", RowColor.blue)
        else:
            self._append_log(f"Параметры UDS: выбран целевой узел 0x{self._options_target_node_sa:02X}.", RowColor.blue)

    @Slot()
    def readSelectedOption(self):
        if self._options_busy:
            self.infoMessage.emit("UDS Options", "Operation is already in progress. Please wait.")
            return

        if self._programming_active:
            self.infoMessage.emit("Параметры UDS", "Завершите активную операцию перед чтением DID.")
            return

        if self._options_bulk_busy:
            self.infoMessage.emit("UDS Options", "Bulk DID read is running. Stop it before manual read.")
            return

        if not self._can.is_connect or not self._can.is_trace:
            self.infoMessage.emit("UDS Options", "Connect adapter and start CAN trace first.")
            return

        parameter = get_option_by_index(self._selected_option_index)
        if parameter is None:
            return

        if not parameter.can_read:
            self.infoMessage.emit("UDS Options", "Read is not allowed for selected DID.")
            return

        if not self._start_options_read_request(parameter, request_origin="single", append_history=True):
            self.infoMessage.emit("UDS Options", "Failed to send DID read request.")

    @Slot(str)
    def writeSelectedOption(self, value_text):
        if self._options_busy:
            self.infoMessage.emit("Параметры UDS", "Операция уже выполняется. Подождите завершения.")
            return

        if self._programming_active:
            self.infoMessage.emit("Параметры UDS", "Завершите активную операцию перед записью DID.")
            return

        if not self._can.is_connect or not self._can.is_trace:
            self.infoMessage.emit("Параметры UDS", "Сначала подключите адаптер и запустите трассировку CAN.")
            return

        parameter = get_option_by_index(self._selected_option_index)
        if parameter is None:
            return

        if not parameter.can_write:
            self.infoMessage.emit("Параметры UDS", "Для выбранного параметра запись недоступна.")
            return

        try:
            write_value = self._parse_option_write_value(parameter, value_text)
        except ValueError as exc:
            self.infoMessage.emit("Параметры UDS", str(exc))
            return

        if parameter.size > 4:
            self.infoMessage.emit("Параметры UDS", "Запись DID размером более 4 байт в этой версии не поддерживается.")
            return

        target_sa = self._resolve_options_target_sa()
        tx_identifier = self._build_options_tx_identifier(target_sa)

        self._options_pending_action = "write"
        self._options_pending_did = int(parameter.did)
        self._options_pending_target_sa = int(target_sa) & 0xFF
        self._options_pending_write_bytes = self._encode_option_value_bytes(write_value, int(parameter.size))
        self._options_busy = True
        self._options_status = f"Запись DID 0x{int(parameter.did):04X} (SA 0x{int(target_sa) & 0xFF:02X})..."
        self.optionOperationChanged.emit()

        proxy_var = UdsOptionProxy(parameter.did, parameter.size, parameter.name)
        if not self._options_write_service.write_data(proxy_var, write_value, tx_identifier=tx_identifier):
            self._options_busy = False
            self._options_pending_action = ""
            self._options_pending_did = None
            self._options_pending_target_sa = None
            self._options_pending_write_bytes = b""
            self._options_status = "Ошибка отправки запроса записи"
            self.optionOperationChanged.emit()
            self.infoMessage.emit("Параметры UDS", "Не удалось отправить запрос записи DID.")
            return

        self._append_option_history(
            "Запись",
            parameter,
            "Отправлено",
            f"SA 0x{int(target_sa) & 0xFF:02X} | значение: {write_value}",
            "#0ea5e9",
            value_bytes=self._options_pending_write_bytes,
        )
        self._options_timeout_timer.start(4000)

    @Slot()
    def clearOptionHistory(self):
        self._options_history = []
        self._options_history_next_id = 1
        self.optionHistoryChanged.emit()

    @Slot()
    def refreshUdsIdentifiers(self):
        self._refresh_uds_identifier_texts()
        if len(self._observed_candidate_values) > 0:
            self._rebuild_observed_candidate_list()

    @Slot()
    def applyObservedUdsIdentifiers(self):
        if self._programming_active:
            self.infoMessage.emit("Протокол", "Нельзя менять UDS идентификаторы во время программирования.")
            return

        if self._source_address_busy:
            self.infoMessage.emit("Протокол", "Подождите завершения операции Source Address.")
            return

        if not (0 <= self._observed_candidate_index < len(self._observed_candidate_values)):
            self.infoMessage.emit("Протокол", "Нет кандидатов из RX J1939 потока для автоопределения адреса.")
            return

        device_sa = int(self._observed_candidate_values[self._observed_candidate_index]) & 0xFF
        node = self._observed_node_stats.get(device_sa, {})
        tester_sa, _ = self._choose_tester_sa_for_node(node, int(UdsIdentifiers.tx.src) & 0xFF)
        tester_sa = int(tester_sa) & 0xFF

        UdsIdentifiers.tx.src = tester_sa
        UdsIdentifiers.tx.dst = device_sa
        UdsIdentifiers.rx.src = device_sa
        UdsIdentifiers.rx.dst = tester_sa

        self._source_address_text = f"0x{UdsIdentifiers.rx.src:02X}"
        self.sourceAddressTextChanged.emit()
        self._refresh_uds_identifier_texts()

        self.infoMessage.emit(
            "Протокол",
            (
                f"Идентификаторы обновлены из RX потока: "
                f"SA устройства=0x{device_sa:02X}, SA тестера=0x{tester_sa:02X}."
            ),
        )

    @Slot()
    def resetObservedUdsCandidate(self):
        self._reset_observed_uds_candidate()

    @Slot(int)
    def setSelectedObservedUdsCandidateIndex(self, index):
        try:
            new_index = int(index)
        except (TypeError, ValueError):
            return

        if new_index < 0 or new_index >= len(self._observed_candidate_values):
            return

        if self._observed_candidate_index == new_index:
            return

        self._observed_candidate_index = new_index
        self._update_observed_candidate_text()
        self.observedUdsCandidateChanged.emit()

    @Slot(str, str, str, str, str, str, str, str)
    def applyUdsIdentifiers(self, tx_priority, tx_pgn, tx_src, tx_dst, rx_priority, rx_pgn, rx_src, rx_dst):
        if self._programming_active:
            self.infoMessage.emit("Протокол", "Нельзя менять UDS идентификаторы во время программирования.")
            return

        if self._source_address_busy:
            self.infoMessage.emit("Протокол", "Подождите завершения операции Source Address.")
            return

        try:
            tx_priority_value = self._parse_uint_field(tx_priority, 0, 0x7, "TX Priority")
            tx_pgn_value = self._parse_uint_field(tx_pgn, 0, 0xFFFF, "TX PGN")
            tx_src_value = self._parse_uint_field(tx_src, 0, 0xFF, "TX Source")
            tx_dst_value = self._parse_uint_field(tx_dst, 0, 0xFF, "TX Destination")

            rx_priority_value = self._parse_uint_field(rx_priority, 0, 0x7, "RX Priority")
            rx_pgn_value = self._parse_uint_field(rx_pgn, 0, 0xFFFF, "RX PGN")
            rx_src_value = self._parse_uint_field(rx_src, 0, 0xFF, "RX Source")
            rx_dst_value = self._parse_uint_field(rx_dst, 0, 0xFF, "RX Destination")
        except ValueError as exc:
            self.infoMessage.emit("Протокол", str(exc))
            return

        UdsIdentifiers.tx.priority = tx_priority_value
        UdsIdentifiers.tx.pgn = tx_pgn_value
        UdsIdentifiers.tx.src = tx_src_value
        UdsIdentifiers.tx.dst = tx_dst_value

        UdsIdentifiers.rx.priority = rx_priority_value
        UdsIdentifiers.rx.pgn = rx_pgn_value
        UdsIdentifiers.rx.src = rx_src_value
        UdsIdentifiers.rx.dst = rx_dst_value

        self._source_address_text = f"0x{UdsIdentifiers.rx.src:02X}"
        self.sourceAddressTextChanged.emit()

        self._refresh_uds_identifier_texts()
        self.infoMessage.emit(
            "Протокол",
            f"UDS идентификаторы обновлены: TX={self._tx_identifier_text}, RX={self._rx_identifier_text}.",
        )

    @Slot(str)
    def debugEvent(self, text):
        if not self._debug_enabled:
            return
        message = str(text)
        LOGGER.info("QML debug: %s", message)
        self._append_log(f"DEBUG: {message}", QColor("#93c5fd"))
        self.infoMessage.emit("Отладка", message)

    @Slot()
    def scanDevices(self):
        if self._debug_enabled:
            LOGGER.info("scanDevices() called")
        devices_count = self._can.get_devices()
        if devices_count is None:
            self.infoMessage.emit("Сканирование", "TSCAN API не вернул список устройств.")
            self._devices = []
            self._device_indices = []
            self.devicesChanged.emit()
            self._selected_device_index = -1
            self.selectedDeviceIndexChanged.emit()
            self._refresh_device_info()
            return

        count = int(getattr(devices_count, "value", 0) or 0)
        count = max(count, 0)

        self._device_indices = list(range(count))
        labels: list[str] = []

        for hw_index in self._device_indices:
            manufacturer = ""
            product = ""
            serial = ""

            try:
                self._can.update_device_info(hw_index)
                info = self._can.device_info
                manufacturer = self._decode_bytes(getattr(info.manufacturer, "value", None))
                product = self._decode_bytes(getattr(info.product, "value", None))
                serial = self._decode_bytes(getattr(info.serial, "value", None))
            except Exception:
                # Keep scan resilient even if one adapter fails info query.
                pass

            base_name = product or manufacturer or "CAN-адаптер"
            label = f"{hw_index}: {base_name}"
            if serial:
                label += f" [{serial}]"

            labels.append(label)

        self._devices = labels
        self.devicesChanged.emit()

        if self._selected_device_index >= len(self._devices):
            self._selected_device_index = -1

        if self._selected_device_index == -1 and self._devices:
            self._selected_device_index = 0

        self.selectedDeviceIndexChanged.emit()
        self._refresh_device_info()

        if count == 0:
            self.infoMessage.emit("Сканирование", "CAN-адаптеры не найдены.")
        else:
            self.infoMessage.emit("Сканирование", f"Найдено CAN-адаптеров: {count}.")

    @Slot(int)
    def setSelectedDeviceIndex(self, index):
        if index < 0 or index >= len(self._devices):
            return

        if self._selected_device_index == index:
            return

        self._selected_device_index = index
        self.selectedDeviceIndexChanged.emit()
        self._refresh_device_info()

    @Slot()
    def toggleConnection(self):
        if self._can.is_connect:
            self._can.disconnect_device()
            self._can.stop_trace()
            self._device_handle = ""
            self._cancel_options_operation("Операция прервана: CAN отключен.")
            self._reset_observed_uds_candidate()
            self._collector_state = "stopped"
            self.collectorStateChanged.emit()
            self._collector_session_dir = None
            self._collector_csv_managers = {}
            self._collector_combined_csv_manager = None
            self._collector_nodes = {}
            self._collector_node_order = []
            self._collector_nodes_view = []
            self._collector_poll_node_index = 0
            self._collector_poll_phase = 0
            self._collector_trend_csv_series = []
            self.collectorNodesChanged.emit()
            self._reset_collector_trend()
            self._stop_calibration_poll_timer()
            self._calibration_waiting_session = False
            self._calibration_write_verify_pending = {}
            self._calibration_recent_samples = []
            self._calibration_captured_level = 0
            self._calibration_captured_available = False
            self._calibration_restore_current_did = None
            self._calibration_backup_pending = False
            self._calibration_backup_values_pending = {}
            self._calibration_restore_active = False
            self._calibration_restore_queue = []
            if self._calibration_active:
                self._calibration_active = False
                self.calibrationStateChanged.emit()
            self._reset_calibration_wizard_state()
            self.calibrationVerificationChanged.emit()
            self.calibrationValuesChanged.emit()
            if self._programming_start_timer.isActive():
                self._programming_start_timer.stop()
            self._pending_programming_after_reset = False
            self._set_programming_active(False)
            self.deviceInfoChanged.emit()
            self.connectionStateChanged.emit()
            self.traceStateChanged.emit()
            return

        hw_index = self._selected_hw_index()
        if hw_index < 0:
            self.infoMessage.emit("Подключение", "Выберите устройство CAN-адаптера.")
            return

        handle = self._can.connect_to(hw_index)
        if handle is None or handle.value == 0:
            self.infoMessage.emit("Подключение", "Не удалось подключиться к CAN-адаптеру.")
        else:
            self._device_handle = str(handle.value)
            self._refresh_device_info()

        self.connectionStateChanged.emit()
        self.traceStateChanged.emit()

    @Slot(int, int, bool)
    def toggleTrace(self, channel_index, baud_rate, terminator):
        if not self._can.is_connect:
            self.infoMessage.emit("Подключение", "Сначала подключите CAN-адаптер.")
            return

        if self._can.is_trace:
            self._can.stop_trace()
            self._cancel_options_operation("Операция прервана: трассировка остановлена.")
            if self._collector_state == "recording":
                self._collector_state = "paused"
                self.collectorStateChanged.emit()
                self._set_programming_active(False)
                self._append_log("Коллектор: запись приостановлена, потому что трассировка остановлена.", RowColor.yellow)
        else:
            self._can.start_trace(channel_index, baud_rate, terminator)

        self.traceStateChanged.emit()

    @Slot(str)
    def loadFirmware(self, path_or_url):
        file_path = self._to_local_path(path_or_url)
        if not file_path:
            self.infoMessage.emit("Прошивка", "Путь не выбран.")
            return

        if self._firmware_loading:
            self.infoMessage.emit("Прошивка", "Загрузка BIN файла уже выполняется. Подождите.")
            return

        # Update UI path immediately after selection, even before file validation.
        self._firmware_path = str(Path(file_path))
        self.firmwarePathChanged.emit()

        self._set_firmware_loading(True)
        self._append_log("Чтение BIN файла...", RowColor.blue)
        self.infoMessage.emit("Прошивка", "BIN файл выбран. Идет загрузка...")

        # Defer actual worker start to the next event loop turn so UI updates instantly.
        QTimer.singleShot(0, lambda p=file_path: self._start_firmware_loading(p))

    @Slot()
    def startProgramming(self):
        if self._programming_active:
            return

        if not self._can.is_connect:
            self.infoMessage.emit("Программирование", "Сначала подключите CAN-адаптер.")
            return

        if self._firmware_loading:
            self.infoMessage.emit("Программирование", "Дождитесь завершения загрузки BIN-файла.")
            return

        self._set_programming_active(True)

        if self._auto_reset_before_programming:
            self._pending_programming_after_reset = True
            self._append_log("Автосброс: отправка команды перехода в загрузчик", RowColor.blue)

            try:
                self._ui_ecu_reset_service.ecu_uds_reset()
            except Exception:
                self._pending_programming_after_reset = False
                self._set_programming_active(False)
                self._append_log("Автосброс: ошибка отправки команды", RowColor.red)
                self.infoMessage.emit("Программирование", "Не удалось отправить команду автосброса.")
                return

            self._programming_start_timer.start(self._auto_reset_delay_ms)
            return

        self._start_programming_flow()

    @Slot()
    def checkState(self):
        self._bootloader.check_state()

    @Slot()
    def resetToBootloader(self):
        if not self._can.is_connect:
            self.infoMessage.emit("Сброс", "Сначала подключите CAN-адаптер.")
            return

        self._ui_ecu_reset_service.ecu_uds_reset()
        self._append_log("Отправлена команда сброса в загрузчик", RowColor.blue)

    @Slot()
    def resetToMainProgram(self):
        if not self._can.is_connect:
            self.infoMessage.emit("Сброс", "Сначала подключите CAN-адаптер.")
            return

        self._ui_ecu_reset_service.ecu_software_reset()
        self._append_log("Отправлена команда сброса в основное ПО", RowColor.blue)

    @Slot()
    def clearLogs(self):
        self._logs = []
        self.logsChanged.emit()

    @Slot(str)
    def setCollectorOutputDirectory(self, path_or_url):
        resolved = self._to_local_path(path_or_url)
        if not resolved:
            return

        candidate = Path(resolved)
        if candidate.is_file():
            candidate = candidate.parent

        if not self._apply_collector_output_directory(candidate):
            self.infoMessage.emit("Коллектор", "Не удалось создать каталог выгрузки CSV.")
            return

        self._collector_output_is_session_dir = False
        self.infoMessage.emit("Коллектор", "Каталог выгрузки CSV обновлен.")

    @Slot()
    def createCollectorTimestampedLogsDirectory(self):
        timestamp = datetime.now().strftime("%d.%m.%Y_%H-%M-%S")
        base_logs_dir = self._project_root_directory / "logs"
        try:
            base_logs_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.infoMessage.emit("Коллектор", "Не удалось создать корневой каталог logs.")
            return

        candidate = base_logs_dir / timestamp
        if not self._apply_collector_output_directory(candidate):
            self.infoMessage.emit("Коллектор", "Не удалось создать каталог с датой и временем внутри logs.")
            return

        self._collector_output_is_session_dir = True
        self.infoMessage.emit("Коллектор", f"Создан каталог для CSV: {self._collector_output_directory}")

    @Slot(str)
    def setCollectorPollIntervalMs(self, interval_value):
        try:
            parsed = int(str(interval_value).strip())
        except (TypeError, ValueError):
            self.infoMessage.emit("Коллектор", "Интервал опроса должен быть целым числом в миллисекундах.")
            return

        bounded = max(30, min(10000, parsed))
        if bounded != parsed:
            self.infoMessage.emit("Коллектор", "Интервал ограничен диапазоном 30..10000 мс.")

        if self._collector_poll_interval_ms == bounded:
            return

        self._collector_poll_interval_ms = bounded
        if self._collector_poll_phase == 1:
            self._collector_poll_timer.setInterval(self._collector_poll_interval_ms)
        self.collectorPollIntervalChanged.emit()
        self._append_log(f"Интервал UDS-опроса: {self._collector_poll_interval_ms} мс", RowColor.blue)

    @Slot(str)
    def setCollectorCyclePauseMs(self, interval_value):
        try:
            parsed = int(str(interval_value).strip())
        except (TypeError, ValueError):
            self.infoMessage.emit("Коллектор", "Пауза между циклами должна быть целым числом в миллисекундах.")
            return

        bounded = max(30, min(10000, parsed))
        if bounded != parsed:
            self.infoMessage.emit("Коллектор", "Пауза между циклами ограничена диапазоном 30..10000 мс.")

        if self._collector_cycle_pause_ms == bounded:
            return

        self._collector_cycle_pause_ms = bounded
        if self._collector_poll_phase == 0:
            self._collector_poll_timer.setInterval(self._collector_cycle_pause_ms)
        self.collectorCyclePauseChanged.emit()
        self._append_log(f"Пауза между циклами UDS: {self._collector_cycle_pause_ms} мс", RowColor.blue)

    @Slot()
    def startCollectorRecording(self):
        if not self._collector_enabled:
            self.infoMessage.emit("Коллектор", "Сначала включите сценарий коллектора.")
            return

        if self._collector_state == "recording":
            return

        if not self._can.is_connect:
            self.infoMessage.emit("Коллектор", "Сначала подключите CAN-адаптер.")
            return

        if not self._can.is_trace:
            self.infoMessage.emit("Коллектор", "Сначала включите трассировку CAN.")
            return

        if self._options_busy or self._options_bulk_busy or self._calibration_active:
            self.infoMessage.emit("Коллектор", "Завершите текущую UDS-операцию перед запуском коллектора.")
            return

        if self._programming_active and self._collector_state != "paused":
            self.infoMessage.emit("Коллектор", "Сейчас выполняется другая активная операция.")
            return

        try:
            base_dir = Path(self._collector_output_directory)
            base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.infoMessage.emit("Коллектор", "Не удалось создать каталог для CSV.")
            return

        if self._collector_state == "stopped" or self._collector_session_dir is None:
            if self._collector_output_is_session_dir:
                self._collector_session_dir = base_dir
            else:
                self._collector_session_dir = base_dir / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self._collector_session_dir.mkdir(parents=True, exist_ok=True)
            self._collector_csv_managers = {}
            try:
                self._collector_combined_csv_manager = CollectorCombinedCsvManager(self._collector_session_dir)
            except Exception:
                self._collector_combined_csv_manager = None
                self._append_log("Коллектор: не удалось создать сводный CSV файл all_nodes.csv.", RowColor.yellow)
            self._append_log(f"Сессия записи: {self._collector_session_dir}", RowColor.green)
        else:
            if self._collector_combined_csv_manager is None:
                try:
                    self._collector_combined_csv_manager = CollectorCombinedCsvManager(self._collector_session_dir)
                except Exception:
                    self._collector_combined_csv_manager = None
                    self._append_log("Коллектор: не удалось создать сводный CSV файл all_nodes.csv.", RowColor.yellow)
            self._append_log("Продолжение записи CSV.", RowColor.blue)

        self._collector_state = "recording"
        self.collectorStateChanged.emit()
        self._set_programming_active(True)

    @Slot()
    def pauseCollectorRecording(self):
        if self._collector_state != "recording":
            return
        self._collector_state = "paused"
        self.collectorStateChanged.emit()
        self._set_programming_active(False)
        self._append_log("Запись CSV приостановлена.", RowColor.yellow)

    @Slot()
    def stopCollectorRecording(self):
        if self._collector_state == "stopped":
            return
        self._collector_state = "stopped"
        self.collectorStateChanged.emit()
        self._set_programming_active(False)
        self._collector_session_dir = None
        self._collector_csv_managers = {}
        self._collector_combined_csv_manager = None
        self._append_log("Запись CSV остановлена.", RowColor.blue)

    @Slot()
    def clearCollectorNodes(self):
        self._collector_nodes = {}
        self._collector_node_order = []
        self._collector_poll_node_index = 0
        self._collector_poll_phase = 0
        self._collector_pending_requests = {}
        self._collector_last_request_monotonic = 0.0
        self._collector_nodes_view = []
        self.collectorNodesChanged.emit()
        self._reset_collector_trend()

    @Slot()
    def clearCollectorErrorLogs(self):
        if len(self._collector_error_logs) == 0:
            return
        self._collector_error_logs = []
        self._collector_diagnostics_rate_limit = {}
        self.collectorDiagnosticsChanged.emit()

    @Slot("QVariant")
    def loadCollectorTrendCsv(self, path_or_urls):
        raw_items: list[object] = []
        if isinstance(path_or_urls, (list, tuple, set)):
            raw_items.extend(list(path_or_urls))
        else:
            raw_items.append(path_or_urls)

        paths: list[Path] = []
        for item in raw_items:
            resolved = self._to_local_path(item)
            if not resolved:
                continue
            try:
                paths.append(Path(resolved).expanduser().resolve())
            except Exception:
                paths.append(Path(resolved))

        if len(paths) == 0:
            self.infoMessage.emit("Графики", "CSV файл не выбран.")
            return

        loaded_series = list(self._collector_trend_csv_series)
        loaded_by_path = {
            str(item.get("path", "")): item
            for item in loaded_series
            if isinstance(item, dict)
        }

        appended_count = 0
        total_points = 0
        total_temp_fixes = 0
        for csv_path in paths:
            parsed = self._parse_collector_trend_csv_file(csv_path)
            if parsed is None:
                continue
            loaded_by_path[str(parsed.get("path", ""))] = parsed
            appended_count += 1
            total_points += int(parsed.get("count", 0))
            total_temp_fixes += int(parsed.get("legacyTemperatureCorrections", 0))

        if appended_count <= 0:
            self.infoMessage.emit("Графики", "Не удалось загрузить данные из выбранных CSV файлов.")
            return

        self._collector_trend_csv_series = list(loaded_by_path.values())
        self.collectorTrendChanged.emit()
        if total_temp_fixes > 0:
            self._append_log(
                f"Collector CSV: legacy temperature auto-fix applied to {total_temp_fixes} points.",
                RowColor.yellow,
            )
        self.infoMessage.emit("Графики", f"Загружено CSV файлов: {appended_count}, точек: {total_points}.")

    @Slot()
    def clearCollectorTrendCsv(self):
        if len(self._collector_trend_csv_series) == 0:
            return
        self._collector_trend_csv_series = []
        self.collectorTrendChanged.emit()
        self.infoMessage.emit("Графики", "Загруженные CSV данные очищены.")

    @Slot()
    def clearCanTrafficLogs(self):
        if self._can_filter_rebuild_timer.isActive():
            self._can_filter_rebuild_timer.stop()
        self._can_traffic_logs = []
        self._rebuild_can_traffic_view()

    @Slot(str, str)
    def setCanTrafficFilter(self, field, value):
        key = str(field or "").strip()
        if key not in self._can_filter_values:
            return

        text = str(value or "").strip()
        if self._can_filter_values.get(key, "") == text:
            return

        self._can_filter_values[key] = text
        self._schedule_can_traffic_rebuild(restart=True)

    @Slot()
    def resetCanTrafficFilters(self):
        updated = False
        for field in self.CAN_FILTER_FIELDS:
            if self._can_filter_values.get(field):
                self._can_filter_values[field] = ""
                updated = True
        if updated:
            self._schedule_can_traffic_rebuild(restart=True)

    @Slot()
    def startOptionsBulkReadAll(self):
        if self._options_bulk_busy:
            return

        if self._programming_active:
            self.infoMessage.emit("Параметры UDS", "Завершите активную операцию перед массовым чтением DID.")
            return

        if self._options_busy:
            self.infoMessage.emit("UDS Options", "Wait until current operation completes.")
            return

        if not self._can.is_connect or not self._can.is_trace:
            self.infoMessage.emit("UDS Options", "Connect adapter and start CAN trace first.")
            return

        self._start_options_bulk_read()

    @Slot()
    def stopOptionsBulkReadAll(self):
        self._stop_options_bulk_read("Bulk DID read stopped.")

    @Slot()
    def clearOptionsBulkRows(self):
        if self._options_bulk_busy:
            return
        self._options_bulk_rows = []
        self._options_bulk_plan = []
        self._options_bulk_next_index = 0
        self._options_bulk_success_count = 0
        self._options_bulk_fail_count = 0
        self._options_bulk_status = "Ready for bulk DID read"
        self.optionsBulkRowsChanged.emit()
        self.optionsBulkChanged.emit()

    @Slot(int)
    def setOptionsBulkDelayMs(self, value):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return

        bounded = max(0, min(parsed, 5000))
        if bounded == self._options_bulk_delay_ms:
            return

        self._options_bulk_delay_ms = bounded
        self.optionsBulkChanged.emit()
