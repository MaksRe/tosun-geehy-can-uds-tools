import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

Card {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    readonly property int contentPadding: 14

    Layout.fillWidth: true
    Layout.fillHeight: true
    Layout.minimumHeight: 280

    implicitHeight: 320

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.contentPadding
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                text: "Системный лог"
                color: root.textMain
                font.pixelSize: 18
                font.bold: true
                font.family: "Bahnschrift"
            }

            Text {
                text: "UDS, ответы, служебные события"
                color: root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
            }

            Item { Layout.fillWidth: true }

            Text {
                text: "Записей: " + (root.appController ? root.appController.logs.length : 0)
                color: root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
            }

            FancyButton {
                text: "Очистить"
                Layout.preferredWidth: 98
                Layout.preferredHeight: 32
                fontPixelSize: 12
                tone: "#64748b"
                toneHover: "#55657a"
                tonePressed: "#465669"
                onClicked: if (root.appController) root.appController.clearLogs()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 12
            color: "#f4f8fd"
            border.color: "#d6e2ef"

            ListView {
                id: logList
                anchors.fill: parent
                anchors.margins: 8
                clip: true
                spacing: 1
                model: root.appController ? root.appController.logs : []

                onCountChanged: if (count > 0) positionViewAtEnd()

                delegate: Rectangle {
                    width: logList.width
                    height: Math.max(24, logRow.implicitHeight + 4)
                    radius: 5
                    color: index % 2 === 0 ? "#f8fbff" : "#edf3fa"

                    RowLayout {
                        id: logRow
                        anchors.fill: parent
                        anchors.leftMargin: 5
                        anchors.rightMargin: 5
                        spacing: 5

                        Text {
                            Layout.preferredWidth: 80
                            Layout.minimumWidth: 80
                            Layout.alignment: Qt.AlignVCenter
                            Layout.fillHeight: true
                            text: modelData.time
                            color: root.textSoft
                            font.pixelSize: 10
                            font.family: "Consolas"
                            horizontalAlignment: Text.AlignLeft
                            verticalAlignment: Text.AlignVCenter
                        }

                        Rectangle {
                            Layout.preferredWidth: 4
                            Layout.fillHeight: true
                            Layout.topMargin: 2
                            Layout.bottomMargin: 2
                            radius: 2
                            color: modelData.color ? modelData.color : "#94a3b8"
                            opacity: 0.9
                        }

                        Text {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.preferredHeight: implicitHeight
                            Layout.alignment: Qt.AlignVCenter
                            text: modelData.text
                            color: modelData.color ? modelData.color : root.textMain
                            wrapMode: Text.Wrap
                            verticalAlignment: Text.AlignVCenter
                            font.pixelSize: 10
                            font.family: "Bahnschrift"
                        }
                    }
                }

                ScrollBar.vertical: ScrollBar {}
            }
        }
    }
}
