import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

/*
  Сообщение программы одной строкой: цветной значок по важности и короткий заголовок.
  Назначение: длинные строки состояния, проверок и замечаний не копятся в окне, а раскрываются
  по нажатию - карточкой «что произошло / почему это важно / что сделать / полный текст».

  Цвет значка (notices.py):
  - красный «!» - нужна рука человека, иначе работа не пойдёт;
  - жёлтый «!» - работа идёт, но результат неполный или под вопросом;
  - синий «i» - сведения;
  - зелёный «✓» - получилось.

  Публичные свойства:
  - appController: контроллер (разбор сообщения - в нём, notices.py);
  - text, tone: текст сообщения и его цвет или уровень («#d97706», «warn», «bad»);
  - kind: о чём сообщение («Камера», «Прогон», «Журнал») - подпись в карточке;
  - title: свой заголовок вместо первой фразы;
  - items: список сообщений вместо одного text - одна строка со счётом, в карточке каждое отдельно;
  - remarks: items - замечания расчёта таблиц (для них пояснения написаны заранее);
  - compact: только значок, без заголовка (рядом с полем или числом).
*/
Item {
    id: noticeLine

    property var appController: null
    property string text: ""
    property string tone: ""
    property string kind: ""
    property string title: ""
    property var items: null
    property bool remarks: false
    property bool compact: false
    property int fontSize: 12

    readonly property var notice: {
        const controller = noticeLine.appController
        if (noticeLine.items !== null && noticeLine.items !== undefined) {
            if (!controller || noticeLine.items.length === 0)
                return ({})
            return controller.noticeForList(noticeLine.items, noticeLine.tone, noticeLine.kind,
                                            noticeLine.title, noticeLine.remarks)
        }
        if (!controller || noticeLine.text.length === 0)
            return ({})
        return controller.noticeFor(noticeLine.text, noticeLine.tone, noticeLine.kind, noticeLine.title)
    }
    readonly property bool hasNotice: (noticeLine.notice.title || "").length > 0

    function open() {
        if (noticeLine.hasNotice)
            noticePopup.open()
    }

    function close() {
        noticePopup.close()
    }

    visible: noticeLine.hasNotice
    implicitHeight: 24
    implicitWidth: noticeLine.compact ? 20 : lineRow.implicitWidth + 8
    Layout.fillWidth: !noticeLine.compact
    Layout.preferredHeight: noticeLine.visible ? 24 : 0

    // Значок уровня: используется и в строке, и в карточке.
    component LevelBadge: Rectangle {
        property var source: ({})
        property int size: 18
        implicitWidth: size
        implicitHeight: size
        Layout.preferredWidth: size
        Layout.preferredHeight: size
        Layout.alignment: Qt.AlignTop
        radius: size / 2
        color: source.color || "#2563eb"

        Text {
            anchors.centerIn: parent
            text: parent.source.glyph || "i"
            color: "#ffffff"
            font.pixelSize: Math.round(parent.size * 0.62)
            font.bold: true
            font.family: "Bahnschrift"
        }
    }

    // Раздел карточки: заголовок и строки; пустой раздел не виден.
    component Section: ColumnLayout {
        id: section
        property string heading: ""
        property var lines: []
        property bool numbered: false
        property color tone: "#334155"
        visible: (lines || []).length > 0
        spacing: 2
        Layout.fillWidth: true

        Text {
            text: section.heading
            color: "#64748b"
            font.pixelSize: 11
            font.bold: true
            font.family: "Bahnschrift"
            font.capitalization: Font.AllUppercase
        }

        Repeater {
            model: section.lines || []

            Text {
                required property var modelData
                required property int index
                Layout.fillWidth: true
                text: (section.numbered ? (index + 1) + ". " : "• ") + modelData
                color: section.tone
                font.pixelSize: 13
                font.family: "Bahnschrift"
                wrapMode: Text.WordWrap
                lineHeight: 1.1
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: 6
        color: lineArea.containsMouse ? (noticeLine.notice.soft || "#f1f5f9") : "transparent"
        border.width: lineArea.containsMouse ? 1 : 0
        border.color: noticeLine.notice.border || "#cbd5e1"
    }

    RowLayout {
        id: lineRow
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: noticeLine.compact ? 1 : 3
        anchors.rightMargin: 4
        spacing: 7

        LevelBadge {
            source: noticeLine.notice
            Layout.alignment: Qt.AlignVCenter
        }

        Text {
            visible: !noticeLine.compact
            Layout.fillWidth: true
            text: noticeLine.notice.title || ""
            color: noticeLine.notice.textColor || "#334155"
            font.pixelSize: noticeLine.fontSize
            font.family: "Bahnschrift"
            elide: Text.ElideRight
        }

        Text {
            visible: !noticeLine.compact
            text: "подробнее ›"
            color: lineArea.containsMouse ? (noticeLine.notice.color || "#2563eb") : "#94a3b8"
            font.pixelSize: 11
            font.family: "Bahnschrift"
        }
    }

    MouseArea {
        id: lineArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: noticeLine.open()
    }

    ToolTip {
        visible: noticeLine.compact && lineArea.containsMouse
        delay: 200
        text: noticeLine.notice.title || ""
    }

    Popup {
        id: noticePopup
        parent: Overlay.overlay
        modal: true
        dim: true
        focus: true
        padding: 0
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        width: Math.min(640, (parent ? parent.width : 700) - 40)
        height: Math.min(cardColumn.implicitHeight + 36, (parent ? parent.height : 700) - 60)
        x: parent ? Math.round((parent.width - width) / 2) : 0
        y: parent ? Math.round(Math.max(30, (parent.height - height) / 2)) : 0

        background: Rectangle {
            radius: 14
            color: "#ffffff"
            border.width: 1
            border.color: noticeLine.notice.border || "#cbd5e1"
        }

        contentItem: Flickable {
            id: cardFlick
            clip: true
            contentWidth: width
            contentHeight: cardColumn.implicitHeight + 36
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            ColumnLayout {
                id: cardColumn
                x: 18
                y: 18
                width: cardFlick.width - 36
                spacing: 12

                // Шапка: уровень и тема, справа - закрыть.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    LevelBadge {
                        source: noticeLine.notice
                        size: 22
                        Layout.alignment: Qt.AlignVCenter
                    }

                    Text {
                        Layout.fillWidth: true
                        text: (noticeLine.notice.levelTitle || "")
                              + ((noticeLine.notice.kind || "").length > 0 ? "  ·  " + noticeLine.notice.kind : "")
                        color: noticeLine.notice.color || "#2563eb"
                        font.pixelSize: 12
                        font.bold: true
                        font.family: "Bahnschrift"
                        font.capitalization: Font.AllUppercase
                    }

                    Rectangle {
                        Layout.preferredWidth: 26
                        Layout.preferredHeight: 26
                        radius: 13
                        color: closeArea.containsMouse ? "#f1f5f9" : "transparent"

                        Text {
                            anchors.centerIn: parent
                            text: "✕"
                            color: "#64748b"
                            font.pixelSize: 14
                        }

                        MouseArea {
                            id: closeArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: noticePopup.close()
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: noticeLine.notice.title || ""
                    color: "#0f172a"
                    font.pixelSize: 16
                    font.bold: true
                    font.family: "Bahnschrift"
                    wrapMode: Text.WordWrap
                }

                Section { heading: "Что произошло"; lines: noticeLine.notice.what || [] }
                Section { heading: "Почему это важно"; lines: noticeLine.notice.why || [] }
                Section {
                    heading: "Что сделать"
                    lines: noticeLine.notice.todo || []
                    numbered: true
                    tone: "#0f172a"
                }

                // Несколько сообщений: каждое своей карточкой, тяжёлые - сверху.
                Repeater {
                    model: noticeLine.notice.items || []

                    Rectangle {
                        id: itemCard
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: itemColumn.implicitHeight + 20
                        radius: 10
                        color: itemCard.modelData.soft || "#f8fafc"
                        border.width: 1
                        border.color: itemCard.modelData.border || "#e2e8f0"

                        ColumnLayout {
                            id: itemColumn
                            x: 10
                            y: 10
                            width: itemCard.width - 20
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                LevelBadge { source: itemCard.modelData }

                                Text {
                                    Layout.fillWidth: true
                                    text: (itemCard.modelData.title || "")
                                          + ((itemCard.modelData.count || 1) > 1
                                             ? "   ×" + itemCard.modelData.count : "")
                                    color: itemCard.modelData.textColor || "#0f172a"
                                    font.pixelSize: 14
                                    font.bold: true
                                    font.family: "Bahnschrift"
                                    wrapMode: Text.WordWrap
                                }
                            }

                            Section { heading: "Что произошло"; lines: itemCard.modelData.what || [] }
                            Section { heading: "Почему это важно"; lines: itemCard.modelData.why || [] }
                            Section {
                                heading: "Что сделать"
                                lines: itemCard.modelData.todo || []
                                numbered: true
                                tone: "#0f172a"
                            }
                        }
                    }
                }

                // Полный текст как есть: его можно выделить и скопировать.
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: (noticeLine.notice.detail || "").length > 0
                    spacing: 2

                    Text {
                        text: "Полный текст"
                        color: "#94a3b8"
                        font.pixelSize: 11
                        font.bold: true
                        font.family: "Bahnschrift"
                        font.capitalization: Font.AllUppercase
                    }

                    TextEdit {
                        Layout.fillWidth: true
                        text: noticeLine.notice.detail || ""
                        readOnly: true
                        selectByMouse: true
                        wrapMode: TextEdit.WordWrap
                        color: "#64748b"
                        font.pixelSize: 12
                        font.family: "Bahnschrift"
                    }
                }
            }
        }
    }
}
