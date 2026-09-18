import QtQuick 2.15

/*
  График одного живого числа: время слева направо, значение по высоте.

  ЗАЧЕМ ДВА ВИДА
  В карточке нужен маленький график: по нему видно только направление и дрожание,
  подписи там всё равно не прочитать. Развёрнутый показывает то же самое с сеткой,
  шкалами и подписями экстремумов. Чтобы оба вида не разъезжались, это один
  компонент: вид переключает свойство compact.

  ЭКСТРЕМУМЫ
  Наименьшее и наибольшее значение приходят готовыми: они считаются по всем
  пришедшим данным, а не по тем точкам, что остались на графике. Рисуются
  пунктиром, поэтому сразу видно, далеко ли текущее значение от своих границ.

  Публичные свойства:
  - points: точки [{ x: секунды, y: значение }];
  - lineColor: цвет линии;
  - compact: маленький вид без подписей;
  - minValue/maxValue: экстремумы, NaN - не показывать;
  - unit: единица для подписей шкалы;
  - emptyText: что написать, пока точек нет.
*/
Rectangle {
    id: root

    property var points: []
    property color lineColor: "#0284c7"
    property bool compact: false
    property real minValue: NaN
    property real maxValue: NaN
    property real meanValue: NaN
    property string unit: ""
    property string emptyText: "нет данных"

    radius: root.compact ? 6 : 10
    color: "#ffffff"
    border.width: 1
    border.color: "#e2ebf5"
    clip: true

    onPointsChanged: canvas.requestPaint()
    onMinValueChanged: canvas.requestPaint()
    onMaxValueChanged: canvas.requestPaint()
    onMeanValueChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()

    function decimalText(value, digits) {
        return Number(value).toFixed(digits).replace(".", ",")
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true
        renderStrategy: Canvas.Immediate

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()

            var source = root.points || []
            var left = root.compact ? 4 : 56
            var right = root.compact ? 4 : 12
            var top = root.compact ? 4 : 10
            var bottom = root.compact ? 4 : 22
            var plotWidth = width - left - right
            var plotHeight = height - top - bottom
            if (plotWidth < 6 || plotHeight < 6)
                return

            if (source.length < 1) {
                ctx.fillStyle = "#94a3b8"
                ctx.font = (root.compact ? "9px" : "11px") + " Bahnschrift"
                ctx.fillText(root.emptyText, left + 4, top + plotHeight / 2)
                return
            }

            // Границы данных: экстремумы входят в них, чтобы пунктир не ушёл за край.
            var xMin = Number(source[0].x)
            var xMax = Number(source[source.length - 1].x)
            var yMin = Number(source[0].y)
            var yMax = yMin
            for (var i = 0; i < source.length; i++) {
                var value = Number(source[i].y)
                if (value < yMin) yMin = value
                if (value > yMax) yMax = value
            }
            if (isFinite(root.minValue) && root.minValue < yMin) yMin = root.minValue
            if (isFinite(root.maxValue) && root.maxValue > yMax) yMax = root.maxValue

            if (xMax - xMin < 1e-6) xMax = xMin + 1.0
            if (yMax - yMin < 1e-9) {
                yMin -= 0.5
                yMax += 0.5
            }
            var pad = (yMax - yMin) * 0.08
            yMin -= pad
            yMax += pad

            function mapX(value) { return left + ((Number(value) - xMin) / (xMax - xMin)) * plotWidth }
            function mapY(value) { return top + (1.0 - (Number(value) - yMin) / (yMax - yMin)) * plotHeight }

            // Сетка и шкалы только у развёрнутого графика: в миниатюре они превращаются в кашу.
            if (!root.compact) {
                ctx.strokeStyle = "#eef4fb"
                ctx.lineWidth = 1
                ctx.font = "10px Bahnschrift"
                ctx.fillStyle = "#64748b"
                ctx.textBaseline = "middle"
                for (var gy = 0; gy <= 4; gy++) {
                    var yy = top + (plotHeight / 4) * gy
                    ctx.beginPath()
                    ctx.moveTo(left, yy)
                    ctx.lineTo(left + plotWidth, yy)
                    ctx.stroke()
                    ctx.textAlign = "right"
                    ctx.fillText(root.decimalText(yMax - ((yMax - yMin) / 4) * gy, 1), left - 6, yy)
                }
                ctx.textAlign = "center"
                ctx.textBaseline = "alphabetic"
                for (var gx = 0; gx <= 4; gx++) {
                    var xx = left + (plotWidth / 4) * gx
                    ctx.beginPath()
                    ctx.moveTo(xx, top)
                    ctx.lineTo(xx, top + plotHeight)
                    ctx.stroke()
                    var seconds = xMin + ((xMax - xMin) / 4) * gx
                    ctx.fillText(root.decimalText(seconds, 0) + " с", xx, height - 6)
                }
            }

            // Экстремумы пунктиром.
            function dashedLine(value, color) {
                if (!isFinite(value))
                    return
                var y = mapY(value)
                ctx.strokeStyle = color
                ctx.lineWidth = 1
                ctx.beginPath()
                for (var x = left; x < left + plotWidth; x += 8) {
                    ctx.moveTo(x, y)
                    ctx.lineTo(Math.min(x + 4, left + plotWidth), y)
                }
                ctx.stroke()
            }
            dashedLine(root.maxValue, "#f0a35e")
            dashedLine(root.minValue, "#7dbfe8")
            dashedLine(root.meanValue, "#8fbfb4")

            ctx.strokeStyle = root.lineColor
            ctx.lineWidth = root.compact ? 1.5 : 2
            ctx.beginPath()
            for (var p = 0; p < source.length; p++) {
                var px = mapX(source[p].x)
                var py = mapY(source[p].y)
                if (p === 0)
                    ctx.moveTo(px, py)
                else
                    ctx.lineTo(px, py)
            }
            ctx.stroke()

            // Последняя точка: по ней видно, где сейчас находится значение.
            var lastX = mapX(source[source.length - 1].x)
            var lastY = mapY(source[source.length - 1].y)
            ctx.fillStyle = root.lineColor
            ctx.beginPath()
            ctx.arc(lastX, lastY, root.compact ? 2.0 : 3.2, 0, Math.PI * 2)
            ctx.fill()
        }
    }
}
