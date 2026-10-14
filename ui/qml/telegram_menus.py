"""Меню бота кнопками: все отчёты и всё управление без набора команд с «/».

ЗАЧЕМ
Команд у бота-запасной панели много (/status, /steps, /setpoint, /rule, /cmd...),
набирать их и листать список неудобно, особенно с телефона у камеры. Поэтому
всё то же самое доступно кнопками:
- внизу экрана - постоянная клавиатура с главным (статус, шаги, точки,
  камера, прогон, меню, экстренная остановка);
- в сообщении - меню из кнопок, которое листается на месте (одно сообщение
  перерисовывается, чат не засоряется): камера, прогон, шаги, сценарий,
  правила, команды ESPEC, файлы, отчёты.
Где нужно число (своя уставка, температура шага, значение правила), бот
просит прислать его обычным сообщением - без «/».

КАК УСТРОЕНО
Здесь только построение экранов: функция получает снимок состояния (тот же,
что видит мини-приложение) и права человека и возвращает текст и ряды кнопок.
Кнопка - это надпись и «что сделать» (словарь):
- {"t": "menu", "name": ..., "arg": ...} - открыть другой экран;
- {"t": "view", "name": ...} - отчёт с кнопкой «Обновить»;
- {"t": "act", "action": ..., "params": ..., "confirm": ...} - действие
  управления (с подтверждением, если confirm не пустой);
- {"t": "ask", "command": ..., "prefix": ..., "prompt": ...} - попросить ввести
  значение; ответ превращается в текстовую команду бота (те же проверки);
- {"t": "settings"}, {"t": "login"} - настройки уведомлений, вход на сайт.
Выполняет кнопки бот (telegram_bot.py): права проверяются при нажатии, все
действия идут через ту же точку управления программы и пишутся в журнал.
"""

from __future__ import annotations

from html import escape

from ui.qml import telegram_reports as reports

# Постоянная клавиатура внизу экрана: надписи кнопок. Нажатие присылает боту этот текст.
KB_STATUS = "📊 Статус"
KB_STEPS = "🪜 Шаги"
KB_POINTS = "📍 Точки"
KB_EVENTS = "🔔 События"
KB_REPORTS = "📑 Отчёты"
KB_MENU = "☰ Меню"
KB_CAMERA = "🌡 Камера"
KB_RUN = "▶️ Прогон"
KB_ESTOP = "⛔ СТОП камеры"
KB_SETTINGS = "⚙️ Уведомления"

# Отчёты: имя - (заголовок кнопки, функция снимок -> текст).
VIEWS = {
    "status": ("📊 Статус", reports.status_report),
    "steps": ("🪜 Шаги", reports.steps_report),
    "points": ("📍 Точки", reports.points_report),
    "events": ("🔔 События", reports.events_report),
    "log": ("📝 Журнал действий", reports.actions_report),
    "rules": ("⚖ Правила", reports.rules_report),
    "scenarios": ("🧾 Сценарии", reports.scenarios_report),
    "answers": ("💬 Ответы камеры", reports.answers_report),
    "commands": ("🛠 Команды ESPEC", reports.commands_report),
}

# Короткие подписи правил для кнопок: полные - в тексте экрана.
RULE_SHORT = {
    "reach_tolerance_c": "Допуск выхода камеры",
    "settle_min": "Окно устаивания",
    "settle_rate": "Порог скорости",
    "reach_timeout_min": "Ждать камеру до",
    "settle_timeout_min": "Ждать плату до",
    "board_tolerance_c": "Допуск платы",
    "board_max_shift_c": "Сдвиг уставки до",
    "board_attempts": "Попыток доводки",
    "finish_setpoint": "В конце уставка",
    "finish_stop": "В конце остановить",
}
# Выдержка шага кнопками, мин.
HOLD_CHOICES = (0, 5, 15, 30, 60)
# Шаги уставки относительно текущей, °C.
NUDGES = (-5, -1, 1, 5)


