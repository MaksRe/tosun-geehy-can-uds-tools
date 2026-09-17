import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import "."

/*
  Раздел «Уровень и вид топлива».

  ЗАЧЕМ ОДИН РАЗДЕЛ
  Отметки бака и опорные точки плоского конденсатора снимаются в одних и тех же
  двух положениях датчика: сухом и полностью погружённом. Пока они жили в двух
  разделах, при каждом положении приходилось переключаться между ними и
  вспоминать, что уже снято. Здесь раздел идёт по порядку работы: живые
  показания обоих контуров, шаг «датчик сухой» с отметкой 0 % и точкой
  «воздух», шаг «датчик в топливе» с отметкой 100 % и точкой «топливо», затем
  поправка по виду топлива. Подгонка нуля и резервные копии свёрнуты внизу.

  Публичные свойства:
  - appController: контроллер приложения;
  - cardColor/cardBorder/textMain/textSoft: общая палитра окна;
  - inputBg/inputBorder/inputFocus: цвета полей ввода.
*/
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
    readonly property int contentPadding: 10
    property bool zeroTrimForceRefresh: false

    readonly property bool writeAllowed: root.appController ? root.appController.mediaWizardWriteAllowed : false
    readonly property bool mediaBusy: root.appController ? root.appController.mediaWizardBusy : false
    // Оба контура опрашиваются, пока запущена калибровка.
    readonly property bool calibrationActive: root.appController ? root.appController.calibrationActive : false
    // Стадия сценария калибровки: по ней отметки показывают, записаны ли они в этом сеансе.
    readonly property int wizardStage: root.appController ? root.appController.calibrationWizardStage : 0
    // Два столбца, пока хватает ширины; на узком окне шаги идут друг под другом.
    readonly property bool wide: contentColumn.width >= 820

    Layout.fillWidth: true
    implicitHeight: contentColumn.implicitHeight + (root.contentPadding * 2)
    clip: true

    // Раздел живёт в StackLayout и растянут на всю высоту окна: высоту задаёт
    // содержимое, а всё, что не поместилось, прокручивается.
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
            spacing: 10

            // --- Заголовок и интервал опроса ---
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        Layout.fillWidth: true
                        text: "Уровень и вид топлива"
                        color: root.textMain
                        font.pixelSize: 19
                        font.bold: true
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "Сверху вниз: датчик сухой, датчик в топливе, затем поправка по виду топлива"
                        color: root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }
                }

                // Интервал опроса общий для обоих контуров, поэтому стоит над их карточками.
                Rectangle {
                    Layout.preferredHeight: pollLayout.implicitHeight + 12
                    Layout.preferredWidth: pollLayout.implicitWidth + 20
                    radius: 10
                    color: "#f8fbff"
                    border.width: 1
                    border.color: "#d6e2ef"

                    RowLayout {
                        id: pollLayout
                        anchors.centerIn: parent
                        spacing: 8

                        ColumnLayout {
                            spacing: 0

                            Text {
                                text: "Опрос показаний, мс"
                                color: root.textMain
                                font.pixelSize: 12
                                font.bold: true
                                font.family: "Bahnschrift"
                            }

                            Text {
                                text: "основной контур и плоский конденсатор"
                                color: root.textSoft
                                font.pixelSize: 10
                                font.family: "Bahnschrift"
                            }
                        }

                        FancyTextField {
                            id: pollIntervalField
                            Layout.preferredWidth: 76
                            Layout.preferredHeight: 32
                            text: root.appController ? String(root.appController.calibrationPollingIntervalMs) : "1000"
                            placeholderText: "мс"
                            textColor: root.textMain
                            bgColor: root.inputBg
                            borderColor: root.inputBorder
                            focusBorderColor: root.inputFocus
                            validator: IntValidator { bottom: 100; top: 10000 }
                            onAccepted: if (root.appController) root.appController.setCalibrationPollingIntervalMs(text)
                        }

                        FancyButton {
                            Layout.preferredWidth: 56
                            Layout.preferredHeight: 32
                            text: "OK"
                            tone: "#0284c7"
                            toneHover: "#0369a1"
                            tonePressed: "#075985"
                            toolTipText: "Применить интервал к опросу основного контура и плоского конденсатора"
                            enabled: root.appController !== null
                            onClicked: if (root.appController) root.appController.setCalibrationPollingIntervalMs(pollIntervalField.text)
                        }
                    }
                }
            }

            // --- Живые показания обоих контуров ---
            GridLayout {
                Layout.fillWidth: true
                columns: root.wide ? 2 : 1
                columnSpacing: 10
                rowSpacing: 10

                // Основной контур
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredHeight: mainLiveLayout.implicitHeight + 20
                    radius: 12
                    color: "#f2f7ff"
                    border.width: 1
                    border.color: "#c6dcf5"

                    ColumnLayout {
                        id: mainLiveLayout
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 4

                        Text {
                            text: "Основной контур: период уровня"
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 24

                            ColumnLayout {
                                spacing: 0

                                Text {
                                    text: "Текущий"
                                    color: root.textSoft
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }

                                Text {
                                    text: root.appController ? root.appController.calibrationCurrentLevelText : "-"
                                    color: root.textMain
                                    font.pixelSize: 26
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }
                            }

                            ColumnLayout {
                                spacing: 0

                                Text {
                                    text: "Захват, среднее"
                                    color: root.textSoft
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }

                                Text {
                                    text: root.appController ? root.appController.calibrationCapturedLevelText : "-"
                                    color: "#0f766e"
                                    font.pixelSize: 26
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }
                            }

                            Item { Layout.fillWidth: true }
                        }

                        // Приходят ли ответы и мерит ли основной контур сам.
                        LiveFreshnessLine {
                            Layout.fillWidth: true
                            info: root.appController ? root.appController.calibrationLiveFreshness : ({})
                        }

                        Text {
                            visible: !root.calibrationActive
                            text: "Показания обновляются после «Начать калибровку»"
                            color: "#b45309"
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                        }

                        Item { Layout.fillHeight: true }

                        // Сверка записанной отметки.
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

                // Контур вида топлива: бирюзовый, как полосы блоков точек плоского конденсатора ниже.
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredHeight: mediaLiveLayout.implicitHeight + 20
                    radius: 12
                    color: "#effaf7"
                    border.width: 1
                    border.color: "#a7ddd2"

                    ColumnLayout {
                        id: mediaLiveLayout
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 4

                        Text {
                            text: "Контур вида топлива: плоский конденсатор"
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 24

                            ColumnLayout {
                                spacing: 0

                                Text {
                                    text: "Сейчас"
                                    color: root.textSoft
                                    font.pixelSize: 11
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

                            // Скользящее среднее, как у основного контура: из него точка переносится в поле.
                            ColumnLayout {
                                spacing: 0

                                Text {
                                    text: "Захват, среднее"
                                    color: root.textSoft
                                    font.pixelSize: 11
                                    font.family: "Bahnschrift"
                                }

                                Text {
                                    text: root.appController ? root.appController.mediaWizardCapturedText : "-"
                                    color: "#0f766e"
                                    font.pixelSize: 26
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                }
                            }

                            Text {
                                Layout.alignment: Qt.AlignBottom
                                Layout.bottomMargin: 4
                                text: root.appController ? root.appController.mediaWizardCapturedSpreadText : ""
                                color: root.appController && root.appController.mediaWizardCapturedSpreadWarn ? "#b45309" : root.textSoft
                                font.pixelSize: 11
                                font.bold: root.appController !== null && root.appController.mediaWizardCapturedSpreadWarn
                                font.family: "Bahnschrift"
                            }

                            Item { Layout.fillWidth: true }
                        }

                        // Застывшее число неотличимо от зависшего контура без этой строки.
                        LiveFreshnessLine {
                            Layout.fillWidth: true
                            info: root.appController ? root.appController.mediaWizardLiveFreshness : ({})
                        }

                        Text {
                            visible: !root.calibrationActive
                            text: "Показания обновляются после «Начать калибровку»"
                            color: "#b45309"
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                        }

                        Item { Layout.fillHeight: true }

                        Text {
                            Layout.fillWidth: true
                            text: "Сохраняйте, когда «Захват, среднее» обоих контуров перестанет заметно меняться."
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }

            // --- Два положения датчика ---
            GridLayout {
                Layout.fillWidth: true
                columns: root.wide ? 2 : 1
                columnSpacing: 10
                rowSpacing: 10

                // Шаг 1
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredHeight: dryLayout.implicitHeight + 24
                    radius: 12
                    color: "#fbfdff"
                    border.width: 1
                    border.color: "#e2ebf5"

                    ColumnLayout {
                        id: dryLayout
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 8

                        Text {
                            text: "Шаг 1. Датчик сухой"
                            color: root.textMain
                            font.pixelSize: 15
                            font.bold: true
                            font.family: "Bahnschrift"
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "Выньте датчик из топлива и дайте обсохнуть: на плоском конденсаторе не должно остаться плёнки."
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }

                        CaptureValueBlock {
                            id: mark0
                            title: "Основной контур: отметка 0 %"
                            chipText: root.wizardStage >= 4 ? "ОК" : (root.wizardStage >= 2 ? "Записан" : "Ожидание")
                            chipOk: root.wizardStage >= 2
                            savedText: root.appController ? root.appController.calibrationLevel0Text : "-"
                            capturedText: root.appController ? root.appController.calibrationCapturedLevelText : "-"
                            captureHint: "Подставить в поле усреднённое показание основного контура"
                            accent: "#0284c7"
                            saveEnabled: root.appController !== null
                            readEnabled: root.appController !== null
                            textMain: root.textMain
                            textSoft: root.textSoft
                            inputBg: root.inputBg
                            inputBorder: root.inputBorder
                            inputFocus: root.inputFocus
                            onReadRequested: if (root.appController) root.appController.readCalibrationLevel0()
                            onSaveRequested: function(valueText) {
                                if (root.appController) root.appController.saveCalibrationLevel0(valueText)
                            }
                        }

                        // Точка плоского конденсатора снимается так же, как отметка: захват в поле, затем «Сохранить».
                        CaptureValueBlock {
                            id: pointAir
                            title: "Плоский конденсатор: точка «воздух»"
                            savedText: root.appController ? root.appController.mediaWizardAirText : "-"
                            capturedText: root.appController ? root.appController.mediaWizardCapturedText : "-"
                            captureHint: "Подставить в поле усреднённое показание плоского конденсатора"
                            accent: "#0f766e"
                            saveEnabled: root.appController !== null && !root.mediaBusy
                            readEnabled: root.appController !== null && !root.mediaBusy
                            textMain: root.textMain
                            textSoft: root.textSoft
                            inputBg: root.inputBg
                            inputBorder: root.inputBorder
                            inputFocus: root.inputFocus
                            onReadRequested: if (root.appController) root.appController.refreshMediaWizardSaved()
                            onSaveRequested: function(valueText) {
                                if (root.appController) root.appController.saveMediaWizardAir(valueText)
                            }
                        }

                        Item { Layout.fillHeight: true }
                    }
                }

                // Шаг 2
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredHeight: fuelLayout.implicitHeight + 24
                    radius: 12
                    color: "#fbfdff"
                    border.width: 1
                    border.color: "#e2ebf5"

                    ColumnLayout {
                        id: fuelLayout
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 8

                        Text {
                            text: "Шаг 2. Датчик полностью в топливе"
                            color: root.textMain
                            font.pixelSize: 15
                            font.bold: true
                            font.family: "Bahnschrift"
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "Погрузите датчик полностью в то топливо, по которому калибруете: плоский конденсатор должен быть залит целиком."
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }

                        CaptureValueBlock {
                            id: mark100
                            title: "Основной контур: отметка 100 %"
                            chipText: root.wizardStage >= 4 ? "ОК" : (root.wizardStage >= 3 ? "Записан" : "Ожидание")
                            chipOk: root.wizardStage >= 3
                            savedText: root.appController ? root.appController.calibrationLevel100Text : "-"
                            capturedText: root.appController ? root.appController.calibrationCapturedLevelText : "-"
                            captureHint: "Подставить в поле усреднённое показание основного контура"
                            accent: "#0284c7"
                            saveEnabled: root.appController !== null
                            readEnabled: root.appController !== null
                            textMain: root.textMain
                            textSoft: root.textSoft
                            inputBg: root.inputBg
                            inputBorder: root.inputBorder
                            inputFocus: root.inputFocus
                            onReadRequested: if (root.appController) root.appController.readCalibrationLevel100()
                            onSaveRequested: function(valueText) {
                                if (root.appController) root.appController.saveCalibrationLevel100(valueText)
                            }
                        }

                        // Точка плоского конденсатора снимается так же, как отметка: захват в поле, затем «Сохранить».
                        CaptureValueBlock {
                            id: pointLiquid
                            title: "Плоский конденсатор: точка «топливо»"
                            savedText: root.appController ? root.appController.mediaWizardCalText : "-"
                            capturedText: root.appController ? root.appController.mediaWizardCapturedText : "-"
                            captureHint: "Подставить в поле усреднённое показание плоского конденсатора"
                            accent: "#0f766e"
                            saveEnabled: root.appController !== null && !root.mediaBusy
                            readEnabled: root.appController !== null && !root.mediaBusy
                            textMain: root.textMain
                            textSoft: root.textSoft
                            inputBg: root.inputBg
                            inputBorder: root.inputBorder
                            inputFocus: root.inputFocus
                            onReadRequested: if (root.appController) root.appController.refreshMediaWizardSaved()
                            onSaveRequested: function(valueText) {
                                if (root.appController) root.appController.saveMediaWizardLiquid(valueText)
                            }
                        }

                        Item { Layout.fillHeight: true }
                    }
                }
            }

            // --- Шаг 3 ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: stepThreeLayout.implicitHeight + 24
                radius: 12
                color: "#fbfdff"
                border.width: 1
                border.color: "#e2ebf5"

                GridLayout {
                    id: stepThreeLayout
                    anchors.fill: parent
                    anchors.margins: 12
                    columns: root.wide ? 2 : 1
                    columnSpacing: 8
                    rowSpacing: 8

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Text {
                            text: "Шаг 3. Поправка по виду топлива"
                            color: root.textMain
                            font.pixelSize: 15
                            font.bold: true
                            font.family: "Bahnschrift"
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "Разница точек: " + (root.appController ? root.appController.mediaWizardSpanText : "-")
                                + ".  Сейчас: " + (root.appController ? root.appController.mediaWizardEnabledText : "-")
                            color: root.textSoft
                            font.pixelSize: 12
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }
                    }

                    // Кнопки всегда одним рядом: на узком окне ряд уходит под текст, а не в столбик.
                    RowLayout {
                        spacing: 8

                        FancyButton {
                            Layout.preferredWidth: 170
                            Layout.preferredHeight: 34
                            text: "Прочитать точки"
                            tone: "#64748b"
                            toneHover: "#475569"
                            tonePressed: "#334155"
                            toolTipText: "Прочитать из прибора точки «воздух», «топливо» и состояние поправки"
                            enabled: root.appController !== null && !root.mediaBusy
                            onClicked: if (root.appController) root.appController.refreshMediaWizardSaved()
                        }

                        FancyButton {
                            Layout.preferredWidth: 130
                            Layout.preferredHeight: 34
                            text: "Включить"
                            tone: "#16a34a"
                            toneHover: "#15803d"
                            tonePressed: "#166534"
                            enabled: root.appController !== null && root.writeAllowed && !root.mediaBusy
                                && root.appController.mediaWizardCanEnable
                            onClicked: if (root.appController) root.appController.setMediaWizardEnabled(true)
                        }

                        FancyButton {
                            Layout.preferredWidth: 130
                            Layout.preferredHeight: 34
                            text: "Выключить"
                            tone: "#64748b"
                            toneHover: "#475569"
                            tonePressed: "#334155"
                            enabled: root.appController !== null && root.writeAllowed && !root.mediaBusy
                            onClicked: if (root.appController) root.appController.setMediaWizardEnabled(false)
                        }
                    }
                }
            }

            // --- Ход работы ---
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: statusLayout.implicitHeight + 20
                radius: 10
                color: "#f8fbff"
                border.width: 1
                border.color: "#d6e2ef"

                ColumnLayout {
                    id: statusLayout
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 4

                    RowLayout {
                        Layout.fillWidth: true
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
                            wrapMode: Text.WordWrap
                        }
                    }

                    // Итог записи вида топлива к последней отметке: нужен модели уровня по двум контурам.
                    Text {
                        Layout.fillWidth: true
                        Layout.leftMargin: 22
                        visible: text !== ""
                        text: root.appController ? root.appController.calibrationMarkMediaStatus : ""
                        color: root.appController ? root.appController.calibrationMarkMediaStatusColor : root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // --- Подгонка нуля ---
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

            // --- Резервные копии ---
            SpoilerSection {
                id: backupSpoiler
                Layout.fillWidth: true
                Layout.fillHeight: false
                title: "Резервные копии калибровки"
                hintText: "Дамп текущего узла: сохранить, загрузить и применить в прибор"
                cardColor: "#f8fafc"
                cardBorder: "#dbeafe"
                textMain: root.textMain
                textSoft: root.textSoft
                accentColor: "#2563eb"
                expanded: false

                Rectangle {
                    Layout.fillWidth: true
                    radius: 9
                    color: "#ffffff"
                    border.color: "#d6e2ef"
                    implicitHeight: backupLayout.implicitHeight + 14

                    ColumnLayout {
                        id: backupLayout
                        anchors.fill: parent
                        anchors.margins: 7
                        spacing: 6

                        Text {
                            Layout.fillWidth: true
                            text: root.appController ? root.appController.calibrationBackupSourceText : "Дамп калибровки не сохранен."
                            color: root.textSoft
                            font.pixelSize: 11
                            font.family: "Bahnschrift"
                            elide: Text.ElideRight
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

                            Item { Layout.fillWidth: true }
                        }
                    }
                }
            }
        }
    }

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
            mark0.setValueIfIdle(root.appController.calibrationBackupLevel0Text)
            mark100.setValueIfIdle(root.appController.calibrationBackupLevel100Text)
            if (!zeroTrimField.activeFocus) {
                var savedZeroTrim = root.appController.calibrationBackupZeroTrimText
                zeroTrimField.text = (savedZeroTrim && savedZeroTrim !== "-") ? savedZeroTrim : ""
            }
        }
    }

    Component.onCompleted: {
        if (root.appController) {
            var currentZeroTrim = root.appController.calibrationZeroTrimCurrentText
            zeroTrimField.text = (currentZeroTrim && currentZeroTrim !== "-") ? currentZeroTrim : ""
        }
    }
}
