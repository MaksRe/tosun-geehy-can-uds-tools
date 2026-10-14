"""Отчёты бота наблюдения: состояние, шаги, точки, события, действия, правила - аккуратными таблицами.

ЗАЧЕМ
Если сайт и мини-приложение недоступны (кончился лимит туннеля, нет интернета у
туннеля), бот остаётся: он сам ходит в Telegram и от туннеля не зависит. Поэтому
всё важное бот показывает сам - коротко и так, чтобы колонки не съезжали:
таблицы - в моноширинном блоке <pre>, строки не шире ~34 знаков (экран телефона).

Все функции берут снимок состояния (тот же, что видит мини-приложение) и
возвращают текст в разметке HTML Telegram. Снимок собирает программа раз в
секунду, бот только читает его.
"""

from __future__ import annotations

from html import escape

# Ширина строки таблицы: столько знаков моноширинного шрифта помещается на экране телефона.
WIDTH = 34
# Предел длины сообщения Telegram - 4096 знаков; запас на разметку.
MAX_TEXT = 3900


def _cell(value) -> str:
    return "—" if value is None or value == "" else str(value)


def table(headers: list[str], rows: list[list], right: tuple[int, ...] = ()) -> str:
    """Таблица для моноширинного блока: колонки по ширине, числа - вправо."""
    rows = [[_cell(cell) for cell in row] for row in rows]
    widths = [max(len(str(item)) for item in column) for column in zip(headers, *rows)] if rows else [len(h) for h in headers]

    def line(cells):
        return " ".join(str(cell).rjust(width) if index in right else str(cell).ljust(width)
                        for index, (cell, width) in enumerate(zip(cells, widths))).rstrip()
    out = [line(headers), "─" * min(WIDTH, max(len(line(headers)), 10))]
    out += [line(row) for row in rows]
    return "\n".join(out)


def pre(text: str) -> str:
    return f"<pre>{escape(text)}</pre>"


