"""Проверка профиля и калибровки плат перед проверочным прогоном (12.11.2026).

Тесты закрепляют:
- оценку прочитанного: полный применённый профиль с калибровкой - в порядке; пустой профиль, нет
  строк трубки, нет калибровки, включённая поправка по виду топлива без эталонов - недостатки;
  отметка 0 % далеко от строки трубки при +25 °C - предупреждение;
- обмен: программа сама читает каждую плату на шине по очереди, а проверка перед стартом не даёт
  начать, пока чтение идёт или у платы чего-то не хватает; плата без ответа - понятная причина.
"""

from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_multiboard import BOARDS, _stub, _with_control
from ui.qml.controller.profile_audit_mixin import (AUDIT_ITEMS, AppControllerProfileAuditMixin,
                                                   profile_audit_verdict)

NODES = [-400, -200, 0, 250, 500, 700, 850]
AIR = [15300, 15350, 15420, 15480, 15530, 15600, 15650]


def _good_values() -> dict:
    full = [value + 11785 for value in AIR]
    return {"status": 0x0F, "crc": 0xCF09, "nodes": list(NODES),
            "board_main": [12, 400, 6, 200, 3, 100, 0, 0, -4, -150, -9, -300, -14, -450],
            "board_media": [8, 300, 4, 150, 2, 80, 0, 0, -3, -90, -6, -200, -10, -320],
            "tube_air_main": list(AIR), "tube_full_main": full,
            "tube_air_media": [10500 + i for i in range(7)], "tube_full_media": [14500 + i for i in range(7)],
            "empty": AIR[3], "full": full[3], "media_on": 1, "media_air": 10564, "media_cal": 14523,
            "two_contour": 0, "two_empty": 0, "two_full": 0}


def test_full_profile_with_calibration_is_fine():
    verdict = profile_audit_verdict(_good_values())
    assert verdict["problems"] == [] and verdict["notes"] == []
    assert "сумма 0xCF09" in verdict["summary"] and "0 % = 15480" in verdict["summary"]
    assert "поправка по виду топлива включена" in verdict["summary"]


def test_missing_parts_are_problems():
    values = dict(_good_values(), status=0x00)
    assert any("профиль пустой" in text for text in profile_audit_verdict(values)["problems"])
    values = dict(_good_values(), status=0x07)
    assert any("не применяются" in text for text in profile_audit_verdict(values)["problems"])
    values = dict(_good_values(), tube_air_main=[0] * 7, tube_full_main=[0] * 7)
    problems = profile_audit_verdict(values)["problems"]
    assert any("второго этапа в профиле нет" in text for text in problems), problems
    values = dict(_good_values(), empty=0, full=0)
    assert any("калибровка не записана" in text for text in profile_audit_verdict(values)["problems"])
    values = dict(_good_values(), media_air=0, tube_full_media=[0] * 7)
    problems = profile_audit_verdict(values)["problems"]
    assert any("эталоны не записаны" in text for text in problems)
    assert any("вид топлива в жидкости" in text for text in problems)
    # Поправка выключена - строки вида топлива и эталоны не нужны.
    values = dict(_good_values(), media_on=0, media_air=0, tube_full_media=[0] * 7)
    assert profile_audit_verdict(values)["problems"] == []
    values = dict(_good_values(), two_contour=1)
    assert any("двум контурам" in text for text in profile_audit_verdict(values)["problems"])


def test_zero_mark_far_from_profile_air_is_a_warning():
    values = dict(_good_values(), empty=AIR[3] + 90)  # 90 отсч. при размахе ~11700 - 0,77 % уровня
    verdict = profile_audit_verdict(values)
    assert verdict["problems"] == []
    assert len(verdict["notes"]) == 1 and "отметка 0 %" in verdict["notes"][0] and "+90 отсч." in verdict["notes"][0]


def _pack(name: str, value) -> bytes:
    if isinstance(value, list):
        return b"".join(struct.pack("<h", int(item)) for item in value)
    if name in ("status", "media_on", "two_contour"):
        return bytes([int(value)])
    return struct.pack("<H", int(value))


