"""Сообщения программы в виде карточки: значок по важности, короткий заголовок и раскрытие.

08.11.2026: в окне копились длинные строки состояния, проверок и замечаний, и их было трудно
читать. Каждое такое сообщение теперь показывается одной строкой - цветной значок и заголовок, -
а по нажатию раскрывается разбор: что произошло, почему это важно, что сделать, и полный текст.

Уровни (цвет значка):
- error - красный «!»: прогон или запись не пойдут, нужна рука человека;
- warn  - жёлтый «!»: работа идёт, но результат будет неполным или под вопросом;
- info  - синий «i»: сведения, ничего делать не нужно;
- ok    - зелёный «✓»: всё получилось.

Сообщения в программе пишутся свободным текстом, поэтому разбор - по устройству русской фразы:
заголовок - первая фраза (до двоеточия или скобки, если она длинная); фразы и части после двоеточия,
которые начинаются с повелительного глагола («нажмите», «поставьте»), - в «что сделать»; начинающиеся
с «без», «иначе», «потому» - в «почему». Полный текст всегда остаётся в раскрытии, поэтому ошибка
разбора ничего не прячет. Замечания расчёта таблиц известны заранее - для них пояснение написано
вручную (explain_remark).
"""

from __future__ import annotations

import re

LEVELS = {
    "error": {"color": "#dc2626", "soft": "#fef2f2", "border": "#fca5a5", "text": "#991b1b", "glyph": "!",
              "title": "Требует действия"},
    "warn": {"color": "#d97706", "soft": "#fffbeb", "border": "#fcd34d", "text": "#92400e", "glyph": "!",
             "title": "Внимание"},
    "info": {"color": "#2563eb", "soft": "#eff6ff", "border": "#bfdbfe", "text": "#1e3a8a", "glyph": "i",
             "title": "Сведения"},
    "ok": {"color": "#16a34a", "soft": "#f0fdf4", "border": "#86efac", "text": "#166534", "glyph": "✓",
           "title": "Готово"},
}

# Цвета, которыми программа красит строки состояния, и слова уровней из её данных.
_RED = {"#dc2626", "#b91c1c", "#ef4444", "#991b1b", "#e11d48", "red"}
_AMBER = {"#d97706", "#b45309", "#f59e0b", "#92400e", "#ea580c", "#c2410c", "#ca8a04", "orange"}
_GREEN = {"#16a34a", "#15803d", "#22c55e", "#059669", "#047857", "green"}
_WORDS = {"error": "error", "bad": "error", "block": "error", "fail": "error", "danger": "error",
          "warn": "warn", "warning": "warn", "info": "info", "normal": "info", "run": "info",
          "ok": "ok", "done": "ok", "success": "ok"}

TITLE_MAX = 90
# Повелительное наклонение: «нажмите», «поставьте», «ставьте», «откройте».
_IMPERATIVE = re.compile(r"^(?:не\s+)?[а-яё]+(?:ите|йте|ьте)\b", re.IGNORECASE)
# Слова на -ите/-йте, которые не глаголы: «на сайте», «в байте», «в лимите».
_NOT_VERBS = {"сайте", "байте", "лимите", "граните", "транзите", "кредите", "элите", "свите", "орбите"}
_WHY = re.compile(r"^(?:без |иначе|потому|так как|из-за|причина|это значит|зачем|это нужно|нужно, |тогда )",
                  re.IGNORECASE)
# Конец фразы: точка, «!» или «?» и пробел перед заглавной буквой, кавычкой или числом.
_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[«\"(A-ZА-ЯЁ0-9+\-−])")
# Часть после двоеточия, точки с запятой или тире, с которой начинается совет.
_ADVICE_TAIL = re.compile(r"(?:[:;,]\s+|\s[-–—]\s)((?:чтобы .+?,\s*)?(?:не\s+)?[а-яё]+(?:ите|йте|ьте)\b.*)$",
                          re.IGNORECASE)

# «чтобы плата пришла к -20,0 °C, » перед советом: цель совета, сам совет - после неё.
_PURPOSE = re.compile(r"^чтобы .*?,\s*(?=(?:не\s+)?[а-яё]+(?:ите|йте|ьте)\b)", re.IGNORECASE)


