from __future__ import annotations

import csv
from datetime import datetime
import json
import logging
from pathlib import Path
import re

from PySide6.QtCore import QCoreApplication, QTimer, Slot
from PySide6.QtGui import QColor

from colors import RowColor
from uds.data_identifiers import UdsData
from uds.options_catalog import get_option_by_did, get_option_by_index
from uds.services.session import Session
from uds.uds_identifiers import UdsIdentifiers
from ui.qml.collector_csv_manager import CollectorCombinedCsvManager

from .contract import AppControllerContract
from .workers import UdsOptionProxy

LOGGER = logging.getLogger(__name__)

class AppControllerPublicSlotsMixin(AppControllerContract):
    @staticmethod
    def _extract_firmware_version_from_name(path_text: str) -> str:
        """Цель функции в извлечении версии из имени BIN, затем она возвращает формат вида 1.0.0.b0006."""
        file_name = Path(str(path_text or "")).name
        if not file_name:
            return ""
        match = re.search(r"(\d+\.\d+\.\d+\.b\d{4})", file_name, flags=re.IGNORECASE)
        if match is None:
            return ""
        return str(match.group(1))

    @staticmethod
    def _normalize_software_version_text(version_text: str) -> str:
        """Цель функции в валидации версии ПО, затем она возвращает безопасную ASCII-строку для DID 0xF195."""
        value = str(version_text or "").strip()
        if not value:
            raise ValueError("Поле версии ПО пустое.")
        if len(value) > 127:
            raise ValueError("Версия ПО слишком длинная: максимум 127 символов.")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise ValueError("Версия ПО должна содержать только латиницу, цифры, точку, дефис или подчёркивание.")
        return value

    def _resolve_software_version_target_sa(self) -> int:
        """Цель функции в выборе узла для DID 0xF195, затем она использует SA из Security Access при его наличии."""
        if self._service_access_target_sa is not None:
            return int(self._service_access_target_sa) & 0xFF
        return int(self._resolve_options_target_sa()) & 0xFF

    @Slot()
    def readSoftwareVersionDid(self):
        """Цель функции в чтении DID 0xF195, затем она обновляет версию ПО в правом верхнем блоке главной формы."""
        if self._software_version_busy or self._options_busy or self._options_bulk_busy:
            self.infoMessage.emit("Версия ПО", "Подождите завершения текущей UDS-операции.")
            return

        if self._programming_active or self._programming_batch_active:
            self.infoMessage.emit("Версия ПО", "Во время программирования чтение DID 0xF195 недоступно.")
            return

        if not self._can.is_connect or not self._can.is_trace:
            self.infoMessage.emit("Версия ПО", "Сначала подключите адаптер и запустите трассировку CAN.")
            return

        parameter = get_option_by_did(int(self._software_version_did))
        if parameter is None or (not parameter.can_read):
            self.infoMessage.emit("Версия ПО", "DID 0xF195 недоступен для чтения в текущем каталоге параметров.")
            return

        self._software_version_busy = True
        self._software_version_status = "Чтение DID 0xF195..."
        self.softwareVersionChanged.emit()

        target_sa = self._resolve_software_version_target_sa()
        if not self._start_options_read_request(
            parameter,
            request_origin="sw_version_read",
            append_history=False,
            target_sa_override=target_sa,
        ):
            self._software_version_busy = False
            self._software_version_status = "Ошибка отправки запроса чтения DID 0xF195."
            self.softwareVersionChanged.emit()
            self.infoMessage.emit("Версия ПО", "Не удалось отправить запрос чтения DID 0xF195.")

    @Slot(str)
    def writeSoftwareVersionDid(self, version_text):
        """Цель функции в записи DID 0xF195, затем она отправляет версию ПО в EEPROM выбранного узла."""
        if self._software_version_busy or self._options_busy or self._options_bulk_busy:
            self.infoMessage.emit("Версия ПО", "Подождите завершения текущей UDS-операции.")
            return

        if self._programming_active or self._programming_batch_active:
            self.infoMessage.emit("Версия ПО", "Во время программирования запись DID 0xF195 недоступна.")
            return

        if not self._can.is_connect or not self._can.is_trace:
            self.infoMessage.emit("Версия ПО", "Сначала подключите адаптер и запустите трассировку CAN.")
            return

        parameter = get_option_by_did(int(self._software_version_did))
        if parameter is None or (not parameter.can_write):
            self.infoMessage.emit("Версия ПО", "DID 0xF195 недоступен для записи в текущем каталоге параметров.")
            return

        try:
            normalized = self._normalize_software_version_text(str(version_text or ""))
        except ValueError as exc:
            self.infoMessage.emit("Версия ПО", str(exc))
            return

        encoded = normalized.encode("ascii", errors="strict")
        size = int(parameter.size)
        if size <= 1:
            self.infoMessage.emit("Версия ПО", "Некорректный размер DID 0xF195 в каталоге параметров.")
            return
        if len(encoded) > (size - 1):
            self.infoMessage.emit("Версия ПО", f"Версия ПО не помещается в DID 0xF195 ({size} байт).")
            return

        # Для строковых DID передаем только полезную строку и завершающий ноль.
        # Остальные байты до размера переменной MCU заполнит нулями на своей стороне.
        payload = encoded + b"\x00"
        target_sa = self._resolve_software_version_target_sa()
        self._software_version_busy = True
        self._software_version_status = f"Запись DID 0xF195 для SA 0x{target_sa:02X}: {normalized}..."
        self.softwareVersionChanged.emit()

        started = self._start_options_write_multiframe_request(
            parameter,
            payload,
            request_origin="sw_version_write",
            append_history=False,
            target_sa_override=target_sa,
        )
        if not started:
            self._software_version_busy = False
            self._software_version_status = "Ошибка отправки записи DID 0xF195."
            self.softwareVersionChanged.emit()
            self.infoMessage.emit("Версия ПО", "Не удалось отправить запись DID 0xF195.")

    @Slot()
    def writeSoftwareVersionFromFirmwareFile(self):
        """Цель функции в записи версии из BIN-файла, затем она автоматически использует формат из имени прошивки."""
        version_text = str(self._firmware_file_version_text or "").strip()
        if not version_text or version_text == "—":
            self.infoMessage.emit("Версия ПО", "В имени выбранного BIN-файла версия не найдена.")
            return
        self.writeSoftwareVersionDid(version_text)

    @staticmethod
    def _supplier_did_definitions() -> tuple[dict[str, object], ...]:
        """Цель функции в описании набора DID изготовителя, затем она возвращает компактный список строк для главной таблицы."""
        return (
            {"did": 0xF18A, "name": "Идентификатор поставщика"},
            {"did": 0xF18B, "name": "Дата изготовления ЭБУ"},
            {"did": 0xF18C, "name": "Серийный номер ЭБУ"},
            {"did": 0xF191, "name": "HW номер ЭБУ (OEM)"},
            {"did": 0xF192, "name": "HW номер ЭБУ (поставщик)"},
            {"did": 0xF193, "name": "HW версия ЭБУ"},
            {"did": 0xF194, "name": "SW номер ЭБУ"},
            {"did": 0xF195, "name": "SW версия ЭБУ"},
        )

    def _init_supplier_did_rows(self):
        """Цель функции в инициализации строк DID изготовителя, затем она подготавливает модель для QML-таблицы."""
        rows: list[dict[str, object]] = []
        for item in self._supplier_did_definitions():
            did_value = int(item.get("did", 0)) & 0xFFFF
            parameter = get_option_by_did(did_value)
            row = {
                "didInt": did_value,
                "didText": f"0x{did_value:04X}",
                "name": str(item.get("name", f"DID 0x{did_value:04X}")),
                "value": "",
                "busy": False,
                "canRead": bool(parameter is not None and parameter.can_read),
                "canWrite": bool(parameter is not None and parameter.can_write),
                "maxBytes": int(parameter.size) if parameter is not None else 0,
            }
            rows.append(row)
        self._supplier_did_rows = rows

    def _find_supplier_did_row_index(self, did_value: int) -> int:
        """Цель функции в поиске строки по DID, затем она возвращает индекс или -1 при отсутствии."""
        target = int(did_value) & 0xFFFF
        for index, row in enumerate(self._supplier_did_rows):
            if int(row.get("didInt", -1)) == target:
                return int(index)
        return -1

    def _update_supplier_did_row(self, did_value: int, **changes):
        """Цель функции в точечном обновлении строки DID, затем она заменяет только переданные поля без потери остальных значений."""
        index = self._find_supplier_did_row_index(did_value)
        if index < 0:
            return
        updated_rows = list(self._supplier_did_rows)
        row = dict(updated_rows[index])
        for key, value in changes.items():
            row[str(key)] = value
        updated_rows[index] = row
        self._supplier_did_rows = updated_rows
        self.softwareVersionChanged.emit()

    @staticmethod
    def _normalize_supplier_did_text_value(value_text: str) -> str:
        """Цель функции в нормализации текстового значения DID, затем она убирает лишние пробелы по краям строки."""
        return str(value_text or "").strip()

    def _build_supplier_did_payload(self, did_value: int, value_text: str) -> bytes:
        """Цель функции в упаковке текста в полезные байты DID, затем она валидирует размер и добавляет нуль-терминатор."""
        index = self._find_supplier_did_row_index(did_value)
        if index < 0:
            raise ValueError(f"Не найдена строка DID 0x{int(did_value) & 0xFFFF:04X}.")
        row = self._supplier_did_rows[index]
        max_bytes = int(row.get("maxBytes", 0))
        if max_bytes <= 1:
            raise ValueError(f"DID 0x{int(did_value) & 0xFFFF:04X} имеет некорректный размер.")

        normalized = self._normalize_supplier_did_text_value(value_text)
        if not normalized:
            raise ValueError("Поле значения пустое.")

        encoded = normalized.encode("utf-8")
        if len(encoded) > (max_bytes - 1):
            raise ValueError(
                f"Значение для DID 0x{int(did_value) & 0xFFFF:04X} слишком длинное: максимум {max_bytes - 1} байт UTF-8."
            )
        return bytes(encoded) + b"\x00"

    def _start_supplier_did_bulk_read_next(self):
        """Цель функции в запуске следующего шага массового чтения DID, затем она отправляет запрос только после завершения предыдущего."""
        if not bool(self._supplier_did_bulk_busy):
            return
        if bool(self._options_busy):
            return

        while len(self._supplier_did_bulk_queue) > 0:
            did_value = int(self._supplier_did_bulk_queue.pop(0)) & 0xFFFF
            index = self._find_supplier_did_row_index(did_value)
            if index < 0:
                self._supplier_did_bulk_done += 1
                self._supplier_did_bulk_fail += 1
                continue

            row = dict(self._supplier_did_rows[index])
            if not bool(row.get("canRead", False)):
                self._supplier_did_bulk_done += 1
                self._supplier_did_bulk_fail += 1
                self._update_supplier_did_row(did_value, value="Недоступно", busy=False)
                continue

            parameter = get_option_by_did(did_value)
            if parameter is None or (not parameter.can_read):
                self._supplier_did_bulk_done += 1
                self._supplier_did_bulk_fail += 1
                self._update_supplier_did_row(did_value, value="Нет в каталоге", busy=False)
                continue

            self._update_supplier_did_row(did_value, busy=True)
            target_sa = self._resolve_software_version_target_sa()
            self._supplier_did_status_text = (
                f"Чтение DID изготовителя {self._supplier_did_bulk_done + 1}/{max(1, self._supplier_did_bulk_total)}: "
                f"0x{did_value:04X} (SA 0x{target_sa:02X})."
            )
            self.softwareVersionChanged.emit()
            started = self._start_options_read_request(
                parameter,
                request_origin=f"supplier_did_bulk:{did_value:04X}",
                append_history=False,
                target_sa_override=target_sa,
            )
            if started:
                return

            self._supplier_did_bulk_done += 1
            self._supplier_did_bulk_fail += 1
            self._update_supplier_did_row(did_value, busy=False)

        self._finish_supplier_did_bulk_read()

    def _finish_supplier_did_bulk_read(self):
        """Цель функции в завершении массового чтения DID изготовителя, затем она очищает очередь и публикует итоговый статус."""
        total_count = int(self._supplier_did_bulk_total)
        success_count = int(self._supplier_did_bulk_success)
        fail_count = int(self._supplier_did_bulk_fail)
        self._supplier_did_bulk_busy = False
        self._supplier_did_bulk_queue = []
        self._supplier_did_bulk_total = 0
        self._supplier_did_bulk_done = 0
        self._supplier_did_bulk_success = 0
        self._supplier_did_bulk_fail = 0
        self._supplier_did_status_text = (
            f"Чтение DID изготовителя завершено. Успешно: {success_count}, ошибок: {fail_count}, всего: {total_count}."
        )
        self.softwareVersionChanged.emit()

    @Slot()
    def readAllSupplierDidRows(self):
        """Цель функции в последовательном чтении всех DID изготовителя, затем она обновляет таблицу одной операцией по кнопке."""
        if bool(self._supplier_did_bulk_busy) or bool(self._options_busy) or bool(self._options_bulk_busy):
            self.infoMessage.emit("DID изготовителя", "Подождите завершения текущей UDS-операции.")
            return
        if self._programming_active or self._programming_batch_active:
            self.infoMessage.emit("DID изготовителя", "Во время программирования чтение DID изготовителя недоступно.")
            return
        if not self._can.is_connect or not self._can.is_trace:
            self.infoMessage.emit("DID изготовителя", "Сначала подключите адаптер и запустите трассировку CAN.")
            return

        self._supplier_did_bulk_queue = [
            int(row.get("didInt", 0)) & 0xFFFF
            for row in self._supplier_did_rows
        ]
        self._supplier_did_bulk_total = len(self._supplier_did_bulk_queue)
        self._supplier_did_bulk_done = 0
        self._supplier_did_bulk_success = 0
        self._supplier_did_bulk_fail = 0
        self._supplier_did_bulk_busy = True
        self._supplier_did_status_text = "Запущено массовое чтение DID изготовителя."
        self.softwareVersionChanged.emit()
        self._start_supplier_did_bulk_read_next()

    @Slot(int, str)
    def writeSupplierDidValue(self, did_value, value_text):
        """Цель функции в записи одной строки DID изготовителя, затем она отправляет 0x2E для выбранного идентификатора."""
        did = int(did_value) & 0xFFFF
        index = self._find_supplier_did_row_index(did)
        if index < 0:
            self.infoMessage.emit("DID изготовителя", f"Строка DID 0x{did:04X} не найдена.")
            return
        row = dict(self._supplier_did_rows[index])
        if not bool(row.get("canWrite", False)):
            self.infoMessage.emit("DID изготовителя", f"DID 0x{did:04X} недоступен для записи.")
            return

        if bool(self._supplier_did_bulk_busy) or bool(self._options_busy) or bool(self._options_bulk_busy):
            self.infoMessage.emit("DID изготовителя", "Подождите завершения текущей UDS-операции.")
            return
        if self._programming_active or self._programming_batch_active:
            self.infoMessage.emit("DID изготовителя", "Во время программирования запись DID изготовителя недоступна.")
            return
        if not self._can.is_connect or not self._can.is_trace:
            self.infoMessage.emit("DID изготовителя", "Сначала подключите адаптер и запустите трассировку CAN.")
            return

        parameter = get_option_by_did(did)
        if parameter is None or (not parameter.can_write):
            self.infoMessage.emit("DID изготовителя", f"DID 0x{did:04X} недоступен для записи в каталоге параметров.")
            return

        try:
            payload = self._build_supplier_did_payload(did, str(value_text or ""))
        except ValueError as exc:
            self.infoMessage.emit("DID изготовителя", str(exc))
            return

        target_sa = self._resolve_software_version_target_sa()
        self._update_supplier_did_row(did, busy=True)
        self._supplier_did_status_text = f"Запись DID 0x{did:04X} (SA 0x{target_sa:02X})..."
        self.softwareVersionChanged.emit()
        started = self._start_options_write_multiframe_request(
            parameter,
            payload,
            request_origin=f"supplier_did_write:{did:04X}",
            append_history=False,
            target_sa_override=target_sa,
        )
        if not started:
            self._update_supplier_did_row(did, busy=False)
            self._supplier_did_status_text = f"Ошибка отправки записи DID 0x{did:04X}."
            self.softwareVersionChanged.emit()
            self.infoMessage.emit("DID изготовителя", f"Не удалось отправить запись DID 0x{did:04X}.")

    def _handle_supplier_did_options_result(
        self,
        *,
        success: bool,
        request_origin: str,
        pending_action: str,
        pending_did: int | None,
        value_bytes: bytes | None,
        message: str,
    ):
        """Цель функции в обработке ответов UDS по DID изготовителя, затем она синхронизирует таблицу и продолжает массовое чтение."""
        if not str(request_origin or "").startswith("supplier_did_"):
            return

        did = int(pending_did) & 0xFFFF if pending_did is not None else None
        if did is not None:
            self._update_supplier_did_row(did, busy=False)

        if success and did is not None:
            decoded_text = self._decode_software_version_bytes(value_bytes)
            if pending_action == "read":
                self._update_supplier_did_row(did, value=decoded_text)
                self._supplier_did_status_text = f"Прочитан DID 0x{did:04X}."
            elif pending_action == "write":
                self._update_supplier_did_row(did, value=decoded_text)
                self._supplier_did_status_text = f"Записан DID 0x{did:04X}."

            if did == int(self._software_version_did):
                self._software_version_text = decoded_text if decoded_text else "—"
                self._software_version_status = f"DID 0x{did:04X} синхронизирован в таблице изготовителя."
        elif did is not None:
            self._supplier_did_status_text = f"Ошибка DID 0x{did:04X}: {str(message)}"

        if str(request_origin).startswith("supplier_did_bulk:"):
            self._supplier_did_bulk_done += 1
            if success:
                self._supplier_did_bulk_success += 1
            else:
                self._supplier_did_bulk_fail += 1
            self.softwareVersionChanged.emit()
            QTimer.singleShot(0, self._start_supplier_did_bulk_read_next)
        else:
            self.softwareVersionChanged.emit()

    @Slot(bool)
    def setCollectorSftpEnabled(self, enabled):
        """Цель функции в переключении SFTP-выгрузки, затем она обновляет конфиг uploader и уведомляет UI."""
        value = bool(enabled)
        if value == bool(self._collector_sftp_enabled):
            return
        self._collector_sftp_enabled = value
        self._collector_refresh_sftp_uploader_config()
        if value:
            self._collector_sftp_status_text = "SFTP: включен, ожидает выгрузки."
        else:
            self._collector_sftp_status_text = "SFTP: выключен."
            self._collector_sftp_busy = False
        self.collectorSftpChanged.emit()

    @Slot(str)
    def setCollectorSftpHost(self, host_text):
        """Цель функции в сохранении SFTP-хоста, затем она синхронизирует runtime-конфиг выгрузки."""
        value = str(host_text or "").strip()
        if value == str(self._collector_sftp_host):
            return
        self._collector_sftp_host = value
        self._collector_refresh_sftp_uploader_config()
        self.collectorSftpChanged.emit()

    @Slot(str)
    def setCollectorSftpPort(self, port_text):
        """Цель функции в сохранении SFTP-порта, затем она валидирует диапазон и обновляет конфиг uploader."""
        try:
            parsed = int(str(port_text).strip())
        except (TypeError, ValueError):
            self.infoMessage.emit("SFTP", "Порт SFTP должен быть целым числом.")
            return
        bounded = max(1, min(65535, parsed))
        if bounded == int(self._collector_sftp_port):
            return
        self._collector_sftp_port = bounded
        self._collector_refresh_sftp_uploader_config()
        self.collectorSftpChanged.emit()

    @Slot(str)
    def setCollectorSftpUsername(self, username_text):
        """Цель функции в сохранении имени пользователя SFTP, затем она применяет изменения к uploader."""
        value = str(username_text or "").strip()
        if value == str(self._collector_sftp_username):
            return
        self._collector_sftp_username = value
        self._collector_refresh_sftp_uploader_config()
        self.collectorSftpChanged.emit()

    @Slot(str)
    def setCollectorSftpPassword(self, password_text):
        """Цель функции в сохранении пароля SFTP, затем она применяет его в runtime-конфиге выгрузки."""
        value = str(password_text or "")
        if value == str(self._collector_sftp_password):
            return
        self._collector_sftp_password = value
        self._collector_refresh_sftp_uploader_config()
        self.collectorSftpChanged.emit()

    @Slot(str)
    def setCollectorSftpRemoteDir(self, remote_dir_text):
        """Цель функции в сохранении удаленного каталога SFTP, затем она синхронизирует путь выгрузки."""
        value = str(remote_dir_text or "").strip()
        if not value:
            value = "/incoming/csv"
        if value == str(self._collector_sftp_remote_dir):
            return
        self._collector_sftp_remote_dir = value
        self._collector_refresh_sftp_uploader_config()
        self.collectorSftpChanged.emit()

    @Slot()
    def uploadCollectorCurrentSessionToSftp(self):
        """Цель функции в ручном запуске выгрузки текущей сессии, затем она ставит каталог в очередь uploader."""
        if self._collector_session_dir is None:
            self.infoMessage.emit("SFTP", "Нет активной сессии коллектора для выгрузки.")
            return
        self._collector_schedule_sftp_upload(Path(self._collector_session_dir))
        self.infoMessage.emit("SFTP", "Текущая сессия поставлена в очередь выгрузки.")

    @staticmethod
    def _calibration_dump_required_dids() -> tuple[int, int, int, int, int]:
        """Цель функции в фиксации состава дампа калибровки, затем она возвращает DID 0%/100%/K1/K0/zero trim."""
        return (
            int(UdsData.empty_fuel_tank.pid),
            int(UdsData.full_fuel_tank.pid),
            int(UdsData.fuel_temp_comp_k1_x100.pid),
            int(UdsData.fuel_temp_comp_k0_count.pid),
            int(UdsData.fuel_zero_trim_count.pid),
        )

    @staticmethod
    def _calibration_dump_did_name(did: int) -> str:
        """Цель функции в человеко-понятной подписи DID, затем она возвращает название параметра для логов."""
        did_value = int(did) & 0xFFFF
        if did_value == int(UdsData.empty_fuel_tank.pid):
            return "0% (DID 0x0012)"
        if did_value == int(UdsData.full_fuel_tank.pid):
            return "100% (DID 0x0013)"
        if did_value == int(UdsData.fuel_temp_comp_k1_x100.pid):
            return "K1 (DID 0x001B)"
        if did_value == int(UdsData.fuel_temp_comp_k0_count.pid):
            return "K0 (DID 0x001C)"
        if did_value == int(UdsData.fuel_zero_trim_count.pid):
            return "Смещение 0% (DID 0x002D)"
        return f"DID 0x{did_value:04X}"

    def _reset_calibration_dump_capture_state(self):
        """Цель функции в полном сбросе шага чтения дампа, затем она останавливает таймер и очищает промежуточные значения."""
        self._calibration_dump_capture_active = False
        self._calibration_dump_capture_target_sa = None
        self._calibration_dump_capture_queue = []
        self._calibration_dump_capture_current_did = None
        self._calibration_dump_capture_values = {}
        if self._calibration_dump_capture_timeout_timer.isActive():
            self._calibration_dump_capture_timeout_timer.stop()

    def _resolve_calibration_dump_directory(self) -> Path:
        """Цель функции в выборе каталога хранения дампов, затем она возвращает рабочий путь для файлов резервной калибровки."""
        try:
            output_dir = Path(str(self._collector_output_directory)).expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            return output_dir
        except Exception:
            fallback_dir = Path(self._project_root_directory) / "logs"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            return fallback_dir

    def _write_calibration_dump_file(self, payload: dict[str, object]) -> str:
        """Цель функции в сохранении дампа в UTF-8 JSON, затем она записывает файл с именем, содержащим SA узла."""
        output_dir = self._resolve_calibration_dump_directory()
        try:
            node_sa = int(payload.get("nodeSaDec", 0)) & 0xFF
        except Exception:
            node_sa = 0
        timestamp_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"calibration_dump_node_0x{node_sa:02X}_{timestamp_name}.json"
        file_path = output_dir / file_name
        with file_path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        return str(file_path)

    def _apply_calibration_dump_to_state(
        self,
        *,
        node_sa: int,
        level_0: int,
        level_100: int,
        k1: int,
        k0: int,
        zero_trim: int,
        file_path: str,
        source_text: str,
        saved_at_text: str,
        loaded_from_file: bool,
    ):
        """Цель функции в синхронизации UI с данными дампа, затем она обновляет все поля отображения резервной копии."""
        self._calibration_backup_node_sa = int(node_sa) & 0xFF
        self._calibration_backup_level_0 = int(level_0)
        self._calibration_backup_level_100 = int(level_100)
        self._calibration_backup_k1 = int(k1)
        self._calibration_backup_k0 = int(k0)
        self._calibration_backup_zero_trim = int(zero_trim)
        self._calibration_backup_file_path = str(file_path or "")
        self._calibration_backup_source_text = str(source_text or "").strip()
        self._calibration_backup_saved_at_text = str(saved_at_text or "").strip()
        self._calibration_backup_loaded_from_file = bool(loaded_from_file)
        self._calibration_backup_available = True
        self.calibrationBackupChanged.emit()

    def _finish_calibration_dump_capture(self, success: bool, message: str):
        """Цель функции в завершении чтения дампа, затем она либо сохраняет файл и обновляет UI, либо сообщает причину отказа."""
        values = dict(self._calibration_dump_capture_values)
        target_sa = self._calibration_dump_capture_target_sa
        self._reset_calibration_dump_capture_state()

        if not success:
            self._append_log(str(message), RowColor.red)
            self.infoMessage.emit("Калибровка", str(message))
            return

        if target_sa is None:
            self._append_log("Калибровка: дамп не сохранен, не определен целевой узел.", RowColor.red)
            self.infoMessage.emit("Калибровка", "Не удалось определить целевой узел для дампа.")
            return

        did0, did100, didk1, didk0, didtrim = self._calibration_dump_required_dids()
        missing = [did for did in (did0, did100, didk1, didk0, didtrim) if did not in values]
        if len(missing) > 0:
            missing_text = ", ".join(f"0x{int(did) & 0xFFFF:04X}" for did in missing)
            error_text = f"Калибровка: дамп не сохранен, не получены DID: {missing_text}."
            self._append_log(error_text, RowColor.red)
            self.infoMessage.emit("Калибровка", error_text)
            return

        saved_at_text = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        payload = {
            "format": "fuel-intake-calibration-dump-v1",
            "savedAt": saved_at_text,
            "nodeSaHex": f"0x{int(target_sa) & 0xFF:02X}",
            "nodeSaDec": int(target_sa) & 0xFF,
            "values": {
                "did_0x0012": int(values[did0]),
                "did_0x0013": int(values[did100]),
                "did_0x001B": int(values[didk1]),
                "did_0x001C": int(values[didk0]),
                "did_0x002D": int(values[didtrim]),
            },
        }

        try:
            file_path = self._write_calibration_dump_file(payload)
        except Exception as exc:
            error_text = f"Калибровка: ошибка сохранения дампа: {str(exc)}"
            self._append_log(error_text, RowColor.red)
            self.infoMessage.emit("Калибровка", error_text)
            return

        self._apply_calibration_dump_to_state(
            node_sa=int(target_sa) & 0xFF,
            level_0=int(values[did0]),
            level_100=int(values[did100]),
            k1=int(values[didk1]),
            k0=int(values[didk0]),
            zero_trim=int(values[didtrim]),
            file_path=file_path,
            source_text="Источник дампа: считан из МК.",
            saved_at_text=saved_at_text,
            loaded_from_file=False,
        )
        self._append_log(
            f"Калибровка: дамп узла 0x{int(target_sa) & 0xFF:02X} сохранен в {file_path}.",
            RowColor.green,
        )
        self.infoMessage.emit("Калибровка", f"Дамп калибровки сохранен: {file_path}")

    def _request_next_calibration_dump_capture_did(self):
        """Цель функции в последовательном чтении параметров дампа, затем она отправляет следующий DID в МК."""
        if not bool(self._calibration_dump_capture_active):
            return

        if len(self._calibration_dump_capture_queue) <= 0:
            self._finish_calibration_dump_capture(True, "Калибровка: дамп сохранен.")
            return

        did = int(self._calibration_dump_capture_queue.pop(0)) & 0xFFFF
        target_var = UdsData.get_var_by_pid(did)
        if target_var is None:
            self._finish_calibration_dump_capture(False, f"Калибровка: параметр DID 0x{did:04X} отсутствует в каталоге.")
            return

        self._calibration_dump_capture_current_did = int(did)
        self._configure_calibration_uds_services()
        self._calibration_read_service.read_data_by_identifier(self._build_calibration_tx_identifier(), target_var)
        self._calibration_dump_capture_timeout_timer.start()
        self._append_log(
            f"Калибровка: чтение для дампа {self._calibration_dump_did_name(did)}.",
            RowColor.blue,
        )

    def _on_calibration_dump_capture_timeout(self):
        """Цель функции в защите шага чтения дампа от зависания, затем она завершает операцию с понятной ошибкой."""
        if not bool(self._calibration_dump_capture_active):
            return
        did = self._calibration_dump_capture_current_did
        if did is None:
            self._finish_calibration_dump_capture(False, "Калибровка: таймаут чтения дампа.")
            return
        self._finish_calibration_dump_capture(
            False,
            f"Калибровка: таймаут чтения {self._calibration_dump_did_name(int(did))}.",
        )

    @staticmethod
    def _parse_calibration_dump_value(raw_value, field_name: str) -> int:
        """Цель функции в строгой валидации значения дампа, затем она преобразует поле в целое число."""
        if isinstance(raw_value, bool):
            raise ValueError(f"Поле {field_name} имеет некорректный тип.")
        if isinstance(raw_value, int):
            return int(raw_value)
        text = str(raw_value).strip()
        if len(text) <= 0:
            raise ValueError(f"Поле {field_name} не заполнено.")
        if text.lower().startswith("0x"):
            return int(text, 16)
        return int(text, 10)

    @classmethod
    def _load_calibration_dump_payload(cls, file_path: Path) -> dict[str, object]:
        """Цель функции в чтении JSON-дампа, затем она возвращает словарь с параметрами и метаданными узла."""
        with file_path.open("r", encoding="utf-8") as file:
            raw_payload = json.load(file)
        if not isinstance(raw_payload, dict):
            raise ValueError("Формат дампа поврежден: корень JSON должен быть объектом.")

        values = raw_payload.get("values")
        if not isinstance(values, dict):
            raise ValueError("Формат дампа поврежден: отсутствует блок values.")

        node_sa_raw = raw_payload.get("nodeSaDec", raw_payload.get("nodeSa", raw_payload.get("nodeSaHex", 0)))
        node_sa = cls._parse_calibration_dump_value(node_sa_raw, "nodeSa")
        if node_sa < 0 or node_sa > 0xFF:
            raise ValueError("Поле nodeSa выходит за диапазон 0..255.")

        result = {
            "node_sa": int(node_sa) & 0xFF,
            "saved_at": str(raw_payload.get("savedAt", "")).strip(),
            "level_0": cls._parse_calibration_dump_value(values.get("did_0x0012"), "did_0x0012"),
            "level_100": cls._parse_calibration_dump_value(values.get("did_0x0013"), "did_0x0013"),
            "k1": cls._parse_calibration_dump_value(values.get("did_0x001B"), "did_0x001B"),
            "k0": cls._parse_calibration_dump_value(values.get("did_0x001C"), "did_0x001C"),
            "zero_trim": cls._parse_calibration_dump_value(values.get("did_0x002D"), "did_0x002D"),
        }
        return result

    @staticmethod
    def _calibration_backup_all_nodes_required_dids() -> tuple[int, int, int, int]:
        """Цель функции в фиксации состава резервной копии, затем она возвращает DID 0%/100%/K1/K0 для опроса."""
        return (
            int(UdsData.empty_fuel_tank.pid),
            int(UdsData.full_fuel_tank.pid),
            int(UdsData.fuel_temp_comp_k1_x100.pid),
            int(UdsData.fuel_temp_comp_k0_count.pid),
        )

    def _resolve_calibration_backup_all_nodes_targets(self) -> list[int]:
        """Цель функции в сборе узлов для резервной копии, затем она возвращает уникальный список SA без авто-элементов."""
        targets: list[int] = []
        seen: set[int] = set()

        for value in list(self._calibration_node_values):
            if value is None:
                continue
            try:
                normalized = int(value) & 0xFF
            except (TypeError, ValueError):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            targets.append(normalized)

        fallback_sa = int(self._resolve_calibration_target_sa()) & 0xFF
        if fallback_sa not in seen:
            targets.append(fallback_sa)

        return targets

    def _resolve_calibration_backup_all_nodes_directory(self) -> Path:
        """Цель функции в выборе каталога резервной копии, затем она возвращает рабочий путь для CSV-файла."""
        try:
            output_dir = Path(str(self._collector_output_directory)).expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            return output_dir
        except Exception:
            fallback_dir = Path(self._project_root_directory) / "logs"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            return fallback_dir

    def _write_calibration_backup_all_nodes_csv(self, values_by_sa: dict[int, dict[int, int]]) -> str:
        """Цель функции в сохранении резервной копии по всем узлам, затем она пишет отдельный UTF-8 CSV с 0%/100%/K1/K0."""
        output_dir = self._resolve_calibration_backup_all_nodes_directory()
        file_name = f"calibration_backup_all_nodes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        csv_path = output_dir / file_name

        did0, did100, didk1, didk0 = self._calibration_backup_all_nodes_required_dids()
        with csv_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow(("Время", "Узел", "0% (DID 0x0012)", "100% (DID 0x0013)", "K1 (DID 0x001B)", "K0 (DID 0x001C)"))
            timestamp_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for node_sa in sorted(values_by_sa.keys()):
                node_values = values_by_sa.get(int(node_sa) & 0xFF, {})
                level0 = node_values.get(did0, "")
                level100 = node_values.get(did100, "")
                k1_value = node_values.get(didk1, "")
                k0_value = node_values.get(didk0, "")
                writer.writerow((timestamp_text, f"0x{int(node_sa) & 0xFF:02X}", level0, level100, k1_value, k0_value))

        return str(csv_path)

    def _finish_calibration_backup_all_nodes(self):
        """Цель функции в штатном завершении копирования, затем она восстанавливает целевой SA и пишет итоговый CSV."""
        if self._calibration_backup_all_nodes_step_timer.isActive():
            self._calibration_backup_all_nodes_step_timer.stop()

        original_target = self._calibration_backup_all_nodes_original_target_sa
        if original_target is None:
            self._calibration_target_node_sa = None
        else:
            self._calibration_target_node_sa = int(original_target) & 0xFF

        values_by_sa = dict(self._calibration_backup_all_nodes_values_by_sa)
        reference_sa = self._calibration_backup_all_nodes_reference_sa
        self._calibration_backup_all_nodes_active = False
        self._calibration_backup_all_nodes_queue = []
        self._calibration_backup_all_nodes_current_sa = None
        self._calibration_backup_all_nodes_original_target_sa = None
        self._calibration_backup_all_nodes_reference_sa = None

        if len(values_by_sa) <= 0:
            self._append_log("Калибровка: резервная копия не сохранена, данные по узлам не получены.", RowColor.red)
            self.infoMessage.emit("Калибровка", "Не удалось получить данные для резервной копии.")
            return

        try:
            csv_path = self._write_calibration_backup_all_nodes_csv(values_by_sa)
        except Exception as exc:
            self._append_log(f"Калибровка: ошибка записи CSV резервной копии: {str(exc)}", RowColor.red)
            self.infoMessage.emit("Калибровка", f"Не удалось сохранить CSV резервной копии: {str(exc)}")
            return

        if reference_sa is not None:
            ref_values = values_by_sa.get(int(reference_sa) & 0xFF, {})
            did0, did100, _, _ = self._calibration_backup_all_nodes_required_dids()
            if did0 in ref_values and did100 in ref_values:
                self._calibration_backup_level_0 = int(ref_values[did0])
                self._calibration_backup_level_100 = int(ref_values[did100])
                self._calibration_backup_available = True
                self.calibrationBackupChanged.emit()

        self._calibration_backup_all_nodes_file_path = str(csv_path)
        self._append_log(f"Калибровка: резервная копия всех узлов сохранена в {csv_path}.", RowColor.green)
        self.infoMessage.emit("Калибровка", f"CSV копий сохранен: {csv_path}")

    def _request_next_calibration_backup_all_nodes_node(self):
        """Цель функции в пошаговом опросе узлов, затем она отправляет чтение DID 0x0012/0x0013/0x001B/0x001C для очередного SA."""
        if not bool(self._calibration_backup_all_nodes_active):
            return

        if len(self._calibration_backup_all_nodes_queue) <= 0:
            self._finish_calibration_backup_all_nodes()
            return

        next_sa = int(self._calibration_backup_all_nodes_queue.pop(0)) & 0xFF
        self._calibration_backup_all_nodes_current_sa = next_sa
        self._calibration_target_node_sa = next_sa
        self._calibration_backup_all_nodes_values_by_sa.setdefault(next_sa, {})
        self._calibration_backup_pending = False
        self._calibration_backup_values_pending = {}

        tx_identifier = self._build_calibration_tx_identifier()
        requested_dids = self._calibration_backup_all_nodes_required_dids()
        for did in requested_dids:
            target_var = UdsData.get_var_by_pid(did)
            if target_var is None:
                continue
            self._calibration_read_service.read_data_by_identifier(tx_identifier, target_var)

        self._append_log(
            f"Калибровка: чтение копии для узла 0x{next_sa:02X} (0%/100%/K1/K0).",
            RowColor.blue,
        )
        self._calibration_backup_all_nodes_step_timer.start()

    def _on_calibration_backup_all_nodes_step_timeout(self):
        """Цель функции в защите от зависания шага копирования, затем она переходит к следующему узлу при таймауте ответа."""
        if not bool(self._calibration_backup_all_nodes_active):
            return
        current_sa = self._calibration_backup_all_nodes_current_sa
        if current_sa is None:
            return
        self._append_log(
            f"Калибровка: таймаут чтения копии для узла 0x{int(current_sa) & 0xFF:02X}, переход к следующему.",
            RowColor.yellow,
        )
        self._request_next_calibration_backup_all_nodes_node()

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
        auto_stage = str(getattr(self, "_post_program_version_write_stage", "") or "")
        if pending_action == "session":
            message = "Таймаут ожидания ответа на Session Control 0x10."
        elif pending_action == "security_seed":
            message = "Таймаут ожидания seed на Security Access 0x27."
        else:
            message = "Таймаут ожидания подтверждения key на Security Access 0x27."
        self._reset_service_access_state(message)
        self._append_log(message, RowColor.red)
        if bool(getattr(self, "_post_program_version_write_pending", False)) and auto_stage in ("wait_session", "wait_security"):
            self._finish_post_program_version_write(False, message)

    def _resolve_source_address_operation_target_sa(self) -> int:
        # Держим SA-операции на том же узле, где уже запускались сервисные операции 0x10/0x27.
        if self._service_access_target_sa is not None:
            return int(self._service_access_target_sa) & 0xFF
        return int(self._resolve_options_target_sa()) & 0xFF

    @staticmethod
    def _communication_control_mode_value_for_index(index: int) -> int:
        """Цель функции в нормализации индекса режима 0x28, затем она возвращает подфункцию управления RX/TX."""
        normalized = int(index)
        if normalized < 0:
            return 0
        if normalized > 3:
            return 3
        return normalized

    @staticmethod
    def _communication_control_type_value_for_index(index: int) -> int:
        """Цель функции в нормализации типа сообщений 0x28, затем она возвращает CommunicationType по ISO."""
        if int(index) == 0:
            return 0x01
        if int(index) == 1:
            return 0x02
        return 0x03

    def _build_communication_control_tx_identifier(self, target_sa: int) -> int:
        """Цель функции в выборе физической или функциональной адресации 0x28, затем она формирует CAN ID запроса."""
        if int(self._selected_communication_control_addressing_index) == 1:
            tx_identifier = int(UdsIdentifiers.tx.identifier)
            priority = (tx_identifier >> 26) & 0x07
            source_address = tx_identifier & 0xFF
            return int((priority << 26) | (0xDBFF << 8) | source_address)
        return self._build_options_tx_identifier(target_sa)

    def _communication_control_expected_functional_sas(self) -> set[int]:
        """Цель функции в расчете ожидаемых ответов на functional 0x28, затем она возвращает только реально найденные SA."""
        expected: set[int] = set()
        tester_sas = {
            int(UdsIdentifiers.tx.src) & 0xFF,
            int(UdsIdentifiers.rx.dst) & 0xFF,
        }

        def add_sa(raw_value):
            try:
                node_sa = int(raw_value) & 0xFF
            except (TypeError, ValueError):
                return
            if node_sa in tester_sas:
                return
            expected.add(node_sa)

        for raw_value in list(self._observed_candidate_values):
            add_sa(raw_value)
        for raw_value in list(self._collector_node_order):
            add_sa(raw_value)

        return expected

    def _set_communication_control_busy(self, busy: bool):
        """Цель функции в переключении состояния операции 0x28, затем она обновляет UI-флаги занятости."""
        value = bool(busy)
        if self._communication_control_busy == value:
            return
        self._communication_control_busy = value
        self.protocolControlChanged.emit()

    def _set_communication_control_status(self, status_text: str):
        """Цель функции в обновлении статуса 0x28, затем она отправляет новое текстовое состояние в UI."""
        value = str(status_text or "").strip()
        if self._communication_control_status == value:
            return
        self._communication_control_status = value
        self.protocolControlChanged.emit()

    def _reset_communication_control_state(self, status_text: str | None = None):
        """Цель функции в сбросе промежуточного состояния 0x28, затем она очищает ожидания ответа и таймер."""
        if self._communication_control_timeout_timer.isActive():
            self._communication_control_timeout_timer.stop()
        self._communication_control_pending_target_sa = None
        self._communication_control_pending_sub_function = None
        self._communication_control_pending_suppress = False
        self._communication_control_pending_functional = False
        self._communication_control_expected_response_sas = set()
        self._communication_control_functional_response_sas = set()
        self._set_communication_control_busy(False)
        if status_text is not None:
            self._set_communication_control_status(status_text)

    def _on_communication_control_timeout(self):
        """Цель функции в обработке таймаута 0x28, затем она завершает операцию с учетом подавления положительного ответа."""
        if not self._communication_control_busy:
            return
        pending_suppress = bool(self._communication_control_pending_suppress)
        if pending_suppress:
            target_sa = self._communication_control_pending_target_sa
            self._reset_communication_control_state(
                "Команда 0x28 отправлена без положительного ответа МК, подтверждение ожидаемо не приходит."
            )
            if target_sa is not None:
                self._append_log(
                    f"SID 0x28: положительный ответ не ожидался (бит 0x80 включен), узел 0x{int(target_sa) & 0xFF:02X}.",
                    RowColor.green,
                )
            return

        if bool(self._communication_control_pending_functional):
            response_sas = sorted(int(item) & 0xFF for item in self._communication_control_functional_response_sas)
            expected_sas = sorted(int(item) & 0xFF for item in self._communication_control_expected_response_sas)
            missing_sas = [item for item in expected_sas if item not in response_sas]
            if len(response_sas) > 0:
                response_text = ", ".join(f"0x{item:02X}" for item in response_sas)
                expected_text = f"/{len(expected_sas)}" if len(expected_sas) > 0 else ""
                missing_text = ""
                if len(missing_sas) > 0:
                    missing_text = " Не ответили: " + ", ".join(f"0x{item:02X}" for item in missing_sas) + "."
                self._reset_communication_control_state(
                    f"Функциональный SID 0x28 завершен: подтверждений {len(response_sas)}{expected_text}, ответили узлы {response_text}.{missing_text}"
                )
                self._append_log(
                    f"SID 0x28: функциональная команда принята, ответили узлы {response_text}.{missing_text}",
                    RowColor.yellow if len(missing_sas) > 0 else RowColor.green,
                )
                return

            self._reset_communication_control_state("Функциональный SID 0x28 отправлен, но ответы от узлов не пришли.")
            self._append_log("SID 0x28: функциональный запрос без ответов от узлов.", RowColor.yellow)
            return

        self._reset_communication_control_state("Таймаут ожидания ответа на SID 0x28.")
        self._append_log("SID 0x28: таймаут ожидания ответа.", RowColor.red)

    @Slot(int)
    def setSelectedCommunicationControlModeIndex(self, index):
        """Цель функции в выборе режима управления RX/TX, затем она сохраняет подфункцию SID 0x28 для отправки."""
        try:
            parsed = int(index)
        except (TypeError, ValueError):
            return
        if parsed < 0 or parsed >= len(self._communication_control_mode_items):
            return
        if parsed == self._selected_communication_control_mode_index:
            return
        self._selected_communication_control_mode_index = parsed
        self.protocolControlChanged.emit()

    @Slot(int)
    def setSelectedCommunicationControlAddressingIndex(self, index):
        """Цель функции в выборе адресации SID 0x28, затем она сохраняет физический или функциональный CAN ID."""
        try:
            parsed = int(index)
        except (TypeError, ValueError):
            return
        if parsed < 0 or parsed >= len(self._communication_control_addressing_items):
            return
        if parsed == self._selected_communication_control_addressing_index:
            return
        self._selected_communication_control_addressing_index = parsed
        self.protocolControlChanged.emit()

    @Slot(int)
    def setSelectedCommunicationControlTypeIndex(self, index):
        """Цель функции в выборе CommunicationType, затем она сохраняет тип сообщений для запроса SID 0x28."""
        try:
            parsed = int(index)
        except (TypeError, ValueError):
            return
        if parsed < 0 or parsed >= len(self._communication_control_type_items):
            return
        if parsed == self._selected_communication_control_type_index:
            return
        self._selected_communication_control_type_index = parsed
        self.protocolControlChanged.emit()

    @Slot(bool)
    def setCommunicationControlSuppressPositiveResponse(self, enabled):
        """Цель функции в переключении подавления положительного ответа, затем она сохраняет бит 0x80 подфункции."""
        value = bool(enabled)
        if self._communication_control_suppress_positive_response == value:
            return
        self._communication_control_suppress_positive_response = value
        self.protocolControlChanged.emit()

    @Slot()
    def applyCommunicationControl(self):
        """Цель функции в отправке запроса SID 0x28, затем она запускает ожидание ответа и обновляет статус оператора."""
        if self._communication_control_busy:
            self.infoMessage.emit("Протокол", "Операция CommunicationControl уже выполняется.")
            return

        if self._programming_active or self._options_busy or self._options_bulk_busy or self._source_address_busy or self._calibration_active:
            self.infoMessage.emit("Протокол", "Завершите активную UDS операцию перед отправкой SID 0x28.")
            return

        if self._service_access_busy:
            self.infoMessage.emit("Протокол", "Дождитесь завершения Session/Security Access перед SID 0x28.")
            return

        if not self._can.is_connect or not self._can.is_trace:
            self.infoMessage.emit("Протокол", "Сначала подключите адаптер и запустите трассировку CAN.")
            return

        control_type = self._communication_control_mode_value_for_index(self._selected_communication_control_mode_index)
        communication_type = self._communication_control_type_value_for_index(self._selected_communication_control_type_index)
        suppress_positive = bool(self._communication_control_suppress_positive_response)
        target_sa = int(self._resolve_source_address_operation_target_sa()) & 0xFF
        tx_identifier = self._build_communication_control_tx_identifier(target_sa)
        functional_addressing = int(self._selected_communication_control_addressing_index) == 1
        addressing_text = "функционально" if functional_addressing else "физически"

        self._communication_control_pending_target_sa = target_sa
        self._communication_control_pending_sub_function = int(control_type) & 0x7F
        self._communication_control_pending_suppress = suppress_positive
        self._communication_control_pending_functional = functional_addressing
        self._communication_control_expected_response_sas = (
            self._communication_control_expected_functional_sas() if functional_addressing else {target_sa}
        )
        self._communication_control_functional_response_sas = set()
        self._set_communication_control_busy(True)
        target_text = "всем известным узлам"
        if functional_addressing:
            expected_sas = sorted(int(item) & 0xFF for item in self._communication_control_expected_response_sas)
            if len(expected_sas) > 0:
                target_text = "всем узлам, ожидаемые ответы: " + ", ".join(f"0x{item:02X}" for item in expected_sas)
            else:
                target_text = "всем узлам, список известных SA пуст"
        else:
            target_text = f"SA 0x{target_sa:02X}"
        self._set_communication_control_status(
            f"SID 0x28 отправлен {addressing_text}: sub=0x{int(control_type) & 0x7F:02X}, type=0x{int(communication_type) & 0xFF:02X}, {target_text}."
        )
        self._append_log(
            (
                f"SID 0x28: запрос sub=0x{int(control_type) & 0x7F:02X}, "
                f"type=0x{int(communication_type) & 0xFF:02X}, SPR={1 if suppress_positive else 0}, "
                f"адресация={addressing_text}, CAN ID=0x{int(tx_identifier) & 0x1FFFFFFF:08X}, {target_text}."
            ),
            RowColor.blue,
        )

        if not self._communication_control_service.request(
            control_type=control_type,
            communication_type=communication_type,
            suppress_positive_response=suppress_positive,
            tx_identifier=tx_identifier,
        ):
            self._reset_communication_control_state("Ошибка отправки SID 0x28.")
            self.infoMessage.emit("Протокол", "Не удалось отправить команду CommunicationControl.")
            return

        if suppress_positive:
            timeout_ms = 900
        elif functional_addressing:
            expected_count = max(1, len(self._communication_control_expected_response_sas))
            timeout_ms = max(2200, min(5000, 1200 + expected_count * 450))
        else:
            timeout_ms = 1800
        self._communication_control_timeout_timer.start(timeout_ms)

    @Slot()
    def applyCommunicationControlEnableAll(self):
        """Цель функции в быстром возврате штатной связи, затем она отправляет режим RX/TX включены для SID 0x28."""
        self._selected_communication_control_mode_index = 0
        self._selected_communication_control_type_index = 0
        self._communication_control_suppress_positive_response = False
        self.protocolControlChanged.emit()
        self.applyCommunicationControl()

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
    def setSelectedProgrammingNodeIndex(self, index):
        """Цель функции в выборе узла прошивки, затем она сразу настраивает UDS ID под этот SA."""
        if self._programming_active or self._programming_batch_active:
            self.infoMessage.emit("Программирование", "Нельзя менять целевой узел во время программирования.")
            return

        try:
            parsed_index = int(index)
        except (TypeError, ValueError):
            return

        if parsed_index < 0 or parsed_index >= len(self._programming_node_values):
            return

        self._selected_programming_node_index = parsed_index
        target_sa = int(self._programming_node_values[parsed_index]) & 0xFF
        self._apply_programming_target_sa(target_sa, "Настройки UDS обновлены после выбора узла.")
        self.programmingNodeSelectionChanged.emit()

    @Slot()
    def refreshProgrammingNodeList(self):
        """Цель функции в ручном обновлении списка узлов прошивки, затем она перечитывает накопленные CAN-кандидаты."""
        self._refresh_programming_node_options()
        self.infoMessage.emit("Программирование", "Список узлов обновлен по принятым CAN/J1939 кадрам.")

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

        # Для DID-сервисов UDS проекта всегда используется стандартный big-endian порядок DID.
        # Переключатель порядка байтов применяется только к передаче прошивки в bootloader.
        self._calibration_read_service.set_byte_order("big")
        self._calibration_write_service.set_byte_order("big")
        self._collector_read_service.set_byte_order("big")
        self._options_read_service.set_byte_order("big")
        self._options_write_service.set_byte_order("big")
        self._source_address_read_service.set_byte_order("big")
        self._source_address_write_service.set_byte_order("big")

        label = "Little Endian" if new_index == 1 else "Big Endian"
        self._append_log(f"Выбран порядок байтов передачи прошивки: {label}. DID-сервисы UDS фиксированы в Big Endian.", QColor("#0ea5e9"))
        self.infoMessage.emit("Протокол", f"Порядок байтов для прошивки: {label}. DID-сервисы UDS работают в Big Endian.")

    @Slot(int)
    def setSelectedCalibrationNodeIndex(self, index):
        """Цель функции в выборе целевого узла калибровки, затем она переключает SA для UDS-команд блока калибровки."""
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

    @Slot(int)
    def setSelectedCalibrationTempCompDatasetIndex(self, index):
        """Цель функции в выборе набора CSV для офлайн-анализа, затем она пересчитывает графики и метрики по выбранному узлу."""
        try:
            parsed_index = int(index)
        except (TypeError, ValueError):
            return

        if parsed_index < 0 or parsed_index >= len(self._calibration_temp_comp_dataset_values):
            return

        selected_sa = int(self._calibration_temp_comp_dataset_values[parsed_index]) & 0xFF
        if (
            self._selected_calibration_temp_comp_dataset_index == parsed_index
            and len(self._calibration_temp_comp_samples) > 0
        ):
            return

        self._selected_calibration_temp_comp_dataset_index = parsed_index
        self.calibrationTempCompChanged.emit()

        self._set_calibration_temp_comp_operation_status(
            f"Переключение набора CSV на узел 0x{selected_sa:02X}...",
            busy=True,
            progress_percent=0,
            determinate=False,
        )
        QCoreApplication.processEvents()

        if not self._apply_calibration_temp_comp_node_samples(
            selected_sa,
            clear_coefficients=False,
        ):
            self._set_calibration_temp_comp_operation_status(
                f"Переключение набора CSV завершено с ошибкой: данные узла 0x{selected_sa:02X} недоступны.",
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            self._append_log(
                f"Калибровка: не удалось применить набор CSV для узла 0x{selected_sa:02X}.",
                RowColor.red,
            )
            return

        self._set_calibration_temp_comp_operation_status(
            f"Переключение набора CSV завершено: активен узел 0x{selected_sa:02X}.",
            busy=False,
            progress_percent=100,
            determinate=True,
        )
        self._append_log(
            f"Калибровка: выбран набор CSV для узла 0x{selected_sa:02X}.",
            RowColor.blue,
        )

    @Slot()
    def toggleCalibration(self):
        """Цель функции в удобном запуске/остановке калибровки, затем она переключает сценарий одной кнопкой."""
        if self._calibration_active:
            self.stopCalibration()
            return
        self.startCalibration()

    @Slot()
    def startCalibration(self):
        """Цель функции в запуске сессии калибровки, затем она поднимает Extended Session и автоцепочку Security Access."""
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
        self._calibration_runtime_target_sa = None
        self._reset_calibration_temp_comp_state(clear_samples=False, clear_coefficients=False)
        self.calibrationStateChanged.emit()
        self._reset_calibration_wizard_state()
        self._reset_calibration_sequence_state()
        self._calibration_level_0_known = False
        self._calibration_level_100_known = False
        self._calibration_waiting_session = True
        self._start_calibration_sequence_wait("activate_session")
        tx_identifier = self._build_calibration_tx_identifier()
        resolved_sa = int(self._resolve_calibration_target_sa()) & 0xFF
        self._calibration_session_service.set(Session.EXTENDED, tx_identifier)
        self._append_log(
            (
                "Калибровка: запрос расширенной сессии UDS "
                f"(режим: {self.calibrationSelectedNodeText}, SA: 0x{resolved_sa:02X}, TX: 0x{int(tx_identifier) & 0x1FFFFFFF:08X})."
            ),
            RowColor.blue,
        )

    @Slot()
    def stopCalibration(self):
        """Цель функции в корректном завершении калибровки, затем она возвращает МК в default-сессию."""
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
        """Цель функции в ручном чтении периода, затем она отправляет DID 0x0014 в выбранный узел."""
        if not self._can.is_connect or not self._can.is_trace:
            return
        self._configure_calibration_uds_services()
        self._calibration_read_service.read_data_by_identifier(self._build_calibration_tx_identifier(), UdsData.curr_fuel_tank)

    @Slot()
    def readCalibrationLevel0(self):
        """Цель функции в чтении калибровки 0%, затем она отправляет DID 0x0012 через текущий UDS маршрут."""
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
        """Цель функции в чтении калибровки 100%, затем она отправляет DID 0x0013 через текущий UDS маршрут."""
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return
        if not self._can.is_trace:
            self.infoMessage.emit("Калибровка", "Сначала включите трассировку CAN.")
            return
        self._configure_calibration_uds_services()
        self._calibration_read_service.read_data_by_identifier(self._build_calibration_tx_identifier(), UdsData.full_fuel_tank)
        self._append_log("Калибровка: чтение уровня 100%.", RowColor.blue)

    @Slot()
    def clearCalibrationTempCompSamples(self):
        """Цель функции в очистке анализируемой выборки, затем она удаляет собранные точки без сброса текущих K1/K0."""
        self._set_calibration_temp_comp_operation_status(
            "Очистка офлайн-данных и сброс графиков...",
            busy=True,
            progress_percent=0,
            determinate=False,
        )
        QCoreApplication.processEvents()
        self._reset_calibration_temp_comp_state(
            clear_samples=True,
            clear_coefficients=False,
            clear_cached_nodes=True,
        )
        self._set_calibration_temp_comp_operation_status(
            "Очистка завершена: графики и метрики сброшены.",
            busy=False,
            progress_percent=100,
            determinate=True,
        )
        self._append_log("Калибровка: точки температурной компенсации очищены.", RowColor.blue)

    @Slot()
    def readCalibrationTempCompK1(self):
        """Цель функции в чтении коэффициента компенсации, затем она отправляет запрос DID 0x001B."""
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return
        if not self._can.is_trace:
            self.infoMessage.emit("Калибровка", "Сначала включите трассировку CAN.")
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: последовательное чтение расширенных DID остановлено для чтения K1.",
                RowColor.yellow,
            )

        if not self._request_calibration_temp_comp_k1_read():
            self.infoMessage.emit("Калибровка", "Не удалось отправить чтение DID 0x001B.")
            return

        self._append_log("Калибровка: чтение коэффициента K1 (DID 0x001B).", RowColor.blue)

    @Slot()
    def readCalibrationTempCompK0(self):
        """Цель функции в чтении коэффициента смещения, затем она отправляет запрос DID 0x001C."""
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return
        if not self._can.is_trace:
            self.infoMessage.emit("Калибровка", "Сначала включите трассировку CAN.")
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: последовательное чтение расширенных DID остановлено для чтения K0.",
                RowColor.yellow,
            )

        if not self._request_calibration_temp_comp_k0_read():
            self.infoMessage.emit("Калибровка", "Не удалось отправить чтение DID 0x001C.")
            return

        self._append_log("Калибровка: чтение коэффициента K0 (DID 0x001C).", RowColor.blue)

    @Slot()
    def readCalibrationTempCompZeroTrim(self):
        """Цель функции в чтении коррекции zero trim, затем она отправляет прямой запрос DID 0x002D."""
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return
        if not self._can.is_trace:
            self.infoMessage.emit("Калибровка", "Сначала включите трассировку CAN.")
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: последовательное чтение расширенных DID остановлено для чтения zero trim.",
                RowColor.yellow,
            )

        if not self._request_calibration_temp_comp_zero_trim_read():
            self.infoMessage.emit("Калибровка", "Не удалось отправить чтение DID 0x002D.")
            return

        self._append_log("Калибровка: чтение коррекции zero trim (DID 0x002D).", RowColor.blue)

    @Slot()
    def autoAdjustCalibrationTempCompK0ForCurrentPoint(self):
        """Цель функции в автоподстройке K0 по фактическому выходу МК, затем она читает 0x0012/0x0013/0x0018/0x001C и записывает рассчитанный DID 0x001C."""
        if not self._ensure_calibration_write_ready("автоподстройка K0 к 0%"):
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: последовательное чтение расширенных DID остановлено для автоподстройки K0.",
                RowColor.yellow,
            )

        if len(self._calibration_write_verify_pending) > 0:
            self.infoMessage.emit(
                "Калибровка",
                "Дождитесь завершения текущей автопроверки DID перед автоподстройкой K0.",
            )
            return
        if bool(self._calibration_temp_comp_zero_trim_air_zero_adjust_active):
            self.infoMessage.emit(
                "Калибровка",
                "Сначала дождитесь завершения автоподстройки zero trim.",
            )
            return

        self._calibration_temp_comp_k0_air_zero_adjust_active = True
        self._calibration_temp_comp_k0_air_zero_adjust_empty_period = None
        self._calibration_temp_comp_k0_air_zero_adjust_full_period = None
        self._calibration_temp_comp_k0_air_zero_adjust_level_x10 = None
        self._calibration_temp_comp_k0_air_zero_adjust_current_k0 = None

        if not self._request_next_calibration_temp_comp_k0_air_zero_adjust_did():
            self._reset_calibration_temp_comp_k0_air_zero_adjust_state()
            self._set_calibration_temp_comp_operation_status(
                "Автоподстройка K0 не запущена: не удалось отправить первый DID-запрос.",
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            self.infoMessage.emit(
                "Калибровка",
                "Не удалось отправить первый DID-запрос для автоподстройки K0.",
            )
            return

        self._set_calibration_temp_comp_operation_status(
            "Автоподстройка K0: последовательное чтение DID 0x0012 -> 0x0013 -> 0x0018 -> 0x001C...",
            busy=True,
            progress_percent=0,
            determinate=False,
        )
        self._append_log(
            "Калибровка: запуск автоподстройки K0 по фактическому выходу МК (DID 0x0012/0x0013/0x0018/0x001C).",
            RowColor.blue,
        )

    @Slot()
    def autoAdjustCalibrationTempCompZeroTrimForCurrentPoint(self):
        """Цель функции в автоподстройке zero trim по фактическому выходу МК, затем она читает 0x0012/0x0013/0x0018/0x002D и записывает рассчитанный DID 0x002D."""
        if not self._ensure_calibration_write_ready("автоподстройка zero trim к 0%"):
            return

        if len(self._calibration_temp_comp_recommendation_apply_queue) > 0:
            self.infoMessage.emit(
                "Калибровка",
                "Дождитесь завершения пакетной записи рекомендаций K1/K0 перед автоподгонкой zero trim.",
            )
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: последовательное чтение расширенных DID остановлено для автоподстройки zero trim.",
                RowColor.yellow,
            )

        if len(self._calibration_write_verify_pending) > 0:
            self.infoMessage.emit(
                "Калибровка",
                "Дождитесь завершения текущей автопроверки DID перед автоподстройкой zero trim.",
            )
            return
        if bool(self._calibration_temp_comp_k0_air_zero_adjust_active):
            self.infoMessage.emit(
                "Калибровка",
                "Сначала дождитесь завершения автоподстройки K0.",
            )
            return

        self._calibration_temp_comp_zero_trim_air_zero_adjust_active = True
        self._calibration_temp_comp_zero_trim_air_zero_adjust_empty_period = None
        self._calibration_temp_comp_zero_trim_air_zero_adjust_full_period = None
        self._calibration_temp_comp_zero_trim_air_zero_adjust_level_x10 = None
        self._calibration_temp_comp_zero_trim_air_zero_adjust_level_samples = []
        self._calibration_temp_comp_zero_trim_air_zero_adjust_current_zero_trim = None

        if not self._request_next_calibration_temp_comp_zero_trim_air_zero_adjust_did():
            self._reset_calibration_temp_comp_zero_trim_air_zero_adjust_state()
            self._set_calibration_temp_comp_operation_status(
                "Автоподстройка zero trim не запущена: не удалось отправить первый DID-запрос.",
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            self.infoMessage.emit(
                "Калибровка",
                "Не удалось отправить первый DID-запрос для автоподстройки zero trim.",
            )
            return

        self._set_calibration_temp_comp_operation_status(
            "Автоподстройка zero trim: последовательное чтение DID 0x0012 -> 0x0013 -> 0x0018 -> 0x002D...",
            busy=True,
            progress_percent=0,
            determinate=False,
        )
        self._append_log(
            "Калибровка: запуск автоподстройки zero trim по фактическому выходу МК (DID 0x0012/0x0013/0x0018/0x002D).",
            RowColor.blue,
        )

    @Slot()
    def readCalibrationTempCompFromMcu(self):
        """Цель функции в чтении параметров компенсации из МК, затем она выполняет последовательный опрос K1/K0/zero trim и DID текущего режима."""
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            self._set_calibration_temp_comp_operation_status(
                "Чтение параметров из МК не запущено: адаптер не подключен.",
                busy=False,
                progress_percent=0,
                determinate=False,
            )
            return
        if not self._can.is_trace:
            self.infoMessage.emit("Калибровка", "Сначала включите трассировку CAN.")
            self._set_calibration_temp_comp_operation_status(
                "Чтение параметров из МК не запущено: трассировка CAN выключена.",
                busy=False,
                progress_percent=0,
                determinate=False,
            )
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: предыдущая очередь чтения DID остановлена перед новым запуском.",
                RowColor.yellow,
            )

        mode_known = self._calibration_temp_comp_advanced_values.get("mode") is not None
        mode_value = self._temp_comp_get_mode_from_values(self._calibration_temp_comp_advanced_values)
        mode_text = self._temp_comp_mode_text(mode_value)
        queued_count, total_count = self._request_calibration_temp_comp_advanced_read_for_mode(
            mode_value,
            include_base=True,
        )
        if total_count <= 0 or queued_count <= 0:
            self.infoMessage.emit("Калибровка", "Не удалось отправить чтение параметров температурной компенсации.")
            self._set_calibration_temp_comp_operation_status(
                "Чтение параметров из МК не запущено: очередь DID не сформирована.",
                busy=False,
                progress_percent=0,
                determinate=False,
            )
            return

        if not mode_known:
            self._append_log(
                "Калибровка: mode до чтения не был известен, поэтому использован базовый профиль mode 0; DID 0x001D уточнит фактический режим и очередь автоматически подстроится.",
                RowColor.yellow,
            )

        self._append_log(
            (
                "Калибровка: запущено чтение параметров температурной компенсации по режиму "
                f"{mode_text} ({queued_count} DID, включая K1/K0/zero trim)."
            ),
            RowColor.blue,
        )
        self.infoMessage.emit(
            "Калибровка",
            f"Запущено последовательное чтение {queued_count} DID по режиму {mode_text}, включая K1/K0/zero trim.",
        )

    @Slot()
    def readCalibrationTempCompAdvanced(self):
        """Цель функции в чтении расширенных параметров компенсации, затем она запрашивает DID 0x001D..0x002C."""
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            self._set_calibration_temp_comp_operation_status(
                "Чтение параметров из МК не запущено: адаптер не подключен.",
                busy=False,
                progress_percent=0,
                determinate=False,
            )
            return
        if not self._can.is_trace:
            self.infoMessage.emit("Калибровка", "Сначала включите трассировку CAN.")
            self._set_calibration_temp_comp_operation_status(
                "Чтение параметров из МК не запущено: трассировка CAN выключена.",
                busy=False,
                progress_percent=0,
                determinate=False,
            )
            return

        queued_count, total_count = self._request_calibration_temp_comp_advanced_read_all()
        if total_count <= 0 or queued_count <= 0:
            self.infoMessage.emit("Калибровка", "Не удалось отправить чтение расширенных DID 0x001D..0x002C.")
            self._set_calibration_temp_comp_operation_status(
                "Чтение параметров из МК не запущено: не удалось сформировать очередь DID 0x001D..0x002C.",
                busy=False,
                progress_percent=0,
                determinate=False,
            )
            return

        self._append_log(
            (
                "Калибровка: запущено последовательное чтение расширенных DID "
                f"0x001D..0x002C ({queued_count} параметров)."
            ),
            RowColor.blue,
        )
        self.infoMessage.emit(
            "Калибровка",
            f"Запущено последовательное чтение {queued_count} параметров. Дождитесь завершения в журнале.",
        )

    @Slot(str)
    def readCalibrationTempCompAdvancedParam(self, field_key):
        """Цель функции в чтении одного расширенного параметра, затем она отправляет DID по ключу строки UI."""
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return
        if not self._can.is_trace:
            self.infoMessage.emit("Калибровка", "Сначала включите трассировку CAN.")
            return

        field = self._temp_comp_advanced_field_by_key(str(field_key))
        if field is None:
            self.infoMessage.emit("Калибровка", "Неизвестный параметр температурной компенсации.")
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: последовательное чтение расширенных DID остановлено для одиночного запроса.",
                RowColor.yellow,
            )

        if not self._request_calibration_temp_comp_advanced_read(str(field.get("key", ""))):
            field_var = field.get("var")
            did_text = "----" if field_var is None else f"0x{int(field_var.pid) & 0xFFFF:04X}"
            self.infoMessage.emit("Калибровка", f"Не удалось отправить чтение DID {did_text}.")
            return

        self._append_log(
            f"Калибровка: чтение {self._temp_comp_field_display_name(field)}.",
            RowColor.blue,
        )

    @Slot(str, str)
    def setCalibrationTempCompAdvancedPreviewValue(self, field_key, value_text):
        """Цель функции в локальном предпросмотре параметра, затем она пересчитывает график и метрики без записи в МК."""
        field = self._temp_comp_advanced_field_by_key(str(field_key))
        if field is None:
            return

        target_key = str(field.get("key", ""))
        if not target_key:
            return

        current_value = self._calibration_temp_comp_advanced_values.get(target_key)
        try:
            preview_value = self._resolve_calibration_temp_comp_advanced_write_value(
                field,
                value_text,
                current_value,
            )
        except ValueError:
            return

        normalized_value = int(preview_value)
        if current_value is not None and int(current_value) == normalized_value:
            return

        if bool(self._calibration_temp_comp_linear_preview_enabled):
            self._calibration_temp_comp_linear_preview_enabled = False
            self._calibration_temp_comp_linear_preview_k1_x100 = None
            self._calibration_temp_comp_linear_preview_k0_count = None
            self._set_calibration_temp_comp_preview_status(
                "Линейное превью отключено: применяются ручные параметры режима компенсации.",
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            self._append_log(
                "Калибровка: линейное превью отключено, чтобы пересчет учитывал выбранный mode/segment/heat-cool.",
                RowColor.blue,
            )

        if target_key == "mode":
            self._seed_temp_comp_segment_tables_for_preview(int(normalized_value))

        self._set_calibration_temp_comp_operation_status(
            "Пересчет графиков по выбранным параметрам...",
            busy=True,
            progress_percent=0,
            determinate=False,
        )
        QCoreApplication.processEvents()
        self._calibration_temp_comp_advanced_values[target_key] = int(normalized_value)
        self._recompute_calibration_temp_comp_metrics()
        self._set_calibration_temp_comp_operation_status(
            "Пересчет графиков завершен.",
            busy=False,
            progress_percent=100,
            determinate=True,
        )

    @Slot(str, str)
    def setCalibrationTempCompLinearPreview(self, k1_text, k0_text):
        """Цель функции в локальном предпросмотре линейного режима, затем она применяет K1/K0 к графику без записи в МК."""
        if len(self._calibration_temp_comp_samples) <= 0:
            self._set_calibration_temp_comp_preview_status(
                "Нет данных для превью. Сначала загрузите CSV.",
                busy=False,
                progress_percent=0,
                determinate=True,
            )
            self.infoMessage.emit(
                "Калибровка",
                "Для предпросмотра сначала загрузите CSV с данными температурной компенсации.",
            )
            return

        fallback_k1 = self._calibration_temp_comp_linear_preview_k1_x100
        if fallback_k1 is None:
            if self._calibration_temp_comp_k1_x100_current is not None:
                fallback_k1 = int(self._calibration_temp_comp_k1_x100_current)
            elif self._calibration_temp_comp_k1_x100_base is not None:
                fallback_k1 = int(self._calibration_temp_comp_k1_x100_base)
            else:
                fallback_k1 = 0

        fallback_k0 = self._calibration_temp_comp_linear_preview_k0_count
        if fallback_k0 is None:
            if self._calibration_temp_comp_k0_count_current is not None:
                fallback_k0 = int(self._calibration_temp_comp_k0_count_current)
            elif self._calibration_temp_comp_k0_count_base is not None:
                fallback_k0 = int(self._calibration_temp_comp_k0_count_base)
            else:
                fallback_k0 = 0

        try:
            preview_k1 = self._resolve_calibration_k1_write_value(k1_text, int(fallback_k1))
            preview_k0 = self._resolve_calibration_k0_write_value(k0_text, int(fallback_k0))
        except ValueError as exc:
            self._set_calibration_temp_comp_preview_status(
                "Ошибка ввода коэффициентов превью.",
                busy=False,
                progress_percent=0,
                determinate=True,
            )
            self.infoMessage.emit("Калибровка", str(exc))
            return

        normalized_k1 = int(preview_k1)
        normalized_k0 = int(preview_k0)
        unchanged = (
            bool(self._calibration_temp_comp_linear_preview_enabled)
            and self._calibration_temp_comp_linear_preview_k1_x100 is not None
            and self._calibration_temp_comp_linear_preview_k0_count is not None
            and int(self._calibration_temp_comp_linear_preview_k1_x100) == normalized_k1
            and int(self._calibration_temp_comp_linear_preview_k0_count) == normalized_k0
        )
        if unchanged:
            self._set_calibration_temp_comp_preview_status(
                "Превью уже применено с этими K1/K0.",
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            return

        self._set_calibration_temp_comp_operation_status(
            "Пересчет графиков по линейному превью...",
            busy=True,
            progress_percent=0,
            determinate=False,
        )
        self._set_calibration_temp_comp_preview_status(
            "Подготовка параметров превью...",
            busy=True,
            progress_percent=10,
            determinate=True,
        )
        QCoreApplication.processEvents()

        self._calibration_temp_comp_linear_preview_enabled = True
        self._calibration_temp_comp_linear_preview_k1_x100 = int(normalized_k1)
        self._calibration_temp_comp_linear_preview_k0_count = int(normalized_k0)
        self._set_calibration_temp_comp_preview_status(
            "Применение K1/K0 и пересчет метрик...",
            busy=True,
            progress_percent=45,
            determinate=True,
        )
        QCoreApplication.processEvents()
        self._recompute_calibration_temp_comp_metrics()
        self._set_calibration_temp_comp_preview_status(
            "Обновление графика...",
            busy=True,
            progress_percent=85,
            determinate=True,
        )
        QCoreApplication.processEvents()
        self._set_calibration_temp_comp_preview_status(
            f"Превью обновлено: K1={int(normalized_k1)}, K0={int(normalized_k0)}.",
            busy=False,
            progress_percent=100,
            determinate=True,
        )
        self._set_calibration_temp_comp_operation_status(
            "Линейное превью пересчитано.",
            busy=False,
            progress_percent=100,
            determinate=True,
        )

    @Slot()
    def clearCalibrationTempCompLinearPreview(self):
        """Цель функции в сбросе локального превью K1/K0, затем она возвращает графики к текущим считанным параметрам."""
        if (
            (not bool(self._calibration_temp_comp_linear_preview_enabled))
            and self._calibration_temp_comp_linear_preview_k1_x100 is None
            and self._calibration_temp_comp_linear_preview_k0_count is None
        ):
            self._set_calibration_temp_comp_preview_status(
                "Превью уже сброшено.",
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            return

        self._set_calibration_temp_comp_operation_status(
            "Сброс линейного превью и пересчет графиков...",
            busy=True,
            progress_percent=0,
            determinate=False,
        )
        self._set_calibration_temp_comp_preview_status(
            "Сброс превью и восстановление текущих параметров...",
            busy=True,
            progress_percent=20,
            determinate=True,
        )
        QCoreApplication.processEvents()

        self._calibration_temp_comp_linear_preview_enabled = False
        self._calibration_temp_comp_linear_preview_k1_x100 = None
        self._calibration_temp_comp_linear_preview_k0_count = None
        self._set_calibration_temp_comp_preview_status(
            "Пересчет графика после сброса...",
            busy=True,
            progress_percent=65,
            determinate=True,
        )
        QCoreApplication.processEvents()
        self._recompute_calibration_temp_comp_metrics()
        self._set_calibration_temp_comp_preview_status(
            "Превью сброшено. График вернулся к текущим параметрам.",
            busy=False,
            progress_percent=100,
            determinate=True,
        )
        self._set_calibration_temp_comp_operation_status(
            "Линейное превью сброшено.",
            busy=False,
            progress_percent=100,
            determinate=True,
        )

    def _seed_temp_comp_segment_tables_for_preview(self, mode_value: int):
        """Цель функции в подготовке осмысленного предпросмотра mode=1/2, затем она подставляет информативные сегментные таблицы вместо вырожденного linear-профиля."""
        normalized_mode = int(mode_value)
        if normalized_mode not in (
            int(self._TEMP_COMP_MODE_SEGMENTED),
            int(self._TEMP_COMP_MODE_SEGMENTED_HEAT_COOL),
        ):
            return

        current_values = {
            str(key): (None if value is None else int(value))
            for key, value in self._calibration_temp_comp_advanced_values.items()
        }
        linear_k1 = int(self._calibration_temp_comp_k1_x100_current or 0)
        cooling_table, heating_table = self._temp_comp_build_segment_tables_from_values(current_values)
        need_cooling_seed = (
            self._temp_comp_segment_table_is_zero(cooling_table)
            or self._temp_comp_segment_table_is_linear(cooling_table, linear_k1)
        )
        need_heating_seed = (
            normalized_mode == int(self._TEMP_COMP_MODE_SEGMENTED_HEAT_COOL)
            and (
                self._temp_comp_segment_table_is_zero(heating_table)
                or self._temp_comp_segment_table_is_linear(heating_table, linear_k1)
            )
        )
        if not need_cooling_seed and not need_heating_seed:
            return

        recommended_values = {
            str(key): int(value)
            for key, value in self._calibration_temp_comp_advanced_recommended_values.items()
            if value is not None
        }
        has_informative_recommended_values = False
        if len(recommended_values) > 0:
            has_informative_recommended_values = self._temp_comp_values_have_informative_segments(
                {str(key): int(value) for key, value in recommended_values.items()},
                mode_value=normalized_mode,
                linear_k1_x100=linear_k1,
            )
        if (not has_informative_recommended_values) and len(self._calibration_temp_comp_samples) >= 2:
            recommended_values = self._build_temp_comp_advanced_recommendations(
                list(self._calibration_temp_comp_samples),
                fallback_linear_k1_x100=linear_k1,
                forced_mode=normalized_mode,
            )
            if not self._temp_comp_values_have_informative_segments(
                {str(key): int(value) for key, value in recommended_values.items()},
                mode_value=normalized_mode,
                linear_k1_x100=linear_k1,
            ):
                recommended_values = self._build_temp_comp_advanced_recommendations(
                    list(self._calibration_temp_comp_samples),
                    fallback_linear_k1_x100=0,
                    forced_mode=normalized_mode,
                )

        if len(recommended_values) <= 0:
            return

        seeded = False

        if need_cooling_seed:
            for segment_index in range(1, int(self._TEMP_COMP_SEGMENT_COUNT) + 1):
                key = f"k1_cool_seg{segment_index}_x100"
                recommended = recommended_values.get(key)
                if recommended is None:
                    continue
                self._calibration_temp_comp_advanced_values[key] = int(recommended)
                seeded = True

        if need_heating_seed:
            for segment_index in range(1, int(self._TEMP_COMP_SEGMENT_COUNT) + 1):
                key = f"k1_heat_seg{segment_index}_x100"
                recommended = recommended_values.get(key)
                if recommended is None:
                    continue
                self._calibration_temp_comp_advanced_values[key] = int(recommended)
                seeded = True

        support_keys = (
            "dir_hyst_x10",
            "seg_t1_x10",
            "seg_t2_x10",
            "seg_t3_x10",
            "seg_t4_x10",
        )
        for key in support_keys:
            recommended = recommended_values.get(key)
            if recommended is None:
                continue
            self._calibration_temp_comp_advanced_values[key] = int(recommended)
            seeded = True

        if seeded:
            self._append_log(
                "Калибровка: для предпросмотра mode=1/2 подставлены информативные сегментные параметры, чтобы режим не оставался эквивалентным linear K1.",
                RowColor.blue,
            )

    @Slot(str, str)
    def writeCalibrationTempCompAdvancedParam(self, field_key, value_text):
        """Цель функции в записи одного расширенного параметра, затем она валидирует ввод и отправляет UDS 0x2E."""
        if not self._ensure_calibration_write_ready("запись расширенного параметра компенсации"):
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: последовательное чтение расширенных DID остановлено для записи параметра.",
                RowColor.yellow,
            )

        if len(self._calibration_write_verify_pending) > 0:
            self.infoMessage.emit(
                "Калибровка",
                "Дождитесь завершения текущей автопроверки DID перед новой записью.",
            )
            return

        field = self._temp_comp_advanced_field_by_key(str(field_key))
        if field is None:
            self.infoMessage.emit("Калибровка", "Неизвестный параметр температурной компенсации.")
            return

        field_var = field.get("var")
        if field_var is None:
            self.infoMessage.emit("Калибровка", "Выбранный параметр не имеет DID в текущей карте.")
            return

        current_value = self._calibration_temp_comp_advanced_values.get(str(field.get("key", "")))
        try:
            value = self._resolve_calibration_temp_comp_advanced_write_value(field, value_text, current_value)
        except ValueError as exc:
            self.infoMessage.emit("Калибровка", str(exc))
            return

        payload_size_bits = max(8, int(field_var.size) * 8)
        payload_mask = (1 << payload_size_bits) - 1
        write_payload = int(value) & payload_mask
        if self._calibration_write_service.write_data(
            field_var,
            write_payload,
            tx_identifier=self._build_calibration_tx_identifier(),
        ):
            self._calibration_write_verify_pending[int(field_var.pid)] = int(value)
            self.calibrationVerificationChanged.emit()
            self._append_log(
                f"Калибровка: запись {self._temp_comp_field_display_name(field)} = {int(value)}.",
                RowColor.blue,
            )
            return

        self.infoMessage.emit(
            "Калибровка",
            f"Не удалось отправить запись DID 0x{int(field_var.pid) & 0xFFFF:04X}.",
        )

    @Slot("QVariant")
    def loadCalibrationTempCompCsv(self, path_or_urls):
        """Цель функции в офлайн-анализе температурной компенсации, затем она загружает CSV/XLSX логи коллектора и считает коэффициенты."""
        # Фиксирует верхний селектор CAN-узла, чтобы оффлайн-загрузка CSV/XLSX не меняла рабочий target для UDS.
        calibration_node_snapshot = {
            "options": list(self._calibration_node_options),
            "values": list(self._calibration_node_values),
            "selected_index": int(self._selected_calibration_node_index),
            "target_sa": self._calibration_target_node_sa,
        }

        raw_items = self._expand_qvariant_items(path_or_urls)

        paths: list[Path] = []
        for item in raw_items:
            resolved = self._to_local_path(item)
            if not resolved:
                continue
            try:
                paths.append(Path(resolved).expanduser().resolve())
            except Exception:
                paths.append(Path(resolved))

        self._append_log(
            f"Калибровка: получены пути CSV/XLSX для анализа температурной компенсации: {len(paths)}.",
            RowColor.blue,
        )
        if len(paths) == 0:
            self.infoMessage.emit("Калибровка", "Файл CSV/XLSX не выбран.")
            self._set_calibration_temp_comp_operation_status(
                "Загрузка CSV/XLSX отменена: файл не выбран.",
                busy=False,
                progress_percent=0,
                determinate=False,
            )
            return

        self._set_calibration_temp_comp_operation_status(
            f"Загрузка CSV/XLSX и пересчет графиков: подготовка ({len(paths)} файлов)...",
            busy=True,
            progress_percent=0,
            determinate=True,
        )
        QCoreApplication.processEvents()
        try:
            loaded_files, loaded_points = self._load_calibration_temp_comp_csv_files(paths)
        except Exception as exc:
            error_text = f"Ошибка загрузки CSV/XLSX: {str(exc)}"
            if (
                list(self._calibration_node_options) != calibration_node_snapshot["options"]
                or list(self._calibration_node_values) != calibration_node_snapshot["values"]
                or int(self._selected_calibration_node_index) != int(calibration_node_snapshot["selected_index"])
                or self._calibration_target_node_sa != calibration_node_snapshot["target_sa"]
            ):
                self._calibration_node_options = list(calibration_node_snapshot["options"])
                self._calibration_node_values = list(calibration_node_snapshot["values"])
                self._selected_calibration_node_index = int(calibration_node_snapshot["selected_index"])
                self._calibration_target_node_sa = calibration_node_snapshot["target_sa"]
                self.calibrationNodeSelectionChanged.emit()
            self._set_calibration_temp_comp_operation_status(
                error_text,
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            self._append_log(f"Калибровка: {error_text}", RowColor.red)
            self.infoMessage.emit("Калибровка", error_text)
            return
        if loaded_files <= 0:
            if (
                list(self._calibration_node_options) != calibration_node_snapshot["options"]
                or list(self._calibration_node_values) != calibration_node_snapshot["values"]
                or int(self._selected_calibration_node_index) != int(calibration_node_snapshot["selected_index"])
                or self._calibration_target_node_sa != calibration_node_snapshot["target_sa"]
            ):
                self._calibration_node_options = list(calibration_node_snapshot["options"])
                self._calibration_node_values = list(calibration_node_snapshot["values"])
                self._selected_calibration_node_index = int(calibration_node_snapshot["selected_index"])
                self._calibration_target_node_sa = calibration_node_snapshot["target_sa"]
                self.calibrationNodeSelectionChanged.emit()
            status_text = str(self._calibration_temp_comp_status or "").strip()
            if not status_text:
                status_text = "Не удалось загрузить данные температурной компенсации из выбранных CSV/XLSX."
            self._set_calibration_temp_comp_operation_status(
                f"Загрузка CSV/XLSX завершена с ошибкой: {status_text}",
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            self.infoMessage.emit("Калибровка", status_text)
            return

        # Принудительно обновляет метрики и график после каждой успешной загрузки CSV/XLSX.
        self._recompute_calibration_temp_comp_metrics()

        if (
            list(self._calibration_node_options) != calibration_node_snapshot["options"]
            or list(self._calibration_node_values) != calibration_node_snapshot["values"]
            or int(self._selected_calibration_node_index) != int(calibration_node_snapshot["selected_index"])
            or self._calibration_target_node_sa != calibration_node_snapshot["target_sa"]
        ):
            self._calibration_node_options = list(calibration_node_snapshot["options"])
            self._calibration_node_values = list(calibration_node_snapshot["values"])
            self._selected_calibration_node_index = int(calibration_node_snapshot["selected_index"])
            self._calibration_target_node_sa = calibration_node_snapshot["target_sa"]
            self.calibrationNodeSelectionChanged.emit()

        self._set_calibration_temp_comp_operation_status(
            f"Загрузка CSV/XLSX завершена: файлов {loaded_files}, точек {loaded_points}. Графики пересчитаны.",
            busy=False,
            progress_percent=100,
            determinate=True,
        )
        self._append_log(
            f"Калибровка: загружено CSV/XLSX файлов для анализа температурной компенсации: {loaded_files}, точек: {loaded_points}.",
            RowColor.green,
        )
        self.infoMessage.emit(
            "Калибровка",
            f"Загружено CSV/XLSX файлов: {loaded_files}, точек: {loaded_points}. Анализ пересчитан.",
        )

    @Slot(str)
    def writeCalibrationTempCompK1(self, value_text):
        """Цель функции в записи нового K1, затем она валидирует ввод и отправляет UDS 0x2E по DID 0x001B."""
        if not self._ensure_calibration_write_ready("запись коэффициента K1"):
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: последовательное чтение расширенных DID остановлено для записи K1.",
                RowColor.yellow,
            )

        if len(self._calibration_write_verify_pending) > 0:
            self.infoMessage.emit(
                "Калибровка",
                "Дождитесь завершения текущей автопроверки DID перед записью нового K1.",
            )
            return

        try:
            value = self._resolve_calibration_k1_write_value(value_text, self._calibration_temp_comp_k1_x100_current)
        except ValueError as exc:
            self.infoMessage.emit("Калибровка", str(exc))
            return

        write_payload = int(value) & 0xFFFF
        if self._calibration_write_service.write_data(
            UdsData.fuel_temp_comp_k1_x100,
            write_payload,
            tx_identifier=self._build_calibration_tx_identifier(),
        ):
            self._calibration_write_verify_pending[int(UdsData.fuel_temp_comp_k1_x100.pid)] = int(value)
            self.calibrationVerificationChanged.emit()
            self._append_log(f"Калибровка: запись коэффициента K1 = {int(value)}.", RowColor.blue)
            return

        self.infoMessage.emit("Калибровка", "Не удалось отправить запись DID 0x001B.")

    @Slot(str)
    def writeCalibrationTempCompK0(self, value_text):
        """Цель функции в записи нового K0, затем она валидирует ввод и отправляет UDS 0x2E по DID 0x001C."""
        if not self._ensure_calibration_write_ready("запись коэффициента K0"):
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: последовательное чтение расширенных DID остановлено для записи K0.",
                RowColor.yellow,
            )

        if len(self._calibration_write_verify_pending) > 0:
            self.infoMessage.emit(
                "Калибровка",
                "Дождитесь завершения текущей автопроверки DID перед записью нового K0.",
            )
            return

        try:
            value = self._resolve_calibration_k0_write_value(value_text, self._calibration_temp_comp_k0_count_current)
        except ValueError as exc:
            self.infoMessage.emit("Калибровка", str(exc))
            return

        write_payload = int(value) & 0xFFFF
        if self._calibration_write_service.write_data(
            UdsData.fuel_temp_comp_k0_count,
            write_payload,
            tx_identifier=self._build_calibration_tx_identifier(),
        ):
            self._calibration_write_verify_pending[int(UdsData.fuel_temp_comp_k0_count.pid)] = int(value)
            self.calibrationVerificationChanged.emit()
            self._append_log(f"Калибровка: запись коэффициента K0 = {int(value)}.", RowColor.blue)
            return

        self.infoMessage.emit("Калибровка", "Не удалось отправить запись DID 0x001C.")

    @Slot(str)
    def writeCalibrationTempCompZeroTrim(self, value_text):
        """Цель функции в записи коррекции zero trim, затем она валидирует ввод и отправляет UDS 0x2E по DID 0x002D."""
        if not self._ensure_calibration_write_ready("запись коррекции zero trim"):
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: последовательное чтение расширенных DID остановлено для записи zero trim.",
                RowColor.yellow,
            )

        if len(self._calibration_write_verify_pending) > 0:
            self.infoMessage.emit(
                "Калибровка",
                "Дождитесь завершения текущей автопроверки DID перед записью zero trim.",
            )
            return

        try:
            value = self._resolve_calibration_zero_trim_write_value(
                value_text,
                self._calibration_temp_comp_zero_trim_count_current,
            )
        except ValueError as exc:
            self.infoMessage.emit("Калибровка", str(exc))
            return

        write_payload = int(value) & 0xFFFF
        self._reset_calibration_temp_comp_zero_trim_verify_state()
        self._calibration_temp_comp_zero_trim_residual_x10 = None
        if self._calibration_write_service.write_data(
            UdsData.fuel_zero_trim_count,
            write_payload,
            tx_identifier=self._build_calibration_tx_identifier(),
        ):
            self._calibration_write_verify_pending[int(UdsData.fuel_zero_trim_count.pid)] = int(value)
            self.calibrationVerificationChanged.emit()
            self._append_log(f"Калибровка: запись коррекции zero trim = {int(value)}.", RowColor.blue)
            return

        self.infoMessage.emit("Калибровка", "Не удалось отправить запись DID 0x002D.")

    @Slot()
    def resetCalibrationTempCompZeroTrim(self):
        """Цель функции в сбросе коррекции zero trim, затем она отправляет запись 0 в DID 0x002D."""
        self.writeCalibrationTempCompZeroTrim("0")

    @Slot()
    def applyCalibrationTempCompRecommendations(self):
        """Цель функции в пакетной записи рекомендаций, затем она последовательно записывает K1/K0 и рассчитанные расширенные DID с автопроверкой каждого шага."""
        if not self._ensure_calibration_write_ready("запись рекомендуемых параметров компенсации"):
            return

        if bool(self._calibration_temp_comp_zero_trim_air_zero_adjust_active) or bool(self._calibration_temp_comp_zero_trim_verify_pending):
            self.infoMessage.emit(
                "Калибровка",
                "Дождитесь завершения автоподстройки/автопроверки zero trim перед записью рекомендаций K1/K0.",
            )
            return

        if self._calibration_temp_comp_adv_read_active:
            self._stop_calibration_temp_comp_advanced_read_sequence()
            self._append_log(
                "Калибровка: последовательное чтение расширенных DID остановлено для записи рекомендаций.",
                RowColor.yellow,
            )

        if len(self._calibration_write_verify_pending) > 0:
            self.infoMessage.emit(
                "Калибровка",
                "Дождитесь завершения текущей автопроверки DID перед записью рекомендаций.",
            )
            return

        steps: list[str] = []
        if self._calibration_temp_comp_k1_x100_next is not None:
            steps.append("k1")
        if self._calibration_temp_comp_k0_count_next is not None:
            steps.append("k0")

        current_mode = self._temp_comp_get_mode_from_values(self._calibration_temp_comp_advanced_values)
        allowed_field_keys = self._calibration_temp_comp_advanced_read_field_keys_for_mode(
            current_mode,
            include_mode=True,
        )
        for field_key in allowed_field_keys:
            if not field_key:
                continue
            recommended_value = self._calibration_temp_comp_advanced_recommended_values.get(field_key)
            if recommended_value is None:
                continue
            current_value = self._calibration_temp_comp_advanced_values.get(field_key)
            if current_value is not None and int(current_value) == int(recommended_value):
                continue
            steps.append(f"adv:{field_key}")

        if len(steps) <= 0:
            self.infoMessage.emit("Калибровка", "Нет рассчитанных рекомендаций для записи. Сначала загрузите CSV/XLSX.")
            return

        self._calibration_temp_comp_recommendation_apply_queue = list(steps)
        self._append_log(
            (
                "Калибровка: запуск пакетной записи рекомендаций "
                f"для текущего режима {self._temp_comp_mode_text(current_mode)} "
                f"({', '.join(steps)})."
            ),
            RowColor.blue,
        )
        self._append_log(
            "Калибровка: пакет рекомендаций изменяет только K1/K0 и DID 0x001D..0x002C. Zero trim (0x002D) выполняется отдельной эксплуатационной подгонкой.",
            RowColor.blue,
        )
        self._continue_calibration_temp_comp_recommendation_apply_queue()

    @Slot()
    def applyCalibrationTempCompNextK1(self):
        """Цель функции в записи рекомендованного K1, затем она отправляет рассчитанное значение в DID 0x001B."""
        self._reset_calibration_temp_comp_recommendation_apply_queue()
        next_k1 = self._calibration_temp_comp_k1_x100_next
        if next_k1 is None:
            self.infoMessage.emit("Калибровка", "Сначала загрузите CSV и дождитесь расчета рекомендованного K1.")
            return

        self.writeCalibrationTempCompK1(str(int(next_k1)))

    @Slot()
    def applyCalibrationTempCompNextK0(self):
        """Цель функции в записи рекомендованного K0, затем она отправляет рассчитанное значение в DID 0x001C."""
        self._reset_calibration_temp_comp_recommendation_apply_queue()
        next_k0 = self._calibration_temp_comp_k0_count_next
        if next_k0 is None:
            self.infoMessage.emit("Калибровка", "Сначала загрузите CSV и дождитесь расчета рекомендованного K0.")
            return

        self.writeCalibrationTempCompK0(str(int(next_k0)))

    @Slot(str)
    def saveCalibrationLevel0(self, value_text):
        """Цель функции в записи эталона 0%, затем она отправляет DID 0x0012 и включает автопроверку результата."""
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
        """Цель функции в записи эталона 100%, затем она отправляет DID 0x0013 и включает автопроверку результата."""
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
        """Цель функции в фиксации усредненного периода, затем она логирует стабильное значение из скользящего окна."""
        captured, sample_count = self._recompute_calibration_stable_capture()
        if captured is None:
            self.infoMessage.emit("Калибровка", "Недостаточно данных для стабильного захвата. Подождите обновление уровня.")
            return

        self._append_log(f"Калибровка: стабильный захват = {captured} (по {sample_count} точкам).", RowColor.green)

    @Slot()
    def createCalibrationBackup(self):
        """Цель функции в создании дампа текущего узла, затем она последовательно считывает 0%/100%/K1/K0/zero trim и сохраняет JSON."""
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return

        if bool(self._calibration_dump_capture_active):
            self.infoMessage.emit("Калибровка", "Сохранение дампа уже выполняется.")
            return

        if self._calibration_restore_active:
            self.infoMessage.emit("Калибровка", "Сейчас выполняется применение дампа. Дождитесь завершения.")
            return

        target_sa = int(self._resolve_calibration_target_sa()) & 0xFF
        self._calibration_target_node_sa = int(target_sa)
        self._calibration_dump_capture_active = True
        self._calibration_dump_capture_target_sa = int(target_sa)
        self._calibration_dump_capture_values = {}
        self._calibration_dump_capture_current_did = None
        self._calibration_dump_capture_queue = [int(did) & 0xFFFF for did in self._calibration_dump_required_dids()]
        if self._calibration_dump_capture_timeout_timer.isActive():
            self._calibration_dump_capture_timeout_timer.stop()
        self._append_log(
            f"Калибровка: запуск сохранения дампа для узла 0x{int(target_sa) & 0xFF:02X}.",
            RowColor.blue,
        )
        self._request_next_calibration_dump_capture_did()

    @Slot(str)
    def loadCalibrationBackupDump(self, path_or_url):
        """Цель функции в загрузке JSON-дампа, затем она валидирует параметры и показывает их в блоке резервной копии."""
        file_path = self._to_local_path(path_or_url)
        if not file_path:
            self.infoMessage.emit("Калибровка", "Путь к дампу не выбран.")
            return

        candidate = Path(str(file_path))
        if not candidate.exists() or (not candidate.is_file()):
            self.infoMessage.emit("Калибровка", "Файл дампа не найден.")
            return

        try:
            parsed = self._load_calibration_dump_payload(candidate)
        except Exception as exc:
            self.infoMessage.emit("Калибровка", f"Не удалось загрузить дамп: {str(exc)}")
            self._append_log(f"Калибровка: ошибка загрузки дампа {candidate}: {str(exc)}", RowColor.red)
            return

        self._apply_calibration_dump_to_state(
            node_sa=int(parsed["node_sa"]) & 0xFF,
            level_0=int(parsed["level_0"]),
            level_100=int(parsed["level_100"]),
            k1=int(parsed["k1"]),
            k0=int(parsed["k0"]),
            zero_trim=int(parsed["zero_trim"]),
            file_path=str(candidate),
            source_text="Источник дампа: загружен из файла.",
            saved_at_text=str(parsed.get("saved_at", "")).strip(),
            loaded_from_file=True,
        )
        self._append_log(
            f"Калибровка: дамп загружен из файла {candidate}.",
            RowColor.green,
        )
        self.infoMessage.emit("Калибровка", f"Дамп загружен: {candidate}")

    @Slot()
    def restoreCalibrationBackup(self):
        """Цель функции в применении загруженного дампа, затем она поочередно записывает 0%/100%/K1/K0/zero trim в текущий узел."""
        if not self._calibration_backup_available:
            self.infoMessage.emit("Калибровка", "Сначала сохраните или загрузите дамп калибровки.")
            return

        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return

        if bool(self._calibration_dump_capture_active):
            self.infoMessage.emit("Калибровка", "Сейчас выполняется чтение дампа из МК. Дождитесь завершения.")
            return

        backup0 = int(self._calibration_backup_level_0)
        backup100 = int(self._calibration_backup_level_100)
        backup_k1 = int(self._calibration_backup_k1)
        backup_k0 = int(self._calibration_backup_k0)
        backup_zero_trim = int(self._calibration_backup_zero_trim)
        target_sa = int(self._resolve_calibration_target_sa()) & 0xFF
        self._calibration_target_node_sa = int(target_sa)

        self._calibration_restore_active = True
        self._calibration_restore_queue = [
            (int(UdsData.empty_fuel_tank.pid), backup0),
            (int(UdsData.full_fuel_tank.pid), backup100),
            (int(UdsData.fuel_temp_comp_k1_x100.pid), backup_k1),
            (int(UdsData.fuel_temp_comp_k0_count.pid), backup_k0),
            (int(UdsData.fuel_zero_trim_count.pid), backup_zero_trim),
        ]
        self._calibration_restore_current_did = None
        source_sa = self._calibration_backup_node_sa
        source_text = f"0x{int(source_sa) & 0xFF:02X}" if source_sa is not None else "-"
        if source_sa is not None and (int(source_sa) & 0xFF) != (int(target_sa) & 0xFF):
            self._append_log(
                (
                    f"Калибровка: применяется дамп узла {source_text} к выбранному узлу 0x{target_sa:02X}. "
                    "Проверьте соответствие изделия перед записью."
                ),
                RowColor.yellow,
            )
        self._append_log(
            (
                f"Калибровка: запуск применения дампа к узлу 0x{target_sa:02X} "
                f"(источник дампа: {source_text})."
            ),
            RowColor.blue,
        )
        self._send_next_calibration_restore_write()

    @Slot(str)
    def setCalibrationPollingIntervalMs(self, interval_value):
        """Цель функции в настройке частоты опроса, затем она применяет новый интервал таймера калибровки."""
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
        """Цель функции в реактивном обновлении поля SA, затем она сохраняет введенный текст для последующей валидации."""
        value = str(text).strip()
        if self._source_address_text == value:
            return
        self._source_address_text = value
        self.sourceAddressTextChanged.emit()

    def _set_source_address_status(self, status_text: str):
        """Цель функции в отображении состояния Source Address, затем она передает оператору причину ожидания или отказа."""
        value = str(status_text or "").strip()
        if self._source_address_status == value:
            return
        self._source_address_status = value
        self.sourceAddressStatusChanged.emit()

    def _reset_source_address_operation(self):
        """Цель функции в завершении операции SA, затем она очищает ожидания ответа и снимает занятость UI."""
        if self._source_address_timeout_timer.isActive():
            self._source_address_timeout_timer.stop()
        self._source_address_pending_target_sa = None
        self._source_address_pending_new_sa = None
        self._set_source_address_busy(False)

    def _on_source_address_timeout(self):
        """Цель функции в обработке таймаута SA, затем она завершает чтение или запись DID 0x0011 ошибкой."""
        operation = str(self._source_address_operation or "")
        target_sa = self._source_address_pending_target_sa
        self._reset_source_address_operation()
        if operation == "write":
            message = "Таймаут ожидания подтверждения записи Source Address (DID 0x0011)."
        else:
            message = "Таймаут ожидания чтения Source Address (DID 0x0011)."
        if target_sa is not None:
            message = f"{message} Узел: 0x{int(target_sa) & 0xFF:02X}."
        self._set_source_address_status(message)
        self._append_log(message, RowColor.red)
        self.infoMessage.emit("Протокол", message)

    @Slot(str)
    def applySourceAddress(self, text):
        """Цель функции в записи Source Address, затем она отправляет команду в МК и синхронизирует локальный UI."""
        requested_text = str(text).strip()
        self._set_source_address_status(f"Запрошена запись Source Address: {requested_text or '<пусто>'}.")
        if self._source_address_busy:
            message = "Изменение Source Address уже выполняется."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit("Протокол", message)
            return

        if self._service_access_busy:
            message = "Дождитесь завершения Session/Security Access перед сменой Source Address."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit("Протокол", message)
            return

        if self._programming_active:
            message = "Нельзя менять Source Address во время программирования."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit("Протокол", message)
            return

        if self._options_busy or self._options_bulk_busy or self._calibration_active:
            message = "Завершите активную UDS операцию перед сменой Source Address."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit("Протокол", message)
            return

        if not self._can.is_connect or not self._can.is_trace:
            message = "Сначала подключите адаптер и запустите трассировку CAN."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit("Протокол", message)
            return

        if not self._service_security_unlocked:
            message = "Для записи Source Address сначала установите Extended Session и откройте Security Access."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit(
                "Протокол",
                message,
            )
            return

        try:
            source_address = self._parse_source_address(text)
        except ValueError:
            message = "Некорректный Source Address. Допустимо 0..255 или 0x00..0xFF."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit("Протокол", message)
            return

        target_sa = self._resolve_source_address_operation_target_sa()
        tx_identifier = self._build_options_tx_identifier(target_sa)

        self._source_address_pending_target_sa = int(target_sa) & 0xFF
        self._source_address_pending_new_sa = int(source_address) & 0xFF
        self._set_source_address_operation("write")
        self._set_source_address_busy(True)
        self._set_source_address_status(
            f"Отправка DID 0x0011: новый SA 0x{source_address:02X}, текущий узел 0x{target_sa:02X}, CAN ID 0x{int(tx_identifier) & 0x1FFFFFFF:08X}."
        )
        if not self._source_address_write_service.write_data(
            UdsData.can_sa,
            int(source_address) & 0xFF,
            tx_identifier=tx_identifier,
        ):
            self._reset_source_address_operation()
            message = "Не удалось отправить запрос на изменение Source Address."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.red)
            self.infoMessage.emit("Протокол", message)
            return

        self._append_log(
            f"Source Address: отправлена запись DID 0x0011 = 0x{source_address:02X} для узла 0x{target_sa:02X}, CAN ID 0x{int(tx_identifier) & 0x1FFFFFFF:08X}.",
            RowColor.blue,
        )
        self._source_address_timeout_timer.start()

    @Slot()
    def readSourceAddress(self):
        """Цель функции в чтении Source Address, затем она инициирует запрос текущего SA в выбранном узле."""
        self._set_source_address_status("Запрошено чтение Source Address.")
        if self._source_address_busy:
            message = "Операция с Source Address уже выполняется."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit("Протокол", message)
            return

        if self._service_access_busy:
            message = "Дождитесь завершения Session/Security Access перед чтением Source Address."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit("Протокол", message)
            return

        if self._programming_active:
            message = "Нельзя читать Source Address во время программирования."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit("Протокол", message)
            return

        if self._options_busy or self._options_bulk_busy or self._calibration_active:
            message = "Завершите активную UDS операцию перед чтением Source Address."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit("Протокол", message)
            return

        if not self._can.is_connect or not self._can.is_trace:
            message = "Сначала подключите адаптер и запустите трассировку CAN."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.yellow)
            self.infoMessage.emit("Протокол", message)
            return

        target_sa = self._resolve_source_address_operation_target_sa()
        tx_identifier = self._build_options_tx_identifier(target_sa)

        self._source_address_pending_target_sa = int(target_sa) & 0xFF
        self._source_address_pending_new_sa = None
        self._set_source_address_operation("read")
        self._set_source_address_busy(True)
        self._set_source_address_status(
            f"Отправка чтения DID 0x0011 для узла 0x{target_sa:02X}, CAN ID 0x{int(tx_identifier) & 0x1FFFFFFF:08X}."
        )
        if not self._source_address_read_service.read_data_by_identifier(tx_identifier, UdsData.can_sa):
            self._reset_source_address_operation()
            message = "Не удалось отправить запрос на чтение Source Address."
            self._set_source_address_status(message)
            self._append_log(f"Source Address: {message}", RowColor.red)
            self.infoMessage.emit("Протокол", message)
            return

        self._append_log(
            f"Source Address: отправлено чтение DID 0x0011 для узла 0x{target_sa:02X}, CAN ID 0x{int(tx_identifier) & 0x1FFFFFFF:08X}.",
            RowColor.blue,
        )
        self._source_address_timeout_timer.start()

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
        """Цель функции в управлении подключением адаптера, затем она подключает CAN или выполняет полный локальный сброс состояния."""
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
            self._calibration_backup_all_nodes_active = False
            self._calibration_backup_all_nodes_queue = []
            self._calibration_backup_all_nodes_current_sa = None
            self._calibration_backup_all_nodes_values_by_sa = {}
            self._calibration_backup_all_nodes_original_target_sa = None
            self._calibration_backup_all_nodes_reference_sa = None
            if self._calibration_backup_all_nodes_step_timer.isActive():
                self._calibration_backup_all_nodes_step_timer.stop()
            self._reset_calibration_dump_capture_state()
            self._calibration_restore_active = False
            self._calibration_restore_queue = []
            self._reset_calibration_temp_comp_state(
                clear_samples=True,
                clear_coefficients=True,
                clear_cached_nodes=True,
            )
            self._refresh_calibration_node_options()
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
        parsed_version = self._extract_firmware_version_from_name(self._firmware_path)
        self._firmware_file_version_text = parsed_version if parsed_version else "—"
        self.softwareVersionChanged.emit()

        self._set_firmware_loading(True)
        self._append_log("Чтение BIN файла...", RowColor.blue)
        self.infoMessage.emit("Прошивка", "BIN файл выбран. Идет загрузка...")

        # Defer actual worker start to the next event loop turn so UI updates instantly.
        QTimer.singleShot(0, lambda p=file_path: self._start_firmware_loading(p))

    @Slot()
    def startProgramming(self):
        if not self._validate_programming_start_conditions():
            return

        target_sa = self._resolve_programming_selected_sa()
        self._programming_batch_active = False
        self._programming_batch_queue = []
        self._programming_batch_total = 0
        self._programming_batch_done = 0
        self._programming_batch_status = "Запущено программирование одного выбранного узла."
        self.programmingBatchChanged.emit()
        self._start_programming_for_node(target_sa)

    @Slot()
    def startProgrammingAllNodes(self):
        """Цель функции в запуске групповой прошивки, затем она программирует найденные узлы строго по одному."""
        if not self._validate_programming_start_conditions():
            return

        nodes = self._detected_programming_node_values()
        if len(nodes) == 0:
            self.infoMessage.emit(
                "Программирование",
                "Нет найденных узлов для группового программирования. Запустите трассировку CAN и дождитесь RX кадров от узлов.",
            )
            return

        self._programming_batch_active = True
        self._programming_batch_queue = list(nodes)
        self._programming_batch_total = len(nodes)
        self._programming_batch_done = 0
        self._programming_batch_status = f"Групповое программирование: подготовлено {len(nodes)} узл."
        self.programmingBatchChanged.emit()
        self._append_log(
            "Групповое программирование: очередь узлов "
            + ", ".join(f"0x{int(node) & 0xFF:02X}" for node in nodes),
            RowColor.blue,
        )
        self._start_next_programming_batch_node()

    def _validate_programming_start_conditions(self) -> bool:
        """Цель функции в проверке безопасного старта прошивки, затем она блокирует конфликтующие операции."""
        if self._programming_active or self._programming_batch_active:
            self.infoMessage.emit("Программирование", "Программирование уже выполняется.")
            return False

        if not self._can.is_connect:
            self.infoMessage.emit("Программирование", "Сначала подключите CAN-адаптер.")
            return False

        if self._firmware_loading:
            self.infoMessage.emit("Программирование", "Дождитесь завершения загрузки BIN-файла.")
            return False

        if not str(self._firmware_path).strip():
            self.infoMessage.emit("Программирование", "Сначала выберите BIN-файл прошивки.")
            return False

        if self._source_address_busy or self._service_access_busy or self._communication_control_busy:
            self.infoMessage.emit("Программирование", "Дождитесь завершения активной UDS-операции.")
            return False

        if self._options_busy or self._options_bulk_busy or self._calibration_active:
            self.infoMessage.emit("Программирование", "Завершите настройку параметров или калибровку перед прошивкой.")
            return False

        if self._collector_state == "recording":
            self.infoMessage.emit("Программирование", "Остановите запись коллектора перед прошивкой.")
            return False

        return True

    def _start_programming_for_node(self, target_sa: int) -> bool:
        """Цель функции в запуске прошивки одного SA, затем она применяет UDS ID и выполняет автосброс при необходимости."""
        normalized_sa = int(target_sa) & 0xFF
        self._finish_post_program_version_write(False, "Подготовка нового цикла программирования, предыдущая автозапись версии отменена.")
        self._apply_programming_target_sa(normalized_sa, "Узел подготовлен к программированию.")

        self._progress_value = 0
        self.progressChanged.emit()
        self._set_programming_active(True)

        if self._auto_reset_before_programming:
            self._pending_programming_after_reset = True
            self._append_log(f"Автосброс: отправка команды перехода в загрузчик для узла 0x{normalized_sa:02X}", RowColor.blue)

            try:
                self._ui_ecu_reset_service.ecu_uds_reset()
            except Exception:
                self._pending_programming_after_reset = False
                self._set_programming_active(False)
                self._append_log("Автосброс: ошибка отправки команды", RowColor.red)
                self.infoMessage.emit("Программирование", "Не удалось отправить команду автосброса.")
                return False

            self._programming_start_timer.start(self._auto_reset_delay_ms)
            return True

        self._start_programming_flow()
        return True

    def _start_next_programming_batch_node(self):
        """Цель функции в продолжении групповой прошивки, затем она берет следующий SA из очереди."""
        if not self._programming_batch_active:
            return

        if len(self._programming_batch_queue) == 0:
            self._finish_programming_batch(True, "Групповое программирование успешно завершено.")
            return

        target_sa = int(self._programming_batch_queue.pop(0)) & 0xFF
        step_index = int(self._programming_batch_done) + 1
        self._programming_batch_status = (
            f"Групповое программирование: узел {step_index}/{self._programming_batch_total}, SA 0x{target_sa:02X}."
        )
        self.programmingBatchChanged.emit()

        if not self._start_programming_for_node(target_sa):
            self._finish_programming_batch(False, f"Групповое программирование остановлено на узле 0x{target_sa:02X}.")

    def _finish_programming_batch(self, success: bool, message: str):
        """Цель функции в завершении групповой прошивки, затем она очищает очередь и сообщает итог оператору."""
        if self._programming_batch_step_timer.isActive():
            self._programming_batch_step_timer.stop()
        self._programming_batch_active = False
        self._programming_batch_queue = []
        self._programming_batch_total = 0
        self._programming_batch_done = 0
        self._programming_batch_status = str(message)
        self.programmingBatchChanged.emit()
        self._append_log(message, RowColor.green if success else RowColor.red)
        if not success:
            self._set_programming_active(False)

    def _on_programming_batch_step_timeout(self):
        """Цель функции в задержке между узлами, затем она запускает следующий элемент групповой очереди."""
        self._start_next_programming_batch_node()

    @Slot()
    def checkState(self):
        target_sa = self._resolve_programming_selected_sa()
        self._apply_programming_target_sa(target_sa, "Проверка статуса будет отправлена этому узлу.")
        self._bootloader.check_state()

    @Slot()
    def resetToBootloader(self):
        if not self._can.is_connect:
            self.infoMessage.emit("Сброс", "Сначала подключите CAN-адаптер.")
            return

        target_sa = self._resolve_programming_selected_sa()
        self._apply_programming_target_sa(target_sa, "Сброс в загрузчик будет отправлен этому узлу.")
        self._ui_ecu_reset_service.ecu_uds_reset()
        self._append_log(f"Отправлена команда сброса в загрузчик для узла 0x{int(target_sa) & 0xFF:02X}", RowColor.blue)

    @Slot()
    def resetToMainProgram(self):
        if not self._can.is_connect:
            self.infoMessage.emit("Сброс", "Сначала подключите CAN-адаптер.")
            return

        target_sa = self._resolve_programming_selected_sa()
        self._apply_programming_target_sa(target_sa, "Сброс в основное ПО будет отправлен этому узлу.")
        self._ui_ecu_reset_service.ecu_software_reset()
        self._append_log(f"Отправлена команда сброса в основное ПО для узла 0x{int(target_sa) & 0xFF:02X}", RowColor.blue)

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
        session_name = self._collector_session_directory_name()
        base_logs_dir = self._project_root_directory / "logs"
        try:
            base_logs_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.infoMessage.emit("Коллектор", "Не удалось создать корневой каталог logs.")
            return

        candidate = base_logs_dir / session_name
        if not self._apply_collector_output_directory(candidate):
            self.infoMessage.emit("Коллектор", "Не удалось создать каталог с датой и временем внутри logs.")
            return

        self._collector_output_is_session_dir = True
        self.infoMessage.emit("Коллектор", f"Создан каталог для CSV: {self._collector_output_directory}")

    @staticmethod
    def _collector_session_timestamp_text() -> str:
        """Цель функции в формировании единой метки времени каталога, затем она возвращает формат День.Месяц.Год_Час-Минуты-Секунды."""
        return datetime.now().strftime("%d.%m.%Y_%H-%M-%S")

    def _collector_session_nodes_suffix_text(self) -> str:
        """Цель функции в формировании суффикса узлов сессии, затем она возвращает список SA, участвующих в логировании."""
        nodes: list[int] = []
        seen: set[int] = set()
        for raw_value in list(self._collector_node_order):
            try:
                node_sa = int(raw_value) & 0xFF
            except (TypeError, ValueError):
                continue
            if node_sa in seen:
                continue
            seen.add(node_sa)
            nodes.append(node_sa)

        if len(nodes) <= 0:
            return "nodes-none"

        nodes = sorted(nodes)
        max_items = 8
        labels = [f"0x{value:02X}" for value in nodes[:max_items]]
        if len(nodes) > max_items:
            labels.append(f"more{len(nodes) - max_items}")
        return "nodes-" + "-".join(labels)

    def _collector_session_directory_name(self) -> str:
        """Цель функции в сборке имени каталога сессии, затем она объединяет метку времени и список узлов."""
        return f"{self._collector_session_timestamp_text()}_{self._collector_session_nodes_suffix_text()}"

    @Slot(str)
    def setCollectorPollIntervalMs(self, interval_value):
        try:
            parsed = int(str(interval_value).strip())
        except (TypeError, ValueError):
            self.infoMessage.emit("Коллектор", "Интервал опроса должен быть целым числом в миллисекундах.")
            return

        bounded = max(30, min(10000, parsed))
        if bounded != parsed:
            self.infoMessage.emit("Коллектор", "Интервал опроса ограничен диапазоном 30..10000 мс.")

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
                self._collector_session_dir = base_dir / self._collector_session_directory_name()
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
        session_dir_for_upload = self._collector_session_dir
        self._collector_state = "stopped"
        self.collectorStateChanged.emit()
        self._set_programming_active(False)
        self._collector_session_dir = None
        self._collector_csv_managers = {}
        self._collector_combined_csv_manager = None
        self._append_log("Запись CSV остановлена.", RowColor.blue)
        self._collector_schedule_sftp_upload(session_dir_for_upload)

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
        raw_items = self._expand_qvariant_items(path_or_urls)

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