def keyboard(can_control: bool) -> dict:
    """Постоянная клавиатура внизу экрана: у наблюдателя - отчёты, у назначенных - ещё управление."""
    if can_control:
        rows = [[KB_STATUS, KB_STEPS, KB_POINTS], [KB_CAMERA, KB_RUN, KB_MENU], [KB_EVENTS, KB_REPORTS, KB_ESTOP]]
    else:
        rows = [[KB_STATUS, KB_STEPS, KB_POINTS], [KB_EVENTS, KB_REPORTS, KB_SETTINGS], [KB_MENU]]
    return {"keyboard": [[{"text": text} for text in row] for row in rows],
            "resize_keyboard": True, "is_persistent": True}


# ------------------------------------------------------------------ мелочи


def _c(value) -> str:
    """Температура для надписи: +25 °C, -40,5 °C."""
    try:
        return f"{float(value):+g} °C".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def _num(value) -> str:
    return f"{float(value):g}".replace(".", ",") if isinstance(value, (int, float)) and not isinstance(value, bool) else "—"


def _menu(name: str, arg=None) -> dict:
    return {"t": "menu", "name": name, "arg": arg}


def _view(name: str) -> dict:
    return {"t": "view", "name": name}


def _act(action: str, params: dict | None = None, confirm: str | None = None, back: tuple | None = None) -> dict:
    return {"t": "act", "action": action, "params": dict(params or {}), "confirm": confirm, "back": back}


def _ask(command: str, prompt: str, prefix: str = "", placeholder: str = "") -> dict:
    return {"t": "ask", "command": command, "prefix": prefix, "prompt": prompt, "placeholder": placeholder}


def _climate(snapshot: dict) -> dict:
    return snapshot.get("climate") or {}


def _control(snapshot: dict) -> dict:
    return _climate(snapshot).get("control") or {}


def _run(snapshot: dict) -> dict:
    return _climate(snapshot).get("run") or {}


def _steps(snapshot: dict) -> list[dict]:
    return [dict(step) for step in _climate(snapshot).get("steps") or []]


def _home() -> tuple:
    return ("☰ Меню", _menu("main"))


def _camera_line(snapshot: dict) -> str:
    climate = _climate(snapshot)
    if not climate.get("connected"):
        return "Камера не подключена к программе."
    return (f"Камера: {climate.get('actualText', '—')}, уставка {climate.get('setpointText', '—')}, "
            f"{climate.get('runningText', '—')}" + ("" if climate.get("ok") else ", НЕТ СВЯЗИ") + ".")


def _run_line(snapshot: dict) -> str:
    run = _run(snapshot)
    if not run.get("active"):
        return "Автопрогон не идёт."
    climate = _climate(snapshot)
    index, steps = climate.get("runIndex", -1), climate.get("steps") or []
    return (f"Прогон: шаг {index + 1} из {len(steps)}, {run.get('stage') or '—'}"
            + (", ПАУЗА" if run.get("paused") else "") + ".")


# ------------------------------------------------------------------ экраны


def build(name: str, arg, snapshot: dict, can_control: bool) -> tuple[str, list[list[tuple[str, dict]]]]:
    """Экран меню: текст (HTML) и ряды кнопок. Неизвестный экран или нет права - главное меню."""
    builders = {"main": _main, "reports": _reports}
    if can_control:
        builders.update({"camera": _camera, "run": _run_menu, "goto": _goto, "scenario": _scenario,
                         "load": _load, "steps_edit": _steps_edit, "step": _step, "rules": _rules,
                         "espec": _espec, "espec_group": _espec_group, "espec_cmd": _espec_cmd, "files": _files})
    builder = builders.get(name, _main)
    return builder(snapshot, arg, can_control)


def view(name: str, snapshot: dict, can_control: bool) -> tuple[str, list[list[tuple[str, dict]]]]:
    """Отчёт с кнопками «Обновить» и «Меню»; у статуса для назначенных - ещё камера и прогон."""
    _title, report = VIEWS.get(name, VIEWS["status"])
    text = report(snapshot) if snapshot else "Данных пока нет: программа у камеры ещё не прислала состояние."
    rows = [[("⟳ Обновить", _view(name)), _home()]]
    if name == "status" and can_control:
        rows.insert(0, [("🌡 Камера", _menu("camera")), ("▶️ Прогон", _menu("run"))])
    if name == "steps" and can_control:
        rows.insert(0, [("✏️ Править шаги", _menu("steps_edit")), ("🎯 К шагу…", _menu("goto"))])
    return text, rows


