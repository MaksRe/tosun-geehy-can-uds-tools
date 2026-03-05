import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

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
    readonly property bool controlsEnabled: root.appController
                                            ? (!root.appController.serviceAccessBusy
                                               && !root.appController.programmingActive
                                               && !root.appController.optionOperationBusy
                                               && !root.appController.sourceAddressBusy
                                               && !root.appController.calibrationActive)
                                            : false

    Layout.fillWidth: true
    implicitHeight: contentColumn.implicitHeight + (root.contentPadding * 2)

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: root.contentPadding
        spacing: 8

        Text {
            text: "Управление UDS доступом"
            visible: root.showCardHeader
            color: root.textMain
            font.pixelSize: 18
            font.bold: true
            font.family: "Bahnschrift"
        }

        Text {
            text: "Session Control 0x10 и Security Access 0x27 для подготовки записи 0x2E"
            visible: root.showCardHeader
            color: root.textSoft
            font.pixelSize: 12
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
        }

        Text {
            text: "Для проекта МК запись 0x2E требует Extended Session (0x03) и успешный Security Access."
            color: root.textSoft
            font.pixelSize: 11
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
        }

        Text {
            text: "Целевой узел UDS"
            color: root.textSoft
            font.pixelSize: 12
            font.family: "Bahnschrift"
        }

        FancyComboBox {
            Layout.fillWidth: true
            model: root.appController ? root.appController.optionsTargetNodeItems : []
            currentIndex: root.appController ? root.appController.selectedOptionsTargetNodeIndex : 0
            enabled: root.controlsEnabled
            textColor: root.textMain
            bgColor: root.inputBg
            borderColor: root.inputBorder
            focusBorderColor: root.inputFocus
            onActivated: if (root.appController) root.appController.setSelectedOptionsTargetNodeIndex(currentIndex)
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            FancyComboBox {
                Layout.fillWidth: true
                model: root.appController ? root.appController.serviceSessionItems : []
                currentIndex: root.appController ? root.appController.selectedServiceSessionIndex : 0
                enabled: root.controlsEnabled
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
                onActivated: if (root.appController) root.appController.setSelectedServiceSessionIndex(currentIndex)
            }

            FancyButton {
                Layout.preferredWidth: 170
                Layout.preferredHeight: 34
                text: root.appController && root.appController.serviceAccessBusy ? "Выполняется..." : "Установить 0x10"
                enabled: root.controlsEnabled
                tone: "#0284c7"
                toneHover: "#0369a1"
                tonePressed: "#075985"
                onClicked: if (root.appController) root.appController.applySelectedServiceSession()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            FancyButton {
                Layout.preferredWidth: 188
                Layout.preferredHeight: 34
                text: "Открыть доступ 0x27"
                enabled: root.controlsEnabled
                tone: "#0f766e"
                toneHover: "#115e59"
                tonePressed: "#134e4a"
                onClicked: if (root.appController) root.appController.requestSecurityAccess()
            }

            StatusChip {
                Layout.fillWidth: true
                label: root.appController && root.appController.serviceSecurityUnlocked ? "Security Access: открыт" : "Security Access: не открыт"
                chipColor: root.appController && root.appController.serviceSecurityUnlocked ? "#e7f8ef" : "#f4f8fd"
                chipBorder: root.appController && root.appController.serviceSecurityUnlocked ? "#88d4af" : "#c6d7ea"
                textColor: root.textMain
            }
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 10
            color: "#f7fbff"
            border.color: "#d6e2ef"
            border.width: 1
            implicitHeight: statusText.implicitHeight + 16

            Text {
                id: statusText
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 9
                anchors.rightMargin: 9
                text: root.appController ? root.appController.serviceAccessStatusText : "Ожидание контроллера"
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }
        }
    }
}
