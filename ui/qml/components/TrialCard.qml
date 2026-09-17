import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Window 2.15
import "."

/*
  Раздел пробной калибровки на столе.
  Назначение:
  - показывает этапы пробной калибровки таблицей: состояние, итог и время каждого;
  - запускает все этапы подряд одной кнопкой либо любой этап отдельно;
  - пишет в отдельный журнал, что делает каждый этап, какие числа получил и чем закончил;
  - постоянно показывает отсчёты обоих контуров, обе температуры и состояние эмуляции.

  Публичные свойства:
  - appController: контроллер приложения;
  - cardColor/cardBorder/textMain/textSoft: общая палитра окна;
  - inputBg/inputBorder/inputFocus: цвета полей ввода.
*/
Card {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f6faff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"

    signal saveProtocolRequested()

    readonly property bool busy: root.appController ? root.appController.trialBusy : false
    readonly property bool autoActive: root.appController ? root.appController.trialAutoActive : false
    readonly property bool ready: root.appController !== null && !root.busy && !root.autoActive
    // Ширины колонок таблицы. Одни и те же для шапки и строк, иначе подписи разъедутся.
    readonly property int colNumber: 30
    readonly property int colTitle: 250
    readonly property int colStatus: 130
    readonly property int colTime: 62
    readonly property int colAction: 104

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    // Одна подсказка на весь раздел: у каждой ячейки своя мешала бы соседней.
    property Item hoveredItem: null
    property string hoveredText: ""

    function setHover(item, hovered, text) {
        if (hovered) {
            root.hoveredItem = item
            root.hoveredText = text
        } else if (root.hoveredItem === item) {
            root.hoveredItem = null
        }
    }

    function logColor(level) {
        if (level === "ok")
            return "#15803d"
        if (level === "warn")
            return "#b45309"
        if (level === "fail")
            return "#b91c1c"
        if (level === "step")
            return root.textMain
        if (level === "detail")
            return "#607084"
        return "#334155"
    }

    ToolTip {
        parent: root.hoveredItem
        visible: root.hoveredItem !== null && root.hoveredText.length > 0
        text: root.hoveredText
        delay: 450
        timeout: 12000
        x: 0
        y: parent ? parent.height + 2 : 0
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        // --- Заголовок ---
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: "Пробная калибровка на столе"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: "Плата на шине, на каждом контуре по одному конденсатору. Настройки прибора запоминаются в начале и возвращаются в конце"
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }

            Text {
                text: root.appController ? root.appController.trialSummaryText : ""
                color: root.textMain
                font.pixelSize: 14
                font.bold: true
                font.family: "Bahnschrift"
            }
        }

        // --- Управление ---
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            FancyButton {
                Layout.preferredWidth: 170
                Layout.preferredHeight: 34
                text: "Запустить всё"
                tone: "#16a34a"
                toneHover: "#15803d"
                tonePressed: "#166534"
                toolTipText: "Проходит все этапы по порядку. При отказе после запоминания настроек сразу возвращает их"
                enabled: root.ready
                onClicked: root.appController.runAllTrialSteps()
            }

            FancyButton {
                Layout.preferredWidth: 130
                Layout.preferredHeight: 34
                text: "Остановить"
                tone: "#ef4444"
                toneHover: "#dc2626"
                tonePressed: "#b91c1c"
                toolTipText: "Прогон закончится после текущего этапа, этап на середине не обрывается"
                enabled: root.autoActive
                onClicked: root.appController.stopTrialAuto()
            }

            Text {
                Layout.fillWidth: true
                text: {
                    if (!root.appController)
                        return "Контроллер недоступен"
                    return root.autoActive ? root.appController.trialAutoProgressText : root.appController.trialStatusText
                }
                color: root.appController ? root.appController.trialStatusColor : "#64748b"
                font.pixelSize: 13
                font.family: "Bahnschrift"
                elide: Text.ElideRight
            }

            FancyButton {
                Layout.preferredWidth: 170
                Layout.preferredHeight: 30
                fontPixelSize: 12
                text: "Выключить эмуляцию"
                tone: "#b45309"
                toneHover: "#92400e"
                tonePressed: "#78350f"
                toolTipText: "Возвращает прибор к настоящим датчикам температуры"
                enabled: root.appController !== null && !root.busy
                onClicked: root.appController.trialEmulationOff()
            }

            FancyButton {
                Layout.preferredWidth: 110
                Layout.preferredHeight: 30
                fontPixelSize: 12
                text: "Сбросить"
                tone: "#64748b"
                toneHover: "#475569"
                tonePressed: "#334155"
                toolTipText: "Возвращает все этапы в состояние «не проверено». В приборе ничего не меняет"
                enabled: root.ready
                onClicked: root.appController.trialResetSteps()
            }

            FancyButton {
                Layout.preferredWidth: 170
                Layout.preferredHeight: 30
                fontPixelSize: 12
                text: "Сохранить протокол"
                tone: "#64748b"
                toneHover: "#475569"
                tonePressed: "#334155"
                toolTipText: "Записывает таблицу этапов и весь журнал в текстовый файл"
                enabled: root.appController !== null
                onClicked: root.saveProtocolRequested()
            }
        }

        // --- Таблица этапов ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: tableColumn.implicitHeight + 2
            radius: 10
            color: "#ffffff"
            border.width: 1
            border.color: "#d6e2ef"
            clip: true

            ColumnLayout {
                id: tableColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 1
                spacing: 0

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 28
                    color: "#f1f5f9"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        spacing: 8

                        Repeater {
                            model: [
                                {"text": "№", "width": root.colNumber},
                                {"text": "Этап", "width": root.colTitle},
                                {"text": "Состояние", "width": root.colStatus},
                                {"text": "Итог", "width": -1},
                                {"text": "Время", "width": root.colTime},
                                {"text": "", "width": root.colAction}
                            ]

                            Text {
                                required property var modelData
                                Layout.preferredWidth: modelData.width > 0 ? modelData.width : -1
                                Layout.fillWidth: modelData.width <= 0
                                text: modelData.text
                                color: root.textSoft
                                font.pixelSize: 11
                                font.bold: true
                                font.family: "Bahnschrift"
                                horizontalAlignment: modelData.text === "Время" ? Text.AlignRight : Text.AlignLeft
                            }
                        }
                    }
                }

                Repeater {
                    model: root.appController ? root.appController.trialSteps : []

                    Rectangle {
                        id: stepRow
                        required property int index
                        required property var modelData

                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        color: stepRow.modelData.current ? "#eaf3ff" : (stepRow.index % 2 === 1 ? "#fbfdff" : "#ffffff")

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: 1
                            color: "#eef2f7"
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            spacing: 8

                            Text {
                                Layout.preferredWidth: root.colNumber
                                text: stepRow.modelData.number
                                color: root.textSoft
                                font.pixelSize: 12
                                font.family: "Bahnschrift"
                            }

                            Text {
                                id: titleCell
                                Layout.preferredWidth: root.colTitle
                                text: stepRow.modelData.title
                                color: root.textMain
                                font.pixelSize: 12
                                font.bold: stepRow.modelData.current === true
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight

                                HoverHandler {
                                    onHoveredChanged: root.setHover(titleCell, hovered, stepRow.modelData.hint)
                                }
                            }

                            Item {
                                Layout.preferredWidth: root.colStatus
                                Layout.fillHeight: true

                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: Math.min(parent.width, chipText.implicitWidth + 16)
                                    height: 22
                                    radius: 11
                                    color: "transparent"
                                    border.width: 1
                                    border.color: stepRow.modelData.statusColor

                                    Text {
                                        id: chipText
                                        anchors.centerIn: parent
                                        text: stepRow.modelData.statusText
                                        color: stepRow.modelData.statusColor
                                        font.pixelSize: 11
                                        font.bold: true
                                        font.family: "Bahnschrift"
                                    }
                                }
                            }

                            Text {
                                id: summaryCell
                                Layout.fillWidth: true
                                text: stepRow.modelData.summary.length > 0 ? stepRow.modelData.summary : "—"
                                color: stepRow.modelData.status === "fail" ? "#b91c1c" : root.textMain
                                font.pixelSize: 12
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight

                                HoverHandler {
                                    onHoveredChanged: root.setHover(summaryCell, hovered, stepRow.modelData.detail)
                                }
                            }

                            Text {
                                Layout.preferredWidth: root.colTime
                                text: stepRow.modelData.duration
                                color: root.textSoft
                                font.pixelSize: 12
                                font.family: "Bahnschrift"
                                horizontalAlignment: Text.AlignRight
                            }

                            FancyButton {
                                Layout.preferredWidth: root.colAction
                                Layout.preferredHeight: 26
                                fontPixelSize: 11
                                text: "Выполнить"
                                tone: "#0284c7"
                                toneHover: "#0369a1"
                                tonePressed: "#075985"
                                enabled: root.ready
                                onClicked: root.appController.runTrialStep(stepRow.modelData.key)
                            }
                        }
                    }
                }
            }
        }

        // --- Журнал проверки ---
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 150
            radius: 10
            color: "#fbfdff"
            border.width: 1
            border.color: "#d6e2ef"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        text: "Журнал проверки"
                        color: root.textMain
                        font.pixelSize: 13
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "что делает каждый этап, какие числа получены и чем он закончился"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }

                    FancyButton {
                        Layout.preferredWidth: 140
                        Layout.preferredHeight: 26
                        fontPixelSize: 11
                        text: "Очистить журнал"
                        tone: "#64748b"
                        toneHover: "#475569"
                        tonePressed: "#334155"
                        enabled: root.appController !== null
                        onClicked: root.appController.clearTrialLog()
                    }
                }

                ListView {
                    id: logView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 2
                    boundsBehavior: Flickable.StopAtBounds
                    model: root.appController ? root.appController.trialLogRows : []

                    // Журнал держится на последней строке, пока оператор сам не прокрутил его вверх.
                    property bool followTail: true
                    onMovementEnded: followTail = atYEnd
                    onCountChanged: if (followTail) Qt.callLater(logView.positionViewAtEnd)
                    onModelChanged: if (followTail) Qt.callLater(logView.positionViewAtEnd)

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                    }

                    delegate: RowLayout {
                        required property var modelData
                        width: logView.width - 16
                        spacing: 8

                        Text {
                            Layout.preferredWidth: 58
                            Layout.alignment: Qt.AlignTop
                            text: modelData.time
                            color: "#94a3b8"
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                        }

                        Text {
                            Layout.fillWidth: true
                            leftPadding: modelData.level === "detail" ? 16 : 0
                            text: modelData.text
                            color: root.logColor(modelData.level)
                            font.pixelSize: 12
                            font.bold: modelData.level === "step"
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }
}