def _main(snapshot: dict, _arg, can_control: bool):
    text = "<b>Меню</b>\n" + escape(_camera_line(snapshot)) + "\n" + escape(_run_line(snapshot))
    rows = [[("📊 Статус", _view("status")), ("🪜 Шаги", _view("steps")), ("📍 Точки", _view("points"))],
            [("🔔 События", _view("events")), ("📑 Все отчёты", _menu("reports"))]]
    if can_control:
        espec = bool(_control(snapshot).get("espec"))
        rows += [[("🌡 Камера", _menu("camera")), ("▶️ Прогон", _menu("run"))],
                 [("🧾 Сценарий", _menu("scenario")), ("⚖ Правила", _menu("rules"))],
                 ([("🛠 Команды ESPEC", _menu("espec"))] if espec else []) + [("📁 Файлы", _menu("files"))],
                 [("⛔ Экстренная остановка", _act("estop", confirm="Экстренно остановить камеру? Автопрогон тоже остановится."))],
                 [("🔑 Вход на сайт", {"t": "login"}), ("⚙️ Уведомления", {"t": "settings"})]]
    else:
        rows.append([("⚙️ Уведомления", {"t": "settings"})])
        text += "\n\nУправлять камерой могут только админ и те, кому он дал право."
    return text, rows


def _reports(snapshot: dict, _arg, can_control: bool):
    names = list(VIEWS)
    if not _control(snapshot).get("espec"):
        names = [name for name in names if name not in ("answers", "commands")]
    buttons = [(VIEWS[name][0], _view(name)) for name in names]
    rows = [buttons[index:index + 3] for index in range(0, len(buttons), 3)]
    rows.append([_home()])
    return "<b>Отчёты</b>\nВыберите, что показать. У каждого отчёта есть кнопка «Обновить».", rows


def _camera(snapshot: dict, _arg, _can):
    climate = _climate(snapshot)
    control = _control(snapshot)
    limits = control.get("limits") or {}
    active = bool(_run(snapshot).get("active"))
    lines = ["<b>Камера</b>", escape(_camera_line(snapshot)),
             f"Режим: {escape(str((climate.get('espec') or {}).get('modeText') or '—'))}. "
             f"Авария: {escape(str(climate.get('alarmText') or '—'))}.",
             f"Пределы уставки: {_c(limits.get('min'))} … {_c(limits.get('max'))}."]
    if active:
        lines.append("Идёт автопрогон: ручная уставка поставит его на паузу.")
    hold = " Автопрогон встанет на паузу." if active else ""
    rows = []
    modes = control.get("modes") or []
    if modes:
        rows.append([(str(mode.get("title") or mode["key"]),
                      _act("mode", {"mode": mode["key"]}, f"Переключить камеру: «{mode.get('title') or mode['key']}»?",
                           back=("camera", None)))
                     for mode in modes[:4]])
    temps = sorted({float(step["temp"]) for step in _steps(snapshot) if isinstance(step.get("temp"), (int, float))})
    quick = [(f"{temp:+g}", _act("setpoint", {"value": f"{temp:g}"}, f"Задать камере уставку {_c(temp)}?{hold}",
                                 back=("camera", None))) for temp in temps[:8]]
    rows += [quick[index:index + 4] for index in range(0, len(quick), 4)]
    current = climate.get("setpointValue")
    if isinstance(current, (int, float)):
        rows.append([(f"{step:+d}", _act("setpoint", {"value": f"{current + step:g}"},
                                          f"Задать камере уставку {_c(current + step)} (сейчас {_c(current)})?{hold}",
                                          back=("camera", None))) for step in NUDGES])
    rows.append([("✏️ Своя уставка", _ask("/setpoint", "Пришлите уставку камеры, °C. Например: -40", placeholder="-40")),
                 ("↔ Пределы", _ask("/limits", "Пришлите нижний и верхний пределы уставки, °C. Например: -60 110",
                                    placeholder="-60 110"))])
    rows.append([("⛔ Экстренная остановка", _act("estop", confirm="Экстренно остановить камеру? Автопрогон тоже остановится."))])
    rows.append([("⟳ Обновить", _menu("camera")), _home()])
    return "\n".join(lines), rows


