from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer

from app_can.CanDevice import CanDevice
from uds.bootloader import Bootloader
from uds.data_identifiers import UdsData
from uds.options_catalog import UDS_OPTIONS, UdsOptionParameter
from uds.services.ecu_reset import ServiceEcuReset
from uds.services.read_data_by_id import ServiceReadDataById
from uds.services.security_access import ServiceSecurityAccess
from uds.services.session import ServiceSession
from uds.services.write_data_by_id import ServiceWriteDataById
from uds.uds_identifiers import UdsIdentifiers
from ui.qml.collector_csv_manager import CollectorCombinedCsvManager, CollectorCsvManager

from .controller import (
    AppControllerCalibrationMixin,
    AppControllerCanMixin,
    AppControllerCollectorMixin,
    AppControllerOptionsMixin,
    AppControllerPropertiesMixin,
    AppControllerPublicSlotsMixin,
    AppControllerRuntimeMixin,
    FirmwareLoadWorker,
)


class AppController(
    AppControllerPropertiesMixin,
    AppControllerPublicSlotsMixin,
    AppControllerOptionsMixin,
    AppControllerCalibrationMixin,
    AppControllerCollectorMixin,
    AppControllerCanMixin,
    AppControllerRuntimeMixin,
    QObject,
):
    CAN_FILTER_FIELDS = ("time", "dir", "frameId", "pgn", "src", "dst", "j1939", "dlc", "uds", "data")


    def __init__(self):
        super().__init__()

        self._can = CanDevice.instance()
        self._bootloader = Bootloader()
        self._bootloader.set_transfer_byte_order("big")
        self._ui_ecu_reset_service = ServiceEcuReset()

        # Display labels for ComboBox and actual hardware indexes from TSCAN.
        self._devices: list[str] = []
        self._device_indices: list[int] = []
        self._selected_device_index = -1

        self._manufacturer = ""
        self._product = ""
        self._serial = ""
        self._device_handle = ""

        self._firmware_path = ""
        self._firmware = None
        self._progress_value = 0
        self._progress_max = 1

        self._logs: list[dict[str, str]] = []
        self._can_traffic_logs: list[dict[str, str]] = []
        self._filtered_can_traffic_logs: list[dict[str, str]] = []
        self._can_filter_values: dict[str, str] = {field: "" for field in self.CAN_FILTER_FIELDS}
        self._can_filter_options: dict[str, list[str]] = {field: [] for field in self.CAN_FILTER_FIELDS}
        self._can_filter_option_seen: dict[str, set[str]] = {field: set() for field in self.CAN_FILTER_FIELDS}
        self._can_filter_option_limits: dict[str, int] = {
            "time": 60,
            "dir": 10,
            "frameId": 120,
            "pgn": 120,
            "src": 120,
            "dst": 120,
            "j1939": 120,
            "dlc": 20,
            "uds": 120,
            "data": 80,
        }
        self._programming_active = False
        self._auto_reset_before_programming = True
        self._auto_reset_delay_ms = 650
        self._pending_programming_after_reset = False
        self._debug_enabled = False
        self._firmware_loading = False
        self._service_session_items = [
            "Default Session (0x01)",
            "Programming Session (0x02)",
            "Extended Session (0x03)",
        ]
        self._selected_service_session_index = 2
        self._service_access_busy = False
        self._service_access_pending_action = ""
        self._service_access_status = "Для записи 0x2E установите Extended Session (0x03), затем откройте Security Access (0x27)."
        self._service_security_unlocked = False
        self._service_access_target_sa: int | None = None
        self._service_session_service = ServiceSession()
        self._service_security_access_service = ServiceSecurityAccess()
        self._transfer_byte_order_index = 0
        self._source_address_text = f"0x{UdsIdentifiers.rx.src:02X}"
        self._source_address_busy = False
        self._source_address_operation = ""
        self._can_journal_enabled = False
        self._auto_detect_enabled = True

        self._calibration_active = False
        self._calibration_waiting_session = False
        self._calibration_poll_interval_ms = 1000
        self._calibration_current_level = 0
        self._calibration_level_0 = 0
        self._calibration_level_100 = 0
        self._calibration_level_0_known = False
        self._calibration_level_100_known = False
        self._calibration_write_verify_pending: dict[int, int] = {}
        self._calibration_verify_tolerance = 1
        self._calibration_wizard_stage = 0
        self._calibration_wizard_hint = "Запустите калибровку, чтобы начать пошаговый процесс."
        self._calibration_session_ready = False
        self._calibration_sequence_next_action = ""
        self._calibration_sequence_waiting_action = ""
        self._calibration_sequence_delay_ms = 180
        self._calibration_sequence_timeout_ms = 4000
        self._calibration_level0_written = False
        self._calibration_level100_written = False
        self._calibration_verify0_ok = False
        self._calibration_verify100_ok = False
        self._calibration_recent_samples: list[tuple[float, int]] = []
        self._calibration_recent_window_sec = 4.0
        self._calibration_captured_level = 0
        self._calibration_captured_available = False
        self._calibration_temp_comp_status = "Загрузите CSV из коллектора для офлайн-анализа температурной компенсации."
        self._calibration_temp_comp_samples: list[dict[str, object]] = []
        self._calibration_temp_comp_samples_by_node: dict[int, dict[str, object]] = {}
        self._calibration_temp_comp_sample_limit = 3000
        self._calibration_temp_comp_last_period: int | None = None
        self._calibration_temp_comp_last_temperature_x10: int | None = None
        self._calibration_temp_comp_last_temperature_c: float | None = None
        self._calibration_temp_comp_k1_x100_current: int | None = None
        self._calibration_temp_comp_k1_x100_base: int | None = None
        self._calibration_temp_comp_k1_x100_recommended: int | None = None
        self._calibration_temp_comp_k1_x100_delta: int | None = None
        self._calibration_temp_comp_k1_x100_next: int | None = None
        self._calibration_temp_comp_period_slope_before: float | None = None
        self._calibration_temp_comp_period_slope_after: float | None = None
        self._calibration_temp_comp_level_slope_before: float | None = None
        self._calibration_temp_comp_level_slope_after: float | None = None
        self._calibration_temp_comp_period_reduction_percent: float | None = None
        self._calibration_temp_comp_level_reduction_percent: float | None = None
        self._calibration_temp_comp_chart_series: list[dict[str, object]] = []
        self._calibration_backup_available = False
        self._calibration_backup_level_0 = 0
        self._calibration_backup_level_100 = 0
        self._calibration_backup_pending = False
        self._calibration_backup_values_pending: dict[int, int] = {}
        self._calibration_restore_active = False
        self._calibration_restore_queue: list[tuple[int, int]] = []
        self._calibration_restore_current_did: int | None = None
        self._calibration_target_node_sa: int | None = None
        self._calibration_node_options: list[str] = ["Авто (по текущим UDS ID)"]
        self._calibration_node_values: list[int | None] = [None]
        self._selected_calibration_node_index = 0
        self._calibration_csv_node_candidates: set[int] = set()
        self._calibration_read_service = ServiceReadDataById()
        self._calibration_write_service = ServiceWriteDataById()
        self._calibration_session_service = ServiceSession()
        self._calibration_read_service.set_byte_order("big")
        self._calibration_write_service.set_byte_order("big")

        self._collector_read_service = ServiceReadDataById()
        self._collector_read_service.set_byte_order("big")
        self._collector_enabled = False
        self._collector_trend_enabled = False
        self._collector_nodes: dict[int, dict[str, object]] = {}
        self._collector_node_order: list[int] = []
        self._collector_nodes_view: list[dict[str, str]] = []
        self._collector_state = "stopped"
        self._collector_poll_interval_ms = 220
        self._collector_cycle_pause_ms = 120
        self._collector_calibration_refresh_cycles = 24
        self._project_root_directory = self._resolve_project_root_directory()
        self._collector_output_directory = ""
        self._collector_output_is_session_dir = False
        default_collector_directory = self._project_root_directory / "logs"
        if not self._apply_collector_output_directory(default_collector_directory, emit_signal=False):
            self._apply_collector_output_directory(Path.cwd() / "logs", emit_signal=False)
        self._collector_session_dir: Path | None = None
        self._collector_csv_managers: dict[int, CollectorCsvManager] = {}
        self._collector_combined_csv_manager: CollectorCombinedCsvManager | None = None
        self._collector_poll_vars = [
            UdsData.curr_fuel_tank,
            UdsData.raw_fuel_level,
            UdsData.raw_temperature,
        ]
        self._collector_poll_node_index = 0
        self._collector_poll_phase = 0
        self._collector_pending_requests: dict[tuple[int, int], dict[str, float | int | str]] = {}
        self._collector_pending_timeout_ms = 1400
        self._collector_max_pending_requests = 1
        self._collector_min_inter_request_ms = 40
        self._collector_last_request_monotonic = 0.0
        self._collector_error_logs: list[dict[str, str]] = []
        self._collector_error_log_limit = 500
        self._collector_diagnostics_rate_limit: dict[str, float] = {}
        self._collector_trend_points: list[dict[str, object]] = []
        self._collector_trend_max_points = 180
        # Bounded in-memory history per node to keep collector UI responsive.
        # Old points are thinned adaptively in mixin to preserve full-period trend shape.
        # Full raw history is still persisted to CSV while recording.
        self._collector_trend_history_limit = 12000
        self._collector_trend_caption = "Ожидание данных от узлов..."
        self._collector_trend_latest_fuel = 0.0
        self._collector_trend_latest_temperature = 0.0
        self._collector_trend_points_by_node: dict[int, list[dict[str, object]]] = {}
        self._collector_trend_nodes_view: list[dict[str, object]] = []
        self._collector_trend_metrics_rows: list[dict[str, str]] = []
        self._collector_trend_network_metrics: dict[str, float | int] = {
            "nodesCount": 0,
            "fuelMean": 0.0,
            "temperatureMean": 0.0,
            "fuelSpread": 0.0,
            "temperatureSpread": 0.0,
            "fuelStd": 0.0,
            "temperatureStd": 0.0,
        }
        self._collector_trend_csv_series: list[dict[str, object]] = []

        self._options_parameters: list[UdsOptionParameter] = list(UDS_OPTIONS)
        self._options_items: list[str] = [f"0x{int(p.did) & 0xFFFF:04X} | {p.name} | {p.access.value}" for p in self._options_parameters]
        self._selected_option_index = 0
        self._options_read_service = ServiceReadDataById()
        self._options_write_service = ServiceWriteDataById()
        self._options_read_service.set_byte_order("big")
        self._options_write_service.set_byte_order("big")
        self._options_pending_did: int | None = None
        self._options_pending_action = ""
        self._options_request_origin = ""
        self._options_busy = False
        self._options_status = "Готово к операциям чтения/записи"
        self._options_value_text = "-"
        self._options_raw_hex = "-"
        self._options_history: list[dict[str, object]] = []
        self._options_history_next_id = 1
        self._options_selected_did = "-"
        self._options_selected_name = "-"
        self._options_selected_size = "-"
        self._options_selected_access = "-"
        self._options_selected_note = ""
        self._options_selected_can_read = False
        self._options_selected_can_write = False
        self._options_target_node_sa: int | None = None
        self._options_target_node_values: list[int | None] = [None]
        self._options_target_node_items: list[str] = ["Авто (по UDS RX ID)"]
        self._selected_options_target_node_index = 0
        self._options_pending_target_sa: int | None = None
        self._options_pending_write_bytes = b""
        self._options_last_read_bytes = b""
        self._options_isotp_total_len = 0
        self._options_isotp_buffer = bytearray()
        self._options_isotp_next_sn = 1
        self._options_bulk_busy = False
        self._options_bulk_delay_ms = 100
        self._options_bulk_status = "Ready for bulk DID read"
        self._options_bulk_rows: list[dict[str, object]] = []
        self._options_bulk_plan: list[UdsOptionParameter] = []
        self._options_bulk_next_index = 0
        self._options_bulk_success_count = 0
        self._options_bulk_fail_count = 0

        self._tx_priority_text = ""
        self._tx_pgn_text = ""
        self._tx_src_text = ""
        self._tx_dst_text = ""
        self._tx_identifier_text = ""
        self._rx_priority_text = ""
        self._rx_pgn_text = ""
        self._rx_src_text = ""
        self._rx_dst_text = ""
        self._rx_identifier_text = ""
        self._observed_node_stats: dict[int, dict[str, object]] = {}
        self._observed_candidate_order: list[int] = []
        self._observed_candidate_values: list[int] = []
        self._observed_candidate_items: list[str] = []
        self._observed_candidate_index = -1
        self._observed_frame_seq = 0
        self._observed_uds_text = "Ожидание входящих J1939 RX кадров для автоопределения адреса..."
        self._perf_origin = time.perf_counter()
        self._wall_origin = time.time()
        self._rx_time_anchor_raw: float | None = None
        self._rx_time_anchor_wall: float | None = None

        self._refresh_uds_identifier_texts(emit_signal=False)
        self._refresh_options_selection(emit_signal=False)

        self._firmware_loader_thread: QThread | None = None
        self._firmware_loader_worker: FirmwareLoadWorker | None = None

        self._bootloader.signal_new_state.connect(self._on_bootloader_state)
        self._bootloader.signal_data_sent.connect(self._on_data_sent)
        self._bootloader.signal_finished.connect(self._on_programming_finished)
        self._bootloader.signal_source_address_applied.connect(self._on_source_address_applied)
        self._bootloader.signal_source_address_read.connect(self._on_source_address_read)

        self._can.signal_new_message.connect(self._on_can_message)
        self._can.signal_tracing_started.connect(self._on_trace_state_event)
        self._can.signal_tracing_stopped.connect(self._on_trace_state_event)

        self._can_filter_rebuild_timer = QTimer(self)
        self._can_filter_rebuild_timer.setSingleShot(True)
        self._can_filter_rebuild_timer.setInterval(90)
        self._can_filter_rebuild_timer.timeout.connect(self._rebuild_can_traffic_view)

        self._programming_start_timer = QTimer(self)
        self._programming_start_timer.setSingleShot(True)
        self._programming_start_timer.timeout.connect(self._start_programming_after_reset)

        self._calibration_poll_timer = QTimer(self)
        self._calibration_poll_timer.setSingleShot(False)
        self._calibration_poll_timer.setInterval(self._calibration_poll_interval_ms)
        self._calibration_poll_timer.timeout.connect(self._on_calibration_poll_tick)
        self._calibration_sequence_delay_timer = QTimer(self)
        self._calibration_sequence_delay_timer.setSingleShot(True)
        self._calibration_sequence_delay_timer.timeout.connect(self._on_calibration_sequence_delay_timeout)
        self._calibration_sequence_timeout_timer = QTimer(self)
        self._calibration_sequence_timeout_timer.setSingleShot(True)
        self._calibration_sequence_timeout_timer.setInterval(self._calibration_sequence_timeout_ms)
        self._calibration_sequence_timeout_timer.timeout.connect(self._on_calibration_sequence_timeout)

        self._collector_poll_timer = QTimer(self)
        self._collector_poll_timer.setInterval(self._collector_poll_interval_ms)
        self._collector_poll_timer.timeout.connect(self._on_collector_poll_tick)

        self._collector_view_update_pending_nodes = False
        self._collector_view_update_pending_trend = False
        self._collector_view_update_timer = QTimer(self)
        self._collector_view_update_timer.setSingleShot(True)
        self._collector_view_update_timer.setInterval(220)
        self._collector_view_update_timer.timeout.connect(self._flush_collector_views_update)

        self._options_timeout_timer = QTimer(self)
        self._options_timeout_timer.setSingleShot(True)
        self._options_timeout_timer.timeout.connect(self._on_options_timeout)
        self._service_access_timeout_timer = QTimer(self)
        self._service_access_timeout_timer.setSingleShot(True)
        self._service_access_timeout_timer.setInterval(4000)
        self._service_access_timeout_timer.timeout.connect(self._on_service_access_timeout)
        self._options_fc_retry_left = 0
        self._options_fc_retry_timer = QTimer(self)
        self._options_fc_retry_timer.setSingleShot(False)
        self._options_fc_retry_timer.setInterval(25)
        self._options_fc_retry_timer.timeout.connect(self._on_options_fc_retry_tick)
        self._options_bulk_step_timer = QTimer(self)
        self._options_bulk_step_timer.setSingleShot(True)
        self._options_bulk_step_timer.timeout.connect(self._on_options_bulk_step_tick)

        self._rebuild_can_traffic_view()
