import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import QtQuick.Window 2.15
import "components"

ApplicationWindow {
    id: window

    visible: true
    width: 1440
    height: 920
    minimumWidth: 1100
    minimumHeight: 760
    title: "TOSUN Geehy CAN UDS Tools"

    readonly property color bgStart: "#f9fcff"
    readonly property color bgEnd: "#edf4fb"
    readonly property color cardColor: "#ffffff"
    readonly property color cardBorder: "#d6e2ef"
    readonly property color textMain: "#1f2d3d"
    readonly property color textSoft: "#607084"
    readonly property color inputBg: "#f6faff"
    readonly property color inputBorder: "#c8d9ea"
    readonly property color inputFocus: "#0ea5e9"
    readonly property var backendController: appController
    readonly property int bottomStatusBarHeight: 44

    property string toastTitle: ""
    property string toastText: ""
    property bool toastVisible: false

    function showToast(title, text) {
        toastTitle = title ? title : ""
        toastText = text ? text : ""
        toastVisible = true
        toastTimer.restart()
    }

    function raiseToolWindow(targetWindow) {
        if (!targetWindow) {
            return
        }
        targetWindow.visible = true
        targetWindow.raise()
        targetWindow.requestActivate()
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: window.bgStart }
            GradientStop { position: 1.0; color: window.bgEnd }
        }

        Rectangle {
            width: 420
            height: width
            radius: width / 2
            x: -130
            y: -180
            color: "#60a5fa"
            opacity: 0.16
        }

        Rectangle {
            width: 560
            height: width
            radius: width / 2
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: -240
            color: "#14b8a6"
            opacity: 0.11
        }
    }

    Timer {
        id: toastTimer
        interval: 2600
        repeat: false
        onTriggered: window.toastVisible = false
    }

    Rectangle {
        id: toast
        z: 1000
        width: Math.min(window.width - 40, 560)
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.topMargin: 14
        radius: 12
        color: "#ffffff"
        border.color: "#bfd6eb"
        border.width: 1
        opacity: window.toastVisible ? 1 : 0
        visible: opacity > 0

        Behavior on opacity {
            NumberAnimation {
                duration: 180
                easing.type: Easing.OutCubic
            }
        }

        Column {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 4

            Text {
                text: window.toastTitle
                color: window.textMain
                font.pixelSize: 14
                font.bold: true
                font.family: "Bahnschrift"
            }

            Text {
                text: window.toastText
                color: window.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
                width: parent.width
            }
        }
    }

    Connections {
        target: window.backendController

        function onInfoMessage(title, text) {
            window.showToast(title, text)
        }
    }

    FileDialog {
        id: firmwareDialog
        title: "Выберите BIN-файл"
        nameFilters: ["BIN файлы (*.bin)", "Все файлы (*)"]

        onAccepted: {
            var chosen = ""
            if (selectedFile) {
                chosen = selectedFile.toString()
            } else if (selectedFiles && selectedFiles.length > 0) {
                chosen = selectedFiles[0].toString()
            } else if (currentFile) {
                chosen = currentFile.toString()
            }

            if (window.backendController) {
                window.backendController.loadFirmware(chosen)
            }
        }
    }

    FolderDialog {
        id: collectorDirDialog
        title: "Выберите каталог для CSV"

        onAccepted: {
            if (!window.backendController) {
                return
            }
            var selected = selectedFolder ? selectedFolder.toString() : (currentFolder ? currentFolder.toString() : "")
            window.backendController.setCollectorOutputDirectory(selected)
        }
    }

    Window {
        id: canJournalWindow
        width: 1440
        height: 920
        minimumWidth: 1180
        minimumHeight: 640
        visible: false
        modality: Qt.NonModal
        transientParent: window
        title: "Журнал CAN"

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: window.bgStart }
                GradientStop { position: 1.0; color: window.bgEnd }
            }
        }

        CanTrafficCard {
            anchors.fill: parent
            anchors.margins: 14
            appController: window.backendController
            textMain: window.textMain
            textSoft: window.textSoft
        }
    }

    Window {
        id: bootloaderWindow
        width: 980
        height: 860
        minimumWidth: 860
        minimumHeight: 720
        visible: false
        modality: Qt.NonModal
        transientParent: window
        title: "Программирование"

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: window.bgStart }
                GradientStop { position: 1.0; color: window.bgEnd }
            }
        }

        BootloaderCard {
            anchors.fill: parent
            anchors.margins: 14
            appController: window.backendController
            cardColor: window.cardColor
            cardBorder: window.cardBorder
            textMain: window.textMain
            textSoft: window.textSoft
            inputBg: window.inputBg
            inputBorder: window.inputBorder
            inputFocus: window.inputFocus
            onOpenFirmwareDialogRequested: firmwareDialog.open()
        }
    }

    Window {
        id: calibrationWindow
        width: 1120
        height: 940
        minimumWidth: 960
        minimumHeight: 760
        visible: false
        modality: Qt.NonModal
        transientParent: window
        title: "Калибровка"

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: window.bgStart }
                GradientStop { position: 1.0; color: window.bgEnd }
            }
        }

        CalibrationCard {
            anchors.fill: parent
            anchors.margins: 14
            appController: window.backendController
            cardColor: window.cardColor
            cardBorder: window.cardBorder
            textMain: window.textMain
            textSoft: window.textSoft
            inputBg: window.inputBg
            inputBorder: window.inputBorder
            inputFocus: window.inputFocus
        }
    }

    Window {
        id: collectorWindow
        width: 1480
        height: 980
        minimumWidth: 1180
        minimumHeight: 760
        visible: false
        modality: Qt.NonModal
        transientParent: window
        title: "Коллектор и анализ"

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: window.bgStart }
                GradientStop { position: 1.0; color: window.bgEnd }
            }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 0

            CollectorCard {
                Layout.fillWidth: true
                Layout.fillHeight: true
                appController: window.backendController
                cardColor: window.cardColor
                cardBorder: window.cardBorder
                textMain: window.textMain
                textSoft: window.textSoft
                inputBg: window.inputBg
                inputBorder: window.inputBorder
                inputFocus: window.inputFocus
                onSelectOutputDirectoryRequested: collectorDirDialog.open()
                onOpenTrendWindowRequested: {
                    collectorTrendWindow.visible = true
                    collectorTrendWindow.raise()
                    collectorTrendWindow.requestActivate()
                }
            }
        }
    }

    Window {
        id: collectorTrendWindow
        width: 1480
        height: 980
        minimumWidth: 1180
        minimumHeight: 760
        visible: false
        modality: Qt.NonModal
        transientParent: window
        title: "Графики и параметры узлов CAN"

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: window.bgStart }
                GradientStop { position: 1.0; color: window.bgEnd }
            }
        }

        CollectorTrendCard {
            anchors.fill: parent
            anchors.margins: 14
            appController: window.backendController
            cardColor: window.cardColor
            cardBorder: window.cardBorder
            textMain: window.textMain
            textSoft: window.textSoft
        }
    }

    Window {
        id: optionsBulkWindow
        width: 1500
        height: 780
        minimumWidth: 1180
        minimumHeight: 600
        visible: false
        modality: Qt.NonModal
        transientParent: window
        title: "Массовое чтение DID"

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: window.bgStart }
                GradientStop { position: 1.0; color: window.bgEnd }
            }
        }

        OptionsBulkReadCard {
            anchors.fill: parent
            anchors.margins: 14
            appController: window.backendController
            cardColor: window.cardColor
            cardBorder: window.cardBorder
            textMain: window.textMain
            textSoft: window.textSoft
            inputBg: window.inputBg
            inputBorder: window.inputBorder
            inputFocus: window.inputFocus
        }
    }

    Window {
        id: optionsWindow
        width: 1420
        height: 940
        minimumWidth: 1180
        minimumHeight: 760
        visible: false
        modality: Qt.NonModal
        transientParent: window
        title: "Параметры UDS"

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: window.bgStart }
                GradientStop { position: 1.0; color: window.bgEnd }
            }
        }

        OptionsCard {
            anchors.fill: parent
            anchors.margins: 14
            appController: window.backendController
            cardColor: window.cardColor
            cardBorder: window.cardBorder
            textMain: window.textMain
            textSoft: window.textSoft
            inputBg: window.inputBg
            inputBorder: window.inputBorder
            inputFocus: window.inputFocus
            onOpenBulkReadRequested: window.raiseToolWindow(optionsBulkWindow)
        }
    }

    Window {
        id: serviceSettingsWindow
        width: 1280
        height: 940
        minimumWidth: 1040
        minimumHeight: 760
        visible: false
        modality: Qt.NonModal
        transientParent: window
        title: "Дополнительные настройки CAN / UDS"

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: window.bgStart }
                GradientStop { position: 1.0; color: window.bgEnd }
            }
        }

        ScrollView {
            anchors.fill: parent
            anchors.margins: 14
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                width: Math.max(0, parent.width)
                spacing: 12

                SpoilerSection {
                    Layout.fillWidth: true
                    title: "UDS Session и Security Access"
                    hintText: "Сервисы 0x10, 0x27 и подготовка к 0x2E"
                    cardColor: window.cardColor
                    cardBorder: window.cardBorder
                    textMain: window.textMain
                    textSoft: window.textSoft
                    accentColor: "#0284c7"
                    expanded: false

                    ServiceAccessCard {
                        Layout.fillWidth: true
                        appController: window.backendController
                        cardColor: window.cardColor
                        cardBorder: window.cardBorder
                        textMain: window.textMain
                        textSoft: window.textSoft
                        inputBg: window.inputBg
                        inputBorder: window.inputBorder
                        inputFocus: window.inputFocus
                        showCardHeader: false
                    }
                }

                SpoilerSection {
                    Layout.fillWidth: true
                    title: "Автоопределение адреса"
                    hintText: "Анализ RX J1939 потока"
                    cardColor: window.cardColor
                    cardBorder: window.cardBorder
                    textMain: window.textMain
                    textSoft: window.textSoft
                    accentColor: "#16a34a"
                    expanded: false

                    AutoDetectCard {
                        Layout.fillWidth: true
                        appController: window.backendController
                        cardColor: window.cardColor
                        cardBorder: window.cardBorder
                        textMain: window.textMain
                        textSoft: window.textSoft
                        inputBg: window.inputBg
                        inputBorder: window.inputBorder
                        inputFocus: window.inputFocus
                        showCardHeader: false
                    }
                }

                SpoilerSection {
                    Layout.fillWidth: true
                    title: "Параметры протокола"
                    hintText: "Source Address, SID 0x28 и порядок байтов"
                    cardColor: window.cardColor
                    cardBorder: window.cardBorder
                    textMain: window.textMain
                    textSoft: window.textSoft
                    accentColor: "#d97706"
                    expanded: false

                    ProtocolCard {
                        Layout.fillWidth: true
                        appController: window.backendController
                        cardColor: window.cardColor
                        cardBorder: window.cardBorder
                        textMain: window.textMain
                        textSoft: window.textSoft
                        inputBg: window.inputBg
                        inputBorder: window.inputBorder
                        inputFocus: window.inputFocus
                        showCardHeader: false
                    }
                }

                SpoilerSection {
                    Layout.fillWidth: true
                    title: "UDS CAN идентификаторы"
                    hintText: "Ручная настройка TX/RX J1939"
                    cardColor: window.cardColor
                    cardBorder: window.cardBorder
                    textMain: window.textMain
                    textSoft: window.textSoft
                    accentColor: "#7c3aed"
                    expanded: false

                    IdentifiersCard {
                        Layout.fillWidth: true
                        appController: window.backendController
                        cardColor: window.cardColor
                        cardBorder: window.cardBorder
                        textMain: window.textMain
                        textSoft: window.textSoft
                        inputBg: window.inputBg
                        inputBorder: window.inputBorder
                        inputFocus: window.inputFocus
                        showCardHeader: false
                    }
                }
            }
        }
    }

    ColumnLayout {
        id: contentLayout
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: bottomStatusBar.top
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.topMargin: 12
        anchors.bottomMargin: 8
        spacing: 12

        ConnectionCard {
            Layout.fillWidth: true
            appController: window.backendController
            cardColor: window.cardColor
            cardBorder: window.cardBorder
            textMain: window.textMain
            textSoft: window.textSoft
            inputBg: window.inputBg
            inputBorder: window.inputBorder
            inputFocus: window.inputFocus
            showCardHeader: false
            compactMode: true
        }

        ToolLauncherCard {
            Layout.fillWidth: true
            appController: window.backendController
            cardColor: window.cardColor
            cardBorder: window.cardBorder
            textMain: window.textMain
            textSoft: window.textSoft
            onOpenBootloaderRequested: window.raiseToolWindow(bootloaderWindow)
            onOpenCalibrationRequested: window.raiseToolWindow(calibrationWindow)
            onOpenCollectorRequested: window.raiseToolWindow(collectorWindow)
            onOpenOptionsRequested: window.raiseToolWindow(optionsWindow)
            onOpenServiceSettingsRequested: window.raiseToolWindow(serviceSettingsWindow)
        }

        AppLogCard {
            Layout.fillWidth: true
            Layout.fillHeight: true
            appController: window.backendController
            cardColor: window.cardColor
            cardBorder: window.cardBorder
            textMain: window.textMain
            textSoft: window.textSoft
        }
    }

    Rectangle {
        id: bottomStatusBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.bottomMargin: 10
        height: window.bottomStatusBarHeight
        radius: 10
        color: "#f7fbff"
        border.color: "#d6e2ef"
        border.width: 1

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 8
            spacing: 8

            Rectangle {
                radius: 7
                color: window.backendController && window.backendController.connected ? "#e6f8ef" : "#fdecec"
                border.color: window.backendController && window.backendController.connected ? "#7acda5" : "#f5a5a5"
                border.width: 1
                implicitHeight: 28
                implicitWidth: canStatusText.implicitWidth + 14

                Text {
                    id: canStatusText
                    anchors.centerIn: parent
                    text: window.backendController && window.backendController.connected ? "CAN: OK" : "CAN: OFF"
                    color: window.textMain
                    font.pixelSize: 11
                    font.bold: true
                    font.family: "Bahnschrift"
                }
            }

            Rectangle {
                radius: 7
                color: window.backendController && window.backendController.tracing ? "#e9f2ff" : "#f1f5fa"
                border.color: window.backendController && window.backendController.tracing ? "#93c5fd" : "#c6d7ea"
                border.width: 1
                implicitHeight: 28
                implicitWidth: traceStatusText.implicitWidth + 14

                Text {
                    id: traceStatusText
                    anchors.centerIn: parent
                    text: window.backendController && window.backendController.tracing ? "Trace: ON" : "Trace: OFF"
                    color: window.textMain
                    font.pixelSize: 11
                    font.bold: true
                    font.family: "Bahnschrift"
                }
            }

            Item { Layout.fillWidth: true }

            Text {
                text: "DBG"
                color: window.textSoft
                font.pixelSize: 11
                font.bold: true
                font.family: "Bahnschrift"
                Layout.alignment: Qt.AlignVCenter
            }

            FancySwitch {
                id: bottomDebugSwitch
                Layout.alignment: Qt.AlignVCenter
                trackWidth: 42
                trackHeight: 22
                onColor: "#10b981"
                offColor: "#dfe9f5"
                borderOnColor: "#059669"
                borderOffColor: "#b4c8df"
                checked: window.backendController ? window.backendController.debugEnabled : false
                onToggled: if (window.backendController) window.backendController.setDebugEnabled(checked)
            }

            FancyButton {
                Layout.preferredWidth: 132
                Layout.preferredHeight: 30
                text: "Журнал CAN"
                fontPixelSize: 12
                tone: "#0ea5a4"
                toneHover: "#0f766e"
                tonePressed: "#115e59"
                onClicked: window.raiseToolWindow(canJournalWindow)
            }
        }
    }

    Component.onCompleted: {
        if (!window.backendController) {
            window.showToast("Отладка", "appController не найден при старте")
            return
        }
        window.backendController.scanDevices()
    }
}
