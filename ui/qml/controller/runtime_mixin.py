from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QThread, QUrl, Slot
from PySide6.QtGui import QColor

from colors import RowColor
from j1939.j1939_can_identifier import J1939CanIdentifier
from uds.services.session import Session
from uds.uds_identifiers import UdsIdentifiers

from .contract import AppControllerContract
from .workers import FirmwareLoadWorker

class AppControllerRuntimeMixin(AppControllerContract):
    def _reset_post_program_version_write_state(self):
        """Цель функции в очистке состояния автозаписи версии, затем она снимает все промежуточные флаги цепочки."""
        self._post_program_version_write_pending = False
        self._post_program_version_write_stage = ""
        self._post_program_version_write_target_sa = None
        self._post_program_version_write_value = ""
        self._post_program_version_write_retry_left = 0
        self._post_program_version_write_wait_logged = False

    def _finish_post_program_version_write(self, success: bool, message: str):
        """Цель функции в завершении автозаписи версии, затем она пишет итог в лог и очищает внутреннее состояние."""
        active = bool(self._post_program_version_write_pending)
        target_sa = self._post_program_version_write_target_sa
        version_text = str(self._post_program_version_write_value or "").strip()
        if self._post_program_version_write_timer.isActive():
            self._post_program_version_write_timer.stop()
        self._reset_post_program_version_write_state()

        if not active:
            return

        if success:
            if target_sa is None:
                self._append_log(
                    f"Автозапись версии ПО после прошивки завершена: {version_text}.",
                    RowColor.green,
                )
            else:
                self._append_log(
                    (
                        f"Автозапись версии ПО после прошивки завершена для узла 0x{int(target_sa) & 0xFF:02X}: "
                        f"{version_text}."
                    ),
                    RowColor.green,
                )
            return

        details = str(message or "").strip()
        if target_sa is None:
            self._append_log(f"Автозапись версии ПО после прошивки не выполнена: {details}", RowColor.yellow)
        else:
            self._append_log(
                f"Автозапись версии ПО после прошивки для узла 0x{int(target_sa) & 0xFF:02X} не выполнена: {details}",
                RowColor.yellow,
            )

    def _schedule_post_program_version_write(self, target_sa: int | None):
        """Цель функции в планировании автозаписи версии, затем она запускает таймер старта цепочки 0x10/0x27/0x2E."""
        if self._programming_batch_active:
            self._reset_post_program_version_write_state()
            self._append_log(
                "Групповой режим: автозапись версии после прошивки пропущена для текущего шага.",
                RowColor.yellow,
            )
            return

        version_text = str(self._firmware_file_version_text or "").strip()
        if not version_text or version_text == "—":
            self._reset_post_program_version_write_state()
            self._append_log(
                "Автозапись версии после прошивки пропущена: в имени BIN не найден формат версии.",
                RowColor.yellow,
            )
            return

        if not self._can.is_connect or not self._can.is_trace:
            self._reset_post_program_version_write_state()
            self._append_log(
                "Автозапись версии после прошивки пропущена: нужна активная трассировка CAN.",
                RowColor.yellow,
            )
            return

        if target_sa is None:
            target_sa = self._resolve_programming_selected_sa()
        normalized_sa = int(target_sa) & 0xFF

        self._post_program_version_write_pending = True
        self._post_program_version_write_stage = "wait_delay"
        self._post_program_version_write_target_sa = normalized_sa
        self._post_program_version_write_value = version_text
        self._post_program_version_write_retry_left = 8
        self._post_program_version_write_wait_logged = False

        if self._post_program_version_write_timer.isActive():
            self._post_program_version_write_timer.stop()
        self._post_program_version_write_timer.start(max(200, int(self._post_program_version_write_delay_ms)))
        self._append_log(
            (
                f"Автозапись версии ПО после прошивки запланирована для узла 0x{normalized_sa:02X}: "
                f"{version_text} (задержка {int(self._post_program_version_write_delay_ms)} мс)."
            ),
            RowColor.blue,
        )

    def _on_post_program_version_write_timeout(self):
        """Цель функции в старте цепочки автозаписи версии, затем она отправляет запрос Extended Session для нужного SA."""
        if not bool(self._post_program_version_write_pending):
            return
        if str(self._post_program_version_write_stage or "") != "wait_delay":
            return

        if (
            self._programming_active
            or self._source_address_busy
            or self._options_busy
            or self._options_bulk_busy
            or self._service_access_busy
            or self._communication_control_busy
            or self._calibration_active
        ):
            self._post_program_version_write_retry_left -= 1
            if self._post_program_version_write_retry_left <= 0:
                self._finish_post_program_version_write(
                    False,
                    "UDS канал занят: не удалось запустить автозапись версии в отведенное время.",
                )
                return
            if not bool(self._post_program_version_write_wait_logged):
                self._append_log(
                    "Автозапись версии ПО: ожидание освобождения UDS канала.",
                    RowColor.blue,
                )
                self._post_program_version_write_wait_logged = True
            self._post_program_version_write_timer.start(250)
            return

        target_sa = self._post_program_version_write_target_sa
        if target_sa is None:
            self._finish_post_program_version_write(False, "Не определен целевой SA для автозаписи версии.")
            return

        self._post_program_version_write_wait_logged = False
        self._apply_programming_target_sa(int(target_sa) & 0xFF, "Автозапись версии ПО после прошивки.")
        self._selected_service_session_index = self._service_session_index_for_value(int(Session.EXTENDED))
        self.serviceAccessChanged.emit()
        self._post_program_version_write_stage = "wait_session"
        self.applySelectedServiceSession()
        if not bool(self._service_access_busy) or str(self._service_access_pending_action or "") != "session":
            self._finish_post_program_version_write(False, "Не удалось отправить запрос Extended Session для автозаписи версии.")

    def _continue_post_program_version_after_session(self):
        """Цель функции в продолжении автозаписи после 0x10, затем она запускает Security Access 0x27."""
        if not bool(self._post_program_version_write_pending):
            return
        if str(self._post_program_version_write_stage or "") != "wait_session":
            return
        self._post_program_version_write_stage = "wait_security"
        self.requestSecurityAccess()
        if not bool(self._service_access_busy) or str(self._service_access_pending_action or "") != "security_seed":
            self._finish_post_program_version_write(False, "Не удалось запустить Security Access для автозаписи версии.")

    def _continue_post_program_version_after_security(self):
        """Цель функции в продолжении автозаписи после 0x27, затем она отправляет запись DID 0xF195."""
        if not bool(self._post_program_version_write_pending):
            return
        if str(self._post_program_version_write_stage or "") != "wait_security":
            return
        version_text = str(self._post_program_version_write_value or "").strip()
        if not version_text:
            self._finish_post_program_version_write(False, "Пустая версия ПО для записи DID 0xF195.")
            return
        self._post_program_version_write_stage = "wait_write"
        self.writeSoftwareVersionDid(version_text)
        if not bool(self._software_version_busy):
            self._finish_post_program_version_write(False, "Не удалось запустить запись DID 0xF195.")

    def _on_bootloader_state(self, text, color):
        self._append_log(text, color)
        if self._programming_batch_active and isinstance(color, QColor) and color == RowColor.red:
            current_sa = self._programming_current_target_sa
            if current_sa is None:
                self._finish_programming_batch(False, "Групповое программирование остановлено из-за ошибки загрузчика.")
            else:
                self._finish_programming_batch(
                    False,
                    f"Групповое программирование остановлено из-за ошибки узла 0x{int(current_sa) & 0xFF:02X}.",
                )

    def _on_data_sent(self, value):
        clamped_value = min(max(value, 0), self._progress_max)
        if self._progress_value == clamped_value:
            return
        self._progress_value = clamped_value
        self.progressChanged.emit()

    def _on_programming_finished(self, success):
        if not success:
            self._finish_post_program_version_write(False, "Прошивка не завершилась успешно, автозапись версии отменена.")
        elif bool(self._post_program_version_write_pending):
            self._finish_post_program_version_write(False, "Предыдущая цепочка автозаписи версии не была завершена и отменена.")
        if self._programming_start_timer.isActive():
            self._programming_start_timer.stop()
        self._pending_programming_after_reset = False
        self._set_programming_active(False)
        if not success:
            if self._programming_batch_active:
                current_sa = self._programming_current_target_sa
                if current_sa is None:
                    self._finish_programming_batch(False, "Групповое программирование остановлено: узел не прошился.")
                else:
                    self._finish_programming_batch(
                        False,
                        f"Групповое программирование остановлено: узел 0x{int(current_sa) & 0xFF:02X} не прошился.",
                    )
            return

        current_sa = self._programming_current_target_sa
        self._progress_value = self._progress_max
        self.progressChanged.emit()
        if current_sa is None:
            self._append_log("Программирование успешно завершено", RowColor.green)
        else:
            self._append_log(f"Программирование узла 0x{int(current_sa) & 0xFF:02X} успешно завершено", RowColor.green)

        if self._programming_batch_active:
            self._programming_batch_done += 1
            self._programming_batch_status = (
                f"Групповое программирование: готово {self._programming_batch_done}/{self._programming_batch_total}."
            )
            self.programmingBatchChanged.emit()

        if not self._can.is_connect:
            self.infoMessage.emit(
                "Программирование",
                "Программирование завершено, но CAN отключен: автосброс в основное ПО не отправлен.",
            )
            if self._programming_batch_active:
                self._finish_programming_batch(False, "Групповое программирование остановлено: CAN отключен.")
            return

        try:
            self._ui_ecu_reset_service.ecu_software_reset()
            if current_sa is None:
                self._append_log("Автосброс: отправлена команда перехода в основное ПО", RowColor.blue)
            else:
                self._append_log(
                    f"Автосброс: отправлена команда перехода в основное ПО для узла 0x{int(current_sa) & 0xFF:02X}",
                    RowColor.blue,
                )
        except Exception:
            self._append_log("Автосброс: ошибка отправки команды перехода в основное ПО", RowColor.red)
            self.infoMessage.emit(
                "Программирование",
                "Программирование завершено, но автосброс в основное ПО не отправлен.",
            )
            if self._programming_batch_active:
                self._finish_programming_batch(False, "Групповое программирование остановлено: не удалось сбросить узел.")
            return

        self._schedule_post_program_version_write(current_sa)

        if self._programming_batch_active:
            if len(self._programming_batch_queue) > 0:
                self._programming_batch_status = (
                    f"Пауза перед следующим узлом, осталось {len(self._programming_batch_queue)}."
                )
                self.programmingBatchChanged.emit()
                self._programming_batch_step_timer.start(self._programming_batch_delay_ms)
            else:
                self._finish_programming_batch(True, "Групповое программирование успешно завершено.")
            return

        self.infoMessage.emit(
            "Программирование",
            "Программирование завершено. Отправлена команда запуска основного ПО.",
        )

    def _on_trace_state_event(self):
        self._rx_time_anchor_raw = None
        self._rx_time_anchor_wall = None
        if (not self._can.is_trace) and bool(self._post_program_version_write_pending):
            self._finish_post_program_version_write(False, "Трассировка CAN остановлена, автозапись версии отменена.")
        if not self._can.is_trace:
            self._stop_calibration_poll_timer()
        elif self._calibration_active and (not self._calibration_waiting_session):
            self._start_calibration_poll_timer()
        self.traceStateChanged.emit()

    @Slot(int, bool)
    def _on_source_address_applied(self, source_address, success):
        self._set_source_address_busy(False)
        if success:
            self._source_address_text = f"0x{int(source_address) & 0xFF:02X}"
            self.sourceAddressTextChanged.emit()
            self._refresh_uds_identifier_texts()
            self._set_source_address_status(f"Source Address изменен: {self._source_address_text}.")
            self.infoMessage.emit("Протокол", f"Source Address изменен: {self._source_address_text}.")
        else:
            self._source_address_text = f"0x{UdsIdentifiers.rx.src:02X}"
            self.sourceAddressTextChanged.emit()
            self._refresh_uds_identifier_texts()
            self._set_source_address_status("Не удалось применить Source Address.")
            self.infoMessage.emit("Протокол", "Не удалось применить Source Address.")

    @Slot(int, bool)
    def _on_source_address_read(self, source_address, success):
        self._set_source_address_busy(False)
        if success:
            self._source_address_text = f"0x{int(source_address) & 0xFF:02X}"
            self.sourceAddressTextChanged.emit()
            self._refresh_uds_identifier_texts()
            self._set_source_address_status(f"Source Address считан: {self._source_address_text}.")
            self.infoMessage.emit("Протокол", f"Source Address считан: {self._source_address_text}.")
        else:
            self._set_source_address_status("Не удалось прочитать Source Address.")
            self.infoMessage.emit("Протокол", "Не удалось прочитать Source Address.")

    @Slot(str, bool, bytes, str)
    def _on_firmware_loaded(self, _file_path, success, binary_content, error_text):
        try:
            if not success:
                self._append_log("Ошибка загрузки BIN файла", RowColor.red)
                self.infoMessage.emit("Прошивка", error_text if error_text else "Не удалось открыть BIN файл.")
                return

            self._bootloader.set_firmware(binary_content)

            file_size = len(binary_content)
            self._progress_max = max(file_size, 1)
            self._progress_value = 0
            self.progressChanged.emit()

            self._append_log(f"BIN файл загружен ({file_size} байт)", RowColor.green)
            self.infoMessage.emit("Прошивка", f"BIN файл успешно загружен. Размер: {file_size} байт.")
        finally:
            self._set_firmware_loading(False)

    def _start_firmware_loading(self, file_path: str):
        self._firmware_loader_thread = QThread(self)
        self._firmware_loader_worker = FirmwareLoadWorker(file_path)
        self._firmware_loader_worker.moveToThread(self._firmware_loader_thread)

        self._firmware_loader_thread.started.connect(self._firmware_loader_worker.run)
        self._firmware_loader_worker.finished.connect(self._on_firmware_loaded)
        self._firmware_loader_worker.finished.connect(self._firmware_loader_thread.quit)
        self._firmware_loader_worker.finished.connect(self._firmware_loader_worker.deleteLater)
        self._firmware_loader_thread.finished.connect(self._firmware_loader_thread.deleteLater)
        self._firmware_loader_thread.finished.connect(self._clear_firmware_loader)
        self._firmware_loader_thread.start()

    def _clear_firmware_loader(self):
        self._firmware_loader_thread = None
        self._firmware_loader_worker = None

    def _refresh_device_info(self):
        hw_index = self._selected_hw_index()
        if hw_index < 0:
            self._manufacturer = ""
            self._product = ""
            self._serial = ""
            self.deviceInfoChanged.emit()
            return

        self._can.update_device_info(hw_index)
        info = self._can.device_info

        self._manufacturer = self._decode_bytes(getattr(info.manufacturer, "value", None))
        self._product = self._decode_bytes(getattr(info.product, "value", None))
        self._serial = self._decode_bytes(getattr(info.serial, "value", None))
        self.deviceInfoChanged.emit()

    def _selected_hw_index(self) -> int:
        if self._selected_device_index < 0 or self._selected_device_index >= len(self._device_indices):
            return -1
        return self._device_indices[self._selected_device_index]

    @staticmethod
    def _decode_bytes(raw_value):
        if raw_value is None:
            return ""
        if isinstance(raw_value, bytes):
            try:
                return raw_value.decode("utf-8")
            except UnicodeDecodeError:
                return raw_value.decode("cp1251", errors="ignore")
        return str(raw_value)

    @staticmethod
    def _parse_uint_field(text, minimum: int, maximum: int, field_name: str) -> int:
        raw = str(text).strip()
        if not raw:
            raise ValueError(f"Поле '{field_name}' не заполнено.")

        base = 16 if raw.lower().startswith("0x") else 10
        try:
            value = int(raw, base)
        except ValueError as exc:
            raise ValueError(f"Поле '{field_name}' содержит некорректное число.") from exc

        if value < minimum or value > maximum:
            raise ValueError(f"Поле '{field_name}' вне диапазона {minimum}..{maximum}.")

        return value

    def _refresh_uds_identifier_texts(self, emit_signal: bool = True):
        tx = UdsIdentifiers.tx
        rx = UdsIdentifiers.rx

        self._tx_priority_text = str(int(tx.priority) & 0x7)
        self._tx_pgn_text = f"0x{int(tx.pgn) & 0xFFFF:04X}"
        self._tx_src_text = f"0x{int(tx.src) & 0xFF:02X}"
        self._tx_dst_text = f"0x{int(tx.dst) & 0xFF:02X}"
        self._tx_identifier_text = f"0x{int(tx.identifier) & 0x1FFFFFFF:08X}"

        self._rx_priority_text = str(int(rx.priority) & 0x7)
        self._rx_pgn_text = f"0x{int(rx.pgn) & 0xFFFF:04X}"
        self._rx_src_text = f"0x{int(rx.src) & 0xFF:02X}"
        self._rx_dst_text = f"0x{int(rx.dst) & 0xFF:02X}"
        self._rx_identifier_text = f"0x{int(rx.identifier) & 0x1FFFFFFF:08X}"
        self._refresh_options_target_node_options(emit_signal=emit_signal)
        self._refresh_programming_node_options(emit_signal=emit_signal)

        if emit_signal:
            self.udsIdentifiersChanged.emit()

    def _detected_programming_node_values(self) -> list[int]:
        """Цель функции в сборе найденных узлов, затем она возвращает SA из CAN-потока и коллектора без дублей."""
        nodes: list[int] = []
        seen: set[int] = set()

        for raw_value in list(self._observed_candidate_values) + list(self._collector_node_order):
            try:
                node_sa = int(raw_value) & 0xFF
            except (TypeError, ValueError):
                continue
            if node_sa in seen:
                continue
            seen.add(node_sa)
            nodes.append(node_sa)

        return nodes

    def _refresh_programming_node_options(self, emit_signal: bool = True):
        """Цель функции в обновлении списка узлов программирования, затем она синхронизирует ComboBox с найденными SA."""
        previous_items = list(self._programming_node_items)
        previous_values = list(self._programming_node_values)
        previous_index = int(self._selected_programming_node_index)
        previous_status = str(self._programming_target_status)

        selected_sa = None
        if 0 <= previous_index < len(previous_values):
            selected_sa = int(previous_values[previous_index]) & 0xFF

        current_sa = int(UdsIdentifiers.rx.src) & 0xFF
        detected_nodes = self._detected_programming_node_values()
        detected_set = set(detected_nodes)

        new_values: list[int] = []
        new_items: list[str] = []
        seen: set[int] = set()

        def add_node(node_sa: int, label: str):
            normalized_sa = int(node_sa) & 0xFF
            if normalized_sa in seen:
                return
            seen.add(normalized_sa)
            new_values.append(normalized_sa)
            new_items.append(label)

        current_suffix = ", найден в CAN" if current_sa in detected_set else ""
        add_node(current_sa, f"Узел 0x{current_sa:02X} (текущий UDS{current_suffix})")

        for node_sa in detected_nodes:
            normalized_sa = int(node_sa) & 0xFF
            if normalized_sa == current_sa:
                continue
            add_node(normalized_sa, f"Узел 0x{normalized_sa:02X} (найден CAN)")

        if len(new_values) == 0:
            add_node(current_sa, f"Узел 0x{current_sa:02X} (текущий UDS)")

        if selected_sa in new_values:
            new_index = new_values.index(selected_sa)
        elif current_sa in new_values:
            new_index = new_values.index(current_sa)
        else:
            new_index = 0

        self._programming_node_values = new_values
        self._programming_node_items = new_items
        self._selected_programming_node_index = int(new_index)

        target_sa = int(new_values[new_index]) & 0xFF if 0 <= new_index < len(new_values) else current_sa
        found_count = len(detected_nodes)
        self._programming_target_status = (
            f"Целевой узел: 0x{target_sa:02X}. Найдено узлов для группового программирования: {found_count}."
        )

        if emit_signal and (
            previous_items != self._programming_node_items
            or previous_values != self._programming_node_values
            or previous_index != self._selected_programming_node_index
            or previous_status != self._programming_target_status
        ):
            self.programmingNodeSelectionChanged.emit()

    def _resolve_programming_selected_sa(self) -> int:
        """Цель функции в определении выбранного узла прошивки, затем она возвращает SA для UDS-запросов."""
        index = int(self._selected_programming_node_index)
        if 0 <= index < len(self._programming_node_values):
            return int(self._programming_node_values[index]) & 0xFF
        return int(UdsIdentifiers.rx.src) & 0xFF

    def _apply_programming_target_sa(self, target_sa: int, reason: str = ""):
        """Цель функции в настройке UDS ID под выбранный узел, затем она обновляет TX/RX адреса перед командами загрузчика."""
        normalized_sa = int(target_sa) & 0xFF
        node = self._observed_node_stats.get(normalized_sa, {})
        tester_sa, _ = self._choose_tester_sa_for_node(node, int(UdsIdentifiers.tx.src) & 0xFF)
        tester_sa = int(tester_sa) & 0xFF

        changed = (
            (int(UdsIdentifiers.tx.dst) & 0xFF) != normalized_sa
            or (int(UdsIdentifiers.rx.src) & 0xFF) != normalized_sa
            or (int(UdsIdentifiers.tx.src) & 0xFF) != tester_sa
            or (int(UdsIdentifiers.rx.dst) & 0xFF) != tester_sa
        )

        UdsIdentifiers.tx.src = tester_sa
        UdsIdentifiers.tx.dst = normalized_sa
        UdsIdentifiers.rx.src = normalized_sa
        UdsIdentifiers.rx.dst = tester_sa

        self._programming_current_target_sa = normalized_sa
        self._source_address_text = f"0x{normalized_sa:02X}"
        self.sourceAddressTextChanged.emit()
        self._refresh_uds_identifier_texts()

        if changed or reason:
            suffix = f" {reason}" if reason else ""
            self._append_log(
                f"Программирование: выбран узел 0x{normalized_sa:02X}, SA тестера 0x{tester_sa:02X}.{suffix}",
                RowColor.blue,
            )

    @staticmethod
    def _parse_source_address(text):
        raw = str(text).strip()
        if not raw:
            raise ValueError("Empty Source Address")

        base = 16 if raw.lower().startswith("0x") else 10
        value = int(raw, base)
        if value < 0 or value > 0xFF:
            raise ValueError("Source Address out of range")
        return value

    @staticmethod
    def _expand_qvariant_items(value):
        """Цель функции в нормализации QVariant/QJSValue, затем она разворачивает вход в плоский список элементов."""
        pending: list[object] = [value]
        normalized: list[object] = []

        while len(pending) > 0:
            current = pending.pop(0)
            if current is None:
                continue

            if hasattr(current, "isArray") and hasattr(current, "property"):
                try:
                    if bool(current.isArray()):
                        length_value = current.property("length")
                        if hasattr(length_value, "toVariant"):
                            length_value = length_value.toVariant()
                        length = int(length_value)
                        array_items = [current.property(index) for index in range(max(length, 0))]
                        pending = array_items + pending
                        continue
                except Exception:
                    pass

            converted = current
            if hasattr(current, "toVariant"):
                try:
                    converted = current.toVariant()
                except Exception:
                    converted = current

            if converted is None:
                continue

            if isinstance(converted, dict):
                indexed_items: list[tuple[int, object]] = []
                for key, item in converted.items():
                    try:
                        indexed_items.append((int(key), item))
                    except Exception:
                        continue
                if len(indexed_items) > 0:
                    pending = [item for _, item in sorted(indexed_items, key=lambda pair: pair[0])] + pending
                    continue

            if isinstance(converted, (list, tuple, set)):
                pending = list(converted) + pending
                continue

            normalized.append(converted)

        return normalized

    @staticmethod
    def _to_local_path(path_or_url):
        if not path_or_url:
            return ""

        if hasattr(path_or_url, "toVariant"):
            try:
                path_or_url = path_or_url.toVariant()
            except Exception:
                pass

        if isinstance(path_or_url, (list, tuple, set)):
            if len(path_or_url) <= 0:
                return ""
            first_item = next((item for item in path_or_url if item), None)
            if first_item is None:
                return ""
            path_or_url = first_item

        if hasattr(path_or_url, "__fspath__"):
            return str(path_or_url)

        if isinstance(path_or_url, QUrl):
            parsed = path_or_url
        else:
            raw_path = str(path_or_url).strip()
            if not raw_path:
                return ""
            if "://" not in raw_path and not raw_path.casefold().startswith("file:"):
                return raw_path
            parsed = QUrl(raw_path)

        if parsed.isLocalFile():
            return parsed.toLocalFile()

        if parsed.scheme() == "file":
            return parsed.toLocalFile()

        return str(path_or_url)

    def _set_programming_active(self, active):
        value = bool(active)
        if not value:
            if self._programming_start_timer.isActive():
                self._programming_start_timer.stop()
            self._pending_programming_after_reset = False
            if self._calibration_active and self._can.is_trace and (not self._calibration_waiting_session):
                self._start_calibration_poll_timer()
        else:
            self._stop_calibration_poll_timer()

        if self._programming_active == value:
            return
        self._programming_active = value
        self.programmingActiveChanged.emit()

    def _start_programming_after_reset(self):
        if not self._pending_programming_after_reset:
            return
        self._pending_programming_after_reset = False
        current_sa = self._programming_current_target_sa
        if current_sa is None:
            self._append_log("Автосброс завершен, запуск сценария программирования", RowColor.blue)
        else:
            self._append_log(
                f"Автосброс завершен, запуск сценария программирования узла 0x{int(current_sa) & 0xFF:02X}",
                RowColor.blue,
            )
        self._start_programming_flow()

    def _start_programming_flow(self):
        current_sa = self._programming_current_target_sa
        if current_sa is not None:
            self._apply_programming_target_sa(current_sa, "Запуск bootloader-сценария.")
        if not self._bootloader.start():
            self._set_programming_active(False)

    def _set_source_address_busy(self, busy):
        value = bool(busy)
        if self._source_address_busy == value:
            return
        self._source_address_busy = value
        if not value:
            self._set_source_address_operation("")
        self.sourceAddressBusyChanged.emit()

    def _set_source_address_operation(self, operation: str):
        value = str(operation).strip().lower()
        if value not in ("", "read", "write"):
            value = ""
        if self._source_address_operation == value:
            return
        self._source_address_operation = value
        self.sourceAddressOperationChanged.emit()

    def _set_firmware_loading(self, loading):
        value = bool(loading)
        if self._firmware_loading == value:
            return
        self._firmware_loading = value
        self.firmwareLoadingChanged.emit()

    def _append_log(self, text, color):
        if isinstance(color, QColor):
            color_value = color.name()
        else:
            color_value = "#cbd5e1"

        self._logs.append(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "text": str(text),
                "color": color_value,
            }
        )

        if len(self._logs) > 2000:
            self._logs = self._logs[-2000:]

        self.logsChanged.emit()

        if self._programming_active and isinstance(color, QColor) and color == RowColor.red:
            self._set_programming_active(False)
