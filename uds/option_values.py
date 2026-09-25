"""Представление значений параметров UDS в окне параметров.

ЗАЧЕМ
Прибор отдаёт параметр набором байт. Показывать его как «LE=65524 | BE=62719»
бесполезно: оператор должен видеть «-12 отсч.», «25.3 °C» или «включена», а
при записи вводить значение в тех же единицах, в которых он его видит.

Модуль знает для каждого параметра, как устроены его байты (число со знаком
или без, масштаб, единицы, список, флаги, текст), и в обе стороны переводит
байты и человекочитаемый текст. Он не зависит от Qt, поэтому проверяется
обычными тестами.

Типы и масштабы сверены с прошивкой: eeprom_app_matrix.h и обработчик чтения
DID в charon_DiagnosticAndCommunicationManagementFunctionalUnit.c.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from uds.options_catalog import UdsOptionParameter

# Виды значений.
KIND_UINT = "uint"            # целое без знака
KIND_INT = "int"              # целое со знаком
KIND_HEX = "hex"              # целое без знака, удобнее видеть в шестнадцатеричном виде
KIND_ENUM = "enum"            # целое с именованными значениями
KIND_BITS = "bits"            # набор флагов
KIND_TEXT = "text"            # строка
KIND_I16_LIST = "i16_list"    # список int16
KIND_LUT_PAIRS = "lut_pairs"  # пары int16: сдвиг и растяжение
KIND_AGE_PAIR = "age_pair"    # два возраста uint16, мс
KIND_EEPROM_STATE = "eeprom_state"  # 4 байта состояния записи в EEPROM
KIND_BYTES = "bytes"          # просто байты

# Способы ввода значения для записи.
INPUT_VALUE = "value"   # в единицах параметра, как он показан
INPUT_RAW = "raw"       # сырое целое число, как хранится в приборе
INPUT_TEXT = "text"     # строка
INPUT_BYTES = "bytes"   # байты в шестнадцатеричном виде

INPUT_MODES: list[tuple[str, str]] = [
    (INPUT_VALUE, "Значение"),
    (INPUT_RAW, "Сырое число"),
    (INPUT_TEXT, "Текст"),
    (INPUT_BYTES, "Байты HEX"),
]

# Значение 0x0061, при котором эмуляция температуры выключена.
_EMULATION_OFF = -32768


@dataclass(frozen=True)
class OptionPresentation:
    """Как читать и показывать байты одного параметра."""

    kind: str = KIND_UINT
    scale: int = 1                 # делитель: 10 означает шаг 0.1
    unit: str = ""
    enum: dict[int, str] = field(default_factory=dict)
    bits: tuple[str, ...] = ()
    min_value: float | None = None  # границы в единицах параметра
    max_value: float | None = None


def _p(kind: str = KIND_UINT, scale: int = 1, unit: str = "", **kwargs) -> OptionPresentation:
    return OptionPresentation(kind=kind, scale=scale, unit=unit, **kwargs)


_COUNT = "отсч."

PRESENTATIONS: dict[int, OptionPresentation] = {
    0x0010: _p(KIND_UINT),
    0x0011: _p(KIND_HEX),
    0x0012: _p(KIND_UINT, unit=_COUNT),
    0x0013: _p(KIND_UINT, unit=_COUNT),
    0x0014: _p(KIND_UINT, unit=_COUNT),
    0x0015: _p(KIND_HEX),
    0x0016: _p(KIND_UINT),
    0x0017: _p(KIND_UINT, scale=10, unit="%"),
    0x0018: _p(KIND_INT, scale=10, unit="%"),
    0x0019: _p(KIND_INT, scale=10, unit="°C"),
    0x002D: _p(KIND_INT, unit=_COUNT),
    0x002E: _p(KIND_ENUM, enum={0: "выключена", 1: "включена"}),
    0x002F: _p(KIND_UINT, unit=_COUNT),
    0x0030: _p(KIND_UINT, unit=_COUNT),
    0x0031: _p(KIND_INT, scale=1000),
    0x0032: _p(KIND_INT, scale=1000),
    0x0033: _p(KIND_INT, scale=1000),
    0x0034: _p(KIND_UINT, unit="%", min_value=0, max_value=95),
    0x0035: _p(KIND_UINT, scale=1000),
    0x0036: _p(KIND_UINT, unit=_COUNT),
    0x0037: _p(KIND_BITS, bits=("коррекция применяется", "данные устарели",
                                "обновление заморожено", "отказ контура")),
    0x0038: _p(KIND_UINT),
    0x0039: _p(KIND_UINT, scale=1000),
    0x003A: _p(KIND_ENUM, enum={0: "датчик топлива", 1: "датчик платы"}),
    0x003B: _p(KIND_INT, scale=10, unit="°C"),
    0x003C: _p(KIND_UINT),
    0x003D: _p(KIND_UINT, unit=_COUNT),
    0x003E: _p(KIND_UINT, unit=_COUNT),
    0x003F: _p(KIND_INT, unit=_COUNT),
    0x0040: _p(KIND_UINT),
    0x0041: _p(KIND_UINT, unit=_COUNT),
    0x0042: _p(KIND_UINT),
    0x0043: _p(KIND_INT, scale=100, unit="отсч./°C"),
    0x0044: _p(KIND_INT, unit=_COUNT),
    0x0045: _p(KIND_INT, scale=100, unit="отсч./°C"),
    0x0046: _p(KIND_INT, unit=_COUNT),
    0x0047: _p(KIND_UINT, unit=_COUNT),
    0x0048: _p(KIND_INT, scale=10, unit="°C"),
    0x0049: _p(KIND_INT, unit="ppm/°C"),
    0x004A: _p(KIND_INT, unit="ppm/°C"),
    0x004B: _p(KIND_I16_LIST, scale=10, unit="°C"),
    0x004C: _p(KIND_LUT_PAIRS),
    0x004D: _p(KIND_LUT_PAIRS),
    0x004E: _p(KIND_BITS, bits=("таблица платы, основной", "таблица платы, вид топлива",
                                "сетка узлов неверна", "приведение трубки, основной",
                                "приведение трубки, вид топлива")),
    0x004F: _p(KIND_I16_LIST, unit=_COUNT),
    0x0050: _p(KIND_I16_LIST, unit=_COUNT),
    0x0051: _p(KIND_I16_LIST, unit=_COUNT),
    0x0052: _p(KIND_I16_LIST, unit=_COUNT),
    0x0053: _p(KIND_ENUM, enum={0: "прежняя", 1: "по двум контурам"}),
    0x0054: _p(KIND_UINT, unit=_COUNT),
    0x0055: _p(KIND_UINT, unit=_COUNT),
    0x0056: _p(KIND_UINT, scale=1000),
    0x0057: _p(KIND_UINT, scale=1000),
    0x0058: _p(KIND_UINT, scale=1000),
    0x0059: _p(KIND_INT, unit=_COUNT),
    0x005A: _p(KIND_INT, scale=1000),
    0x005B: _p(KIND_UINT, unit=_COUNT),
    0x005C: _p(KIND_UINT),
    0x005D: _p(KIND_UINT),
    0x005E: _p(KIND_HEX),
    0x005F: _p(KIND_HEX),
    0x0060: _p(KIND_BITS, bits=("заполнен", "сумма сходится", "алгоритм совпадает", "применяется")),
    0x0061: _p(KIND_INT, scale=10, unit="°C"),
    0x0062: _p(KIND_UINT, unit=_COUNT),
    0x0063: _p(KIND_EEPROM_STATE),
    0x0064: _p(KIND_AGE_PAIR),
    0x0065: _p(KIND_UINT, unit="с", min_value=1, max_value=60),
    0x0066: _p(KIND_UINT, unit="с", min_value=1, max_value=60),
}

# Группы для фильтра окна параметров: название и принадлежащие ей DID.
_GROUP_RANGES: list[tuple[str, tuple[int, ...]]] = [
    ("Связь и сессия", (0x0010, 0x0011, 0x0015, 0x0016)),
    ("Уровень и бак", (0x0012, 0x0013, 0x0014, 0x0017, 0x0018, 0x002D, 0x0062, 0x0065)),
    ("Вид топлива", tuple(range(0x002E, 0x003A)) + (0x0066,)),
    ("Температура и профиль", (0x0019, 0x003A, 0x003B, 0x003C) + tuple(range(0x0043, 0x0053))
     + tuple(range(0x005C, 0x0062))),
    ("Модель по двум контурам", tuple(range(0x0053, 0x005C))),
    ("Качество измерения", tuple(range(0x003D, 0x0043)) + (0x0063, 0x0064)),
]
GROUP_IDENTIFICATION = "Идентификация ЭБУ"
GROUP_OTHER = "Прочее"
OPTION_GROUPS: list[str] = [name for name, _ in _GROUP_RANGES] + [GROUP_IDENTIFICATION, GROUP_OTHER]


def option_group(did: int) -> str:
    """Группа параметра для фильтра окна параметров."""
    value = int(did) & 0xFFFF
    for name, dids in _GROUP_RANGES:
        if value in dids:
            return name
    if value >= 0xF100:
        return GROUP_IDENTIFICATION
    return GROUP_OTHER


def option_presentation(parameter: UdsOptionParameter) -> OptionPresentation:
    """Как показывать параметр. Для неописанных - по размеру и номеру."""
    known = PRESENTATIONS.get(int(parameter.did) & 0xFFFF)
    if known is not None:
        return known
    if int(parameter.did) >= 0xF100:
        return _p(KIND_TEXT)
    if int(parameter.size) <= 8:
        return _p(KIND_UINT)
    return _p(KIND_BYTES)


def _decimals(scale: int) -> int:
    digits = 0
    rest = int(scale)
    while rest >= 10:
        rest //= 10
        digits += 1
    return digits


def _format_scaled(raw: int, scale: int) -> str:
    """Число с учётом масштаба: 253 при масштабе 10 даёт «25.3»."""
    if scale <= 1:
        return str(int(raw))
    digits = _decimals(scale)
    return f"{raw / scale:.{digits}f}"


def _with_unit(text: str, unit: str) -> str:
    return f"{text} {unit}" if unit else text


def _int_from(data: bytes, signed: bool) -> int:
    return int.from_bytes(bytes(data), byteorder="little", signed=signed)


def _i16_values(data: bytes) -> list[int]:
    payload = bytes(data)
    return [int.from_bytes(payload[i:i + 2], byteorder="little", signed=True)
            for i in range(0, len(payload) - 1, 2)]


def _decode_text(data: bytes) -> str:
    trimmed = bytes(data).split(b"\x00", 1)[0]
    try:
        return trimmed.decode("utf-8")
    except UnicodeDecodeError:
        return trimmed.decode("latin-1", errors="replace")


def _ascii_view(data: bytes) -> str:
    parts = []
    for byte in bytes(data):
        parts.append(chr(byte) if 0x20 <= byte <= 0x7E else "·")
    return "".join(parts)


def _bits_text(value: int, names: tuple[str, ...]) -> str:
    active = [names[bit] if bit < len(names) else f"бит {bit}"
              for bit in range(max(len(names), value.bit_length())) if value & (1 << bit)]
    return ", ".join(active) if active else "нет флагов"


_EEPROM_FLAGS = ("сбой обмена", "запись не подтвердилась", "часть сброшена при включении",
                 "всё сброшено при включении")


def format_option_value(parameter: UdsOptionParameter, data: bytes | None) -> dict[str, str]:
    """Все представления значения для окна параметров.

    display - главное, в единицах параметра; number - целое как хранится
    (со знаком, если параметр знаковый); hex - то же в шестнадцатеричном виде;
    raw - байты; text - байты как текст.
    """
    empty = {"display": "", "number": "", "hex": "", "raw": "", "text": ""}
    if data is None or len(data) == 0:
        return empty

    payload = bytes(data)
    presentation = option_presentation(parameter)
    kind = presentation.kind
    raw_hex = " ".join(f"{byte:02X}" for byte in payload)
    result = dict(empty)
    result["raw"] = raw_hex
    result["text"] = _ascii_view(payload)

    if len(payload) <= 8:
        signed = kind == KIND_INT
        number = _int_from(payload, signed)
        unsigned = _int_from(payload, False)
        result["number"] = str(number)
        result["hex"] = f"0x{unsigned:0{len(payload) * 2}X}"

    if kind in (KIND_UINT, KIND_INT) and len(payload) <= 8:
        number = _int_from(payload, kind == KIND_INT)
        if int(parameter.did) == 0x0061 and number == _EMULATION_OFF:
            result["display"] = "выключена"
        else:
            result["display"] = _with_unit(_format_scaled(number, presentation.scale), presentation.unit)
    elif kind == KIND_HEX and len(payload) <= 8:
        number = _int_from(payload, False)
        result["display"] = f"0x{number:0{len(payload) * 2}X} ({number})"
    elif kind == KIND_ENUM and len(payload) <= 8:
        number = _int_from(payload, False)
        name = presentation.enum.get(number)
        result["display"] = f"{number} - {name}" if name else f"{number} - неизвестное значение"
    elif kind == KIND_BITS and len(payload) <= 8:
        number = _int_from(payload, False)
        result["display"] = f"0x{number:02X}: {_bits_text(number, presentation.bits)}"
    elif kind == KIND_TEXT:
        text = _decode_text(payload)
        result["display"] = text if text.strip() else "(пусто)"
    elif kind == KIND_I16_LIST:
        values = [_format_scaled(value, presentation.scale) for value in _i16_values(payload)]
        result["display"] = _with_unit(", ".join(values), presentation.unit)
    elif kind == KIND_LUT_PAIRS:
        values = _i16_values(payload)
        pairs = [f"{values[i]}/{values[i + 1]}" for i in range(0, len(values) - 1, 2)]
        result["display"] = "сдвиг/ppm: " + ", ".join(pairs)
    elif kind == KIND_AGE_PAIR and len(payload) >= 4:
        ages = [int.from_bytes(payload[i:i + 2], byteorder="little") for i in (0, 2)]
        texts = ["нет измерений" if age == 0xFFFF else f"{age} мс" for age in ages]
        result["display"] = f"основной {texts[0]}, вид топлива {texts[1]}"
    elif kind == KIND_EEPROM_STATE and len(payload) >= 4:
        flags = _bits_text(int(payload[1]), _EEPROM_FLAGS)
        result["display"] = (f"не записано {payload[0]}, флаги: {flags}, "
                             f"сброшено при включении {payload[2]}, ошибок {payload[3]}")
    else:
        result["display"] = raw_hex

    return result


def option_edit_text(parameter: UdsOptionParameter, data: bytes | None, mode: str = INPUT_VALUE) -> str:
    """Текущее значение в том виде, в каком его вводят для записи.

    Нужен, чтобы подставить прочитанное значение в поле записи и поправить
    его, а не набирать заново.
    """
    if data is None or len(data) == 0:
        return ""
    payload = bytes(data)
    presentation = option_presentation(parameter)
    kind = presentation.kind

    if mode == INPUT_BYTES:
        return " ".join(f"{byte:02X}" for byte in payload)
    if mode == INPUT_TEXT:
        return _decode_text(payload)
    if mode == INPUT_RAW:
        if len(payload) > 8:
            return ""
        return str(_int_from(payload, kind == KIND_INT))

    if kind == KIND_TEXT:
        return _decode_text(payload)
    if kind == KIND_I16_LIST:
        return ", ".join(_format_scaled(value, presentation.scale) for value in _i16_values(payload))
    if kind == KIND_LUT_PAIRS:
        return ", ".join(str(value) for value in _i16_values(payload))
    if kind == KIND_HEX and len(payload) <= 8:
        return f"0x{_int_from(payload, False):X}"
    if kind in (KIND_UINT, KIND_INT, KIND_ENUM, KIND_BITS) and len(payload) <= 8:
        return _format_scaled(_int_from(payload, kind == KIND_INT), presentation.scale)
    return " ".join(f"{byte:02X}" for byte in payload)


def default_input_mode(parameter: UdsOptionParameter) -> str:
    """Способ ввода, который подходит параметру по умолчанию."""
    kind = option_presentation(parameter).kind
    if kind == KIND_TEXT:
        return INPUT_TEXT
    if kind in (KIND_BYTES, KIND_AGE_PAIR, KIND_EEPROM_STATE):
        return INPUT_BYTES
    return INPUT_VALUE


def option_input_hint(parameter: UdsOptionParameter, mode: str = INPUT_VALUE) -> str:
    """Подсказка под полем записи: что и в каком виде вводить."""
    presentation = option_presentation(parameter)
    kind = presentation.kind
    size = int(parameter.size)

    if mode == INPUT_BYTES:
        return f"Байты в шестнадцатеричном виде через пробел, не больше {size}: например 0A 00."
    if mode == INPUT_TEXT:
        return f"Строка, не длиннее {size} байт в UTF-8. Остаток прибор заполнит нулями."
    if mode == INPUT_RAW:
        low, high = _raw_limits(size, kind == KIND_INT)
        return f"Целое число, как хранится в приборе: от {low} до {high}, можно 0x-вид."

    if kind == KIND_TEXT:
        return f"Строка, не длиннее {size} байт в UTF-8."
    if kind == KIND_I16_LIST:
        count = size // 2
        step = _format_scaled(1, presentation.scale)
        return f"{count} чисел через запятую, шаг {step}{(' ' + presentation.unit) if presentation.unit else ''}."
    if kind == KIND_LUT_PAIRS:
        return f"{size // 2} чисел через запятую: сдвиг, ppm, сдвиг, ppm..."
    if kind == KIND_ENUM:
        choices = "; ".join(f"{value} - {name}" for value, name in presentation.enum.items())
        return f"Одно из значений: {choices}."
    if kind == KIND_BITS:
        return "Число с флагами: десятичное или 0x-вид."
    if kind in (KIND_AGE_PAIR, KIND_EEPROM_STATE, KIND_BYTES):
        return f"Байты в шестнадцатеричном виде через пробел, не больше {size}."

    low, high = _value_limits(parameter, presentation)
    step = _format_scaled(1, presentation.scale)
    unit = f" {presentation.unit}" if presentation.unit else ""
    if presentation.scale > 1:
        return f"Число от {low} до {high}{unit}, шаг {step}. Запятая или точка - всё равно."
    return f"Целое число от {low} до {high}{unit}."


def _raw_limits(size: int, signed: bool) -> tuple[int, int]:
    bits = int(size) * 8
    if signed:
        return -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return 0, (1 << bits) - 1


def _value_limits(parameter: UdsOptionParameter, presentation: OptionPresentation) -> tuple[str, str]:
    low_raw, high_raw = _raw_limits(int(parameter.size), presentation.kind == KIND_INT)
    low = _format_scaled(low_raw, presentation.scale)
    high = _format_scaled(high_raw, presentation.scale)
    if presentation.min_value is not None:
        low = _format_number(presentation.min_value)
    if presentation.max_value is not None:
        high = _format_number(presentation.max_value)
    return low, high


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


class OptionInputError(ValueError):
    """Ввод нельзя превратить в байты параметра. Текст сообщения показывается оператору."""


_NUMBER_SPLIT = re.compile(r"[\s,;/]+")


def _parse_integer(text: str) -> int:
    raw = str(text).strip().replace(" ", "")
    if not raw:
        raise OptionInputError("Пустое значение.")
    negative = raw.startswith("-")
    body = raw[1:] if negative else raw
    try:
        value = int(body, 16) if body.lower().startswith("0x") else int(body, 10)
    except ValueError as exc:
        raise OptionInputError(f"«{text}» - не целое число.") from exc
    return -value if negative else value


def _parse_scaled(text: str, scale: int) -> int:
    """Число в единицах параметра в сырое целое: «25.3» при масштабе 10 даёт 253."""
    raw = str(text).strip().replace(" ", "").replace(",", ".")
    if not raw:
        raise OptionInputError("Пустое значение.")
    if raw.lower().lstrip("-").startswith("0x"):
        return _parse_integer(raw)
    try:
        value = float(raw)
    except ValueError as exc:
        raise OptionInputError(f"«{text}» - не число.") from exc
    scaled = value * int(scale)
    rounded = round(scaled)
    if abs(scaled - rounded) > 1e-6:
        step = _format_scaled(1, scale)
        raise OptionInputError(f"«{text}»: точность параметра {step}.")
    return int(rounded)


def _is_hex_text(text: str) -> bool:
    return str(text).strip().replace(" ", "").lower().startswith("0x")


def _hex_as_signed(value: int, size: int) -> int:
    """Шестнадцатеричный ввод знакового параметра - это его байты: 0x8000 в int16 даёт -32768."""
    bits = int(size) * 8
    if 0 <= value < (1 << bits) and value >= (1 << (bits - 1)):
        return value - (1 << bits)
    return value


def _pack_int(value: int, size: int, signed: bool) -> bytes:
    low, high = _raw_limits(size, signed)
    if value < low or value > high:
        raise OptionInputError(f"{value} не помещается в {size} байт: допустимо от {low} до {high}.")
    return int(value).to_bytes(int(size), byteorder="little", signed=signed)


def _parse_hex_bytes(text: str, size: int) -> bytes:
    cleaned = re.sub(r"0x", "", str(text), flags=re.IGNORECASE)
    cleaned = re.sub(r"[\s,;:\-]+", "", cleaned)
    if not cleaned:
        raise OptionInputError("Пустой набор байт.")
    if len(cleaned) % 2 != 0 or not re.fullmatch(r"[0-9a-fA-F]+", cleaned):
        raise OptionInputError("Байты вводятся парами шестнадцатеричных цифр: например 0A 00.")
    payload = bytes.fromhex(cleaned)
    if len(payload) > int(size):
        raise OptionInputError(f"Байт {len(payload)}, а параметр вмещает {size}.")
    return payload


def _check_value_limits(value_raw: int, presentation: OptionPresentation, text: str):
    scale = max(1, int(presentation.scale))
    physical = value_raw / scale
    if presentation.min_value is not None and physical < presentation.min_value:
        raise OptionInputError(f"«{text}» меньше допустимого {_format_number(presentation.min_value)}.")
    if presentation.max_value is not None and physical > presentation.max_value:
        raise OptionInputError(f"«{text}» больше допустимого {_format_number(presentation.max_value)}.")
    if presentation.kind == KIND_ENUM and presentation.enum and value_raw not in presentation.enum:
        allowed = ", ".join(str(item) for item in presentation.enum)
        raise OptionInputError(f"Допустимые значения: {allowed}.")


def encode_option_input(parameter: UdsOptionParameter, text: str, mode: str = INPUT_VALUE) -> bytes:
    """Превращает ввод оператора в байты для записи параметра.

    Бросает OptionInputError с понятным текстом, если ввод не подходит:
    не число, не та точность, вне диапазона, лишние байты.
    """
    size = int(parameter.size)
    presentation = option_presentation(parameter)
    kind = presentation.kind
    raw_text = str(text or "")

    if mode == INPUT_BYTES:
        return _parse_hex_bytes(raw_text, size)

    if mode == INPUT_TEXT or (mode == INPUT_VALUE and kind == KIND_TEXT):
        payload = raw_text.encode("utf-8")
        if len(payload) == 0:
            raise OptionInputError("Пустая строка.")
        if len(payload) > size:
            raise OptionInputError(f"Строка занимает {len(payload)} байт, а параметр вмещает {size}.")
        return payload

    if mode == INPUT_RAW:
        if size > 8:
            raise OptionInputError("Параметр длиннее 8 байт: вводите байтами или текстом.")
        value = _parse_integer(raw_text)
        if kind == KIND_INT and _is_hex_text(raw_text):
            value = _hex_as_signed(value, size)
        return _pack_int(value, size, kind == KIND_INT)

    # Ввод в единицах параметра.
    if kind in (KIND_I16_LIST, KIND_LUT_PAIRS):
        parts = [part for part in _NUMBER_SPLIT.split(raw_text.strip()) if part]
        expected = size // 2
        if len(parts) != expected:
            raise OptionInputError(f"Нужно {expected} чисел, введено {len(parts)}.")
        scale = presentation.scale if kind == KIND_I16_LIST else 1
        values = [_parse_scaled(part, scale) for part in parts]
        return b"".join(_pack_int(value, 2, True) for value in values)

    if kind in (KIND_AGE_PAIR, KIND_EEPROM_STATE, KIND_BYTES) or size > 8:
        return _parse_hex_bytes(raw_text, size)

    if kind in (KIND_HEX, KIND_BITS):
        value = _parse_integer(raw_text)
    elif kind == KIND_ENUM:
        # Подходит и «1», и «1 - включена»: берётся первое слово.
        first = raw_text.strip().split(" ", 1)[0] if raw_text.strip() else ""
        value = _parse_integer(first)
    else:
        value = _parse_scaled(raw_text, presentation.scale)
        if kind == KIND_INT and _is_hex_text(raw_text):
            value = _hex_as_signed(value, size)

    _check_value_limits(value, presentation, raw_text.strip())
    return _pack_int(value, size, kind == KIND_INT)


def describe_option_bytes(parameter: UdsOptionParameter, payload: bytes) -> str:
    """Что уйдёт в прибор: значение в единицах параметра и сами байты."""
    formatted = format_option_value(parameter, payload)
    raw = formatted["raw"] or "-"
    display = formatted["display"]
    if display and display != raw:
        return f"{display}  ·  байты: {raw}"
    return f"байты: {raw}"
