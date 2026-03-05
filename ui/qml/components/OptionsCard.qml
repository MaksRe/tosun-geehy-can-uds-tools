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
    property var historyFormatByRowId: ({})
    property var historyEndianByRowId: ({})

    readonly property bool controlsEnabled: root.appController
                                          && root.appController.connected
                                          && root.appController.tracing
                                          && !root.appController.optionOperationBusy
    readonly property int contentPadding: 14
    readonly property int colTimeWidth: 72
    readonly property int colActionWidth: 72
    readonly property int colDidWidth: 80
    readonly property int colResultWidth: 90
    readonly property int colFormatWidth: 128
    readonly property int colEndianWidth: 86
    property int lastHistoryCount: 0
    signal openBulkReadRequested()

    function historyRowKey(rowData, rowIndex) {
        if (rowData && rowData.rowId !== undefined && rowData.rowId !== null) {
            return String(rowData.rowId)
        }
        return String(rowIndex)
    }

    function historyGetFormat(rowKey) {
        if (!rowKey) {
            return 1
        }
        var value = historyFormatByRowId[rowKey]
        if (value === undefined || value === null) {
            return 1
        }
        return Number(value)
    }

    function historySetFormat(rowKey, value) {
        if (!rowKey) {
            return
        }
        var next = {}
        for (var key in historyFormatByRowId) {
            next[key] = historyFormatByRowId[key]
        }
        next[rowKey] = Number(value)
        historyFormatByRowId = next
    }

    function historyGetEndian(rowKey) {
        if (!rowKey) {
            return 0
        }
        var value = historyEndianByRowId[rowKey]
        if (value === undefined || value === null) {
            return 0
        }
        return Number(value)
    }

    function historySetEndian(rowKey, value) {
        if (!rowKey) {
            return
        }
        var next = {}
        for (var key in historyEndianByRowId) {
            next[key] = historyEndianByRowId[key]
        }
        next[rowKey] = Number(value)
        historyEndianByRowId = next
    }

    function resetHistorySelectorState() {
        historyFormatByRowId = ({})
        historyEndianByRowId = ({})
    }

    Layout.fillWidth: true
    implicitHeight: contentColumn.implicitHeight + (root.contentPadding * 2)

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: root.contentPadding
        spacing: 10

        Text {
            text: "Параметры UDS (Options)"
            color: root.textMain
            font.pixelSize: 20
            font.bold: true
            font.family: "Bahnschrift"
        }

        Text {
            text: "Чтение и запись DID параметров с указанием прав доступа"
            color: root.textSoft
            font.pixelSize: 12
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                text: "Целевой узел (SA)"
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                Layout.preferredWidth: 132
                verticalAlignment: Text.AlignVCenter
            }

            FancyComboBox {
                id: targetNodeCombo
                Layout.fillWidth: true
                model: root.appController ? root.appController.optionsTargetNodeItems : []
                currentIndex: root.appController ? root.appController.selectedOptionsTargetNodeIndex : 0
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
                onActivated: if (root.appController) root.appController.setSelectedOptionsTargetNodeIndex(currentIndex)
            }
        }

        Text {
            text: "Текущий SA для операций: " + (root.appController ? root.appController.optionsTargetNodeText : "-")
            color: root.textSoft
            font.pixelSize: 11
            font.family: "Consolas"
            Layout.fillWidth: true
            elide: Text.ElideRight
        }

        FancyComboBox {
            id: parameterCombo
            Layout.fillWidth: true
            model: root.appController ? root.appController.optionsParameterItems : []
            currentIndex: root.appController ? root.appController.selectedOptionsParameterIndex : -1
            textColor: root.textMain
            bgColor: root.inputBg
            borderColor: root.inputBorder
            focusBorderColor: root.inputFocus
            onActivated: if (root.appController) root.appController.setSelectedOptionsParameterIndex(currentIndex)
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 10
            color: "#f4f8fd"
            border.color: "#d6e2ef"
            border.width: 1
            implicitHeight: infoGrid.implicitHeight + 14

            GridLayout {
                id: infoGrid
                anchors.fill: parent
                anchors.margins: 7
                columns: 2
                rowSpacing: 4
                columnSpacing: 8

                Text { text: "DID"; color: root.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                Text { text: root.appController ? root.appController.selectedOptionDidText : "-"; color: root.textMain; font.pixelSize: 12; font.family: "Consolas"; elide: Text.ElideRight; Layout.fillWidth: true }

                Text { text: "Параметр"; color: root.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                Text { text: root.appController ? root.appController.selectedOptionNameText : "-"; color: root.textMain; font.pixelSize: 12; font.family: "Bahnschrift"; wrapMode: Text.WordWrap; Layout.fillWidth: true }

                Text { text: "Размер"; color: root.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                Text { text: root.appController ? root.appController.selectedOptionSizeText : "-"; color: root.textMain; font.pixelSize: 12; font.family: "Bahnschrift"; Layout.fillWidth: true }

                Text { text: "Доступ"; color: root.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                Text { text: root.appController ? root.appController.selectedOptionAccessText : "-"; color: root.textMain; font.pixelSize: 12; font.family: "Bahnschrift"; Layout.fillWidth: true }

                Text { text: "Примечание"; color: root.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                Text { text: root.appController ? root.appController.selectedOptionNoteText : ""; color: root.textSoft; font.pixelSize: 11; font.family: "Bahnschrift"; wrapMode: Text.WordWrap; Layout.fillWidth: true }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            FancyTextField {
                id: writeField
                Layout.fillWidth: true
                placeholderText: "Значение для записи (dec или 0xHEX)"
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
                enabled: root.controlsEnabled && root.appController && root.appController.selectedOptionCanWrite
            }

            FancyButton {
                Layout.preferredWidth: 138
                text: root.appController && root.appController.optionOperationBusy ? "Чтение..." : "Прочитать"
                enabled: root.controlsEnabled && root.appController && root.appController.selectedOptionCanRead
                loading: root.appController ? root.appController.optionOperationBusy : false
                tone: "#2563eb"
                toneHover: "#1d4ed8"
                tonePressed: "#1e40af"
                onClicked: if (root.appController) root.appController.readSelectedOption()
            }

            FancyButton {
                Layout.preferredWidth: 128
                text: root.appController && root.appController.optionOperationBusy ? "Запись..." : "Записать"
                enabled: root.controlsEnabled && root.appController && root.appController.selectedOptionCanWrite
                loading: root.appController ? root.appController.optionOperationBusy : false
                tone: "#0ea5a4"
                toneHover: "#0f766e"
                tonePressed: "#115e59"
                onClicked: if (root.appController) root.appController.writeSelectedOption(writeField.text)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 10
            color: "#eef5ff"
            border.color: "#c9d8ec"
            border.width: 1
            implicitHeight: 58

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 6
                spacing: 2

                Text {
                    text: "Статус операции: " + (root.appController ? root.appController.optionOperationStatusText : "-")
                    color: root.textMain
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }

                Text {
                    text: "Значение: " + (root.appController ? root.appController.selectedOptionValueText : "-")
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Consolas"
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                Text {
                    text: "RAW: " + (root.appController ? root.appController.selectedOptionRawHexText : "-")
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Consolas"
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 280
            Layout.preferredHeight: 340
            radius: 10
            color: "#f7fbff"
            border.color: "#d7e3ef"
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 6
                spacing: 4

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Text {
                        text: "Журнал операций UDS"
                        color: root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                    }

                    Item { Layout.fillWidth: true }

                    FancyButton {
                        Layout.preferredWidth: 210
                        Layout.preferredHeight: 26
                        text: "Массовое чтение DID"
                        tone: "#2563eb"
                        toneHover: "#1d4ed8"
                        tonePressed: "#1e40af"
                        onClicked: root.openBulkReadRequested()
                    }

                    FancyButton {
                        Layout.preferredWidth: 120
                        Layout.preferredHeight: 26
                        text: "Очистить журнал"
                        tone: "#64748b"
                        toneHover: "#475569"
                        tonePressed: "#334155"
                        onClicked: {
                            root.resetHistorySelectorState()
                            if (root.appController) {
                                root.appController.clearOptionHistory()
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 24
                    radius: 6
                    color: "#e9f1fb"
                    border.width: 1
                    border.color: "#d2dfed"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 6
                        anchors.rightMargin: 6
                        spacing: 6

                        Text { text: "Время"; color: "#4b6078"; font.pixelSize: 10; font.family: "Bahnschrift"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; Layout.preferredWidth: root.colTimeWidth; Layout.minimumWidth: root.colTimeWidth; Layout.alignment: Qt.AlignVCenter }
                        Text { text: "Операция"; color: "#4b6078"; font.pixelSize: 10; font.family: "Bahnschrift"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; Layout.preferredWidth: root.colActionWidth; Layout.minimumWidth: root.colActionWidth; Layout.alignment: Qt.AlignVCenter }
                        Text { text: "DID"; color: "#4b6078"; font.pixelSize: 10; font.family: "Bahnschrift"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; Layout.preferredWidth: root.colDidWidth; Layout.minimumWidth: root.colDidWidth; Layout.alignment: Qt.AlignVCenter }
                        Text { text: "Статус"; color: "#4b6078"; font.pixelSize: 10; font.family: "Bahnschrift"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; Layout.preferredWidth: root.colResultWidth; Layout.minimumWidth: root.colResultWidth; Layout.alignment: Qt.AlignVCenter }
                        Text { text: "Формат"; color: "#4b6078"; font.pixelSize: 10; font.family: "Bahnschrift"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; Layout.preferredWidth: root.colFormatWidth; Layout.minimumWidth: root.colFormatWidth; Layout.alignment: Qt.AlignVCenter }
                        Text { text: "Порядок"; color: "#4b6078"; font.pixelSize: 10; font.family: "Bahnschrift"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; Layout.preferredWidth: root.colEndianWidth; Layout.minimumWidth: root.colEndianWidth; Layout.alignment: Qt.AlignVCenter }
                        Text { text: "Значение"; color: "#4b6078"; font.pixelSize: 10; font.family: "Bahnschrift"; font.bold: true; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; Layout.fillWidth: true; Layout.alignment: Qt.AlignVCenter }
                    }
                }

                ListView {
                    id: historyList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 3
                    model: root.appController ? root.appController.optionOperationHistory : []
                    onCountChanged: {
                        if (count > 0) {
                            Qt.callLater(function() {
                                historyList.currentIndex = count - 1
                                historyList.positionViewAtEnd()
                            })
                        } else {
                            var actualCount = 0
                            if (root.appController && root.appController.optionOperationHistory) {
                                actualCount = root.appController.optionOperationHistory.length
                            }
                            if (root.lastHistoryCount > 0 && actualCount === 0) {
                                root.resetHistorySelectorState()
                            }
                        }
                        root.lastHistoryCount = count
                    }

                    delegate: Rectangle {
                        id: rowItem
                        width: historyList.width
                        height: Math.max(48, Math.ceil(valueText.paintedHeight) + 12)
                        radius: 8
                        clip: true
                        color: index % 2 === 0 ? "#f8fbff" : "#f1f6fc"
                        border.width: 1
                        border.color: "#d8e5f2"
                        property bool hasValue: Boolean(modelData && modelData.hasValue)
                        property string rowKey: root.historyRowKey(modelData, index)
                        property int formatIndex: rowItem.hasValue ? root.historyGetFormat(rowItem.rowKey) : 1 // 0=DEC, 1=HEX, 2=FLOAT, 3=ASCII, 4=UTF-8
                        property int endianIndex: rowItem.hasValue ? root.historyGetEndian(rowItem.rowKey) : 0 // 0=LE, 1=BE
                        property string formattedValue: {
                            if (!hasValue || !modelData) {
                                return modelData && modelData.details ? modelData.details : ""
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
                            spacing: 6

                            Text { text: modelData.time; color: root.textSoft; font.pixelSize: 11; font.family: "Consolas"; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; Layout.preferredWidth: root.colTimeWidth; Layout.minimumWidth: root.colTimeWidth; Layout.alignment: Qt.AlignVCenter }
                            Text { text: modelData.action; color: root.textMain; font.pixelSize: 11; font.family: "Bahnschrift"; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; Layout.preferredWidth: root.colActionWidth; Layout.minimumWidth: root.colActionWidth; Layout.alignment: Qt.AlignVCenter }
                            Text { text: modelData.did; color: root.textMain; font.pixelSize: 11; font.family: "Consolas"; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; Layout.preferredWidth: root.colDidWidth; Layout.minimumWidth: root.colDidWidth; Layout.alignment: Qt.AlignVCenter }
                            Text { text: modelData.result; color: modelData.color ? modelData.color : "#334155"; font.pixelSize: 11; font.family: "Bahnschrift"; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; Layout.preferredWidth: root.colResultWidth; Layout.minimumWidth: root.colResultWidth; Layout.alignment: Qt.AlignVCenter }

                            Item {
                                Layout.preferredWidth: root.colFormatWidth
                                Layout.minimumWidth: root.colFormatWidth
                                Layout.preferredHeight: 28
                                Layout.alignment: Qt.AlignVCenter

                                FancyComboBox {
                                    id: formatSelector
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
                                    onActivated: root.historySetFormat(rowItem.rowKey, currentIndex)
                                }
                            }

                            Item {
                                Layout.preferredWidth: root.colEndianWidth
                                Layout.minimumWidth: root.colEndianWidth
                                Layout.preferredHeight: 28
                                Layout.alignment: Qt.AlignVCenter

                                FancyComboBox {
                                    id: endianSelector
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
                                    onActivated: root.historySetEndian(rowItem.rowKey, currentIndex)
                                }
                            }

                            Text {
                                id: valueText
                                text: rowItem.hasValue
                                      ? rowItem.formattedValue
                                      : modelData.details
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Consolas"
                                verticalAlignment: Text.AlignVCenter
                                horizontalAlignment: Text.AlignLeft
                                wrapMode: Text.WrapAnywhere
                                elide: Text.ElideNone
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignVCenter
                            }
                        }
                    }
                }
            }
        }
    }
}
