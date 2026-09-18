import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Ёмкость обоих контуров в отсчётах и пикофарадах и её плавание.

  ЗАЧЕМ
  Отсчёт контура - это время между порогами компараторов, и сам по себе он ни о
  чём не говорит. В пикофарадах видно, похожа ли ёмкость на расчётную по
  геометрии датчика, а плавание показывает, насколько устойчиво измерение: при
  спокойном контуре оно единицы отсчётов, а при наводке или плохом контакте
  сразу десятки.

  Эффективным считается среднее по окну захвата - то самое число, которое уходит
  в отметку по кнопке «Взять захват».

  Публичные свойства:
  - appController: контроллер приложения;
  - textMain/textSoft: палитра окна.
*/
Rectangle {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property bool wide: true

    readonly property var capacitance: root.appController ? root.appController.capacitance : ({})

    Layout.fillWidth: true
    Layout.preferredHeight: layout.implicitHeight + 24
    radius: 12
    color: "#fbfdff"
    border.width: 1
    border.color: "#e2ebf5"

    ColumnLayout {
        id: layout
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        Text {
            text: "Ёмкость контуров"
            color: root.textMain
            font.pixelSize: 15
            font.bold: true
            font.family: "Bahnschrift"
        }

        GridLayout {
            Layout.fillWidth: true
            columns: root.wide ? 2 : 1
            columnSpacing: 10
            rowSpacing: 8

            Repeater {
                model: [
                    { "key": "main", "title": "Основной контур", "accent": "#0284c7", "bg": "#f2f7ff", "border": "#c6dcf5" },
                    { "key": "media", "title": "Плоский конденсатор", "accent": "#0f766e", "bg": "#effaf7", "border": "#a7ddd2" }
                ]

                Rectangle {
                    id: circuitCard
                    required property var modelData
                    readonly property var info: root.capacitance[circuitCard.modelData.key] || ({})

                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredHeight: circuitLayout.implicitHeight + 20
                    radius: 10
                    color: circuitCard.modelData.bg
                    border.width: 1
                    border.color: circuitCard.info.warn ? "#f5c98b" : circuitCard.modelData.border

                    ColumnLayout {
                        id: circuitLayout
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 2

                        Text {
                            text: circuitCard.modelData.title
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            Text {
                                text: circuitCard.info.effectivePf || "—"
                                color: circuitCard.modelData.accent
                                font.pixelSize: 24
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            Text {
                                Layout.alignment: Qt.AlignBottom
                                Layout.bottomMargin: 3
                                text: "эффективная, " + (circuitCard.info.effectiveCounts || "—")
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                            }

                            Item { Layout.fillWidth: true }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "сейчас " + (circuitCard.info.currentCounts || "—") + " · " + (circuitCard.info.currentPf || "—")
                            color: root.textMain
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "плавание " + (circuitCard.info.swingText || "—")
                            color: circuitCard.info.warn ? "#b45309" : root.textSoft
                            font.pixelSize: 12
                            font.bold: circuitCard.info.warn === true
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: circuitCard.info.spreadText || ""
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: circuitCard.info.offsetText || ""
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: root.capacitance.note || ""
            color: root.textSoft
            font.pixelSize: 11
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
        }
    }
}
