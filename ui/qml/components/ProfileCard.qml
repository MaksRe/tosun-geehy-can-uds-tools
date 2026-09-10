import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Окно температурного профиля.
  Назначение:
  - показывает семь таблиц профиля числами, по семь значений в каждой;
  - само считает контрольную сумму и пишет её последней, после всех таблиц;
  - сохраняет профиль в файл и загружает обратно, что даёт откат;
  - принимает файл, который выдаёт расчёт по журналу климатической камеры.

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
    // В общем окне калибровки выбор прибора стоит в шапке, один на все разделы.
    property bool showNodeControls: true

    signal saveProfileRequested()
    signal loadProfileRequested()

    readonly property bool busy: root.appController ? root.appController.profileBusy : false

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        // --- Заголовок и кнопки ---
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 150
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: "Температурный профиль"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: "Семь таблиц по семь узлов температуры. Сумма считается сама и пишется последней"
                    color: root.textSoft
                    font.pixelSize: 12
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                }
            }

            FancyComboBox {
                id: nodeSelector
                visible: root.showNodeControls
                Layout.preferredWidth: 220
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
                Layout.preferredWidth: 168
                Layout.preferredHeight: 36
                text: "Прочитать из прибора"
                tone: "#0284c7"
                toneHover: "#0369a1"
                tonePressed: "#075985"
                enabled: root.appController !== null && !root.busy
                onClicked: if (root.appController) root.appController.readProfileFromDevice()
            }

            FancyButton {
                Layout.preferredWidth: 158
                Layout.preferredHeight: 36
                text: "Записать в прибор"
                tone: "#16a34a"
                toneHover: "#15803d"
                tonePressed: "#166534"
                toolTipText: "Сначала все таблицы, затем номер алгоритма и поколение, и в последнюю очередь сумма"
                enabled: root.appController !== null && !root.busy
                onClicked: if (root.appController) root.appController.writeProfileToDevice()
            }
        }

        // --- Работа с файлом ---
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Text {
                text: "Файл профиля"
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                Layout.alignment: Qt.AlignVCenter
            }

            Text {
                Layout.fillWidth: true
                text: root.appController && root.appController.profileFilePath.length > 0
                    ? root.appController.profileFilePath
                    : "файл не выбран"
                color: root.textMain
                font.pixelSize: 12
                font.family: "Bahnschrift"
                elide: Text.ElideLeft
            }

            FancyButton {
                Layout.preferredWidth: 150
                Layout.preferredHeight: 32
                fontPixelSize: 12
                text: "Сохранить в файл"
                tone: "#64748b"
                toneHover: "#475569"
                tonePressed: "#334155"
                toolTipText: "Сохранённый файл возвращает прежний профиль, если новый набор окажется неудачным"
                enabled: root.appController !== null && !root.busy
                onClicked: root.saveProfileRequested()
            }

            FancyButton {
                Layout.preferredWidth: 158
                Layout.preferredHeight: 32
                fontPixelSize: 12
                text: "Загрузить из файла"
                tone: "#64748b"
                toneHover: "#475569"
                tonePressed: "#334155"
                toolTipText: "Принимает и свой файл, и результат расчёта по журналу камеры"
                enabled: root.appController !== null && !root.busy
                onClicked: root.loadProfileRequested()
            }
        }

        // --- Сводка ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 62
            radius: 12
            color: "#f2f7ff"
            border.width: 1
            border.color: "#c6dcf5"

            RowLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 22

                Repeater {
                    model: [
                        {
                            "title": "Сумма по таблицам на экране",
                            "value": root.appController ? root.appController.profileCrcText : "-"
                        },
                        {
                            "title": "Сумма, записанная в приборе",
                            "value": root.appController ? root.appController.profileDeviceCrcText : "-"
                        },
                        {
                            "title": "Поколение",
                            "value": root.appController ? root.appController.profileGenerationText : "-"
                        }
                    ]

                    ColumnLayout {
                        required property var modelData
                        spacing: 2

                        Text {
                            text: modelData.title
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                        }

                        Text {
                            text: modelData.value
                            color: root.textMain
                            font.pixelSize: 16
                            font.bold: true
                            font.family: "Bahnschrift"
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        text: "Что сейчас в приборе"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.appController ? root.appController.profileDeviceStatusText : "-"
                        color: root.textMain
                        font.pixelSize: 13
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }
                }
            }
        }

        // --- Таблицы ---
        ScrollView {
            id: tableScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                width: tableScroll.availableWidth
                spacing: 4

                // Шапка: температуры узлов.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Text {
                        Layout.preferredWidth: 250
                        text: "Величина"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    Repeater {
                        model: root.appController ? root.appController.profileNodeTitles : []

                        Text {
                            required property string modelData
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            text: modelData
                            color: root.textSoft
                            font.pixelSize: 11
                            font.bold: true
                            font.family: "Bahnschrift"
                        }
                    }
                }

                Repeater {
                    model: root.appController ? root.appController.profileRows : []

                    RowLayout {
                        id: tableRow
                        required property int index
                        required property var modelData

                        Layout.fillWidth: true
                        spacing: 4

                        Text {
                            Layout.preferredWidth: 250
                            text: tableRow.modelData.title
                            color: root.textMain
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }

                        Repeater {
                            model: tableRow.modelData.values

                            FancyTextField {
                                required property int index
                                required property string modelData

                                Layout.fillWidth: true
                                Layout.preferredHeight: 28
                                text: modelData
                                readOnly: !tableRow.modelData.editable
                                horizontalAlignment: Text.AlignHCenter
                                textColor: root.textMain
                                bgColor: tableRow.modelData.editable ? root.inputBg : "#eef2f7"
                                borderColor: root.inputBorder
                                focusBorderColor: root.inputFocus
                                onEditingFinished: {
                                    if (root.appController && tableRow.modelData.editable) {
                                        root.appController.setProfileCell(tableRow.index, index, text)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // --- Ход работы ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 46
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
                    color: root.appController ? root.appController.profileStatusColor : "#64748b"
                }

                Text {
                    Layout.fillWidth: true
                    text: root.appController ? root.appController.profileStatusText : "Контроллер недоступен"
                    color: root.appController ? root.appController.profileStatusColor : "#64748b"
                    font.pixelSize: 13
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
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
