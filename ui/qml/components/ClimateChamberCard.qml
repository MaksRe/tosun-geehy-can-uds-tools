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

                            Text {
                                Layout.fillWidth: true
                                text: root.climate.status || ""
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
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
                        SettingField { key: "espec_port"; Layout.preferredWidth: 90 }
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

                    Text {
                        Layout.fillWidth: true
                        visible: root.climate.driver === "espec"
                        text: "Переходник USB-RS-422/485 на 4 провода: TX± к контактам 3-4 камеры (RD±), RX± к 1-2 (SD±), земля к 5. "
                              + "На пульте камеры: те же адрес, скорость и конец строки, 8 бит, без чётности, защита от удалённого управления выключена."
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

                    // Строка камере как есть: проверка связи на месте.
                    RowLayout {
                        Layout.fillWidth: true
                        visible: root.climate.driver === "espec" || root.climate.driver === "simcon_ascii2"
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
