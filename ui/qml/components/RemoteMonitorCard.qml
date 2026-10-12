import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Раздел «Удалённое наблюдение».
  Назначение:
  - бот Telegram с несколькими пользователями: у каждого свой уровень
    уведомлений и переключатели (точки, сводки, файлы); доступ одобряет
    администратор или код доступа;
  - мини-приложение Telegram со всей телеметрией прогона: адрес https даёт
    туннель ngrok (основной), туннель Cloudflare или свой сервер;
  - копия каждого сохранённого журнала в сетевую папку или на сервер по SFTP.

  Всё это только для наблюдения: управлять прибором издалека нужно через
  удалённый рабочий стол. Настройки сохраняются в файл и включаются сами
  после перезапуска программы. Пояснения спрятаны в знаки «i».

  Публичные свойства:
  - appController: контроллер приложения;
  - textMain/textSoft: общая палитра окна;
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

    readonly property var remote: root.appController ? root.appController.remoteMonitor : ({})
    readonly property var levelShort: ({ "all": "Все", "important": "Важные", "alarms": "Аварии", "off": "Выкл" })
    readonly property var userOptions: [{ "key": "points", "title": "точки" }, { "key": "summaries", "title": "сводки" },
                                        { "key": "files", "title": "файлы" }]

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    // Поле настройки: показ обновляется раз в секунду, поэтому текст меняется,
    // только пока оператор в поле не печатает. Сохраняется по Enter и уходу из поля.
    component SettingField: FancyTextField {
        id: settingField
        // Имя поля в показе контроллера и имя настройки в файле.
        property string key: ""
        property string settingKey: ""
        readonly property string value: root.remote[settingField.key] !== undefined ? String(root.remote[settingField.key]) : ""
        Layout.preferredHeight: 32
        textColor: root.textMain
        bgColor: root.inputBg
        borderColor: root.inputBorder
        focusBorderColor: root.inputFocus
        onValueChanged: if (!settingField.activeFocus) settingField.text = settingField.value
        Component.onCompleted: settingField.text = settingField.value
        onEditingFinished: if (root.appController && settingField.text !== settingField.value)
                               root.appController.setRemoteSetting(settingField.settingKey, settingField.text)
    }

    component Caption: Text {
        color: root.textSoft
        font.pixelSize: 12
        font.family: "Bahnschrift"
        Layout.alignment: Qt.AlignVCenter
    }

    component Title: Text {
        color: root.textMain
        font.pixelSize: 14
        font.bold: true
        font.family: "Bahnschrift"
        Layout.alignment: Qt.AlignVCenter
    }

    component SmallButton: FancyButton {
        Layout.preferredHeight: 28
        fontPixelSize: 12
        tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
    }

    component StatusLine: RowLayout {
        id: statusLine
        property string text: ""
        property bool ok: false
        visible: statusLine.text.length > 0
        Layout.fillWidth: true
        spacing: 8

        Rectangle {
            Layout.alignment: Qt.AlignVCenter
            Layout.preferredWidth: 10
            Layout.preferredHeight: 10
            radius: 5
            color: statusLine.ok ? "#16a34a" : "#f59e0b"
        }

        Text {
            Layout.fillWidth: true
            text: statusLine.text
            color: root.textMain
            font.pixelSize: 12
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
        }
    }

    // Выбор уровня уведомлений: четыре кнопки, выбранная - синяя.
    component LevelPicker: RowLayout {
        id: levelPicker
        property string current: ""
        signal picked(string level)
        spacing: 4

        Repeater {
            model: root.remote.levels || []

            FancyButton {
                required property var modelData
                Layout.preferredWidth: 66
                Layout.preferredHeight: 26
                fontPixelSize: 11
                text: root.levelShort[modelData.key] || modelData.title
                toolTipText: modelData.title
                tone: levelPicker.current === modelData.key ? "#0284c7" : "#94a3b8"
                toneHover: "#0369a1"
                tonePressed: "#075985"
                onClicked: levelPicker.picked(modelData.key)
            }
        }
    }

    // Переключатель с подписью справа, маленький - для строк пользователей.
    component SmallSwitch: RowLayout {
        id: smallSwitch
        property string title: ""
        property bool checked: false
        property bool active: true
        signal toggled(bool checked)
        spacing: 4

        FancySwitch {
            trackWidth: 36
            trackHeight: 20
            enabled: smallSwitch.active
            checked: smallSwitch.checked
            onToggled: smallSwitch.toggled(checked)
        }
        Caption { text: smallSwitch.title; opacity: smallSwitch.active ? 1.0 : 0.5 }
    }

    component Block: Rectangle {
        default property alias content: blockLayout.data
        property bool enabledFlag: false
        Layout.fillWidth: true
        Layout.preferredHeight: blockLayout.implicitHeight + 20
        radius: 12
        color: enabledFlag ? "#f2f7ff" : "#f8fafc"
        border.width: 1
        border.color: enabledFlag ? "#c6dcf5" : "#e2e8f0"

        ColumnLayout {
            id: blockLayout
            anchors.fill: parent
            anchors.margins: 10
            spacing: 8
        }
    }

    // Пользователь бота: кто, доступ, уровень, переключатели, действия администратора.
    component UserRow: Rectangle {
        id: userRow
        required property var modelData
        readonly property bool isAdminChat: userRow.modelData.id === root.remote.telegramChat
        Layout.fillWidth: true
        Layout.preferredHeight: userLayout.implicitHeight + 12
        radius: 8
        color: userRow.modelData.approved ? "#ffffff" : "#fff7ed"
        border.width: 1
        border.color: userRow.modelData.approved ? "#e2e8f0" : "#fed7aa"

        RowLayout {
            id: userLayout
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 8
            spacing: 12

            ColumnLayout {
                Layout.preferredWidth: 210
                Layout.maximumWidth: 210
                spacing: 0

                Text {
                    Layout.fillWidth: true
                    text: (userRow.modelData.name || userRow.modelData.id) + (userRow.modelData.admin ? "  ★" : "")
                    color: root.textMain
                    font.pixelSize: 13
                    font.bold: true
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
                Text {
                    Layout.fillWidth: true
                    text: (userRow.modelData.username ? "@" + userRow.modelData.username + " · " : "")
                          + (userRow.modelData.admin ? "администратор" : userRow.modelData.approved ? "одобрен" : "ждёт одобрения")
                    color: userRow.modelData.approved ? root.textSoft : "#c2410c"
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }

            LevelPicker {
                current: userRow.modelData.level
                onPicked: (level) => { if (root.appController) root.appController.setRemoteUserLevel(userRow.modelData.id, level) }
            }

            Repeater {
                model: root.userOptions

                SmallSwitch {
                    required property var modelData
                    title: modelData.title
                    checked: userRow.modelData[modelData.key] === true
                    active: userRow.modelData.level !== "off"
                    onToggled: (checked) => {
                        if (root.appController) root.appController.setRemoteUserFlag(userRow.modelData.id, modelData.key, checked)
                    }
                }
            }

            Item { Layout.fillWidth: true }

            SmallButton {
                visible: !userRow.modelData.approved
                Layout.preferredWidth: 90
                text: "Одобрить"
                tone: "#16a34a"; toneHover: "#15803d"; tonePressed: "#166534"
                onClicked: if (root.appController) root.appController.remoteUserAction(userRow.modelData.id, "ok")
            }
            SmallButton {
                visible: !userRow.isAdminChat && userRow.modelData.approved
                Layout.preferredWidth: 80
                text: userRow.modelData.admin ? "− админ" : "+ админ"
                toolTipText: "Администратор одобряет заявки и видит пользователей в мини-приложении"
                onClicked: if (root.appController) root.appController.remoteUserAction(userRow.modelData.id, "ad")
            }
            SmallButton {
                visible: !userRow.isAdminChat
                Layout.preferredWidth: 80
                text: "Убрать"
                tone: "#ef4444"; toneHover: "#dc2626"; tonePressed: "#b91c1c"
                onClicked: if (root.appController) root.appController.remoteUserAction(userRow.modelData.id, "rm")
            }
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
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "Удалённое наблюдение"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                }
                InfoMark {
                    tip: "Прогон идёт на этом компьютере у камеры. Здесь включается то, что позволяет видеть его издалека: "
                         + "бот и мини-приложение в Telegram, копия журналов. Управлять прибором издалека - через удалённый "
                         + "рабочий стол.<br><br>Настройки хранятся в " + (root.remote.settingsPath || "")
                         + " и включаются сами после перезапуска программы."
                }
                Item { Layout.fillWidth: true }
            }

            // --- Бот Telegram ---
            Block {
                enabledFlag: root.remote.telegramEnabled === true

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    FancySwitch {
                        checked: root.remote.telegramEnabled === true
                        onToggled: if (root.appController) root.appController.setRemoteFlag("telegram_enabled", checked)
                    }
                    Title { text: "Бот Telegram" }
                    InfoMark {
                        tip: "<b>Как подключить</b><br>1. В Telegram найдите @BotFather, команда /newbot, впишите выданный токен.<br>"
                             + "2. Напишите своему боту /start и нажмите «Найти чат» - вы станете администратором.<br>"
                             + "3. Коллеги пишут боту /start: вам придёт заявка с кнопками «Одобрить» / «Отклонить». "
                             + "С кодом доступа («/start КОД») они подключатся сразу.<br><br>"
                             + "Каждый сам выбирает уровень уведомлений командой /settings или в мини-приложении."
                    }
                    Item { Layout.fillWidth: true }
                    SmallButton {
                        Layout.preferredWidth: 110
                        text: "Проверить"
                        tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                        toolTipText: "Пробное сообщение администратору"
                        onClicked: if (root.appController) root.appController.sendRemoteTelegramTest()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Caption { text: "Токен" }
                    SettingField { key: "telegramToken"; Layout.fillWidth: true; echoMode: activeFocus ? TextInput.Normal : TextInput.Password
                        placeholderText: "выдаёт @BotFather, вида 123456:ABC..."; settingKey: "telegram_token" }

                    Caption { text: "Администратор" }
                    SettingField { key: "telegramChat"; Layout.preferredWidth: 140; placeholderText: "номер чата"; settingKey: "telegram_chat" }

                    SmallButton {
                        Layout.preferredWidth: 100
                        text: "Найти чат"
                        toolTipText: "Берёт чат того, кто последним написал боту"
                        onClicked: if (root.appController) root.appController.findRemoteTelegramChat()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Caption { text: "Код доступа" }
                    SettingField { key: "telegramAccessCode"; Layout.preferredWidth: 110; placeholderText: "нет"
                        horizontalAlignment: TextInput.AlignHCenter; settingKey: "telegram_access_code" }
                    SmallButton {
                        Layout.preferredWidth: 100
                        text: "Новый код"
                        onClicked: if (root.appController) root.appController.newRemoteAccessCode()
                    }
                    InfoMark {
                        tip: "Кто пришлёт боту «/start КОД», подключится сразу, без одобрения. "
                             + "Пусто - только по одобрению администратора. Новый код не отключает уже подключённых."
                    }

                    Item { Layout.preferredWidth: 16 }

                    Caption { text: "Новым:" }
                    LevelPicker {
                        current: root.remote.telegramDefaultLevel || ""
                        onPicked: (level) => { if (root.appController) root.appController.setRemoteSetting("telegram_default_level", level) }
                    }
                    SmallSwitch {
                        title: "точки"
                        checked: root.remote.telegramPoints === true
                        onToggled: (checked) => { if (root.appController) root.appController.setRemoteFlag("telegram_points", checked) }
                    }
                    SmallSwitch {
                        title: "сводки"
                        checked: root.remote.telegramSummaries === true
                        onToggled: (checked) => { if (root.appController) root.appController.setRemoteFlag("telegram_summaries", checked) }
                    }
                    SmallSwitch {
                        title: "файлы"
                        checked: root.remote.telegramFiles === true
                        onToggled: (checked) => { if (root.appController) root.appController.setRemoteFlag("telegram_files", checked) }
                    }
                    InfoMark {
                        tip: "<b>Уровни уведомлений</b><br>Все - весь ход прогона.<br>"
                             + "Важные - выход на этапы, итоги, предупреждения и аварии.<br>"
                             + "Аварии - только беды: авария камеры, нет связи, прогон встал.<br>"
                             + "Выкл - ничего, только по запросу (/status, мини-приложение).<br><br>"
                             + "<b>Точки</b> - сообщение о каждой записанной точке. <b>Сводки</b> - ход прогона по расписанию. "
                             + "<b>Файлы</b> - журнал, профиль и отчёт диагностики в чат.<br><br>"
                             + "Здесь - что получит новый пользователь; потом каждый меняет своё сам."
                    }
                    Item { Layout.fillWidth: true }
                }

                StatusLine { text: root.remote.telegramStatus || ""; ok: root.remote.telegramOk === true }
            }

            // --- Пользователи бота ---
            Block {
                visible: root.remote.telegramEnabled === true
                enabledFlag: true

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Title { text: "Пользователи · " + (root.remote.users || []).length }
                    InfoMark {
                        tip: "Кто подключён к боту и что получает. ★ - администратор: одобряет заявки и видит этот список "
                             + "в мини-приложении. Администратора из настроек убрать нельзя."
                    }
                    Item { Layout.fillWidth: true }
                }

                Repeater {
                    model: root.remote.users || []
                    UserRow {}
                }

                Caption {
                    visible: (root.remote.users || []).length === 0
                    text: "Пока никого: пользователи появятся, когда напишут боту /start."
                }
            }

            // --- Мини-приложение ---
            Block {
                enabledFlag: root.remote.serverEnabled === true

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    FancySwitch {
                        checked: root.remote.serverEnabled === true
                        onToggled: if (root.appController) root.appController.setRemoteFlag("server_enabled", checked)
                    }
                    Title { text: "Мини-приложение в Telegram" }
                    InfoMark {
                        tip: "Кнопка «Камера» в боте открывает всё о прогоне: камера и плата, контуры, история, "
                             + "ход по узлам, проблемы, события, журналы в чат и свои настройки уведомлений.<br><br>"
                             + "Telegram открывает мини-приложение только по адресу https:// из интернета:<br>"
                             + "<b>ngrok</b> - основной: бесплатная учётная запись, постоянный адрес, работает по обычному "
                             + "https и проходит почти любую сеть;<br>"
                             + "<b>Cloudflare</b> - без регистрации, но адрес меняется при каждом запуске, нужен порт 7844, "
                             + "а при частых запусках Cloudflare временно отказывает (429);<br>"
                             + "<b>Свой адрес</b> - если есть сервер с https, проксирующий на порт этой программы.<br><br>"
                             + "Данные видят только одобренные в боте пользователи: каждый запрос подписан Telegram."
                    }
                    Item { Layout.fillWidth: true }

                    Repeater {
                        model: [{ "mode": "ngrok", "title": "ngrok" }, { "mode": "tunnel", "title": "Cloudflare" },
                                { "mode": "manual", "title": "Свой адрес" }]

                        FancyButton {
                            required property var modelData
                            Layout.preferredWidth: 110
                            Layout.preferredHeight: 28
                            fontPixelSize: 12
                            text: modelData.title
                            tone: root.remote.miniappMode === modelData.mode ? "#0284c7" : "#94a3b8"
                            toneHover: "#0369a1"
                            tonePressed: "#075985"
                            onClicked: if (root.appController) root.appController.setRemoteSetting("miniapp_mode", modelData.mode)
                        }
                    }

                    Caption { text: "Порт" }
                    SettingField { key: "serverPort"; Layout.preferredWidth: 70; horizontalAlignment: TextInput.AlignHCenter; settingKey: "server_port" }
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: root.remote.miniappMode === "ngrok"
                    spacing: 8

                    Caption { text: "ngrok" }
                    SettingField {
                        key: "ngrokPath"
                        Layout.fillWidth: true
                        placeholderText: root.remote.ngrokFound ? "найден: " + root.remote.ngrokFound
                                                                 : "не найден - укажите путь к ngrok.exe"
                        settingKey: "ngrok_path"
                    }
                    Caption { text: "Токен ngrok" }
                    SettingField {
                        key: "ngrokAuthtoken"
                        Layout.preferredWidth: 200
                        echoMode: activeFocus ? TextInput.Normal : TextInput.Password
                        placeholderText: root.remote.ngrokConfigured ? "уже записан в ngrok" : "Your Authtoken"
                        settingKey: "ngrok_authtoken"
                    }
                    Caption { text: "Адрес" }
                    SettingField { key: "ngrokDomain"; Layout.preferredWidth: 220; placeholderText: "выданный учётной записи"
                        settingKey: "ngrok_domain" }
                    InfoMark {
                        tip: "<b>Как подключить ngrok</b><br>"
                             + "1. Зарегистрируйтесь на ngrok.com (бесплатно).<br>"
                             + "2. Скачайте ngrok для Windows (ngrok.com/download), положите ngrok.exe рядом с программой "
                             + "или в папку tools - тогда путь можно не указывать.<br>"
                             + "3. Скопируйте «Your Authtoken» из кабинета ngrok в поле «Токен ngrok». Если токен уже "
                             + "записан командой «ngrok config add-authtoken», поле можно оставить пустым.<br><br>"
                             + "Адрес выдаётся учётной записи и не меняется (вида https://слова.ngrok-free.dev); поле "
                             + "«Адрес» - только для своего домена ngrok. Бесплатно одновременно работает один ngrok на "
                             + "учётную запись.<br><br>При самом первом открытии ngrok может показать страницу-предупреждение "
                             + "- нажмите «Visit Site», дальше она не появится."
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: root.remote.miniappMode === "tunnel"
                    spacing: 8

                    Caption { text: "cloudflared" }
                    SettingField {
                        key: "cloudflaredPath"
                        Layout.fillWidth: true
                        placeholderText: root.remote.cloudflaredFound ? "найден: " + root.remote.cloudflaredFound
                                                                       : "не найден - укажите путь к cloudflared.exe"
                        settingKey: "cloudflared_path"
                    }
                    InfoMark {
                        tip: "Программа туннеля Cloudflare. Скачайте cloudflared-windows-amd64.exe со страницы "
                             + "github.com/cloudflare/cloudflared/releases, переименуйте в cloudflared.exe и положите рядом "
                             + "с программой (или в папку tools) - тогда путь можно не указывать."
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: root.remote.miniappMode === "manual"
                    spacing: 8

                    Caption { text: "Адрес https" }
                    SettingField { key: "miniappUrl"; Layout.fillWidth: true; placeholderText: "https://camera.example.ru/app"; settingKey: "miniapp_url" }
                    Caption { text: "Ключ отладки" }
                    SettingField { key: "serverKey"; Layout.preferredWidth: 140; placeholderText: "закрыто"; settingKey: "server_key" }
                    SmallButton {
                        Layout.preferredWidth: 100
                        text: "Новый ключ"
                        onClicked: if (root.appController) root.appController.newRemoteServerKey()
                    }
                    InfoMark {
                        tip: "Адрес, по которому ваш сервер с https пересылает запросы на порт этой программы.<br><br>"
                             + "Ключ отладки открывает в сети снимок status.json?key=... для проверки; пусто - закрыто."
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: root.remote.serverEnabled === true
                    spacing: 8

                    Caption { text: "Открывается по" }
                    Text {
                        Layout.fillWidth: true
                        text: root.remote.publicUrl || "адреса пока нет"
                        color: root.remote.publicUrl ? "#0f6ab4" : root.textSoft
                        font.pixelSize: 13
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }
                    SmallButton {
                        visible: !!root.remote.publicUrl
                        Layout.preferredWidth: 100
                        text: "Копировать"
                        onClicked: if (root.appController) root.appController.copyTextToClipboard(root.remote.publicUrl)
                    }
                }

                StatusLine { text: root.remote.serverStatus || ""; ok: root.remote.serverOk === true }
                StatusLine {
                    visible: root.remote.miniappMode !== "manual" && (root.remote.tunnelStatus || "").length > 0
                    text: root.remote.tunnelStatus || ""
                    ok: root.remote.tunnelOk === true
                }
            }

            // --- Копия журналов ---
            Block {
                enabledFlag: root.remote.syncEnabled === true

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    FancySwitch {
                        checked: root.remote.syncEnabled === true
                        onToggled: if (root.appController) root.appController.setRemoteFlag("sync_enabled", checked)
                    }
                    Title { text: "Копия журналов на рабочее место" }
                    InfoMark {
                        tip: "Копируются журнал прогона после каждой точки, записанный профиль и раз в минуту журнал "
                             + "калибровки, если он пишется. Пропала сеть - копия догонит при следующем сохранении."
                    }
                    Item { Layout.fillWidth: true }

                    Repeater {
                        model: [{ "mode": "folder", "title": "Сетевая папка" }, { "mode": "sftp", "title": "SFTP" }]

                        FancyButton {
                            required property var modelData
                            Layout.preferredWidth: 130
                            Layout.preferredHeight: 28
                            fontPixelSize: 12
                            text: modelData.title
                            tone: root.remote.syncMode === modelData.mode ? "#0284c7" : "#94a3b8"
                            toneHover: "#0369a1"
                            tonePressed: "#075985"
                            onClicked: if (root.appController) root.appController.setRemoteSetting("sync_mode", modelData.mode)
                        }
                    }

                    SmallButton {
                        Layout.preferredWidth: 150
                        text: "Скопировать сейчас"
                        onClicked: if (root.appController) root.appController.syncRemoteNow()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: root.remote.syncMode !== "sftp"
                    spacing: 8

                    Caption { text: "Папка" }
                    SettingField { key: "syncFolder"; Layout.fillWidth: true; placeholderText: "например \\\\server\\share\\chamber или Z:\\chamber"; settingKey: "sync_folder" }
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: root.remote.syncMode === "sftp"
                    spacing: 8

                    Caption { text: "Сервер" }
                    SettingField { key: "syncHost"; Layout.fillWidth: true; settingKey: "sync_host" }
                    Caption { text: "Порт" }
                    SettingField { key: "syncPort"; Layout.preferredWidth: 70; settingKey: "sync_port" }
                    Caption { text: "Пользователь" }
                    SettingField { key: "syncUser"; Layout.preferredWidth: 130; settingKey: "sync_user" }
                    Caption { text: "Пароль" }
                    SettingField { key: "syncPassword"; Layout.preferredWidth: 130; echoMode: TextInput.Password; settingKey: "sync_password" }
                    Caption { text: "Папка" }
                    SettingField { key: "syncRemoteDir"; Layout.preferredWidth: 150; settingKey: "sync_remote_dir" }
                }

                StatusLine { text: root.remote.syncStatus || ""; ok: root.remote.syncOk === true }
            }

            // --- Состояние и события ---
            Block {
                enabledFlag: true

                Title { text: "Что видит наблюдение" }

                StatusLine { text: root.remote.stableText || ""; ok: root.remote.stableOk === true }

                Repeater {
                    model: root.remote.events || []

                    Text {
                        required property var modelData
                        Layout.fillWidth: true
                        text: modelData.time + "  " + modelData.text
                        color: modelData.level === "bad" ? "#dc2626" : modelData.level === "ok" ? "#15803d"
                             : modelData.level === "warn" ? "#b45309" : root.textMain
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }
                }

                Caption {
                    visible: (root.remote.events || []).length === 0
                    text: "Событий пока нет. Они появятся, когда включён бот или мини-приложение."
                }
            }
        }
    }
}
