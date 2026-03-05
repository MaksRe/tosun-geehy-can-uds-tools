import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

Card {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property bool showCardHeader: true
    property bool compactMode: false
    readonly property int contentPadding: 14

    function fileNameFromPath(pathText) {
        var value = String(pathText || "")
        if (value.length === 0)
            return ""
        var normalized = value.replace(/\\/g, "/")
        var parts = normalized.split("/")
        return parts.length > 0 ? parts[parts.length - 1] : value
    }

    function programmingPrimaryText() {
        if (!root.appController)
            return "Ожидание"
        if (root.appController.firmwareLoading)
            return "Загрузка"
        if (root.appController.programmingActive)
            return "Активно"
        return root.appController.firmwarePath ? "BIN выбран" : "Нет BIN"
    }

    function programmingSecondaryText() {
        if (!root.appController || !root.appController.firmwarePath)
            return "Файл не выбран"
        return root.fileNameFromPath(root.appController.firmwarePath)
    }

    function programmingCompactText() {
        if (!root.appController)
            return "Программирование: ожидание"
        if (root.appController.firmwareLoading)
            return "Программирование: загрузка BIN"
        if (root.appController.programmingActive)
            return "Программирование: активно"
        return root.appController.firmwarePath ? "Программирование: BIN выбран" : "Программирование: BIN не выбран"
    }

    function calibrationPrimaryText() {
        if (!root.appController)
            return "Ожидание"
        if (root.appController.calibrationActive)
            return "Активна"
        return root.appController.calibrationSelectedNodeText || "-"
    }

    function calibrationSecondaryText() {
        if (!root.appController)
            return "Уровень: -"
        return "Уровень: " + root.appController.calibrationCurrentLevelText
    }

    function calibrationCompactText() {
        if (!root.appController)
            return "Калибровка: ожидание"
        if (root.appController.calibrationActive)
            return "Калибровка: активна"
        return "Калибровка: " + (root.appController.calibrationSelectedNodeText || "-")
    }

    function collectorPrimaryText() {
        if (!root.appController)
            return "Ожидание"
        if (!root.appController.collectorEnabled)
            return "Выключен"
        if (root.appController.collectorRecording)
            return "Запись"
        if (root.appController.collectorPaused)
            return "Пауза"
        return "Готов"
    }

    function collectorSecondaryText() {
        if (!root.appController)
            return "Узлов: 0"
        return "Узлов: " + root.appController.collectorNodes.length
    }

    function collectorCompactText() {
        if (!root.appController)
            return "Коллектор: ожидание"
        if (!root.appController.collectorEnabled)
            return "Коллектор: выключен"
        if (root.appController.collectorRecording)
            return "Коллектор: запись, узлов " + root.appController.collectorNodes.length
        if (root.appController.collectorPaused)
            return "Коллектор: пауза, узлов " + root.appController.collectorNodes.length
        return "Коллектор: готов, узлов " + root.appController.collectorNodes.length
    }

    function optionsPrimaryText() {
        if (!root.appController)
            return "Ожидание"
        if (root.appController.optionsBulkBusy)
            return "Чтение DID"
        if (root.appController.optionOperationBusy)
            return "Операция"
        return "Готово"
    }

    function optionsSecondaryText() {
        if (!root.appController)
            return "Узел: -"
        return "Узел: " + root.appController.optionsTargetNodeText
    }

    function optionsCompactText() {
        if (!root.appController)
            return "UDS: ожидание"
        if (root.appController.optionsBulkBusy)
            return "UDS: массовое чтение DID"
        if (root.appController.optionOperationBusy)
            return "UDS: операция выполняется"
        return "UDS: узел " + root.appController.optionsTargetNodeText
    }

    implicitHeight: contentColumn.implicitHeight + (contentPadding * 2)

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: root.contentPadding
        spacing: 10

        Text {
            text: "Текущая сводка"
            visible: root.showCardHeader
            color: root.textMain
            font.pixelSize: 20
            font.bold: true
            font.family: "Bahnschrift"
        }

        Loader {
            Layout.fillWidth: true
            sourceComponent: root.compactMode ? compactSummaryComponent : detailedSummaryComponent
        }
    }

    Component {
        id: compactSummaryComponent

        Flow {
            width: contentColumn.width
            spacing: 8

            StatusChip {
                label: root.programmingCompactText()
                chipColor: "#fff3d6"
                chipBorder: "#f4c86f"
                textColor: root.textMain
            }

            StatusChip {
                label: root.calibrationCompactText()
                chipColor: "#e7f8ef"
                chipBorder: "#88d4af"
                textColor: root.textMain
            }

            StatusChip {
                label: root.collectorCompactText()
                chipColor: "#e7f1ff"
                chipBorder: "#93c5fd"
                textColor: root.textMain
            }

            StatusChip {
                label: root.optionsCompactText()
                chipColor: "#f2ebff"
                chipBorder: "#c4b5fd"
                textColor: root.textMain
            }
        }
    }

    Component {
        id: detailedSummaryComponent

        GridLayout {
            width: contentColumn.width
            columns: width > 720 ? 2 : 1
            columnSpacing: 12
            rowSpacing: 10

            Rectangle {
                Layout.fillWidth: true
                radius: 10
                color: "#f7fbff"
                border.color: "#d6e2ef"
                border.width: 1
                implicitHeight: firmwareColumn.implicitHeight + 14

                ColumnLayout {
                    id: firmwareColumn
                    anchors.fill: parent
                    anchors.margins: 7
                    spacing: 4

                    Text {
                        text: "Программирование"
                        color: root.textSoft
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.programmingPrimaryText()
                        color: root.textMain
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.programmingSecondaryText()
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                radius: 10
                color: "#f7fbff"
                border.color: "#d6e2ef"
                border.width: 1
                implicitHeight: calibrationColumn.implicitHeight + 14

                ColumnLayout {
                    id: calibrationColumn
                    anchors.fill: parent
                    anchors.margins: 7
                    spacing: 4

                    Text {
                        text: "Калибровка"
                        color: root.textSoft
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.calibrationPrimaryText()
                        color: root.textMain
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.calibrationSecondaryText()
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                radius: 10
                color: "#f7fbff"
                border.color: "#d6e2ef"
                border.width: 1
                implicitHeight: collectorColumn.implicitHeight + 14

                ColumnLayout {
                    id: collectorColumn
                    anchors.fill: parent
                    anchors.margins: 7
                    spacing: 4

                    Text {
                        text: "Коллектор"
                        color: root.textSoft
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.collectorPrimaryText()
                        color: root.textMain
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.collectorSecondaryText()
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                radius: 10
                color: "#f7fbff"
                border.color: "#d6e2ef"
                border.width: 1
                implicitHeight: optionsColumn.implicitHeight + 14

                ColumnLayout {
                    id: optionsColumn
                    anchors.fill: parent
                    anchors.margins: 7
                    spacing: 4

                    Text {
                        text: "Параметры UDS"
                        color: root.textSoft
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.optionsPrimaryText()
                        color: root.textMain
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.optionsSecondaryText()
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }
}
