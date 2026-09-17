import QtQuick 2.15
import QtQuick.Layouts 1.15

/*
  Строка свежести живого числа.
  Назначение:
  - показывает, приходят ли ответы прибора и сколько число не меняется;
  - показывает, мерит ли сам измерительный контур, по возрасту измерения из прибора.

  Публичные свойства:
  - info: словарь из контроллера с полями color, text, deviceColor, deviceText;
  - stacked: две части друг под другом, для узких карточек.
*/
GridLayout {
    id: root

    property var info: ({})
    property bool stacked: false

    columns: root.stacked ? 2 : 4
    columnSpacing: 6
    rowSpacing: 1

    Rectangle {
        width: 8
        height: 8
        radius: 4
        color: root.info.color || "#94a3b8"
    }

    Text {
        Layout.fillWidth: root.stacked
        text: root.info.text || ""
        color: "#475569"
        font.pixelSize: 11
        font.family: "Bahnschrift"
        elide: Text.ElideRight
    }

    Rectangle {
        Layout.leftMargin: root.stacked ? 0 : 6
        width: 8
        height: 8
        radius: 4
        color: root.info.deviceColor || "#94a3b8"
    }

    Text {
        Layout.fillWidth: true
        text: root.info.deviceText || ""
        color: "#475569"
        font.pixelSize: 11
        font.family: "Bahnschrift"
        elide: Text.ElideRight
    }
}
