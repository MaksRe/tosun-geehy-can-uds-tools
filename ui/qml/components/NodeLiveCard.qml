import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Раздел «Текущие данные узла».
  Назначение:
  - сразу после калибровки показывает, какой уровень выдаёт прибор, от него и в J1939;
  - показывает оба контура и обе температуры с признаками свежести;
  - собирает отладочные данные: что сейчас в приборе записано и работает, как идёт
    измерение и в каком состоянии сам прибор.

  Опрос идёт, только пока раздел виден и окно открыто: без этого он нагружал бы
  шину и тогда, когда смотреть на данные некому.

  Публичные свойства:
  - appController: контроллер приложения;
  - cardColor/cardBorder/textMain/textSoft: общая палитра окна;
  - inputBg/inputBorder/inputFocus: цвета полей ввода.
*/
Card {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f6faff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"

    readonly property var live: root.appController ? root.appController.nodeLive : ({})
    readonly property var rows: root.live.rows || ({})

    readonly property bool liveWanted: root.visible && root.Window.visibility !== Window.Hidden && liveSwitch.checked
    onLiveWantedChanged: if (root.appController) root.appController.setNodeLiveEnabled(root.liveWanted)
    Component.onCompleted: if (root.appController) root.appController.setNodeLiveEnabled(root.liveWanted)

    // Группы отладочных строк. Список постоянный: меняются только значения, строки не пересоздаются.
    readonly property var groups: [
        {
            "title": "Калибровка в приборе",
            "items": [
                { "key": "empty", "label": "Отметка 0 %" },
                { "key": "full", "label": "Отметка 100 %" },
                { "key": "zero_trim", "label": "Подгонка нуля" },
                { "key": "tank_model", "label": "Модель уровня" },
                { "key": "media_enable", "label": "Поправка по виду топлива" },
                { "key": "rf", "label": "Коэффициент среды" },
                { "key": "media_state", "label": "Состояние поправки" },
                { "key": "rf_rejected", "label": "Отбраковано коэффициентов" }
            ]
        },
        {
            "title": "Температурная компенсация",
            "items": [
                { "key": "emul", "label": "Эмуляция температуры" },
                { "key": "profile_status", "label": "Температурный профиль" },
                { "key": "stage_mode", "label": "Работают ступени" },
                { "key": "board_stage", "label": "Период после ступени платы" }
            ]
        },
        {
            "title": "Качество измерения",
            "items": [
                { "key": "age", "label": "Возраст измерения" },
                { "key": "main_spread", "label": "Размах серии, основной" },
                { "key": "main_overrun", "label": "Перезахваты, основной" },
                { "key": "media_spread", "label": "Размах серии, вид топлива" },
                { "key": "media_overrun", "label": "Перезахваты, вид топлива" }
            ]
        },
        {
            "title": "Прибор",
            "items": [
                { "key": "program", "label": "Программа" },
                { "key": "session", "label": "Сессия" },
                { "key": "eeprom", "label": "Память" }
            ]
        }
    ]

    function toneColor(tone, fresh) {
        if (!fresh)
            return "#94a3b8"
        if (tone === "ok")
            return "#15803d"
        if (tone === "warn")
            return "#b45309"
        if (tone === "bad")
            return "#b91c1c"
        return root.textMain
    }

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        // --- Заголовок ---
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: "Текущие данные узла"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: "Что прибор показывает сейчас и что с ним происходит. Серое значение давно не обновлялось"
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }

            Text {
                text: root.live.stateText || ""
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
            }

            ColumnLayout {
                spacing: 2

                FancySwitch {
                    id: liveSwitch
                    Layout.alignment: Qt.AlignHCenter
                    checked: true
                }

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "опрос"
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                }
            }
        }

        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                width: scroll.availableWidth
                spacing: 10

                // --- Главное: уровень, контуры, температуры ---
                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 1050 ? 5 : (width >= 640 ? 3 : 2)
                    columnSpacing: 10
                    rowSpacing: 10

                    // Уровень топлива
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 120
                        radius: 12
                        color: "#effaf3"
                        border.width: 1
                        border.color: root.live.levelWarn ? "#f5c98b" : "#bfe8d2"

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 2

                            Text {
                                text: "Уровень топлива"
                                color: root.textSoft
                                font.pixelSize: 12
                                font.family: "Bahnschrift"
                            }

                            Text {
                                text: root.live.levelText || "—"
                                color: root.live.levelFresh ? (root.live.levelWarn ? "#b45309" : "#166534") : "#94a3b8"
                                font.pixelSize: 32
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            Text {
                                Layout.fillWidth: true
                                text: "по расчёту прибора"
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                            }

                            Text {
                                Layout.fillWidth: true
                                text: root.live.levelJ1939Text || ""
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    // Основной контур
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 120
                        radius: 12
                        color: "#ffffff"
                        border.width: 1
                        border.color: "#d6e2ef"

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 2

                            Text {
                                text: "Основной контур, период"
                                color: root.textSoft
                                font.pixelSize: 12
                                font.family: "Bahnschrift"
                            }

                            Text {
                                text: root.live.mainRaw || "—"
                                color: root.live.mainFresh ? root.textMain : "#94a3b8"
                                font.pixelSize: 26
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            Text {
                                text: "итоговый " + (root.live.mainComp || "—")
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                            }

                            LiveFreshnessLine {
                                Layout.fillWidth: true
                                Layout.topMargin: 2
                                stacked: true
                                info: root.live.mainFreshness || ({})
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    // Контур вида топлива
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 120
                        radius: 12
                        color: "#ffffff"
                        border.width: 1
                        border.color: "#d6e2ef"

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 2

                            Text {
                                text: "Контур вида топлива"
                                color: root.textSoft
                                font.pixelSize: 12
                                font.family: "Bahnschrift"
                            }

                            Text {
                                text: root.live.media || "—"
                                color: root.live.mediaFresh ? root.textMain : "#94a3b8"
                                font.pixelSize: 26
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            Text {
                                text: "после поправок платы и трубки"
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                            }

                            LiveFreshnessLine {
                                Layout.fillWidth: true
                                Layout.topMargin: 2
                                stacked: true
                                info: root.live.mediaFreshness || ({})
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    // Температура топлива
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 120
                        radius: 12
                        color: "#ffffff"
                        border.width: 1
                        border.color: root.live.emulationOn ? "#f5c98b" : "#d6e2ef"

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 2

                            Text {
                                text: "Температура топлива"
                                color: root.textSoft
                                font.pixelSize: 12
                                font.family: "Bahnschrift"
                            }

                            Text {
                                text: root.live.fuelTemp || "—"
                                color: root.live.fuelTempFresh ? root.textMain : "#94a3b8"
                                font.pixelSize: 26
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            Text {
                                Layout.fillWidth: true
                                text: root.live.tempSource || ""
                                color: root.live.emulationOn ? "#b45309" : root.textSoft
                                font.pixelSize: 11
                                font.bold: root.live.emulationOn === true
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    // Температура платы
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 120
                        radius: 12
                        color: "#ffffff"
                        border.width: 1
                        border.color: root.live.emulationOn ? "#f5c98b" : "#d6e2ef"

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 2

                            Text {
                                text: "Температура платы"
                                color: root.textSoft
                                font.pixelSize: 12
                                font.family: "Bahnschrift"
                            }

                            Text {
                                text: root.live.boardTemp || "—"
                                color: root.live.boardTempFresh ? root.textMain : "#94a3b8"
                                font.pixelSize: 26
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            Text {
                                Layout.fillWidth: true
                                text: root.live.tempSource || ""
                                color: root.live.emulationOn ? "#b45309" : root.textSoft
                                font.pixelSize: 11
                                font.bold: root.live.emulationOn === true
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }
                }

                // --- Отладочные данные по группам ---
                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 900 ? 2 : 1
                    columnSpacing: 10
                    rowSpacing: 10

                    Repeater {
                        model: root.groups

                        Rectangle {
                            id: groupCard
                            required property var modelData

                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.alignment: Qt.AlignTop
                            implicitHeight: groupLayout.implicitHeight + 20
                            radius: 12
                            color: "#fbfdff"
                            border.width: 1
                            border.color: "#e2ebf5"

                            ColumnLayout {
                                id: groupLayout
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 10
                                spacing: 5

                                Text {
                                    text: groupCard.modelData.title
                                    color: root.textMain
                                    font.pixelSize: 14
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }

                                Repeater {
                                    model: groupCard.modelData.items

                                    RowLayout {
                                        id: rowItem
                                        required property var modelData
                                        readonly property var row: root.rows[rowItem.modelData.key] || ({})

                                        Layout.fillWidth: true
                                        spacing: 8

                                        Text {
                                            Layout.preferredWidth: 190
                                            Layout.alignment: Qt.AlignTop
                                            text: rowItem.modelData.label
                                            color: root.textSoft
                                            font.pixelSize: 12
                                            font.family: "Bahnschrift"
                                            elide: Text.ElideRight
                                        }

                                        Text {
                                            Layout.fillWidth: true
                                            text: rowItem.row.value || "—"
                                            color: root.toneColor(rowItem.row.tone, rowItem.row.fresh === true)
                                            font.pixelSize: 12
                                            font.bold: rowItem.row.tone === "bad" || rowItem.row.tone === "warn"
                                            font.family: "Bahnschrift"
                                            wrapMode: Text.WordWrap
                                            maximumLineCount: 3
                                            elide: Text.ElideRight
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
