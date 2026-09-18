import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Миниатюра графика в карточке живого числа.

  Показывает направление и дрожание за время наблюдения и крайние значения
  словами. Нажатие разворачивает полноразмерный график: в миниатюре подписей нет
  и рассмотреть в ней нечего, кроме формы линии.

  Публичные свойства:
  - trend: данные графика от контроллера;
  - textSoft: цвет мелких подписей.

  Сигнал openRequested(): оператор попросил развернуть график.
*/
ColumnLayout {
    id: root

    property var trend: ({})
    property color textSoft: "#607084"

    signal openRequested()

    spacing: 1

    TrendChart {
        id: chart
        Layout.fillWidth: true
        Layout.preferredHeight: 46
        compact: true
        points: root.trend.points || []
        lineColor: root.trend.color || "#0284c7"
        minValue: root.trend.minValue === undefined || root.trend.minValue === null ? NaN : root.trend.minValue
        maxValue: root.trend.maxValue === undefined || root.trend.maxValue === null ? NaN : root.trend.maxValue
        emptyText: "график заполнится при опросе"
        border.color: hoverArea.containsMouse ? "#7cb2ea" : "#e2ebf5"

        MouseArea {
            id: hoverArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.openRequested()

            ToolTip.visible: hoverArea.containsMouse
            ToolTip.text: "Развернуть график"
            ToolTip.delay: 600
        }
    }

    Text {
        Layout.fillWidth: true
        text: root.trend.hasData
              ? "мин " + (root.trend.minShort || "—") + " · макс " + (root.trend.maxShort || "—")
              : "нажмите, чтобы развернуть график"
        color: root.textSoft
        font.pixelSize: 10
        font.family: "Bahnschrift"
        elide: Text.ElideRight
    }

    // Дельта говорит о размахе качки, среднее - о рабочей точке.
    Text {
        Layout.fillWidth: true
        visible: root.trend.hasData === true
        text: "Δ " + (root.trend.deltaText || "—") + " · среднее " + (root.trend.meanText || "—")
        color: root.textSoft
        font.pixelSize: 10
        font.family: "Bahnschrift"
        elide: Text.ElideRight
    }
}
