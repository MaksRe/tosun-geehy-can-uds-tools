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

            // --- Снятие точки ---
            Rectangle {
                Layout.fillWidth: true
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

                        Rectangle {
                            Layout.alignment: Qt.AlignVCenter
                            Layout.preferredWidth: 10
                            Layout.preferredHeight: 10
                            radius: 5
                            color: root.appController ? root.appController.chamberStatusColor : "#64748b"
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.appController ? root.appController.chamberStatusText : "Контроллер недоступен"
                            color: root.appController ? root.appController.chamberStatusColor : "#64748b"
                            font.pixelSize: 13
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
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

                    Text {
                        Layout.fillWidth: true
                        text: (root.chain.status || "") + (root.chain.autoWrite === true ? "  ·  запишется сам при полных данных" : "")
                        color: root.chain.color || root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }
                }
            }

            // --- Замечания расчёта: только когда расчёту чего-то не хватило ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: reportLayout.implicitHeight + 16
                visible: root.appController && root.appController.chamberReportLines.length > 0
                radius: 10
                color: "#fffbeb"
                border.width: 1
                border.color: "#fcd34d"

                ColumnLayout {
                    id: reportLayout
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 2

                    Text {
                        text: "Чего не хватило расчёту"
                        color: "#92400e"
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Repeater {
                        model: root.appController ? root.appController.chamberReportLines : []

                        Text {
                            required property string modelData
                            Layout.fillWidth: true
                            text: "- " + modelData
                            color: "#92400e"
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }

            // --- Режим прогона и расчёт: задаётся один раз на прогон ---
            Spoiler {
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

                        Item { Layout.fillWidth: true }
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: root.boardOnly
                        text: "В каждом узле снимается одна точка «0/0»: к входам ничего не подключено. Поправка возвращает показание "
                              + "при своей ёмкости платы к показанию при +25 °C. При подключённой трубке это допущение: сдвиг и "
                              + "растяжение по одной ёмкости не разделить. Ряды трубки в профиле не меняются."
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
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

                    Text {
                        Layout.fillWidth: true
                        visible: !root.boardOnly && extendSwitch.checked
                        text: "Нужно, когда в камеру нельзя ставить топливо. Погружение снимается один раз "
                            + "при комнатной температуре, в остальных узлах размах считается таким же. "
                            + "Пустое поле означает «взять размах из снятой пары состояний»."
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
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

                        Text {
                            Layout.fillWidth: true
                            text: root.appController ? root.appController.chamberTablesText : ""
                            color: root.appController ? root.appController.chamberTablesColor : root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                    }
                }
            }

            // --- Файлы журнала и таблиц: журнал и так сохраняется сам после каждой точки ---
            Spoiler {
                title: "Файлы журнала и таблиц"
                hintText: {
                    if (!root.appController)
                        return ""
                    var path = root.appController.chamberFilePath
                    return path.length > 0 ? "журнал сохраняется сам: " + path : "журнал сохранится сам после первой точки"
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

                    SmallButton {
                        Layout.preferredWidth: 150
                        text: "Очистить журнал"
                        tone: "#ef4444"; toneHover: "#dc2626"; tonePressed: "#b91c1c"
                        toolTipText: "Убирает все точки из окна. Файл прежнего журнала остаётся на диске, следующая точка начнёт новый"
                        enabled: root.appController !== null && !root.busy
                        onClicked: if (root.appController) root.appController.clearChamberPoints()
                    }
                }
            }

            // --- Тестовый режим на столе: отладка без камеры ---
            Spoiler {
                title: "Тестовый режим на столе (отладка без камеры)"
                hintText: root.test.mode ? "включён: " + (root.test.emulationText || "настоящая температура")
                                         : "температура задаётся прибору эмуляцией, весь прогон проходится на столе"
                expanded: false

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
                            toolTipText: "Любая температура от -40 до +85 °C, например -12,5"
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

                    Text {
                        Layout.fillWidth: true
                        visible: root.test.mode === true && (root.test.checkText || "").length > 0
                        text: root.test.checkText || ""
                        color: root.test.checkColor || root.textSoft
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // --- Журнал снятых точек ---
            Text {
                text: "Журнал точек" + (root.appController ? "  ·  снято " + root.appController.chamberPointCount : "")
                color: root.textMain
                font.pixelSize: 13
                font.bold: true
                font.family: "Bahnschrift"
            }

            ScrollView {
                id: logScroll
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
                    spacing: 3

                    // Ширина колонок считается один раз и применяется и к шапке, и к
                    // строкам: иначе подписи разъедутся с данными.
                    readonly property var weights: [0.10, 0.22, 0.13, 0.13, 0.105, 0.105, 0.105, 0.105]
                    function columnWidth(index) {
                        return Math.max(54, (width - 7 * 6) * weights[index])
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Repeater {
                            model: ["Время", "Что подключено", "Основной", "Вид топлива",
                                    "T топлива", "T платы", "T камеры", "Узел"]

                            Text {
                                required property int index
                                required property string modelData
                                Layout.preferredWidth: logBody.columnWidth(index)
                                Layout.fillWidth: false
                                text: modelData
                                color: root.textSoft
                                font.pixelSize: 11
                                font.bold: true
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                            }
                        }
                    }

                    Repeater {
                        model: root.appController ? root.appController.chamberRows : []

                        RowLayout {
                            id: logRow
                            required property var modelData

                            Layout.fillWidth: true
                            spacing: 6

                            Repeater {
                                model: [logRow.modelData.time, logRow.modelData.note, logRow.modelData.main,
                                        logRow.modelData.media, logRow.modelData.fuelTemp,
                                        logRow.modelData.boardTemp, logRow.modelData.chamberTemp,
                                        logRow.modelData.node]

                                Text {
                                    required property int index
                                    required property string modelData
                                    Layout.preferredWidth: logBody.columnWidth(index)
                                    Layout.fillWidth: false
                                    text: modelData
                                    color: (index === 7 && !logRow.modelData.nodeOk) ? "#b45309" : root.textMain
                                    font.pixelSize: 12
                                    font.family: "Bahnschrift"
                                    elide: Text.ElideRight
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
