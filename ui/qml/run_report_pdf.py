"""Итоговый отчёт прогона в камере - файлом PDF.

ЗАЧЕМ
После прогона его разбирали по архиву: журналы, итоги текстом, скриншоты мини-приложения. Отчёт
PDF собирает главное в один документ, который можно переслать и распечатать (13.11.2026): что за
прогон, какие платы и что в них было записано, итог по каждой плате против требования ±1 %,
погрешность и сдвиг уровня по узлам температуры, графики, таблицы итогов и события.

КАК УСТРОЕН
Данные собирает программа (report_data в контроллере) обычным словарём, здесь - только вид:
HTML для QTextDocument и графики, нарисованные QPainter. Печать - QPdfWriter: всё из Qt, новых
библиотек не нужно, русский текст и знаки (°, −, ±) - шрифтом системы.
"""

from __future__ import annotations

import math
import os
import sys
from html import escape

# Цвета плат на графиках - те же, что в мини-приложении.
BOARD_COLORS = ("#0284c7", "#ea580c", "#16a34a", "#9333ea", "#dc2626", "#0d9488", "#ca8a04", "#db2777")
TONE_COLORS = {"ok": "#16a34a", "warn": "#d97706", "bad": "#dc2626", "info": "#475569"}
TONE_SOFT = {"ok": "#ecfdf5", "warn": "#fffbeb", "bad": "#fef2f2", "info": "#ffffff"}
# Таблица шире стольких столбцов на листе не читается: вместо неё - ссылка на архив.
WIDE_COLUMNS = 11


def _ensure_app():
    """Шрифты и печать Qt требуют приложения; в программе оно уже есть, в проверках - создаётся без окна."""
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        # В Windows - обычная платформа (окон не открывает, а шрифты системы видит); «offscreen» шрифтов
        # Windows не знает и печатает квадраты вместо букв. Без экрана в других системах - offscreen.
        if not sys.platform.startswith("win"):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _ensure_app.app = QGuiApplication([])
    return QGuiApplication.instance()


def _e(value) -> str:
    return escape("" if value is None else str(value))


def _num(value: float, digits: int = 2, sign: bool = True) -> str:
    text = f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"
    return text.replace(".", ",").replace("-", "−")


# ------------------------------------------------------------------ графики

