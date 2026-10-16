"""Сценарий автоматического прогона в климатической камере: что, в каком порядке и как.

ЗАЧЕМ
Раньше прогон задавался списком температур и общими настройками: все узлы
проходились по одним правилам, а режим расчёта и пометка жили в другом окне.
Сценарий собирает всё в одно и хранится файлом: его можно составить один раз,
сохранить под понятным именем, загрузить на другом компьютере и быть уверенным,
что испытание пройдёт одинаково.

ЧТО В СЦЕНАРИИ
- Общее: режим «только плата» и модель ухода, пометки (что подключено),
  автозапись профиля, критерии по умолчанию (выход на уставку, устойчивость
  платы), когда предупреждать о зависании, что делать в конце.
- Шаги по порядку. У шага своя температура и, по желанию, свои: выдержка после
  того, как плата устоялась; окно и скорость устойчивости; допуск выхода на
  уставку; снимать ли точку (шаг без точки - например, прогрев перед циклом);
  примечание. Пустое значение шага означает «как в общем».

ФАЙЛ
JSON в UTF-8: {"format": "climate_scenario", "version": 1, ...}. Значения
проверяются при чтении: неверное поле заменяется значением по умолчанию, а
причина попадает в список замечаний - испорченный файл не роняет программу.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

FORMAT = "climate_scenario"
# Версия 2: новые значения по умолчанию (плата в коробке) и порядок шагов цикла платы.
VERSION = 2

# Модели ухода при одной ёмкости: как в расчёте таблиц (chamber_fit.SINGLE_MODELS).
SINGLE_MODELS = ("растяжение", "сдвиг")

# Общие значения по умолчанию. Подобраны по стенду 13-14.10.2026 (плата в своей коробке):
# у коробки медленный «хвост» устаивания, поэтому окно длиннее и порог скорости строже -
# меньше ложных «устоялась» и лишних доводок; на холоде плате нужен воздух на 17-20 °C
# холоднее шага, поэтому сдвиг до 25 °C и четыре попытки (запас на первый холодный шаг).
DEFAULTS = {
    "reach_tolerance_c": 1.0,
    "settle_min": 12.0,
    "settle_rate": 0.03,
    "reach_timeout_min": 120.0,
    "settle_timeout_min": 180.0,
    # Доводка платы: плата должна устояться у температуры шага с этим допуском; если нет -
    # уставка камеры сдвигается не дальше чем на board_max_shift_c, не больше board_attempts раз.
    "board_tolerance_c": 1.0,
    "board_max_shift_c": 25.0,
    "board_attempts": 4.0,
}
# Значения по умолчанию версии 1: в сценарии прежней версии такие значения заменяются новыми,
# а заданные человеком иначе - остаются.
DEFAULTS_V1 = {"settle_min": 5.0, "settle_rate": 0.05, "board_max_shift_c": 20.0, "board_attempts": 3.0}
# Как назвать эти правила человеку в замечании об обновлении.
DEFAULTS_V1_TITLES = {"settle_min": "окно устаивания {:g} мин", "settle_rate": "порог {:g} °C/мин",
                      "board_max_shift_c": "сдвиг уставки до {:g} °C", "board_attempts": "попыток доводки {:g}"}

# Поля шага, которые могут переопределять общие: (ключ, наименьшее, наибольшее).
STEP_LIMITS = {
    "hold_min": (0.0, 10000.0),
    "settle_min": (0.5, 600.0),
    "settle_rate": (0.001, 5.0),
    "reach_tolerance_c": (0.1, 20.0),
}
GENERAL_LIMITS = {
    "reach_tolerance_c": (0.1, 20.0),
    "settle_min": (0.5, 600.0),
    "settle_rate": (0.001, 5.0),
    "reach_timeout_min": (1.0, 10000.0),
    "settle_timeout_min": (1.0, 10000.0),
    "board_tolerance_c": (0.2, 10.0),
    "board_max_shift_c": (0.0, 30.0),
    "board_attempts": (0.0, 10.0),
}
TEMP_LIMITS = (-100.0, 200.0)

BOARD_CYCLE_NAME = "Испытание платы, один цикл"
# Пометка точки одной платы: эталоны не подключены (основной 0 / вид топлива 0).
BOARD_LABEL = "0/0"
# Порядок цикла: к -40 прогон подходит уже с холодной точкой от -20, и упреждение уставки для -40
# точное (модель «воздух -> плата» на холоде иная, чем на тепле). Камера проходит те же 190 °C,
# что и при прежнем порядке 25, -40, -20, ...
BOARD_CYCLE_TEMPS = (25.0, -20.0, -40.0, 0.0, 50.0, 70.0, 85.0)
BOARD_CYCLE_TEMPS_V1 = (25.0, -40.0, -20.0, 0.0, 50.0, 70.0, 85.0)
# Выдержка на крайних шагах, мин: запас на медленный «хвост» платы в коробке.
BOARD_CYCLE_HOLD = {-40.0: 15.0, 85.0: 15.0}


def new_step(temp: float = 25.0) -> dict:
    """Шаг с общими правилами: только температура, остальное «как в общем»."""
    return {"temp": float(temp), "hold_min": 0.0, "settle_min": None, "settle_rate": None,
            "reach_tolerance_c": None, "capture": True, "note": ""}


def empty_scenario(name: str = "Новый сценарий") -> dict:
    """Пустой сценарий: общие значения по умолчанию, один шаг +25 °C."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "name": name,
        "description": "",
        "board_only": False,
        "single_model": SINGLE_MODELS[0],
        "labels": [],
        "auto_write": True,
        **DEFAULTS,
        "finish_setpoint": 25.0,
        "finish_stop": False,
        "steps": [new_step(25.0)],
    }


