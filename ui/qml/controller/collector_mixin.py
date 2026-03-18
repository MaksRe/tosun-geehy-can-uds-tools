from __future__ import annotations

import csv
from copy import copy
from datetime import datetime
import logging
import math
from pathlib import Path
import time

from j1939.j1939_can_identifier import J1939CanIdentifier
from uds.data_identifiers import UdsData
from uds.services.read_data_by_id import ServiceReadDataById
from uds.uds_identifiers import UdsIdentifiers
from ui.qml.collector_csv_manager import CollectorCombinedCsvManager, CollectorCsvManager

from .contract import AppControllerContract


LOGGER = logging.getLogger(__name__)


class AppControllerCollectorMixin(AppControllerContract):
    def _set_collector_enabled_state(self, enabled: bool, *, emit_signal: bool = True):
        value = bool(enabled)
        if bool(self._collector_enabled) == value:
            return

        self._collector_enabled = value
        if value:
            self._collector_poll_timer.setInterval(
                self._collector_cycle_pause_ms if int(self._collector_poll_phase) == 0 else self._collector_poll_interval_ms
            )
            if not self._collector_poll_timer.isActive():
                self._collector_poll_timer.start()
        else:
            if self._collector_poll_timer.isActive():
                self._collector_poll_timer.stop()
            if self._collector_state != "stopped":
                self._collector_state = "stopped"
                self.collectorStateChanged.emit()
            self._collector_session_dir = None
            self._collector_csv_managers = {}
            self._collector_combined_csv_manager = None
            self._collector_nodes = {}
            self._collector_node_order = []
            self._collector_nodes_view = []
            self._collector_pending_requests = {}
            self._collector_last_request_monotonic = 0.0
            self._collector_error_logs = []
            self._collector_diagnostics_rate_limit = {}
            self._collector_poll_node_index = 0
            self._collector_poll_phase = 0
            self.collectorNodesChanged.emit()
            self.collectorDiagnosticsChanged.emit()
            self._reset_collector_trend()
            self._set_programming_active(False)

        if emit_signal:
            self.collectorEnabledChanged.emit()

    @staticmethod
    def _parse_collector_csv_number(raw_value: str) -> float | None:
        text = str(raw_value).strip().replace(" ", "")
        if not text:
            return None
        normalized = text.replace(",", ".")
        try:
            return float(normalized)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _decode_signed(raw_value: int, bits: int) -> int:
        width = max(1, int(bits))
        mask = (1 << width) - 1
        sign_bit = 1 << (width - 1)
        value = int(raw_value) & mask
        if value & sign_bit:
            return value - (1 << width)
        return value

    @staticmethod
    def _calc_fuel_from_period_x10(period_ticks: int, empty_ticks: int, full_ticks: int) -> int:
        delta = int(full_ticks) - int(empty_ticks)
        if delta <= 0:
            return 0
        numerator = (int(period_ticks) - int(empty_ticks)) * 1000
        return int(numerator / delta)

    def _recompute_collector_node_fuel_from_period(self, node: dict[str, object]):
        period_ticks = int(node.get("period", 0))
        empty_ticks = int(node.get("emptyPeriod", 0))
        full_ticks = int(node.get("fullPeriod", 0))
        fuel_x10 = self._calc_fuel_from_period_x10(period_ticks, empty_ticks, full_ticks)
        node["fuelLevelX10"] = int(fuel_x10)

    @staticmethod
    def _normalize_legacy_csv_temperature(temperature_c: float) -> tuple[float, bool]:
        value = float(temperature_c)
        # Legacy CSV files could store signed int16 raw temperature as unsigned tenths.
        # Example: 6553.5 means -0.1 C.
        if value > 3276.7:
            raw_u16 = int(round(value * 10.0)) & 0xFFFF
            signed_value = AppControllerCollectorMixin._decode_signed(raw_u16, 16)
            return (signed_value / 10.0, True)
        return (value, False)

    @staticmethod
    def _resolve_collector_csv_indexes(header: list[str]) -> dict[str, int]:
        idx_time = -1
        idx_temp = -1
        idx_fuel = -1

        for index, raw_name in enumerate(header):
            name = str(raw_name).strip().casefold()
            if not name:
                continue
            if idx_time < 0 and ("время" in name or "time" in name):
                idx_time = index
                continue
            if idx_temp < 0 and ("температ" in name or "temp" in name):
                idx_temp = index
                continue
            if idx_fuel < 0 and ("топлив" in name or "fuel" in name):
                idx_fuel = index
                continue

        if idx_temp < 0 or idx_fuel < 0:
            if len(header) >= 4:
                if idx_time < 0:
                    idx_time = 0
                idx_temp = 2 if idx_temp < 0 else idx_temp
                idx_fuel = 3 if idx_fuel < 0 else idx_fuel
            elif len(header) >= 3:
                idx_temp = 1 if idx_temp < 0 else idx_temp
                idx_fuel = 2 if idx_fuel < 0 else idx_fuel

        return {
            "time": idx_time,
            "temperature": idx_temp,
            "fuel": idx_fuel,
        }

    @staticmethod
    def _is_collector_csv_header_row(row: list[str]) -> bool:
        if len(row) == 0:
            return False
        joined = ";".join(str(value).strip() for value in row).casefold()
        has_time = ("время" in joined) or ("time" in joined)
        has_temp = ("температ" in joined) or ("temp" in joined)
        has_fuel = ("топлив" in joined) or ("fuel" in joined)
        return has_time and has_temp and has_fuel

    def _parse_collector_trend_csv_file(self, csv_path: Path) -> dict[str, object] | None:
        try:
            resolved_path = Path(csv_path).expanduser().resolve()
        except Exception:
            resolved_path = Path(csv_path)

        if not resolved_path.exists() or not resolved_path.is_file():
            return None

        points: list[dict[str, object]] = []
        legacy_temp_fix_count = 0
        try:
            with resolved_path.open("r", encoding="utf-8-sig", newline="") as file:
                reader = csv.reader(file, delimiter=";")
                header: list[str] | None = None
                indexes: dict[str, int] = {"time": -1, "temperature": -1, "fuel": -1}

                for row in reader:
                    normalized_row = [str(value).strip() for value in row]
                    if len(normalized_row) == 0:
                        continue
                    if not any(normalized_row):
                        continue

                    if header is None:
                        if not self._is_collector_csv_header_row(normalized_row):
                            continue
                        header = normalized_row
                        indexes = self._resolve_collector_csv_indexes(header)
                        continue

                    idx_temp = int(indexes.get("temperature", -1))
                    idx_fuel = int(indexes.get("fuel", -1))
                    if idx_temp < 0 or idx_fuel < 0:
                        continue
                    if idx_temp >= len(normalized_row) or idx_fuel >= len(normalized_row):
                        continue

                    temperature_value = self._parse_collector_csv_number(normalized_row[idx_temp])
                    fuel_value = self._parse_collector_csv_number(normalized_row[idx_fuel])
                    if temperature_value is None or fuel_value is None:
                        continue
                    normalized_temperature, was_fixed = self._normalize_legacy_csv_temperature(temperature_value)
                    if was_fixed:
                        legacy_temp_fix_count += 1

                    idx_time = int(indexes.get("time", -1))
                    if 0 <= idx_time < len(normalized_row):
                        time_text = normalized_row[idx_time]
                    else:
                        time_text = str(len(points) + 1)

                    points.append(
                        {
                            "fuel": float(fuel_value),
                            "temperature": float(normalized_temperature),
                            "time": str(time_text),
                        }
                    )
        except Exception as exc:
            LOGGER.exception("Ошибка чтения CSV %s: %s", resolved_path, exc)
            return None

        if len(points) == 0:
            return None

        node_text = f"CSV {resolved_path.stem}"
        return {
            "node": node_text,
            "nodeSa": -1,
            "count": len(points),
            "points": points,
            "path": str(resolved_path),
            "source": "csv",
            "legacyTemperatureCorrections": int(legacy_temp_fix_count),
        }
    @staticmethod
    def _resolve_project_root_directory() -> Path:
        try:
            return Path(__file__).resolve().parents[2]
        except Exception:
            return Path.cwd()

    def _apply_collector_output_directory(self, directory: Path, emit_signal: bool = True) -> bool:
        try:
            resolved = Path(directory).resolve()
            resolved.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False

        new_value = str(resolved)
        changed = self._collector_output_directory != new_value
        self._collector_output_directory = new_value
        if emit_signal and changed:
            self.collectorOutputDirectoryChanged.emit()
        return True

    @staticmethod
    def _extract_collector_node_sa(parsed_id: J1939CanIdentifier) -> int:
        node_sa = int(parsed_id.src) & 0xFF
        tester_sa = int(UdsIdentifiers.rx.dst) & 0xFF
        if node_sa == tester_sa:
            node_sa = int(parsed_id.dst) & 0xFF
        return node_sa

    def _ensure_collector_node(self, node_sa: int) -> dict[str, object]:
        normalized = int(node_sa) & 0xFF
        node = self._collector_nodes.get(normalized)
        if node is None:
            node = {
                "nodeSa": normalized,
                "period": 0,
                "fuelLevel": 0.0,
                "fuelLevelX10": 0,
                "emptyPeriod": 0,
                "fullPeriod": 0,
                "emptyKnown": False,
                "fullKnown": False,
                "temperature": 0.0,
                "temperatureKnown": False,
                "calibrationRefreshCountdown": int(self._collector_calibration_refresh_cycles),
                "calibrationRefreshPhase": 0,
                "timeoutStreak": 0,
                "nextPollAfter": 0.0,
                "fuelCount": 0,
                "temperatureCount": 0,
                "lastSeen": "-",
                "lastSeenMonotonic": time.monotonic(),
            }
            self._collector_nodes[normalized] = node
            if normalized not in self._collector_node_order:
                self._collector_node_order.append(normalized)
        return node

    def _collector_node_stale_timeout_sec(self) -> float:
        nodes_count = max(1, len(self._collector_node_order))
        # Fast poll vars + occasional refresh of calibration DIDs.
        vars_count = max(1, len(self._collector_poll_vars)) + 2
        cycle_estimate_sec = (
            (float(self._collector_poll_interval_ms) * float(vars_count)) + float(self._collector_cycle_pause_ms)
        ) * nodes_count / 1000.0
        return max(6.0, cycle_estimate_sec * 2.5)

    def _collector_effective_poll_interval_ms(self, nodes_count: int) -> int:
        base_interval = max(30, int(self._collector_poll_interval_ms))
        normalized_nodes = max(1, int(nodes_count))
        if normalized_nodes <= 1:
            return base_interval
        # Keep full per-node fast update round under ~2.5s as node count grows.
        adaptive_interval = max(40, int(2500 / normalized_nodes))
        return min(base_interval, adaptive_interval)

    @staticmethod
    def _collector_did_name(did: int) -> str:
        normalized = int(did) & 0xFFFF
        labels = {
            int(UdsData.curr_fuel_tank.pid) & 0xFFFF: "curr_fuel_tank",
            int(UdsData.empty_fuel_tank.pid) & 0xFFFF: "empty_fuel_tank",
            int(UdsData.full_fuel_tank.pid) & 0xFFFF: "full_fuel_tank",
            int(UdsData.raw_temperature.pid) & 0xFFFF: "raw_temperature",
            int(UdsData.raw_fuel_level.pid) & 0xFFFF: "raw_fuel_level",
        }
        return labels.get(normalized, f"DID_0x{normalized:04X}")

    def _collector_append_error_log(
        self,
        message: str,
        *,
        node_sa: int | None = None,
        did: int | None = None,
        dedup_key: str | None = None,
        min_repeat_sec: float = 1.5,
    ):
        now = time.monotonic()
        key = str(dedup_key) if dedup_key else str(message)
        last_emit = float(self._collector_diagnostics_rate_limit.get(key, 0.0))
        if (now - last_emit) < max(0.0, float(min_repeat_sec)):
            return
        self._collector_diagnostics_rate_limit[key] = now

        row = {
            "time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "node": "-" if node_sa is None else f"0x{int(node_sa) & 0xFF:02X}",
            "did": "-" if did is None else f"0x{int(did) & 0xFFFF:04X}",
            "message": str(message),
        }
        self._collector_error_logs.append(row)
        if len(self._collector_error_logs) > int(self._collector_error_log_limit):
            self._collector_error_logs = self._collector_error_logs[-int(self._collector_error_log_limit):]
        self.collectorDiagnosticsChanged.emit()

    def _collector_request_timeout_sec(self, nodes_count: int) -> float:
        configured_timeout = max(0.2, float(self._collector_pending_timeout_ms) / 1000.0)
        adaptive = max(0.6, float(self._collector_effective_poll_interval_ms(nodes_count)) * 4.0 / 1000.0)
        return max(configured_timeout, adaptive)

    def _collector_register_pending_request(self, node_sa: int, did: int, *, timeout_sec: float):
        key = (int(node_sa) & 0xFF, int(did) & 0xFFFF)
        now = time.monotonic()
        existing = self._collector_pending_requests.get(key)
        if isinstance(existing, dict):
            sent_at = float(existing.get("sent_at", 0.0))
            if sent_at > 0.0 and (now - sent_at) > timeout_sec:
                self._collector_append_error_log(
                    (
                        f"Таймаут ожидания ответа 0x62/0x7F для {self._collector_did_name(key[1])} "
                        f"(узел 0x{key[0]:02X}, DID 0x{key[1]:04X}). Возможна перегрузка шины или проигрыш арбитража CAN."
                    ),
                    node_sa=key[0],
                    did=key[1],
                    dedup_key=f"collector_timeout_resend_{key[0]:02X}_{key[1]:04X}",
                    min_repeat_sec=2.0,
                )
        self._collector_pending_requests[key] = {
            "sent_at": now,
            "timeout_sec": float(timeout_sec),
        }

    def _collector_resolve_pending_response_did(self, node_sa: int, did_hint: int | None = None) -> int | None:
        normalized_sa = int(node_sa) & 0xFF
        if did_hint is not None:
            normalized_did = int(did_hint) & 0xFFFF
            key = (normalized_sa, normalized_did)
            if key in self._collector_pending_requests:
                self._collector_pending_requests.pop(key, None)
                return normalized_did

        oldest_key: tuple[int, int] | None = None
        oldest_sent_at = 0.0
        for key, entry in self._collector_pending_requests.items():
            if key[0] != normalized_sa:
                continue
            sent_at = float(entry.get("sent_at", 0.0)) if isinstance(entry, dict) else 0.0
            if oldest_key is None or sent_at < oldest_sent_at:
                oldest_key = key
                oldest_sent_at = sent_at

        if oldest_key is None:
            return None
        self._collector_pending_requests.pop(oldest_key, None)
        return int(oldest_key[1]) & 0xFFFF

    def _collector_cleanup_pending_requests(self, *, timeout_sec: float):
        now = time.monotonic()
        expired: list[tuple[int, int]] = []
        for key, entry in self._collector_pending_requests.items():
            sent_at = float(entry.get("sent_at", 0.0)) if isinstance(entry, dict) else 0.0
            if sent_at <= 0.0:
                continue
            if (now - sent_at) >= float(timeout_sec):
                expired.append(key)

        for node_sa, did in expired:
            self._collector_pending_requests.pop((node_sa, did), None)
            node = self._collector_nodes.get(int(node_sa) & 0xFF)
            if isinstance(node, dict):
                try:
                    streak = int(node.get("timeoutStreak", 0))
                except (TypeError, ValueError):
                    streak = 0
                streak = min(max(0, streak) + 1, 8)
                node["timeoutStreak"] = streak
                node["nextPollAfter"] = now + min(2.0, 0.08 * (2 ** (streak - 1)))
            self._collector_append_error_log(
                (
                    f"Нет ответа на UDS-запрос {self._collector_did_name(did)} "
                    f"(узел 0x{int(node_sa) & 0xFF:02X}, DID 0x{int(did) & 0xFFFF:04X}). "
                    "Вероятно высокая загрузка шины/арбитраж CAN, либо узел не отвечает."
                ),
                node_sa=node_sa,
                did=did,
                dedup_key=f"collector_timeout_{int(node_sa) & 0xFF:02X}_{int(did) & 0xFFFF:04X}",
                min_repeat_sec=2.0,
            )

    def _prune_collector_inactive_nodes(self):
        if len(self._collector_node_order) == 0:
            return

        now_monotonic = time.monotonic()
        timeout_sec = self._collector_node_stale_timeout_sec()
        kept_nodes: list[int] = []
        removed_nodes: list[int] = []

        for node_sa in self._collector_node_order:
            node = self._collector_nodes.get(node_sa)
            if node is None:
                continue
            try:
                last_seen_monotonic = float(node.get("lastSeenMonotonic", 0.0))
            except (TypeError, ValueError):
                last_seen_monotonic = 0.0

            if last_seen_monotonic <= 0.0 or (now_monotonic - last_seen_monotonic) > timeout_sec:
                removed_nodes.append(int(node_sa) & 0xFF)
            else:
                kept_nodes.append(int(node_sa) & 0xFF)

        if len(removed_nodes) == 0:
            return

        removed_set = {int(node_sa) & 0xFF for node_sa in removed_nodes}
        for node_sa in removed_set:
            self._collector_nodes.pop(node_sa, None)
            self._collector_trend_points_by_node.pop(node_sa, None)
        if len(removed_set) > 0 and len(self._collector_pending_requests) > 0:
            pending_keys = list(self._collector_pending_requests.keys())
            for key in pending_keys:
                if int(key[0]) & 0xFF in removed_set:
                    self._collector_pending_requests.pop(key, None)

        self._collector_node_order = [node_sa for node_sa in kept_nodes if node_sa not in removed_set]
        if len(self._collector_node_order) == 0:
            self._collector_poll_node_index = 0
            self._collector_poll_phase = 0
        else:
            self._collector_poll_node_index %= len(self._collector_node_order)

        self._schedule_collector_views_update(nodes=True, trend=True)
    @staticmethod
    def _calc_series_stats(values: list[float]) -> dict[str, float]:
        if len(values) == 0:
            return {
                "last": 0.0,
                "min": 0.0,
                "max": 0.0,
                "mean": 0.0,
                "std": 0.0,
                "span": 0.0,
                "delta": 0.0,
            }

        normalized = [float(v) for v in values]
        count = len(normalized)
        minimum = min(normalized)
        maximum = max(normalized)
        mean = sum(normalized) / float(count)
        variance = 0.0
        for value in normalized:
            variance += (value - mean) ** 2
        variance /= float(count)
        std = math.sqrt(variance)
        delta = normalized[-1] - normalized[-2] if count > 1 else 0.0
        return {
            "last": normalized[-1],
            "min": minimum,
            "max": maximum,
            "mean": mean,
            "std": std,
            "span": maximum - minimum,
            "delta": delta,
        }

    @staticmethod
    def _calc_point_key_stats(points: list[dict[str, object]], key: str) -> dict[str, float]:
        if len(points) == 0:
            return {
                "last": 0.0,
                "min": 0.0,
                "max": 0.0,
                "mean": 0.0,
                "std": 0.0,
                "span": 0.0,
                "delta": 0.0,
            }

        count = 0
        minimum = 0.0
        maximum = 0.0
        mean = 0.0
        m2 = 0.0
        last = 0.0
        prev = 0.0

        for point in points:
            raw_value = point.get(key, 0.0)
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                value = 0.0

            if count == 0:
                minimum = value
                maximum = value
            else:
                minimum = min(minimum, value)
                maximum = max(maximum, value)

            count += 1
            delta = value - mean
            mean += delta / float(count)
            delta2 = value - mean
            m2 += delta * delta2

            prev = last
            last = value

        variance = (m2 / float(count)) if count > 0 else 0.0
        std = math.sqrt(max(0.0, variance))
        delta_value = (last - prev) if count > 1 else 0.0
        return {
            "last": last,
            "min": minimum,
            "max": maximum,
            "mean": mean,
            "std": std,
            "span": maximum - minimum,
            "delta": delta_value,
        }

    def _schedule_collector_views_update(self, *, nodes: bool = False, trend: bool = False):
        if nodes:
            self._collector_view_update_pending_nodes = True
        if trend and bool(self._collector_trend_enabled):
            self._collector_view_update_pending_trend = True

        if self._collector_view_update_pending_nodes or self._collector_view_update_pending_trend:
            if not self._collector_view_update_timer.isActive():
                self._collector_view_update_timer.start()

    def _flush_collector_views_update(self):
        emit_nodes = self._collector_view_update_pending_nodes
        emit_trend = self._collector_view_update_pending_trend

        self._collector_view_update_pending_nodes = False
        self._collector_view_update_pending_trend = False

        if emit_nodes:
            self._refresh_collector_nodes_view()

        if emit_trend:
            self._rebuild_collector_trend_views()
            self.collectorTrendChanged.emit()

    def _rebuild_collector_trend_views(self):
        entries: list[dict[str, object]] = []
        for node_sa in self._collector_node_order:
            normalized_sa = int(node_sa) & 0xFF
            points = self._collector_trend_points_by_node.get(normalized_sa, [])
            node = self._collector_nodes.get(normalized_sa, {})

            if len(points) == 0:
                fallback_fuel = float(node.get("fuelLevel", 0.0))
                fallback_temp = float(node.get("temperature", 0.0))
                fallback_time = str(node.get("lastSeen", "-"))
                points = [{"fuel": fallback_fuel, "temperature": fallback_temp, "time": fallback_time}]

            fuel_stats = self._calc_point_key_stats(points, "fuel")
            temp_stats = self._calc_point_key_stats(points, "temperature")

            latest_time = str(points[-1].get("time", "-"))
            fuel_error_pct = abs(fuel_stats["std"] / fuel_stats["mean"] * 100.0) if abs(fuel_stats["mean"]) > 1e-9 else 0.0
            temp_error_pct = abs(temp_stats["std"] / temp_stats["mean"] * 100.0) if abs(temp_stats["mean"]) > 1e-9 else 0.0

            entries.append(
                {
                    "nodeSa": normalized_sa,
                    "node": f"0x{normalized_sa:02X}",
                    "points": points,
                    "count": len(points),
                    "latestTime": latest_time,
                    "latestFuel": float(fuel_stats["last"]),
                    "latestTemperature": float(temp_stats["last"]),
                    "fuelMin": float(fuel_stats["min"]),
                    "fuelMax": float(fuel_stats["max"]),
                    "fuelMean": float(fuel_stats["mean"]),
                    "fuelStd": float(fuel_stats["std"]),
                    "fuelSpan": float(fuel_stats["span"]),
                    "fuelDelta": float(fuel_stats["delta"]),
                    "fuelErrorPct": float(fuel_error_pct),
                    "temperatureMin": float(temp_stats["min"]),
                    "temperatureMax": float(temp_stats["max"]),
                    "temperatureMean": float(temp_stats["mean"]),
                    "temperatureStd": float(temp_stats["std"]),
                    "temperatureSpan": float(temp_stats["span"]),
                    "temperatureDelta": float(temp_stats["delta"]),
                    "temperatureErrorPct": float(temp_error_pct),
                    "fuelDeviationFromNetwork": 0.0,
                    "temperatureDeviationFromNetwork": 0.0,
                    "fuelDivergencePct": 0.0,
                    "temperatureDivergencePct": 0.0,
                }
            )

        latest_fuel_values = [float(item.get("latestFuel", 0.0)) for item in entries]
        latest_temp_values = [float(item.get("latestTemperature", 0.0)) for item in entries]
        fuel_network = self._calc_series_stats(latest_fuel_values)
        temp_network = self._calc_series_stats(latest_temp_values)
        fuel_mean = float(fuel_network["mean"])
        temp_mean = float(temp_network["mean"])
        fuel_spread = float(fuel_network["span"])
        temp_spread = float(temp_network["span"])

        for item in entries:
            fuel_dev = float(item.get("latestFuel", 0.0)) - fuel_mean
            temp_dev = float(item.get("latestTemperature", 0.0)) - temp_mean
            item["fuelDeviationFromNetwork"] = fuel_dev
            item["temperatureDeviationFromNetwork"] = temp_dev
            item["fuelDivergencePct"] = abs(fuel_dev / fuel_mean * 100.0) if abs(fuel_mean) > 1e-9 else 0.0
            item["temperatureDivergencePct"] = abs(temp_dev / temp_mean * 100.0) if abs(temp_mean) > 1e-9 else 0.0

        metrics_rows: list[dict[str, str]] = []
        for item in entries:
            metrics_rows.append(
                {
                    "node": str(item.get("node", "")),
                    "deltaFuel": f"{float(item.get('fuelDelta', 0.0)):+.2f}",
                    "deltaTemperature": f"{float(item.get('temperatureDelta', 0.0)):+.2f}",
                    "devFuel": f"{float(item.get('fuelDeviationFromNetwork', 0.0)):+.2f}",
                    "devTemperature": f"{float(item.get('temperatureDeviationFromNetwork', 0.0)):+.2f}",
                    "errFuel": f"{float(item.get('fuelErrorPct', 0.0)):.2f}%",
                    "errTemperature": f"{float(item.get('temperatureErrorPct', 0.0)):.2f}%",
                    "divFuel": f"{float(item.get('fuelDivergencePct', 0.0)):.2f}%",
                    "divTemperature": f"{float(item.get('temperatureDivergencePct', 0.0)):.2f}%",
                }
            )

        self._collector_trend_nodes_view = entries
        self._collector_trend_metrics_rows = metrics_rows
        self._collector_trend_network_metrics = {
            "nodesCount": len(entries),
            "fuelMean": fuel_mean,
            "temperatureMean": temp_mean,
            "fuelSpread": fuel_spread,
            "temperatureSpread": temp_spread,
            "fuelStd": float(fuel_network["std"]),
            "temperatureStd": float(temp_network["std"]),
        }

    def _append_collector_trend_sample(self, node_sa: int, node: dict[str, object], timestamp: str):
        if not bool(self._collector_trend_enabled):
            return

        normalized_sa = int(node_sa) & 0xFF
        fuel = float(node.get("fuelLevel", 0))
        temperature = float(node.get("temperature", 0.0))
        sample = {
            "fuel": fuel,
            "temperature": temperature,
            "node": f"0x{normalized_sa:02X}",
            "time": str(timestamp),
        }
        points = self._collector_trend_points
        points.append(sample)
        if len(points) > self._collector_trend_max_points:
            del points[: len(points) - self._collector_trend_max_points]

        node_points = self._collector_trend_points_by_node.get(normalized_sa)
        if node_points is None:
            node_points = []
            self._collector_trend_points_by_node[normalized_sa] = node_points
        node_points.append(sample)
        if self._collector_trend_history_limit > 0 and len(node_points) > self._collector_trend_history_limit:
            keep_tail = max(1, int(self._collector_trend_history_limit // 2))
            if keep_tail < len(node_points):
                head = node_points[:-keep_tail]
                tail = node_points[-keep_tail:]
                # Thin older half to preserve the full-period trend with bounded RAM.
                thinned_head = head[::2] if len(head) > 1 else head
                node_points[:] = thinned_head + tail
            if len(node_points) > self._collector_trend_history_limit:
                del node_points[: len(node_points) - self._collector_trend_history_limit]

        self._collector_trend_caption = f"Узел {sample['node']} | Последнее обновление: {sample['time']}"
        self._collector_trend_latest_fuel = fuel
        self._collector_trend_latest_temperature = temperature
        self._schedule_collector_views_update(trend=True)

    def _reset_collector_trend(self):
        if self._collector_view_update_timer.isActive():
            self._collector_view_update_timer.stop()
        self._collector_view_update_pending_nodes = False
        self._collector_view_update_pending_trend = False
        self._collector_trend_points = []
        self._collector_trend_points_by_node = {}
        self._collector_trend_nodes_view = []
        self._collector_trend_metrics_rows = []
        self._collector_trend_network_metrics = {
            "nodesCount": 0,
            "fuelMean": 0.0,
            "temperatureMean": 0.0,
            "fuelSpread": 0.0,
            "temperatureSpread": 0.0,
            "fuelStd": 0.0,
            "temperatureStd": 0.0,
        }
        self._collector_trend_caption = "Ожидание данных от узлов..."
        self._collector_trend_latest_fuel = 0.0
        self._collector_trend_latest_temperature = 0.0
        self.collectorTrendChanged.emit()

    def _refresh_collector_nodes_view(self):
        rows: list[dict[str, str]] = []
        for node_sa in self._collector_node_order:
            node = self._collector_nodes.get(node_sa)
            if not node:
                continue
            rows.append(
                {
                    "node": f"0x{int(node_sa) & 0xFF:02X}",
                    "period": str(int(node.get("period", 0))),
                    "fuelLevel": f"{float(node.get('fuelLevel', 0.0)):.1f}",
                    "temperature": f"{float(node.get('temperature', 0.0)):.1f}",
                    "fuelCount": str(int(node.get("fuelCount", 0))),
                    "temperatureCount": str(int(node.get("temperatureCount", 0))),
                    "lastSeen": str(node.get("lastSeen", "-")),
                }
            )
        self._collector_nodes_view = rows
        self.collectorNodesChanged.emit()

    def _append_collector_csv(self, node_sa: int, node: dict[str, object], timestamp: str):
        if (not self._collector_enabled) or self._collector_state != "recording" or self._collector_session_dir is None:
            return
        if not bool(node.get("temperatureKnown", False)):
            return
        manager = self._collector_csv_managers.get(node_sa)
        if manager is None:
            manager = CollectorCsvManager(f"0x{int(node_sa) & 0xFF:02X}", self._collector_session_dir)
            self._collector_csv_managers[node_sa] = manager
        manager.append_metric(
            measurement_time=str(timestamp),
            period_ticks=int(node.get("period", 0)),
            temperature_c=float(node.get("temperature", 0.0)),
            fuel_percent=float(node.get("fuelLevel", 0.0)),
            fuel_from_period_x10=int(node.get("fuelLevelX10", int(round(float(node.get("fuelLevel", 0.0)) * 10.0)))),
            empty_ticks=int(node.get("emptyPeriod", 0)),
            full_ticks=int(node.get("fullPeriod", 0)),
            empty_known=bool(node.get("emptyKnown", False)),
            full_known=bool(node.get("fullKnown", False)),
        )
        self._append_collector_combined_csv(timestamp)

    def _collector_snapshot_for_combined_csv(self) -> dict[str, dict[str, object]]:
        snapshot: dict[str, dict[str, object]] = {}
        for node_sa in self._collector_node_order:
            node = self._collector_nodes.get(node_sa)
            if not isinstance(node, dict):
                continue
            node_hex = f"0x{int(node_sa) & 0xFF:02X}".lower()
            snapshot[node_hex] = {
                "period": int(node.get("period", 0)),
                "fuel": float(node.get("fuelLevel", 0.0)),
                "temperature": float(node.get("temperature", 0.0)),
                "fuelPeriodX10": int(node.get("fuelLevelX10", int(round(float(node.get("fuelLevel", 0.0)) * 10.0)))),
                "emptyPeriod": int(node.get("emptyPeriod", 0)),
                "fullPeriod": int(node.get("fullPeriod", 0)),
                "emptyKnown": bool(node.get("emptyKnown", False)),
                "fullKnown": bool(node.get("fullKnown", False)),
            }
        return snapshot

    def _append_collector_combined_csv(self, timestamp: str):
        manager: CollectorCombinedCsvManager | None = self._collector_combined_csv_manager
        if manager is None:
            return
        snapshot = self._collector_snapshot_for_combined_csv()
        if len(snapshot) == 0:
            return
        manager.append_snapshot(
            measurement_time=str(timestamp),
            nodes_snapshot=snapshot,
        )

    def _handle_collector_frame(self, timestamp: str, parsed_id: J1939CanIdentifier, payload: list[int]):
        if not self._collector_enabled:
            return

        node_sa = self._extract_collector_node_sa(parsed_id)
        tester_sa = int(UdsIdentifiers.rx.dst) & 0xFF
        if node_sa == tester_sa:
            return

        was_new_node = int(node_sa) not in self._collector_nodes
        node = self._ensure_collector_node(node_sa)
        nodes_changed = was_new_node
        node["lastSeenMonotonic"] = time.monotonic()
        new_last_seen = timestamp[:8] if len(timestamp) >= 8 else timestamp
        if str(node.get("lastSeen", "")) != new_last_seen:
            node["lastSeen"] = new_last_seen
            nodes_changed = True

        pgn = int(parsed_id.pgn) & 0x3FFFF
        if pgn != (int(UdsIdentifiers.rx.pgn) & 0x3FFFF):
            if nodes_changed:
                self._schedule_collector_views_update(nodes=True, trend=was_new_node)
            return

        if len(payload) < 2:
            if nodes_changed:
                self._schedule_collector_views_update(nodes=True, trend=was_new_node)
            return

        sid = int(payload[1]) & 0xFF
        if sid == 0x7F:
            original_sid = int(payload[2]) & 0xFF if len(payload) > 2 else 0
            nrc = int(payload[3]) & 0xFF if len(payload) > 3 else 0
            nrc_text = self._uds_nrc_description(nrc)
            pending_did = self._collector_resolve_pending_response_did(node_sa, None)
            self._collector_append_error_log(
                (
                    f"Негативный ответ UDS: SID 0x{original_sid:02X}, NRC 0x{nrc:02X} ({nrc_text}). "
                    f"Ожидался ответ по {self._collector_did_name(pending_did) if pending_did is not None else 'запросу коллектора'}."
                ),
                node_sa=node_sa,
                did=pending_did,
                dedup_key=f"collector_nrc_{int(node_sa) & 0xFF:02X}_{original_sid:02X}_{nrc:02X}_{pending_did if pending_did is not None else 0:04X}",
                min_repeat_sec=1.2,
            )
            if nodes_changed:
                self._schedule_collector_views_update(nodes=True, trend=was_new_node)
            return

        if sid != self._collector_read_service.success_sid:
            pending_did = self._collector_resolve_pending_response_did(node_sa, None)
            self._collector_append_error_log(
                f"Неожиданный SID ответа 0x{sid:02X} для запроса коллектора.",
                node_sa=node_sa,
                did=pending_did,
                dedup_key=f"collector_sid_{int(node_sa) & 0xFF:02X}_{sid:02X}_{pending_did if pending_did is not None else 0:04X}",
                min_repeat_sec=1.2,
            )
            if nodes_changed:
                self._schedule_collector_views_update(nodes=True, trend=was_new_node)
            return

        if len(payload) < 4:
            pending_did = self._collector_resolve_pending_response_did(node_sa, None)
            self._collector_append_error_log(
                "Короткий ответ UDS на запрос коллектора (меньше 4 байт payload).",
                node_sa=node_sa,
                did=pending_did,
                dedup_key=f"collector_short_{int(node_sa) & 0xFF:02X}_{pending_did if pending_did is not None else 0:04X}",
                min_repeat_sec=1.2,
            )
            if nodes_changed:
                self._schedule_collector_views_update(nodes=True, trend=was_new_node)
            return

        try:
            did = int(self._collector_read_service.parse_did_field(payload)) & 0xFFFF
            value = int(ServiceReadDataById.parse_data_field(payload))
        except Exception:
            pending_did = self._collector_resolve_pending_response_did(node_sa, None)
            self._collector_append_error_log(
                "Не удалось разобрать ответ 0x62 (DID/данные).",
                node_sa=node_sa,
                did=pending_did,
                dedup_key=f"collector_parse_{int(node_sa) & 0xFF:02X}_{pending_did if pending_did is not None else 0:04X}",
                min_repeat_sec=1.2,
            )
            if nodes_changed:
                self._schedule_collector_views_update(nodes=True, trend=was_new_node)
            return

        self._collector_resolve_pending_response_did(node_sa, int(did) & 0xFFFF)
        if isinstance(node, dict):
            node["timeoutStreak"] = 0
            node["nextPollAfter"] = 0.0
        has_trend_update = False

        if did == int(UdsData.curr_fuel_tank.pid):
            node["period"] = value
            self._recompute_collector_node_fuel_from_period(node)
            node["fuelCount"] = int(node.get("fuelCount", 0)) + 1
            self._append_collector_csv(node_sa, node, timestamp)
            has_trend_update = True
            nodes_changed = True
        elif did == int(UdsData.empty_fuel_tank.pid):
            if int(node.get("emptyPeriod", 0)) != int(value):
                node["emptyPeriod"] = value
                self._recompute_collector_node_fuel_from_period(node)
                nodes_changed = True
            if not bool(node.get("emptyKnown", False)):
                node["emptyKnown"] = True
                nodes_changed = True
        elif did == int(UdsData.full_fuel_tank.pid):
            if int(node.get("fullPeriod", 0)) != int(value):
                node["fullPeriod"] = value
                self._recompute_collector_node_fuel_from_period(node)
                nodes_changed = True
            if not bool(node.get("fullKnown", False)):
                node["fullKnown"] = True
                nodes_changed = True
        elif did == int(UdsData.raw_fuel_level.pid):
            # Keep value for diagnostics only. Main trend/PNG/CSV fuel now comes from period-based formula.
            node["fuelLevelReported"] = value / 10.0
            nodes_changed = True
        elif did == int(UdsData.raw_temperature.pid):
            bits = max(8, int(UdsData.raw_temperature.size) * 8)
            signed_value = self._decode_signed(value, bits)
            temperature = signed_value / 10.0
            node["temperature"] = temperature
            node["temperatureKnown"] = True
            node["temperatureCount"] = int(node.get("temperatureCount", 0)) + 1
            self._append_collector_csv(node_sa, node, timestamp)
            has_trend_update = True
            nodes_changed = True

        if has_trend_update:
            self._append_collector_trend_sample(node_sa, node, str(node.get("lastSeen", "-")))

        if nodes_changed:
            self._schedule_collector_views_update(nodes=True, trend=was_new_node)

    def _on_collector_poll_tick(self):
        if not self._collector_enabled:
            if self._collector_poll_timer.isActive():
                self._collector_poll_timer.stop()
            return
        if not self._can.is_connect:
            return
        if self._source_address_busy:
            return

        self._prune_collector_inactive_nodes()

        if len(self._collector_poll_vars) == 0:
            return

        nodes = list(self._collector_node_order)
        if len(nodes) == 0:
            return

        effective_poll_interval = self._collector_effective_poll_interval_ms(len(nodes))
        timeout_sec = self._collector_request_timeout_sec(len(nodes))
        self._collector_cleanup_pending_requests(timeout_sec=timeout_sec)
        max_pending = max(1, int(self._collector_max_pending_requests))
        if len(self._collector_pending_requests) >= max_pending:
            self._collector_poll_timer.setInterval(max(30, min(90, effective_poll_interval)))
            return

        self._collector_poll_node_index %= len(nodes)
        poll_vars_count = len(self._collector_poll_vars)
        self._collector_poll_phase %= poll_vars_count

        pending_nodes = {int(key[0]) & 0xFF for key in self._collector_pending_requests.keys()}
        selected_index = -1
        now = time.monotonic()
        for offset in range(len(nodes)):
            idx = (self._collector_poll_node_index + offset) % len(nodes)
            candidate_sa = int(nodes[idx]) & 0xFF
            if candidate_sa in pending_nodes:
                continue
            candidate_node = self._collector_nodes.get(candidate_sa)
            next_allowed = 0.0
            if isinstance(candidate_node, dict):
                try:
                    next_allowed = float(candidate_node.get("nextPollAfter", 0.0))
                except (TypeError, ValueError):
                    next_allowed = 0.0
            if next_allowed > now:
                continue
            selected_index = idx
            break

        if selected_index < 0:
            self._collector_poll_timer.setInterval(max(30, min(90, effective_poll_interval)))
            return

        self._collector_poll_node_index = selected_index
        node_sa = int(nodes[self._collector_poll_node_index]) & 0xFF
        node = self._collector_nodes.get(node_sa)
        use_fast_schedule = True
        poll_var = None

        if isinstance(node, dict):
            if not bool(node.get("emptyKnown", False)):
                poll_var = UdsData.empty_fuel_tank
                use_fast_schedule = False
            elif not bool(node.get("fullKnown", False)):
                poll_var = UdsData.full_fuel_tank
                use_fast_schedule = False
            else:
                try:
                    refresh_countdown = int(node.get("calibrationRefreshCountdown", self._collector_calibration_refresh_cycles))
                except (TypeError, ValueError):
                    refresh_countdown = int(self._collector_calibration_refresh_cycles)

                if refresh_countdown <= 0:
                    try:
                        refresh_phase = int(node.get("calibrationRefreshPhase", 0)) & 0x01
                    except (TypeError, ValueError):
                        refresh_phase = 0
                    poll_var = UdsData.empty_fuel_tank if refresh_phase == 0 else UdsData.full_fuel_tank
                    node["calibrationRefreshPhase"] = (refresh_phase + 1) % 2
                    node["calibrationRefreshCountdown"] = int(self._collector_calibration_refresh_cycles)
                    use_fast_schedule = False
                else:
                    node["calibrationRefreshCountdown"] = refresh_countdown - 1

        if poll_var is None:
            poll_var = self._collector_poll_vars[self._collector_poll_phase]

        min_gap_sec = max(0.0, float(self._collector_min_inter_request_ms) / 1000.0)
        try:
            last_tx = float(self._collector_last_request_monotonic)
        except (TypeError, ValueError):
            last_tx = 0.0
        if last_tx > 0.0:
            since_last = time.monotonic() - last_tx
            if since_last < min_gap_sec:
                self._collector_poll_timer.setInterval(max(30, int((min_gap_sec - since_last) * 1000.0)))
                return

        tx_identifier = copy(UdsIdentifiers.tx)
        tx_identifier.dst = node_sa
        self._collector_read_service.read_data_by_identifier(tx_identifier.identifier, poll_var)
        self._collector_last_request_monotonic = time.monotonic()
        try:
            did_value = int(poll_var.pid) & 0xFFFF
            self._collector_register_pending_request(node_sa, did_value, timeout_sec=timeout_sec)
        except Exception:
            self._collector_append_error_log(
                "Не удалось зарегистрировать ожидаемый ответ коллектора (невалидный DID).",
                node_sa=node_sa,
                dedup_key=f"collector_pending_register_{int(node_sa) & 0xFF:02X}",
                min_repeat_sec=2.0,
            )

        if not use_fast_schedule:
            self._collector_poll_node_index = (self._collector_poll_node_index + 1) % len(nodes)
            self._collector_poll_timer.setInterval(effective_poll_interval)
            return

        next_phase = (self._collector_poll_phase + 1) % poll_vars_count
        self._collector_poll_phase = next_phase
        if next_phase != 0:
            self._collector_poll_timer.setInterval(effective_poll_interval)
        else:
            self._collector_poll_node_index = (self._collector_poll_node_index + 1) % len(nodes)
            pause_interval = max(30, min(int(self._collector_cycle_pause_ms), effective_poll_interval * 2))
            self._collector_poll_timer.setInterval(pause_interval)

