"""Расчёт температурных таблиц прибора по точкам, снятым в климатической камере.

ЗАЧЕМ ЗДЕСЬ КОПИЯ РАСЧЁТА
Тот же расчёт лежит в репозитории прошивки, в tools/chamber_fit.py, и работает
как отдельный скрипт. Программа настройки собирается в один исполняемый файл и
до соседнего репозитория не дотянется, поэтому расчёт повторён здесь. Обе
стороны обязаны давать одинаковые числа: за этим следят проверки в tests.

ДВЕ СТУПЕНИ
Ступень платы убирает дрейф электроники. Чтобы её посчитать, в каждой
температурной точке нужно измерить не меньше двух известных ёмкостей: по одной
ёмкости сдвиг показания и его растяжение выглядят одинаково, и разделить их
невозможно никаким расчётом.

Ступень трубки убирает изменение самой сборки. Для неё в каждой точке нужны два
состояния: сухая трубка и полностью погружённая в опорную жидкость.

ЧТО НА ВХОДЕ
Список точек. Каждая точка это один замер обоих контуров с пометкой оператора
о том, что было подключено:

    «150/47»           - к основному контуру эталон 150 пФ, к контуру вида
                         топлива 47 пФ; «0/0» - к обоим ничего, только своя
                         ёмкость платы
    «осн 150 вид 47»   - то же словами, порядок любой; можно указать и один канал
    «150 пФ»           - одно число: эталон только основного контура (так
                         помечались точки до того, как появилась таблица второго
                         контура)
    «воздух»           - собранное изделие, трубка сухая
    «жидкость»         - собранное изделие, трубка полностью погружена

Пометки с числами идут в расчёт ступени платы, «воздух» и «жидкость» - в расчёт
ступени трубки.

ТАБЛИЦА ПЛАТЫ У КАЖДОГО КОНТУРА СВОЯ
Контуры собраны на разных компараторах и резисторах и уходят с температурой
по-разному, поэтому таблица платы считается для каждого по его собственным
эталонам. Строки ступени трубки каждого контура считаются после поправки платы
этого же контура - ровно так, как прибор применяет обе ступени.
"""

from __future__ import annotations

import re

# Сетка температурных узлов прибора, десятые доли градуса.
NODES_X10 = [-400, -200, 0, 250, 500, 700, 850]

# Опорный узел: при этой температуре поправка равна нулю по построению.
REFERENCE_X10 = 250

# Насколько далеко от узла может стоять точка, чтобы попасть в него, 0.1 °C.
NODE_TOLERANCE_X10 = 30

# Сколько разных ёмкостей нужно в точке, чтобы разделить сдвиг и растяжение.
MIN_REFERENCES_PER_NODE = 2

# Как считать таблицу платы, если в каждом узле снята только одна ёмкость, -
# своя ёмкость платы без эталонов. По одной ёмкости сдвиг и растяжение не
# разделить, поэтому весь уход приписывается одному из них:
#   растяжение - уход пропорционален показанию (резисторы, пороги генератора);
#   сдвиг      - уход постоянен в отсчётах (плавает сама ёмкость на плате).
SINGLE_GAIN = "растяжение"
SINGLE_OFFSET = "сдвиг"
SINGLE_MODELS = (SINGLE_GAIN, SINGLE_OFFSET)

# Наименьший размах между сухой и погружённой трубкой, который примет прибор.
# То же число задано в прошивке как FUEL_TUBE_MIN_SPAN.
TUBE_MIN_SPAN = 100

# Пометки состояний трубки по умолчанию.
AIR_NOTE = "воздух"
LIQUID_NOTE = "жидкость"


# Контуры прибора: ключ в точке прогона и название для отчёта.
CHANNELS = (("main", "основной контур"), ("media", "контур вида топлива"))

_NUMBER = r"(-?\d+(?:[.,]\d+)?)"
_MAIN_WORD = re.compile(r"(?:осн\w*|main)\D{0,12}?" + _NUMBER)
_MEDIA_WORD = re.compile(r"(?:вид\w*|плоск\w*|media)\D{0,12}?" + _NUMBER)


def _to_float(text: str) -> float:
    return float(text.replace(",", "."))


