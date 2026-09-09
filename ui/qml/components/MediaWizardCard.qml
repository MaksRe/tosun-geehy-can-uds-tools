import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Мастер калибровки контура вида топлива.
  Назначение:
  - проводит оператора по трём шагам: точка в воздухе, точка в топливе, включение поправки;
  - показывает живое измерение плоского конденсатора, чтобы дождаться устоявшегося значения;
  - не даёт включить поправку, пока опорные точки не сняты правильно.

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

    readonly property bool writeAllowed: root.appController ? root.appController.mediaWizardWriteAllowed : false
    readonly property bool busy: root.appController ? root.appController.mediaWizardBusy : false

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        // --- Заголовок ---
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 150
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: "Калибровка контура вида топлива"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: "Две опорные точки плоского конденсатора: в воздухе и в эталонном топливе"
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }

            FancyComboBox {
                id: nodeSelector
                Layout.preferredWidth: 240
                Layout.preferredHeight: 36
                model: root.appController ? root.appController.calibrationNodeOptions : []
                textColor: root.textMain
                bgColor: root.inputBg
                borderColor: root.inputBorder
                focusBorderColor: root.inputFocus
                onActivated: function(index) {
                    if (root.appController) {
                        nodeSelector.currentIndex = index
                        root.appController.setSelectedCalibrationNodeIndex(index)
                    }
                }
            }

            FancyButton {
                Layout.preferredWidth: 190
                Layout.preferredHeight: 36
                text: "Прочитать из прибора"
                tone: "#64748b"
                toneHover: "#475569"
                tonePressed: "#334155"
                enabled: root.appController !== null && !root.busy
                onClicked: if (root.appController) root.appController.refreshMediaWizardSaved()
            }
        }

        // --- Предупреждение о правах на запись ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 42
            visible: !root.writeAllowed
            radius: 10
            color: "#fdf3e3"
            border.width: 1
            border.color: "#f0c98a"

            Text {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                verticalAlignment: Text.AlignVCenter
                text: "Запись закрыта. Нажмите «Начать калибровку» в окне калибровки: она открывает прибору доступ на запись."
                color: "#92400e"
                font.pixelSize: 12
                font.family: "Bahnschrift"
                elide: Text.ElideRight
            }
        }

        // --- Живое измерение ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 78
            radius: 12
            color: "#f2f7ff"
            border.width: 1
            border.color: "#c6dcf5"

            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 14

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        text: "Плоский конденсатор сейчас"
                        color: root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                    }

                    Text {
                        text: root.appController ? root.appController.mediaWizardLiveText : "-"
                        color: root.textMain
                        font.pixelSize: 26
                        font.bold: true
                        font.family: "Bahnschrift"
                    }
                }

                Text {
                    Layout.preferredWidth: 260
                    text: "Дождитесь, пока число перестанет заметно меняться, и только потом снимайте точку."
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                FancyButton {
                    Layout.preferredWidth: 180
                    Layout.preferredHeight: 36
                    text: root.appController && root.appController.mediaWizardWatching
                        ? "Остановить обновление" : "Обновлять показание"
                    tone: root.appController && root.appController.mediaWizardWatching ? "#ef4444" : "#0284c7"
                    toneHover: root.appController && root.appController.mediaWizardWatching ? "#dc2626" : "#0369a1"
                    tonePressed: root.appController && root.appController.mediaWizardWatching ? "#b91c1c" : "#075985"
                    enabled: root.appController !== null
                    onClicked: {
                        if (!root.appController)
                            return
                        if (root.appController.mediaWizardWatching)
                            root.appController.stopMediaWizardWatch()
                        else
                            root.appController.startMediaWizardWatch()
                    }
                }
            }
        }

        // --- Три шага ---
        GridLayout {
            Layout.fillWidth: true
            columns: width > 980 ? 3 : 1
            columnSpacing: 10
            rowSpacing: 10

            // Шаг 1
            Rectangle {
                Layout.fillWidth: true
                // Высота карточки шага фиксирована: свободное место забирает
                // распорка внизу окна, иначе шаги тянутся на весь экран.
                Layout.preferredHeight: 208
                radius: 12
                color: "#fbfdff"
                border.width: 1
                border.color: "#e2ebf5"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8

                    Text {
                        text: "Шаг 1. Точка в воздухе"
                        color: root.textMain
                        font.pixelSize: 15
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Достаньте трубку из топлива и дайте плоскому конденсатору обсохнуть. На нём не должно остаться плёнки."
                        color: root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }

                    Item { Layout.fillHeight: true }

                    Text {
                        text: "Сохранено: " + (root.appController ? root.appController.mediaWizardAirText : "-")
                        color: root.textMain
                        font.pixelSize: 14
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    FancyButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 36
                        text: "Снять точку в воздухе"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        enabled: root.appController !== null && root.writeAllowed && !root.busy
                        onClicked: if (root.appController) root.appController.captureMediaWizardAir()
                    }
                }
            }

            // Шаг 2
            Rectangle {
                Layout.fillWidth: true
                // Высота карточки шага фиксирована: свободное место забирает
                // распорка внизу окна, иначе шаги тянутся на весь экран.
                Layout.preferredHeight: 208
                radius: 12
                color: "#fbfdff"
                border.width: 1
                border.color: "#e2ebf5"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8

                    Text {
                        text: "Шаг 2. Точка в топливе"
                        color: root.textMain
                        font.pixelSize: 15
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Погрузите плоский конденсатор в то топливо, по которому калибруете. Он должен быть полностью залит."
                        color: root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }

                    Item { Layout.fillHeight: true }

                    Text {
                        text: "Сохранено: " + (root.appController ? root.appController.mediaWizardCalText : "-")
                        color: root.textMain
                        font.pixelSize: 14
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    FancyButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 36
                        text: "Снять точку в топливе"
                        tone: "#0284c7"
                        toneHover: "#0369a1"
                        tonePressed: "#075985"
                        enabled: root.appController !== null && root.writeAllowed && !root.busy
                        onClicked: if (root.appController) root.appController.captureMediaWizardLiquid()
                    }
                }
            }

            // Шаг 3
            Rectangle {
                Layout.fillWidth: true
                // Высота карточки шага фиксирована: свободное место забирает
                // распорка внизу окна, иначе шаги тянутся на весь экран.
                Layout.preferredHeight: 208
                radius: 12
                color: "#fbfdff"
                border.width: 1
                border.color: "#e2ebf5"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8

                    Text {
                        text: "Шаг 3. Поправка"
                        color: root.textMain
                        font.pixelSize: 15
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Разница точек: " + (root.appController ? root.appController.mediaWizardSpanText : "-")
                        color: root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }

                    Item { Layout.fillHeight: true }

                    Text {
                        text: "Сейчас: " + (root.appController ? root.appController.mediaWizardEnabledText : "-")
                        color: root.textMain
                        font.pixelSize: 14
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        FancyButton {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 36
                            text: "Включить"
                            tone: "#16a34a"
                            toneHover: "#15803d"
                            tonePressed: "#166534"
                            enabled: root.appController !== null && root.writeAllowed && !root.busy
                                && root.appController.mediaWizardCanEnable
                            onClicked: if (root.appController) root.appController.setMediaWizardEnabled(true)
                        }

                        FancyButton {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 36
                            text: "Выключить"
                            tone: "#64748b"
                            toneHover: "#475569"
                            tonePressed: "#334155"
                            enabled: root.appController !== null && root.writeAllowed && !root.busy
                            onClicked: if (root.appController) root.appController.setMediaWizardEnabled(false)
                        }
                    }
                }
            }
        }

        // --- Ход работы ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            radius: 10
            color: "#f8fbff"
            border.width: 1
            border.color: "#d6e2ef"

            RowLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 10

                Rectangle {
                    Layout.alignment: Qt.AlignVCenter
                    Layout.preferredWidth: 12
                    Layout.preferredHeight: 12
                    radius: 6
                    color: root.appController ? root.appController.mediaWizardStatusColor : "#64748b"
                }

                Text {
                    Layout.fillWidth: true
                    text: root.appController ? root.appController.mediaWizardStatusText : "Контроллер недоступен"
                    color: root.appController ? root.appController.mediaWizardStatusColor : "#64748b"
                    font.pixelSize: 13
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }

    Connections {
        target: root.appController

        function onCalibrationNodeSelectionChanged() {
            if (!root.appController) {
                return
            }
            if (nodeSelector.currentIndex !== root.appController.selectedCalibrationNodeIndex) {
                nodeSelector.currentIndex = root.appController.selectedCalibrationNodeIndex
            }
        }
    }

    Component.onCompleted: {
        if (root.appController) {
            nodeSelector.currentIndex = root.appController.selectedCalibrationNodeIndex
        }
    }
}
