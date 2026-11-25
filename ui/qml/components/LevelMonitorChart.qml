import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "."

ColumnLayout {
    id: root
    property var monitor: ({})
    property string axis: "time"
    property var hiddenBoards: ({})
    readonly property var plot: (monitor.plots || {})[axis] || ({})
    readonly property var boards: plot.boards || []
    property var viewport: null
    property var marks: []
    property var geometry: null
    property string sessionId: ""
    spacing: 8
    Layout.fillWidth: true

    component ChartButton: Button {
        id: button
        implicitWidth: label.implicitWidth + 24
        implicitHeight: 32
        contentItem: Text {
            id: label
            text: button.text
            color: button.enabled ? "#0f172a" : "#64748b"
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: 7
            color: !button.enabled ? "#dbeafe" : button.hovered ? "#e2e8f0" : "#f1f5f9"
            border.color: "#cbd5e1"
        }
    }

    // Для независимого выбора линий меняет только видимость, сохраняя сбор показаний всех плат.
    function setBoard(key, shown) {
        var next = Object.assign({}, hiddenBoards)
        next[key] = !shown
        hiddenBoards = next
    }

    // Для быстрого сравнения включает или скрывает все линии графика.
    function showAll(shown) {
        var next = {}
        for (var i = 0; i < boards.length; ++i)
            next[boards[i].key] = !shown
        hiddenBoards = next
    }

    // Для сопоставимых чисел выводит проценты с общей точностью и явным знаком.
    function number(value, signed) {
        return value === null || value === undefined || !isFinite(value) ? "—"
            : (signed !== false && value > 0 ? "+" : "") + Number(value).toFixed(2).replace(".", ",")
    }

    // Чтобы имя платы не меняло разметку сводки, экранирует служебные символы HTML.
    function safe(value) {
        return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    }

    // Для обновлений сохраняет выбранный масштаб, сбрасывая его только при смене прогона или оси.
    function resetView() {
        viewport = null
        marks = []
        chart.requestPaint()
    }
    onAxisChanged: resetView()
    onMonitorChanged: {
        var next = monitor.sessionId || "live"
        if (sessionId !== next) { sessionId = next; resetView() }
    }

    // Для краткой сводки берёт точные итоги полной истории, а у старого архива — сохранённые экстремумы.
    function stats() {
        var timeBoards = ((monitor.plots || {}).time || {}).boards || []
        return timeBoards.filter(function(b) { return !root.hiddenBoards[b.key] }).map(function(b) {
            var exact = (root.monitor.summary || []).find(function(r) { return r.key === b.key })
            if (exact && exact.count) return Object.assign({}, b, exact)
            var values = (b.pts || []).map(function(p) { return p[1] })
            if (!values.length) return Object.assign({}, b, {count: 0})
            var min = Math.min.apply(Math, values), max = Math.max.apply(Math, values)
            return Object.assign({}, b, {count: values.length, min: min, max: max,
                span: max - min, delta: values[values.length - 1] - values[0], worst: Math.max(Math.abs(min), Math.abs(max))})
        }).filter(function(r) { return r.count > 0 })
    }

    // Для оценки всего прогона показывает экстремумы и изменения независимо от масштаба и видимой области.
    function summaryHtml() {
        var rows = stats()
        if (!rows.length) return "Нет показаний выбранных плат."
        var worst = Math.max.apply(Math, rows.map(function(r) { return r.worst }))
        var currents = rows.map(function(r) { return r.current }).filter(function(v) { return v !== null && v !== undefined && isFinite(v) })
        var spread = currents.length > 1 ? Math.max.apply(Math, currents) - Math.min.apply(Math, currents) : null
        var text = "<b>Выбранные платы · весь прогон</b><br>Худшее: <b>" + number(worst, false) + " %</b>"
            + "<br>Допуск ±1 %: " + (worst > 1 ? "<font color='#dc2626'>превышен</font>" : "соблюдён по данным")
            + "<br>Разница плат сейчас: " + number(spread, false) + " п.п."
        for (var i = 0; i < rows.length; ++i) {
            var r = rows[i]
            text += "<br><br><b><font color='" + r.color + "'>" + safe(r.label) + "</font></b>"
                + "<br>Min / max: " + number(r.min) + " / " + number(r.max) + " %"
                + "<br>Размах: " + number(r.span, false) + " п.п. · Δ: " + number(r.delta) + " п.п."
        }
        text += "<br><br><b>Сравнение A → B</b>"
        for (var j = 0; j < marks.length; ++j)
            text += "<br>" + (j ? "B" : "A") + ": " + safe(marks[j].label) + " · " + number(marks[j].y) + " % · "
                + number(marks[j].x, false) + (axis === "time" ? " ч" : " °C")
        if (marks.length === 2)
            text += "<br>Δ уровня: <b>" + number(marks[1].y - marks[0].y) + " п.п.</b>"
                + "<br>Δ " + (axis === "time" ? "времени: " : "температуры: ") + number(marks[1].x - marks[0].x)
                + (axis === "time" ? " ч" : " °C")
        else text += "<br>Нажмите две точки графика."
        return text
    }

    // Для приближения участка сохраняет координаты измерения под указателем.
    function zoom(factor, x, y) {
        var g = geometry
        if (!g) return
        var v = viewport || g.base
        var rx = Math.max(0, Math.min(1, (x - g.left) / g.pw)), ry = Math.max(0, Math.min(1, (y - g.top) / g.ph))
        var bx = g.base[1] - g.base[0], by = g.base[3] - g.base[2]
        var sx = Math.max(bx * .001, Math.min(bx * 8, (v[1] - v[0]) * factor))
        var sy = Math.max(by * .001, Math.min(by * 8, (v[3] - v[2]) * factor))
        var ax = v[0] + rx * (v[1] - v[0]), ay = v[3] - ry * (v[3] - v[2])
        viewport = [ax - rx * sx, ax + (1 - rx) * sx, ay - (1 - ry) * sy, ay + ry * sy]
        chart.requestPaint()
    }

    // Для честного сравнения ставит A/B на ближайший сохранённый отсчёт без интерполяции.
    function markPoint(x, y) {
        var g = geometry
        if (!g || x < g.left || x > g.left + g.pw || y < g.top || y > g.top + g.ph) return
        var v = viewport || g.base, distance = Infinity, nearest = null
        for (var i = 0; i < boards.length; ++i) {
            var b = boards[i]
            if (hiddenBoards[b.key]) continue
            for (var j = 0; j < b.pts.length; ++j) {
                var p = b.pts[j]
                var dx = g.left + (p[0] - v[0]) / (v[1] - v[0]) * g.pw - x
                var dy = g.top + (v[3] - p[1]) / (v[3] - v[2]) * g.ph - y
                var d = dx * dx + dy * dy
                if (d < distance) { distance = d; nearest = {x:p[0], y:p[1], label:b.label, color:b.color} }
            }
        }
        if (nearest) { marks = marks.length === 2 ? [nearest] : marks.concat([nearest]); chart.requestPaint() }
    }

    Flow {
        Layout.fillWidth: true
        spacing: 6
        ChartButton {
            text: "По времени"
            enabled: root.axis !== "time"
            onClicked: root.axis = "time"
        }
        ChartButton {
            text: "По температуре"
            enabled: root.axis !== "temperature"
            onClicked: root.axis = "temperature"
        }
        ChartButton { text: "Все платы"; onClicked: root.showAll(true) }
        ChartButton { text: "Скрыть все"; onClicked: root.showAll(false) }
    }
    Flow {
        Layout.fillWidth: true
        spacing: 10
        Repeater {
            model: root.boards
            CheckBox {
                id: choice
                required property var modelData
                text: modelData.label
                checked: !root.hiddenBoards[modelData.key]
                indicator: Rectangle {
                    implicitWidth: 16; implicitHeight: 16
                    x: choice.leftPadding
                    y: (choice.height - height) / 2
                    radius: 3
                    color: choice.checked ? choice.modelData.color : "white"
                    border.color: choice.modelData.color
                    Rectangle { visible: choice.checked; x: 3; y: 8; width: 5; height: 2; rotation: 45; color: "white" }
                    Rectangle { visible: choice.checked; x: 6; y: 7; width: 8; height: 2; rotation: -45; color: "white" }
                }
                contentItem: Text {
                    text: choice.text
                    leftPadding: 24
                    verticalAlignment: Text.AlignVCenter
                    color: choice.modelData.color
                    font.pixelSize: 12
                }
                onToggled: root.setBoard(modelData.key, checked)
            }
        }
    }
    Text {
        text: (root.plot.title || "Отклонение уровня") + ", % · допуск ±1 %"
        color: "#0f172a"
        font.bold: true
        font.pixelSize: 14
    }
    Flow {
        Layout.fillWidth: true
        spacing: 6
        ChartButton { text: "+"; onClicked: root.zoom(1 / 1.4, chart.width / 2, chart.height / 2) }
        ChartButton { text: "−"; onClicked: root.zoom(1.4, chart.width / 2, chart.height / 2) }
        ChartButton { text: "Весь прогон"; onClicked: root.resetView() }
        ChartButton { text: "Убрать A/B"; onClicked: { root.marks = []; chart.requestPaint() } }
    }
    Text {
        Layout.fillWidth: true
        text: "Колесо — масштаб · перетаскивание — сдвиг · два нажатия — A/B. Δ — изменение от начала."
        wrapMode: Text.WordWrap
        color: "#64748b"
        font.pixelSize: 12
    }
    GridLayout {
        Layout.fillWidth: true
        columns: root.width > 820 ? 2 : 1
        columnSpacing: 14
        rowSpacing: 10
        Canvas {
            id: chart
            objectName: "levelCanvas"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 160
            Layout.preferredHeight: Math.max(280, Math.min(430, root.width * .30))
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            Connections {
                target: root
                // Для свежих показаний перерисовывает линии, сохраняя масштаб.
                function onPlotChanged() { chart.requestPaint() }
                // Для выбора плат перерисовывает только видимые линии.
                function onHiddenBoardsChanged() { chart.requestPaint() }
            }
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var lines = root.boards.filter(function(b) { return !root.hiddenBoards[b.key] && b.pts.length > 0 })
                var left = 54, top = 12, bottom = 40, right = 16
                var pw = width - left - right, ph = height - top - bottom
                if (pw <= 0 || ph <= 0) return
                var xMin = root.axis === "time" ? 0 : -40
                var xMax = root.axis === "time" ? 1 / 60 : 85, peak = 1.2
                for (var i = 0; i < lines.length; ++i) {
                    for (var j = 0; j < lines[i].pts.length; ++j) {
                        var p = lines[i].pts[j]
                        xMin = Math.min(xMin, p[0]); xMax = Math.max(xMax, p[0]); peak = Math.max(peak, Math.abs(p[1]))
                    }
                }
                var yMax = Math.ceil(peak * 4) / 4, base = [xMin, xMax, -yMax, yMax]
                var v = root.viewport || base
                root.geometry = {left:left, top:top, pw:pw, ph:ph, base:base}
                // Для масштаба переводит координату измерения в горизонтальный пиксель.
                function px(value) { return left + (value - v[0]) / (v[1] - v[0]) * pw }
                // Для масштаба переводит отклонение в вертикальный пиксель.
                function py(value) { return top + (v[3] - value) / (v[3] - v[2]) * ph }
                ctx.save(); ctx.beginPath(); ctx.rect(left, top, pw, ph); ctx.clip()
                ctx.fillStyle = "#fff3df"; ctx.fillRect(left, py(1), pw, py(-1) - py(1))
                ctx.fillStyle = "#e0efdc"; ctx.fillRect(left, py(.5), pw, py(-.5) - py(.5))
                ctx.restore()
                ctx.font = "11px 'Segoe UI'"; ctx.textBaseline = "middle"; ctx.lineWidth = 1
                for (var tick = 0; tick <= 5; ++tick) {
                    var value = v[2] + (v[3] - v[2]) * tick / 5
                    ctx.strokeStyle = "#d9e2ec"; ctx.beginPath(); ctx.moveTo(left, py(value)); ctx.lineTo(left + pw, py(value)); ctx.stroke()
                    ctx.fillStyle = "#475569"; ctx.textAlign = "right"; ctx.fillText(root.number(value), left - 6, py(value))
                    var vx = v[0] + (v[1] - v[0]) * tick / 5
                    ctx.textAlign = "center"; ctx.fillText(root.number(vx, false), px(vx), height - 24)
                }
                ctx.textAlign = "right"; ctx.fillText(root.plot.xLabel || "", left + pw, height - 8)
                ctx.save(); ctx.beginPath(); ctx.rect(left, top, pw, ph); ctx.clip()
                for (var lim = -1; lim <= 1; ++lim) {
                    ctx.strokeStyle = lim ? "#b98631" : "#94a3b8"
                    ctx.beginPath(); ctx.moveTo(left, py(lim)); ctx.lineTo(left + pw, py(lim)); ctx.stroke()
                }
                for (var n = 0; n < lines.length; ++n) {
                    var data = lines[n].pts
                    ctx.strokeStyle = lines[n].color; ctx.fillStyle = lines[n].color; ctx.lineWidth = 1.8; ctx.beginPath()
                    for (var k = 0; k < data.length; ++k) {
                        if (k === 0) ctx.moveTo(px(data[k][0]), py(data[k][1]))
                        else ctx.lineTo(px(data[k][0]), py(data[k][1]))
                    }
                    ctx.stroke()
                    var last = data[data.length - 1]
                    ctx.beginPath(); ctx.arc(px(last[0]), py(last[1]), 3, 0, Math.PI * 2); ctx.fill()
                }
                for (var m = 0; m < root.marks.length; ++m) {
                    var mark = root.marks[m]
                    ctx.fillStyle = mark.color; ctx.beginPath(); ctx.arc(px(mark.x), py(mark.y), 5, 0, Math.PI * 2); ctx.fill()
                    ctx.textAlign = "left"; ctx.fillText(m ? "B" : "A", px(mark.x) + 7, py(mark.y) - 8)
                }
                ctx.restore()
                if (!lines.length) {
                    ctx.fillStyle = "#64748b"; ctx.textAlign = "center"
                    ctx.fillText("Выберите платы с показаниями", left + pw / 2, top + ph / 2)
                }
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.CrossCursor
                preventStealing: true
                property var drag: null
                onPressed: function(mouse) {
                    if (root.geometry) drag = {x:mouse.x, y:mouse.y, v:(root.viewport || root.geometry.base).slice(), moved:false}
                }
                onPositionChanged: function(mouse) {
                    if (!drag || !root.geometry) return
                    var dx = mouse.x - drag.x, dy = mouse.y - drag.y, g = root.geometry
                    if (Math.abs(dx) + Math.abs(dy) > 5) drag.moved = true
                    if (!drag.moved) return
                    var sx = dx / g.pw * (drag.v[1] - drag.v[0]), sy = dy / g.ph * (drag.v[3] - drag.v[2])
                    root.viewport = [drag.v[0] - sx, drag.v[1] - sx, drag.v[2] + sy, drag.v[3] + sy]
                    chart.requestPaint()
                }
                onReleased: function(mouse) { if (drag && !drag.moved) root.markPoint(mouse.x, mouse.y); drag = null }
                onCanceled: drag = null
                onDoubleClicked: root.resetView()
                onWheel: function(wheel) { if (!wheel.angleDelta.y) return; root.zoom(wheel.angleDelta.y > 0 ? 1 / 1.18 : 1.18, wheel.x, wheel.y); wheel.accepted = true }
            }
        }
        Rectangle {
            Layout.fillWidth: root.width <= 820
            Layout.preferredWidth: root.width > 820 ? 270 : -1
            Layout.preferredHeight: summary.implicitHeight + 24
            Layout.alignment: Qt.AlignTop
            color: "#f8fafc"
            border.color: "#dbe3ed"
            radius: 10
            Text {
                id: summary
                anchors.left: parent.left; anchors.right: parent.right
                anchors.top: parent.top; anchors.margins: 12
                text: root.summaryHtml()
                textFormat: Text.RichText
                wrapMode: Text.WordWrap
                font.pixelSize: 12
                color: "#334155"
            }
        }
    }
    Text {
        Layout.fillWidth: true
        text: "Отклонение от 0 % включает остаточную плёнку. Выбор линий не отключает опрос и запись плат."
        wrapMode: Text.WordWrap
        color: "#64748b"
        font.pixelSize: 12
    }
}
