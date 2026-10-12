import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

/*
  Знак «i» со всплывающей подсказкой.
  Назначение: пояснение показывается при наведении и не занимает место в форме,
  чтобы разделы оставались лаконичными.

  Публичные свойства:
  - tip: текст подсказки (можно с простым HTML: <b>, <br>); пустой - знак скрыт.
*/
Rectangle {
    id: infoMark

    property string tip: ""

    visible: infoMark.tip.length > 0
    Layout.preferredWidth: 16
    Layout.preferredHeight: 16
    Layout.alignment: Qt.AlignVCenter
    implicitWidth: 16
    implicitHeight: 16
    radius: 8
    color: infoArea.containsMouse ? "#0284c7" : "#e0f2fe"
    border.width: 1
    border.color: "#7dd3fc"

    Text {
        anchors.centerIn: parent
        text: "i"
        color: infoArea.containsMouse ? "#ffffff" : "#0369a1"
        font.pixelSize: 11
        font.bold: true
        font.family: "Bahnschrift"
    }

    MouseArea {
        id: infoArea
        anchors.fill: parent
        hoverEnabled: true
    }

    ToolTip {
        visible: infoArea.containsMouse
        delay: 150
        width: Math.min(460, implicitWidth)
        text: infoMark.tip
    }
}