def board_cycle_scenario() -> dict:
    """Наш случай: одна плата на своих ёмкостях, все 7 узлов прибора за один проход.

    Первым опорный +25 °C, затем -20 и -40, потом вверх до +85, в конце камера
    возвращается к +25 °C. Пометка «0/0»: к входам ничего не подключено.
    """
    scenario = empty_scenario(BOARD_CYCLE_NAME)
    scenario["description"] = ("Одна плата, только её собственные ёмкости, один проход по всем 7 узлам "
                               "прибора. Опорный узел +25 °C первым.")
    scenario["board_only"] = True
    scenario["labels"] = ["0/0"]
    scenario["steps"] = _board_cycle_steps()
    return scenario


def _board_cycle_steps() -> list[dict]:
    """Шаги цикла платы: порядок, выдержка на крайних шагах, примечания."""
    steps = [new_step(temp) for temp in BOARD_CYCLE_TEMPS]
    for step in steps:
        step["hold_min"] = BOARD_CYCLE_HOLD.get(step["temp"], 0.0)
    steps[0]["note"] = "опорная точка"
    return steps


def _upgrade_v1(scenario: dict, problems: list):
    """Сценарий версии 1: старые значения по умолчанию -> новые; цикл платы как был - в новом порядке.

    Значения, которые человек задал сам (не равные старым по умолчанию), и свои шаги не меняются.
    """
    changed = [key for key, old in DEFAULTS_V1.items() if scenario.get(key) == old]
    for key in changed:
        scenario[key] = DEFAULTS[key]
    steps = scenario.get("steps") or []
    untouched = (tuple(step["temp"] for step in steps) == BOARD_CYCLE_TEMPS_V1
                 and all(not step["hold_min"] and step["capture"] and step["settle_min"] is None
                         and step["settle_rate"] is None and step["reach_tolerance_c"] is None for step in steps))
    if untouched:
        scenario["steps"] = _board_cycle_steps()
    if changed or untouched:
        problems.append("сценарий прежней версии обновлён до новых значений по умолчанию"
                        + (": " + ", ".join(DEFAULTS_V1_TITLES[key].format(DEFAULTS[key]).replace(".", ",")
                                   for key in changed)
                           if changed else "")
                        + ("; шаги цикла платы - в порядке 25, -20, -40, 0, 50, 70, 85 с выдержкой 15 мин "
                           "на -40 и +85" if untouched else ""))


def from_settings(settings: dict, board_only: bool = False, single_model: str = "", label: str = "",
                  auto_write: bool = True) -> dict:
    """Сценарий из прежних настроек прогона: так ничего не теряется при переходе на сценарии."""
    scenario = empty_scenario("Из настроек прогона")
    try:
        temps = [float(part) for part in re.split(r"[;,\s]+", str(settings.get("run_nodes", "")).replace("°", "")
                                                 .replace("C", "").replace("С", "")) if part]
    except ValueError:
        temps = []
    if temps:
        scenario["steps"] = [new_step(temp) for temp in temps]
    labels = [part.strip() for part in str(settings.get("run_labels", "")).split(";") if part.strip()]
    scenario["labels"] = labels or ([label] if label else [])
    for key in DEFAULTS:
        if key in settings:
            scenario[key] = settings[key]
    scenario["finish_setpoint"] = settings.get("finish_setpoint", 25.0)
    scenario["finish_stop"] = bool(settings.get("finish_stop", False))
    scenario["board_only"] = bool(board_only)
    if single_model in SINGLE_MODELS:
        scenario["single_model"] = single_model
    scenario["auto_write"] = bool(auto_write)
    return normalize(scenario)[0]


