import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Раздел «Климатическая камера».
  Назначение:
  - выбор камеры: ESPEC MC-811P (испытания платы), Weiss WK1-600/70 (изделие в сборе),
    имитатор (отладка на столе) или другая камера с Modbus;
  - карта регистров камеры: адреса вписываются из её документации;
  - температура, уставка, пуск и авария камеры, ручная уставка;
  - ESPEC: порт переходника Moxa UPort (auto), поиск адреса и скорости камеры,
    ручное управление (режим, пределы аварии, холодильник, пульт, плавный
    переход), список всех команд руководства с параметрами и журнал обмена;
  - автоматический прогон по списку температур: уставка, выход на неё,
    устоявшаяся плата, точки, следующий узел.

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

    readonly property var climate: root.appController ? root.appController.climate : ({})
    readonly property var settings: root.climate.settings || ({})
    readonly property var run: root.climate.run || ({})
    readonly property bool modbus: root.climate.driver === "modbus_tcp" || root.climate.driver === "modbus_rtu"
    readonly property bool espec: root.climate.driver === "espec"
    readonly property var especState: root.climate.espec || ({})
    // Во время автоматического прогона камерой управляет программа: ручные настройки только на паузе.
    readonly property bool manualAllowed: !root.run.active || root.run.paused === true
    // Выбранная команда в списке команд ESPEC и значения её параметров.
    property var selectedCommand: null
    property var commandValues: ({})
    property int commandValuesRevision: 0

    // Строка, которая уйдёт камере: шаблон команды с подставленными параметрами и адресом.
    function commandPreview() {
        var item = root.selectedCommand
        if (!item) return ""
        var revision = root.commandValuesRevision
        var line = item.command
        for (var i = 0; i < item.params.length; ++i) {
            var name = item.params[i].name
            var value = root.commandValues[name] !== undefined ? root.commandValues[name] : item.params[i].default
            line = line.replace("{" + name + "}", value)
        }
        return (root.settings.espec_address || "1") + "," + line
    }

    // Выбор команды в списке: параметры заполняются значениями по умолчанию.
    function selectCommand(item) {
        var values = {}
        for (var i = 0; i < item.params.length; ++i)
            values[item.params[i].name] = item.params[i].default
        root.commandValues = values
        root.selectedCommand = item
        root.commandValuesRevision += 1
    }

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    // Поле настройки: показ обновляется дважды в секунду, поэтому текст меняется,
    // только пока оператор в поле не печатает. Сохраняется по Enter и уходу из поля.
    component SettingField: FancyTextField {
        id: settingField
        property string key: ""
        readonly property string value: root.settings[settingField.key] !== undefined ? String(root.settings[settingField.key]) : ""
        Layout.preferredHeight: 30
        textColor: root.textMain
        bgColor: root.inputBg
        borderColor: root.inputBorder
        focusBorderColor: root.inputFocus
        onValueChanged: if (!settingField.activeFocus) settingField.text = settingField.value
        Component.onCompleted: settingField.text = settingField.value
        onEditingFinished: if (root.appController && settingField.text !== settingField.value)
                               root.appController.setClimateSetting(settingField.key, settingField.text)
    }

    // Поле карты регистров: «имя.поле», например «setpoint.address».
    component MapField: FancyTextField {
        id: mapField
        property string entry: ""
        property string field: ""
        readonly property string value: {
            var item = (root.climate.map || {})[mapField.entry]
            return item && item[mapField.field] !== undefined ? String(item[mapField.field]) : ""
        }
        Layout.preferredHeight: 30
        Layout.preferredWidth: 80
        horizontalAlignment: TextInput.AlignHCenter
        textColor: root.textMain
        bgColor: root.inputBg
        borderColor: root.inputBorder
        focusBorderColor: root.inputFocus
        onValueChanged: if (!mapField.activeFocus) mapField.text = mapField.value
        Component.onCompleted: mapField.text = mapField.value
        onEditingFinished: if (root.appController && mapField.text !== mapField.value)
                               root.appController.setClimateSetting("map." + mapField.entry + "." + mapField.field, mapField.text)
    }

    // Кнопка, которая перебирает варианты по кругу: таблица регистров, тип значения.
    component CycleButton: FancyButton {
        id: cycleButton
        property string entry: ""
        property string field: ""
        property var options: []
        readonly property string value: {
            var item = (root.climate.map || {})[cycleButton.entry]
            return item && item[cycleButton.field] !== undefined ? String(item[cycleButton.field]) : ""
        }
        Layout.preferredHeight: 28
        Layout.preferredWidth: 90
        fontPixelSize: 11
        text: cycleButton.value
        tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
        onClicked: {
            if (!root.appController) return
            var index = cycleButton.options.indexOf(cycleButton.value)
            var next = cycleButton.options[(index + 1) % cycleButton.options.length]
            root.appController.setClimateSetting("map." + cycleButton.entry + "." + cycleButton.field, next)
        }
    }

    // Кнопка команды ESPEC из каталога. Опасная команда (выключить панель) уходит
    // только после второго нажатия за 4 с, чтобы камеру не погасить случайно.
    component CmdButton: FancyButton {
        id: cmdButton
        property string key: ""
        property var values: ({})
        property bool danger: false
        property bool setting: true
        property bool armed: false
        property string label: ""
        Layout.preferredHeight: 30
        Layout.preferredWidth: Math.max(90, cmdButton.implicitWidth)
        fontPixelSize: 12
        text: cmdButton.armed ? "Точно? Ещё раз" : cmdButton.label
        tone: cmdButton.armed ? "#dc2626" : (cmdButton.danger ? "#b45309" : "#0f766e")
        toneHover: cmdButton.armed ? "#b91c1c" : (cmdButton.danger ? "#92400e" : "#115e59")
        tonePressed: cmdButton.armed ? "#991b1b" : (cmdButton.danger ? "#78350f" : "#134e4a")
        enabled: root.climate.connected === true && (!cmdButton.setting || root.manualAllowed)
        onClicked: {
            if (!root.appController) return
            if (cmdButton.danger && !cmdButton.armed) {
                cmdButton.armed = true
                armTimer.restart()
                return
            }
            cmdButton.armed = false
            root.appController.sendClimateCommand(cmdButton.key, JSON.stringify(cmdButton.values))
        }
        Timer { id: armTimer; interval: 4000; onTriggered: cmdButton.armed = false }
    }

    // Пара «подпись - значение» в блоке состояния ESPEC.
    component Fact: ColumnLayout {
        property string title: ""
        property string value: "—"
        property color valueColor: root.textMain
        spacing: 0
        Text { text: parent.title; color: root.textSoft; font.pixelSize: 11; font.family: "Bahnschrift" }
        Text { text: parent.value; color: parent.valueColor; font.pixelSize: 14; font.bold: true; font.family: "Bahnschrift" }
    }

    // Поле ручного ввода в блоке управления: значение живёт только в окне до отправки.
    component Input: FancyTextField {
        Layout.preferredHeight: 30
        Layout.preferredWidth: 70
        horizontalAlignment: TextInput.AlignHCenter
        textColor: root.textMain
        bgColor: root.inputBg
        borderColor: root.inputBorder
        focusBorderColor: root.inputFocus
    }

    component Caption: Text {
        color: root.textSoft
        font.pixelSize: 12
        font.family: "Bahnschrift"
        Layout.alignment: Qt.AlignVCenter
    }

    component Block: Rectangle {
        default property alias content: blockLayout.data
        Layout.fillWidth: true
        Layout.preferredHeight: blockLayout.implicitHeight + 20
        radius: 12
        color: "#f8fbff"
        border.width: 1
        border.color: "#d6e2ef"

        ColumnLayout {
            id: blockLayout
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8
        }
    }

    component BlockTitle: Text {
        color: root.textMain
        font.pixelSize: 14
        font.bold: true
        font.family: "Bahnschrift"
    }

    component Big: ColumnLayout {
        property string title: ""
        property string value: "—"
        property color valueColor: root.textMain
        spacing: 0
        Text { text: parent.title; color: root.textSoft; font.pixelSize: 11; font.family: "Bahnschrift" }
        Text { text: parent.value; color: parent.valueColor; font.pixelSize: 24; font.bold: true; font.family: "Bahnschrift" }
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
            spacing: 10

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Text {
                    text: "Климатическая камера"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                Text {
                    Layout.fillWidth: true
                    text: "Выберите камеру, подключитесь и запустите прогон: программа сама задаёт температуру, ждёт, пока устоится плата, и снимает точки."
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }
            }

            // --- Выбор камеры: у каждой своё назначение ---
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Repeater {
                    model: [
                        { "key": "espec", "name": "ESPEC MC-811P", "purpose": "Испытания платы", "link": "RS-485, 4 провода", "accent": "#0f766e", "fill": "#ecfdf5" },
                        { "key": "simcon_ascii2", "name": "Weiss WK1-600/70", "purpose": "Изделие в сборе: с трубками, в корпусе", "link": "RS-232", "accent": "#1d4ed8", "fill": "#eff6ff" },
                        { "key": "simulator", "name": "Имитатор", "purpose": "Отладка на столе, без камеры", "link": "", "accent": "#9a3412", "fill": "#fff7ed" }
                    ]

                    Rectangle {
                        id: chamberTile
                        required property var modelData
                        readonly property bool selected: root.climate.driver === modelData.key

                        Layout.fillWidth: true
                        Layout.preferredWidth: modelData.key === "simulator" ? 1 : 2
                        Layout.preferredHeight: 64
                        radius: 12
                        color: selected ? modelData.fill : "#f8fafc"
                        border.width: selected ? 2 : 1
                        border.color: selected ? modelData.accent : "#e2e8f0"
                        opacity: (root.run.active && !selected) ? 0.5 : 1.0

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 2

                            RowLayout {
                                spacing: 8
                                Rectangle {
                                    Layout.preferredWidth: 12
                                    Layout.preferredHeight: 12
                                    radius: 6
                                    color: chamberTile.selected ? chamberTile.modelData.accent : "transparent"
                                    border.width: 2
                                    border.color: chamberTile.modelData.accent
                                }
                                Text {
                                    text: chamberTile.modelData.name
                                    color: chamberTile.selected ? chamberTile.modelData.accent : root.textMain
                                    font.pixelSize: 15
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }
                                Text {
                                    visible: chamberTile.modelData.link.length > 0
                                    text: "· " + chamberTile.modelData.link
                                    color: root.textSoft
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: chamberTile.modelData.purpose
                                color: root.textSoft
                                font.pixelSize: 12
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            enabled: !root.run.active
                            cursorShape: Qt.PointingHandCursor
                            onClicked: if (root.appController) root.appController.setClimateSetting("driver", chamberTile.modelData.key)
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: (root.climate.modeHint || "").length > 0
                text: "⚠ " + (root.climate.modeHint || "")
                color: "#b45309"
                font.pixelSize: 12
                font.bold: true
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }

            // --- Подключение выбранной камеры ---
            Rectangle {
                Layout.fillWidth: true
                visible: root.climate.driver !== "none"
                Layout.preferredHeight: connectLayout.implicitHeight + 20
                radius: 12
                color: "#ffffff"
                border.width: 1
                border.color: "#d6e2ef"

                // Цветная полоса слева: сразу видно, с какой камерой идёт работа.
                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 6
                    radius: 3
                    color: (root.climate.chamber || {}).accent || "#94a3b8"
                }

                ColumnLayout {
                    id: connectLayout
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 10
                    anchors.topMargin: 10
                    anchors.bottomMargin: 10
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Rectangle {
                            Layout.alignment: Qt.AlignVCenter
                            Layout.preferredWidth: 12
                            Layout.preferredHeight: 12
                            radius: 6
                            color: root.climate.ok ? "#16a34a" : (root.climate.connected ? "#dc2626" : "#94a3b8")
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0

                            Text {
                                text: ((root.climate.chamber || {}).name || "") + "  ·  "
                                      + (root.climate.ok ? "на связи" : (root.climate.connected ? "нет ответа" : "не подключена"))
                                color: root.textMain
                                font.pixelSize: 14
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            // Перенос, а не обрезка: в причине нет связи подсказано, какую пару кабеля проверить.
                            Text {
                                Layout.fillWidth: true
                                text: root.climate.status || ""
                                color: root.climate.connected && !root.climate.ok ? "#b45309" : root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                                wrapMode: Text.WordWrap
                            }
                        }

                        FancyButton {
                            Layout.preferredWidth: 140
                            Layout.preferredHeight: 34
                            text: root.climate.connected ? "Отключить" : "Подключить"
                            tone: root.climate.connected ? "#ef4444" : "#16a34a"
                            toneHover: root.climate.connected ? "#dc2626" : "#15803d"
                            tonePressed: root.climate.connected ? "#b91c1c" : "#166534"
                            enabled: !root.run.active
                            onClicked: {
                                if (!root.appController) return
                                if (root.climate.connected) root.appController.disconnectClimate()
                                else root.appController.connectClimate()
                            }
                        }
                    }

                    // ESPEC MC-811P: RS-485, текстовые команды.
                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.climate.driver === "espec"
                        spacing: 8
                        Caption { text: "COM-порт" }
                        SettingField {
                            key: "espec_port"
                            Layout.preferredWidth: 90
                            ToolTip.visible: hovered
                            ToolTip.text: "auto - программа сама находит переходник Moxa UPort"
                        }
                        Caption { text: "Скорость" }
                        SettingField { key: "espec_baud"; Layout.preferredWidth: 80 }
                        Caption { text: "Адрес" }
                        SettingField { key: "espec_address"; Layout.preferredWidth: 50 }
                        Caption { text: "Конец строки" }

                        Repeater {
                            model: ["CRLF", "CR", "LF"]

                            FancyButton {
                                required property string modelData
                                Layout.preferredWidth: 56
                                Layout.preferredHeight: 28
                                fontPixelSize: 11
                                text: modelData
                                tone: root.settings.espec_delimiter === modelData ? "#0f766e" : "#94a3b8"
                                toneHover: "#115e59"
                                tonePressed: "#134e4a"
                                onClicked: if (root.appController) root.appController.setClimateSetting("espec_delimiter", modelData)
                            }
                        }
                        Item { Layout.fillWidth: true }
                    }

                    // Порты компьютера: переходник Moxa UPort первым и подсвечен.
                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.espec
                        spacing: 6
                        Caption { text: "Порты:" }

                        FancyButton {
                            Layout.preferredWidth: 120
                            Layout.preferredHeight: 26
                            fontPixelSize: 11
                            text: "auto (Moxa сам)"
                            tone: root.settings.espec_port === "auto" ? "#0f766e" : "#94a3b8"
                            toneHover: "#115e59"; tonePressed: "#134e4a"
                            enabled: !root.run.active
                            onClicked: if (root.appController) root.appController.setClimateSetting("espec_port", "auto")
                        }

                        Repeater {
                            model: root.climate.ports || []

                            FancyButton {
                                required property var modelData
                                Layout.preferredHeight: 26
                                Layout.preferredWidth: Math.min(260, 24 + 6.5 * (modelData.device.length + 3 + modelData.description.length))
                                fontPixelSize: 11
                                text: (modelData.moxa ? "★ " : "") + modelData.device + " · " + modelData.description
                                toolTipText: modelData.moxa ? "Переходник Moxa UPort" : modelData.description
                                tone: root.settings.espec_port === modelData.device ? "#0f766e" : (modelData.moxa ? "#0e7490" : "#94a3b8")
                                toneHover: "#115e59"; tonePressed: "#134e4a"
                                enabled: !root.run.active
                                onClicked: if (root.appController) root.appController.setClimateSetting("espec_port", modelData.device)
                            }
                        }

                        FancyButton {
                            Layout.preferredWidth: 90
                            Layout.preferredHeight: 26
                            fontPixelSize: 11
                            text: "Обновить"
                            tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
                            onClicked: if (root.appController) root.appController.refreshClimatePorts()
                        }
                        Item { Layout.fillWidth: true }
                    }

                    // Поиск камеры: адрес, скорость и конец строки находятся сами.
                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.espec
                        spacing: 8

                        FancyButton {
                            Layout.preferredWidth: 150
                            Layout.preferredHeight: 30
                            fontPixelSize: 12
                            text: (root.climate.scan || {}).active ? "Ищу камеру..." : "Найти камеру"
                            toolTipText: "Перебирает адреса 1...16 и скорости 9600, 19200, 4800 и узнаёт конец строки по ответу"
                            tone: "#0e7490"; toneHover: "#155e75"; tonePressed: "#164e63"
                            enabled: !root.run.active && !((root.climate.scan || {}).active)
                            onClicked: if (root.appController) root.appController.scanClimateChamber()
                        }

                        Text {
                            Layout.fillWidth: true
                            text: (root.climate.scan || {}).status || "Если адрес и скорость на пульте неизвестны, нажмите «Найти камеру»."
                            color: (root.climate.scan || {}).active ? "#0e7490" : root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: root.climate.driver === "espec"
                        text: "Moxa UPort 1150: в диспетчере устройств у порта выберите Interface = RS-422 (или RS-485 4W), из коробки там RS-232. "
                              + "Кабель от клеммника переходника Moxa (TB) к DB9 камеры: клемма 1 TxD+ → 3 RD+, 2 TxD− → 4 RD−, "
                              + "3 RxD+ → 1 SD+, 4 RxD− → 2 SD−, 5 GND → 5. Соединять по знаку «+»/«−», буквы A/B у Moxa и ESPEC противоположны. "
                              + "На пульте камеры: 8 бит, без чётности, защита от удалённого управления выключена."
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }

                    // Weiss WK1-600/70: контроллер SIMCON/32, протокол ASCII-2 по RS-232.
                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.climate.driver === "simcon_ascii2"
                        spacing: 8
                        Caption { text: "COM-порт" }
                        SettingField { key: "weiss_port"; Layout.preferredWidth: 90 }
                        Caption { text: "Скорость" }
                        SettingField { key: "weiss_baud"; Layout.preferredWidth: 80 }
                        Caption { text: "Адрес" }
                        SettingField { key: "simcon_address"; Layout.preferredWidth: 50 }
                        Item { Layout.fillWidth: true }
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: root.climate.driver === "simcon_ascii2"
                        text: "Нуль-модемный кабель RS-232: 2↔3 крест, 5 - земля. На пульте: протокол ASCII-2, те же скорость и адрес, режим EXTERN. "
                              + "Камера принимает не больше одной строки в 5 секунд, показания обновляются раз в 5 с."
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.climate.driver === "modbus_tcp"
                        spacing: 8
                        Caption { text: "Адрес камеры" }
                        SettingField { key: "tcp_host"; Layout.preferredWidth: 160 }
                        Caption { text: "Порт" }
                        SettingField { key: "tcp_port"; Layout.preferredWidth: 70 }
                        Caption { text: "Номер устройства" }
                        SettingField { key: "unit"; Layout.preferredWidth: 60 }
                        Item { Layout.fillWidth: true }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.climate.driver === "modbus_rtu"
                        spacing: 8
                        Caption { text: "Порт" }
                        SettingField { key: "rtu_port"; Layout.preferredWidth: 90 }
                        Caption { text: "Скорость" }
                        SettingField { key: "rtu_baud"; Layout.preferredWidth: 80 }
                        Caption { text: "Чётность N/E/O" }
                        SettingField { key: "rtu_parity"; Layout.preferredWidth: 50 }
                        Caption { text: "Стоп-биты" }
                        SettingField { key: "rtu_stopbits"; Layout.preferredWidth: 50 }
                        Caption { text: "Номер устройства" }
                        SettingField { key: "unit"; Layout.preferredWidth: 60 }
                        Item { Layout.fillWidth: true }
                    }

                    // Строка камере Weiss как есть: проверка связи на месте. У ESPEC она в блоке «Команды камеры».
                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.climate.driver === "simcon_ascii2"
                        spacing: 8
                        Caption { text: "Команда камере" }

                        FancyTextField {
                            id: rawField
                            Layout.preferredWidth: 220
                            Layout.preferredHeight: 30
                            placeholderText: root.climate.driver === "espec" ? "например TEMP? или MON?" : "например $00I"
                            textColor: root.textMain
                            bgColor: root.inputBg
                            borderColor: root.inputBorder
                            focusBorderColor: root.inputFocus
                            onAccepted: if (root.appController) root.appController.sendClimateRaw(text)
                        }

                        FancyButton {
                            Layout.preferredWidth: 100
                            Layout.preferredHeight: 30
                            fontPixelSize: 12
                            text: "Отправить"
                            tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
                            toolTipText: root.climate.driver === "espec"
                                         ? "Адрес и конец строки добавляются сами"
                                         : "Строка уходит как есть, <CR> добавляется сам"
                            enabled: root.climate.connected === true && rawField.text.length > 0
                            onClicked: if (root.appController) root.appController.sendClimateRaw(rawField.text)
                        }

                        Text {
                            Layout.fillWidth: true
                            text: {
                                var log = root.climate.rawLog || []
                                if (log.length === 0) return "Ответов пока нет"
                                var last = log[0]
                                return last.time + "  " + last.sent + "  →  " + last.answer
                            }
                            color: (root.climate.rawLog || []).length > 0 && !(root.climate.rawLog[0].ok) ? "#dc2626" : root.textMain
                            font.pixelSize: 12
                            font.family: "Consolas"
                            elide: Text.ElideRight
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.climate.driver === "simulator"
                        spacing: 8
                        Caption { text: "Ускорение времени" }

                        Repeater {
                            model: ["1", "10", "60"]

                            FancyButton {
                                required property string modelData
                                Layout.preferredWidth: 60
                                Layout.preferredHeight: 28
                                fontPixelSize: 12
                                text: "×" + modelData
                                tone: root.settings.sim_speed === modelData ? "#9a3412" : "#94a3b8"
                                toneHover: "#7c2d12"
                                tonePressed: "#7c2d12"
                                onClicked: if (root.appController) root.appController.setClimateSetting("sim_speed", modelData)
                            }
                        }

                        FancySwitch {
                            checked: root.settings.sim_bridge === true
                            onToggled: if (root.appController) root.appController.setClimateFlag("sim_bridge", checked)
                        }

                        Caption {
                            Layout.fillWidth: true
                            text: "Задавать прибору температуру платы из имитатора (нужен тестовый режим в разделе «Прогон в камере»)"
                            elide: Text.ElideRight
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        visible: (root.climate.bridgeStatus || "").length > 0
                        text: root.climate.bridgeStatus || ""
                        color: "#9a3412"
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        FancySwitch {
                            checked: root.settings.autoconnect === true
                            trackWidth: 44; trackHeight: 24
                            onToggled: if (root.appController) root.appController.setClimateFlag("autoconnect", checked)
                        }
                        Caption { text: "подключаться при запуске программы" }
                        Item { Layout.fillWidth: true }
                        Caption { text: "Опрос, с" }
                        SettingField { key: "poll_s"; Layout.preferredWidth: 60 }
                    }

                    // Другая камера с Modbus: редкий случай, поэтому мелко внизу.
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Caption { text: "Другая камера:" }

                        Repeater {
                            model: [{ "key": "modbus_tcp", "title": "Modbus TCP" }, { "key": "modbus_rtu", "title": "Modbus RTU" }]

                            FancyButton {
                                required property var modelData
                                Layout.preferredWidth: 100
                                Layout.preferredHeight: 24
                                fontPixelSize: 11
                                text: modelData.title
                                tone: root.climate.driver === modelData.key ? "#475569" : "#cbd5e1"
                                toneHover: "#64748b"
                                tonePressed: "#334155"
                                enabled: !root.run.active
                                onClicked: if (root.appController) root.appController.setClimateSetting("driver", modelData.key)
                            }
                        }
                        Item { Layout.fillWidth: true }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: root.climate.driver === "none"
                text: "Камера не выбрана. Нажмите на плитку нужной камеры выше. Другая камера с Modbus выбирается после этого внизу блока подключения."
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }

            // --- Карта регистров ---
            Block {
                visible: root.modbus

                BlockTitle { text: "Карта регистров камеры" }

                Text {
                    Layout.fillWidth: true
                    text: "Адреса берутся из документации камеры, с нуля: регистр 40001 - это адрес 0 в таблице holding, 30001 - адрес 0 в input. "
                          + "Масштаб переводит число в градусы: 0,1 означает «в регистре десятые доли градуса»."
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 9
                    columnSpacing: 8
                    rowSpacing: 4

                    Caption { text: "Величина" }
                    Caption { text: "Есть" }
                    Caption { text: "Таблица" }
                    Caption { text: "Адрес" }
                    Caption { text: "Тип" }
                    Caption { text: "Масштаб" }
                    Caption { text: "Старшее слово первым" }
                    Caption { text: "Пуск =" }
                    Caption { text: "Стоп =" }

                    // Строки таблицы заданы явно: у каждой величины свой набор полей.
                    Text { text: "Температура в камере"; color: root.textMain; font.pixelSize: 12; font.family: "Bahnschrift" }
                    FancySwitch { checked: ((root.climate.map || {}).actual || {}).enabled === true; trackWidth: 44; trackHeight: 24
                        onToggled: if (root.appController) root.appController.setClimateSetting("map.actual.enabled", checked ? "true" : "false") }
                    CycleButton { entry: "actual"; field: "table"; options: ["holding", "input"] }
                    MapField { entry: "actual"; field: "address" }
                    CycleButton { entry: "actual"; field: "value_type"; options: ["int16", "uint16", "int32", "uint32", "float32"] }
                    MapField { entry: "actual"; field: "scale" }
                    FancySwitch { checked: ((root.climate.map || {}).actual || {}).high_word_first === true; trackWidth: 44; trackHeight: 24
                        onToggled: if (root.appController) root.appController.setClimateSetting("map.actual.high_word_first", checked ? "true" : "false") }
                    Item { width: 1 }
                    Item { width: 1 }

                    Text { text: "Уставка"; color: root.textMain; font.pixelSize: 12; font.family: "Bahnschrift" }
                    FancySwitch { checked: ((root.climate.map || {}).setpoint || {}).enabled === true; trackWidth: 44; trackHeight: 24
                        onToggled: if (root.appController) root.appController.setClimateSetting("map.setpoint.enabled", checked ? "true" : "false") }
                    CycleButton { entry: "setpoint"; field: "table"; options: ["holding", "input"] }
                    MapField { entry: "setpoint"; field: "address" }
                    CycleButton { entry: "setpoint"; field: "value_type"; options: ["int16", "uint16", "int32", "uint32", "float32"] }
                    MapField { entry: "setpoint"; field: "scale" }
                    FancySwitch { checked: ((root.climate.map || {}).setpoint || {}).high_word_first === true; trackWidth: 44; trackHeight: 24
                        onToggled: if (root.appController) root.appController.setClimateSetting("map.setpoint.high_word_first", checked ? "true" : "false") }
                    Item { width: 1 }
                    Item { width: 1 }

                    Text { text: "Пуск / стоп"; color: root.textMain; font.pixelSize: 12; font.family: "Bahnschrift" }
                    FancySwitch { checked: ((root.climate.map || {}).run || {}).enabled === true; trackWidth: 44; trackHeight: 24
                        onToggled: if (root.appController) root.appController.setClimateSetting("map.run.enabled", checked ? "true" : "false") }
                    CycleButton { entry: "run"; field: "table"; options: ["coil", "holding"] }
                    MapField { entry: "run"; field: "address" }
                    Item { width: 1 }
                    Item { width: 1 }
                    Item { width: 1 }
                    MapField { entry: "run"; field: "on_value"; Layout.preferredWidth: 60 }
                    MapField { entry: "run"; field: "off_value"; Layout.preferredWidth: 60 }

                    Text { text: "Авария"; color: root.textMain; font.pixelSize: 12; font.family: "Bahnschrift" }
                    FancySwitch { checked: ((root.climate.map || {}).alarm || {}).enabled === true; trackWidth: 44; trackHeight: 24
                        onToggled: if (root.appController) root.appController.setClimateSetting("map.alarm.enabled", checked ? "true" : "false") }
                    CycleButton { entry: "alarm"; field: "table"; options: ["holding", "input", "coil"] }
                    MapField { entry: "alarm"; field: "address" }
                    CycleButton { entry: "alarm"; field: "value_type"; options: ["uint16", "int16"] }
                    Item { width: 1 }
                    Item { width: 1 }
                    Item { width: 1 }
                    Item { width: 1 }
                }
            }

            // --- Камера сейчас ---
            Block {
                BlockTitle { text: "Камера сейчас" }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 28

                    Big { title: "Температура в камере"; value: root.climate.actualText || "—" }
                    Big { title: "Уставка"; value: root.climate.setpointText || "—"; valueColor: "#0f766e" }
                    Big { title: "Состояние"; value: root.climate.runningText || "—" }
                    Big { title: "Авария"; value: root.climate.alarmText || "—"; valueColor: root.climate.alarm ? "#dc2626" : root.textMain }
                    Big { visible: root.climate.driver === "simulator"; title: "Изделие (имитатор)"; value: root.climate.productText || "—"; valueColor: "#9a3412" }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Caption { text: "Уставка, °C" }

                    FancyTextField {
                        id: setpointField
                        Layout.preferredWidth: 90
                        Layout.preferredHeight: 30
                        horizontalAlignment: TextInput.AlignHCenter
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        onAccepted: if (root.appController) root.appController.setClimateSetpoint(text)
                    }

                    FancyButton {
                        Layout.preferredWidth: 90
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Задать"
                        tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                        enabled: root.climate.canSet === true && !root.run.active && setpointField.text.length > 0
                        onClicked: if (root.appController) root.appController.setClimateSetpoint(setpointField.text)
                    }

                    FancyButton {
                        Layout.preferredWidth: 80
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Пуск"
                        tone: "#16a34a"; toneHover: "#15803d"; tonePressed: "#166534"
                        enabled: root.climate.canRun === true
                        onClicked: if (root.appController) root.appController.setClimateRunning(true)
                    }

                    FancyButton {
                        Layout.preferredWidth: 80
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Стоп"
                        tone: "#ef4444"; toneHover: "#dc2626"; tonePressed: "#b91c1c"
                        enabled: root.climate.canRun === true
                        onClicked: if (root.appController) root.appController.setClimateRunning(false)
                    }

                    Caption { text: "Пределы уставки, °C" }
                    SettingField { key: "min_c"; Layout.preferredWidth: 60 }
                    SettingField { key: "max_c"; Layout.preferredWidth: 60 }

                    Text {
                        Layout.fillWidth: true
                        text: root.climate.commandStatus || ""
                        color: root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }
                }
            }

            // --- Ручное управление камерой ESPEC ---
            Block {
                visible: root.espec

                RowLayout {
                    Layout.fillWidth: true
                    BlockTitle { text: "Управление камерой ESPEC" }
                    Item { Layout.fillWidth: true }
                    Text {
                        visible: !root.manualAllowed
                        text: "Идёт автопрогон: настройки камеры меняются только на паузе"
                        color: "#b45309"
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                    }
                }

                // Состояние камеры из автоопроса: режим, пределы, нагреватель, холодильник, пульт.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 24
                    Fact { title: "Режим"; value: root.especState.modeText || "—"
                        valueColor: root.especState.powerOff ? "#64748b" : (root.especState.program ? "#7c3aed" : "#0f766e") }
                    Fact { title: "Верхний предел аварии"; value: root.especState.highText || "—" }
                    Fact { title: "Нижний предел аварии"; value: root.especState.lowText || "—" }
                    Fact { title: "Нагреватель"; value: root.especState.heaterText || "—" }
                    Fact { title: "Холодильник"; value: root.especState.refText || "—" }
                    Fact { title: "Пульт"; value: root.especState.keyText || "—"
                        valueColor: root.especState.keyProtect ? "#b45309" : root.textMain }
                    Item { Layout.fillWidth: true }
                }

                Text {
                    Layout.fillWidth: true
                    visible: (root.especState.programText || "").length > 0 || (root.especState.alarmsText || "").length > 0
                    text: ((root.especState.programText || "").length > 0 ? "Программа: " + root.especState.programText + ".  " : "")
                          + ((root.especState.alarmsText || "").length > 0 ? "Номера аварий: " + root.especState.alarmsText + "." : "")
                    color: (root.especState.alarmsText || "").length > 0 ? "#dc2626" : "#7c3aed"
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                Text {
                    Layout.fillWidth: true
                    text: "Контроллер: " + (root.especState.identity || "—")
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Caption { text: "Режим"; Layout.preferredWidth: 130 }
                    CmdButton { key: "mode_constant"; label: "Пуск" }
                    CmdButton { key: "mode_standby"; label: "Стоп" }
                    CmdButton { key: "power_on"; label: "Включить панель"; Layout.preferredWidth: 140 }
                    CmdButton { key: "power_off"; label: "Выключить панель"; danger: true; Layout.preferredWidth: 150 }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Caption { text: "Пределы аварии, °C"; Layout.preferredWidth: 130 }
                    Caption { text: "верх" }
                    Input { id: highInput; placeholderText: "100,0" }
                    CmdButton { key: "set_high"; label: "Задать"; values: ({ "high": highInput.text })
                        enabled: root.climate.connected === true && root.manualAllowed && highInput.text.length > 0 }
                    Caption { text: "низ" }
                    Input { id: lowInput; placeholderText: "-50,0" }
                    CmdButton { key: "set_low"; label: "Задать"; values: ({ "low": lowInput.text })
                        enabled: root.climate.connected === true && root.manualAllowed && lowInput.text.length > 0 }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Caption { text: "Холодильник"; Layout.preferredWidth: 130 }
                    CmdButton { key: "set_ref"; label: "Авто"; values: ({ "ref": "9" }) }
                    CmdButton { key: "set_ref"; label: "Выключить"; values: ({ "ref": "0" }) }
                    CmdButton { key: "set_ref"; label: "Включить"; values: ({ "ref": "1" }) }
                    Caption { text: "Пульт"; Layout.leftMargin: 20 }
                    CmdButton { key: "key_on"; label: "Заблокировать"; Layout.preferredWidth: 130 }
                    CmdButton { key: "key_off"; label: "Разблокировать"; Layout.preferredWidth: 130 }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Caption { text: "Плавный переход"; Layout.preferredWidth: 130 }
                    Caption { text: "от, °C" }
                    Input { id: rampStart; text: "25" }
                    Caption { text: "до, °C" }
                    Input { id: rampEnd; text: "-40" }
                    Caption { text: "за, ч:мм" }
                    Input { id: rampTime; text: "1:00" }
                    CmdButton { key: "run_prgm"; label: "Запустить"
                        values: ({ "start": rampStart.text, "end": rampEnd.text, "time": rampTime.text }) }
                    Item { Layout.fillWidth: true }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Caption { text: "Программа"; Layout.preferredWidth: 130 }
                    CmdButton { key: root.especState.paused ? "prgm_continue" : "prgm_pause"
                        label: root.especState.paused ? "Продолжить" : "Пауза"
                        enabled: root.climate.connected === true && root.manualAllowed && root.especState.program === true }
                    CmdButton { key: "prgm_end_hold"; label: "Закончить, держать уставку"; Layout.preferredWidth: 210
                        enabled: root.climate.connected === true && root.manualAllowed && root.especState.program === true }
                    CmdButton { key: "prgm_end_standby"; label: "Закончить и остановить"; Layout.preferredWidth: 190
                        enabled: root.climate.connected === true && root.manualAllowed && root.especState.program === true }
                    Item { Layout.fillWidth: true }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Плавный переход - удалённая программа камеры: температура меняется от начальной к конечной за заданное время, "
                          + "потом конечная держится. Все команды и ответы камеры видны в журнале обмена ниже."
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }
            }

            // --- Список всех команд ESPEC и журнал обмена ---
            Block {
                visible: root.espec

                BlockTitle { text: "Команды камеры ESPEC" }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    // Список команд по разделам руководства.
                    Rectangle {
                        Layout.preferredWidth: 330
                        Layout.preferredHeight: 340
                        radius: 8
                        color: "#ffffff"
                        border.width: 1
                        border.color: "#d6e2ef"
                        clip: true

                        ListView {
                            id: commandList
                            anchors.fill: parent
                            anchors.margins: 4
                            model: root.climate.commands || []
                            boundsBehavior: Flickable.StopAtBounds
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                            // Строка команды; над первой командой раздела - его заголовок.
                            delegate: Column {
                                id: commandRow
                                required property var modelData
                                required property int index
                                readonly property bool current: root.selectedCommand !== null && root.selectedCommand.key === modelData.key
                                readonly property bool firstInGroup: commandRow.index === 0
                                    || (root.climate.commands || [])[commandRow.index - 1].group !== commandRow.modelData.group
                                width: commandList.width - 10

                                Text {
                                    visible: commandRow.firstInGroup
                                    width: commandRow.width
                                    topPadding: 6
                                    bottomPadding: 2
                                    leftPadding: 6
                                    text: commandRow.modelData.group
                                    color: commandRow.modelData.newOnly ? "#94a3b8" : "#0f766e"
                                    font.pixelSize: 12
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }

                                Rectangle {
                                    width: commandRow.width
                                    height: 26
                                    radius: 6
                                    color: commandRow.current ? "#ccfbf1" : (rowMouse.containsMouse ? "#f1f5f9" : "transparent")

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 10
                                        anchors.rightMargin: 6
                                        spacing: 6
                                        Text {
                                            Layout.fillWidth: true
                                            text: commandRow.modelData.title
                                            color: commandRow.modelData.newOnly ? "#94a3b8" : (commandRow.modelData.danger ? "#b45309" : root.textMain)
                                            font.pixelSize: 12
                                            font.family: "Bahnschrift"
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            text: commandRow.modelData.command.split(",")[0]
                                            color: root.textSoft
                                            font.pixelSize: 11
                                            font.family: "Consolas"
                                        }
                                    }

                                    MouseArea {
                                        id: rowMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: root.selectCommand(commandRow.modelData)
                                    }
                                }
                            }
                        }
                    }

                    // Выбранная команда: что делает, параметры, итоговая строка и отправка.
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        spacing: 8

                        Text {
                            Layout.fillWidth: true
                            text: root.selectedCommand ? root.selectedCommand.title : "Выберите команду в списке слева"
                            color: root.textMain
                            font.pixelSize: 15
                            font.bold: true
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: root.selectedCommand !== null
                            text: root.selectedCommand ? root.selectedCommand.hint : ""
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }

                        Text {
                            Layout.fillWidth: true
                            visible: root.selectedCommand !== null && root.selectedCommand.newOnly === true
                            text: "Эта команда есть только у новой серии контроллера (модели на «2»). MC-811P ответит «камера не знает такой команды»."
                            color: "#b45309"
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }

                        Repeater {
                            model: root.selectedCommand ? root.selectedCommand.params : []

                            RowLayout {
                                required property var modelData
                                spacing: 8
                                Caption { text: modelData.label; Layout.preferredWidth: 150 }
                                FancyTextField {
                                    Layout.preferredWidth: 120
                                    Layout.preferredHeight: 30
                                    horizontalAlignment: TextInput.AlignHCenter
                                    textColor: root.textMain
                                    bgColor: root.inputBg
                                    borderColor: root.inputBorder
                                    focusBorderColor: root.inputFocus
                                    Component.onCompleted: text = root.commandValues[modelData.name] !== undefined
                                                                  ? root.commandValues[modelData.name] : modelData.default
                                    onTextChanged: {
                                        root.commandValues[modelData.name] = text
                                        root.commandValuesRevision += 1
                                    }
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            visible: root.selectedCommand !== null
                            spacing: 8
                            Caption { text: "Уйдёт камере:" }
                            Text {
                                Layout.fillWidth: true
                                text: root.commandPreview()
                                color: "#0f766e"
                                font.pixelSize: 13
                                font.family: "Consolas"
                                elide: Text.ElideRight
                            }
                        }

                        CmdButton {
                            visible: root.selectedCommand !== null
                            Layout.preferredWidth: 160
                            key: root.selectedCommand ? root.selectedCommand.key : ""
                            label: "Отправить"
                            danger: root.selectedCommand ? root.selectedCommand.danger === true : false
                            setting: root.selectedCommand ? root.selectedCommand.setting === true : false
                            values: {
                                var revision = root.commandValuesRevision
                                var copy = {}
                                for (var name in root.commandValues) copy[name] = root.commandValues[name]
                                return copy
                            }
                        }

                        Item { Layout.preferredHeight: 6 }

                        // Любая строка вручную: для команд, которых нет в списке.
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Caption { text: "Своя строка" }

                            FancyTextField {
                                id: especRawField
                                Layout.fillWidth: true
                                Layout.preferredHeight: 30
                                placeholderText: "например TEMP? - адрес и конец строки добавятся сами"
                                textColor: root.textMain
                                bgColor: root.inputBg
                                borderColor: root.inputBorder
                                focusBorderColor: root.inputFocus
                                onAccepted: if (root.appController) root.appController.sendClimateRaw(text)
                            }

                            FancyButton {
                                Layout.preferredWidth: 100
                                Layout.preferredHeight: 30
                                fontPixelSize: 12
                                text: "Отправить"
                                tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
                                enabled: root.climate.connected === true && especRawField.text.length > 0
                                onClicked: if (root.appController) root.appController.sendClimateRaw(especRawField.text)
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.climate.commandStatus || ""
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }
                    }
                }

                // Журнал обмена: что ушло, что ответила камера и что это значит.
                Text {
                    text: "Журнал обмена (последние 50 команд, новые сверху)"
                    color: root.textMain
                    font.pixelSize: 12
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                Text {
                    visible: (root.climate.rawLog || []).length === 0
                    text: "Команд пока не было. Автоопрос камеры в журнал не пишется, только команды из окна."
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                }

                Repeater {
                    model: root.climate.rawLog || []

                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 10
                        Text { text: modelData.time; color: root.textSoft; font.pixelSize: 12; font.family: "Consolas" }
                        Text { text: modelData.sent; color: root.textMain; font.pixelSize: 12; font.family: "Consolas"; Layout.preferredWidth: 260; elide: Text.ElideRight }
                        // Без пояснения (отказ, неизвестный ответ) ответ занимает всю оставшуюся ширину.
                        Text { text: "→ " + modelData.answer; color: modelData.ok ? "#0f766e" : "#dc2626"; font.pixelSize: 12; font.family: "Consolas"
                            Layout.preferredWidth: (modelData.explain || "").length > 0 ? 300 : -1
                            Layout.fillWidth: (modelData.explain || "").length === 0
                            // Причину отказа видно целиком: в ней подсказка, что проверить.
                            elide: modelData.ok ? Text.ElideRight : Text.ElideNone
                            wrapMode: modelData.ok ? Text.NoWrap : Text.WordWrap }
                        Text { Layout.fillWidth: true; visible: (modelData.explain || "").length > 0; text: modelData.explain || ""
                            color: root.textSoft; font.pixelSize: 12; font.family: "Bahnschrift"; elide: Text.ElideRight }
                    }
                }
            }

            // --- Диагностика связи: журнал, проверка, отчёт для разбора ---
            Block {
                id: diagBlock
                visible: root.climate.driver !== "none"
                readonly property var diag: root.climate.diag || ({})
                readonly property var selftest: root.climate.selftest || ({})
                readonly property var moxaCheck: root.climate.moxaCheck || ({})

                BlockTitle { text: "Диагностика связи" }

                Text {
                    Layout.fillWidth: true
                    visible: (diagBlock.moxaCheck.text || "").length > 0
                    text: (diagBlock.moxaCheck.ok ? "✓ " : "⚠ ") + (diagBlock.moxaCheck.text || "")
                    color: diagBlock.moxaCheck.ok ? "#15803d" : "#dc2626"
                    font.pixelSize: 12
                    font.bold: !diagBlock.moxaCheck.ok
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                Text {
                    Layout.fillWidth: true
                    text: "Счётчики сеанса: " + (diagBlock.diag.stats || "—")
                          + ".  Последний ответ: " + (diagBlock.diag.lastOk || "—")
                    color: root.textMain
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                Text {
                    Layout.fillWidth: true
                    visible: (diagBlock.diag.lastError || "").length > 0
                    text: "Последняя ошибка (" + (diagBlock.diag.lastErrorTime || "") + "): " + (diagBlock.diag.lastError || "")
                    color: "#b45309"
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    FancyButton {
                        Layout.preferredWidth: 160
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: diagBlock.selftest.active ? "Проверяю..." : "Проверить связь"
                        toolTipText: "Отправляет камере набор запросов и показывает ответ, задержку и итог каждого"
                        tone: "#0e7490"; toneHover: "#155e75"; tonePressed: "#164e63"
                        enabled: root.climate.connected === true && !diagBlock.selftest.active
                        onClicked: if (root.appController) root.appController.runClimateSelftest()
                    }

                    FancyButton {
                        Layout.preferredWidth: 230
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Сохранить отчёт для разбора"
                        toolTipText: "Один файл: окружение, настройки, порты, режим Moxa, состояние, журнал и последние обмены"
                        tone: "#7c3aed"; toneHover: "#6d28d9"; tonePressed: "#5b21b6"
                        onClicked: if (root.appController) root.appController.saveClimateReport()
                    }

                    FancyButton {
                        Layout.preferredWidth: 190
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Открыть папку журналов"
                        tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
                        onClicked: if (root.appController) root.appController.openClimateLogs()
                    }

                    FancySwitch {
                        checked: root.settings.diag_verbose === true
                        trackWidth: 44; trackHeight: 24
                        onToggled: if (root.appController) root.appController.setClimateFlag("diag_verbose", checked)
                    }
                    Caption {
                        Layout.fillWidth: true
                        text: "каждый обмен в файл (иначе - первые обмены сеанса и всё вокруг ошибок)"
                        elide: Text.ElideRight
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Журнал: " + (diagBlock.diag.path || "—")
                          + ((diagBlock.diag.report || "").length > 0 ? "\nПоследний отчёт: " + diagBlock.diag.report : "")
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Consolas"
                    wrapMode: Text.WrapAnywhere
                }

                Text {
                    Layout.fillWidth: true
                    visible: (diagBlock.diag.writeError || "").length > 0
                    text: "⚠ " + (diagBlock.diag.writeError || "")
                    color: "#dc2626"
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                // Итог проверки связи: по каждому запросу ответ, задержка и смысл словами.
                Text {
                    Layout.fillWidth: true
                    visible: (diagBlock.selftest.text || "").length > 0
                    text: "Проверка связи: " + (diagBlock.selftest.text || "")
                    color: root.textMain
                    font.pixelSize: 12
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                Repeater {
                    model: diagBlock.selftest.results || []

                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 10
                        Text { text: modelData.ok ? "✓" : "✗"; color: modelData.ok ? "#15803d" : "#dc2626"; font.pixelSize: 13; font.bold: true }
                        Text { text: modelData.query; color: root.textMain; font.pixelSize: 12; font.family: "Consolas"; Layout.preferredWidth: 110 }
                        Text { text: modelData.ms + " мс"; color: root.textSoft; font.pixelSize: 12; font.family: "Consolas"; Layout.preferredWidth: 70 }
                        Text { Layout.fillWidth: true; color: modelData.ok ? "#0f766e" : "#dc2626"; font.pixelSize: 12; font.family: "Consolas"
                            text: modelData.answer + ((modelData.explain || "").length > 0 ? "   (" + modelData.explain + ")" : "")
                            wrapMode: Text.WordWrap }
                    }
                }

                Text {
                    text: "Последние события журнала (новые сверху)"
                    color: root.textMain
                    font.pixelSize: 12
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                Repeater {
                    model: (diagBlock.diag.events || []).slice(0, 15)

                    Text {
                        required property string modelData
                        Layout.fillWidth: true
                        text: modelData
                        color: modelData.indexOf("[ERROR]") >= 0 ? "#dc2626" : (modelData.indexOf("[WARN") >= 0 ? "#b45309" : root.textSoft)
                        font.pixelSize: 11
                        font.family: "Consolas"
                        elide: Text.ElideRight
                    }
                }
            }

            // --- Автоматический прогон ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: runLayout.implicitHeight + 20
                radius: 12
                color: root.run.active ? "#f0fdf4" : "#f8fbff"
                border.width: 1
                border.color: root.run.active ? "#86efac" : "#d6e2ef"

                ColumnLayout {
                    id: runLayout
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 8

                    BlockTitle { text: "Автоматический прогон" }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Caption { text: "Температуры, °C" }
                        SettingField { key: "run_nodes"; Layout.preferredWidth: 260 }
                        Caption { text: "Пометки через «;»" }
                        SettingField { key: "run_labels"; Layout.fillWidth: true
                            placeholderText: "например 0/0; 68/22; 150/47. Пусто - текущая пометка из «Прогона в камере»" }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Caption { text: "Выход на уставку ±, °C" }
                        SettingField { key: "reach_tolerance_c"; Layout.preferredWidth: 50 }
                        Caption { text: "Плата устоялась: за, мин" }
                        SettingField { key: "settle_min"; Layout.preferredWidth: 50 }
                        Caption { text: "медленнее, °C/мин" }
                        SettingField { key: "settle_rate"; Layout.preferredWidth: 60 }
                        Caption { text: "Предупредить через, мин:" }
                        SettingField { key: "reach_timeout_min"; Layout.preferredWidth: 55 }
                        SettingField { key: "settle_timeout_min"; Layout.preferredWidth: 55 }
                        Caption { text: "В конце, °C" }
                        SettingField { key: "finish_setpoint"; Layout.preferredWidth: 55 }
                        FancySwitch {
                            checked: root.settings.finish_stop === true
                            trackWidth: 44; trackHeight: 24
                            onToggled: if (root.appController) root.appController.setClimateFlag("finish_stop", checked)
                        }
                        Caption { text: "и остановить" }
                        Item { Layout.fillWidth: true }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Repeater {
                            model: root.run.nodes || []

                            Rectangle {
                                required property var modelData
                                Layout.preferredHeight: 26
                                Layout.preferredWidth: nodeText.implicitWidth + 20
                                radius: 13
                                color: modelData.state === "done" ? "#dcfce7" : modelData.state === "run" ? "#dbeafe" : "#f1f5f9"
                                border.width: 1
                                border.color: modelData.state === "done" ? "#86efac" : modelData.state === "run" ? "#93c5fd" : "#e2e8f0"

                                Text {
                                    id: nodeText
                                    anchors.centerIn: parent
                                    text: parent.modelData.text + (parent.modelData.state === "done" ? "  ✓" : "")
                                    color: parent.modelData.state === "run" ? "#1d4ed8" : root.textMain
                                    font.pixelSize: 12
                                    font.family: "Bahnschrift"
                                }
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.run.active ? "Этап: " + (root.run.stage || "") + (root.run.paused ? " (пауза)" : "") : ""
                            color: "#1d4ed8"
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        FancyButton {
                            Layout.preferredWidth: 200
                            Layout.preferredHeight: 34
                            text: root.run.active ? "Остановить прогон" : "Начать прогон"
                            tone: root.run.active ? "#ef4444" : "#16a34a"
                            toneHover: root.run.active ? "#dc2626" : "#15803d"
                            tonePressed: root.run.active ? "#b91c1c" : "#166534"
                            enabled: root.run.active || (root.climate.ok === true && root.climate.canSet === true)
                            onClicked: {
                                if (!root.appController) return
                                if (root.run.active) root.appController.stopClimateRun()
                                else root.appController.startClimateRun()
                            }
                        }

                        FancyButton {
                            Layout.preferredWidth: 170
                            Layout.preferredHeight: 34
                            fontPixelSize: 13
                            visible: root.run.active === true
                            text: root.run.paused ? "Продолжить прогон" : "Пауза"
                            tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
                            onClicked: if (root.appController) root.appController.pauseClimateRun(!root.run.paused)
                        }

                        FancyButton {
                            Layout.preferredWidth: 200
                            Layout.preferredHeight: 34
                            fontPixelSize: 13
                            visible: root.run.operator === true
                            text: "Эталоны переключены"
                            tone: "#ea580c"; toneHover: "#c2410c"; tonePressed: "#9a3412"
                            onClicked: if (root.appController) root.appController.continueClimateRun()
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.run.status || ""
                            color: root.run.color || root.textSoft
                            font.pixelSize: 13
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "В каждом узле: уставка - выход камеры на неё - плата устоялась - точки со всеми пометками - следующий узел. "
                              + "Если пометок несколько, программа просит переключить эталоны и ждёт «Эталоны переключены», "
                              + "а порядок чередует, чтобы переключать реже. Журнал, таблицы и запись профиля идут как обычно."
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }
}
