from __future__ import annotations

import math
import struct
import time
from datetime import datetime

from j1939.j1939_can_identifier import J1939CanIdentifier
from uds.options_catalog import UdsOptionParameter, get_option_by_did, get_option_by_index
from uds.uds_identifiers import UdsIdentifiers

from .contract import AppControllerContract
from .workers import UdsOptionProxy

class AppControllerOptionsMixin(AppControllerContract):
    OPTIONS_OPERATION_TIMEOUT_MS = 4000
    OPTIONS_BULK_TIMEOUT_RETRY_LIMIT = 1
    OPTIONS_FLOW_CONTROL_STMIN = 0x0A  # 10 ms between CF frames for better stability on busy bus.

    def _set_options_bulk_busy(self, value: bool):
        new_value = bool(value)
        if bool(self._options_bulk_busy) == new_value:
            self._options_bulk_busy = new_value
            return
        self._options_bulk_busy = new_value
        # optionOperationBusy depends on _options_bulk_busy too.
        self.optionOperationChanged.emit()

    @staticmethod
    def _is_timeout_message(message: str) -> bool:
        text = str(message or "").lower()
        return ("таймаут" in text) or ("timeout" in text)

    def _options_bulk_get_retry_count(self, did: int) -> int:
        target = int(did) & 0xFFFF
        for row in self._options_bulk_rows:
            if int(row.get("didInt", -1)) == target:
                try:
                    return int(row.get("retryCount", 0))
                except (TypeError, ValueError):
                    return 0
        return 0

    def _handle_options_frame(self, identifier: int, payload: list[int]):
        if (not self._options_busy) or (len(payload) < 2):
            return

        if not self._is_options_response_identifier(identifier):
            return

        if self._options_pending_action == "read":
            pci_type = (int(payload[0]) >> 4) & 0x0F

            # Single Frame
            if pci_type == 0x0:
                sf_len = int(payload[0]) & 0x0F
                if sf_len <= 0 or sf_len > (len(payload) - 1):
                    return
                uds_payload = bytes(payload[1:1 + sf_len])
                if not self._is_expected_options_read_payload(uds_payload):
                    return
                self._touch_options_timeout()
                self._handle_options_read_payload(uds_payload)
                return

            # First Frame: старт сборки мультипакета и отправка Flow Control (CTS).
            if pci_type == 0x1:
                total_len = ((int(payload[0]) & 0x0F) << 8) | (int(payload[1]) & 0xFF)
                if total_len <= 0:
                    return

                initial_payload = bytes(payload[2:8])
                if len(initial_payload) > total_len:
                    initial_payload = initial_payload[:total_len]
                if not self._is_expected_options_read_payload(initial_payload):
                    return

                self._options_isotp_total_len = int(total_len)
                self._options_isotp_buffer = bytearray(payload[2:8])
                if len(self._options_isotp_buffer) > self._options_isotp_total_len:
                    self._options_isotp_buffer = self._options_isotp_buffer[:self._options_isotp_total_len]
                self._options_isotp_next_sn = 1
                self._touch_options_timeout()

                if not self._send_options_flow_control():
                    self._finish_options_operation(False, "Ошибка отправки Flow Control для UDS ISO-TP.")
                    return

                # For some ECUs first FC can be lost; retry FC only after FF was really received.
                self._options_fc_retry_left = 12
                if len(self._options_isotp_buffer) < self._options_isotp_total_len:
                    if not self._options_fc_retry_timer.isActive():
                        self._options_fc_retry_timer.start()

                if len(self._options_isotp_buffer) >= self._options_isotp_total_len:
                    uds_payload = bytes(self._options_isotp_buffer[:self._options_isotp_total_len])
                    self._handle_options_read_payload(uds_payload)
                return

            # Consecutive Frame: продолжаем сборку.
            if pci_type == 0x2:
                if self._options_isotp_total_len <= 0:
                    return

                self._touch_options_timeout()
                if self._options_fc_retry_timer.isActive():
                    self._options_fc_retry_timer.stop()
                    self._options_fc_retry_left = 0
                sn = int(payload[0]) & 0x0F
                if sn != (self._options_isotp_next_sn & 0x0F):
                    self._finish_options_operation(
                        False,
                        f"Ошибка UDS ISO-TP: ожидался SN=0x{self._options_isotp_next_sn & 0x0F:X}, получен SN=0x{sn:X}.",
                    )
                    return

                self._options_isotp_next_sn = (self._options_isotp_next_sn + 1) & 0x0F
                remaining = int(self._options_isotp_total_len) - len(self._options_isotp_buffer)
                if remaining > 0:
                    take = min(7, remaining)
                    self._options_isotp_buffer.extend(payload[1:1 + take])

                if len(self._options_isotp_buffer) >= self._options_isotp_total_len:
                    uds_payload = bytes(self._options_isotp_buffer[:self._options_isotp_total_len])
                    self._handle_options_read_payload(uds_payload)
                return

            # FlowControl от ECU на чтение нам не нужен.
            if pci_type == 0x3:
                return

            return

        if self._options_pending_action == "write":
            pci_type = (int(payload[0]) >> 4) & 0x0F

            # При мультикадровой записи DID 0x2E сначала ждем Flow Control от МК.
            # Если вместо FC пришел SF с NRC, обрабатываем отказ сразу и не ждем таймаут.
            if bool(self._options_write_isotp_active) and bool(self._options_write_isotp_waiting_fc):
                if pci_type == 0x3:
                    if not self._send_options_write_consecutive_frames(payload):
                        self._finish_options_operation(False, "Ошибка передачи Consecutive Frame для UDS записи DID.")
                        return
                    self._touch_options_timeout()
                    return

                if pci_type == 0x0:
                    sf_len = int(payload[0]) & 0x0F
                    if sf_len <= 0 or sf_len > (len(payload) - 1):
                        return
                    uds_payload = bytes(payload[1:1 + sf_len])
                    if len(uds_payload) > 0 and (int(uds_payload[0]) & 0xFF) == 0x6E:
                        if len(uds_payload) < 3:
                            return
                        did = ((int(uds_payload[1]) & 0xFF) << 8) | (int(uds_payload[2]) & 0xFF)
                        self._finish_options_operation(True, f"Запись DID 0x{did:04X} выполнена")
                        return
                    if len(uds_payload) > 0 and (int(uds_payload[0]) & 0xFF) == 0x7F:
                        original_sid = int(uds_payload[1]) & 0xFF if len(uds_payload) > 1 else 0
                        if original_sid != 0x2E:
                            return
                        nrc = int(uds_payload[2]) & 0xFF if len(uds_payload) > 2 else 0
                        if nrc == 0x78:
                            # MCU сообщает «response pending». Продолжаем ждать финальный ответ.
                            self._touch_options_timeout()
                            return
                        self._finish_options_operation(False, f"Негативный ответ UDS (NRC=0x{nrc:02X})")
                        return
                return

            if pci_type != 0x0:
                return

            sf_len = int(payload[0]) & 0x0F
            if sf_len <= 0 or sf_len > (len(payload) - 1):
                return

            uds_payload = bytes(payload[1:1 + sf_len])
            if len(uds_payload) > 0 and (int(uds_payload[0]) & 0xFF) == 0x7F:
                original_sid = int(uds_payload[1]) & 0xFF if len(uds_payload) > 1 else 0
                if original_sid != 0x2E:
                    return
                nrc = int(uds_payload[2]) & 0xFF if len(uds_payload) > 2 else 0
                self._finish_options_operation(False, f"Негативный ответ UDS (NRC=0x{nrc:02X})")
                return

            if not self._options_write_service.verify_answer_write_data(payload):
                return

            did = int(self._options_write_service.parse_pid_field(payload))
            self._finish_options_operation(True, f"Запись DID 0x{did:04X} выполнена")

    def _handle_options_read_payload(self, uds_payload: bytes):
        self._reset_options_isotp_state()

        if uds_payload is None or len(uds_payload) == 0:
            return

        sid = int(uds_payload[0]) & 0xFF
        if sid == 0x7F:
            nrc = int(uds_payload[2]) & 0xFF if len(uds_payload) > 2 else 0
            self._finish_options_operation(False, f"Негативный ответ UDS (NRC=0x{nrc:02X})")
            return

        if len(uds_payload) < 3:
            return

        sf_like_frame = [min(0xFF, len(uds_payload))] + [int(b) & 0xFF for b in uds_payload]
        if not self._options_read_service.verify_answer_read_data(sf_like_frame):
            self._finish_options_operation(False, "Unexpected UDS response while reading DID.")
            return

        did = int(self._options_read_service.parse_pid_field(sf_like_frame))
        data_bytes = bytes(uds_payload[3:])
        self._options_last_read_bytes = data_bytes
        self._options_value_text = self._format_option_data(data_bytes)
        self._options_raw_hex = " ".join(f"{int(b) & 0xFF:02X}" for b in data_bytes) if len(data_bytes) > 0 else "-"
        self.optionValueChanged.emit()
        self._finish_options_operation(True, f"Чтение DID 0x{did:04X} выполнено")

    def _send_options_flow_control(self) -> bool:
        try:
            target_sa = self._options_pending_target_sa
            if target_sa is None:
                target_sa = self._resolve_options_target_sa()
            tx_identifier = self._build_options_tx_identifier(int(target_sa) & 0xFF)
            payload = [0x30, 0x00, int(self.OPTIONS_FLOW_CONTROL_STMIN) & 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
            # Use async to avoid blocking callback processing while CF frames are incoming.
            ret = self._can.send_async(tx_identifier, 8, payload)
            if ret is None:
                return False
            return int(ret) in (0, 5)
        except Exception:
            return False

    @staticmethod
    def _is_send_success(ret) -> bool:
        """Цель функции в единообразной проверке send_async, затем она считает успешным любой неотрицательный код."""
        if ret is None:
            return False
        if isinstance(ret, bool):
            return bool(ret)
        try:
            return int(ret) >= 0
        except Exception:
            return bool(ret)

    @staticmethod
    def _isotp_stmin_to_seconds(raw_stmin: int) -> float:
        """Цель функции в преобразовании STmin из Flow Control, затем она возвращает задержку между CF в секундах."""
        value = int(raw_stmin) & 0xFF
        if value <= 0x7F:
            return float(value) / 1000.0
        if 0xF1 <= value <= 0xF9:
            return float(value - 0xF0) / 10000.0
        return 0.0

    def _build_options_write_isotp_frames(self, uds_payload: bytes) -> tuple[list[int], list[list[int]]]:
        """Цель функции в формировании ISO-TP кадрирования 0x2E, затем она возвращает FF и список CF."""
        payload = bytes(uds_payload or b"")
        total_len = len(payload)
        if total_len <= 7:
            single = [int(total_len) & 0x0F] + [int(item) & 0xFF for item in payload]
            while len(single) < 8:
                single.append(0xFF)
            return single, []

        first_frame = [
            0x10 | ((total_len >> 8) & 0x0F),
            total_len & 0xFF,
        ]
        first_frame.extend(int(item) & 0xFF for item in payload[:6])
        while len(first_frame) < 8:
            first_frame.append(0xFF)

        cf_frames: list[list[int]] = []
        sn = 1
        index = 6
        while index < total_len:
            frame = [0x20 | (sn & 0x0F)]
            chunk = payload[index:index + 7]
            frame.extend(int(item) & 0xFF for item in chunk)
            while len(frame) < 8:
                frame.append(0xFF)
            cf_frames.append(frame)
            index += len(chunk)
            sn = (sn + 1) & 0x0F
            if sn <= 0:
                sn = 1

        return first_frame, cf_frames

    def _reset_options_write_isotp_state(self):
        """Цель функции в очистке состояния мультикадровой записи, затем она готовит контроллер к следующей операции."""
        self._options_write_isotp_active = False
        self._options_write_isotp_waiting_fc = False
        self._options_write_isotp_cf_frames = []

    def _send_options_write_consecutive_frames(self, flow_control_payload: list[int]) -> bool:
        """Цель функции в отправке CF после FC, затем она соблюдает block-size и STmin полученные от МК."""
        if flow_control_payload is None or len(flow_control_payload) < 3:
            return False

        flow_status = int(flow_control_payload[0]) & 0x0F
        if flow_status == 0x1:
            # ECU просит подождать, продолжаем ожидание следующего Flow Control.
            self._options_write_isotp_waiting_fc = True
            return True
        if flow_status != 0x0:
            return False

        block_size = int(flow_control_payload[1]) & 0xFF
        stmin_seconds = self._isotp_stmin_to_seconds(int(flow_control_payload[2]) & 0xFF)

        remaining = list(self._options_write_isotp_cf_frames)
        if len(remaining) <= 0:
            self._options_write_isotp_waiting_fc = False
            return True

        send_count = len(remaining) if block_size == 0 else min(block_size, len(remaining))
        target_sa = self._options_pending_target_sa
        if target_sa is None:
            target_sa = self._resolve_options_target_sa()
        tx_identifier = self._build_options_tx_identifier(int(target_sa) & 0xFF)

        for index in range(send_count):
            frame = remaining[index]
            ret = self._can.send_async(int(tx_identifier), 8, frame)
            if not self._is_send_success(ret):
                return False
            if stmin_seconds > 0 and index < (send_count - 1):
                time.sleep(stmin_seconds)

        self._options_write_isotp_cf_frames = remaining[send_count:]
        self._options_write_isotp_waiting_fc = len(self._options_write_isotp_cf_frames) > 0
        return True

    def _start_options_write_multiframe_request(
        self,
        parameter: UdsOptionParameter,
        value_bytes: bytes,
        request_origin: str,
        append_history: bool,
        target_sa_override: int | None = None,
    ) -> bool:
        """Цель функции в запуске мультикадровой записи DID, затем она отправляет FF и ожидает FC от МК."""
        if parameter is None or not parameter.can_write:
            return False

        payload = bytes(value_bytes or b"")
        if len(payload) <= 0:
            return False

        target_sa = self._resolve_options_target_sa() if target_sa_override is None else (int(target_sa_override) & 0xFF)
        tx_identifier = self._build_options_tx_identifier(target_sa)
        did_b0, did_b1 = self._options_write_service._pid_to_bytes(int(parameter.did) & 0xFFFF)
        uds_payload = bytes([0x2E, int(did_b0) & 0xFF, int(did_b1) & 0xFF]) + payload
        first_frame, cf_frames = self._build_options_write_isotp_frames(uds_payload)

        self._options_pending_action = "write"
        self._options_pending_did = int(parameter.did) & 0xFFFF
        self._options_pending_target_sa = int(target_sa) & 0xFF
        self._options_pending_write_bytes = payload
        self._options_last_read_bytes = b""
        self._options_request_origin = str(request_origin or "")
        self._options_busy = True
        self._options_status = f"Запись DID 0x{int(parameter.did) & 0xFFFF:04X} (SA 0x{int(target_sa) & 0xFF:02X})..."
        self.optionOperationChanged.emit()

        self._reset_options_isotp_state()
        self._options_fc_retry_left = 0
        self._options_fc_retry_timer.stop()
        self._options_write_isotp_active = len(cf_frames) > 0
        self._options_write_isotp_waiting_fc = len(cf_frames) > 0
        self._options_write_isotp_cf_frames = list(cf_frames)

        ret = self._can.send_async(int(tx_identifier), 8, first_frame)
        if not self._is_send_success(ret):
            self._finish_options_operation(False, "Не удалось отправить первый ISO-TP кадр записи DID.")
            return False

        if append_history:
            self._append_option_history(
                "Запись",
                parameter,
                "Отправлено",
                f"SA 0x{int(target_sa) & 0xFF:02X} | мультикадровая запись",
                "#0ea5e9",
                value_bytes=payload,
            )

        self._touch_options_timeout()
        return True

    def _touch_options_timeout(self):
        self._options_timeout_timer.start(self.OPTIONS_OPERATION_TIMEOUT_MS)

    def _is_expected_options_read_payload(self, uds_payload: bytes) -> bool:
        if uds_payload is None or len(uds_payload) == 0:
            return False

        sid = int(uds_payload[0]) & 0xFF
        if sid == 0x7F:
            return (len(uds_payload) >= 2) and ((int(uds_payload[1]) & 0xFF) == int(self._options_read_service.sid))

        if len(uds_payload) < 3:
            return False

        sf_like_frame = [min(0xFF, len(uds_payload))] + [int(b) & 0xFF for b in uds_payload]
        return bool(self._options_read_service.verify_answer_read_data(sf_like_frame))

    def _reset_options_isotp_state(self):
        self._options_isotp_total_len = 0
        self._options_isotp_buffer = bytearray()
        self._options_isotp_next_sn = 1

    def _start_options_read_request(
        self,
        parameter: UdsOptionParameter,
        request_origin: str,
        append_history: bool,
        target_sa_override: int | None = None,
    ) -> bool:
        if parameter is None or not parameter.can_read:
            return False

        target_sa = self._resolve_options_target_sa() if target_sa_override is None else (int(target_sa_override) & 0xFF)
        tx_identifier = self._build_options_tx_identifier(target_sa)

        self._options_pending_action = "read"
        self._options_pending_did = int(parameter.did) & 0xFFFF
        self._options_pending_target_sa = int(target_sa) & 0xFF
        self._options_last_read_bytes = b""
        self._options_request_origin = str(request_origin or "")
        self._reset_options_isotp_state()
        self._reset_options_write_isotp_state()
        self._options_fc_retry_left = 0
        self._options_fc_retry_timer.stop()
        self._options_busy = True
        self._options_status = f"Чтение DID 0x{int(parameter.did) & 0xFFFF:04X} (SA 0x{int(target_sa) & 0xFF:02X})..."
        self.optionOperationChanged.emit()

        try:
            sent = self._options_read_service.read_data_by_identifier(
                tx_identifier,
                UdsOptionProxy(parameter.did, parameter.size, parameter.name),
            )
            if not sent:
                raise RuntimeError("send_async failed for DID read request")
        except Exception:
            self._options_busy = False
            self._options_pending_action = ""
            self._options_pending_did = None
            self._options_pending_target_sa = None
            self._options_last_read_bytes = b""
            self._options_request_origin = ""
            self._options_status = "Ошибка отправки запроса чтения"
            self.optionOperationChanged.emit()
            return False

        if append_history:
            self._append_option_history(
                "Чтение",
                parameter,
                "Отправлено",
                f"SA 0x{int(target_sa) & 0xFF:02X} | ожидание ответа UDS",
                "#0ea5e9",
            )

        self._options_timeout_timer.start(self.OPTIONS_OPERATION_TIMEOUT_MS)
        return True

    def _on_options_timeout(self):
        if not self._options_busy:
            return
        if int(self._options_isotp_total_len) > 0:
            received = len(self._options_isotp_buffer)
            expected = int(self._options_isotp_total_len)
            next_sn = int(self._options_isotp_next_sn) & 0x0F
            self._finish_options_operation(
                False,
                (
                    "Таймаут UDS ISO-TP: неполный мультифрейм "
                    f"({received}/{expected} байт), ожидался CF SN=0x{next_sn:X}."
                ),
            )
            return
        self._finish_options_operation(False, "Таймаут ожидания ответа UDS (не получен SF/FF).")

    def _on_options_fc_retry_tick(self):
        if (not self._options_busy) or (self._options_pending_action != "read"):
            self._options_fc_retry_timer.stop()
            self._options_fc_retry_left = 0
            return

        # Retry FC only while waiting for CF after a received FF.
        if self._options_isotp_total_len <= 0:
            self._options_fc_retry_timer.stop()
            self._options_fc_retry_left = 0
            return
        if len(self._options_isotp_buffer) >= self._options_isotp_total_len:
            self._options_fc_retry_timer.stop()
            self._options_fc_retry_left = 0
            return

        if self._options_fc_retry_left <= 0:
            self._options_fc_retry_timer.stop()
            return

        self._options_fc_retry_left -= 1
        if not self._send_options_flow_control():
            self._options_fc_retry_timer.stop()
            self._options_fc_retry_left = 0

    def _refresh_options_selection(self, emit_signal: bool):
        parameter = get_option_by_index(self._selected_option_index)
        if parameter is None:
            self._options_selected_did = "-"
            self._options_selected_name = "-"
            self._options_selected_size = "-"
            self._options_selected_access = "-"
            self._options_selected_note = ""
            self._options_selected_can_read = False
            self._options_selected_can_write = False
        else:
            self._options_selected_did = f"0x{int(parameter.did) & 0xFFFF:04X}"
            self._options_selected_name = str(parameter.name)
            self._options_selected_size = f"{int(parameter.size)} байт"
            self._options_selected_access = str(parameter.access.value)
            self._options_selected_note = str(parameter.note or "")
            self._options_selected_can_read = bool(parameter.can_read)
            self._options_selected_can_write = bool(parameter.can_write)

        if emit_signal:
            self.optionSelectionChanged.emit()

    def _resolve_options_target_sa(self) -> int:
        if self._options_target_node_sa is not None:
            return int(self._options_target_node_sa) & 0xFF
        return int(UdsIdentifiers.rx.src) & 0xFF

    def _build_options_tx_identifier(self, target_sa: int | None = None) -> int:
        try:
            tx = J1939CanIdentifier(int(UdsIdentifiers.tx.identifier))
            resolved_sa = self._resolve_options_target_sa() if target_sa is None else (int(target_sa) & 0xFF)
            tx.dst = resolved_sa
            return int(tx.identifier)
        except Exception:
            return int(UdsIdentifiers.tx.identifier)

    def _is_options_response_identifier(self, identifier: int) -> bool:
        try:
            parsed = J1939CanIdentifier(int(identifier))
        except Exception:
            return False

        expected_pgn = int(UdsIdentifiers.rx.pgn) & 0x3FFFF
        if (int(parsed.pgn) & 0x3FFFF) != expected_pgn:
            return False

        expected_dst = int(UdsIdentifiers.rx.dst) & 0xFF
        if (int(parsed.dst) & 0xFF) != expected_dst:
            return False

        expected_src = self._options_pending_target_sa
        if expected_src is None:
            expected_src = self._resolve_options_target_sa()
        return (int(parsed.src) & 0xFF) == (int(expected_src) & 0xFF)

    def _refresh_options_target_node_options(self, emit_signal: bool = True):
        previous_values = list(self._options_target_node_values)
        previous_items = list(self._options_target_node_items)
        previous_selected = int(self._selected_options_target_node_index)

        selected_sa = self._options_target_node_sa
        if selected_sa is None and 0 <= previous_selected < len(previous_values):
            previous_value = previous_values[previous_selected]
            if previous_value is not None:
                selected_sa = int(previous_value) & 0xFF

        default_sa = int(UdsIdentifiers.rx.src) & 0xFF
        new_values: list[int | None] = [None]
        new_items: list[str] = [f"Авто (UDS RX SA: 0x{default_sa:02X})"]
        seen_values: set[int] = set()
        for device_sa in self._observed_candidate_values:
            value = int(device_sa) & 0xFF
            if value in seen_values:
                continue
            seen_values.add(value)
            new_values.append(value)
            new_items.append(f"Узел 0x{value:02X}")

        new_selected = 0
        if selected_sa is not None and selected_sa in new_values:
            new_selected = new_values.index(selected_sa)
        elif 0 <= previous_selected < len(new_values):
            new_selected = previous_selected

        self._options_target_node_values = new_values
        self._options_target_node_items = new_items
        self._selected_options_target_node_index = int(new_selected)

        selected_value = new_values[new_selected] if 0 <= new_selected < len(new_values) else None
        self._options_target_node_sa = None if selected_value is None else int(selected_value) & 0xFF

        if emit_signal and (
            previous_values != self._options_target_node_values
            or previous_items != self._options_target_node_items
            or previous_selected != self._selected_options_target_node_index
        ):
            self.optionsTargetNodeChanged.emit()

    def _parse_option_write_value(self, parameter: UdsOptionParameter, text: str) -> int:
        raw = str(text or "").strip()
        if not raw:
            raise ValueError("Поле значения для записи пустое.")

        base = 16 if raw.lower().startswith("0x") else 10
        try:
            value = int(raw, base)
        except ValueError as exc:
            raise ValueError("Значение записи должно быть числом (dec или 0xHEX).") from exc

        if value < 0:
            raise ValueError("Отрицательные значения не поддерживаются.")

        max_value = (1 << (int(parameter.size) * 8)) - 1 if int(parameter.size) > 0 else 0
        if value > max_value:
            raise ValueError(f"Значение не помещается в {int(parameter.size)} байт.")

        return int(value)

    def _format_option_data(self, data: bytes) -> str:
        if data is None or len(data) == 0:
            return "-"

        payload = bytes(data)
        if len(payload) <= 8:
            value_le = int.from_bytes(payload, byteorder="little", signed=False)
            value_be = int.from_bytes(payload, byteorder="big", signed=False)
            return f"LE={value_le} | BE={value_be}"

        return f"{len(payload)} байт"

    @staticmethod
    def _encode_option_value_bytes(value: int, size: int) -> bytes:
        byte_size = int(size)
        if byte_size <= 0:
            return b""
        return int(value).to_bytes(byte_size, byteorder="little", signed=False)

    @staticmethod
    def _decode_software_version_bytes(value_bytes: bytes | None) -> str:
        """Цель функции в декодировании поля DID 0xF195, затем она возвращает строку до первого нулевого байта."""
        if value_bytes is None:
            return ""
        payload = bytes(value_bytes)
        if len(payload) <= 0:
            return ""
        trimmed = payload.split(b"\x00", 1)[0]
        if len(trimmed) <= 0:
            return ""
        try:
            return trimmed.decode("utf-8").strip()
        except UnicodeDecodeError:
            return trimmed.decode("latin-1", errors="ignore").strip()

    @staticmethod
    def _build_option_value_variants(value_bytes: bytes | None) -> dict[str, object]:
        if value_bytes is None or len(value_bytes) == 0:
            return {
                "hasValue": False,
                "rawHex": "-",
                "valueLeDec": "-",
                "valueLeHex": "-",
                "valueLeFloat": "-",
                "valueAscii": "-",
                "valueUtf8": "-",
                "valueBeDec": "-",
                "valueBeHex": "-",
                "valueBeFloat": "-",
            }

        payload = bytes(value_bytes)
        value_le = int.from_bytes(payload, byteorder="little", signed=False)
        value_be = int.from_bytes(payload, byteorder="big", signed=False)
        value_le_float = AppControllerOptionsMixin._format_option_float(payload, little_endian=True)
        value_be_float = AppControllerOptionsMixin._format_option_float(payload, little_endian=False)
        value_ascii = AppControllerOptionsMixin._format_option_ascii(payload)
        value_utf8 = AppControllerOptionsMixin._format_option_utf8(payload)
        return {
            "hasValue": True,
            "rawHex": " ".join(f"{int(b) & 0xFF:02X}" for b in payload),
            "valueLeDec": str(value_le),
            "valueLeHex": f"0x{value_le:X}",
            "valueLeFloat": value_le_float,
            "valueAscii": value_ascii,
            "valueUtf8": value_utf8,
            "valueBeDec": str(value_be),
            "valueBeHex": f"0x{value_be:X}",
            "valueBeFloat": value_be_float,
        }

    @staticmethod
    def _format_option_float(payload: bytes, little_endian: bool) -> str:
        size = len(payload)
        if size not in (4, 8):
            return "-"

        if size == 4:
            fmt = "<f" if little_endian else ">f"
        else:
            fmt = "<d" if little_endian else ">d"

        try:
            value = float(struct.unpack(fmt, payload)[0])
        except Exception:
            return "-"

        if not math.isfinite(value):
            return str(value)
        return f"{value:.6g}"

    @staticmethod
    def _format_option_ascii(payload: bytes) -> str:
        if payload is None or len(payload) == 0:
            return "-"

        parts: list[str] = []
        for byte in payload:
            value = int(byte) & 0xFF
            if 0x20 <= value <= 0x7E:
                parts.append(chr(value))
            elif value == 0x0A:
                parts.append("\\n")
            elif value == 0x0D:
                parts.append("\\r")
            elif value == 0x09:
                parts.append("\\t")
            else:
                parts.append(f"\\x{value:02X}")
        return "".join(parts) if len(parts) > 0 else "-"

    @staticmethod
    def _format_option_utf8(payload: bytes) -> str:
        if payload is None or len(payload) == 0:
            return "-"

        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            text = payload.decode("utf-8", errors="replace")

        text = text.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
        return text if len(text) > 0 else "-"

    def _append_option_history(
        self,
        action: str,
        parameter: UdsOptionParameter,
        result: str,
        details: str,
        color: str,
        value_bytes: bytes | None = None,
    ):
        variants = self._build_option_value_variants(value_bytes)
        row_id = int(self._options_history_next_id)
        self._options_history_next_id += 1
        row: dict[str, object] = {
            "rowId": row_id,
            "time": datetime.now().strftime("%H:%M:%S"),
            "action": str(action),
            "did": f"0x{int(parameter.did) & 0xFFFF:04X}",
            "name": str(parameter.name),
            "result": str(result),
            "details": str(details),
            "color": str(color),
        }
        row.update(variants)
        self._options_history.append(row)

        if len(self._options_history) > 600:
            self._options_history = self._options_history[-600:]

        self.optionHistoryChanged.emit()

    def _format_options_bulk_value(self, value_bytes: bytes | None) -> str:
        variants = self._build_option_value_variants(value_bytes)
        if not bool(variants.get("hasValue")):
            return "-"
        return str(variants.get("rawHex", "-"))

    def _options_bulk_update_row(
        self,
        did: int,
        status: str,
        color: str,
        details: str,
        value_bytes: bytes | None = None,
        retry_increment: bool = False,
    ):
        updated: list[dict[str, object]] = []
        target = int(did) & 0xFFFF
        variants = self._build_option_value_variants(value_bytes)
        for row in self._options_bulk_rows:
            current = dict(row)
            if int(current.get("didInt", -1)) == target:
                current["status"] = str(status)
                current["color"] = str(color)
                current["details"] = str(details)
                current.update(variants)
                current["value"] = (
                    str(variants.get("rawHex", "-"))
                    if bool(variants.get("hasValue"))
                    else "-"
                )
                if retry_increment:
                    try:
                        current["retryCount"] = int(current.get("retryCount", 0)) + 1
                    except (TypeError, ValueError):
                        current["retryCount"] = 1
            updated.append(current)
        self._options_bulk_rows = updated
        self.optionsBulkRowsChanged.emit()

    def _start_options_bulk_read(self):
        readable = [item for item in self._options_parameters if bool(item.can_read)]
        self._options_bulk_plan = list(readable)
        self._options_bulk_next_index = 0
        self._options_bulk_success_count = 0
        self._options_bulk_fail_count = 0
        self._options_bulk_rows = [
            {
                "rowId": int(item.did) & 0xFFFF,
                "didInt": int(item.did) & 0xFFFF,
                "did": f"0x{int(item.did) & 0xFFFF:04X}",
                "name": str(item.name),
                "size": int(item.size),
                "access": str(item.access.value),
                "status": "Ожидание",
                "color": "#64748b",
                "value": "-",
                "details": "",
                "retryCount": 0,
                **self._build_option_value_variants(None),
            }
            for item in readable
        ]
        self.optionsBulkRowsChanged.emit()

        if len(self._options_bulk_plan) == 0:
            self._set_options_bulk_busy(False)
            self._options_bulk_status = "Нет DID с доступом на чтение."
            self.optionsBulkChanged.emit()
            return

        self._set_options_bulk_busy(True)
        self._options_bulk_status = f"Подготовка к чтению {len(self._options_bulk_plan)} DID..."
        self.optionsBulkChanged.emit()
        self._send_next_options_bulk_request()

    def _stop_options_bulk_read(self, reason: str):
        if self._options_bulk_step_timer.isActive():
            self._options_bulk_step_timer.stop()

        was_busy = bool(self._options_bulk_busy)
        self._set_options_bulk_busy(False)
        self._options_bulk_plan = []
        self._options_bulk_next_index = 0
        self._options_bulk_status = str(reason)
        self.optionsBulkChanged.emit()

        if was_busy and self._options_busy and str(self._options_request_origin or "") == "bulk":
            self._finish_options_operation(False, str(reason))

    def _send_next_options_bulk_request(self):
        if not self._options_bulk_busy:
            return
        if self._options_busy:
            return

        total = len(self._options_bulk_plan)
        if self._options_bulk_next_index >= total:
            self._set_options_bulk_busy(False)
            self._options_bulk_status = (
                f"Готово. Успешно: {int(self._options_bulk_success_count)}, "
                f"ошибок: {int(self._options_bulk_fail_count)}, всего: {total}."
            )
            self._options_bulk_plan = []
            self._options_bulk_next_index = 0
            self.optionsBulkChanged.emit()
            return

        parameter = self._options_bulk_plan[self._options_bulk_next_index]
        self._options_bulk_next_index += 1

        did = int(parameter.did) & 0xFFFF
        self._options_bulk_update_row(did, "Запрос", "#0ea5e9", "Ожидание ответа UDS")
        self._options_bulk_status = f"Чтение {self._options_bulk_next_index}/{total}: DID 0x{did:04X}"
        self.optionsBulkChanged.emit()

        if not self._start_options_read_request(parameter, request_origin="bulk", append_history=False):
            self._on_options_bulk_read_finished(False, did, "Ошибка отправки запроса чтения DID.", None)

    def _on_options_bulk_step_tick(self):
        self._send_next_options_bulk_request()

    def _on_options_bulk_read_finished(self, success: bool, did: int, message: str, value_bytes: bytes | None):
        if not self._options_bulk_busy:
            return

        target_did = int(did) & 0xFFFF
        if (not success) and self._is_timeout_message(message):
            retries_used = self._options_bulk_get_retry_count(target_did)
            if retries_used < self.OPTIONS_BULK_TIMEOUT_RETRY_LIMIT:
                self._options_bulk_update_row(
                    target_did,
                    "Повтор",
                    "#f59e0b",
                    f"Таймаут ответа UDS, повтор {retries_used + 1}/{self.OPTIONS_BULK_TIMEOUT_RETRY_LIMIT}",
                    retry_increment=True,
                )
                parameter = get_option_by_did(target_did)
                if parameter is not None and bool(parameter.can_read):
                    self._options_bulk_status = (
                        f"Повтор {retries_used + 1}/{self.OPTIONS_BULK_TIMEOUT_RETRY_LIMIT}: DID 0x{target_did:04X}"
                    )
                    self.optionsBulkChanged.emit()
                    if self._start_options_read_request(parameter, request_origin="bulk", append_history=False):
                        return

        if success:
            self._options_bulk_success_count += 1
            self._options_bulk_update_row(
                target_did,
                "OK",
                "#16a34a",
                "Данные получены",
                value_bytes,
            )
        else:
            self._options_bulk_fail_count += 1
            self._options_bulk_update_row(
                target_did,
                "Ошибка",
                "#dc2626",
                str(message),
            )

        done = int(self._options_bulk_success_count) + int(self._options_bulk_fail_count)
        total = len(self._options_bulk_plan)
        if done >= total:
            self._set_options_bulk_busy(False)
            self._options_bulk_status = (
                f"Готово. Успешно: {int(self._options_bulk_success_count)}, "
                f"ошибок: {int(self._options_bulk_fail_count)}, всего: {total}."
            )
            self._options_bulk_plan = []
            self._options_bulk_next_index = 0
            self.optionsBulkChanged.emit()
            return

        delay = int(self._options_bulk_delay_ms)
        self._options_bulk_status = f"Пауза {delay} мс перед следующим DID ({done}/{total})"
        self.optionsBulkChanged.emit()
        if delay <= 0:
            self._send_next_options_bulk_request()
        else:
            self._options_bulk_step_timer.start(delay)

    def _finish_options_operation(self, success: bool, message: str):
        pending_did = int(self._options_pending_did) & 0xFFFF if self._options_pending_did is not None else None
        pending_action = str(self._options_pending_action or "")
        request_origin = str(self._options_request_origin or "")
        pending_target_sa = self._options_pending_target_sa

        parameter = get_option_by_did(pending_did) if pending_did is not None else get_option_by_index(self._selected_option_index)
        action = "Чтение" if pending_action == "read" else "Запись"
        result = "OK" if success else "Ошибка"
        color = "#16a34a" if success else "#dc2626"
        details = str(message)
        value_bytes: bytes | None = None

        if success and pending_action == "read":
            value_bytes = bytes(self._options_last_read_bytes)
            details = "Данные получены" if len(value_bytes) > 0 else "Ответ без данных"
        elif success and pending_action == "write":
            value_bytes = bytes(self._options_pending_write_bytes)
            details = "Запись подтверждена"

        if parameter is not None and request_origin != "bulk":
            self._append_option_history(action, parameter, result, details, color, value_bytes=value_bytes)

        # Для DID 0xF195 синхронизируем компактный виджет версии ПО на главной форме.
        if request_origin in ("sw_version_read", "sw_version_write"):
            if success and pending_action == "read":
                decoded = self._decode_software_version_bytes(value_bytes)
                self._software_version_text = decoded if decoded else "—"
                self._software_version_status = "Версия ПО считана по DID 0xF195."
            elif success and pending_action == "write":
                decoded = self._decode_software_version_bytes(value_bytes)
                if decoded:
                    self._software_version_text = decoded
                self._software_version_status = "Версия ПО записана в DID 0xF195."
            else:
                nrc_value = None
                upper_message = str(message or "").upper()
                nrc_marker = "NRC=0X"
                marker_index = upper_message.find(nrc_marker)
                if marker_index >= 0 and len(upper_message) >= (marker_index + len(nrc_marker) + 2):
                    nrc_hex = upper_message[marker_index + len(nrc_marker): marker_index + len(nrc_marker) + 2]
                    try:
                        nrc_value = int(nrc_hex, 16)
                    except (TypeError, ValueError):
                        nrc_value = None

                if nrc_value in (0x7E, 0x7F):
                    if (
                        (pending_target_sa is not None)
                        and (self._service_access_target_sa is not None)
                        and ((int(self._service_access_target_sa) & 0xFF) == (int(pending_target_sa) & 0xFF))
                    ):
                        # Сбрасываем локальный флаг, чтобы оператор повторно выполнил 0x27 перед новой записью.
                        self._service_security_unlocked = False
                        self.serviceAccessChanged.emit()
                    if pending_target_sa is None:
                        self._software_version_status = (
                            "Ошибка DID 0xF195: на МК неактивна требуемая сессия/доступ. "
                            "Повторите 0x10 (Extended 0x03) и 0x27, затем повторите запись."
                        )
                    else:
                        self._software_version_status = (
                            f"Ошибка DID 0xF195 для SA 0x{int(pending_target_sa) & 0xFF:02X}: "
                            "на МК неактивна требуемая сессия/доступ. "
                            "Повторите 0x10 (Extended 0x03) и 0x27, затем повторите запись."
                        )
                else:
                    self._software_version_status = f"Ошибка DID 0xF195: {str(message)}"
            self._software_version_busy = False
            self.softwareVersionChanged.emit()

        self._options_busy = False
        self._options_pending_action = ""
        self._options_pending_did = None
        self._options_pending_target_sa = None
        self._options_pending_write_bytes = b""
        self._options_last_read_bytes = b""
        self._options_request_origin = ""
        self._reset_options_isotp_state()
        self._reset_options_write_isotp_state()
        if self._options_fc_retry_timer.isActive():
            self._options_fc_retry_timer.stop()
        self._options_fc_retry_left = 0
        self._options_status = str(message)
        self._options_timeout_timer.stop()
        self.optionOperationChanged.emit()

        if request_origin == "bulk" and pending_action == "read" and pending_did is not None:
            self._on_options_bulk_read_finished(success, pending_did, str(message), value_bytes)

        if not success and request_origin != "bulk":
            self.infoMessage.emit("Параметры UDS", str(message))

    def _cancel_options_operation(self, message: str):
        if self._options_bulk_busy:
            self._stop_options_bulk_read(str(message))
            return
        if not self._options_busy:
            return
        self._finish_options_operation(False, str(message))