def _clip(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "\n…"


def _pairs(rows: list[tuple[str, str]]) -> str:
    """Два столбца «что - значение» для моноширинного блока."""
    width = max((len(name) for name, _value in rows), default=0)
    return "\n".join(f"{name.ljust(width)}  {_cell(value)}" for name, value in rows)


def status_report(snapshot: dict) -> str:
    """Что сейчас: камера, плата, контуры, прогон, проблемы."""
    climate = snapshot.get("climate") or {}
    run = climate.get("run") or {}
    auto = run.get("auto") or {}
    live = snapshot.get("live") or {}
    espec = climate.get("espec") or {}
    stability = snapshot.get("stability") or {}
    journal = snapshot.get("run") or {}
    rows = []
    if climate.get("connected"):
        chamber = (climate.get("chamber") or {}).get("name", "камера")
        rows += [("Камера", f"{chamber}, {'на связи' if climate.get('ok') else 'НЕТ СВЯЗИ'}"),
                 ("Воздух", climate.get("actualText")),
                 ("Уставка", climate.get("setpointText")),
                 ("Режим", f"{climate.get('runningText', '—')}, {espec.get('modeText', '—')}"),
                 ("Авария", climate.get("alarmText"))]
    else:
        rows.append(("Камера", "не подключена к программе"))
    board = live.get("boardTemp") or {}
    rows += [("Плата", f"{board.get('now') or '—'} (ср. {board.get('avg') or '—'})"),
             ("Топливо", (live.get("fuelTemp") or {}).get("now")),
             ("Основной", (live.get("main") or {}).get("avg") or (live.get("main") or {}).get("now")),
             ("Вид топл.", (live.get("media") or {}).get("avg") or (live.get("media") or {}).get("now"))]
    if run.get("active"):
        index = climate.get("runIndex", -1)
        steps = climate.get("steps") or []
        rows += [("Прогон", f"шаг {index + 1}/{len(steps)}" + (", ПАУЗА" if run.get("paused") else "")),
                 ("Этап", run.get("stage")),
                 ("Время", (auto.get("progressText") or "").split("·", 1)[-1].strip())]
    else:
        rows.append(("Прогон", "не идёт"))
    rows.append(("Точек", journal.get("points", 0)))
    text = f"<b>Прогон в камере</b> · {escape(str(snapshot.get('time', '')))}\n" + pre(_pairs(rows))
    lines = []
    if stability.get("text"):
        lines.append(("✅ " if stability.get("ok") else "⏳ ") + str(stability["text"]))
    if run.get("active") and run.get("status"):
        lines.append(str(run["status"]))
    for alert in auto.get("alerts") or []:
        lines.append(("❌ " if alert.get("level") == "bad" else "⚠️ ") + str(alert.get("text", "")))
    if lines:
        text += "\n" + escape("\n".join(lines))
    return _clip(text)


def steps_report(snapshot: dict) -> str:
    """Шаги сценария: что пройдено, что идёт, что впереди."""
    climate = snapshot.get("climate") or {}
    steps = climate.get("steps") or []
    index = climate.get("runIndex", -1)
    if not steps:
        return "Шагов нет: сценарий пустой."
    rows = []
    for number, step in enumerate(steps):
        state = "пройден" if 0 <= number < index else ("ИДЁТ" if number == index else "")
        temp = step.get("temp")
        rows.append([number + 1, f"{temp:+g}" if isinstance(temp, (int, float)) else temp,
                     f"{step.get('hold_min') or 0:g}", "да" if step.get("capture", True) else "—", state])
    name = climate.get("scenarioName") or "сценарий"
    head = f"<b>Шаги</b> · {escape(name)}" + ("" if index < 0 else f" · идёт {index + 1} из {len(steps)}")
    return _clip(head + "\n" + pre(table(["№", "°C", "выд,мин", "точка", "статус"], rows, right=(0, 1, 2))))


def points_report(snapshot: dict) -> str:
    """Последние точки журнала прогона."""
    journal = snapshot.get("run") or {}
    rows = [[row.get("time", ""), row.get("boardTemp", ""), row.get("node", ""), row.get("main", ""), row.get("media", "")]
            for row in (journal.get("rows") or [])[:15]]
    head = f"<b>Точки</b> · всего {journal.get('points', 0)}" + (f" · {escape(journal['file'])}" if journal.get("file") else "")
    if not rows:
        return head + "\nТочек пока нет."
    return _clip(head + "\n" + pre(table(["время", "плата", "узел", "осн", "вид"], rows, right=(1, 3, 4))))


def events_report(snapshot: dict, count: int = 15) -> str:
    """Последние события программы."""
    events = (snapshot.get("events") or [])[:count]
    if not events:
        return "Событий пока нет."
    mark = {"bad": "❌", "warn": "⚠️", "ok": "✅"}
    return _clip("<b>События</b>\n" + "\n".join(
        f"<code>{escape(str(item.get('time', '')))}</code> {mark.get(item.get('level'), '•')} {escape(str(item.get('text', '')))}"
        for item in events))


def actions_report(snapshot: dict, count: int = 12) -> str:
    """Журнал действий: кто и что менял."""
    log = (((snapshot.get("climate") or {}).get("control") or {}).get("log") or [])[:count]
    if not log:
        return "Действий управления пока не было."
    lines = []
    for item in log:
        details = f": {item['details']}" if item.get("details") else ""
        lines.append(f"<code>{escape(str(item.get('time', ''))[-8:])}</code> <b>{escape(str(item.get('who', '')))}</b> "
                     f"({escape(str(item.get('channel', '')))}) - {escape(str(item.get('action', '')))}{escape(details)}"
                     f"\n   {'✅' if item.get('ok') else '❌'} {escape(str(item.get('result', '')))}")
    return _clip("<b>Журнал действий</b>\n" + "\n".join(lines))


def rules_report(snapshot: dict) -> str:
    """Правила сценария с ключами для команды /rule."""
    rules = ((snapshot.get("climate") or {}).get("control") or {}).get("rules") or []
    if not rules:
        return "Правил нет."
    rows = []
    for rule in rules:
        value = rule.get("value")
        shown = ("да" if value else "нет") if isinstance(value, bool) else (f"{value:g}" if isinstance(value, (int, float)) else _cell(value))
        rows.append(f"{rule['key']} = {shown} {rule.get('unit', '')}".rstrip())
        rows.append(f"  {rule.get('title', '')}")
    return _clip("<b>Правила сценария</b> · изменить: /rule ключ значение\n" + pre("\n".join(rows)))


def scenarios_report(snapshot: dict) -> str:
    """Сохранённые сценарии с номерами для /load."""
    control = (snapshot.get("climate") or {}).get("control") or {}
    files = control.get("scenarioFiles") or []
    current = control.get("scenarioFile") or "не сохранён в файл"
    text = f"<b>Сценарии</b> · текущий: {escape(current)}" + (" (есть изменения)" if control.get("scenarioDirty") else "")
    if not files:
        return text + "\nСохранённых сценариев нет."
    return _clip(text + "\n" + pre("\n".join(f"{number}. {item['name']}" for number, item in enumerate(files, start=1)))
                 + "\nЗагрузить: /load номер · сохранить текущий: /save")


def commands_report(snapshot: dict) -> str:
    """Каталог команд камеры ESPEC с ключами для /cmd."""
    commands = ((snapshot.get("climate") or {}).get("control") or {}).get("commands") or []
    if not commands:
        return "Команды ESPEC доступны, когда подключена камера ESPEC."
    lines, group = [], ""
    for item in commands:
        if item["group"] != group:
            group = item["group"]
            lines.append(f"[{group}]")
        params = " ".join(f"{param['name']}={param.get('default', '')}" for param in item.get("params") or [])
        lines.append(f"{item['key']}{' ' + params if params else ''}{' ⚠' if item.get('danger') else ''}")
    return _clip("<b>Команды ESPEC</b> · /cmd ключ имя=значение\n" + pre("\n".join(lines)))


def answers_report(snapshot: dict) -> str:
    """Последние обмены с камерой: что отправлено и что она ответила."""
    answers = ((snapshot.get("climate") or {}).get("control") or {}).get("answers") or []
    if not answers:
        return "Обменов с камерой пока нет."
    lines = [f"{item.get('time', '')} {item.get('sent', '')}\n  → {item.get('answer', '')}"
             + (f"\n  ({item['explain']})" if item.get("explain") else "") for item in answers[:10]]
    return _clip("<b>Ответы камеры</b>\n" + pre("\n".join(lines)))
