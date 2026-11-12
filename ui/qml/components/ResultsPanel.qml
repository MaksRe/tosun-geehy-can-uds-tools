import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Итоги прогона прямо в окне: по чему видно, удался ли прогон, без скачивания файлов.
  Источник - appController.chamberResults (chamber_results.py):
  - при нескольких платах - сводка по платам и выбор платы;
  - итог платы одной строкой (значок по важности, разбор по нажатию);
  - сводные показатели с подсказками «i»;
  - таблицы: покрытие узлов, этап 1, этап 2, погружение - у каждого столбца подсказка.
*/
ColumnLayout {
    id: panel

    property var appController: null
    readonly property var results: panel.appController ? panel.appController.chamberResults : ({})
    readonly property var boards: panel.results.boards || []
    property int picked: -1
    readonly property int index: {
        if (panel.picked >= 0 && panel.picked < panel.boards.length)
            return panel.picked
        for (let i = 0; i < panel.boards.length; ++i)
            if (panel.boards[i].shown)
                return i
        return 0
    }
    readonly property var board: panel.boards.length > 0 ? panel.boards[panel.index] : ({})
    readonly property var toneColor: ({ "ok": "#16a34a", "warn": "#d97706", "bad": "#dc2626", "info": "#2563eb" })

    spacing: 10
    Layout.fillWidth: true

    ResultsTable {
        visible: !!panel.results.overview
        table: panel.results.overview || ({})
    }

    // Выбор платы: точка - итог платы (зелёная - всё снято, жёлтая - не хватает данных).
    Flow {
        Layout.fillWidth: true
        visible: panel.boards.length > 1
        spacing: 6

        Repeater {
            model: panel.boards

            Rectangle {
                id: chip
                required property var modelData
                required property int index
                readonly property bool current: chip.index === panel.index
                width: chipRow.implicitWidth + 20
                height: 30
                radius: 15
                color: chip.current ? "#e0f2fe" : (chipArea.containsMouse ? "#f1f5f9" : "#ffffff")
                border.width: chip.current ? 2 : 1
                border.color: chip.current ? "#0284c7" : "#cbd5e1"

                Row {
                    id: chipRow
                    anchors.centerIn: parent
                    spacing: 6
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 9; height: 9; radius: 5
                        color: panel.toneColor[chip.modelData.tone] || "#94a3b8"
                    }
                    Text {
                        text: chip.modelData.name + "  " + chip.modelData.sa
                        color: "#0f172a"
                        font.pixelSize: 12
                        font.bold: chip.current
                        font.family: "Bahnschrift"
                    }
                }

                MouseArea {
                    id: chipArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: panel.picked = chip.index
                }
            }
        }
    }

    NoticeLine {
        appController: panel.appController
        text: panel.board.verdict || ""
        tone: panel.board.tone || "info"
        kind: "Итоги прогона" + (panel.board.sa ? " · " + panel.board.name + " " + panel.board.sa : "")
        fontSize: 13
    }

    // Сводные показатели таблицей «Показатель | Значение»: сетка, шапка, строки через одну, у показателя - «i».
    Column {
        id: summaryTable
        visible: (panel.board.summary || []).length > 0
        readonly property int labelWidth: 380
        readonly property int valueWidth: Math.max(260, Math.min(560, panel.width - summaryTable.labelWidth))
        Layout.preferredWidth: summaryTable.labelWidth + summaryTable.valueWidth
        Layout.preferredHeight: implicitHeight

        Row {
            Repeater {
                model: [["Показатель", summaryTable.labelWidth], ["Значение", summaryTable.valueWidth]]

                Rectangle {
                    id: summaryHead
                    required property var modelData
                    width: summaryHead.modelData[1]
                    height: 28
                    color: "#e8eef5"
                    border.width: 1
                    border.color: "#c5d0dc"

                    Text {
                        anchors.centerIn: parent
                        text: summaryHead.modelData[0]
                        color: "#334155"
                        font.pixelSize: 11
                        font.bold: true
                        font.family: "Bahnschrift"
                    }
                }
            }
        }

        Repeater {
            model: panel.board.summary || []

            Row {
                id: summaryItem
                required property var modelData
                required property int index
                readonly property color rowColor: summaryItem.index % 2 === 1 ? "#f5f8fb" : "#ffffff"

                Rectangle {
                    width: summaryTable.labelWidth
                    height: Math.max(28, summaryValue.implicitHeight + 10)
                    color: summaryItem.rowColor
                    border.width: 1
                    border.color: "#dbe3ec"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 6
                        spacing: 6

                        Text {
                            Layout.fillWidth: true
                            text: summaryItem.modelData.label
                            color: "#1f2d3d"
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                        InfoMark { tip: summaryItem.modelData.tip || "" }
                    }
                }

                Rectangle {
                    width: summaryTable.valueWidth
                    height: Math.max(28, summaryValue.implicitHeight + 10)
                    color: summaryItem.rowColor
                    border.width: 1
                    border.color: "#dbe3ec"

                    Text {
                        id: summaryValue
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        text: summaryItem.modelData.value
                        color: summaryItem.modelData.tone === "warn" ? "#b45309"
                               : (summaryItem.modelData.tone === "ok" ? "#15803d" : "#0f172a")
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }

    Repeater {
        model: panel.board.tables || []

        ResultsTable {
            required property var modelData
            table: modelData
        }
    }

    Text {
        visible: (panel.results.time || "").length > 0
        text: "Посчитано по журналам точек " + (panel.results.time || "")
              + ((panel.results.file || "").length > 0 ? "  ·  показанная плата: " + panel.results.file : "")
        color: "#94a3b8"
        font.pixelSize: 11
        font.family: "Bahnschrift"
    }
}
