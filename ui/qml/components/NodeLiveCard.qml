import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Раздел «Текущие данные узла».
  Назначение:
  - сразу после калибровки показывает, какой уровень выдаёт прибор, от него и в J1939;
  - показывает оба контура и обе температуры с признаками свежести;
  - у изменяющихся величин рисует график: миниатюру в карточке и развёрнутый по нажатию;
  - пишет журнал калибровки в CSV;
  - собирает отладочные данные: что сейчас в приборе записано и работает, как идёт
    измерение и в каком состоянии сам прибор.

  Опрос идёт, пока раздел виден и окно открыто, а также пока пишется журнал: иначе
  при переходе в другой раздел в журнале появлялась бы дыра.

  ГРАФИКИ
  Миниатюра показывает направление и дрожание, разглядывать по ней числа
  бессмысленно. Нажатие разворачивает тот же график во весь экран с сеткой,
  шкалами и экстремумами; он продолжает обновляться, пока открыт. Сброс графика
  очищает историю вместе с экстремумами, сброс экстремумов оставляет историю.

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
    readonly property var trends: root.appController ? root.appController.nodeTrends : ({})
    readonly property var logState: root.appController ? root.appController.calibrationLog : ({})

    // Журнал держит опрос включённым сам, поэтому переключатель его не касается.
    readonly property bool liveWanted: root.visible && root.Window.visibility !== Window.Hidden && liveSwitch.checked
    onLiveWantedChanged: if (root.appController) root.appController.setNodeLiveEnabled(root.liveWanted)
    Component.onCompleted: if (root.appController) root.appController.setNodeLiveEnabled(root.liveWanted)

    function trendOf(key) {
        var item = root.trends[key]
        return item ? item : ({})
    }

    function openTrend(key) {
        trendPopup.trendKey = key
        trendPopup.reload()
        trendPopup.open()
    }

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

        // --- Журнал калибровки и сброс графиков ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: logLayout.implicitHeight + 16
            radius: 10
            color: root.logState.recording ? "#fff7ed" : "#f8fbff"
            border.width: 1
            border.color: root.logState.recording ? "#f5c98b" : "#d6e2ef"

            RowLayout {
                id: logLayout
                anchors.fill: parent
                anchors.margins: 8
                spacing: 10

                FancyButton {
                    Layout.preferredWidth: 190
                    Layout.preferredHeight: 32
                    text: root.logState.recording ? "Остановить журнал" : "Писать журнал в CSV"
                    tone: root.logState.recording ? "#ef4444" : "#0284c7"
                    toneHover: root.logState.recording ? "#dc2626" : "#0369a1"
                    tonePressed: root.logState.recording ? "#b91c1c" : "#075985"
                    toolTipText: "Пишет в файл каждое изменение любого показания узла и все записи в прибор"
                    enabled: root.appController !== null
                    onClicked: if (root.appController) root.appController.setCalibrationLogRecording(!root.logState.recording)
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    Text {
                        Layout.fillWidth: true
                        text: (root.logState.statusText || "") + (root.logState.recording ? "  " + (root.logState.rowsText || "") : "")
                        color: root.logState.statusColor || root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: text !== ""
                        text: root.logState.pathText || ""
                        color: root.textSoft
                        font.pixelSize: 10
                        font.family: "Bahnschrift"
                        elide: Text.ElideMiddle
                    }
                }

                FancyButton {
                    Layout.preferredWidth: 160
                    Layout.preferredHeight: 32
                    text: "Очистить графики"
                    tone: "#64748b"
                    toneHover: "#475569"
                    tonePressed: "#334155"
                    toolTipText: "Стереть историю всех графиков вместе с экстремумами и начать заново"
                    enabled: root.appController !== null
                    onClicked: if (root.appController) root.appController.clearNodeTrend("")
                }

                FancyButton {
                    Layout.preferredWidth: 180
                    Layout.preferredHeight: 32
                    text: "Сбросить экстремумы"
                    tone: "#64748b"
                    toneHover: "#475569"
                    tonePressed: "#334155"
                    toolTipText: "Обнулить минимумы и максимумы, графики оставить как есть"
                    enabled: root.appController !== null
                    onClicked: if (root.appController) root.appController.clearNodeTrendExtremes("")
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
                        Layout.preferredHeight: 192
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
                                font.pixelSize: 30
                                font.bold: true
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

                            TrendMiniature {
                                Layout.fillWidth: true
                                trend: root.trendOf("level")
                                textSoft: root.textSoft
                                onOpenRequested: root.openTrend("level")
                            }

                            Item { Layout.fillHeight: true }
                        }
                    }

                    // Основной контур
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 192
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

                            TrendMiniature {
                                Layout.fillWidth: true
                                trend: root.trendOf("main_raw")
                                textSoft: root.textSoft
                                onOpenRequested: root.openTrend("main_raw")
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
                        Layout.preferredHeight: 192
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

                            TrendMiniature {
                                Layout.fillWidth: true
                                trend: root.trendOf("media")
                                textSoft: root.textSoft
                                onOpenRequested: root.openTrend("media")
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
                        Layout.preferredHeight: 192
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
                        Layout.preferredHeight: 192
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

    // --- Развёрнутый график ---
    Popup {
        id: trendPopup

        property string trendKey: ""
        readonly property var trend: root.trendOf(trendPopup.trendKey)
        property var fullPoints: []

        // История берётся целиком отдельным запросом: в карточку она не помещается,
        // а гонять её в каждое обновление показаний слишком дорого.
        function reload() {
            if (!root.appController) {
                trendPopup.fullPoints = []
                return
            }
            trendPopup.fullPoints = root.appController.nodeTrendSeries(trendPopup.trendKey)
        }

        parent: Overlay.overlay
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        width: Math.min(1000, root.Window.window ? root.Window.window.width - 80 : 900)
        height: Math.min(620, root.Window.window ? root.Window.window.height - 80 : 560)
        anchors.centerIn: Overlay.overlay
        padding: 0

        background: Rectangle {
            radius: 14
            color: "#ffffff"
            border.width: 1
            border.color: "#c6dcf5"
        }

        Timer {
            // Полная история обновляется реже показаний: рисовать её чаще незачем.
            running: trendPopup.opened
            interval: 700
            repeat: true
            onTriggered: trendPopup.reload()
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                ColumnLayout {
                    spacing: 0

                    Text {
                        text: trendPopup.trend.title || ""
                        color: root.textMain
                        font.pixelSize: 18
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Text {
                        text: (trendPopup.trend.countText || "") + "  " + (trendPopup.trend.spanText || "")
                        color: root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                    }
                }

                Text {
                    Layout.leftMargin: 10
                    text: "сейчас " + (trendPopup.trend.lastText || "—")
                    color: root.textMain
                    font.pixelSize: 16
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                Item { Layout.fillWidth: true }

                FancyButton {
                    Layout.preferredWidth: 110
                    Layout.preferredHeight: 32
                    text: "Закрыть"
                    tone: "#64748b"
                    toneHover: "#475569"
                    tonePressed: "#334155"
                    onClicked: trendPopup.close()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 16

                Text {
                    text: "минимум: " + (trendPopup.trend.minText || "—")
                    color: "#2563eb"
                    font.pixelSize: 13
                    font.family: "Bahnschrift"
                }

                Text {
                    text: "максимум: " + (trendPopup.trend.maxText || "—")
                    color: "#b45309"
                    font.pixelSize: 13
                    font.family: "Bahnschrift"
                }

                Item { Layout.fillWidth: true }

                FancyButton {
                    Layout.preferredWidth: 180
                    Layout.preferredHeight: 30
                    text: "Сбросить экстремумы"
                    tone: "#64748b"
                    toneHover: "#475569"
                    tonePressed: "#334155"
                    toolTipText: "Обнулить минимум и максимум, график оставить"
                    enabled: root.appController !== null
                    onClicked: {
                        if (root.appController)
                            root.appController.clearNodeTrendExtremes(trendPopup.trendKey)
                    }
                }

                FancyButton {
                    Layout.preferredWidth: 170
                    Layout.preferredHeight: 30
                    text: "Очистить график"
                    tone: "#0284c7"
                    toneHover: "#0369a1"
                    tonePressed: "#075985"
                    toolTipText: "Стереть историю вместе с экстремумами и начать заполнение заново"
                    enabled: root.appController !== null
                    onClicked: {
                        if (root.appController)
                            root.appController.clearNodeTrend(trendPopup.trendKey)
                        trendPopup.reload()
                    }
                }
            }

            TrendChart {
                Layout.fillWidth: true
                Layout.fillHeight: true
                points: trendPopup.fullPoints
                lineColor: trendPopup.trend.color || "#0284c7"
                unit: trendPopup.trend.unit || ""
                minValue: trendPopup.trend.minValue === undefined || trendPopup.trend.minValue === null
                          ? NaN : trendPopup.trend.minValue
                maxValue: trendPopup.trend.maxValue === undefined || trendPopup.trend.maxValue === null
                          ? NaN : trendPopup.trend.maxValue
                emptyText: "Данных ещё нет: опрос идёт, пока раздел открыт"
            }

            Text {
                Layout.fillWidth: true
                text: "По горизонтали секунды с начала записи графика. Пунктиром показаны минимум и максимум."
                color: root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
            }
        }
    }
}
