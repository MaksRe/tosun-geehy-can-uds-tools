import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import "."

Card {
    id: root

    property var appController
    property color textMain: "#1f2d3d"
    property color textSoft: "#607084"
    readonly property int contentPadding: 8

    property int viewMode: 2
    property int selectedNodeIndex: 0
    property var nodeEnabledMap: ({})
    property bool showPointLabels: false
    property bool includeLoadedCsv: true
    property bool swapAxes: false
    property bool showAdvancedControls: false
    property int rangeStartIndex: 0
    property int rangeEndIndex: -1
    readonly property bool collectorEnabled: root.appController ? root.appController.collectorEnabled : false

    readonly property var nodePalette: ["#2563eb", "#10b981", "#f97316", "#8b5cf6", "#ef4444", "#14b8a6", "#0ea5e9", "#a855f7"]

    Layout.fillWidth: true
    implicitHeight: 620
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
        return "Диапазон: " + root.rangeStartIndex + "..." + endValue + " из " + total
    }

    function csvSummaryText() {
        var files = csvSeries()
        if (files.length === 0)
            return "CSV: 0"
        var total = 0
        for (var i = 0; i < files.length; i++) {
            var count = Number(files[i].count)
            if (!isNaN(count))
                total += count
        }
        return "CSV: " + files.length + ", точек: " + total
    }

    function _toLocalFilePath(pathOrUrl) {
        if (!pathOrUrl)
            return ""

        var raw = ""
        if (typeof pathOrUrl === "string")
            raw = pathOrUrl
        else if (pathOrUrl.toString)
            raw = pathOrUrl.toString()

        raw = String(raw).trim()
        if (raw.length === 0)
            return ""

        if (raw.indexOf("file:///") === 0) {
            var decoded = decodeURIComponent(raw.substring(8))
            if (decoded.length > 2 && decoded.charAt(0) === "/" && decoded.charAt(2) === ":")
                decoded = decoded.substring(1)
            return decoded
        }

        return raw
    }

    function _ensurePngExtension(pathText) {
        var normalized = String(pathText)
        var lowered = normalized.toLowerCase()
        if (lowered.length >= 4 && lowered.substring(lowered.length - 4) === ".png")
            return normalized
        return normalized + ".png"
    }

    function exportCurrentTrendPng(pathOrUrl) {
        var localPath = _toLocalFilePath(pathOrUrl)
        if (!localPath || localPath.length === 0)
            return
        localPath = _ensurePngExtension(localPath)

        if (!summaryTrendCanvas || summaryTrendCanvas.width < 2 || summaryTrendCanvas.height < 2)
            return

        summaryTrendCanvas.grabToImage(function(result) {
            var ok = result.saveToFile(localPath)
            exportStatusDialog.text = ok
                ? ("PNG сохранён: " + localPath)
                : "Не удалось сохранить PNG. Проверьте путь и права доступа."
            exportStatusDialog.open()
        }, Qt.size(1920, 1080))
    }

    function nodesSummaryText() {
        var nodes = trendNodes()
        var visible = 0
        for (var i = 0; i < nodes.length; i++)
            if (isNodeVisible(String(nodes[i].node)))
                visible += 1
        return "Узлов: " + nodes.length + ", видно: " + visible
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
        anchors.bottom: parent.bottom
        anchors.leftMargin: root.contentPadding
        anchors.rightMargin: root.contentPadding
        anchors.topMargin: root.contentPadding
        anchors.bottomMargin: root.contentPadding
        spacing: 4

        Rectangle {
            Layout.fillWidth: true
            radius: 8
            color: "#f8fbff"
            border.color: "#d6e2ef"
            border.width: 1
            implicitHeight: panelColumn.implicitHeight + 8

            ColumnLayout {
                id: panelColumn
                anchors.fill: parent
                anchors.margins: 4
                spacing: 4

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    FancyComboBox {
                        Layout.preferredWidth: 166
                        Layout.preferredHeight: 28
                        model: ["Выбранный узел", "Все узлы", "Все + CSV"]
                        currentIndex: root.viewMode
                        onCurrentIndexChanged: root.viewMode = currentIndex
                    }

                    FancyComboBox {
                        Layout.preferredWidth: 126
                        Layout.preferredHeight: 28
                        enabled: root.viewMode === 0
                        model: root.nodeLabelList()
                        currentIndex: root.selectedNodeIndex
                        onCurrentIndexChanged: root.selectedNodeIndex = currentIndex
                    }

                    FancyButton {
                        Layout.preferredWidth: 62
                        Layout.preferredHeight: 28
                        fontPixelSize: 10
                        text: root.swapAxes ? "Y/X" : "X/Y"
                        toolTipText: "Поменять оси местами: X=температура, Y=топливо или наоборот."
                        tone: "#7c3aed"
                        toneHover: "#6d28d9"
                        tonePressed: "#5b21b6"
                        onClicked: root.swapAxes = !root.swapAxes
                    }

                    FancyButton {
                        Layout.preferredWidth: 82
                        Layout.preferredHeight: 28
                        fontPixelSize: 10
                        text: root.includeLoadedCsv ? "CSV ON" : "CSV OFF"
                        toolTipText: "Показать или скрыть на графике серии, загруженные из внешних CSV файлов."
                        onClicked: root.includeLoadedCsv = !root.includeLoadedCsv
                    }

                    FancyButton {
                        Layout.preferredWidth: 58
                        Layout.preferredHeight: 28
                        fontPixelSize: 10
                        text: "CSV+"
                        toolTipText: "Загрузить один или несколько CSV файлов для сравнения с текущими данными."
                        tone: "#0f766e"
                        toneHover: "#115e59"
                        tonePressed: "#134e4a"
                        onClicked: csvFileDialog.open()
                    }

                    FancyButton {
                        Layout.preferredWidth: 58
                        Layout.preferredHeight: 28
                        fontPixelSize: 10
                        text: "CSV-"
                        toolTipText: "Удалить все загруженные CSV-серии из графика (онлайн-данные не затрагиваются)."
                        enabled: root.csvSeries().length > 0
                        tone: "#64748b"
                        toneHover: "#55657a"
                        tonePressed: "#475569"
                        onClicked: if (root.appController) root.appController.clearCollectorTrendCsv()
                    }

                    FancyButton {
                        Layout.preferredWidth: 66
                        Layout.preferredHeight: 28
                        fontPixelSize: 10
                        text: "Период"
                        toolTipText: "Сбросить фильтрацию диапазона и показать весь доступный период точек."
                        onClicked: root.resetRange()
                    }

                    FancyButton {
                        Layout.preferredWidth: 56
                        Layout.preferredHeight: 28
                        fontPixelSize: 10
                        text: "PNG"
                        toolTipText: "Сохранить текущий вид графика в PNG с учетом всех выбранных настроек."
                        tone: "#0f766e"
                        toneHover: "#115e59"
                        tonePressed: "#134e4a"
                        onClicked: pngSaveDialog.open()
                    }

                    FancyButton {
                        Layout.preferredWidth: 92
                        Layout.preferredHeight: 28
                        fontPixelSize: 10
                        text: root.showAdvancedControls ? "Свернуть" : "Расширить"
                        toolTipText: "Показать или скрыть дополнительные инструменты анализа и фильтрации узлов."
                        tone: "#1d4ed8"
                        toneHover: "#1e40af"
                        tonePressed: "#1e3a8a"
                        onClicked: root.showAdvancedControls = !root.showAdvancedControls
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        text: root.nodesSummaryText()
                        color: root.textSoft
                        font.pixelSize: 10
                        font.family: "Bahnschrift"
                        Layout.alignment: Qt.AlignVCenter
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    visible: root.showAdvancedControls
                    Layout.minimumHeight: root.showAdvancedControls ? implicitHeight : 0
                    Layout.maximumHeight: root.showAdvancedControls ? implicitHeight : 0

                    FancyButton {
                        Layout.preferredWidth: 82
                        Layout.preferredHeight: 26
                        fontPixelSize: 10
                        text: root.showPointLabels ? "Метки ON" : "Метки OFF"
                        toolTipText: "Включить/выключить подписи значений возле точек графика."
                        onClicked: root.showPointLabels = !root.showPointLabels
                    }

                    FancyButton {
                        Layout.preferredWidth: 54
                        Layout.preferredHeight: 26
                        fontPixelSize: 10
                        text: "Все"
                        toolTipText: "Сделать видимыми на графике все узлы."
                        onClicked: root.setAllNodesVisible(true)
                    }

                    FancyButton {
                        Layout.preferredWidth: 64
                        Layout.preferredHeight: 26
                        fontPixelSize: 10
                        text: "Скрыть"
                        toolTipText: "Скрыть на графике все узлы. Далее можно включить нужные узлы вручную."
                        onClicked: root.setAllNodesVisible(false)
                    }

                    Text {
                        Layout.fillWidth: true
                        text: root.rangeInfoText() + " | " + root.csvSummaryText() + " | ЛКМ: zoom, ПКМ: pan"
                        color: root.textSoft
                        font.pixelSize: 10
                        font.family: "Bahnschrift"
                        elide: Text.ElideRight
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 32
                    radius: 6
                    color: "#ffffff"
                    border.color: "#d6e2ef"
                    border.width: 1
                    visible: root.showAdvancedControls

                    Flickable {
                        anchors.fill: parent
                        anchors.margins: 2
                        clip: true
                        interactive: true
                        contentWidth: nodesRow.implicitWidth
                        contentHeight: nodesRow.implicitHeight

                        Row {
                            id: nodesRow
                            spacing: 4

                            Repeater {
                                model: root.trendNodes()
                                delegate: FancyButton {
                                    readonly property string nodeLabel: String(modelData.node)
                                    width: 82
                                    height: 24
                                    fontPixelSize: 10
                                    text: nodeLabel
                                    toolTipText: "Показать или скрыть серию узла " + nodeLabel + " на графике."
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
        }

        TrendCanvas {
            id: summaryTrendCanvas
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 220
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
            maxRenderPoints: root.showAdvancedControls ? 0 : 500
            maxPointLabels: root.showAdvancedControls ? 80 : 0
            swapAxes: root.swapAxes
        }
    }

    FileDialog {
        id: pngSaveDialog
        title: "Сохранить итоговый график PNG"
        fileMode: FileDialog.SaveFile
        nameFilters: ["PNG файлы (*.png)", "Все файлы (*)"]
        defaultSuffix: "png"
        onAccepted: {
            var output = selectedFile
            if ((!output || String(output).length === 0) && selectedFiles && selectedFiles.length > 0)
                output = selectedFiles[0]
            root.exportCurrentTrendPng(output)
        }
    }

    MessageDialog {
        id: exportStatusDialog
        title: "Экспорт графика"
        text: ""
        buttons: MessageDialog.Ok
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
