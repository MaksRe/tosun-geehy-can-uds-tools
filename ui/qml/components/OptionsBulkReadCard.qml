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
    property var rowFormatByRowId: ({})
    property var rowEndianByRowId: ({})

    readonly property bool canStart: root.appController
                                     && root.appController.connected
                                     && root.appController.tracing
                                     && !root.appController.optionsBulkBusy
                                     && !root.appController.optionOperationBusy
    readonly property int delayMinMs: 0
    readonly property int delayMaxMs: 5000
    readonly property int delayStepMs: 10
    readonly property int tableGap: 6
    property int delayAdjustDirection: 0

    function currentDelayMs() {
        if (!root.appController) {
            return 100
        }
        return Number(root.appController.optionsBulkDelayMs)
    }

    function clampDelay(value) {
        var parsed = Number(value)
        if (isNaN(parsed)) {
            parsed = 100
        }
        if (parsed < root.delayMinMs) {
            parsed = root.delayMinMs
        }
        if (parsed > root.delayMaxMs) {
            parsed = root.delayMaxMs
        }
        return Math.round(parsed / root.delayStepMs) * root.delayStepMs
    }

    function applyDelay(value) {
        if (!root.appController) {
            return
        }
        root.appController.setOptionsBulkDelayMs(root.clampDelay(value))
    }

    function beginDelayAdjust(direction) {
        if (!root.appController || root.appController.optionsBulkBusy) {
            return
        }
        root.delayAdjustDirection = direction
        root.applyDelay(root.currentDelayMs() + (direction * root.delayStepMs))
    }

    function endDelayAdjust() {
        root.delayAdjustDirection = 0
    }

    function rowKey(rowData, rowIndex) {
        if (rowData && rowData.rowId !== undefined && rowData.rowId !== null) {
            return String(rowData.rowId)
        }
        return String(rowIndex)
    }

    function getRowFormat(rowKeyValue) {
        if (!rowKeyValue) {
            return 1
        }
        var value = rowFormatByRowId[rowKeyValue]
        if (value === undefined || value === null) {
            return 1
        }
        return Number(value)
    }

    function setRowFormat(rowKeyValue, value) {
        if (!rowKeyValue) {
            return
        }
        var next = {}
        for (var key in rowFormatByRowId) {
            next[key] = rowFormatByRowId[key]
        }
        next[rowKeyValue] = Number(value)
        rowFormatByRowId = next
    }

    function getRowEndian(rowKeyValue) {
        if (!rowKeyValue) {
            return 0
        }
        var value = rowEndianByRowId[rowKeyValue]
        if (value === undefined || value === null) {
            return 0
        }
        return Number(value)
    }

    function setRowEndian(rowKeyValue, value) {
        if (!rowKeyValue) {
            return
        }
        var next = {}
        for (var key in rowEndianByRowId) {
            next[key] = rowEndianByRowId[key]
        }
        next[rowKeyValue] = Number(value)
        rowEndianByRowId = next
    }

    function resetRowSelectorState() {
        rowFormatByRowId = ({})
        rowEndianByRowId = ({})
    }

    Timer {
        id: delayRepeatTimer
        interval: 120
        repeat: true
        running: root.delayAdjustDirection !== 0
        onTriggered: root.applyDelay(root.currentDelayMs() + (root.delayAdjustDirection * root.delayStepMs))
    }

    Layout.fillWidth: true
    implicitHeight: contentColumn.implicitHeight + 18

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        Text {
            text: "Массовое чтение DID"
            color: root.textMain
            font.pixelSize: 16
            font.bold: true
            font.family: "Bahnschrift"
        }

        Text {
            text: "Последовательно читает все DID с правом чтения и отображает результат в отдельной таблице."
            color: root.textSoft
            font.pixelSize: 11
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 10
            color: "#f6faff"
            border.color: "#d3e1ef"
            border.width: 1
            implicitHeight: 42

            RowLayout {
                anchors.fill: parent
                anchors.margins: 6
                spacing: 8

                Text {
                    text: "Пауза между DID"
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    Layout.preferredWidth: 118
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }

                Rectangle {
                    id: stepper
                    Layout.preferredWidth: 118
                    Layout.minimumWidth: 112
                    Layout.maximumWidth: 126
                    Layout.preferredHeight: 28
                    radius: 8
                    color: "#ffffff"
                    border.width: 1
                    border.color: "#c8d9ea"

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 2
                        spacing: 3

                        Rectangle {
                            id: minusButton
                            readonly property bool enabledState: root.appController
                                                                && !root.appController.optionsBulkBusy
                                                                && root.currentDelayMs() > root.delayMinMs
                            Layout.preferredWidth: 22
                            Layout.preferredHeight: 22
                            radius: 6
                            color: !enabledState ? "#e2e8f0" : (minusArea.pressed ? "#0f766e" : "#14b8a6")
                            border.width: 1
                            border.color: !enabledState ? "#cbd5e1" : "#0f766e"

                            Text {
                                anchors.centerIn: parent
                                text: "-"
                                color: "#ffffff"
                                font.pixelSize: 15
                                font.family: "Bahnschrift"
                                font.bold: true
                            }

                            MouseArea {
                                id: minusArea
                                anchors.fill: parent
                                enabled: minusButton.enabledState
                                onPressed: root.beginDelayAdjust(-1)
                                onReleased: root.endDelayAdjust()
                                onCanceled: root.endDelayAdjust()
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            text: String(root.currentDelayMs()) + " мс"
                            color: root.textMain
                            font.pixelSize: 12
                            font.family: "Consolas"
                            font.bold: true
                            elide: Text.ElideRight
                        }

                        Rectangle {
                            id: plusButton
                            readonly property bool enabledState: root.appController
                                                                && !root.appController.optionsBulkBusy
                                                                && root.currentDelayMs() < root.delayMaxMs
                            Layout.preferredWidth: 22
                            Layout.preferredHeight: 22
                            radius: 6
                            color: !enabledState ? "#e2e8f0" : (plusArea.pressed ? "#1d4ed8" : "#2563eb")
                            border.width: 1
                            border.color: !enabledState ? "#cbd5e1" : "#1e40af"

                            Text {
                                anchors.centerIn: parent
                                text: "+"
                                color: "#ffffff"
                                font.pixelSize: 15
                                font.family: "Bahnschrift"
                                font.bold: true
                            }

                            MouseArea {
                                id: plusArea
                                anchors.fill: parent
                                enabled: plusButton.enabledState
                                onPressed: root.beginDelayAdjust(1)
                                onReleased: root.endDelayAdjust()
                                onCanceled: root.endDelayAdjust()
                            }
                        }
                    }
                }

                Item { Layout.fillWidth: true }
            }
        }

        Flow {
            id: controlsFlow
            Layout.fillWidth: true
            spacing: 8
            flow: Flow.LeftToRight
            layoutDirection: Qt.LeftToRight

            readonly property bool stacked: width < 520
            readonly property real buttonWidth: stacked ? width : Math.floor((width - (spacing * 2)) / 3)

            FancyButton {
                width: controlsFlow.buttonWidth
                text: "Прочитать все DID"
                enabled: root.canStart
                tone: "#2563eb"
                toneHover: "#1d4ed8"
                tonePressed: "#1e40af"
                onClicked: if (root.appController) root.appController.startOptionsBulkReadAll()
            }

            FancyButton {
                width: controlsFlow.buttonWidth
                text: "Стоп"
                enabled: root.appController && root.appController.optionsBulkBusy
                tone: "#dc2626"
                toneHover: "#b91c1c"
                tonePressed: "#991b1b"
                onClicked: if (root.appController) root.appController.stopOptionsBulkReadAll()
            }

            FancyButton {
                width: controlsFlow.buttonWidth
                text: "Очистить"
                enabled: root.appController && !root.appController.optionsBulkBusy
                tone: "#64748b"
                toneHover: "#475569"
                tonePressed: "#334155"
                onClicked: {
                    root.resetRowSelectorState()
                    if (root.appController) {
                        root.appController.clearOptionsBulkRows()
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 8
            color: "#eef5ff"
            border.color: "#c9d8ec"
            border.width: 1
            implicitHeight: 50

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 6
                spacing: 2

                Text {
                    text: "Статус: " + (root.appController ? root.appController.optionsBulkStatusText : "-")
                    color: root.textMain
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }

                Text {
                    text: "Прогресс: " + (root.appController ? root.appController.optionsBulkProgressText : "0/0")
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Consolas"
                    Layout.fillWidth: true
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 360
            radius: 10
            color: "#f7fbff"
            border.color: "#d7e3ef"
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 6
                spacing: 4

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 24
                    radius: 6
                    color: "#e9f1fb"
                    border.width: 1
                    border.color: "#d2dfed"

                    RowLayout {
                        id: tableHeaderRow
                        anchors.fill: parent
                        anchors.leftMargin: 6
                        anchors.rightMargin: 6
                        spacing: root.tableGap

                        readonly property int didW: 84
                        readonly property int sizeW: 54
                        readonly property int statusW: 86
                        readonly property int formatW: 126
                        readonly property int endianW: 86
                        readonly property int fixedW: didW + sizeW + statusW + formatW + endianW + (root.tableGap * 6)
                        readonly property int flexW: Math.max(0, width - fixedW)
                        readonly property int nameW: Math.max(170, Math.min(320, Math.round(flexW * 0.28)))
                        readonly property int valueW: Math.max(260, flexW - nameW)

                        Text {
                            text: "DID"
                            color: "#4b6078"
                            font.pixelSize: 10
                            font.bold: true
                            font.family: "Bahnschrift"
                            Layout.preferredWidth: tableHeaderRow.didW
                            Layout.minimumWidth: tableHeaderRow.didW
                            verticalAlignment: Text.AlignVCenter
                        }

                        Text {
                            text: "Имя"
                            color: "#4b6078"
                            font.pixelSize: 10
                            font.bold: true
                            font.family: "Bahnschrift"
                            Layout.preferredWidth: tableHeaderRow.nameW
                            Layout.minimumWidth: tableHeaderRow.nameW
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }

                        Text {
                            text: "Размер"
                            color: "#4b6078"
                            font.pixelSize: 10
                            font.bold: true
                            font.family: "Bahnschrift"
                            Layout.preferredWidth: tableHeaderRow.sizeW
                            Layout.minimumWidth: tableHeaderRow.sizeW
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        Text {
                            text: "Статус"
                            color: "#4b6078"
                            font.pixelSize: 10
                            font.bold: true
                            font.family: "Bahnschrift"
                            Layout.preferredWidth: tableHeaderRow.statusW
                            Layout.minimumWidth: tableHeaderRow.statusW
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        Text {
                            text: "Формат"
                            color: "#4b6078"
                            font.pixelSize: 10
                            font.bold: true
                            font.family: "Bahnschrift"
                            Layout.preferredWidth: tableHeaderRow.formatW
                            Layout.minimumWidth: tableHeaderRow.formatW
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        Text {
                            text: "Порядок"
                            color: "#4b6078"
                            font.pixelSize: 10
                            font.bold: true
                            font.family: "Bahnschrift"
                            Layout.preferredWidth: tableHeaderRow.endianW
                            Layout.minimumWidth: tableHeaderRow.endianW
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }

                        Text {
                            text: "Значение"
                            color: "#4b6078"
                            font.pixelSize: 10
                            font.bold: true
                            font.family: "Bahnschrift"
                            Layout.preferredWidth: tableHeaderRow.valueW
                            Layout.minimumWidth: tableHeaderRow.valueW
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                    }
                }

                ListView {
                    id: bulkList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 3
                    model: root.appController ? root.appController.optionsBulkRows : []
                    onCountChanged: if (count === 0) root.resetRowSelectorState()
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        id: rowItem
                        width: bulkList.width
                        radius: 7
                        color: index % 2 === 0 ? "#f8fbff" : "#f1f6fc"
                        border.width: 1
                        border.color: "#d8e5f2"
                        implicitHeight: Math.max(44, Math.ceil(valueText.paintedHeight) + 14)
                        property bool hasValue: Boolean(modelData && modelData.hasValue)
                        property string rowKeyValue: root.rowKey(modelData, index)
                        property int formatIndex: rowItem.hasValue ? root.getRowFormat(rowItem.rowKeyValue) : 1
                        property int endianIndex: rowItem.hasValue ? root.getRowEndian(rowItem.rowKeyValue) : 0
                        property string formattedValue: {
                            if (!hasValue || !modelData) {
                                return modelData && modelData.details ? modelData.details : "-"
                            }
                            var isHex = formatIndex === 1
                            var isFloat = formatIndex === 2
                            var isAscii = formatIndex === 3
                            var isUtf8 = formatIndex === 4
                            var isBig = endianIndex === 1
                            if (isAscii) {
                                return modelData.valueAscii || "-"
                            }
                            if (isUtf8) {
                                return modelData.valueUtf8 || "-"
                            }
                            if (isFloat) {
                                return isBig
                                    ? (modelData.valueBeFloat || "-")
                                    : (modelData.valueLeFloat || "-")
                            }
                            if (isBig) {
                                return isHex
                                    ? (modelData.valueBeHex || "-")
                                    : (modelData.valueBeDec || "-")
                            }
                            return isHex
                                ? (modelData.valueLeHex || "-")
                                : (modelData.valueLeDec || "-")
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 6
                            anchors.rightMargin: 6
                            anchors.topMargin: 4
                            anchors.bottomMargin: 4
                            spacing: root.tableGap

                            Text {
                                text: modelData.did
                                color: root.textMain
                                font.pixelSize: 11
                                font.family: "Consolas"
                                Layout.preferredWidth: tableHeaderRow.didW
                                Layout.minimumWidth: tableHeaderRow.didW
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }

                            Text {
                                text: modelData.name
                                color: root.textMain
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                                Layout.preferredWidth: tableHeaderRow.nameW
                                Layout.minimumWidth: tableHeaderRow.nameW
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }

                            Text {
                                text: String(modelData.size)
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Consolas"
                                Layout.preferredWidth: tableHeaderRow.sizeW
                                Layout.minimumWidth: tableHeaderRow.sizeW
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }

                            Text {
                                text: modelData.status
                                color: modelData.color ? modelData.color : root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                                Layout.preferredWidth: tableHeaderRow.statusW
                                Layout.minimumWidth: tableHeaderRow.statusW
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }

                            Item {
                                Layout.preferredWidth: tableHeaderRow.formatW
                                Layout.minimumWidth: tableHeaderRow.formatW
                                Layout.preferredHeight: 28
                                Layout.alignment: Qt.AlignVCenter

                                FancyComboBox {
                                    anchors.fill: parent
                                    visible: rowItem.hasValue
                                    enabled: rowItem.hasValue
                                    model: ["DEC", "HEX", "FLOAT", "ASCII", "UTF-8"]
                                    currentIndex: rowItem.formatIndex
                                    textColor: "#1f2d3d"
                                    bgColor: "#ffffff"
                                    borderColor: "#c5d7e9"
                                    focusBorderColor: "#0ea5e9"
                                    popupColor: "#ffffff"
                                    popupBorderColor: "#bcd0e5"
                                    highlightedItemColor: "#dff1ff"
                                    normalItemTextColor: "#1f2d3d"
                                    highlightedItemTextColor: "#0f2a43"
                                    onActivated: root.setRowFormat(rowItem.rowKeyValue, currentIndex)
                                }
                            }

                            Item {
                                Layout.preferredWidth: tableHeaderRow.endianW
                                Layout.minimumWidth: tableHeaderRow.endianW
                                Layout.preferredHeight: 28
                                Layout.alignment: Qt.AlignVCenter

                                FancyComboBox {
                                    anchors.fill: parent
                                    visible: rowItem.hasValue
                                    enabled: rowItem.hasValue && rowItem.formatIndex <= 2
                                    opacity: rowItem.formatIndex <= 2 ? 1.0 : 0.45
                                    model: ["LE", "BE"]
                                    currentIndex: rowItem.endianIndex
                                    textColor: "#1f2d3d"
                                    bgColor: "#ffffff"
                                    borderColor: "#c5d7e9"
                                    focusBorderColor: "#0ea5e9"
                                    popupColor: "#ffffff"
                                    popupBorderColor: "#bcd0e5"
                                    highlightedItemColor: "#dff1ff"
                                    normalItemTextColor: "#1f2d3d"
                                    highlightedItemTextColor: "#0f2a43"
                                    onActivated: root.setRowEndian(rowItem.rowKeyValue, currentIndex)
                                }
                            }

                            Text {
                                id: valueText
                                text: rowItem.formattedValue
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Consolas"
                                Layout.preferredWidth: tableHeaderRow.valueW
                                Layout.minimumWidth: tableHeaderRow.valueW
                                wrapMode: Text.WrapAnywhere
                                elide: Text.ElideNone
                                verticalAlignment: Text.AlignVCenter
                            }
                        }

                        ToolTip.visible: hoverArea.containsMouse && modelData.details && String(modelData.details).length > 0
                        ToolTip.text: String(modelData.details || "")
                        ToolTip.delay: 450

                        MouseArea {
                            id: hoverArea
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.NoButton
                        }
                    }
                }
            }
        }
    }
}
