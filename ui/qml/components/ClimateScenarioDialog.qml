import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import "."

/*
  Форма сценария автоматического прогона в климатической камере.
  Назначение:
  - общие настройки сценария: «только плата» и модель ухода, пометки, автозапись
    профиля, критерии по умолчанию, когда предупреждать, что делать в конце;
  - шаги по порядку: температура и, по желанию, свои выдержка, окно и скорость
    устойчивости, допуск, «снимать ли точку», примечание; добавить, удалить, сдвинуть;
  - файлы: новый (пустой или «Испытание платы, один цикл»), открыть, сохранить,
    сохранить как, список сохранённых в папке scenarios.

  Форма правит свою копию сценария и после каждой правки отдаёт её контроллеру
  целиком; контроллер проверяет значения и показывает замечания. Перечитывается
  копия только при загрузке или создании сценария (растёт ревизия).

  Публичные свойства:
  - appController: контроллер приложения;
  - view: сценарий из контроллера (climate.scenario);
  - textMain/textSoft/inputBg/inputBorder/inputFocus: палитра окна.
*/
Popup {
    id: dialog

    property var appController
    property var view: ({})
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f6faff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"

    // Копия сценария, которую правит форма, и счётчик её перестроений.
    property var draft: ({ "steps": [] })
    property int draftRevision: 0
    property int loadedRevision: -1
    readonly property bool locked: dialog.view.locked === true

    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape
    anchors.centerIn: Overlay.overlay
    width: Math.min(1400, (Overlay.overlay ? Overlay.overlay.width : 1400) - 40)
    height: Math.min(860, (Overlay.overlay ? Overlay.overlay.height : 900) - 60)
    padding: 0

    background: Rectangle {
        radius: 14
        color: "#ffffff"
        border.width: 1
        border.color: "#c6dcf5"
    }

    // Копия сценария из контроллера: при открытии и после загрузки или создания.
    function reload() {
        if (!dialog.view.scenario)
            return
        dialog.draft = JSON.parse(JSON.stringify(dialog.view.scenario))
        dialog.loadedRevision = dialog.view.revision
        dialog.draftRevision += 1
    }

    // Правка уходит в контроллер целиком: он проверит значения и сохранит текущий сценарий.
    function push() {
        if (dialog.appController && !dialog.locked)
            dialog.appController.updateClimateScenario(JSON.stringify(dialog.draft))
    }

    // Число из поля: пустое поле - null («как в общем»), запятая как точка.
    function num(text) {
        var cleaned = String(text).trim().replace(",", ".")
        return cleaned.length > 0 ? Number(cleaned) : null
    }

    function show(value) {
        return value === null || value === undefined ? "" : String(value).replace(".", ",")
    }

    function addStep() {
        var steps = dialog.draft.steps || []
        var last = steps.length > 0 ? steps[steps.length - 1].temp : 25
        steps.push({ "temp": last, "hold_min": 0, "settle_min": null, "settle_rate": null,
                     "reach_tolerance_c": null, "capture": true, "note": "" })
        dialog.draft.steps = steps
        dialog.draftRevision += 1
        dialog.push()
    }

    function removeStep(index) {
        dialog.draft.steps.splice(index, 1)
        dialog.draftRevision += 1
        dialog.push()
    }

    function moveStep(index, delta) {
        var steps = dialog.draft.steps
        var other = index + delta
        if (other < 0 || other >= steps.length)
            return
        var item = steps[index]
        steps[index] = steps[other]
        steps[other] = item
        dialog.draftRevision += 1
        dialog.push()
    }

    onOpened: dialog.reload()
    onViewChanged: if (dialog.opened && dialog.view.revision !== undefined && dialog.view.revision !== dialog.loadedRevision)
                       dialog.reload()
    onClosed: dialog.push()

    component Caption: Text {
        color: dialog.textSoft
        font.pixelSize: 12
        font.family: "Bahnschrift"
        Layout.alignment: Qt.AlignVCenter
    }

    component SectionTitle: Text {
        color: dialog.textMain
        font.pixelSize: 14
        font.bold: true
        font.family: "Bahnschrift"
    }

    component Field: FancyTextField {
        Layout.preferredHeight: 30
        Layout.minimumWidth: 50
        implicitWidth: 80
        textColor: dialog.textMain
        bgColor: dialog.inputBg
        borderColor: dialog.inputBorder
        focusBorderColor: dialog.inputFocus
        enabled: !dialog.locked
    }

    component SmallButton: FancyButton {
        Layout.preferredHeight: 30
        fontPixelSize: 12
        tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
    }

    // Общее числовое поле сценария: правка сразу в копию, в контроллер - по завершении ввода.
    component GeneralNumber: Field {
        id: generalField
        property string key: ""
        property bool optional: false
        Layout.preferredWidth: 70
        horizontalAlignment: TextInput.AlignHCenter
        text: dialog.draftRevision >= 0 ? dialog.show(dialog.draft[generalField.key]) : ""
        onTextEdited: dialog.draft[generalField.key] = dialog.num(text)
        onEditingFinished: dialog.push()
    }

    FileDialog {
        id: openDialog
        title: "Открыть сценарий прогона"
        currentFolder: dialog.view.folderUrl || ""
        nameFilters: ["Сценарий прогона (*.json)", "Все файлы (*)"]
        onAccepted: if (dialog.appController) dialog.appController.loadClimateScenario(selectedFile.toString())
    }

    FileDialog {
        id: saveDialog
        title: "Сохранить сценарий прогона"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "json"
        currentFolder: dialog.view.folderUrl || ""
        nameFilters: ["Сценарий прогона (*.json)", "Все файлы (*)"]
        onAccepted: {
            dialog.push()
            if (dialog.appController) dialog.appController.saveClimateScenario(selectedFile.toString())
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        // --- Шапка: название, файл, закрыть ---
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Text {
                text: "Сценарий прогона"
                color: dialog.textMain
                font.pixelSize: 19
                font.bold: true
                font.family: "Bahnschrift"
            }

            Text {
                Layout.fillWidth: true
                text: (dialog.view.fileName ? "файл " + dialog.view.fileName : "ещё не сохранён в файл")
                      + (dialog.view.dirty ? "  ·  есть несохранённые изменения" : "")
                color: dialog.view.dirty ? "#b45309" : dialog.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                elide: Text.ElideMiddle
            }

            SmallButton {
                Layout.preferredWidth: 100
                text: "Закрыть"
                onClicked: dialog.close()
            }
        }

        Text {
            Layout.fillWidth: true
            visible: dialog.locked
            text: "Идёт прогон: он идёт по сценарию, с которым начат. Менять сценарий можно после окончания или остановки."
            color: "#b45309"
            font.pixelSize: 12
            font.bold: true
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
        }

        // --- Файлы ---
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            SmallButton {
                Layout.preferredWidth: 230
                text: "Новый: испытание платы, один цикл"
                tone: "#0f766e"; toneHover: "#115e59"; tonePressed: "#134e4a"
                enabled: !dialog.locked
                onClicked: if (dialog.appController) dialog.appController.newClimateScenario("board_cycle")
            }
            SmallButton {
                Layout.preferredWidth: 120
                text: "Новый пустой"
                enabled: !dialog.locked
                onClicked: if (dialog.appController) dialog.appController.newClimateScenario("empty")
            }
            SmallButton {
                Layout.preferredWidth: 120
                text: "Открыть файл…"
                enabled: !dialog.locked
                onClicked: openDialog.open()
            }
            SmallButton {
                Layout.preferredWidth: 110
                text: "Сохранить"
                tone: "#16a34a"; toneHover: "#15803d"; tonePressed: "#166534"
                toolTipText: "В свой файл, а если его нет - в папку сценариев по названию"
                onClicked: {
                    dialog.push()
                    if (dialog.appController) dialog.appController.saveClimateScenario("")
                }
            }
            SmallButton {
                Layout.preferredWidth: 140
                text: "Сохранить как…"
                onClicked: saveDialog.open()
            }
            Text {
                Layout.fillWidth: true
                text: dialog.view.status || ""
                color: dialog.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                elide: Text.ElideRight
            }
        }

        // Сохранённые сценарии в папке: нажатие загружает.
        Flow {
            Layout.fillWidth: true
            spacing: 6

            Text {
                text: "Сохранённые:"
                color: dialog.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                height: 26
                verticalAlignment: Text.AlignVCenter
            }

            Repeater {
                model: dialog.view.files || []

                FancyButton {
                    required property var modelData
                    width: Math.min(320, 30 + 7 * modelData.name.length)
                    height: 26
                    fontPixelSize: 11
                    text: modelData.name
                    toolTipText: modelData.path
                    tone: modelData.path === dialog.view.path ? "#0f766e" : "#94a3b8"
                    toneHover: "#115e59"; tonePressed: "#134e4a"
                    enabled: !dialog.locked
                    onClicked: if (dialog.appController) dialog.appController.loadClimateScenario(modelData.path)
                }
            }

            FancyButton {
                width: 90
                height: 26
                fontPixelSize: 11
                text: "Обновить"
                tone: "#cbd5e1"; toneHover: "#94a3b8"; tonePressed: "#64748b"
                onClicked: if (dialog.appController) dialog.appController.refreshClimateScenarios()
            }
        }

        ScrollView {
            id: bodyScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                width: bodyScroll.availableWidth
                spacing: 10

                // --- Название и описание ---
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Caption { text: "Название" }
                    Field {
                        Layout.preferredWidth: 340
                        text: dialog.draftRevision >= 0 ? (dialog.draft.name || "") : ""
                        onTextEdited: dialog.draft.name = text
                        onEditingFinished: dialog.push()
                    }
                    Caption { text: "Описание" }
                    Field {
                        Layout.fillWidth: true
                        text: dialog.draftRevision >= 0 ? (dialog.draft.description || "") : ""
                        placeholderText: "что за испытание и для какой платы"
                        onTextEdited: dialog.draft.description = text
                        onEditingFinished: dialog.push()
                    }
                }

                // --- Общее ---
                SectionTitle { text: "Общее" }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    FancySwitch {
                        checked: dialog.draftRevision >= 0 && dialog.draft.board_only === true
                        enabled: !dialog.locked
                        onToggled: { dialog.draft.board_only = checked; dialog.push() }
                    }
                    Caption { text: "Только плата, своя ёмкость (без эталонов и трубки)" }

                    Caption { text: "   уход считать как" }
                    Repeater {
                        model: ["растяжение", "сдвиг"]
                        SmallButton {
                            required property string modelData
                            Layout.preferredWidth: 110
                            text: modelData
                            enabled: !dialog.locked
                            tone: dialog.draftRevision >= 0 && dialog.draft.single_model === modelData ? "#0284c7" : "#94a3b8"
                            toneHover: "#0369a1"; tonePressed: "#075985"
                            onClicked: { dialog.draft.single_model = modelData; dialog.draftRevision += 1; dialog.push() }
                        }
                    }

                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Caption { text: "Пометки (что подключено) через «;»" }
                    Field {
                        Layout.preferredWidth: 220
                        text: dialog.draftRevision >= 0 ? (dialog.draft.labels || []).join("; ") : ""
                        placeholderText: "0/0 или 0/0; 68/22; 150/47"
                        onTextEdited: dialog.draft.labels = text.split(";").map(function (part) { return part.trim() })
                                                                .filter(function (part) { return part.length > 0 })
                        onEditingFinished: dialog.push()
                    }

                    FancySwitch {
                        checked: dialog.draftRevision >= 0 && dialog.draft.auto_write === true
                        enabled: !dialog.locked
                        onToggled: { dialog.draft.auto_write = checked; dialog.push() }
                    }
                    Caption { text: "автозапись профиля" }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Caption { text: "По умолчанию для шагов:  выход на уставку ±, °C" }
                    GeneralNumber { key: "reach_tolerance_c" }
                    Caption { text: "   плата устоялась: за, мин" }
                    GeneralNumber { key: "settle_min" }
                    Caption { text: "медленнее, °C/мин" }
                    GeneralNumber { key: "settle_rate" }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Caption { text: "Предупредить, если камера не вышла на уставку за, мин" }
                    GeneralNumber { key: "reach_timeout_min" }
                    Caption { text: "   плата не устоялась за, мин" }
                    GeneralNumber { key: "settle_timeout_min" }
                    Caption { text: "   В конце задать камере, °C" }
                    GeneralNumber { key: "finish_setpoint"; optional: true; placeholderText: "не менять" }
                    FancySwitch {
                        checked: dialog.draftRevision >= 0 && dialog.draft.finish_stop === true
                        enabled: !dialog.locked
                        onToggled: { dialog.draft.finish_stop = checked; dialog.push() }
                    }
                    Caption { text: "и остановить камеру" }
                    Item { Layout.fillWidth: true }
                }

                // --- Шаги ---
                RowLayout {
                    Layout.fillWidth: true
                    SectionTitle { text: "Шаги по порядку" }
                    Caption { text: "   пустое поле шага - как в общем; «Точка» выключена - шаг без точки (например, прогрев)" }
                    Item { Layout.fillWidth: true }
                }

                // Таблица шагов: у заголовка и строк одни и те же ширины колонок.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Caption { text: "№"; Layout.preferredWidth: 28 }
                    Caption { text: "Температура, °C"; Layout.preferredWidth: 96 }
                    Caption { text: "Выдержка, мин"; Layout.preferredWidth: 86 }
                    Caption { text: "Устоялась за, мин"; Layout.preferredWidth: 104 }
                    Caption { text: "медленнее, °C/мин"; Layout.preferredWidth: 104 }
                    Caption { text: "Допуск ±, °C"; Layout.preferredWidth: 86 }
                    Caption { text: "Точка"; Layout.preferredWidth: 56 }
                    Caption { text: "Примечание"; Layout.fillWidth: true }
                    Item { Layout.preferredWidth: 3 * 34 + 2 * 6 }
                }

                Repeater {
                    model: dialog.draftRevision >= 0 ? (dialog.draft.steps || []).length : 0

                    RowLayout {
                        id: stepRow
                        required property int index
                        readonly property var step: dialog.draft.steps[stepRow.index] || ({})
                        Layout.fillWidth: true
                        spacing: 6

                        Text {
                            Layout.preferredWidth: 28
                            text: (stepRow.index + 1) + "."
                            color: dialog.textMain
                            font.pixelSize: 13
                            font.family: "Bahnschrift"
                        }
                        Field {
                            Layout.preferredWidth: 96
                            horizontalAlignment: TextInput.AlignHCenter
                            text: dialog.show(stepRow.step.temp)
                            onTextEdited: dialog.draft.steps[stepRow.index].temp = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Field {
                            Layout.preferredWidth: 86
                            horizontalAlignment: TextInput.AlignHCenter
                            text: stepRow.step.hold_min ? dialog.show(stepRow.step.hold_min) : ""
                            placeholderText: "0"
                            onTextEdited: dialog.draft.steps[stepRow.index].hold_min = dialog.num(text) || 0
                            onEditingFinished: dialog.push()
                        }
                        Field {
                            Layout.preferredWidth: 104
                            horizontalAlignment: TextInput.AlignHCenter
                            text: dialog.show(stepRow.step.settle_min)
                            placeholderText: "общее " + dialog.show(dialog.draft.settle_min)
                            onTextEdited: dialog.draft.steps[stepRow.index].settle_min = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Field {
                            Layout.preferredWidth: 104
                            horizontalAlignment: TextInput.AlignHCenter
                            text: dialog.show(stepRow.step.settle_rate)
                            placeholderText: "общее " + dialog.show(dialog.draft.settle_rate)
                            onTextEdited: dialog.draft.steps[stepRow.index].settle_rate = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Field {
                            Layout.preferredWidth: 86
                            horizontalAlignment: TextInput.AlignHCenter
                            text: dialog.show(stepRow.step.reach_tolerance_c)
                            placeholderText: "общее " + dialog.show(dialog.draft.reach_tolerance_c)
                            onTextEdited: dialog.draft.steps[stepRow.index].reach_tolerance_c = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Item {
                            Layout.preferredWidth: 56
                            Layout.preferredHeight: 30
                            FancySwitch {
                                anchors.verticalCenter: parent.verticalCenter
                                checked: stepRow.step.capture !== false
                                enabled: !dialog.locked
                                onToggled: { dialog.draft.steps[stepRow.index].capture = checked; dialog.push() }
                            }
                        }
                        Field {
                            Layout.fillWidth: true
                            text: stepRow.step.note || ""
                            onTextEdited: dialog.draft.steps[stepRow.index].note = text
                            onEditingFinished: dialog.push()
                        }
                        SmallButton {
                            Layout.preferredWidth: 34
                            text: "↑"
                            enabled: !dialog.locked && stepRow.index > 0
                            onClicked: dialog.moveStep(stepRow.index, -1)
                        }
                        SmallButton {
                            Layout.preferredWidth: 34
                            text: "↓"
                            enabled: !dialog.locked && stepRow.index < (dialog.draft.steps || []).length - 1
                            onClicked: dialog.moveStep(stepRow.index, 1)
                        }
                        SmallButton {
                            Layout.preferredWidth: 34
                            text: "✕"
                            tone: "#ef4444"; toneHover: "#dc2626"; tonePressed: "#b91c1c"
                            enabled: !dialog.locked && (dialog.draft.steps || []).length > 1
                            onClicked: dialog.removeStep(stepRow.index)
                        }
                    }
                }

                SmallButton {
                    Layout.preferredWidth: 160
                    text: "+ Добавить шаг"
                    tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                    enabled: !dialog.locked
                    onClicked: dialog.addStep()
                }

                // --- Итог и замечания проверки ---
                Text {
                    Layout.fillWidth: true
                    text: "Итого: " + (dialog.view.summary || "")
                    color: dialog.textMain
                    font.pixelSize: 13
                    font.bold: true
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                Repeater {
                    model: dialog.view.problems || []
                    Text {
                        required property string modelData
                        Layout.fillWidth: true
                        text: "⚠ " + modelData
                        color: "#b45309"
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Сценарии хранятся в папке " + (dialog.view.folder || "scenarios") + ". Прогон берёт сценарий, "
                          + "открытый здесь; при старте режим «только плата», пометка и автозапись переносятся в «Прогон в камере»."
                    color: dialog.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}