def _run_menu(snapshot: dict, _arg, _can):
    run = _run(snapshot)
    auto = run.get("auto") or {}
    control = _control(snapshot)
    lines = ["<b>Прогон</b>", escape(_run_line(snapshot))]
    if run.get("status"):
        lines.append(escape(str(run["status"])))
    if auto.get("progressText"):
        lines.append(escape(str(auto["progressText"])))
    lines.append(f"Пометка точки: {escape(str(control.get('label') or '—'))}")
    rows = []
    if run.get("active"):
        rows.append([("▶ Продолжить", _act("run_resume", back=("run", None))) if run.get("paused")
                     else ("⏸ Пауза", _act("run_pause", back=("run", None))),
                     ("⏭ Следующий шаг", _act("step_next", confirm="Перейти к следующему шагу, не дожидаясь точек текущего?",
                                              back=("run", None)))])
        rows.append([("📍 Записать точку", _act("capture", confirm="Записать точку сейчас по текущим средним прибора?",
                                                back=("run", None))),
                     ("🎯 К шагу…", _menu("goto"))])
        if run.get("operator"):
            rows.append([("🔁 Эталоны переключены", _act("run_operator", back=("run", None)))])
        rows.append([("⏹ Остановить прогон", _act("run_stop", confirm="Остановить автопрогон? Уставка камеры останется как есть.",
                                                  back=("run", None)))])
    else:
        resume = auto.get("resume")
        if resume:
            lines.append("⚠️ " + escape(str(resume.get("text") or "Есть прерванный прогон.")))
            rows.append([("↩ Продолжить прерванный", _act("resume_saved", confirm="Продолжить прерванный прогон?",
                                                         back=("run", None))),
                         ("🗑 Забыть", _act("discard_saved", confirm="Забыть прерванный прогон? Продолжить его будет нельзя.",
                                           back=("run", None)))])
        rows.append([("▶ Запустить прогон", _act("run_start", confirm="Запустить автопрогон по текущему сценарию?",
                                                 back=("run", None)))])
        rows.append([("📍 Записать точку", _act("capture", confirm="Записать точку сейчас по текущим средним прибора?",
                                                back=("run", None)))])
    rows.append([("🏷 Пометка точки", _ask("/label", "Пришлите пометку точки. Например: 0/0", placeholder="0/0")),
                 ("🪜 Шаги", _view("steps"))])
    rows.append([("⟳ Обновить", _menu("run")), _home()])
    return "\n".join(lines), rows


def _goto(snapshot: dict, _arg, _can):
    steps = _steps(snapshot)
    index = _climate(snapshot).get("runIndex", -1)
    rows = []
    for number, step in enumerate(steps):
        mark = "▶ " if number == index else ""
        rows.append((f"{mark}{number + 1} · {_c(step.get('temp'))}",
                     _act("step_goto", {"index": number},
                          f"Перейти к шагу {number + 1} ({_c(step.get('temp'))})? Точки текущего шага сняты не будут.",
                          back=("run", None))))
    grid = [rows[start:start + 3] for start in range(0, len(rows), 3)]
    grid.append([("← Прогон", _menu("run")), _home()])
    text = "<b>Перейти к шагу</b>\n" + ("Прогон не идёт: переход - только во время прогона." if index < 0
                                        else f"Сейчас шаг {index + 1}. Выберите, к какому перейти.")
    return text, grid


