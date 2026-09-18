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
    programmingNodeSelectionChanged = Signal()
    programmingBatchChanged = Signal()
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
    calibrationZeroTrimChanged = Signal()
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
    diagnosticsChanged = Signal()
    mediaWizardChanged = Signal()
    markMediaChanged = Signal()
    liveFreshnessChanged = Signal()
    profileChanged = Signal()
    chamberChanged = Signal()
    trialChanged = Signal()
    nodeLiveChanged = Signal()
    nodeTrendChanged = Signal()
    capacitanceChanged = Signal()
    calibrationLogChanged = Signal()
    eepromCommitChanged = Signal()
    softwareVersionChanged = Signal()

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

    @Property(str, notify=softwareVersionChanged)
    def softwareVersionText(self):
        """Цель функции в выдаче текущей версии ПО из DID 0xF195, затем она отображает значение на главной форме."""
        return str(self._software_version_text)

    @Property(str, notify=softwareVersionChanged)
    def softwareVersionStatusText(self):
        """Цель функции в выдаче статуса операций DID 0xF195, затем она показывает оператору ход чтения или записи."""
        return str(self._software_version_status)

    @Property(bool, notify=softwareVersionChanged)
    def softwareVersionBusy(self):
        """Цель функции в выдаче флага занятости DID 0xF195, затем она блокирует повторные клики в UI."""
        return bool(self._software_version_busy)

    @Property(str, notify=softwareVersionChanged)
    def firmwareFileVersionText(self):
        """Цель функции в выдаче версии из имени BIN-файла, затем она позволяет записать ее в DID 0xF195."""
        return str(self._firmware_file_version_text)

    @Property("QVariantList", notify=softwareVersionChanged)
    def supplierDidRows(self):
        """Цель функции в выдаче строк DID изготовителя, затем она формирует компактную таблицу на главной форме."""
        return list(self._supplier_did_rows)

    @Property(bool, notify=softwareVersionChanged)
    def supplierDidBulkBusy(self):
        """Цель функции в выдаче флага массового чтения DID изготовителя, затем она блокирует повторный запуск кнопки."""
        return bool(self._supplier_did_bulk_busy)

    @Property(str, notify=softwareVersionChanged)
    def supplierDidStatusText(self):
        """Цель функции в выдаче статуса блока DID изготовителя, затем она показывает оператору текущий шаг или итог."""
        return str(self._supplier_did_status_text)

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

    @Property("QStringList", notify=programmingNodeSelectionChanged)
    def programmingNodeItems(self):
        return self._programming_node_items

    @Property(int, notify=programmingNodeSelectionChanged)
    def selectedProgrammingNodeIndex(self):
        return int(self._selected_programming_node_index)

    @Property(str, notify=programmingNodeSelectionChanged)
    def programmingTargetText(self):
        return str(self._programming_target_status)

    @Property(bool, notify=programmingNodeSelectionChanged)
    def programmingAllNodesAvailable(self):
        return len(self._detected_programming_node_values()) > 0

    @Property(bool, notify=programmingBatchChanged)
    def programmingBatchActive(self):
        return bool(self._programming_batch_active)

    @Property(str, notify=programmingBatchChanged)
    def programmingBatchStatusText(self):
        return str(self._programming_batch_status)

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

    @Property(str, notify=calibrationBackupChanged)
    def calibrationBackupZeroTrimText(self):
        if not self._calibration_backup_available:
            return "-"
        return str(int(self._calibration_backup_zero_trim))

    @Property(str, notify=calibrationBackupChanged)
    def calibrationBackupNodeText(self):
        if (not self._calibration_backup_available) or (self._calibration_backup_node_sa is None):
            return "-"
        return f"0x{int(self._calibration_backup_node_sa) & 0xFF:02X}"

    @Property(str, notify=calibrationBackupChanged)
    def calibrationBackupSavedAtText(self):
        if not self._calibration_backup_available:
            return "-"
        saved_text = str(self._calibration_backup_saved_at_text).strip()
        return saved_text if saved_text else "-"

    @Property(str, notify=calibrationBackupChanged)
    def calibrationBackupFilePathText(self):
        path_text = str(self._calibration_backup_file_path).strip()
        return path_text if path_text else "-"

    @Property(str, notify=calibrationBackupChanged)
    def calibrationBackupSourceText(self):
        source_text = str(self._calibration_backup_source_text).strip()
        if source_text:
            return source_text
        if self._calibration_backup_available:
            return "Источник дампа: МК."
        return "Дамп калибровки не сохранен."

    @Property(str, notify=calibrationZeroTrimChanged)
    def calibrationZeroTrimOperationText(self):
        """Цель свойства в показе хода подгонки нуля, затем оно возвращает текст последней операции."""
        return str(self._calibration_zero_trim_operation_text)

    @Property(bool, notify=calibrationZeroTrimChanged)
    def calibrationZeroTrimOperationBusy(self):
        """Цель свойства в блокировке кнопок на время обмена, затем оно возвращает признак занятости."""
        return bool(self._calibration_zero_trim_operation_busy)

    @Property(int, notify=calibrationZeroTrimChanged)
    def calibrationZeroTrimOperationProgressPercent(self):
        """Цель свойства в показе доли выполненного, затем оно возвращает проценты от 0 до 100."""
        return int(self._calibration_zero_trim_operation_progress_percent)

    @Property(bool, notify=calibrationZeroTrimChanged)
    def calibrationZeroTrimOperationProgressDeterminate(self):
        """Цель свойства в выборе вида полосы хода, затем оно говорит, известна ли доля выполненного."""
        return bool(self._calibration_zero_trim_operation_progress_determinate)

    @Property(str, notify=calibrationZeroTrimChanged)
    def calibrationZeroTrimCurrentText(self):
        value = self._calibration_zero_trim_count_current
        if value is None:
            return "не считан (DID 0x002D)"
        return str(int(value))

    @Property(str, notify=calibrationZeroTrimChanged)
    def calibrationZeroTrimRecommendedText(self):
        value = self._calibration_zero_trim_count_recommended
        if value is None:
            return "не рассчитан"
        return str(int(value))

    @Property(str, notify=calibrationZeroTrimChanged)
    def calibrationZeroTrimDeltaText(self):
        value = self._calibration_zero_trim_count_delta
        if value is None:
            return "не рассчитан"
        return f"{int(value):+d}"

    @Property(str, notify=calibrationZeroTrimChanged)
    def calibrationZeroTrimNextText(self):
        value = self._calibration_zero_trim_count_next
        if value is None:
            return "не рассчитан"
        return str(int(value))

    @Property(str, notify=calibrationZeroTrimChanged)
    def calibrationZeroTrimResidualText(self):
        value = self._calibration_zero_trim_residual_x10
        if value is None:
            return "не рассчитан"
        return f"{float(value) / 10.0:+.1f} %"

    @Property(str, notify=calibrationZeroTrimChanged)
    def calibrationZeroTrimLastReportText(self):
        value = str(self._calibration_zero_trim_last_report or "").strip()
        if not value:
            return "Операции подгонки еще не выполнялись."
        return value

    @Property(bool, notify=diagnosticsChanged)
    def diagnosticsRunning(self):
        """Цель функции в признаке идущей проверки, затем она позволяет QML показать нужную кнопку."""
        return bool(self._diagnostics_running)

    @Property(str, notify=diagnosticsChanged)
    def diagnosticsActionText(self):
        """Цель функции в подписи кнопки запуска, затем она переключает текст по состоянию проверки."""
        return "Остановить проверку" if self._diagnostics_running else "Начать проверку"

    @Property(str, notify=diagnosticsChanged)
    def diagnosticsStatusText(self):
        """Цель функции в показе хода опроса, затем она возвращает последнее сообщение диагностики."""
        return str(self._diagnostics_status)

    @Property(str, notify=diagnosticsChanged)
    def diagnosticsSummaryText(self):
        """Цель функции в общем вердикте по прибору, затем она возвращает худшую из найденных оценок."""
        return str(self._diagnostics_summary_text)

    @Property(str, notify=diagnosticsChanged)
    def diagnosticsSummaryColor(self):
        """Цель функции в цвете общего вердикта, затем она возвращает готовый код цвета для QML."""
        return str(self._diagnostics_summary_color)

    @Property("QVariantList", notify=diagnosticsChanged)
    def diagnosticsRows(self):
        """Цель функции в передаче таблицы проверки в QML, затем она возвращает готовые строки с вердиктами."""
        return self._diagnostics_rows

    @Property(str, notify=diagnosticsChanged)
    def diagnosticsCyclesText(self):
        """Цель функции в показе числа завершённых кругов опроса, затем она поясняет достоверность счётчиков."""
        cycles = int(self._diagnostics_cycles_done)
        if cycles <= 0:
            return "Кругов опроса: 0"
        return f"Кругов опроса: {cycles}"

    @Property(str, notify=diagnosticsChanged)
    def diagnosticsReportText(self):
        """Цель функции в выдаче текстового отчёта, затем она позволяет скопировать результат проверки целиком."""
        return self._build_diagnostics_report()

    @Property("QVariantList", notify=trialChanged)
    def trialSteps(self):
        """Цель функции в передаче этапов пробной калибровки в таблицу, затем видно итог и время каждого."""
        return self._trial_step_rows()

    @Property("QVariantList", notify=trialChanged)
    def trialLogRows(self):
        """Цель функции в передаче журнала проверки, затем видно, что делал каждый этап и почему."""
        return self._trial_log_rows()

    @Property(bool, notify=trialChanged)
    def trialBusy(self):
        """Цель функции в признаке идущего обмена, затем она блокирует кнопки на это время."""
        return bool(self._trial_busy)

    @Property(bool, notify=trialChanged)
    def trialAutoActive(self):
        """Цель функции в признаке автоматического прогона, затем окно показывает кнопку остановки."""
        return bool(self._trial_auto_active)

    @Property(str, notify=trialChanged)
    def trialAutoProgressText(self):
        """Цель функции в показе хода прогона, затем видно, какой этап идёт."""
        return self._trial_auto_progress()

    @Property(str, notify=trialChanged)
    def trialStatusText(self):
        """Цель функции в подписи о ходе работы, затем она объясняет текущий этап."""
        return str(self._trial_status)

    @Property(str, notify=trialChanged)
    def trialStatusColor(self):
        """Цель функции в цвете подписи, затем она отделяет успех от замечаний и отказа."""
        return str(self._trial_status_color)

    @Property(str, notify=trialChanged)
    def trialSummaryText(self):
        """Цель функции в короткой сводке, затем видно, сколько этапов пройдено."""
        return self._trial_summary()

    @Property("QVariantMap", notify=nodeLiveChanged)
    def nodeLive(self):
        """Цель функции в показе текущих данных узла, затем видно уровень и что происходит с прибором."""
        return self._node_live_view()

    @Property("QVariantMap", notify=nodeTrendChanged)
    def nodeTrends(self):
        """Цель функции в показе графиков живых чисел, затем видно динамику и экстремумы каждого."""
        return self._node_trend_view()

    @Property("QVariantMap", notify=capacitanceChanged)
    def capacitance(self):
        """Цель функции в показе ёмкости контуров, затем видно её значение в пикофарадах и плавание."""
        return self._capacitance_view()

    @Property("QVariantMap", notify=calibrationLogChanged)
    def calibrationLog(self):
        """Цель функции в показе журнала калибровки, затем видно, пишется ли он и куда."""
        return self._calibration_log_view()

    @Property("QVariantMap", notify=eepromCommitChanged)
    def eepromCommit(self):
        """Цель функции в показе сохранения в память прибора, затем видно, легла ли запись в микросхему."""
        return self._eeprom_commit_view()

    @Property(str, notify=chamberChanged)
    def chamberLabel(self):
        """Цель функции в показе текущей пометки, затем окно не теряет её при обновлении."""
        return str(self._chamber_label)

    @Property(bool, notify=chamberChanged)
    def chamberBusy(self):
        """Цель функции в признаке идущего замера, затем она блокирует кнопки на это время."""
        return bool(self._chamber_busy)

    @Property(str, notify=chamberChanged)
    def chamberStatusText(self):
        """Цель функции в подписи о ходе работы, затем она объясняет оператору текущий шаг."""
        return str(self._chamber_status)

    @Property(str, notify=chamberChanged)
    def chamberStatusColor(self):
        """Цель функции в цвете подписи, затем она отделяет успех от предупреждения и отказа."""
        return str(self._chamber_status_color)

    @Property(int, notify=chamberChanged)
    def chamberPointCount(self):
        """Цель функции в счётчике снятых точек, затем оператор видит объём прогона."""
        return len(self._chamber_points)

    @Property("QVariantList", notify=chamberChanged)
    def chamberRows(self):
        """Цель функции в показе журнала прогона, затем она отдаёт последние точки сверху."""
        return self._chamber_rows()

    @Property("QVariantList", notify=chamberChanged)
    def chamberCoverageRows(self):
        """Цель функции в показе полноты прогона, затем она называет, чего не хватает по узлам."""
        return self._chamber_coverage_rows()

    @Property("QStringList", notify=chamberChanged)
    def chamberReportLines(self):
        """Цель функции в перечислении недостающих данных, затем она объясняет отказ расчёта."""
        return [str(item) for item in self._chamber_report]

    @Property(bool, notify=chamberChanged)
    def chamberExtendLiquid(self):
        """Цель функции в признаке достройки строк «в жидкости», затем окно показывает её состояние."""
        return bool(self._chamber_extend_liquid)

    @Property(str, notify=chamberChanged)
    def chamberSpanMainText(self):
        """Цель функции в показе заданного размаха основного контура, затем пустая строка означает «из измерения»."""
        return "" if self._chamber_span_main is None else str(int(self._chamber_span_main))

    @Property(str, notify=chamberChanged)
    def chamberSpanMediaText(self):
        """Цель функции в показе заданного размаха контура вида топлива, затем пустая строка означает «из измерения»."""
        return "" if self._chamber_span_media is None else str(int(self._chamber_span_media))

    @Property(str, notify=chamberChanged)
    def chamberFilePath(self):
        """Цель функции в показе пути журнала прогона, затем оператор видит, куда он сохранён."""
        return str(self._chamber_file_path)

    @Property("QVariantList", notify=profileChanged)
    def profileRows(self):
        """Цель функции в передаче таблиц профиля в окно, затем она отдаёт по строке на каждую величину."""
        return self._profile_rows()

    @Property("QStringList", notify=profileChanged)
    def profileNodeTitles(self):
        """Цель функции в подписях колонок, затем она показывает температуры узлов."""
        return [f"{value / 10:.0f} °C" for value in self._profile_values["nodes"]]

    @Property(bool, notify=profileChanged)
    def profileBusy(self):
        """Цель функции в признаке идущего обмена, затем она блокирует кнопки на время записи."""
        return bool(self._profile_busy)

    @Property("QStringList", notify=profileChanged)
    def profileVerifyReport(self):
        """Цель функции в перечислении расхождений после проверки записи, затем виден каждый несовпавший узел."""
        return [str(item) for item in self._profile_verify_report]

    @Property(str, notify=profileChanged)
    def profileStatusText(self):
        """Цель функции в подписи о ходе работы, затем она объясняет оператору текущий шаг."""
        return str(self._profile_status)

    @Property(str, notify=profileChanged)
    def profileStatusColor(self):
        """Цель функции в цвете подписи, затем она отделяет успех от предупреждения и отказа."""
        return str(self._profile_status_color)

    @Property(str, notify=profileChanged)
    def profileCrcText(self):
        """Цель функции в показе суммы, затем она позволяет сверить её с прибором до записи."""
        return f"0x{self._profile_calc_crc():04X}"

    @Property(str, notify=profileChanged)
    def profileDeviceCrcText(self):
        """Цель функции в показе суммы из прибора, затем она выявляет недописанный профиль."""
        if self._profile_device_crc is None:
            return "не читалась"
        return f"0x{int(self._profile_device_crc):04X}"

    @Property(str, notify=profileChanged)
    def profileDeviceStatusText(self):
        """Цель функции в расшифровке состояния профиля в приборе, затем она называет причину отказа."""
        return self._profile_device_status_text()

    @Property(str, notify=profileChanged)
    def profileGenerationText(self):
        """Цель функции в показе поколения профиля, затем она даёт прослеживаемость записей."""
        return str(int(self._profile_generation))

    @Property(str, notify=profileChanged)
    def profileFilePath(self):
        """Цель функции в показе последнего файла профиля, затем она напоминает, откуда взяты таблицы."""
        return str(self._profile_file_path)

    @Property(bool, notify=mediaWizardChanged)
    def mediaWizardBusy(self):
        """Цель функции в признаке идущей операции мастера, затем она блокирует кнопки на время записи."""
        return bool(self._media_wizard_busy)

    @Property(str, notify=markMediaChanged)
    def calibrationMarkMediaStatus(self):
        """Итог записи вида топлива к отметке бака: видно, готова ли отметка для модели по двум контурам."""
        return str(self._mark_media_status)

    @Property(str, notify=markMediaChanged)
    def calibrationMarkMediaStatusColor(self):
        """Цвет итога записи вида топлива к отметке."""
        return str(self._mark_media_status_color)

    @Property("QVariantMap", notify=liveFreshnessChanged)
    def calibrationLiveFreshness(self):
        """Свежесть числа «Текущий»: приходят ли ответы и мерит ли основной контур."""
        return self._live_freshness_view("level", float(self._calibration_poll_interval_ms) / 1000.0)

    @Property("QVariantMap", notify=liveFreshnessChanged)
    def mediaWizardLiveFreshness(self):
        """Свежесть живого показания плоского конденсатора и работа контура вида топлива."""
        return self._live_freshness_view("flatcap", float(self._media_wizard_watch_gap_ms()) / 1000.0)

    @Property(bool, notify=mediaWizardChanged)
    def mediaWizardWatching(self):
        """Цель функции в признаке живого наблюдения, затем она показывает, обновляется ли показание."""
        return bool(self._media_wizard_watching)

    @Property(str, notify=mediaWizardChanged)
    def mediaWizardStatusText(self):
        """Цель функции в подписи о ходе работы мастера, затем она объясняет оператору текущий шаг."""
        return str(self._media_wizard_status)

    @Property(str, notify=mediaWizardChanged)
    def mediaWizardStatusColor(self):
        """Цель функции в цвете подписи мастера, затем она отделяет успех от предупреждения и отказа."""
        return str(self._media_wizard_status_color)

    @Property(str, notify=mediaWizardChanged)
    def mediaWizardLiveText(self):
        """Цель функции в живом показании плоского конденсатора, затем она позволяет дождаться устоявшегося значения."""
        if self._media_wizard_live_raw is None:
            return "-"
        # Без единиц, как у основного контура: оба числа стоят рядом и читаются одинаково.
        return str(int(self._media_wizard_live_raw))

    @Property(str, notify=mediaWizardChanged)
    def mediaWizardCapturedText(self):
        """Цель функции в усреднённом захвате плоского конденсатора, затем из него точка переносится в поле."""
        return "-" if self._media_wizard_captured is None else str(int(self._media_wizard_captured))

    @Property(str, notify=mediaWizardChanged)
    def mediaWizardCapturedSpreadText(self):
        """Цель функции в разбросе показаний за окно захвата, затем видно, устоялось ли число."""
        spread = self._media_wizard_captured_spread
        if spread is None:
            return ""
        return f"разброс {int(spread)} отсч. за {int(round(self._media_wizard_capture_window_s()))} с"

    @Property(bool, notify=mediaWizardChanged)
    def mediaWizardCapturedSpreadWarn(self):
        """Цель функции в признаке неустоявшегося числа, затем разброс подсвечивается."""
        spread = self._media_wizard_captured_spread
        return spread is not None and int(spread) > self.MEDIA_WIZARD_STABLE_SPREAD

    @Property(str, notify=mediaWizardChanged)
    def mediaWizardAirText(self):
        """Цель функции в показе сохранённой точки в воздухе, затем она подтверждает первый шаг калибровки."""
        return "-" if self._media_wizard_air is None else str(int(self._media_wizard_air))

    @Property(str, notify=mediaWizardChanged)
    def mediaWizardCalText(self):
        """Цель функции в показе сохранённой точки в жидкости, затем она подтверждает второй шаг калибровки."""
        return "-" if self._media_wizard_cal is None else str(int(self._media_wizard_cal))

    @Property(str, notify=mediaWizardChanged)
    def mediaWizardSpanText(self):
        """Цель функции в показе разницы между точками, затем она сразу говорит, годится ли пара опор."""
        return self._media_wizard_span_text()

    @Property(str, notify=mediaWizardChanged)
    def mediaWizardEnabledText(self):
        """Цель функции в показе состояния поправки, затем она избавляет от чтения DID вручную."""
        if self._media_wizard_enabled is None:
            return "неизвестно"
        return "включена" if int(self._media_wizard_enabled) == 1 else "выключена"

    @Property(bool, notify=mediaWizardChanged)
    def mediaWizardCanEnable(self):
        """Цель функции в защите от включения поправки без калибровки, затем она гасит кнопку включения."""
        return bool(self._media_wizard_points_are_valid())

    @Property(bool, notify=calibrationStateChanged)
    def mediaWizardWriteAllowed(self):
        """Цель функции в признаке открытого доступа на запись, затем она объясняет, почему кнопки неактивны."""
        return bool(self._media_wizard_write_allowed())
