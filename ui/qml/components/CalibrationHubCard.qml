import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Окно калибровки: один вход во все её разделы.

  ЗАЧЕМ ОДНО ОКНО
  Раньше калибровка была разнесена по трём окнам, и это мешало. Запись
  параметров разрешает только запущенный сценарий калибровки, а кнопка запуска
  находилась в другом окне. Оператор оказывался в разделе вида топлива, видел
  предупреждение «запись закрыта» и не понимал, куда идти.

  Теперь выбор прибора и кнопка запуска стоят сверху и действуют на все разделы,
  а сами разделы переключаются слева. Из любого раздела видно, открыт доступ на
  запись или нет.

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

    signal saveProfileRequested()
    signal loadProfileRequested()

    property int currentSection: 0

    readonly property bool writeAllowed: root.appController ? root.appController.mediaWizardWriteAllowed : false

    function sectionStatus(index) {
        if (!root.appController)
            return "Ожидание контроллера"

        if (index === 0)
            return root.appController.calibrationActive
                ? "Сценарий активен"
                : (root.appController.calibrationSelectedNodeText || "Не запущена")

        if (index === 1) {
            if (root.appController.mediaWizardBusy)
                return "Идёт запись точки"
            return root.appController.mediaWizardCanEnable
                ? "Точки сняты: " + root.appController.mediaWizardEnabledText
                : "Опорные точки не сняты"
        }

        if (root.appController.profileBusy)
            return "Идёт обмен с прибором"
        return root.appController.profileDeviceStatusText
    }

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        // --- Общая шапка: действует на все разделы ---
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
                spacing: 10

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 150
                    spacing: 2

                    Text {
                        Layout.fillWidth: true
                        text: "Калибровка топливозаборника"
                        color: root.textMain
                        font.pixelSize: 18
                        font.bold: true
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.writeAllowed
                            ? "Запись в прибор разрешена во всех разделах"
                            : "Запись закрыта. Нажмите «Начать калибровку», иначе прибор ничего не сохранит"
                        color: root.writeAllowed ? "#16a34a" : "#d97706"
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }
                }

                FancyComboBox {
                    id: nodeSelector
                    Layout.preferredWidth: 230
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
                    text: root.appController ? root.appController.calibrationActionText : "Начать калибровку"
                    tone: root.appController && root.appController.calibrationActive ? "#ef4444" : "#16a34a"
                    toneHover: root.appController && root.appController.calibrationActive ? "#dc2626" : "#15803d"
                    tonePressed: root.appController && root.appController.calibrationActive ? "#b91c1c" : "#166534"
                    toolTipText: "Поднимает сессию и открывает доступ на запись. Без неё прибор запись отклонит"
                    enabled: root.appController !== null
                    onClicked: if (root.appController) root.appController.toggleCalibration()
                }
            }
        }

        // --- Навигация слева и раздел справа ---
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            ColumnLayout {
                // Ширину колонки задаём жёстко: длинные подписи разделов иначе
                // растягивают её на всё окно и раздел справа исчезает.
                Layout.preferredWidth: 250
                Layout.minimumWidth: 250
                Layout.maximumWidth: 250
                Layout.fillWidth: false
                Layout.fillHeight: true
                Layout.alignment: Qt.AlignTop
                spacing: 8

                Repeater {
                    model: [
                        {
                            "title": "Уровень бака",
                            "hint": "Отметки 0 % и 100 %, температурная компенсация"
                        },
                        {
                            "title": "Вид топлива",
                            "hint": "Плоский конденсатор: воздух и топливо"
                        },
                        {
                            "title": "Температурный профиль",
                            "hint": "Таблицы из климатической камеры"
                        }
                    ]

                    Rectangle {
                        id: navItem
                        required property int index
                        required property var modelData

                        readonly property bool selected: root.currentSection === navItem.index

                        Layout.fillWidth: true
                        Layout.preferredHeight: 74
                        radius: 11
                        color: navItem.selected ? "#e7f1ff" : (navArea.containsMouse ? "#f4f9ff" : "#fbfdff")
                        border.width: 1
                        border.color: navItem.selected ? "#7cb2ea" : "#e2ebf5"

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 2

                            Text {
                                Layout.fillWidth: true
                                text: navItem.modelData.title
                                color: root.textMain
                                font.pixelSize: 14
                                font.bold: navItem.selected
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                            }

                            Text {
                                Layout.fillWidth: true
                                text: navItem.modelData.hint
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                            }

                            Text {
                                Layout.fillWidth: true
                                text: root.sectionStatus(navItem.index)
                                color: "#0f6ab4"
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                            }
                        }

                        MouseArea {
                            id: navArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.currentSection = navItem.index
                        }
                    }
                }

                Item {
                    Layout.fillHeight: true
                }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 600
                currentIndex: root.currentSection

                CalibrationCard {
                    appController: root.appController
                    showNodeControls: false
                    cardColor: root.cardColor
                    cardBorder: root.cardBorder
                    textMain: root.textMain
                    textSoft: root.textSoft
                    inputBg: root.inputBg
                    inputBorder: root.inputBorder
                    inputFocus: root.inputFocus
                }

                MediaWizardCard {
                    appController: root.appController
                    showNodeControls: false
                    cardColor: root.cardColor
                    cardBorder: root.cardBorder
                    textMain: root.textMain
                    textSoft: root.textSoft
                    inputBg: root.inputBg
                    inputBorder: root.inputBorder
                    inputFocus: root.inputFocus
                }

                ProfileCard {
                    appController: root.appController
                    showNodeControls: false
                    cardColor: root.cardColor
                    cardBorder: root.cardBorder
                    textMain: root.textMain
                    textSoft: root.textSoft
                    inputBg: root.inputBg
                    inputBorder: root.inputBorder
                    inputFocus: root.inputFocus
                    onSaveProfileRequested: root.saveProfileRequested()
                    onLoadProfileRequested: root.loadProfileRequested()
                }
            }
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