def level_of(tone) -> str:
    """Уровень по цвету строки или по слову уровня; незнакомое - «сведения»."""
    word = str(tone or "").strip().lower()
    if word in LEVELS:
        return word
    if word in _WORDS:
        return _WORDS[word]
    if word in _RED:
        return "error"
    if word in _AMBER:
        return "warn"
    if word in _GREEN:
        return "ok"
    return "info"


def _is_imperative(text: str) -> bool:
    match = _IMPERATIVE.match(text.strip())
    if match is None:
        return False
    word = match.group(0).split()[-1].lower()
    return word not in _NOT_VERBS


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text.lstrip("⚠⛔✓✗!•-– ").strip()


def _sentence(text: str) -> str:
    """С заглавной буквы и с точкой в конце: так части раскрытия читаются как фразы."""
    text = text.strip().rstrip(";,: ")
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?…»)" else text + "."


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCES.split(_clean(text)) if part.strip()]


def _short_title(first: str) -> tuple[str, str]:
    """Заголовок из первой фразы и то, что от неё осталось (уйдёт в «что произошло»)."""
    first = first.strip().rstrip(".")
    colon = first.find(": ")
    if 6 <= colon <= 70:
        return first[:colon], first[colon + 2:]
    if len(first) <= TITLE_MAX:
        return first, ""
    # Длинная фраза: режем по скобке, запятой или тире до предела, остаток - в описание.
    for mark in (" (", ", ", " - ", " – ", "; "):
        cut = first.rfind(mark, 20, TITLE_MAX)
        if cut > 0:
            rest = first[cut + len(mark):]
            if mark == " (":
                # Скобка уходит в описание отдельной строкой, остаток фразы - следующей.
                inner, _, after = rest.partition(")")
                rest = inner + ("; " + after.lstrip(", ") if after.strip(" ,") else "")
            return first[:cut], rest.lstrip(", -–;")
    cut = first.rfind(" ", 20, TITLE_MAX)
    cut = cut if cut > 0 else TITLE_MAX
    return first[:cut] + "…", first[cut:].strip()


def make_notice(text, tone="", kind: str = "", title: str = "") -> dict:
    """Карточка сообщения: уровень, заголовок, что произошло, почему, что сделать и полный текст."""
    full = _clean(text)
    level = level_of(tone)
    style = LEVELS[level]
    notice = {"level": level, "glyph": style["glyph"], "color": style["color"], "soft": style["soft"],
              "border": style["border"], "textColor": style["text"], "levelTitle": style["title"],
              "kind": str(kind or ""), "title": "", "what": [], "why": [], "todo": [], "detail": full,
              "items": []}
    if not full:
        return notice
    sentences = split_sentences(full)
    if title:
        notice["title"] = _sentence(title).rstrip(".")
        pieces = sentences
    else:
        head, rest = _short_title(sentences[0])
        notice["title"] = _sentence(head).rstrip(".")
        pieces = ([rest] if rest else []) + sentences[1:]
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if _is_imperative(piece):
            notice["todo"].append(_sentence(piece))
            continue
        if _WHY.match(piece):
            notice["why"].append(_sentence(piece))
            continue
        tail = _ADVICE_TAIL.search(piece)
        if tail is not None and _is_imperative(_PURPOSE.sub("", tail.group(1))):
            head_part = piece[:tail.start()].strip()
            if head_part:
                notice["what"].extend(_sentence(item) for item in head_part.split("; ") if item.strip())
            notice["todo"].append(_sentence(tail.group(1)))
            continue
        notice["what"].extend(_sentence(item) for item in piece.split("; ") if item.strip())
    # Описание, совпавшее с заголовком, не повторяем.
    notice["what"] = [item for item in notice["what"] if item.rstrip(".") != notice["title"]]
    return notice


# ------------------------------------------------------------------ замечания расчёта таблиц

def _nodes(text: str) -> str:
    return text.strip().rstrip(".")


_REMARKS: list[tuple[re.Pattern, str, callable]] = []


def _remark(pattern: str, level: str):
    def register(builder):
        _REMARKS.append((re.compile(pattern, re.IGNORECASE), level, builder))
        return builder
    return register


