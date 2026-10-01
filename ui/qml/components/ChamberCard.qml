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

            // --- Заголовок ---
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: "Прогон в климатической камере"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: "Доведите камеру до температуры, подключите эталоны, дождитесь, пока среднее успокоится, напишите что подключено и запишите точку"
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }

            // --- Живые показания: текущее и среднее рядом, как в калибровке бака ---
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
                                { "title": "Основной контур: период", "key": "main" },
                                { "title": "Вид топлива: период", "key": "media" }
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

                                        Text {
                                            text: "Текущий"
                                            color: root.textSoft
                                            font.pixelSize: 11
                                            font.family: "Bahnschrift"
                                        }

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

                                        Text {
                                            text: "Среднее, пойдёт в точку"
                                            color: root.textSoft
                                            font.pixelSize: 11
                                            font.family: "Bahnschrift"
                                        }

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
                            Text {
                                text: (root.live.boardTemp || {}).now || "—"
                                color: root.textMain
                                font.pixelSize: 15
                                font.bold: true
                                font.family: "Bahnschrift"
                            }
                            Text {
                                text: (root.live.boardTemp || {}).avg || "—"
                                color: "#0f766e"
                                font.pixelSize: 15
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            Text { text: "Топливо"; color: root.textMain; font.pixelSize: 13; font.family: "Bahnschrift" }
                            Text {
                                text: (root.live.fuelTemp || {}).now || "—"
                                color: root.textMain
                                font.pixelSize: 15
                                font.bold: true
                                font.family: "Bahnschrift"
                            }
                            Text {
                                text: (root.live.fuelTemp || {}).avg || "—"
                                color: "#0f766e"
                                font.pixelSize: 15
                                font.bold: true
                                font.family: "Bahnschrift"
                            }
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

                        Text {
                            text: "Окно среднего, с"
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            Layout.alignment: Qt.AlignVCenter
                        }

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
                }
            }

            // --- Тестовый режим: камера на столе, температуру задаёт эмуляция в приборе ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: testLayout.implicitHeight + 16
                radius: 12
                color: root.test.mode ? "#fff7ed" : "#f8fafc"
                border.width: 1
                border.color: root.test.mode ? "#fdba74" : "#e2e8f0"

                ColumnLayout {
                    id: testLayout
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        FancySwitch {
                            checked: root.test.mode === true
                            enabled: root.appController !== null && !root.busy
                            onToggled: if (root.appController) root.appController.setChamberTestMode(checked)
                        }

                        Text {
                            text: "Тестовый режим на столе"
                            color: root.textMain
                            font.pixelSize: 13
                            font.bold: true
                            font.family: "Bahnschrift"
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.test.mode
                                ? "Температуру задаёт эмуляция в приборе. Сейчас: " + (root.test.emulationText || "настоящая")
                                  + ". Точки помечаются как пробные"
                                : "Температура задаётся прибору вручную: весь прогон проходится на столе без камеры"
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

                        Text {
                            text: "Задать:"
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            Layout.alignment: Qt.AlignVCenter
                        }

                        Repeater {
                            model: root.test.nodes || []

                            FancyButton {
                                required property var modelData
                                Layout.preferredWidth: 76
                                Layout.preferredHeight: 28
                                fontPixelSize: 12
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

                        FancyButton {
                            Layout.preferredWidth: 80
                            Layout.preferredHeight: 28
                            fontPixelSize: 12
                            text: "Задать"
                            tone: "#64748b"
                            toneHover: "#475569"
                            tonePressed: "#334155"
                            toolTipText: "Любая температура от -40 до +85 °C, например -12,5"
                            enabled: root.testIdle && testTempField.text.length > 0
                            onClicked: if (root.appController) root.appController.setChamberTestTemperatureText(testTempField.text)
                        }

                        FancyButton {
                            Layout.preferredWidth: 100
                            Layout.preferredHeight: 28
                            fontPixelSize: 12
                            text: "Настоящая"
                            tone: "#0f766e"
                            toneHover: "#115e59"
                            tonePressed: "#134e4a"
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
                        visible: root.test.mode === true
                        text: root.test.status || ""
                        color: root.test.color || root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
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

            // --- Снятие точки ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 92
                radius: 12
                color: "#f2f7ff"
                border.width: 1
                border.color: "#c6dcf5"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Text {
                            text: "Что подключено сейчас"
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            Layout.alignment: Qt.AlignVCenter
                        }

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

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Text {
                            Layout.fillWidth: true
                            text: "«150/47»: эталон основного и вида топлива, у каждого контура своя таблица платы. «воздух» и «жидкость» - в расчёт трубки"
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }

                        Repeater {
                            model: ["воздух", "жидкость"]

                            FancyButton {
                                required property string modelData
                                Layout.preferredWidth: 104
                                Layout.preferredHeight: 28
                                fontPixelSize: 12
                                text: modelData
                                tone: "#64748b"
                                toneHover: "#475569"
                                tonePressed: "#334155"
                                enabled: root.appController !== null && !root.busy
                                onClicked: {
                                    labelField.text = modelData
                                    if (root.appController) root.appController.setChamberLabel(modelData)
                                }
                            }
                        }

                        FancyButton {
                            Layout.preferredWidth: 150
                            Layout.preferredHeight: 28
                            fontPixelSize: 12
                            text: "Отменить последнюю"
                            tone: "#b45309"
                            toneHover: "#92400e"
                            tonePressed: "#78350f"
                            enabled: root.appController !== null && !root.busy
                            onClicked: if (root.appController) root.appController.removeLastChamberPoint()
                        }
                    }
                }
            }

            // --- Ход работы ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 36
                radius: 10
                color: "#f8fbff"
                border.width: 1
                border.color: "#d6e2ef"

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 10

                    Rectangle {
                        Layout.alignment: Qt.AlignVCenter
                        Layout.preferredWidth: 12
                        Layout.preferredHeight: 12
                        radius: 6
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
                }
            }

            // --- Полнота прогона по узлам ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: coverageLayout.implicitHeight + 20
                radius: 12
                color: "#f8fbff"
                border.width: 1
                border.color: "#d6e2ef"

                ColumnLayout {
                    id: coverageLayout
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 6

                    Text {
                        text: "Чего ещё не хватает  ·  эталоны: основной · вид топлива, нужно по 2"
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
                                Layout.preferredHeight: 60
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
                                        text: "трубка: " + modelData.tube
                                        color: modelData.tubeOk ? "#15803d" : "#b45309"
                                        font.pixelSize: 11
                                        font.family: "Bahnschrift"
                                        horizontalAlignment: Text.AlignHCenter
                                        wrapMode: Text.WordWrap
                                        maximumLineCount: 2
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // --- Достройка строк «в жидкости» ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: extendLayout.implicitHeight + 12
                radius: 12
                color: "#fefce8"
                border.width: 1
                border.color: "#fde68a"

                ColumnLayout {
                    id: extendLayout
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        FancySwitch {
                            id: extendSwitch
                            checked: root.appController ? root.appController.chamberExtendLiquid : false
                            enabled: root.appController !== null
                            onToggled: if (root.appController) root.appController.setChamberExtendLiquid(checked)
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "Достроить строки «в жидкости» по постоянному размаху"
                            color: root.textMain
                            font.pixelSize: 13
                            font.bold: true
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }

                        Text {
                            text: "Размах основного"
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            Layout.alignment: Qt.AlignVCenter
                            visible: extendSwitch.checked
                        }

                        FancyTextField {
                            id: spanMainField
                            Layout.preferredWidth: 110
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

                        Text {
                            text: "Размах вида топлива"
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            Layout.alignment: Qt.AlignVCenter
                            visible: extendSwitch.checked
                        }

                        FancyTextField {
                            id: spanMediaField
                            Layout.preferredWidth: 110
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
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: extendSwitch.checked
                        text: "Нужно, когда в камеру нельзя ставить топливо. Погружение снимается один раз "
                            + "при комнатной температуре, в остальных узлах размах считается таким же. "
                            + "Пустое поле означает «взять размах из снятой пары состояний»."
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // --- Расчёт таблиц: идёт сам после каждой точки ---
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                FancyButton {
                    Layout.preferredWidth: 190
                    Layout.preferredHeight: 32
                    fontPixelSize: 13
                    text: "Пересчитать таблицы"
                    tone: "#0284c7"
                    toneHover: "#0369a1"
                    tonePressed: "#075985"
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

            // --- Запись профиля в прибор: доступ, запись, сверка, файл ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: chainLayout.implicitHeight + 18
                radius: 12
                color: "#f0fdf4"
                border.width: 1
                border.color: "#bbf7d0"

                ColumnLayout {
                    id: chainLayout
                    anchors.fill: parent
                    anchors.margins: 9
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        FancySwitch {
                            checked: root.chain.autoWrite === true
                            enabled: root.appController !== null
                            onToggled: if (root.appController) root.appController.setChamberAutoWrite(checked)
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "Сам писать профиль в прибор, когда данных хватило во всех узлах"
                            color: root.textMain
                            font.pixelSize: 13
                            font.bold: true
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }

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
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

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
                            text: root.chain.status || ""
                            color: root.chain.color || root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                    }
                }
            }

            // --- Файлы журнала ---
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    Layout.fillWidth: true
                    text: {
                        if (!root.appController)
                            return "Контроллер недоступен"
                        var count = root.appController.chamberPointCount
                        var path = root.appController.chamberFilePath
                        var head = "Снято точек: " + count
                        return path.length > 0 ? head + ". Журнал сохраняется сам: " + path
                                               : head + ". Журнал сохранится сам после первой точки"
                    }
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    elide: Text.ElideLeft
                }

                FancyButton {
                    Layout.preferredWidth: 160
                    Layout.preferredHeight: 30
                    fontPixelSize: 12
                    text: "Сохранить журнал как..."
                    tone: "#64748b"
                    toneHover: "#475569"
                    tonePressed: "#334155"
                    toolTipText: "Журнал и так сохраняется после каждой точки. Кнопка переносит его в другой файл, дальше автосохранение пишет туда"
                    enabled: root.appController !== null && !root.busy
                    onClicked: root.saveLogRequested()
                }

                FancyButton {
                    Layout.preferredWidth: 140
                    Layout.preferredHeight: 30
                    fontPixelSize: 12
                    text: "Загрузить журнал"
                    tone: "#64748b"
                    toneHover: "#475569"
                    tonePressed: "#334155"
                    toolTipText: "Продолжить прерванный прогон: новые точки допишутся в этот же файл"
                    enabled: root.appController !== null && !root.busy
                    onClicked: root.loadLogRequested()
                }

                FancyButton {
                    Layout.preferredWidth: 140
                    Layout.preferredHeight: 30
                    fontPixelSize: 12
                    text: "Выгрузить таблицы"
                    tone: "#64748b"
                    toneHover: "#475569"
                    tonePressed: "#334155"
                    toolTipText: "Сохраняет результат расчёта отдельным файлом для другого прибора"
                    enabled: root.appController !== null && !root.busy
                            && root.appController.chamberPointCount > 0
                    onClicked: root.exportTablesRequested()
                }

                FancyButton {
                    Layout.preferredWidth: 100
                    Layout.preferredHeight: 30
                    fontPixelSize: 12
                    text: "Очистить"
                    tone: "#ef4444"
                    toneHover: "#dc2626"
                    tonePressed: "#b91c1c"
                    toolTipText: "Убирает все точки из окна. Файл прежнего журнала остаётся на диске, следующая точка начнёт новый"
                    enabled: root.appController !== null && !root.busy
                    onClicked: if (root.appController) root.appController.clearChamberPoints()
                }
            }

            // --- Замечания расчёта ---
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

            // --- Журнал снятых точек ---
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
                    readonly property var weights: [0.11, 0.24, 0.15, 0.15, 0.12, 0.12, 0.11]
                    function columnWidth(index) {
                        return Math.max(54, (width - 6 * 6) * weights[index])
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Repeater {
                            model: ["Время", "Что подключено", "Основной", "Вид топлива",
                                    "T топлива", "T платы", "Узел"]

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
                                        logRow.modelData.boardTemp, logRow.modelData.node]

                                Text {
                                    required property int index
                                    required property string modelData
                                    Layout.preferredWidth: logBody.columnWidth(index)
                                    Layout.fillWidth: false
                                    text: modelData
                                    color: (index === 6 && !logRow.modelData.nodeOk) ? "#b45309" : root.textMain
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
