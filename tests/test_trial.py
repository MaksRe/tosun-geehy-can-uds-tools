"""Проверки пробной калибровки на столе.

Пробная калибровка решает, идти ли в камеру. Если она пропустит неисправность,
выезд пропадёт впустую. Если будет ругать исправный прибор, её перестанут
запускать. Поэтому здесь закреплены её решения на известных ответах прибора:
что считается пройденным, что нет, и какими словами это объясняется.
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
    """Носитель логики пробной калибровки без Qt и без шины."""

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
        self._trial_capture_target = ""
        self._trial_level_empty = None
        self._trial_level_full = None
        self._trial_media_air = None
        self._trial_media_fuel = None
        self._trial_rf_deadline = 0.0
        self._trial_chamber_ref1 = 300.0
        self._trial_chamber_ref2 = 600.0
        self._trial_chamber_plan = []
        self._trial_chamber_index = 0
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

        self.invalidated = []

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


# ------------------------------------------------------------------ связь

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
    """Забытая эмуляция это не отказ, но оператор обязан о ней узнать."""
    stub = _TrialStub()
    stub._trial_link_done({"status": 0x08, "emul": -400, "legacy": ("nrc", 0x31),
                           "fuel_t": -400, "board_t": -400})
    assert _status(stub, "link") == "warn"


# ------------------------------------------------------------------ доступ

def test_access_fails_without_a_session():
    stub = _TrialStub()
    stub._calibration_active = False
    assert not stub._trial_run_access()
    assert _status(stub, "access") == "fail"


def test_access_fails_when_unlocked_for_another_device():
    """Открытый доступ к соседнему прибору не даёт права писать в выбранный."""
    stub = _TrialStub()
    stub._service_access_target_sa = 0x2B
    assert not stub._trial_run_access()
    assert "не для выбранного" in _detail(stub, "access")


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
    """Если датчик платы не видит эмуляцию, ступень платы в проверке применения будет врать."""
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


# ------------------------------------------------------------------ отметки бака

def test_level_order_writes_empty_first_when_it_fits():
    stub = _TrialStub()
    keys = [op["key"] for op in stub._trial_level_order(9640, 4820, 9700)]
    assert keys == ["w_empty", "w_full"]


def test_level_order_writes_full_first_when_empty_would_be_refused():
    """Новая отметка 0 % выше текущей 100 % прибор отвергнет, поэтому сначала пишется 100 %."""
    stub = _TrialStub()
    keys = [op["key"] for op in stub._trial_level_order(4000, 4820, 9640)]
    assert keys == ["w_full", "w_empty"]
    keys = [op["key"] for op in stub._trial_level_order(None, 4820, 9640)]
    assert keys == ["w_full", "w_empty"]


def _level_stub(raw_shift=0):
    stub = _TrialStub()
    stub._trial_level_empty = {"raw": 4820 + raw_shift, "comp": 4820}
    stub._trial_level_full = {"raw": 9640 + raw_shift, "comp": 9640}
    return stub


def _level_answers(**overrides):
    answers = {"w_empty": True, "w_full": True, "rb_empty": 4820, "rb_full": 9640,
               "tank_model": 0, "comp_now": 9640, "level": 1000}
    answers.update(overrides)
    return answers


def test_level_passes_and_remembers_marks():
    stub = _level_stub()
    stub._trial_level_write_done(_level_answers())
    assert _status(stub, "level") == "pass"
    assert stub._trial_expected == {"empty": 4820, "full": 9640}


def test_level_catches_a_readback_mismatch():
    stub = _level_stub()
    stub._trial_level_write_done(_level_answers(rb_full=9000))
    assert _status(stub, "level") == "fail"
    assert "100 %" in _detail(stub, "level")
    assert stub._trial_expected == {}


def test_level_catches_a_wrong_level():
    """Отметки записались, но уровень при полном баке не 100 %: значит прибор их не применяет."""
    stub = _level_stub()
    stub._trial_level_write_done(_level_answers(level=700))
    assert _status(stub, "level") == "fail"
    assert "должен быть 100 %" in _detail(stub, "level")


def test_level_warns_when_raw_and_compensated_differ():
    """Расхождение сырого и итогового периода сдвинет уровень в разделе «Уровень бака»."""
    stub = _level_stub(raw_shift=50)
    stub._trial_level_write_done(_level_answers())
    assert _status(stub, "level") == "warn"
    assert "сырому периоду" in _detail(stub, "level")


# ------------------------------------------------------------------ вид топлива

def _media_stub():
    stub = _TrialStub()
    stub._trial_media_air = 2000
    stub._trial_media_fuel = 3000
    return stub


def _media_answers(**overrides):
    answers = {"w_air": True, "w_cal": True, "w_en": True, "rb_air": 2000, "rb_cal": 3000, "rb_en": 1,
               "freeze": 5, "level": 1000, "flat_now": 3000}
    answers.update(overrides)
    return answers


def test_media_detects_a_frozen_coefficient():
    """При пустом баке коэффициент среды заморожен, и проверка обязана сказать, что подключить."""
    stub = _media_stub()
    stub._trial_media_write_done(_media_answers(level=20))
    assert _status(stub, "media") == "fail"
    assert "порога заморозки" in _detail(stub, "media")


def test_media_detects_the_wrong_capacitor():
    stub = _media_stub()
    stub._trial_media_write_done(_media_answers(flat_now=2000))
    assert _status(stub, "media") == "fail"
    assert "не «топливо»" in _detail(stub, "media")


def test_media_rf_near_one_passes():
    stub = _media_stub()
    stub._trial_rf_deadline = 0.0
    stub._trial_media_rf_poll({"rf": 1008})
    assert _status(stub, "media") == "pass"


def test_media_rf_far_from_one_fails_after_the_deadline():
    stub = _media_stub()
    stub._trial_rf_deadline = 0.0
    stub._trial_media_rf_poll({"rf": 1120})
    assert _status(stub, "media") == "fail"


# ------------------------------------------------------------------ прогон

def test_chamber_plan_covers_every_node():
    stub = _TrialStub()
    plan = stub._trial_build_chamber_plan()
    assert len(plan) == 22
    for node in chamber_fit.NODES_X10:
        labels = [label for plan_node, label, _text in plan if plan_node == node]
        assert "300 пФ" in labels and "600 пФ" in labels and chamber_fit.AIR_NOTE in labels
    wet = [plan_node for plan_node, label, _text in plan if label == chamber_fit.LIQUID_NOTE]
    assert wet == [chamber_fit.REFERENCE_X10]


def test_chamber_refs_must_differ():
    stub = _TrialStub()
    assert not stub._trial_set_chamber_refs("300", "300")
    assert stub._trial_set_chamber_refs("150", "470,5")
    assert stub._trial_chamber_ref2 == 470.5


def test_chamber_capture_rejects_a_point_outside_its_node():
    """Если эмуляция не дошла до измерения, точка встанет в чужой узел, и это обязано ловиться."""
    stub = _TrialStub()
    stub._trial_chamber_plan = stub._trial_build_chamber_plan()
    stub._chamber_points = [{"note": "300 пФ", "board_temp_x10": 248, "fuel_temp_x10": 248, "main": 4100}]
    stub._trial_chamber_capture_done({"w_node": True, "capture_started": True, "captured": True})
    assert _status(stub, "chamber") == "fail"
    assert "Эмуляция не дошла" in _detail(stub, "chamber")
    assert stub._trial_chamber_index == 0


def test_chamber_capture_advances_on_a_good_point():
    stub = _TrialStub()
    stub._trial_chamber_plan = stub._trial_build_chamber_plan()
    stub._chamber_points = [{"note": "300 пФ", "board_temp_x10": -400, "fuel_temp_x10": -400, "main": 4100}]
    stub._trial_chamber_capture_done({"w_node": True, "capture_started": True, "captured": True})
    assert stub._trial_chamber_index == 1
    assert "600 пФ" in _detail(stub, "chamber")


def test_chamber_compute_treats_missing_references_as_failure():
    stub = _TrialStub()
    stub._trial_chamber_plan = stub._trial_build_chamber_plan()
    stub._trial_chamber_index = len(stub._trial_chamber_plan)
    stub._chamber_report = ["узел -40 °C: только 1 ёмкость, нужно минимум 2. Разделить сдвиг и растяжение нельзя"]
    stub._trial_chamber_compute_done({"computed": True})
    assert _status(stub, "chamber") == "fail"


def test_chamber_compute_passes_with_expected_notes_only():
    """Замечания о пробе и о достройке ожидаемы на столе и провалом не считаются."""
    stub = _TrialStub()
    stub._trial_chamber_plan = stub._trial_build_chamber_plan()
    stub._trial_chamber_index = len(stub._trial_chamber_plan)
    stub._chamber_report = [
        "в прогоне есть точки пробной калибровки с эмуляцией температуры",
        "нет замера погружённой трубки в узлах: -40 °C",
        "строки «в жидкости» для основного контура достроены по размаху 4800 отсчётов",
    ]
    stub._trial_chamber_compute_done({"computed": True})
    assert _status(stub, "chamber") == "pass"


# ------------------------------------------------------------------ применение

def _apply_answers(stub, raw=7000, shift_at=None, mode=0x09):
    profile = {name: list(values) for name, values in stub._profile_values.items()}
    answers = {"status": 0x0F, "zero_trim": 0, "emul_off_end": True}
    for index, temperature in enumerate(stub.TRIAL_APPLY_TEMPS_X10):
        prediction = profile_model.predict_main(raw, profile, board_temp_x10=temperature,
                                                tube_temp_x10=temperature, trusted=True)
        comp = prediction["compensated"] + (10 if shift_at == index else 0)
        answers.update({
            f"w{index}": True, f"raw_a{index}": raw, f"raw_b{index}": raw,
            f"board{index}": prediction["board_stage"], f"comp{index}": comp, f"mode{index}": mode,
        })
    return answers


def test_apply_passes_when_the_device_matches_the_model():
    stub = _TrialStub()
    problems, lines = stub._trial_apply_compare(_apply_answers(stub))
    assert problems == []
    assert len(lines) == len(stub.TRIAL_APPLY_TEMPS_X10)


def test_apply_catches_a_wrong_period_and_names_the_temperature():
    stub = _TrialStub()
    problems, _lines = stub._trial_apply_compare(_apply_answers(stub, shift_at=1))
    assert len(problems) == 1
    assert "-30.0 °C" in problems[0]


def test_apply_catches_a_stage_that_is_not_working():
    """Если прибор не сообщает о работе ступени трубки, совпадение чисел могло быть случайным."""
    stub = _TrialStub()
    problems, _lines = stub._trial_apply_compare(_apply_answers(stub, mode=0x01))
    assert problems
    assert all("признаки" in item for item in problems)


def test_apply_tolerates_a_recalculation_between_reads():
    """Прибор мог пересчитать цепочку между запросами, это не должно считаться ошибкой."""
    stub = _TrialStub()
    answers = _apply_answers(stub)
    answers["raw_b0"] = 7002
    problems, _lines = stub._trial_apply_compare(answers)
    assert problems == []


# ------------------------------------------------------------------ сохранение

def test_persist_fails_when_emulation_survives_the_reset():
    stub = _TrialStub()
    stub._trial_expected = {"empty": 4820}
    stub._trial_persist_done({"reset": True, "p_empty": 4820, "p_emul": -400, "p_status": 0x08})
    assert _status(stub, "persist") == "fail"
    assert "пережила перезапуск" in _detail(stub, "persist")
    assert stub.invalidated, "сессия калибровки на экране обязана закрыться после перезапуска"


def test_persist_passes_and_closes_the_session():
    stub = _TrialStub()
    stub._trial_expected = {"empty": 4820, "crc": 0x1234}
    stub._trial_persist_done({"reset": True, "p_empty": 4820, "p_crc": 0x1234,
                              "p_emul": TRIAL_EMULATION_OFF_VALUE, "p_status": 0x0F})
    assert _status(stub, "persist") == "pass"
    assert stub.invalidated


def test_persist_catches_a_lost_value():
    stub = _TrialStub()
    stub._trial_expected = {"media_air": 2000}
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
    """Ответ на чужой номер не должен засчитываться: иначе проверка сверит не ту величину."""
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
