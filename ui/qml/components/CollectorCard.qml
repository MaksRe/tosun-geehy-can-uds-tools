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
    readonly property bool collectorEnabled: root.appController ? root.appController.collectorEnabled : false
    readonly property bool collectorTrendEnabled: root.appController ? root.appController.collectorTrendEnabled : false
    property string collectorInfoTitle: ""
    property string collectorInfoText: ""

    signal selectOutputDirectoryRequested()
    signal openTrendWindowRequested()

    // Цель функции в открытии справки по колонке, затем она показывает простое описание источника и формулы значения.
    function openCollectorInfo(titleText, bodyText) {
        collectorInfoTitle = String(titleText || "")
        collectorInfoText = String(bodyText || "")
        collectorInfoPopup.open()
    }

    Layout.fillWidth: true
    Layout.fillHeight: true
    implicitHeight: 640

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
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Text {
                    text: "Коллектор"
                    color: root.textMain
                    font.pixelSize: 18
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                Text {
                    text: "Опрос узлов по UDS и запись параметров в CSV"
                    color: root.textSoft
                    font.pixelSize: 10
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }

            FancyButton {
                Layout.preferredWidth: 140
                Layout.preferredHeight: 30
                fontPixelSize: 11
                text: "Графики CAN"
                tone: "#1d4ed8"
                toneHover: "#1e40af"
                tonePressed: "#1e3a8a"
                onClicked: root.openTrendWindowRequested()
            }

            Text {
                text: root.collectorTrendEnabled ? "Графики: ВКЛ" : "Графики: ВЫКЛ"
                color: root.collectorTrendEnabled ? "#0ea5a4" : root.textSoft
                font.pixelSize: 11
                font.bold: true
                font.family: "Bahnschrift"
                Layout.alignment: Qt.AlignVCenter
            }

            FancySwitch {
                Layout.alignment: Qt.AlignVCenter
                trackWidth: 42
                trackHeight: 22
                checked: root.collectorTrendEnabled
                onToggled: if (root.appController) root.appController.setCollectorTrendEnabled(checked)
            }

            Text {
                text: root.collectorEnabled ? "Сценарий: ВКЛ" : "Сценарий: ВЫКЛ"
                color: root.collectorEnabled ? "#059669" : root.textSoft
                font.pixelSize: 11
                font.bold: true
                font.family: "Bahnschrift"
                Layout.alignment: Qt.AlignVCenter
            }

            FancySwitch {
                Layout.alignment: Qt.AlignVCenter
                trackWidth: 44
                trackHeight: 24
                checked: root.collectorEnabled
                onToggled: if (root.appController) root.appController.setCollectorEnabled(checked)
            }
        }

        ColumnLayout {
            id: collectorBody
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 6
            enabled: root.collectorEnabled
            opacity: root.collectorEnabled ? 1.0 : 0.45

            Behavior on opacity {
                NumberAnimation {
                    duration: 140
                    easing.type: Easing.OutCubic
                }
            }

            Rectangle {
                Layout.fillWidth: true
                radius: 9
                color: "#f8fbff"
                border.color: "#d6e2ef"
                border.width: 1
                implicitHeight: csvSectionLayout.implicitHeight + 12

                ColumnLayout {
                    id: csvSectionLayout
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 4

                    Text {
                        text: "CSV и каталог выгрузки"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        FancyTextField {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 30
                            text: root.appController ? root.appController.collectorOutputDirectory : ""
                            readOnly: true
                            placeholderText: "Папка для CSV не выбрана"
                            textColor: root.textMain
                            bgColor: root.inputBg
                            borderColor: root.inputBorder
                            focusBorderColor: root.inputFocus
                        }

                        FancyButton {
                            Layout.preferredWidth: 148
                            Layout.preferredHeight: 30
                            fontPixelSize: 11
                            text: "Выбрать каталог"
                            tone: "#0ea5a4"
                            toneHover: "#0f766e"
                            tonePressed: "#115e59"
                            onClicked: root.selectOutputDirectoryRequested()
                        }

                        FancyButton {
                            Layout.preferredWidth: 158
                            Layout.preferredHeight: 30
                            fontPixelSize: 11
                            text: "Папка с датой"
                            tone: "#64748b"
                            toneHover: "#55657a"
                            tonePressed: "#465669"
                            onClicked: if (root.appController) root.appController.createCollectorTimestampedLogsDirectory()
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                radius: 9
                color: "#f8fbff"
                border.color: "#d6e2ef"
                border.width: 1
                implicitHeight: 54

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 6

                    Text {
                        text: "Параметры опроса"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.bold: true
                        font.family: "Bahnschrift"
                        Layout.preferredWidth: 118
                        verticalAlignment: Text.AlignVCenter
                    }

                    Text {
                        text: "Шаг, мс"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        Layout.alignment: Qt.AlignVCenter
                    }

                    FancyTextField {
                        id: pollIntervalField
                        Layout.preferredWidth: 88
                        Layout.preferredHeight: 30
                        text: root.appController ? String(root.appController.collectorPollIntervalMs) : "1000"
                        placeholderText: "мс"
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        validator: IntValidator { bottom: 30; top: 10000 }
                        onAccepted: if (root.appController) root.appController.setCollectorPollIntervalMs(text)
                    }

                    Text {
                        text: "Пауза цикла, мс"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        Layout.alignment: Qt.AlignVCenter
                    }

                    FancyTextField {
                        id: cyclePauseField
                        Layout.preferredWidth: 96
                        Layout.preferredHeight: 30
                        text: root.appController ? String(root.appController.collectorCyclePauseMs) : "1000"
                        placeholderText: "мс"
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        validator: IntValidator { bottom: 30; top: 10000 }
                        onAccepted: if (root.appController) root.appController.setCollectorCyclePauseMs(text)
                    }

                    FancyButton {
                        Layout.preferredWidth: 102
                        Layout.preferredHeight: 30
                        fontPixelSize: 11
                        text: "Применить"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        onClicked: if (root.appController) {
                            root.appController.setCollectorPollIntervalMs(pollIntervalField.text)
                            root.appController.setCollectorCyclePauseMs(cyclePauseField.text)
                        }
                    }

                    Item { Layout.fillWidth: true }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 260
                radius: 10
                color: "#f4f8fd"
                border.color: "#d6e2ef"

                Item {
                    anchors.fill: parent
                    anchors.margins: 6
                    clip: true

                    Rectangle {
                        id: controlPanel
                        width: 116
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.right: parent.right
                        z: 2
                        radius: 8
                        color: "#ffffff"
                        border.color: "#d7e4f0"

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 6
                            spacing: 6

                            Text {
                                text: "Запись"
                                color: root.textSoft
                                font.pixelSize: 11
                                font.bold: true
                                font.family: "Bahnschrift"
                                horizontalAlignment: Text.AlignHCenter
                                Layout.fillWidth: true
                            }

                            FancyButton {
                                text: "Старт"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 30
                                fontPixelSize: 11
                                tone: "#10b981"
                                toneHover: "#059669"
                                tonePressed: "#047857"
                                enabled: root.appController ? !root.appController.collectorRecording : false
                                onClicked: if (root.appController) root.appController.startCollectorRecording()
                            }

                            FancyButton {
                                text: "Пауза"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 30
                                fontPixelSize: 11
                                tone: "#f59e0b"
                                toneHover: "#d97706"
                                tonePressed: "#b45309"
                                enabled: root.appController ? root.appController.collectorRecording : false
                                onClicked: if (root.appController) root.appController.pauseCollectorRecording()
                            }

                            FancyButton {
                                text: "Стоп"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 30
                                fontPixelSize: 11
                                tone: "#ef4444"
                                toneHover: "#dc2626"
                                tonePressed: "#b91c1c"
                                enabled: root.appController ? (root.appController.collectorRecording || root.appController.collectorPaused) : false
                                onClicked: if (root.appController) root.appController.stopCollectorRecording()
                            }

                            FancyButton {
                                text: "Очистить"
                                Layout.fillWidth: true
                                Layout.preferredHeight: 30
                                fontPixelSize: 11
                                tone: "#64748b"
                                toneHover: "#55657a"
                                tonePressed: "#465669"
                                onClicked: if (root.appController) root.appController.clearCollectorNodes()
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    ColumnLayout {
                        id: tableArea
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.left: parent.left
                        anchors.right: controlPanel.left
                        anchors.rightMargin: 8
                        z: 1
                        clip: true
                        spacing: 4
                        readonly property real columnWidth: Math.max(52, Math.floor((width - 22) / 8))

                        Text {
                            Layout.fillWidth: true
                            text: root.appController ? root.appController.collectorStateText : "Статус записи: -"
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 4

                            Repeater {
                                model: [
                                    { "label": "Узел" },
                                    { "label": "Период" },
                                    {
                                        "label": "Топливо",
                                        "infoTitle": "Колонка «Топливо»",
                                        "infoText": "Это значение приходит готовым с МК по DID 0x0018.\n\nКак считается на МК (простыми словами):\n1) Берется текущий период датчика.\n2) К периоду применяется алгоритм температурной компенсации (K1/K0 и выбранный режим компенсации).\n3) Результат ограничивается калибровочными границами empty/full.\n4) После этого период переводится в проценты топлива.\n\nФормат передачи: значение хранится в десятых долях процента.\nПример: 488 => 48.8%."
                                    },
                                    {
                                        "label": "Топл.(расч.)",
                                        "infoTitle": "Колонка «Топл.(расч.)»",
                                        "infoText": "Это расчет на стороне GUI для наглядной проверки.\n\nЧто используется в расчете:\n1) Период из DID 0x0014.\n2) Калибровочные точки empty/full из DID 0x0012/0x0013.\n3) Линейная формула перевода периода в проценты: ((period - empty) * 100) / (full - empty).\n\nПро алгоритм компенсации:\n- В тракте уровня топлива компенсация температуры применяется на МК (K1/K0/режимы).\n- В этой колонке показывается расчетный канал по текущему периоду и калибровке, поэтому значение используется как контрольный индикатор и может отличаться от колонки «Топливо».\n\nФормат отображения: со знаком и одной цифрой после запятой."
                                    },
                                    { "label": "Температура" },
                                    { "label": "Cnt(топл.)" },
                                    { "label": "Cnt(темп.)" },
                                    { "label": "Время" }
                                ]

                                delegate: Item {
                                    Layout.preferredWidth: tableArea.columnWidth
                                    Layout.preferredHeight: 18
                                    readonly property bool hasInfo: modelData.infoText !== undefined
                                    clip: true

                                    // Цель функции в позиционировании значка рядом с текстом заголовка, затем она удерживает иконку внутри ячейки.
                                    function badgeX() {
                                        var labelVisualWidth = Math.min(headerLabel.paintedWidth, headerLabel.width)
                                        var desired = labelVisualWidth + 3
                                        var maxX = Math.max(0, width - infoBadge.width)
                                        return Math.max(0, Math.min(desired, maxX))
                                    }

                                    Text {
                                        id: headerLabel
                                        anchors.left: parent.left
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: hasInfo ? Math.max(8, parent.width - infoBadge.width - 2) : parent.width
                                        text: modelData.label
                                        color: root.textSoft
                                        font.pixelSize: 10
                                        font.family: "Bahnschrift"
                                        font.bold: true
                                        elide: Text.ElideRight
                                        verticalAlignment: Text.AlignVCenter
                                    }

                                    Rectangle {
                                        id: infoBadge
                                        visible: hasInfo
                                        width: 14
                                        height: 14
                                        radius: 7
                                        x: parent.badgeX()
                                        anchors.verticalCenter: headerLabel.verticalCenter
                                        color: infoBadgeMouse.containsMouse ? "#e6effb" : "#f3f7fd"
                                        border.color: infoBadgeMouse.containsMouse ? "#7fa2cc" : "#99b5d6"

                                        Text {
                                            anchors.centerIn: parent
                                            text: "i"
                                            color: "#1e3a8a"
                                            font.pixelSize: 10
                                            font.bold: true
                                            font.family: "Bahnschrift"
                                        }

                                        MouseArea {
                                            id: infoBadgeMouse
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: root.openCollectorInfo(
                                                modelData.infoTitle,
                                                modelData.infoText
                                            )
                                        }

                                        ToolTip.visible: infoBadgeMouse.containsMouse
                                        ToolTip.delay: 220
                                        ToolTip.timeout: 2000
                                        ToolTip.text: "Пояснение"
                                    }
                                }
                            }

                            Item { Layout.fillWidth: true }
                        }

                        ListView {
                            id: nodesList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 2
                            model: root.appController ? root.appController.collectorNodes : []

                            delegate: Rectangle {
                                width: nodesList.width
                                height: 24
                                radius: 6
                                color: index % 2 === 0 ? "#f8fbff" : "#edf3fa"

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 6
                                    anchors.rightMargin: 6
                                    spacing: 4

                                    Text { Layout.preferredWidth: tableArea.columnWidth; text: modelData.node; color: root.textMain; font.pixelSize: 11; font.family: "Bahnschrift"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                    Text { Layout.preferredWidth: tableArea.columnWidth; text: modelData.period; color: root.textMain; font.pixelSize: 11; font.family: "Bahnschrift"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                    Text { Layout.preferredWidth: tableArea.columnWidth; text: modelData.fuelLevel; color: root.textMain; font.pixelSize: 11; font.family: "Bahnschrift"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                    Text { Layout.preferredWidth: tableArea.columnWidth; text: modelData.fuelFromPeriod; color: root.textMain; font.pixelSize: 11; font.family: "Bahnschrift"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                    Text { Layout.preferredWidth: tableArea.columnWidth; text: modelData.temperature; color: root.textMain; font.pixelSize: 11; font.family: "Bahnschrift"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                    Text { Layout.preferredWidth: tableArea.columnWidth; text: modelData.fuelCount; color: root.textMain; font.pixelSize: 11; font.family: "Bahnschrift"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                    Text { Layout.preferredWidth: tableArea.columnWidth; text: modelData.temperatureCount; color: root.textMain; font.pixelSize: 11; font.family: "Bahnschrift"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                    Text { Layout.preferredWidth: tableArea.columnWidth; text: modelData.lastSeen; color: root.textMain; font.pixelSize: 11; font.family: "Bahnschrift"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                                    Item { Layout.fillWidth: true }
                                }
                            }

                            ScrollBar.vertical: ScrollBar {}
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 4

                            Text {
                                text: root.appController ? ("Узлов: " + root.appController.collectorNodes.length) : "Узлов: 0"
                                color: root.textSoft
                                font.pixelSize: 10
                                font.family: "Bahnschrift"
                            }

                            Item { Layout.fillWidth: true }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 176
                Layout.minimumHeight: 132
                radius: 9
                color: "#f8fbff"
                border.color: "#d6e2ef"
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 4

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Text {
                            text: "Ошибки UDS коллектора"
                            color: root.textSoft
                            font.pixelSize: 11
                            font.bold: true
                            font.family: "Bahnschrift"
                        }

                        Text {
                            text: root.appController ? ("(" + String(root.appController.collectorErrorCount) + ")") : "(0)"
                            color: root.textSoft
                            font.pixelSize: 10
                            font.family: "Bahnschrift"
                        }

                        Item { Layout.fillWidth: true }

                        FancyButton {
                            Layout.preferredWidth: 98
                            Layout.preferredHeight: 28
                            fontPixelSize: 11
                            text: "Очистить"
                            tone: "#64748b"
                            toneHover: "#55657a"
                            tonePressed: "#465669"
                            enabled: root.appController ? root.appController.collectorErrorCount > 0 : false
                            onClicked: if (root.appController) root.appController.clearCollectorErrorLogs()
                        }
                    }

                    ListView {
                        id: errorList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 2
                        model: root.appController ? root.appController.collectorErrorLogs : []

                        delegate: Rectangle {
                            width: errorList.width
                            radius: 6
                            color: index % 2 === 0 ? "#f9fbff" : "#eef4fb"
                            implicitHeight: logColumn.implicitHeight + 8

                            ColumnLayout {
                                id: logColumn
                                anchors.fill: parent
                                anchors.margins: 4
                                spacing: 1

                                Text {
                                    Layout.fillWidth: true
                                    text: (modelData.time ? modelData.time : "--:--:--")
                                          + " | " + (modelData.node ? modelData.node : "-")
                                          + " | " + (modelData.did ? modelData.did : "-")
                                    color: "#4f6278"
                                    font.pixelSize: 10
                                    font.family: "Bahnschrift"
                                    elide: Text.ElideRight
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.message ? modelData.message : ""
                                    color: root.textMain
                                    font.pixelSize: 10
                                    font.family: "Bahnschrift"
                                    wrapMode: Text.Wrap
                                    maximumLineCount: 3
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        ScrollBar.vertical: ScrollBar {}
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: (root.appController ? root.appController.collectorErrorCount : 0) === 0
                        text: "Ошибок UDS пока нет"
                        color: root.textSoft
                        font.pixelSize: 10
                        font.family: "Bahnschrift"
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
            }
        }
    }

    Connections {
        target: root.appController

        function onCollectorPollIntervalChanged() {
            if (!pollIntervalField.activeFocus && root.appController) {
                pollIntervalField.text = String(root.appController.collectorPollIntervalMs)
            }
        }

        function onCollectorCyclePauseChanged() {
            if (!cyclePauseField.activeFocus && root.appController) {
                cyclePauseField.text = String(root.appController.collectorCyclePauseMs)
            }
        }
    }

    Popup {
        id: collectorInfoPopup
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        width: Math.min(640, Math.max(360, root.width * 0.78))
        x: (root.width - width) / 2
        y: Math.max(18, (root.height - height) / 2)
        padding: 0

        background: Rectangle {
            radius: 10
            color: "#ffffff"
            border.color: "#c9d9ea"
        }

        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: root.collectorInfoTitle
                color: root.textMain
                font.pixelSize: 14
                font.bold: true
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 8
                color: "#f8fbff"
                border.color: "#d6e2ef"
                implicitHeight: 170

                Flickable {
                    anchors.fill: parent
                    anchors.margins: 8
                    contentWidth: width
                    contentHeight: infoTextBlock.implicitHeight
                    clip: true

                    Text {
                        id: infoTextBlock
                        width: parent.width
                        text: root.collectorInfoText
                        color: root.textMain
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }

                FancyButton {
                    Layout.preferredWidth: 88
                    Layout.preferredHeight: 28
                    fontPixelSize: 11
                    text: "Закрыть"
                    tone: "#64748b"
                    toneHover: "#55657a"
                    tonePressed: "#465669"
                    onClicked: collectorInfoPopup.close()
                }
            }
        }
    }
}
