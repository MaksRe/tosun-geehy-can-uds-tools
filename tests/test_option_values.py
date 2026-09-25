"""Проверки представления значений в окне параметров UDS.

Окно показывает байты параметра в единицах оператора и принимает запись в тех
же единицах. Ошибка здесь стоит дорого: прибор получит не то число, которое
оператор видел и вводил. Поэтому проверяется и показ, и разбор ввода, и то,
что прочитанное значение, подставленное в поле записи, превращается ровно в те
же байты.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uds.option_values import (
    INPUT_BYTES,
    INPUT_RAW,
    INPUT_TEXT,
    INPUT_VALUE,
    KIND_AGE_PAIR,
    KIND_EEPROM_STATE,
    KIND_I16_LIST,
    KIND_LUT_PAIRS,
    OPTION_GROUPS,
    OptionInputError,
    default_input_mode,
    describe_option_bytes,
    encode_option_input,
    format_option_value,
    option_edit_text,
    option_group,
    option_input_hint,
    option_presentation,
)
from uds.options_catalog import UDS_OPTIONS, get_option_by_did


def _option(did: int):
    option = get_option_by_did(did)
    assert option is not None, f"0x{did:04X} нет в каталоге"
    return option


def _le(value: int, size: int, signed: bool = False) -> bytes:
    return int(value).to_bytes(size, byteorder="little", signed=signed)


# ------------------------------------------------------------------ показ

def test_signed_value_is_shown_with_sign():
    """Подгонка нуля хранится со знаком: 0xFFF4 - это -12, а не 65524."""
    formatted = format_option_value(_option(0x002D), _le(-12, 2, signed=True))
    assert formatted["display"] == "-12 отсч."
    assert formatted["number"] == "-12"
    assert formatted["hex"] == "0xFFF4"
    assert formatted["raw"] == "F4 FF"


def test_temperature_is_shown_in_degrees():
    assert format_option_value(_option(0x003B), _le(253, 2, True))["display"] == "25.3 °C"
    assert format_option_value(_option(0x003B), _le(-405, 2, True))["display"] == "-40.5 °C"


def test_fuel_level_permille_is_shown_in_percent():
    assert format_option_value(_option(0x0018), _le(992, 2, True))["display"] == "99.2 %"


def test_media_coefficient_is_shown_as_fraction():
    assert format_option_value(_option(0x0035), _le(960, 2))["display"] == "0.960"


def test_averaging_window_is_shown_in_seconds():
    assert format_option_value(_option(0x0065), _le(10, 1))["display"] == "10 с"
    assert format_option_value(_option(0x0066), _le(30, 1))["display"] == "30 с"


def test_enum_value_is_named():
    assert format_option_value(_option(0x002E), b"\x01")["display"] == "1 - включена"
    assert format_option_value(_option(0x0053), b"\x00")["display"] == "0 - прежняя"
    assert "неизвестное" in format_option_value(_option(0x0053), b"\x07")["display"]


def test_bits_are_named():
    display = format_option_value(_option(0x0037), b"\x05")["display"]
    assert display == "0x05: коррекция применяется, обновление заморожено"
    assert format_option_value(_option(0x0037), b"\x00")["display"] == "0x00: нет флагов"


def test_text_parameter_is_decoded_up_to_zero():
    payload = b"1.2.3" + b"\x00" * 10
    assert format_option_value(_option(0xF195), payload)["display"] == "1.2.3"
    assert format_option_value(_option(0xF195), b"\x00" * 8)["display"] == "(пусто)"


def test_node_table_is_shown_as_list_in_degrees():
    nodes = [-400, -200, 0, 250, 500, 700, 850]
    payload = b"".join(_le(value, 2, True) for value in nodes)
    display = format_option_value(_option(0x004B), payload)["display"]
    assert display == "-40.0, -20.0, 0.0, 25.0, 50.0, 70.0, 85.0 °C"


def test_board_table_is_shown_as_pairs():
    values = [0, 0, 12, -350] + [0] * 10
    payload = b"".join(_le(value, 2, True) for value in values)
    display = format_option_value(_option(0x004C), payload)["display"]
    assert display.startswith("сдвиг/ppm: 0/0, 12/-350, 0/0")


def test_measurement_age_is_decoded():
    payload = _le(100, 2) + _le(0xFFFF, 2)
    display = format_option_value(_option(0x0064), payload)["display"]
    assert display == "основной 100 мс, вид топлива нет измерений"


def test_eeprom_state_is_decoded():
    display = format_option_value(_option(0x0063), bytes([2, 0x04, 1, 0]))["display"]
    assert "не записано 2" in display
    assert "часть сброшена при включении" in display
    assert "сброшено при включении 1" in display


def test_temperature_emulation_off_marker_is_named():
    assert format_option_value(_option(0x0061), _le(-32768, 2, True))["display"] == "выключена"


def test_empty_value_gives_empty_strings():
    assert format_option_value(_option(0x0065), b"")["display"] == ""
    assert format_option_value(_option(0x0065), None)["raw"] == ""


# ------------------------------------------------------------------ ввод

def test_value_input_uses_parameter_units():
    """Температуру вводят в градусах, в прибор уходит десятые доли."""
    assert encode_option_input(_option(0x0061), "25.3") == _le(253, 2, True)
    assert encode_option_input(_option(0x0061), "-40,5") == _le(-405, 2, True)


def test_value_input_rejects_finer_than_parameter_step():
    with pytest.raises(OptionInputError, match="точность"):
        encode_option_input(_option(0x0061), "25.35")


def test_hex_input_of_signed_parameter_is_its_bytes():
    """Эмуляцию выключают записью 0x8000: для знакового параметра это байты, а не число 32768."""
    payload = encode_option_input(_option(0x0061), "0x8000")
    assert payload == b"\x00\x80"
    assert format_option_value(_option(0x0061), payload)["display"] == "выключена"
    assert encode_option_input(_option(0x002D), "0xFFF4", INPUT_RAW) == _le(-12, 2, True)


def test_signed_value_input():
    assert encode_option_input(_option(0x002D), "-12") == _le(-12, 2, True)


def test_unsigned_parameter_rejects_negative():
    with pytest.raises(OptionInputError):
        encode_option_input(_option(0x0012), "-1")


def test_averaging_window_range_is_enforced():
    """Окно усреднения прибор принимает только 1..60 с - окно не должно пропускать другое."""
    assert encode_option_input(_option(0x0065), "30") == b"\x1e"
    with pytest.raises(OptionInputError, match="больше допустимого 60"):
        encode_option_input(_option(0x0065), "61")
    with pytest.raises(OptionInputError, match="меньше допустимого 1"):
        encode_option_input(_option(0x0066), "0")


def test_enum_input_accepts_only_known_values():
    assert encode_option_input(_option(0x002E), "1") == b"\x01"
    assert encode_option_input(_option(0x002E), "1 - включена") == b"\x01"
    with pytest.raises(OptionInputError, match="Допустимые"):
        encode_option_input(_option(0x002E), "2")


def test_hex_input_for_address():
    assert encode_option_input(_option(0x0011), "0x2F") == b"\x2f"


def test_raw_input_packs_integer():
    assert encode_option_input(_option(0x0061), "253", INPUT_RAW) == _le(253, 2, True)
    with pytest.raises(OptionInputError, match="не помещается"):
        encode_option_input(_option(0x0065), "300", INPUT_RAW)


def test_text_input_and_length_limit():
    assert encode_option_input(_option(0xF195), "1.0.0.97") == b"1.0.0.97"
    with pytest.raises(OptionInputError, match="вмещает 17"):
        encode_option_input(_option(0xF190), "X" * 18, INPUT_TEXT)


def test_bytes_input():
    assert encode_option_input(_option(0x0063), "02 04 01 00", INPUT_BYTES) == bytes([2, 4, 1, 0])
    with pytest.raises(OptionInputError, match="парами"):
        encode_option_input(_option(0x0065), "ABC", INPUT_BYTES)


def test_list_input_requires_exact_count():
    with pytest.raises(OptionInputError, match="Нужно 7 чисел"):
        encode_option_input(_option(0x004B), "-40, -20, 0")
    payload = encode_option_input(_option(0x004B), "-40, -20, 0, 25, 50, 70, 85")
    assert payload[:2] == _le(-400, 2, True)


def test_empty_input_is_rejected():
    with pytest.raises(OptionInputError):
        encode_option_input(_option(0x0065), "  ")


def test_describe_bytes_shows_value_and_bytes():
    text = describe_option_bytes(_option(0x0065), b"\x0a")
    assert text == "10 с  ·  байты: 0A"


# ------------------------------------------------------------------ весь каталог

def _sample_payload(option, rng: random.Random) -> bytes:
    """Правдоподобные байты параметра в пределах его диапазона."""
    presentation = option_presentation(option)
    size = int(option.size)
    if presentation.enum:
        return _le(rng.choice(list(presentation.enum)), size)
    if presentation.min_value is not None and presentation.max_value is not None:
        low = int(presentation.min_value * max(1, presentation.scale))
        high = int(presentation.max_value * max(1, presentation.scale))
        return _le(rng.randint(low, high), size)
    if option_presentation(option).kind == "text":
        text = "".join(rng.choice("ABC123.-") for _ in range(min(size, 6)))
        return text.encode("ascii") + b"\x00" * (size - len(text))
    return bytes(rng.randrange(256) for _ in range(size))


@pytest.mark.parametrize("option", [item for item in UDS_OPTIONS if item.can_write],
                         ids=lambda item: f"0x{int(item.did):04X}")
def test_read_value_put_into_editor_writes_same_bytes(option):
    """Прочитанное значение, подставленное в поле записи, должно записаться теми же байтами."""
    rng = random.Random(int(option.did))
    for _ in range(20):
        payload = _sample_payload(option, rng)
        mode = default_input_mode(option)
        text = option_edit_text(option, payload, mode)
        encoded = encode_option_input(option, text, mode)
        stored = encoded + b"\x00" * (len(payload) - len(encoded))
        assert stored == payload, f"0x{int(option.did):04X}: ввод «{text}» дал {encoded.hex()}"


@pytest.mark.parametrize("option", UDS_OPTIONS, ids=lambda item: f"0x{int(item.did):04X}")
def test_every_parameter_can_be_shown(option):
    """Любые байты любого параметра должны показываться без исключений."""
    rng = random.Random(int(option.did) + 1)
    payload = bytes(rng.randrange(256) for _ in range(int(option.size)))
    formatted = format_option_value(option, payload)
    assert formatted["display"]
    assert formatted["raw"]
    assert option_input_hint(option, default_input_mode(option))
    assert option_group(option.did) in OPTION_GROUPS


def test_structured_parameters_have_matching_sizes():
    """Списки и пары занимают чётное число байт, составные поля - ровно 4."""
    for option in UDS_OPTIONS:
        kind = option_presentation(option).kind
        if kind in (KIND_I16_LIST, KIND_LUT_PAIRS):
            assert int(option.size) % 2 == 0, f"0x{int(option.did):04X}"
        if kind in (KIND_AGE_PAIR, KIND_EEPROM_STATE):
            assert int(option.size) == 4, f"0x{int(option.did):04X}"


def test_removed_temperature_compensation_is_not_offered():
    """Номера прежней компенсации прибор отвергает - в окне их быть не должно."""
    for did in range(0x001B, 0x002D):
        assert get_option_by_did(did) is None, f"0x{did:04X} остался в каталоге"


def test_every_input_mode_has_a_hint():
    option = _option(0x0065)
    for mode in (INPUT_VALUE, INPUT_RAW, INPUT_TEXT, INPUT_BYTES):
        assert option_input_hint(option, mode)
