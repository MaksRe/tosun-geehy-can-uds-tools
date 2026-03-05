from __future__ import annotations

import time

from j1939.j1939_can_identifier import J1939CanIdentifier
from colors import RowColor
from uds.data_identifiers import UdsData
from uds.uds_identifiers import UdsIdentifiers

from .contract import AppControllerContract

class AppControllerCalibrationMixin(AppControllerContract):
    def _is_calibration_response_identifier(self, identifier: int) -> bool:
        try:
            parsed = J1939CanIdentifier(int(identifier))
        except Exception:
            return False

        expected_pgn = int(UdsIdentifiers.rx.pgn) & 0x3FFFF
        parsed_pgn = int(parsed.pgn) & 0x3FFFF
        if parsed_pgn != expected_pgn:
            return False

        expected_dst = int(UdsIdentifiers.rx.dst) & 0xFF
        if (int(parsed.dst) & 0xFF) != expected_dst:
            return False

        parsed_src = int(parsed.src) & 0xFF
        if self._calibration_target_node_sa is None:
            return parsed_src == (int(UdsIdentifiers.rx.src) & 0xFF)
        return parsed_src == (int(self._calibration_target_node_sa) & 0xFF)

    def _build_calibration_tx_identifier(self) -> int:
        try:
            tx = J1939CanIdentifier(int(UdsIdentifiers.tx.identifier))
            if self._calibration_target_node_sa is not None:
                tx.dst = int(self._calibration_target_node_sa) & 0xFF
            return int(tx.identifier)
        except Exception:
            return int(UdsIdentifiers.tx.identifier)

    def _resolve_calibration_target_sa(self) -> int:
        if self._calibration_target_node_sa is not None:
            return int(self._calibration_target_node_sa) & 0xFF
        return int(UdsIdentifiers.rx.src) & 0xFF

    def _configure_calibration_uds_services(self):
        # Для этого МК DID в 0x22/0x2E всегда идут в стандартном UDS big-endian порядке.
        self._calibration_read_service.set_byte_order("big")
        self._calibration_write_service.set_byte_order("big")

    @staticmethod
    def _calibration_did_label(did: int) -> str:
        if int(did) == int(UdsData.empty_fuel_tank.pid):
            return "уровня 0%"
        if int(did) == int(UdsData.full_fuel_tank.pid):
            return "уровня 100%"
        return f"DID 0x{int(did) & 0xFFFF:04X}"

    def _pending_calibration_write_did(self) -> int | None:
        if self._calibration_restore_current_did is not None:
            return int(self._calibration_restore_current_did)

        for did in (int(UdsData.empty_fuel_tank.pid), int(UdsData.full_fuel_tank.pid)):
            if did in self._calibration_write_verify_pending:
                return did

        if len(self._calibration_write_verify_pending) == 1:
            return int(next(iter(self._calibration_write_verify_pending.keys())))

        return None

    def _is_calibration_security_ready(self) -> bool:
        if (not self._service_security_unlocked) or (self._service_access_target_sa is None):
            return False
        return (int(self._service_access_target_sa) & 0xFF) == self._resolve_calibration_target_sa()

    def _ensure_calibration_write_ready(self, operation_label: str) -> bool:
        if not self._can.is_connect:
            self.infoMessage.emit("Калибровка", "Сначала подключите CAN-адаптер.")
            return False

        if not self._can.is_trace:
            self.infoMessage.emit("Калибровка", "Сначала включите трассировку CAN.")
            return False

        if not self._calibration_session_ready:
            message = "Сначала запустите калибровку и дождитесь подтверждения extended-сессии UDS."
            self.infoMessage.emit("Калибровка", message)
            self._append_log(f"Калибровка: {operation_label} не отправлена. {message}", RowColor.yellow)
            return False

        target_sa = self._resolve_calibration_target_sa()
        if self._service_access_target_sa is None or not self._service_security_unlocked:
            message = f"Для записи откройте Security Access 0x27 для узла 0x{target_sa:02X}."
            self.infoMessage.emit("Калибровка", message)
            self._append_log(f"Калибровка: {operation_label} не отправлена. {message}", RowColor.yellow)
            return False

        access_target_sa = int(self._service_access_target_sa) & 0xFF
        if access_target_sa != target_sa:
            message = (
                f"Security Access открыт для узла 0x{access_target_sa:02X}, "
                f"а калибровка настроена на узел 0x{target_sa:02X}."
            )
            self.infoMessage.emit("Калибровка", message)
            self._append_log(f"Калибровка: {operation_label} не отправлена. {message}", RowColor.yellow)
            return False

        self._configure_calibration_uds_services()
        return True

    def _reset_calibration_sequence_state(self):
        if self._calibration_sequence_delay_timer.isActive():
            self._calibration_sequence_delay_timer.stop()
        if self._calibration_sequence_timeout_timer.isActive():
            self._calibration_sequence_timeout_timer.stop()
        self._calibration_sequence_next_action = ""
        self._calibration_sequence_waiting_action = ""

    def _schedule_calibration_sequence_action(self, action: str, delay_ms: int | None = None):
        self._calibration_sequence_next_action = str(action or "")
        delay = self._calibration_sequence_delay_ms if delay_ms is None else delay_ms
        self._calibration_sequence_delay_timer.start(max(0, int(delay)))

    def _start_calibration_sequence_wait(self, action: str):
        self._calibration_sequence_waiting_action = str(action or "")
        if self._calibration_sequence_timeout_timer.isActive():
            self._calibration_sequence_timeout_timer.stop()
        self._calibration_sequence_timeout_timer.start(self._calibration_sequence_timeout_ms)

    def _finish_calibration_sequence_wait(self, expected_action: str | None = None) -> bool:
        current_action = str(self._calibration_sequence_waiting_action or "")
        if expected_action is not None and current_action != str(expected_action):
            return False
        if self._calibration_sequence_timeout_timer.isActive():
            self._calibration_sequence_timeout_timer.stop()
        self._calibration_sequence_waiting_action = ""
        return True

    def _set_calibration_service_access_state(
        self,
        *,
        busy: bool,
        pending_action: str = "",
        unlocked: bool = False,
        target_sa: int | None = None,
        status: str | None = None,
    ):
        self._service_access_busy = bool(busy)
        self._service_access_pending_action = str(pending_action or "")
        self._service_security_unlocked = bool(unlocked)
        self._service_access_target_sa = None if target_sa is None else (int(target_sa) & 0xFF)
        if status is not None:
            self._service_access_status = str(status)
        self.serviceAccessChanged.emit()

    def _fail_calibration_activation(self, message: str):
        self._reset_calibration_sequence_state()
        self._set_calibration_service_access_state(
            busy=False,
            pending_action="",
            unlocked=False,
            target_sa=None,
            status=message,
        )
        self._calibration_waiting_session = False
        self._calibration_session_ready = False
        self._stop_calibration_poll_timer()
        self._calibration_write_verify_pending = {}
        self.calibrationVerificationChanged.emit()
        if self._calibration_active:
            self._calibration_active = False
            self.calibrationStateChanged.emit()
        self._append_log(message, RowColor.red)
        self._recompute_calibration_wizard_state()

    def _finish_calibration_deactivation(self, message: str):
        self._reset_calibration_sequence_state()
        self._set_calibration_service_access_state(
            busy=False,
            pending_action="",
            unlocked=False,
            target_sa=None,
            status=message,
        )
        self._calibration_waiting_session = False
        self._calibration_session_ready = False
        self._calibration_write_verify_pending = {}
        self._calibration_restore_active = False
        self._calibration_restore_current_did = None
        self.calibrationVerificationChanged.emit()
        self._recompute_calibration_wizard_state()

    def _send_calibration_security_seed_request(self):
        target_sa = self._resolve_calibration_target_sa()
        self._set_calibration_service_access_state(
            busy=True,
            pending_action="calibration_security_seed",
            unlocked=False,
            target_sa=target_sa,
            status=f"Калибровка: запрос seed 0x27 для SA 0x{target_sa:02X}...",
        )
        self._append_log(
            f"Калибровка: автоматический запрос Security Access seed для узла 0x{target_sa:02X}.",
            RowColor.blue,
        )
        self._service_security_access_service.request_seed(self._build_calibration_tx_identifier())
        self._start_calibration_sequence_wait("security_seed")

    def _send_calibration_security_key_request(self):
        target_sa = self._resolve_calibration_target_sa()
        self._set_calibration_service_access_state(
            busy=True,
            pending_action="calibration_security_key",
            unlocked=False,
            target_sa=target_sa,
            status=f"Калибровка: отправка key 0x27 для SA 0x{target_sa:02X}...",
        )
        self._append_log(
            f"Калибровка: отправка Security Access key для узла 0x{target_sa:02X}.",
            RowColor.blue,
        )
        self._service_security_access_service.request_check_key(self._build_calibration_tx_identifier())
        self._start_calibration_sequence_wait("security_key")

    def _send_calibration_initial_read(self, did: int):
        self._configure_calibration_uds_services()
        target_var = UdsData.empty_fuel_tank if int(did) == int(UdsData.empty_fuel_tank.pid) else UdsData.full_fuel_tank
        label = "0%" if int(did) == int(UdsData.empty_fuel_tank.pid) else "100%"
        if not self._calibration_read_service.read_data_by_identifier(self._build_calibration_tx_identifier(), target_var):
            self._fail_calibration_activation(f"Калибровка: не удалось отправить чтение уровня {label}.")
            return
        self._append_log(f"Калибровка: автоматическое чтение сохраненного уровня {label}.", RowColor.blue)
        wait_action = "read_level_0" if int(did) == int(UdsData.empty_fuel_tank.pid) else "read_level_100"
        self._start_calibration_sequence_wait(wait_action)

    def _on_calibration_sequence_delay_timeout(self):
        action = str(self._calibration_sequence_next_action or "")
        self._calibration_sequence_next_action = ""
        if not action:
            return

        if action == "request_security_seed":
            self._send_calibration_security_seed_request()
            return

        if action == "send_security_key":
            self._send_calibration_security_key_request()
            return

        if action == "read_level_0":
            self._send_calibration_initial_read(int(UdsData.empty_fuel_tank.pid))
            return

        if action == "read_level_100":
            self._send_calibration_initial_read(int(UdsData.full_fuel_tank.pid))

    def _on_calibration_sequence_timeout(self):
        action = str(self._calibration_sequence_waiting_action or "")
        if action == "activate_session":
            self._fail_calibration_activation("Калибровка: таймаут ожидания ответа на Extended Session 0x10.")
            return
        if action == "security_seed":
            self._fail_calibration_activation("Калибровка: таймаут ожидания seed на Security Access 0x27.")
            return
        if action == "security_key":
            self._fail_calibration_activation("Калибровка: таймаут ожидания подтверждения key на Security Access 0x27.")
            return
        if action == "read_level_0":
            self._fail_calibration_activation("Калибровка: таймаут чтения сохраненного уровня 0%.")
            return
        if action == "read_level_100":
            self._fail_calibration_activation("Калибровка: таймаут чтения сохраненного уровня 100%.")
            return
        if action == "deactivate_session":
            self._finish_calibration_deactivation("Калибровка: таймаут возврата в default-сессию, локальное состояние сброшено.")

    def _add_calibration_recent_sample(self, value: int):
        now_monotonic = time.monotonic()
        self._calibration_recent_samples.append((now_monotonic, int(value)))
        min_ts = now_monotonic - float(self._calibration_recent_window_sec)
        self._calibration_recent_samples = [
            (sample_ts, sample_value)
            for (sample_ts, sample_value) in self._calibration_recent_samples
            if float(sample_ts) >= min_ts
        ]
        if len(self._calibration_recent_samples) > 100:
            self._calibration_recent_samples = self._calibration_recent_samples[-100:]
        # Автообновление стабильного значения на каждом новом семпле.
        self._recompute_calibration_stable_capture()

    def _recompute_calibration_stable_capture(self) -> tuple[int | None, int]:
        now_monotonic = time.monotonic()
        valid_samples = [
            int(sample_value)
            for (sample_ts, sample_value) in self._calibration_recent_samples
            if (now_monotonic - float(sample_ts)) <= float(self._calibration_recent_window_sec)
        ]

        if len(valid_samples) < 2:
            if self._calibration_captured_available:
                self._calibration_captured_available = False
                self.calibrationValuesChanged.emit()
            return None, len(valid_samples)

        avg_value = sum(valid_samples) / float(len(valid_samples))
        captured = int(round(avg_value))
        changed = (not self._calibration_captured_available) or (self._calibration_captured_level != captured)
        self._calibration_captured_level = captured
        self._calibration_captured_available = True
        if changed:
            self.calibrationValuesChanged.emit()
        return captured, len(valid_samples)

    def _handle_calibration_frame(self, identifier: int, payload: list[int]):
        if len(payload) < 2:
            return

        if not self._is_calibration_response_identifier(identifier):
            return

        if payload[1] == 0x7F and len(payload) >= 4:
            original_sid = int(payload[2]) & 0xFF
            nrc = int(payload[3]) & 0xFF
            nrc_text = self._uds_nrc_description(nrc)

            if self._calibration_waiting_session and original_sid == 0x10:
                current_action = str(self._calibration_sequence_waiting_action or "")
                if current_action == "deactivate_session":
                    self._append_log(
                        f"Калибровка: ошибка возврата в default-сессию, NRC 0x{nrc:02X} ({nrc_text}).",
                        RowColor.red,
                    )
                    self._finish_calibration_deactivation(
                        f"Калибровка: default-сессия не подтверждена, NRC 0x{nrc:02X} ({nrc_text})."
                    )
                    return

                self._fail_calibration_activation(
                    f"Калибровка: ошибка смены сессии, NRC 0x{nrc:02X} ({nrc_text})."
                )
                return
                self._calibration_waiting_session = False
                self._stop_calibration_poll_timer()
                self._calibration_session_ready = False
                if current_action == "deactivate_session":
                    self._append_log("Калибровка: возврат в default-сессию выполнен.", RowColor.green)
                    self._finish_calibration_deactivation("Калибровка завершена. Security Access закрыт, активна default-сессия.")
                    return

                self._append_log("Калибровка: расширенная сессия активирована.", RowColor.green)
                self._schedule_calibration_sequence_action("request_security_seed")
                self._recompute_calibration_wizard_state()
                return
                self._calibration_write_verify_pending = {}
                self.calibrationVerificationChanged.emit()
                if self._calibration_active:
                    self._calibration_active = False
                    self.calibrationStateChanged.emit()
                self._append_log(
                    f"Калибровка: ошибка смены сессии, NRC 0x{nrc:02X} ({nrc_text}).",
                    RowColor.red,
                )
                self._recompute_calibration_wizard_state()
                return

            if original_sid == 0x27:
                target_sa = self._resolve_calibration_target_sa()
                self._set_calibration_service_access_state(
                    busy=False,
                    pending_action="",
                    unlocked=False,
                    target_sa=target_sa,
                    status=f"Калибровка: отказ Security Access, NRC 0x{nrc:02X} ({nrc_text}).",
                )
                self._fail_calibration_activation(
                    f"Калибровка: Security Access отклонён, NRC 0x{nrc:02X} ({nrc_text})."
                )
                return

            if original_sid == 0x2E:
                did = self._pending_calibration_write_did()
                did_label = "параметра"
                extra_hint = ""
                expected_value = None

                if did is not None:
                    expected_value = self._calibration_write_verify_pending.get(int(did))
                    did_label = self._calibration_did_label(did)
                    self._calibration_write_verify_pending.pop(int(did), None)
                    if int(did) == int(UdsData.empty_fuel_tank.pid):
                        self._calibration_level0_written = False
                        self._calibration_verify0_ok = False
                    elif int(did) == int(UdsData.full_fuel_tank.pid):
                        self._calibration_level100_written = False
                        self._calibration_verify100_ok = False
                    self.calibrationVerificationChanged.emit()

                if self._calibration_restore_active:
                    self._calibration_restore_active = False
                    self._calibration_restore_current_did = None

                if nrc == 0x33:
                    target_sa = self._resolve_calibration_target_sa()
                    if self._service_access_target_sa is None:
                        extra_hint = f" Откройте Security Access 0x27 для узла 0x{target_sa:02X}."
                    else:
                        access_target_sa = int(self._service_access_target_sa) & 0xFF
                        if access_target_sa != target_sa:
                            extra_hint = (
                                f" Сейчас 0x27 открыт для узла 0x{access_target_sa:02X}, "
                                f"а запись идёт в узел 0x{target_sa:02X}."
                            )
                        else:
                            extra_hint = f" Повторно выполните Security Access 0x27 для узла 0x{target_sa:02X}."
                elif nrc == 0x22 and did is not None:
                    extra_hint = (
                        " Проверьте условия записи на стороне МК: "
                        "активная сессия, Security Access, состояние приложения/загрузчика и внутренние блокировки DID."
                    )

                self._append_log(
                    f"Калибровка: запись {did_label} отклонена, NRC 0x{nrc:02X} ({nrc_text}).{extra_hint}",
                    RowColor.red,
                )
                self._recompute_calibration_wizard_state()
                return

            if original_sid == 0x22:
                if self._calibration_sequence_waiting_action in ("read_level_0", "read_level_100"):
                    self._fail_calibration_activation(
                        f"Калибровка: чтение исходных уровней отклонено, NRC 0x{nrc:02X} ({nrc_text})."
                    )
                    return
                self._append_log(
                    f"Калибровка: чтение параметра отклонено, NRC 0x{nrc:02X} ({nrc_text}).",
                    RowColor.red,
                )
                return

        if payload[1] == 0x67 and len(payload) >= 3:
            sub_function = int(payload[2]) & 0xFF
            target_sa = self._resolve_calibration_target_sa()

            if sub_function == 0x01 and self._calibration_sequence_waiting_action == "security_seed":
                if self._service_security_access_service.verify_answer_request_seed(payload):
                    self._finish_calibration_sequence_wait("security_seed")
                    self._set_calibration_service_access_state(
                        busy=True,
                        pending_action="calibration_security_key",
                        unlocked=False,
                        target_sa=target_sa,
                        status=f"Калибровка: seed получен, подготовка key для SA 0x{target_sa:02X}...",
                    )
                    self._append_log(
                        (
                            f"Калибровка: seed=0x{int(self._service_security_access_service.seed) & 0xFFFF:04X}, "
                            f"key=0x{int(self._service_security_access_service.key) & 0xFFFF:04X}, "
                            f"узел 0x{target_sa:02X}."
                        ),
                        RowColor.blue,
                    )
                    self._schedule_calibration_sequence_action("send_security_key")
                    return

            if sub_function == 0x02 and self._calibration_sequence_waiting_action == "security_key":
                if self._service_security_access_service.verify_answer_request_check_key(payload):
                    self._finish_calibration_sequence_wait("security_key")
                    self._set_calibration_service_access_state(
                        busy=False,
                        pending_action="",
                        unlocked=True,
                        target_sa=target_sa,
                        status=f"Калибровка: Security Access открыт для SA 0x{target_sa:02X}.",
                    )
                    self._append_log(
                        f"Калибровка: Security Access подтверждён для узла 0x{target_sa:02X}.",
                        RowColor.green,
                    )
                    self._schedule_calibration_sequence_action("read_level_0")
                    return

        if self._calibration_waiting_session:
            if self._calibration_session_service.verify_answer(payload):
                current_action = str(self._calibration_sequence_waiting_action or "")
                self._finish_calibration_sequence_wait(current_action if current_action else None)
                self._calibration_waiting_session = False
                self._calibration_session_ready = False
                if current_action == "deactivate_session":
                    self._append_log("Калибровка: возврат в default-сессию выполнен.", RowColor.green)
                    self._finish_calibration_deactivation("Калибровка завершена. Security Access закрыт, активна default-сессия.")
                    return

                self._append_log("Калибровка: расширенная сессия активирована.", RowColor.green)
                self._schedule_calibration_sequence_action("request_security_seed")
                self._recompute_calibration_wizard_state()
                return
                if self._calibration_active:
                    self._append_log("Калибровка: расширенная сессия активирована.", RowColor.green)
                    self._start_calibration_poll_timer()
                    self.readCalibrationCurrentLevel()
                    self.readCalibrationLevel0()
                    self.readCalibrationLevel100()
                else:
                    self._append_log("Калибровка: переход в default-сессию выполнен.", RowColor.green)
                self._recompute_calibration_wizard_state()
                return

            if payload[1] == 0x7F and len(payload) >= 4 and payload[2] == 0x10:
                self._calibration_waiting_session = False
                self._stop_calibration_poll_timer()
                self._calibration_session_ready = False
                self._calibration_write_verify_pending = {}
                self.calibrationVerificationChanged.emit()
                if self._calibration_active:
                    self._calibration_active = False
                    self.calibrationStateChanged.emit()
                self._append_log(f"Калибровка: ошибка смены сессии (NRC=0x{payload[3]:02X}).", RowColor.red)
                self._recompute_calibration_wizard_state()
                return

        if self._calibration_read_service.verify_answer_read_data(payload):
            did = int(self._calibration_read_service.parse_pid_field(payload))
            value = int(self._calibration_read_service.parse_data_field(payload))
            changed = False

            if did == int(UdsData.curr_fuel_tank.pid):
                if self._calibration_current_level != value:
                    self._calibration_current_level = value
                    changed = True
                self._add_calibration_recent_sample(value)
            elif did == int(UdsData.empty_fuel_tank.pid):
                self._calibration_level_0 = value
                self._calibration_level_0_known = True
                changed = True
                self._append_log(f"Калибровка: считан уровень 0% = {value}.", RowColor.green)
            elif did == int(UdsData.full_fuel_tank.pid):
                self._calibration_level_100 = value
                self._calibration_level_100_known = True
                changed = True
                self._append_log(f"Калибровка: считан уровень 100% = {value}.", RowColor.green)

            if self._calibration_sequence_waiting_action == "read_level_0" and did == int(UdsData.empty_fuel_tank.pid):
                self._finish_calibration_sequence_wait("read_level_0")
                self._schedule_calibration_sequence_action("read_level_100")
            elif self._calibration_sequence_waiting_action == "read_level_100" and did == int(UdsData.full_fuel_tank.pid):
                self._finish_calibration_sequence_wait("read_level_100")
                self._calibration_session_ready = True
                self._start_calibration_poll_timer()
                self.readCalibrationCurrentLevel()
                self._append_log(
                    "Калибровка: extended-сессия и Security Access активны, исходные уровни считаны.",
                    RowColor.green,
                )
                self._recompute_calibration_wizard_state()

            if self._calibration_backup_pending and did in (int(UdsData.empty_fuel_tank.pid), int(UdsData.full_fuel_tank.pid)):
                self._calibration_backup_values_pending[did] = value
                if (
                    int(UdsData.empty_fuel_tank.pid) in self._calibration_backup_values_pending
                    and int(UdsData.full_fuel_tank.pid) in self._calibration_backup_values_pending
                ):
                    self._calibration_backup_pending = False
                    self._calibration_backup_level_0 = int(self._calibration_backup_values_pending[int(UdsData.empty_fuel_tank.pid)])
                    self._calibration_backup_level_100 = int(self._calibration_backup_values_pending[int(UdsData.full_fuel_tank.pid)])
                    self._calibration_backup_values_pending = {}
                    self._calibration_backup_available = True
                    self.calibrationBackupChanged.emit()
                    self._append_log("Калибровка: резервная копия параметров сохранена.", RowColor.green)

            expected_value = self._calibration_write_verify_pending.get(did)
            if expected_value is not None:
                diff = abs(int(value) - int(expected_value))
                if diff <= int(self._calibration_verify_tolerance):
                    if did == int(UdsData.empty_fuel_tank.pid):
                        self._calibration_verify0_ok = True
                    elif did == int(UdsData.full_fuel_tank.pid):
                        self._calibration_verify100_ok = True
                    self._append_log(
                        f"Калибровка: автопроверка DID 0x{did:04X} успешна (ожидалось {expected_value}, факт {value}).",
                        RowColor.green,
                    )
                else:
                    if did == int(UdsData.empty_fuel_tank.pid):
                        self._calibration_verify0_ok = False
                    elif did == int(UdsData.full_fuel_tank.pid):
                        self._calibration_verify100_ok = False
                    self._append_log(
                        f"Калибровка: автопроверка DID 0x{did:04X} НЕ пройдена (ожидалось {expected_value}, факт {value}).",
                        RowColor.red,
                    )
                self._calibration_write_verify_pending.pop(did, None)
                self.calibrationVerificationChanged.emit()
                self._recompute_calibration_wizard_state()

            if changed:
                self.calibrationValuesChanged.emit()
            return

        if self._calibration_write_service.verify_answer_write_data(payload):
            did = int(self._calibration_write_service.parse_pid_field(payload))
            if did == int(UdsData.empty_fuel_tank.pid):
                self._append_log("Калибровка: уровень 0% успешно сохранен.", RowColor.green)
                self.readCalibrationLevel0()
            elif did == int(UdsData.full_fuel_tank.pid):
                self._append_log("Калибровка: уровень 100% успешно сохранен.", RowColor.green)
                self.readCalibrationLevel100()

            if self._calibration_restore_active and self._calibration_restore_current_did == did:
                self._send_next_calibration_restore_write()

    def _on_calibration_poll_tick(self):
        if not self._calibration_active:
            self._stop_calibration_poll_timer()
            return
        if not self._can.is_connect or not self._can.is_trace:
            return
        if self._source_address_busy:
            return
        if self._programming_active:
            return
        self.readCalibrationCurrentLevel()

    def _start_calibration_poll_timer(self):
        if self._calibration_poll_timer.interval() != self._calibration_poll_interval_ms:
            self._calibration_poll_timer.setInterval(self._calibration_poll_interval_ms)
        if not self._calibration_poll_timer.isActive():
            self._calibration_poll_timer.start()

    def _stop_calibration_poll_timer(self):
        if self._calibration_poll_timer.isActive():
            self._calibration_poll_timer.stop()

    def _send_next_calibration_restore_write(self):
        if not self._calibration_restore_active:
            return

        if len(self._calibration_restore_queue) == 0:
            self._calibration_restore_active = False
            self._calibration_restore_current_did = None
            self._append_log("Калибровка: восстановление из резервной копии завершено.", RowColor.green)
            return

        did, value = self._calibration_restore_queue.pop(0)
        self._calibration_restore_current_did = int(did)
        target_var = UdsData.empty_fuel_tank if int(did) == int(UdsData.empty_fuel_tank.pid) else UdsData.full_fuel_tank
        self._configure_calibration_uds_services()
        if self._calibration_write_service.write_data(
            target_var,
            int(value),
            tx_identifier=self._build_calibration_tx_identifier(),
        ):
            self._calibration_write_verify_pending[int(did)] = int(value)
            if int(did) == int(UdsData.empty_fuel_tank.pid):
                self._calibration_level0_written = True
                self._calibration_verify0_ok = False
            else:
                self._calibration_level100_written = True
                self._calibration_verify100_ok = False
            self.calibrationVerificationChanged.emit()
            self._recompute_calibration_wizard_state()
            self._append_log(f"Калибровка: восстановление DID 0x{int(did):04X} = {int(value)}.", RowColor.blue)
        else:
            self._calibration_restore_active = False
            self._calibration_restore_current_did = None
            self._append_log(f"Калибровка: ошибка восстановления DID 0x{int(did):04X}.", RowColor.red)

    def _reset_calibration_wizard_state(self):
        self._calibration_session_ready = False
        self._calibration_level0_written = False
        self._calibration_level100_written = False
        self._calibration_verify0_ok = False
        self._calibration_verify100_ok = False
        self.calibrationVerificationChanged.emit()
        self._recompute_calibration_wizard_state()

    def _recompute_calibration_wizard_state(self):
        if not self._calibration_active:
            stage = 0
            hint = "Запустите калибровку, чтобы начать пошаговый процесс."
        elif self._calibration_verify0_ok and self._calibration_verify100_ok:
            stage = 4
            hint = "Проверка значений 0% и 100% успешно завершена."
        elif self._calibration_level100_written:
            stage = 3
            hint = "Эталон 100% записан. Дождитесь автопроверки."
        elif self._calibration_level0_written:
            stage = 2
            hint = "Эталон 0% записан. Запишите 100%."
        elif self._calibration_session_ready:
            stage = 1
            hint = "Сессия открыта. Сохраните эталон 0%, затем 100%."
        else:
            stage = 0
            hint = "Ожидание подтверждения сессии UDS."

        changed = False
        if self._calibration_wizard_stage != stage:
            self._calibration_wizard_stage = stage
            changed = True
        if self._calibration_wizard_hint != hint:
            self._calibration_wizard_hint = hint
            changed = True

        if changed:
            self.calibrationWizardChanged.emit()

    def _refresh_calibration_node_options(self):
        previous_values = list(self._calibration_node_values)
        previous_options = list(self._calibration_node_options)
        previous_selected = int(self._selected_calibration_node_index)
        selected_sa = self._calibration_target_node_sa

        new_values: list[int | None] = [None]
        new_options: list[str] = ["Авто (по текущим UDS ID)"]

        for device_sa in self._observed_candidate_values:
            sa = int(device_sa) & 0xFF
            new_values.append(sa)
            # Статичные подписи: без live-счетчиков, чтобы выбор не "прыгал" при обновлении трафика.
            new_options.append(f"Узел 0x{sa:02X}")

        new_selected = 0
        if selected_sa is not None:
            for index, value in enumerate(new_values):
                if value is not None and int(value) == int(selected_sa):
                    new_selected = index
                    break
            else:
                self._calibration_target_node_sa = None
        elif 0 <= previous_selected < len(new_values):
            new_selected = previous_selected

        self._calibration_node_values = new_values
        self._calibration_node_options = new_options
        self._selected_calibration_node_index = new_selected

        if (
            previous_values != self._calibration_node_values
            or previous_options != self._calibration_node_options
            or previous_selected != self._selected_calibration_node_index
        ):
            self.calibrationNodeSelectionChanged.emit()

    @staticmethod
    def _resolve_calibration_write_value(text, fallback_value: int) -> int:
        raw = str(text).strip()
        if not raw:
            return int(fallback_value)

        base = 16 if raw.lower().startswith("0x") else 10
        try:
            value = int(raw, base)
        except ValueError as exc:
            raise ValueError("Некорректное значение калибровки. Используйте десятичный или hex-формат.") from exc

        if value < 0 or value > 0xFFFF:
            raise ValueError("Значение калибровки вне диапазона 0..65535.")
        return int(value)
