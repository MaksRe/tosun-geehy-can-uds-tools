"""Проверки тестового режима прогона: камера на столе.

Режим нужен, чтобы до выезда в камеру пройти весь путь на столе: задать
прибору температуру эмуляцией, снять точки во всех узлах, посчитать таблицы и
записать профиль. Тесты закрепляют:
- температура задаётся только после открытия доступа и считается заданной,
  когда прибор её показал;
- отказ прибора называется, а не превращается в вечное ожидание;
- обход проходит все узлы сетки, пишет точку в каждом и в конце выключает эмуляцию;
- имитация ухода добавляется к периодам, а расчёт её восстанавливает;
- выключение режима гасит эмуляцию в приборе.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_fit
from ui.qml.controller.chamber_chain_mixin import AppControllerChamberChainMixin
from ui.qml.controller.chamber_test_mixin import EMULATION_OFF_WIRE, AppControllerChamberTestMixin
from tests.test_chamber_auto import _FakeTimer, _LiveStub


class _FakeWrite:
    def __init__(self):
        self.sent = []

    def write_data(self, var, value, tx_identifier=None):
        self.sent.append((int(var.pid), int(value)))
        return True


class _TestStub(AppControllerChamberTestMixin, AppControllerChamberChainMixin, _LiveStub):
    """Прогон в тестовом режиме: живые показания, эмуляция и запись профиля без Qt и шины."""

    def __init__(self, root: Path | None = None):
        _LiveStub.__init__(self, root)
        self._chamber_test_write_service = _FakeWrite()
        self._chamber_test_mode = True
        self._chamber_test_drift_on = False
        self._chamber_test_emulation = None
        self._chamber_test_target = None
        self._chamber_test_stage = ""
        self._chamber_test_deadline = 0.0
        self._chamber_test_pending = False
        self._chamber_test_pending_s = 0.0
        self._chamber_test_attempt = 0
        self._chamber_test_status = ""
        self._chamber_test_color = ""
        self._chamber_test_walk = []
        self._chamber_test_walk_stage = ""
        self._chamber_test_walk_points = 0
        self._chamber_test_walk_deadline = 0.0
        self._chamber_test_walk_total = 0
        self._chamber_test_check_text = ""
        self._chamber_test_check_color = ""
        self._chamber_test_timer = _FakeTimer()

        # Запись профиля сама в этих проверках не нужна.
        self._chamber_auto_write = False
        self._chamber_chain_stage = ""

        self._calibration_active = False
        self._calibration_session_ready = False
        self._service_access_target_sa = None
        self._service_security_unlocked = False
        self.toggled = 0

    def _resolve_calibration_target_sa(self):
        return 0x6A

    def _build_calibration_tx_identifier(self):
        return 0x18DA6AF1

    def _is_calibration_response_identifier(self, identifier):
        return True

    def toggleCalibration(self):
        self.toggled += 1
        self._calibration_active = True

    def open_access(self):
        self._calibration_active = True
        self._calibration_session_ready = True
        self._service_access_target_sa = 0x6A
        self._service_security_unlocked = True


def _confirm_write(stub):
    """Прибор подтвердил запись эмуляции."""
    did = 0x0061
    stub._handle_chamber_test_frame(0x18DAF16A, [0x03, 0x6E, (did >> 8) & 0xFF, did & 0xFF, 0, 0, 0, 0])


def _device_reports(stub, temperature_x10=None, main=7600, media=5400):
    """Прибор отдаёт показания: температуры те, что заданы эмуляцией."""
    now = time.monotonic()
    temp = 250 if temperature_x10 is None else temperature_x10
    for index in range(3):
        stamp = now - 0.6 + index * 0.2
        stub._chamber_live_note("main", main, stamp)
        stub._chamber_live_note("media", media, stamp)
        stub._chamber_live_note("board_temp", temp, stamp)
        stub._chamber_live_note("fuel_temp", temp, stamp)


def _drive(stub, limit=400, **values):
    """Ведёт тестовый режим до конца: прибор подтверждает записи и показывает заданное."""
    for _ in range(limit):
        if not stub._chamber_test_stage and not stub._chamber_test_walk_stage:
            return
        stub._uds_background_tx_s = 0.0
        if stub._chamber_test_pending:
            _confirm_write(stub)
        if stub._chamber_test_stage == "settle":
            _device_reports(stub, stub._chamber_test_target, **values)
        stub._on_chamber_test_tick()
    raise AssertionError(f"тестовый режим не закончил: {stub._chamber_test_status}")


# ------------------------------------------------------------------ температура

def test_temperature_is_set_after_access_and_confirmed_by_the_device():
    stub = _TestStub()
    assert stub._chamber_test_start_set(-400)
    assert stub.toggled == 1

    # Доступ ещё закрыт: в прибор ничего не уходит.
    stub._on_chamber_test_tick()
    assert stub._chamber_test_write_service.sent == []

    stub.open_access()
    stub._uds_background_tx_s = 0.0
    stub._on_chamber_test_tick()
    assert stub._chamber_test_write_service.sent == [(0x0061, (-400) & 0xFFFF)]

    _confirm_write(stub)
    assert stub._chamber_test_stage == "settle"

    _device_reports(stub, -400)
    stub._on_chamber_test_tick()
    assert stub._chamber_test_stage == ""
    assert stub._chamber_test_emulation == -400
    assert "показывает" in stub._chamber_test_status


def test_old_temperature_readings_do_not_count_after_the_change():
    """Пока прибор не показал новую температуру, старые показания её не подменяют."""
    stub = _TestStub()
    stub.open_access()
    _device_reports(stub, 250)
    stub._chamber_test_start_set(-200)
    stub._uds_background_tx_s = 0.0
    stub._on_chamber_test_tick()
    _confirm_write(stub)

    assert stub._chamber_live_stats("board_temp") is None
    _device_reports(stub, 250)
    stub._on_chamber_test_tick()
    assert stub._chamber_test_stage == "settle"


def test_refusal_is_named():
    stub = _TestStub()
    stub.open_access()
    stub._chamber_test_start_set(500)
    stub._uds_background_tx_s = 0.0
    stub._on_chamber_test_tick()

    stub._handle_chamber_test_frame(0x18DAF16A, [0x03, 0x7F, 0x2E, 0x33, 0, 0, 0, 0])

    assert stub._chamber_test_stage == ""
    assert "закрыл запись" in stub._chamber_test_status


def test_lost_write_is_repeated_then_abandoned():
    stub = _TestStub()
    stub.open_access()
    stub._chamber_test_start_set(500)
    for _ in range(stub.CHAMBER_TEST_WRITE_RETRIES + 2):
        stub._uds_background_tx_s = 0.0
        stub._on_chamber_test_tick()
        stub._chamber_test_pending_s -= 10.0
        stub._on_chamber_test_tick()

    assert len(stub._chamber_test_write_service.sent) == stub.CHAMBER_TEST_WRITE_RETRIES + 1
    assert stub._chamber_test_stage == ""
    assert "не ответил" in stub._chamber_test_status


def test_temperature_needs_test_mode():
    stub = _TestStub()
    stub._chamber_test_mode = False
    assert not stub._chamber_test_start_set(-400)
    assert "тестовый режим" in stub._chamber_test_status


def test_temperature_text_is_parsed():
    stub = _TestStub()
    stub.open_access()
    assert stub._chamber_test_set_text("-12,5 °C")
    assert stub._chamber_test_target == -125
    assert not _TestStub()._chamber_test_set_text("холодно")


def test_switching_the_mode_off_returns_the_real_temperature():
    stub = _TestStub()
    stub.open_access()
    stub._chamber_test_emulation = -400

    stub._chamber_test_set_mode(False)
    _drive(stub)

    assert stub._chamber_test_write_service.sent[-1] == (0x0061, EMULATION_OFF_WIRE)
    assert stub._chamber_test_emulation is None


# ------------------------------------------------------------------ обход узлов

def test_walk_takes_a_point_at_every_node_and_switches_emulation_off(tmp_path: Path):
    stub = _TestStub(tmp_path)
    stub.open_access()
    stub._chamber_label = "0/0"

    assert stub._chamber_test_walk_start()
    _drive(stub)

    assert [point["board_temp_x10"] for point in stub._chamber_points] == list(chamber_fit.NODES_X10)
    assert all(point["note"] == "0/0" for point in stub._chamber_points)
    # Точки на столе помечаются: по журналу видно, что это не настоящая камера.
    assert all(point["rehearsal"] for point in stub._chamber_points)
    assert stub._chamber_test_emulation is None
    assert stub._chamber_test_write_service.sent[-1] == (0x0061, EMULATION_OFF_WIRE)
    assert "закончен" in stub._chamber_test_status
    # Журнал сохранился сам и на столе.
    assert Path(stub._chamber_file_path).exists()


def test_walk_needs_a_label():
    stub = _TestStub()
    assert not stub._chamber_test_walk_start()
    assert "пометка" in stub._chamber_test_status


def test_walk_can_be_stopped():
    stub = _TestStub()
    stub.open_access()
    stub._chamber_label = "0/0"
    stub._chamber_test_walk_start()
    stub._on_chamber_test_tick()

    stub._chamber_test_walk_stop()
    assert stub._chamber_test_walk_stage == ""
    assert stub._chamber_test_walk == []


def test_three_walks_give_complete_tables_and_allow_the_bench_write(tmp_path: Path):
    """Три обхода с разными эталонами плюс трубка - таблицы полные, запись на стенд разрешена."""
    stub = _TestStub(tmp_path)
    stub.open_access()
    applied = {}
    stub._profile_apply_chamber_format = lambda payload: applied.update(payload) or True

    for note, main, media in (("0/0", 4820, 4500), ("68/22", 7601, 5409), ("150/47", 10955, 6441),
                              ("воздух", 7300, 5000), ("жидкость", 9700, 6000)):
        stub._chamber_label = note
        stub._chamber_test_walk_start()
        _drive(stub, main=main, media=media)

    assert len(stub._chamber_points) == 5 * len(chamber_fit.NODES_X10)
    assert stub._chamber_tables_complete
    assert "Тестовый прогон" in stub._chamber_tables_text
    assert applied.get("ступень_платы")
    # Пробные точки запись на стенд не запрещают, пока включён тестовый режим.
    stub._profile_validate = lambda: []
    stub._profile_busy = False
    stub._options_busy = False
    assert stub._chamber_chain_problem() == ""
    stub._chamber_test_mode = False
    assert "тестовом режиме" in stub._chamber_chain_problem()


# ------------------------------------------------------------------ имитация ухода

def test_drift_is_added_to_the_point():
    stub = _TestStub()
    stub._chamber_test_drift_on = True
    point = {"main": 10000, "media": 6000, "board_temp_x10": -400, "fuel_temp_x10": -400}

    drifted = stub._chamber_test_apply_drift(point)

    gain, offset = stub.CHAMBER_TEST_DRIFT["main"]
    assert drifted["main"] == round(10000 * (1 + gain * -65 / 1e6) + offset * -65)
    assert drifted["media"] != 6000
    # В опорной точке ухода нет.
    same = stub._chamber_test_apply_drift(dict(point, board_temp_x10=250))
    assert same["main"] == 10000 and same["media"] == 6000


def test_drift_is_not_added_outside_test_mode():
    stub = _TestStub()
    stub._chamber_test_drift_on = True
    stub._chamber_test_mode = False
    point = {"main": 10000, "media": 6000, "board_temp_x10": -400, "fuel_temp_x10": -400}
    assert stub._chamber_test_apply_drift(point) is point


def test_calculation_recovers_the_simulated_drift(tmp_path: Path):
    """Главная проверка алгоритмов: заложенный уход расчёт обязан вернуть таблицами платы."""
    stub = _TestStub(tmp_path)
    stub.open_access()
    stub._chamber_test_drift_on = True
    stub._profile_apply_chamber_format = lambda payload: True

    for note, main, media in (("0/0", 4820, 4500), ("68/22", 7601, 5409), ("150/47", 10955, 6441),
                              ("воздух", 7300, 5000), ("жидкость", 9700, 6000)):
        stub._chamber_label = note
        stub._chamber_test_walk_start()
        _drive(stub, main=main, media=media)

    cold = [point for point in stub._chamber_points if point["board_temp_x10"] == -400 and point["note"] == "150/47"]
    assert cold and cold[0]["main"] != 10955

    assert "пройдена" in stub._chamber_test_check_text, stub._chamber_test_check_text


def test_check_fails_when_points_were_taken_without_drift():
    stub = _TestStub()
    stub._chamber_test_drift_on = True
    flat = [[0, 0]] * len(chamber_fit.NODES_X10)
    stub._chamber_test_after_compute({"ступень_платы": flat, "ступень_платы_вида": flat})
    assert "НЕ ПРОЙДЕНА" in stub._chamber_test_check_text
