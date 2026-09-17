import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import "."

Item {
    id: root

    property var appController
    property color cardColor: "#ffffff"
    property color cardBorder: "#d6e2ef"
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    property color inputBg: "#f7fbff"
    property color inputBorder: "#c8d9ea"
    property color inputFocus: "#0ea5e9"
    // В общем окне калибровки выбор прибора и кнопка запуска стоят в шапке,
    // одни на все разделы. Внутри раздела они были бы вторыми такими же.
    property bool showNodeControls: true
    readonly property int contentPadding: 10
    property bool zeroTrimForceRefresh: false

    function applyCapturedToField(targetField, targetSwitch) {
        if (!root.appController) {
            return
        }
        var captured = root.appController.calibrationCapturedLevelText
        if (!captured || captured === "-") {
            return
        }
        targetSwitch.checked = true
        targetField.text = captured
    }

    Layout.fillWidth: true
    implicitHeight: contentColumn.implicitHeight + (root.contentPadding * 2)
    clip: true

    // Раздел живёт в StackLayout и растянут на всю высоту окна. Без прокрутки
    // раскрытый спойлер либо отдавал лишнюю высоту блокам, и они разъезжались,
    // либо не помещался, и блоки сжимались. Здесь высоту задаёт содержимое.
    ScrollView {
        id: contentScroll
        anchors.fill: parent
        anchors.margins: root.contentPadding
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        ColumnLayout {
            id: contentColumn
            width: contentScroll.availableWidth
            spacing: 8

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: false
                Layout.alignment: Qt.AlignTop
                Layout.preferredHeight: implicitHeight
                Layout.maximumHeight: implicitHeight
                radius: 10
                color: "#f8fbff"
                border.color: "#d6e2ef"
                implicitHeight: topPanelLayout.implicitHeight + 14

                ColumnLayout {
                    id: topPanelLayout
                    anchors.fill: parent
                    anchors.margins: 7
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        FancyComboBox {
                            id: nodeSelector
                            visible: root.showNodeControls
                            Layout.fillWidth: true
                            Layout.preferredHeight: 32
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
                            Layout.preferredWidth: 184
                            Layout.preferredHeight: 32
                            text: root.appController ? root.appController.calibrationActionText : "Начать калибровку"
                            visible: root.showNodeControls
                            tone: root.appController && root.appController.calibrationActive ? "#ef4444" : "#16a34a"
                            toneHover: root.appController && root.appController.calibrationActive ? "#dc2626" : "#15803d"
                            tonePressed: root.appController && root.appController.calibrationActive ? "#b91c1c" : "#166534"
                            enabled: root.appController !== null
                            onClicked: if (root.appController) root.appController.toggleCalibration()
                        }

                        // Подпись нужна, потому что в общем окне калибровки слева от поля
                        // больше нет выбора прибора, и поле осталось без пояснения.
                        Text {
                            text: "Интервал опроса, мс"
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            Layout.alignment: Qt.AlignVCenter
                        }

                        FancyTextField {
                            id: pollIntervalField
                            Layout.preferredWidth: 88
                            Layout.preferredHeight: 32
                            text: root.appController ? String(root.appController.calibrationPollingIntervalMs) : "1000"
                            placeholderText: "Опрос"
                            textColor: root.textMain
                            bgColor: root.inputBg
                            borderColor: root.inputBorder
                            focusBorderColor: root.inputFocus
                            validator: IntValidator { bottom: 100; top: 10000 }
                            onAccepted: if (root.appController) root.appController.setCalibrationPollingIntervalMs(text)
                        }

                        FancyButton {
                            Layout.preferredWidth: 78
                            Layout.preferredHeight: 32
                            text: "OK"
                            tone: "#0284c7"
                            toneHover: "#0369a1"
                            tonePressed: "#075985"
                            enabled: root.appController !== null
                            onClicked: if (root.appController) root.appController.setCalibrationPollingIntervalMs(pollIntervalField.text)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Rectangle {
                            width: 10
                            height: 10
                            radius: 5
                            color: {
                                if (!root.appController) return "#94a3b8"
                                if (root.appController.calibrationVerifyInProgress) return "#f59e0b"
                                var status = root.appController.calibrationVerifyStatusText
                                if (status.indexOf("успешно") >= 0) return "#16a34a"
                                if (status.indexOf("не пройдена") >= 0) return "#ef4444"
                                return "#94a3b8"
                            }
                        }

                        BusyIndicator {
                            running: root.appController && root.appController.calibrationVerifyInProgress
                            visible: running
                            Layout.preferredWidth: 16
                            Layout.preferredHeight: 16
                        }

                        Text {
                            Layout.fillWidth: true
                            text: root.appController ? root.appController.calibrationVerifyStatusText : "Ожидание"
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: false
                Layout.alignment: Qt.AlignTop
                Layout.preferredHeight: implicitHeight
                Layout.maximumHeight: implicitHeight
                radius: 10
                color: "#f8fbff"
                border.color: "#d6e2ef"
                implicitHeight: backupTopLayout.implicitHeight + 14

                ColumnLayout {
                    id: backupTopLayout
                    anchors.fill: parent
                    anchors.margins: 7
                    spacing: 6

                    Text {
                        Layout.fillWidth: true
                        text: "Резервные копии калибровки"
                        color: root.textMain
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Text {
                            Layout.fillWidth: true
                            text: root.appController ? root.appController.calibrationBackupSourceText : "Дамп калибровки не сохранен."
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 8
                        color: "#f3f8ff"
                        border.color: "#d9e7f5"
                        border.width: 1
                        implicitHeight: backupMetaLayout.implicitHeight + 10

                        ColumnLayout {
                            id: backupMetaLayout
                            anchors.fill: parent
                            anchors.margins: 5
                            spacing: 4

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 14

                                Text {
                                    text: "Узел: " + (root.appController ? root.appController.calibrationBackupNodeText : "-")
                                    color: root.textMain
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                    font.bold: true
                                }

                                Text {
                                    text: "Сохранен: " + (root.appController ? root.appController.calibrationBackupSavedAtText : "-")
                                    color: root.textMain
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }

                                Item { Layout.fillWidth: true }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 12

                                Text {
                                    text: "0%: " + (root.appController ? root.appController.calibrationBackupLevel0Text : "-")
                                    color: root.textMain
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }
                                Text {
                                    text: "100%: " + (root.appController ? root.appController.calibrationBackupLevel100Text : "-")
                                    color: root.textMain
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }
                                Text {
                                    text: "Подгонка нуля: " + (root.appController ? root.appController.calibrationBackupZeroTrimText : "-")
                                    color: root.textMain
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }
                                Item { Layout.fillWidth: true }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 8
                        color: "#f7fbff"
                        border.color: "#d9e7f5"
                        border.width: 1
                        implicitHeight: backupPathLayout.implicitHeight + 10

                        ColumnLayout {
                            id: backupPathLayout
                            anchors.fill: parent
                            anchors.margins: 5
                            spacing: 4

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                Text {
                                    Layout.preferredWidth: 58
                                    text: "Каталог:"
                                    color: root.textSoft
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }

                                Text {
                                    id: backupDirectoryText
                                    Layout.fillWidth: true
                                    text: root.appController ? root.appController.collectorOutputDirectory : "-"
                                    color: root.textMain
                                    font.pixelSize: 10
                                    font.family: "Bahnschrift"
                                    elide: Text.ElideMiddle
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                Text {
                                    Layout.preferredWidth: 58
                                    text: "Файл:"
                                    color: root.textSoft
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }

                                Text {
                                    id: backupFilePathText
                                    Layout.fillWidth: true
                                    text: root.appController ? root.appController.calibrationBackupFilePathText : "-"
                                    color: root.textMain
                                    font.pixelSize: 10
                                    font.family: "Bahnschrift"
                                    elide: Text.ElideMiddle
                                }
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        FancyButton {
                            Layout.preferredWidth: 210
                            Layout.preferredHeight: 30
                            text: "Сохранить дамп текущего узла"
                            tone: "#0f766e"
                            toneHover: "#115e59"
                            tonePressed: "#134e4a"
                            enabled: root.appController !== null
                            onClicked: if (root.appController) root.appController.createCalibrationBackup()
                        }

                        FancyButton {
                            Layout.preferredWidth: 170
                            Layout.preferredHeight: 30
                            text: "Загрузить дамп"
                            tone: "#2563eb"
                            toneHover: "#1d4ed8"
                            tonePressed: "#1e40af"
                            enabled: root.appController !== null
                            onClicked: calibrationDumpFileDialog.open()
                        }

                        FancyButton {
                            Layout.preferredWidth: 182
                            Layout.preferredHeight: 30
                            text: "Применить дамп в МК"
                            tone: "#475569"
                            toneHover: "#334155"
                            tonePressed: "#1e293b"
                            enabled: root.appController && root.appController.calibrationBackupAvailable
                            onClicked: if (root.appController) root.appController.restoreCalibrationBackup()
                        }
                    }
                }
            }

            SpoilerSection {
                id: levelCalibrationSpoiler
                Layout.fillWidth: true
                Layout.fillHeight: false
                Layout.alignment: Qt.AlignTop
                Layout.preferredHeight: implicitHeight
                Layout.maximumHeight: implicitHeight
                title: "Калибровка уровней 0% и 100%"
                hintText: "Чтение и запись калибровочных точек уровня"
                cardColor: root.cardColor
                cardBorder: root.cardBorder
                textMain: root.textMain
                textSoft: root.textSoft
                accentColor: "#0284c7"
                expanded: false

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: false
                    Layout.preferredHeight: implicitHeight
                    Layout.maximumHeight: implicitHeight
                    radius: 10
                    color: "#f4f8fd"
                    border.color: "#d6e2ef"
                    implicitHeight: currentLevelRow.implicitHeight + 14

                    RowLayout {
                        id: currentLevelRow
                        anchors.fill: parent
                        anchors.margins: 7
                        spacing: 8

                        Rectangle {
                            radius: 8
                            color: "#eef5ff"
                            border.color: "#d6e2ef"
                            implicitHeight: 34
                            implicitWidth: currentValueRow.implicitWidth + 16

                            RowLayout {
                                id: currentValueRow
                                anchors.centerIn: parent
                                spacing: 6

                                Text {
                                    text: "Текущий"
                                    color: root.textSoft
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }

                                Text {
                                    text: root.appController ? root.appController.calibrationCurrentLevelText : "-"
                                    color: root.textMain
                                    font.pixelSize: 18
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }
                            }
                        }

                        Rectangle {
                            width: 1
                            Layout.preferredHeight: 22
                            color: "#d6e2ef"
                        }

                        Rectangle {
                            radius: 8
                            color: "#ecfdf5"
                            border.color: "#bfe8d2"
                            implicitHeight: 34
                            implicitWidth: capturedValueRow.implicitWidth + 16

                            RowLayout {
                                id: capturedValueRow
                                anchors.centerIn: parent
                                spacing: 6

                                Text {
                                    text: "Захват"
                                    color: root.textSoft
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }

                                Text {
                                    text: root.appController ? root.appController.calibrationCapturedLevelText : "-"
                                    color: "#0f766e"
                                    font.pixelSize: 14
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }
                            }
                        }

                        Item { Layout.fillWidth: true }

                        FancyButton {
                            Layout.preferredWidth: 90
                            Layout.preferredHeight: 30
                            text: "-> 0%"
                            tone: "#0284c7"
                            toneHover: "#0369a1"
                            tonePressed: "#075985"
                            enabled: root.appController && root.appController.calibrationCapturedLevelText !== "-"
                            onClicked: root.applyCapturedToField(custom0Field, custom0Switch)
                        }

                        FancyButton {
                            Layout.preferredWidth: 96
                            Layout.preferredHeight: 30
                            text: "-> 100%"
                            tone: "#0284c7"
                            toneHover: "#0369a1"
                            tonePressed: "#075985"
                            enabled: root.appController && root.appController.calibrationCapturedLevelText !== "-"
                            onClicked: root.applyCapturedToField(custom100Field, custom100Switch)
                        }
                    }
                }

                // Свежесть числа «Текущий»: приходят ли ответы и мерит ли основной контур.
                LiveFreshnessLine {
                    Layout.fillWidth: true
                    info: root.appController ? root.appController.calibrationLiveFreshness : ({})
                }

                // Итог записи вида топлива к последней отметке: нужен модели уровня по двум контурам.
                Text {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: root.appController ? root.appController.calibrationMarkMediaStatus : ""
                    color: root.appController ? root.appController.calibrationMarkMediaStatusColor : root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: false
                    Layout.preferredHeight: Math.max(level0Layout.implicitHeight, level100Layout.implicitHeight) + 14
                    Layout.maximumHeight: Layout.preferredHeight
                    spacing: 8

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: implicitHeight
                        Layout.maximumHeight: implicitHeight
                        radius: 10
                        color: "#f8fbff"
                        border.color: "#d6e2ef"
                        implicitHeight: level0Layout.implicitHeight + 14

                        ColumnLayout {
                            id: level0Layout
                            anchors.fill: parent
                            anchors.margins: 7
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                Text {
                                    text: "0%"
                                    color: root.textMain
                                    font.pixelSize: 15
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }

                                Rectangle {
                                    radius: 7
                                    color: root.appController && root.appController.calibrationWizardStage >= 2 ? "#dcfce7" : "#e2e8f0"
                                    border.color: root.appController && root.appController.calibrationWizardStage >= 2 ? "#86efac" : "#cbd5e1"
                                    implicitWidth: status0Text.implicitWidth + 12
                                    implicitHeight: 22

                                    Text {
                                        id: status0Text
                                        anchors.centerIn: parent
                                        text: root.appController && root.appController.calibrationWizardStage >= 4 ? "ОК" :
                                              (root.appController && root.appController.calibrationWizardStage >= 2 ? "Записан" : "Ожидание")
                                        color: root.appController && root.appController.calibrationWizardStage >= 2 ? "#166534" : "#475569"
                                        font.pixelSize: 10
                                        font.bold: true
                                        font.family: "Bahnschrift"
                                    }
                                }

                                Item { Layout.fillWidth: true }

                                FancyButton {
                                    Layout.preferredWidth: 100
                                    Layout.preferredHeight: 30
                                    text: "Прочитать"
                                    tone: "#0f766e"
                                    toneHover: "#115e59"
                                    tonePressed: "#134e4a"
                                    enabled: root.appController !== null
                                    onClicked: if (root.appController) root.appController.readCalibrationLevel0()
                                }
                            }

                            Text {
                                text: "Сохранено: " + (root.appController ? root.appController.calibrationLevel0Text : "-")
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                FancySwitch {
                                    id: custom0Switch
                                    trackWidth: 40
                                    trackHeight: 22
                                }

                                FancyTextField {
                                    id: custom0Field
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 30
                                    enabled: custom0Switch.checked
                                    text: ""
                                    placeholderText: "Текущее / вручную"
                                    textColor: root.textMain
                                    bgColor: root.inputBg
                                    borderColor: root.inputBorder
                                    focusBorderColor: root.inputFocus
                                }

                                FancyButton {
                                    Layout.preferredWidth: 98
                                    Layout.preferredHeight: 30
                                    text: "Сохранить"
                                    tone: "#0284c7"
                                    toneHover: "#0369a1"
                                    tonePressed: "#075985"
                                    enabled: root.appController !== null
                                    onClicked: if (root.appController) root.appController.saveCalibrationLevel0(custom0Switch.checked ? custom0Field.text : "")
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: implicitHeight
                        Layout.maximumHeight: implicitHeight
                        radius: 10
                        color: "#f8fbff"
                        border.color: "#d6e2ef"
                        implicitHeight: level100Layout.implicitHeight + 14

                        ColumnLayout {
                            id: level100Layout
                            anchors.fill: parent
                            anchors.margins: 7
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                Text {
                                    text: "100%"
                                    color: root.textMain
                                    font.pixelSize: 15
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }

                                Rectangle {
                                    radius: 7
                                    color: root.appController && root.appController.calibrationWizardStage >= 3 ? "#dcfce7" : "#e2e8f0"
                                    border.color: root.appController && root.appController.calibrationWizardStage >= 3 ? "#86efac" : "#cbd5e1"
                                    implicitWidth: status100Text.implicitWidth + 12
                                    implicitHeight: 22

                                    Text {
                                        id: status100Text
                                        anchors.centerIn: parent
                                        text: root.appController && root.appController.calibrationWizardStage >= 4 ? "ОК" :
                                              (root.appController && root.appController.calibrationWizardStage >= 3 ? "Записан" : "Ожидание")
                                        color: root.appController && root.appController.calibrationWizardStage >= 3 ? "#166534" : "#475569"
                                        font.pixelSize: 10
                                        font.bold: true
                                        font.family: "Bahnschrift"
                                    }
                                }

                                Item { Layout.fillWidth: true }

                                FancyButton {
                                    Layout.preferredWidth: 100
                                    Layout.preferredHeight: 30
                                    text: "Прочитать"
                                    tone: "#0f766e"
                                    toneHover: "#115e59"
                                    tonePressed: "#134e4a"
                                    enabled: root.appController !== null
                                    onClicked: if (root.appController) root.appController.readCalibrationLevel100()
                                }
                            }

                            Text {
                                text: "Сохранено: " + (root.appController ? root.appController.calibrationLevel100Text : "-")
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6

                                FancySwitch {
                                    id: custom100Switch
                                    trackWidth: 40
                                    trackHeight: 22
                                }

                                FancyTextField {
                                    id: custom100Field
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 30
                                    enabled: custom100Switch.checked
                                    text: ""
                                    placeholderText: "Текущее / вручную"
                                    textColor: root.textMain
                                    bgColor: root.inputBg
                                    borderColor: root.inputBorder
                                    focusBorderColor: root.inputFocus
                                }

                                FancyButton {
                                    Layout.preferredWidth: 98
                                    Layout.preferredHeight: 30
                                    text: "Сохранить"
                                    tone: "#0284c7"
                                    toneHover: "#0369a1"
                                    tonePressed: "#075985"
                                    enabled: root.appController !== null
                                    onClicked: if (root.appController) root.appController.saveCalibrationLevel100(custom100Switch.checked ? custom100Field.text : "")
                                }
                            }
                        }
                    }
                }

            }

            SpoilerSection {
                id: zeroTrimSpoiler
                Layout.fillWidth: true
                Layout.fillHeight: false
                title: "Подгонка нуля при обслуживании"
                hintText: "Ручной сдвиг показания уровня без повторной калибровки"
                cardColor: "#f8fafc"
                cardBorder: "#dbeafe"
                textMain: root.textMain
                textSoft: root.textSoft
                accentColor: "#0f766e"
                expanded: false

                Rectangle {
                    Layout.fillWidth: true
                    radius: 9
                    color: "#ffffff"
                    border.color: "#d6e2ef"
                    implicitHeight: zeroTrimLayout.implicitHeight + 12

                    ColumnLayout {
                        id: zeroTrimLayout
                        anchors.fill: parent
                        anchors.margins: 6
                        spacing: 6

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            Text {
                                Layout.preferredWidth: 148
                                text: "Смещение 0% (0x002D)"
                                color: root.textSoft
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                            }

                            FancyTextField {
                                id: zeroTrimField
                                Layout.fillWidth: true
                                Layout.preferredHeight: 34
                                placeholderText: "signed dec / 0xHEX"
                                textColor: root.textMain
                                bgColor: root.inputBg
                                borderColor: root.inputBorder
                                focusBorderColor: root.inputFocus
                                onAccepted: if (root.appController) root.appController.writeCalibrationZeroTrim(text)
                            }

                            FancyButton {
                                Layout.preferredWidth: 92
                                Layout.preferredHeight: 32
                                text: "Читать"
                                tone: "#0f766e"
                                toneHover: "#115e59"
                                tonePressed: "#134e4a"
                                enabled: root.appController !== null
                                onClicked: {
                                    if (!root.appController) {
                                        return
                                    }
                                    root.zeroTrimForceRefresh = true
                                    zeroTrimField.focus = false
                                    root.appController.readCalibrationZeroTrim()
                                }
                            }

                            FancyButton {
                                Layout.preferredWidth: 96
                                Layout.preferredHeight: 32
                                text: "Записать"
                                tone: "#0284c7"
                                toneHover: "#0369a1"
                                tonePressed: "#075985"
                                enabled: root.appController !== null
                                onClicked: if (root.appController) root.appController.writeCalibrationZeroTrim(zeroTrimField.text)
                            }

                            FancyButton {
                                Layout.preferredWidth: 84
                                Layout.preferredHeight: 32
                                text: "Сброс"
                                tone: "#475569"
                                toneHover: "#334155"
                                tonePressed: "#1e293b"
                                enabled: root.appController !== null
                                onClicked: if (root.appController) root.appController.resetCalibrationZeroTrim()
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Текущее смещение"
                                valueText: root.appController ? root.appController.calibrationZeroTrimCurrentText : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "Изменение"
                                valueText: root.appController ? root.appController.calibrationZeroTrimDeltaText : "-"
                                labelColor: root.textSoft
                                valueColor: root.textMain
                                fontFamily: "Bahnschrift"
                            }

                            LabelValue {
                                Layout.fillWidth: true
                                labelText: "К записи"
                                valueText: root.appController ? root.appController.calibrationZeroTrimNextText : "-"
                                labelColor: root.textSoft
                                valueColor: "#166534"
                                fontFamily: "Bahnschrift"
                            }
                        }

                        LabelValue {
                            Layout.fillWidth: true
                            labelText: "Остаток после подгонки"
                            valueText: root.appController ? root.appController.calibrationZeroTrimResidualText : "-"
                            labelColor: root.textSoft
                            valueColor: "#334155"
                            fontFamily: "Bahnschrift"
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            radius: 7
                            color: "#f8fafc"
                            border.color: "#d6e2ef"
                            implicitHeight: zeroTrimReportLayout.implicitHeight + 8

                            ColumnLayout {
                                id: zeroTrimReportLayout
                                anchors.fill: parent
                                anchors.margins: 4
                                spacing: 2

                                Text {
                                    Layout.fillWidth: true
                                    text: "Последняя операция"
                                    color: "#334155"
                                    font.pixelSize: 10
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }

                                Text {
                                    Layout.fillWidth: true
                                    text: root.appController ? root.appController.calibrationZeroTrimLastReportText : "Операции подгонки еще не выполнялись."
                                    color: root.textSoft
                                    font.pixelSize: 10
                                    font.family: "Bahnschrift"
                                    wrapMode: Text.WordWrap
                                    maximumLineCount: 3
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        // Ход операции: подгонка идёт несколькими запросами подряд, и без
                        // этой строки оператор не видит, чем она закончилась.
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            Text {
                                Layout.fillWidth: true
                                text: root.appController ? root.appController.calibrationZeroTrimOperationText : "Ожидание операций."
                                color: root.appController && root.appController.calibrationZeroTrimOperationBusy
                                    ? "#0f6ab4"
                                    : root.textMain
                                font.pixelSize: 11
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight
                            }

                            ProgressBar {
                                Layout.preferredWidth: 140
                                Layout.preferredHeight: 6
                                visible: root.appController
                                    ? root.appController.calibrationZeroTrimOperationProgressDeterminate
                                    : false
                                from: 0
                                to: 100
                                value: root.appController ? root.appController.calibrationZeroTrimOperationProgressPercent : 0
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            Text {
                                Layout.fillWidth: true
                                text: "Подгонка меняет только смещение нуля (DID 0x002D). Отметки 0% и 100% и таблицы температурного профиля остаются без изменений."
                                color: root.textSoft
                                font.pixelSize: 10
                                font.family: "Bahnschrift"
                                wrapMode: Text.WordWrap
                            }

                            FancyButton {
                                // Ширина под самую длинную подпись: при 206 точках текст
                                // упирался в края кнопки.
                                Layout.preferredWidth: 226
                                Layout.preferredHeight: 32
                                text: "Подогнать смещение 0% к нулю"
                                tone: "#0f766e"
                                toneHover: "#115e59"
                                tonePressed: "#134e4a"
                                enabled: root.appController !== null
                                onClicked: if (root.appController) root.appController.autoAdjustCalibrationZeroTrimForCurrentPoint()
                            }
                        }
                    }
                }
            }
        }
    }

    // Диалог выбора файла дампа стоял внутри блока температурной компенсации и
    // ушёл бы вместе с ним, хотя к компенсации отношения не имеет.
    FileDialog {
        id: calibrationDumpFileDialog
        title: "Выберите файл дампа калибровки"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Дамп калибровки (*.json)", "JSON файлы (*.json)", "Все файлы (*)"]

        onAccepted: {
            if (!root.appController) {
                return
            }
            function asPathText(value) {
                if (value && value.toString) {
                    return value.toString()
                }
                return String(value)
            }
            var chosenPath = ""
            if (selectedFile) {
                chosenPath = asPathText(selectedFile)
            } else if (currentFile) {
                chosenPath = asPathText(currentFile)
            }
            if (chosenPath.length > 0) {
                root.appController.loadCalibrationBackupDump(chosenPath)
            }
        }
    }

    Connections {
        target: root.appController

        function onCalibrationPollingIntervalChanged() {
            if (!pollIntervalField.activeFocus && root.appController) {
                pollIntervalField.text = String(root.appController.calibrationPollingIntervalMs)
            }
        }

        function onCalibrationNodeSelectionChanged() {
            if (!root.appController) {
                return
            }
            if (nodeSelector.currentIndex !== root.appController.selectedCalibrationNodeIndex) {
                nodeSelector.currentIndex = root.appController.selectedCalibrationNodeIndex
            }
        }

        function onCalibrationZeroTrimChanged() {
            if (!root.appController) {
                return
            }
            // Поле не перезаписывается, пока оператор в нём печатает. Исключение
            // делается сразу после записи в прибор: там нужно показать принятое
            // значение, даже если поле осталось в фокусе.
            if (root.zeroTrimForceRefresh || !zeroTrimField.activeFocus) {
                var currentZeroTrim = root.appController.calibrationZeroTrimCurrentText
                zeroTrimField.text = (currentZeroTrim && currentZeroTrim !== "-") ? currentZeroTrim : ""
                root.zeroTrimForceRefresh = false
            }
        }

        function onCalibrationBackupChanged() {
            if (!root.appController) {
                return
            }

            var saved0 = root.appController.calibrationBackupLevel0Text
            var saved100 = root.appController.calibrationBackupLevel100Text
            var savedZeroTrim = root.appController.calibrationBackupZeroTrimText

            if (!custom0Field.activeFocus) {
                custom0Field.text = (saved0 && saved0 !== "-") ? saved0 : ""
            }
            if (!custom100Field.activeFocus) {
                custom100Field.text = (saved100 && saved100 !== "-") ? saved100 : ""
            }
            if (!zeroTrimField.activeFocus) {
                zeroTrimField.text = (savedZeroTrim && savedZeroTrim !== "-") ? savedZeroTrim : ""
            }
        }
    }

    Component.onCompleted: {
        if (root.appController) {
            nodeSelector.currentIndex = root.appController.selectedCalibrationNodeIndex
            var currentZeroTrim = root.appController.calibrationZeroTrimCurrentText
            zeroTrimField.text = (currentZeroTrim && currentZeroTrim !== "-") ? currentZeroTrim : ""
        }
    }
}

