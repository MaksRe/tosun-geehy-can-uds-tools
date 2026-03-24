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
    readonly property int advancedParamColumnWidth: 250
    readonly property int advancedRecommendedColumnWidth: 260
    readonly property int advancedReadButtonWidth: 76
    readonly property int advancedWriteButtonWidth: 88
    property bool tempCompShowRawSeries: true
    property bool tempCompShowCurrentSeries: true
    property bool tempCompShowRecommendedSeries: true

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

    function filteredTempCompSeries() {
        if (!root.appController) {
            return []
        }
        var source = root.appController.calibrationTempCompTrendSeries
        var filtered = []
        for (var i = 0; i < source.length; i += 1) {
            if (tempCompSeriesVisible(source[i])) {
                filtered.push(source[i])
            }
        }
        return filtered
    }

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

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: false
            Layout.preferredHeight: implicitHeight
            Layout.maximumHeight: implicitHeight
            radius: 10
            color: "#f8fbff"
            border.color: "#d6e2ef"
            implicitHeight: backupRow.implicitHeight + 14

            RowLayout {
                id: backupRow
                anchors.fill: parent
                anchors.margins: 7
                spacing: 6

                Text {
                    Layout.fillWidth: true
                    text: root.appController && root.appController.calibrationBackupAvailable
                          ? ("Копия: 0%=" + root.appController.calibrationBackupLevel0Text + ", 100%=" + root.appController.calibrationBackupLevel100Text)
                          : "Копия не создана"
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }

                FancyButton {
                    Layout.preferredWidth: 172
                    Layout.preferredHeight: 30
                    text: "Создать копию"
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
                    tone: "#7c3aed"
                    toneHover: "#6d28d9"
                    tonePressed: "#5b21b6"
                    enabled: root.appController && root.appController.calibrationBackupAvailable
                    onClicked: if (root.appController) root.appController.restoreCalibrationBackup()
                }
            }
        }

        SpoilerSection {
            id: tempCompSpoiler
            Layout.fillWidth: true
            Layout.fillHeight: expanded
            Layout.minimumHeight: 44
            title: "Температурная компенсация"
            hintText: "Офлайн-анализ CSV и настройка K1/K0 + segmented heat/cool"
            cardColor: root.cardColor
            cardBorder: root.cardBorder
            textMain: root.textMain
            textSoft: root.textSoft
            accentColor: "#0284c7"
            expanded: false

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
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
                        policy: ScrollBar.AsNeeded
                    }

                    ScrollBar.horizontal: ScrollBar {
                        policy: ScrollBar.AlwaysOff
                    }

                    ColumnLayout {
                        id: tempCompLayout
                        x: 7
                        y: 7
                        width: Math.max(0, tempCompFlick.width - 14)
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

                            FancyButton {
                                Layout.preferredWidth: 138
                                Layout.preferredHeight: 28
                                text: "Загрузить CSV"
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
                                Layout.preferredWidth: 170
                                Layout.preferredHeight: 28
                                text: "Прочитать из МК"
                                tone: "#0f766e"
                                toneHover: "#115e59"
                                tonePressed: "#134e4a"
                                enabled: root.appController !== null
                                onClicked: if (root.appController) {
                                    root.appController.readCalibrationTempCompK1()
                                    root.appController.readCalibrationTempCompK0()
                                    root.appController.readCalibrationTempCompAdvanced()
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
                        text: "Базовый поток: загрузить CSV -> проверить график -> записать рекомендации. Ручные DID доступны в расширенном блоке."
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
                        cardColor: "#f4f8fd"
                        cardBorder: "#d6e2ef"
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
                                    implicitHeight: summaryStatusText.implicitHeight + 14

                                    Text {
                                        id: summaryStatusText
                                        anchors.fill: parent
                                        anchors.margins: 7
                                        text: root.appController ? root.appController.calibrationTempCompStatusText : "Ожидание CSV."
                                        color: root.textMain
                                        font.pixelSize: 11
                                        font.family: "Bahnschrift"
                                        wrapMode: Text.WordWrap
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

                                Text {
                                    Layout.fillWidth: true
                                    text: root.appController && (root.appController.calibrationTempCompCanApplyNext || root.appController.calibrationTempCompCanApplyNextK0)
                                        ? "Рекомендации готовы к записи. Кнопка «Записать рекомендации» записывает все доступные рассчитанные параметры по очереди."
                                        : "Рекомендации еще не готовы. Загрузите CSV и дождитесь расчета."
                                    color: root.textSoft
                                    font.pixelSize: 10
                                    font.family: "Bahnschrift"
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }

                    SpoilerSection {
                        id: tempCompAdvancedSpoiler
                        Layout.fillWidth: true
                        Layout.fillHeight: false
                        title: "Расширенные настройки (DID 0x001D..0x002C)"
                        hintText: "Ручной ввод K1/K0 и детальные DID по сегментной компенсации"
                        cardColor: "#f4f8fd"
                        cardBorder: "#d6e2ef"
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

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Text {
                                        Layout.preferredWidth: 140
                                        text: "K1 / K0"
                                        color: root.textSoft
                                        font.pixelSize: 11
                                        font.bold: true
                                        font.family: "Bahnschrift"
                                    }

                                    FancyTextField {
                                        id: tempCompK1Field
                                        Layout.preferredWidth: 180
                                        Layout.preferredHeight: 34
                                        placeholderText: "K1 (signed dec / 0xHEX)"
                                        textColor: root.textMain
                                        bgColor: root.inputBg
                                        borderColor: root.inputBorder
                                        focusBorderColor: root.inputFocus
                                        onAccepted: if (root.appController) root.appController.writeCalibrationTempCompK1(text)
                                    }

                                    FancyButton {
                                        Layout.preferredWidth: 106
                                        Layout.preferredHeight: 32
                                        text: "Записать K1"
                                        tone: "#0284c7"
                                        toneHover: "#0369a1"
                                        tonePressed: "#075985"
                                        enabled: root.appController !== null
                                        onClicked: if (root.appController) root.appController.writeCalibrationTempCompK1(tempCompK1Field.text)
                                    }

                                    FancyTextField {
                                        id: tempCompK0Field
                                        Layout.preferredWidth: 180
                                        Layout.preferredHeight: 34
                                        placeholderText: "K0 (signed dec / 0xHEX)"
                                        textColor: root.textMain
                                        bgColor: root.inputBg
                                        borderColor: root.inputBorder
                                        focusBorderColor: root.inputFocus
                                        onAccepted: if (root.appController) root.appController.writeCalibrationTempCompK0(text)
                                    }

                                    FancyButton {
                                        Layout.preferredWidth: 106
                                        Layout.preferredHeight: 32
                                        text: "Записать K0"
                                        tone: "#0284c7"
                                        toneHover: "#0369a1"
                                        tonePressed: "#075985"
                                        enabled: root.appController !== null
                                        onClicked: if (root.appController) root.appController.writeCalibrationTempCompK0(tempCompK0Field.text)
                                    }

                                    Item { Layout.fillWidth: true }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Text {
                                        Layout.fillWidth: true
                                        text: "Каждая строка: чтение/запись DID. При загрузке CSV автоматически рассчитываются рекомендации по 0x001D..0x002C. Режим (0x001D) выбирается из списка. Гистерезис (0x001E): единицы 0.1 °C, пример 5 = 0.5 °C."
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
                                        implicitHeight: advancedRowLayout.implicitHeight + 8

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
                                                Layout.preferredHeight: 32
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
                                                Layout.preferredHeight: 32
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
                                                Layout.preferredHeight: 34

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
                                                Layout.preferredHeight: 32
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
                                                Layout.preferredHeight: 32
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

                        Rectangle {
                            Layout.fillWidth: true
                            radius: 7
                            color: "#eff6ff"
                            border.color: "#bfdbfe"
                            implicitHeight: 28

                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                verticalAlignment: Text.AlignVCenter
                                text: "Этап 1. CSV"
                                color: "#1e3a8a"
                                font.pixelSize: 11
                                font.bold: true
                                font.family: "Bahnschrift"
                            }
                        }

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

                        Rectangle {
                            Layout.fillWidth: true
                            radius: 7
                            color: "#f0fdf4"
                            border.color: "#bbf7d0"
                            implicitHeight: 28

                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                verticalAlignment: Text.AlignVCenter
                                text: "Этап 2. K1/K0"
                                color: "#14532d"
                                font.pixelSize: 11
                                font.bold: true
                                font.family: "Bahnschrift"
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

                        Rectangle {
                            Layout.fillWidth: true
                            radius: 7
                            color: "#fff7ed"
                            border.color: "#fed7aa"
                            implicitHeight: 28

                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                verticalAlignment: Text.AlignVCenter
                                text: "Этап 3. Ошибка и дрейф"
                                color: "#9a3412"
                                font.pixelSize: 11
                                font.bold: true
                                font.family: "Bahnschrift"
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: 3
                            rowSpacing: 4
                            columnSpacing: 6

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Ошибка min..max, %"
                                valueText: root.appController ? (root.appController.calibrationTempCompErrorRangeBeforeText + " -> " + root.appController.calibrationTempCompErrorRangeAfterText) : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Max |ошибка|, %"
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
                                labelText: "Дрейф пер., count/°C"
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

                        Text {
                            Layout.fillWidth: true
                            color: root.textSoft
                            font.pixelSize: 10
                            font.family: "Bahnschrift"
                            text: "Формат метрик: текущее -> после рекомендаций. Цвета: красная/синяя/зеленая."
                            elide: Text.ElideRight
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12

                            CheckBox {
                                text: "Сырой"
                                checked: root.tempCompShowRawSeries
                                onToggled: root.tempCompShowRawSeries = checked
                            }

                            CheckBox {
                                text: "Текущий K1/K0"
                                checked: root.tempCompShowCurrentSeries
                                onToggled: root.tempCompShowCurrentSeries = checked
                            }

                            CheckBox {
                                text: "Рекоменд. K1/K0"
                                checked: root.tempCompShowRecommendedSeries
                                onToggled: root.tempCompShowRecommendedSeries = checked
                            }

                            Item { Layout.fillWidth: true }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3

                        Repeater {
                            model: root.filteredTempCompSeries()

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

                    TrendCanvas {
                        Layout.fillWidth: true
                        Layout.fillHeight: false
                        Layout.preferredHeight: Math.max(360, tempCompFlick.height * 0.58)
                        Layout.minimumHeight: 80
                        overlayMode: true
                        resetViewportOnDataChange: false
                        xMajorTicks: 12
                        yMajorTicks: 12
                        adaptiveRenderFactor: 1
                        maxMarkerPoints: 0
                        secondaryYAxisEnabled: root.appController ? root.appController.calibrationLevelBoundsKnown : false
                        secondaryYAxisTitle: "Уровень, %"
                        secondaryYAxisEmptyPeriod: root.appController ? root.appController.calibrationLevel0Value : NaN
                        secondaryYAxisFullPeriod: root.appController ? root.appController.calibrationLevel100Value : NaN
                        series: root.filteredTempCompSeries()
                        emptyText: "Загрузите CSV из Коллектора для построения графика."
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
                title: "Выберите CSV файл(ы) Коллектора"
                fileMode: FileDialog.OpenFiles
                nameFilters: ["CSV файлы (*.csv)", "Все файлы (*)"]

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
            Layout.preferredHeight: 0
            Layout.maximumHeight: tempCompSpoiler.expanded ? 0 : 16777215
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
            if (!tempCompK1Field.activeFocus) {
                var currentK1 = root.appController.calibrationTempCompCurrentK1Text
                tempCompK1Field.text = (currentK1 && currentK1 !== "-") ? currentK1 : ""
            }
            if (!tempCompK0Field.activeFocus) {
                var currentK0 = root.appController.calibrationTempCompCurrentK0Text
                tempCompK0Field.text = (currentK0 && currentK0 !== "-") ? currentK0 : ""
            }
        }
    }

    Component.onCompleted: {
        if (root.appController) {
            nodeSelector.currentIndex = root.appController.selectedCalibrationNodeIndex
            var currentK1 = root.appController.calibrationTempCompCurrentK1Text
            tempCompK1Field.text = (currentK1 && currentK1 !== "-") ? currentK1 : ""
            var currentK0 = root.appController.calibrationTempCompCurrentK0Text
            tempCompK0Field.text = (currentK0 && currentK0 !== "-") ? currentK0 : ""
        }
    }
}
