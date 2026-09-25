import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Окно «Параметры UDS»: все параметры прибора в одной таблице.

  Здесь объединены прежние окна «Параметры UDS» и «Массовое чтение DID»:
  - таблица показывает каждый параметр с последним известным значением в его
    единицах (°C, %, секунды, знак, списки, текст), откуда бы его ни прочитали;
  - поиск по номеру или словам названия и фильтр по группам;
  - «Прочитать показанные» читает по очереди все строки, что сейчас на экране;
  - справа выбранный параметр: описание, значение во всех видах, запись с
    предпросмотром байт и сверкой чтением после записи;
  - доступ на запись открывается одной кнопкой в шапке.
*/
Card {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"

    readonly property bool linkReady: root.appController
                                      && root.appController.connected
                                      && root.appController.tracing
    readonly property bool busy: root.appController ? root.appController.optionOperationBusy : false
    readonly property bool bulkBusy: root.appController ? root.appController.optionsBulkBusy : false
    readonly property bool accessBusy: root.appController ? root.appController.serviceAccessBusy : false
    readonly property bool accessOpen: root.appController ? root.appController.optionsWriteAccessOpen : false
    readonly property var sel: root.appController ? root.appController.selectedOptionView : ({})
    readonly property int selectedDid: root.sel && root.sel.did !== undefined ? root.sel.did : -1

    // Предпросмотр того, что уйдёт в прибор при записи введённого значения.
    property var writePreview: ({ "ok": false, "text": "" })

    readonly property var delayChoices: [0, 20, 50, 100, 200, 500]
    readonly property int colDid: 70
    readonly property int colStatus: 176
    readonly property int colRead: 34

    function refreshPreview() {
        if (!root.appController) {
            root.writePreview = ({ "ok": false, "text": "" })
            return
        }
        root.writePreview = root.appController.previewOptionInput(writeField.text)
    }

    function fillWithCurrentValue() {
        writeField.text = root.sel && root.sel.editText !== undefined ? String(root.sel.editText) : ""
        root.refreshPreview()
    }

    function bulkProgressRatio() {
        if (!root.appController) {
            return 0
        }
        var parts = String(root.appController.optionsBulkProgressText).split("/")
        var total = Number(parts[1])
        return total > 0 ? Number(parts[0]) / total : 0
    }

    function delayIndex() {
        var current = root.appController ? Number(root.appController.optionsBulkDelayMs) : 100
        var best = 0
        for (var i = 0; i < root.delayChoices.length; i++) {
            if (Math.abs(root.delayChoices[i] - current) < Math.abs(root.delayChoices[best] - current)) {
                best = i
            }
        }
        return best
    }

    // Смена параметра подставляет его текущее значение в поле записи.
    onSelectedDidChanged: root.fillWithCurrentValue()

    // Значение пришло, пока поле пустое: подставляем его, чтобы не набирать заново.
    readonly property string selectedEditText: root.sel && root.sel.editText !== undefined ? String(root.sel.editText) : ""
    onSelectedEditTextChanged: {
        if (writeField.text === "" && root.selectedEditText !== "") {
            root.fillWithCurrentValue()
        }
    }

    Layout.fillWidth: true
    implicitHeight: contentColumn.implicitHeight + 28

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        // ---------------------------------------------------------------- шапка
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true

                Text {
                    text: "Параметры UDS"
                    color: root.textMain
                    font.pixelSize: 20
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                Text {
                    text: "Все параметры прибора в одной таблице: поиск, чтение, запись со сверкой"
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }

            Text {
                text: "Узел"
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
            }

            FancyComboBox {
                Layout.preferredWidth: 230
                model: root.appController ? root.appController.optionsTargetNodeItems : []
                currentIndex: root.appController ? root.appController.selectedOptionsTargetNodeIndex : 0
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
                enabled: !root.busy
                onActivated: if (root.appController) root.appController.setSelectedOptionsTargetNodeIndex(currentIndex)
            }

            Rectangle {
                Layout.preferredHeight: 38
                Layout.preferredWidth: accessText.implicitWidth + 34
                radius: 10
                color: root.accessOpen ? "#e7f8ef" : "#fff7e6"
                border.color: root.accessOpen ? "#88d4af" : "#f3c77a"
                border.width: 1

                Row {
                    anchors.centerIn: parent
                    spacing: 7

                    Rectangle {
                        width: 9
                        height: 9
                        radius: 5
                        anchors.verticalCenter: parent.verticalCenter
                        color: root.accessOpen ? "#16a34a" : "#d97706"
                    }

                    Text {
                        id: accessText
                        text: root.appController ? root.appController.optionsWriteAccessText : "-"
                        color: root.accessOpen ? "#166534" : "#92400e"
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }

            FancyButton {
                Layout.preferredWidth: 170
                text: root.accessBusy ? "Открываю..." : "Открыть доступ"
                loading: root.accessBusy
                enabled: root.linkReady && !root.accessOpen && !root.busy
                tone: "#d97706"
                toneHover: "#b45309"
                tonePressed: "#92400e"
                toolTipText: "Сессия 0x10 Extended и Security Access 0x27 для выбранного узла: без них прибор отвергает запись"
                onClicked: if (root.appController) root.appController.openOptionsWriteAccess()
            }
        }

        // ---------------------------------------------------------------- панель инструментов
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: toolbarRow.implicitHeight + 16
            radius: 10
            color: "#f4f8fd"
            border.color: "#d6e2ef"
            border.width: 1

            RowLayout {
                id: toolbarRow
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8

                FancyTextField {
                    id: searchField
                    Layout.preferredWidth: 300
                    placeholderText: "Поиск: номер или слова из названия"
                    textColor: root.textMain
                    bgColor: "#ffffff"
                    borderColor: root.inputBorder
                    focusBorderColor: root.inputFocus
                    selectByMouse: true
                    onTextChanged: if (root.appController) root.appController.setOptionsFilterText(text)
                }

                FancyComboBox {
                    Layout.preferredWidth: 230
                    model: root.appController ? root.appController.optionsGroupItems : []
                    currentIndex: root.appController ? root.appController.selectedOptionsGroupIndex : 0
                    textColor: root.textMain
                    bgColor: "#ffffff"
                    borderColor: root.inputBorder
                    focusBorderColor: root.inputFocus
                    onActivated: if (root.appController) root.appController.setSelectedOptionsGroupIndex(currentIndex)
                }

                Text {
                    text: root.appController ? root.appController.optionsTableSummaryText : ""
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                Text {
                    text: "Пауза"
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                }

                FancyComboBox {
                    Layout.preferredWidth: 100
                    model: ["0 мс", "20 мс", "50 мс", "100 мс", "200 мс", "500 мс"]
                    currentIndex: root.delayIndex()
                    enabled: !root.bulkBusy
                    textColor: root.textMain
                    bgColor: "#ffffff"
                    borderColor: root.inputBorder
                    focusBorderColor: root.inputFocus
                    onActivated: if (root.appController) root.appController.setOptionsBulkDelayMs(root.delayChoices[currentIndex])
                }

                FancyButton {
                    Layout.preferredWidth: 196
                    text: root.bulkBusy ? "Чтение " + root.appController.optionsBulkProgressText : "Прочитать показанные"
                    loading: root.bulkBusy
                    enabled: root.linkReady && !root.busy
                    tone: "#2563eb"
                    toneHover: "#1d4ed8"
                    tonePressed: "#1e40af"
                    toolTipText: "Читает по очереди все параметры, которые сейчас показаны в таблице"
                    onClicked: if (root.appController) root.appController.startOptionsBulkReadVisible()
                }

                FancyButton {
                    Layout.preferredWidth: 80
                    visible: root.bulkBusy
                    text: "Стоп"
                    tone: "#dc2626"
                    toneHover: "#b91c1c"
                    tonePressed: "#991b1b"
                    onClicked: if (root.appController) root.appController.stopOptionsBulkReadAll()
                }

                FancyButton {
                    Layout.preferredWidth: 110
                    text: "В CSV"
                    enabled: !root.bulkBusy
                    tone: "#0f766e"
                    toneHover: "#115e59"
                    tonePressed: "#134e4a"
                    toolTipText: "Сохранить показанную таблицу в папку logs/options"
                    onClicked: if (root.appController) root.appController.exportOptionsTableCsv()
                }

                FancyButton {
                    Layout.preferredWidth: 110
                    text: "Очистить"
                    enabled: !root.bulkBusy
                    tone: "#64748b"
                    toneHover: "#475569"
                    tonePressed: "#334155"
                    toolTipText: "Забыть прочитанные значения: таблица снова пустая"
                    onClicked: if (root.appController) root.appController.clearOptionsValues()
                }
            }
        }

        // Ход чтения списка.
        FancyProgressBar {
            Layout.fillWidth: true
            visible: root.bulkBusy
            implicitHeight: 8
            from: 0
            to: 1
            value: root.bulkProgressRatio()
        }

        // ---------------------------------------------------------------- таблица и выбранный параметр
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 360
            spacing: 10

            // Таблица параметров.
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 10
                color: "#ffffff"
                border.color: "#d7e3ef"
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 4

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 26
                        radius: 6
                        color: "#e9f1fb"
                        border.width: 1
                        border.color: "#d2dfed"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            spacing: 8

                            Text { text: "DID"; color: "#4b6078"; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift"; Layout.preferredWidth: root.colDid }
                            Text { text: "Параметр"; color: "#4b6078"; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift"; Layout.preferredWidth: tableList.width * 0.36 }
                            Text { text: "Значение"; color: "#4b6078"; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift"; Layout.fillWidth: true }
                            Text { text: "Состояние"; color: "#4b6078"; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift"; Layout.preferredWidth: root.colStatus }
                            Item { Layout.preferredWidth: root.colRead }
                        }
                    }

                    ListView {
                        id: tableList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 2
                        boundsBehavior: Flickable.StopAtBounds
                        model: root.appController ? root.appController.optionsTableModel : null
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                        delegate: Rectangle {
                            id: rowItem
                            width: tableList.width - 10
                            height: 40
                            radius: 7
                            readonly property bool isSelected: model.didInt === root.selectedDid
                            color: isSelected ? "#dbeafe" : (rowHover.containsMouse ? "#f1f6fd" : (index % 2 === 0 ? "#fbfdff" : "#f6f9fd"))
                            border.width: 1
                            border.color: isSelected ? "#60a5fa" : "#e3ebf4"

                            MouseArea {
                                id: rowHover
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: if (root.appController) root.appController.selectOptionByDid(model.didInt)
                                onDoubleClicked: {
                                    if (root.appController && model.canRead && root.linkReady && !root.busy) {
                                        root.appController.readOptionByDid(model.didInt)
                                    }
                                }
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                spacing: 8

                                ColumnLayout {
                                    Layout.preferredWidth: root.colDid
                                    spacing: 0

                                    Text {
                                        text: model.did
                                        color: root.textMain
                                        font.pixelSize: 12
                                        font.family: "Consolas"
                                        font.bold: rowItem.isSelected
                                    }

                                    Text {
                                        text: model.canWrite ? "запись" : (model.canRead ? "чтение" : "нет")
                                        color: model.canWrite ? "#0f766e" : "#94a3b8"
                                        font.pixelSize: 9
                                        font.family: "Bahnschrift"
                                    }
                                }

                                Text {
                                    text: model.name
                                    color: root.textMain
                                    font.pixelSize: 12
                                    font.family: "Bahnschrift"
                                    elide: Text.ElideRight
                                    Layout.preferredWidth: tableList.width * 0.36
                                    ToolTip.visible: nameHover.containsMouse && (model.note !== "" || truncated)
                                    ToolTip.text: model.note !== "" ? model.name + "\n" + model.note : model.name
                                    ToolTip.delay: 500

                                    MouseArea {
                                        id: nameHover
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        acceptedButtons: Qt.NoButton
                                    }
                                }

                                Text {
                                    text: model.value
                                    color: model.hasValue ? "#0f2a43" : "#a8b5c4"
                                    font.pixelSize: 12
                                    font.family: "Consolas"
                                    font.bold: model.hasValue
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                    ToolTip.visible: valueHover.containsMouse && truncated
                                    ToolTip.text: model.value
                                    ToolTip.delay: 400

                                    MouseArea {
                                        id: valueHover
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        acceptedButtons: Qt.NoButton
                                    }
                                }

                                Row {
                                    Layout.preferredWidth: root.colStatus
                                    spacing: 6

                                    Rectangle {
                                        width: 8
                                        height: 8
                                        radius: 4
                                        color: model.statusColor
                                        anchors.verticalCenter: parent.verticalCenter
                                    }

                                    Column {
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 0

                                        Text {
                                            text: model.status
                                            color: model.statusColor
                                            font.pixelSize: 11
                                            font.family: "Bahnschrift"
                                            width: root.colStatus - 16
                                            elide: Text.ElideRight
                                            ToolTip.visible: statusHover.containsMouse && model.details !== ""
                                            ToolTip.text: model.details
                                            ToolTip.delay: 300

                                            MouseArea {
                                                id: statusHover
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                acceptedButtons: Qt.NoButton
                                            }
                                        }

                                        Text {
                                            text: model.time
                                            visible: model.time !== ""
                                            color: root.textSoft
                                            font.pixelSize: 9
                                            font.family: "Consolas"
                                        }
                                    }
                                }

                                Rectangle {
                                    Layout.preferredWidth: root.colRead
                                    Layout.preferredHeight: 28
                                    radius: 7
                                    readonly property bool canPress: model.canRead && root.linkReady && !root.busy
                                    color: !canPress ? "#eef2f7" : (readHover.pressed ? "#1d4ed8" : (readHover.containsMouse ? "#3b82f6" : "#e0ecff"))
                                    border.width: 1
                                    border.color: canPress ? "#93c5fd" : "#dde5ee"
                                    visible: model.canRead

                                    Text {
                                        anchors.centerIn: parent
                                        text: "⟳"
                                        color: parent.canPress ? (readHover.containsMouse ? "#ffffff" : "#1d4ed8") : "#a8b5c4"
                                        font.pixelSize: 16
                                        font.bold: true
                                    }

                                    MouseArea {
                                        id: readHover
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        enabled: parent.canPress
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: if (root.appController) root.appController.readOptionByDid(model.didInt)
                                    }

                                    ToolTip.visible: readHover.containsMouse
                                    ToolTip.text: "Прочитать из прибора"
                                    ToolTip.delay: 500
                                }
                            }
                        }

                        Text {
                            anchors.centerIn: parent
                            visible: tableList.count === 0
                            text: "Ничего не найдено. Измените поиск или группу."
                            color: root.textSoft
                            font.pixelSize: 13
                            font.family: "Bahnschrift"
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Щелчок выбирает параметр, двойной щелчок или ⟳ читает его из прибора."
                        color: root.textSoft
                        font.pixelSize: 10
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }
                }
            }

            // Выбранный параметр.
            Rectangle {
                Layout.preferredWidth: 440
                Layout.fillHeight: true
                radius: 10
                color: "#f7fbff"
                border.color: "#d7e3ef"
                border.width: 1

                Flickable {
                    id: detailFlick
                    anchors.fill: parent
                    anchors.margins: 12
                    clip: true
                    contentWidth: width
                    contentHeight: detailColumn.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    ColumnLayout {
                        id: detailColumn
                        width: detailFlick.width - 8
                        spacing: 8

                        Text {
                            text: root.sel.didText !== undefined ? root.sel.didText : "-"
                            color: "#2563eb"
                            font.pixelSize: 13
                            font.family: "Consolas"
                            font.bold: true
                        }

                        Text {
                            text: root.sel.name !== undefined ? root.sel.name : ""
                            color: root.textMain
                            font.pixelSize: 16
                            font.bold: true
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }

                        Flow {
                            Layout.fillWidth: true
                            spacing: 6

                            StatusChip { label: root.sel.group !== undefined ? root.sel.group : ""; visible: label !== "" }
                            StatusChip { label: root.sel.sizeText !== undefined ? root.sel.sizeText : ""; visible: label !== "" }
                            StatusChip {
                                label: root.sel.access !== undefined ? root.sel.access : ""
                                visible: label !== ""
                                chipColor: root.sel.canWrite ? "#e7f8ef" : "#f1f5f9"
                                chipBorder: root.sel.canWrite ? "#88d4af" : "#cbd5e1"
                            }
                        }

                        Text {
                            visible: text !== ""
                            text: root.sel.note !== undefined ? root.sel.note : ""
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }

                        // Значение.
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: valueColumn.implicitHeight + 20
                            radius: 10
                            color: "#ffffff"
                            border.color: "#d6e2ef"
                            border.width: 1

                            ColumnLayout {
                                id: valueColumn
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 6

                                RowLayout {
                                    Layout.fillWidth: true

                                    Text {
                                        text: "Значение в приборе"
                                        color: root.textSoft
                                        font.pixelSize: 11
                                        font.family: "Bahnschrift"
                                        Layout.fillWidth: true
                                    }

                                    Text {
                                        text: root.sel.status !== undefined ? root.sel.status + (root.sel.time ? "  " + root.sel.time : "") : ""
                                        color: root.sel.statusColor !== undefined ? root.sel.statusColor : root.textSoft
                                        font.pixelSize: 11
                                        font.family: "Bahnschrift"
                                    }
                                }

                                TextEdit {
                                    Layout.fillWidth: true
                                    text: root.sel.display !== undefined ? root.sel.display : "—"
                                    color: root.sel.hasValue ? "#0f2a43" : "#a8b5c4"
                                    font.pixelSize: 20
                                    font.bold: true
                                    font.family: "Consolas"
                                    wrapMode: TextEdit.WrapAnywhere
                                    readOnly: true
                                    selectByMouse: true
                                }

                                Text {
                                    visible: text !== ""
                                    text: root.sel.details !== undefined ? root.sel.details : ""
                                    color: "#dc2626"
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }

                                GridLayout {
                                    Layout.fillWidth: true
                                    visible: root.sel.hasValue === true
                                    columns: 2
                                    columnSpacing: 10
                                    rowSpacing: 3

                                    Text { text: "Число"; color: root.textSoft; font.pixelSize: 11; font.family: "Bahnschrift"; visible: root.sel.number !== "" }
                                    TextEdit { text: root.sel.number !== undefined ? root.sel.number : ""; visible: text !== ""; readOnly: true; selectByMouse: true; color: root.textMain; font.pixelSize: 12; font.family: "Consolas"; Layout.fillWidth: true }

                                    Text { text: "HEX"; color: root.textSoft; font.pixelSize: 11; font.family: "Bahnschrift"; visible: root.sel.hex !== "" }
                                    TextEdit { text: root.sel.hex !== undefined ? root.sel.hex : ""; visible: text !== ""; readOnly: true; selectByMouse: true; color: root.textMain; font.pixelSize: 12; font.family: "Consolas"; Layout.fillWidth: true }

                                    Text { text: "Байты"; color: root.textSoft; font.pixelSize: 11; font.family: "Bahnschrift" }
                                    TextEdit { text: root.sel.raw !== undefined ? root.sel.raw : ""; readOnly: true; selectByMouse: true; color: root.textMain; font.pixelSize: 12; font.family: "Consolas"; wrapMode: TextEdit.WrapAnywhere; Layout.fillWidth: true }

                                    Text { text: "Как текст"; color: root.textSoft; font.pixelSize: 11; font.family: "Bahnschrift"; visible: root.sel.text !== undefined && root.sel.text !== "" }
                                    TextEdit { text: root.sel.text !== undefined ? root.sel.text : ""; visible: text !== ""; readOnly: true; selectByMouse: true; color: root.textMain; font.pixelSize: 12; font.family: "Consolas"; wrapMode: TextEdit.WrapAnywhere; Layout.fillWidth: true }
                                }

                                FancyButton {
                                    Layout.fillWidth: true
                                    text: root.busy && !root.bulkBusy ? "Идёт операция..." : "Прочитать из прибора"
                                    loading: root.busy && !root.bulkBusy
                                    enabled: root.sel.canRead === true && root.linkReady && !root.busy
                                    tone: "#2563eb"
                                    toneHover: "#1d4ed8"
                                    tonePressed: "#1e40af"
                                    onClicked: if (root.appController) root.appController.readSelectedOption()
                                }
                            }
                        }

                        // Запись.
                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: writeColumn.implicitHeight + 20
                            radius: 10
                            color: "#ffffff"
                            border.color: "#d6e2ef"
                            border.width: 1

                            ColumnLayout {
                                id: writeColumn
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 6

                                Text {
                                    text: "Запись"
                                    color: root.textSoft
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }

                                Text {
                                    visible: root.sel.canWrite !== true
                                    text: "Этот параметр только для чтения."
                                    color: root.textSoft
                                    font.pixelSize: 12
                                    font.family: "Bahnschrift"
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }

                                ColumnLayout {
                                    visible: root.sel.canWrite === true
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Rectangle {
                                        visible: !root.accessOpen
                                        Layout.fillWidth: true
                                        implicitHeight: accessHint.implicitHeight + 12
                                        radius: 8
                                        color: "#fff7e6"
                                        border.color: "#f3c77a"
                                        border.width: 1

                                        Text {
                                            id: accessHint
                                            anchors.fill: parent
                                            anchors.margins: 6
                                            text: "Прибор примет запись только с открытым доступом: нажмите «Открыть доступ» вверху."
                                            color: "#92400e"
                                            font.pixelSize: 11
                                            font.family: "Bahnschrift"
                                            wrapMode: Text.WordWrap
                                        }
                                    }

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6

                                        FancyComboBox {
                                            Layout.preferredWidth: 150
                                            model: root.appController ? root.appController.optionsInputModeItems : []
                                            currentIndex: root.sel.inputModeIndex !== undefined ? root.sel.inputModeIndex : 0
                                            textColor: root.textMain
                                            bgColor: root.inputBg
                                            borderColor: root.inputBorder
                                            focusBorderColor: root.inputFocus
                                            onActivated: {
                                                if (root.appController) {
                                                    root.appController.setSelectedOptionInputModeIndex(currentIndex)
                                                    root.fillWithCurrentValue()
                                                }
                                            }
                                        }

                                        FancyButton {
                                            Layout.fillWidth: true
                                            text: "Подставить текущее"
                                            enabled: root.sel.hasValue === true
                                            tone: "#64748b"
                                            toneHover: "#475569"
                                            tonePressed: "#334155"
                                            toolTipText: "Вставить в поле значение, прочитанное из прибора, чтобы поправить его"
                                            onClicked: root.fillWithCurrentValue()
                                        }
                                    }

                                    FancyTextField {
                                        id: writeField
                                        Layout.fillWidth: true
                                        placeholderText: "Новое значение"
                                        textColor: root.textMain
                                        bgColor: root.inputBg
                                        borderColor: root.writePreview.ok || text === "" ? root.inputBorder : "#fca5a5"
                                        focusBorderColor: root.writePreview.ok || text === "" ? root.inputFocus : "#dc2626"
                                        font.family: "Consolas"
                                        selectByMouse: true
                                        onTextChanged: root.refreshPreview()
                                        onAccepted: {
                                            if (root.appController && root.writePreview.ok && root.linkReady && !root.busy) {
                                                root.appController.writeSelectedOptionInput(text)
                                            }
                                        }
                                    }

                                    Text {
                                        text: root.sel.inputHint !== undefined ? root.sel.inputHint : ""
                                        color: root.textSoft
                                        font.pixelSize: 11
                                        font.family: "Bahnschrift"
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }

                                    Text {
                                        visible: text !== ""
                                        text: root.writePreview.text !== undefined ? root.writePreview.text : ""
                                        color: root.writePreview.ok ? "#15803d" : "#dc2626"
                                        font.pixelSize: 12
                                        font.family: "Consolas"
                                        wrapMode: Text.WrapAnywhere
                                        Layout.fillWidth: true
                                    }

                                    FancyButton {
                                        Layout.fillWidth: true
                                        text: root.busy && !root.bulkBusy ? "Идёт операция..." : "Записать и проверить"
                                        loading: root.busy && !root.bulkBusy
                                        enabled: root.writePreview.ok === true && root.linkReady && !root.busy
                                        tone: "#0ea5a4"
                                        toneHover: "#0f766e"
                                        tonePressed: "#115e59"
                                        toolTipText: "Записать значение и сразу прочитать его обратно для сверки"
                                        onClicked: if (root.appController) root.appController.writeSelectedOptionInput(writeField.text)
                                    }
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.appController ? "Последняя операция: " + root.appController.optionOperationStatusText : ""
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }

        // ---------------------------------------------------------------- журнал
        SpoilerSection {
            id: journalSection
            objectName: "optionsJournal"
            Layout.fillWidth: true
            title: "Журнал операций"
            hintText: "Чтение, запись и сверка по порядку, с ответами прибора"
            textMain: root.textMain
            textSoft: root.textSoft

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4

                RowLayout {
                    Layout.fillWidth: true

                    Item { Layout.fillWidth: true }

                    FancyButton {
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: 30
                        text: "Очистить журнал"
                        tone: "#64748b"
                        toneHover: "#475569"
                        tonePressed: "#334155"
                        onClicked: if (root.appController) root.appController.clearOptionHistory()
                    }
                }

                ListView {
                    id: historyList
                    Layout.fillWidth: true
                    Layout.preferredHeight: 190
                    clip: true
                    spacing: 2
                    model: root.appController ? root.appController.optionOperationHistory : []
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    onCountChanged: if (count > 0) Qt.callLater(function() { historyList.positionViewAtEnd() })

                    delegate: Rectangle {
                        width: historyList.width - 10
                        height: 26
                        radius: 6
                        color: index % 2 === 0 ? "#f8fbff" : "#f1f6fc"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            spacing: 8

                            Text { text: modelData.time; color: root.textSoft; font.pixelSize: 11; font.family: "Consolas"; Layout.preferredWidth: 60 }
                            Text { text: modelData.action; color: root.textMain; font.pixelSize: 11; font.family: "Bahnschrift"; Layout.preferredWidth: 110; elide: Text.ElideRight }
                            Text { text: modelData.did; color: root.textMain; font.pixelSize: 11; font.family: "Consolas"; Layout.preferredWidth: 60 }
                            Text { text: modelData.name; color: root.textMain; font.pixelSize: 11; font.family: "Bahnschrift"; Layout.preferredWidth: 280; elide: Text.ElideRight }
                            Text { text: modelData.result; color: modelData.color ? modelData.color : root.textMain; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift"; Layout.preferredWidth: 90 }
                            Text {
                                text: modelData.hasValue ? modelData.details + "  ·  " + modelData.rawHex : modelData.details
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Consolas"
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }
        }
    }
}
