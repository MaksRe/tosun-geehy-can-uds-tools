import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import "."

Item {
    id: root

    property var appController
    property color cardColor: "#ffffff"
    property color cardBorder: "#d6e2ef"
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"
    readonly property int contentPadding: 10
    readonly property int tempCompScrollBarWidth: 16
    readonly property int advancedParamColumnWidth: 232
    readonly property int advancedRecommendedColumnWidth: 220
    readonly property int advancedReadButtonWidth: 72
    readonly property int advancedWriteButtonWidth: 82
    property bool tempCompShowRawSeries: true
    property bool tempCompShowCurrentSeries: true
    property bool tempCompShowRecommendedSeries: true
    property var tempCompFilteredSeries: []
    property int tempCompLastChartRevision: -1
    property string tempCompLastFilterMask: ""

    function applyCapturedToField(targetField, targetSwitch) {
        if (!root.appController) {
            return
        }
        var captured = root.appController.calibrationCapturedLevelText
        if (!captured || captured === "-") {
            return
        }
        targetSwitch.checked = true
        targetField.text = captured
    }

    function seriesField(seriesItem, fieldName, fallbackValue) {
        if (!seriesItem || fieldName === undefined || fieldName === null) {
            return fallbackValue
        }
        if (seriesItem[fieldName] !== undefined && seriesItem[fieldName] !== null) {
            return seriesItem[fieldName]
        }
        return fallbackValue
    }

    function tempCompSeriesVisible(seriesItem) {
        var name = String(seriesField(seriesItem, "node", ""))
        if (name.indexOf("Сырой период") === 0) {
            return tempCompShowRawSeries
        }
        if (name.indexOf("После текущих") === 0) {
            return tempCompShowCurrentSeries
        }
        if (name.indexOf("После рекоменд.") === 0) {
            return tempCompShowRecommendedSeries
        }
        return true
    }

    // Цель функции в стабилизации набора серий для графика, затем она обновляет кэш только при смене данных или фильтров.
    function rebuildFilteredTempCompSeries(forceUpdate) {
        if (!root.appController) {
            root.tempCompFilteredSeries = []
            root.tempCompLastChartRevision = -1
            root.tempCompLastFilterMask = ""
            return
        }
        var force = (forceUpdate === true)
        var revision = Number(root.appController.calibrationTempCompChartRevision)
        if (!isFinite(revision)) {
            revision = -1
        }
        var filterMask = (root.tempCompShowRawSeries ? "1" : "0")
            + (root.tempCompShowCurrentSeries ? "1" : "0")
            + (root.tempCompShowRecommendedSeries ? "1" : "0")
        if (!force && root.tempCompLastChartRevision === revision && root.tempCompLastFilterMask === filterMask) {
            return
        }
        var source = root.appController.calibrationTempCompTrendSeries
        var filtered = []
        for (var i = 0; i < source.length; i += 1) {
            if (tempCompSeriesVisible(source[i])) {
                filtered.push(source[i])
            }
        }
        root.tempCompFilteredSeries = filtered
        root.tempCompLastChartRevision = revision
        root.tempCompLastFilterMask = filterMask
    }

    // Цель функции в извлечении signed-числа из текстовой метки, затем она возвращает только пригодное для ввода значение.
    function parseSignedIntText(value) {
        var normalized = String(value === undefined || value === null ? "" : value).trim()
        if (normalized.length <= 0) {
            return ""
        }
        var match = normalized.match(/^[-+]?\d+/)
        if (!match || match.length <= 0) {
            return ""
        }
        return String(match[0])
    }

    // Цель функции в синхронизации полей превью с данными контроллера, затем она обновляет K1/K0 без перезаписи активного ввода.
    function syncLinearPreviewFields(forceUpdate) {
        if (!root.appController) {
            return
        }
        var force = (forceUpdate === true)
        if (force || !tempCompPreviewK1Field.activeFocus) {
            tempCompPreviewK1Field.text = String(root.appController.calibrationTempCompLinearPreviewK1Text)
        }
        if (force || !tempCompPreviewK0Field.activeFocus) {
            tempCompPreviewK0Field.text = String(root.appController.calibrationTempCompLinearPreviewK0Text)
        }
    }

    // Цель функции в локальном запуске пересчета графика, затем она передает K1/K0 из полей в preview-слот контроллера.
    function applyLinearPreviewFromFields() {
        if (!root.appController) {
            return
        }
        root.appController.setCalibrationTempCompLinearPreview(
            tempCompPreviewK1Field.text,
            tempCompPreviewK0Field.text
        )
    }

    // Цель функции в быстром заполнении превью текущими коэффициентами, затем она сразу запускает пересчет графика и метрик.
    function fillLinearPreviewFromCurrent() {
        if (!root.appController) {
            return
        }
        var currentK1 = parseSignedIntText(root.appController.calibrationTempCompCurrentK1Text)
        var currentK0 = parseSignedIntText(root.appController.calibrationTempCompCurrentK0Text)
        tempCompPreviewK1Field.text = currentK1 !== "" ? currentK1 : String(root.appController.calibrationTempCompLinearPreviewK1Text)
        tempCompPreviewK0Field.text = currentK0 !== "" ? currentK0 : String(root.appController.calibrationTempCompLinearPreviewK0Text)
        applyLinearPreviewFromFields()
    }

    // Цель функции в быстром заполнении превью рекомендованными коэффициентами, затем она сразу запускает пересчет графика и метрик.
    function fillLinearPreviewFromRecommended() {
        if (!root.appController) {
            return
        }
        var recommendedK1 = parseSignedIntText(root.appController.calibrationTempCompRecommendedK1Text)
        var recommendedK0 = parseSignedIntText(root.appController.calibrationTempCompRecommendedK0Text)
        if (recommendedK1 !== "") {
            tempCompPreviewK1Field.text = recommendedK1
        }
        if (recommendedK0 !== "") {
            tempCompPreviewK0Field.text = recommendedK0
        }
        applyLinearPreviewFromFields()
    }

    // Цель функции в показе активного mode рядом с графиком, затем она читает значение mode из списка расширенных DID.
    function tempCompModeSummaryText() {
        if (!root.appController) {
            return "mode: нет данных"
        }
        var rows = root.appController.calibrationTempCompAdvancedRows
        for (var i = 0; i < rows.length; i += 1) {
            var row = rows[i]
            if (String(root.seriesField(row, "key", "")) === "mode") {
                var valueText = String(root.seriesField(row, "valueText", "не считан"))
                return "mode: " + valueText
            }
        }
        return "mode: не считан"
    }

    onAppControllerChanged: rebuildFilteredTempCompSeries(true)

    Layout.fillWidth: true
    implicitHeight: contentColumn.implicitHeight + (root.contentPadding * 2)
    clip: true

    ColumnLayout {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: root.contentPadding
        anchors.rightMargin: root.contentPadding
        anchors.topMargin: root.contentPadding
        anchors.bottomMargin: root.contentPadding
        spacing: 8

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: false
            Layout.preferredHeight: implicitHeight
            Layout.maximumHeight: implicitHeight
            radius: 10
            color: "#f8fbff"
            border.color: "#d6e2ef"
            implicitHeight: topPanelLayout.implicitHeight + 14

            ColumnLayout {
                id: topPanelLayout
                anchors.fill: parent
                anchors.margins: 7
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    FancyComboBox {
                        id: nodeSelector
                        Layout.fillWidth: true
                        Layout.preferredHeight: 32
                        model: root.appController ? root.appController.calibrationNodeOptions : []
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        onActivated: function(index) {
                            if (root.appController) {
                                nodeSelector.currentIndex = index
                                root.appController.setSelectedCalibrationNodeIndex(index)
                            }
                        }
                    }

                    FancyButton {
                        Layout.preferredWidth: 184
                        Layout.preferredHeight: 32
                        text: root.appController ? root.appController.calibrationActionText : "Начать калибровку"
                        tone: root.appController && root.appController.calibrationActive ? "#ef4444" : "#16a34a"
                        toneHover: root.appController && root.appController.calibrationActive ? "#dc2626" : "#15803d"
                        tonePressed: root.appController && root.appController.calibrationActive ? "#b91c1c" : "#166534"
                        enabled: root.appController !== null
                        onClicked: if (root.appController) root.appController.toggleCalibration()
                    }

                    FancyTextField {
                        id: pollIntervalField
                        Layout.preferredWidth: 88
                        Layout.preferredHeight: 32
                        text: root.appController ? String(root.appController.calibrationPollingIntervalMs) : "1000"
                        placeholderText: "Опрос"
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        validator: IntValidator { bottom: 100; top: 10000 }
                        onAccepted: if (root.appController) root.appController.setCalibrationPollingIntervalMs(text)
                    }

                    FancyButton {
                        Layout.preferredWidth: 78
                        Layout.preferredHeight: 32
                        text: "OK"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        enabled: root.appController !== null
                        onClicked: if (root.appController) root.appController.setCalibrationPollingIntervalMs(pollIntervalField.text)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Rectangle {
                        width: 10
                        height: 10
                        radius: 5
                        color: {
                            if (!root.appController) return "#94a3b8"
                            if (root.appController.calibrationVerifyInProgress) return "#f59e0b"
                            var status = root.appController.calibrationVerifyStatusText
                            if (status.indexOf("успешно") >= 0) return "#16a34a"
                            if (status.indexOf("не пройдена") >= 0) return "#ef4444"
                            return "#94a3b8"
                        }
                    }

                    BusyIndicator {
                        running: root.appController && root.appController.calibrationVerifyInProgress
                        visible: running
                        Layout.preferredWidth: 16
                        Layout.preferredHeight: 16
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.appController ? root.appController.calibrationVerifyStatusText : "Ожидание"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: false
            Layout.preferredHeight: implicitHeight
            Layout.maximumHeight: implicitHeight
            radius: 10
            color: "#f8fbff"
            border.color: "#d6e2ef"
            implicitHeight: backupTopLayout.implicitHeight + 14

            ColumnLayout {
                id: backupTopLayout
                anchors.fill: parent
                anchors.margins: 7
                spacing: 6

                Text {
                    Layout.fillWidth: true
                    text: "Резервные копии калибровки"
                    color: root.textMain
                    font.pixelSize: 12
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Text {
                        Layout.fillWidth: true
                        text: root.appController && root.appController.calibrationBackupAvailable
                              ? ("Текущая копия узла: 0%=" + root.appController.calibrationBackupLevel0Text + ", 100%=" + root.appController.calibrationBackupLevel100Text)
                              : "Локальная копия текущего узла не создана"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }

                    FancyButton {
                        Layout.preferredWidth: 188
                        Layout.preferredHeight: 30
                        text: "Создать копию (все узлы)"
                        tone: "#0f766e"
                        toneHover: "#115e59"
                        tonePressed: "#134e4a"
                        enabled: root.appController !== null
                        onClicked: if (root.appController) root.appController.createCalibrationBackup()
                    }

                    FancyButton {
                        Layout.preferredWidth: 182
                        Layout.preferredHeight: 30
                        text: "Восстановить"
                        tone: "#475569"
                        toneHover: "#334155"
                        tonePressed: "#1e293b"
                        enabled: root.appController && root.appController.calibrationBackupAvailable
                        onClicked: if (root.appController) root.appController.restoreCalibrationBackup()
                    }
                }
            }
        }

        SpoilerSection {
            id: levelCalibrationSpoiler
            Layout.fillWidth: true
            Layout.fillHeight: false
            Layout.preferredHeight: implicitHeight
            Layout.maximumHeight: implicitHeight
            title: "Калибровка уровней 0% и 100%"
            hintText: "Чтение и запись калибровочных точек уровня"
            cardColor: root.cardColor
            cardBorder: root.cardBorder
            textMain: root.textMain
            textSoft: root.textSoft
            accentColor: "#0284c7"
            expanded: false

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: false
                Layout.preferredHeight: implicitHeight
                Layout.maximumHeight: implicitHeight
                radius: 10
                color: "#f4f8fd"
                border.color: "#d6e2ef"
                implicitHeight: currentLevelRow.implicitHeight + 14

                RowLayout {
                    id: currentLevelRow
                    anchors.fill: parent
                    anchors.margins: 7
                    spacing: 8

                    Rectangle {
                        radius: 8
                        color: "#eef5ff"
                        border.color: "#d6e2ef"
                        implicitHeight: 34
                        implicitWidth: currentValueRow.implicitWidth + 16

                        RowLayout {
                            id: currentValueRow
                            anchors.centerIn: parent
                            spacing: 6

                            Text {
                                text: "Текущий"
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                            }

                            Text {
                                text: root.appController ? root.appController.calibrationCurrentLevelText : "-"
                                color: root.textMain
                                font.pixelSize: 18
                                font.bold: true
                                font.family: "Bahnschrift"
                            }
                        }
                    }

                    Rectangle {
                        width: 1
                        Layout.preferredHeight: 22
                        color: "#d6e2ef"
                    }

                    Rectangle {
                        radius: 8
                        color: "#ecfdf5"
                        border.color: "#bfe8d2"
                        implicitHeight: 34
                        implicitWidth: capturedValueRow.implicitWidth + 16

                        RowLayout {
                            id: capturedValueRow
                            anchors.centerIn: parent
                            spacing: 6

                            Text {
                                text: "Захват"
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                            }

                            Text {
                                text: root.appController ? root.appController.calibrationCapturedLevelText : "-"
                                color: "#0f766e"
                                font.pixelSize: 14
                                font.bold: true
                                font.family: "Bahnschrift"
                            }
                        }
                    }

                    Item { Layout.fillWidth: true }

                    FancyButton {
                        Layout.preferredWidth: 90
                        Layout.preferredHeight: 30
                        text: "-> 0%"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        enabled: root.appController && root.appController.calibrationCapturedLevelText !== "-"
                        onClicked: root.applyCapturedToField(custom0Field, custom0Switch)
                    }

                    FancyButton {
                        Layout.preferredWidth: 96
                        Layout.preferredHeight: 30
                        text: "-> 100%"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        enabled: root.appController && root.appController.calibrationCapturedLevelText !== "-"
                        onClicked: root.applyCapturedToField(custom100Field, custom100Switch)
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: false
                Layout.preferredHeight: Math.max(level0Layout.implicitHeight, level100Layout.implicitHeight) + 14
                Layout.maximumHeight: Layout.preferredHeight
                spacing: 8

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: implicitHeight
                    Layout.maximumHeight: implicitHeight
                    radius: 10
                    color: "#f8fbff"
                    border.color: "#d6e2ef"
                    implicitHeight: level0Layout.implicitHeight + 14

                    ColumnLayout {
                        id: level0Layout
                        anchors.fill: parent
                        anchors.margins: 7
                        spacing: 6

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            Text {
                                text: "0%"
                                color: root.textMain
                                font.pixelSize: 15
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            Rectangle {
                                radius: 7
                                color: root.appController && root.appController.calibrationWizardStage >= 2 ? "#dcfce7" : "#e2e8f0"
                                border.color: root.appController && root.appController.calibrationWizardStage >= 2 ? "#86efac" : "#cbd5e1"
                                implicitWidth: status0Text.implicitWidth + 12
                                implicitHeight: 22

                                Text {
                                    id: status0Text
                                    anchors.centerIn: parent
                                    text: root.appController && root.appController.calibrationWizardStage >= 4 ? "ОК" :
                                          (root.appController && root.appController.calibrationWizardStage >= 2 ? "Записан" : "Ожидание")
                                    color: root.appController && root.appController.calibrationWizardStage >= 2 ? "#166534" : "#475569"
                                    font.pixelSize: 10
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }
                            }

                            Item { Layout.fillWidth: true }

                            FancyButton {
                                Layout.preferredWidth: 100
                                Layout.preferredHeight: 30
                                text: "Прочитать"
                                tone: "#0f766e"
                                toneHover: "#115e59"
                                tonePressed: "#134e4a"
                                enabled: root.appController !== null
                                onClicked: if (root.appController) root.appController.readCalibrationLevel0()
                            }
                        }

                        Text {
                            text: "Сохранено: " + (root.appController ? root.appController.calibrationLevel0Text : "-")
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            FancySwitch {
                                id: custom0Switch
                                trackWidth: 40
                                trackHeight: 22
                            }

                            FancyTextField {
                                id: custom0Field
                                Layout.fillWidth: true
                                Layout.preferredHeight: 30
                                enabled: custom0Switch.checked
                                text: ""
                                placeholderText: "Текущее / вручную"
                                textColor: root.textMain
                                bgColor: root.inputBg
                                borderColor: root.inputBorder
                                focusBorderColor: root.inputFocus
                            }

                            FancyButton {
                                Layout.preferredWidth: 98
                                Layout.preferredHeight: 30
                                text: "Сохранить"
                                tone: "#0284c7"
                                toneHover: "#0369a1"
                                tonePressed: "#075985"
                                enabled: root.appController !== null
                                onClicked: if (root.appController) root.appController.saveCalibrationLevel0(custom0Switch.checked ? custom0Field.text : "")
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: implicitHeight
                    Layout.maximumHeight: implicitHeight
                    radius: 10
                    color: "#f8fbff"
                    border.color: "#d6e2ef"
                    implicitHeight: level100Layout.implicitHeight + 14

                    ColumnLayout {
                        id: level100Layout
                        anchors.fill: parent
                        anchors.margins: 7
                        spacing: 6

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            Text {
                                text: "100%"
                                color: root.textMain
                                font.pixelSize: 15
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            Rectangle {
                                radius: 7
                                color: root.appController && root.appController.calibrationWizardStage >= 3 ? "#dcfce7" : "#e2e8f0"
                                border.color: root.appController && root.appController.calibrationWizardStage >= 3 ? "#86efac" : "#cbd5e1"
                                implicitWidth: status100Text.implicitWidth + 12
                                implicitHeight: 22

                                Text {
                                    id: status100Text
                                    anchors.centerIn: parent
                                    text: root.appController && root.appController.calibrationWizardStage >= 4 ? "ОК" :
                                          (root.appController && root.appController.calibrationWizardStage >= 3 ? "Записан" : "Ожидание")
                                    color: root.appController && root.appController.calibrationWizardStage >= 3 ? "#166534" : "#475569"
                                    font.pixelSize: 10
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }
                            }

                            Item { Layout.fillWidth: true }

                            FancyButton {
                                Layout.preferredWidth: 100
                                Layout.preferredHeight: 30
                                text: "Прочитать"
                                tone: "#0f766e"
                                toneHover: "#115e59"
                                tonePressed: "#134e4a"
                                enabled: root.appController !== null
                                onClicked: if (root.appController) root.appController.readCalibrationLevel100()
                            }
                        }

                        Text {
                            text: "Сохранено: " + (root.appController ? root.appController.calibrationLevel100Text : "-")
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            FancySwitch {
                                id: custom100Switch
                                trackWidth: 40
                                trackHeight: 22
                            }

                            FancyTextField {
                                id: custom100Field
                                Layout.fillWidth: true
                                Layout.preferredHeight: 30
                                enabled: custom100Switch.checked
                                text: ""
                                placeholderText: "Текущее / вручную"
                                textColor: root.textMain
                                bgColor: root.inputBg
                                borderColor: root.inputBorder
                                focusBorderColor: root.inputFocus
                            }

                            FancyButton {
                                Layout.preferredWidth: 98
                                Layout.preferredHeight: 30
                                text: "Сохранить"
                                tone: "#0284c7"
                                toneHover: "#0369a1"
                                tonePressed: "#075985"
                                enabled: root.appController !== null
                                onClicked: if (root.appController) root.appController.saveCalibrationLevel100(custom100Switch.checked ? custom100Field.text : "")
                            }
                        }
                    }
                }
            }

        }

        SpoilerSection {
            id: tempCompSpoiler
            Layout.fillWidth: true
            Layout.fillHeight: expanded
            Layout.minimumHeight: 44
            contentFillAvailableHeight: true
            title: "Температурная компенсация"
            hintText: "Офлайн-анализ CSV/XLSX и настройка K1/K0 + segmented heat/cool"
            cardColor: root.cardColor
            cardBorder: root.cardBorder
            textMain: root.textMain
            textSoft: root.textSoft
            accentColor: "#0284c7"
            expanded: false

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 320
                Layout.preferredHeight: -1
                Layout.maximumHeight: 16777215
                clip: true
                radius: 10
                color: "#f8fbff"
                border.color: "#d6e2ef"

                Flickable {
                    id: tempCompFlick
                    anchors.fill: parent
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    contentWidth: width
                    contentHeight: tempCompLayout.implicitHeight + 14

                    ScrollBar.vertical: ScrollBar {
                        id: tempCompVerticalScrollBar
                        policy: ScrollBar.AsNeeded
                        width: root.tempCompScrollBarWidth
                        implicitWidth: root.tempCompScrollBarWidth
                        minimumSize: 0.12
                    }

                    ScrollBar.horizontal: ScrollBar {
                        policy: ScrollBar.AlwaysOff
                    }

                    ColumnLayout {
                        id: tempCompLayout
                        x: 7
                        y: 7
                        width: Math.max(0, tempCompFlick.width - (root.tempCompScrollBarWidth + 12))
                        spacing: 6


                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Rectangle {
                            radius: 7
                            color: "#ecfdf5"
                            border.color: "#bfe8d2"
                            implicitHeight: 22
                            implicitWidth: sampleCounterText.implicitWidth + 12

                            Text {
                                id: sampleCounterText
                                anchors.centerIn: parent
                                text: root.appController ? ("Точек: " + root.appController.calibrationTempCompSampleCount) : "Точек: 0"
                                color: "#166534"
                                font.pixelSize: 10
                                font.bold: true
                                font.family: "Bahnschrift"
                            }
                        }

                        Text {
                            Layout.preferredWidth: 170
                            text: "Узел: " + (root.appController ? root.appController.calibrationSelectedNodeText : "Авто")
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }

                        Item { Layout.preferredWidth: 8 }

                        Text {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 260
                            text: "Подробный статус расчета и рекомендуемые параметры смотрите в спойлере «Итог офлайн-анализа»."
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                            maximumLineCount: 3
                            elide: Text.ElideRight
                            horizontalAlignment: Text.AlignRight
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 7
                        color: "#eef6ff"
                        border.color: "#c7d9ee"
                        implicitHeight: 44

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 4
                            spacing: 6

                            Text {
                                Layout.preferredWidth: 122
                                text: "Набор CSV/XLSX:"
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                                verticalAlignment: Text.AlignVCenter
                            }

                            FancyComboBox {
                                id: tempCompDatasetSelector
                                Layout.fillWidth: true
                                Layout.preferredHeight: 30
                                model: root.appController ? root.appController.calibrationTempCompDatasetOptions : []
                                currentIndex: root.appController ? root.appController.selectedCalibrationTempCompDatasetIndex : -1
                                enabled: root.appController && model && model.length > 0
                                textColor: root.textMain
                                bgColor: root.inputBg
                                borderColor: root.inputBorder
                                focusBorderColor: root.inputFocus
                                onActivated: if (root.appController && index >= 0) {
                                    root.appController.setSelectedCalibrationTempCompDatasetIndex(index)
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 7
                        color: "#eef6ff"
                        border.color: "#c7d9ee"
                        implicitHeight: 44

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 4
                            spacing: 6

                            FancyButton {
                                Layout.preferredWidth: 138
                                Layout.preferredHeight: 28
                                text: "Загрузить CSV/XLSX"
                                tone: "#0284c7"
                                toneHover: "#0369a1"
                                tonePressed: "#075985"
                                enabled: root.appController !== null
                                onClicked: tempCompCsvFileDialog.open()
                            }

                            FancyButton {
                                Layout.preferredWidth: 106
                                Layout.preferredHeight: 28
                                text: "Очистить"
                                tone: "#475569"
                                toneHover: "#334155"
                                tonePressed: "#1e293b"
                                enabled: root.appController !== null
                                onClicked: if (root.appController) root.appController.clearCalibrationTempCompSamples()
                            }

                            FancyButton {
                                Layout.preferredWidth: 186
                                Layout.preferredHeight: 28
                                text: "Чтение из текущего режима"
                                tone: "#0f766e"
                                toneHover: "#115e59"
                                tonePressed: "#134e4a"
                                enabled: root.appController !== null
                                onClicked: if (root.appController) {
                                    root.appController.readCalibrationTempCompFromMcu()
                                }
                            }

                            FancyButton {
                                Layout.preferredWidth: 198
                                Layout.preferredHeight: 28
                                text: "Записать рекомендации"
                                tone: "#16a34a"
                                toneHover: "#15803d"
                                tonePressed: "#166534"
                                enabled: root.appController && (
                                    root.appController.calibrationTempCompCanApplyNext
                                    || root.appController.calibrationTempCompCanApplyNextK0
                                )
                                onClicked: if (root.appController) root.appController.applyCalibrationTempCompRecommendations()
                            }

                            FancyButton {
                                Layout.preferredWidth: 254
                                Layout.preferredHeight: 28
                                text: "Подогнать K0 к 0% (текущая T)"
                                tone: "#b45309"
                                toneHover: "#92400e"
                                tonePressed: "#78350f"
                                enabled: root.appController !== null
                                onClicked: if (root.appController) root.appController.autoAdjustCalibrationTempCompK0ForCurrentPoint()
                            }

                            Item { Layout.fillWidth: true }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Rectangle {
                            width: 10
                            height: 10
                            radius: 5
                            color: {
                                if (!root.appController) return "#94a3b8"
                                return root.appController.calibrationTempCompOperationBusy ? "#f59e0b" : "#16a34a"
                            }
                        }

                        BusyIndicator {
                            running: root.appController && root.appController.calibrationTempCompOperationBusy
                            visible: running
                            Layout.preferredWidth: 16
                            Layout.preferredHeight: 16
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.appController ? root.appController.calibrationTempCompOperationText : "Ожидание операций."
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        visible: root.appController !== null

                        ProgressBar {
                            Layout.fillWidth: true
                            from: 0
                            to: 100
                            value: root.appController ? root.appController.calibrationTempCompOperationProgressPercent : 0
                            indeterminate: root.appController ? (
                                !root.appController.calibrationTempCompOperationProgressDeterminate
                                && root.appController.calibrationTempCompOperationBusy
                            ) : false
                            visible: root.appController ? (
                                root.appController.calibrationTempCompOperationBusy
                                || root.appController.calibrationTempCompOperationProgressDeterminate
                            ) : false
                        }

                        Text {
                            Layout.preferredWidth: 42
                            horizontalAlignment: Text.AlignRight
                            text: root.appController && root.appController.calibrationTempCompOperationProgressDeterminate
                                ? (root.appController.calibrationTempCompOperationProgressPercent + "%")
                                : ""
                            color: root.textSoft
                            font.pixelSize: 10
                            font.family: "Bahnschrift"
                            visible: root.appController && root.appController.calibrationTempCompOperationProgressDeterminate
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Базовый поток: загрузить CSV/XLSX -> проверить график -> записать рекомендации. Ручные DID доступны в расширенном блоке."
                        color: root.textSoft
                        font.pixelSize: 10
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }


                    SpoilerSection {
                        id: tempCompSummarySpoiler
                        Layout.fillWidth: true
                        Layout.fillHeight: false
                        title: "Итог офлайн-анализа"
                        hintText: "Подробный статус и рекомендуемые параметры для записи в МК"
                        cardColor: "#f0f7ff"
                        cardBorder: "#bfdbfe"
                        textMain: root.textMain
                        textSoft: root.textSoft
                        accentColor: "#0284c7"
                        expanded: false

                        Rectangle {
                            Layout.fillWidth: true
                            radius: 9
                            color: "#ffffff"
                            border.color: "#d6e2ef"
                            implicitHeight: summaryLayout.implicitHeight + 12

                            ColumnLayout {
                                id: summaryLayout
                                anchors.fill: parent
                                anchors.margins: 6
                                spacing: 6

                                Rectangle {
                                    Layout.fillWidth: true
                                    radius: 7
                                    color: "#f8fbff"
                                    border.color: "#d6e2ef"
                                    implicitHeight: summaryFactsGrid.implicitHeight + 10

                                    GridLayout {
                                        id: summaryFactsGrid
                                        anchors.fill: parent
                                        anchors.margins: 5
                                        columns: 2
                                        columnSpacing: 8
                                        rowSpacing: 3

                                        LabelValue {
                                            Layout.fillWidth: true
                                            labelText: "Набор"
                                            valueText: root.appController ? root.appController.calibrationTempCompSelectedDatasetText : "не выбран"
                                            labelColor: root.textSoft
                                            valueColor: root.textMain
                                            fontFamily: "Bahnschrift"
                                        }

                                        LabelValue {
                                            Layout.fillWidth: true
                                            labelText: "Точек"
                                            valueText: root.appController ? String(root.appController.calibrationTempCompSampleCount) : "0"
                                            labelColor: root.textSoft
                                            valueColor: root.textMain
                                            fontFamily: "Bahnschrift"
                                        }

                                        LabelValue {
                                            Layout.fillWidth: true
                                            labelText: "Температура"
                                            valueText: root.appController ? root.appController.calibrationTempCompTemperatureRangeText : "нет данных"
                                            labelColor: root.textSoft
                                            valueColor: root.textMain
                                            fontFamily: "Bahnschrift"
                                        }

                                        LabelValue {
                                            Layout.fillWidth: true
                                            labelText: "Период"
                                            valueText: root.appController ? root.appController.calibrationTempCompPeriodRangeText : "нет данных"
                                            labelColor: root.textSoft
                                            valueColor: root.textMain
                                            fontFamily: "Bahnschrift"
                                        }

                                        LabelValue {
                                            Layout.fillWidth: true
                                            labelText: "Уровень"
                                            valueText: root.appController ? root.appController.calibrationTempCompLevelRangeText : "нет данных"
                                            labelColor: root.textSoft
                                            valueColor: root.textMain
                                            fontFamily: "Bahnschrift"
                                        }

                                        LabelValue {
                                            Layout.fillWidth: true
                                            labelText: "Рекомендации"
                                            valueText: root.appController && (root.appController.calibrationTempCompCanApplyNext || root.appController.calibrationTempCompCanApplyNextK0)
                                                ? "готовы"
                                                : "нет"
                                            labelColor: root.textSoft
                                            valueColor: root.appController && (root.appController.calibrationTempCompCanApplyNext || root.appController.calibrationTempCompCanApplyNextK0)
                                                ? "#166534"
                                                : "#475569"
                                            fontFamily: "Bahnschrift"
                                        }
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Rectangle {
                                        Layout.fillWidth: true
                                        radius: 7
                                        color: "#eff6ff"
                                        border.color: "#bfdbfe"
                                        implicitHeight: k1SummaryLayout.implicitHeight + 10

                                        ColumnLayout {
                                            id: k1SummaryLayout
                                            anchors.fill: parent
                                            anchors.margins: 5
                                            spacing: 2

                                            Text {
                                                Layout.fillWidth: true
                                                text: "K1 (DID 0x001B)"
                                                color: "#1e3a8a"
                                                font.pixelSize: 11
                                                font.bold: true
                                                font.family: "Bahnschrift"
                                            }

                                            LabelValue {
                                                Layout.fillWidth: true
                                                labelText: "Текущее"
                                                valueText: root.appController ? root.appController.calibrationTempCompCurrentK1Text : "-"
                                                labelColor: root.textSoft
                                                valueColor: root.textMain
                                                fontFamily: "Bahnschrift"
                                            }

                                            LabelValue {
                                                Layout.fillWidth: true
                                                labelText: "Рекоменд."
                                                valueText: root.appController ? root.appController.calibrationTempCompRecommendedK1Text : "-"
                                                labelColor: root.textSoft
                                                valueColor: "#0f766e"
                                                fontFamily: "Bahnschrift"
                                            }

                                            LabelValue {
                                                Layout.fillWidth: true
                                                labelText: "Изменение"
                                                valueText: root.appController ? root.appController.calibrationTempCompDeltaK1Text : "-"
                                                labelColor: root.textSoft
                                                valueColor: root.textMain
                                                fontFamily: "Bahnschrift"
                                            }

                                            LabelValue {
                                                Layout.fillWidth: true
                                                labelText: "К записи"
                                                valueText: root.appController ? root.appController.calibrationTempCompNextK1Text : "-"
                                                labelColor: root.textSoft
                                                valueColor: "#166534"
                                                fontFamily: "Bahnschrift"
                                            }
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        radius: 7
                                        color: "#f0fdf4"
                                        border.color: "#bbf7d0"
                                        implicitHeight: k0SummaryLayout.implicitHeight + 10

                                        ColumnLayout {
                                            id: k0SummaryLayout
                                            anchors.fill: parent
                                            anchors.margins: 5
                                            spacing: 2

                                            Text {
                                                Layout.fillWidth: true
                                                text: "K0 (DID 0x001C)"
                                                color: "#14532d"
                                                font.pixelSize: 11
                                                font.bold: true
                                                font.family: "Bahnschrift"
                                            }

                                            LabelValue {
                                                Layout.fillWidth: true
                                                labelText: "Текущее"
                                                valueText: root.appController ? root.appController.calibrationTempCompCurrentK0Text : "-"
                                                labelColor: root.textSoft
                                                valueColor: root.textMain
                                                fontFamily: "Bahnschrift"
                                            }

                                            LabelValue {
                                                Layout.fillWidth: true
                                                labelText: "Рекоменд."
                                                valueText: root.appController ? root.appController.calibrationTempCompRecommendedK0Text : "-"
                                                labelColor: root.textSoft
                                                valueColor: "#0f766e"
                                                fontFamily: "Bahnschrift"
                                            }

                                            LabelValue {
                                                Layout.fillWidth: true
                                                labelText: "Изменение"
                                                valueText: root.appController ? root.appController.calibrationTempCompDeltaK0Text : "-"
                                                labelColor: root.textSoft
                                                valueColor: root.textMain
                                                fontFamily: "Bahnschrift"
                                            }

                                            LabelValue {
                                                Layout.fillWidth: true
                                                labelText: "К записи"
                                                valueText: root.appController ? root.appController.calibrationTempCompNextK0Text : "-"
                                                labelColor: root.textSoft
                                                valueColor: "#166534"
                                                fontFamily: "Bahnschrift"
                                            }
                                        }
                                    }
                                }

                            }
                        }
                    }


                    SpoilerSection {
                        id: tempCompAdvancedSpoiler
                        Layout.fillWidth: true
                        Layout.fillHeight: false
                        title: "Расширенные настройки (DID 0x001D..0x002D)"
                        hintText: "Ручной ввод K1/K0/zero trim и детальные DID по сегментной компенсации"
                        cardColor: "#f0fdf4"
                        cardBorder: "#bbf7d0"
                        textMain: root.textMain
                        textSoft: root.textSoft
                        accentColor: "#0f766e"
                        expanded: false

                        Rectangle {
                            Layout.fillWidth: true
                            radius: 9
                            color: "#ffffff"
                            border.color: "#d6e2ef"
                            implicitHeight: advancedCompLayout.implicitHeight + 12

                            ColumnLayout {
                                id: advancedCompLayout
                                anchors.fill: parent
                                anchors.margins: 6
                                spacing: 4

                                Text {
                                    Layout.fillWidth: true
                                    text: "Линейные коэффициенты"
                                    color: root.textSoft
                                    font.pixelSize: 11
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Text {
                                        Layout.preferredWidth: 140
                                        text: "K1 (DID 0x001B)"
                                        color: root.textSoft
                                        font.pixelSize: 11
                                        font.family: "Bahnschrift"
                                    }

                                    FancyTextField {
                                        id: tempCompK1Field
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 34
                                        placeholderText: "signed dec / 0xHEX"
                                        textColor: root.textMain
                                        bgColor: root.inputBg
                                        borderColor: root.inputBorder
                                        focusBorderColor: root.inputFocus
                                        onAccepted: if (root.appController) root.appController.writeCalibrationTempCompK1(text)
                                    }

                                    FancyButton {
                                        Layout.preferredWidth: 92
                                        Layout.preferredHeight: 32
                                        text: "Читать"
                                        tone: "#0f766e"
                                        toneHover: "#115e59"
                                        tonePressed: "#134e4a"
                                        enabled: root.appController !== null
                                        onClicked: if (root.appController) root.appController.readCalibrationTempCompK1()
                                    }

                                    FancyButton {
                                        Layout.preferredWidth: 96
                                        Layout.preferredHeight: 32
                                        text: "Записать"
                                        tone: "#0284c7"
                                        toneHover: "#0369a1"
                                        tonePressed: "#075985"
                                        enabled: root.appController !== null
                                        onClicked: if (root.appController) root.appController.writeCalibrationTempCompK1(tempCompK1Field.text)
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Text {
                                        Layout.preferredWidth: 140
                                        text: "K0 (DID 0x001C)"
                                        color: root.textSoft
                                        font.pixelSize: 11
                                        font.family: "Bahnschrift"
                                    }

                                    FancyTextField {
                                        id: tempCompK0Field
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 34
                                        placeholderText: "signed dec / 0xHEX"
                                        textColor: root.textMain
                                        bgColor: root.inputBg
                                        borderColor: root.inputBorder
                                        focusBorderColor: root.inputFocus
                                        onAccepted: if (root.appController) root.appController.writeCalibrationTempCompK0(text)
                                    }

                                    FancyButton {
                                        Layout.preferredWidth: 92
                                        Layout.preferredHeight: 32
                                        text: "Читать"
                                        tone: "#0f766e"
                                        toneHover: "#115e59"
                                        tonePressed: "#134e4a"
                                        enabled: root.appController !== null
                                        onClicked: if (root.appController) root.appController.readCalibrationTempCompK0()
                                    }

                                    FancyButton {
                                        Layout.preferredWidth: 96
                                        Layout.preferredHeight: 32
                                        text: "Записать"
                                        tone: "#0284c7"
                                        toneHover: "#0369a1"
                                        tonePressed: "#075985"
                                        enabled: root.appController !== null
                                        onClicked: if (root.appController) root.appController.writeCalibrationTempCompK0(tempCompK0Field.text)
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Text {
                                        Layout.preferredWidth: 140
                                        text: "Zero trim (0x002D)"
                                        color: root.textSoft
                                        font.pixelSize: 11
                                        font.family: "Bahnschrift"
                                    }

                                    FancyTextField {
                                        id: tempCompZeroTrimField
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 34
                                        placeholderText: "signed dec / 0xHEX"
                                        textColor: root.textMain
                                        bgColor: root.inputBg
                                        borderColor: root.inputBorder
                                        focusBorderColor: root.inputFocus
                                        onAccepted: if (root.appController) root.appController.writeCalibrationTempCompZeroTrim(text)
                                    }

                                    FancyButton {
                                        Layout.preferredWidth: 92
                                        Layout.preferredHeight: 32
                                        text: "Читать"
                                        tone: "#0f766e"
                                        toneHover: "#115e59"
                                        tonePressed: "#134e4a"
                                        enabled: root.appController !== null
                                        onClicked: if (root.appController) root.appController.readCalibrationTempCompZeroTrim()
                                    }

                                    FancyButton {
                                        Layout.preferredWidth: 96
                                        Layout.preferredHeight: 32
                                        text: "Записать"
                                        tone: "#0284c7"
                                        toneHover: "#0369a1"
                                        tonePressed: "#075985"
                                        enabled: root.appController !== null
                                        onClicked: if (root.appController) root.appController.writeCalibrationTempCompZeroTrim(tempCompZeroTrimField.text)
                                    }

                                    FancyButton {
                                        Layout.preferredWidth: 84
                                        Layout.preferredHeight: 32
                                        text: "Сброс"
                                        tone: "#475569"
                                        toneHover: "#334155"
                                        tonePressed: "#1e293b"
                                        enabled: root.appController !== null
                                        onClicked: if (root.appController) root.appController.resetCalibrationTempCompZeroTrim()
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8

                                    LabelValue {
                                        Layout.fillWidth: true
                                        labelText: "Текущее trim"
                                        valueText: root.appController ? root.appController.calibrationTempCompCurrentZeroTrimText : "-"
                                        labelColor: root.textSoft
                                        valueColor: root.textMain
                                        fontFamily: "Bahnschrift"
                                    }

                                    LabelValue {
                                        Layout.fillWidth: true
                                        labelText: "Рекоменд."
                                        valueText: root.appController ? root.appController.calibrationTempCompRecommendedZeroTrimText : "-"
                                        labelColor: root.textSoft
                                        valueColor: "#0f766e"
                                        fontFamily: "Bahnschrift"
                                    }

                                    LabelValue {
                                        Layout.fillWidth: true
                                        labelText: "Изменение"
                                        valueText: root.appController ? root.appController.calibrationTempCompDeltaZeroTrimText : "-"
                                        labelColor: root.textSoft
                                        valueColor: root.textMain
                                        fontFamily: "Bahnschrift"
                                    }

                                    LabelValue {
                                        Layout.fillWidth: true
                                        labelText: "К записи"
                                        valueText: root.appController ? root.appController.calibrationTempCompNextZeroTrimText : "-"
                                        labelColor: root.textSoft
                                        valueColor: "#166534"
                                        fontFamily: "Bahnschrift"
                                    }
                                }

                                LabelValue {
                                    Layout.fillWidth: true
                                    labelText: "Остаток после подгонки"
                                    valueText: root.appController ? root.appController.calibrationTempCompResidualZeroTrimText : "-"
                                    labelColor: root.textSoft
                                    valueColor: "#334155"
                                    fontFamily: "Bahnschrift"
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Автоподстройка zero trim меняет только DID 0x002D и не затрагивает K0/K1."
                                        color: root.textSoft
                                        font.pixelSize: 10
                                        font.family: "Bahnschrift"
                                        wrapMode: Text.WordWrap
                                    }

                                    FancyButton {
                                        Layout.preferredWidth: 206
                                        Layout.preferredHeight: 32
                                        text: "Подогнать zero trim к 0%"
                                        tone: "#0f766e"
                                        toneHover: "#115e59"
                                        tonePressed: "#134e4a"
                                        enabled: root.appController !== null
                                        onClicked: if (root.appController) root.appController.autoAdjustCalibrationTempCompZeroTrimForCurrentPoint()
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Каждая строка: чтение/запись DID. При загрузке CSV/XLSX автоматически рассчитываются рекомендации по 0x001D..0x002C. Режим (0x001D) выбирается из списка. Гистерезис (0x001E): единицы 0.1 °C, пример 5 = 0.5 °C."
                                        color: root.textSoft
                                        font.pixelSize: 10
                                        font.family: "Bahnschrift"
                                        wrapMode: Text.WordWrap
                                    }

                                    FancyButton {
                                        Layout.preferredWidth: 194
                                        Layout.preferredHeight: 32
                                        text: "Прочитать все DID"
                                        tone: "#0f766e"
                                        toneHover: "#115e59"
                                        tonePressed: "#134e4a"
                                        enabled: root.appController !== null
                                        onClicked: if (root.appController) root.appController.readCalibrationTempCompAdvanced()
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    radius: 6
                                    color: "#e2e8f0"
                                    border.color: "#cbd5e1"
                                    implicitHeight: 28

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.margins: 4
                                        spacing: 6

                                        Text {
                                            Layout.preferredWidth: root.advancedParamColumnWidth
                                            text: "Параметр"
                                            color: "#334155"
                                            font.pixelSize: 10
                                            font.bold: true
                                            font.family: "Bahnschrift"
                                            elide: Text.ElideRight
                                            verticalAlignment: Text.AlignVCenter
                                        }

                                        Text {
                                            Layout.preferredWidth: root.advancedRecommendedColumnWidth
                                            text: "Рекомендуемое (из CSV)"
                                            color: "#334155"
                                            font.pixelSize: 10
                                            font.bold: true
                                            font.family: "Bahnschrift"
                                            elide: Text.ElideRight
                                            verticalAlignment: Text.AlignVCenter
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            text: "Ввод и действия"
                                            color: "#334155"
                                            font.pixelSize: 10
                                            font.bold: true
                                            font.family: "Bahnschrift"
                                            elide: Text.ElideRight
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                }

                                Repeater {
                                    model: root.appController ? root.appController.calibrationTempCompAdvancedRows : []

                                    Rectangle {
                                        Layout.fillWidth: true
                                        radius: 7
                                        color: index % 2 === 0 ? "#f8fafc" : "#f1f5f9"
                                        border.color: "#dbe3ec"
                                        implicitHeight: advancedRowLayout.implicitHeight + 6

                                        RowLayout {
                                            id: advancedRowLayout
                                            anchors.fill: parent
                                            anchors.margins: 4
                                            spacing: 6

                                            function advancedFieldKey() {
                                                return String(root.seriesField(modelData, "key", ""))
                                            }

                                            function advancedIsModeField() {
                                                return advancedFieldKey() === "mode"
                                            }

                                            function advancedWriteValueText() {
                                                if (advancedIsModeField()) {
                                                    return String(modeValueCombo.currentIndex)
                                                }
                                                return advancedValueField.text
                                            }

                                            Text {
                                                Layout.preferredWidth: root.advancedParamColumnWidth
                                                Layout.preferredHeight: 30
                                                text: {
                                                    var title = String(root.seriesField(modelData, "label", "Параметр"))
                                                    var did = String(root.seriesField(modelData, "did", "0x----"))
                                                    return title + " (" + did + ")"
                                                }
                                                color: root.textMain
                                                font.pixelSize: 11
                                                font.family: "Bahnschrift"
                                                elide: Text.ElideRight
                                                verticalAlignment: Text.AlignVCenter
                                            }

                                            Text {
                                                Layout.preferredWidth: root.advancedRecommendedColumnWidth
                                                Layout.preferredHeight: 30
                                                text: String(root.seriesField(modelData, "recommendedText", "не рассчитан"))
                                                color: root.seriesField(modelData, "hasRecommended", false) ? "#0f766e" : "#94a3b8"
                                                font.pixelSize: 10
                                                font.family: "Bahnschrift"
                                                elide: Text.ElideRight
                                                verticalAlignment: Text.AlignVCenter
                                            }

                                            Item {
                                                Layout.fillWidth: true
                                                Layout.minimumWidth: 130
                                                Layout.preferredWidth: 180
                                                Layout.preferredHeight: 30

                                                FancyTextField {
                                                    id: advancedValueField
                                                    anchors.fill: parent
                                                    visible: !advancedRowLayout.advancedIsModeField()
                                                    placeholderText: String(root.seriesField(modelData, "placeholder", "dec/0xHEX"))
                                                    text: String(root.seriesField(modelData, "valueRawText", ""))
                                                    textColor: root.textMain
                                                    bgColor: root.inputBg
                                                    borderColor: root.inputBorder
                                                    focusBorderColor: root.inputFocus
                                                    onAccepted: if (root.appController) {
                                                        root.appController.writeCalibrationTempCompAdvancedParam(
                                                            String(root.seriesField(modelData, "key", "")),
                                                            text
                                                        )
                                                    }
                                                }

                                                FancyComboBox {
                                                    id: modeValueCombo
                                                    anchors.fill: parent
                                                    visible: advancedRowLayout.advancedIsModeField()
                                                    property bool previewReady: false
                                                    model: [
                                                        "0 - single (линейный K1)",
                                                        "1 - segmented (K1 по сегментам)",
                                                        "2 - segmented heat/cool (нагрев/охлаждение)"
                                                    ]
                                                    function pushPreviewToController() {
                                                        if (!root.appController) {
                                                            return
                                                        }
                                                        root.appController.setCalibrationTempCompAdvancedPreviewValue(
                                                            String(root.seriesField(modelData, "key", "")),
                                                            String(currentIndex)
                                                        )
                                                    }
                                                    currentIndex: {
                                                        var parsed = parseInt(String(root.seriesField(modelData, "valueRawText", "0")))
                                                        if (isNaN(parsed) || parsed < 0 || parsed > 2) {
                                                            return 0
                                                        }
                                                        return parsed
                                                    }
                                                    textColor: root.textMain
                                                    bgColor: root.inputBg
                                                    borderColor: root.inputBorder
                                                    focusBorderColor: root.inputFocus
                                                    onActivated: pushPreviewToController()
                                                    onCurrentIndexChanged: if (previewReady) pushPreviewToController()
                                                    Component.onCompleted: previewReady = true
                                                }
                                            }

                                            FancyButton {
                                                Layout.preferredWidth: root.advancedReadButtonWidth
                                                Layout.preferredHeight: 30
                                                text: "Читать"
                                                tone: "#0284c7"
                                                toneHover: "#0369a1"
                                                tonePressed: "#075985"
                                                enabled: root.appController !== null
                                                onClicked: if (root.appController) {
                                                    root.appController.readCalibrationTempCompAdvancedParam(
                                                        String(root.seriesField(modelData, "key", ""))
                                                    )
                                                }
                                            }

                                            FancyButton {
                                                Layout.preferredWidth: root.advancedWriteButtonWidth
                                                Layout.preferredHeight: 30
                                                text: "Записать"
                                                tone: "#16a34a"
                                                toneHover: "#15803d"
                                                tonePressed: "#166534"
                                                enabled: root.appController !== null
                                                onClicked: if (root.appController) {
                                                    root.appController.writeCalibrationTempCompAdvancedParam(
                                                        String(root.seriesField(modelData, "key", "")),
                                                        advancedRowLayout.advancedWriteValueText()
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6


                        GridLayout {
                            Layout.fillWidth: true
                            columns: 3
                            rowSpacing: 4
                            columnSpacing: 6

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Период, count"
                                valueText: root.appController ? root.appController.calibrationTempCompPeriodRangeText : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Темп., °C"
                                valueText: root.appController ? root.appController.calibrationTempCompTemperatureRangeText : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Уровень, %"
                                valueText: root.appController ? root.appController.calibrationTempCompLevelRangeText : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }
                        }


                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            rowSpacing: 4
                            columnSpacing: 6

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "K1 текущее"
                                valueText: root.appController ? root.appController.calibrationTempCompCurrentK1Text : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "K1 рекоменд."
                                valueText: root.appController ? root.appController.calibrationTempCompRecommendedK1Text : "-"
                                labelColor: root.textSoft
                                valueColor: "#0f766e"
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "dK1"
                                valueText: root.appController ? root.appController.calibrationTempCompDeltaK1Text : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "K1 к записи"
                                valueText: root.appController ? root.appController.calibrationTempCompNextK1Text : "-"
                                labelColor: root.textSoft
                                valueColor: "#166534"
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "K0 текущее"
                                valueText: root.appController ? root.appController.calibrationTempCompCurrentK0Text : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "K0 рекоменд."
                                valueText: root.appController ? root.appController.calibrationTempCompRecommendedK0Text : "-"
                                labelColor: root.textSoft
                                valueColor: "#0f766e"
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "dK0"
                                valueText: root.appController ? root.appController.calibrationTempCompDeltaK0Text : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "K0 к записи"
                                valueText: root.appController ? root.appController.calibrationTempCompNextK0Text : "-"
                                labelColor: root.textSoft
                                valueColor: "#166534"
                                fontFamily: "Bahnschrift"
                            }
                        }


                        SpoilerSection {
                            id: tempCompPreviewSpoiler
                            Layout.fillWidth: true
                            Layout.fillHeight: false
                            title: "Быстрое превью линейного режима"
                            hintText: "Локальный пересчет графиков без записи в МК"
                            cardColor: "#fffbeb"
                            cardBorder: "#fde68a"
                            textMain: root.textMain
                            textSoft: root.textSoft
                            accentColor: "#0f766e"
                            expanded: false

                            Rectangle {
                                Layout.fillWidth: true
                                radius: 8
                                color: "#eef3f9"
                                border.color: "#c9d6e8"
                                implicitHeight: linearPreviewPanelLayout.implicitHeight + 10

                                ColumnLayout {
                                    id: linearPreviewPanelLayout
                                    anchors.fill: parent
                                    anchors.margins: 5
                                    spacing: 5

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6

                                        Text {
                                            text: "Параметры превью"
                                            color: "#1f3a56"
                                            font.pixelSize: 11
                                            font.bold: true
                                            font.family: "Bahnschrift"
                                        }

                                        Item { Layout.fillWidth: true }

                                        Rectangle {
                                            radius: 5
                                            color: root.appController && root.appController.calibrationTempCompLinearPreviewEnabled ? "#dcfce7" : "#e2e8f0"
                                            border.color: root.appController && root.appController.calibrationTempCompLinearPreviewEnabled ? "#86efac" : "#cbd5e1"
                                            implicitWidth: 98
                                            implicitHeight: 20

                                            Text {
                                                anchors.centerIn: parent
                                                text: root.appController && root.appController.calibrationTempCompLinearPreviewEnabled ? "Превью: вкл" : "Превью: выкл"
                                                color: root.appController && root.appController.calibrationTempCompLinearPreviewEnabled ? "#166534" : "#475569"
                                                font.pixelSize: 9
                                                font.family: "Bahnschrift"
                                            }
                                        }
                                    }

                                    GridLayout {
                                        Layout.fillWidth: true
                                        columns: 4
                                        rowSpacing: 4
                                        columnSpacing: 6

                                        Text {
                                            Layout.alignment: Qt.AlignVCenter
                                            text: "K1"
                                            color: "#334155"
                                            font.pixelSize: 10
                                            font.family: "Bahnschrift"
                                        }

                                        FancyTextField {
                                            id: tempCompPreviewK1Field
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 34
                                            placeholderText: "signed dec/hex"
                                            textColor: root.textMain
                                            bgColor: root.inputBg
                                            borderColor: root.inputBorder
                                            focusBorderColor: root.inputFocus
                                            onAccepted: root.applyLinearPreviewFromFields()
                                        }

                                        Text {
                                            Layout.alignment: Qt.AlignVCenter
                                            text: "K0"
                                            color: "#334155"
                                            font.pixelSize: 10
                                            font.family: "Bahnschrift"
                                        }

                                        FancyTextField {
                                            id: tempCompPreviewK0Field
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 34
                                            placeholderText: "signed dec/hex"
                                            textColor: root.textMain
                                            bgColor: root.inputBg
                                            borderColor: root.inputBorder
                                            focusBorderColor: root.inputFocus
                                            onAccepted: root.applyLinearPreviewFromFields()
                                        }
                                    }

                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 6

                                        FancyButton {
                                            implicitWidth: 124
                                            height: 26
                                            text: "Применить превью"
                                            fontPixelSize: 12
                                            tone: "#0284c7"
                                            toneHover: "#0369a1"
                                            tonePressed: "#075985"
                                            enabled: root.appController !== null
                                            onClicked: root.applyLinearPreviewFromFields()
                                        }

                                    FancyButton {
                                        implicitWidth: 108
                                        height: 26
                                        text: "Сброс превью"
                                        fontPixelSize: 12
                                        tone: "#64748b"
                                        toneHover: "#475569"
                                        tonePressed: "#334155"
                                        enabled: root.appController && root.appController.calibrationTempCompLinearPreviewEnabled
                                        onClicked: if (root.appController) {
                                            root.appController.clearCalibrationTempCompLinearPreview()
                                            tempCompPreviewK1Field.focus = false
                                            tempCompPreviewK0Field.focus = false
                                            root.syncLinearPreviewFields(true)
                                        }
                                    }

                                    FancyButton {
                                        implicitWidth: 132
                                        height: 26
                                        text: "Текущие K1/K0"
                                        fontPixelSize: 12
                                        tone: "#0f766e"
                                        toneHover: "#115e59"
                                        tonePressed: "#134e4a"
                                        enabled: root.appController !== null
                                        onClicked: root.fillLinearPreviewFromCurrent()
                                    }

                                    FancyButton {
                                        implicitWidth: 146
                                        height: 26
                                        text: "Рекоменд. K1/K0"
                                        fontPixelSize: 12
                                        tone: "#166534"
                                        toneHover: "#14532d"
                                        tonePressed: "#052e16"
                                        enabled: root.appController !== null
                                        onClicked: root.fillLinearPreviewFromRecommended()
                                    }
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: root.appController ? root.appController.calibrationTempCompPreviewStatusText : "Ожидание превью."
                                    color: "#334155"
                                    font.pixelSize: 9
                                    font.family: "Bahnschrift"
                                    wrapMode: Text.WordWrap
                                    maximumLineCount: 2
                                    elide: Text.ElideRight
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 4
                                    visible: root.appController !== null

                                    BusyIndicator {
                                        running: root.appController ? root.appController.calibrationTempCompPreviewBusy : false
                                        visible: running
                                        Layout.preferredWidth: 14
                                        Layout.preferredHeight: 14
                                    }

                                    ProgressBar {
                                        Layout.fillWidth: true
                                        from: 0
                                        to: 100
                                        value: root.appController ? root.appController.calibrationTempCompPreviewProgressPercent : 0
                                        indeterminate: root.appController ? (
                                            !root.appController.calibrationTempCompPreviewProgressDeterminate
                                            && root.appController.calibrationTempCompPreviewBusy
                                        ) : false
                                        visible: root.appController ? (
                                            root.appController.calibrationTempCompPreviewBusy
                                            || root.appController.calibrationTempCompPreviewProgressDeterminate
                                        ) : false
                                    }

                                    Text {
                                        Layout.preferredWidth: 36
                                        horizontalAlignment: Text.AlignRight
                                        text: root.appController && root.appController.calibrationTempCompPreviewProgressDeterminate
                                            ? (root.appController.calibrationTempCompPreviewProgressPercent + "%")
                                            : ""
                                        color: "#475569"
                                        font.pixelSize: 9
                                        font.family: "Bahnschrift"
                                        visible: root.appController && root.appController.calibrationTempCompPreviewProgressDeterminate
                                    }
                                }

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Режим только для предпросмотра: значения в МК не записываются."
                                        color: "#64748b"
                                        font.pixelSize: 9
                                        font.family: "Bahnschrift"
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }


                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            rowSpacing: 3
                            columnSpacing: 6
                            z: 2

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Ошибк. min..max, %"
                                valueText: root.appController ? (root.appController.calibrationTempCompErrorRangeBeforeText + " -> " + root.appController.calibrationTempCompErrorRangeAfterText) : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Max|ошибк.|, %"
                                valueText: root.appController ? (root.appController.calibrationTempCompErrorMaxBeforeText + " -> " + root.appController.calibrationTempCompErrorMaxAfterText) : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "P95, %"
                                valueText: root.appController ? (root.appController.calibrationTempCompErrorP95BeforeText + " -> " + root.appController.calibrationTempCompErrorP95AfterText) : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Дрейф ур., %/°C"
                                valueText: root.appController ? (root.appController.calibrationTempCompSlopeBeforeLevelText + " -> " + root.appController.calibrationTempCompSlopeAfterLevelText) : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Дрейф пер., cnt/°C"
                                valueText: root.appController ? (root.appController.calibrationTempCompSlopeBeforePeriodText + " -> " + root.appController.calibrationTempCompSlopeAfterPeriodText) : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Снижение ур./пер."
                                valueText: root.appController ? (root.appController.calibrationTempCompReductionLevelText + " / " + root.appController.calibrationTempCompReductionPeriodText) : "-"
                                labelColor: root.textSoft
                                valueColor: "#166534"
                                fontFamily: "Bahnschrift"
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            z: 2

                            CheckBox {
                                text: "Сырой"
                                checked: root.tempCompShowRawSeries
                                onToggled: {
                                    root.tempCompShowRawSeries = checked
                                    root.rebuildFilteredTempCompSeries(true)
                                }
                            }

                            CheckBox {
                                text: "Текущий K1/K0"
                                checked: root.tempCompShowCurrentSeries
                                onToggled: {
                                    root.tempCompShowCurrentSeries = checked
                                    root.rebuildFilteredTempCompSeries(true)
                                }
                            }

                            CheckBox {
                                text: "Рекоменд. K1/K0"
                                checked: root.tempCompShowRecommendedSeries
                                onToggled: {
                                    root.tempCompShowRecommendedSeries = checked
                                    root.rebuildFilteredTempCompSeries(true)
                                }
                            }

                            Item { Layout.fillWidth: true }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        z: 2

                        Repeater {
                            model: root.tempCompFilteredSeries

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 5

                                Rectangle {
                                    width: 10
                                    height: 10
                                    radius: 5
                                    color: modelData && modelData.color ? modelData.color : "#64748b"
                                    border.color: "#cbd5e1"
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: {
                                        var baseText = String(root.seriesField(modelData, "node", "-"))
                                        var maxErrorText = String(root.seriesField(modelData, "maxAbsLevelText", ""))
                                        if (maxErrorText === "") {
                                            var maxErrorValue = root.seriesField(modelData, "maxAbsLevel", null)
                                            if (maxErrorValue !== null && maxErrorValue !== undefined) {
                                                maxErrorText = Number(maxErrorValue).toFixed(3) + " %"
                                            }
                                        }
                                        if (maxErrorText !== "") {
                                            return baseText + " | max|ошибка| = " + maxErrorText
                                        }
                                        return baseText
                                    }
                                    color: root.textSoft
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 7
                        color: "#f8fafc"
                        border.color: "#d6e2ef"
                        implicitHeight: graphSummaryLayout.implicitHeight + 10
                        z: 2

                        RowLayout {
                            id: graphSummaryLayout
                            anchors.fill: parent
                            anchors.margins: 5
                            spacing: 8

                            Text {
                                text: "Источник: " + (root.appController ? root.appController.calibrationTempCompSelectedDatasetText : "не выбран")
                                color: "#334155"
                                font.pixelSize: 10
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                                Layout.preferredWidth: 280
                            }

                            Text {
                                text: root.tempCompModeSummaryText()
                                color: "#334155"
                                font.pixelSize: 10
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                                Layout.preferredWidth: 180
                            }

                            Text {
                                text: "текущие K1/K0: "
                                    + (root.appController ? root.appController.calibrationTempCompCurrentK1Text : "-")
                                    + " / "
                                    + (root.appController ? root.appController.calibrationTempCompCurrentK0Text : "-")
                                color: "#334155"
                                font.pixelSize: 10
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }

                    TrendCanvas {
                        Layout.fillWidth: true
                        Layout.fillHeight: false
                        Layout.preferredHeight: 460
                        Layout.minimumHeight: 320
                        z: 0
                        overlayMode: true
                        resetViewportOnDataChange: false
                        xMajorTicks: 12
                        yMajorTicks: 12
                        adaptiveRenderFactor: 1
                        maxMarkerPoints: 1600
                        secondaryYAxisEnabled: root.appController ? root.appController.calibrationLevelBoundsKnown : false
                        secondaryYAxisTitle: "Уровень, %"
                        secondaryYAxisEmptyPeriod: root.appController ? root.appController.calibrationLevel0Value : NaN
                        secondaryYAxisFullPeriod: root.appController ? root.appController.calibrationLevel100Value : NaN
                        series: root.tempCompFilteredSeries
                        emptyText: "Загрузите CSV/XLSX из Коллектора для построения графика."
                        customXAxisTitle: "Температура, °C"
                        customYAxisTitle: "Период, count"
                        showPointLabels: false
                        smoothSeriesEnabled: false
                        smoothSeriesAlpha: 0.2
                        panelBg: "#ffffff"
                        panelBorder: "#d6e2ef"
                    }

                        Item {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 6
                        }
                    }
                }
            }

            FileDialog {
                id: tempCompCsvFileDialog
                title: "Выберите CSV/XLSX файл(ы) Коллектора"
                fileMode: FileDialog.OpenFiles
                nameFilters: ["Табличные файлы (*.csv *.xlsx)", "CSV файлы (*.csv)", "XLSX файлы (*.xlsx)", "Все файлы (*)"]

                onAccepted: {
                    if (!root.appController) {
                        return
                    }
                    // Преобразует URL/variant из FileDialog в строковый путь для Python-слота.
                    function asPathText(value) {
                        if (value && value.toString) {
                            return value.toString()
                        }
                        return String(value)
                    }
                    var files = []
                    if (selectedFiles && selectedFiles.length > 0) {
                        for (var i = 0; i < selectedFiles.length; i += 1) {
                            files.push(asPathText(selectedFiles[i]))
                        }
                    } else if (selectedFile) {
                        files = [asPathText(selectedFile)]
                    } else if (currentFile) {
                        files = [asPathText(currentFile)]
                    }
                    root.appController.loadCalibrationTempCompCsv(files)
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: !tempCompSpoiler.expanded
            Layout.minimumHeight: 0
            Layout.preferredHeight: tempCompSpoiler.expanded ? 0 : 1
            opacity: 0
            enabled: false
        }
    }

    Connections {
        target: root.appController

        function onCalibrationPollingIntervalChanged() {
            if (!pollIntervalField.activeFocus && root.appController) {
                pollIntervalField.text = String(root.appController.calibrationPollingIntervalMs)
            }
        }

        function onCalibrationNodeSelectionChanged() {
            if (!root.appController) {
                return
            }
            if (nodeSelector.currentIndex !== root.appController.selectedCalibrationNodeIndex) {
                nodeSelector.currentIndex = root.appController.selectedCalibrationNodeIndex
            }
        }

        function onCalibrationTempCompChanged() {
            if (!root.appController) {
                return
            }
            if (tempCompDatasetSelector.currentIndex !== root.appController.selectedCalibrationTempCompDatasetIndex) {
                tempCompDatasetSelector.currentIndex = root.appController.selectedCalibrationTempCompDatasetIndex
            }
            if (!tempCompK1Field.activeFocus) {
                var currentK1 = root.appController.calibrationTempCompCurrentK1Text
                tempCompK1Field.text = (currentK1 && currentK1 !== "-") ? currentK1 : ""
            }
            if (!tempCompK0Field.activeFocus) {
                var currentK0 = root.appController.calibrationTempCompCurrentK0Text
                tempCompK0Field.text = (currentK0 && currentK0 !== "-") ? currentK0 : ""
            }
            if (!tempCompZeroTrimField.activeFocus) {
                var currentZeroTrim = root.appController.calibrationTempCompCurrentZeroTrimText
                tempCompZeroTrimField.text = (currentZeroTrim && currentZeroTrim !== "-") ? currentZeroTrim : ""
            }
            root.syncLinearPreviewFields()
            root.rebuildFilteredTempCompSeries()
        }
    }

    Component.onCompleted: {
        if (root.appController) {
            nodeSelector.currentIndex = root.appController.selectedCalibrationNodeIndex
            tempCompDatasetSelector.currentIndex = root.appController.selectedCalibrationTempCompDatasetIndex
            var currentK1 = root.appController.calibrationTempCompCurrentK1Text
            tempCompK1Field.text = (currentK1 && currentK1 !== "-") ? currentK1 : ""
            var currentK0 = root.appController.calibrationTempCompCurrentK0Text
            tempCompK0Field.text = (currentK0 && currentK0 !== "-") ? currentK0 : ""
            var currentZeroTrim = root.appController.calibrationTempCompCurrentZeroTrimText
            tempCompZeroTrimField.text = (currentZeroTrim && currentZeroTrim !== "-") ? currentZeroTrim : ""
            root.syncLinearPreviewFields()
            root.rebuildFilteredTempCompSeries(true)
        }
    }
}

