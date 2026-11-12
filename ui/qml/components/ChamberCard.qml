import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Раздел прогона изделия в климатической камере.
  Назначение:
  - всё время показывает период обоих контуров и обе температуры: текущее и среднее;
  - по кнопке сразу кладёт средние в журнал прогона;
  - после каждой точки сам сохраняет журнал и пересчитывает обе ступени в таблицу профиля;
  - показывает, чего ещё не хватает по каждому узлу температурной сетки;
  - пишет профиль в прибор, сверяет и сохраняет в файл: по кнопке или сам при полных данных;
  - в тестовом режиме задаёт прибору температуру эмуляцией и проходит все узлы на столе.

  Оператору на виду только то, что нужно на каждой точке: показания, запись
  точки, ход работы, полнота узлов, запись профиля и журнал. Режим расчёта,
  файлы и тестовый режим убраны в спойлеры внизу; включённый нестандартный
  режим всё равно виден значком в шапке.

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
    // Вкладка раздела: показания и запись точки видны всегда, остальное - на своей вкладке.
    property string page: "points"
    readonly property var pages: [
        { "key": "points", "title": "Точки", "tip": "Запись точки, полнота по узлам, замечания расчёта и журнал точек" },
        { "key": "results", "title": "Итоги", "tip": "Итоги прогона: таблицы по узлам и этапам, ёмкость, уход от +25 °C, разброс" },
        { "key": "profile", "title": "Расчёт и профиль", "tip": "Режим прогона, расчёт таблиц и запись профиля в прибор" },
        { "key": "journals", "title": "Журналы", "tip": "Журналы на диске: открыть, сохранить, журналы первого этапа всем платам" },
        { "key": "boards", "title": "Платы", "tip": "Несколько плат в камере: список плат, адреса, у каждой свой журнал" },
        { "key": "test", "title": "Тестовый режим", "tip": "Отладка прогона на столе без камеры" }
    ]

    signal saveLogRequested()
    signal loadLogRequested()
    signal exportTablesRequested()

    readonly property bool busy: root.appController ? root.appController.chamberBusy : false
    readonly property bool boardOnly: root.appController ? root.appController.chamberBoardOnly : false
    readonly property bool waiting: root.appController ? root.appController.chamberWaiting : false
    readonly property var live: root.appController ? root.appController.chamberLive : ({})
    readonly property var chain: root.appController ? root.appController.chamberChain : ({})
    readonly property var test: root.appController ? root.appController.chamberTest : ({})
    // Температуру можно менять, когда не идёт ни замер, ни смена температуры, ни обход, ни запись профиля.
    readonly property bool testIdle: root.appController !== null && root.test.mode === true && !root.busy
                                     && !root.waiting && !root.test.busy && !root.test.walking && !root.chain.busy

    // Прибор опрашивается, только пока раздел открыт и окно не свёрнуто.
    readonly property bool liveWanted: root.visible && root.Window.visibility !== Window.Hidden
    onLiveWantedChanged: if (root.appController) root.appController.setChamberLiveEnabled(root.liveWanted)
    Component.onCompleted: if (root.appController) root.appController.setChamberLiveEnabled(root.liveWanted)

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    // Спойлер для редко нужного: компактный заголовок, содержимое с отступом.
    component Spoiler: SpoilerSection {
        headerHeight: 36
        contentPadding: 10
        cardColor: "#f8fafc"
        cardBorder: "#e2e8f0"
        textMain: root.textMain
        textSoft: root.textSoft
        accentColor: "#0f766e"
    }

    component Caption: Text {
        color: root.textSoft
        font.pixelSize: 12
        font.family: "Bahnschrift"
        Layout.alignment: Qt.AlignVCenter
    }

    component SmallButton: FancyButton {
        Layout.preferredHeight: 28
        fontPixelSize: 12
        tone: "#64748b"
        toneHover: "#475569"
        tonePressed: "#334155"
    }

    // Значок включённого режима в шапке: виден, даже когда его настройки свёрнуты.
    component Badge: Rectangle {
        property string text: ""
        property color tint: "#0284c7"
        Layout.alignment: Qt.AlignVCenter
        Layout.preferredHeight: 22
        Layout.preferredWidth: badgeText.implicitWidth + 16
        radius: 11
        color: Qt.lighter(tint, 1.9)
        border.width: 1
        border.color: tint
        Text {
            id: badgeText
            anchors.centerIn: parent
            text: parent.text
            color: parent.tint
            font.pixelSize: 11
            font.bold: true
            font.family: "Bahnschrift"
        }
    }

    ScrollView {
        id: pageScroll
        anchors.fill: parent
        anchors.margins: 14
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        ColumnLayout {
            width: pageScroll.availableWidth
            // Журнал забирает всё свободное место, а если его нет, прокручивается вся карточка.
            height: Math.max(pageScroll.availableHeight, implicitHeight)
            spacing: 10

            // --- Заголовок и включённые режимы ---
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "Прогон в климатической камере"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                Badge { visible: root.boardOnly; text: "Только плата"; tint: "#0284c7" }
                Badge { visible: root.test.mode === true; text: "Тестовый режим"; tint: "#ea580c" }
                Badge {
                    visible: !root.boardOnly && root.appController !== null && root.appController.chamberExtendLiquid
                    text: "Достройка «в жидкости»"
                    tint: "#a16207"
                }

                Item { Layout.fillWidth: true }
            }

            // --- Живые показания: текущее и среднее рядом ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: liveLayout.implicitHeight + 18
                radius: 12
                color: "#f2f7ff"
                border.width: 1
                border.color: "#c6dcf5"

                ColumnLayout {
                    id: liveLayout
                    anchors.fill: parent
                    anchors.margins: 9
                    spacing: 4

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 16

                        Repeater {
                            model: [
                                { "title": "Основной контур", "key": "main" },
                                { "title": "Вид топлива", "key": "media" }
                            ]

                            ColumnLayout {
                                id: channelColumn
                                required property var modelData
                                readonly property var info: root.live[modelData.key] || ({})

                                Layout.fillWidth: true
                                Layout.preferredWidth: 1
                                spacing: 0

                                Text {
                                    text: channelColumn.modelData.title
                                    color: root.textSoft
                                    font.pixelSize: 12
                                    font.family: "Bahnschrift"
                                }

                                RowLayout {
                                    spacing: 18

                                    ColumnLayout {
                                        spacing: 0
                                        Text { text: "Текущий"; color: root.textSoft; font.pixelSize: 11; font.family: "Bahnschrift" }
                                        Text {
                                            text: channelColumn.info.now || "—"
                                            color: root.textMain
                                            font.pixelSize: 24
                                            font.bold: true
                                            font.family: "Bahnschrift"
                                        }
                                    }

                                    ColumnLayout {
                                        spacing: 0
                                        Text { text: "Среднее, пойдёт в точку"; color: root.textSoft; font.pixelSize: 11; font.family: "Bahnschrift" }
                                        Text {
                                            text: channelColumn.info.avg || "—"
                                            color: "#0f766e"
                                            font.pixelSize: 24
                                            font.bold: true
                                            font.family: "Bahnschrift"
                                        }
                                    }
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: channelColumn.info.info || ""
                                    color: channelColumn.info.ok ? "#15803d" : "#b45309"
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        // Температуры: по плате выбирается узел сетки, по топливу строки трубки.
                        GridLayout {
                            Layout.alignment: Qt.AlignTop
                            columns: 3
                            columnSpacing: 12
                            rowSpacing: 2

                            Text { text: "Температура"; color: root.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                            Text { text: "Текущая"; color: root.textSoft; font.pixelSize: 11; font.family: "Bahnschrift" }
                            Text { text: "Средняя"; color: root.textSoft; font.pixelSize: 11; font.family: "Bahnschrift" }

                            Text { text: "Плата"; color: root.textMain; font.pixelSize: 13; font.family: "Bahnschrift" }
                            Text { text: (root.live.boardTemp || {}).now || "—"; color: root.textMain; font.pixelSize: 15; font.bold: true; font.family: "Bahnschrift" }
                            Text { text: (root.live.boardTemp || {}).avg || "—"; color: "#0f766e"; font.pixelSize: 15; font.bold: true; font.family: "Bahnschrift" }

                            Text { text: "Топливо"; color: root.textMain; font.pixelSize: 13; font.family: "Bahnschrift" }
                            Text { text: (root.live.fuelTemp || {}).now || "—"; color: root.textMain; font.pixelSize: 15; font.bold: true; font.family: "Bahnschrift" }
                            Text { text: (root.live.fuelTemp || {}).avg || "—"; color: "#0f766e"; font.pixelSize: 15; font.bold: true; font.family: "Bahnschrift" }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Rectangle {
                            Layout.alignment: Qt.AlignVCenter
                            Layout.preferredWidth: 10
                            Layout.preferredHeight: 10
                            radius: 5
                            color: root.live.freshOk ? "#16a34a" : "#f59e0b"
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.live.freshText || ""
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                    }
                }
            }

            // --- Тестовый режим включён: напоминание, что точки пробные ---
            Rectangle {
                Layout.fillWidth: true
                visible: root.test.mode === true
                Layout.preferredHeight: testBannerLayout.implicitHeight + 12
                radius: 10
                color: "#fff7ed"
                border.width: 1
                border.color: "#fdba74"

                RowLayout {
                    id: testBannerLayout
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 8

                    Text {
                        Layout.fillWidth: true
                        text: "Тестовый режим: температуру задаёт эмуляция (" + (root.test.emulationText || "настоящая")
                              + "), точки помечаются как пробные. " + (root.test.status || "")
                        color: "#9a3412"
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }

                    SmallButton {
                        Layout.preferredWidth: 110
                        text: "Выключить"
                        tone: "#ea580c"; toneHover: "#c2410c"; tonePressed: "#9a3412"
                        enabled: root.appController !== null && !root.busy && !root.test.walking
                        onClicked: if (root.appController) root.appController.setChamberTestMode(false)
                    }
                }
            }

            // --- Вкладки раздела ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                radius: 11
                color: "#eef3f9"
                border.width: 1
                border.color: "#d6e2ef"

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 4
                    spacing: 4

                    Repeater {
                        model: root.pages

                        Rectangle {
                            id: pageTab
                            required property var modelData
                            readonly property bool current: root.page === pageTab.modelData.key
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 8
                            color: pageTab.current ? "#0f766e" : (pageTabArea.containsMouse ? "#dfe8f1" : "transparent")

                            Text {
                                anchors.centerIn: parent
                                text: pageTab.modelData.title
                                      + (pageTab.modelData.key === "points" && root.appController
                                         ? "  " + root.appController.chamberPointCount : "")
                                color: pageTab.current ? "#ffffff" : root.textMain
                                font.pixelSize: 13
                                font.bold: pageTab.current
                                font.family: "Bahnschrift"
                            }

                            MouseArea {
                                id: pageTabArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.page = pageTab.modelData.key
                            }

                            ToolTip {
                                visible: pageTabArea.containsMouse
                                delay: 500
                                text: pageTab.modelData.tip
                            }
                        }
                    }
                }
            }

            // --- Снятие точки ---
            Rectangle {
                Layout.fillWidth: true
                visible: root.page === "points"
                Layout.preferredHeight: captureLayout.implicitHeight + 20
                radius: 12
                color: "#f2f7ff"
                border.width: 1
                border.color: "#c6dcf5"

                ColumnLayout {
                    id: captureLayout
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Caption { text: "Что подключено сейчас" }

                        FancyTextField {
                            id: labelField
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            text: root.appController ? root.appController.chamberLabel : ""
                            placeholderText: "например: 0/0, 68/22, 150/47 (основной/вид топлива), воздух, жидкость"
                            textColor: root.textMain
                            bgColor: root.inputBg
                            borderColor: root.inputBorder
                            focusBorderColor: root.inputFocus
                            onAccepted: if (root.appController) root.appController.setChamberLabel(text)
                            onEditingFinished: if (root.appController) root.appController.setChamberLabel(text)
                        }

                        Repeater {
                            model: ["воздух", "жидкость"]

                            SmallButton {
                                required property string modelData
                                Layout.preferredWidth: 90
                                Layout.preferredHeight: 34
                                text: modelData
                                toolTipText: "«воздух» и «жидкость» идут в расчёт трубки"
                                enabled: root.appController !== null && !root.busy
                                onClicked: {
                                    labelField.text = modelData
                                    if (root.appController) root.appController.setChamberLabel(modelData)
                                }
                            }
                        }

                        FancyButton {
                            Layout.preferredWidth: 164
                            Layout.preferredHeight: 34
                            text: root.busy ? "Идёт замер..." : (root.waiting ? "Жду среднее..." : "Записать точку")
                            tone: "#16a34a"
                            toneHover: "#15803d"
                            tonePressed: "#166534"
                            toolTipText: "Сразу кладёт в журнал средние из полей выше. Если среднего ещё нет, запишет сама, как только оно наберётся"
                            enabled: root.appController !== null && !root.busy && !root.waiting
                            onClicked: {
                                if (root.appController) {
                                    root.appController.setChamberLabel(labelField.text)
                                    root.appController.captureChamberPoint()
                                }
                            }
                        }
                    }

                    // Ход работы и отмена ошибочной точки - в одной строке под записью.
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        // Последнее сообщение журнала: значок и заголовок, разбор - по нажатию.
                        NoticeLine {
                            appController: root.appController
                            text: root.appController ? root.appController.chamberStatusText : "Контроллер недоступен"
                            tone: root.appController ? root.appController.chamberStatusColor : ""
                            kind: "Журнал"
                            fontSize: 13
                        }

                        SmallButton {
                            Layout.preferredWidth: 150
                            text: "Отменить последнюю"
                            tone: "#b45309"; toneHover: "#92400e"; tonePressed: "#78350f"
                            enabled: root.appController !== null && !root.busy && root.appController.chamberPointCount > 0
                            onClicked: if (root.appController) root.appController.removeLastChamberPoint()
                        }
                    }
                }
            }

            // --- Полнота прогона по узлам ---
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.page === "points"
                spacing: 6

                Text {
                    text: root.boardOnly
                          ? "Чего ещё не хватает  ·  в каждом узле точка «0/0»"
                          : "Чего ещё не хватает  ·  эталоны основной · вид топлива, нужно по 2"
                    color: root.textMain
                    font.pixelSize: 13
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Repeater {
                        model: root.appController ? root.appController.chamberCoverageRows : []

                        Rectangle {
                            required property var modelData
                            readonly property bool allOk: modelData.capsOk && modelData.tubeOk

                            Layout.fillWidth: true
                            Layout.preferredHeight: 56
                            radius: 9
                            color: allOk ? "#ecfdf5" : "#fffbeb"
                            border.width: 1
                            border.color: allOk ? "#86efac" : "#fcd34d"

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 5
                                spacing: 1

                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.node
                                    color: root.textMain
                                    font.pixelSize: 12
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                    horizontalAlignment: Text.AlignHCenter
                                    elide: Text.ElideRight
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.caps
                                    color: modelData.capsOk ? "#15803d" : "#b45309"
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                    horizontalAlignment: Text.AlignHCenter
                                    elide: Text.ElideRight
                                }

                                Text {
                                    Layout.fillWidth: true
                                    visible: !root.boardOnly
                                    text: "трубка: " + modelData.tube
                                    color: modelData.tubeOk ? "#15803d" : "#b45309"
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                    horizontalAlignment: Text.AlignHCenter
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }

            // --- Запись профиля в прибор: доступ, запись, сверка, файл ---
            Rectangle {
                Layout.fillWidth: true
                visible: root.page === "profile"
                Layout.preferredHeight: chainLayout.implicitHeight + 18
                radius: 12
                color: "#f0fdf4"
                border.width: 1
                border.color: "#bbf7d0"

                RowLayout {
                    id: chainLayout
                    anchors.fill: parent
                    anchors.margins: 9
                    spacing: 6

                    FancyButton {
                        Layout.preferredWidth: 250
                        Layout.preferredHeight: 32
                        fontPixelSize: 12
                        text: root.chain.busy ? "Идёт запись профиля..." : "Записать в прибор, сверить, сохранить"
                        tone: "#16a34a"
                        toneHover: "#15803d"
                        tonePressed: "#166534"
                        toolTipText: "Открывает доступ на запись, пишет таблицы, читает их обратно и сохраняет профиль в файл рядом с журналом"
                        enabled: root.appController !== null && !root.busy && !root.chain.busy
                                && root.appController.chamberPointCount > 0
                        onClicked: if (root.appController) root.appController.writeChamberProfile()
                    }

                    Repeater {
                        model: root.chain.steps || []

                        Rectangle {
                            id: stepChip
                            required property var modelData
                            required property int index
                            readonly property string state_: modelData.state

                            Layout.preferredHeight: 24
                            Layout.preferredWidth: stepText.implicitWidth + 18
                            radius: 12
                            color: state_ === "ok" ? "#dcfce7"
                                 : state_ === "fail" ? "#fee2e2"
                                 : state_ === "run" ? "#dbeafe" : "#f1f5f9"
                            border.width: 1
                            border.color: state_ === "ok" ? "#86efac"
                                        : state_ === "fail" ? "#fca5a5"
                                        : state_ === "run" ? "#93c5fd" : "#e2e8f0"

                            Text {
                                id: stepText
                                anchors.centerIn: parent
                                text: (stepChip.index + 1) + ". " + stepChip.modelData.title
                                      + (stepChip.state_ === "ok" ? "  ✓"
                                         : stepChip.state_ === "fail" ? "  ✗"
                                         : stepChip.state_ === "run" ? "  …" : "")
                                color: stepChip.state_ === "ok" ? "#15803d"
                                     : stepChip.state_ === "fail" ? "#b91c1c"
                                     : stepChip.state_ === "run" ? "#1d4ed8" : root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                            }
                        }
                    }

                    NoticeLine {
                        appController: root.appController
                        text: (root.chain.status || "") + (root.chain.autoWrite === true ? ". Запишется сам при полных данных." : "")
                        tone: root.chain.color || ""
                        kind: "Профиль"
                    }
                }
            }

            // --- Замечания расчёта: одной строкой со счётом, каждое с пояснением - по нажатию ---
            NoticeLine {
                visible: root.page === "points" && hasNotice
                appController: root.appController
                items: root.appController ? root.appController.chamberReportLines : []
                remarks: true
                tone: "warn"
                kind: "Таблицы"
                title: "Чего не хватило расчёту: замечаний {count}"
                fontSize: 13
            }

            // --- Режим прогона и расчёт: задаётся один раз на прогон ---
            Spoiler {
                visible: root.page === "profile"
                expanded: true
                title: "Режим прогона и расчёт таблиц"
                hintText: (root.boardOnly ? "только плата (" + (root.appController ? root.appController.chamberSingleModel : "") + ")"
                                          : "эталоны и трубка")
                          + "  ·  окно среднего " + (root.live.windowText || "10") + " с"
                          + ((root.chain.autoWrite === true) ? "  ·  автозапись профиля" : "")

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        FancySwitch {
                            checked: root.boardOnly
                            enabled: root.appController !== null && !root.busy
                            onToggled: if (root.appController) root.appController.setChamberBoardOnly(checked)
                        }

                        Text {
                            text: "Только плата, своя ёмкость: без эталонов и без трубки"
                            color: root.textMain
                            font.pixelSize: 13
                            font.family: "Bahnschrift"
                        }

                        Caption { visible: root.boardOnly; text: "  уход считать как" }

                        Repeater {
                            model: root.boardOnly ? [
                                { "key": "растяжение", "tip": "Ёмкости на плате C0G: уходят резисторы и пороги генератора, уход пропорционален показанию" },
                                { "key": "сдвиг", "tip": "Ёмкости на плате X7R: плавает сама ёмкость, уход постоянен в отсчётах" }
                            ] : []

                            SmallButton {
                                required property var modelData
                                Layout.preferredWidth: 110
                                text: modelData.key
                                toolTipText: modelData.tip
                                tone: root.appController && root.appController.chamberSingleModel === modelData.key ? "#0284c7" : "#94a3b8"
                                toneHover: "#0369a1"
                                tonePressed: "#075985"
                                onClicked: if (root.appController) root.appController.setChamberSingleModel(modelData.key)
                            }
                        }

                        InfoMark {
                            tip: root.boardOnly
                                 ? "В каждом узле снимается одна точка «0/0»: к входам ничего не подключено. Поправка возвращает "
                                   + "показание при своей ёмкости платы к показанию при +25 °C.<br>При подключённой трубке это "
                                   + "допущение: сдвиг и растяжение по одной ёмкости не разделить. Ряды трубки в профиле не меняются."
                                 : ""
                        }

                        Item { Layout.fillWidth: true }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: !root.boardOnly
                        spacing: 8

                        FancySwitch {
                            id: extendSwitch
                            checked: root.appController ? root.appController.chamberExtendLiquid : false
                            enabled: root.appController !== null
                            onToggled: if (root.appController) root.appController.setChamberExtendLiquid(checked)
                        }

                        Text {
                            text: "Достроить строки «в жидкости» по постоянному размаху"
                            color: root.textMain
                            font.pixelSize: 13
                            font.family: "Bahnschrift"
                        }

                        InfoMark {
                            tip: "Нужно, когда в камеру нельзя ставить топливо. Погружение снимается один раз при комнатной "
                                 + "температуре, в остальных узлах размах считается таким же.<br>Пустое поле размаха - "
                                 + "«взять размах из снятой пары состояний»."
                        }

                        Caption { text: "  основной"; visible: extendSwitch.checked }

                        FancyTextField {
                            id: spanMainField
                            Layout.preferredWidth: 100
                            Layout.preferredHeight: 30
                            visible: extendSwitch.checked
                            text: root.appController ? root.appController.chamberSpanMainText : ""
                            placeholderText: "из замера"
                            textColor: root.textMain
                            bgColor: root.inputBg
                            borderColor: root.inputBorder
                            focusBorderColor: root.inputFocus
                            onAccepted: if (root.appController) root.appController.setChamberSpanMain(text)
                            onEditingFinished: if (root.appController) root.appController.setChamberSpanMain(text)
                        }

                        Caption { text: "вид топлива"; visible: extendSwitch.checked }

                        FancyTextField {
                            id: spanMediaField
                            Layout.preferredWidth: 100
                            Layout.preferredHeight: 30
                            visible: extendSwitch.checked
                            text: root.appController ? root.appController.chamberSpanMediaText : ""
                            placeholderText: "из замера"
                            textColor: root.textMain
                            bgColor: root.inputBg
                            borderColor: root.inputBorder
                            focusBorderColor: root.inputFocus
                            onAccepted: if (root.appController) root.appController.setChamberSpanMedia(text)
                            onEditingFinished: if (root.appController) root.appController.setChamberSpanMedia(text)
                        }

                        Item { Layout.fillWidth: true }
                    }


                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        FancySwitch {
                            checked: root.chain.autoWrite === true
                            enabled: root.appController !== null
                            onToggled: if (root.appController) root.appController.setChamberAutoWrite(checked)
                        }

                        Text {
                            text: "Сам писать профиль в прибор, когда данных хватило во всех узлах"
                            color: root.textMain
                            font.pixelSize: 13
                            font.family: "Bahnschrift"
                        }

                        Item { Layout.fillWidth: true }

                        Caption { text: "Окно среднего, с" }

                        FancyTextField {
                            id: windowField
                            Layout.preferredWidth: 72
                            Layout.preferredHeight: 30
                            // Без привязки: показ обновляется много раз в секунду и затирал бы ввод.
                            Component.onCompleted: text = root.live.windowText || "10"
                            horizontalAlignment: TextInput.AlignHCenter
                            textColor: root.textMain
                            bgColor: root.inputBg
                            borderColor: root.inputBorder
                            focusBorderColor: root.inputFocus
                            onAccepted: if (root.appController) root.appController.setChamberWindow(text)
                            onEditingFinished: if (root.appController) root.appController.setChamberWindow(text)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        SmallButton {
                            Layout.preferredWidth: 180
                            text: "Пересчитать таблицы"
                            tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                            toolTipText: "Таблицы и так пересчитываются после каждой точки. Кнопка нужна, чтобы увидеть подробности расчёта"
                            enabled: root.appController !== null && !root.busy
                                    && root.appController.chamberPointCount > 0
                            onClicked: if (root.appController) root.appController.computeChamberTables()
                        }

                        NoticeLine {
                            appController: root.appController
                            text: root.appController ? root.appController.chamberTablesText : ""
                            tone: root.appController ? root.appController.chamberTablesColor : ""
                            kind: "Таблицы"
                        }
                    }
                }
            }

            // --- Несколько плат в камере: у каждой свой журнал, таблицы и профиль ---
            Spoiler {
                id: boardsSpoiler
                visible: root.page === "boards"
                readonly property var mb: root.appController ? root.appController.chamberBoards : ({})
                title: "Несколько плат в камере"
                hintText: (boardsSpoiler.mb.enabled ? "включено: плат " + (boardsSpoiler.mb.boards || []).length
                           : "выключено: одна плата") + (boardsSpoiler.mb.status ? "  ·  " + boardsSpoiler.mb.status : "")
                expanded: true

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    FancySwitch {
                        checked: boardsSpoiler.mb.configured === true
                        enabled: root.appController !== null && !root.busy
                        onToggled: if (root.appController) root.appController.setChamberMultiEnabled(checked)
                    }
                    Text {
                        text: "Несколько плат сразу"
                        color: root.textMain
                        font.pixelSize: 13
                        font.family: "Bahnschrift"
                    }
                    InfoMark {
                        tip: "<b>Несколько плат в камере</b><br>У каждой платы свой адрес на шине CAN (SA), свой журнал "
                             + "точек (файл с её именем), свои таблицы и свой профиль. Камера одна: доводка идёт по средней "
                             + "температуре плат, точка шага снимается у каждой платы.<br><br>"
                             + "<b>Адреса.</b> Платы с одинаковым адресом на одной шине мешают друг другу. Перед прогоном "
                             + "подключите их по одной и задайте разные адреса (раздел «Протокол», смена SA).<br><br>"
                             + "<b>Свободная шина.</b> На время прогона обычная рассылка J1939 у плат выключается одной "
                             + "командой всем (CommunicationControl 0x28) и после прогона включается обратно.<br><br>"
                             + "<b>Профиль</b> в конце пишется в каждую плату по очереди."
                    }
                    Item { Layout.preferredWidth: 16 }
                    FancySwitch {
                        checked: boardsSpoiler.mb.quietBus === true
                        onToggled: if (root.appController) root.appController.setChamberQuietBus(checked)
                    }
                    Caption { text: "выключать рассылку J1939 плат на время прогона" }
                    Item { Layout.fillWidth: true }
                }

                // Платы: адрес, имя, температура, контуры, точки, профиль.
                Repeater {
                    model: boardsSpoiler.mb.boards || []

                    RowLayout {
                        id: boardRow
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 8

                        Rectangle {
                            Layout.preferredWidth: 10
                            Layout.preferredHeight: 10
                            radius: 5
                            color: boardRow.modelData.fresh ? "#16a34a" : "#f59e0b"
                        }
                        Text {
                            Layout.preferredWidth: 150
                            text: (boardRow.modelData.active ? "● " : "") + boardRow.modelData.name + "  " + boardRow.modelData.saText
                            color: boardRow.modelData.active ? "#0f6ab4" : root.textMain
                            font.pixelSize: 13
                            font.bold: boardRow.modelData.active === true
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                        Caption { text: "плата " + boardRow.modelData.boardTemp }
                        Caption { text: "осн " + boardRow.modelData.main + " / вид " + boardRow.modelData.media }
                        Caption { text: "точек " + boardRow.modelData.points }
                        Caption {
                            Layout.fillWidth: true
                            text: boardRow.modelData.profile || boardRow.modelData.tables
                            elide: Text.ElideRight
                        }
                        SmallButton {
                            Layout.preferredWidth: 100
                            text: boardRow.modelData.active ? "Показана" : "Показать"
                            toolTipText: "Журнал, таблицы и профиль этой платы - в окне"
                            enabled: boardRow.modelData.active !== true && !root.busy
                            onClicked: if (root.appController) root.appController.selectChamberBoard(boardRow.modelData.sa)
                        }
                        SmallButton {
                            Layout.preferredWidth: 34
                            text: "✕"
                            tone: "#94a3b8"; toneHover: "#dc2626"; tonePressed: "#b91c1c"
                            toolTipText: "Убрать плату из списка (её журнал на диске останется)"
                            onClicked: if (root.appController) root.appController.removeChamberBoard(boardRow.modelData.sa)
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Caption { text: "Добавить плату: адрес" }
                    FancyTextField {
                        id: boardSaField
                        Layout.preferredWidth: 90
                        Layout.preferredHeight: 30
                        placeholderText: "0x80"
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                    }
                    Caption { text: "имя" }
                    FancyTextField {
                        id: boardNameField
                        Layout.preferredWidth: 140
                        Layout.preferredHeight: 30
                        placeholderText: "П1"
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                    }
                    SmallButton {
                        Layout.preferredWidth: 110
                        text: "Добавить"
                        enabled: boardSaField.text.length > 0
                        onClicked: {
                            if (root.appController) root.appController.addChamberBoard(boardSaField.text, boardNameField.text)
                            boardSaField.text = ""
                            boardNameField.text = ""
                        }
                    }
                    Caption {
                        visible: (boardsSpoiler.mb.candidates || []).length > 0
                        text: "  на шине: "
                    }
                    Repeater {
                        model: boardsSpoiler.mb.candidates || []
                        SmallButton {
                            required property string modelData
                            Layout.preferredWidth: 70
                            text: modelData
                            toolTipText: "Добавить плату с этим адресом"
                            onClicked: if (root.appController) root.appController.addChamberBoard(modelData, "")
                        }
                    }
                    Item { Layout.fillWidth: true }
                }
            }

            // --- Итоги прогона: таблицы по узлам и этапам, по ним видно, удался ли прогон ---
            Spoiler {
                id: resultsSpoiler
                visible: root.page === "results"
                expanded: true
                title: "Итоги прогона"
                hintText: (((root.appController ? root.appController.chamberResults : ({})).boards || []).length > 1
                           ? "сводка по платам, " : "")
                          + "узлы по этапам, ёмкость, уход от +25 °C, разброс"

                ResultsPanel {
                    Layout.fillWidth: true
                    appController: root.appController
                }
            }

            // --- Журналы и таблицы: журнал и так сохраняется сам после каждой точки ---
            Spoiler {
                id: journalsSpoiler
                visible: root.page === "journals"
                expanded: true
                title: "Журналы и таблицы"
                // Несколько плат: у каждого журнала - плата по адресу в имени файла; показанная плата.
                readonly property var mb: root.appController ? root.appController.chamberBoards : ({})
                readonly property bool multi: journalsSpoiler.mb.enabled === true
                function boardOf(sa) {
                    var boards = journalsSpoiler.mb.boards || []
                    for (var i = 0; i < boards.length; ++i)
                        if (boards[i].sa === sa) return boards[i]
                    return null
                }
                hintText: {
                    if (!root.appController)
                        return ""
                    var path = root.appController.chamberFilePath
                    return path.length > 0 ? "журнал сохраняется сам: " + path : "журнал сохранится сам после первой точки"
                }

                // Журналы на диске: своя папка и прошлые версии программы. Открыть - новые точки допишутся к нему
                // (так добирают точку к прошлому прогону); журнал прошлой версии открывается копией в своей папке.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Caption { text: "Журналы на диске (новые сверху)"; font.bold: true }
                    Item { Layout.fillWidth: true }
                    SmallButton {
                        Layout.preferredWidth: 110
                        text: "Обновить"
                        toolTipText: "Перечитать папки журналов"
                        onClicked: if (root.appController) root.appController.refreshChamberJournals()
                    }
                    SmallButton {
                        id: newJournalButton
                        property bool armed: false
                        Layout.preferredWidth: 150
                        text: armed ? "Точно? Ещё раз" : "Новый журнал"
                        tone: "#ef4444"; toneHover: "#dc2626"; tonePressed: "#b91c1c"
                        toolTipText: "Убирает точки из окна; следующая точка начнёт новый файл. Прежний файл остаётся на диске"
                        enabled: root.appController !== null && !root.busy && root.appController.chamberPointCount > 0
                        onClicked: {
                            if (!armed) { armed = true; newJournalDisarm.restart(); return }
                            armed = false
                            if (root.appController) root.appController.newChamberJournal()
                        }
                        Timer { id: newJournalDisarm; interval: 4000; onTriggered: newJournalButton.armed = false }
                    }
                }

                // Второй этап при нескольких платах: каждой плате - её журнал первого этапа одной кнопкой.
                RowLayout {
                    Layout.fillWidth: true
                    visible: journalsSpoiler.multi
                    spacing: 8

                    SmallButton {
                        Layout.preferredWidth: 270
                        text: "Журналы первого этапа всем платам"
                        tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                        toolTipText: "Каждой плате на шине откроется её журнал (адрес платы в имени файла, …_0x82.csv) с наибольшим числом узлов первого этапа - из любой папки, в том числе прошлой версии программы. Новые точки второго этапа допишутся к нему"
                        enabled: root.appController !== null && !root.busy
                        onClicked: if (root.appController) root.appController.openStage1Journals()
                    }
                    InfoMark {
                        tip: "Кнопка «Открыть» ниже открывает журнал только показанной плате"
                             + (journalsSpoiler.mb.shownName ? " - «" + journalsSpoiler.mb.shownName + "»" : "")
                             + ".<br>Журнал другой платы не откроется: покажите её в ленте."
                    }

                    Item { Layout.fillWidth: true }
                }

                NoticeLine {
                    appController: root.appController
                    text: journalsSpoiler.multi && (journalsSpoiler.mb.status || "").indexOf("Журналы первого этапа") === 0
                          ? journalsSpoiler.mb.status : ""
                    tone: (journalsSpoiler.mb.status || "").indexOf("нет") >= 0 ? "warn" : "ok"
                    kind: "Журналы"
                }

                Repeater {
                    model: root.appController ? root.appController.chamberJournals : []

                    RowLayout {
                        id: journalRow
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 8

                        readonly property var owner: journalsSpoiler.multi && journalRow.modelData.sa !== null
                                                     && journalRow.modelData.sa !== undefined
                                                     ? journalsSpoiler.boardOf(journalRow.modelData.sa) : null
                        // Журнал другой платы списка: показанной плате его не открыть.
                        readonly property bool foreign: journalRow.owner !== null
                                                        && ("0x" + ("0" + journalRow.owner.sa.toString(16).toUpperCase()).slice(-2))
                                                        !== journalsSpoiler.mb.shownSa

                        Text {
                            Layout.preferredWidth: 46
                            visible: journalsSpoiler.multi
                            text: journalRow.owner ? journalRow.owner.name : ""
                            color: journalRow.foreign ? "#94a3b8" : "#0f6ab4"
                            font.pixelSize: 12
                            font.bold: !journalRow.foreign
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            text: (journalRow.modelData.current ? "● " : "") + journalRow.modelData.name
                                  + (journalRow.modelData.folder ? "   ·   " + journalRow.modelData.folder : "")
                            color: journalRow.modelData.current ? "#0f6ab4" : (journalRow.foreign ? "#94a3b8" : root.textMain)
                            font.pixelSize: 12
                            font.bold: journalRow.modelData.current === true
                            font.family: "Bahnschrift"
                            elide: Text.ElideMiddle
                        }
                        Caption {
                            text: journalRow.modelData.points + " точ."
                                  + (journalRow.modelData.nodes ? "  ·  узлов " + journalRow.modelData.nodes + " из 7" : "")
                                  + "  ·  " + journalRow.modelData.modified
                        }
                        SmallButton {
                            Layout.preferredWidth: 100
                            text: journalRow.modelData.current ? "Открыт" : "Открыть"
                            toolTipText: "Новые точки допишутся к этому журналу. Журнал прошлой версии откроется копией в своей папке"
                            enabled: root.appController !== null && !root.busy && journalRow.modelData.current !== true
                                     && !journalRow.foreign
                            onClicked: if (root.appController) root.appController.openChamberJournal(journalRow.modelData.path)
                        }
                    }
                }

                Caption {
                    visible: !root.appController || root.appController.chamberJournals.length === 0
                    text: "Журналов на диске пока нет: первый появится сам после первой точки."
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    SmallButton {
                        Layout.preferredWidth: 170
                        text: "Сохранить журнал как..."
                        toolTipText: "Журнал и так сохраняется после каждой точки. Кнопка переносит его в другой файл, дальше автосохранение пишет туда"
                        enabled: root.appController !== null && !root.busy
                        onClicked: root.saveLogRequested()
                    }

                    SmallButton {
                        Layout.preferredWidth: 150
                        text: "Загрузить журнал"
                        toolTipText: "Продолжить прерванный прогон: новые точки допишутся в этот же файл"
                        enabled: root.appController !== null && !root.busy
                        onClicked: root.loadLogRequested()
                    }

                    SmallButton {
                        Layout.preferredWidth: 150
                        text: "Выгрузить таблицы"
                        toolTipText: "Сохраняет результат расчёта отдельным файлом для другого прибора"
                        enabled: root.appController !== null && !root.busy
                                && root.appController.chamberPointCount > 0
                        onClicked: root.exportTablesRequested()
                    }

                    Item { Layout.fillWidth: true }

                }
            }

            // --- Тестовый режим на столе: отладка без камеры ---
            Spoiler {
                title: "Тестовый режим на столе (отладка без камеры)"
                hintText: root.test.mode ? "включён: " + (root.test.emulationText || "настоящая температура")
                                         : "температура задаётся прибору эмуляцией, весь прогон проходится на столе"
                visible: root.page === "test"
                expanded: true

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        FancySwitch {
                            checked: root.test.mode === true
                            enabled: root.appController !== null && !root.busy
                            onToggled: if (root.appController) root.appController.setChamberTestMode(checked)
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.test.mode
                                  ? "Включён. Сейчас: " + (root.test.emulationText || "настоящая") + ". Точки помечаются как пробные"
                                  : "Выключен: прибор работает от своих датчиков"
                            color: root.test.mode ? "#9a3412" : root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.test.mode === true
                        spacing: 6

                        Caption { text: "Задать:" }

                        Repeater {
                            model: root.test.nodes || []

                            SmallButton {
                                required property var modelData
                                Layout.preferredWidth: 76
                                text: modelData.text
                                tone: modelData.current ? "#ea580c" : "#64748b"
                                toneHover: modelData.current ? "#c2410c" : "#475569"
                                tonePressed: modelData.current ? "#9a3412" : "#334155"
                                enabled: root.testIdle
                                onClicked: if (root.appController) root.appController.setChamberTestTemperature(modelData.value)
                            }
                        }

                        FancyTextField {
                            id: testTempField
                            Layout.preferredWidth: 80
                            Layout.preferredHeight: 30
                            placeholderText: "°C"
                            horizontalAlignment: TextInput.AlignHCenter
                            textColor: root.textMain
                            bgColor: root.inputBg
                            borderColor: root.inputBorder
                            focusBorderColor: root.inputFocus
                            onAccepted: if (root.appController && root.testIdle) root.appController.setChamberTestTemperatureText(text)
                        }

                        SmallButton {
                            Layout.preferredWidth: 80
                            text: "Задать"
                            toolTipText: "Любая температура от -55 до +125 °C, например -12,5"
                            enabled: root.testIdle && testTempField.text.length > 0
                            onClicked: if (root.appController) root.appController.setChamberTestTemperatureText(testTempField.text)
                        }

                        SmallButton {
                            Layout.preferredWidth: 100
                            text: "Настоящая"
                            tone: "#0f766e"; toneHover: "#115e59"; tonePressed: "#134e4a"
                            toolTipText: "Выключить эмуляцию: прибор вернётся к своим датчикам"
                            enabled: root.testIdle
                            onClicked: if (root.appController) root.appController.chamberTestEmulationOff()
                        }

                        Item { Layout.fillWidth: true }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.test.mode === true
                        spacing: 8

                        FancyButton {
                            Layout.preferredWidth: 270
                            Layout.preferredHeight: 30
                            fontPixelSize: 12
                            text: root.test.walking ? "Остановить обход" : "Пройти все узлы с текущей пометкой"
                            tone: root.test.walking ? "#b45309" : "#ea580c"
                            toneHover: root.test.walking ? "#92400e" : "#c2410c"
                            tonePressed: root.test.walking ? "#78350f" : "#9a3412"
                            toolTipText: "По очереди задаёт -40 ... +85 °C, ждёт, пока прибор их покажет, и в каждой пишет точку. В конце выключает эмуляцию"
                            enabled: root.appController !== null && !root.busy && !root.chain.busy
                                    && (root.test.walking || !root.test.busy)
                            onClicked: {
                                if (!root.appController)
                                    return
                                root.appController.setChamberLabel(labelField.text)
                                if (root.test.walking)
                                    root.appController.stopChamberTestWalk()
                                else
                                    root.appController.startChamberTestWalk()
                            }
                        }

                        FancySwitch {
                            checked: root.test.drift === true
                            enabled: root.appController !== null
                            onToggled: if (root.appController) root.appController.setChamberTestDrift(checked)
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "Имитировать уход платы: " + (root.test.driftText || "")
                            color: root.textMain
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                    }

                    NoticeLine {
                        appController: root.appController
                        text: root.test.mode === true ? (root.test.checkText || "") : ""
                        tone: root.test.checkColor || ""
                        kind: "Проверка"
                    }
                }
            }

            // --- Журнал снятых точек ---
            Text {
                visible: root.page === "points"
                text: "Журнал точек" + (root.appController ? "  ·  снято " + root.appController.chamberPointCount : "")
                color: root.textMain
                font.pixelSize: 13
                font.bold: true
                font.family: "Bahnschrift"
            }

            // На вкладках без журнала точек свободное место - внизу, а не над содержимым.
            Item {
                visible: root.page !== "points"
                Layout.fillWidth: true
                Layout.fillHeight: true
            }

            ScrollView {
                id: logScroll
                visible: root.page === "points"
                Layout.fillWidth: true
                Layout.fillHeight: true
                // Хотя бы несколько последних точек видно всегда, даже в невысоком окне.
                Layout.preferredHeight: 170
                Layout.minimumHeight: 170
                clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                ColumnLayout {
                    id: logBody
                    width: logScroll.availableWidth
                    spacing: 0

                    // Ширина колонок считается один раз и применяется и к шапке, и к
                    // строкам: иначе подписи разъедутся с данными.
                    readonly property var weights: [0.10, 0.22, 0.13, 0.13, 0.105, 0.105, 0.105, 0.105]
                    // Справа у каждой строки - кнопка «убрать точку».
                    readonly property int removeWidth: 34
                    function columnWidth(index) {
                        return Math.max(54, (width - removeWidth) * weights[index])
                    }

                    // Шапка таблицы: каждая подпись в своей ячейке с рамкой - над своим столбцом.
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        Repeater {
                            model: ["Время", "Что подключено", "Основной, отсч.", "Вид топлива, отсч.",
                                    "Трубка, °C", "Плата, °C", "Воздух камеры, °C", "Узел"]

                            Rectangle {
                                id: headCell
                                required property int index
                                required property string modelData
                                Layout.preferredWidth: logBody.columnWidth(headCell.index)
                                Layout.preferredHeight: 28
                                color: "#e8eef5"
                                border.width: 1
                                border.color: "#c5d0dc"

                                Text {
                                    anchors.fill: parent
                                    anchors.leftMargin: 6
                                    anchors.rightMargin: 6
                                    verticalAlignment: Text.AlignVCenter
                                    horizontalAlignment: Text.AlignHCenter
                                    text: headCell.modelData
                                    color: "#334155"
                                    font.pixelSize: 11
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                    elide: Text.ElideRight
                                }
                            }
                        }
                        Rectangle {
                            Layout.preferredWidth: logBody.removeWidth
                            Layout.preferredHeight: 28
                            color: "#e8eef5"
                            border.width: 1
                            border.color: "#c5d0dc"
                        }
                    }

                    Repeater {
                        model: root.appController ? root.appController.chamberRows : []

                        RowLayout {
                            id: logRow
                            required property var modelData
                            required property int index
                            // Строки через одну - с подложкой: глаз не теряет строку в широкой таблице.
                            readonly property color rowColor: logRow.index % 2 === 1 ? "#f5f8fb" : "#ffffff"

                            Layout.fillWidth: true
                            spacing: 0

                            Repeater {
                                model: [logRow.modelData.time, logRow.modelData.note, logRow.modelData.main,
                                        logRow.modelData.media, logRow.modelData.fuelTemp,
                                        logRow.modelData.boardTemp, logRow.modelData.chamberTemp,
                                        logRow.modelData.node]

                                Rectangle {
                                    id: bodyCell
                                    required property int index
                                    required property string modelData
                                    Layout.preferredWidth: logBody.columnWidth(bodyCell.index)
                                    Layout.preferredHeight: 26
                                    color: (bodyCell.index === 7 && !logRow.modelData.nodeOk) ? "#fff7e6" : logRow.rowColor
                                    border.width: 1
                                    border.color: "#dbe3ec"

                                    Text {
                                        anchors.fill: parent
                                        anchors.leftMargin: 6
                                        anchors.rightMargin: 6
                                        verticalAlignment: Text.AlignVCenter
                                        // Числа - по правому краю, слова - по левому: так столбцы читаются ровно.
                                        horizontalAlignment: bodyCell.index >= 2 && bodyCell.index <= 6 ? Text.AlignRight
                                                                                                         : Text.AlignLeft
                                        text: bodyCell.modelData
                                        color: (bodyCell.index === 7 && !logRow.modelData.nodeOk) ? "#b45309" : root.textMain
                                        font.pixelSize: 12
                                        font.family: "Bahnschrift"
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            // Убрать эту точку (например, недостоверную): первое нажатие - «точно?», второе - убирает.
                            Rectangle {
                                Layout.preferredWidth: logBody.removeWidth
                                Layout.preferredHeight: 26
                                color: logRow.rowColor
                                border.width: 1
                                border.color: "#dbe3ec"

                            SmallButton {
                                id: removeButton
                                property bool armed: false
                                anchors.centerIn: parent
                                width: logBody.removeWidth - 8
                                height: 20
                                fontPixelSize: 11
                                text: armed ? "?" : "✕"
                                tone: armed ? "#dc2626" : "#94a3b8"; toneHover: "#dc2626"; tonePressed: "#b91c1c"
                                toolTipText: armed ? "Нажмите ещё раз, чтобы убрать точку " + logRow.modelData.time
                                                   : "Убрать эту точку из журнала"
                                enabled: root.appController !== null && !root.busy
                                onClicked: {
                                    if (!armed) { armed = true; removeDisarm.restart(); return }
                                    armed = false
                                    if (root.appController)
                                        root.appController.removeChamberPoint(logRow.modelData.index, logRow.modelData.time)
                                }
                                Timer { id: removeDisarm; interval: 4000; onTriggered: removeButton.armed = false }
                            }
                            }
                        }
                    }
                }
            }
        }
    }

    Connections {
        target: root.appController

        function onChamberChanged() {
            if (!root.appController) {
                return
            }
            if (!labelField.activeFocus && labelField.text !== root.appController.chamberLabel) {
                labelField.text = root.appController.chamberLabel
            }
        }
    }
}
