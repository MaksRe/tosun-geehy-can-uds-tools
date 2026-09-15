"""Проверки пробной калибровки на столе.

Пробная калибровка решает, идти ли в камеру. Если она пропустит неисправность,
выезд пропадёт впустую. Если будет ругать исправный прибор, её перестанут
запускать. Поэтому здесь закреплены её решения на известных ответах прибора:
что считается пройденным, что нет, и какими словами это объясняется.

Отдельно закреплены автоматический прогон, где отказ после запоминания настроек
обязан вернуть их в прибор, и постоянный показ отсчётов, который не должен
разрывать замеры этапов.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_fit
import profile_model
from ui.qml.controller.profile_mixin import AppControllerProfileMixin
from ui.qml.controller.trial_mixin import TRIAL_EMULATION_OFF_VALUE, AppControllerTrialMixin
from uds.data_identifiers import UdsData


class _Signal:
    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _FakeTimer:
    def __init__(self):
        self.started = 0

    def start(self, *args):
        self.started += 1

    def stop(self):
        pass

    def isActive(self):
        return False


class _FakeRead:
    def __init__(self):
        self.sent = []

    def read_data_by_identifier(self, identifier, var):
        self.sent.append(int(var.pid))
        return True


class _FakeWrite:
    def __init__(self):
        self.sent = []

    def write_data(self, var, value, tx_identifier=None):
        self.sent.append((int(var.pid), int(value)))
        return True


class _FakeCan:
    is_connect = True
    is_trace = True


class _TrialStub(AppControllerTrialMixin):
    """Носитель логики пробной калибровки без Qt и без шины.

    Запуск очереди подменён: вместо обмена с прибором очередь запоминается, а
    проверки сами вызывают обработчик итога с заранее известными ответами.
    """

    def __init__(self):
        self.trialChanged = _Signal()
        self.trialLiveChanged = _Signal()
        self.profileChanged = _Signal()
        self.infoMessage = _Signal()

        self._can = _FakeCan()
        self._trial_read = _FakeRead()
        self._trial_write = _FakeWrite()

        self._trial_steps_state = {key: {"status": "pending", "detail": "", "duration": None}
                                   for key, _t, _h in self.TRIAL_STEPS}
        self._trial_step_started_s = {}
        self._trial_busy = False
        self._trial_status = ""
        self._trial_status_color = ""
        self._trial_log = []
        self._trial_ops = []
        self._trial_pending = None
        self._trial_results = {}
        self._trial_done_handler = None
        self._trial_backup = None
        self._trial_expected = {}
        self._trial_level_reading = None
        self._trial_media_points = None
        self._trial_rf_deadline = 0.0
        self._trial_chamber_plan = []
        self._trial_chamber_index = 0
        self._trial_chamber_outcome = None
        self._trial_applied_profile = None
        self._trial_dirty = set()
        self._trial_expect_trusted = False
        self._trial_commit_ctx = None
        self._trial_ee_errors = None

        self._trial_auto_active = False
        self._trial_auto_queue = []
        self._trial_auto_current = None
        self._trial_auto_last = None
        self._trial_auto_stop_requested = False
        self._trial_auto_backup_ok = False
        self._trial_auto_failed = False

        self._trial_live = {key: None for key, _v, _s in self.TRIAL_LIVE_VARS}
        self._trial_live_seen = {key: 0.0 for key, _v, _s in self.TRIAL_LIVE_VARS}
        self._trial_live_enabled = True
        self._trial_live_index = 0
        self._trial_live_last_inject = 0.0
        self._trial_live_last_poll = 0.0
        self._trial_live_suspend_until = 0.0

        self._trial_gap_timer = _FakeTimer()
        self._trial_wait_timer = _FakeTimer()
        self._trial_timeout_timer = _FakeTimer()
        self._trial_poll_timer = _FakeTimer()
        self._trial_auto_timer = _FakeTimer()
        self._trial_live_timer = _FakeTimer()

        self._calibration_active = True
        self._calibration_session_ready = True
        self._service_access_target_sa = 0x2A
        self._service_security_unlocked = True
        self._options_busy = False

        self._profile_values = profile_model.build_test_profile()
        self._profile_generation = 3
        self._profile_status = ""
        self._profile_verify_report = []
        self._profile_busy = False
        self._profile_device_crc = None
        self._profile_device_status = None

        self._chamber_points = []
        self._chamber_status = ""
        self._chamber_report = []
        self._chamber_busy = False
        self._chamber_rehearsal = False
        self._chamber_label = ""

        self.invalidated = []
        self.started = []
        self.toggled = 0
        self.backup_folder = None
        self.refuse_start = False

    def _trial_start_ops(self, ops, done_handler):
        if self.refuse_start:
            return False
        self.started.append((list(ops), done_handler))
        return True

    def _chamber_clear_points(self):
        self._chamber_points = []

    def _resolve_calibration_target_sa(self):
        return 0x2A

    def _build_calibration_tx_identifier(self):
        return 0x18DA2AF1

    def _resolve_calibration_backup_all_nodes_directory(self):
        return self.backup_folder

    def _invalidate_calibration_session_after_nrc(self, message):
        self.invalidated.append(message)

    def _profile_calc_crc(self):
        return 0x1234

    def _is_calibration_response_identifier(self, identifier):
        return True

    def toggleCalibration(self):
        self.toggled += 1


def _status(stub, key):
    return stub._trial_steps_state[key]["status"]


def _detail(stub, key):
    return stub._trial_steps_state[key]["detail"]


def _last_ops(stub):
    ops, handler = stub.started[-1]
    return {op["key"]: op for op in ops if op.get("key")}, handler


def _samples(prefix, value, count=AppControllerTrialMixin.TRIAL_SAMPLES):
    return {f"{prefix}{index}": value for index in range(count)}


def _log_text(stub):
    return "\n".join(entry["text"] for entry in stub._trial_log)


def _commit(stub, ee=0):
    """Ответ прибора о состоянии памяти после записи: по умолчанию всё записано."""
    stub._trial_commit_poll({"ee": ee})


# ------------------------------------------------------------------ связь и доступ

def test_link_passes_on_new_firmware():
    stub = _TrialStub()
    stub._trial_link_done({"status": 0x08, "emul": TRIAL_EMULATION_OFF_VALUE, "legacy": ("nrc", 0x31),
                           "fuel_t": 213, "board_t": 248, "ee": 0})
    assert _status(stub, "link") == "pass"


def test_link_catches_old_firmware():
    """Ответ на номер прежнего K1 означает старую прошивку, и дальше идти нельзя."""
    stub = _TrialStub()
    stub._trial_link_done({"status": 0x08, "emul": TRIAL_EMULATION_OFF_VALUE, "legacy": 1234,
                           "fuel_t": 213, "board_t": 248, "ee": 0})
    assert _status(stub, "link") == "fail"
    assert "старая прошивка" in _detail(stub, "link")


def test_link_catches_missing_emulation():
    stub = _TrialStub()
    stub._trial_link_done({"status": 0x08, "emul": ("nrc", 0x31), "legacy": ("nrc", 0x31),
                           "fuel_t": 213, "board_t": 248, "ee": 0})
    assert _status(stub, "link") == "fail"
    assert "эмуляции" in _detail(stub, "link")


def test_access_passes_immediately_when_write_is_open():
    stub = _TrialStub()
    assert stub._trial_run_access()
    assert _status(stub, "access") == "pass"
    assert stub.started == []


def test_access_starts_calibration_when_it_is_not_running():
    """Этап сам запускает калибровку, как кнопка в шапке, и ждёт доступа на запись."""
    stub = _TrialStub()
    stub._calibration_active = False
    assert stub._trial_run_access()
    ops, handler = _last_ops(stub)
    assert "calibration_started" in ops and "write_ready" in ops
    assert handler == "_trial_access_done"
    stub._trial_access_start_call()
    assert stub.toggled == 1


def test_access_does_not_toggle_a_running_calibration():
    """Нажатие «запустить» на уже запущенной калибровке её бы остановило."""
    stub = _TrialStub()
    stub._calibration_session_ready = False
    stub._trial_run_access()
    ops, _handler = _last_ops(stub)
    assert "calibration_started" not in ops


def test_access_fails_when_unlocked_for_another_device():
    stub = _TrialStub()
    stub._service_access_target_sa = 0x2B
    stub._trial_access_done({"write_ready": ("timeout",)})
    assert _status(stub, "access") == "fail"
    assert "не для выбранного" in _detail(stub, "access")


def test_steps_refuse_to_write_without_access():
    stub = _TrialStub()
    stub._calibration_active = False
    for run in (stub._trial_run_level, stub._trial_run_media, stub._trial_run_chamber,
                stub._trial_run_profile, stub._trial_run_apply):
        assert not run()
    assert stub.started == []
    assert "Открыть запись в прибор" in _detail(stub, "level")


# ------------------------------------------------------------------ запомнить и вернуть

def _backup_answers(**overrides):
    answers = {"b_empty": 4820, "b_full": 9640, "b_zero_trim": -12, "b_media_enable": 1,
               "b_media_air": 2380, "b_media_cal": 3610, "profile_started": True, "profile_read": True}
    answers.update(overrides)
    return answers


def test_backup_remembers_every_value_and_saves_a_file(tmp_path: Path):
    stub = _TrialStub()
    stub.backup_folder = str(tmp_path)
    stub._trial_backup_done(_backup_answers())

    assert _status(stub, "backup") == "pass"
    assert stub._trial_backup["values"]["zero_trim"] == -12
    files = list(tmp_path.glob("trial_backup_0x2A_*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["values"]["empty"] == 4820


def test_backup_fails_when_a_value_is_missing():
    stub = _TrialStub()
    stub._trial_backup_done(_backup_answers(b_media_air=("timeout",)))
    assert _status(stub, "backup") == "fail"
    assert stub._trial_backup is None


def test_restore_without_backup_fails():
    stub = _TrialStub()
    assert not stub._trial_run_restore()
    assert "Запомнить текущие настройки" in _detail(stub, "restore")


def _stub_with_backup():
    stub = _TrialStub()
    stub._trial_backup = {
        "values": {"empty": 4820, "full": 9640, "zero_trim": -12, "media_enable": 1,
                   "media_air": 2380, "media_cal": 3610},
        "profile": {name: [0] * len(values) for name, values in stub._profile_values.items()},
        "generation": 2, "crc": 0x7ED1, "saved_at": "14.09.2026 11:02:15", "node": 0x2A,
    }
    return stub


def test_restore_sets_expectations_for_the_reboot_check():
    """После возврата перезапуск обязан проверять именно исходные настройки прибора."""
    stub = _stub_with_backup()
    values = stub._trial_backup["values"]
    answers = {f"r_{key}": value for key, value in values.items()}
    answers.update({"write_started": True, "written": True, "write_status": "Готово.",
                    "verify_started": True, "verified": True, "status": 0x08})
    stub._trial_restore_done(answers)
    _commit(stub)

    assert _status(stub, "restore") == "pass"
    assert stub._trial_expected["empty"] == 4820
    assert stub._trial_expected["media_air"] == 2380
    assert stub._trial_expected["crc"] == 0x1234


def test_restore_reports_a_value_that_did_not_come_back():
    stub = _stub_with_backup()
    values = stub._trial_backup["values"]
    answers = {f"r_{key}": value for key, value in values.items()}
    answers["r_zero_trim"] = 0
    answers.update({"write_started": True, "written": True, "write_status": "Готово.",
                    "verify_started": True, "verified": True, "status": 0x08})
    stub._trial_restore_done(answers)
    assert _status(stub, "restore") == "fail"
    assert "подгонка нуля" in _detail(stub, "restore")


def test_restore_writes_back_only_what_the_trial_changed():
    """Лишняя запись это износ памяти и лишний шанс оборваться, но сверяется всё."""
    stub = _stub_with_backup()
    stub._trial_dirty = {"level"}
    stub._trial_restore_stage2({"cur_full": 16136})
    ops, handler = _last_ops(stub)

    assert handler == "_trial_restore_done"
    assert {"w_empty", "w_full", "w_zero_trim"} <= set(ops)
    assert "w_media_air" not in ops
    assert "write_started" not in ops, "нетронутый профиль перезаписывать нельзя"
    assert "crc_now" in ops
    assert "r_media_air" in ops, "сверяются все запомненные настройки"


def test_restore_without_profile_rewrite_checks_the_device_sum():
    stub = _stub_with_backup()
    stub._trial_backup["device_crc"] = 0x7ED1
    stub._trial_backup["device_status"] = 0x00
    stub._trial_dirty = {"level"}
    answers = {f"r_{key}": value for key, value in stub._trial_backup["values"].items()}
    answers["crc_now"] = 0x7ED1
    stub._trial_restore_done(answers)
    _commit(stub)

    assert _status(stub, "restore") == "pass"
    assert "отметки бака" in _detail(stub, "restore")
    assert stub._trial_dirty == set()
    assert stub._trial_expected["crc"] == 0x7ED1
    assert stub._trial_expect_trusted is False


def test_restore_notices_a_profile_that_changed_without_the_trial():
    stub = _stub_with_backup()
    stub._trial_backup["device_crc"] = 0x7ED1
    answers = {f"r_{key}": value for key, value in stub._trial_backup["values"].items()}
    answers["crc_now"] = 0x1111
    stub._trial_restore_done(answers)
    assert _status(stub, "restore") == "fail"
    assert "сумма профиля" in _detail(stub, "restore")


def test_backup_is_not_overwritten_while_trial_values_remain():
    """Перечитав пробные значения, программа запомнила бы их вместо настоящих настроек."""
    stub = _stub_with_backup()
    stub._trial_dirty = {"level"}
    original = stub._trial_backup
    assert stub._trial_run_backup()
    assert _status(stub, "backup") == "warn"
    assert stub._trial_backup is original
    assert stub.started == []


def test_resetting_steps_does_not_forget_what_was_changed():
    stub = _TrialStub()
    stub._trial_dirty = {"media"}
    stub._trial_reset_steps()
    assert stub._trial_dirty == {"media"}


# ------------------------------------------------------------------ эмуляция

def _emulation_answers(**overrides):
    answers = {
        "w_cold": True, "f_cold": -400, "b_cold": -400, "e_cold": -400,
        "w_hot": True, "f_hot": 850, "b_hot": 850, "e_hot": 850,
        "w_off": True, "f_off": 213, "b_off": 248, "e_off": TRIAL_EMULATION_OFF_VALUE,
    }
    answers.update(overrides)
    return answers


def test_emulation_passes_when_both_sensors_follow():
    stub = _TrialStub()
    stub._trial_emulation_done(_emulation_answers())
    assert _status(stub, "emulation") == "pass"


def test_emulation_fails_when_board_sensor_ignores_it():
    stub = _TrialStub()
    stub._trial_emulation_done(_emulation_answers(b_cold=248))
    assert _status(stub, "emulation") == "fail"


def test_emulation_fails_when_it_does_not_switch_off():
    stub = _TrialStub()
    stub._trial_emulation_done(_emulation_answers(e_off=250))
    assert _status(stub, "emulation") == "fail"


# ------------------------------------------------------------------ отметки бака одним конденсатором

def test_level_marks_give_a_quarter_of_the_scale():
    stub = _TrialStub()
    empty, full = stub._trial_level_marks(6000)
    assert (empty, full) == (5000, 9000)
    assert (6000 - empty) * 1000 // (full - empty) == stub.TRIAL_LEVEL_EXPECTED_PERMILLE


def test_level_writes_marks_around_the_reading():
    stub = _TrialStub()
    stub._trial_level_stage2({**_samples("raw", 6000), **_samples("comp", 6000),
                              "cur_full": 9640, "tank_model": 0})
    ops, handler = _last_ops(stub)
    assert handler == "_trial_level_done"
    assert ops["w_empty"]["value"] == 5000
    assert ops["w_full"]["value"] == 9000


def test_level_writes_full_first_when_empty_would_be_refused():
    stub = _TrialStub()
    stub._trial_level_stage2({**_samples("raw", 6000), **_samples("comp", 6000),
                              "cur_full": 4000, "tank_model": 0})
    order = [op["key"] for op in stub.started[-1][0] if op["kind"] == "write"]
    assert order == ["w_full", "w_empty"]


def _level_stub(raw=6000, comp=6000):
    stub = _TrialStub()
    stub._trial_level_reading = {"raw": raw, "comp": comp, "empty": comp - 1000, "full": comp + 3000,
                                 "tank_model": 0}
    return stub


def _level_answers(level=250, **overrides):
    answers = {"w_empty": True, "w_full": True, "rb_empty": 5000, "rb_full": 9000, **_samples("lvl", level)}
    answers.update(overrides)
    return answers


def test_level_passes_at_a_quarter_and_remembers_marks():
    stub = _level_stub()
    stub._trial_level_done(_level_answers())
    _commit(stub)
    assert _status(stub, "level") == "pass"
    assert stub._trial_expected == {"empty": 5000, "full": 9000}


def test_level_catches_a_swapped_scale():
    stub = _level_stub()
    stub._trial_level_done(_level_answers(level=750))
    assert _status(stub, "level") == "fail"
    assert "25.0 %" in _detail(stub, "level")


def test_level_warns_when_raw_and_compensated_differ():
    stub = _level_stub(raw=6050, comp=6000)
    stub._trial_level_done(_level_answers())
    _commit(stub)
    assert _status(stub, "level") == "warn"


def test_level_goes_above_the_media_freeze_threshold():
    """При пороге заморозки 40 % уровень 25 % заморозил бы коэффициент среды, поэтому берётся 75 %."""
    stub = _TrialStub()
    stub._trial_level_stage2({**_samples("raw", 6000), **_samples("comp", 6000),
                              "cur_full": 9640, "tank_model": 0, "freeze": 40})
    ops, _handler = _last_ops(stub)
    assert stub._trial_level_reading["target"] == 750
    assert (ops["w_empty"]["value"], ops["w_full"]["value"]) == (3000, 7000)
    assert "level" in stub._trial_dirty


def test_level_target_list_follows_the_threshold():
    stub = _TrialStub()
    assert stub._trial_level_target(None) == 250
    assert stub._trial_level_target(5) == 250
    assert stub._trial_level_target(40) == 750
    assert stub._trial_level_target(80) == 900
    assert stub._trial_level_target(90) is None


def test_level_refuses_a_threshold_it_cannot_get_above():
    stub = _TrialStub()
    stub._trial_level_stage2({**_samples("raw", 6000), **_samples("comp", 6000),
                              "cur_full": 9640, "tank_model": 0, "freeze": 90})
    assert _status(stub, "level") == "fail"
    assert "0x0034" in _detail(stub, "level")
    assert stub.started == []


def test_level_at_three_quarters_passes_and_catches_a_swap():
    stub = _TrialStub()
    stub._trial_level_reading = {"raw": 6000, "comp": 6000, "empty": 3000, "full": 7000, "target": 750,
                                 "freeze": 40, "tank_model": 0}
    stub._trial_level_done(_level_answers(level=750, rb_empty=3000, rb_full=7000))
    _commit(stub)
    assert _status(stub, "level") == "pass"
    assert "порога заморозки вида топлива 40 %" in _detail(stub, "level")

    stub._trial_level_done(_level_answers(level=250, rb_empty=3000, rb_full=7000))
    assert _status(stub, "level") == "fail"


# ------------------------------------------------------------------ вид топлива одним конденсатором

def test_media_points_give_the_target_coefficient():
    stub = _TrialStub()
    air, cal = stub._trial_media_points_for(2400)
    assert (2400 - air) * 1000 // (cal - air) == stub.TRIAL_MEDIA_TARGET_X1000


def test_media_detects_a_frozen_coefficient_and_points_to_level_step():
    stub = _TrialStub()
    stub._trial_media_stage2({**_samples("m", 2400), "level": 20, "freeze": 5})
    assert _status(stub, "media") == "fail"
    assert "Отметки бака" in _detail(stub, "media")


def test_media_neutral_coefficient_is_not_accepted():
    stub = _TrialStub()
    stub._trial_media_points = {"flatcap": 2400, "air": 1300, "cal": 2300}
    stub._trial_rf_deadline = 0.0
    stub._trial_media_rf_poll({"rf": 1000})
    assert _status(stub, "media") == "fail"


def test_media_coefficient_at_target_passes():
    stub = _TrialStub()
    stub._trial_media_points = {"flatcap": 2400, "air": 1300, "cal": 2300}
    stub._trial_media_rf_poll({"rf": 1104})
    _commit(stub)
    assert _status(stub, "media") == "pass"


def test_media_freeze_after_a_passed_level_step_names_the_real_problem():
    """После пройденных отметок бака отправлять оператора их выполнять бессмысленно."""
    stub = _TrialStub()
    stub._trial_steps_state["level"]["status"] = "pass"
    stub._trial_media_stage2({**_samples("m", 2400), "level": 251, "freeze": 40})
    assert _status(stub, "media") == "fail"
    assert "проверьте" in _detail(stub, "media")
    assert "Сначала выполните" not in _detail(stub, "media")


def test_media_counts_as_changed_before_its_writes():
    stub = _TrialStub()
    stub._trial_media_stage2({**_samples("m", 2400), "level": 750, "freeze": 40})
    assert "media" in stub._trial_dirty
    assert stub.started[-1][1] == "_trial_media_stage3"


# ------------------------------------------------------------------ снятие точек

def _point(node, main=6000):
    return {"note": AppControllerTrialMixin.TRIAL_CHAMBER_LABEL, "board_temp_x10": node,
            "fuel_temp_x10": node, "main": main, "media": 2400}


def _good_capture():
    return {"w_node": True, "capture_started": True, "captured": True}


def test_chamber_walks_through_all_nodes_and_passes():
    stub = _TrialStub()
    stub._trial_run_chamber()
    for node in chamber_fit.NODES_X10:
        stub._chamber_points.append(_point(node, main=6000 + (node % 3)))
        stub._trial_chamber_capture_done(_good_capture())

    _ops, handler = _last_ops(stub)
    assert handler == "_trial_chamber_finish"
    stub._trial_chamber_finish({"emul_off": True})
    assert _status(stub, "chamber") == "pass"
    assert stub._chamber_rehearsal is False


def test_chamber_point_outside_its_node_fails_after_switching_emulation_off():
    stub = _TrialStub()
    stub._trial_run_chamber()
    stub._chamber_points.append(_point(248))
    stub._trial_chamber_capture_done(_good_capture())
    stub._trial_chamber_finish({"emul_off": True})
    assert _status(stub, "chamber") == "fail"
    assert "Эмуляция не дошла" in _detail(stub, "chamber")


def test_chamber_logs_every_point():
    """Числа каждой точки обязаны попадать в журнал: по ним разбирают неудачный прогон."""
    stub = _TrialStub()
    stub._trial_run_chamber()
    stub._chamber_points.append(_point(-400, main=6010))
    stub._trial_chamber_capture_done(_good_capture())
    assert "основной 6010" in _log_text(stub)


# ------------------------------------------------------------------ профиль и применение

def test_profile_step_remembers_what_was_verified():
    stub = _TrialStub()
    stub._trial_profile_done({"write_started": True, "written": True, "write_status": "Готово.",
                              "verify_started": True, "verified": True, "status": 0x0F})
    _commit(stub)
    assert _status(stub, "profile") == "pass"
    assert stub._trial_applied_profile == stub._profile_values


def test_profile_counts_as_changed_once_its_write_starts():
    stub = _TrialStub()
    stub._profile_write_to_device = lambda **kwargs: True
    stub._trial_profile_write_call()
    assert "profile" in stub._trial_dirty


def test_apply_requires_the_profile_step():
    stub = _TrialStub()
    assert not stub._trial_run_apply()
    assert "записи профиля" in _detail(stub, "apply")


def _apply_answers(stub, raw=7000, shift_at=None, mode=0x09, status=0x0F):
    answers = {"status": status, "zero_trim": 0, "emul_off_end": True}
    for index, temperature in enumerate(stub.TRIAL_APPLY_TEMPS_X10):
        prediction = profile_model.predict_main(raw, stub._trial_applied_profile, board_temp_x10=temperature,
                                                tube_temp_x10=temperature, trusted=True)
        comp = prediction["compensated"] + (10 if shift_at == index else 0)
        answers.update({
            f"w{index}": True, f"raw_a{index}": raw, f"raw_b{index}": raw,
            f"board{index}": prediction["board_stage"], f"comp{index}": comp, f"mode{index}": mode,
        })
    return answers


def _applied_stub():
    stub = _TrialStub()
    stub._trial_applied_profile = profile_model.build_test_profile()
    return stub


def test_apply_passes_when_the_device_matches_the_model():
    stub = _applied_stub()
    problems, lines = stub._trial_apply_compare(_apply_answers(stub))
    assert problems == []
    assert len(lines) == len(stub.TRIAL_APPLY_TEMPS_X10)


def test_apply_catches_a_wrong_period_and_names_the_temperature():
    stub = _applied_stub()
    problems, _lines = stub._trial_apply_compare(_apply_answers(stub, shift_at=1))
    assert len(problems) == 1
    assert "-30.0 °C" in problems[0]


def test_apply_catches_an_untrusted_profile():
    stub = _applied_stub()
    problems, _lines = stub._trial_apply_compare(_apply_answers(stub, status=0x03))
    assert any("не применяет профиль" in item for item in problems)


# ------------------------------------------------------------------ сохранение

def test_persist_fails_when_emulation_survives_the_reset():
    stub = _TrialStub()
    stub._trial_expected = {"empty": 5000}
    stub._trial_persist_done({"reset": True, "p_empty": 5000, "p_emul": -400, "p_status": 0x08})
    assert _status(stub, "persist") == "fail"
    assert stub.invalidated


def test_persist_passes_and_closes_the_session():
    stub = _TrialStub()
    stub._trial_expected = {"empty": 5000, "crc": 0x1234}
    stub._trial_persist_done({"reset": True, "p_empty": 5000, "p_crc": 0x1234,
                              "p_emul": TRIAL_EMULATION_OFF_VALUE, "p_status": 0x0F, "p_ee": 0})
    assert _status(stub, "persist") == "pass"
    assert stub.invalidated


# ------------------------------------------------------------------ запись в память

def _ee(pending=0, flags=0, damaged=0, errors=0):
    """Число состояния памяти так, как его возвращает чтение 0x0063."""
    return pending | (flags << 8) | (damaged << 16) | (errors << 24)


def test_step_is_not_declared_before_the_device_writes_its_memory():
    """Ответ «записано» означает только оперативную память: итог ждёт микросхему."""
    stub = _TrialStub()
    stub._trial_commit_then("level", "pass", "Отметки записаны.")
    assert _status(stub, "level") == "running"
    assert stub.started[-1][1] == "_trial_commit_poll"

    _commit(stub, _ee(pending=2))
    assert _status(stub, "level") == "running"
    ops = [op["kind"] for op in stub.started[-1][0]]
    assert ops == ["wait", "read"]

    _commit(stub, _ee())
    assert _status(stub, "level") == "pass"
    assert "проверено чтением" in _detail(stub, "level")


def test_memory_that_never_finishes_fails_the_step():
    stub = _TrialStub()
    stub._trial_commit_then("media", "pass", "Точки записаны.")
    stub._trial_commit_ctx["deadline"] = time.monotonic() - 1.0
    _commit(stub, _ee(pending=1))
    assert _status(stub, "media") == "fail"
    assert "не записал в память" in _detail(stub, "media")


def test_memory_chip_error_fails_the_step():
    stub = _TrialStub()
    stub._trial_commit_then("profile", "pass", "Профиль записан.")
    _commit(stub, _ee(flags=0x01))
    assert _status(stub, "profile") == "fail"
    assert "не отвечает" in _detail(stub, "profile")


def test_memory_write_repeats_are_reported():
    stub = _TrialStub()
    stub._trial_ee_errors = 0
    stub._trial_commit_then("restore", "pass", "Возвращено.")
    _commit(stub, _ee(errors=3))
    assert _status(stub, "restore") == "warn"
    assert "повторов: 3" in _detail(stub, "restore")


def test_link_requires_the_memory_state():
    stub = _TrialStub()
    stub._trial_link_done({"status": 0x08, "emul": TRIAL_EMULATION_OFF_VALUE, "legacy": ("nrc", 0x31),
                           "fuel_t": 213, "board_t": 248, "ee": ("nrc", 0x31)})
    assert _status(stub, "link") == "fail"
    assert "0x0063" in _detail(stub, "link")


def test_link_warns_about_memory_reset_at_power_on():
    stub = _TrialStub()
    stub._trial_link_done({"status": 0x08, "emul": TRIAL_EMULATION_OFF_VALUE, "legacy": ("nrc", 0x31),
                           "fuel_t": 213, "board_t": 248, "ee": _ee(flags=0x04, damaged=2)})
    assert _status(stub, "link") == "warn"
    assert "сбросил их к заводским: 2" in _detail(stub, "link")


def test_persist_catches_a_write_torn_by_the_reset():
    """Оборванная перезапуском запись видна по сбросу повреждённых параметров при включении."""
    stub = _TrialStub()
    stub._trial_expected = {"empty": 5000}
    stub._trial_persist_done({"reset": True, "p_empty": 5000, "p_emul": TRIAL_EMULATION_OFF_VALUE,
                              "p_status": 0x08, "p_ee": _ee(flags=0x04, damaged=1)})
    assert _status(stub, "persist") == "fail"
    assert "после перезапуска" in _detail(stub, "persist")


# ------------------------------------------------------------------ автоматический прогон

def test_auto_run_starts_with_the_link_check():
    stub = _TrialStub()
    assert stub._trial_auto_start()
    assert stub._trial_auto_active
    assert stub._trial_auto_current == "link"
    assert stub.started[-1][1] == "_trial_link_done"
    assert [key for key, _t, _h in stub.TRIAL_STEPS][1:] == stub._trial_auto_queue


def test_auto_run_moves_to_the_next_step_after_a_pass():
    stub = _TrialStub()
    stub._trial_auto_start()
    stub._trial_link_done({"status": 0x08, "emul": TRIAL_EMULATION_OFF_VALUE, "legacy": ("nrc", 0x31),
                           "fuel_t": 213, "board_t": 248, "ee": 0})
    assert stub._trial_auto_timer.started == 1
    stub._on_trial_auto_timer()
    assert stub._trial_auto_current == "backup"
    assert stub.started[-1][1] == "_trial_backup_done"


def test_auto_run_returns_settings_when_a_step_fails_after_backup():
    """Отказ после запоминания настроек обязан вернуть их: прибор не остаётся с пробной калибровкой."""
    stub = _stub_with_backup()
    stub._trial_auto_active = True
    stub._trial_auto_backup_ok = True
    stub._trial_auto_current = "level"
    stub._trial_auto_queue = ["media", "chamber", "profile", "apply", "restore", "persist"]

    stub._trial_set_step("level", "fail", "уровень 75.0 %, а должен быть 25.0 %.")
    stub._on_trial_auto_timer()

    assert stub._trial_auto_current == "restore"
    for key in ("media", "chamber", "profile", "apply", "persist"):
        assert _status(stub, key) == "skip"
    assert "Возвращаю запомненные настройки" in _log_text(stub)


def test_auto_run_stops_without_restore_when_nothing_was_written():
    stub = _TrialStub()
    stub._trial_auto_active = True
    stub._trial_auto_current = "access"
    stub._trial_auto_queue = ["emulation", "level", "media", "chamber", "profile", "apply", "restore", "persist"]

    stub._trial_set_step("access", "fail", "Запись не открылась.")
    stub._on_trial_auto_timer()

    assert not stub._trial_auto_active
    assert _status(stub, "restore") == "skip"
    assert "настройки прибора не менялись" in _log_text(stub)


def test_auto_run_stops_after_the_current_step_on_request():
    stub = _TrialStub()
    stub._trial_auto_start()
    stub._trial_auto_stop()
    stub._trial_link_done({"status": 0x08, "emul": TRIAL_EMULATION_OFF_VALUE, "legacy": ("nrc", 0x31),
                           "fuel_t": 213, "board_t": 248, "ee": 0})
    stub._on_trial_auto_timer()

    assert not stub._trial_auto_active
    assert _status(stub, "backup") == "pending"
    assert "остановлена" in _log_text(stub)


def test_auto_run_reports_completion():
    stub = _TrialStub()
    stub._trial_auto_active = True
    stub._trial_auto_current = "persist"
    stub._trial_auto_queue = []
    stub._trial_set_step("persist", "pass", "После перезапуска всё на месте.")
    stub._on_trial_auto_timer()
    assert not stub._trial_auto_active
    assert stub._trial_log[-1]["level"] == "ok"
    assert "завершена" in stub._trial_log[-1]["text"]


def test_auto_progress_names_the_table_row_even_after_skips():
    """После отказа часть этапов пропущена, но ход прогона обязан называть номер строки таблицы."""
    stub = _stub_with_backup()
    stub._trial_auto_active = True
    stub._trial_auto_current = "restore"
    for key in ("profile", "apply", "persist"):
        stub._trial_steps_state[key]["status"] = "skip"
    assert stub._trial_auto_progress() == "Этап 10 из 11: Вернуть как было"


def test_auto_run_refuses_to_start_twice():
    stub = _TrialStub()
    assert stub._trial_auto_start()
    assert not stub._trial_auto_start()


def test_step_that_cannot_start_is_marked_failed():
    """Этап, который не смог даже начать обмен, не должен висеть в состоянии «идёт проверка»."""
    stub = _TrialStub()
    stub.refuse_start = True
    assert not stub._trial_run_step("link")
    assert _status(stub, "link") == "fail"
    assert "не запустился" in _detail(stub, "link")


# ------------------------------------------------------------------ журнал и таблица

def test_step_start_logs_what_and_why():
    stub = _TrialStub()
    stub._trial_run_step("link")
    levels = [entry["level"] for entry in stub._trial_log[:2]]
    assert levels == ["step", "info"]
    assert stub._trial_log[0]["text"] == stub._trial_title("link")


def test_multiline_detail_goes_to_separate_log_rows():
    stub = _TrialStub()
    stub._trial_set_step("apply", "pass", "Совпало.\n-40.0 °C: итог 7249\n+85.0 °C: итог 6723")
    assert [entry["level"] for entry in stub._trial_log[-3:]] == ["ok", "detail", "detail"]


def test_step_duration_is_shown_in_the_table():
    stub = _TrialStub()
    stub._trial_step_started_s["link"] = time.monotonic() - 2.0
    stub._trial_set_step("link", "pass", "Всё хорошо.")
    row = stub._trial_step_rows()[0]
    assert row["duration"].startswith("2,")
    assert row["summary"] == "Всё хорошо."


def test_table_rows_mark_the_running_step():
    stub = _TrialStub()
    stub._trial_auto_current = "media"
    rows = {row["key"]: row for row in stub._trial_step_rows()}
    assert rows["media"]["current"] is True
    assert rows["level"]["current"] is False


# ------------------------------------------------------------------ постоянные отсчёты

def test_live_frame_updates_the_main_period():
    stub = _TrialStub()
    stub._handle_trial_live_frame(0x18DA2AF1, [0x05, 0x62, 0x00, 0x14, 0xD5, 0x12, 0x00, 0x00])
    view = stub._trial_live_view()
    assert view["mainRaw"] == "4821"
    assert view["mainFresh"] is True


def test_live_frame_decodes_signed_temperature_and_emulation():
    stub = _TrialStub()
    stub._handle_trial_live_frame(0x18DA2AF1, [0x05, 0x62, 0x00, 0x19, 0x70, 0xFE, 0x00, 0x00])
    stub._handle_trial_live_frame(0x18DA2AF1, [0x05, 0x62, 0x00, 0x61, 0x52, 0x03, 0x00, 0x00])
    view = stub._trial_live_view()
    assert view["fuelTemp"] == "-40.0 °C"
    assert view["emulationOn"] is True
    assert "+85.0" in view["emulation"]


def test_live_frame_is_ignored_when_display_is_off():
    stub = _TrialStub()
    stub._trial_live_enabled = False
    stub._handle_trial_live_frame(0x18DA2AF1, [0x05, 0x62, 0x00, 0x14, 0xD5, 0x12, 0x00, 0x00])
    assert stub._trial_live["main_raw"] is None


def test_old_live_data_is_marked_stale():
    stub = _TrialStub()
    stub._trial_live["main_raw"] = 4821
    stub._trial_live_seen["main_raw"] = time.monotonic() - 10.0
    assert stub._trial_live_view()["mainFresh"] is False


def test_live_reads_are_injected_before_a_write():
    """Во время этапа отсчёты обновляются, но только на границе его замеров."""
    stub = _TrialStub()
    stub._trial_busy = True
    stub._trial_ops = [stub._op_write("w", UdsData.fuel_zero_trim_count, 0)]
    stub._trial_next_op()
    assert stub._trial_read.sent == [int(UdsData.curr_fuel_tank.pid)]
    assert stub._trial_pending["key"] == "_live_main_raw"


def test_live_reads_never_split_a_series_of_reads():
    """Между сырым и итоговым периодом нельзя вклинивать лишний запрос: это сбило бы сверку."""
    stub = _TrialStub()
    stub._trial_busy = True
    stub._trial_ops = [stub._op_read("raw_a0", UdsData.curr_fuel_tank)]
    stub._trial_next_op()
    assert stub._trial_pending["key"] == "raw_a0"


def test_live_reads_pause_while_the_device_restarts():
    stub = _TrialStub()
    stub._trial_busy = True
    stub._trial_live_suspend_until = time.monotonic() + 5.0
    stub._trial_ops = [stub._op_write("w", UdsData.fuel_zero_trim_count, 0)]
    stub._trial_next_op()
    assert stub._trial_pending["key"] == "w"


def test_step_waits_for_the_answer_to_a_fresh_poll():
    """Отказ старой прошивки на опрос отсчётов этап не должен принять за ответ на свой запрос."""
    stub = _TrialStub()
    stub._trial_live_last_poll = time.monotonic()
    ops = [stub._op_read("status", UdsData.fuel_thermal_profile_status)]
    assert AppControllerTrialMixin._trial_start_ops(stub, ops, "_trial_link_done")
    assert stub._trial_gap_timer.started == 1
    assert stub._trial_pending is None
    assert stub._trial_read.sent == []


def test_idle_poll_stays_off_the_bus_during_the_calibration_handshake():
    stub = _TrialStub()
    stub._calibration_session_ready = False
    stub._on_trial_live_tick()
    assert stub._trial_read.sent == []


def test_idle_poll_waits_while_another_section_uses_the_bus():
    stub = _TrialStub()
    stub._profile_busy = True
    stub._on_trial_live_tick()
    assert stub._trial_read.sent == []

    stub._profile_busy = False
    stub._on_trial_live_tick()
    assert len(stub._trial_read.sent) == 1


# ------------------------------------------------------------------ разбор ответов

def _pending(stub, kind, var, signed=False):
    stub._trial_busy = True
    stub._trial_pending = {"kind": kind, "key": "x", "var": var, "signed": signed}


def test_signed_read_is_decoded():
    stub = _TrialStub()
    _pending(stub, "read", UdsData.raw_temperature, signed=True)
    stub._handle_trial_frame(0x18DA2AF1, [0x05, 0x62, 0x00, 0x19, 0x70, 0xFE, 0x00, 0x00])
    assert stub._trial_results["x"] == -400


def test_refusal_is_recorded_with_its_code():
    stub = _TrialStub()
    _pending(stub, "write", UdsData.temperature_emulation_x10)
    stub._handle_trial_frame(0x18DA2AF1, [0x03, 0x7F, 0x2E, 0x33, 0x00, 0x00, 0x00, 0x00])
    assert stub._trial_results["x"] == ("nrc", 0x33)
    assert "нет доступа" in stub._trial_error_text(stub._trial_results, "x")


def test_answer_to_another_parameter_is_ignored():
    stub = _TrialStub()
    _pending(stub, "read", UdsData.raw_temperature, signed=True)
    stub._handle_trial_frame(0x18DA2AF1, [0x05, 0x62, 0x00, 0x3B, 0x70, 0xFE, 0x00, 0x00])
    assert "x" not in stub._trial_results


# ------------------------------------------------------------------ протокол

def test_protocol_contains_the_table_and_the_log(tmp_path: Path):
    stub = _TrialStub()
    stub._trial_set_step("link", "pass", "температура топлива +23.4 °C.")
    path = tmp_path / "protocol.txt"
    assert stub._trial_save_protocol(str(path))
    text = path.read_text(encoding="utf-8")
    assert "Этапы:" in text and "Журнал:" in text
    assert "Прибор на связи, прошивка новая: пройдено" in text


# ------------------------------------------------------------------ возврат пустого профиля

class _ProfileStub(AppControllerProfileMixin):
    def __init__(self):
        self.profileChanged = _Signal()
        self._options_busy = False
        self._init_profile_state()


def test_empty_profile_can_be_written_back_on_restore():
    stub = _ProfileStub()
    stub._start_options_write_multiframe_request = lambda *args, **kwargs: True
    stub._start_options_read_request = lambda *args, **kwargs: True
    assert not stub._profile_write_to_device()
    assert stub._profile_write_to_device(allow_empty=True)
