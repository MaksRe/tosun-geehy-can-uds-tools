"""Проверки раздела «Текущие данные узла».

После калибровки в колбе по этому разделу смотрят, какой уровень выдаёт прибор,
и понимают, что с узлом: мерят ли контуры, откуда температура, что записано и
работает. Если раздел покажет старое число как свежее или спутает состояние,
калибровку сочтут удачной, когда она не удалась.

Тесты закрепляют: числа и температуры разбираются верно; старые значения
сереют; опрос спрашивает быстрые числа чаще остальных и уступает шину; параметр,
которого нет в прошивке, перестают спрашивать; уровень J1939 берётся только от
выбранного узла; отладочные строки говорят словами и с правильным тоном.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller import live_freshness_mixin as lf
from ui.qml.controller import node_live_mixin as nl
from uds.data_identifiers import UdsData

RX_ID = 0x18DA2AF1


class _Signal:
    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _FakeRead:
    def __init__(self):
        self.sent = []

    def read_data_by_identifier(self, identifier, var):
        self.sent.append(int(var.pid) & 0xFFFF)
        return True


class _FakeCan:
    is_connect = True
    is_trace = True


class _NodeStub(nl.AppControllerNodeLiveMixin, lf.AppControllerLiveFreshnessMixin):
    """Логика раздела без Qt и без шины."""

    def __init__(self):
        self.nodeLiveChanged = _Signal()
        self.liveFreshnessChanged = _Signal()
        self._can = _FakeCan()
        self._node_live_read = _FakeRead()
        keys = [item[0] for item in nl.NODE_LIVE_VARS]
        self._node_live = {key: None for key in keys}
        self._node_live_seen = {key: 0.0 for key in keys}
        self._node_live_asked = {key: 0.0 for key in keys}
        self._node_live_refusals = {}
        self._node_live_missing = set()
        self._node_live_pending_key = None
        self._node_live_pending_s = 0.0
        self._node_live_j1939 = None
        self._node_live_j1939_seen = 0.0
        self._node_live_enabled = True
        self._node_live_last_inject = 0.0
        self._node_live_last_poll = 0.0
        self._node_live_suspend_until = 0.0
        self._live_tracks = {"level": lf.LiveTrack(), "flatcap": lf.LiveTrack()}
        self._live_age = {"main_ms": None, "media_ms": None, "received_s": None, "supported": None, "misses": 0}
        self._live_age_counters = {"level": 0, "flatcap": 0}
        self._calibration_active = True
        self._calibration_session_ready = True

    def _node_trend_note(self, key, value, now=None):
        """Истории графиков в заглушке нет: показание никуда не кладётся."""

    def _calibration_log_note(self, key):
        """Журнала калибровки в заглушке нет: строка не пишется."""

    def _is_calibration_response_identifier(self, identifier):
        return identifier == RX_ID

    def _build_calibration_tx_identifier(self):
        return 0x18DAF12A

    def _resolve_calibration_target_sa(self):
        return 0x2A


def _answer(stub, var, data):
    did = int(var.pid) & 0xFFFF
    body = [0x62, did >> 8, did & 0xFF] + list(data)
    stub._handle_node_live_frame(RX_ID, [len(body)] + body + [0x00] * (7 - len(body)))


def _u16(value):
    value &= 0xFFFF
    return [value & 0xFF, value >> 8]


def _tick(stub, count):
    for _ in range(count):
        stub._uds_background_tx_s = 0.0
        stub._on_node_live_tick()


# ------------------------------------------------------------------ карточки

def test_level_card_shows_what_the_device_calculates():
    stub = _NodeStub()
    _answer(stub, UdsData.raw_fuel_level, _u16(452))
    view = stub._node_live_view()
    assert view["levelText"] == "45,2 %"
    assert view["levelFresh"] is True and view["levelWarn"] is False

    _answer(stub, UdsData.raw_fuel_level, _u16(-12))
    view = stub._node_live_view()
    assert view["levelText"] == "-1,2 %"
    assert view["levelWarn"] is True, "уровень за пределами шкалы подсвечивается"


def test_counts_and_temperatures_are_decoded():
    stub = _NodeStub()
    _answer(stub, UdsData.curr_fuel_tank, _u16(4821))
    _answer(stub, UdsData.raw_temperature, _u16(-400))
    view = stub._node_live_view()
    assert view["mainRaw"] == "4821" and view["mainFresh"] is True
    assert view["fuelTemp"] == "-40.0 °C" and view["fuelTempFresh"] is True
    assert view["boardTempFresh"] is False, "ответа о плате не было"
    assert view["tempSource"] == "эмуляция: нет данных"

    _answer(stub, UdsData.temperature_emulation_x10, _u16(nl.EMULATION_OFF_VALUE))
    assert stub._node_live_view()["tempSource"] == "с датчика"
    _answer(stub, UdsData.temperature_emulation_x10, _u16(850))
    view = stub._node_live_view()
    assert view["tempSource"] == "задана эмуляцией" and view["emulationOn"] is True


def test_answers_note_freshness_of_both_circuits():
    stub = _NodeStub()
    _answer(stub, UdsData.curr_fuel_tank, _u16(4821))
    _answer(stub, UdsData.fuel_media_flatcap_raw, _u16(2380))
    view = stub._node_live_view()
    assert view["mainFreshness"]["text"].startswith("ответ ")
    assert view["mediaFreshness"]["text"].startswith("ответ ")


def test_frames_are_ignored_while_the_section_is_closed():
    stub = _NodeStub()
    stub._node_live_enabled = False
    _answer(stub, UdsData.curr_fuel_tank, _u16(4821))
    assert stub._node_live["main_raw"] is None


def test_old_values_turn_gray():
    stub = _NodeStub()
    _answer(stub, UdsData.curr_fuel_tank, _u16(4821))
    stub._node_live_seen["main_raw"] = time.monotonic() - 20.0
    assert stub._node_live_view()["mainFresh"] is False


# ------------------------------------------------------------------ опрос

def test_first_round_asks_every_parameter_fast_ones_first():
    stub = _NodeStub()
    _tick(stub, len(nl.NODE_LIVE_VARS))
    sent = stub._node_live_read.sent
    assert sent[:3] == [int(UdsData.curr_fuel_tank.pid), int(UdsData.fuel_media_flatcap_raw.pid),
                        int(UdsData.raw_fuel_level.pid)]
    assert sorted(sent) == sorted(int(item[1].pid) & 0xFFFF for item in nl.NODE_LIVE_VARS)


def test_fast_values_come_back_before_slow_ones():
    stub = _NodeStub()
    now = 1000.0
    for key in stub._node_live_asked:
        stub._node_live_asked[key] = now - 2.0
    picked = [stub._node_live_pick(now)[0]]
    stub._node_live_asked[picked[0]] = now
    picked.append(stub._node_live_pick(now)[0])
    assert set(picked) <= {"main_raw", "media", "level"}


def test_age_is_skipped_for_firmware_without_it():
    stub = _NodeStub()
    stub._live_age["supported"] = False
    _tick(stub, len(nl.NODE_LIVE_VARS))
    assert int(UdsData.measurement_age.pid) not in stub._node_live_read.sent


def test_parameter_refused_twice_is_no_longer_asked():
    stub = _NodeStub()
    for _ in range(2):
        stub._node_live_pending_key = "board_stage"
        stub._node_live_pending_s = time.monotonic()
        stub._handle_node_live_frame(RX_ID, [0x03, 0x7F, 0x22, 0x31, 0, 0, 0, 0])
    assert "board_stage" in stub._node_live_missing
    assert stub._node_live_view()["rows"]["board_stage"]["value"] == "нет в прошивке"

    _tick(stub, len(nl.NODE_LIVE_VARS))
    assert int(UdsData.fuel_board_stage_period.pid) not in stub._node_live_read.sent


def test_late_foreign_refusal_is_not_counted():
    stub = _NodeStub()
    stub._node_live_pending_key = "board_stage"
    stub._node_live_pending_s = time.monotonic() - 5.0
    stub._handle_node_live_frame(RX_ID, [0x03, 0x7F, 0x22, 0x31, 0, 0, 0, 0])
    assert stub._node_live_refusals == {}


def test_poll_yields_the_bus_and_waits_for_the_device():
    stub = _NodeStub()
    stub._calibration_session_ready = False
    _tick(stub, 1)
    assert stub._node_live_read.sent == [], "пока калибровка открывает доступ, опрос молчит"

    stub._calibration_session_ready = True
    stub._profile_busy = True
    _tick(stub, 1)
    assert stub._node_live_read.sent == [], "другой раздел занял шину"

    stub._profile_busy = False
    stub._node_live_suspend_until = time.monotonic() + 5.0
    _tick(stub, 1)
    assert stub._node_live_read.sent == [], "прибор перезапускается"

    stub._node_live_suspend_until = 0.0
    _tick(stub, 1)
    assert len(stub._node_live_read.sent) == 1


# ------------------------------------------------------------------ J1939

class _Id:
    def __init__(self, pgn, src):
        self.pgn = pgn
        self.src = src


def test_j1939_level_comes_only_from_the_selected_node():
    stub = _NodeStub()
    stub._handle_node_live_j1939_frame(_Id(0xFEFC, 0x33), [0xFF, 200, 0, 0, 0, 0, 0, 0])
    assert stub._node_live_view()["levelJ1939Text"] == "J1939: кадров уровня нет"

    stub._handle_node_live_j1939_frame(_Id(0xFEFC, 0x2A), [0xFF, 113, 0, 0, 0, 0, 0, 0])
    assert stub._node_live_view()["levelJ1939Text"] == "J1939: 45,2 %"

    stub._handle_node_live_j1939_frame(_Id(0xFEFC, 0x2A), [0xFF, 0xFF, 0, 0, 0, 0, 0, 0])
    assert stub._node_live_view()["levelJ1939Text"] == "J1939: нет данных у прибора"


# ------------------------------------------------------------------ отладочные строки

def test_debug_rows_speak_plainly():
    stub = _NodeStub()
    _answer(stub, UdsData.fuel_media_state, [0x05])
    _answer(stub, UdsData.fuel_board_stage_mode, [0x09])
    _answer(stub, UdsData.fuel_thermal_profile_status, [0x01])
    _answer(stub, UdsData.fuel_tank_model, [0x01])
    _answer(stub, UdsData.fuel_media_rf_x1000, _u16(1100))
    _answer(stub, nl.VAR_ACTIVE_PROGRAM, [0x01])
    _answer(stub, UdsData.eeprom_state, [0x02, 0x00, 0x00, 0x00])
    rows = stub._node_live_view()["rows"]

    assert rows["media_state"] == {"value": "применяется, обновление заморожено", "fresh": True, "tone": nl.TONE_WARN}
    assert rows["stage_mode"]["value"] == "плата основного, трубка основного"
    assert rows["profile_status"]["value"] == "не применяется: сумма не сходится, алгоритм не тот"
    assert rows["profile_status"]["tone"] == nl.TONE_BAD
    assert rows["tank_model"]["value"] == "по двум контурам"
    assert rows["rf"]["value"] == "1,100"
    assert rows["program"] == {"value": "загрузчик", "fresh": True, "tone": nl.TONE_BAD}
    assert rows["eeprom"]["value"] == "пишется, осталось параметров 2"


def test_state_texts_for_faults_and_resets():
    assert nl.media_state_text(0x0A) == ("отказ контура, контур молчит", nl.TONE_BAD)
    assert nl.media_state_text(0x00) == ("не применяется", nl.TONE_NORMAL)
    assert nl.stage_mode_text(0x04)[1] == nl.TONE_BAD
    assert nl.profile_status_text(0x0E) == ("пустой", nl.TONE_NORMAL)
    assert nl.profile_status_text(0x0F) == ("таблицы применяются", nl.TONE_OK)
    text, tone = nl.eeprom_text([0x00, 0x08, 0x00, 0x00])
    assert tone == nl.TONE_BAD and "заводскими" in text
    assert nl.eeprom_text([0x00, 0x00, 0x00, 0x00]) == ("всё записано", nl.TONE_OK)
