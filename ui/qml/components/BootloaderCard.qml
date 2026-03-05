import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Карточка управления UDS bootloader-процессом.
  Назначение:
  - выбор BIN-файла;
  - запуск программирования и сервисные команды reset/check;
  - отображение прогресса передачи;
  - отображение журнала состояний.

  Контракт:
  - appController предоставляет методы startProgramming/checkState/resetToBootloader/
    resetToMainProgram/clearLogs и свойства firmwarePath/progressValue/progressMax/logs/programmingActive.

  Сигналы:
  - openFirmwareDialogRequested: пробрасывается в Main.qml,
    где открывается FileDialog (чтобы диалог был в одном месте).
*/
Card {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"
    readonly property int contentPadding: 14
    readonly property bool serviceControlsEnabled: root.appController
                                                   ? (!root.appController.programmingActive
                                                      && !root.appController.firmwareLoading)
                                                   : false

    signal openFirmwareDialogRequested()

    Layout.fillWidth: true
    Layout.fillHeight: true
    implicitHeight: contentColumn.implicitHeight + (root.contentPadding * 2)

    ColumnLayout {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: root.contentPadding
        anchors.rightMargin: root.contentPadding
        anchors.topMargin: root.contentPadding
        anchors.bottomMargin: root.contentPadding
        spacing: 10

        Text {
            text: "Программирование"
            color: root.textMain
            font.pixelSize: 20
            font.bold: true
            font.family: "Bahnschrift"
        }

        Text {
            text: "Загрузите BIN, запустите программирование и контролируйте процесс"
            color: root.textSoft
            font.pixelSize: 12
            font.family: "Bahnschrift"
        }

        // Выбор прошивки и показ текущего пути к файлу.
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            FancyTextField {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: root.appController ? root.appController.firmwarePath : ""
                readOnly: true
                placeholderText: "BIN-файл не выбран"
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
            }

            FancyButton {
                Layout.preferredWidth: 158
                Layout.minimumWidth: 146
                text: root.appController && root.appController.firmwareLoading ? "Загрузка BIN..." : "Открыть BIN"
                loading: root.appController ? root.appController.firmwareLoading : false
                debugLog: root.appController ? root.appController.debugEnabled : false
                tone: "#d97706"
                toneHover: "#b45309"
                tonePressed: "#92400e"
                onClicked: {
                    if (root.appController && root.appController.debugEnabled) {
                        console.log("[UI][BootloaderCard] Open BIN clicked. appController exists:", !!root.appController)
                    }
                    if (root.appController && root.appController.debugEnabled && root.appController.debugEvent) {
                        root.appController.debugEvent("UI: Open BIN clicked")
                    }
                    if (!root.appController) {
                        console.error("[UI][BootloaderCard] appController is null on Open BIN click")
                    }
                    root.openFirmwareDialogRequested()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 18 : 0
            spacing: 6
            visible: root.appController ? root.appController.firmwareLoading : false
            opacity: visible ? 1 : 0

            Behavior on opacity {
                NumberAnimation {
                    duration: 140
                    easing.type: Easing.OutCubic
                }
            }

            Item {
                id: firmwareBusySpinner
                width: 14
                height: 14
                rotation: 0

                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: "transparent"
                    border.width: 2
                    border.color: "#0ea5e9"
                    opacity: 0.35
                }

                Rectangle {
                    width: 4
                    height: 4
                    radius: 2
                    color: "#1d4ed8"
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.top
                }

                RotationAnimator on rotation {
                    running: firmwareBusySpinner.visible
                    loops: Animation.Infinite
                    from: 0
                    to: 360
                    duration: 760
                }
            }

            Text {
                text: "Чтение BIN файла, подождите..."
                color: "#2563eb"
                font.pixelSize: 12
                font.family: "Bahnschrift"
            }

            Item {
                Layout.fillWidth: true
            }
        }

        // Основные действия по программированию и диагностике.
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: "Автосброс в загрузчик перед программированием"
                color: root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }

            FancySwitch {
                checked: root.appController ? root.appController.autoResetBeforeProgramming : true
                enabled: root.appController ? !root.appController.programmingActive : false
                onToggled: if (root.appController) root.appController.setAutoResetBeforeProgramming(checked)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            FancyButton {
                Layout.fillWidth: true
                text: root.appController && root.appController.programmingActive ? "Идет загрузка..." : "Начать программирование"
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                enabled: root.appController ? (!root.appController.programmingActive && !root.appController.firmwareLoading) : false
                tone: "#10b981"
                toneHover: "#059669"
                tonePressed: "#047857"
                onClicked: if (root.appController) root.appController.startProgramming()
            }
        }

        // Быстрые reset-команды ЭБУ.
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            FancyButton {
                Layout.fillWidth: true
                text: "Проверить статус"
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                enabled: root.serviceControlsEnabled
                tone: "#3b82f6"
                toneHover: "#2563eb"
                tonePressed: "#1d4ed8"
                onClicked: if (root.appController) root.appController.checkState()
            }

            FancyButton {
                Layout.fillWidth: true
                text: "Сброс в загрузчик"
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                enabled: root.serviceControlsEnabled
                tone: "#14b8a6"
                toneHover: "#0d9488"
                tonePressed: "#0f766e"
                onClicked: if (root.appController) root.appController.resetToBootloader()
            }

            FancyButton {
                Layout.fillWidth: true
                text: "Сброс в основное ПО"
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                enabled: root.serviceControlsEnabled
                tone: "#6366f1"
                toneHover: "#4f46e5"
                tonePressed: "#4338ca"
                onClicked: if (root.appController) root.appController.resetToMainProgram()
            }
        }

        // Виджет прогресса передачи данных в bootloader.
        Rectangle {
            Layout.fillWidth: true
            radius: 10
            color: "#f4f8fd"
            border.color: "#d6e2ef"
            implicitHeight: 78

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 4

                FancyProgressBar {
                    Layout.fillWidth: true
                    from: 0
                    to: root.appController ? root.appController.progressMax : 1
                    value: root.appController ? root.appController.progressValue : 0
                }

                RowLayout {
                    Layout.fillWidth: true

                    Text {
                        text: {
                            if (!root.appController) {
                                return "0 / 0 байт"
                            }
                            return root.appController.progressValue + " / " + root.appController.progressMax + " байт"
                        }
                        color: root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        text: {
                            if (!root.appController || root.appController.progressMax <= 0) {
                                return "0%"
                            }
                            return Math.round((root.appController.progressValue / root.appController.progressMax) * 100) + "%"
                        }
                        color: root.textMain
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        font.bold: true
                    }
                }
            }
        }

        // Журнал состояния bootloader-сценария.
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 210
            radius: 12
            color: "#f4f8fd"
            border.color: "#d6e2ef"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 6

                ListView {
                    id: logList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 4
                    model: root.appController ? root.appController.logs : []

                    // Автоскролл к последнему сообщению.
                    onCountChanged: if (count > 0) positionViewAtEnd()

                    delegate: Rectangle {
                        width: logList.width
                        height: logText.implicitHeight + 8
                        radius: 8
                        color: index % 2 === 0 ? "#f8fbff" : "#edf3fa"

                        Text {
                            id: logText
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            text: modelData.time + "   " + modelData.text
                            color: modelData.color
                            wrapMode: Text.Wrap
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                        }
                    }

                    ScrollBar.vertical: ScrollBar {}
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    Text {
                        text: "Записей: " + (root.appController ? root.appController.logs.length : 0)
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                    }

                    Item { Layout.fillWidth: true }

                    FancyButton {
                        text: "Очистить"
                        Layout.preferredWidth: 98
                        Layout.minimumWidth: 88
                        Layout.preferredHeight: 30
                        fontPixelSize: 12
                        tone: "#64748b"
                        toneHover: "#55657a"
                        tonePressed: "#465669"
                        onClicked: if (root.appController) root.appController.clearLogs()
                    }
                }
            }
        }
    }
}