def parse_references(note: str) -> dict:
    """Номиналы эталонов по каналам из пометки оператора.

    Возвращает {"main": пФ или None, "media": пФ или None}. None означает, что
    для этого канала пометка эталона не задаёт. Виды пометок - в описании модуля.
    """
    text = str(note).casefold()
    result = {"main": None, "media": None}

    main = _MAIN_WORD.search(text)
    media = _MEDIA_WORD.search(text)
    if main is not None or media is not None:
        if main is not None:
            result["main"] = _to_float(main.group(1))
        if media is not None:
            result["media"] = _to_float(media.group(1))
        return result

    numbers = re.findall(_NUMBER, text)
    if "/" in text and len(numbers) >= 2:
        result["main"] = _to_float(numbers[0])
        result["media"] = _to_float(numbers[1])
    elif numbers:
        result["main"] = _to_float(numbers[0])
    return result


def parse_reference_pf(note: str):
    """Номинал эталона основного контура из пометки. Без числа возвращает None."""
    return parse_references(note)["main"]


def nearest_node(temperature_x10):
    """Возвращает ближайший узел сетки или None, если точка слишком далеко."""
    if temperature_x10 is None:
        return None
    best = min(NODES_X10, key=lambda node: abs(node - temperature_x10))
    return best if abs(best - temperature_x10) <= NODE_TOLERANCE_X10 else None


def average(values) -> float:
    return sum(values) / float(len(values))


def node_text(node_x10: int) -> str:
    """Температура узла для отчёта. Ноль без знака, остальные со знаком."""
    value = node_x10 / 10.0
    return "0 °C" if abs(value) < 0.05 else f"{value:+.0f} °C"


def capacity_word(count: int) -> str:
    """Правильное окончание после числа: 1 ёмкость, 2 ёмкости, 5 ёмкостей."""
    tail_two = count % 100
    tail_one = count % 10
    if 11 <= tail_two <= 14:
        return "ёмкостей"
    if tail_one == 1:
        return "ёмкость"
    if tail_one in (2, 3, 4):
        return "ёмкости"
    return "ёмкостей"


def fit_line(points):
    """Метод наименьших квадратов для прямой y = a*x + b. Возвращает (a, b, остаток)."""
    count = len(points)
    sum_x = sum(x for x, _ in points)
    sum_y = sum(y for _, y in points)
    sum_xx = sum(x * x for x, _ in points)
    sum_xy = sum(x * y for x, y in points)

    denominator = count * sum_xx - sum_x * sum_x
    if abs(denominator) < 1e-9:
        return None

    a = (count * sum_xy - sum_x * sum_y) / denominator
    b = (sum_y - a * sum_x) / count
    residual = max(abs(y - (a * x + b)) for x, y in points) if count > 2 else 0.0
    return a, b, residual


def group_stage1(records, channel: str = "main") -> dict:
    """Собирает данные ступени платы канала: узел -> номинал эталона -> среднее показание."""
    grouped: dict[int, dict[float, list[float]]] = {}
    for item in records:
        capacitance = parse_references(item["note"])[channel]
        if capacitance is None:
            continue
        if item.get(channel) is None:
            continue
        node = nearest_node(item["board_temp_x10"])
        if node is None:
            continue
        grouped.setdefault(node, {}).setdefault(capacitance, []).append(item[channel])

    return {
        node: {cap: average(values) for cap, values in caps.items()}
        for node, caps in grouped.items()
    }