@_remark(r"^нет замера сухой трубки в узлах: (?P<nodes>.+)$", "warn")
def _dry_missing(match):
    nodes = _nodes(match["nodes"])
    return (f"Нет сухой трубки в узлах {nodes}",
            ["В этих узлах нет точки «воздух», при которой трубка была ближе 3 °C к узлу.",
             "Точка могла сниматься, но трубка в корпусе греется сама и стоит теплее воздуха камеры - "
             "тогда точка не относится ни к одному узлу."],
            ["Строки трубки для этих температур не посчитаны: прибор возьмёт их от соседних узлов, и там "
             "ошибка уровня будет больше."],
            ["Доберите эти узлы прогоном «Изделие в сборе»: в сценарии оставьте только недостающие температуры.",
             "Камера, которой управляет программа (Vötsch, Weiss, ESPEC), сама сдвигает уставку, пока трубка не "
             "придёт к узлу. Если камера только читается, ставьте на пульте температуру, которую подскажет прогон."])


@_remark(r"^нет замера погружённой трубки в узлах: (?P<nodes>.+)$", "warn")
def _liquid_missing(match):
    nodes = _nodes(match["nodes"])
    return (f"Нет погружённой трубки в узлах {nodes}",
            ["Точки «жидкость» (трубка в топливе) в этих узлах нет."],
            ["Без неё строка «в жидкости» в этих узлах не строится, если не включена достройка по размаху."],
            ["Включите «Достроить строки в жидкости по постоянному размаху» («Режим прогона и расчёт таблиц»).",
             "После прогона при комнатной температуре погрузите трубку и запишите точку «жидкость» - "
             "одной пары хватит на все узлы."])


@_remark(r"^строки «в жидкости» для (?P<title>.+?) не достроены: размах не задан", "warn")
def _span_missing(match):
    return (f"Строки «в жидкости» ({match['title']}) не достроены",
            ["Размах (разница показаний пустой и полной трубки) не задан, и пары «воздух» + «жидкость» "
             "в журнале ещё нет."],
            ["Без размаха прибор не знает, сколько отсчётов прибавить к сухой трубке при полной."],
            ["При комнатной температуре погрузите трубку в топливо и запишите точку «жидкость» - размах "
             "возьмётся из этой пары сам.",
             "Или впишите размах вручную в поле рядом с переключателем достройки."])


@_remark(r"^строки «в жидкости» для (?P<title>.+?) не достроены: размах (?P<value>\d+)", "error")
def _span_small(match):
    return (f"Размах {match['value']} отсчётов слишком мал ({match['title']})",
            ["Размах меньше, чем прибор согласен применить."],
            ["Такой размах похож на не полностью погружённую трубку или на перепутанные точки."],
            ["Проверьте, что при точке «жидкость» трубка была погружена полностью, и снимите её заново."])


@_remark(r"^строки «в жидкости» для (?P<title>.+?) достроены по размаху", "ok")
def _span_built(match):
    return (f"Строки «в жидкости» ({match['title']}) достроены по размаху", [], [], [])


@_remark(r"^(?P<title>.+?), узел (?P<node>\S+ °C): только \d+", "warn")
def _few_caps(match):
    return (f"{match['title']}: в узле {match['node']} мало эталонов",
            ["В узле снята одна ёмкость, а для разделения сдвига и растяжения нужно две."],
            ["По одной ёмкости поправка платы в этом узле не считается."],
            ["Снимите в этом узле вторую ёмкость (другой эталон)."])


@_remark(r"^(?P<title>.+?), узел (?P<node>\S+ °C): ёмкости совпали", "warn")
def _same_caps(match):
    return (f"{match['title']}: в узле {match['node']} обе точки с одной ёмкостью",
            ["Точки узла записаны с одинаковым эталоном - прямую по ним не провести."],
            [], ["Проверьте пометку «что подключено» и снимите точку с другим эталоном."])


@_remark(r"^(?P<title>.+?), узел (?P<node>\S+ °C): показание не растёт", "error")
def _not_rising(match):
    return (f"{match['title']}: в узле {match['node']} показание не растёт с ёмкостью",
            ["С большей ёмкостью показание вышло не больше, чем с меньшей."],
            ["Так бывает при перепутанных эталонах, плохом контакте или неверной пометке."],
            ["Проверьте оснастку и пометки точек, снимите узел заново."])


@_remark(r"^(?P<title>.+?), узел (?P<node>\S+ °C): точки плохо ложатся на прямую", "warn")
def _bad_line(match):
    return (f"{match['title']}: в узле {match['node']} точки разбросаны",
            ["Точки узла плохо ложатся на прямую."],
            ["Возможна помеха или плата не устоялась при снятии."], ["Снимите этот узел повторно."])


