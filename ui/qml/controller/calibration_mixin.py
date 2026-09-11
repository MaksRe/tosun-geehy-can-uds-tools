from __future__ import annotations

import csv
import math
from pathlib import Path
import re
import time
try:
    from openpyxl import load_workbook
except Exception:
    load_workbook = None

from j1939.j1939_can_identifier import J1939CanIdentifier
from colors import RowColor
from uds.data_identifiers import UdsData
from uds.uds_identifiers import UdsIdentifiers

from .contract import AppControllerContract

class AppControllerCalibrationMixin(AppControllerContract):
    _INT16_MIN = -32768
    _INT16_MAX = 32767

    # Подгонка нуля читается и пишется по одному номеру параметра, поэтому
    # таблица полей для неё не нужна: обращение идёт напрямую к UdsData.

    @staticmethod
    def _parse_calibration_response_identifier(identifier: int) -> tuple[int, int, int] | None:
        """Цель функции в безопасном разборе CAN-ID ответа, затем она возвращает pgn/dst/src для UDS-фильтрации."""
        try:
            parsed = J1939CanIdentifier(int(identifier))
        except Exception:
            return None
        parsed_pgn = int(parsed.pgn) & 0x3FFFF
        parsed_dst = int(parsed.dst) & 0xFF
        parsed_src = int(parsed.src) & 0xFF
        return parsed_pgn, parsed_dst, parsed_src

    def _try_bind_calibration_runtime_target_from_session_response(self, identifier: int, payload: list[int]):
        """Цель функции в привязке целевого SA в авто-режиме, затем она фиксирует узел по реальному ответу на 0x10."""
        if self._calibration_target_node_sa is not None:
            return
        if not self._calibration_waiting_session:
            return
        if str(self._calibration_sequence_waiting_action or "") != "activate_session":
            return
        if len(payload) < 2:
            return

        sid = int(payload[1]) & 0xFF
        is_session_answer = sid == 0x50
        if not is_session_answer:
            is_session_answer = sid == 0x7F and len(payload) >= 4 and (int(payload[2]) & 0xFF) == 0x10
        if not is_session_answer:
            return

        parsed = self._parse_calibration_response_identifier(identifier)
        if parsed is None:
            return
        parsed_pgn, parsed_dst, parsed_src = parsed
        expected_pgn = int(UdsIdentifiers.rx.pgn) & 0x3FFFF
        expected_dst = int(UdsIdentifiers.rx.dst) & 0xFF
        if parsed_pgn != expected_pgn or parsed_dst != expected_dst:
            return

        if self._calibration_runtime_target_sa == parsed_src:
            return
        self._calibration_runtime_target_sa = int(parsed_src) & 0xFF

        configured_auto_sa = int(UdsIdentifiers.rx.src) & 0xFF
        if int(parsed_src) != configured_auto_sa:
            self._append_log(
                (
                    f"Калибровка: авто-режим подтвердил ответ 0x10 от узла 0x{int(parsed_src) & 0xFF:02X}. "
                    "Для текущей сессии используется этот узел."
                ),
                RowColor.blue,
            )

    def _is_calibration_response_identifier(self, identifier: int) -> bool:
        parsed = self._parse_calibration_response_identifier(identifier)
        if parsed is None:
            return False
        parsed_pgn, parsed_dst, parsed_src = parsed

        expected_pgn = int(UdsIdentifiers.rx.pgn) & 0x3FFFF
        if parsed_pgn != expected_pgn:
            return False

        expected_dst = int(UdsIdentifiers.rx.dst) & 0xFF
        if parsed_dst != expected_dst:
            return False

        expected_src = int(self._resolve_calibration_target_sa()) & 0xFF
        return parsed_src == expected_src

    def _build_calibration_tx_identifier(self) -> int:
        try:
            tx = J1939CanIdentifier(int(UdsIdentifiers.tx.identifier))
            tx.dst = int(self._resolve_calibration_target_sa()) & 0xFF
            return int(tx.identifier)
        except Exception:
            return int(UdsIdentifiers.tx.identifier)

    def _set_calibration_session_ready(self, ready: bool):
        """Меняет признак готовности сессии и сообщает об этом окнам.

        Раньше признак менялся присваиванием, и окна о нём не узнавали. Из-за
        этого в окне калибровки вида топлива предупреждение «запись закрыта»
        оставалось висеть после запуска калибровки, а кнопки сохранения так и
        не становились доступными, хотя обмен уже шёл.
        """
        value = bool(ready)
        if bool(self._calibration_session_ready) == value:
            return

        self._calibration_session_ready = value
        self.calibrationStateChanged.emit()

    def _resolve_calibration_target_sa(self) -> int:
        if self._calibration_target_node_sa is not None:
            return int(self._calibration_target_node_sa) & 0xFF
        if self._calibration_runtime_target_sa is not None:
            return int(self._calibration_runtime_target_sa) & 0xFF
        if 0 <= int(self._observed_candidate_index) < len(self._observed_candidate_values):
            return int(self._observed_candidate_values[int(self._observed_candidate_index)]) & 0xFF
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
        if int(did) == int(UdsData.fuel_zero_trim_count.pid):
            return "подгонки нуля"
        return f"DID 0x{int(did) & 0xFFFF:04X}"

    def _pending_calibration_write_did(self) -> int | None:
        if self._calibration_restore_current_did is not None:
            return int(self._calibration_restore_current_did)

        check_dids = [
            int(UdsData.empty_fuel_tank.pid),
            int(UdsData.full_fuel_tank.pid),
            int(UdsData.fuel_zero_trim_count.pid),
        ]
        for did in check_dids:
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
        self._calibration_runtime_target_sa = None
        self._set_calibration_service_access_state(
            busy=False,
            pending_action="",
            unlocked=False,
            target_sa=None,
            status=message,
        )
        self._calibration_waiting_session = False
        self._set_calibration_session_ready(False)
        self._stop_calibration_poll_timer()
        self._calibration_write_verify_pending = {}
        self.calibrationVerificationChanged.emit()
        if self._calibration_active:
            self._calibration_active = False
            self.calibrationStateChanged.emit()
        self._append_log(message, RowColor.red)
        self._recompute_calibration_wizard_state()

    def _invalidate_calibration_session_after_nrc(self, message: str):
        """Цель функции в сбросе локального состояния калибровки после потери сессии на МК, затем она переводит UI в безопасный режим до повторного запуска."""
        self._reset_calibration_sequence_state()
        self._reset_calibration_zero_trim_air_zero_adjust_state()
        self._reset_calibration_zero_trim_verify_state()
        self._calibration_runtime_target_sa = None
        self._calibration_waiting_session = False
        self._set_calibration_session_ready(False)
        self._stop_calibration_poll_timer()
        self._calibration_write_verify_pending = {}
        self.calibrationVerificationChanged.emit()
        self._set_calibration_service_access_state(
            busy=False,
            pending_action="",
            unlocked=False,
            target_sa=None,
            status=message,
        )
        if self._calibration_active:
            self._calibration_active = False
            self.calibrationStateChanged.emit()
        self._append_log(message, RowColor.yellow)
        self._recompute_calibration_wizard_state()

    def _finish_calibration_deactivation(self, message: str):
        self._reset_calibration_sequence_state()
        self._calibration_runtime_target_sa = None
        self._set_calibration_service_access_state(
            busy=False,
            pending_action="",
            unlocked=False,
            target_sa=None,
            status=message,
        )
        self._calibration_waiting_session = False
        self._set_calibration_session_ready(False)
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

    @staticmethod
    def _decode_signed_value(raw_value: int, bits: int) -> int:
        """Цель функции в корректной интерпретации знаковых DID, затем она выполняет sign-extension по числу бит."""
        width = max(1, int(bits))
        mask = (1 << width) - 1
        sign_bit = 1 << (width - 1)
        value = int(raw_value) & mask
        if value & sign_bit:
            return value - (1 << width)
        return value

    @staticmethod
    def _c_trunc_div(numerator: int, denominator: int) -> int:
        """Цель функции в повторении поведения C-деления, затем она делит с усечением к нулю."""
        if int(denominator) == 0:
            raise ZeroDivisionError("Деление на ноль недопустимо.")

        quotient = abs(int(numerator)) // abs(int(denominator))
        if (int(numerator) < 0) ^ (int(denominator) < 0):
            return -quotient
        return quotient

    def _set_calibration_zero_trim_operation_status(
        self,
        text: str,
        *,
        busy: bool,
        progress_percent: int | None = None,
        determinate: bool | None = None,
    ):
        """Цель функции в обновлении статуса подгонки нуля, затем она синхронизирует текст, занятость и прогресс для окна."""
        normalized_text = str(text or "").strip()
        if not normalized_text:
            normalized_text = "Ожидание операций."
        normalized_busy = bool(busy)
        normalized_determinate = (
            bool(progress_percent is not None)
            if determinate is None
            else bool(determinate)
        )
        normalized_progress_percent = 0
        if normalized_determinate:
            if progress_percent is None:
                normalized_progress_percent = 100 if not normalized_busy else 0
            else:
                normalized_progress_percent = max(0, min(100, int(progress_percent)))

        changed = (
            str(self._calibration_zero_trim_operation_text) != normalized_text
            or bool(self._calibration_zero_trim_operation_busy) != normalized_busy
            or int(self._calibration_zero_trim_operation_progress_percent) != int(normalized_progress_percent)
            or bool(self._calibration_zero_trim_operation_progress_determinate) != bool(normalized_determinate)
        )
        self._calibration_zero_trim_operation_text = normalized_text
        self._calibration_zero_trim_operation_busy = normalized_busy
        self._calibration_zero_trim_operation_progress_percent = int(normalized_progress_percent)
        self._calibration_zero_trim_operation_progress_determinate = bool(normalized_determinate)
        if changed:
            self.calibrationZeroTrimChanged.emit()

    def _set_calibration_zero_trim_last_report(
        self,
        *,
        old_zero_trim: int | None,
        new_zero_trim: int | None,
        residual_x10: int | None,
        status_text: str,
        write_csv: bool = False,
    ):
        """Цель функции в формировании краткой сводки подгонки zero trim, затем она сохраняет человеко-понятный отчет для оператора."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        node_sa = int(self._resolve_calibration_target_sa()) & 0xFF
        temperature_x10 = self._calibration_last_temperature_x10
        if temperature_x10 is None:
            temperature_text = "н/д"
        else:
            temperature_text = f"{float(int(temperature_x10)) / 10.0:+.1f}°C"

        old_text = "н/д" if old_zero_trim is None else str(int(old_zero_trim))
        new_text = "н/д" if new_zero_trim is None else str(int(new_zero_trim))
        residual_text = "н/д" if residual_x10 is None else f"{float(int(residual_x10)) / 10.0:+.1f}%"
        status_value = str(status_text or "").strip()
        if not status_value:
            status_value = "выполнено"

        self._calibration_zero_trim_last_report = (
            f"{timestamp} | SA 0x{node_sa:02X} | T={temperature_text} | "
            f"trim {old_text}->{new_text} | остаток {residual_text} | {status_value}."
        )
        if bool(write_csv):
            try:
                csv_path = self._append_calibration_zero_trim_report_csv_row(
                    timestamp_text=timestamp,
                    node_sa=node_sa,
                    temperature_text=temperature_text,
                    old_zero_trim_text=old_text,
                    new_zero_trim_text=new_text,
                    residual_text=residual_text,
                    status_text=status_value,
                )
                if str(self._calibration_zero_trim_csv_log_path) != str(csv_path):
                    self._calibration_zero_trim_csv_log_path = str(csv_path)
                    self._append_log(
                        f"Калибровка: CSV-лог операций zero trim записывается в {csv_path}.",
                        RowColor.blue,
                    )
            except Exception as exc:
                self._append_log(
                    f"Калибровка: не удалось записать CSV-лог zero trim: {str(exc)}",
                    RowColor.yellow,
                )

    def _resolve_calibration_zero_trim_report_directory(self) -> Path:
        """Цель функции в выборе каталога логов подгонки zero trim, затем она возвращает рабочий путь для CSV-отчета операций."""
        session_dir = self._collector_session_dir
        if session_dir is not None:
            try:
                resolved_session_dir = Path(session_dir).expanduser().resolve()
                resolved_session_dir.mkdir(parents=True, exist_ok=True)
                return resolved_session_dir
            except Exception:
                pass

        try:
            output_dir = Path(str(self._collector_output_directory)).expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            return output_dir
        except Exception:
            fallback_dir = Path(self._project_root_directory) / "logs"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            return fallback_dir

    def _append_calibration_zero_trim_report_csv_row(
        self,
        *,
        timestamp_text: str,
        node_sa: int,
        temperature_text: str,
        old_zero_trim_text: str,
        new_zero_trim_text: str,
        residual_text: str,
        status_text: str,
    ) -> str:
        """Цель функции в накоплении CSV-истории подгонки zero trim, затем она добавляет строку операции в UTF-8 файл сессии."""
        report_dir = self._resolve_calibration_zero_trim_report_directory()
        csv_path = report_dir / "calibration_zero_trim_session.csv"
        need_header = not csv_path.exists()
        with csv_path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter=";")
            if need_header:
                writer.writerow(
                    (
                        "Время",
                        "Узел",
                        "Температура",
                        "Zero trim старый",
                        "Zero trim новый",
                        "Остаток",
                        "Статус",
                    )
                )
            writer.writerow(
                (
                    str(timestamp_text),
                    f"0x{int(node_sa) & 0xFF:02X}",
                    str(temperature_text),
                    str(old_zero_trim_text),
                    str(new_zero_trim_text),
                    str(residual_text),
                    str(status_text),
                )
            )
        return str(csv_path)

    @classmethod
    def _saturate_int16(cls, value: int) -> int:
        """Цель функции в защите от переполнения DID int16, затем она ограничивает значение диапазоном -32768..32767."""
        return max(cls._INT16_MIN, min(cls._INT16_MAX, int(value)))

    @classmethod
    def _calculate_zero_trim_adjustment(
        cls,
        *,
        span_count: int,
        current_level_x10: int,
        current_zero_trim: int,
    ) -> tuple[int, int, int]:
        """Цель функции в вычислении коррекции 0%-смещения, затем она возвращает delta/target/residual в формате int16 + x10%."""
        span = int(span_count)
        if span <= 0:
            raise ValueError("Некорректный span для расчета zero trim.")

        normalized_level_x10 = max(-1000, min(1000, int(current_level_x10)))
        delta_zero_trim = cls._c_trunc_div((-normalized_level_x10) * span, 1000)
        target_zero_trim = cls._saturate_int16(int(current_zero_trim) + int(delta_zero_trim))
        applied_delta = int(target_zero_trim) - int(current_zero_trim)
        residual_x10 = int(normalized_level_x10) + cls._c_trunc_div(int(applied_delta) * 1000, span)
        return int(delta_zero_trim), int(target_zero_trim), int(residual_x10)

    @staticmethod
    def _classify_zero_trim_verification_result(
        *,
        residual_x10: int,
        tolerance_x10: int,
        repeat_threshold_x10: int,
    ) -> str:
        """Цель функции в единой классификации автопроверки zero trim, затем она возвращает статус success/repeat/mechanics."""
        abs_level_x10 = abs(int(residual_x10))
        normalized_tolerance_x10 = max(0, int(tolerance_x10))
        normalized_repeat_threshold_x10 = max(normalized_tolerance_x10, int(repeat_threshold_x10))
        if abs_level_x10 <= normalized_tolerance_x10:
            return "success"
        if abs_level_x10 <= normalized_repeat_threshold_x10:
            return "repeat"
        return "mechanics"

    def _period_to_level_percent(self, period: int | float) -> float | None:
        """Цель функции в пересчете периода в проценты, затем она применяет текущие границы empty/full из калибровки."""
        empty_period = int(self._calibration_level_0)
        full_period = int(self._calibration_level_100)
        span = full_period - empty_period
        if span <= 0:
            return None
        return ((float(period) - float(empty_period)) * 100.0) / float(span)

    @staticmethod
    def _linear_regression_slope(x_values: list[float], y_values: list[float]) -> float | None:
        """Цель функции в оценке температурного дрейфа, затем она возвращает наклон линейной регрессии dy/dx."""
        if len(x_values) != len(y_values):
            return None
        if len(x_values) < 2:
            return None

        x_mean = sum(float(x) for x in x_values) / float(len(x_values))
        y_mean = sum(float(y) for y in y_values) / float(len(y_values))

        ss_x = sum((float(x) - x_mean) ** 2 for x in x_values)
        if ss_x <= 0.0:
            return None

        cov_xy = sum((float(x) - x_mean) * (float(y) - y_mean) for (x, y) in zip(x_values, y_values))
        return float(cov_xy / ss_x)

    @staticmethod
    def _calc_reduction_percent(before: float | None, after: float | None) -> float | None:
        """Цель функции в расчете эффекта компенсации, затем она возвращает процент снижения модуля дрейфа."""
        if before is None or after is None:
            return None
        if float(before) == 0.0:
            return 0.0
        return (1.0 - abs(float(after)) / abs(float(before))) * 100.0

    @staticmethod
    def _calc_percentile_abs(values: list[float], percentile: float) -> float | None:
        """Цель функции в расчете устойчивой оценки ошибки, затем она возвращает перцентиль абсолютного отклонения."""
        if len(values) <= 0:
            return None
        sorted_abs = sorted(abs(float(value)) for value in values)
        if len(sorted_abs) <= 0:
            return None
        ratio = max(0.0, min(1.0, float(percentile)))
        index = int(round(ratio * float(len(sorted_abs) - 1)))
        index = max(0, min(index, len(sorted_abs) - 1))
        return float(sorted_abs[index])

    @staticmethod
    def _calc_level_error_metrics(level_values: list[float]) -> dict[str, float | tuple[float, float]] | None:
        """Цель функции в человеко-понятной оценке компенсации, затем она считает коридор, максимум и P95 ошибки уровня."""
        if len(level_values) <= 0:
            return None

        min_level = min(float(value) for value in level_values)
        max_level = max(float(value) for value in level_values)
        max_abs = max(abs(float(value)) for value in level_values)
        p95_abs = AppControllerCalibrationMixin._calc_percentile_abs(level_values, 0.95)
        if p95_abs is None:
            return None

        return {
            "range": (float(min_level), float(max_level)),
            "max_abs": float(max_abs),
            "p95_abs": float(p95_abs),
        }

    @staticmethod
    def _find_max_abs_level_error(level_values: list[float]) -> tuple[int | None, float | None]:
        """Цель функции в поиске точки наихудшей ошибки, затем она возвращает индекс и signed-значение уровня."""
        if len(level_values) <= 0:
            return None, None
        max_index = max(range(len(level_values)), key=lambda idx: abs(float(level_values[idx])))
        return int(max_index), float(level_values[max_index])

    @staticmethod
    def _calc_quantile(values: list[float], ratio: float) -> float | None:
        """Цель функции в вычислении квантили набора, затем она возвращает интерполированное значение для заданной доли."""
        if len(values) <= 0:
            return None
        ordered = sorted(float(value) for value in values)
        if len(ordered) == 1:
            return float(ordered[0])

        bounded_ratio = max(0.0, min(1.0, float(ratio)))
        position = bounded_ratio * float(len(ordered) - 1)
        left_index = int(math.floor(position))
        right_index = int(math.ceil(position))
        if left_index == right_index:
            return float(ordered[left_index])

        weight = float(position - float(left_index))
        left_value = float(ordered[left_index])
        right_value = float(ordered[right_index])
        return (left_value * (1.0 - weight)) + (right_value * weight)

    @staticmethod
    def _parse_csv_float(value: object) -> float | None:
        """Цель функции в чтении чисел из CSV, затем она преобразует строку с запятой или точкой в float."""
        raw = str(value or "").strip().replace(" ", "")
        if not raw:
            return None
        normalized = raw.replace(",", ".")
        try:
            return float(normalized)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_csv_int(value: object) -> int | None:
        """Цель функции в разборе целого значения периода, затем она обрабатывает как integer, так и float-представление."""
        parsed_float = AppControllerCalibrationMixin._parse_csv_float(value)
        if parsed_float is None:
            return None
        try:
            return int(round(float(parsed_float)))
        except Exception:
            return None

    @staticmethod
    def _extract_node_sa_from_text(text: object) -> int | None:
        """Цель функции в извлечении адреса узла, затем она ищет SA формата 0xNN в произвольной строке."""
        raw = str(text or "")
        match = re.search(r"0x([0-9a-fA-F]{1,2})", raw)
        if match is None:
            return None
        try:
            return int(match.group(1), 16) & 0xFF
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_empty_full_from_text(text: object) -> tuple[int | None, int | None]:
        """Цель функции в разборе калибровки из метаданных CSV, затем она извлекает empty/full через регулярные выражения."""
        raw = str(text or "")
        empty_match = re.search(r"empty\s*=\s*(-?\d+)", raw, flags=re.IGNORECASE)
        full_match = re.search(r"full\s*=\s*(-?\d+)", raw, flags=re.IGNORECASE)
        empty_value = int(empty_match.group(1)) if empty_match is not None else None
        full_value = int(full_match.group(1)) if full_match is not None else None
        return empty_value, full_value

    @staticmethod
    def _is_csv_header_like(row: list[str]) -> bool:
        """Цель функции в пропуске служебных строк, затем она определяет заголовки/метаданные по ключевым словам."""
        if len(row) == 0:
            return True
        joined = ";".join(str(cell or "").strip() for cell in row).casefold()
        if not joined:
            return True
        markers = ("время", "узел", "калибровк", "формул", "period", "период", "температ", "temp", "топлив", "fuel")
        return any(marker in joined for marker in markers)

    def _request_calibration_runtime_snapshot(self):
        """Цель функции в опросе рабочего периода калибровки, затем она читает DID 0x0014 для отображения текущего значения."""
        if not self._can.is_connect or not self._can.is_trace:
            return
        self._configure_calibration_uds_services()
        tx_identifier = self._build_calibration_tx_identifier()
        self._calibration_read_service.read_data_by_identifier(tx_identifier, UdsData.curr_fuel_tank)

    def _reset_calibration_zero_trim_air_zero_adjust_state(self):
        """Цель функции в сбросе автоподстройки zero trim, затем она очищает временные значения DID 0x0012/0x0013/0x0018/0x002D."""
        if self._calibration_zero_trim_air_zero_adjust_timeout_timer.isActive():
            self._calibration_zero_trim_air_zero_adjust_timeout_timer.stop()
        self._calibration_zero_trim_air_zero_adjust_active = False
        self._calibration_zero_trim_air_zero_adjust_empty_period = None
        self._calibration_zero_trim_air_zero_adjust_full_period = None
        self._calibration_zero_trim_air_zero_adjust_level_x10 = None
        self._calibration_zero_trim_air_zero_adjust_level_samples = []
        self._calibration_zero_trim_air_zero_adjust_current_zero_trim = None

    def _reset_calibration_zero_trim_verify_state(self):
        """Цель функции в безопасном завершении автопроверки zero trim, затем она сбрасывает флаг и таймер ожидания DID 0x0018."""
        if self._calibration_zero_trim_verify_timeout_timer.isActive():
            self._calibration_zero_trim_verify_timeout_timer.stop()
        self._calibration_zero_trim_verify_pending = False
        self._calibration_zero_trim_verify_retries_left = 0

    def _request_next_calibration_zero_trim_air_zero_adjust_did(self) -> bool:
        """Цель функции в пошаговом чтении DID для автоподстройки zero trim, затем она отправляет только следующий необходимый запрос."""
        if not bool(self._calibration_zero_trim_air_zero_adjust_active):
            return False

        next_var = None
        required_samples = max(1, int(self._calibration_zero_trim_air_zero_adjust_required_samples))
        level_samples = list(self._calibration_zero_trim_air_zero_adjust_level_samples)
        if self._calibration_zero_trim_air_zero_adjust_empty_period is None:
            next_var = UdsData.empty_fuel_tank
        elif self._calibration_zero_trim_air_zero_adjust_full_period is None:
            next_var = UdsData.full_fuel_tank
        elif len(level_samples) < required_samples:
            next_var = UdsData.raw_fuel_level
        elif self._calibration_zero_trim_air_zero_adjust_current_zero_trim is None:
            next_var = UdsData.fuel_zero_trim_count
        else:
            return False

        self._configure_calibration_uds_services()
        sent = bool(
            self._calibration_read_service.read_data_by_identifier(
                self._build_calibration_tx_identifier(),
                next_var,
            )
        )
        if not sent:
            return False

        self._calibration_zero_trim_air_zero_adjust_timeout_timer.start(
            max(300, int(self._calibration_zero_trim_air_zero_adjust_timeout_ms))
        )
        return True

    def _continue_calibration_zero_trim_air_zero_adjust(self):
        """Цель функции в продолжении автоподстройки zero trim после ответа DID, затем она запрашивает следующий DID или завершает расчет."""
        if not bool(self._calibration_zero_trim_air_zero_adjust_active):
            return

        if self._calibration_zero_trim_air_zero_adjust_timeout_timer.isActive():
            self._calibration_zero_trim_air_zero_adjust_timeout_timer.stop()

        required_samples = max(1, int(self._calibration_zero_trim_air_zero_adjust_required_samples))
        sample_count = len(self._calibration_zero_trim_air_zero_adjust_level_samples)
        missing_data = (
            self._calibration_zero_trim_air_zero_adjust_empty_period is None
            or self._calibration_zero_trim_air_zero_adjust_full_period is None
            or sample_count < required_samples
            or self._calibration_zero_trim_air_zero_adjust_current_zero_trim is None
        )
        if missing_data:
            if self._request_next_calibration_zero_trim_air_zero_adjust_did():
                return
            self._reset_calibration_zero_trim_air_zero_adjust_state()
            self._set_calibration_zero_trim_operation_status(
                "Автоподстройка zero trim остановлена: не удалось отправить следующий DID-запрос.",
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            return

        self._try_apply_calibration_zero_trim_air_zero_adjust()

    def _on_calibration_zero_trim_air_zero_adjust_timeout(self):
        """Цель функции в защите от зависания автоподстройки zero trim, затем она завершает операцию по таймауту шага чтения DID."""
        if not bool(self._calibration_zero_trim_air_zero_adjust_active):
            return
        self._reset_calibration_zero_trim_air_zero_adjust_state()
        self._set_calibration_zero_trim_operation_status(
            "Автоподстройка zero trim остановлена по таймауту чтения DID. Повторите операцию.",
            busy=False,
            progress_percent=100,
            determinate=True,
        )
        self._append_log(
            "Калибровка: автоподстройка zero trim остановлена по таймауту (ожидание DID 0x0012/0x0013/0x0018/0x002D).",
            RowColor.red,
        )

    def _try_apply_calibration_zero_trim_air_zero_adjust(self):
        """Цель функции в завершении автоподстройки zero trim, затем она вычисляет значение по фактическому уровню DID 0x0018 и отправляет DID 0x002D."""
        if not bool(self._calibration_zero_trim_air_zero_adjust_active):
            return

        empty_period = self._calibration_zero_trim_air_zero_adjust_empty_period
        full_period = self._calibration_zero_trim_air_zero_adjust_full_period
        level_samples = list(self._calibration_zero_trim_air_zero_adjust_level_samples)
        current_zero_trim = self._calibration_zero_trim_air_zero_adjust_current_zero_trim
        if (
            empty_period is None
            or full_period is None
            or len(level_samples) <= 0
            or current_zero_trim is None
        ):
            return

        current_level_x10 = int(round(sum(level_samples) / float(len(level_samples))))
        sample_spread_x10 = int(max(level_samples) - min(level_samples))
        stability_threshold_x10 = max(0, int(self._calibration_zero_trim_air_zero_adjust_stability_threshold_x10))
        if sample_spread_x10 > stability_threshold_x10:
            self._reset_calibration_zero_trim_air_zero_adjust_state()
            self._set_calibration_zero_trim_operation_status(
                (
                    "Автоподстройка zero trim остановлена: сигнал уровня нестабилен, "
                    f"разброс {float(sample_spread_x10) / 10.0:.1f}% выше порога {float(stability_threshold_x10) / 10.0:.1f}%."
                ),
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            self._append_log(
                (
                    "Калибровка: автоподстройка zero trim прервана из-за нестабильного уровня "
                    f"(n={len(level_samples)}, разброс={float(sample_spread_x10) / 10.0:.1f}%)."
                ),
                RowColor.yellow,
            )
            return

        span = int(full_period) - int(empty_period)
        if span <= 0:
            self._reset_calibration_zero_trim_air_zero_adjust_state()
            self._set_calibration_zero_trim_operation_status(
                "Автоподстройка zero trim остановлена: некорректные границы 0%/100% (DID 0x0012/0x0013).",
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            return

        current_zero_trim_int = int(current_zero_trim)
        delta_zero_trim, target_zero_trim, residual_x10 = self._calculate_zero_trim_adjustment(
            span_count=int(span),
            current_level_x10=int(current_level_x10),
            current_zero_trim=current_zero_trim_int,
        )
        normalized_level_x10 = max(-1000, min(1000, int(current_level_x10)))
        self._calibration_zero_trim_count_recommended = int(target_zero_trim)
        self._calibration_zero_trim_count_delta = int(delta_zero_trim)
        self._calibration_zero_trim_count_next = int(target_zero_trim)
        self._calibration_zero_trim_residual_x10 = int(residual_x10)
        self._set_calibration_zero_trim_last_report(
            old_zero_trim=int(current_zero_trim_int),
            new_zero_trim=int(target_zero_trim),
            residual_x10=int(residual_x10),
            status_text="расчет выполнен, запись отправлена",
        )
        self._reset_calibration_zero_trim_air_zero_adjust_state()
        self._append_log(
            (
                "Калибровка: автоподстройка zero trim по фактическому уровню МК: "
                f"level={int(normalized_level_x10) / 10.0:.1f}%, span={int(span)} count, "
                f"dTrim={int(delta_zero_trim):+d}, TrimNew={int(current_zero_trim_int)}+{int(delta_zero_trim):+d}={int(target_zero_trim)}, "
                f"остаток={float(residual_x10) / 10.0:+.1f}%, n={len(level_samples)}, разброс={float(sample_spread_x10) / 10.0:.1f}%."
            ),
            RowColor.blue,
        )

        pending_key = int(UdsData.fuel_zero_trim_count.pid)
        pending_before = pending_key in self._calibration_write_verify_pending
        self.writeCalibrationZeroTrim(str(int(target_zero_trim)))
        pending_after = pending_key in self._calibration_write_verify_pending

        if (not pending_before) and pending_after:
            self._calibration_zero_trim_verify_retries_left = max(
                0,
                int(self._calibration_zero_trim_verify_retries_max),
            )
            self._calibration_zero_trim_verify_pending = True
            self._calibration_zero_trim_verify_timeout_timer.start(
                max(500, int(self._calibration_zero_trim_verify_timeout_ms))
            )
            self._set_calibration_zero_trim_operation_status(
                (
                    "Автоподстройка zero trim: рассчитано и отправлено значение "
                    f"{int(target_zero_trim)} в DID 0x002D. Ожидается автопроверка."
                ),
                busy=False,
                progress_percent=100,
                determinate=True,
            )
            return

        self._reset_calibration_zero_trim_verify_state()
        self._set_calibration_zero_trim_operation_status(
            "Автоподстройка zero trim завершена с ошибкой: запись DID 0x002D не подтверждена.",
            busy=False,
            progress_percent=100,
            determinate=True,
        )

    def _request_calibration_zero_trim_read(self) -> bool:
        """Цель функции в чтении текущего zero trim через UDS, затем она отправляет запрос DID 0x002D в выбранный узел."""
        if not self._can.is_connect or not self._can.is_trace:
            return False
        self._configure_calibration_uds_services()
        return bool(
            self._calibration_read_service.read_data_by_identifier(
                self._build_calibration_tx_identifier(),
                UdsData.fuel_zero_trim_count,
            )
        )

    def _request_calibration_raw_level_read(self) -> bool:
        """Цель функции в чтении текущего сырого уровня для автопроверки, затем она отправляет запрос DID 0x0018 в выбранный узел."""
        if not self._can.is_connect or not self._can.is_trace:
            return False
        self._configure_calibration_uds_services()
        return bool(
            self._calibration_read_service.read_data_by_identifier(
                self._build_calibration_tx_identifier(),
                UdsData.raw_fuel_level,
            )
        )

    def _on_calibration_zero_trim_verify_timeout(self):
        """Цель функции в завершении автопроверки zero trim по таймауту, затем она сообщает оператору о необходимости повторить проверку."""
        if not bool(self._calibration_zero_trim_verify_pending):
            return
        retries_left = max(0, int(self._calibration_zero_trim_verify_retries_left))
        if retries_left > 0:
            self._calibration_zero_trim_verify_retries_left = retries_left - 1
            if self._request_calibration_raw_level_read():
                self._calibration_zero_trim_verify_timeout_timer.start(
                    max(500, int(self._calibration_zero_trim_verify_timeout_ms))
                )
                self._set_calibration_zero_trim_operation_status(
                    (
                        "Автопроверка zero trim: DID 0x0018 не получен, выполняется повторный запрос "
                        f"(осталось попыток: {int(self._calibration_zero_trim_verify_retries_left)})."
                    ),
                    busy=True,
                    progress_percent=90,
                    determinate=True,
                )
                self._append_log(
                    "Калибровка: автопроверка zero trim — повторный запрос DID 0x0018 после таймаута.",
                    RowColor.yellow,
                )
                return

        self._set_calibration_zero_trim_last_report(
            old_zero_trim=self._calibration_zero_trim_count_current,
            new_zero_trim=self._calibration_zero_trim_count_next,
            residual_x10=self._calibration_zero_trim_residual_x10,
            status_text="таймаут автопроверки, нужен повтор",
            write_csv=True,
        )
        self._reset_calibration_zero_trim_verify_state()
        self._set_calibration_zero_trim_operation_status(
            "Автопроверка zero trim не завершена: не получен DID 0x0018. Повторите чтение уровня.",
            busy=False,
            progress_percent=100,
            determinate=True,
        )
        self._append_log(
            "Калибровка: автопроверка zero trim остановлена по таймауту ожидания DID 0x0018.",
            RowColor.yellow,
        )

    def _handle_calibration_frame(self, identifier: int, payload: list[int]):
        if len(payload) < 2:
            return

        self._try_bind_calibration_runtime_target_from_session_response(identifier, payload)
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
                if (did is None) and (not self._calibration_restore_active):
                    # Игнорируем чужие ответы 0x2E (например, запись DID из других карточек UI).
                    return

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
                elif nrc in (0x7E, 0x7F):
                    extra_hint = (
                        " На МК неактивна требуемая диагностическая сессия. "
                        "Повторно запустите калибровку (0x10/0x27) и повторите запись."
                    )

                self._append_log(
                    f"Калибровка: запись {did_label} отклонена, NRC 0x{nrc:02X} ({nrc_text}).{extra_hint}",
                    RowColor.red,
                )
                if nrc in (0x7E, 0x7F):
                    self._invalidate_calibration_session_after_nrc(
                        "Калибровка: сессия на МК завершена или недоступна. Перезапустите калибровку перед записью параметров."
                    )
                self._recompute_calibration_wizard_state()
                return

            if original_sid == 0x22:
                if (
                    (not bool(self._calibration_dump_capture_active))
                    and (str(self._calibration_sequence_waiting_action or "") not in ("read_level_0", "read_level_100"))
                ):
                    # Игнорируем чужие ответы 0x22 (например, чтение DID из других карточек UI).
                    return

                if bool(self._calibration_dump_capture_active):
                    did_text = "-"
                    if self._calibration_dump_capture_current_did is not None:
                        did_text = f"0x{int(self._calibration_dump_capture_current_did) & 0xFFFF:04X}"
                    self._finish_calibration_dump_capture(
                        False,
                        f"Калибровка: чтение дампа отклонено, DID {did_text}, NRC 0x{nrc:02X} ({nrc_text}).",
                    )
                    return

                if self._calibration_sequence_waiting_action in ("read_level_0", "read_level_100"):
                    self._fail_calibration_activation(
                        f"Калибровка: чтение исходных уровней отклонено, NRC 0x{nrc:02X} ({nrc_text})."
                    )
                    return
                self._append_log(
                    f"Калибровка: чтение параметра отклонено, NRC 0x{nrc:02X} ({nrc_text}).",
                    RowColor.red,
                )
                if nrc in (0x7E, 0x7F):
                    self._invalidate_calibration_session_after_nrc(
                        "Калибровка: сессия на МК завершена или недоступна. Перезапустите калибровку перед чтением параметров."
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
                self._set_calibration_session_ready(False)
                if current_action == "deactivate_session":
                    self._append_log("Калибровка: возврат в default-сессию выполнен.", RowColor.green)
                    self._finish_calibration_deactivation("Калибровка завершена. Security Access закрыт, активна default-сессия.")
                    return

                self._append_log("Калибровка: расширенная сессия активирована.", RowColor.green)
                self._schedule_calibration_sequence_action("request_security_seed")
                self._recompute_calibration_wizard_state()
                return

            if payload[1] == 0x7F and len(payload) >= 4 and payload[2] == 0x10:
                self._calibration_waiting_session = False
                self._stop_calibration_poll_timer()
                self._set_calibration_session_ready(False)
                self._calibration_write_verify_pending = {}
                self.calibrationVerificationChanged.emit()
                if self._calibration_active:
                    self._calibration_active = False
                    self.calibrationStateChanged.emit()
                self._append_log(f"Калибровка: ошибка смены сессии (NRC=0x{payload[3]:02X}).", RowColor.red)
                self._recompute_calibration_wizard_state()
                return

        if (int(payload[1]) & 0xFF) == int(self._calibration_read_service.success_sid) and len(payload) >= 4:
            did = (int(payload[2]) << 8) | int(payload[3])
            raw_value = int(self._calibration_read_service.parse_data_field(payload))
            value = int(raw_value)
            changed = False

            if did == int(UdsData.curr_fuel_tank.pid):
                if self._calibration_current_level != value:
                    self._calibration_current_level = value
                    changed = True
                self._add_calibration_recent_sample(value)
            elif did == int(UdsData.empty_fuel_tank.pid):
                self._calibration_level_0 = value
                self._calibration_level_0_known = True
                if bool(self._calibration_zero_trim_air_zero_adjust_active):
                    self._calibration_zero_trim_air_zero_adjust_empty_period = int(value)
                changed = True
                self._append_log(f"Калибровка: считан уровень 0% = {value}.", RowColor.green)
            elif did == int(UdsData.full_fuel_tank.pid):
                self._calibration_level_100 = value
                self._calibration_level_100_known = True
                if bool(self._calibration_zero_trim_air_zero_adjust_active):
                    self._calibration_zero_trim_air_zero_adjust_full_period = int(value)
                changed = True
                self._append_log(f"Калибровка: считан уровень 100% = {value}.", RowColor.green)
            elif did == int(UdsData.raw_fuel_level.pid):
                bits = max(8, int(UdsData.raw_fuel_level.size) * 8)
                signed_level = self._decode_signed_value(raw_value, bits)
                value = int(signed_level)
                if bool(self._calibration_zero_trim_air_zero_adjust_active):
                    self._calibration_zero_trim_air_zero_adjust_level_x10 = int(signed_level)
                    samples = list(self._calibration_zero_trim_air_zero_adjust_level_samples)
                    samples.append(int(signed_level))
                    max_samples = max(1, int(self._calibration_zero_trim_air_zero_adjust_required_samples))
                    if len(samples) > max_samples:
                        samples = samples[-max_samples:]
                    self._calibration_zero_trim_air_zero_adjust_level_samples = list(samples)
                if bool(self._calibration_zero_trim_verify_pending):
                    self._reset_calibration_zero_trim_verify_state()
                    self._calibration_zero_trim_residual_x10 = int(signed_level)
                    tolerance_x10 = max(0, int(self._calibration_zero_trim_verify_tolerance_x10))
                    repeat_threshold_x10 = max(
                        tolerance_x10,
                        int(self._calibration_zero_trim_verify_repeat_threshold_x10),
                    )
                    residual_text = f"{float(int(signed_level)) / 10.0:+.1f}%"
                    verification_state = self._classify_zero_trim_verification_result(
                        residual_x10=int(signed_level),
                        tolerance_x10=int(tolerance_x10),
                        repeat_threshold_x10=int(repeat_threshold_x10),
                    )
                    if verification_state == "success":
                        self._set_calibration_zero_trim_last_report(
                            old_zero_trim=self._calibration_zero_trim_count_current,
                            new_zero_trim=self._calibration_zero_trim_count_next,
                            residual_x10=int(signed_level),
                            status_text="успех",
                            write_csv=True,
                        )
                        self._set_calibration_zero_trim_operation_status(
                            f"Автопроверка zero trim: успех, остаток {residual_text}.",
                            busy=False,
                            progress_percent=100,
                            determinate=True,
                        )
                        self._append_log(
                            f"Калибровка: автопроверка zero trim успешна, остаток уровня {residual_text}.",
                            RowColor.green,
                        )
                    elif verification_state == "repeat":
                        self._set_calibration_zero_trim_last_report(
                            old_zero_trim=self._calibration_zero_trim_count_current,
                            new_zero_trim=self._calibration_zero_trim_count_next,
                            residual_x10=int(signed_level),
                            status_text="нужен повтор",
                            write_csv=True,
                        )
                        self._set_calibration_zero_trim_operation_status(
                            f"Автопроверка zero trim: остаток {residual_text} выше допуска, рекомендуется повторить подгонку.",
                            busy=False,
                            progress_percent=100,
                            determinate=True,
                        )
                        self._append_log(
                            f"Калибровка: автопроверка zero trim дала остаток {residual_text}, рекомендуется повторить подгонку.",
                            RowColor.yellow,
                        )
                    else:
                        self._set_calibration_zero_trim_last_report(
                            old_zero_trim=self._calibration_zero_trim_count_current,
                            new_zero_trim=self._calibration_zero_trim_count_next,
                            residual_x10=int(signed_level),
                            status_text="подозрение на механику/датчик",
                            write_csv=True,
                        )
                        self._set_calibration_zero_trim_operation_status(
                            f"Автопроверка zero trim: остаток {residual_text} слишком большой, проверьте механику/датчик.",
                            busy=False,
                            progress_percent=100,
                            determinate=True,
                        )
                        self._append_log(
                            f"Калибровка: автопроверка zero trim выявила большой остаток {residual_text} — требуется проверка механики/датчика.",
                            RowColor.red,
                        )
            elif did == int(UdsData.raw_temperature.pid):
                bits = max(8, int(UdsData.raw_temperature.size) * 8)
                signed_temperature = self._decode_signed_value(raw_value, bits)
                value = int(signed_temperature)
                self._calibration_last_temperature_x10 = int(signed_temperature)
            elif did == int(UdsData.fuel_zero_trim_count.pid):
                bits = max(8, int(UdsData.fuel_zero_trim_count.size) * 8)
                signed_zero_trim = self._decode_signed_value(raw_value, bits)
                value = int(signed_zero_trim)
                previous_zero_trim = self._calibration_zero_trim_count_current
                self._calibration_zero_trim_count_current = int(signed_zero_trim)
                if previous_zero_trim != signed_zero_trim:
                    self._append_log(
                        f"Калибровка: считана коррекция zero trim = {int(signed_zero_trim)}.",
                        RowColor.green,
                    )
                else:
                    self._append_log(
                        f"Калибровка: подтверждено значение zero trim = {int(signed_zero_trim)} (без изменений).",
                        RowColor.blue,
                    )
                if bool(self._calibration_zero_trim_air_zero_adjust_active):
                    self._calibration_zero_trim_air_zero_adjust_current_zero_trim = int(signed_zero_trim)
            if bool(self._calibration_dump_capture_active):
                required_dids = set(int(item) & 0xFFFF for item in self._calibration_dump_required_dids())
                if (int(did) & 0xFFFF) in required_dids:
                    self._calibration_dump_capture_values[int(did) & 0xFFFF] = int(value)
                    if self._calibration_dump_capture_timeout_timer.isActive():
                        self._calibration_dump_capture_timeout_timer.stop()
                    self._calibration_dump_capture_current_did = None
                    self._request_next_calibration_dump_capture_did()

            if self._calibration_sequence_waiting_action == "read_level_0" and did == int(UdsData.empty_fuel_tank.pid):
                self._finish_calibration_sequence_wait("read_level_0")
                self._schedule_calibration_sequence_action("read_level_100")
            elif self._calibration_sequence_waiting_action == "read_level_100" and did == int(UdsData.full_fuel_tank.pid):
                self._finish_calibration_sequence_wait("read_level_100")
                self._set_calibration_session_ready(True)
                self._start_calibration_poll_timer()
                self._request_calibration_runtime_snapshot()
                self._append_log(
                    "Калибровка: extended-сессия и Security Access активны, исходные уровни считаны. Параметры температурной компенсации читаются только вручную.",
                    RowColor.green,
                )
                self._recompute_calibration_wizard_state()

            if bool(self._calibration_backup_all_nodes_active):
                required_dids = self._calibration_backup_all_nodes_required_dids()
                if did in required_dids:
                    current_sa = self._calibration_backup_all_nodes_current_sa
                    if current_sa is not None:
                        node_key = int(current_sa) & 0xFF
                        node_values = self._calibration_backup_all_nodes_values_by_sa.setdefault(node_key, {})
                        node_values[int(did)] = int(value)
                        if all((required_did in node_values) for required_did in required_dids):
                            if self._calibration_backup_all_nodes_step_timer.isActive():
                                self._calibration_backup_all_nodes_step_timer.stop()
                            self._request_next_calibration_backup_all_nodes_node()

            if (not bool(self._calibration_backup_all_nodes_active)) and self._calibration_backup_pending and did in (int(UdsData.empty_fuel_tank.pid), int(UdsData.full_fuel_tank.pid)):
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

            zero_trim_air_zero_adjust_dids = {
                int(UdsData.empty_fuel_tank.pid),
                int(UdsData.full_fuel_tank.pid),
                int(UdsData.raw_fuel_level.pid),
                int(UdsData.fuel_zero_trim_count.pid),
            }

            if bool(self._calibration_zero_trim_air_zero_adjust_active) and did in zero_trim_air_zero_adjust_dids:
                self._continue_calibration_zero_trim_air_zero_adjust()

            if changed:
                self.calibrationValuesChanged.emit()
            return

        if self._calibration_write_service.verify_answer_write_data(payload):
            did = int(self._calibration_write_service.parse_pid_field(payload))
            if did == int(UdsData.empty_fuel_tank.pid):
                self._append_log("Калибровка: уровень 0% успешно сохранен.", RowColor.green)
                self.readCalibrationLevel0()
                self._append_log(
                    "Калибровка: после изменения 0% рекомендуется выполнить эксплуатационную подгонку zero trim.",
                    RowColor.yellow,
                )
            elif did == int(UdsData.full_fuel_tank.pid):
                self._append_log("Калибровка: уровень 100% успешно сохранен.", RowColor.green)
                self.readCalibrationLevel100()
                self._append_log(
                    "Калибровка: после изменения 100% рекомендуется выполнить эксплуатационную подгонку zero trim.",
                    RowColor.yellow,
                )
            elif did == int(UdsData.fuel_zero_trim_count.pid):
                self._append_log("Калибровка: коррекция zero trim успешно сохранена.", RowColor.green)
                self._request_calibration_zero_trim_read()
                if bool(self._calibration_zero_trim_verify_pending):
                    if not self._request_calibration_raw_level_read():
                        self._reset_calibration_zero_trim_verify_state()
                        self._set_calibration_zero_trim_operation_status(
                            "Автопроверка zero trim не запущена: не удалось отправить DID 0x0018.",
                            busy=False,
                            progress_percent=100,
                            determinate=True,
                        )
                        self._append_log(
                            "Калибровка: после записи zero trim не удалось запросить DID 0x0018 для автопроверки.",
                            RowColor.yellow,
                        )

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
        self._request_calibration_runtime_snapshot()

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
        target_var = UdsData.get_var_by_pid(int(did))
        if target_var is None:
            self._calibration_restore_active = False
            self._calibration_restore_current_did = None
            self._append_log(f"Калибровка: восстановление остановлено, DID 0x{int(did) & 0xFFFF:04X} не найден.", RowColor.red)
            return
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
            elif int(did) == int(UdsData.full_fuel_tank.pid):
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
        self._set_calibration_session_ready(False)
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

        merged_candidates = set(int(value) & 0xFF for value in self._observed_candidate_values)

        for sa in sorted(merged_candidates):
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
        else:
            # При режиме "Авто" всегда держим индекс 0, чтобы отображение не расходилось с реальной логикой target SA.
            new_selected = 0

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

    @classmethod
    def _resolve_calibration_signed_int16_value(
        cls,
        text,
        fallback_value: int | None,
        value_label: str,
        did_hint: str,
    ) -> int:
        """Цель функции в едином разборе signed int16, затем она валидирует dec/hex и подготавливает значение для UDS 0x2E."""
        raw = str(text).strip()
        if not raw:
            if fallback_value is None:
                raise ValueError(
                    f"Текущее значение {value_label} неизвестно. "
                    f"Сначала прочитайте DID {did_hint} или введите число вручную."
                )
            return cls._saturate_int16(int(fallback_value))

        base = 16 if raw.lower().startswith(("0x", "-0x", "+0x")) else 10
        try:
            value = int(raw, base)
        except ValueError as exc:
            raise ValueError(
                f"Некорректное значение {value_label}. Используйте signed dec или 0xHEX."
            ) from exc

        if base == 16 and value >= 0:
            if value > 0xFFFF:
                raise ValueError(f"HEX-значение {value_label} должно быть в диапазоне 0x0000..0xFFFF.")
            if value > cls._INT16_MAX:
                value -= 0x10000

        if value < cls._INT16_MIN or value > cls._INT16_MAX:
            raise ValueError(f"Значение {value_label} вне диапазона int16 (-32768..32767).")

        return int(value)

    @classmethod
    def _resolve_calibration_zero_trim_write_value(cls, text, fallback_value: int | None) -> int:
        """Цель функции в удобном вводе zero trim из UI, затем она парсит dec/hex и приводит значение к int16."""
        return cls._resolve_calibration_signed_int16_value(text, fallback_value, "zero trim", "0x002D")
