import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Карточка проверки прибора.
  Назначение:
  - показывает состояние обоих измерительных контуров и обоих датчиков температуры;
  - переводит числа телеметрии в короткий вердикт и подсказку что делать;
  - не требует от оператора знания номеров DID и допусков.

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

    readonly property string colorOk: "#16a34a"
    readonly property string colorWarn: "#d97706"
    readonly property string colorBad: "#dc2626"
    readonly property string colorIdle: "#64748b"

    // Пастельный фон и рамка для плашки вердикта подбираются по его цвету.
    function verdictBackground(verdictColor) {
        if (verdictColor === root.colorOk)
            return "#e8f7ee"
        if (verdictColor === root.colorWarn)
            return "#fdf3e3"
        if (verdictColor === root.colorBad)
            return "#fdeaea"
        return "#eef2f7"
    }

    function verdictBorder(verdictColor) {
        if (verdictColor === root.colorOk)
            return "#a8dfc2"
        if (verdictColor === root.colorWarn)
            return "#f0c98a"
        if (verdictColor === root.colorBad)
            return "#f3aeae"
        return "#cbd5e1"
    }

    // Худший вердикт внутри группы. По нему красится плитка итога сверху.
    function groupColor(groupName) {
        if (!root.appController)
            return root.colorIdle

        var rows = root.appController.diagnosticsRows
        var found = root.colorIdle
        var hasOk = false

        for (var i = 0; i < rows.length; ++i) {
            if (rows[i].group !== groupName)
                continue
            if (rows[i].color === root.colorBad)
                return root.colorBad
            if (rows[i].color === root.colorWarn)
                found = root.colorWarn
            if (rows[i].color === root.colorOk)
                hasOk = true
        }

        if (found === root.colorWarn)
            return root.colorWarn
        return hasOk ? root.colorOk : root.colorIdle
    }

    function groupVerdictText(groupName) {
        var groupVerdictColor = root.groupColor(groupName)
        if (groupVerdictColor === root.colorOk)
            return "В норме"
        if (groupVerdictColor === root.colorWarn)
            return "Требует внимания"
        if (groupVerdictColor === root.colorBad)
            return "Есть отказ"
        return "Нет данных"
    }

    // Первая строка группы рисуется вместе с заголовком группы.
    function isGroupStart(index) {
        if (!root.appController)
            return false

        var rows = root.appController.diagnosticsRows
        if (index <= 0)
            return true
        return rows[index].group !== rows[index - 1].group
    }

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        // --- Заголовок и управление ---
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 150
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: "Проверка прибора"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: "Оба контура измерения ёмкости и оба датчика температуры одним списком"
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }

            FancyComboBox {
                id: nodeSelector
                Layout.preferredWidth: 260
                Layout.preferredHeight: 36
                model: root.appController ? root.appController.calibrationNodeOptions : []
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
                onActivated: function(index) {
                    if (root.appController) {
                        nodeSelector.currentIndex = index
                        root.appController.setSelectedCalibrationNodeIndex(index)
                    }
                }
            }

            FancyButton {
                Layout.preferredWidth: 190
                Layout.preferredHeight: 36
                text: root.appController ? root.appController.diagnosticsActionText : "Начать проверку"
                tone: root.appController && root.appController.diagnosticsRunning ? "#ef4444" : "#0284c7"
                toneHover: root.appController && root.appController.diagnosticsRunning ? "#dc2626" : "#0369a1"
                tonePressed: root.appController && root.appController.diagnosticsRunning ? "#b91c1c" : "#075985"
                enabled: root.appController !== null
                onClicked: if (root.appController) root.appController.toggleDiagnostics()
            }

            FancyButton {
                Layout.preferredWidth: 180
                Layout.preferredHeight: 36
                text: "Скопировать отчёт"
                tone: "#64748b"
                toneHover: "#475569"
                tonePressed: "#334155"
                toolTipText: "Кладёт результат проверки в буфер обмена одним текстом"
                enabled: root.appController !== null
                onClicked: if (root.appController) root.appController.copyDiagnosticsReport()
            }
        }

        // --- Общий вердикт ---
        Rectangle {
            Layout.fillWidth: true
            // Высота плашки фиксирована, обе подписи в одну строку с многоточием.
            Layout.preferredHeight: 68
            radius: 12
            color: root.appController
                ? root.verdictBackground(root.appController.diagnosticsSummaryColor)
                : "#eef2f7"
            border.width: 1
            border.color: root.appController
                ? root.verdictBorder(root.appController.diagnosticsSummaryColor)
                : "#cbd5e1"

            RowLayout {
                id: summaryLayout
                anchors.fill: parent
                anchors.margins: 10
                spacing: 12

                Rectangle {
                    Layout.alignment: Qt.AlignVCenter
                    Layout.preferredWidth: 14
                    Layout.preferredHeight: 14
                    radius: 7
                    color: root.appController ? root.appController.diagnosticsSummaryColor : root.colorIdle
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 160
                    spacing: 2

                    Text {
                        Layout.fillWidth: true
                        text: root.appController ? root.appController.diagnosticsSummaryText : "Контроллер недоступен"
                        color: root.appController ? root.appController.diagnosticsSummaryColor : root.colorIdle
                        font.pixelSize: 16
                        font.bold: true
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.appController ? root.appController.diagnosticsStatusText : ""
                        color: root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }
                }

                StatusChip {
                    Layout.alignment: Qt.AlignVCenter
                    label: root.appController ? root.appController.diagnosticsCyclesText : "Кругов опроса: 0"
                    chipColor: "#ffffff"
                    chipBorder: "#cbd5e1"
                    textColor: root.textSoft
                }
            }
        }

        // --- Плитки по трём блокам прибора ---
        GridLayout {
            Layout.fillWidth: true
            columns: width > 900 ? 3 : 1
            columnSpacing: 10
            rowSpacing: 10

            Repeater {
                model: ["Контур уровня топлива", "Контур вида топлива", "Температура"]

                Rectangle {
                    required property string modelData

                    Layout.fillWidth: true
                    radius: 11
                    implicitHeight: 62
                    color: root.verdictBackground(root.groupColor(modelData))
                    border.width: 1
                    border.color: root.verdictBorder(root.groupColor(modelData))

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 2

                        Text {
                            Layout.fillWidth: true
                            text: modelData
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.groupVerdictText(modelData)
                            color: root.groupColor(modelData)
                            font.pixelSize: 17
                            font.bold: true
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        // --- Подробная таблица ---
        ScrollView {
            id: detailsScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            // Ширину содержимого задаём явно, иначе ScrollView берёт её от самого содержимого
            // и колонка схлопывается до минимума, а строки выезжают за карточку.
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                width: detailsScroll.availableWidth
                spacing: 6

                Repeater {
                    model: root.appController ? root.appController.diagnosticsRows : []

                    ColumnLayout {
                        id: rowBlock
                        required property int index
                        required property var modelData

                        Layout.fillWidth: true
                        spacing: 6

                        Text {
                            Layout.fillWidth: true
                            Layout.topMargin: rowBlock.index > 0 ? 10 : 0
                            visible: root.isGroupStart(rowBlock.index)
                            text: rowBlock.modelData.group
                            color: root.textMain
                            font.pixelSize: 14
                            font.bold: true
                            font.family: "Bahnschrift"
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            // Высота строки фиксирована: подписи в одну строку с многоточием,
                            // поэтому таблица не прыгает и текст никогда не выходит за рамку.
                            Layout.preferredHeight: 52
                            radius: 10
                            color: rowHover.hovered ? "#f4f9ff" : "#fbfdff"
                            border.width: 1
                            border.color: rowHover.hovered ? "#cbdcf0" : "#e2ebf5"

                            HoverHandler {
                                id: rowHover
                            }

                            ToolTip.visible: rowHover.hovered && rowBlock.modelData.hint.length > 0
                            ToolTip.delay: 400
                            ToolTip.text: rowBlock.modelData.label + ": " + rowBlock.modelData.hint

                            RowLayout {
                                id: checkLayout
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 10

                                Rectangle {
                                    Layout.alignment: Qt.AlignVCenter
                                    Layout.preferredWidth: 10
                                    Layout.preferredHeight: 10
                                    radius: 5
                                    color: rowBlock.modelData.color
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 120
                                    spacing: 1

                                    Text {
                                        Layout.fillWidth: true
                                        text: rowBlock.modelData.label
                                        color: root.textMain
                                        font.pixelSize: 13
                                        font.family: "Bahnschrift"
                                        elide: Text.ElideRight
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: rowBlock.modelData.hint
                                        color: root.textSoft
                                        font.pixelSize: 11
                                        font.family: "Bahnschrift"
                                        elide: Text.ElideRight
                                    }
                                }

                                Text {
                                    Layout.preferredWidth: 150
                                    Layout.minimumWidth: 80
                                    Layout.alignment: Qt.AlignVCenter
                                    horizontalAlignment: Text.AlignRight
                                    text: rowBlock.modelData.value
                                    color: root.textMain
                                    font.pixelSize: 14
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                    elide: Text.ElideRight
                                }

                                Rectangle {
                                    Layout.preferredWidth: 168
                                    Layout.minimumWidth: 96
                                    Layout.preferredHeight: 26
                                    Layout.alignment: Qt.AlignVCenter
                                    radius: 8
                                    color: root.verdictBackground(rowBlock.modelData.color)
                                    border.width: 1
                                    border.color: root.verdictBorder(rowBlock.modelData.color)

                                    Text {
                                        anchors.fill: parent
                                        anchors.margins: 5
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                        text: rowBlock.modelData.verdict
                                        color: rowBlock.modelData.color
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

        // --- Расшифровка цветов ---
        RowLayout {
            Layout.fillWidth: true
            spacing: 14

            Repeater {
                model: [
                    { legendColor: root.colorOk, legendText: "Норма, вмешательство не нужно" },
                    { legendColor: root.colorWarn, legendText: "Работает, но стоит разобраться" },
                    { legendColor: root.colorBad, legendText: "Отказ, прибор нельзя отдавать" },
                    { legendColor: root.colorIdle, legendText: "Справочно или нет данных" }
                ]

                RowLayout {
                    required property var modelData
                    spacing: 6

                    Rectangle {
                        Layout.preferredWidth: 10
                        Layout.preferredHeight: 10
                        radius: 5
                        color: modelData.legendColor
                    }

                    Text {
                        text: modelData.legendText
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                    }
                }
            }

            Item {
                Layout.fillWidth: true
            }
        }
    }

    Connections {
        target: root.appController

        function onCalibrationNodeSelectionChanged() {
            if (!root.appController) {
                return
            }
            if (nodeSelector.currentIndex !== root.appController.selectedCalibrationNodeIndex) {
                nodeSelector.currentIndex = root.appController.selectedCalibrationNodeIndex
            }
        }
    }

    Component.onCompleted: {
        if (root.appController) {
            nodeSelector.currentIndex = root.appController.selectedCalibrationNodeIndex
        }
    }
}
