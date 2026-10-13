import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import "."

/*
  Форма сценария автоматического прогона в климатической камере.

  Разделы сверху вниз, в каждом строки «что - значение - пояснение» с одинаковыми
  колонками:
  1. Сценарий: название и описание.
  2. Что испытываем: одна плата на своих ёмкостях или эталоны и трубка; как
     пересчитывать уход платы; что подключено (только для эталонов); запись профиля.
  3. Правила для всех шагов: когда камера вышла на уставку, когда плата
     устоялась, когда предупреждать о зависании.
  4. В конце: что сделать с камерой.
  5. Шаги по порядку: подсказка, как их настраивать, и таблица шагов с колонкой
     «Узел прибора» - в какой узел сетки попадёт точка шага; ниже проверка
     полноты сетки.

  Форма правит свою копию сценария и после каждой правки отдаёт её контроллеру
  целиком; контроллер проверяет значения и показывает замечания. Копия
  перечитывается только при загрузке или создании сценария (растёт ревизия).

  Во время прогона сценарий тоже правится, но правки копятся и уходят к идущему
  прогону кнопкой «Применить к прогону» (с записью в журнал действий):
  пройденные шаги закрыты, текущий правится, но не удаляется и не двигается;
  режим испытания (раздел 2) во время прогона не меняется.

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
    // Пересчёт проверки сетки после правки температуры шага (строки при этом не перестраиваются).
    property int checkTick: 0
    readonly property bool locked: dialog.view.locked === true
    // Идущий шаг прогона (-1 - прогон не идёт) и есть ли неприменённые правки к идущему прогону.
    readonly property int runIndex: dialog.view.runIndex !== undefined ? dialog.view.runIndex : -1
    property bool pending: false
    readonly property bool boardOnly: dialog.draftRevision >= 0 && dialog.draft.board_only === true

    // Сетка температурных узлов прибора и допуск попадания точки в узел (по температуре платы).
    readonly property var gridNodes: [-40, -20, 0, 25, 50, 70, 85]
    readonly property real gridTolerance: 3.0

    // Ширины колонок формы: подпись, значение, пояснение тянется.
    readonly property int labelWidth: 330
    readonly property int valueWidth: 330

    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape
    anchors.centerIn: Overlay.overlay
    width: Math.min(1400, (Overlay.overlay ? Overlay.overlay.width : 1400) - 40)
    height: Math.min(900, (Overlay.overlay ? Overlay.overlay.height : 900) - 40)
    padding: 0

    background: Rectangle {
        radius: 14
        color: "#f8fafc"
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
        dialog.pending = false
    }

    // Во время прогона шаг правится, если он не пройден; двигать и удалять можно только будущие.
    function stepEditable(index) {
        return !dialog.locked || index >= dialog.runIndex
    }
    function stepMovable(index) {
        return !dialog.locked || index > dialog.runIndex
    }

    // Правка уходит в контроллер целиком: он проверит значения и сохранит текущий сценарий.
    function push() {
        if (dialog.locked) {
            // Идёт прогон: правка копится до «Применить к прогону».
            dialog.pending = true
            return
        }
        if (dialog.appController)
            dialog.appController.updateClimateScenario(JSON.stringify(dialog.draft))
    }

    // Правка, после которой форма перестраивается (переключатели, кнопки, шаги).
    function change(key, value) {
        dialog.draft[key] = value
        dialog.draftRevision += 1
        dialog.push()
    }

    // Число из поля: пустое поле - null («как в общих правилах»), запятая как точка.
    function num(text) {
        var cleaned = String(text).trim().replace(",", ".")
        return cleaned.length > 0 ? Number(cleaned) : null
    }

    function show(value) {
        return value === null || value === undefined ? "" : String(value).replace(".", ",")
    }

    // Узел прибора, в который попадёт точка при этой температуре, или null.
    function gridNode(temp) {
        if (temp === null || temp === undefined || isNaN(temp))
            return null
        var best = dialog.gridNodes[0]
        for (var i = 1; i < dialog.gridNodes.length; ++i)
            if (Math.abs(dialog.gridNodes[i] - temp) < Math.abs(best - temp))
                best = dialog.gridNodes[i]
        return Math.abs(best - temp) <= dialog.gridTolerance ? best : null
    }

    function nodeText(node) {
        return (node > 0 ? "+" : "") + node + " °C"
    }

    // Проверка сетки по шагам с точкой: опорный +25 и все 7 узлов.
    function gridCheck() {
        var revision = dialog.draftRevision + dialog.checkTick
        var covered = {}
        var outside = []
        var steps = dialog.draft.steps || []
        for (var i = 0; i < steps.length; ++i) {
            if (steps[i].capture === false)
                continue
            var node = dialog.gridNode(steps[i].temp)
            if (node === null)
                outside.push(steps[i].temp)
            else
                covered[node] = true
        }
        var missing = dialog.gridNodes.filter(function (node) { return !covered[node] })
        return { "reference": covered[25] === true, "missing": missing, "outside": outside }
    }

    function addStep() {
        var steps = dialog.draft.steps || []
        var last = steps.length > 0 ? steps[steps.length - 1].temp : 25
        steps.push({ "temp": last, "hold_min": 0, "settle_min": null, "settle_rate": null,
                     "reach_tolerance_c": null, "capture": true, "note": "" })
        dialog.change("steps", steps)
    }

    function removeStep(index) {
        dialog.draft.steps.splice(index, 1)
        dialog.change("steps", dialog.draft.steps)
    }

    function moveStep(index, delta) {
        var steps = dialog.draft.steps
        var other = index + delta
        if (other < 0 || other >= steps.length)
            return
        var item = steps[index]
        steps[index] = steps[other]
        steps[other] = item
        dialog.change("steps", steps)
    }

    onOpened: dialog.reload()
    onViewChanged: if (dialog.opened && dialog.view.revision !== undefined && dialog.view.revision !== dialog.loadedRevision)
                       dialog.reload()
    onClosed: dialog.push()

    // ------------------------------------------------------------------ элементы формы

    component Soft: Text {
        color: dialog.textSoft
        font.pixelSize: 11
        font.family: "Bahnschrift"
        wrapMode: Text.WordWrap
    }

    component Field: FancyTextField {
        Layout.preferredHeight: 30
        Layout.minimumWidth: 50
        implicitWidth: 80
        textColor: dialog.textMain
        bgColor: dialog.inputBg
        borderColor: dialog.inputBorder
        focusBorderColor: dialog.inputFocus
        onTextChanged: if (!activeFocus) cursorPosition = 0
    }

    component NumberField: Field {
        Layout.preferredWidth: 72
        horizontalAlignment: TextInput.AlignHCenter
    }

    component SmallButton: FancyButton {
        Layout.preferredHeight: 30
        fontPixelSize: 12
        tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
    }

    // Кнопка выбора из нескольких: выбранная подсвечена.
    component Choice: FancyButton {
        property bool selected: false
        Layout.preferredHeight: 30
        fontPixelSize: 12
        enabled: !dialog.locked
        tone: selected ? "#0f766e" : "#94a3b8"
        toneHover: selected ? "#115e59" : "#64748b"
        tonePressed: "#134e4a"
    }

    // Раздел-карточка: заголовок со знаком «i», строки.
    component Section: Rectangle {
        id: section
        property string title: ""
        property string hint: ""
        default property alias content: sectionBody.data
        Layout.fillWidth: true
        Layout.preferredHeight: sectionLayout.implicitHeight + 24
        radius: 10
        color: "#ffffff"
        border.width: 1
        border.color: "#e2e8f0"

        ColumnLayout {
            id: sectionLayout
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Text {
                    text: section.title
                    color: dialog.textMain
                    font.pixelSize: 15
                    font.bold: true
                    font.family: "Bahnschrift"
                }
                InfoMark { tip: section.hint }
                Item { Layout.fillWidth: true }
            }

            ColumnLayout {
                id: sectionBody
                Layout.fillWidth: true
                spacing: 8
            }
        }
    }

    // Строка формы: подпись со знаком «i» - значение (поля и кнопки).
    component FormRow: RowLayout {
        id: formRow
        property string label: ""
        property string hint: ""
        default property alias value: valueBox.data
        Layout.fillWidth: true
        spacing: 12

        RowLayout {
            Layout.preferredWidth: dialog.labelWidth
            Layout.maximumWidth: dialog.labelWidth
            Layout.alignment: Qt.AlignVCenter
            spacing: 6

            Text {
                Layout.fillWidth: true
                text: formRow.label
                color: dialog.textMain
                font.pixelSize: 12
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }
            InfoMark { tip: formRow.hint }
        }

        RowLayout {
            id: valueBox
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 6
        }
    }

    // ------------------------------------------------------------------ файлы

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

        // --- Шапка: название формы, файл, закрыть ---
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

        // --- Файлы: новый, открыть, сохранить; сохранённые в папке ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: filesLayout.implicitHeight + 20
            radius: 10
            color: "#ffffff"
            border.width: 1
            border.color: "#e2e8f0"

            ColumnLayout {
                id: filesLayout
                anchors.fill: parent
                anchors.margins: 10
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        Layout.preferredWidth: 90
                        text: "Новый"
                        color: dialog.textMain
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                    }
                    SmallButton {
                        Layout.preferredWidth: 230
                        text: "Испытание платы, один цикл"
                        tone: "#0f766e"; toneHover: "#115e59"; tonePressed: "#134e4a"
                        enabled: !dialog.locked
                        onClicked: if (dialog.appController) dialog.appController.newClimateScenario("board_cycle")
                    }
                    SmallButton {
                        Layout.preferredWidth: 110
                        text: "Пустой"
                        enabled: !dialog.locked
                        onClicked: if (dialog.appController) dialog.appController.newClimateScenario("empty")
                    }

                    Item { Layout.preferredWidth: 24 }

                    Text {
                        text: "Файл"
                        color: dialog.textMain
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                    }
                    SmallButton {
                        Layout.preferredWidth: 110
                        text: "Открыть…"
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
                        Layout.preferredWidth: 130
                        text: "Сохранить как…"
                        onClicked: saveDialog.open()
                    }
                    Soft {
                        Layout.fillWidth: true
                        text: dialog.view.status || ""
                        elide: Text.ElideRight
                        wrapMode: Text.NoWrap
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    RowLayout {
                        Layout.preferredWidth: 90
                        spacing: 4
                        Text {
                            text: "Сохранённые"
                            color: dialog.textMain
                            font.pixelSize: 12
                            font.bold: true
                            font.family: "Bahnschrift"
                        }
                        InfoMark {
                            tip: "Сценарии хранятся в папке " + (dialog.view.folder || "scenarios") + ". Нажатие загружает сценарий. "
                                 + "Прогон идёт по сценарию, открытому здесь; при старте режим, уход платы и запись профиля "
                                 + "переносятся в «Прогон в камере»."
                        }
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 6

                        Repeater {
                            model: dialog.view.files || []

                            FancyButton {
                                required property var modelData
                                width: Math.min(320, 30 + 7 * modelData.name.length)
                                height: 28
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
                            height: 28
                            fontPixelSize: 11
                            text: "Обновить"
                            tone: "#cbd5e1"; toneHover: "#94a3b8"; tonePressed: "#64748b"
                            onClicked: if (dialog.appController) dialog.appController.refreshClimateScenarios()
                        }
                    }
                }
            }
        }

        // Идёт прогон: правки копятся и применяются к нему одной кнопкой.
        RowLayout {
            Layout.fillWidth: true
            visible: dialog.locked
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: "Идёт прогон, шаг " + (dialog.runIndex + 1) + ". Правки применятся к нему кнопкой «Применить к прогону»: "
                      + "пройденные шаги не меняются, текущий можно поправить (новая температура - шаг заново), "
                      + "режим испытания не меняется. Действие записывается в журнал."
                color: "#b45309"
                font.pixelSize: 12
                font.bold: true
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }
            SmallButton {
                Layout.preferredWidth: 170
                text: "Применить к прогону"
                enabled: dialog.pending
                tone: "#b45309"; toneHover: "#92400e"; tonePressed: "#78350f"
                onClicked: {
                    if (dialog.appController)
                        dialog.appController.applyClimateScenarioLive(JSON.stringify(dialog.draft))
                    dialog.pending = false
                }
            }
            SmallButton {
                Layout.preferredWidth: 130
                text: "Отменить правки"
                enabled: dialog.pending
                onClicked: dialog.reload()
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
                width: bodyScroll.availableWidth - 12
                spacing: 10

                // --- 1. Сценарий ---
                Section {
                    title: "1. Сценарий"

                    FormRow {
                        label: "Название"
                        Field {
                            Layout.fillWidth: true
                            text: dialog.draftRevision >= 0 ? (dialog.draft.name || "") : ""
                            onTextEdited: dialog.draft.name = text
                            onEditingFinished: dialog.push()
                        }
                    }

                    FormRow {
                        label: "Описание"
                        Field {
                            Layout.fillWidth: true
                            text: dialog.draftRevision >= 0 ? (dialog.draft.description || "") : ""
                            onTextEdited: dialog.draft.description = text
                            onEditingFinished: dialog.push()
                        }
                    }
                }

                // --- 2. Что испытываем ---
                Section {
                    title: "2. Что испытываем"

                    FormRow {
                        label: "Режим"
                        hint: dialog.boardOnly
                              ? "Одна плата, к входам ничего не подключено: в каждом узле одна точка на своей ёмкости платы (пометка «0/0» ставится сама). Наш случай."
                              : "К прибору по очереди подключают эталонные ёмкости и трубку: в каждом узле по точке на каждый эталон."
                        Choice {
                            Layout.preferredWidth: 160
                            text: "Одна плата"
                            selected: dialog.boardOnly
                            onClicked: dialog.change("board_only", true)
                        }
                        Choice {
                            Layout.preferredWidth: 160
                            text: "Эталоны и трубка"
                            selected: !dialog.boardOnly
                            onClicked: dialog.change("board_only", false)
                        }
                    }

                    FormRow {
                        visible: dialog.boardOnly
                        label: "Как пересчитывать уход платы с температурой"
                        hint: "По одной ёмкости не различить, какая часть ухода пропорциональна показанию, а какая постоянна, - весь уход "
                              + "приписывается одному виду. «Растяжение»: ёмкости на плате стабильные (C0G/NP0), плывут резисторы и "
                              + "пороги - ошибка пропорциональна показанию. «Сдвиг»: плывёт сама ёмкость (X7R) - постоянная добавка. "
                              + "При ёмкости самой платы оба дают одно и то же; разница - только с подключённой трубкой."
                        Choice {
                            Layout.preferredWidth: 160
                            text: "Растяжение"
                            selected: dialog.draftRevision >= 0 && dialog.draft.single_model === "растяжение"
                            onClicked: dialog.change("single_model", "растяжение")
                        }
                        Choice {
                            Layout.preferredWidth: 160
                            text: "Сдвиг"
                            selected: dialog.draftRevision >= 0 && dialog.draft.single_model === "сдвиг"
                            onClicked: dialog.change("single_model", "сдвиг")
                        }
                    }

                    FormRow {
                        visible: !dialog.boardOnly
                        label: "Что подключено (эталоны основной/вид топлива, пФ)"
                        hint: "Через «;», например «0/0; 68/22; 150/47». Если эталонов несколько, в каждом узле программа попросит "
                              + "оператора переключить их и снимет точку с каждым. Один эталон - оператор не нужен."
                        Field {
                            Layout.fillWidth: true
                            text: dialog.draftRevision >= 0 ? (dialog.draft.labels || []).join("; ") : ""
                            placeholderText: "0/0; 68/22; 150/47"
                            onTextEdited: dialog.draft.labels = text.split(";").map(function (part) { return part.trim() })
                                                                    .filter(function (part) { return part.length > 0 })
                            onEditingFinished: dialog.push()
                        }
                    }

                    FormRow {
                        label: "Записать профиль в прибор"
                        hint: "Когда данных хватит во всех 7 узлах, программа сама откроет запись, запишет таблицы, сверит их и сохранит профиль в файл."
                        FancySwitch {
                            checked: dialog.draftRevision >= 0 && dialog.draft.auto_write === true
                            enabled: !dialog.locked
                            onToggled: dialog.change("auto_write", checked)
                        }
                        Text {
                            text: dialog.draftRevision >= 0 && dialog.draft.auto_write === true ? "сама, в конце" : "нет, вручную"
                            color: dialog.textMain
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                        }
                        Item { Layout.fillWidth: true }
                    }
                }

                // --- 3. Правила для всех шагов ---
                Section {
                    title: "3. Правила для всех шагов"
                    hint: "По ним программа решает, когда переходить дальше. У отдельного шага их можно переопределить в таблице шагов."

                    FormRow {
                        label: "Камера вышла на уставку, если воздух отличается от неё не больше чем на"
                        hint: "Пока камера не вышла на уставку, плату не ждут. Обычно 1 °C; камера, которая держит хуже, - 1,5…2 °C."
                        NumberField {
                            text: dialog.draftRevision >= 0 ? dialog.show(dialog.draft.reach_tolerance_c) : ""
                            onTextEdited: dialog.draft.reach_tolerance_c = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Text { text: "°C"; color: dialog.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                        Item { Layout.fillWidth: true }
                    }

                    FormRow {
                        label: "Плата устоялась, если за последние"
                        hint: "Температура платы за это окно менялась медленнее заданной скорости - значит плата прогрелась вместе с "
                              + "воздухом, и точка снимается. Обычно 5 мин и 0,05 °C/мин; строже - точнее, но дольше."
                        NumberField {
                            text: dialog.draftRevision >= 0 ? dialog.show(dialog.draft.settle_min) : ""
                            onTextEdited: dialog.draft.settle_min = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Text { text: "мин менялась медленнее"; color: dialog.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                        NumberField {
                            text: dialog.draftRevision >= 0 ? dialog.show(dialog.draft.settle_rate) : ""
                            onTextEdited: dialog.draft.settle_rate = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Text { text: "°C/мин"; color: dialog.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                        Item { Layout.fillWidth: true }
                    }

                    FormRow {
                        label: "Предупредить, если камера не вышла на уставку за"
                        hint: "Придёт предупреждение, прогон продолжит ждать; вдвое дольше - сообщение о зависании."
                        NumberField {
                            text: dialog.draftRevision >= 0 ? dialog.show(dialog.draft.reach_timeout_min) : ""
                            onTextEdited: dialog.draft.reach_timeout_min = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Text { text: "мин"; color: dialog.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                        Item { Layout.fillWidth: true }
                    }

                    FormRow {
                        label: "Плата должна дойти до температуры шага с допуском"
                        hint: "Плата греется сама, и её тянет к комнате (тепло по кабелю, оснастка), поэтому она устаивается не там, "
                              + "где воздух. Программа по ходу прогона строит прямую «плата ≈ k × воздух + b»: следующие шаги сразу "
                              + "начинаются с поправленной уставкой (упреждение), а если плата всё же устоялась дальше допуска, "
                              + "уставка сдвигается по этой прямой (доводка). Не дальше заданного сдвига и пределов уставки камеры. "
                              + "Не вышло за заданное число попыток - предупреждение в события и журнал действий, точка снимается "
                              + "при текущих условиях, прогон идёт дальше. Сдвиг 0 - ни упреждения, ни доводки. Шаг без точки - как задан."
                        NumberField {
                            text: dialog.draftRevision >= 0 ? dialog.show(dialog.draft.board_tolerance_c) : ""
                            onTextEdited: dialog.draft.board_tolerance_c = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Text { text: "°C; сдвигать уставку до"; color: dialog.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                        NumberField {
                            text: dialog.draftRevision >= 0 ? dialog.show(dialog.draft.board_max_shift_c) : ""
                            onTextEdited: dialog.draft.board_max_shift_c = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Text { text: "°C, попыток"; color: dialog.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                        NumberField {
                            text: dialog.draftRevision >= 0 ? dialog.show(dialog.draft.board_attempts) : ""
                            onTextEdited: dialog.draft.board_attempts = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Item { Layout.fillWidth: true }
                    }

                    FormRow {
                        label: "Предупредить, если плата не устоялась за"
                        hint: "Считая от выхода камеры на уставку. Так же: предупреждение, прогон ждёт дальше."
                        NumberField {
                            text: dialog.draftRevision >= 0 ? dialog.show(dialog.draft.settle_timeout_min) : ""
                            onTextEdited: dialog.draft.settle_timeout_min = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Text { text: "мин"; color: dialog.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                        Item { Layout.fillWidth: true }
                    }
                }

                // --- 4. В конце ---
                Section {
                    title: "4. В конце прогона"

                    FormRow {
                        label: "Задать камере температуру"
                        hint: "После последнего шага. Пусто - уставку не менять. Обычно +25 °C, чтобы плату можно было достать."
                        NumberField {
                            text: dialog.draftRevision >= 0 ? dialog.show(dialog.draft.finish_setpoint) : ""
                            placeholderText: "не менять"
                            onTextEdited: dialog.draft.finish_setpoint = dialog.num(text)
                            onEditingFinished: dialog.push()
                        }
                        Text { text: "°C"; color: dialog.textSoft; font.pixelSize: 12; font.family: "Bahnschrift" }
                        Item { Layout.fillWidth: true }
                    }

                    FormRow {
                        label: "Остановить камеру"
                        hint: "Выключено - камера держит эту температуру, пока её не остановят."
                        FancySwitch {
                            checked: dialog.draftRevision >= 0 && dialog.draft.finish_stop === true
                            onToggled: dialog.change("finish_stop", checked)
                        }
                        Text {
                            text: dialog.draftRevision >= 0 && dialog.draft.finish_stop === true ? "да" : "нет"
                            color: dialog.textMain
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                        }
                        Item { Layout.fillWidth: true }
                    }
                }

                // --- 5. Шаги по порядку ---
                Section {
                    title: "5. Шаги по порядку"
                    hint: "Каждый шаг: задать камере температуру - дождаться выхода на неё - дождаться, пока устоится плата - "
                          + "выдержка - точка - следующий шаг.<br><br>" + "<b>Как настроить шаги</b><br>"
                                  + "1. <b>Первым - +25 °C.</b> Это опорная точка: поправка во всех узлах считается от неё. Без неё таблица не посчитается.<br>"
                                  + "2. <b>Дальше - все узлы прибора:</b> −40, −20, 0, +50, +70, +85 °C. Удобный порядок - от +25 вниз до −40 и затем вверх до +85: "
                                  + "камера меньше мечется, цикл короче. Колонка «Узел прибора» показывает, в какой узел попадёт точка шага.<br>"
                                  + "3. <b>Температура шага = узел.</b> Точка попадает в узел, если температура платы в пределах ±3 °C от него.<br>"
                                  + "4. <b>Выдержка</b> - сколько ещё держать после того, как плата устоялась. Обычно 0. Если плата массивная или "
                                  + "хотите запас - 15…30 мин на крайних −40 и +85.<br>"
                                  + "5. <b>Точка</b> выключена - вспомогательный шаг без точки: прогрев перед циклом, переход. Он в таблицу не идёт.<br>"
                                  + "6. <b>Свои правила шага</b> (допуск, окно, скорость) - только если на этой температуре камера ведёт себя иначе, "
                                  + "например на −40 держит хуже: допуск 2 °C. Пусто - правила из раздела 3."

                    // Шапка таблицы: те же ширины колонок, что у строк.
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 40
                        radius: 6
                        color: "#f1f5f9"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            spacing: 6

                            Text { Layout.preferredWidth: 26; text: "№"; color: dialog.textSoft; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift" }
                            Text { Layout.preferredWidth: 86; text: "Температура,\n°C"; color: dialog.textSoft; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift" }
                            RowLayout {
                                Layout.preferredWidth: 96
                                spacing: 4
                                Text { text: "Узел\nприбора"; color: dialog.textSoft; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift" }
                                InfoMark { tip: "В какой узел сетки прибора попадёт точка шага: температура платы должна быть в пределах ±3 °C от узла. «вне узлов!» - точка в таблицу не войдёт." }
                            }
                            RowLayout {
                                Layout.preferredWidth: 56
                                spacing: 4
                                Text { text: "Точка"; color: dialog.textSoft; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift" }
                                InfoMark { tip: "Выключено - вспомогательный шаг без точки (прогрев, переход): в таблицу не идёт." }
                            }
                            RowLayout {
                                Layout.preferredWidth: 80
                                spacing: 4
                                Text { text: "Выдержка,\nмин"; color: dialog.textSoft; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift" }
                                InfoMark { tip: "Сколько ещё держать после того, как плата устоялась. Обычно 0; на крайних -40 и +85 можно 15...30 мин." }
                            }
                            RowLayout {
                                Layout.preferredWidth: 80
                                spacing: 4
                                Text { text: "Допуск ±,\n°C"; color: dialog.textSoft; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift" }
                                InfoMark { tip: "Свои правила шага: допуск выхода на уставку, окно и скорость устойчивости платы. Пусто - правила раздела 3 (видны серым)." }
                            }
                            Text { Layout.preferredWidth: 80; text: "Окно,\nмин"; color: dialog.textSoft; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift" }
                            Text { Layout.preferredWidth: 80; text: "Скорость,\n°C/мин"; color: dialog.textSoft; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift" }
                            Text { Layout.fillWidth: true; text: "Примечание"; color: dialog.textSoft; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift" }
                            Text { Layout.preferredWidth: 3 * 32 + 2 * 6; text: "Порядок"; color: dialog.textSoft; font.pixelSize: 11; font.bold: true; font.family: "Bahnschrift"; horizontalAlignment: Text.AlignHCenter }
                        }
                    }

                    Repeater {
                        model: dialog.draftRevision >= 0 ? (dialog.draft.steps || []).length : 0

                        Rectangle {
                            id: stepRow
                            required property int index
                            readonly property var step: dialog.draft.steps[stepRow.index] || ({})
                            // Узел пересчитывается при правке температуры: счётчик меняет поле температуры.
                            property real tempNow: stepRow.step.temp
                            readonly property var node: dialog.gridNode(stepRow.tempNow)
                            readonly property bool capture: stepRow.step.capture !== false

                            Layout.fillWidth: true
                            Layout.preferredHeight: 38
                            radius: 6
                            // Пройденные шаги идущего прогона закрыты, идущий - подсвечен.
                            enabled: dialog.stepEditable(stepRow.index)
                            opacity: enabled ? 1.0 : 0.55
                            color: dialog.locked && stepRow.index === dialog.runIndex ? "#e0f2fe"
                                   : (stepRow.index % 2 === 0 ? "#ffffff" : "#f8fafc")
                            border.width: 1
                            border.color: "#eef2f7"

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                spacing: 6

                                Text {
                                    Layout.preferredWidth: 26
                                    text: (stepRow.index + 1) + "."
                                    color: dialog.textMain
                                    font.pixelSize: 13
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }
                                NumberField {
                                    Layout.preferredWidth: 86
                                    text: dialog.show(stepRow.step.temp)
                                    onTextEdited: {
                                        dialog.draft.steps[stepRow.index].temp = dialog.num(text)
                                        stepRow.tempNow = dialog.num(text)
                                    }
                                    onEditingFinished: { dialog.push(); dialog.checkTick += 1 }
                                }
                                Text {
                                    Layout.preferredWidth: 96
                                    text: !stepRow.capture ? "без точки"
                                          : (stepRow.node === null ? "вне узлов!" : "→ " + dialog.nodeText(stepRow.node)
                                             + (stepRow.node === 25 ? " (опора)" : ""))
                                    color: !stepRow.capture ? dialog.textSoft : (stepRow.node === null ? "#dc2626" : "#0f766e")
                                    font.pixelSize: 12
                                    font.bold: stepRow.capture
                                    font.family: "Bahnschrift"
                                }
                                Item {
                                    Layout.preferredWidth: 56
                                    Layout.preferredHeight: 30
                                    FancySwitch {
                                        anchors.verticalCenter: parent.verticalCenter
                                        checked: stepRow.capture
                                        onToggled: {
                                            dialog.draft.steps[stepRow.index].capture = checked
                                            dialog.change("steps", dialog.draft.steps)
                                        }
                                    }
                                }
                                NumberField {
                                    Layout.preferredWidth: 80
                                    text: stepRow.step.hold_min ? dialog.show(stepRow.step.hold_min) : ""
                                    placeholderText: "0"
                                    onTextEdited: dialog.draft.steps[stepRow.index].hold_min = dialog.num(text) || 0
                                    onEditingFinished: dialog.push()
                                }
                                NumberField {
                                    Layout.preferredWidth: 80
                                    text: dialog.show(stepRow.step.reach_tolerance_c)
                                    placeholderText: dialog.show(dialog.draft.reach_tolerance_c)
                                    onTextEdited: dialog.draft.steps[stepRow.index].reach_tolerance_c = dialog.num(text)
                                    onEditingFinished: dialog.push()
                                }
                                NumberField {
                                    Layout.preferredWidth: 80
                                    text: dialog.show(stepRow.step.settle_min)
                                    placeholderText: dialog.show(dialog.draft.settle_min)
                                    onTextEdited: dialog.draft.steps[stepRow.index].settle_min = dialog.num(text)
                                    onEditingFinished: dialog.push()
                                }
                                NumberField {
                                    Layout.preferredWidth: 80
                                    text: dialog.show(stepRow.step.settle_rate)
                                    placeholderText: dialog.show(dialog.draft.settle_rate)
                                    onTextEdited: dialog.draft.steps[stepRow.index].settle_rate = dialog.num(text)
                                    onEditingFinished: dialog.push()
                                }
                                Field {
                                    Layout.fillWidth: true
                                    text: stepRow.step.note || ""
                                    placeholderText: stepRow.node === 25 ? "опорная точка" : ""
                                    onTextEdited: dialog.draft.steps[stepRow.index].note = text
                                    onEditingFinished: dialog.push()
                                }
                                SmallButton {
                                    Layout.preferredWidth: 32
                                    text: "↑"
                                    toolTipText: "Выше"
                                    enabled: dialog.stepMovable(stepRow.index) && dialog.stepMovable(stepRow.index - 1) && stepRow.index > 0
                                    onClicked: dialog.moveStep(stepRow.index, -1)
                                }
                                SmallButton {
                                    Layout.preferredWidth: 32
                                    text: "↓"
                                    toolTipText: "Ниже"
                                    enabled: dialog.stepMovable(stepRow.index) && stepRow.index < (dialog.draft.steps || []).length - 1
                                    onClicked: dialog.moveStep(stepRow.index, 1)
                                }
                                SmallButton {
                                    Layout.preferredWidth: 32
                                    text: "✕"
                                    toolTipText: "Удалить шаг"
                                    tone: "#ef4444"; toneHover: "#dc2626"; tonePressed: "#b91c1c"
                                    enabled: dialog.stepMovable(stepRow.index) && (dialog.draft.steps || []).length > 1
                                    onClicked: dialog.removeStep(stepRow.index)
                                }
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        SmallButton {
                            Layout.preferredWidth: 160
                            text: "+ Добавить шаг"
                            tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                            onClicked: dialog.addStep()
                        }

                        Item { Layout.fillWidth: true }
                    }

                    // Проверка сетки: опорный узел и все 7 узлов по шагам с точкой.
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 24
                        rowSpacing: 3
                        property var check: dialog.gridCheck()

                        Text {
                            text: parent.check.reference ? "✓  Опорный узел +25 °C есть" : "✗  Нет шага +25 °C с точкой: таблица не посчитается"
                            color: parent.check.reference ? "#15803d" : "#dc2626"
                            font.pixelSize: 12
                            font.bold: !parent.check.reference
                            font.family: "Bahnschrift"
                        }
                        Text {
                            Layout.fillWidth: true
                            text: parent.check.missing.length === 0 ? "✓  Все 7 узлов прибора есть: таблица будет полной"
                                  : "!  Нет узлов " + parent.check.missing.map(dialog.nodeText).join(", ")
                                    + ": таблица неполная, профиль сам не запишется"
                            color: parent.check.missing.length === 0 ? "#15803d" : "#b45309"
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            visible: parent.check.outside.length > 0
                            Layout.columnSpan: 2
                            text: "!  Шаги с точкой вне узлов (дальше ±3 °C): " + parent.check.outside.join(", ") + " °C - их точки в таблицу не войдут"
                            color: "#b45309"
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                        }
                    }
                }

                // --- Итог и замечания проверки значений ---
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


            }
        }
    }
}
