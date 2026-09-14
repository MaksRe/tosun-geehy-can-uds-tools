import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Раздел пробной калибровки на столе.
  Назначение:
  - проходит весь порядок калибровки до выезда в климатическую камеру;
  - плата подключена к шине, на каждом контуре висит по одному постоянному
    конденсатору, а температуру прибору задаёт эмуляция в самой прошивке;
  - ни один шаг не требует менять конденсатор: отметки и точки программа
    ставит вокруг показания того, что уже подключено;
  - проверяет не только запись, но и применение: итоговый период прибора
    сверяется с расчётом по формулам прошивки;
  - запоминает настройки прибора до начала и возвращает их в конце.

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

    signal saveProtocolRequested()

    readonly property bool busy: root.appController ? root.appController.trialBusy : false
    readonly property bool ready: root.appController !== null && !root.busy

    // Строка шага по ключу. Привязки ниже пересчитываются, когда контроллер обновляет шаги.
    function stepRow(key) {
        var rows = root.appController ? root.appController.trialSteps : []
        for (var i = 0; i < rows.length; i += 1) {
            if (rows[i].key === key)
                return rows[i]
        }
        return {"number": 0, "title": "", "hint": "", "statusText": "", "statusColor": "#64748b", "detail": ""}
    }

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    // Карточка шага с одной кнопкой: таких шагов большинство.
    component SimpleStep: TrialStepCard {
        id: simpleStep
        property string stepKey: ""
        property string buttonText: "Проверить"
        property color buttonTone: "#0284c7"
        property color buttonHover: "#0369a1"
        property color buttonPressed: "#075985"
        property int buttonWidth: 160
        property string buttonHint: ""
        readonly property var row: root.stepRow(stepKey)

        Layout.fillWidth: true
        number: row.number
        title: row.title
        hint: row.hint
        statusText: row.statusText
        statusColor: row.statusColor
        detail: row.detail
        textMain: root.textMain
        textSoft: root.textSoft

        FancyButton {
            Layout.preferredWidth: simpleStep.buttonWidth
            Layout.preferredHeight: 30
            fontPixelSize: 12
            text: simpleStep.buttonText
            tone: simpleStep.buttonTone
            toneHover: simpleStep.buttonHover
            tonePressed: simpleStep.buttonPressed
            toolTipText: simpleStep.buttonHint
            enabled: root.ready
            onClicked: root.appController.runTrialStep(simpleStep.stepKey)
        }
    }

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
                    text: "Пробная калибровка на столе"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: "Плата на шине, на каждом контуре по одному конденсатору, температуру задаёт эмуляция в самом приборе"
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }

            Text {
                text: root.appController ? root.appController.trialSummaryText : ""
                color: root.textMain
                font.pixelSize: 14
                font.bold: true
                font.family: "Bahnschrift"
            }
        }

        // --- Безопасность: запомнить и вернуть ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: safetyLayout.implicitHeight + 18
            radius: 12
            color: "#fff7ed"
            border.width: 1
            border.color: "#fdba74"

            ColumnLayout {
                id: safetyLayout
                anchors.fill: parent
                anchors.margins: 9
                spacing: 6

                Text {
                    Layout.fillWidth: true
                    text: "Пробная калибровка перезаписывает калибровку прибора. Перед началом нажмите "
                        + "«Запомнить текущие настройки», в конце «Вернуть как было»."
                    color: "#9a3412"
                    font.pixelSize: 12
                    font.bold: true
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                Text {
                    Layout.fillWidth: true
                    text: root.appController ? root.appController.trialBackupText : ""
                    color: "#9a3412"
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    FancyButton {
                        Layout.preferredWidth: 230
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Запомнить текущие настройки"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        toolTipText: "Читает отметки бака, подгонку нуля, точки вида топлива и профиль, и сохраняет копию в файл"
                        enabled: root.ready
                        onClicked: root.appController.trialBackupSettings()
                    }

                    FancyButton {
                        Layout.preferredWidth: 170
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Вернуть как было"
                        tone: "#16a34a"
                        toneHover: "#15803d"
                        tonePressed: "#166534"
                        toolTipText: "Записывает запомненные настройки обратно и читает их для сверки"
                        enabled: root.ready
                        onClicked: root.appController.trialRestoreSettings()
                    }

                    FancyButton {
                        Layout.preferredWidth: 170
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Выключить эмуляцию"
                        tone: "#b45309"
                        toneHover: "#92400e"
                        tonePressed: "#78350f"
                        toolTipText: "Возвращает прибор к настоящим датчикам температуры"
                        enabled: root.ready
                        onClicked: root.appController.trialEmulationOff()
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    FancyButton {
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Сбросить отметки"
                        tone: "#64748b"
                        toneHover: "#475569"
                        tonePressed: "#334155"
                        toolTipText: "Возвращает все шаги в состояние «не проверено». В приборе ничего не меняет"
                        enabled: root.ready
                        onClicked: root.appController.trialResetSteps()
                    }

                    FancyButton {
                        Layout.preferredWidth: 170
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Сохранить протокол"
                        tone: "#64748b"
                        toneHover: "#475569"
                        tonePressed: "#334155"
                        toolTipText: "Записывает итог каждого шага и ход работы в текстовый файл"
                        enabled: root.appController !== null
                        onClicked: root.saveProtocolRequested()
                    }
                }
            }
        }

        // --- Шаги ---
        ScrollView {
            id: stepsScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                width: stepsScroll.availableWidth
                spacing: 8

                SimpleStep {
                    stepKey: "link"
                }

                SimpleStep {
                    stepKey: "access"
                }

                SimpleStep {
                    stepKey: "emulation"
                }

                SimpleStep {
                    stepKey: "level"
                    buttonText: "Записать и проверить"
                    buttonTone: "#16a34a"
                    buttonHover: "#15803d"
                    buttonPressed: "#166534"
                    buttonWidth: 190
                    buttonHint: "Снимает показание конденсатора, ставит вокруг него отметки и сверяет уровень с 25 %"
                }

                SimpleStep {
                    stepKey: "media"
                    buttonText: "Записать и проверить"
                    buttonTone: "#16a34a"
                    buttonHover: "#15803d"
                    buttonPressed: "#166534"
                    buttonWidth: 190
                    buttonHint: "Снимает показание конденсатора, ставит точки и ждёт, пока коэффициент среды станет 1,100"
                }

                TrialStepCard {
                    id: chamberStep
                    readonly property var row: root.stepRow("chamber")
                    Layout.fillWidth: true
                    number: row.number
                    title: row.title
                    hint: row.hint
                    statusText: row.statusText
                    statusColor: row.statusColor
                    detail: row.detail
                    textMain: root.textMain
                    textSoft: root.textSoft

                    FancyButton {
                        Layout.preferredWidth: 170
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Снять все точки"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        toolTipText: "Очищает журнал прогона и проходит семь температур сетки, конденсаторы трогать не нужно"
                        enabled: root.ready
                        onClicked: root.appController.runTrialStep("chamber")
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.appController ? root.appController.trialChamberProgressText : ""
                        color: root.textMain
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                        horizontalAlignment: Text.AlignRight
                        elide: Text.ElideLeft
                    }
                }

                SimpleStep {
                    stepKey: "profile"
                    buttonText: "Записать и сверить"
                    buttonWidth: 180
                }

                SimpleStep {
                    stepKey: "apply"
                    buttonText: "Проверить применение"
                    buttonWidth: 200
                }

                SimpleStep {
                    stepKey: "persist"
                    buttonText: "Перезапустить и проверить"
                    buttonTone: "#b45309"
                    buttonHover: "#92400e"
                    buttonPressed: "#78350f"
                    buttonWidth: 230
                    buttonHint: "Перезапускает прибор. Сессию калибровки после этого нужно запустить заново"
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
                    color: root.appController ? root.appController.trialStatusColor : "#64748b"
                }

                Text {
                    Layout.fillWidth: true
                    text: root.appController ? root.appController.trialStatusText : "Контроллер недоступен"
                    color: root.appController ? root.appController.trialStatusColor : "#64748b"
                    font.pixelSize: 13
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }
        }
    }
}
