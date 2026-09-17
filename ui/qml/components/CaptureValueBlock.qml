import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Блок одного сохраняемого значения: отметка бака или точка плоского конденсатора.
  Назначение:
  - показывает, что лежит в приборе, и короткое состояние;
  - подставляет в поле усреднённый захват своего контура или принимает число вручную;
  - отдаёт команды прочитать и записать значение.

  Отметки и точки устроены одинаково, чтобы оператор делал одно и то же: дождался
  захвата, нажал «Взять захват», затем «Сохранить».

  Публичные свойства:
  - title: подпись значения, с названием контура;
  - chipText/chipOk: короткое состояние и его цвет;
  - savedText: значение в приборе;
  - capturedText: усреднённый захват контура или «-»;
  - captureHint: подсказка к кнопке захвата;
  - accent: цвет полосы слева, как у карточки своего контура;
  - saveEnabled/readEnabled: доступность кнопок;
  - textMain/textSoft/inputBg/inputBorder/inputFocus: палитра окна.

  Сигналы:
  - readRequested(): прочитать значение из прибора;
  - saveRequested(valueText): записать; пустая строка означает текущее показание прибора.
*/
Rectangle {
    id: root

    property string title: ""
    property string chipText: ""
    property bool chipOk: false
    property string savedText: "-"
    property string capturedText: "-"
    property string captureHint: "Подставить в поле усреднённое показание"
    property color accent: "#0284c7"
    property bool saveEnabled: true
    property bool readEnabled: true
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"

    signal readRequested()
    signal saveRequested(string valueText)

    // Подставляет значение из резервной копии, пока оператор не печатает в поле.
    function setValueIfIdle(value) {
        if (!valueField.activeFocus)
            valueField.text = (value && value !== "-") ? value : ""
    }

    Layout.fillWidth: true
    implicitHeight: blockLayout.implicitHeight + 16
    radius: 10
    color: "#ffffff"
    border.width: 1
    border.color: "#d6e2ef"

    // Полоса слева в цвет карточки своего контура: сразу видно, к какому конденсатору относится блок.
    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 6
        width: 4
        radius: 2
        color: root.accent
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
                Layout.minimumWidth: 80
                text: root.title
                color: root.textMain
                font.pixelSize: 14
                font.bold: true
                font.family: "Bahnschrift"
                elide: Text.ElideRight
            }

            Rectangle {
                visible: root.chipText !== ""
                radius: 7
                color: root.chipOk ? "#dcfce7" : "#e2e8f0"
                border.color: root.chipOk ? "#86efac" : "#cbd5e1"
                implicitWidth: chipLabel.implicitWidth + 12
                implicitHeight: 22

                Text {
                    id: chipLabel
                    anchors.centerIn: parent
                    text: root.chipText
                    color: root.chipOk ? "#166534" : "#475569"
                    font.pixelSize: 10
                    font.bold: true
                    font.family: "Bahnschrift"
                }
            }

            Text {
                text: "В приборе: " + root.savedText
                color: root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
            }

            FancyButton {
                Layout.preferredWidth: 96
                Layout.preferredHeight: 30
                text: "Прочитать"
                tone: "#0f766e"
                toneHover: "#115e59"
                tonePressed: "#134e4a"
                enabled: root.readEnabled
                onClicked: root.readRequested()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            FancyButton {
                Layout.preferredWidth: 116
                Layout.preferredHeight: 30
                text: "Взять захват"
                tone: "#0284c7"
                toneHover: "#0369a1"
                tonePressed: "#075985"
                toolTipText: root.captureHint
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
                placeholderText: "Текущее / вручную"
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
            }

            FancyButton {
                Layout.preferredWidth: 98
                Layout.preferredHeight: 30
                text: "Сохранить"
                tone: "#16a34a"
                toneHover: "#15803d"
                tonePressed: "#166534"
                enabled: root.saveEnabled
                onClicked: root.saveRequested(valueSwitch.checked ? valueField.text : "")
            }
        }
    }
}
