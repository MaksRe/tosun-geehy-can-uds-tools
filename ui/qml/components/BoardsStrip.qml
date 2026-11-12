import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Лента плат над разделами калибровки (режим «несколько плат в камере»).
  Назначение:
  - видно сразу все платы камеры: температура платы, оба контура, точки,
    таблицы и профиль - не нужно переключаться между ними, чтобы следить;
  - щелчок по плитке показывает эту плату во всех разделах (данные узла,
    профиль, прогон, пробная калибровка);
  - пока лента видна, программа опрашивает все платы (в любом разделе).

  Публичные свойства:
  - appController: контроллер приложения;
  - textMain/textSoft: общая палитра окна.
*/
Rectangle {
    id: strip

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"

    readonly property var view: strip.appController ? strip.appController.chamberBoards : ({})
    // Только платы в работе: участники прогона, вне прогона - те, что на шине.
    readonly property var boards: (strip.view.boards || []).filter(function(board) { return board.working !== false })
    readonly property var toneColors: ({ "ok": "#15803d", "bad": "#dc2626", "run": "#1d4ed8", "normal": "#64748b" })

    // Ряд меток узлов одного этапа: зелёная - в узле снято, серая - нет; наведение - что именно.
    component NodeMarks: RowLayout {
        id: marksRow
        property var marks: []
        property string field: "board"
        property string label: ""
        property bool liquid: false
        property bool showLiquid: false
        spacing: 3

        Text {
            Layout.preferredWidth: 40
            text: marksRow.label
            color: strip.textSoft
            font.pixelSize: 9
            font.family: "Bahnschrift"
        }

        Repeater {
            model: marksRow.marks

            Rectangle {
                id: nodeDot
                required property var modelData
                readonly property bool done: marksRow.field === "board" ? !!nodeDot.modelData.board
                                                                        : (nodeDot.modelData[marksRow.field] || 0) > 0
                Layout.preferredWidth: 20
                Layout.preferredHeight: 12
                radius: 6
                color: nodeDot.done ? (marksRow.field === "board" ? "#16a34a" : "#0d9488") : "#f1f5f9"
                border.width: 1
                border.color: nodeDot.done ? (marksRow.field === "board" ? "#15803d" : "#0f766e") : "#cbd5e1"

                Text {
                    anchors.centerIn: parent
                    text: nodeDot.modelData.short
                    color: nodeDot.done ? "#ffffff" : "#94a3b8"
                    font.pixelSize: 8
                    font.family: "Bahnschrift"
                }

                MouseArea {
                    id: dotArea
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                }

                ToolTip {
                    visible: dotArea.containsMouse
                    delay: 150
                    text: nodeDot.modelData.tip || nodeDot.modelData.node
                }
            }
        }

        // «Жидкость» снимается один раз при комнатной - отдельная метка в конце ряда «в сборе».
        Rectangle {
            visible: marksRow.showLiquid
            Layout.preferredWidth: 14
            Layout.preferredHeight: 12
            radius: 6
            color: marksRow.liquid ? "#2563eb" : "#f1f5f9"
            border.width: 1
            border.color: marksRow.liquid ? "#1d4ed8" : "#cbd5e1"

            Text {
                anchors.centerIn: parent
                text: "Ж"
                color: marksRow.liquid ? "#ffffff" : "#94a3b8"
                font.pixelSize: 8
                font.bold: true
                font.family: "Bahnschrift"
            }

            MouseArea {
                id: liquidArea
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }

            ToolTip {
                visible: liquidArea.containsMouse
                delay: 150
                text: marksRow.liquid ? "«Жидкость» снята: строки «в жидкости» достроятся по размаху"
                                      : "«Жидкость» ещё не снята: после прогона при комнатной погрузите трубку и запишите точку"
            }
        }
    }

    implicitHeight: stripLayout.implicitHeight + 20
    radius: 12
    color: "#f8fbff"
    border.width: 1
    border.color: "#d6e2ef"

    onVisibleChanged: if (strip.appController) strip.appController.setBoardsStripVisible(strip.visible)
    Component.onCompleted: if (strip.appController) strip.appController.setBoardsStripVisible(strip.visible)

    ColumnLayout {
        id: stripLayout
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                text: "Платы в камере"
                color: strip.textMain
                font.pixelSize: 13
                font.bold: true
                font.family: "Bahnschrift"
            }
            Text {
                text: String(strip.boards.length)
                color: strip.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
            }
            Item { Layout.fillWidth: true }
            Text {
                visible: (strip.view.switchNote || "").length > 0
                text: strip.view.switchNote || ""
                color: "#b45309"
                font.pixelSize: 11
                font.family: "Bahnschrift"
                elide: Text.ElideRight
                Layout.maximumWidth: 520
            }
            Text {
                visible: !(strip.view.switchNote || "").length
                text: strip.view.shownName ? "ниже показана «" + strip.view.shownName + "» (" + strip.view.shownSa
                                             + ") · щелчок по плате - показать её во всех разделах" : ""
                color: strip.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
                elide: Text.ElideLeft
                Layout.maximumWidth: 560
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 8

            Repeater {
                model: strip.boards

                Rectangle {
                    id: tile
                    required property var modelData
                    readonly property bool shown: !!tile.modelData.active
                    width: 240
                    height: tileLayout.implicitHeight + 16
                    radius: 10
                    color: tile.shown ? "#eff6ff" : (tileArea.containsMouse ? "#f8fafc" : "#ffffff")
                    border.width: tile.shown ? 2 : 1
                    border.color: tile.shown ? "#3b82f6" : "#e2e8f0"

                    ColumnLayout {
                        id: tileLayout
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 3

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            // Свежие ли показания: зелёный - температура платы приходит, серый - молчит.
                            Rectangle {
                                Layout.preferredWidth: 8
                                Layout.preferredHeight: 8
                                radius: 4
                                color: tile.modelData.fresh ? "#16a34a" : "#cbd5e1"
                            }
                            Text {
                                text: tile.modelData.name
                                color: strip.textMain
                                font.pixelSize: 13
                                font.bold: true
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                                Layout.maximumWidth: 90
                            }
                            Text {
                                text: tile.modelData.saText
                                color: "#1d4ed8"
                                font.pixelSize: 11
                                font.bold: true
                                font.family: "Consolas"
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: tile.modelData.boardTemp
                                color: strip.textMain
                                font.pixelSize: 13
                                font.bold: true
                                font.family: "Bahnschrift"
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "осн " + tile.modelData.main + " · вид " + tile.modelData.media
                            color: strip.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                        // Узлы температуры по двум этапам: «плата» - точка первого этапа с эталонами,
                        // «в сборе» - сухая трубка (узел по датчику трубки ±3 °C), «Ж» - снята «жидкость».
                        NodeMarks { marks: tile.modelData.nodes || []; field: "board"; label: "плата" }
                        NodeMarks {
                            marks: tile.modelData.nodes || []
                            field: "air"
                            label: "в сборе"
                            liquid: !!(tile.modelData.stages || {}).liquid
                            showLiquid: true
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Text {
                                text: "точек " + tile.modelData.points
                                      + (tile.modelData.tablesComplete ? " · таблицы ✓" : "")
                                color: strip.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: tile.modelData.profileState || ""
                                color: strip.toneColors[tile.modelData.profileTone] || strip.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                                Layout.maximumWidth: 110
                            }
                        }
                    }

                    MouseArea {
                        id: tileArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: tile.shown ? Qt.ArrowCursor : Qt.PointingHandCursor
                        onClicked: if (strip.appController && !tile.shown) strip.appController.selectChamberBoard(tile.modelData.sa)
                    }
                    ToolTip.visible: tileArea.containsMouse && !tile.shown
                    ToolTip.delay: 600
                    ToolTip.text: "Показать «" + tile.modelData.name + "» во всех разделах"
                }
            }
        }
    }
}