def _audit_stub(tmp_path: Path):
    stub = _with_control(_stub(tmp_path))
    stub.__class__ = type("_AuditStub", (AppControllerProfileAuditMixin, stub.__class__), {})
    stub._can = type("Can", (), {"is_connect": True, "is_trace": True})()
    stub.sent = []

    def start(parameter, request_origin, append_history, target_sa_override=None):
        stub.sent.append((int(target_sa_override), int(parameter.did), request_origin))
        return True

    stub._start_options_read_request = start
    return stub


def _serve(stub, devices: dict, limit: int = 500):
    """Отвечает на запросы чтения, как ответили бы платы: devices[sa] - значения или None (молчит)."""
    names = {did: name for name, did, _required in AUDIT_ITEMS}
    for _ in range(limit):
        if not stub._profile_audit_busy():
            return
        before = len(stub.sent)
        stub._profile_audit_tick(time.monotonic())
        if len(stub.sent) == before:
            continue
        sa, did, origin = stub.sent[-1]
        values = devices.get(sa)
        if values is None:
            stub._handle_profile_audit_options_result(success=False, request_origin=origin, pending_action="read",
                                                      pending_did=did, value_bytes=b"",
                                                      message="Таймаут ожидания ответа UDS (не получен SF/FF).")
            continue
        stub._handle_profile_audit_options_result(success=True, request_origin=origin, pending_action="read",
                                                  pending_did=did, value_bytes=_pack(names[did], values[names[did]]),
                                                  message="")
    raise AssertionError("чтение не закончилось")


def test_check_run_waits_for_profiles_and_blocks_on_incomplete_board(tmp_path: Path):
    stub = _audit_stub(tmp_path)
    assert stub._climate_scenario_new("check")
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert not checks["profiles"]["ok"] and "Читаю профиль" in checks["profiles"]["text"]
    assert any("Читаю профиль" in text for text in stub._climate_auto_blockers())

    bad = dict(_good_values(), tube_air_main=[0] * 7)
    _serve(stub, {0x80: _good_values(), 0x81: bad, 0x82: _good_values()})
    assert {sa for sa, _did, _origin in stub.sent} == {sa for sa, *_rest in BOARDS}
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert "profiles" not in checks
    assert not checks["profile_81"]["ok"] and "второго этапа в профиле нет" in checks["profile_81"]["text"]
    assert checks["profiles_ok"]["ok"] and "0x80" in checks["profiles_ok"]["text"]
    assert any("0x81" in text for text in stub._climate_auto_blockers())

    # Профиль переписан - «Перечитать профили плат» читает заново, и старт разрешён.
    assert stub._profile_audit_start(force=True) == 3
    _serve(stub, {sa: _good_values() for sa, *_rest in BOARDS})
    assert not any("профил" in text.lower() for text in stub._climate_auto_blockers())
    lines = stub._profile_audit_log_lines()
    assert len(lines) == 3 and all("сумма 0xCF09" in line for line in lines)


def test_silent_board_is_named_and_blocks(tmp_path: Path):
    stub = _audit_stub(tmp_path)
    assert stub._climate_scenario_new("check")
    stub._climate_auto_checks()
    _serve(stub, {0x80: _good_values(), 0x81: _good_values(), 0x82: None})
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert not checks["profile_82"]["ok"] and "плата не отвечает" in checks["profile_82"]["text"]
    # Повтор того же параметра был, прежде чем сдаться.
    asked = [did for sa, did, _origin in stub.sent if sa == 0x82]
    assert asked == [0x0060, 0x0060]


def test_ordinary_run_does_not_read_profiles(tmp_path: Path):
    stub = _audit_stub(tmp_path)
    assert stub._climate_scenario_new("assembly")
    checks = {item["key"] for item in stub._climate_auto_checks()}
    assert "profiles" not in checks and not stub._profile_audit_busy() and stub.sent == []
