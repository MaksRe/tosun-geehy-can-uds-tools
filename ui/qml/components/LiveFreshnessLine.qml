import QtQuick 2.15
import QtQuick.Layouts 1.15

/*
  Строка свежести живого числа.
  Назначение:
  - показывает, приходят ли ответы прибора и сколько число не меняется;
  - показывает, мерит ли сам измерительный контур, по возрасту измерения из прибора.

  Публичные свойства:
  - info: словарь из контроллера с полями color, text, deviceColor, deviceText.
*/
RowLayout {
    id: root

    property var info: ({})

    spacing: 6

    Rectangle {
        width: 8
        height: 8
        radius: 4
        color: root.info.color || "#94a3b8"
    }

    Text {
        text: root.info.text || ""
        color: "#475569"
        font.pixelSize: 11
        font.family: "Bahnschrift"
    }

    Rectangle {
        Layout.leftMargin: 6
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