def build_board_table(stage1: dict, report: list[str], title: str = "основной контур",
                      single_model=None):
    """Строит таблицу ступени платы одного канала: на каждый узел сдвиг и растяжение.

    single_model - SINGLE_GAIN или SINGLE_OFFSET: разрешает считать таблицу по
    одной ёмкости в узле, см. build_board_table_single. Без него одна ёмкость
    в узле - это недостаток данных.
    """
    fits: dict[int, tuple[float, float]] = {}
    singles: dict[int, tuple[float, float]] = {}

    for node in sorted(stage1):
        points = sorted(stage1[node].items())
        if len(points) < MIN_REFERENCES_PER_NODE:
            if single_model in SINGLE_MODELS and len(points) == 1:
                singles[node] = points[0]
                continue
            report.append(
                f"{title}, узел {node_text(node)}: только {len(points)} {capacity_word(len(points))}, "
                f"нужно минимум {MIN_REFERENCES_PER_NODE}. Разделить сдвиг и растяжение нельзя"
            )
            continue

        result = fit_line(points)
        if result is None:
            report.append(f"{title}, узел {node_text(node)}: ёмкости совпали, прямая не строится")
            continue

        slope, intercept, residual = result
        if slope <= 0:
            report.append(f"{title}, узел {node_text(node)}: показание не растёт с ёмкостью, проверьте оснастку")
            continue

        fits[node] = (slope, intercept)
        if len(points) > 2 and residual > 0.02 * abs(slope) * max(cap for cap, _ in points):
            report.append(
                f"{title}, узел {node_text(node)}: точки плохо ложатся на прямую, "
                f"наибольшее отклонение {residual:.1f} отсчёта"
            )

    if singles and not fits:
        return build_board_table_single(singles, report, title, single_model)
    for node in sorted(singles):
        # Узлы с двумя ёмкостями считаются честно, одиночный узел к ним не подмешивается.
        report.append(
            f"{title}, узел {node_text(node)}: одна ёмкость, а в других узлах их по две. "
            "Снимите вторую ёмкость и в этом узле"
        )

    if REFERENCE_X10 not in fits:
        report.append(
            f"{title}: нет данных в опорной точке {node_text(REFERENCE_X10)}. "
            "Без неё не от чего отсчитывать поправку"
        )
        return None, fits

    slope_ref, intercept_ref = fits[REFERENCE_X10]

    table = []
    for node in NODES_X10:
        if node not in fits:
            table.append((0, 0))
            continue
        slope, intercept = fits[node]
        gain = slope / slope_ref
        gain_ppm = int(round((gain - 1.0) * 1_000_000))
        offset = int(round(intercept_ref * gain - intercept))
        table.append((offset, gain_ppm))

    return table, fits


def build_board_table_single(singles: dict, report: list[str], title: str, single_model):
    """Таблица платы по одной ёмкости в каждом узле: своя ёмкость платы без эталонов.

    В каждом узле показание при этой ёмкости возвращается ровно к показанию в
    опорной точке. Весь уход приписывается растяжению или сдвигу (single_model):
    при этой ёмкости оба способа дают одно и то же, а при другой ёмкости
    (подключённая трубка) поправка становится допущением. Ёмкость должна быть
    одна и та же во всех узлах, иначе сравнивать нечего.
    """
    if REFERENCE_X10 not in singles:
        report.append(
            f"{title}: нет данных в опорной точке {node_text(REFERENCE_X10)}. "
            "Без неё не от чего отсчитывать поправку"
        )
        return None, {}

    cap_ref, value_ref = singles[REFERENCE_X10]
    used: dict[int, tuple[float, float]] = {}
    missing = []
    table = []
    for node in NODES_X10:
        item = singles.get(node)
        if item is None:
            missing.append(node)
            table.append((0, 0))
            continue
        cap, value = item
        if cap != cap_ref or value <= 0:
            report.append(
                f"{title}, узел {node_text(node)}: ёмкость {cap:g} пФ, а в опорной точке {cap_ref:g} пФ. "
                "По одной ёмкости поправка считается, только если она одна и та же во всех узлах"
            )
            table.append((0, 0))
            continue
        used[node] = item
        if single_model == SINGLE_GAIN:
            table.append((0, int(round((value / value_ref - 1.0) * 1_000_000))))
        else:
            table.append((int(round(value_ref - value)), 0))

    if missing:
        report.append(
            f"{title}: нет точки в узлах " + ", ".join(node_text(node) for node in missing)
            + ". Без них поправка между соседними узлами будет неверной"
        )
    return table, used


def interpolate_pair(table, temperature_x10):
    """Линейная интерполяция пары значений по сетке узлов."""
    if temperature_x10 <= NODES_X10[0]:
        return table[0]
    for index in range(1, len(NODES_X10)):
        if temperature_x10 > NODES_X10[index]:
            continue
        span = NODES_X10[index] - NODES_X10[index - 1]
        position = temperature_x10 - NODES_X10[index - 1]
        left, right = table[index - 1], table[index]
        return (
            left[0] + (right[0] - left[0]) * position / span,
            left[1] + (right[1] - left[1]) * position / span,
        )
    return table[-1]


def apply_board_table(value: float, table, node_x10) -> float:
    """Применяет ступень платы так же, как это делает прибор."""
    if table is None:
        return value

    offset, gain_ppm = interpolate_pair(table, node_x10)
    corrected = value + offset
    gain_units = 1_000_000 + gain_ppm
    if gain_units <= 0:
        return corrected
    return corrected * 1_000_000.0 / gain_units


