"""Проверки связи с камерой в программе и автоматического прогона.

Автоматический прогон идёт сутки без человека рядом. Ошибка в порядке шагов
означает потерянные сутки камеры. Тесты закрепляют:
- прогон проходит все узлы по порядку: уставка, выход на неё, устоявшаяся
  плата, точки, следующий узел, а в конце возвращает камеру к +25 °C;
- точку не снимают, пока плата не устоялась, даже если воздух уже на уставке;
- при нескольких пометках оператора зовут только когда нужно переключить
  эталоны, и порядок чередуется, чтобы переключений было меньше;
- затянувшийся этап предупреждает один раз, а не на каждом шаге;
- имитатор задаёт прибору температуру изделия через эмуляцию;
- температура камеры попадает в журнал прогона, старые журналы читаются;
- уставка вне пределов не уходит в камеру; настройки переживают перезапуск.
"""

from __future__ import annotations

import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from tests.test_chamber_run import _ChamberStub, _full_run_points, _Signal
from tests.test_chamber_test_mode import _TestStub
from ui.qml.climate_chamber import SimulatedChamber
from ui.qml.controller.climate_chamber_mixin import AppControllerClimateChamberMixin, parse_labels, parse_nodes


class _FakeLink:
    """Связь с камерой без потока: команды сразу уходят в имитатор."""

    def __init__(self, driver):
        self.driver = driver
        self.commands = []

    def command(self, name, value=None):
        self.commands.append((name, value))
        if name == "setpoint":
            self.driver.set_setpoint(value)
        elif name == "run":
            self.driver.set_running(value)

    def close(self):
        pass


class _ClimateStub(AppControllerClimateChamberMixin, _TestStub):
    """Камера, прибор и прогон без Qt, шины и потоков."""

    def __init__(self, root: Path):
        _TestStub.__init__(self, root)
        self.climateChanged = _Signal()
        self.events = []
        self._climate_lock = __import__("threading").Lock()
        self._climate_incoming = []
        self._climate_settings = self._climate_default_settings()
        self._climate_settings["driver"] = "simulator"
        self._climate_reading = None
        self._climate_last_ok_s = 0.0
        self._climate_status = ""
        self._climate_ok = False
        self._climate_command_status = ""
        self._climate_lost_reported = False
        self._climate_alarm_reported = 0
        self._climate_history = deque(maxlen=5000)
        self._climate_board = deque(maxlen=5000)
        self._climate_last_board_s = 0.0
        self._climate_bridge_last_s = 0.0
        self._climate_bridge_status = ""
        self._climate_run_reset()
        self.clock = [0.0]
        self.sim = SimulatedChamber(clock=lambda: self.clock[0], seed=3)
        self.sim.set_running(True)
        self.sim.set_setpoint(23.0)
        self._climate_link = _FakeLink(self.sim)

    def _remote_event(self, text, level="info", telegram=True):
        self.events.append((level, text))


def _run_until_done(stub, labels_switch=None, limit=4000, step_s=30.0):
    """Ведёт прогон модельным временем: камера, прибор и такт программы."""
    start = time.monotonic()
    operator_calls = []
    for step in range(limit):
        if not stub._climate_run_stage:
            return operator_calls
        now = start + step * step_s
        stub.clock[0] = step * step_s
        reading = stub.sim.read()
        stub._climate_reading = reading
        stub._climate_last_ok_s = now
        stub._climate_board.append((now, reading.product_c))

        # Прибор отдаёт периоды и температуру изделия: в тестовом режиме её задаёт эмуляция.
        real = time.monotonic()
        for key in ("board_temp", "fuel_temp"):
            stub._chamber_live_recent[key] = []
        for index in range(3):
            stamp = real - 0.3 + index * 0.1
            stub._chamber_live_note("main", 5000, stamp)
            stub._chamber_live_note("media", 4500, stamp)
            stub._chamber_live_note("board_temp", int(round(reading.product_c * 10)), stamp)
            stub._chamber_live_note("fuel_temp", int(round(reading.product_c * 10)), stamp)

        stub._climate_run_tick(now)
        if stub._climate_run_stage == "operator":
            operator_calls.append(stub._climate_run_order[stub._climate_run_label_index])
            stub._climate_run_continue()
            # Продолжение отсчитывает окно от настоящих часов: переносим на модельные.
            stub._climate_run_since = now
    raise AssertionError(f"прогон не закончился: {stub._climate_run_status}")


