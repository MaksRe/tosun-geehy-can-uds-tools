"""Проверки «Профиль из камеры: проверка на столе».

Проверка идёт перед сборкой плат в корпус. Если она пропустит плату с чужим или
неприменяемым профилем, ошибка всплывёт только в следующем прогоне камеры. Если
будет ругать исправную плату, по ней начнут зря перепрошивать профиль. Поэтому
здесь закреплены её решения на известных ответах прибора, сверка с файлом из
камеры и очередь нескольких плат, где калибровка переходит от платы к плате.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import profile_model
from tests.test_trial import _FakeTimer, _TrialStub
from ui.qml.controller.bench_profile_mixin import AppControllerBenchProfileMixin
from ui.qml.controller.profile_mixin import AppControllerProfileMixin


# Профиль платы П1 из прогона 28.10: только множители ступени платы, трубок нет.
CHAMBER_PROFILE = {
    "nodes": [-400, -200, 0, 250, 500, 700, 850],
    "board_main": [0, -662, 0, -441, 0, -441, 0, 0, 0, 0, 0, 1103, 0, 1764],
    "board_media": [0, -1121, 0, -673, 0, -224, 0, 0, 0, 449, 0, 2018, 0, 4037],
    "tube_air_main": [0] * 7,
    "tube_full_main": [0] * 7,
    "tube_air_media": [0] * 7,
    "tube_full_media": [0] * 7,
}


class _BenchStub(AppControllerBenchProfileMixin, _TrialStub):
    """Пробная калибровка без шины плюс проверка профиля на столе."""

    PROFILE_TABLES = AppControllerProfileMixin.PROFILE_TABLES

    def __init__(self, folder: Path | None = None):
        super().__init__()
        self._bench_active = False
        self._bench_queue = []
        self._bench_current = None
        self._bench_stage = ""
        self._bench_stage_since = 0.0
        self._bench_opened = False
        self._bench_board_opened = False
        self._bench_stop_requested = False
        self._bench_switch_since = None
        self._bench_results = {}
        self._bench_order = []
        self._bench_timer = _FakeTimer()

        self._profile_values = {name: list(values) for name, values in CHAMBER_PROFILE.items()}
        self._profile_device_crc = 0xA7E7
        self._profile_device_crc_actual = 0xA7E7
        self._profile_status = "Профиль прочитан."
        self._calibration_waiting_session = False
        self.folder = folder
        self.calibration_starts = 0
        self.calibration_stops = 0

    def _chamber_journal_dirs(self):
        return [self.folder] if self.folder is not None else []

    def startCalibration(self):
        self.calibration_starts += 1
        self._calibration_active = True

    def stopCalibration(self):
        self.calibration_stops += 1
        self._calibration_active = False


class _MultiBenchStub(_BenchStub):
    """Несколько плат: показ платы и переход калибровки от платы к плате."""

    def __init__(self, folder: Path | None = None):
        super().__init__(folder)
        self._mb_boards = [{"sa": 0x81, "name": "П1"}, {"sa": 0x82, "name": "П2"}]
        self._mb_active_sa = 0x81
        self.activated = []
        self.closed = 0

    def _mb_on(self):
        return True

    def _mb_name(self, sa):
        return next(board["name"] for board in self._mb_boards if board["sa"] == sa)

    def _mb_profiles_busy(self):
        return False

    def _mb_calibration_free_for(self, sa, now):
        return True

    def _mb_activate(self, sa, force=False):
        self.activated.append(sa)
        self._mb_active_sa = sa
        self._service_access_target_sa = sa
        return True

    def _resolve_calibration_target_sa(self):
        return self._mb_active_sa

    def _mb_calibration_close(self):
        self.closed += 1


def _answers(stub, profile=None, raw=7000, shift_at=None, emul_after=-32768):
    """Ответы прибора, который считает точно по формулам прошивки с профилем profile."""
    profile = profile or CHAMBER_PROFILE
    answers = {"profile_started": True, "profile_read": True, "emul_off": True, "status": 0x0F, "zero_trim": 0,
               "emul_off_end": True, "emul_after": emul_after}
    now = profile_model.predict_main(raw, profile, board_temp_x10=243, tube_temp_x10=241, trusted=True)
    answers.update({"now_board_t": 243, "now_fuel_t": 241, "now_raw_a": raw, "now_raw_b": raw,
                    "now_board": now["board_stage"], "now_comp": now["compensated"]})
    for index, temperature in enumerate(stub.TRIAL_APPLY_TEMPS_X10):
        prediction = profile_model.predict_main(raw, profile, board_temp_x10=temperature,
                                                tube_temp_x10=temperature, trusted=True)
        answers.update({
            f"w{index}": True, f"raw_a{index}": raw, f"raw_b{index}": raw,
            f"board{index}": prediction["board_stage"],
            f"comp{index}": prediction["compensated"] + (10 if shift_at == index else 0),
            f"mode{index}": prediction["mode_main"],
        })
    return answers


def _write_profile_file(folder: Path, sa: int, tables=None, crc=0xA7E7) -> Path:
    path = folder / f"chamber_20261028_114805_П1_0x{sa:02X}_profile.json"
    path.write_text(json.dumps({"формат": 1, "контрольная_сумма": crc,
                                "таблицы": tables or CHAMBER_PROFILE}, ensure_ascii=False), encoding="utf-8")
    return path


def _run_one(stub, answers):
    """Проводит плату через доступ и обмен: обмен подменён готовыми ответами."""
    ok, problem = stub._bench_start(False)
    assert ok, problem
    stub._bench_tick()
    ops, handler = stub.started[-1]
    assert handler == "_bench_ops_done"
    getattr(stub, handler)(answers)
    return ops


def _result(stub, sa):
    return stub._bench_results[sa]


# ------------------------------------------------------------------ одна плата

def test_profile_from_the_chamber_passes_on_the_bench(tmp_path: Path):
    stub = _BenchStub(tmp_path)
    _write_profile_file(tmp_path, 0x2A)
    ops = _run_one(stub, _answers(stub))
    result = _result(stub, 0x2A)
    assert result["status"] == "pass", result
    assert "поправка от" in result["summary"]
    assert "все таблицы совпали" in result["detail"]
    assert not stub._bench_active
    # В память прибора ничего не пишется: записи только эмуляции (0x0061).
    writes = {int(op["var"].pid) for op in ops if op["kind"] == "write"}
    assert writes == {0x0061}


def test_without_a_chamber_file_it_is_a_remark_not_a_failure(tmp_path: Path):
    stub = _BenchStub(tmp_path)
    _run_one(stub, _answers(stub))
    result = _result(stub, 0x2A)
    assert result["status"] == "warn"
    assert "не найден" in result["summary"]


def test_a_different_profile_in_the_board_is_caught(tmp_path: Path):
    stub = _BenchStub(tmp_path)
    other = dict(CHAMBER_PROFILE, board_main=[0, -600] + CHAMBER_PROFILE["board_main"][2:])
    _write_profile_file(tmp_path, 0x2A, tables=other)
    _run_one(stub, _answers(stub))
    result = _result(stub, 0x2A)
    assert result["status"] == "fail"
    assert "не тот профиль" in result["summary"]
    assert "плата, основной" in result["summary"]


def test_newest_file_of_the_board_is_used(tmp_path: Path):
    import os
    stub = _BenchStub(tmp_path)
    old = _write_profile_file(tmp_path, 0x2A, tables=dict(CHAMBER_PROFILE, board_main=[0] * 14))
    os.utime(old, (1_000_000, 1_000_000))
    newer = tmp_path / "run2"
    newer.mkdir()
    _write_profile_file(newer, 0x2A)
    assert stub._bench_profile_file(0x2A).parent == newer


def test_wrong_compensation_names_the_temperature(tmp_path: Path):
    stub = _BenchStub(tmp_path)
    _write_profile_file(tmp_path, 0x2A)
    _run_one(stub, _answers(stub, shift_at=0))
    result = _result(stub, 0x2A)
    assert result["status"] == "fail"
    assert "-40.0 °C" in result["summary"]


def test_empty_profile_in_the_board_fails(tmp_path: Path):
    stub = _BenchStub(tmp_path)
    empty = dict(CHAMBER_PROFILE, board_main=[0] * 14)
    stub._profile_values = {name: list(values) for name, values in empty.items()}
    _run_one(stub, _answers(stub, profile=empty))
    assert _result(stub, 0x2A)["status"] == "fail"
    assert "пустая" in _result(stub, 0x2A)["summary"]


def test_emulation_left_on_is_a_failure(tmp_path: Path):
    stub = _BenchStub(tmp_path)
    _write_profile_file(tmp_path, 0x2A)
    _run_one(stub, _answers(stub, emul_after=850))
    assert _result(stub, 0x2A)["status"] == "fail"
    assert "эмуляция" in _result(stub, 0x2A)["summary"]


def test_access_is_opened_by_the_check_and_closed_after(tmp_path: Path):
    stub = _BenchStub(tmp_path)
    _write_profile_file(tmp_path, 0x2A)
    stub._calibration_active = False
    stub._service_security_unlocked = False
    ok, _ = stub._bench_start(False)
    assert ok
    stub._bench_tick()
    assert stub.calibration_starts == 1
    # Доступ открылся: обмен запускается.
    stub._service_security_unlocked = True
    stub._bench_tick()
    ops, handler = stub.started[-1]
    getattr(stub, handler)(_answers(stub))
    assert _result(stub, 0x2A)["status"] == "pass"
    assert stub.calibration_stops == 1


def test_session_that_never_opens_fails_the_board():
    stub = _BenchStub()
    stub._calibration_active = False
    stub._service_security_unlocked = False
    stub.startCalibration = lambda: None
    stub._bench_start(False)
    stub._bench_tick()
    stub._bench_tick()
    assert _result(stub, 0x2A)["status"] == "fail"
    assert "не открыла сеанс" in _result(stub, 0x2A)["summary"]


def test_refused_while_trial_is_busy():
    stub = _BenchStub()
    stub._trial_busy = True
    ok, problem = stub._bench_start(False)
    assert not ok
    assert "пробная калибровка" in problem


def test_trial_steps_are_closed_while_the_check_runs():
    stub = _BenchStub()
    stub._bench_active = True
    assert not stub._trial_run_step("link")
    assert not stub._trial_auto_start()


# ------------------------------------------------------------------ несколько плат

def test_all_boards_are_checked_one_by_one(tmp_path: Path):
    stub = _MultiBenchStub(tmp_path)
    _write_profile_file(tmp_path, 0x81)
    _write_profile_file(tmp_path, 0x82)
    ok, _ = stub._bench_start(True)
    assert ok
    for sa in (0x81, 0x82):
        stub._bench_tick()
        assert stub._mb_active_sa == sa
        ops, handler = stub.started[-1]
        getattr(stub, handler)(_answers(stub))
    stub._bench_tick()
    assert [row["status"] for row in stub._bench_view()["rows"]] == ["pass", "pass"]
    assert stub.activated == [0x81, 0x82]
    assert stub.closed == 1
    assert not stub._bench_active
    assert "у 2 из 2 плат" in stub._trial_status


def test_shown_board_only(tmp_path: Path):
    stub = _MultiBenchStub(tmp_path)
    stub._mb_active_sa = 0x82
    stub._bench_start(False)
    assert stub._bench_order == [0x82]


def test_stop_finishes_the_current_board_and_skips_the_rest(tmp_path: Path):
    stub = _MultiBenchStub(tmp_path)
    stub._bench_start(True)
    stub._bench_tick()
    ops, handler = stub.started[-1]
    stub._bench_stop()
    assert stub._bench_active
    getattr(stub, handler)(_answers(stub))
    rows = stub._bench_view()["rows"]
    assert rows[0]["status"] in ("pass", "warn")
    assert rows[1]["status"] == "skip"
    assert not stub._bench_active


def test_protocol_lists_every_board(tmp_path: Path):
    stub = _MultiBenchStub(tmp_path)
    _write_profile_file(tmp_path, 0x81)
    stub._bench_start(False)
    stub._bench_tick()
    getattr(stub, stub.started[-1][1])(_answers(stub))
    target = tmp_path / "protocol.txt"
    stub._trial_step_rows = lambda: []
    stub._trial_summary = lambda: "этапы не запускались"
    assert stub._trial_save_protocol(str(target))
    text = target.read_text(encoding="utf-8")
    assert "Профиль из камеры, проверка на столе:" in text
    assert "П1 (0x81): профиль работает" in text
