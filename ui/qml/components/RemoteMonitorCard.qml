import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Раздел «Удалённое наблюдение».
  Назначение:
  - страница состояния прогона для браузера на рабочем месте и в телефоне;
  - сообщения о важном в Telegram: плата устоялась, точка записана, прибор замолчал;
  - копия каждого сохранённого журнала в сетевую папку или на сервер по SFTP.

  Всё это только для наблюдения: управлять прибором издалека нужно через
  удалённый рабочий стол. Настройки сохраняются в файл и включаются сами
  после перезапуска программы.

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

    readonly property var remote: root.appController ? root.appController.remoteMonitor : ({})

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

    component StatusLine: RowLayout {
        id: statusLine
        property string text: ""
        property bool ok: false
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

    component Block: Rectangle {
        default property alias content: blockLayout.data
        property string title: ""
        property bool enabledFlag: false
        property string flagKey: ""
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
                    text: "Удалённое наблюдение"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                Text {
                    Layout.fillWidth: true
                    text: "Прогон идёт на этом компьютере у камеры. Здесь включается то, что позволяет видеть его с рабочего места: "
                          + "страница в браузере, сообщения в Telegram и копия журналов. Управлять прибором издалека - через удалённый рабочий стол."
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }
            }

            // --- Страница состояния ---
            Block {
                enabledFlag: root.remote.serverEnabled === true

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    FancySwitch {
                        checked: root.remote.serverEnabled === true
                        onToggled: if (root.appController) root.appController.setRemoteFlag("server_enabled", checked)
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Страница состояния в браузере"
                        color: root.textMain
                        font.pixelSize: 14
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Caption { text: "Порт" }
                    SettingField { key: "serverPort"; Layout.preferredWidth: 80; horizontalAlignment: TextInput.AlignHCenter; settingKey: "server_port" }

                    Caption { text: "Ключ доступа" }
                    SettingField { key: "serverKey"; Layout.preferredWidth: 170; placeholderText: "без ключа"; settingKey: "server_key" }

                    FancyButton {
                        Layout.preferredWidth: 110
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Новый ключ"
                        tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
                        toolTipText: "Без ключа в адресе страница не откроется: посторонний в сети её не увидит"
                        onClicked: if (root.appController) root.appController.newRemoteServerKey()
                    }
                }

                StatusLine { text: root.remote.serverStatus || ""; ok: root.remote.serverOk === true }

                Repeater {
                    model: root.remote.serverUrls || []

                    RowLayout {
                        required property string modelData
                        Layout.fillWidth: true
                        spacing: 8

                        Text {
                            Layout.fillWidth: true
                            text: parent.modelData
                            color: "#0f6ab4"
                            font.pixelSize: 13
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }

                        FancyButton {
                            Layout.preferredWidth: 90
                            Layout.preferredHeight: 26
                            fontPixelSize: 11
                            text: "Открыть"
                            tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                            onClicked: Qt.openUrlExternally(parent.modelData)
                        }

                        FancyButton {
                            Layout.preferredWidth: 110
                            Layout.preferredHeight: 26
                            fontPixelSize: 11
                            text: "Копировать"
                            tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
                            onClicked: if (root.appController) root.appController.copyTextToClipboard(parent.modelData)
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    visible: root.remote.serverEnabled === true
                    text: "Адрес открывается с любого компьютера или телефона в той же сети (или через VPN). "
                          + "При первом запуске Windows может спросить разрешение для брандмауэра - разрешите для рабочей сети."
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }
            }

            // --- Telegram ---
            Block {
                enabledFlag: root.remote.telegramEnabled === true

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    FancySwitch {
                        checked: root.remote.telegramEnabled === true
                        onToggled: if (root.appController) root.appController.setRemoteFlag("telegram_enabled", checked)
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Сообщения в Telegram"
                        color: root.textMain
                        font.pixelSize: 14
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    FancySwitch {
                        checked: root.remote.telegramPoints === true
                        onToggled: if (root.appController) root.appController.setRemoteFlag("telegram_points", checked)
                    }
                    Caption { text: "о каждой точке" }

                    FancySwitch {
                        checked: root.remote.telegramFiles === true
                        onToggled: if (root.appController) root.appController.setRemoteFlag("telegram_files", checked)
                    }
                    Caption { text: "журнал и профиль после записи" }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Caption { text: "Токен бота" }
                    SettingField { key: "telegramToken"; Layout.fillWidth: true; echoMode: activeFocus ? TextInput.Normal : TextInput.Password
                        placeholderText: "выдаёт @BotFather, вида 123456:ABC..."; settingKey: "telegram_token" }

                    Caption { text: "Номер чата" }
                    SettingField { key: "telegramChat"; Layout.preferredWidth: 150; settingKey: "telegram_chat" }

                    FancyButton {
                        Layout.preferredWidth: 110
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Найти чат"
                        tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
                        toolTipText: "Сначала напишите своему боту любое сообщение"
                        onClicked: if (root.appController) root.appController.findRemoteTelegramChat()
                    }

                    FancyButton {
                        Layout.preferredWidth: 110
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        text: "Проверить"
                        tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                        toolTipText: "Отправляет пробное сообщение"
                        onClicked: if (root.appController) root.appController.sendRemoteTelegramTest()
                    }
                }

                StatusLine { text: root.remote.telegramStatus || ""; ok: root.remote.telegramOk === true }

                Text {
                    Layout.fillWidth: true
                    text: "Как подключить: в Telegram найдите @BotFather, команда /newbot, впишите выданный токен. "
                          + "Напишите своему боту любое сообщение и нажмите «Найти чат». Для общего чата добавьте бота в группу и напишите в ней."
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
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

                    Text {
                        Layout.fillWidth: true
                        text: "Копия журналов на рабочее место"
                        color: root.textMain
                        font.pixelSize: 14
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

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

                    FancyButton {
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: 28
                        fontPixelSize: 12
                        text: "Скопировать сейчас"
                        tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
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

                Text {
                    Layout.fillWidth: true
                    text: "Копируются журнал прогона после каждой точки, записанный профиль и раз в минуту журнал калибровки, если он пишется. "
                          + "Пропала сеть - копия догонит при следующем сохранении."
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }
            }

            // --- Состояние и события ---
            Block {
                enabledFlag: true

                Text {
                    text: "Что видит наблюдение"
                    color: root.textMain
                    font.pixelSize: 14
                    font.bold: true
                    font.family: "Bahnschrift"
                }

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

                Text {
                    visible: (root.remote.events || []).length === 0
                    text: "Событий пока нет. Они появятся, когда включена страница или Telegram."
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                }
            }

            Text {
                Layout.fillWidth: true
                text: "Настройки хранятся в " + (root.remote.settingsPath || "") + " и включаются сами после перезапуска программы."
                color: root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
                elide: Text.ElideLeft
            }
        }
    }
}