def build_tube_tables(records, board_tables, air_note: str, liquid_note: str, report: list[str]):
    """Строит ряды ступени трубки: показания на воздухе и в опорной жидкости.

    board_tables - таблицы платы по каналам {"main": ..., "media": ...}: каждый
    канал поправляется своей, как в приборе. Отсутствующая таблица означает,
    что прибор этот канал по плате не поправляет, и здесь его тоже не трогаем.

    Состояния заполняются независимо друг от друга. Так сохраняются те строки
    «на воздухе», которые сняты, даже если погружение в этом узле сделать не
    удалось: их потом можно достроить по размаху опорной точки.
    """
    board_main = board_tables.get("main") if isinstance(board_tables, dict) else board_tables
    board_media = board_tables.get("media") if isinstance(board_tables, dict) else None
    collected: dict[str, dict[int, dict[str, list[float]]]] = {air_note: {}, liquid_note: {}}

    for item in records:
        note = str(item["note"]).strip().casefold()
        if note == air_note.casefold():
            bucket = air_note
        elif note == liquid_note.casefold():
            bucket = liquid_note
        else:
            continue

        tube_x10 = item["fuel_temp_x10"]
        if tube_x10 is None or item.get("main") is None:
            continue
        node = nearest_node(tube_x10)
        if node is None:
            continue

        board_node = nearest_node(item["board_temp_x10"])
        board_x10 = board_node if board_node is not None else item["board_temp_x10"]

        target = collected[bucket].setdefault(node, {"main": [], "media": []})
        target["main"].append(apply_board_table(item["main"], board_main, board_x10))
        if item.get("media") is not None:
            target["media"].append(apply_board_table(item["media"], board_media, board_x10))

    rows = {"air_main": [], "full_main": [], "air_media": [], "full_media": []}
    missing_air = []
    missing_liquid = []

    for node in NODES_X10:
        air = collected[air_note].get(node)
        liquid = collected[liquid_note].get(node)

        if air is None:
            missing_air.append(node)
            rows["air_main"].append(0)
            rows["air_media"].append(0)
        else:
            rows["air_main"].append(int(round(average(air["main"]))))
            rows["air_media"].append(int(round(average(air["media"]))) if air["media"] else 0)

        if liquid is None:
            missing_liquid.append(node)
            rows["full_main"].append(0)
            rows["full_media"].append(0)
        else:
            rows["full_main"].append(int(round(average(liquid["main"]))))
            rows["full_media"].append(int(round(average(liquid["media"]))) if liquid["media"] else 0)

    if missing_air:
        report.append(
            "нет замера сухой трубки в узлах: "
            + ", ".join(node_text(node) for node in missing_air)
        )
    if missing_liquid:
        report.append(
            "нет замера погружённой трубки в узлах: "
            + ", ".join(node_text(node) for node in missing_liquid)
        )

    return rows


def measured_span(rows, key_air: str, key_full: str):
    """Возвращает размах из узла, где сняты оба состояния. Опорная точка в приоритете.

    Малый размах здесь не отсеивается: решение о пригодности принимает вызывающая
    сторона, иначе «пара не снята» и «пара снята, но размах мал» выглядели бы
    одинаково, и оператор не понял бы, что именно не так.
    """
    order = [NODES_X10.index(REFERENCE_X10)] + [
        index for index in range(len(NODES_X10)) if NODES_X10[index] != REFERENCE_X10
    ]
    for index in order:
        air = rows[key_air][index]
        full = rows[key_full][index]
        if air != 0 and full != 0:
            return full - air, NODES_X10[index]
    return None, None


def extend_liquid_rows(rows, report: list[str], span_main=None, span_media=None):
    """Достраивает недостающие строки «в жидкости» по постоянному размаху.

    ЗАЧЕМ ЭТО НУЖНО
    В климатическую камеру часто нельзя ставить топливо, и погружение при каждой
    температуре снять не получается. Тогда размах между пустым и полным снимают
    один раз при комнатной температуре, а в остальных узлах считают его таким же.

    ЧТО ЭТО ДАЁТ И ЧЕГО НЕ ДАЁТ
    Прибор будет править смещение нуля по температуре, то есть основную часть
    ухода сборки. Масштаб он оставит как есть. Размах меняется в основном из-за
    проницаемости топлива, а её прибор измеряет контуром вида топлива в реальном
    времени, поэтому остаётся только тепловое расширение самой трубки.
    """
    for key_air, key_full, span, title in (
        ("air_main", "full_main", span_main, "основного контура"),
        ("air_media", "full_media", span_media, "контура вида топлива"),
    ):
        value = span
        source = "задан вручную"
        if value is None:
            value, node = measured_span(rows, key_air, key_full)
            source = f"взят из узла {node_text(node)}" if value is not None else ""

        if value is None:
            report.append(
                f"строки «в жидкости» для {title} не достроены: "
                "размах не задан и ни в одном узле не снята пара состояний"
            )
            continue

        if value < TUBE_MIN_SPAN:
            report.append(
                f"строки «в жидкости» для {title} не достроены: размах {int(value)} отсчётов "
                f"({source}) меньше {TUBE_MIN_SPAN}, прибор такое приведение не применит"
            )
            continue

        built = []
        for index, node in enumerate(NODES_X10):
            if rows[key_air][index] == 0 or rows[key_full][index] != 0:
                continue
            rows[key_full][index] = int(round(rows[key_air][index] + value))
            built.append(node)

        if built:
            report.append(
                f"строки «в жидкости» для {title} достроены по размаху "
                f"{int(value)} отсчётов, {source}, в узлах: "
                + ", ".join(node_text(node) for node in built)
            )

    return rows


