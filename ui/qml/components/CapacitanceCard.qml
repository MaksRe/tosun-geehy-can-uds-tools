import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Ёмкость обоих контуров: из чего она складывается и насколько устойчива.

  ЗАЧЕМ
  Отсчёт контура - это время между порогами компараторов, и само по себе это
  число ни о чём не говорит. В пикофарадах видно, похожа ли ёмкость на
  расчётную по геометрии датчика; плавание показывает, устойчиво ли измерение;
  а постоянная часть отвечает на вопрос, сколько в измеренном приходится не на
  датчик, а на образцовый конденсатор, кабель, разъём и плату.

  КАК ЧИТАЕТСЯ КАРТОЧКА
  Каждая строка названа и подписана, откуда взялась: «сейчас» - последнее
  показание, «эффективная» - среднее по окну захвата, «плавание» - разброс в
  этом окне, «постоянная часть» - расчёт по двум опорным точкам контура.

  Публичные свойства:
  - appController: контроллер приложения;
  - textMain/textSoft: палитра окна;
  - inputBg/inputBorder/inputFocus: цвета поля ввода.
*/
Rectangle {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"
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

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Text {
                    text: "Ёмкость контуров"
                    color: root.textMain
                    font.pixelSize: 15
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                Text {
                    Layout.fillWidth: true
                    text: "Пересчёт отсчётов в пикофарады и разделение измеренного на датчик и постоянную часть"
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }

            // Проницаемость нужна, чтобы отделить датчик от постоянной части: без
            // неё две опорные точки не разложить.
            Text {
                text: "Проницаемость топлива"
                color: root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
            }

            FancyTextField {
                id: epsField
                Layout.preferredWidth: 70
                Layout.preferredHeight: 30
                text: root.capacitance.fuelEpsText || "2,35"
                placeholderText: "2,35"
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
                onAccepted: if (root.appController) root.appController.setCapacitanceFuelPermittivity(text)
            }

            FancyButton {
                Layout.preferredWidth: 50
                Layout.preferredHeight: 30
                text: "OK"
                tone: "#0284c7"
                toneHover: "#0369a1"
                tonePressed: "#075985"
                toolTipText: "Для дизельного топлива около 2,35. Применяется к расчёту постоянной части"
                enabled: root.appController !== null
                onClicked: if (root.appController) root.appController.setCapacitanceFuelPermittivity(epsField.text)
            }
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
                        spacing: 5

                        Text {
                            text: circuitCard.modelData.title
                            color: root.textMain
                            font.pixelSize: 13
                            font.bold: true
                            font.family: "Bahnschrift"
                        }

                        // --- Строка «эффективная»: главное число карточки ---
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Text {
                                Layout.preferredWidth: 110
                                text: "Эффективная"
                                color: root.textSoft
                                font.pixelSize: 12
                                font.family: "Bahnschrift"
                            }

                            Text {
                                text: circuitCard.info.effectivePf || "—"
                                color: circuitCard.modelData.accent
                                font.pixelSize: 22
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            Text {
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignBottom
                                Layout.bottomMargin: 3
                                text: circuitCard.info.effectiveCounts || "—"
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            Layout.leftMargin: 118
                            visible: text !== ""
                            text: circuitCard.info.effectiveNote || ""
                            color: root.textSoft
                            font.pixelSize: 10
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }

                        // --- Остальные строки одинакового вида ---
                        Repeater {
                            model: [
                                {
                                    "label": "Сейчас",
                                    "value": (circuitCard.info.currentPf || "—") + "  ·  " + (circuitCard.info.currentCounts || "—"),
                                    "note": circuitCard.info.offsetText || "",
                                    "warn": false
                                },
                                {
                                    "label": "Плавание",
                                    "value": circuitCard.info.swingText || "—",
                                    "note": circuitCard.info.spreadText || "",
                                    "warn": circuitCard.info.warn === true
                                },
                                {
                                    "label": "Постоянная часть",
                                    "value": circuitCard.info.parasiticText || "—",
                                    "note": (circuitCard.info.strayText || "") + (circuitCard.info.strayText && circuitCard.info.sensitivityText ? ". " : "") + (circuitCard.info.sensitivityText || ""),
                                    "warn": false
                                }
                            ]

                            ColumnLayout {
                                id: rowItem
                                required property var modelData

                                Layout.fillWidth: true
                                spacing: 0

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8

                                    Text {
                                        Layout.preferredWidth: 110
                                        Layout.alignment: Qt.AlignTop
                                        text: rowItem.modelData.label
                                        color: root.textSoft
                                        font.pixelSize: 12
                                        font.family: "Bahnschrift"
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: rowItem.modelData.value
                                        color: rowItem.modelData.warn ? "#b45309" : root.textMain
                                        font.pixelSize: 12
                                        font.bold: rowItem.modelData.warn
                                        font.family: "Bahnschrift"
                                        wrapMode: Text.WordWrap
                                    }
                                }

                                Text {
                                    Layout.fillWidth: true
                                    Layout.leftMargin: 118
                                    visible: text !== ""
                                    text: rowItem.modelData.note
                                    color: root.textSoft
                                    font.pixelSize: 10
                                    font.family: "Bahnschrift"
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: text !== ""
                            text: circuitCard.info.sourceText || ""
                            color: root.textSoft
                            font.pixelSize: 10
                            font.italic: true
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
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
