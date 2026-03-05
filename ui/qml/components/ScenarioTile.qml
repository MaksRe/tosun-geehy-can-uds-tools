import QtQuick 2.15
import QtQuick.Layouts 1.15
import "."

Card {
    id: root

    property string title: ""
    property string statusText: ""
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color accentColor: "#2563eb"
    property color accentColorHover: "#1d4ed8"
    property color baseColor: "#f7fbff"
    property color baseBorder: "#d6e2ef"
    property color chipColor: "#eef4fb"
    property color chipBorder: "#c6d7ea"

    readonly property bool hovered: tileArea.containsMouse
    readonly property bool pressed: tileArea.pressed

    signal clicked()

    cardColor: root.hovered ? Qt.tint(root.baseColor, "#0fffffff") : root.baseColor
    cardBorder: root.hovered ? root.accentColor : root.baseBorder
    implicitHeight: contentColumn.implicitHeight + 24

    y: root.pressed ? 1 : (root.hovered ? -2 : 0)
    scale: root.pressed ? 0.992 : 1.0

    Behavior on y {
        NumberAnimation {
            duration: 120
            easing.type: Easing.OutCubic
        }
    }

    Behavior on scale {
        NumberAnimation {
            duration: 120
            easing.type: Easing.OutCubic
        }
    }

    Behavior on cardBorder {
        ColorAnimation {
            duration: 120
        }
    }

    Behavior on cardColor {
        ColorAnimation {
            duration: 120
        }
    }

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        Text {
            text: root.title
            color: root.textMain
            font.pixelSize: 16
            font.bold: true
            font.family: "Bahnschrift"
        }

        StatusChip {
            Layout.fillWidth: true
            label: root.statusText
            chipColor: root.chipColor
            chipBorder: root.chipBorder
            textColor: root.textMain
        }
    }

    MouseArea {
        id: tileArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