def test_text_lists_are_parsed():
    assert parse_nodes("25, -40; -20  0 +85 °C") == [25.0, -40.0, -20.0, 0.0, 85.0]
    assert parse_labels(" 0/0; 68/22 ;;150/47 ") == ["0/0", "68/22", "150/47"]


def test_run_walks_all_nodes_and_returns_the_chamber(tmp_path: Path):
    stub = _ClimateStub(tmp_path)
    stub._climate_settings["run_nodes"] = "25, -40, 85"
    stub._chamber_label = "0/0"
    stub._climate_reading = stub.sim.read()
    stub._climate_last_ok_s = time.monotonic()

    assert stub._climate_run_start()
    _run_until_done(stub)

    setpoints = [value for name, value in stub._climate_link.commands if name == "setpoint"]
    assert setpoints == [25.0, -40.0, 85.0, 25.0]
    boards = [point["board_temp_x10"] for point in stub._chamber_points]
    assert boards == pytest.approx([250, -400, 850], abs=2)
    assert all(point["note"] == "0/0" for point in stub._chamber_points)
    # Температура камеры легла в каждую точку.
    assert all("chamber_temp_x10" in point for point in stub._chamber_points)
    assert any("закончен" in text for _level, text in stub.events)


def test_points_wait_for_the_board_not_for_the_air(tmp_path: Path):
    """Воздух на уставке, а плата ещё догоняет: точку снимать рано."""
    stub = _ClimateStub(tmp_path)
    stub._climate_settings["run_nodes"] = "-40"
    stub._chamber_label = "0/0"
    stub._climate_reading = stub.sim.read()
    stub._climate_last_ok_s = time.monotonic()
    stub._climate_run_start()

    start = time.monotonic()
    reached_at = None
    for step in range(2000):
        now = start + step * 30.0
        stub.clock[0] = step * 30.0
        reading = stub.sim.read()
        stub._climate_reading = reading
        stub._climate_last_ok_s = now
        stub._climate_board.append((now, reading.product_c))
        stub._climate_run_tick(now)
        if stub._climate_run_stage == "settle" and reached_at is None:
            reached_at = reading.product_c
        if stub._climate_run_stage == "points":
            break
    assert reached_at is not None and reached_at > -38.0
    assert stub.sim.product_c == pytest.approx(-40.0, abs=0.3)


def test_operator_is_called_only_to_switch_references(tmp_path: Path):
    stub = _ClimateStub(tmp_path)
    stub._climate_settings["run_nodes"] = "25, -40, -20"
    stub._climate_settings["run_labels"] = "0/0; 150/47"
    stub._chamber_label = "0/0"
    stub._climate_reading = stub.sim.read()
    stub._climate_last_ok_s = time.monotonic()
    stub._climate_run_start()

    calls = _run_until_done(stub)

    # Порядок чередуется: 0/0 -> 150/47, затем 150/47 -> 0/0, затем снова: по переключению на узел.
    assert calls == ["150/47", "0/0", "150/47"]
    notes = [point["note"] for point in stub._chamber_points]
    assert notes == ["0/0", "150/47", "150/47", "0/0", "0/0", "150/47"]
    assert sum("переключите эталоны" in text for _level, text in stub.events) == 3


def test_slow_stage_warns_once(tmp_path: Path):
    stub = _ClimateStub(tmp_path)
    stub._climate_settings["run_nodes"] = "-40"
    stub._climate_settings["reach_timeout_min"] = 5.0
    stub._chamber_label = "0/0"
    stub._climate_reading = stub.sim.read()
    stub._climate_last_ok_s = time.monotonic()
    stub._climate_run_start()
    start = time.monotonic()
    for step in range(40):
        now = start + step * 30.0
        stub.clock[0] = step * 30.0
        stub._climate_reading = stub.sim.read()
        stub._climate_last_ok_s = now
        stub._climate_run_tick(now)
    assert sum("не вышла" in text for _level, text in stub.events) == 1
    assert stub._climate_run_stage == "reach"


def test_run_needs_a_live_chamber(tmp_path: Path):
    stub = _ClimateStub(tmp_path)
    assert not stub._climate_run_start()
    assert "нет связи" in stub._climate_run_status


