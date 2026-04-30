from __future__ import annotations

from PySide6.QtCore import Property, Signal

from uds.data_identifiers import UdsData
from uds.uds_identifiers import UdsIdentifiers

from .contract import AppControllerContract


class AppControllerPropertiesMixin(AppControllerContract):
    devicesChanged = Signal()
    selectedDeviceIndexChanged = Signal()
    deviceInfoChanged = Signal()
    connectionStateChanged = Signal()
    traceStateChanged = Signal()
    firmwarePathChanged = Signal()
    progressChanged = Signal()
    logsChanged = Signal()
    canTrafficLogsChanged = Signal()
    canFilterOptionsChanged = Signal()
    infoMessage = Signal(str, str)
    programmingActiveChanged = Signal()
    autoResetBeforeProgrammingChanged = Signal()
    debugEnabledChanged = Signal()
    firmwareLoadingChanged = Signal()
    serviceAccessChanged = Signal()
    protocolControlChanged = Signal()
    transferByteOrderIndexChanged = Signal()
    sourceAddressTextChanged = Signal()
    sourceAddressBusyChanged = Signal()
    sourceAddressOperationChanged = Signal()
    sourceAddressStatusChanged = Signal()
    udsIdentifiersChanged = Signal()
    observedUdsCandidateChanged = Signal()
    canJournalEnabledChanged = Signal()
    autoDetectEnabledChanged = Signal()
    calibrationStateChanged = Signal()
    calibrationValuesChanged = Signal()
    calibrationPollingIntervalChanged = Signal()
    calibrationWizardChanged = Signal()
    calibrationVerificationChanged = Signal()
    calibrationBackupChanged = Signal()
    calibrationNodeSelectionChanged = Signal()
    calibrationTempCompChanged = Signal()
    collectorEnabledChanged = Signal()
    collectorNodesChanged = Signal()
    collectorOutputDirectoryChanged = Signal()
    collectorPollIntervalChanged = Signal()
    collectorCyclePauseChanged = Signal()
    collectorDiagnosticsChanged = Signal()
    collectorStateChanged = Signal()
    collectorTrendEnabledChanged = Signal()
    collectorTrendChanged = Signal()
    collectorSftpChanged = Signal()
    optionSelectionChanged = Signal()
    optionValueChanged = Signal()
    optionOperationChanged = Signal()
    optionHistoryChanged = Signal()
    optionsTargetNodeChanged = Signal()
    optionsBulkChanged = Signal()
    optionsBulkRowsChanged = Signal()

    @Property("QStringList", notify=devicesChanged)
    def devices(self):
        return self._devices

    @Property(int, notify=selectedDeviceIndexChanged)
    def selectedDeviceIndex(self):
        return self._selected_device_index

    @Property(str, notify=deviceInfoChanged)
    def manufacturer(self):
        return self._manufacturer

    @Property(str, notify=deviceInfoChanged)
    def product(self):
        return self._product

    @Property(str, notify=deviceInfoChanged)
    def serial(self):
        return self._serial

    @Property(str, notify=deviceInfoChanged)
    def deviceHandle(self):
        return self._device_handle

    @Property(bool, notify=connectionStateChanged)
    def connected(self):
        return self._can.is_connect

    @Property(str, notify=connectionStateChanged)
    def connectionActionText(self):
        return "Отключиться" if self._can.is_connect else "Подключиться"

    @Property(bool, notify=traceStateChanged)
    def tracing(self):
        return self._can.is_trace

    @Property(str, notify=traceStateChanged)
    def traceActionText(self):
        return "Остановить трассировку" if self._can.is_trace else "Запустить трассировку"

    @Property(str, notify=firmwarePathChanged)
    def firmwarePath(self):
        return self._firmware_path

    @Property(int, notify=progressChanged)
    def progressValue(self):
        return self._progress_value

    @Property(int, notify=progressChanged)
    def progressMax(self):
        return self._progress_max

    @Property("QVariantList", notify=logsChanged)
    def logs(self):
        return self._logs

    @Property("QVariantList", notify=canTrafficLogsChanged)
    def canTrafficLogs(self):
        return self._can_traffic_logs

    @Property("QVariantList", notify=canTrafficLogsChanged)
    def filteredCanTrafficLogs(self):
        return self._filtered_can_traffic_logs

    @Property("QStringList", notify=canFilterOptionsChanged)
    def canFilterTimeOptions(self):
        return self._can_filter_options.get("time", [])

    @Property("QStringList", notify=canFilterOptionsChanged)
    def canFilterDirOptions(self):
        return self._can_filter_options.get("dir", [])

    @Property("QStringList", notify=canFilterOptionsChanged)
    def canFilterIdOptions(self):
        return self._can_filter_options.get("frameId", [])

    @Property("QStringList", notify=canFilterOptionsChanged)
    def canFilterPgnOptions(self):
        return self._can_filter_options.get("pgn", [])

    @Property("QStringList", notify=canFilterOptionsChanged)
    def canFilterSrcOptions(self):
        return self._can_filter_options.get("src", [])

    @Property("QStringList", notify=canFilterOptionsChanged)
    def canFilterDstOptions(self):
        return self._can_filter_options.get("dst", [])

    @Property("QStringList", notify=canFilterOptionsChanged)
    def canFilterJ1939Options(self):
        return self._can_filter_options.get("j1939", [])

    @Property("QStringList", notify=canFilterOptionsChanged)
    def canFilterDlcOptions(self):
        return self._can_filter_options.get("dlc", [])

    @Property("QStringList", notify=canFilterOptionsChanged)
    def canFilterUdsOptions(self):
        return self._can_filter_options.get("uds", [])

    @Property("QStringList", notify=canFilterOptionsChanged)
    def canFilterDataOptions(self):
        return self._can_filter_options.get("data", [])

    @Property(bool, notify=programmingActiveChanged)
    def programmingActive(self):
        return self._programming_active

    @Property(bool, notify=autoResetBeforeProgrammingChanged)
    def autoResetBeforeProgramming(self):
        return self._auto_reset_before_programming

    @Property(bool, notify=debugEnabledChanged)
    def debugEnabled(self):
        return self._debug_enabled

    @Property(bool, notify=canJournalEnabledChanged)
    def canJournalEnabled(self):
        return self._can_journal_enabled

    @Property(bool, notify=autoDetectEnabledChanged)
    def autoDetectEnabled(self):
        return self._auto_detect_enabled

    @Property(bool, notify=firmwareLoadingChanged)
    def firmwareLoading(self):
        return self._firmware_loading

    @Property("QStringList", notify=serviceAccessChanged)
    def serviceSessionItems(self):
        return self._service_session_items

    @Property(int, notify=serviceAccessChanged)
    def selectedServiceSessionIndex(self):
        return int(self._selected_service_session_index)

    @Property(bool, notify=serviceAccessChanged)
    def serviceAccessBusy(self):
        return bool(self._service_access_busy)

    @Property(str, notify=serviceAccessChanged)
    def serviceAccessStatusText(self):
        return str(self._service_access_status)

    @Property(bool, notify=serviceAccessChanged)
    def serviceSecurityUnlocked(self):
        return bool(self._service_security_unlocked)

    @Property("QStringList", notify=protocolControlChanged)
    def communicationControlModeItems(self):
        return self._communication_control_mode_items

    @Property(int, notify=protocolControlChanged)
    def selectedCommunicationControlModeIndex(self):
        return int(self._selected_communication_control_mode_index)

    @Property("QStringList", notify=protocolControlChanged)
    def communicationControlAddressingItems(self):
        return self._communication_control_addressing_items

    @Property(int, notify=protocolControlChanged)
    def selectedCommunicationControlAddressingIndex(self):
        return int(self._selected_communication_control_addressing_index)

    @Property("QStringList", notify=protocolControlChanged)
    def communicationControlTypeItems(self):
        return self._communication_control_type_items

    @Property(int, notify=protocolControlChanged)
    def selectedCommunicationControlTypeIndex(self):
        return int(self._selected_communication_control_type_index)

    @Property(bool, notify=protocolControlChanged)
    def communicationControlSuppressPositiveResponse(self):
        return bool(self._communication_control_suppress_positive_response)

    @Property(bool, notify=protocolControlChanged)
    def communicationControlBusy(self):
        return bool(self._communication_control_busy)

    @Property(str, notify=protocolControlChanged)
    def communicationControlStatusText(self):
        return str(self._communication_control_status)

    @Property(int, notify=transferByteOrderIndexChanged)
    def transferByteOrderIndex(self):
        return self._transfer_byte_order_index

    @Property(str, notify=sourceAddressTextChanged)
    def sourceAddressText(self):
        return self._source_address_text

    @Property(bool, notify=sourceAddressBusyChanged)
    def sourceAddressBusy(self):
        return self._source_address_busy

    @Property(str, notify=sourceAddressOperationChanged)
    def sourceAddressOperation(self):
        return self._source_address_operation

    @Property(str, notify=sourceAddressStatusChanged)
    def sourceAddressStatusText(self):
        return str(self._source_address_status)

    @Property(str, notify=udsIdentifiersChanged)
    def txPriorityText(self):
        return self._tx_priority_text

    @Property(str, notify=udsIdentifiersChanged)
    def txPgnText(self):
        return self._tx_pgn_text

    @Property(str, notify=udsIdentifiersChanged)
    def txSrcText(self):
        return self._tx_src_text

    @Property(str, notify=udsIdentifiersChanged)
    def txDstText(self):
        return self._tx_dst_text

    @Property(str, notify=udsIdentifiersChanged)
    def txIdentifierText(self):
        return self._tx_identifier_text

    @Property(str, notify=udsIdentifiersChanged)
    def rxPriorityText(self):
        return self._rx_priority_text

    @Property(str, notify=udsIdentifiersChanged)
    def rxPgnText(self):
        return self._rx_pgn_text

    @Property(str, notify=udsIdentifiersChanged)
    def rxSrcText(self):
        return self._rx_src_text

    @Property(str, notify=udsIdentifiersChanged)
    def rxDstText(self):
        return self._rx_dst_text

    @Property(str, notify=udsIdentifiersChanged)
    def rxIdentifierText(self):
        return self._rx_identifier_text

    @Property(bool, notify=observedUdsCandidateChanged)
    def observedUdsCandidateAvailable(self):
        return 0 <= self._observed_candidate_index < len(self._observed_candidate_values)

    @Property(str, notify=observedUdsCandidateChanged)
    def observedUdsCandidateText(self):
        return self._observed_uds_text

    @Property("QStringList", notify=observedUdsCandidateChanged)
    def observedUdsCandidates(self):
        return self._observed_candidate_items

    @Property(int, notify=observedUdsCandidateChanged)
    def selectedObservedUdsCandidateIndex(self):
        return self._observed_candidate_index

    @Property(bool, notify=collectorEnabledChanged)
    def collectorEnabled(self):
        return bool(self._collector_enabled)

    @Property("QVariantList", notify=collectorNodesChanged)
    def collectorNodes(self):
        return self._collector_nodes_view

    @Property(str, notify=collectorOutputDirectoryChanged)
    def collectorOutputDirectory(self):
        return self._collector_output_directory

    @Property(int, notify=collectorPollIntervalChanged)
    def collectorPollIntervalMs(self):
        return self._collector_poll_interval_ms

    @Property(int, notify=collectorCyclePauseChanged)
    def collectorCyclePauseMs(self):
        return self._collector_cycle_pause_ms

    @Property(str, notify=collectorStateChanged)
    def collectorStateText(self):
        if self._collector_state == "recording":
            return "Статус записи: идет запись"
        if self._collector_state == "paused":
            return "Статус записи: пауза"
        return "Статус записи: остановлено"

    @Property(bool, notify=collectorStateChanged)
    def collectorRecording(self):
        return self._collector_state == "recording"

    @Property(bool, notify=collectorStateChanged)
    def collectorPaused(self):
        return self._collector_state == "paused"

    @Property(bool, notify=collectorTrendEnabledChanged)
    def collectorTrendEnabled(self):
        return bool(self._collector_trend_enabled)

    @Property("QVariantList", notify=collectorDiagnosticsChanged)
    def collectorErrorLogs(self):
        return self._collector_error_logs

    @Property(int, notify=collectorDiagnosticsChanged)
    def collectorErrorCount(self):
        return len(self._collector_error_logs)

    @Property("QVariantList", notify=collectorTrendChanged)
    def collectorTrendPoints(self):
        return self._collector_trend_points

    @Property(str, notify=collectorTrendChanged)
    def collectorTrendCaption(self):
        return self._collector_trend_caption

    @Property(str, notify=collectorTrendChanged)
    def collectorTrendFuelText(self):
        return f"{float(self._collector_trend_latest_fuel):.1f} %"

    @Property(str, notify=collectorTrendChanged)
    def collectorTrendTemperatureText(self):
        return f"{float(self._collector_trend_latest_temperature):.1f} °C"

    @Property("QVariantList", notify=collectorTrendChanged)
    def collectorTrendNodes(self):
        return self._collector_trend_nodes_view

    @Property("QStringList", notify=collectorTrendChanged)
    def collectorTrendNodeLabels(self):
        return [str(item.get("node", "")) for item in self._collector_trend_nodes_view]

    @Property("QVariantList", notify=collectorTrendChanged)
    def collectorTrendMetricsRows(self):
        return self._collector_trend_metrics_rows

    @Property("QVariantMap", notify=collectorTrendChanged)
    def collectorTrendNetworkMetrics(self):
        return self._collector_trend_network_metrics

    @Property("QVariantList", notify=collectorTrendChanged)
    def collectorTrendCsvSeries(self):
        return self._collector_trend_csv_series

    @Property(bool, notify=collectorSftpChanged)
    def collectorSftpEnabled(self):
        return bool(self._collector_sftp_enabled)

    @Property(str, notify=collectorSftpChanged)
    def collectorSftpHost(self):
        return str(self._collector_sftp_host)

    @Property(int, notify=collectorSftpChanged)
    def collectorSftpPort(self):
        return int(self._collector_sftp_port)

    @Property(str, notify=collectorSftpChanged)
    def collectorSftpUsername(self):
        return str(self._collector_sftp_username)

    @Property(str, notify=collectorSftpChanged)
    def collectorSftpPassword(self):
        return str(self._collector_sftp_password)

    @Property(str, notify=collectorSftpChanged)
    def collectorSftpRemoteDir(self):
        return str(self._collector_sftp_remote_dir)

    @Property(bool, notify=collectorSftpChanged)
    def collectorSftpBusy(self):
        return bool(self._collector_sftp_busy)

    @Property(str, notify=collectorSftpChanged)
    def collectorSftpStatusText(self):
        return str(self._collector_sftp_status_text)

    @Property("QStringList", notify=optionSelectionChanged)
    def optionsParameterItems(self):
        return self._options_items

    @Property(int, notify=optionSelectionChanged)
    def selectedOptionsParameterIndex(self):
        return int(self._selected_option_index)

    @Property("QStringList", notify=optionsTargetNodeChanged)
    def optionsTargetNodeItems(self):
        return self._options_target_node_items

    @Property(int, notify=optionsTargetNodeChanged)
    def selectedOptionsTargetNodeIndex(self):
        return int(self._selected_options_target_node_index)

    @Property(str, notify=optionsTargetNodeChanged)
    def optionsTargetNodeText(self):
        if self._options_target_node_sa is None:
            return f"Авто (UDS RX SA: 0x{int(UdsIdentifiers.rx.src) & 0xFF:02X})"
        return f"0x{int(self._options_target_node_sa) & 0xFF:02X}"

    @Property(str, notify=optionSelectionChanged)
    def selectedOptionDidText(self):
        return self._options_selected_did

    @Property(str, notify=optionSelectionChanged)
    def selectedOptionNameText(self):
        return self._options_selected_name

    @Property(str, notify=optionSelectionChanged)
    def selectedOptionSizeText(self):
        return self._options_selected_size

    @Property(str, notify=optionSelectionChanged)
    def selectedOptionAccessText(self):
        return self._options_selected_access

    @Property(str, notify=optionSelectionChanged)
    def selectedOptionNoteText(self):
        return self._options_selected_note

    @Property(bool, notify=optionSelectionChanged)
    def selectedOptionCanRead(self):
        return bool(self._options_selected_can_read)

    @Property(bool, notify=optionSelectionChanged)
    def selectedOptionCanWrite(self):
        return bool(self._options_selected_can_write)

    @Property(str, notify=optionValueChanged)
    def selectedOptionValueText(self):
        return self._options_value_text

    @Property(str, notify=optionValueChanged)
    def selectedOptionRawHexText(self):
        return self._options_raw_hex

    @Property(bool, notify=optionOperationChanged)
    def optionOperationBusy(self):
        return bool(self._options_busy or self._options_bulk_busy)

    @Property(str, notify=optionOperationChanged)
    def optionOperationStatusText(self):
        return self._options_status

    @Property("QVariantList", notify=optionHistoryChanged)
    def optionOperationHistory(self):
        return self._options_history

    @Property(bool, notify=optionsBulkChanged)
    def optionsBulkBusy(self):
        return bool(self._options_bulk_busy)

    @Property(str, notify=optionsBulkChanged)
    def optionsBulkStatusText(self):
        return str(self._options_bulk_status)

    @Property(int, notify=optionsBulkChanged)
    def optionsBulkDelayMs(self):
        return int(self._options_bulk_delay_ms)

    @Property(str, notify=optionsBulkChanged)
    def optionsBulkProgressText(self):
        total = len(self._options_bulk_plan)
        done = int(self._options_bulk_success_count) + int(self._options_bulk_fail_count)
        if total <= 0:
            return "0/0"
        return f"{done}/{total}"

    @Property("QVariantList", notify=optionsBulkRowsChanged)
    def optionsBulkRows(self):
        return self._options_bulk_rows

    @Property(bool, notify=calibrationStateChanged)
    def calibrationActive(self):
        return self._calibration_active

    @Property(str, notify=calibrationStateChanged)
    def calibrationActionText(self):
        return "Завершить калибровку" if self._calibration_active else "Начать калибровку"

    @Property(str, notify=calibrationValuesChanged)
    def calibrationCurrentLevelText(self):
        return str(int(self._calibration_current_level))

    @Property(str, notify=calibrationValuesChanged)
    def calibrationLevel0Text(self):
        return str(int(self._calibration_level_0))

    @Property(str, notify=calibrationValuesChanged)
    def calibrationLevel100Text(self):
        return str(int(self._calibration_level_100))

    @Property(int, notify=calibrationValuesChanged)
    def calibrationLevel0Value(self):
        return int(self._calibration_level_0)

    @Property(int, notify=calibrationValuesChanged)
    def calibrationLevel100Value(self):
        return int(self._calibration_level_100)

    @Property(bool, notify=calibrationValuesChanged)
    def calibrationLevelBoundsKnown(self):
        return (
            bool(self._calibration_level_0_known)
            and bool(self._calibration_level_100_known)
            and int(self._calibration_level_100) > int(self._calibration_level_0)
        )

    @Property(int, notify=calibrationPollingIntervalChanged)
    def calibrationPollingIntervalMs(self):
        return int(self._calibration_poll_interval_ms)

    @Property(int, notify=calibrationWizardChanged)
    def calibrationWizardStage(self):
        return int(self._calibration_wizard_stage)

    @Property(str, notify=calibrationWizardChanged)
    def calibrationWizardHint(self):
        return str(self._calibration_wizard_hint)

    @Property("QStringList", notify=calibrationNodeSelectionChanged)
    def calibrationNodeOptions(self):
        return self._calibration_node_options

    @Property(int, notify=calibrationNodeSelectionChanged)
    def selectedCalibrationNodeIndex(self):
        return int(self._selected_calibration_node_index)

    @Property(str, notify=calibrationNodeSelectionChanged)
    def calibrationSelectedNodeText(self):
        if 0 <= self._selected_calibration_node_index < len(self._calibration_node_options):
            return str(self._calibration_node_options[self._selected_calibration_node_index])
        return "Авто (по текущим UDS ID)"

    @Property(str, notify=calibrationValuesChanged)
    def calibrationCapturedLevelText(self):
        if not self._calibration_captured_available:
            return "-"
        return str(int(self._calibration_captured_level))

    @Property(bool, notify=calibrationVerificationChanged)
    def calibrationVerifyInProgress(self):
        return len(self._calibration_write_verify_pending) > 0

    @Property(str, notify=calibrationVerificationChanged)
    def calibrationVerifyPendingDidsText(self):
        if len(self._calibration_write_verify_pending) == 0:
            return "-"

        labels: list[str] = []
        for did in sorted(int(key) for key in self._calibration_write_verify_pending.keys()):
            if did == int(UdsData.empty_fuel_tank.pid):
                labels.append("0%")
            elif did == int(UdsData.full_fuel_tank.pid):
                labels.append("100%")
            else:
                labels.append(f"0x{did:04X}")
        return ", ".join(labels)

    @Property(str, notify=calibrationVerificationChanged)
    def calibrationVerifyStatusText(self):
        pending_dids = {int(key) for key in self._calibration_write_verify_pending.keys()}
        if len(pending_dids) > 0:
            return f"Автопроверка выполняется: ожидание DID {self.calibrationVerifyPendingDidsText}."

        fail0 = self._calibration_level0_written and (not self._calibration_verify0_ok)
        fail100 = self._calibration_level100_written and (not self._calibration_verify100_ok)
        if fail0 or fail100:
            failed_labels: list[str] = []
            if fail0:
                failed_labels.append("0%")
            if fail100:
                failed_labels.append("100%")
            return f"Автопроверка не пройдена для: {', '.join(failed_labels)}."

        if self._calibration_verify0_ok and self._calibration_verify100_ok:
            return "Автопроверка успешно завершена для 0% и 100%."

        return "Ожидание записи значений 0% и 100%."

    @Property(bool, notify=calibrationBackupChanged)
    def calibrationBackupAvailable(self):
        return bool(self._calibration_backup_available)

    @Property(str, notify=calibrationBackupChanged)
    def calibrationBackupLevel0Text(self):
        if not self._calibration_backup_available:
            return "-"
        return str(int(self._calibration_backup_level_0))

    @Property(str, notify=calibrationBackupChanged)
    def calibrationBackupLevel100Text(self):
        if not self._calibration_backup_available:
            return "-"
        return str(int(self._calibration_backup_level_100))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompStatusText(self):
        return str(self._calibration_temp_comp_status)

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompOperationText(self):
        return str(self._calibration_temp_comp_operation_text)

    @Property(bool, notify=calibrationTempCompChanged)
    def calibrationTempCompOperationBusy(self):
        return bool(self._calibration_temp_comp_operation_busy)

    @Property(int, notify=calibrationTempCompChanged)
    def calibrationTempCompOperationProgressPercent(self):
        return int(self._calibration_temp_comp_operation_progress_percent)

    @Property(bool, notify=calibrationTempCompChanged)
    def calibrationTempCompOperationProgressDeterminate(self):
        return bool(self._calibration_temp_comp_operation_progress_determinate)

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompPreviewStatusText(self):
        """Цель функции в выдаче текста локального превью, затем она показывает пользователю текущий этап пересчета графика."""
        return str(self._calibration_temp_comp_preview_status)

    @Property(bool, notify=calibrationTempCompChanged)
    def calibrationTempCompPreviewBusy(self):
        """Цель функции в выдаче флага занятости превью, затем она управляет индикатором выполнения рядом с графиком."""
        return bool(self._calibration_temp_comp_preview_busy)

    @Property(int, notify=calibrationTempCompChanged)
    def calibrationTempCompPreviewProgressPercent(self):
        """Цель функции в выдаче процента прогресса превью, затем она обновляет отдельный ProgressBar блока линейной коррекции."""
        return int(self._calibration_temp_comp_preview_progress_percent)

    @Property(bool, notify=calibrationTempCompChanged)
    def calibrationTempCompPreviewProgressDeterminate(self):
        """Цель функции в выдаче режима прогресса превью, затем она переключает ProgressBar между фиксированным и неопределенным режимом."""
        return bool(self._calibration_temp_comp_preview_progress_determinate)

    def _calibration_temp_comp_has_enough_samples(self) -> bool:
        """Цель функции в проверке достаточности выборки, затем она определяет готовность регрессии по температуре."""
        return len(self._calibration_temp_comp_samples) >= 2

    def _calibration_temp_comp_has_level_calibration(self) -> bool:
        """Цель функции в проверке доступности калибровок 0% и 100%, затем она определяет возможность расчета метрик в процентах."""
        return (
            bool(self._calibration_level_0_known)
            and bool(self._calibration_level_100_known)
            and int(self._calibration_level_100) > int(self._calibration_level_0)
        )

    def _calibration_temp_comp_period_range(self) -> tuple[float, float] | None:
        """Цель функции в сборе диапазона периода из офлайн-CSV, затем она возвращает min/max для карточки метрик."""
        samples = list(self._calibration_temp_comp_samples)
        if len(samples) <= 0:
            return None
        periods = [float(item.get("period", 0.0)) for item in samples]
        return min(periods), max(periods)

    def _calibration_temp_comp_temperature_range(self) -> tuple[float, float] | None:
        """Цель функции в сборе диапазона температуры из офлайн-CSV, затем она возвращает min/max для UI."""
        samples = list(self._calibration_temp_comp_samples)
        if len(samples) <= 0:
            return None
        temperatures = [float(item.get("temperature_c", 0.0)) for item in samples]
        return min(temperatures), max(temperatures)

    def _calibration_temp_comp_level_range(self) -> tuple[float, float] | None:
        """Цель функции в расчете диапазона уровня по периоду, затем она возвращает min/max в процентах."""
        if not self._calibration_temp_comp_has_level_calibration():
            return None
        samples = list(self._calibration_temp_comp_samples)
        if len(samples) <= 0:
            return None

        level_values: list[float] = []
        for sample in samples:
            converted = self._period_to_level_percent(float(sample.get("period", 0.0)))
            if converted is None:
                return None
            level_values.append(float(converted))
        if len(level_values) <= 0:
            return None
        return min(level_values), max(level_values)

    @Property(int, notify=calibrationTempCompChanged)
    def calibrationTempCompSampleCount(self):
        return len(self._calibration_temp_comp_samples)

    @Property("QStringList", notify=calibrationTempCompChanged)
    def calibrationTempCompDatasetOptions(self):
        """Цель функции в выдаче списка наборов CSV, затем она заполняет селектор узлов внутри блока температурной компенсации."""
        return self._calibration_temp_comp_dataset_options

    @Property(int, notify=calibrationTempCompChanged)
    def selectedCalibrationTempCompDatasetIndex(self):
        """Цель функции в выдаче текущего индекса набора CSV, затем она синхронизирует выбор QML-комбобокса."""
        return int(self._selected_calibration_temp_comp_dataset_index)

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompSelectedDatasetText(self):
        """Цель функции в выдаче подписи активного набора CSV, затем она показывает оператору узел офлайн-анализа."""
        selected_index = int(self._selected_calibration_temp_comp_dataset_index)
        if 0 <= selected_index < len(self._calibration_temp_comp_dataset_options):
            return str(self._calibration_temp_comp_dataset_options[selected_index])
        return "Набор CSV не выбран"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompPeriodRangeText(self):
        value = self._calibration_temp_comp_period_range()
        if value is None:
            return "нет данных"
        low_value, high_value = value
        return f"{float(low_value):.1f}..{float(high_value):.1f} count"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompTemperatureRangeText(self):
        value = self._calibration_temp_comp_temperature_range()
        if value is None:
            return "нет данных"
        low_value, high_value = value
        return f"{float(low_value):.1f}..{float(high_value):.1f} °C"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompLevelRangeText(self):
        if len(self._calibration_temp_comp_samples) <= 0:
            return "нет данных"
        value = self._calibration_temp_comp_level_range()
        if value is None:
            return "нужны 0% и 100%"
        low_value, high_value = value
        return f"{float(low_value):.1f}..{float(high_value):.1f} %"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompCurrentPeriodText(self):
        value = self._calibration_temp_comp_last_period
        if value is None:
            return "нет данных"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompCurrentTemperatureText(self):
        value = self._calibration_temp_comp_last_temperature_c
        if value is None:
            return "нет данных"
        return f"{float(value):.1f} °C"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompCurrentK1Text(self):
        value = self._calibration_temp_comp_k1_x100_current
        if value is None:
            return "не считан (DID 0x001B)"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompCurrentK0Text(self):
        value = self._calibration_temp_comp_k0_count_current
        if value is None:
            return "не считан (DID 0x001C)"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompCurrentZeroTrimText(self):
        value = self._calibration_temp_comp_zero_trim_count_current
        if value is None:
            return "не считан (DID 0x002D)"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompRecommendedZeroTrimText(self):
        value = self._calibration_temp_comp_zero_trim_count_recommended
        if value is None:
            return "не рассчитан"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompDeltaZeroTrimText(self):
        value = self._calibration_temp_comp_zero_trim_count_delta
        if value is None:
            return "не рассчитан"
        return f"{int(value):+d}"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompNextZeroTrimText(self):
        value = self._calibration_temp_comp_zero_trim_count_next
        if value is None:
            return "не рассчитан"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompResidualZeroTrimText(self):
        value = self._calibration_temp_comp_zero_trim_residual_x10
        if value is None:
            return "не рассчитан"
        return f"{float(value) / 10.0:+.1f} %"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompZeroTrimLastReportText(self):
        value = str(self._calibration_temp_comp_zero_trim_last_report or "").strip()
        if not value:
            return "Операции подгонки еще не выполнялись."
        return value

    @Property(bool, notify=calibrationTempCompChanged)
    def calibrationTempCompLinearPreviewEnabled(self):
        return bool(self._calibration_temp_comp_linear_preview_enabled)

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompLinearPreviewK1Text(self):
        value = self._calibration_temp_comp_linear_preview_k1_x100
        if value is not None:
            return str(int(value))
        if self._calibration_temp_comp_k1_x100_current is not None:
            return str(int(self._calibration_temp_comp_k1_x100_current))
        if self._calibration_temp_comp_k1_x100_base is not None:
            return str(int(self._calibration_temp_comp_k1_x100_base))
        return "0"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompLinearPreviewK0Text(self):
        value = self._calibration_temp_comp_linear_preview_k0_count
        if value is not None:
            return str(int(value))
        if self._calibration_temp_comp_k0_count_current is not None:
            return str(int(self._calibration_temp_comp_k0_count_current))
        if self._calibration_temp_comp_k0_count_base is not None:
            return str(int(self._calibration_temp_comp_k0_count_base))
        return "0"

    @Property("QVariantList", notify=calibrationTempCompChanged)
    def calibrationTempCompAdvancedRows(self):
        rows: list[dict[str, object]] = []
        for field in self._temp_comp_advanced_fields():
            field_var = field.get("var")
            if field_var is None:
                continue

            field_key = str(field.get("key", ""))
            raw_value = self._calibration_temp_comp_advanced_values.get(field_key)
            display_text = self._temp_comp_field_ui_value_text(field, raw_value)
            raw_text = "" if raw_value is None else str(int(raw_value))
            recommended_raw_value = self._calibration_temp_comp_advanced_recommended_values.get(field_key)
            has_recommended = recommended_raw_value is not None
            recommended_display_text = self._temp_comp_field_ui_value_text(field, recommended_raw_value) if has_recommended else "не рассчитан"
            recommended_raw_text = "" if recommended_raw_value is None else str(int(recommended_raw_value))
            rows.append(
                {
                    "key": field_key,
                    "did": f"0x{int(field_var.pid) & 0xFFFF:04X}",
                    "label": str(field.get("label", "")),
                    "unit": str(field.get("unit", "")),
                    "valueText": display_text,
                    "valueRawText": raw_text,
                    "recommendedText": recommended_display_text,
                    "recommendedRawText": recommended_raw_text,
                    "hasRecommended": bool(has_recommended),
                    "placeholder": str(field.get("placeholder", "dec/0xHEX")),
                }
            )
        return rows

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompBaseK1Text(self):
        value = self._calibration_temp_comp_k1_x100_base
        if value is None:
            if len(self._calibration_temp_comp_samples) <= 0:
                return "нет данных"
            return "0 (оффлайн)"
        if self._calibration_temp_comp_k1_x100_current is None:
            return f"{int(value)} (оффлайн)"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompRecommendedK1Text(self):
        value = self._calibration_temp_comp_k1_x100_recommended
        if value is None:
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompDeltaK1Text(self):
        value = self._calibration_temp_comp_k1_x100_delta
        if value is None:
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{int(value):+d}"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompNextK1Text(self):
        value = self._calibration_temp_comp_k1_x100_next
        if value is None:
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompBaseK0Text(self):
        value = self._calibration_temp_comp_k0_count_base
        if value is None:
            if len(self._calibration_temp_comp_samples) <= 0:
                return "нет данных"
            return "0 (оффлайн)"
        if self._calibration_temp_comp_k0_count_current is None:
            return f"{int(value)} (оффлайн)"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompRecommendedK0Text(self):
        value = self._calibration_temp_comp_k0_count_recommended
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompDeltaK0Text(self):
        value = self._calibration_temp_comp_k0_count_delta
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{int(value):+d}"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompNextK0Text(self):
        value = self._calibration_temp_comp_k0_count_next
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return str(int(value))

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompSlopeBeforePeriodText(self):
        value = self._calibration_temp_comp_period_slope_before
        if value is None:
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{float(value):.4f} count/°C"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompSlopeAfterPeriodText(self):
        value = self._calibration_temp_comp_period_slope_after
        if value is None:
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{float(value):.4f} count/°C"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompSlopeBeforeLevelText(self):
        value = self._calibration_temp_comp_level_slope_before
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{float(value):.4f} %/°C"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompSlopeAfterLevelText(self):
        value = self._calibration_temp_comp_level_slope_after
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{float(value):.4f} %/°C"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompReductionPeriodText(self):
        value = self._calibration_temp_comp_period_reduction_percent
        if value is None:
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{float(value):.2f} %"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompReductionLevelText(self):
        value = self._calibration_temp_comp_level_reduction_percent
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{float(value):.2f} %"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompErrorRangeBeforeText(self):
        value = self._calibration_temp_comp_level_error_range_before
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        low_value, high_value = value
        return f"{float(low_value):.3f}..{float(high_value):.3f} %"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompErrorRangeAfterText(self):
        value = self._calibration_temp_comp_level_error_range_after
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        low_value, high_value = value
        return f"{float(low_value):.3f}..{float(high_value):.3f} %"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompErrorMaxBeforeText(self):
        value = self._calibration_temp_comp_level_error_max_before
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{float(value):.3f} %"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompErrorMaxAfterText(self):
        value = self._calibration_temp_comp_level_error_max_after
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{float(value):.3f} %"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompErrorP95BeforeText(self):
        value = self._calibration_temp_comp_level_error_p95_before
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{float(value):.3f} %"

    @Property(str, notify=calibrationTempCompChanged)
    def calibrationTempCompErrorP95AfterText(self):
        value = self._calibration_temp_comp_level_error_p95_after
        if value is None:
            if not self._calibration_temp_comp_has_level_calibration():
                return "нужны 0% и 100%"
            if not self._calibration_temp_comp_has_enough_samples():
                return "нужно >=2 точки"
            return "не рассчитан"
        return f"{float(value):.3f} %"

    @Property(bool, notify=calibrationTempCompChanged)
    def calibrationTempCompCanApplyNext(self):
        return self._calibration_temp_comp_k1_x100_next is not None

    @Property(bool, notify=calibrationTempCompChanged)
    def calibrationTempCompCanApplyNextK0(self):
        return self._calibration_temp_comp_k0_count_next is not None

    @Property("QVariantList", notify=calibrationTempCompChanged)
    def calibrationTempCompTrendSeries(self):
        return self._calibration_temp_comp_chart_series

    @Property(int, notify=calibrationTempCompChanged)
    def calibrationTempCompChartRevision(self):
        """Цель функции в выдаче версии графика температурной компенсации, затем она позволяет QML пропускать лишние перерисовки."""
        return int(self._calibration_temp_comp_chart_revision)
