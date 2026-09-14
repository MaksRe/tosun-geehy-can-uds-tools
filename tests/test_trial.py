"""Проверки пробной калибровки на столе.

Пробная калибровка решает, идти ли в камеру. Если она пропустит неисправность,
выезд пропадёт впустую. Если будет ругать исправный прибор, её перестанут
запускать. Поэтому здесь закреплены её решения на известных ответах прибора:
что считается пройденным, что нет, и какими словами это объясняется.

На столе на каждом контуре висит по одному постоянному конденсатору, поэтому
отдельно закреплено, что ни один шаг не требует менять ёмкость.
"""

from __future__ import annotations

import sys
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


class _TrialStub(AppControllerTrialMixin):
    """Носитель логики пробной калибровки без Qt и без шины.

    Запуск очереди подменён: вместо обмена с прибором очередь запоминается, а
    проверки сами вызывают обработчик итога с заранее известными ответами.
    """

    def __init__(self):
        self.trialChanged = _Signal()
        self.profileChanged = _Signal()
        self.infoMessage = _Signal()

        self._trial_steps_state = {key: {"status": "pending", "detail": ""} for key, _t, _h in self.TRIAL_STEPS}
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
        self._trial_gap_timer = _FakeTimer()
        self._trial_wait_timer = _FakeTimer()
        self._trial_timeout_timer = _FakeTimer()
        self._trial_poll_timer = _FakeTimer()

        self._calibration_active = True
        self._calibration_session_ready = True
        self._service_access_target_sa = 0x2A
        self._service_security_unlocked = True

        self._profile_values = profile_model.build_test_profile()
        self._profile_generation = 3
        self._profile_status = ""
        self._profile_verify_report = []

        self._chamber_points = []
        self._chamber_status = ""
        self._chamber_report = []
        self._chamber_busy = False
        self._chamber_rehearsal = False
        self._chamber_label = ""

        self.invalidated = []
        self.started = []

    def _trial_start_ops(self, ops, done_handler):
        self.started.append((list(ops), done_handler))
        return True

    def _chamber_clear_points(self):
        self._chamber_points = []

    def _resolve_calibration_target_sa(self):
        return 0x2A

    def _invalidate_calibration_session_after_nrc(self, message):
        self.invalidated.append(message)

    def _profile_calc_crc(self):
        return 0x1234

    def _is_calibration_response_identifier(self, identifier):
        return True


def _status(stub, key):
    return stub._trial_steps_state[key]["status"]


def _detail(stub, key):
    return stub._trial_steps_state[key]["detail"]


def _last_ops(stub):
    ops, handler = stub.started[-1]
    return {op["key"]: op for op in ops if op.get("key")}, handler


def _samples(prefix, value, count=AppControllerTrialMixin.TRIAL_SAMPLES):
    return {f"{prefix}{index}": value for index in range(count)}


# ------------------------------------------------------------------ связь и доступ

def test_link_passes_on_new_firmware():
    stub = _TrialStub()
    stub._trial_link_done({"status": 0x08, "emul": TRIAL_EMULATION_OFF_VALUE, "legacy": ("nrc", 0x31),
                           "fuel_t": 213, "board_t": 248})
    assert _status(stub, "link") == "pass"


def test_link_catches_old_firmware():
    """Ответ на номер прежнего K1 означает старую прошивку, и дальше идти нельзя."""
    stub = _TrialStub()
    stub._trial_link_done({"status": 0x08, "emul": TRIAL_EMULATION_OFF_VALUE, "legacy": 1234,
                           "fuel_t": 213, "board_t": 248})
    assert _status(stub, "link") == "fail"
    assert "старая прошивка" in _detail(stub, "link")


def test_link_catches_missing_emulation():
    stub = _TrialStub()
    stub._trial_link_done({"status": 0x08, "emul": ("nrc", 0x31), "legacy": ("nrc", 0x31),
                           "fuel_t": 213, "board_t": 248})
    assert _status(stub, "link") == "fail"
    assert "эмуляции" in _detail(stub, "link")