def _scenario(snapshot: dict, _arg, _can):
    climate = _climate(snapshot)
    text = reports.scenarios_report(snapshot) + "\n" + escape(str(climate.get("scenario") or ""))
    rows = [[("💾 Сохранить", _act("scenario_save", back=("scenario", None))), ("📂 Загрузить…", _menu("load"))],
            [("✏️ Шаги", _menu("steps_edit")), ("⚖ Правила", _menu("rules"))],
            [("🆕 Новый: цикл платы", _act("scenario_new", {"kind": "board_cycle"},
                                           "Создать новый сценарий «цикл платы»? Несохранённые изменения текущего пропадут.",
                                           back=("scenario", None))),
             ("🆕 Новый: пустой", _act("scenario_new", {"kind": "empty"},
                                       "Создать пустой сценарий? Несохранённые изменения текущего пропадут.",
                                       back=("scenario", None)))],
            [("⟳ Обновить", _menu("scenario")), _home()]]
    return text, rows


def _load(snapshot: dict, _arg, _can):
    files = _control(snapshot).get("scenarioFiles") or []
    rows = [[(f"📄 {item['name']}"[:60], _act("scenario_load", {"file": item["file"]},
                                              f"Загрузить сценарий «{item['name']}»?", back=("scenario", None)))]
            for item in files[:20]]
    rows.append([("← Сценарий", _menu("scenario")), _home()])
    return ("<b>Загрузить сценарий</b>\n" + ("Выберите файл." if files else "Сохранённых сценариев нет.")
            + "\nВо время прогона загрузить другой сценарий нельзя."), rows


def _steps_edit(snapshot: dict, _arg, _can):
    steps = _steps(snapshot)
    index = _climate(snapshot).get("runIndex", -1)
    buttons = [(("▶ " if number == index else "✏️ ") + f"{number + 1} · {_c(step.get('temp'))}", _menu("step", number))
               for number, step in enumerate(steps)]
    rows = [buttons[start:start + 3] for start in range(0, len(buttons), 3)]
    rows.append([("➕ Добавить шаг", _ask("/addstep", "Пришлите температуру нового шага и выдержку, мин "
                                                      "(выдержку можно не писать). Например: -40 15", placeholder="-40 15"))])
    rows.append([("← Сценарий", _menu("scenario")), _home()])
    return reports.steps_report(snapshot) + "\nВыберите шаг, чтобы изменить его.", rows


def _step(snapshot: dict, arg, _can):
    steps = _steps(snapshot)
    try:
        number = int(arg)
    except (TypeError, ValueError):
        number = -1
    if not 0 <= number < len(steps):
        return _steps_edit(snapshot, None, _can)
    step = steps[number]
    index = _climate(snapshot).get("runIndex", -1)
    state = ("пройден" if 0 <= number < index else "идёт сейчас" if number == index else "впереди") if index >= 0 else ""
    capture = step.get("capture", True)
    text = (f"<b>Шаг {number + 1}</b>" + (f" · {state}" if state else "") + "\n"
            f"Температура: {_c(step.get('temp'))}\nВыдержка после устаивания: {_num(step.get('hold_min') or 0)} мин\n"
            f"Снимать точку: {'да' if capture else 'нет'}")
    back = ("step", number)

    def changed(**fields):
        new = [dict(item) for item in steps]
        new[number].update(fields)
        return {"steps": new}

    hold = [(("✓ " if float(step.get("hold_min") or 0) == minutes else "") + f"{minutes} мин",
             _act("scenario_steps", changed(hold_min=float(minutes)), back=back)) for minutes in HOLD_CHOICES]
    rows = [[("🌡 Температура…", _ask("/step", f"Пришлите температуру шага {number + 1}, °C (и выдержку через пробел). "
                                               "Например: -40 15", prefix=str(number + 1), placeholder="-40"))],
            hold,
            [(("✓ " if capture else "✗ ") + "Снимать точку", _act("scenario_steps", changed(capture=not capture), back=back)),
             ("🗑 Удалить шаг", _act("scenario_steps", {"steps": [item for pos, item in enumerate(steps) if pos != number]},
                                    f"Удалить шаг {number + 1} ({_c(step.get('temp'))})?", back=("steps_edit", None)))],
            [("← Шаги", _menu("steps_edit")), _home()]]
    return text, rows


