import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import QtQuick.Window 2.15
import "."

Card {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    readonly property int contentPadding: 12

    property int viewMode: 2
    property int selectedNodeIndex: 0
    property var nodeEnabledMap: ({})
    property bool showPointLabels: false
    property bool includeLoadedCsv: true
    property bool swapAxes: false
    property bool compactExpandedUi: true
    property int rangeStartIndex: 0
    property int rangeEndIndex: -1
    readonly property bool collectorEnabled: root.appController ? root.appController.collectorEnabled : false

    readonly property var nodePalette: ["#2563eb", "#10b981", "#f97316", "#8b5cf6", "#ef4444", "#14b8a6", "#0ea5e9", "#a855f7"]

    Layout.fillWidth: true
    implicitHeight: contentColumn.implicitHeight + (contentPadding * 2)
    enabled: collectorEnabled
    opacity: collectorEnabled ? 1.0 : 0.5

    Behavior on opacity {
        NumberAnimation {
            duration: 140
            easing.type: Easing.OutCubic
        }
    }

    function trendNodes() { return root.appController ? root.appController.collectorTrendNodes : [] }
    function csvSeries() { return root.appController ? root.appController.collectorTrendCsvSeries : [] }
    function nodeLabelList() { return root.appController ? root.appController.collectorTrendNodeLabels : [] }

    function colorForNode(index) {
        if (index < 0)
            return "#2563eb"
        return root.nodePalette[index % root.nodePalette.length]
    }

    function syncNodeEnabled() {
        var nodes = trendNodes()
        var nextMap = {}
        for (var i = 0; i < nodes.length; i++) {
            var label = String(nodes[i].node)
            nextMap[label] = root.nodeEnabledMap.hasOwnProperty(label) ? root.nodeEnabledMap[label] : true
        }
        root.nodeEnabledMap = nextMap

        if (nodes.length === 0)
            root.selectedNodeIndex = -1
        else if (root.selectedNodeIndex < 0 || root.selectedNodeIndex >= nodes.length)
            root.selectedNodeIndex = 0
    }

    function selectedNodeEntry() {
        var nodes = trendNodes()
        if (nodes.length === 0)
            return null
        var idx = root.selectedNodeIndex
        if (idx < 0 || idx >= nodes.length)
            idx = 0
        return nodes[idx]
    }

    function isNodeVisible(label) {
        return !root.nodeEnabledMap.hasOwnProperty(label) || root.nodeEnabledMap[label] !== false
    }

    function toggleNodeVisible(label) {
        var nextMap = {}
        for (var key in root.nodeEnabledMap)
            if (root.nodeEnabledMap.hasOwnProperty(key))
                nextMap[key] = root.nodeEnabledMap[key]
        nextMap[label] = !isNodeVisible(label)
        root.nodeEnabledMap = nextMap
    }

    function setAllNodesVisible(flag) {
        var nodes = trendNodes()
        var nextMap = {}
        for (var i = 0; i < nodes.length; i++)
            nextMap[String(nodes[i].node)] = !!flag
        root.nodeEnabledMap = nextMap
    }

    function hasNodeVisibilityFilter() {
        var nodes = trendNodes()
        for (var i = 0; i < nodes.length; i++) {
            if (!isNodeVisible(String(nodes[i].node)))
                return true
        }
        return false
    }

    function liveOverlaySeries() {
        var nodes = trendNodes()
        var result = []
        for (var i = 0; i < nodes.length; i++) {
            var item = nodes[i]
            var label = String(item.node)
            if (!isNodeVisible(label))
                continue
            result.push({
                "node": label,
                "points": item.points ? item.points : [],
                "color": colorForNode(i)
            })
        }
        return result
    }

    function csvOverlaySeries(colorOffset) {
        var files = csvSeries()
        var result = []
        var start = Math.max(0, Number(colorOffset))
        for (var i = 0; i < files.length; i++) {
            var item = files[i]
            if (!item || !item.points || item.points.length <= 0)
                continue
            result.push({
                "node": String(item.node ? item.node : ("CSV " + (i + 1))),
                "points": item.points,
                "color": colorForNode(start + i)
            })
        }
        return result
    }

    function overlaySeries() {
        var result = liveOverlaySeries()
        if (root.includeLoadedCsv) {
            var csvItems = csvOverlaySeries(result.length)
            for (var i = 0; i < csvItems.length; i++)
                result.push(csvItems[i])
        }
        return result
    }

    function popupUseOverlayMode() {
        if (root.viewMode !== 0)
            return true
        if (root.hasNodeVisibilityFilter())
            return true
        if (root.includeLoadedCsv && root.csvSeries().length > 0)
            return true
        return false
    }

    function popupSeries() {
        var result = []

        if (root.viewMode === 0 && !root.hasNodeVisibilityFilter()) {
            var selected = root.selectedNodeEntry()
            if (selected && selected.points && selected.points.length > 0) {
                result.push({
                    "node": String(selected.node),
                    "points": selected.points,
                    "color": colorForNode(root.selectedNodeIndex)
                })
            }
        } else {
            result = liveOverlaySeries()
        }

        if (root.includeLoadedCsv) {
            var csvItems = csvOverlaySeries(result.length)
            for (var i = 0; i < csvItems.length; i++)
                result.push(csvItems[i])
        }

        return result
    }

    function maxPointCountForCurrentMode() {
        if (!popupUseOverlayMode()) {
            var selected = selectedNodeEntry()
            return selected ? Number(selected.count) : 0
        }

        var maxCount = 0
        var allSeries = popupSeries()
        for (var i = 0; i < allSeries.length; i++) {
            var item = allSeries[i]
            if (!item || !item.points)
                continue
            var count = Number(item.points.length)
            if (count > maxCount)
                maxCount = count
        }
        return maxCount
    }

    function resetRange() {
        root.rangeStartIndex = 0
        root.rangeEndIndex = -1
    }

    function clampRangeToData() {
        var total = maxPointCountForCurrentMode()
        if (total <= 0) {
            root.rangeStartIndex = 0
            root.rangeEndIndex = -1
            return
        }

        root.rangeStartIndex = Math.max(0, Math.min(total - 1, root.rangeStartIndex))
        if (root.rangeEndIndex >= 0) {
            root.rangeEndIndex = Math.max(0, Math.min(total - 1, root.rangeEndIndex))
            if (root.rangeEndIndex < root.rangeStartIndex) {
                var tmp = root.rangeStartIndex
                root.rangeStartIndex = root.rangeEndIndex
                root.rangeEndIndex = tmp
            }
        }
    }

    function rangeInfoText() {
        var total = maxPointCountForCurrentMode()
        if (total <= 0)
            return "Точки: нет данных"
        var endValue = root.rangeEndIndex >= 0 ? root.rangeEndIndex : (total - 1)
        return "Диапазон индексов: " + root.rangeStartIndex + " ... " + endValue + " из " + total
    }

    function csvSummaryText() {
        var files = csvSeries()
        if (files.length === 0)
            return "CSV не загружены"
        var total = 0
        for (var i = 0; i < files.length; i++) {
            var count = Number(files[i].count)
            if (!isNaN(count))
                total += count
        }
        return "CSV файлов: " + files.length + ", точек: " + total
    }

    function axisModeText() {
        return root.swapAxes
            ? "Оси: X - уровень топлива, Y - температура"
            : "Оси: X - температура, Y - уровень топлива"
    }

    function nodesSummaryText() {
        var nodes = trendNodes()
        var visible = 0
        for (var i = 0; i < nodes.length; i++)
            if (isNodeVisible(String(nodes[i].node)))
                visible += 1
        return "Узлов: " + nodes.length + ", отображается: " + visible
    }

    Component.onCompleted: {
        syncNodeEnabled()
        clampRangeToData()
    }

    onViewModeChanged: clampRangeToData()
    onSelectedNodeIndexChanged: clampRangeToData()
    onNodeEnabledMapChanged: clampRangeToData()
    onIncludeLoadedCsvChanged: clampRangeToData()

    ColumnLayout {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: root.contentPadding
        anchors.rightMargin: root.contentPadding
        anchors.topMargin: root.contentPadding
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                text: "Графики параметров узлов CAN"
                color: root.textMain
                font.pixelSize: 16
                font.bold: true
                font.family: "Bahnschrift"
            }

            Item { Layout.fillWidth: true }

            Text {
                text: root.nodesSummaryText()
                color: root.textSoft
                font.pixelSize: 11
                font.family: "Bahnschrift"
            }
        }

        Text {
            Layout.fillWidth: true
            text: root.axisModeText()
            color: root.textSoft
            font.pixelSize: 11
            font.family: "Bahnschrift"
            wrapMode: Text.Wrap
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 10
            color: "#f8fbff"
            border.color: "#d6e2ef"
            border.width: 1
            implicitHeight: controlsLayout.implicitHeight + 12

            ColumnLayout {
                id: controlsLayout
                anchors.fill: parent
                anchors.margins: 8
                spacing: 6

                Text {
                    Layout.fillWidth: true
                    text: root.rangeInfoText() + " | " + root.csvSummaryText()
                    color: root.textSoft
                    font.pixelSize: 11
                    font.family: "Bahnschrift"
                    wrapMode: Text.Wrap
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    FancyButton {
                        Layout.preferredWidth: 130
                        Layout.preferredHeight: 32
                        text: "Загрузить CSV"
                        tone: "#0f766e"
                        toneHover: "#115e59"
                        tonePressed: "#134e4a"
                        onClicked: csvFileDialog.open()
                    }

                    FancyButton {
                        Layout.preferredWidth: 120
                        Layout.preferredHeight: 32
                        text: "Очистить CSV"
                        enabled: root.csvSeries().length > 0
                        tone: "#64748b"
                        toneHover: "#55657a"
                        tonePressed: "#475569"
                        onClicked: if (root.appController) root.appController.clearCollectorTrendCsv()
                    }

                    FancyButton {
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: 32
                        text: root.includeLoadedCsv ? "CSV на графике: ВКЛ" : "CSV на графике: ВЫКЛ"
                        onClicked: root.includeLoadedCsv = !root.includeLoadedCsv
                    }

                    FancyButton {
                        Layout.preferredWidth: 170
                        Layout.preferredHeight: 32
                        text: root.swapAxes ? "Поменять оси: ВКЛ" : "Поменять оси: ВЫКЛ"
                        tone: "#7c3aed"
                        toneHover: "#6d28d9"
                        tonePressed: "#5b21b6"
                        onClicked: root.swapAxes = !root.swapAxes
                    }

                    FancyButton {
                        Layout.preferredWidth: 170
                        Layout.preferredHeight: 32
                        text: "Расширенный режим"
                        tone: "#1d4ed8"
                        toneHover: "#1e40af"
                        tonePressed: "#1e3a8a"
                        onClicked: {
                            trendWindow.visible = true
                            trendWindow.raise()
                            trendWindow.requestActivate()
                        }
                    }

                    Item { Layout.fillWidth: true }
                }
            }
        }

        TrendCanvas {
            Layout.fillWidth: true
            Layout.preferredHeight: 280
            points: {
                var selected = root.selectedNodeEntry()
                if (!root.popupUseOverlayMode() && selected && selected.points)
                    return selected.points
                return []
            }
            overlayMode: root.popupUseOverlayMode()
            series: root.popupSeries()
            emptyText: root.viewMode === 0 ? "Нет данных для выбранного узла" : "Нет выбранных узлов для графика"
            rangeStart: root.rangeStartIndex
            rangeEnd: root.rangeEndIndex
            showPointLabels: false
            maxRenderPoints: 500
            maxPointLabels: 0
            swapAxes: root.swapAxes
        }
    }

    Window {
        id: trendWindow
        width: 1120
        height: 720
        minimumWidth: 900
        minimumHeight: 520
        modality: Qt.NonModal
        visible: false
        title: "Графики узлов CAN (расширенный режим)"
        transientParent: root.Window.window

        Rectangle {
            anchors.fill: parent
            color: "#eef5fc"
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: root.compactExpandedUi ? 8 : 12
            spacing: root.compactExpandedUi ? 6 : 10

            RowLayout {
                Layout.fillWidth: true

                Text {
                    text: "Расширенный просмотр"
                    color: root.textMain
                    font.pixelSize: 15
                    font.bold: true
                    font.family: "Bahnschrift"
                }

                Item { Layout.fillWidth: true }

                FancyButton {
                    Layout.preferredWidth: 110
                    Layout.preferredHeight: 32
                    text: "Закрыть"
                    onClicked: trendWindow.visible = false
                }
            }

            Rectangle {
                Layout.fillWidth: true
                radius: 8
                color: "#ffffff"
                border.color: "#d6e2ef"
                border.width: 1
                implicitHeight: expandedControlsLayout.implicitHeight + 12

                ColumnLayout {
                    id: expandedControlsLayout
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Text {
                            text: "Режим:"
                            color: root.textSoft
                            font.pixelSize: 11
                            font.bold: true
                            font.family: "Bahnschrift"
                            verticalAlignment: Text.AlignVCenter
                        }

                        FancyComboBox {
                            Layout.preferredWidth: 220
                            Layout.preferredHeight: 32
                            model: ["Выбранный узел", "Все узлы (реальное время)", "Все узлы + CSV"]
                            currentIndex: root.viewMode
                            onCurrentIndexChanged: root.viewMode = currentIndex
                        }

                        FancyComboBox {
                            Layout.preferredWidth: 220
                            Layout.preferredHeight: 32
                            enabled: root.viewMode === 0
                            model: root.nodeLabelList()
                            currentIndex: root.selectedNodeIndex
                            onCurrentIndexChanged: root.selectedNodeIndex = currentIndex
                        }

                        FancyButton {
                            Layout.preferredWidth: 170
                            Layout.preferredHeight: 32
                            text: root.swapAxes ? "Поменять оси: ВКЛ" : "Поменять оси: ВЫКЛ"
                            tone: "#7c3aed"
                            toneHover: "#6d28d9"
                            tonePressed: "#5b21b6"
                            onClicked: root.swapAxes = !root.swapAxes
                        }

                        FancyButton {
                            Layout.preferredWidth: 170
                            Layout.preferredHeight: 32
                            text: root.showPointLabels ? "Подписи точек: ВКЛ" : "Подписи точек: ВЫКЛ"
                            onClicked: root.showPointLabels = !root.showPointLabels
                        }

                        Item { Layout.fillWidth: true }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        FancyButton {
                            Layout.preferredWidth: 130
                            Layout.preferredHeight: 32
                            text: "Загрузить CSV"
                            tone: "#0f766e"
                            toneHover: "#115e59"
                            tonePressed: "#134e4a"
                            onClicked: csvFileDialog.open()
                        }

                        FancyButton {
                            Layout.preferredWidth: 120
                            Layout.preferredHeight: 32
                            text: "Очистить CSV"
                            enabled: root.csvSeries().length > 0
                            tone: "#64748b"
                            toneHover: "#55657a"
                            tonePressed: "#475569"
                            onClicked: if (root.appController) root.appController.clearCollectorTrendCsv()
                        }

                        FancyButton {
                            Layout.preferredWidth: 150
                            Layout.preferredHeight: 32
                            text: root.includeLoadedCsv ? "CSV на графике: ВКЛ" : "CSV на графике: ВЫКЛ"
                            onClicked: root.includeLoadedCsv = !root.includeLoadedCsv
                        }

                        FancyButton {
                            Layout.preferredWidth: 120
                            Layout.preferredHeight: 32
                            text: "Весь период"
                            onClicked: root.resetRange()
                        }

                        Item { Layout.fillWidth: true }

                        FancyButton {
                            Layout.preferredWidth: 80
                            Layout.preferredHeight: 32
                            text: "Все"
                            onClicked: root.setAllNodesVisible(true)
                        }

                        FancyButton {
                            Layout.preferredWidth: 80
                            Layout.preferredHeight: 32
                            text: "Скрыть"
                            onClicked: root.setAllNodesVisible(false)
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.rangeInfoText() + " | " + root.csvSummaryText()
                        color: root.textSoft
                        font.pixelSize: 11
                        font.family: "Bahnschrift"
                        wrapMode: Text.Wrap
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                radius: 8
                color: "#ffffff"
                border.color: "#d6e2ef"
                border.width: 1
                implicitHeight: 52

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 8

                    Text {
                        Layout.preferredWidth: 130
                        text: "Видимость узлов"
                        color: root.textSoft
                        font.pixelSize: 11
                        font.bold: true
                        font.family: "Bahnschrift"
                        verticalAlignment: Text.AlignVCenter
                    }

                    Flickable {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        clip: true
                        interactive: true
                        contentWidth: popupNodesRow.implicitWidth
                        contentHeight: 34

                        Row {
                            id: popupNodesRow
                            y: 0
                            spacing: 6

                            Repeater {
                                model: root.trendNodes()
                                delegate: FancyButton {
                                    readonly property string nodeLabel: String(modelData.node)
                                    width: 96
                                    height: 32
                                    text: nodeLabel
                                    fontPixelSize: 12
                                    tone: root.isNodeVisible(nodeLabel) ? "#1d4ed8" : "#94a3b8"
                                    toneHover: root.isNodeVisible(nodeLabel) ? "#1e40af" : "#7f8fa6"
                                    tonePressed: root.isNodeVisible(nodeLabel) ? "#1e3a8a" : "#6b7d95"
                                    onClicked: root.toggleNodeVisible(nodeLabel)
                                }
                            }
                        }
                    }
                }
            }

            TrendCanvas {
                Layout.fillWidth: true
                Layout.fillHeight: true
                points: {
                    var selected = root.selectedNodeEntry()
                    if (!root.popupUseOverlayMode() && selected && selected.points)
                        return selected.points
                    return []
                }
                overlayMode: root.popupUseOverlayMode()
                series: root.popupSeries()
                emptyText: root.viewMode === 0 ? "Нет данных для выбранного узла" : "Нет выбранных узлов для графика"
                rangeStart: root.rangeStartIndex
                rangeEnd: root.rangeEndIndex
                showPointLabels: root.showPointLabels
                maxRenderPoints: 0
                swapAxes: root.swapAxes
            }
        }
    }

    FileDialog {
        id: csvFileDialog
        title: "Выберите CSV файлы для анализа"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["CSV файлы (*.csv)", "Все файлы (*)"]
        onAccepted: {
            if (!root.appController)
                return

            var files = selectedFiles
            if (!files || files.length === 0) {
                if (selectedFile)
                    files = [selectedFile]
                else
                    files = []
            }
            root.appController.loadCollectorTrendCsv(files)
        }
    }

    Connections {
        target: root.appController
        function onCollectorTrendChanged() {
            root.syncNodeEnabled()
            root.clampRangeToData()
        }
    }
}
