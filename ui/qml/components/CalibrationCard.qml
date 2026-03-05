import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

Card {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"
    readonly property int contentPadding: 10

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

    Layout.fillWidth: true
    implicitHeight: contentColumn.implicitHeight + (root.contentPadding * 2)

    ColumnLayout {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: root.contentPadding
        anchors.rightMargin: root.contentPadding
        anchors.topMargin: root.contentPadding
        spacing: 8

        Text {
            text: "Калибровка датчика"
            color: root.textMain
            font.pixelSize: 18
            font.bold: true
            font.family: "Bahnschrift"
        }

        Rectangle {
            Layout.fillWidth: true
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
                    text: "→ 0%"
                    tone: "#0284c7"
                    toneHover: "#0369a1"
                    tonePressed: "#075985"
                    enabled: root.appController && root.appController.calibrationCapturedLevelText !== "-"
                    onClicked: root.applyCapturedToField(custom0Field, custom0Switch)
                }

                FancyButton {
                    Layout.preferredWidth: 96
                    Layout.preferredHeight: 30
                    text: "→ 100%"
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
            spacing: 8

            Rectangle {
                Layout.fillWidth: true
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
    }

    Component.onCompleted: {
        if (root.appController) {
            nodeSelector.currentIndex = root.appController.selectedCalibrationNodeIndex
        }
    }
}
