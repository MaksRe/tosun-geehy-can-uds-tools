import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Карточка параметров протокола UDS.
  Назначение:
  - изменение Source Address (CAN SA) через WriteDataById;
  - выбор порядка байтов для передачи блоков bootloader-сессии.
*/
Card {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"
    property bool showCardHeader: false
    readonly property int contentPadding: 12
    readonly property bool sourceAddressWriteBusy: root.appController ? (root.appController.sourceAddressBusy && root.appController.sourceAddressOperation === "write") : false
    readonly property bool sourceAddressReadBusy: root.appController ? (root.appController.sourceAddressBusy && root.appController.sourceAddressOperation === "read") : false
    readonly property bool communicationControlBusy: root.appController ? root.appController.communicationControlBusy : false

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
        spacing: 8

        Text {
            text: "Параметры протокола"
            visible: root.showCardHeader
            color: root.textMain
            font.pixelSize: 18
            font.bold: true
            font.family: "Bahnschrift"
        }

        Text {
            text: "Изменение Source Address и порядка байтов UDS"
            visible: root.showCardHeader
            color: root.textSoft
            font.pixelSize: 12
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
        }

        Text {
            text: "Адрес источника (Source Address, SA)"
            color: root.textSoft
            font.pixelSize: 12
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            FancyTextField {
                id: sourceAddressField
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.minimumWidth: 0
                text: root.appController ? root.appController.sourceAddressText : "0x6A"
                placeholderText: "0x6A"
                enabled: root.appController ? (!root.appController.sourceAddressBusy && !root.appController.programmingActive) : false
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
                onTextEdited: if (root.appController) root.appController.setSourceAddressText(text)
            }

            FancyButton {
                Layout.preferredWidth: 146
                Layout.minimumWidth: 136
                text: root.sourceAddressWriteBusy ? "Применение..." : "Применить SA"
                loading: root.sourceAddressWriteBusy
                enabled: root.appController ? (!root.appController.sourceAddressBusy && !root.appController.programmingActive) : false
                tone: "#0ea5a4"
                toneHover: "#0f766e"
                tonePressed: "#115e59"
                onClicked: if (root.appController) root.appController.applySourceAddress(sourceAddressField.text)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Item {
                Layout.fillWidth: true
            }

            FancyButton {
                Layout.fillWidth: false
                text: root.sourceAddressReadBusy ? "Чтение..." : "Прочитать SA"
                enabled: root.appController ? (!root.appController.sourceAddressBusy && !root.appController.programmingActive) : false
                loading: root.sourceAddressReadBusy
                Layout.preferredWidth: 146
                Layout.minimumWidth: 136
                tone: "#2563eb"
                toneHover: "#1d4ed8"
                tonePressed: "#1e40af"
                onClicked: if (root.appController) root.appController.readSourceAddress()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 10
            color: "#f7fbff"
            border.color: "#d6e2ef"
            border.width: 1
            implicitHeight: sourceAddressStatusText.implicitHeight + 16

            Text {
                id: sourceAddressStatusText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 9
                anchors.rightMargin: 9
                text: root.appController ? root.appController.sourceAddressStatusText : "Ожидание контроллера"
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1
            color: "#e5edf6"
        }

        Text {
            text: "Блокировка трафика (SID 0x28)"
            color: root.textSoft
            font.pixelSize: 12
            font.family: "Bahnschrift"
            Layout.fillWidth: true
        }

        Text {
            text: "Управление RX/TX обычного J1939/CAN-трафика с сохранением UDS-диагностики. Отдельного Network Management в изделии нет."
            color: root.textSoft
            font.pixelSize: 11
            font.family: "Bahnschrift"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 8
            rowSpacing: 8

            Text {
                text: "Адресация"
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                Layout.alignment: Qt.AlignVCenter
            }

            FancyComboBox {
                Layout.fillWidth: true
                model: root.appController ? root.appController.communicationControlAddressingItems : []
                currentIndex: root.appController ? root.appController.selectedCommunicationControlAddressingIndex : 0
                enabled: root.appController ? (!root.communicationControlBusy && !root.appController.programmingActive) : false
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
                onActivated: if (root.appController) root.appController.setSelectedCommunicationControlAddressingIndex(currentIndex)
            }

            Text {
                text: "Режим RX/TX"
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                Layout.alignment: Qt.AlignVCenter
            }

            FancyComboBox {
                Layout.fillWidth: true
                model: root.appController ? root.appController.communicationControlModeItems : []
                currentIndex: root.appController ? root.appController.selectedCommunicationControlModeIndex : 0
                enabled: root.appController ? (!root.communicationControlBusy && !root.appController.programmingActive) : false
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
                onActivated: if (root.appController) root.appController.setSelectedCommunicationControlModeIndex(currentIndex)
            }

            Text {
                text: "Тип сообщений"
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                Layout.alignment: Qt.AlignVCenter
            }

            FancyComboBox {
                Layout.fillWidth: true
                model: root.appController ? root.appController.communicationControlTypeItems : []
                currentIndex: root.appController ? root.appController.selectedCommunicationControlTypeIndex : 0
                enabled: root.appController ? (!root.communicationControlBusy && !root.appController.programmingActive) : false
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
                onActivated: if (root.appController) root.appController.setSelectedCommunicationControlTypeIndex(currentIndex)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            CheckBox {
                checked: root.appController ? root.appController.communicationControlSuppressPositiveResponse : false
                enabled: root.appController ? (!root.communicationControlBusy && !root.appController.programmingActive) : false
                onToggled: if (root.appController) root.appController.setCommunicationControlSuppressPositiveResponse(checked)
            }

            Text {
                Layout.fillWidth: true
                text: "Без положительного ответа МК (бит 0x80 в подфункции)"
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            FancyButton {
                Layout.preferredWidth: 168
                Layout.minimumWidth: 152
                text: root.communicationControlBusy ? "Отправка..." : "Применить 0x28"
                loading: root.communicationControlBusy
                enabled: root.appController ? (!root.communicationControlBusy && !root.appController.programmingActive) : false
                tone: "#0b8f7a"
                toneHover: "#0f766e"
                tonePressed: "#115e59"
                onClicked: if (root.appController) root.appController.applyCommunicationControl()
            }

            FancyButton {
                Layout.preferredWidth: 196
                Layout.minimumWidth: 170
                text: "Снять блокировку RX/TX"
                enabled: root.appController ? (!root.communicationControlBusy && !root.appController.programmingActive) : false
                tone: "#2563eb"
                toneHover: "#1d4ed8"
                tonePressed: "#1e40af"
                onClicked: if (root.appController) root.appController.applyCommunicationControlEnableAll()
            }

            Item {
                Layout.fillWidth: true
            }
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 10
            color: "#f7fbff"
            border.color: "#d6e2ef"
            border.width: 1
            implicitHeight: communicationStatusText.implicitHeight + 16

            Text {
                id: communicationStatusText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 9
                anchors.rightMargin: 9
                text: root.appController ? root.appController.communicationControlStatusText : "Ожидание контроллера"
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1
            color: "#e5edf6"
        }

        Text {
            text: "Порядок байтов при передаче"
            color: root.textSoft
            font.pixelSize: 12
            font.family: "Bahnschrift"
            Layout.fillWidth: true
        }

        FancyComboBox {
            id: endianCombo
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            model: ["Big Endian (старший байт первым)", "Little Endian (младший байт первым)"]
            currentIndex: root.appController ? root.appController.transferByteOrderIndex : 0
            enabled: root.appController ? (!root.appController.programmingActive && !root.appController.sourceAddressBusy) : false
            textColor: root.textMain
            bgColor: root.inputBg
            borderColor: root.inputBorder
            focusBorderColor: root.inputFocus

            onActivated: if (root.appController) root.appController.setTransferByteOrderIndex(currentIndex)
        }

    }

    Connections {
        target: root.appController

        function onSourceAddressTextChanged() {
            if (!root.appController) {
                return
            }
            if (sourceAddressField.text !== root.appController.sourceAddressText) {
                sourceAddressField.text = root.appController.sourceAddressText
            }
        }
    }
}