def test_link_warns_when_emulation_was_left_on():
    stub = _TrialStub()
    stub._trial_link_done({"status": 0x08, "emul": -400, "legacy": ("nrc", 0x31),
                           "fuel_t": -400, "board_t": -400})
    assert _status(stub, "link") == "warn"


def test_access_fails_when_unlocked_for_another_device():
    """Открытый доступ к соседнему прибору не даёт права писать в выбранный."""
    stub = _TrialStub()
    stub._service_access_target_sa = 0x2B
    assert not stub._trial_run_access()
    assert "не для выбранного" in _detail(stub, "access")


def test_steps_refuse_to_write_without_access():
    stub = _TrialStub()
    stub._calibration_active = False
    for run in (stub._trial_run_level, stub._trial_run_media, stub._trial_run_chamber,
                stub._trial_run_profile, stub._trial_run_apply):
        assert not run()
    assert stub.started == []


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


def test_emulation_explains_a_refused_write():
    stub = _TrialStub()
    stub._trial_emulation_done(_emulation_answers(w_cold=("nrc", 0x33)))
    assert "нет доступа на запись" in _detail(stub, "emulation")


# ------------------------------------------------------------------ отметки бака одним конденсатором

def test_level_marks_give_a_quarter_of_the_scale():
    """Отметки вокруг показания обязаны давать ровно 25 %: так видна и перестановка местами."""
    stub = _TrialStub()
    empty, full = stub._trial_level_marks(6000)
    assert (empty, full) == (5000, 9000)
    assert (6000 - empty) * 1000 // (full - empty) == stub.TRIAL_LEVEL_EXPECTED_PERMILLE


def test_level_needs_no_capacitor_change():
    """Шаг снимает показание один раз и сразу пишет отметки: смены конденсатора нет."""
    stub = _TrialStub()
    assert stub._trial_run_level()
    ops, handler = _last_ops(stub)
    assert handler == "_trial_level_stage2"
    assert "comp0" in ops and "raw0" in ops


def test_level_writes_marks_around_the_reading():
    stub = _TrialStub()
    stub._trial_level_stage2({**_samples("raw", 6000), **_samples("comp", 6000),
                              "cur_full": 9640, "tank_model": 0})
    ops, handler = _last_ops(stub)
    assert handler == "_trial_level_done"
    assert ops["w_empty"]["value"] == 5000
    assert ops["w_full"]["value"] == 9000
    order = [op["key"] for op in stub.started[-1][0] if op["kind"] == "write"]
    assert order == ["w_empty", "w_full"]


def test_level_writes_full_first_when_empty_would_be_refused():
    """Новая отметка 0 % выше текущей 100 % прибор отвергнет, поэтому сначала пишется 100 %."""
    stub = _TrialStub()
    stub._trial_level_stage2({**_samples("raw", 6000), **_samples("comp", 6000),
                              "cur_full": 4000, "tank_model": 0})
    order = [op["key"] for op in stub.started[-1][0] if op["kind"] == "write"]
    assert order == ["w_full", "w_empty"]


def test_level_refuses_a_reading_at_the_edge_of_the_scale():
    stub = _TrialStub()
    stub._trial_level_stage2({**_samples("raw", 500), **_samples("comp", 500), "cur_full": 9640, "tank_model": 0})
    assert _status(stub, "level") == "fail"
    assert stub.started == []


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
    assert _status(stub, "level") == "pass"
    assert stub._trial_expected == {"empty": 5000, "full": 9000}


def test_level_catches_a_swapped_scale():
    """75 % вместо 25 % означает, что прибор перепутал отметки местами."""
    stub = _level_stub()
    stub._trial_level_done(_level_answers(level=750))
    assert _status(stub, "level") == "fail"
    assert "25.0 %" in _detail(stub, "level")


