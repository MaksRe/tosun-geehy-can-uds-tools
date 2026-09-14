import QtQuick 2.15
import QtQuick.Layouts 1.15

/*
  Карточка одного шага пробной калибровки.
  Показывает номер, название, что подключить, состояние проверки и её итог.
  Кнопки шага объявляются внутри карточки и попадают в нижний ряд.
*/
Rectangle {
    id: root

    property int number: 0
    property string title: ""
    property string hint: ""
    property string statusText: ""
    property color statusColor: "#64748b"
    property string detail: ""
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    default property alias actions: actionsRow.data

    implicitHeight: stepLayout.implicitHeight + 20
    radius: 12
    color: "#ffffff"
    border.width: 1
    border.color: "#d6e2ef"

    RowLayout {
        id: stepLayout
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 10
        spacing: 12

        Rectangle {
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 30
            Layout.preferredHeight: 30
            radius: 15
            color: root.statusColor

            Text {
                anchors.centerIn: parent
                text: root.number
                color: "#ffffff"
                font.pixelSize: 14
                font.bold: true
                font.family: "Bahnschrift"
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    Layout.fillWidth: true
                    text: root.title
                    color: root.textMain
                    font.pixelSize: 14
                    font.bold: true
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }

                Rectangle {
                    Layout.preferredWidth: chipText.implicitWidth + 18
                    Layout.preferredHeight: 22
                    radius: 11
                    color: "transparent"
                    border.width: 1
                    border.color: root.statusColor

                    Text {
                        id: chipText
                        anchors.centerIn: parent
                        text: root.statusText
                        color: root.statusColor
                        font.pixelSize: 11
                        font.bold: true
                        font.family: "Bahnschrift"
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: root.hint
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }

            Text {
                Layout.fillWidth: true
                visible: root.detail.length > 0
                text: root.detail
                color: root.textMain
                font.pixelSize: 12
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }

            RowLayout {
                id: actionsRow
                Layout.fillWidth: true
                Layout.topMargin: 2
                spacing: 8
            }
        }
    }
}
