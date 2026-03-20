from __future__ import annotations

import csv
from pathlib import Path
import re
import time

from j1939.j1939_can_identifier import J1939CanIdentifier
from colors import RowColor
from uds.data_identifiers import UdsData
from uds.uds_identifiers import UdsIdentifiers

from .contract import AppControllerContract

class AppControllerCalibrationMixin(AppControllerContract):
    _FUEL_TEMP_COMP_REF_X10 = 200
    _INT16_MIN = -32768
    _INT16_MAX = 32767
    _TEMP_COMP_CHART_POINT_LIMIT = 12000

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
        if int(did) == int(UdsData.fuel_temp_comp_k1_x100.pid):
            return "коэффициента K1"
        return f"DID 0x{int(did) & 0xFFFF:04X}"

    def _pending_calibration_write_did(self) -> int | None:
        if self._calibration_restore_current_did is not None:
            return int(self._calibration_restore_current_did)

        for did in (
            int(UdsData.empty_fuel_tank.pid),
            int(UdsData.full_fuel_tank.pid),
            int(UdsData.fuel_temp_comp_k1_x100.pid),
        ):
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

    @classmethod
    def _saturate_int16(cls, value: int) -> int:
        """Цель функции в защите от переполнения DID int16, затем она ограничивает значение диапазоном -32768..32767."""
        return max(cls._INT16_MIN, min(cls._INT16_MAX, int(value)))

    @classmethod
    def _apply_temperature_compensation_model(cls, raw_period: int, temperature_x10: int, k1_x100: int) -> int:
        """Цель функции в точном повторении алгоритма МК, затем она считает Pcomp по формуле из fuel.c."""
        compensated_period = int(raw_period)
        coefficient = int(k1_x100)
        if coefficient != 0:
            d_temperature_x10 = int(temperature_x10) - int(cls._FUEL_TEMP_COMP_REF_X10)
            delta_period = cls._c_trunc_div(coefficient * d_temperature_x10, 1000)
            compensated_period -= delta_period

            if compensated_period < 0:
                compensated_period = 0
            if compensated_period > 0xFFFF:
                compensated_period = 0xFFFF

        return int(compensated_period)

    @classmethod
    def _apply_temperature_compensation_model_precise(cls, raw_period: int | float, temperature_x10: int, k1_x100: int) -> float:
        """Цель функции в плавном расчете компенсации для аналитики, затем она считает Pcomp без целочисленного усечения для наглядного графика."""
        compensated_period = float(raw_period)
        coefficient = float(k1_x100)
        if coefficient != 0.0:
            d_temperature_x10 = float(int(temperature_x10) - int(cls._FUEL_TEMP_COMP_REF_X10))
            delta_period = (coefficient * d_temperature_x10) / 1000.0
            compensated_period -= delta_period

            if compensated_period < 0.0:
                compensated_period = 0.0
            if compensated_period > 65535.0:
                compensated_period = 65535.0

        return float(compensated_period)

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

    def _extract_temp_comp_csv_node_candidates(self, rows: list[list[str]]) -> set[int]:
        """Цель функции в получении списка узлов из CSV, затем она ищет SA в структурных и обычных заголовках."""
        node_candidates: set[int] = set()
        if len(rows) == 0:
            return node_candidates

        for row in rows[:3]:
            for cell in row:
                text = str(cell or "")
                lowered = text.casefold()
                if ("узел" not in lowered) and ("node" not in lowered):
                    continue
                parsed_sa = self._extract_node_sa_from_text(text)
                if parsed_sa is None:
                    continue
                node_candidates.add(int(parsed_sa) & 0xFF)

        if len(node_candidates) > 0:
            return node_candidates

        for row in rows[:8]:
            joined = ";".join(str(cell or "").strip() for cell in row).casefold()
            if not (("период" in joined or "period" in joined) and ("температ" in joined or "temp" in joined)):
                continue

            for cell in row:
                text = str(cell or "")
                lowered = text.casefold()
                if not (
                    ("период" in lowered)
                    or ("period" in lowered)
                    or ("температ" in lowered)
                    or ("temp" in lowered)
                ):
                    continue
                parsed_sa = self._extract_node_sa_from_text(text)
                if parsed_sa is None:
                    continue
                node_candidates.add(int(parsed_sa) & 0xFF)
            break

        return node_candidates

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

    def _build_temp_comp_samples_from_columns(
        self,
        rows: list[list[str]],
        *,
        data_start: int,
        period_index: int,
        temperature_index: int,
    ) -> list[dict[str, object]]:
        """Цель функции в сборке точек анализа, затем она конвертирует строки CSV в формат внутренних семплов."""
        samples: list[dict[str, object]] = []
        for row in rows[data_start:]:
            if len(row) <= max(period_index, temperature_index):
                continue

            period = self._parse_csv_int(row[period_index])
            temperature_c = self._parse_csv_float(row[temperature_index])
            if period is None or temperature_c is None:
                continue

            temperature_x10 = int(round(float(temperature_c) * 10.0))
            samples.append(
                {
                    "period": int(period),
                    "temperature_x10": int(temperature_x10),
                    "temperature_c": float(temperature_x10) / 10.0,
                    "timestamp": float(len(samples)),
                }
            )

        return samples

    def _parse_temp_comp_structured_csv_all_nodes(
        self,
        rows: list[list[str]],
    ) -> dict[int, dict[str, object]]:
        """Цель функции в разборе all_nodes CSV по всем узлам, затем она возвращает выборки и калибровку для каждого SA."""
        if len(rows) < 3:
            return {}

        node_row = rows[0]
        second_row = rows[1] if len(rows) > 1 else []
        third_row = rows[2] if len(rows) > 2 else []

        second_joined = ";".join(str(cell or "").strip() for cell in second_row).casefold()
        has_calibration_meta = (
            ("empty=" in second_joined)
            or ("full=" in second_joined)
            or ("калибровк" in second_joined)
        )

        calibration_row = second_row if has_calibration_meta else []
        labels_row = third_row if has_calibration_meta else second_row
        data_start = 3 if has_calibration_meta else 2
        node_data_by_sa: dict[int, dict[str, object]] = {}

        for index, cell in enumerate(node_row):
            text = str(cell or "")
            lowered = text.casefold()
            if ("узел" not in lowered) and ("node" not in lowered):
                continue

            node_sa = self._extract_node_sa_from_text(text)
            if node_sa is None:
                continue
            node_sa_key = int(node_sa) & 0xFF

            period_index = None
            temperature_index = None
            search_end = min(len(labels_row), index + 6)
            for column in range(index, search_end):
                label_text = str(labels_row[column] if column < len(labels_row) else "").casefold()
                if period_index is None and (("период" in label_text) or ("period" in label_text)):
                    period_index = column
                if temperature_index is None and (("температ" in label_text) or ("temp" in label_text)):
                    temperature_index = column

            if period_index is None:
                period_index = index
            if temperature_index is None:
                temperature_index = index + 2

            samples = self._build_temp_comp_samples_from_columns(
                rows,
                data_start=data_start,
                period_index=int(period_index),
                temperature_index=int(temperature_index),
            )
            if len(samples) <= 0:
                continue

            calibration_cells: list[str] = []
            if index < len(calibration_row):
                calibration_cells.append(str(calibration_row[index]))
            if (index + 1) < len(calibration_row):
                calibration_cells.append(str(calibration_row[index + 1]))
            empty_period, full_period = self._extract_empty_full_from_text(";".join(calibration_cells))

            existing_entry = node_data_by_sa.get(node_sa_key)
            if existing_entry is None:
                node_data_by_sa[node_sa_key] = {
                    "samples": list(samples),
                    "empty": None if empty_period is None else int(empty_period),
                    "full": None if full_period is None else int(full_period),
                }
                continue

            merged_samples = list(existing_entry.get("samples", []))
            merged_samples.extend(samples)
            existing_entry["samples"] = merged_samples
            if empty_period is not None:
                existing_entry["empty"] = int(empty_period)
            if full_period is not None:
                existing_entry["full"] = int(full_period)

        return node_data_by_sa

    def _parse_temp_comp_structured_csv(
        self,
        rows: list[list[str]],
        *,
        selected_sa: int | None,
    ) -> tuple[list[dict[str, object]], int | None, int | None, int | None]:
        """Цель функции в выборе одного узла из all_nodes CSV, затем она возвращает выборку для текущего SA."""
        node_data_by_sa = self._parse_temp_comp_structured_csv_all_nodes(rows)
        if len(node_data_by_sa) <= 0:
            return [], None, None, None

        chosen_sa: int | None = None
        if selected_sa is not None:
            wanted_sa = int(selected_sa) & 0xFF
            if wanted_sa not in node_data_by_sa:
                return [], None, None, None
            chosen_sa = wanted_sa

        if chosen_sa is None:
            chosen_sa = next(iter(node_data_by_sa.keys()))

        chosen_payload = node_data_by_sa.get(int(chosen_sa) & 0xFF, {})
        samples = list(chosen_payload.get("samples", []))
        empty_value = chosen_payload.get("empty")
        full_value = chosen_payload.get("full")
        return (
            samples,
            int(chosen_sa) & 0xFF,
            None if empty_value is None else int(empty_value),
            None if full_value is None else int(full_value),
        )

    def _parse_temp_comp_generic_csv(
        self,
        rows: list[list[str]],
        *,
        selected_sa: int | None,
    ) -> tuple[list[dict[str, object]], int | None, int | None, int | None]:
        """Цель функции в поддержке старых CSV форматов, затем она ищет колонки периода/температуры и строит выборку."""
        header_index = -1
        header_row: list[str] = []
        for index, row in enumerate(rows):
            joined = ";".join(str(cell or "").strip() for cell in row).casefold()
            if ("период" in joined or "period" in joined) and ("температ" in joined or "temp" in joined):
                header_index = index
                header_row = row
                break

        if header_index < 0:
            return [], None, None, None

        period_by_sa: dict[int, int] = {}
        temp_by_sa: dict[int, int] = {}
        period_no_sa: list[int] = []
        temp_no_sa: list[int] = []

        for index, cell in enumerate(header_row):
            text = str(cell or "")
            lowered = text.casefold()
            node_sa = self._extract_node_sa_from_text(text)
            if "период" in lowered or "period" in lowered:
                if node_sa is None:
                    period_no_sa.append(index)
                else:
                    period_by_sa[int(node_sa)] = index
            if "температ" in lowered or "temp" in lowered:
                if node_sa is None:
                    temp_no_sa.append(index)
                else:
                    temp_by_sa[int(node_sa)] = index

        node_sa_used = None
        period_index = None
        temperature_index = None

        if selected_sa is not None:
            selected_key = int(selected_sa) & 0xFF
            if selected_key in period_by_sa and selected_key in temp_by_sa:
                node_sa_used = selected_key
                period_index = int(period_by_sa[selected_key])
                temperature_index = int(temp_by_sa[selected_key])
            elif len(period_no_sa) > 0 and len(temp_no_sa) > 0:
                # CSV без SA-меток в заголовке: используем первую пару колонок.
                node_sa_used = selected_key
                period_index = int(period_no_sa[0])
                temperature_index = int(temp_no_sa[0])
            else:
                return [], None, None, None
        elif len(period_no_sa) > 0 and len(temp_no_sa) > 0:
            period_index = int(period_no_sa[0])
            temperature_index = int(temp_no_sa[0])
        else:
            common_nodes = sorted(set(period_by_sa.keys()) & set(temp_by_sa.keys()))
            if len(common_nodes) == 0:
                return [], None, None, None
            node_sa_used = int(common_nodes[0]) & 0xFF
            period_index = int(period_by_sa[node_sa_used])
            temperature_index = int(temp_by_sa[node_sa_used])

        empty_period = None
        full_period = None
        for row in rows[:header_index + 1]:
            empty_candidate, full_candidate = self._extract_empty_full_from_text(";".join(str(cell) for cell in row))
            if empty_candidate is not None:
                empty_period = int(empty_candidate)
            if full_candidate is not None:
                full_period = int(full_candidate)

        samples = self._build_temp_comp_samples_from_columns(
            rows,
            data_start=header_index + 1,
            period_index=int(period_index),
            temperature_index=int(temperature_index),
        )
        return samples, node_sa_used, empty_period, full_period

    def _parse_temp_comp_generic_csv_all_nodes(
        self,
        rows: list[list[str]],
    ) -> dict[int, dict[str, object]]:
        """Цель функции в разборе SA-колонок generic CSV, затем она формирует выборки по каждому найденному узлу."""
        header_index = -1
        header_row: list[str] = []
        for index, row in enumerate(rows):
            joined = ";".join(str(cell or "").strip() for cell in row).casefold()
            if ("период" in joined or "period" in joined) and ("температ" in joined or "temp" in joined):
                header_index = index
                header_row = row
                break

        if header_index < 0:
            return {}

        period_by_sa: dict[int, int] = {}
        temp_by_sa: dict[int, int] = {}
        for index, cell in enumerate(header_row):
            text = str(cell or "")
            lowered = text.casefold()
            node_sa = self._extract_node_sa_from_text(text)
            if node_sa is None:
                continue
            node_key = int(node_sa) & 0xFF
            if "период" in lowered or "period" in lowered:
                period_by_sa[node_key] = int(index)
            if "температ" in lowered or "temp" in lowered:
                temp_by_sa[node_key] = int(index)

        common_nodes = sorted(set(period_by_sa.keys()) & set(temp_by_sa.keys()))
        if len(common_nodes) <= 0:
            return {}

        empty_period = None
        full_period = None
        for row in rows[:header_index + 1]:
            empty_candidate, full_candidate = self._extract_empty_full_from_text(";".join(str(cell) for cell in row))
            if empty_candidate is not None:
                empty_period = int(empty_candidate)
            if full_candidate is not None:
                full_period = int(full_candidate)

        node_data_by_sa: dict[int, dict[str, object]] = {}
        for node_sa in common_nodes:
            samples = self._build_temp_comp_samples_from_columns(
                rows,
                data_start=header_index + 1,
                period_index=int(period_by_sa[node_sa]),
                temperature_index=int(temp_by_sa[node_sa]),
            )
            if len(samples) <= 0:
                continue
            node_data_by_sa[int(node_sa) & 0xFF] = {
                "samples": list(samples),
                "empty": None if empty_period is None else int(empty_period),
                "full": None if full_period is None else int(full_period),
            }

        return node_data_by_sa

    def _parse_calibration_temp_comp_csv_file(
        self,
        csv_path: Path,
        *,
        selected_sa: int | None,
    ) -> tuple[list[dict[str, object]], int | None, int | None, int | None, set[int]]:
        """Цель функции в разборе одного CSV лога, затем она извлекает точки period+temperature для анализа K1."""
        try:
            resolved_path = Path(csv_path).expanduser().resolve()
        except Exception:
            resolved_path = Path(csv_path)

        if not resolved_path.exists() or not resolved_path.is_file():
            return [], None, None, None, set()

        try:
            with resolved_path.open("r", encoding="utf-8-sig", newline="") as file:
                rows = list(csv.reader(file, delimiter=";"))
        except Exception:
            return [], None, None, None, set()

        if len(rows) == 0:
            return [], None, None, None, set()

        node_candidates = self._extract_temp_comp_csv_node_candidates(rows)

        structured_samples, structured_sa, structured_empty, structured_full = self._parse_temp_comp_structured_csv(
            rows,
            selected_sa=selected_sa,
        )
        if len(structured_samples) > 0:
            return structured_samples, structured_sa, structured_empty, structured_full, node_candidates

        # Если это структурированный all_nodes (есть групповые колонки "узел"/"node"),
        # но выбранный SA в файле отсутствует, не подменяем выбор generic-парсером.
        if selected_sa is not None and len(rows) > 0:
            first_row_joined = ";".join(str(cell or "").strip() for cell in rows[0]).casefold()
            if ("узел" in first_row_joined) or ("node" in first_row_joined):
                return [], None, None, None, node_candidates

        parsed_samples, parsed_sa, parsed_empty, parsed_full = self._parse_temp_comp_generic_csv(
            rows,
            selected_sa=selected_sa,
        )
        return parsed_samples, parsed_sa, parsed_empty, parsed_full, node_candidates

    def _parse_calibration_temp_comp_csv_file_all_nodes(
        self,
        csv_path: Path,
    ) -> tuple[dict[int, dict[str, object]], set[int]]:
        """Цель функции в извлечении выборок всех узлов из одного CSV, затем она подготавливает карту SA->данные."""
        try:
            resolved_path = Path(csv_path).expanduser().resolve()
        except Exception:
            resolved_path = Path(csv_path)

        if not resolved_path.exists() or not resolved_path.is_file():
            return {}, set()

        try:
            with resolved_path.open("r", encoding="utf-8-sig", newline="") as file:
                rows = list(csv.reader(file, delimiter=";"))
        except Exception:
            return {}, set()

        if len(rows) == 0:
            return {}, set()

        node_candidates = self._extract_temp_comp_csv_node_candidates(rows)
        structured_data = self._parse_temp_comp_structured_csv_all_nodes(rows)
        if len(structured_data) > 0:
            node_candidates.update(int(value) & 0xFF for value in structured_data.keys())
            return structured_data, node_candidates

        generic_data = self._parse_temp_comp_generic_csv_all_nodes(rows)
        if len(generic_data) > 0:
            node_candidates.update(int(value) & 0xFF for value in generic_data.keys())
            return generic_data, node_candidates

        return {}, node_candidates

    def _load_calibration_temp_comp_csv_files(self, paths: list[Path]) -> tuple[int, int]:
        """Цель функции в пакетной загрузке CSV, затем она агрегирует выборки по узлам и обновляет анализ K1."""
        selected_sa = self._calibration_target_node_sa
        selected_key = None if selected_sa is None else (int(selected_sa) & 0xFF)
        requested_files = len(paths)
        loaded_files = 0
        loaded_points = 0
        skipped_files = 0
        csv_node_candidates: set[int] = set()
        aggregated_by_sa: dict[int, dict[str, object]] = {}

        # Перед новой загрузкой очищаем прошлый набор офлайн-выборок по узлам.
        self._calibration_temp_comp_samples_by_node = {}

        for source_path in paths:
            file_node_data, file_node_candidates = self._parse_calibration_temp_comp_csv_file_all_nodes(source_path)
            csv_node_candidates.update(int(value) & 0xFF for value in file_node_candidates)

            if len(file_node_data) <= 0:
                samples, node_sa_used, empty_period, full_period, fallback_candidates = self._parse_calibration_temp_comp_csv_file(
                    source_path,
                    selected_sa=selected_key,
                )
                csv_node_candidates.update(int(value) & 0xFF for value in fallback_candidates)
                if len(samples) <= 0:
                    skipped_files += 1
                    continue

                fallback_sa = node_sa_used
                if fallback_sa is None:
                    if selected_key is not None:
                        fallback_sa = selected_key
                    else:
                        fallback_sa = int(self._resolve_calibration_target_sa()) & 0xFF

                file_node_data = {
                    int(fallback_sa) & 0xFF: {
                        "samples": list(samples),
                        "empty": None if empty_period is None else int(empty_period),
                        "full": None if full_period is None else int(full_period),
                    }
                }

            loaded_files += 1
            for node_sa, payload in file_node_data.items():
                node_key = int(node_sa) & 0xFF
                node_samples = list(payload.get("samples", []))
                if len(node_samples) <= 0:
                    continue

                loaded_points += len(node_samples)
                csv_node_candidates.add(node_key)
                existing = aggregated_by_sa.get(node_key)
                if existing is None:
                    aggregated_by_sa[node_key] = {
                        "samples": list(node_samples),
                        "empty": payload.get("empty"),
                        "full": payload.get("full"),
                    }
                    continue

                merged_samples = list(existing.get("samples", []))
                merged_samples.extend(node_samples)
                existing["samples"] = merged_samples
                if payload.get("empty") is not None:
                    existing["empty"] = payload.get("empty")
                if payload.get("full") is not None:
                    existing["full"] = payload.get("full")

        prepared_by_sa: dict[int, dict[str, object]] = {}
        for node_sa, payload in aggregated_by_sa.items():
            node_key = int(node_sa) & 0xFF
            node_samples = list(payload.get("samples", []))
            if len(node_samples) <= 0:
                continue

            prepared_by_sa[node_key] = {
                "samples": list(node_samples),
                "empty": payload.get("empty"),
                "full": payload.get("full"),
            }

        if len(prepared_by_sa) <= 0:
            self._calibration_temp_comp_samples_by_node = {}
            self._calibration_temp_comp_status = (
                f"CSV-файлы обработаны ({int(requested_files)}), но данные period/temperature не распознаны."
            )
            if len(csv_node_candidates) > 0:
                self._calibration_csv_node_candidates = set(int(value) & 0xFF for value in csv_node_candidates)
                self._refresh_calibration_node_options()
                if selected_key is not None:
                    available_nodes = ", ".join(f"0x{value:02X}" for value in sorted(csv_node_candidates))
                    self._calibration_temp_comp_status = (
                        f"В выбранных CSV нет данных для узла 0x{selected_key:02X}. "
                        f"Доступные узлы в файлах: {available_nodes}."
                    )
            self.calibrationTempCompChanged.emit()
            return 0, 0

        self._calibration_temp_comp_samples_by_node = prepared_by_sa
        effective_candidates = set(int(value) & 0xFF for value in csv_node_candidates)
        effective_candidates.update(int(value) & 0xFF for value in prepared_by_sa.keys())
        self._calibration_csv_node_candidates = effective_candidates
        self._refresh_calibration_node_options()

        applied_sa = self._select_calibration_temp_comp_cached_node(
            selected_sa=selected_key,
            clear_coefficients=False,
        )

        if applied_sa is None and selected_key is not None:
            available_nodes = ", ".join(f"0x{value:02X}" for value in sorted(prepared_by_sa.keys()))
            self._reset_calibration_temp_comp_state(
                clear_samples=True,
                clear_coefficients=False,
                clear_cached_nodes=False,
            )
            self._calibration_temp_comp_status = (
                f"В выбранных CSV нет данных для узла 0x{selected_key:02X}. "
                f"Доступные узлы в файлах: {available_nodes}. "
                "Выберите другой узел в списке сверху."
            )
            self.calibrationTempCompChanged.emit()
            return loaded_files, loaded_points

        status_hints: list[str] = []
        if applied_sa is not None:
            status_hints.append(f"Активный узел анализа: 0x{int(applied_sa) & 0xFF:02X}.")
            if len(prepared_by_sa) > 1:
                status_hints.append("Для просмотра другого узла переключите селектор узла сверху.")
        if skipped_files > 0:
            status_hints.append(f"Пропущено файлов без подходящих данных: {int(skipped_files)}.")
        if len(prepared_by_sa) > 1:
            sorted_sas = ", ".join(f"0x{value:02X}" for value in sorted(prepared_by_sa.keys()))
            status_hints.append(f"В CSV обнаружены узлы: {sorted_sas}.")

        if len(status_hints) > 0:
            self._calibration_temp_comp_status = f"{self._calibration_temp_comp_status} {' '.join(status_hints)}"
            self.calibrationTempCompChanged.emit()

        return loaded_files, loaded_points

    @staticmethod
    def _build_temp_comp_period_accessor(
        samples: list[dict[str, object]],
        compensated_periods: list[float] | None,
    ):
        """Цель функции в выборе источника period для графика, затем она возвращает быстрый accessor по индексу."""
        if compensated_periods is None:
            return lambda idx: float(samples[idx].get("period", 0.0))
        return lambda idx: float(compensated_periods[idx]) if idx < len(compensated_periods) else float(samples[idx].get("period", 0.0))

    @classmethod
    def _select_temp_comp_chart_indices(
        cls,
        samples: list[dict[str, object]],
        *,
        compensated_periods: list[float] | None = None,
    ) -> list[int]:
        """Цель функции в подготовке индексов графика без перегруза UI, затем она сохраняет пики и края каждого температурного сегмента."""
        total_points = len(samples)
        if total_points <= 0:
            return []

        max_points = max(512, int(cls._TEMP_COMP_CHART_POINT_LIMIT))
        if total_points <= max_points:
            return list(range(total_points))

        period_at = cls._build_temp_comp_period_accessor(samples, compensated_periods)
        bucket_count = max(1, max_points // 4)
        bucket_size = max(1, int((total_points + bucket_count - 1) // bucket_count))

        selected_indices: list[int] = []
        used_indices: set[int] = set()

        def add_index(index: int):
            if index < 0 or index >= total_points:
                return
            if index in used_indices:
                return
            used_indices.add(index)
            selected_indices.append(index)

        for start in range(0, total_points, bucket_size):
            end = min(total_points, start + bucket_size)
            if end <= start:
                continue

            first_index = start
            last_index = end - 1
            min_index = first_index
            max_index = first_index
            min_period = period_at(first_index)
            max_period = min_period

            for index in range(start + 1, end):
                period_value = period_at(index)
                if period_value < min_period:
                    min_period = period_value
                    min_index = index
                if period_value > max_period:
                    max_period = period_value
                    max_index = index

            for index in sorted({first_index, min_index, max_index, last_index}):
                add_index(index)

        add_index(total_points - 1)
        selected_indices.sort()
        return selected_indices

    @classmethod
    def _build_calibration_temp_comp_chart_points(
        cls,
        samples: list[dict[str, object]],
        *,
        compensated_periods: list[float] | None = None,
    ) -> list[dict[str, object]]:
        """Цель функции в подготовке данных для TrendCanvas, затем она ограничивает payload без потери ключевой формы сигнала."""
        selected_indices = cls._select_temp_comp_chart_indices(
            samples,
            compensated_periods=compensated_periods,
        )
        period_at = cls._build_temp_comp_period_accessor(samples, compensated_periods)

        points: list[dict[str, object]] = []
        for index in selected_indices:
            sample = samples[index]
            points.append(
                {
                    "fuel": float(period_at(index)),
                    "temperature": float(sample.get("temperature_c", 0.0)),
                    "time": str(int(index) + 1),
                }
            )
        return points
    def _recompute_calibration_temp_comp_metrics(self):
        """Цель функции в пересчете рекомендаций по K1, затем она обновляет метрики дрейфа и серии графика для UI."""
        samples = list(self._calibration_temp_comp_samples)
        sample_count = len(samples)
        current_k1 = self._calibration_temp_comp_k1_x100_current
        base_k1: int | None = None

        ordered_samples = sorted(
            samples,
            key=lambda item: (
                float(item.get("temperature_c", 0.0)),
                float(item.get("timestamp", 0.0)),
            ),
        )
        temperatures = [float(item.get("temperature_c", 0.0)) for item in ordered_samples]
        raw_periods = [float(sample.get("period", 0.0)) for sample in ordered_samples]

        recommended_k1: int | None = None
        delta_k1: int | None = None
        next_k1: int | None = None

        period_slope_before: float | None = None
        period_slope_after: float | None = None
        level_slope_before: float | None = None
        level_slope_after: float | None = None
        period_reduction_percent: float | None = None
        level_reduction_percent: float | None = None

        current_comp_periods: list[float] = []
        recommended_comp_periods: list[float] = []

        level_calibration_ready = (
            bool(self._calibration_level_0_known)
            and bool(self._calibration_level_100_known)
            and (int(self._calibration_level_100) > int(self._calibration_level_0))
        )

        if sample_count > 0:
            base_k1 = int(current_k1) if current_k1 is not None else 0

        if sample_count >= 2 and base_k1 is not None:
            period_slope_before = self._linear_regression_slope(temperatures, raw_periods)
            if period_slope_before is not None:
                recommended_k1 = self._saturate_int16(int(round(float(period_slope_before) * 100.0)))
                delta_k1 = int(recommended_k1) - int(base_k1)
                next_k1 = int(recommended_k1)

                recommended_comp_periods = [
                    self._apply_temperature_compensation_model_precise(
                        float(sample.get("period", 0.0)),
                        int(sample.get("temperature_x10", 0)),
                        int(recommended_k1),
                    )
                    for sample in ordered_samples
                ]
                period_slope_after = self._linear_regression_slope(temperatures, recommended_comp_periods)

            if current_k1 is not None:
                current_comp_periods = [
                    self._apply_temperature_compensation_model_precise(
                        float(sample.get("period", 0.0)),
                        int(sample.get("temperature_x10", 0)),
                        int(current_k1),
                    )
                    for sample in ordered_samples
                ]

            if level_calibration_ready:
                raw_levels: list[float] = []
                raw_levels_valid = True
                for period_value in raw_periods:
                    converted = self._period_to_level_percent(period_value)
                    if converted is None:
                        raw_levels_valid = False
                        break
                    raw_levels.append(float(converted))

                if raw_levels_valid and len(raw_levels) == sample_count:
                    level_slope_before = self._linear_regression_slope(temperatures, raw_levels)
                    if len(recommended_comp_periods) == sample_count:
                        recommended_levels = [self._period_to_level_percent(value) for value in recommended_comp_periods]
                        if all(level is not None for level in recommended_levels):
                            level_slope_after = self._linear_regression_slope(
                                temperatures,
                                [float(level) for level in recommended_levels if level is not None],
                            )

            period_reduction_percent = self._calc_reduction_percent(period_slope_before, period_slope_after)
            level_reduction_percent = self._calc_reduction_percent(level_slope_before, level_slope_after)

        chart_series: list[dict[str, object]] = []
        if sample_count > 0:
            chart_series.append(
                {
                    "node": "Сырой период",
                    "color": "#dc2626",
                    "points": self._build_calibration_temp_comp_chart_points(ordered_samples),
                }
            )

            if (
                len(current_comp_periods) == sample_count
                and current_k1 is not None
                and (recommended_k1 is None or int(current_k1) != int(recommended_k1))
            ):
                chart_series.append(
                    {
                        "node": f"После текущего K1 ({int(current_k1)})",
                        "color": "#2563eb",
                        "points": self._build_calibration_temp_comp_chart_points(
                            ordered_samples,
                            compensated_periods=current_comp_periods,
                        ),
                    }
                )

            if len(recommended_comp_periods) == sample_count and recommended_k1 is not None:
                max_shift = max(
                    abs(float(recommended_comp_periods[index]) - float(raw_periods[index]))
                    for index in range(sample_count)
                ) if sample_count > 0 else 0.0
                shift_hint = "" if max_shift >= 0.05 else " (эффект очень мал)"
                chart_series.append(
                    {
                        "node": f"После рекоменд. K1 ({int(recommended_k1)}){shift_hint}",
                        "color": "#16a34a",
                        "points": self._build_calibration_temp_comp_chart_points(
                            ordered_samples,
                            compensated_periods=recommended_comp_periods,
                        ),
                    }
                )

        if sample_count <= 0:
            detail_text = "Загрузите CSV из коллектора (all_nodes.csv или 0xNN.csv), чтобы рассчитать K1."
        elif sample_count < 2:
            detail_text = f"Собрано точек: {sample_count}. Для регрессии нужно минимум 2."
        else:
            temp_min = min(temperatures)
            temp_max = max(temperatures)
            period_min = min(raw_periods)
            period_max = max(raw_periods)
            detail_text = (
                f"Точек: {sample_count}, температура: {temp_min:.1f}..{temp_max:.1f} °C, "
                f"период: {period_min:.1f}..{period_max:.1f} count."
            )
            if base_k1 is not None:
                detail_text += f" Базовый K1={int(base_k1)}."
            if recommended_k1 is not None:
                detail_text += f" Рекоменд. K1={int(recommended_k1)}."
            if delta_k1 is not None:
                detail_text += f" dK1={int(delta_k1):+d}."
            if not level_calibration_ready:
                detail_text += " Метрики в % будут доступны после чтения калибровок 0% и 100%."

        if sample_count <= 0:
            self._calibration_temp_comp_status = detail_text
        else:
            self._calibration_temp_comp_status = f"Офлайн-анализ CSV. {detail_text}"

        self._calibration_temp_comp_k1_x100_base = base_k1
        self._calibration_temp_comp_k1_x100_recommended = recommended_k1
        self._calibration_temp_comp_k1_x100_delta = delta_k1
        self._calibration_temp_comp_k1_x100_next = next_k1
        self._calibration_temp_comp_period_slope_before = period_slope_before
        self._calibration_temp_comp_period_slope_after = period_slope_after
        self._calibration_temp_comp_level_slope_before = level_slope_before
        self._calibration_temp_comp_level_slope_after = level_slope_after
        self._calibration_temp_comp_period_reduction_percent = period_reduction_percent
        self._calibration_temp_comp_level_reduction_percent = level_reduction_percent
        self._calibration_temp_comp_chart_series = chart_series
        self.calibrationTempCompChanged.emit()

    def _apply_calibration_temp_comp_node_samples(self, node_sa: int, *, clear_coefficients: bool) -> bool:
        """Цель функции в активации выборки конкретного узла, затем она обновляет метрики и связанные поля UI."""
        node_key = int(node_sa) & 0xFF
        payload = self._calibration_temp_comp_samples_by_node.get(node_key)
        if not isinstance(payload, dict):
            return False

        node_samples = list(payload.get("samples", []))
        if len(node_samples) <= 0:
            return False

        self._calibration_temp_comp_samples = list(node_samples)
        last_sample = self._calibration_temp_comp_samples[-1]
        self._calibration_temp_comp_last_period = int(last_sample.get("period", 0))
        self._calibration_temp_comp_last_temperature_x10 = int(last_sample.get("temperature_x10", 0))
        self._calibration_temp_comp_last_temperature_c = float(last_sample.get("temperature_c", 0.0))

        if clear_coefficients:
            self._calibration_temp_comp_k1_x100_current = None

        empty_value = payload.get("empty")
        full_value = payload.get("full")
        levels_changed = False
        if empty_value is not None and full_value is not None:
            empty_period = int(empty_value)
            full_period = int(full_value)
            if full_period > empty_period:
                if (
                    int(self._calibration_level_0) != empty_period
                    or int(self._calibration_level_100) != full_period
                    or not bool(self._calibration_level_0_known)
                    or not bool(self._calibration_level_100_known)
                ):
                    self._calibration_level_0 = empty_period
                    self._calibration_level_100 = full_period
                    self._calibration_level_0_known = True
                    self._calibration_level_100_known = True
                    levels_changed = True
        if levels_changed:
            self.calibrationValuesChanged.emit()

        self._recompute_calibration_temp_comp_metrics()
        return True

    def _select_calibration_temp_comp_cached_node(
        self,
        *,
        selected_sa: int | None,
        clear_coefficients: bool,
    ) -> int | None:
        """Цель функции в выборе активного узла из загруженного кэша, затем она применяет выборку этого узла."""
        if len(self._calibration_temp_comp_samples_by_node) <= 0:
            return None

        chosen_sa = None
        if selected_sa is not None:
            selected_key = int(selected_sa) & 0xFF
            if selected_key in self._calibration_temp_comp_samples_by_node:
                chosen_sa = selected_key
        else:
            auto_sa = int(self._resolve_calibration_target_sa()) & 0xFF
            if auto_sa in self._calibration_temp_comp_samples_by_node:
                chosen_sa = auto_sa
            else:
                chosen_sa = sorted(self._calibration_temp_comp_samples_by_node.keys())[0]

        if chosen_sa is None:
            return None

        if not self._apply_calibration_temp_comp_node_samples(
            int(chosen_sa) & 0xFF,
            clear_coefficients=clear_coefficients,
        ):
            return None
        return int(chosen_sa) & 0xFF

    def _reset_calibration_temp_comp_state(
        self,
        *,
        clear_samples: bool,
        clear_coefficients: bool,
        clear_cached_nodes: bool = False,
    ):
        """Цель функции в безопасном сбросе сценария компенсации, затем она очищает runtime и при необходимости кэш узлов."""
        self._calibration_temp_comp_last_period = None
        self._calibration_temp_comp_last_temperature_x10 = None
        self._calibration_temp_comp_last_temperature_c = None

        if clear_samples:
            self._calibration_temp_comp_samples = []
            if clear_cached_nodes:
                self._calibration_temp_comp_samples_by_node = {}

        if clear_coefficients:
            self._calibration_temp_comp_k1_x100_current = None

        self._calibration_temp_comp_k1_x100_base = None
        self._calibration_temp_comp_k1_x100_recommended = None
        self._calibration_temp_comp_k1_x100_delta = None
        self._calibration_temp_comp_k1_x100_next = None
        self._calibration_temp_comp_period_slope_before = None
        self._calibration_temp_comp_period_slope_after = None
        self._calibration_temp_comp_level_slope_before = None
        self._calibration_temp_comp_level_slope_after = None
        self._calibration_temp_comp_period_reduction_percent = None
        self._calibration_temp_comp_level_reduction_percent = None
        self._calibration_temp_comp_chart_series = []

        self._recompute_calibration_temp_comp_metrics()

    def _request_calibration_runtime_snapshot(self):
        """Цель функции в опросе рабочего периода калибровки, затем она читает DID 0x0014 для отображения текущего значения."""
        if not self._can.is_connect or not self._can.is_trace:
            return
        self._configure_calibration_uds_services()
        tx_identifier = self._build_calibration_tx_identifier()
        self._calibration_read_service.read_data_by_identifier(tx_identifier, UdsData.curr_fuel_tank)

    def _request_calibration_temp_comp_k1_read(self) -> bool:
        """Цель функции в чтении текущего K1 через UDS, затем она отправляет запрос DID 0x001B в выбранный узел."""
        if not self._can.is_connect or not self._can.is_trace:
            return False
        self._configure_calibration_uds_services()
        return bool(
            self._calibration_read_service.read_data_by_identifier(
                self._build_calibration_tx_identifier(),
                UdsData.fuel_temp_comp_k1_x100,
            )
        )

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

        if (int(payload[1]) & 0xFF) == int(self._calibration_read_service.success_sid) and len(payload) >= 4:
            did = (int(payload[2]) << 8) | int(payload[3])
            raw_value = int(self._calibration_read_service.parse_data_field(payload))
            value = int(raw_value)
            changed = False
            emit_temp_comp_signal = False
            recompute_temp_comp = False

            if did == int(UdsData.curr_fuel_tank.pid):
                if self._calibration_current_level != value:
                    self._calibration_current_level = value
                    changed = True
                self._add_calibration_recent_sample(value)
                if self._calibration_temp_comp_last_period != value:
                    self._calibration_temp_comp_last_period = int(value)
                    emit_temp_comp_signal = True
            elif did == int(UdsData.empty_fuel_tank.pid):
                self._calibration_level_0 = value
                self._calibration_level_0_known = True
                changed = True
                recompute_temp_comp = True
                self._append_log(f"Калибровка: считан уровень 0% = {value}.", RowColor.green)
            elif did == int(UdsData.full_fuel_tank.pid):
                self._calibration_level_100 = value
                self._calibration_level_100_known = True
                changed = True
                recompute_temp_comp = True
                self._append_log(f"Калибровка: считан уровень 100% = {value}.", RowColor.green)
            elif did == int(UdsData.raw_temperature.pid):
                bits = max(8, int(UdsData.raw_temperature.size) * 8)
                signed_temperature = self._decode_signed_value(raw_value, bits)
                value = int(signed_temperature)
                self._calibration_temp_comp_last_temperature_x10 = int(signed_temperature)
                self._calibration_temp_comp_last_temperature_c = float(signed_temperature) / 10.0
                recompute_temp_comp = True
            elif did == int(UdsData.fuel_temp_comp_k1_x100.pid):
                bits = max(8, int(UdsData.fuel_temp_comp_k1_x100.size) * 8)
                signed_k1 = self._decode_signed_value(raw_value, bits)
                value = int(signed_k1)
                if self._calibration_temp_comp_k1_x100_current != signed_k1:
                    self._calibration_temp_comp_k1_x100_current = int(signed_k1)
                    self._append_log(f"Калибровка: считан коэффициент K1 = {int(signed_k1)}.", RowColor.green)
                recompute_temp_comp = True

            if self._calibration_sequence_waiting_action == "read_level_0" and did == int(UdsData.empty_fuel_tank.pid):
                self._finish_calibration_sequence_wait("read_level_0")
                self._schedule_calibration_sequence_action("read_level_100")
            elif self._calibration_sequence_waiting_action == "read_level_100" and did == int(UdsData.full_fuel_tank.pid):
                self._finish_calibration_sequence_wait("read_level_100")
                self._calibration_session_ready = True
                self._start_calibration_poll_timer()
                self._request_calibration_runtime_snapshot()
                self._request_calibration_temp_comp_k1_read()
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
            if recompute_temp_comp:
                self._recompute_calibration_temp_comp_metrics()
            elif emit_temp_comp_signal:
                self.calibrationTempCompChanged.emit()
            return

        if self._calibration_write_service.verify_answer_write_data(payload):
            did = int(self._calibration_write_service.parse_pid_field(payload))
            if did == int(UdsData.empty_fuel_tank.pid):
                self._append_log("Калибровка: уровень 0% успешно сохранен.", RowColor.green)
                self.readCalibrationLevel0()
            elif did == int(UdsData.full_fuel_tank.pid):
                self._append_log("Калибровка: уровень 100% успешно сохранен.", RowColor.green)
                self.readCalibrationLevel100()
            elif did == int(UdsData.fuel_temp_comp_k1_x100.pid):
                self._append_log("Калибровка: коэффициент K1 успешно сохранен.", RowColor.green)
                self._request_calibration_temp_comp_k1_read()

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

        merged_candidates = set(int(value) & 0xFF for value in self._observed_candidate_values)
        merged_candidates.update(int(value) & 0xFF for value in self._calibration_csv_node_candidates)

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

    @classmethod
    def _resolve_calibration_k1_write_value(cls, text, fallback_value: int | None) -> int:
        """Цель функции в удобном вводе K1 из UI, затем она парсит dec/hex и приводит значение к int16."""
        raw = str(text).strip()
        if not raw:
            if fallback_value is None:
                raise ValueError("Текущее значение K1 неизвестно. Сначала прочитайте DID 0x001B или введите число вручную.")
            return cls._saturate_int16(int(fallback_value))

        base = 16 if raw.lower().startswith(("0x", "-0x", "+0x")) else 10
        try:
            value = int(raw, base)
        except ValueError as exc:
            raise ValueError("Некорректное значение K1. Используйте signed dec или 0xHEX.") from exc

        if base == 16 and value >= 0:
            if value > 0xFFFF:
                raise ValueError("HEX-значение K1 должно быть в диапазоне 0x0000..0xFFFF.")
            if value > cls._INT16_MAX:
                value -= 0x10000

        if value < cls._INT16_MIN or value > cls._INT16_MAX:
            raise ValueError("Значение K1 вне диапазона int16 (-32768..32767).")

        return int(value)

