import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Тестовая точка «полное погружение» плоского конденсатора.

  ЗАЧЕМ
  Плоский конденсатор подключён к плате коаксиальным кабелем, а длина кабеля
  равна длине трубки основного датчика. Значит, при погружении меняется не только
  ёмкость самого конденсатора, но и ёмкость кабеля, и в опорных точках эта
  добавка неразличима. Точка «полное погружение» снимается отдельно и стоит рядом
  с опорными: по разнице с ними видно, сколько дал кабель.

  В ПРИБОР НЕ ПИШЕТСЯ
  Точка живёт только в программе и ни на что в приборе не влияет: это отладочное
  измерение, а не калибровка.

  Публичные свойства:
  - point: данные точки от контроллера;
  - capturedText: текущий захват плоского конденсатора;
  - enabledActions: доступны ли кнопки;
  - textMain/textSoft/inputBg/inputBorder/inputFocus: палитра окна.

  Сигналы:
  - saveRequested(valueText): запомнить точку; пустая строка - взять захват;
  - clearRequested(): забыть точку.
*/
Rectangle {
    id: root

    property var point: ({})
    property string capturedText: "-"
    property bool enabledActions: true
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"

    signal saveRequested(string valueText)
    signal clearRequested()

    Layout.fillWidth: true
    implicitHeight: blockLayout.implicitHeight + 16
    radius: 10
    color: "#fffdf7"
    border.width: 1
    border.color: "#e7d8b8"

    // Полоса слева цвета контура вида топлива: точка относится к плоскому конденсатору.
    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 6
        width: 4
        radius: 2
        color: "#0f766e"
    }

    ColumnLayout {
        id: blockLayout
        anchors.fill: parent
        anchors.margins: 8
        anchors.leftMargin: 18
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
                Layout.fillWidth: true
                text: "Плоский конденсатор: полное погружение"
                color: root.textMain
                font.pixelSize: 14
                font.bold: true
                font.family: "Bahnschrift"
                elide: Text.ElideRight
            }

            Rectangle {
                radius: 7
                color: "#fef3c7"
                border.color: "#fcd34d"
                implicitWidth: onlyTestLabel.implicitWidth + 12
                implicitHeight: 22

                Text {
                    id: onlyTestLabel
                    anchors.centerIn: parent
                    text: "только проверка"
                    color: "#92400e"
                    font.pixelSize: 10
                    font.bold: true
                    font.family: "Bahnschrift"
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: "В прибор не пишется. Длина коаксиального кабеля равна длине трубки, поэтому при погружении "
                + "растёт и его ёмкость. Разница с точкой «топливо» и показывает вклад кабеля."
            color: root.textSoft
            font.pixelSize: 11
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            FancyButton {
                Layout.preferredWidth: 116
                Layout.preferredHeight: 30
                text: "Взять захват"
                tone: "#0f766e"
                toneHover: "#115e59"
                tonePressed: "#134e4a"
                toolTipText: "Подставить в поле усреднённое показание плоского конденсатора"
                enabled: root.capturedText !== "-"
                onClicked: {
                    valueSwitch.checked = true
                    valueField.text = root.capturedText
                }
            }

            FancySwitch {
                id: valueSwitch
                trackWidth: 40
                trackHeight: 22
            }

            FancyTextField {
                id: valueField
                Layout.fillWidth: true
                Layout.minimumWidth: 70
                Layout.preferredHeight: 30
                enabled: valueSwitch.checked
                text: ""
                placeholderText: "Захват / вручную"
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
            }

            FancyButton {
                Layout.preferredWidth: 104
                Layout.preferredHeight: 30
                text: "Запомнить"
                tone: "#0284c7"
                toneHover: "#0369a1"
                tonePressed: "#075985"
                enabled: root.enabledActions
                onClicked: root.saveRequested(valueSwitch.checked ? valueField.text : "")
            }

            FancyButton {
                Layout.preferredWidth: 88
                Layout.preferredHeight: 30
                text: "Забыть"
                tone: "#94a3b8"
                toneHover: "#64748b"
                tonePressed: "#475569"
                enabled: root.enabledActions && root.point.has === true
                onClicked: root.clearRequested()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: root.point.has === true
            spacing: 12

            Text {
                text: (root.point.countsText || "—") + " · " + (root.point.pfText || "—")
                color: "#0f766e"
                font.pixelSize: 16
                font.bold: true
                font.family: "Bahnschrift"
            }

            Text {
                Layout.fillWidth: true
                text: (root.point.atText || "") + (root.point.spreadText ? ", " + root.point.spreadText : "")
                color: root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
                elide: Text.ElideRight
            }
        }

        Text {
            Layout.fillWidth: true
            visible: root.point.has === true
            text: root.point.vsAirText || ""
            color: root.textSoft
            font.pixelSize: 12
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
        }

        Text {
            Layout.fillWidth: true
            visible: root.point.has === true
            text: root.point.vsFuelText || ""
            color: root.textMain
            font.pixelSize: 12
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
        }

        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: root.point.statusText || ""
            color: root.point.statusColor || root.textSoft
            font.pixelSize: 11
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
        }
    }
}