def test_level_catches_a_readback_mismatch():
    stub = _level_stub()
    stub._trial_level_done(_level_answers(rb_full=8000))
    assert _status(stub, "level") == "fail"
    assert "100 %" in _detail(stub, "level")
    assert stub._trial_expected == {}


def test_level_warns_when_raw_and_compensated_differ():
    stub = _level_stub(raw=6050, comp=6000)
    stub._trial_level_done(_level_answers())
    assert _status(stub, "level") == "warn"
    assert "сырому периоду" in _detail(stub, "level")


# ------------------------------------------------------------------ вид топлива одним конденсатором

def test_media_points_give_the_target_coefficient():
    """При таких точках коэффициент среды обязан стать 1,100, а не нейтральной единицей."""
    stub = _TrialStub()
    flatcap = 2400
    air, cal = stub._trial_media_points_for(flatcap)
    assert cal - air == stub.TRIAL_MEDIA_SPAN
    assert (flatcap - air) * 1000 // (cal - air) == stub.TRIAL_MEDIA_TARGET_X1000


def test_media_writes_points_around_the_reading():
    stub = _TrialStub()
    stub._trial_media_stage2({**_samples("m", 2400), "level": 250, "freeze": 5})
    ops, handler = _last_ops(stub)
    assert handler == "_trial_media_stage3"
    assert ops["w_air"]["value"] == 1300
    assert ops["w_cal"]["value"] == 2300


def test_media_detects_a_frozen_coefficient_and_points_to_step_4():
    stub = _TrialStub()
    stub._trial_media_stage2({**_samples("m", 2400), "level": 20, "freeze": 5})
    assert _status(stub, "media") == "fail"
    assert "шаг 4" in _detail(stub, "media")
    assert stub.started == []


def test_media_refuses_a_too_small_reading():
    stub = _TrialStub()
    stub._trial_media_stage2({**_samples("m", 900), "level": 250, "freeze": 5})
    assert _status(stub, "media") == "fail"


def test_media_catches_a_readback_mismatch():
    stub = _TrialStub()
    stub._trial_media_points = {"flatcap": 2400, "air": 1300, "cal": 2300}
    stub._trial_media_stage3({"w_air": True, "w_cal": True, "w_en": True, "rb_air": 1300, "rb_cal": 2000, "rb_en": 1})
    assert _status(stub, "media") == "fail"
    assert "«топливо»" in _detail(stub, "media")


def test_media_coefficient_at_target_passes():
    stub = _TrialStub()
    stub._trial_media_points = {"flatcap": 2400, "air": 1300, "cal": 2300}
    stub._trial_media_rf_poll({"rf": 1104})
    assert _status(stub, "media") == "pass"


def test_media_neutral_coefficient_is_not_accepted():
    """Единица это нейтральное значение: оно значит, что прибор коэффициент не пересчитал."""
    stub = _TrialStub()
    stub._trial_media_points = {"flatcap": 2400, "air": 1300, "cal": 2300}
    stub._trial_rf_deadline = 0.0
    stub._trial_media_rf_poll({"rf": 1000})
    assert _status(stub, "media") == "fail"


# ------------------------------------------------------------------ снятие точек

def _point(node, main=6000):
    return {"note": AppControllerTrialMixin.TRIAL_CHAMBER_LABEL, "board_temp_x10": node,
            "fuel_temp_x10": node, "main": main}


def _good_capture():
    return {"w_node": True, "capture_started": True, "captured": True}


def test_chamber_starts_at_the_coldest_node():
    stub = _TrialStub()
    assert stub._trial_run_chamber()
    assert stub._trial_chamber_plan == chamber_fit.NODES_X10
    assert stub._chamber_rehearsal is True
    ops, handler = _last_ops(stub)
    assert ops["w_node"]["value"] == chamber_fit.NODES_X10[0]
    assert handler == "_trial_chamber_capture_done"


