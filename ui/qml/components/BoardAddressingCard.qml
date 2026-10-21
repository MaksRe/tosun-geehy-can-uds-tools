import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Раздел «Адреса плат».
  Назначение:
  - мастер назначает каждой новой плате свой адрес на шине CAN: оператор
    подключает платы по одной, мастер сам находит новую, записывает адрес,
    проверяет его чтением, выключает рассылку J1939 платы и проверяет тишину;
  - адрес выбирает мастер (следующий свободный) или оператор: в ручном режиме
    мастер, найдя плату, ждёт адрес и имя;
  - каждый шаг с таймаутом и повторами, при сбое - причина и кнопка повтора;
  - карточки всех плат камеры: адрес, температуры, контуры, профиль.

  Публичные свойства:
  - appController: контроллер приложения;
  - textMain/textSoft: общая палитра окна;
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

    readonly property var addr: root.appController ? root.appController.boardAddressing : ({})
    readonly property bool active: !!root.addr.active
    readonly property bool manual: root.addr.mode === "manual"
    readonly property bool asking: !!root.addr.asking

    // Мастер нашёл плату и ждёт адрес: поля заполняются подсказкой, курсор - в поле адреса.
    onAskingChanged: {
        if (!root.asking)
            return
        manualSaField.text = root.addr.newSa || ""
        manualNameField.text = root.addr.suggestName || ""
        manualSaField.forceActiveFocus()
        manualSaField.selectAll()
    }

    function confirmManual() {
        if (root.appController)
            root.appController.confirmBoardAddress(manualSaField.text, manualNameField.text)
    }
    readonly property var toneColors: ({ "ok": "#16a34a", "bad": "#dc2626", "normal": "#64748b" })

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    component Caption: Text {
        color: root.textSoft
        font.pixelSize: 12
        font.family: "Bahnschrift"
        Layout.alignment: Qt.AlignVCenter
    }

    component SmallButton: FancyButton {
        Layout.preferredHeight: 30
        fontPixelSize: 12
        tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
    }

    // Шаг мастера: кружок состояния и подпись.
    component StepPill: Rectangle {
        id: stepPill
        required property var modelData
        readonly property string state_: stepPill.modelData.state || ""
        width: stepRow.implicitWidth + 20
        height: 28
        radius: 14
        color: stepPill.state_ === "ok" ? "#f0fdf4" : stepPill.state_ === "fail" ? "#fef2f2"
               : stepPill.state_ === "run" ? "#eff6ff" : "#f8fafc"
        border.width: 1
        border.color: stepPill.state_ === "ok" ? "#bbf7d0" : stepPill.state_ === "fail" ? "#fecaca"
                      : stepPill.state_ === "run" ? "#bfdbfe" : "#e2e8f0"

        Row {
            id: stepRow
            anchors.centerIn: parent
            spacing: 6

            Rectangle {
                id: stepDot
                anchors.verticalCenter: parent.verticalCenter
                width: 14
                height: 14
                radius: 7
                color: stepPill.state_ === "ok" ? "#16a34a" : stepPill.state_ === "fail" ? "#dc2626"
                       : stepPill.state_ === "run" ? "#2563eb" : "#cbd5e1"

                Text {
                    anchors.centerIn: parent
                    text: stepPill.state_ === "ok" ? "✓" : stepPill.state_ === "fail" ? "✕" : ""
                    color: "#ffffff"
                    font.pixelSize: 10
                    font.bold: true
                }

                // Идущий шаг мерцает: видно, что мастер работает.
                SequentialAnimation on opacity {
                    running: stepPill.state_ === "run"
                    loops: Animation.Infinite
                    onRunningChanged: if (!running) stepDot.opacity = 1.0
                    NumberAnimation { to: 0.35; duration: 450 }
                    NumberAnimation { to: 1.0; duration: 450 }
                }
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: stepPill.modelData.title
                color: stepPill.state_ === "" ? "#94a3b8" : root.textMain
                font.pixelSize: 12
                font.family: "Bahnschrift"
            }
        }
    }

    // Строка карточки: подпись слева, значение справа.
    component InfoRow: RowLayout {
        id: infoRow
        property string label: ""
        property string value: ""
        property color valueColor: root.textMain
        Layout.fillWidth: true
        spacing: 6

        Text {
            text: infoRow.label
            color: root.textSoft
            font.pixelSize: 12
            font.family: "Bahnschrift"
        }
        Item { Layout.fillWidth: true }
        Text {
            text: infoRow.value
            color: infoRow.valueColor
            font.pixelSize: 13
            font.family: "Bahnschrift"
            font.bold: true
        }
    }

    // Карточка платы: имя и адрес, состояние рассылки, показания и профиль.
    component BoardCard: Rectangle {
        id: boardCard
        required property var modelData
        width: 268
        height: boardLayout.implicitHeight + 28
        radius: 12
        color: "#ffffff"
        border.width: 1
        border.color: "#e2e8f0"

        ColumnLayout {
            id: boardLayout
            anchors.fill: parent
            anchors.margins: 14
            spacing: 6

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: boardCard.modelData.name || boardCard.modelData.saText
                    color: root.textMain
                    font.pixelSize: 17
                    font.bold: true
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                    Layout.maximumWidth: 120
                }
                Rectangle {
                    Layout.preferredWidth: saText.implicitWidth + 14
                    Layout.preferredHeight: 22
                    radius: 11
                    color: "#eff6ff"
                    Text {
                        id: saText
                        anchors.centerIn: parent
                        text: boardCard.modelData.saText
                        color: "#1d4ed8"
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Consolas"
                    }
                }
                Item { Layout.fillWidth: true }
                // Рассылка выключена - плата не мешает на шине.
                Rectangle {
                    Layout.preferredWidth: quietText.implicitWidth + 14
                    Layout.preferredHeight: 22
                    radius: 11
                    color: boardCard.modelData.quiet ? "#f0fdf4" : "#fffbeb"
                    Text {
                        id: quietText
                        anchors.centerIn: parent
                        text: boardCard.modelData.quiet ? "тихая" : "рассылка"
                        color: boardCard.modelData.quiet ? "#15803d" : "#b45309"
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: text.length > 0
                text: (boardCard.modelData.oldSa ? "был " + boardCard.modelData.oldSa : "")
                      + (boardCard.modelData.oldSa && boardCard.modelData.addressedAt ? " · " : "")
                      + (boardCard.modelData.addressedAt ? "назначен " + boardCard.modelData.addressedAt : "")
                color: root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
            }

            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#eef2f7" }

            InfoRow { label: "Плата"; value: boardCard.modelData.boardTemp }
            InfoRow { label: "Топливо"; value: boardCard.modelData.fuelTemp }
            InfoRow { label: "Основной контур"; value: boardCard.modelData.main }
            InfoRow { label: "Контур вида топлива"; value: boardCard.modelData.media }

            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#eef2f7" }

            InfoRow {
                label: "Профиль"
                value: boardCard.modelData.profileText
                valueColor: root.toneColors[boardCard.modelData.profileTone] || root.textMain
            }
            InfoRow {
                label: "Сумма · поколение"
                value: boardCard.modelData.profileCrc + " · " + boardCard.modelData.profileGeneration
            }
            InfoRow { label: "Программа"; value: boardCard.modelData.program }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 6

                Caption {
                    Layout.fillWidth: true
                    text: boardCard.modelData.reading ? "читаю..."
                          : (boardCard.modelData.readAt ? "прочитано " + boardCard.modelData.readAt : "ещё не прочитано")
                    font.pixelSize: 11
                }
                SmallButton {
                    Layout.preferredWidth: 86
                    Layout.preferredHeight: 26
                    fontPixelSize: 11
                    text: "Обновить"
                    enabled: !boardCard.modelData.reading
                    tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                    onClicked: if (root.appController) root.appController.refreshBoardInfo(boardCard.modelData.sa)
                }
            }
        }
    }

    ScrollView {
        id: pageScroll
        anchors.fill: parent
        anchors.margins: 14
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        ColumnLayout {
            width: pageScroll.availableWidth
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "Адреса плат"
                    color: root.textMain
                    font.pixelSize: 19
                    font.bold: true
                    font.family: "Bahnschrift"
                }
                InfoMark {
                    tip: "Для прогона нескольких плат в камере у каждой нужен свой адрес на шине CAN.<br><br>"
                         + "Адрес новой плате выбирает мастер (<b>Автоматически</b>: следующий свободный, начиная с "
                         + "первого) или вы (<b>Вручную</b>: найдя плату, мастер ждёт адрес и имя).<br><br>"
                         + "Запустите мастер и подключайте платы <b>по одной</b>. Для каждой мастер сам: находит её, "
                         + "открывает доступ, записывает новый адрес, проверяет его чтением, выключает рассылку J1939 "
                         + "платы (чтобы она не мешала найти следующую) и проверяет, что на шине тихо. "
                         + "Каждый шаг ждёт подтверждения платы до 1,5 с, до 3 попыток.<br><br>"
                         + "Рассылка остаётся выключенной до перезагрузки питания платы. Если настроенная плата снова "
                         + "зашумит, мастер выключит её рассылку сам. Готовые платы сразу попадают в «Платы в камере»."
                }
                Item { Layout.fillWidth: true }
            }

            // Мастер: первый адрес, запуск и остановка.
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: wizardLayout.implicitHeight + 28
                radius: 12
                color: root.active ? "#f8fbff" : "#f8fafc"
                border.width: 1
                border.color: root.active ? "#c6dcf5" : "#e2e8f0"

                ColumnLayout {
                    id: wizardLayout
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 12

                    // Кто выбирает адрес новой плате: мастер или оператор.
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Caption { text: "Адрес новой плате" }
                        Row {
                            spacing: 0
                            Repeater {
                                model: [{ "key": "auto", "title": "Автоматически" }, { "key": "manual", "title": "Вручную" }]

                                FancyButton {
                                    required property var modelData
                                    width: 130
                                    height: 30
                                    fontPixelSize: 12
                                    text: modelData.title
                                    toolTipText: modelData.key === "auto"
                                                 ? "Мастер сам берёт следующий свободный адрес, начиная с первого"
                                                 : "Найдя плату, мастер ждёт адрес и имя от вас (подсказывает следующий свободный)"
                                    tone: (root.addr.mode || "auto") === modelData.key ? "#0284c7" : "#cbd5e1"
                                    toneHover: "#0369a1"
                                    tonePressed: "#075985"
                                    onClicked: if (root.appController) root.appController.setBoardAddressingMode(modelData.key)
                                }
                            }
                        }
                        Item { Layout.fillWidth: true }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Caption { text: root.manual ? "Подсказывать с" : "Первый адрес" }
                        FancyTextField {
                            id: startField
                            Layout.preferredWidth: 80
                            Layout.preferredHeight: 30
                            enabled: !root.active
                            textColor: root.textMain
                            bgColor: root.inputBg
                            borderColor: root.inputBorder
                            focusBorderColor: root.inputFocus
                            Component.onCompleted: startField.text = root.addr.startText || "0x81"
                        }
                        FancyButton {
                            Layout.preferredWidth: 150
                            Layout.preferredHeight: 30
                            fontPixelSize: 13
                            text: root.active ? "Остановить" : "Запустить мастер"
                            tone: root.active ? "#64748b" : "#16a34a"
                            toneHover: root.active ? "#475569" : "#15803d"
                            tonePressed: root.active ? "#334155" : "#166534"
                            onClicked: {
                                if (!root.appController)
                                    return
                                if (root.active)
                                    root.appController.stopBoardAddressing()
                                else
                                    root.appController.startBoardAddressing(startField.text)
                            }
                        }
                        Item { Layout.fillWidth: true }
                        SmallButton {
                            Layout.preferredWidth: 130
                            text: "Обновить карточки"
                            enabled: (root.addr.cards || []).length > 0
                            onClicked: if (root.appController) root.appController.refreshBoardInfo(-1)
                        }
                        SmallButton {
                            Layout.preferredWidth: 170
                            text: "Вернуть рассылку всем"
                            toolTipText: "Всем платам на шине: снова слать обычную рассылку J1939 (мастер остановится)"
                            tone: "#b45309"; toneHover: "#92400e"; tonePressed: "#78350f"
                            onClicked: if (root.appController) root.appController.releaseBoardsTraffic()
                        }
                    }

                    // Плата, с которой идёт работа: старый адрес -> новый.
                    RowLayout {
                        Layout.fillWidth: true
                        visible: (root.addr.candidate || "").length > 0
                        spacing: 12

                        Text {
                            text: "Плата " + (root.addr.boardNumber || 0)
                            color: root.textMain
                            font.pixelSize: 15
                            font.bold: true
                            font.family: "Bahnschrift"
                        }
                        Text {
                            text: (root.addr.candidate || "") + "  →  " + (root.asking ? "?" : (root.addr.newSa || ""))
                            color: "#1d4ed8"
                            font.pixelSize: 15
                            font.bold: true
                            font.family: "Consolas"
                        }
                    }

                    // Ручной режим: плата найдена, мастер ждёт адрес и имя.
                    Rectangle {
                        Layout.fillWidth: true
                        visible: root.asking
                        Layout.preferredHeight: askLayout.implicitHeight + 20
                        radius: 10
                        color: "#eff6ff"
                        border.width: 1
                        border.color: "#93c5fd"

                        RowLayout {
                            id: askLayout
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 10

                            Caption { text: "Новый адрес" }
                            FancyTextField {
                                id: manualSaField
                                Layout.preferredWidth: 80
                                Layout.preferredHeight: 30
                                placeholderText: "0x81"
                                textColor: root.textMain
                                bgColor: "#ffffff"
                                borderColor: root.inputBorder
                                focusBorderColor: root.inputFocus
                                onAccepted: root.confirmManual()
                            }
                            Caption { text: "Имя" }
                            FancyTextField {
                                id: manualNameField
                                Layout.preferredWidth: 160
                                Layout.preferredHeight: 30
                                placeholderText: "П1"
                                textColor: root.textMain
                                bgColor: "#ffffff"
                                borderColor: root.inputBorder
                                focusBorderColor: root.inputFocus
                                onAccepted: root.confirmManual()
                            }
                            FancyButton {
                                Layout.preferredWidth: 120
                                Layout.preferredHeight: 30
                                fontPixelSize: 13
                                text: "Назначить"
                                tone: "#16a34a"; toneHover: "#15803d"; tonePressed: "#166534"
                                onClicked: root.confirmManual()
                            }
                            Item { Layout.fillWidth: true }
                            SmallButton {
                                Layout.preferredWidth: 140
                                text: "Пропустить плату"
                                onClicked: if (root.appController) root.appController.skipBoardAddressingBoard()
                            }
                        }
                    }

                    Flow {
                        Layout.fillWidth: true
                        visible: root.active || root.addr.failed
                        spacing: 6

                        Repeater {
                            model: root.addr.steps || []
                            StepPill {}
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Rectangle {
                            Layout.alignment: Qt.AlignVCenter
                            Layout.preferredWidth: 10
                            Layout.preferredHeight: 10
                            radius: 5
                            color: root.addr.statusColor || "#64748b"

                            SequentialAnimation on opacity {
                                running: root.active && !!root.addr.waiting
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.3; duration: 700 }
                                NumberAnimation { to: 1.0; duration: 700 }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: root.addr.status || ""
                            color: root.addr.statusColor || root.textMain
                            font.pixelSize: 13
                            font.family: "Bahnschrift"
                            wrapMode: Text.WordWrap
                        }
                        SmallButton {
                            visible: !!root.addr.failed
                            Layout.preferredWidth: 130
                            text: "Повторить шаг"
                            tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                            onClicked: if (root.appController) root.appController.retryBoardAddressingStep()
                        }
                        SmallButton {
                            visible: !!root.addr.failed
                            Layout.preferredWidth: 140
                            text: "Пропустить плату"
                            onClicked: if (root.appController) root.appController.skipBoardAddressingBoard()
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 8

                Text {
                    text: "Платы в камере"
                    color: root.textMain
                    font.pixelSize: 15
                    font.bold: true
                    font.family: "Bahnschrift"
                }
                Caption { text: String((root.addr.cards || []).length) }
                Item { Layout.fillWidth: true }
            }

            Caption {
                visible: (root.addr.cards || []).length === 0
                Layout.fillWidth: true
                text: "Пока ни одной. Запустите мастер и подключите первую плату: после настройки она появится здесь."
                wrapMode: Text.WordWrap
            }

            Flow {
                Layout.fillWidth: true
                spacing: 12

                Repeater {
                    model: root.addr.cards || []
                    BoardCard {}
                }
            }

            Item { Layout.preferredHeight: 4 }
        }
    }
}
