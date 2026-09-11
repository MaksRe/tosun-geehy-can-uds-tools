import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Раздел прогона изделия в климатической камере.
  Назначение:
  - снимает точки прогона: период обоих контуров и обе температуры;
  - показывает, чего ещё не хватает по каждому узлу температурной сетки;
  - сам считает обе ступени и кладёт результат в таблицу профиля;
  - сохраняет журнал прогона в файл, чтобы прерванный прогон можно было продолжить.

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

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
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
                text: "Доведите камеру до температуры, подключите эталон, напишите что подключено и снимите точку"
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                elide: Text.ElideRight
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
                        placeholderText: "например: 300 пФ, 600 пФ, воздух, жидкость"
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
                        text: root.busy ? "Идёт замер..." : "Записать точку"
                        tone: "#16a34a"
                        toneHover: "#15803d"
                        tonePressed: "#166534"
                        toolTipText: "Снимает несколько замеров подряд и кладёт в журнал их среднее"
                        enabled: root.appController !== null && !root.busy
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
                        text: "Пометка с числом идёт в расчёт платы, «воздух» и «жидкость» в расчёт трубки"
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

        // --- Репетиция на столе ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: rehearsalLayout.implicitHeight + 18
            radius: 12
            color: rehearsalSwitch.checked ? "#fef2f2" : "#f8fbff"
            border.width: 1
            border.color: rehearsalSwitch.checked ? "#fca5a5" : "#d6e2ef"

            ColumnLayout {
                id: rehearsalLayout
                anchors.fill: parent
                anchors.margins: 9
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    FancySwitch {
                        id: rehearsalSwitch
                        checked: root.appController ? root.appController.chamberRehearsal : false
                        enabled: root.appController !== null && !root.busy
                        onToggled: if (root.appController) root.appController.setChamberRehearsal(checked)
                    }

                    Text {
                        Layout.fillWidth: true
                        text: rehearsalSwitch.checked
                            ? "Репетиция: температура берётся не из прибора, а из поля справа"
                            : "Репетиция на столе без камеры"
                        color: rehearsalSwitch.checked ? "#b91c1c" : root.textMain
                        font.pixelSize: 13
                        font.bold: true
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }

                    Text {
                        text: "Считать температуру равной"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        Layout.alignment: Qt.AlignVCenter
                        visible: rehearsalSwitch.checked
                    }

                    FancyTextField {
                        id: rehearsalTempField
                        Layout.preferredWidth: 90
                        Layout.preferredHeight: 30
                        visible: rehearsalSwitch.checked
                        text: root.appController ? root.appController.chamberRehearsalTemperatureText : "25"
                        placeholderText: "°C"
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        onAccepted: if (root.appController) root.appController.setChamberRehearsalTemperature(text)
                        onEditingFinished: if (root.appController) root.appController.setChamberRehearsalTemperature(text)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    visible: rehearsalSwitch.checked

                    Text {
                        text: "Узлы сетки"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        Layout.alignment: Qt.AlignVCenter
                    }

                    Repeater {
                        model: root.appController ? root.appController.chamberNodeTitles : []

                        FancyButton {
                            required property int index
                            required property string modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 28
                            fontPixelSize: 12
                            text: modelData
                            tone: "#64748b"
                            toneHover: "#475569"
                            tonePressed: "#334155"
                            enabled: root.appController !== null && !root.busy
                            onClicked: {
                                if (!root.appController)
                                    return
                                var value = String(root.appController.chamberNodeValues[index])
                                rehearsalTempField.text = value
                                root.appController.setChamberRehearsalTemperature(value)
                            }
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Проверка всего порядка работы без камеры. Периоды читаются из настоящего "
                        + "прибора, таблицы считаются и пишутся по-честному, подставляется только "
                        + "температура. Точки репетиции помечаются в журнале, и расчёт напоминает, "
                        + "что такие таблицы в рабочий прибор писать нельзя."
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
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
                    text: "Чего ещё не хватает"
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
                            Layout.preferredHeight: 72
                            radius: 9
                            color: allOk ? "#ecfdf5" : "#fffbeb"
                            border.width: 1
                            border.color: allOk ? "#86efac" : "#fcd34d"

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 7
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
                                    text: "эталоны " + modelData.caps
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
            Layout.preferredHeight: extendLayout.implicitHeight + 18
            radius: 12
            color: "#fefce8"
            border.width: 1
            border.color: "#fde68a"

            ColumnLayout {
                id: extendLayout
                anchors.fill: parent
                anchors.margins: 9
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

        // --- Расчёт и файлы ---
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            FancyButton {
                Layout.preferredWidth: 210
                Layout.preferredHeight: 36
                text: "Посчитать таблицы"
                tone: "#0284c7"
                toneHover: "#0369a1"
                tonePressed: "#075985"
                toolTipText: "Считает обе ступени по снятым точкам и сразу переносит их в раздел профиля"
                enabled: root.appController !== null && !root.busy
                        && root.appController.chamberPointCount > 0
                onClicked: if (root.appController) root.appController.computeChamberTables()
            }

            Text {
                Layout.fillWidth: true
                text: {
                    if (!root.appController)
                        return "Контроллер недоступен"
                    var count = root.appController.chamberPointCount
                    var path = root.appController.chamberFilePath
                    var head = "Снято точек: " + count
                    return path.length > 0 ? head + ". Файл: " + path : head
                }
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                elide: Text.ElideLeft
            }

            FancyButton {
                Layout.preferredWidth: 150
                Layout.preferredHeight: 32
                fontPixelSize: 12
                text: "Сохранить журнал"
                tone: "#64748b"
                toneHover: "#475569"
                tonePressed: "#334155"
                toolTipText: "Прогон длится часами, сохранённый журнал позволяет продолжить его после перерыва"
                enabled: root.appController !== null && !root.busy
                onClicked: root.saveLogRequested()
            }

            FancyButton {
                Layout.preferredWidth: 150
                Layout.preferredHeight: 32
                fontPixelSize: 12
                text: "Загрузить журнал"
                tone: "#64748b"
                toneHover: "#475569"
                tonePressed: "#334155"
                enabled: root.appController !== null && !root.busy
                onClicked: root.loadLogRequested()
            }

            FancyButton {
                Layout.preferredWidth: 150
                Layout.preferredHeight: 32
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
                Layout.preferredWidth: 120
                Layout.preferredHeight: 32
                fontPixelSize: 12
                text: "Очистить"
                tone: "#ef4444"
                toneHover: "#dc2626"
                tonePressed: "#b91c1c"
                toolTipText: "Убирает все снятые точки. Отменить это нельзя"
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

        // --- Ход работы ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 46
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