def test_chamber_walks_through_all_nodes_and_passes():
    stub = _TrialStub()
    stub._trial_run_chamber()
    for node in chamber_fit.NODES_X10:
        stub._chamber_points.append(_point(node, main=6000 + (node % 3)))
        stub._trial_chamber_capture_done(_good_capture())

    ops, handler = _last_ops(stub)
    assert handler == "_trial_chamber_finish"
    assert "emul_off" in ops
    stub._trial_chamber_finish({"emul_off": True})
    assert _status(stub, "chamber") == "pass"
    assert stub._chamber_rehearsal is False


def test_chamber_point_outside_its_node_fails_after_switching_emulation_off():
    """Если эмуляция не дошла до измерения, точка встанет в чужой узел, и это обязано ловиться."""
    stub = _TrialStub()
    stub._trial_run_chamber()
    stub._chamber_points.append(_point(248))
    stub._trial_chamber_capture_done(_good_capture())

    _ops, handler = _last_ops(stub)
    assert handler == "_trial_chamber_finish"
    stub._trial_chamber_finish({"emul_off": True})
    assert _status(stub, "chamber") == "fail"
    assert "Эмуляция не дошла" in _detail(stub, "chamber")


def test_chamber_warns_when_the_capacitor_reading_wanders():
    stub = _TrialStub()
    stub._trial_run_chamber()
    for index, node in enumerate(chamber_fit.NODES_X10):
        stub._chamber_points.append(_point(node, main=6000 + index * 10))
        stub._trial_chamber_capture_done(_good_capture())
    stub._trial_chamber_finish({"emul_off": True})
    assert _status(stub, "chamber") == "warn"
    assert "проводки" in _detail(stub, "chamber")


def test_chamber_fails_when_emulation_cannot_be_switched_off():
    stub = _TrialStub()
    stub._trial_chamber_outcome = ("pass", "Все точки в узлах.")
    stub._trial_chamber_finish({"emul_off": ("timeout",)})
    assert _status(stub, "chamber") == "fail"


# ------------------------------------------------------------------ профиль и применение

def test_profile_step_writes_the_test_profile():
    stub = _TrialStub()
    for name in stub._profile_values:
        stub._profile_values[name] = [0] * len(stub._profile_values[name])
    stub._profile_values["nodes"] = list(chamber_fit.NODES_X10)
    stub._trial_profile_load_call()
    assert stub._profile_values == profile_model.build_test_profile()


def test_profile_step_remembers_what_was_verified():
    stub = _TrialStub()
    stub._trial_profile_done({"write_started": True, "written": True, "write_status": "Готово.",
                              "verify_started": True, "verified": True, "status": 0x0F})
    assert _status(stub, "profile") == "pass"
    assert stub._trial_applied_profile == stub._profile_values
    assert stub._trial_expected["crc"] == 0x1234


def test_profile_step_failure_blocks_the_apply_step():
    stub = _TrialStub()
    stub._profile_verify_report = ["Трубка, основной на воздухе, узел -40 °C: записано 4700, в приборе 0"]
    stub._trial_profile_done({"write_started": True, "written": True, "write_status": "Готово.",
                              "verify_started": True, "verified": True, "status": 0x0F})
    assert _status(stub, "profile") == "fail"
    assert not stub._trial_run_apply()
    assert "шаг 7" in _detail(stub, "apply")


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


def test_apply_uses_the_verified_snapshot_not_the_screen():
    """Правка таблицы на экране после шага 7 не должна менять ожидание: сверка идёт с прибором."""
    stub = _applied_stub()
    answers = _apply_answers(stub)
    stub._profile_values["board_main"][0] = 9999
    problems, _lines = stub._trial_apply_compare(answers)
    assert problems == []


def test_apply_catches_a_wrong_period_and_names_the_temperature():
    stub = _applied_stub()
    problems, _lines = stub._trial_apply_compare(_apply_answers(stub, shift_at=1))
    assert len(problems) == 1
    assert "-30.0 °C" in problems[0]