def clamp_i16(value: int) -> int:
    return max(-32768, min(32767, int(value)))


def compute_tables(records, air_note: str = AIR_NOTE, liquid_note: str = LIQUID_NOTE,
                   extend_liquid: bool = False, span_main=None, span_media=None,
                   single_model=None, board_only: bool = False) -> dict:
    """Считает обе ступени по списку точек прогона.

    Возвращает словарь того же вида, что и файл скрипта прошивки, поэтому окно
    профиля принимает его без всякого преобразования. Ключ «замечания» перечисляет
    всё, чего не хватило: пустой список означает, что таблицы можно записывать.

    Признак extend_liquid включает достройку недостающих строк «в жидкости» по
    постоянному размаху, см. extend_liquid_rows.

    Таблица платы основного контура лежит под ключом «ступень_платы», контура
    вида топлива - под «ступень_платы_вида». Пустой список - таблица не
    посчитана, и окно профиля оставит прежнюю.

    single_model разрешает считать таблицу платы по одной ёмкости в узле (см.
    build_board_table_single). board_only - прогон одной платы без трубки:
    отсутствие точек «воздух» и «жидкость» тогда не считается недостатком.
    """
    report: list[str] = []
    boards: dict[str, list | None] = {}
    nodes: dict[str, list[int]] = {}

    stages = {channel: group_stage1(records, channel) for channel, _title in CHANNELS}
    if not any(stages.values()):
        report.append("в пометках не встретилось ни одного номинала эталона")

    for channel, title in CHANNELS:
        stage1 = stages[channel]
        if not stage1:
            # Одна таблица без другой - частая ошибка оснастки: эталоны подключили
            # только к одному входу. Молча оставлять второй контур без поправки нельзя.
            if any(stages.values()):
                report.append(
                    f"{title}: эталонов в пометках нет, таблица платы для него не посчитана. "
                    "Пометка для обоих каналов пишется так: «150/47»"
                )
            boards[channel] = None
            nodes[channel] = []
            continue
        board, fits = build_board_table(stage1, report, title, single_model=single_model)
        boards[channel] = board
        nodes[channel] = sorted(fits)

    # Прогон одной платы: трубки нет, и её отсутствие - не недостаток данных.
    tube_report: list[str] = []
    tube = build_tube_tables(records, boards, air_note, liquid_note, tube_report)
    if not board_only:
        report.extend(tube_report)
    if extend_liquid:
        tube = extend_liquid_rows(tube, report, span_main=span_main, span_media=span_media)

    has_tube_points = any(any(tube[key]) for key in ("air_main", "full_main", "air_media", "full_media"))
    if has_tube_points and not any(stages.values()):
        report.append(
            "строки трубки посчитаны без поправки платы: в журнале нет эталонов. Если таблицы "
            "платы уже записаны в прибор, загрузите журнал первого этапа и считайте вместе с ним"
        )

    def pairs(board):
        return [[clamp_i16(offset), clamp_i16(gain)] for offset, gain in (board or [])]

    return {
        "узлы_x10": list(NODES_X10),
        "ступень_платы": pairs(boards["main"]),
        "ступень_платы_вида": pairs(boards["media"]),
        "ступень_трубки": tube,
        "замечания": report,
        "узлы_ступени_платы": nodes["main"],
        "узлы_ступени_платы_вида": nodes["media"],
        "одна_ёмкость": single_model if single_model in SINGLE_MODELS else "",
        "только_плата": bool(board_only),
    }
