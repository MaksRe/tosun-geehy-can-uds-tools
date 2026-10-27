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
    readonly property var boards: strip.view.boards || []
    readonly property var toneColors: ({ "ok": "#15803d", "bad": "#dc2626", "run": "#1d4ed8", "normal": "#64748b" })

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
                    width: 204
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
