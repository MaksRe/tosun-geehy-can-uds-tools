"""Журналы первого этапа всем платам одной кнопкой (перед вторым этапом с трубками).

Тесты закрепляют:
- адрес платы берётся из имени журнала (…_П2_0x82.csv, и у копии …_0x82_копия_<время>.csv);
- в списке журналов у каждого - адрес платы и число узлов первого этапа;
- кнопка открывает каждой плате её журнал с наибольшим числом узлов: копия «на 3 точки»,
  даже свежее, не перебивает полный журнал на 7 узлов из подпапки; журнал старше 40 файлов
  списка тоже находится;
- плате без журнала первого этапа - понятная причина, остальным журналы открываются;
- «Открыть» не кладёт журнал другой платы списка в поля показанной платы;
- проверка второго этапа после кнопки - пройдена.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_fit
from tests.test_multiboard import BOARDS, _stub, _with_control
from ui.qml.controller.chamber_mixin import journal_sa, stage1_nodes


def _journal(stub, path: Path, temps, stamp: float):
    """Журнал первого этапа «только плата»: по точке в каждом узле из temps."""
    lines = [";".join(stub.CHAMBER_COLUMNS)]
    for index, temp in enumerate(temps):
        value = f"{temp:.1f}".replace(".", ",")
        lines.append(f"11:{index:02d}:00;0/0;4535;4459;{value};{value};;{value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    os.utime(path, (stamp, stamp))
    return path


ALL = [node / 10 for node in chamber_fit.NODES_X10]


def test_board_address_is_read_from_the_journal_name():
    assert journal_sa("chamber_20261028_114806_П2_0x82.csv") == 0x82
    assert journal_sa("chamber_20261028_114806_П2_0x82_копия_20261106_101500.csv") == 0x82
    assert journal_sa("chamber_20261028_114806.csv") is None
    points = [{"board_temp_x10": 250, "note": "0/0"}, {"board_temp_x10": -400, "note": "0/0", "rehearsal": True}]
    assert stage1_nodes(points) == [250]


def test_button_opens_every_board_its_fullest_journal(tmp_path: Path):
    stub = _with_control(_stub(tmp_path))
    own = stub._chamber_autosave_directory()
    old = time.time() - 9 * 86400
    # П2: полный журнал в подпапке и свежая копия «на 3 точки» с тем же адресом.
    full = _journal(stub, own / "chamber_from_v20" / "chamber_20261028_114806_П2_0x81.csv", ALL, old)
    _journal(stub, own / "chamber_20261028_114806_П2_0x81_копия_20261106_101500.csv", [25.0, 50.0, 85.0], time.time())
    # П1: полный журнал, а сверху - 45 свежих журналов без адреса (полный уже не в первых 40 списка).
    _journal(stub, own / "chamber_from_v20" / "chamber_20261028_114805_П1_0x80.csv", ALL, old)
    for index in range(45):
        _journal(stub, own / f"chamber_20261105_{index:06d}.csv", [25.0], time.time() - index)
    listed = stub._chamber_journals(fresh=True)
    assert len(listed) == 40 and all(item["sa"] != 0x80 for item in listed), "полный журнал П1 - ниже 40-го"
    index = {item["name"]: item for item in stub._chamber_journal_index()}
    assert index[full.name]["sa"] == 0x81 and index[full.name]["nodes"] == 7

    ok, text, _details = stub._control_do_journal_stage1({}, {})
    assert not ok, "у П3 журнала нет"
    assert stub._mb_status.startswith("Журналы первого этапа: ")
    for sa, name, *_rest in BOARDS:
        with stub._mb_context(sa):
            nodes = stage1_nodes(stub._chamber_points)
            if name == "П3":
                assert nodes == [] and f"«П3»: журнала первого этапа с адресом 0x{sa:02X} на диске нет" in text
            else:
                assert len(nodes) == 7, (name, text)
                assert f"_0x{sa:02X}" in Path(stub._chamber_file_path).name
    # Второй раз: открытые полные журналы не трогаются.
    _ok, again, _details = stub._control_do_journal_stage1({}, {})
    assert "«П1»: уже открыт" in again and "«П2»: уже открыт" in again


def test_open_refuses_a_journal_of_another_board(tmp_path: Path):
    stub = _stub(tmp_path)
    own = stub._chamber_autosave_directory()
    other = _journal(stub, own / "chamber_20261028_114806_П2_0x81.csv", ALL, time.time())
    assert stub._mb_active_sa == 0x80
    ok, text = stub._chamber_open_journal(str(other))
    assert not ok and "это журнал платы «П2» (0x81), а показана «П1» (0x80)" in text
    assert stub._chamber_points == []
    assert stub._mb_activate(0x81)
    ok, text = stub._chamber_open_journal(str(other))
    assert ok, text


def test_stage2_check_passes_after_the_button(tmp_path: Path):
    stub = _stub(tmp_path)
    own = stub._chamber_autosave_directory()
    for sa, name, *_rest in BOARDS:
        _journal(stub, own / f"chamber_20261028_114806_{name}_0x{sa:02X}.csv", ALL, time.time())
    checks = []
    stub._climate_auto_stage2_checks(lambda key, ok, text, level="block": checks.append((ok, text)), False)
    assert not checks[0][0] and "Журналы первого этапа всем платам" in checks[0][1]
    assert stub._mb_open_stage1_journals()[0]
    checks = []
    stub._climate_auto_stage2_checks(lambda key, ok, text, level="block": checks.append((ok, text)), False)
    assert checks[0][0], checks[0][1]


def test_first_board_journal_without_address_is_found_by_its_profile(tmp_path: Path):
    """Первая плата снималась одна: журнал без адреса в имени, а потом - неполный журнал с адресом."""
    import json

    stub = _stub(tmp_path)
    own = stub._chamber_autosave_directory()
    alone = _journal(stub, own / "old" / "chamber_20261020_011249.csv", ALL, time.time() - 17 * 86400)
    alone.with_name(f"{alone.stem}_profile.json").write_text(
        json.dumps({"контрольная_сумма": 0x66E8}, ensure_ascii=False), encoding="utf-8")
    # Чужой журнал без адреса и с другим профилем, свежее, - не её.
    other = _journal(stub, own / "chamber_20261021_090000.csv", ALL, time.time() - 86400)
    other.with_name(f"{other.stem}_profile.json").write_text(json.dumps({"контрольная_сумма": 0x1234}), encoding="utf-8")
    _journal(stub, own / "chamber_20261102_163042_П3_0x82.csv", [25.0, 50.0, 70.0, 85.0], time.time())
    stub._addr_info = {0x82: {"profileCrc": 0x66E8}}
    _ok, text = stub._mb_open_stage1_journals()
    with stub._mb_context(0x82):
        assert Path(stub._chamber_file_path).name == alone.name, text
        assert len(stage1_nodes(stub._chamber_points)) == 7
    assert "по нему посчитан профиль в плате" in text
    # П1 и П2 без журналов: чужой журнал без адреса им не достался.
    for sa in (0x80, 0x81):
        with stub._mb_context(sa):
            assert stub._chamber_points == [], text
