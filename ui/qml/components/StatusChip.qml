import QtQuick 2.15

/*
  Небольшой индикатор статуса в шапке экрана.
  Назначение:
  - отображает текущее состояние системы кратким текстом;
  - цветом показывает норму/ошибку/активность.

  Публичные свойства:
  - label: текст статуса;
  - chipColor/chipBorder: цвета фона и рамки;
  - textColor: цвет текста.
*/
Rectangle {
    id: root

    property string label: ""
    property color chipColor: "#eef4fb"
    property color chipBorder: "#c6d7ea"
    property color textColor: "#1f2d3d"

    radius: 9
    color: chipColor
    border.color: chipBorder
    border.width: 1
    implicitHeight: 28
    implicitWidth: labelText.implicitWidth + 16

    // Текст занимает всю ширину чипа и обрезается многоточием: длинный статус
    // больше не вылезает за рамку, когда чип растянут по ширине карточки.
    Text {
        id: labelText
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        text: root.label
        color: root.textColor
        font.pixelSize: 12
        font.family: "Bahnschrift"
    }
}
