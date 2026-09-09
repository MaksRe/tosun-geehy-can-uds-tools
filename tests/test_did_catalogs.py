"""Проверки согласованности двух каталогов DID.

В проекте карта параметров описана дважды: UdsData используется калибровкой и
коллектором, UDS_OPTIONS - окном параметров. Дубликат уже приводил к расхождению:
отпечаток пальцев был записан как 0x1500 вместо 0x0015 и через калибровочный путь
не читался вовсе.

Тесты ниже не дают этому повториться и заодно ловят опечатки в самих значениях.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uds.data_identifiers import UdsData
from uds.options_catalog import UDS_OPTIONS, AccessMode, get_option_by_did


def _vars_by_did() -> dict[int, tuple[str, int]]:
    """Возвращает карту DID -> (ключ, размер) из каталога UdsData."""
    result: dict[int, tuple[str, int]] = {}
    for key, var in UdsData.vars.items():
        result[int(var.pid) & 0xFFFF] = (key, int(var.size))
    return result


def test_uds_data_has_no_duplicate_dids():
    """Один DID не должен встречаться в UdsData дважды под разными именами."""
    seen: dict[int, str] = {}
    duplicates: list[str] = []

    for key, var in UdsData.vars.items():
        did = int(var.pid) & 0xFFFF
        if did in seen:
            duplicates.append(f"0x{did:04X}: {seen[did]} и {key}")
        else:
            seen[did] = key

    assert not duplicates, "Повторяющиеся DID: " + "; ".join(duplicates)


def test_options_catalog_has_no_duplicate_dids():
    """Один DID не должен встречаться в UDS_OPTIONS дважды."""
    seen: set[int] = set()
    duplicates: list[str] = []

    for item in UDS_OPTIONS:
        did = int(item.did) & 0xFFFF
        if did in seen:
            duplicates.append(f"0x{did:04X}")
        else:
            seen.add(did)

    assert not duplicates, "Повторяющиеся DID: " + ", ".join(duplicates)


def test_sizes_match_between_catalogs():
    """Размер параметра должен совпадать в обоих каталогах."""
    mismatches: list[str] = []

    for did, (key, size) in _vars_by_did().items():
        option = get_option_by_did(did)
        if option is None:
            continue
        if int(option.size) != size:
            mismatches.append(
                f"0x{did:04X} ({key}): UdsData={size}, UDS_OPTIONS={option.size}"
            )

    assert not mismatches, "Расходятся размеры: " + "; ".join(mismatches)


def test_every_uds_data_did_is_described_in_options():
    """Каждый DID из UdsData должен быть описан в каталоге окна параметров."""
    missing = [
        f"0x{did:04X} ({key})"
        for did, (key, _size) in sorted(_vars_by_did().items())
        if get_option_by_did(did) is None
    ]

    assert not missing, "Нет в UDS_OPTIONS: " + ", ".join(missing)


def test_fingerprint_did_is_0x0015():
    """Отдельная проверка на уже случавшуюся опечатку в номере DID."""
    assert int(UdsData.fingerprint.pid) & 0xFFFF == 0x0015


@pytest.mark.parametrize(
    "did, name",
    [
        (0x002E, "включение коррекции по виду топлива"),
        (0x002F, "плоский конденсатор в воздухе"),
        (0x0030, "плоский конденсатор в жидкости"),
        (0x0035, "текущий коэффициент среды"),
        (0x0037, "состояние коррекции"),
        (0x003A, "источник температуры компенсации"),
        (0x003B, "температура платы"),
        (0x003E, "максимум размаха, основной контур"),
        (0x0042, "перезахваты контура вида топлива"),
    ],
)
def test_new_dids_present(did: int, name: str):
    """Ключевые параметры второго контура должны быть в обоих каталогах."""
    assert get_option_by_did(did) is not None, f"{name}: нет в UDS_OPTIONS"
    assert UdsData.get_var_by_pid(did) is not None, f"{name}: нет в UdsData"


@pytest.mark.parametrize(
    "did",
    [0x0035, 0x0036, 0x0037, 0x0038, 0x003B, 0x003C, 0x003D, 0x003E, 0x003F, 0x0040, 0x0041, 0x0042],
)
def test_runtime_telemetry_is_read_only(did: int):
    """Величины из ОЗУ прошивка отдаёт только на чтение, запись должна быть закрыта."""
    option = get_option_by_did(did)
    assert option is not None, f"0x{did:04X} отсутствует в каталоге"
    assert option.access == AccessMode.READ, (
        f"0x{did:04X} помечен как {option.access.value}, ожидалось только чтение"
    )
    assert not option.can_write
