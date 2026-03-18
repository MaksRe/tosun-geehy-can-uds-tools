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
    property bool smoothSeriesEnabled: true
    property real smoothSeriesAlpha: 0.22
    property int adaptiveRenderFactor: 3
    property int maxMarkerPoints: 1600

    // Compatibility properties.
    property real zoomX: 1.0
    property bool wheelZoomEnabled: true
    property int panOffset: 0

    // Interaction toggles.
    property bool dragZoomEnabled: true
    property bool dragPanEnabled: true

    // Manual viewport (data space).
    property bool manualViewport: false
    property real viewportXMin: NaN
    property real viewportXMax: NaN
    property real viewportYMin: NaN
    property real viewportYMax: NaN

    // Last drawn chart geometry/bounds (canvas local coordinates).
    property real _chartLeft: 0
    property real _chartTop: 0
    property real _chartWidth: 0
    property real _chartHeight: 0
    property real _drawXMin: 0
    property real _drawXMax: 1
    property real _drawYMin: 0
    property real _drawYMax: 1
    property real _baseXMin: 0
    property real _baseXMax: 1
    property real _baseYMin: 0
    property real _baseYMax: 1

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
        var _ignoredMaxCount = maxCount
        if (_ignoredMaxCount < 0)
            _ignoredMaxCount = 0
        // Keep all source points in data model; rendering optimization is done later
        // with pixel-adaptive aggregation to avoid UI lag on huge datasets.
        return sourcePoints
    }

    function smoothPoints(sourcePoints) {
        if (!sourcePoints || sourcePoints.length <= 2 || !root.smoothSeriesEnabled)
            return sourcePoints

        var alpha = Number(root.smoothSeriesAlpha)
        if (!isFinite(alpha))
            alpha = 0.22
        alpha = Math.max(0.02, Math.min(1.0, alpha))
        if (alpha >= 0.999)
            return sourcePoints

        var first = sourcePoints[0]
        var smoothFuel = Number(first.fuel)
        var smoothTemperature = Number(first.temperature)
        var result = [{
            "_idx": first._idx,
            "fuel": smoothFuel,
            "temperature": smoothTemperature,
            "time": first.time
        }]

        for (var i = 1; i < sourcePoints.length; i++) {
            var point = sourcePoints[i]
            var fuel = Number(point.fuel)
            var temperature = Number(point.temperature)
            if (!isFinite(fuel))
                fuel = smoothFuel
            if (!isFinite(temperature))
                temperature = smoothTemperature

            smoothFuel += (fuel - smoothFuel) * alpha
            smoothTemperature += (temperature - smoothTemperature) * alpha
            result.push({
                "_idx": point._idx,
                "fuel": smoothFuel,
                "temperature": smoothTemperature,
                "time": point.time
            })
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
        return smoothPoints(decimatePoints(selected, root.maxRenderPoints))
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

    function hasDrawableViewport() {
        return root._chartWidth > 2
            && root._chartHeight > 2
            && isFinite(root._drawXMin)
            && isFinite(root._drawXMax)
            && isFinite(root._drawYMin)
            && isFinite(root._drawYMax)
            && Math.abs(root._drawXMax - root._drawXMin) > 1e-12
            && Math.abs(root._drawYMax - root._drawYMin) > 1e-12
    }

    function resetView() {
        root.manualViewport = false
        root.viewportXMin = NaN
        root.viewportXMax = NaN
        root.viewportYMin = NaN
        root.viewportYMax = NaN
        root.requestRepaint()
    }

    function _ensureManualViewportFromCurrent() {
        if (!root.hasDrawableViewport())
            return false

        if (!root.manualViewport
                || !isFinite(root.viewportXMin) || !isFinite(root.viewportXMax)
                || !isFinite(root.viewportYMin) || !isFinite(root.viewportYMax)) {
            root.viewportXMin = root._drawXMin
            root.viewportXMax = root._drawXMax
            root.viewportYMin = root._drawYMin
            root.viewportYMax = root._drawYMax
        }
        root.manualViewport = true
        return true
    }

    function zoomAtPixel(px, py, factor) {
        if (!root.wheelZoomEnabled || !root.hasDrawableViewport())
            return
        if (!root._ensureManualViewportFromCurrent())
            return

        var zoomFactor = Number(factor)
        if (!isFinite(zoomFactor) || zoomFactor <= 0.0)
            return

        var chartX0 = root._chartLeft
        var chartY0 = root._chartTop
        var chartX1 = chartX0 + root._chartWidth
        var chartY1 = chartY0 + root._chartHeight
        var cx = Math.max(chartX0, Math.min(chartX1, Number(px)))
        var cy = Math.max(chartY0, Math.min(chartY1, Number(py)))

        var ratioX = (cx - chartX0) / root._chartWidth
        var ratioY = (cy - chartY0) / root._chartHeight

        var spanX = root.viewportXMax - root.viewportXMin
        var spanY = root.viewportYMax - root.viewportYMin
        if (!isFinite(spanX) || !isFinite(spanY) || spanX <= 1e-12 || spanY <= 1e-12)
            return

        var baseSpanX = Math.max(1e-9, Math.abs(root._baseXMax - root._baseXMin))
        var baseSpanY = Math.max(1e-9, Math.abs(root._baseYMax - root._baseYMin))
        var minSpanX = Math.max(1e-6, baseSpanX * 0.001)
        var minSpanY = Math.max(1e-6, baseSpanY * 0.001)
        var maxSpanX = Math.max(minSpanX, baseSpanX * 200.0)
        var maxSpanY = Math.max(minSpanY, baseSpanY * 200.0)

        var newSpanX = Math.max(minSpanX, Math.min(maxSpanX, spanX * zoomFactor))
        var newSpanY = Math.max(minSpanY, Math.min(maxSpanY, spanY * zoomFactor))

        var anchorX = root.viewportXMin + ratioX * spanX
        var anchorY = root.viewportYMin + (1.0 - ratioY) * spanY

        root.viewportXMin = anchorX - ratioX * newSpanX
        root.viewportXMax = root.viewportXMin + newSpanX
        root.viewportYMin = anchorY - (1.0 - ratioY) * newSpanY
        root.viewportYMax = root.viewportYMin + newSpanY
        root.requestRepaint()
    }

    function panByPixels(dx, dy) {
        if (!root.dragPanEnabled || !root.hasDrawableViewport())
            return
        if (!root._ensureManualViewportFromCurrent())
            return

        var spanX = root.viewportXMax - root.viewportXMin
        var spanY = root.viewportYMax - root.viewportYMin
        if (!isFinite(spanX) || !isFinite(spanY) || spanX <= 1e-12 || spanY <= 1e-12)
            return

        var shiftX = -Number(dx) / root._chartWidth * spanX
        var shiftY = Number(dy) / root._chartHeight * spanY
        root.viewportXMin += shiftX
        root.viewportXMax += shiftX
        root.viewportYMin += shiftY
        root.viewportYMax += shiftY
        root.requestRepaint()
    }

    onPointsChanged: requestRepaint()
    onSeriesChanged: requestRepaint()
    onOverlayModeChanged: requestRepaint()
    onRangeStartChanged: requestRepaint()
    onRangeEndChanged: requestRepaint()
    onShowPointLabelsChanged: requestRepaint()
    onSwapAxesChanged: requestRepaint()
    onSmoothSeriesEnabledChanged: requestRepaint()
    onSmoothSeriesAlphaChanged: requestRepaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        anchors.leftMargin: 18
        anchors.rightMargin: 14
        anchors.topMargin: 16
        anchors.bottomMargin: 40
        antialiasing: true
        renderTarget: Canvas.FramebufferObject
        renderStrategy: Canvas.Threaded
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

            root._chartLeft = l
            root._chartTop = t
            root._chartWidth = pw
            root._chartHeight = ph

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
                        xMin = xv
                        xMax = xv
                        yMin = yv
                        yMax = yv
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
            var baseXMin = xMin - xPad
            var baseXMax = xMax + xPad
            var baseYMin = yMin - yPad
            var baseYMax = yMax + yPad

            root._baseXMin = baseXMin
            root._baseXMax = baseXMax
            root._baseYMin = baseYMin
            root._baseYMax = baseYMax

            var viewXMin = baseXMin
            var viewXMax = baseXMax
            var viewYMin = baseYMin
            var viewYMax = baseYMax

            if (root.manualViewport) {
                var vx0 = Number(root.viewportXMin)
                var vx1 = Number(root.viewportXMax)
                var vy0 = Number(root.viewportYMin)
                var vy1 = Number(root.viewportYMax)
                if (isFinite(vx0) && isFinite(vx1) && Math.abs(vx1 - vx0) > 1e-12) {
                    viewXMin = Math.min(vx0, vx1)
                    viewXMax = Math.max(vx0, vx1)
                }
                if (isFinite(vy0) && isFinite(vy1) && Math.abs(vy1 - vy0) > 1e-12) {
                    viewYMin = Math.min(vy0, vy1)
                    viewYMax = Math.max(vy0, vy1)
                }
            }

            var baseSpanX = Math.max(1e-9, baseXMax - baseXMin)
            var baseSpanY = Math.max(1e-9, baseYMax - baseYMin)
            var minSpanX = Math.max(1e-6, baseSpanX * 0.001)
            var minSpanY = Math.max(1e-6, baseSpanY * 0.001)

            if ((viewXMax - viewXMin) < minSpanX) {
                var cx = (viewXMin + viewXMax) * 0.5
                viewXMin = cx - minSpanX * 0.5
                viewXMax = cx + minSpanX * 0.5
            }
            if ((viewYMax - viewYMin) < minSpanY) {
                var cy = (viewYMin + viewYMax) * 0.5
                viewYMin = cy - minSpanY * 0.5
                viewYMax = cy + minSpanY * 0.5
            }

            root._drawXMin = viewXMin
            root._drawXMax = viewXMax
            root._drawYMin = viewYMin
            root._drawYMax = viewYMax
            root.zoomX = baseSpanX / Math.max(minSpanX, viewXMax - viewXMin)
            root.panOffset = Math.round(((viewXMin - baseXMin) / baseSpanX) * 1000.0)

            function mapX(v) {
                var ratio = (Number(v) - viewXMin) / (viewXMax - viewXMin)
                return l + ratio * pw
            }
            function mapY(v) {
                var ratio = (Number(v) - viewYMin) / (viewYMax - viewYMin)
                return t + (1.0 - ratio) * ph
            }

            function pushUnique(target, entry) {
                if (!entry)
                    return
                if (target.length > 0 && target[target.length - 1].idx === entry.idx)
                    return
                target.push(entry)
            }

            function buildRenderablePoints(sourcePoints) {
                if (!sourcePoints || sourcePoints.length <= 0)
                    return []

                var total = sourcePoints.length
                var denseLimit = Math.max(64, Math.floor(pw * 1.2))
                var result = []

                function addRawPoint(point, idx) {
                    var xv = root.xValue(point)
                    var yv = root.yValue(point)
                    if (!isFinite(xv) || !isFinite(yv))
                        return null
                    var entry = {
                        "idx": idx,
                        "x": mapX(xv),
                        "y": mapY(yv),
                        "rawX": xv,
                        "rawY": yv
                    }
                    if (!isFinite(entry.x) || !isFinite(entry.y))
                        return null
                    return entry
                }

                if (total <= denseLimit) {
                    for (var i = 0; i < total; i++) {
                        var rawEntry = addRawPoint(sourcePoints[i], i)
                        if (rawEntry)
                            result.push(rawEntry)
                    }
                    return result
                }

                var renderFactor = Math.max(1, Math.floor(Number(root.adaptiveRenderFactor)))
                var targetBuckets = Math.max(64, Math.floor(pw * renderFactor))
                var bucketSize = Math.max(1, Math.ceil(total / targetBuckets))

                for (var start = 0; start < total; start += bucketSize) {
                    var end = Math.min(total, start + bucketSize)
                    var first = null
                    var last = null
                    var minEntry = null
                    var maxEntry = null

                    for (var j = start; j < end; j++) {
                        var entry = addRawPoint(sourcePoints[j], j)
                        if (!entry)
                            continue

                        if (!first) {
                            first = entry
                            minEntry = entry
                            maxEntry = entry
                        }
                        last = entry
                        if (entry.y < minEntry.y)
                            minEntry = entry
                        if (entry.y > maxEntry.y)
                            maxEntry = entry
                    }

                    if (!first)
                        continue

                    pushUnique(result, first)

                    var mids = []
                    if (minEntry && minEntry.idx !== first.idx && minEntry.idx !== last.idx)
                        mids.push(minEntry)
                    if (maxEntry && maxEntry.idx !== first.idx && maxEntry.idx !== last.idx && maxEntry.idx !== minEntry.idx)
                        mids.push(maxEntry)
                    mids.sort(function(a, b) { return a.idx - b.idx })
                    for (var m = 0; m < mids.length; m++)
                        pushUnique(result, mids[m])

                    pushUnique(result, last)
                }

                return result
            }

            ctx.save()
            ctx.font = "10px Bahnschrift"
            ctx.fillStyle = "#51667d"
            ctx.textBaseline = "middle"

            for (var xt = 0; xt <= 5; xt++) {
                var xvTick = viewXMin + ((viewXMax - viewXMin) * xt) / 5
                var xx = l + (pw * xt) / 5
                ctx.textAlign = "center"
                ctx.fillText(xvTick.toFixed(1), xx, t + ph + 14)
            }

            for (var yt = 0; yt <= 5; yt++) {
                var yvTick = viewYMax - ((viewYMax - viewYMin) * yt) / 5
                var yy = t + (ph * yt) / 5
                ctx.textAlign = "right"
                ctx.fillText(yvTick.toFixed(1), l - 6, yy)
            }
            ctx.restore()

            ctx.save()
            ctx.beginPath()
            ctx.rect(l, t, pw, ph)
            ctx.clip()

            for (var di = 0; di < dataSeries.length; di++) {
                var seriesItem = dataSeries[di]
                var color = seriesItem.color
                var points = seriesItem.points
                if (!points || points.length <= 0)
                    continue
                var renderPoints = buildRenderablePoints(points)
                if (!renderPoints || renderPoints.length <= 0)
                    continue

                ctx.strokeStyle = color
                ctx.lineWidth = 2
                ctx.globalAlpha = 0.9
                ctx.beginPath()
                for (var li = 0; li < renderPoints.length; li++) {
                    var px = renderPoints[li].x
                    var py = renderPoints[li].y
                    if (li === 0)
                        ctx.moveTo(px, py)
                    else
                        ctx.lineTo(px, py)
                }
                ctx.stroke()

                ctx.globalAlpha = 1.0
                if (renderPoints.length <= Math.max(100, Number(root.maxMarkerPoints))) {
                    ctx.fillStyle = color
                    for (var pi2 = 0; pi2 < renderPoints.length; pi2++) {
                        var pxx = renderPoints[pi2].x
                        var pyy = renderPoints[pi2].y
                        ctx.beginPath()
                        ctx.arc(pxx, pyy, 2.2, 0, Math.PI * 2)
                        ctx.fill()
                    }
                }

                if (root.showPointLabels) {
                    var maxLabels = Math.max(1, Number(root.maxPointLabels))
                    var labelStep = Math.max(1, Math.ceil(renderPoints.length / maxLabels))
                    for (var lb = 0; lb < renderPoints.length; lb += labelStep) {
                        var lx = renderPoints[lb].x
                        var ly = renderPoints[lb].y
                        if (lx < l || lx > (l + pw) || ly < t || ly > (t + ph))
                            continue
                        var valueText = renderPoints[lb].rawX.toFixed(1) + ", " + renderPoints[lb].rawY.toFixed(1)
                        drawLabel(ctx, lx, ly - 6, valueText, color)
                    }
                }
            }
            ctx.restore()
            ctx.globalAlpha = 1.0
        }
    }

    MouseArea {
        id: interactionLayer
        anchors.fill: canvas
        z: 2
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: true
        preventStealing: true
        cursorShape: dragMode === "pan" ? Qt.ClosedHandCursor : Qt.CrossCursor

        property bool dragging: false
        property string dragMode: ""
        property real startX: 0
        property real startY: 0
        property real lastX: 0
        property real lastY: 0

        onPressed: {
            if (!root.hasDrawableViewport())
                return

            dragging = true
            startX = mouse.x
            startY = mouse.y
            lastX = mouse.x
            lastY = mouse.y

            if (mouse.button === Qt.RightButton && root.dragPanEnabled)
                dragMode = "pan"
            else if (mouse.button === Qt.LeftButton && root.dragZoomEnabled)
                dragMode = "zoom"
            else
                dragMode = ""
        }

        onPositionChanged: {
            if (!dragging)
                return

            if (dragMode === "pan") {
                root.panByPixels(mouse.x - lastX, mouse.y - lastY)
            }
            lastX = mouse.x
            lastY = mouse.y
        }

        onReleased: {
            if (!dragging)
                return

            if (dragMode === "zoom" && root.dragZoomEnabled) {
                var dx = Math.abs(lastX - startX)
                var dy = Math.abs(lastY - startY)
                if (dx >= 8 && dy >= 8 && root.hasDrawableViewport()) {
                    var chartX0 = root._chartLeft
                    var chartY0 = root._chartTop
                    var chartX1 = chartX0 + root._chartWidth
                    var chartY1 = chartY0 + root._chartHeight

                    var sx0 = Math.max(chartX0, Math.min(chartX1, Math.min(startX, lastX)))
                    var sx1 = Math.max(chartX0, Math.min(chartX1, Math.max(startX, lastX)))
                    var sy0 = Math.max(chartY0, Math.min(chartY1, Math.min(startY, lastY)))
                    var sy1 = Math.max(chartY0, Math.min(chartY1, Math.max(startY, lastY)))

                    if ((sx1 - sx0) >= 4 && (sy1 - sy0) >= 4) {
                        var rx0 = (sx0 - chartX0) / root._chartWidth
                        var rx1 = (sx1 - chartX0) / root._chartWidth
                        var ry0 = (sy0 - chartY0) / root._chartHeight
                        var ry1 = (sy1 - chartY0) / root._chartHeight

                        var dataX0 = root._drawXMin + rx0 * (root._drawXMax - root._drawXMin)
                        var dataX1 = root._drawXMin + rx1 * (root._drawXMax - root._drawXMin)
                        var dataY0 = root._drawYMin + (1.0 - ry0) * (root._drawYMax - root._drawYMin)
                        var dataY1 = root._drawYMin + (1.0 - ry1) * (root._drawYMax - root._drawYMin)

                        root.viewportXMin = Math.min(dataX0, dataX1)
                        root.viewportXMax = Math.max(dataX0, dataX1)
                        root.viewportYMin = Math.min(dataY0, dataY1)
                        root.viewportYMax = Math.max(dataY0, dataY1)
                        root.manualViewport = true
                        root.requestRepaint()
                    }
                }
            }

            dragging = false
            dragMode = ""
        }

        onCanceled: {
            dragging = false
            dragMode = ""
        }

        onWheel: {
            if (!root.wheelZoomEnabled || !root.hasDrawableViewport())
                return
            wheel.accepted = true
            var dy = wheel.angleDelta.y
            if (dy === 0)
                return
            var factor = dy > 0 ? 0.88 : 1.14
            root.zoomAtPixel(wheel.x, wheel.y, factor)
        }

        onDoubleClicked: root.resetView()

        Rectangle {
            visible: interactionLayer.dragging
                     && interactionLayer.dragMode === "zoom"
                     && Math.abs(interactionLayer.lastX - interactionLayer.startX) >= 4
                     && Math.abs(interactionLayer.lastY - interactionLayer.startY) >= 4
            x: Math.min(interactionLayer.startX, interactionLayer.lastX)
            y: Math.min(interactionLayer.startY, interactionLayer.lastY)
            width: Math.abs(interactionLayer.lastX - interactionLayer.startX)
            height: Math.abs(interactionLayer.lastY - interactionLayer.startY)
            color: "#2563eb22"
            border.color: "#1d4ed8"
            border.width: 1
            radius: 2
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
