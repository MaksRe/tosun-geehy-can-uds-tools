import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

/*
  Таблица итогов прогона (chamber_results.py): заголовок с подсказкой «i», шапка столбцов - у каждого
  своя подсказка, что значит число и от чего считается процент; строки окрашены по итогу
  (зелёная - в порядке, жёлтая - вне допуска, красная - нет точки). Широкая таблица прокручивается
  вбок, шапка остаётся над своими столбцами.

  Публичные свойства:
  - table: {title, tip, columns: [{key, title, tip, align}], rows: [{tone, cells: {key: текст}}]}.
*/
ColumnLayout {
    id: resultsTable

    property var table: ({})
    readonly property var columns: resultsTable.table.columns || []
    readonly property var toneBg: ({ "ok": "#f0fdf4", "warn": "#fffbeb", "bad": "#fef2f2", "info": "#ffffff" })
    readonly property var toneText: ({ "ok": "#166534", "warn": "#92400e", "bad": "#991b1b", "info": "#1f2d3d" })

    function columnWidth(column) {
        if (column.width)
            return column.width
        const title = String(column.title || "")
        return Math.max(68, Math.min(190, title.length * 7 + 34))
    }

    readonly property int totalWidth: {
        let sum = 0
        for (let i = 0; i < resultsTable.columns.length; ++i)
            sum += resultsTable.columnWidth(resultsTable.columns[i])
        return sum
    }

    spacing: 4
    Layout.fillWidth: true

    RowLayout {
        spacing: 6
        Text {
            text: resultsTable.table.title || ""
            color: "#0f172a"
            font.pixelSize: 14
            font.bold: true
            font.family: "Bahnschrift"
        }
        InfoMark { tip: resultsTable.table.tip || "" }
    }

    Flickable {
        id: tableFlick
        Layout.fillWidth: true
        Layout.preferredHeight: tableColumn.implicitHeight + (hBar.visible ? 12 : 0)
        contentWidth: resultsTable.totalWidth
        contentHeight: tableColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.HorizontalFlick
        ScrollBar.horizontal: ScrollBar { id: hBar; policy: tableFlick.contentWidth > tableFlick.width ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff }

        Column {
            id: tableColumn
            width: resultsTable.totalWidth

            // Шапка: название столбца и «i» с пояснением.
            Row {
                Repeater {
                    model: resultsTable.columns

                    Rectangle {
                        id: headCell
                        required property var modelData
                        width: resultsTable.columnWidth(headCell.modelData)
                        height: 44
                        color: "#e8eef5"
                        border.width: 1
                        border.color: "#c5d0dc"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 6
                            anchors.rightMargin: 4
                            spacing: 3

                            Text {
                                Layout.fillWidth: true
                                text: headCell.modelData.title || ""
                                color: "#334155"
                                font.pixelSize: 11
                                font.bold: true
                                font.family: "Bahnschrift"
                                wrapMode: Text.WordWrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                                horizontalAlignment: Text.AlignHCenter
                            }

                            InfoMark { tip: headCell.modelData.tip || "" }
                        }
                    }
                }
            }

            Repeater {
                model: resultsTable.table.rows || []

                Row {
                    id: tableRow
                    required property var modelData
                    required property int index

                    Repeater {
                        model: resultsTable.columns

                        Rectangle {
                            id: bodyCell
                            required property var modelData
                            readonly property string value: (tableRow.modelData.cells || {})[bodyCell.modelData.key] || ""
                            width: resultsTable.columnWidth(bodyCell.modelData)
                            height: 26
                            // Цвет строки - по итогу, строки через одну чуть темнее: строка не теряется.
                            color: tableRow.index % 2 === 1 ? Qt.darker(resultsTable.toneBg[tableRow.modelData.tone] || "#ffffff", 1.035)
                                                           : (resultsTable.toneBg[tableRow.modelData.tone] || "#ffffff")
                            border.width: 1
                            border.color: "#d3dce6"

                            Text {
                                id: cellText
                                anchors.fill: parent
                                anchors.leftMargin: 6
                                anchors.rightMargin: 6
                                verticalAlignment: Text.AlignVCenter
                                horizontalAlignment: bodyCell.modelData.align === "left" ? Text.AlignLeft
                                                     : (bodyCell.modelData.align === "center" ? Text.AlignHCenter : Text.AlignRight)
                                text: bodyCell.value
                                color: bodyCell.modelData.key === "status" || bodyCell.modelData.key === "verdict"
                                       || bodyCell.modelData.key.indexOf("stage") === 0
                                       ? (resultsTable.toneText[tableRow.modelData.tone] || "#1f2d3d") : "#1f2d3d"
                                font.pixelSize: 12
                                font.family: "Bahnschrift"
                                elide: Text.ElideRight

                                MouseArea {
                                    id: cellArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    acceptedButtons: Qt.NoButton
                                }

                                ToolTip {
                                    visible: cellArea.containsMouse && cellText.truncated
                                    delay: 300
                                    text: bodyCell.value
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
