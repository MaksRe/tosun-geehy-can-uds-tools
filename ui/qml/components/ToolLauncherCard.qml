import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

Card {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    readonly property int contentPadding: 14

    signal openBootloaderRequested()
    signal openCalibrationRequested()
    signal openCollectorRequested()
    signal openOptionsRequested()
    signal openServiceSettingsRequested()

    function bootloaderStatusText() {
        if (!root.appController)
            return "Ожидание контроллера"
        if (root.appController.firmwareLoading)
            return "Загрузка BIN"
        if (root.appController.programmingActive && root.appController.firmwarePath.length > 0)
            return "Сценарий активен"
        if (root.appController.firmwarePath.length > 0)
            return "BIN выбран"
        return "BIN не выбран"
    }

    function calibrationStatusText() {
        if (!root.appController)
            return "Ожидание контроллера"
        if (root.appController.calibrationActive)
            return "Сценарий активен"
        return root.appController.calibrationSelectedNodeText || "Калибровка не запущена"
    }

    function collectorStatusText() {
        if (!root.appController)
            return "Ожидание контроллера"
        if (!root.appController.collectorEnabled)
            return "Сценарий выключен"
        return root.appController.collectorStateText
    }

    function optionsStatusText() {
        if (!root.appController)
            return "Ожидание контроллера"
        return root.appController.optionOperationStatusText
    }

    function serviceSettingsStatusText() {
        if (!root.appController)
            return "Ожидание контроллера"
        if (root.appController.serviceAccessBusy)
            return "Операция выполняется"
        if (root.appController.serviceSecurityUnlocked)
            return "Доступ 0x27 открыт"
        return "Session / Security Access"
    }

    implicitHeight: contentColumn.implicitHeight + (contentPadding * 2)

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: root.contentPadding
        spacing: 12

        GridLayout {
            Layout.fillWidth: true
            columns: width > 1260 ? 5 : (width > 900 ? 3 : 2)
            columnSpacing: 10
            rowSpacing: 10

            ScenarioTile {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "Программирование"
                statusText: root.bootloaderStatusText()
                textMain: root.textMain
                textSoft: root.textSoft
                baseColor: "#fff8eb"
                baseBorder: "#f1d39b"
                chipColor: "#fff3d6"
                chipBorder: "#f4c86f"
                accentColor: "#d97706"
                accentColorHover: "#b45309"
                onClicked: root.openBootloaderRequested()
            }

            ScenarioTile {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "Калибровка"
                statusText: root.calibrationStatusText()
                textMain: root.textMain
                textSoft: root.textSoft
                baseColor: "#eefbf5"
                baseBorder: "#a8dfc2"
                chipColor: "#e7f8ef"
                chipBorder: "#88d4af"
                accentColor: "#16a34a"
                accentColorHover: "#15803d"
                onClicked: root.openCalibrationRequested()
            }

            ScenarioTile {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "Коллектор"
                statusText: root.collectorStatusText()
                textMain: root.textMain
                textSoft: root.textSoft
                baseColor: "#eef7ff"
                baseBorder: "#a8caef"
                chipColor: "#e7f1ff"
                chipBorder: "#93c5fd"
                accentColor: "#0284c7"
                accentColorHover: "#0369a1"
                onClicked: root.openCollectorRequested()
            }

            ScenarioTile {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "Параметры UDS"
                statusText: root.optionsStatusText()
                textMain: root.textMain
                textSoft: root.textSoft
                baseColor: "#f6f0ff"
                baseBorder: "#cfb8f2"
                chipColor: "#f2ebff"
                chipBorder: "#c4b5fd"
                accentColor: "#7c3aed"
                accentColorHover: "#6d28d9"
                onClicked: root.openOptionsRequested()
            }

            ScenarioTile {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "Доп. настройки"
                statusText: root.serviceSettingsStatusText()
                textMain: root.textMain
                textSoft: root.textSoft
                baseColor: "#ecfeff"
                baseBorder: "#a5f3fc"
                chipColor: "#e6fbff"
                chipBorder: "#8ce3ee"
                accentColor: "#0f766e"
                accentColorHover: "#115e59"
                onClicked: root.openServiceSettingsRequested()
            }
        }
    }
}