def test_apply_catches_a_stage_that_is_not_working():
    stub = _applied_stub()
    problems, _lines = stub._trial_apply_compare(_apply_answers(stub, mode=0x01))
    assert problems
    assert all("признаки" in item for item in problems)


def test_apply_catches_an_untrusted_profile():
    stub = _applied_stub()
    problems, _lines = stub._trial_apply_compare(_apply_answers(stub, status=0x03))
    assert any("не применяет профиль" in item for item in problems)


def test_apply_tolerates_a_recalculation_between_reads():
    stub = _applied_stub()
    answers = _apply_answers(stub)
    answers["raw_b0"] = 7002
    problems, _lines = stub._trial_apply_compare(answers)
    assert problems == []


# ------------------------------------------------------------------ сохранение

def test_persist_fails_when_emulation_survives_the_reset():
    stub = _TrialStub()
    stub._trial_expected = {"empty": 5000}
    stub._trial_persist_done({"reset": True, "p_empty": 5000, "p_emul": -400, "p_status": 0x08})
    assert _status(stub, "persist") == "fail"
    assert "пережила перезапуск" in _detail(stub, "persist")
    assert stub.invalidated


def test_persist_passes_and_closes_the_session():
    stub = _TrialStub()
    stub._trial_expected = {"empty": 5000, "crc": 0x1234}
    stub._trial_persist_done({"reset": True, "p_empty": 5000, "p_crc": 0x1234,
                              "p_emul": TRIAL_EMULATION_OFF_VALUE, "p_status": 0x0F})
    assert _status(stub, "persist") == "pass"
    assert stub.invalidated


def test_persist_catches_a_lost_value():
    stub = _TrialStub()
    stub._trial_expected = {"media_air": 1300}
    stub._trial_persist_done({"reset": True, "p_media_air": 0,
                              "p_emul": TRIAL_EMULATION_OFF_VALUE, "p_status": 0x08})
    assert _status(stub, "persist") == "fail"
    assert "«воздух»" in _detail(stub, "persist")


def test_persist_refuses_to_run_with_nothing_to_compare():
    stub = _TrialStub()
    assert not stub._trial_run_persist()
    assert _status(stub, "persist") == "fail"


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


def test_write_acknowledgement_is_recorded():
    stub = _TrialStub()
    _pending(stub, "write", UdsData.temperature_emulation_x10)
    stub._handle_trial_frame(0x18DA2AF1, [0x03, 0x6E, 0x00, 0x61, 0x00, 0x00, 0x00, 0x00])
    assert stub._trial_results["x"] is True


def test_answer_to_another_parameter_is_ignored():
    stub = _TrialStub()
    _pending(stub, "read", UdsData.raw_temperature, signed=True)
    stub._handle_trial_frame(0x18DA2AF1, [0x05, 0x62, 0x00, 0x3B, 0x70, 0xFE, 0x00, 0x00])
    assert "x" not in stub._trial_results


def test_refusal_of_another_service_is_ignored():
    stub = _TrialStub()
    _pending(stub, "read", UdsData.raw_temperature, signed=True)
    stub._handle_trial_frame(0x18DA2AF1, [0x03, 0x7F, 0x2E, 0x33, 0x00, 0x00, 0x00, 0x00])
    assert "x" not in stub._trial_results


# ------------------------------------------------------------------ возврат пустого профиля

class _ProfileStub(AppControllerProfileMixin):
    def __init__(self):
        self.profileChanged = _Signal()
        self._options_busy = False
        self._init_profile_state()


def test_empty_profile_can_be_written_back_on_restore():
    """Запомненный профиль мог быть пустым, и вернуть его обязательно должно получиться."""
    stub = _ProfileStub()
    stub._start_options_write_multiframe_request = lambda *args, **kwargs: True
    stub._start_options_read_request = lambda *args, **kwargs: True
    assert not stub._profile_write_to_device()
    assert stub._profile_write_to_device(allow_empty=True)