def _rules(snapshot: dict, _arg, _can):
    rules = _control(snapshot).get("rules") or []
    rows = []
    for rule in rules:
        key, value, unit = rule["key"], rule.get("value"), rule.get("unit", "")
        short = RULE_SHORT.get(key, key)
        if isinstance(value, bool) or key == "finish_stop":
            rows.append([(("✓ " if value else "✗ ") + short,
                          _act("scenario_rules", {key: "нет" if value else "да"}, back=("rules", None)))])
            continue
        shown = _num(value) + (f" {unit}" if unit and value is not None else "")
        hint = " (нет - не менять уставку в конце)" if key == "finish_setpoint" else ""
        rows.append([(f"{short}: {shown}",
                      _ask("/rule", f"Пришлите новое значение: {rule.get('title', short)}, {unit or 'число'}{hint}. "
                                    f"Сейчас: {shown}.", prefix=key, placeholder=_num(value)))])
    rows.append([("⟳ Обновить", _menu("rules")), ("← Сценарий", _menu("scenario")), _home()])
    return reports.rules_report(snapshot) + "\nНажмите правило, чтобы изменить. Действует и на идущий прогон.", rows


def _espec(snapshot: dict, _arg, _can):
    commands = _control(snapshot).get("commands") or []
    groups = list(dict.fromkeys(item["group"] for item in commands))
    rows = [[(group, _menu("espec_group", group))] for group in groups]
    rows.append([("💬 Ответы камеры", _view("answers")), _home()])
    return ("<b>Команды камеры ESPEC</b>\n" + ("Выберите группу." if groups
                                               else "Команды доступны, когда подключена камера ESPEC.")), rows


def _espec_group(snapshot: dict, group, _can):
    commands = [item for item in _control(snapshot).get("commands") or [] if item["group"] == group]
    rows = [[(("⚠ " if item.get("danger") else "") + str(item.get("title") or item["key"])[:60],
              _menu("espec_cmd", item["key"]))] for item in commands]
    rows.append([("← Группы", _menu("espec")), _home()])
    return f"<b>ESPEC · {escape(str(group))}</b>\nВыберите команду.", rows


def _espec_cmd(snapshot: dict, key, _can):
    item = next((entry for entry in _control(snapshot).get("commands") or [] if entry["key"] == key), None)
    if item is None:
        return _espec(snapshot, None, _can)
    params = item.get("params") or []
    defaults = {param["name"]: str(param.get("default", "")) for param in params}
    lines = [f"<b>{escape(str(item.get('title') or key))}</b>"]
    if item.get("hint"):
        lines.append(escape(str(item["hint"])))
    for param in params:
        lines.append(f"• {escape(param['name'])} - {escape(str(param.get('label', '')))}, "
                     f"по умолчанию {escape(str(param.get('default', '')))}")
    if item.get("danger"):
        lines.append("⚠ Команда меняет работу камеры.")
    shown = " ".join(f"{name}={value}" for name, value in defaults.items())
    confirm = f"Отправить камере «{item.get('title') or key}»" + (f" ({shown})" if shown else "") + "?"
    send = _act("espec_command", {"key": key, "values": defaults},
                confirm if (item.get("danger") or params) else None, back=("espec_cmd", key))
    rows = [[("▶ Отправить" + (" (по умолчанию)" if params else ""), send)]]
    if params:
        rows.append([("✏️ Свои параметры", _ask("/cmd", "Пришлите параметры через пробел в виде имя=значение. "
                                                         f"Например: {shown}", prefix=key, placeholder=shown))])
    rows.append([("💬 Ответы камеры", _view("answers")), ("← Группа", _menu("espec_group", item["group"]))])
    return "\n".join(lines), rows


def _files(_snapshot: dict, _arg, _can):
    rows = [[("📄 Отчёт диагностики", _act("send_file", {"which": "report"}))],
            [("📒 Журнал точек", _act("send_file", {"which": "journal"}))],
            [("📈 Ход прогона (CSV)", _act("send_file", {"which": "trace"}))],
            [_home()]]
    return "<b>Файлы в этот чат</b>\nОтчёт диагностики, журнал точек и ход прогона по времени.", rows
