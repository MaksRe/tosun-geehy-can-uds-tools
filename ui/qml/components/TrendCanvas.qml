import QtQuick 2.15
import QtQuick.Controls 2.15

Rectangle {
    id: root

    property bool overlayMode: false
    property var points: []
    property var series: []
    property string emptyText: "Нет данных для построения графика"
    property color panelBg: "#f7fbff"
    property color panelBorder: "#d6e2ef"
    property color fuelColor: "#10b981"
    property color temperatureColor: "#f97316"
    property int rangeStart: 0
    property int rangeEnd: -1
    property bool showPointLabels: false
    property int maxRenderPoints: 1200
    property int maxPointLabels: 60
    property bool swapAxes: false

    // Compatibility properties (kept for existing bindings).
    property real zoomX: 1.0
    property bool wheelZoomEnabled: false
    property int panOffset: 0

    radius: 12
    color: root.panelBg
    border.color: root.panelBorder
    border.width: 1
    implicitHeight: 300

    function normalizeRange(totalCount) {
        if (totalCount <= 0)
            return { "start": 0, "end": -1 }

        var start = Number(root.rangeStart)
        if (isNaN(start))
            start = 0
        start = Math.max(0, Math.min(totalCount - 1, Math.floor(start)))

        var end = Number(root.rangeEnd)
        if (root.rangeEnd < 0 || isNaN(end))
            end = totalCount - 1
        end = Math.max(0, Math.min(totalCount - 1, Math.floor(end)))

        if (end < start) {
            var tmp = start
            start = end
            end = tmp
        }
        return { "start": start, "end": end }
    }

    function decimatePoints(sourcePoints, maxCount) {
        if (!sourcePoints || sourcePoints.length <= 0)
            return []

        var total = sourcePoints.length
        var target = Math.floor(Number(maxCount))
        if (isNaN(target) || target <= 0)
            return sourcePoints
        target = Math.max(2, target)
        if (total <= target)
            return sourcePoints

        var step = (total - 1) / (target - 1)
        var result = []
        var prevIdx = -1
        for (var i = 0; i < target; i++) {
            var idx = Math.round(i * step)
            idx = Math.max(0, Math.min(total - 1, idx))
            if (idx === prevIdx)
                continue
            result.push(sourcePoints[idx])
            prevIdx = idx
        }
        return result
    }

    function selectRange(sourcePoints) {
        if (!sourcePoints || sourcePoints.length <= 0)
            return []

        var normalized = normalizeRange(sourcePoints.length)
        if (normalized.end < normalized.start)
            return []

        var selected = []
        for (var i = normalized.start; i <= normalized.end; i++) {
            var p = sourcePoints[i]
            selected.push({
                "_idx": i,
                "fuel": Number(p.fuel),
                "temperature": Number(p.temperature),
                "time": p.time
            })
        }
        return decimatePoints(selected, root.maxRenderPoints)
    }

    function xValue(point) {
        return root.swapAxes ? Number(point.fuel) : Number(point.temperature)
    }

    function yValue(point) {
        return root.swapAxes ? Number(point.temperature) : Number(point.fuel)
    }

    function buildSeriesForRender() {
        var renderSeries = []
        if (root.overlayMode) {
            if (!root.series)
                return renderSeries
            for (var i = 0; i < root.series.length; i++) {
                var item = root.series[i]
                if (!item || !item.points)
                    continue
                var selected = selectRange(item.points)
                if (selected.length <= 0)
                    continue
                renderSeries.push({
                    "node": item.node ? String(item.node) : "",
                    "color": item.color ? item.color : "#2563eb",
                    "points": selected
                })
            }
            return renderSeries
        }

        var selectedSingle = selectRange(root.points)
        if (selectedSingle.length > 0) {
            renderSeries.push({
                "node": "",
                "color": root.fuelColor,
                "points": selectedSingle
            })
        }
        return renderSeries
    }

    function xAxisTitle() {
        return root.swapAxes ? "Уровень топлива, %" : "Температура, C"
    }

    function yAxisTitle() {
        return root.swapAxes ? "Температура, C" : "Уровень топлива, %"
    }

    function requestRepaint() {
        canvas.requestPaint()
    }

    onPointsChanged: requestRepaint()
    onSeriesChanged: requestRepaint()
    onOverlayModeChanged: requestRepaint()
    onRangeStartChanged: requestRepaint()
    onRangeEndChanged: requestRepaint()
    onShowPointLabelsChanged: requestRepaint()
    onSwapAxesChanged: requestRepaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        anchors.leftMargin: 18
        anchors.rightMargin: 14
        anchors.topMargin: 16
        anchors.bottomMargin: 40
        antialiasing: true
        z: 1

        Component.onCompleted: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()

        function drawGrid(ctx, l, t, pw, ph) {
            ctx.fillStyle = "#ffffff"
            ctx.fillRect(0, 0, width, height)

            ctx.strokeStyle = "#e2ebf5"
            ctx.lineWidth = 1
            for (var gx = 0; gx <= 5; gx++) {
                var xx = l + (pw / 5) * gx
                ctx.beginPath()
                ctx.moveTo(xx, t)
                ctx.lineTo(xx, t + ph)
                ctx.stroke()
            }
            for (var gy = 0; gy <= 5; gy++) {
                var yy = t + (ph / 5) * gy
                ctx.beginPath()
                ctx.moveTo(l, yy)
                ctx.lineTo(l + pw, yy)
                ctx.stroke()
            }

            ctx.strokeStyle = "#b9ccdf"
            ctx.lineWidth = 1
            ctx.strokeRect(l, t, pw, ph)
        }

        function drawLabel(ctx, x, y, text, color) {
            ctx.save()
            ctx.font = "10px Bahnschrift"
            var textWidth = ctx.measureText(text).width
            var rectW = Math.ceil(textWidth + 8)
            var rectH = 14
            var px = Math.round(x - rectW / 2)
            var py = Math.round(y - rectH)

            if (px < 2)
                px = 2
            if (px + rectW > width - 2)
                px = width - rectW - 2
            if (py < 2)
                py = 2
            if (py + rectH > height - 2)
                py = height - rectH - 2

            ctx.fillStyle = "rgba(255,255,255,0.92)"
            ctx.strokeStyle = color
            ctx.lineWidth = 1
            ctx.fillRect(px, py, rectW, rectH)
            ctx.strokeRect(px, py, rectW, rectH)
            ctx.fillStyle = "#1f2d3d"
            ctx.fillText(text, px + 4, py + 10)
            ctx.restore()
        }

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()

            var w = width
            var h = height
            if (w < 60 || h < 60)
                return

            var l = 52
            var r = 14
            var t = 8
            var b = 26
            var pw = w - l - r
            var ph = h - t - b
            if (pw <= 2 || ph <= 2)
                return

            drawGrid(ctx, l, t, pw, ph)

            var dataSeries = root.buildSeriesForRender()
            if (!dataSeries || dataSeries.length <= 0) {
                ctx.fillStyle = "#8aa0b6"
                ctx.font = "12px Bahnschrift"
                ctx.fillText(root.emptyText, l + 10, t + ph / 2)
                return
            }

            var found = false
            var xMin = 0
            var xMax = 0
            var yMin = 0
            var yMax = 0

            for (var si = 0; si < dataSeries.length; si++) {
                var pts = dataSeries[si].points
                for (var pi = 0; pi < pts.length; pi++) {
                    var xv = root.xValue(pts[pi])
                    var yv = root.yValue(pts[pi])
                    if (isNaN(xv) || isNaN(yv))
                        continue
                    if (!found) {
                        xMin = xv; xMax = xv; yMin = yv; yMax = yv
                        found = true
                    } else {
                        if (xv < xMin) xMin = xv
                        if (xv > xMax) xMax = xv
                        if (yv < yMin) yMin = yv
                        if (yv > yMax) yMax = yv
                    }
                }
            }

            if (!found)
                return

            var xSpan = Math.abs(xMax - xMin)
            var ySpan = Math.abs(yMax - yMin)
            if (xSpan < 1e-6) {
                xMin -= 0.5
                xMax += 0.5
                xSpan = 1.0
            }
            if (ySpan < 1e-6) {
                yMin -= 0.5
                yMax += 0.5
                ySpan = 1.0
            }

            var xPad = Math.max(0.2, xSpan * 0.06)
            var yPad = Math.max(0.2, ySpan * 0.06)
            xMin -= xPad
            xMax += xPad
            yMin -= yPad
            yMax += yPad

            function mapX(v) {
                var ratio = (Number(v) - xMin) / (xMax - xMin)
                ratio = Math.max(0, Math.min(1, ratio))
                return l + ratio * pw
            }
            function mapY(v) {
                var ratio = (Number(v) - yMin) / (yMax - yMin)
                ratio = Math.max(0, Math.min(1, ratio))
                return t + (1.0 - ratio) * ph
            }

            ctx.save()
            ctx.font = "10px Bahnschrift"
            ctx.fillStyle = "#51667d"
            ctx.textBaseline = "middle"

            for (var xt = 0; xt <= 5; xt++) {
                var xvTick = xMin + ((xMax - xMin) * xt) / 5
                var xx = l + (pw * xt) / 5
                ctx.textAlign = "center"
                ctx.fillText(xvTick.toFixed(1), xx, t + ph + 14)
            }

            for (var yt = 0; yt <= 5; yt++) {
                var yvTick = yMax - ((yMax - yMin) * yt) / 5
                var yy = t + (ph * yt) / 5
                ctx.textAlign = "right"
                ctx.fillText(yvTick.toFixed(1), l - 6, yy)
            }
            ctx.restore()

            for (var di = 0; di < dataSeries.length; di++) {
                var seriesItem = dataSeries[di]
                var color = seriesItem.color
                var points = seriesItem.points
                if (!points || points.length <= 0)
                    continue

                ctx.strokeStyle = color
                ctx.lineWidth = 2
                ctx.globalAlpha = 0.9
                ctx.beginPath()
                for (var li = 0; li < points.length; li++) {
                    var px = mapX(root.xValue(points[li]))
                    var py = mapY(root.yValue(points[li]))
                    if (li === 0)
                        ctx.moveTo(px, py)
                    else
                        ctx.lineTo(px, py)
                }
                ctx.stroke()

                ctx.globalAlpha = 1.0
                ctx.fillStyle = color
                for (var pi2 = 0; pi2 < points.length; pi2++) {
                    var pxx = mapX(root.xValue(points[pi2]))
                    var pyy = mapY(root.yValue(points[pi2]))
                    ctx.beginPath()
                    ctx.arc(pxx, pyy, 2.7, 0, Math.PI * 2)
                    ctx.fill()
                }

                if (root.showPointLabels) {
                    var maxLabels = Math.max(1, Number(root.maxPointLabels))
                    var labelStep = Math.max(1, Math.ceil(points.length / maxLabels))
                    for (var lb = 0; lb < points.length; lb += labelStep) {
                        var lx = mapX(root.xValue(points[lb]))
                        var ly = mapY(root.yValue(points[lb]))
                        var valueText = root.xValue(points[lb]).toFixed(1) + ", " + root.yValue(points[lb]).toFixed(1)
                        drawLabel(ctx, lx, ly - 6, valueText, color)
                    }
                }
            }
            ctx.globalAlpha = 1.0
        }
    }

    Text {
        text: root.xAxisTitle()
        color: "#4f6379"
        font.pixelSize: 11
        font.family: "Bahnschrift"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 7
        z: 3
    }

    Text {
        text: root.yAxisTitle()
        color: "#4f6379"
        font.pixelSize: 11
        font.family: "Bahnschrift"
        rotation: -90
        transformOrigin: Item.TopLeft
        x: 6
        y: parent.height - 16
        z: 3
    }
}
