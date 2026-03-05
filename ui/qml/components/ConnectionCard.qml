import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Карточка аппаратного подключения CAN-адаптера.
  Назначение:
  - сканирование доступных устройств;
  - подключение/отключение;
  - запуск/останов trace;
  - выбор канала, скорости и терминатора;
  - вывод краткой информации об адаптере.

  Контракт:
  - appController предоставляет методы scanDevices, toggleConnection, toggleTrace
    и свойства devices/selectedDeviceIndex/connected/traceActionText/connectionActionText.
*/
Card {
    id: root

    property var appController
    property bool showCardHeader: true
    property bool compactMode: false
    readonly property bool traceActive: root.appController ? root.appController.tracing : false
    readonly property bool canSettingsEditable: !root.traceActive
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"
    readonly property int contentPadding: root.compactMode ? 8 : 12
    readonly property int fieldLabelWidth: root.compactMode ? 66 : 84
    readonly property int controlHeight: root.compactMode ? 28 : 32
    readonly property int actionColumnWidth: root.compactMode ? 188 : 212

    Layout.fillWidth: true
    implicitHeight: contentColumn.implicitHeight + (root.contentPadding * 2)

    ColumnLayout {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: root.contentPadding
        anchors.rightMargin: root.contentPadding
        anchors.topMargin: root.contentPadding
        spacing: root.compactMode ? 5 : 8

        Text {
            text: "Аппаратное подключение"
            visible: root.showCardHeader
            color: root.textMain
            font.pixelSize: 20
            font.bold: true
            font.family: "Bahnschrift"
        }

        Text {
            text: "Выберите адаптер, подключитесь и запустите trace"
            visible: root.showCardHeader
            color: root.textSoft
            font.pixelSize: 12
            font.family: "Bahnschrift"
        }

        // Строка выбора физического USB/CAN устройства.
        RowLayout {
            Layout.fillWidth: true
            spacing: root.compactMode ? 8 : 12

            RowLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: root.compactMode ? 6 : 8

                Text {
                    text: "Устройство"
                    color: root.textSoft
                    font.pixelSize: root.compactMode ? 10 : 12
                    font.family: "Bahnschrift"
                    Layout.preferredWidth: root.fieldLabelWidth
                    horizontalAlignment: Text.AlignLeft
                    verticalAlignment: Text.AlignVCenter
                }

                FancyComboBox {
                    id: deviceCombo
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredHeight: root.controlHeight
                    model: root.appController ? root.appController.devices : []
                    currentIndex: root.appController ? root.appController.selectedDeviceIndex : -1
                    textColor: root.textMain
                    bgColor: root.inputBg
                    borderColor: root.inputBorder
                    focusBorderColor: root.inputFocus

                    onActivated: {
                        if (root.appController && root.appController.debugEnabled) {
                            console.log("[UI][ConnectionCard] device activated index:", currentIndex, "appController exists:", !!root.appController)
                        }
                        if (root.appController) {
                            if (root.appController.debugEnabled && root.appController.debugEvent) {
                                root.appController.debugEvent("UI: device index changed to " + currentIndex)
                            }
                            root.appController.setSelectedDeviceIndex(currentIndex)
                        } else {
                            console.error("[UI][ConnectionCard] appController is null in onActivated")
                        }
                    }
                }
            }

            FancyButton {
                Layout.preferredWidth: root.actionColumnWidth
                Layout.minimumWidth: root.actionColumnWidth
                Layout.preferredHeight: root.controlHeight
                text: "Сканировать"
                debugLog: root.appController ? root.appController.debugEnabled : false
                tone: "#0ea5a4"
                toneHover: "#0f766e"
                tonePressed: "#115e59"
                onClicked: {
                    if (root.appController && root.appController.debugEnabled) {
                        console.log("[UI][ConnectionCard] Scan clicked. appController exists:", !!root.appController)
                    }
                    if (root.appController) {
                        if (root.appController.debugEnabled && root.appController.debugEvent) {
                            root.appController.debugEvent("UI: Scan button clicked")
                        }
                        root.appController.scanDevices()
                    } else {
                        console.error("[UI][ConnectionCard] appController is null on Scan click")
                    }
                }
            }
        }

        // Параметры CAN слева, действия подключения справа (компактно по высоте).
        RowLayout {
            Layout.fillWidth: true
            spacing: root.compactMode ? 8 : 12

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.alignment: Qt.AlignTop
                spacing: root.compactMode ? 3 : 5
                opacity: root.canSettingsEditable ? 1.0 : 0.65

                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.compactMode ? 6 : 8

                    Text {
                        text: "Канал"
                        color: root.textSoft
                        font.pixelSize: root.compactMode ? 10 : 12
                        font.family: "Bahnschrift"
                        Layout.preferredWidth: root.fieldLabelWidth
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                    }

                    FancyComboBox {
                        id: channelCombo
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredHeight: root.controlHeight
                        model: ["Канал 1", "Канал 2", "Канал 3", "Канал 4"]
                        currentIndex: 0
                        enabled: root.canSettingsEditable
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.compactMode ? 6 : 8

                    Text {
                        text: "Скорость"
                        color: root.textSoft
                        font.pixelSize: root.compactMode ? 10 : 12
                        font.family: "Bahnschrift"
                        Layout.preferredWidth: root.fieldLabelWidth
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                    }

                    FancyComboBox {
                        id: baudCombo
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        Layout.preferredHeight: root.controlHeight
                        model: ["125", "250", "500", "1000"]
                        currentIndex: 2
                        enabled: root.canSettingsEditable
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.compactMode ? 6 : 8

                    Text {
                        text: "Терминатор"
                        color: root.textSoft
                        font.pixelSize: root.compactMode ? 10 : 12
                        font.family: "Bahnschrift"
                        Layout.preferredWidth: root.fieldLabelWidth
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                    }

                    Rectangle {
                        Layout.preferredWidth: root.compactMode ? 84 : 96
                        Layout.minimumWidth: root.compactMode ? 84 : 96
                        Layout.preferredHeight: root.controlHeight
                        implicitHeight: root.controlHeight
                        radius: root.compactMode ? 7 : 9
                        color: root.inputBg
                        border.color: root.inputBorder
                        border.width: 1

                        Item {
                            anchors.fill: parent

                            // Аппаратный терминатор (обычно 120 Ом), если поддерживается адаптером.
                            FancySwitch {
                                id: terminatorSwitch
                                anchors.centerIn: parent
                                trackWidth: root.compactMode ? 38 : 42
                                trackHeight: root.compactMode ? 20 : 23
                                enabled: root.canSettingsEditable
                                onColor: "#0ea5e9"
                                offColor: "#e4ecf7"
                                borderOnColor: "#0284c7"
                                borderOffColor: "#c0d1e4"
                                checked: true
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.preferredWidth: root.actionColumnWidth
                Layout.minimumWidth: root.actionColumnWidth
                Layout.alignment: Qt.AlignTop
                spacing: root.compactMode ? 4 : 6

                FancyButton {
                    Layout.fillWidth: true
                    Layout.preferredHeight: root.controlHeight
                    text: root.appController ? root.appController.connectionActionText : "Подключиться"
                    tone: "#3b82f6"
                    toneHover: "#2563eb"
                    tonePressed: "#1d4ed8"
                    onClicked: if (root.appController) root.appController.toggleConnection()
                }

                FancyButton {
                    Layout.fillWidth: true
                    Layout.preferredHeight: root.controlHeight
                    text: root.appController ? root.appController.traceActionText : "Запустить трассировку"
                    enabled: root.appController ? root.appController.connected : false
                    tone: "#16a34a"
                    toneHover: "#15803d"
                    tonePressed: "#166534"
                    onClicked: {
                        if (root.appController) {
                            root.appController.toggleTrace(channelCombo.currentIndex, parseInt(baudCombo.currentText), terminatorSwitch.checked)
                        }
                    }
                }
            }
        }

        // Техническая информация о выбранном устройстве.
        Rectangle {
            visible: !root.compactMode
            Layout.fillWidth: true
            Layout.preferredHeight: infoGrid.implicitHeight + 14
            radius: 10
            color: "#f4f8fd"
            border.color: "#d6e2ef"

            GridLayout {
                id: infoGrid
                anchors.fill: parent
                anchors.margins: 8
                columns: 1
                rowSpacing: 4

                LabelValue {
                    labelText: "Производитель"
                    valueText: root.appController ? root.appController.manufacturer : ""
                    labelColor: root.textSoft
                    valueColor: root.textMain
                    labelWidth: 160
                }

                LabelValue {
                    labelText: "Модель"
                    valueText: root.appController ? root.appController.product : ""
                    labelColor: root.textSoft
                    valueColor: root.textMain
                    labelWidth: 160
                }

                LabelValue {
                    labelText: "Серийный номер"
                    valueText: root.appController ? root.appController.serial : ""
                    labelColor: root.textSoft
                    valueColor: root.textMain
                    labelWidth: 160
                }

                LabelValue {
                    labelText: "Идентификатор устройства"
                    valueText: root.appController ? root.appController.deviceHandle : ""
                    labelColor: root.textSoft
                    valueColor: root.textMain
                    labelWidth: 160
                }
            }
        }
    }
}