def _number(value, low: float, high: float, name: str, problems: list, default, allow_none: bool = False):
    """Число в пределах или значение по умолчанию с замечанием. Пустое у шага - «как в общем»."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_none:
            return None
        problems.append(f"{name}: не задано, взято {default}")
        return default
    try:
        number = float(str(value).replace(",", "."))
    except ValueError:
        problems.append(f"{name}: «{value}» не число, взято {default}")
        return default
    if not (low <= number <= high):
        problems.append(f"{name}: {number:g} вне пределов {low:g}...{high:g}, взято {default}")
        return default
    return number


def normalize(data) -> tuple[dict, list[str]]:
    """Проверенный сценарий и замечания. Неверное поле заменяется значением по умолчанию."""
    problems: list[str] = []
    base = empty_scenario()
    if not isinstance(data, dict):
        return base, ["сценарий не прочитан: ожидался объект JSON"]
    if data.get("format", FORMAT) != FORMAT:
        problems.append(f"файл не похож на сценарий прогона (format={data.get('format')!r})")
    scenario = copy.deepcopy(base)
    scenario["name"] = str(data.get("name") or base["name"]).strip()[:120]
    scenario["description"] = str(data.get("description") or "").strip()[:2000]
    scenario["board_only"] = bool(data.get("board_only", False))
    model = str(data.get("single_model") or SINGLE_MODELS[0])
    if model not in SINGLE_MODELS:
        problems.append(f"модель ухода «{model}» неизвестна, взято «{SINGLE_MODELS[0]}»")
        model = SINGLE_MODELS[0]
    scenario["single_model"] = model
    labels = data.get("labels") or []
    if isinstance(labels, str):
        labels = labels.split(";")
    scenario["labels"] = [str(label).strip() for label in labels if str(label).strip()][:20]
    if scenario["board_only"]:
        # Одна плата на своих ёмкостях: к входам ничего не подключено, пометка всегда одна - «0/0».
        scenario["labels"] = [BOARD_LABEL]
    scenario["auto_write"] = bool(data.get("auto_write", True))
    for key, (low, high) in GENERAL_LIMITS.items():
        scenario[key] = _number(data.get(key, DEFAULTS[key]), low, high, key, problems, DEFAULTS[key])
    scenario["finish_setpoint"] = _number(data.get("finish_setpoint", 25.0), *TEMP_LIMITS, "в конце, °C", problems,
                                          25.0, allow_none=True)
    scenario["finish_stop"] = bool(data.get("finish_stop", False))

    steps = []
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        problems.append("в сценарии нет шагов")
        raw_steps = []
    for index, raw in enumerate(raw_steps[:100], start=1):
        if not isinstance(raw, dict):
            problems.append(f"шаг {index}: не объект, пропущен")
            continue
        temp = _number(raw.get("temp"), *TEMP_LIMITS, f"шаг {index}, температура", problems, None)
        if temp is None:
            continue
        step = new_step(temp)
        step["hold_min"] = _number(raw.get("hold_min", 0.0), *STEP_LIMITS["hold_min"], f"шаг {index}, выдержка",
                                   problems, 0.0, allow_none=True) or 0.0
        for key in ("settle_min", "settle_rate", "reach_tolerance_c"):
            step[key] = _number(raw.get(key), *STEP_LIMITS[key], f"шаг {index}, {key}", problems, None,
                                allow_none=True)
        step["capture"] = bool(raw.get("capture", True))
        step["note"] = str(raw.get("note") or "").strip()[:200]
        steps.append(step)
    scenario["steps"] = steps
    if not steps:
        problems.append("ни одного годного шага: добавьте хотя бы один")
    elif not any(step["capture"] for step in steps):
        problems.append("ни в одном шаге не снимается точка")
    try:
        version = int(data.get("version", VERSION))
    except (TypeError, ValueError):
        version = VERSION
    if version < 2:
        _upgrade_v1(scenario, problems)
    return scenario, problems


def step_value(scenario: dict, step: dict, key: str):
    """Значение шага, а если оно пустое - общее значение сценария."""
    value = step.get(key) if step else None
    return scenario.get(key, DEFAULTS.get(key)) if value is None else value


def load(path) -> tuple[dict, list[str]]:
    """Читает сценарий из файла. Ошибка чтения - исключение OSError или ValueError."""
    text = Path(path).read_text(encoding="utf-8")
    return normalize(json.loads(text))


def save(scenario: dict, path) -> Path:
    """Пишет сценарий в файл UTF-8 через временный файл: оборванная запись не портит прежний."""
    target = Path(path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    clean, _problems = normalize(scenario)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def file_name(name: str) -> str:
    """Имя файла из названия сценария: без знаков, которые не любит Windows."""
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", str(name)).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return (cleaned or "сценарий")[:80] + ".json"


def summary(scenario: dict) -> str:
    """Сценарий одной строкой: шаги, точки, режим."""
    steps = scenario.get("steps") or []
    temps = " → ".join(f"{step['temp']:+g}" for step in steps)
    points = sum(1 for step in steps if step.get("capture"))
    mode = "только плата" if scenario.get("board_only") else "эталоны и трубка"
    return f"{len(steps)} шагов ({temps} °C), точки в {points}, {mode}"


# Поля для журнала изменений: ключ - как назвать по-русски, единицы.
DIFF_GENERAL = (
    ("name", "название", ""),
    ("board_only", "одна плата", ""),
    ("single_model", "уход платы", ""),
    ("labels", "пометки", ""),
    ("auto_write", "запись профиля", ""),
    ("reach_tolerance_c", "допуск выхода на уставку", " °C"),
    ("settle_min", "окно устойчивости", " мин"),
    ("settle_rate", "скорость устойчивости", " °C/мин"),
    ("reach_timeout_min", "предупредить, если не вышла на уставку за", " мин"),
    ("settle_timeout_min", "предупредить, если не устоялась за", " мин"),
    ("board_tolerance_c", "допуск платы к шагу", " °C"),
    ("board_max_shift_c", "наибольший сдвиг уставки при доводке", " °C"),
    ("board_attempts", "попыток доводки", ""),
    ("finish_setpoint", "уставка в конце", " °C"),
    ("finish_stop", "остановить камеру в конце", ""),
)
DIFF_STEP = (
    ("temp", "температура", " °C"),
    ("hold_min", "выдержка", " мин"),
    ("capture", "точка", ""),
    ("reach_tolerance_c", "допуск", " °C"),
    ("settle_min", "окно", " мин"),
    ("settle_rate", "скорость", " °C/мин"),
    ("note", "примечание", ""),
)


def _shown(value, unit: str = "") -> str:
    """Значение для журнала: да/нет, «общее» для пустого, числа без лишних нулей."""
    if value is None or value == "":
        return "общее" if unit else "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (int, float)):
        text = f"{value:+g}" if unit == " °C" else f"{value:g}"
        return text.replace(".", ",") + unit
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "—"
    return f"{value}{unit}"


def diff(old: dict, new: dict) -> list[str]:
    """Что изменилось в сценарии, строками «что: было → стало» - для журнала действий."""
    old = old or {}
    new = new or {}
    lines = []
    for key, title, unit in DIFF_GENERAL:
        if old.get(key) != new.get(key):
            lines.append(f"{title}: {_shown(old.get(key), unit)} → {_shown(new.get(key), unit)}")
    if (old.get("description") or "") != (new.get("description") or ""):
        lines.append("описание изменено")
    old_steps = old.get("steps") or []
    new_steps = new.get("steps") or []
    for index in range(max(len(old_steps), len(new_steps))):
        number = index + 1
        if index >= len(old_steps):
            lines.append(f"добавлен шаг {number}: {_shown(new_steps[index].get('temp'), ' °C')}")
            continue
        if index >= len(new_steps):
            lines.append(f"убран шаг {number}: {_shown(old_steps[index].get('temp'), ' °C')}")
            continue
        changes = [f"{title} {_shown(old_steps[index].get(key), unit)} → {_shown(new_steps[index].get(key), unit)}"
                   for key, title, unit in DIFF_STEP
                   if old_steps[index].get(key) != new_steps[index].get(key)]
        if changes:
            lines.append(f"шаг {number}: " + ", ".join(changes))
    return lines
