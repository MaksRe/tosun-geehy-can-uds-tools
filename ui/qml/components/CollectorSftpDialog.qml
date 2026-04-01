import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

Popup {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"

    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    width: Math.min(860, Math.max(560, parent ? parent.width * 0.82 : 720))
    x: parent ? (parent.width - width) / 2 : 80
    y: parent ? Math.max(16, (parent.height - height) / 2) : 60
    padding: 0

    background: Rectangle {
        radius: 10
        color: "#ffffff"
        border.color: "#c9d9ea"
    }

    contentItem: ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                text: "Удаленная выгрузка CSV (SFTP, резерв)"
                color: root.textMain
                font.pixelSize: 14
                font.bold: true
                font.family: "Bahnschrift"
            }

            Item { Layout.fillWidth: true }

            Text {
                text: root.appController && root.appController.collectorSftpBusy ? "Выгрузка..." : "Ожидание"
                color: root.appController && root.appController.collectorSftpBusy ? "#0ea5e9" : root.textSoft
                font.pixelSize: 10
                font.family: "Bahnschrift"
            }

            FancySwitch {
                Layout.alignment: Qt.AlignVCenter
                trackWidth: 44
                trackHeight: 24
                checked: root.appController ? root.appController.collectorSftpEnabled : false
                onToggled: if (root.appController) root.appController.setCollectorSftpEnabled(checked)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 8
            color: "#f8fbff"
            border.color: "#d6e2ef"
            implicitHeight: sftpFormLayout.implicitHeight + 14

            ColumnLayout {
                id: sftpFormLayout
                anchors.fill: parent
                anchors.margins: 7
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    FancyTextField {
                        id: sftpHostField
                        Layout.preferredWidth: 180
                        Layout.preferredHeight: 30
                        placeholderText: "SFTP host"
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        text: root.appController ? root.appController.collectorSftpHost : ""
                        onAccepted: if (root.appController) root.appController.setCollectorSftpHost(text)
                    }

                    FancyTextField {
                        id: sftpPortField
                        Layout.preferredWidth: 82
                        Layout.preferredHeight: 30
                        placeholderText: "22"
                        validator: IntValidator { bottom: 1; top: 65535 }
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        text: root.appController ? String(root.appController.collectorSftpPort) : "22"
                        onAccepted: if (root.appController) root.appController.setCollectorSftpPort(text)
                    }

                    FancyTextField {
                        id: sftpUserField
                        Layout.preferredWidth: 144
                        Layout.preferredHeight: 30
                        placeholderText: "user"
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        text: root.appController ? root.appController.collectorSftpUsername : ""
                        onAccepted: if (root.appController) root.appController.setCollectorSftpUsername(text)
                    }

                    FancyTextField {
                        id: sftpPasswordField
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: 30
                        placeholderText: "password"
                        echoMode: TextInput.Password
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        text: root.appController ? root.appController.collectorSftpPassword : ""
                        onAccepted: if (root.appController) root.appController.setCollectorSftpPassword(text)
                    }

                    FancyTextField {
                        id: sftpRemoteDirField
                        Layout.fillWidth: true
                        Layout.preferredHeight: 30
                        placeholderText: "/incoming/csv"
                        textColor: root.textMain
                        bgColor: root.inputBg
                        borderColor: root.inputBorder
                        focusBorderColor: root.inputFocus
                        text: root.appController ? root.appController.collectorSftpRemoteDir : "/incoming/csv"
                        onAccepted: if (root.appController) root.appController.setCollectorSftpRemoteDir(text)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    FancyButton {
                        Layout.preferredWidth: 142
                        Layout.preferredHeight: 28
                        fontPixelSize: 11
                        text: "Применить SFTP"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        onClicked: if (root.appController) {
                            root.appController.setCollectorSftpHost(sftpHostField.text)
                            root.appController.setCollectorSftpPort(sftpPortField.text)
                            root.appController.setCollectorSftpUsername(sftpUserField.text)
                            root.appController.setCollectorSftpPassword(sftpPasswordField.text)
                            root.appController.setCollectorSftpRemoteDir(sftpRemoteDirField.text)
                        }
                    }

                    FancyButton {
                        Layout.preferredWidth: 184
                        Layout.preferredHeight: 28
                        fontPixelSize: 11
                        text: "Выгрузить текущую сессию"
                        tone: "#0ea5a4"
                        toneHover: "#0f766e"
                        tonePressed: "#115e59"
                        onClicked: if (root.appController) root.appController.uploadCollectorCurrentSessionToSftp()
                    }

                    Item { Layout.fillWidth: true }

                    FancyButton {
                        Layout.preferredWidth: 96
                        Layout.preferredHeight: 28
                        fontPixelSize: 11
                        text: "Закрыть"
                        tone: "#64748b"
                        toneHover: "#55657a"
                        tonePressed: "#465669"
                        onClicked: root.close()
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: root.appController ? root.appController.collectorSftpStatusText : "SFTP: не настроен."
            color: root.textSoft
            font.pixelSize: 10
            font.family: "Bahnschrift"
            wrapMode: Text.WordWrap
        }
    }

    Connections {
        target: root.appController

        function onCollectorSftpChanged() {
            if (!root.appController) {
                return
            }
            if (!sftpHostField.activeFocus)
                sftpHostField.text = root.appController.collectorSftpHost
            if (!sftpPortField.activeFocus)
                sftpPortField.text = String(root.appController.collectorSftpPort)
            if (!sftpUserField.activeFocus)
                sftpUserField.text = root.appController.collectorSftpUsername
            if (!sftpPasswordField.activeFocus)
                sftpPasswordField.text = root.appController.collectorSftpPassword
            if (!sftpRemoteDirField.activeFocus)
                sftpRemoteDirField.text = root.appController.collectorSftpRemoteDir
        }
    }
}