def test_setpoint_outside_limits_is_not_sent(tmp_path: Path):
    stub = _ClimateStub(tmp_path)
    assert not stub._climate_send_setpoint(-60.0)
    assert stub._climate_link.commands == []
    assert "пределов" in stub._climate_command_status
    assert stub._climate_set_setpoint_text("-12,5")
    assert stub._climate_link.commands == [("setpoint", -12.5)]


def test_simulator_drives_the_device_emulation(tmp_path: Path):
    """В тестовом режиме прибор показывает температуру изделия из имитатора."""
    stub = _ClimateStub(tmp_path)
    stub.open_access()
    stub._climate_reading = stub.sim.read()
    stub._climate_reading.product_c = -12.34
    stub._climate_last_ok_s = time.monotonic()

    stub._climate_bridge(time.monotonic())
    assert stub._chamber_test_target == -123
    assert "-12,3" in stub._climate_bridge_status

    # Пока температура меняется, следующая запись ждёт паузу.
    stub._chamber_test_stage = ""
    stub._climate_reading.product_c = -15.0
    stub._climate_bridge(stub._climate_bridge_last_s + 0.1)
    assert stub._chamber_test_target == -123


def test_bridge_needs_test_mode(tmp_path: Path):
    stub = _ClimateStub(tmp_path)
    stub._chamber_test_mode = False
    stub._climate_reading = stub.sim.read()
    stub._climate_last_ok_s = time.monotonic()
    stub._climate_bridge(time.monotonic())
    assert stub._chamber_test_target is None
    assert "тестовый режим" in stub._climate_bridge_status


def test_chamber_temperature_goes_to_the_journal(tmp_path: Path):
    stub = _ChamberStub()
    stub._chamber_points = _full_run_points()
    stub._chamber_points[0]["chamber_temp_x10"] = -412
    path = tmp_path / "run.csv"
    assert stub._chamber_save_file(str(path))

    restored = _ChamberStub()
    assert restored._chamber_load_file(str(path))
    assert restored._chamber_points == stub._chamber_points
    assert "Температура камеры" in path.read_text(encoding="utf-8-sig").splitlines()[0]


def test_old_journal_without_chamber_column_is_read(tmp_path: Path):
    path = tmp_path / "old.csv"
    path.write_text(
        "Время;Что подключено;Период основного контура;Период контура вида топлива;"
        "Температура топлива (°C);Температура платы (°C);Режим\n"
        "12:00:00;0/0;4820;4500;25,0;25,4;\n", encoding="utf-8-sig")
    stub = _ChamberStub()
    assert stub._chamber_load_file(str(path))
    assert stub._chamber_points[0]["board_temp_x10"] == 254
    assert "chamber_temp_x10" not in stub._chamber_points[0]


def test_settings_survive_a_restart(tmp_path: Path):
    stub = _ClimateStub(tmp_path)
    stub._climate_link = None
    assert stub._climate_set("tcp_host", "192.168.100.7")
    assert stub._climate_set("map.setpoint.address", "300")
    assert stub._climate_set("map.setpoint.value_type", "float32")
    assert not stub._climate_set("tcp_port", "много")
    assert not stub._climate_set("driver", "telepathy")

    loaded = _ClimateStub(tmp_path)._climate_load_settings()
    assert loaded["tcp_host"] == "192.168.100.7"
    assert loaded["map"]["setpoint"]["address"] == 300
    assert loaded["map"]["setpoint"]["value_type"] == "float32"


def test_alarm_is_reported_once(tmp_path: Path):
    stub = _ClimateStub(tmp_path)
    reading = stub.sim.read()
    reading.alarm = 7
    stub._climate_link = _FakeLink(stub.sim)
    for _ in range(3):
        stub._climate_queue_state({"kind": "reading", "ok": True, "reading": reading})
        stub._climate_take_incoming(time.monotonic())
    assert sum("АВАРИЯ" in text for _level, text in stub.events) == 1


def test_view_is_built(tmp_path: Path):
    stub = _ClimateStub(tmp_path)
    stub._climate_reading = stub.sim.read()
    stub._climate_last_ok_s = time.monotonic()
    view = stub._climate_view()
    assert view["actualText"].endswith("°C")
    assert [node["text"] for node in view["run"]["nodes"]][0] == "+25,0 °C"
    assert view["canSet"] is True