def draw_chart(series: list[dict], title: str, x_label: str, y_label: str, bands=(0.5, 1.0),
               width: int = 1800, height: int = 760, x_ticks_fmt=None):
    """График линиями: series = [{"name", "color", "points": [(x, y), ...], "dots": bool}]; полосы допуска ±bands."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen

    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    font = QFont("Segoe UI")
    font.setPixelSize(22)
    painter.setFont(font)

    left, right, top, bottom = 120, 30, 70, 120
    plot = QRectF(left, top, width - left - right, height - top - bottom)
    xs = [x for item in series for x, _y in item["points"]]
    ys = [y for item in series for _x, y in item["points"]]
    if not xs:
        painter.drawText(plot, Qt.AlignCenter, "данных нет")
        painter.end()
        return image
    x0, x1 = min(xs), max(xs)
    if x1 - x0 < 1e-9:
        x0, x1 = x0 - 1, x1 + 1
    limit = max([abs(y) for y in ys] + [max(bands) * 1.2 if bands else 0.1])
    y0, y1 = -limit * 1.1, limit * 1.1

    def px(x, y):
        return QPointF(plot.left() + (x - x0) / (x1 - x0) * plot.width(),
                       plot.bottom() - (y - y0) / (y1 - y0) * plot.height())

    # Полосы допуска: зелёная - в норме, жёлтая - на грани.
    if bands:
        for edge, color in ((max(bands), "#fef3c7"), (min(bands), "#dcfce7")):
            top_left, bottom_right = px(x0, min(edge, y1)), px(x1, max(-edge, y0))
            painter.fillRect(QRectF(top_left, bottom_right), QColor(color))
    # Сетка и подписи осей.
    painter.setPen(QPen(QColor("#cbd5e1"), 1))
    step = _nice_step(y1 - y0, 8)
    value = math.ceil(y0 / step) * step
    while value <= y1 + 1e-9:
        point = px(x0, value)
        painter.drawLine(QPointF(plot.left(), point.y()), QPointF(plot.right(), point.y()))
        painter.setPen(QColor("#334155"))
        painter.drawText(QRectF(0, point.y() - 14, left - 12, 28), Qt.AlignRight | Qt.AlignVCenter, _num(value, 2))
        painter.setPen(QPen(QColor("#cbd5e1"), 1))
        value += step
    xstep = _nice_step(x1 - x0, 10)
    value = math.ceil(x0 / xstep) * xstep
    while value <= x1 + 1e-9:
        point = px(value, y0)
        painter.drawLine(QPointF(point.x(), plot.top()), QPointF(point.x(), plot.bottom()))
        painter.setPen(QColor("#334155"))
        digits = 0 if xstep >= 1 else (1 if xstep >= 0.1 else 2)
        text = x_ticks_fmt(value) if x_ticks_fmt else _num(value, digits, sign=value < 0)
        painter.drawText(QRectF(point.x() - 60, plot.bottom() + 6, 120, 28), Qt.AlignCenter, text)
        painter.setPen(QPen(QColor("#cbd5e1"), 1))
        value += xstep
    painter.setPen(QPen(QColor("#64748b"), 2))
    zero = px(x0, 0.0)
    painter.drawLine(QPointF(plot.left(), zero.y()), QPointF(plot.right(), zero.y()))
    painter.drawRect(plot)

    for item in series:
        points = sorted(item["points"]) if item.get("sort") else item["points"]
        if not points:
            continue
        color = QColor(item["color"])
        if item.get("dots"):
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            for x, y in points:
                painter.drawEllipse(px(x, y), 5, 5)
            painter.setBrush(Qt.NoBrush)
        else:
            path = QPainterPath(px(*points[0]))
            for x, y in points[1:]:
                path.lineTo(px(x, y))
            painter.setPen(QPen(color, 3))
            painter.drawPath(path)

    title_font = QFont(font)
    title_font.setPixelSize(26)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.setPen(QColor("#0f172a"))
    painter.drawText(QRectF(left, 10, plot.width(), 40), Qt.AlignLeft | Qt.AlignVCenter, title)
    painter.setFont(font)
    painter.setPen(QColor("#334155"))
    painter.drawText(QRectF(left, plot.bottom() + 36, plot.width(), 30), Qt.AlignCenter, x_label)
    painter.save()
    painter.translate(24, plot.center().y())
    painter.rotate(-90)
    painter.drawText(QRectF(-plot.height() / 2, -16, plot.height(), 32), Qt.AlignCenter, y_label)
    painter.restore()
    # Легенда.
    x = plot.left()
    y = height - 38
    for item in series:
        painter.fillRect(QRectF(x, y - 4, 28, 8), QColor(item["color"]))
        painter.drawText(QRectF(x + 34, y - 16, 260, 32), Qt.AlignLeft | Qt.AlignVCenter, item["name"])
        x += 40 + painter.fontMetrics().horizontalAdvance(item["name"]) + 30
    painter.end()
    return image


def _nice_step(span: float, count: int) -> float:
    raw = max(span / max(count, 1), 1e-9)
    power = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        if raw <= factor * power:
            return factor * power
    return 10 * power


# ------------------------------------------------------------------ документ

STYLE = """
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 9pt; color: #0f172a; }
h1 { font-size: 17pt; margin: 0 0 4px 0; }
h2 { font-size: 12pt; margin: 14px 0 4px 0; color: #0f172a; }
h3 { font-size: 10pt; margin: 10px 0 3px 0; }
p { margin: 2px 0; }
.soft { color: #64748b; }
table { border-collapse: collapse; }
th { background: #e2e8f0; font-weight: 600; padding: 3px 5px; border: 1px solid #94a3b8; }
td { padding: 3px 5px; border: 1px solid #cbd5e1; }
.big { font-size: 12pt; font-weight: 700; }
"""


def _table(columns: list[tuple[str, str]], rows: list[dict], tone_key: str = "tone") -> str:
    head = "".join(f"<th>{_e(title)}</th>" for _key, title in columns)
    body = []
    for row in rows:
        tone = row.get(tone_key) or "info"
        cells = "".join(f"<td>{_e(row.get(key, ''))}</td>" for key, _title in columns)
        body.append(f"<tr style='background:{TONE_SOFT.get(tone, '#ffffff')}'>{cells}</tr>")
    return f"<table width='100%' cellspacing='0'><tr>{head}</tr>{''.join(body)}</table>"


def _results_table(table: dict | None) -> str:
    """Таблица в формате ResultsTable (columns/rows/cells) - как в окне и мини-приложении."""
    if not table or not table.get("columns"):
        return ""
    columns = [(column["key"], column["title"]) for column in table["columns"]]
    rows = [dict(row.get("cells") or {}, tone=row.get("tone")) for row in table.get("rows") or []]
    title = f"<h3>{_e(table.get('title', ''))}</h3>" if table.get("title") else ""
    if len(columns) > WIDE_COLUMNS:
        # Таблица всех точек на 19 столбцов на листе A4 нечитаема - она есть в архиве прогона.
        return title + (f"<p class='soft'>Таблица на {len(columns)} столбцов, строк: {len(rows)} - в архиве прогона "
                        "(итоги_прогона.txt и журналы плат).</p>")
    return title + _table(columns, rows)


def build_html(data: dict) -> str:
    """HTML отчёта по данным прогона (графики - ссылками chart:*)."""
    parts = [f"<html><head><style>{STYLE}</style></head><body>"]
    parts.append(f"<h1>{_e(data.get('title', 'Отчёт о прогоне в камере'))}</h1>")
    parts.append(f"<p class='soft'>Сформирован {_e(data.get('created', ''))}</p>")

    info = data.get("info") or []
    if info:
        parts.append("<h2>Прогон</h2><table width='100%' cellspacing='0'>"
                     + "".join(f"<tr><td width='32%'><b>{_e(k)}</b></td><td>{_e(v)}</td></tr>" for k, v in info)
                     + "</table>")

    verdict = data.get("verdict")
    if verdict:
        tone = verdict.get("tone", "info")
        parts.append(f"<h2>Вывод</h2><p class='big' style='color:{TONE_COLORS.get(tone, '#0f172a')}'>"
                     f"{_e(verdict.get('title', ''))}</p>")
        for line in verdict.get("lines") or []:
            parts.append(f"<p>• {_e(line)}</p>")

    boards = data.get("boards") or []
    if boards:
        parts.append("<h2>Платы: итог против требования ±1 %</h2>")
        parts.append(_table([("label", "Плата"), ("state", "Итог"), ("worst", "Худшее за прогон"),
                             ("errNow", "Погрешность в конце, %"), ("shiftNow", "Сдвиг от +25 °C в конце, %"),
                             ("profile", "Профиль и калибровка в плате")], boards))
        parts.append("<p class='soft'>Погрешность - уровень прибора минус настоящий (сухая трубка - 0 %, трубка в "
                     "топливе - 100 %). Сдвиг от +25 °C - уровень минус показание этой же платы при +25 °C трубки: "
                     "ошибка от температуры, которую профиль не убрал. До 0,5 % - в норме, 0,5-1 % - на грани, "
                     "больше 1 % - вне допуска.</p>")

    nodes = data.get("nodes") or {}
    if nodes.get("rows"):
        parts.append(f"<h2>{_e(nodes.get('title', 'По узлам температуры'))}</h2>")
        parts.append(_table(nodes["columns"], nodes["rows"]))
        if nodes.get("note"):
            parts.append(f"<p class='soft'>{_e(nodes['note'])}</p>")

    for index, chart in enumerate(data.get("charts") or []):
        parts.append(f"<h2>{_e(chart['title'])}</h2><p><img src='{_e(chart.get('ref') or f'chart{index}.png')}' "
                     "width='560'></p>")
        if chart.get("note"):
            parts.append(f"<p class='soft'>{_e(chart['note'])}</p>")

    for table in data.get("tables") or []:
        parts.append(_results_table(table))

    for board in data.get("results") or []:
        parts.append(f"<h2>Итоги платы {_e(board.get('label', ''))}</h2>")
        parts.append(f"<p style='color:{TONE_COLORS.get(board.get('tone'), '#0f172a')}'><b>{_e(board.get('verdict', ''))}</b></p>")
        summary = board.get("summary") or []
        if summary:
            parts.append(_table([("label", "Показатель"), ("value", "Значение")], summary))
        for table in board.get("tables") or []:
            parts.append(_results_table(table))

    events = data.get("events") or []
    if events:
        parts.append("<h2>События прогона</h2>")
        parts.append(_table([("time", "Время"), ("text", "Событие")],
                            [{"time": item.get("time", ""), "text": item.get("text", ""),
                              "tone": {"bad": "bad", "warn": "warn", "ok": "ok"}.get(item.get("level"), "info")}
                             for item in events]))
    parts.append("</body></html>")
    return "".join(parts)


def write_pdf(path, data: dict) -> str:
    """Пишет отчёт в файл PDF; возвращает путь."""
    _ensure_app()
    from PySide6.QtCore import QMarginsF, QUrl
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

    document = QTextDocument()
    for index, chart in enumerate(data.get("charts") or []):
        chart["ref"] = f"chart{index}.png"
        image = draw_chart(chart["series"], chart.get("chartTitle", ""), chart.get("xLabel", ""),
                           chart.get("yLabel", ""), chart.get("bands", (0.5, 1.0)), x_ticks_fmt=chart.get("xFmt"))
        document.addResource(QTextDocument.ImageResource, QUrl(chart["ref"]), image)
    document.setHtml(build_html(data))
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter)
    writer.setResolution(110)
    writer.setTitle(str(data.get("title", "Отчёт о прогоне")))
    writer.setCreator("tosun-geehy-can-uds-tools")
    document.print_(writer)
    return str(path)
