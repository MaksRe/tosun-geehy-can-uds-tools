import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

/*
  Универсальный спойлер для дополнительных карточек интерфейса.
  Содержимое раскрывается/сворачивается по клику на заголовок.
*/
ColumnLayout {
    id: root

    property string title: ""
    property string hintText: "Дополнительный функционал"
    property bool expanded: false
    property color cardColor: "#ffffff"
    property color cardBorder: "#d6e2ef"
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color accentColor: "#2563eb"
    property bool contentFillAvailableHeight: false

    default property alias contentData: contentLayout.data

    Layout.fillWidth: true
    implicitHeight: headerRect.implicitHeight
                    + (root.expanded
                       ? (
                           root.contentFillAvailableHeight
                           ? 0
                           : (root.spacing + contentLayout.implicitHeight)
                         )
                       : 0)
    spacing: 6

    Rectangle {
        id: headerRect
        Layout.fillWidth: true
        implicitHeight: 44
        radius: 10
        color: root.cardColor
        border.color: root.cardBorder
        border.width: 1

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 8

            Rectangle {
                width: 20
                height: 20
                radius: 10
                color: root.expanded ? "#e8f2ff" : "#f1f5fa"
                border.color: root.expanded ? root.accentColor : root.cardBorder
                border.width: 1

                Text {
                    anchors.centerIn: parent
                    text: root.expanded ? "−" : "+"
                    color: root.expanded ? root.accentColor : root.textSoft
                    font.family: "Bahnschrift"
                    font.pixelSize: 15
                    font.bold: true
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Text {
                    Layout.fillWidth: true
                    text: root.title
                    color: root.textMain
                    font.family: "Bahnschrift"
                    font.pixelSize: 13
                    font.bold: true
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: root.hintText
                    color: root.textSoft
                    font.family: "Bahnschrift"
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
            }
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.expanded = !root.expanded
        }
    }

    ColumnLayout {
        id: contentLayout
        Layout.fillWidth: true
        Layout.fillHeight: root.expanded && root.contentFillAvailableHeight
        Layout.minimumHeight: 0
        Layout.preferredHeight: root.expanded
                                ? (root.contentFillAvailableHeight ? -1 : contentLayout.implicitHeight)
                                : 0
        Layout.maximumHeight: root.expanded
                              ? (root.contentFillAvailableHeight ? 16777215 : contentLayout.implicitHeight)
                              : 0
        spacing: 0
        visible: root.expanded
        opacity: root.expanded ? 1 : 0

        Behavior on opacity {
            NumberAnimation {
                duration: 140
                easing.type: Easing.OutCubic
            }
        }
    }
}
