import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Раздел «Адреса плат».
  Назначение:
  - мастер назначает каждой новой плате свой адрес на шине CAN: оператор
    подключает платы по одной, мастер сам находит новую, записывает адрес,
    проверяет его чтением, выключает передачу J1939 платы и проверяет тишину;
  - адрес выбирает мастер (следующий свободный) или оператор: в ручном режиме
    мастер, найдя плату, ждёт адрес и имя;
  - каждый шаг с таймаутом и повторами, при сбое - причина и кнопка повтора;
  - карточки всех плат камеры одинакового вида: имя и адрес (меняются прямо в
    карточке), показания, профиль, трафик J1939 - режим CommunicationControl
    (0x28) с подтверждением платы и то, что видно на шине.

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
    readonly property bool readdress: !!root.addr.readdress
    readonly property var toneColors: ({ "ok": "#16a34a", "bad": "#dc2626", "warn": "#d97706", "normal": "#64748b" })
    readonly property int boardCardWidth: 300

    cardColor: "#ffffff"
    cardBorder: "#d6e2ef"

    // Пока раздел открыт, программа опрашивает, какие платы на шине, и показывает только их.
    onVisibleChanged: if (root.appController) root.appController.setBoardAddressingVisible(root.visible)
    Component.onCompleted: if (root.appController) root.appController.setBoardAddressingVisible(root.visible)

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

    component Caption: Text {
        color: root.textSoft
        font.pixelSize: 12
        font.family: "Bahnschrift"
        Layout.alignment: Qt.AlignVCenter
    }

    component SectionTitle: Text {
        color: root.textSoft
        font.pixelSize: 11
        font.bold: true
        font.family: "Bahnschrift"
        font.capitalization: Font.AllUppercase
        font.letterSpacing: 0.6
        Layout.topMargin: 2
    }

    component SmallButton: FancyButton {
        Layout.preferredHeight: 30
        fontPixelSize: 12
        tone: "#64748b"; toneHover: "#475569"; tonePressed: "#334155"
    }

    component Divider: Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 1
        color: "#eef2f7"
    }

    // Переключатель из нескольких вариантов: выбранный - синий, остальные - светлые с тёмным текстом.
    component Segmented: Rectangle {
        id: segmented
        property var options: []
        property var current
        property bool active: true
        property int itemWidth: 120
        property int itemHeight: 30
        property int fontSize: 12
        signal picked(var key)
        implicitWidth: segmentedRow.implicitWidth + 2
        implicitHeight: segmented.itemHeight
        Layout.preferredWidth: segmented.implicitWidth
        Layout.preferredHeight: segmented.itemHeight
        radius: 8
        color: "#f1f5f9"
        border.width: 1
        border.color: "#d6e2ef"
        opacity: segmented.active ? 1.0 : 0.55

        Row {
            id: segmentedRow
            anchors.centerIn: parent
            spacing: 0

            Repeater {
                model: segmented.options

                Rectangle {
                    id: segment
                    required property var modelData
                    readonly property bool selected: segmented.current === segment.modelData.key
                    width: segmented.itemWidth
                    height: segmented.itemHeight - 2
                    radius: 7
                    color: segment.selected ? "#0284c7" : (segmentArea.containsMouse && segmented.active ? "#e2e8f0" : "transparent")

                    Text {
                        anchors.centerIn: parent
                        text: segment.modelData.title
                        color: segment.selected ? "#ffffff" : root.textMain
                        font.pixelSize: segmented.fontSize
                        font.bold: segment.selected
                        font.family: "Bahnschrift"
                    }

                    MouseArea {
                        id: segmentArea
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: segmented.active
                        cursorShape: segmented.active ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: segmented.picked(segment.modelData.key)
                    }

                    ToolTip.visible: segmentArea.containsMouse && (segment.modelData.hint || "").length > 0
                    ToolTip.delay: 400
                    ToolTip.text: segment.modelData.hint || ""
                }
            }
        }
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
        Layout.preferredHeight: 18
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
            elide: Text.ElideLeft
            Layout.maximumWidth: 190
        }
    }

    // Метка-плашка: короткое состояние цветом.
    component Chip: Rectangle {
        id: chip
        property string text: ""
        property color fg: "#475569"
        property color bg: "#f1f5f9"
        Layout.preferredWidth: chipText.implicitWidth + 16
        Layout.preferredHeight: 22
        radius: 11
        color: chip.bg

        Text {
            id: chipText
            anchors.centerIn: parent
            text: chip.text
            color: chip.fg
            font.pixelSize: 11
            font.bold: true
            font.family: "Bahnschrift"
        }
    }

    // Карточка платы: у всех карточек одни и те же строки, поэтому они одной высоты.
    component BoardCard: Rectangle {
        id: boardCard
        required property var modelData
        property bool editingName: false
        property bool editingSa: false
        // Причина, по которой адрес не записан: видна прямо под полем, поле остаётся открытым.
        property string saError: ""
        readonly property bool editable: !!root.addr.editable
        width: root.boardCardWidth
        height: boardLayout.implicitHeight + 28
        radius: 12
        color: "#ffffff"
        border.width: 1
        border.color: boardCard.modelData.readdressing ? "#93c5fd" : "#e2e8f0"

        function saveName() {
            if (root.appController && nameField.text !== boardCard.modelData.name)
                root.appController.renameAddressedBoard(boardCard.modelData.sa, nameField.text)
            boardCard.editingName = false
        }

        function saveSa() {
            if (!root.appController)
                return
            var error = root.appController.readdressBoard(boardCard.modelData.sa, saField.text)
            boardCard.saError = error || ""
            if (!error)
                boardCard.editingSa = false
        }

        ColumnLayout {
            id: boardLayout
            anchors.fill: parent
            anchors.margins: 14
            spacing: 6

            // Имя (меняется по щелчку), адрес и трафик J1939, видимый на шине.
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 30
                spacing: 8

                Text {
                    visible: !boardCard.editingName
                    text: boardCard.modelData.name || boardCard.modelData.saText
                    color: root.textMain
                    font.pixelSize: 17
                    font.bold: true
                    font.family: "Bahnschrift"
                    elide: Text.ElideRight
                    Layout.maximumWidth: 120

                    MouseArea {
                        id: nameArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.IBeamCursor
                        onClicked: {
                            nameField.text = boardCard.modelData.name
                            boardCard.editingName = true
                            nameField.forceActiveFocus()
                            nameField.selectAll()
                        }
                    }
                    ToolTip.visible: nameArea.containsMouse
                    ToolTip.delay: 500
                    ToolTip.text: "Щёлкните, чтобы изменить имя"
                }
                FancyTextField {
                    id: nameField
                    visible: boardCard.editingName
                    Layout.preferredWidth: 130
                    Layout.preferredHeight: 30
                    textColor: root.textMain
                    bgColor: root.inputBg
                    borderColor: root.inputBorder
                    focusBorderColor: root.inputFocus
                    onAccepted: boardCard.saveName()
                    onActiveFocusChanged: if (!activeFocus && boardCard.editingName) boardCard.saveName()
                    Keys.onEscapePressed: boardCard.editingName = false
                }
                Chip {
                    text: boardCard.modelData.saText
                    fg: "#1d4ed8"
                    bg: "#eff6ff"
                }
                Item { Layout.fillWidth: true }
                Chip {
                    text: !boardCard.modelData.listening ? "Трафик ?" : (boardCard.modelData.onBus ? "Трафик вкл" : "Трафик выкл")
                    fg: !boardCard.modelData.listening ? "#64748b" : (boardCard.modelData.onBus ? "#b45309" : "#15803d")
                    bg: !boardCard.modelData.listening ? "#f1f5f9" : (boardCard.modelData.onBus ? "#fffbeb" : "#f0fdf4")
                }
            }

            Text {
                Layout.fillWidth: true
                text: boardCard.modelData.history
                color: root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
                elide: Text.ElideRight
            }

            Divider {}
            SectionTitle {
                text: "Показания" + (boardCard.modelData.reading ? " · читаю..."
                                     : (boardCard.modelData.readAt ? " · " + boardCard.modelData.readAt : ""))
            }
            InfoRow { label: "Температура платы"; value: boardCard.modelData.boardTemp }
            InfoRow { label: "Температура топлива"; value: boardCard.modelData.fuelTemp }
            InfoRow { label: "Основной контур"; value: boardCard.modelData.main }
            InfoRow { label: "Контур вида топлива"; value: boardCard.modelData.media }

            Divider {}
            SectionTitle { text: "Профиль" }
            InfoRow {
                label: "Состояние"
                value: boardCard.modelData.profileText
                valueColor: root.toneColors[boardCard.modelData.profileTone] || root.textMain
            }
            InfoRow { label: "Сумма · поколение"; value: boardCard.modelData.profileCrc + " · " + boardCard.modelData.profileGeneration }
            InfoRow { label: "Программа"; value: boardCard.modelData.program }

            Divider {}
            SectionTitle { text: "Трафик J1939 · UDS 0x28" }
            InfoRow { label: "Режим"; value: boardCard.modelData.commText }
            InfoRow {
                label: "На шине"
                value: boardCard.modelData.trafficText
                valueColor: boardCard.modelData.onBus ? "#b45309" : root.textMain
            }
            Segmented {
                Layout.topMargin: 2
                options: (root.addr.commModes || []).map(function(item) {
                    return { "key": item.mode, "title": item.button, "hint": item.state + ". " + item.hint }
                })
                current: boardCard.modelData.comm
                active: !boardCard.modelData.commBusy && boardCard.editable
                itemWidth: 67
                itemHeight: 28
                fontSize: 11
                onPicked: (key) => { if (root.appController) root.appController.setBoardTraffic(boardCard.modelData.sa, key) }
            }
            Text {
                Layout.fillWidth: true
                Layout.preferredHeight: 15
                text: boardCard.modelData.commResult || " "
                color: root.toneColors[boardCard.modelData.commTone] || root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
                elide: Text.ElideRight
            }

            Divider {}
            // Низ карточки: обычные кнопки или поле нового адреса - одной высоты.
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 30
                spacing: 6
                visible: !boardCard.editingSa

                SmallButton {
                    Layout.preferredWidth: 130
                    Layout.preferredHeight: 28
                    fontPixelSize: 11
                    text: boardCard.modelData.readdressing ? "Меняю адрес..." : "Изменить адрес"
                    enabled: boardCard.editable
                    toolTipText: boardCard.editable ? "Записать плате другой адрес (с проверкой чтением)"
                                                    : "Сейчас нельзя: идёт работа мастера или прогон"
                    onClicked: {
                        saField.text = boardCard.modelData.saText
                        boardCard.saError = ""
                        boardCard.editingSa = true
                        saField.forceActiveFocus()
                        saField.selectAll()
                    }
                }
                Item { Layout.fillWidth: true }
                SmallButton {
                    Layout.preferredWidth: 100
                    Layout.preferredHeight: 28
                    fontPixelSize: 11
                    text: "Обновить"
                    enabled: !boardCard.modelData.reading
                    tone: "#0284c7"; toneHover: "#0369a1"; tonePressed: "#075985"
                    onClicked: if (root.appController) root.appController.refreshBoardInfo(boardCard.modelData.sa)
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 30
                spacing: 6
                visible: boardCard.editingSa

                // Поле растягивается на свободное место: строка не шире карточки при любом масштабе шрифтов.
                FancyTextField {
                    id: saField
                    Layout.fillWidth: true
                    Layout.minimumWidth: 60
                    Layout.preferredHeight: 28
                    placeholderText: "новый адрес, HEX"
                    textColor: root.textMain
                    bgColor: root.inputBg
                    borderColor: root.inputBorder
                    focusBorderColor: root.inputFocus
                    onAccepted: boardCard.saveSa()
                    onTextChanged: boardCard.saError = ""
                    Keys.onEscapePressed: boardCard.editingSa = false
                }
                SmallButton {
                    Layout.preferredWidth: 84
                    Layout.preferredHeight: 28
                    fontPixelSize: 11
                    text: "Записать"
                    toolTipText: "Записать плате этот адрес (с проверкой чтением). Esc - отмена"
                    tone: "#16a34a"; toneHover: "#15803d"; tonePressed: "#166534"
                    onClicked: boardCard.saveSa()
                }
                SmallButton {
                    Layout.preferredWidth: 30
                    Layout.preferredHeight: 28
                    fontPixelSize: 12
                    text: "✕"
                    toolTipText: "Отмена"
                    onClicked: boardCard.editingSa = false
                }
            }
            Text {
                visible: boardCard.editingSa && boardCard.saError.length > 0
                Layout.fillWidth: true
                text: boardCard.saError
                color: "#dc2626"
                font.pixelSize: 11
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }
        }
    }

    // Пункт окна подтверждения: номер в кружке, заголовок и пояснение.
    component ConfirmStep: RowLayout {
        id: confirmStep
        property string number: ""
        property string title: ""
        property string hint: ""
        Layout.fillWidth: true
        spacing: 12

        Rectangle {
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: 24
            Layout.preferredHeight: 24
            radius: 12
            color: "#eff6ff"
            border.width: 1
            border.color: "#bfdbfe"
            Text {
                anchors.centerIn: parent
                text: confirmStep.number
                color: "#1d4ed8"
                font.pixelSize: 12
                font.bold: true
                font.family: "Bahnschrift"
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Text {
                Layout.fillWidth: true
                text: confirmStep.title
                color: root.textMain
                font.pixelSize: 13
                font.bold: true
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                visible: confirmStep.hint.length > 0
                text: confirmStep.hint
                color: root.textSoft
                font.pixelSize: 12
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
                lineHeight: 1.15
            }
        }
    }

    Popup {
        id: resetConfirm
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(540, (parent ? parent.width : 540) - 40)
        modal: true
        focus: true
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        Overlay.modal: Rectangle { color: "#660f172a" }

        background: Rectangle {
            radius: 16
            color: "#ffffff"
            border.width: 1
            border.color: "#e2e8f0"
        }

        contentItem: ColumnLayout {
            spacing: 0

            // Заголовок: значок предупреждения и суть действия.
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.topMargin: 22
                spacing: 14

                Rectangle {
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 40
                    radius: 20
                    color: "#fef2f2"
                    border.width: 1
                    border.color: "#fecaca"
                    Text {
                        anchors.centerIn: parent
                        text: "↺"
                        color: "#dc2626"
                        font.pixelSize: 20
                        font.bold: true
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        text: "Сбросить адреса плат?"
                        color: root.textMain
                        font.pixelSize: 17
                        font.bold: true
                        font.family: "Bahnschrift"
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "Назначение адресов начнётся заново с П1"
                        color: root.textSoft
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; Layout.topMargin: 18; Layout.preferredHeight: 1; color: "#eef2f7" }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.topMargin: 16
                spacing: 14

                ConfirmStep {
                    number: "1"
                    title: "Платам на шине - заводской адрес " + (root.addr.factorySa || "0x6A")
                    hint: "Программа сначала опросит все платы списка, затем по очереди запишет адрес и проверит, "
                          + "что по старому адресу плата больше не отвечает."
                }
                ConfirmStep {
                    number: "2"
                    title: "Список плат и их история очистятся"
                    hint: "Имена, история адресов и режимы трафика будут забыты."
                }
                ConfirmStep {
                    number: "3"
                    title: "Затем отключите все платы"
                    hint: "Запустите мастер и подключайте платы по одной: адреса назначатся с первого по порядку."
                }

                // Платы, которых нет на шине: их адрес не сбросить, он останется занятым.
                Rectangle {
                    Layout.fillWidth: true
                    visible: (root.addr.absent || []).length > 0
                    Layout.preferredHeight: absentNote.implicitHeight + 20
                    radius: 10
                    color: "#fffbeb"
                    border.width: 1
                    border.color: "#fde68a"
                    Text {
                        id: absentNote
                        anchors.fill: parent
                        anchors.margins: 10
                        text: "Сейчас не на шине: " + (root.addr.absent || []).join(", ") + ". Их адреса сбросить "
                              + "нельзя - они останутся занятыми, пока вы не нажмёте «Освободить»."
                        color: "#92400e"
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                        wrapMode: Text.WordWrap
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.topMargin: 22
                Layout.bottomMargin: 20
                spacing: 10

                Item { Layout.fillWidth: true }
                FancyButton {
                    Layout.preferredWidth: 110
                    Layout.preferredHeight: 34
                    fontPixelSize: 13
                    text: "Отмена"
                    tone: "#94a3b8"; toneHover: "#64748b"; tonePressed: "#475569"
                    onClicked: resetConfirm.close()
                }
                FancyButton {
                    Layout.preferredWidth: 170
                    Layout.preferredHeight: 34
                    fontPixelSize: 13
                    text: "Сбросить адреса"
                    tone: "#dc2626"; toneHover: "#b91c1c"; tonePressed: "#991b1b"
                    onClicked: {
                        resetConfirm.close()
                        if (root.appController)
                            root.appController.resetBoardAddresses()
                    }
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
                         + "Запустите мастер и подключайте <b>новые</b> платы <b>по одной</b>. Для каждой мастер сам: "
                         + "находит её, открывает доступ, записывает адрес, проверяет его чтением, выключает передачу "
                         + "J1939 платы (чтобы она не мешала найти следующую) и проверяет тишину на шине. Каждый шаг "
                         + "ждёт подтверждения платы до 1,5 с, до 3 попыток.<br><br>"
                         + "Уже назначенной плате адрес и имя меняются в её карточке, там же - режим трафика J1939 "
                         + "(UDS 0x28). Адреса вводятся в шестнадцатеричном виде: 85 или 0x85."
                }
                Item { Layout.fillWidth: true }
            }

            // Мастер: как выбирается адрес, запуск и остановка.
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

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        Caption { text: "Адрес новой плате назначается" }
                        Segmented {
                            options: [
                                { "key": "auto", "title": "Автоматически",
                                  "hint": "Мастер сам берёт следующий свободный адрес, начиная с первого" },
                                { "key": "manual", "title": "Вручную",
                                  "hint": "Найдя новую плату, мастер ждёт от вас адрес и имя (подставляет свободный)" }
                            ]
                            current: root.addr.mode || "auto"
                            itemWidth: 130
                            onPicked: (key) => { if (root.appController) root.appController.setBoardAddressingMode(key) }
                        }
                        Item { Layout.fillWidth: true }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Caption {
                            visible: !root.manual
                            text: "Первый адрес (HEX)"
                        }
                        FancyTextField {
                            id: startField
                            visible: !root.manual
                            Layout.preferredWidth: 80
                            Layout.preferredHeight: 30
                            enabled: !root.active
                            textColor: root.textMain
                            bgColor: root.inputBg
                            borderColor: root.inputBorder
                            focusBorderColor: root.inputFocus
                            Component.onCompleted: startField.text = root.addr.startText || "0x81"
                        }
                        Caption {
                            visible: root.manual
                            text: "Для каждой найденной платы мастер спросит адрес и имя."
                        }
                        FancyButton {
                            Layout.preferredWidth: 160
                            Layout.preferredHeight: 30
                            fontPixelSize: 13
                            text: root.active ? "Остановить мастер" : "Запустить мастер"
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
                    }

                    // Плата, с которой идёт работа: старый адрес -> новый.
                    RowLayout {
                        Layout.fillWidth: true
                        visible: (root.addr.candidate || "").length > 0
                        spacing: 12

                        Text {
                            text: root.readdress ? "Смена адреса" : "Плата " + (root.addr.boardNumber || 0)
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

                            Caption { text: "Новый адрес (HEX)" }
                            FancyTextField {
                                id: manualSaField
                                Layout.preferredWidth: 80
                                Layout.preferredHeight: 30
                                placeholderText: "81"
                                textColor: root.textMain
                                bgColor: "#ffffff"
                                borderColor: root.inputBorder
                                focusBorderColor: root.inputFocus
                                onAccepted: root.confirmManual()
                            }
                            Caption { text: "Имя платы" }
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
                            text: root.readdress ? "Отменить смену" : "Пропустить плату"
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
                Caption {
                    text: root.addr.checking ? "проверяю, какие платы на шине..."
                          : "на шине " + (root.addr.cards || []).length + " из " + (root.addr.listed || 0)
                }
                Item { Layout.fillWidth: true }
                SmallButton {
                    Layout.preferredWidth: 150
                    text: "Сбросить адреса..."
                    enabled: !!root.addr.editable
                    toolTipText: "Вернуть подключённым платам заводской адрес и назначить адреса заново по порядку"
                    tone: "#dc2626"; toneHover: "#b91c1c"; tonePressed: "#991b1b"
                    onClicked: resetConfirm.open()
                }
                SmallButton {
                    Layout.preferredWidth: 150
                    text: "Обновить показания"
                    enabled: (root.addr.cards || []).length > 0
                    toolTipText: "Прочитать заново данные всех карточек"
                    onClicked: if (root.appController) root.appController.refreshBoardInfo(-1)
                }
                SmallButton {
                    Layout.preferredWidth: 190
                    text: "Всем: только приём (TX выкл)"
                    enabled: (root.addr.cards || []).length > 0
                    toolTipText: "Одна команда всем платам: 0x28 RX вкл · TX выкл (без подтверждения)"
                    tone: "#0f766e"; toneHover: "#115e59"; tonePressed: "#134e4a"
                    onClicked: if (root.appController) root.appController.setAllBoardsTraffic(1)
                }
                SmallButton {
                    Layout.preferredWidth: 170
                    text: "Всем: RX+TX (обычная)"
                    enabled: (root.addr.cards || []).length > 0
                    toolTipText: "Одна команда всем платам: 0x28 RX вкл · TX вкл (мастер остановится)"
                    tone: "#b45309"; toneHover: "#92400e"; tonePressed: "#78350f"
                    onClicked: if (root.appController) root.appController.releaseBoardsTraffic()
                }
            }

            Caption {
                visible: (root.addr.cards || []).length === 0 && !root.addr.checking
                Layout.fillWidth: true
                text: (root.addr.listed || 0) > 0
                      ? "Ни одна плата из списка сейчас не отвечает. Проверьте питание и подключение к шине CAN."
                      : "Пока ни одной. Запустите мастер и подключите первую плату: после настройки она появится здесь."
                wrapMode: Text.WordWrap
            }
            Caption {
                visible: (root.addr.absent || []).length > 0
                Layout.fillWidth: true
                text: "Нет на шине (не отвечают 6 с): " + (root.addr.absent || []).join(", ")
                color: "#b45309"
                wrapMode: Text.WordWrap
            }
            RowLayout {
                visible: (root.addr.reserved || []).length > 0
                Layout.fillWidth: true
                spacing: 8

                Caption {
                    Layout.fillWidth: true
                    text: "Адреса оставлены занятыми (этих плат не было на шине при сбросе; при подключении мастер "
                          + "назначит им новые): " + (root.addr.reserved || []).join(", ")
                    wrapMode: Text.WordWrap
                }
                SmallButton {
                    Layout.preferredWidth: 110
                    text: "Освободить"
                    toolTipText: "Тех плат больше нет: эти адреса снова можно назначать"
                    onClicked: if (root.appController) root.appController.releaseReservedAddresses()
                }
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
