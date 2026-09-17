import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Блок одной отметки бака: 0 % или 100 %.
  Назначение:
  - показывает, что лежит в приборе и записана ли отметка в этом сеансе;
  - подставляет в поле усреднённый захват основного контура или принимает число вручную;
  - отдаёт команды прочитать и записать отметку.

  Публичные свойства:
  - appController: контроллер приложения;
  - title: подпись отметки;
  - writtenStage: с какой стадии сценария отметка считается записанной;
  - savedText: значение в приборе;
  - textMain/textSoft/inputBg/inputBorder/inputFocus: палитра окна.

  Сигналы:
  - readRequested(): прочитать отметку из прибора;
  - saveRequested(valueText): записать; пустая строка означает текущее показание прибора.
*/
Rectangle {
    id: root

    property var appController
    property string title: ""
    property int writtenStage: 2
    property string savedText: "-"
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"

    signal readRequested()
    signal saveRequested(string valueText)

    readonly property int stage: root.appController ? root.appController.calibrationWizardStage : 0
    readonly property string captured: root.appController ? root.appController.calibrationCapturedLevelText : "-"

    // Подставляет значение из резервной копии, пока оператор не печатает в поле.
    function setValueIfIdle(value) {
        if (!valueField.activeFocus)
            valueField.text = (value && value !== "-") ? value : ""
    }

    Layout.fillWidth: true
    implicitHeight: markLayout.implicitHeight + 16
    radius: 10
    color: "#ffffff"
    border.width: 1
    border.color: "#d6e2ef"

    // Синяя полоса: отметка относится к основному контуру, как и его живая карточка.
    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 6
        width: 4
        radius: 2
        color: "#0284c7"
    }

    ColumnLayout {
        id: markLayout
        anchors.fill: parent
        anchors.margins: 8
        anchors.leftMargin: 18
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
                text: root.title
                color: root.textMain
                font.pixelSize: 14
                font.bold: true
                font.family: "Bahnschrift"
            }

            Rectangle {
                radius: 7
                color: root.stage >= root.writtenStage ? "#dcfce7" : "#e2e8f0"
                border.color: root.stage >= root.writtenStage ? "#86efac" : "#cbd5e1"
                implicitWidth: chipText.implicitWidth + 12
                implicitHeight: 22

                Text {
                    id: chipText
                    anchors.centerIn: parent
                    text: root.stage >= 4 ? "ОК" : (root.stage >= root.writtenStage ? "Записан" : "Ожидание")
                    color: root.stage >= root.writtenStage ? "#166534" : "#475569"
                    font.pixelSize: 10
                    font.bold: true
                    font.family: "Bahnschrift"
                }
            }

            Item { Layout.fillWidth: true }

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
                enabled: root.appController !== null
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
                toolTipText: "Подставить в поле усреднённое показание основного контура"
                enabled: root.captured !== "-"
                onClicked: {
                    valueSwitch.checked = true
                    valueField.text = root.captured
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
                enabled: root.appController !== null
                onClicked: root.saveRequested(valueSwitch.checked ? valueField.text : "")
            }
        }
    }
}
