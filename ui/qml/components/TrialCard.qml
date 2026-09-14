import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Раздел пробной калибровки на столе.
  Назначение:
  - проходит весь порядок калибровки до выезда в климатическую камеру;
  - плата подключена к шине, контуры нагружены внешними конденсаторами,
    а температуру прибору задаёт эмуляция в самой прошивке;
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
                    text: "Плата на шине, контуры нагружены конденсаторами, температуру задаёт эмуляция в самом приборе"
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

                TrialStepCard {
                    readonly property var row: root.stepRow("link")
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
                        Layout.preferredWidth: 130
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Проверить"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        enabled: root.ready
                        onClicked: root.appController.runTrialStep("link")
                    }
                }

                TrialStepCard {
                    readonly property var row: root.stepRow("access")
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
                        Layout.preferredWidth: 130
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Проверить"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        enabled: root.ready
                        onClicked: root.appController.runTrialStep("access")
                    }
                }

                TrialStepCard {
                    readonly property var row: root.stepRow("emulation")
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
                        Layout.preferredWidth: 130
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Проверить"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        enabled: root.ready
                        onClicked: root.appController.runTrialStep("emulation")
                    }
                }

                TrialStepCard {
                    readonly property var row: root.stepRow("level")
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
                        Layout.preferredWidth: 140
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Снять пустой"
                        tone: "#64748b"
                        toneHover: "#475569"
                        tonePressed: "#334155"
                        enabled: root.ready
                        onClicked: root.appController.trialCaptureLevel("empty")
                    }

                    FancyButton {
                        Layout.preferredWidth: 140
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Снять полный"
                        tone: "#64748b"
                        toneHover: "#475569"
                        tonePressed: "#334155"
                        enabled: root.ready
                        onClicked: root.appController.trialCaptureLevel("full")
                    }

                    FancyButton {
                        Layout.preferredWidth: 180
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Записать и проверить"
                        tone: "#16a34a"
                        toneHover: "#15803d"
                        tonePressed: "#166534"
                        enabled: root.ready
                        onClicked: root.appController.trialWriteLevel()
                    }
                }

                TrialStepCard {
                    readonly property var row: root.stepRow("media")
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
                        Layout.preferredWidth: 140
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Снять воздух"
                        tone: "#64748b"
                        toneHover: "#475569"
                        tonePressed: "#334155"
                        enabled: root.ready
                        onClicked: root.appController.trialCaptureMedia("air")
                    }

                    FancyButton {
                        Layout.preferredWidth: 140
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Снять топливо"
                        tone: "#64748b"
                        toneHover: "#475569"
                        tonePressed: "#334155"
                        enabled: root.ready
                        onClicked: root.appController.trialCaptureMedia("fuel")
                    }

                    FancyButton {
                        Layout.preferredWidth: 180
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Записать и проверить"
                        tone: "#16a34a"
                        toneHover: "#15803d"
                        tonePressed: "#166534"
                        enabled: root.ready
                        onClicked: root.appController.trialWriteMedia()
                    }
                }

                TrialStepCard {
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

                    Text {
                        text: "Эталон 1, пФ"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        Layout.alignment: Qt.AlignVCenter
                    }

                    FancyTextField {
                        id: ref1Field
                        Layout.preferredWidth: 80
                        Layout.preferredHeight: 30
                        text: root.appController ? root.appController.trialChamberRef1Text : "300"
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        onEditingFinished: if (root.appController) root.appController.setTrialChamberRefs(ref1Field.text, ref2Field.text)
                    }

                    Text {
                        text: "Эталон 2, пФ"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        Layout.alignment: Qt.AlignVCenter
                    }

                    FancyTextField {
                        id: ref2Field
                        Layout.preferredWidth: 80
                        Layout.preferredHeight: 30
                        text: root.appController ? root.appController.trialChamberRef2Text : "600"
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        onEditingFinished: if (root.appController) root.appController.setTrialChamberRefs(ref1Field.text, ref2Field.text)
                    }

                    FancyButton {
                        Layout.preferredWidth: 130
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Начать прогон"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        toolTipText: "Очищает журнал прогона и строит список из 22 точек по семи температурам"
                        enabled: root.ready
                        onClicked: {
                            root.appController.setTrialChamberRefs(ref1Field.text, ref2Field.text)
                            root.appController.trialChamberStart()
                        }
                    }

                    FancyButton {
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Снять эту точку"
                        tone: "#16a34a"
                        toneHover: "#15803d"
                        tonePressed: "#166534"
                        enabled: root.ready
                        onClicked: root.appController.trialChamberCaptureNext()
                    }

                    FancyButton {
                        Layout.preferredWidth: 160
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Посчитать таблицы"
                        tone: "#7c3aed"
                        toneHover: "#6d28d9"
                        tonePressed: "#5b21b6"
                        enabled: root.ready
                        onClicked: root.appController.trialChamberCompute()
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

                TrialStepCard {
                    readonly property var row: root.stepRow("profile")
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
                        Layout.preferredWidth: 180
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Записать и сверить"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        enabled: root.ready
                        onClicked: root.appController.runTrialStep("profile")
                    }
                }

                TrialStepCard {
                    readonly property var row: root.stepRow("apply")
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
                        Layout.preferredWidth: 200
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Проверить применение"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        enabled: root.ready
                        onClicked: root.appController.runTrialStep("apply")
                    }
                }

                TrialStepCard {
                    readonly property var row: root.stepRow("persist")
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
                        Layout.preferredWidth: 230
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Перезапустить и проверить"
                        tone: "#b45309"
                        toneHover: "#92400e"
                        tonePressed: "#78350f"
                        toolTipText: "Перезапускает прибор. Сессию калибровки после этого нужно запустить заново"
                        enabled: root.ready
                        onClicked: root.appController.runTrialStep("persist")
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