@_remark(r"^(?P<title>.+?): нет данных в опорной точке", "error")
def _no_reference(match):
    return (f"{match['title']}: нет опорной точки +25 °C",
            ["В журнале нет точки при +25 °C."],
            ["От неё отсчитывается вся поправка: без неё таблица не считается."],
            ["Снимите точку при +25 °C."])


@_remark(r"^(?P<title>.+?): нет точки в узлах (?P<nodes>[^.]+)", "warn")
def _board_missing(match):
    return (f"{match['title']}: нет точек платы в узлах {_nodes(match['nodes'])}",
            ["В этих узлах нет точек первого этапа (плата с эталонами)."],
            ["Поправка между соседними узлами будет неверной."],
            ["Доберите эти узлы первым этапом или откройте полный журнал первого этапа платы."])


@_remark(r"^к сведению: (?P<text>.+)$", "info")
def _fyi(match):
    text = match["text"]
    if text.startswith("таблица платы - по одной своей ёмкости"):
        return ("Таблица платы посчитана по одной ёмкости",
                ["На первом этапе в каждом узле снималась одна своя ёмкость, и весь уход платы отнесён "
                 "к одной модели (сдвиг или растяжение)."],
                ["Для собранного изделия это допущение: при подключённой трубке ёмкость другая."],
                [])
    return (_sentence(text).rstrip("."), [], [], [])


@_remark(r"^строки трубки посчитаны без поправки платы", "warn")
def _no_board(match):
    return ("Строки трубки посчитаны без поправки платы",
            ["В открытом журнале нет точек первого этапа с эталонами."],
            ["Строки трубки считаются после поправки платы, как в приборе - без неё они сдвинуты."],
            ["Откройте журнал первого этапа платы («Журналы первого этапа всем платам») и пересчитайте."])


def explain_remark(text) -> dict:
    """Замечание расчёта таблиц - карточкой с пояснением; незнакомое - общим разбором."""
    raw = _clean(text)
    for pattern, level, builder in _REMARKS:
        match = pattern.search(raw)
        if match is None:
            continue
        title, what, why, todo = builder(match)
        notice = make_notice(raw, level)
        notice.update({"title": title, "what": list(what), "why": list(why), "todo": list(todo)})
        return notice
    return make_notice(raw, "warn")


def notice_list(items, tone="warn", kind: str = "", title: str = "", remarks: bool = False) -> dict:
    """Несколько сообщений одной строкой: заголовок со счётом, в раскрытии - каждое своей карточкой.

    Одинаковые сообщения (отличаются только числами - время, температура) сливаются в одно со счётом.
    Уровень строки - самый тяжёлый из вложенных.
    """
    cards, seen = [], {}
    for item in items or []:
        text = item.get("text", "") if isinstance(item, dict) else item
        level = item.get("level", tone) if isinstance(item, dict) else tone
        if not _clean(text):
            continue
        card = explain_remark(text) if remarks else make_notice(text, level, kind)
        if card["level"] == "info" and not remarks and level_of(level) != "info":
            card["level"] = level_of(level)
        key = re.sub(r"[-+−]?\d+(?:[.,]\d+)?", "#", card["title"])
        if key in seen:
            seen[key]["count"] += 1
            continue
        card["count"] = 1
        seen[key] = card
        cards.append(card)
    order = ["error", "warn", "info", "ok"]
    if not cards:
        # Нечего показывать - пустая карточка: строка в окне и на странице скрыта.
        return make_notice("", tone, kind)
    if len(cards) == 1 and cards[0]["count"] == 1:
        # Одно сообщение - своей карточкой, без обёртки «сообщений: 1».
        cards[0]["kind"] = cards[0]["kind"] or str(kind or "")
        return cards[0]
    worst = min((card["level"] for card in cards), key=order.index, default=level_of(tone))
    notice = make_notice("", worst, kind)
    total = sum(card["count"] for card in cards)
    notice["title"] = (title.format(count=total) if title else (cards[0]["title"] if cards else ""))
    notice["items"] = sorted(cards, key=lambda card: order.index(card["level"]))
    for card in notice["items"]:
        style = LEVELS[card["level"]]
        card.update({"glyph": style["glyph"], "color": style["color"], "soft": style["soft"],
                     "border": style["border"], "textColor": style["text"], "levelTitle": style["title"]})
    notice["detail"] = ""
    return notice
