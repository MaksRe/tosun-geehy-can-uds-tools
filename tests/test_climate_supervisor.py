"""Проверки автономного прогона в климатической камере.

Прогон идёт сутки без человека, поэтому сторож должен сам заметить беду и
сказать о ней один раз, а после перезапуска программы прогон - продолжиться.
Тесты закрепляют:
- проверка перед стартом не даёт начать заведомо неудачный прогон;
- полный прогон записывает время каждого узла и в конце присылает итог;
- авария камеры ставит прогон на паузу; о снятии аварии сообщается;
- остановленную камеру программа пускает снова, не вышло - пауза;
- сменённую на пульте уставку программа возвращает, не вышло - проблема;
- пропажа связи с камерой и молчание прибора - проблемы с сообщением о возврате;
- камера, которая не идёт к уставке, замечается с данными нагревателя;
- сводка приходит по расписанию;
- состояние прогона сохраняется, после перезапуска прогон продолжается с узла.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_climate_run import _ClimateStub
from ui.qml.climate_chamber import ChamberReading
from ui.qml.controller.climate_supervisor_mixin import AppControllerClimateSupervisorMixin, duration_text


class _SupStub(AppControllerClimateSupervisorMixin, _ClimateStub):
    """Камера, прибор, прогон и сторож без Qt, шины и потоков."""

    def __init__(self, root: Path):
        _ClimateStub.__init__(self, root)
        self._climate_auto_init()

    def kinds(self, level=None):
        return [text for lvl, text in self.events if level is None or lvl == level]


def _feed(stub, now, reading=None, board=True):
    """Свежее показание камеры и, если нужно, температура платы от прибора."""
    stub._climate_reading = reading if reading is not None else stub.sim.read()
    stub._climate_last_ok_s = now
    if board:
        value = stub._climate_reading.product_c
        if value is None:
            value = stub._climate_reading.actual_c or 25.0
        stub._chamber_live_note("board_temp", int(round(value * 10)), time.monotonic())


def _ready(tmp_path, nodes="25, -40, 85"):
    stub = _SupStub(tmp_path)
    stub._climate_settings["run_nodes"] = nodes
    stub._chamber_label = "0/0"
    _feed(stub, time.monotonic())
    return stub


def _walk(stub, limit=6000, step_s=30.0):
    """Ведёт прогон модельным временем до конца, со сторожем на каждом шаге."""
    start = time.monotonic()
    for step in range(limit):
        now = start + step * step_s
        stub.clock[0] = step * step_s
        reading = stub.sim.read()
        _feed(stub, now, reading)
        stub._climate_board.append((now, reading.product_c))
        real = time.monotonic()
        for index in range(3):
            stamp = real - 0.3 + index * 0.1
            stub._chamber_live_note("main", 5000, stamp)
            stub._chamber_live_note("media", 4500, stamp)
            stub._chamber_live_note("fuel_temp", int(round(reading.product_c * 10)), stamp)
        if stub._climate_run_stage:
            stub._climate_run_tick(now)
        stub._climate_auto_tick(now)
        if not stub._climate_run_stage and not stub._climate_auto_finishing:
            return now
    raise AssertionError(f"прогон не закончился: {stub._climate_run_status}")


def _started(tmp_path, nodes="-40"):
    stub = _ready(tmp_path, nodes)
    assert stub._climate_run_start()
    return stub, time.monotonic()


def test_duration_text():
    assert duration_text(None) == "—"
    assert duration_text(59) == "0:00"
    assert duration_text(3 * 3600 + 25 * 60) == "3:25"


# ------------------------------------------------------------------ проверка перед стартом

def test_checks_block_a_run_without_chamber_or_board(tmp_path: Path):
    stub = _ready(tmp_path)
    assert stub._climate_auto_view()["canStart"] is True

    stub._climate_link = None
    view = stub._climate_auto_view()
    assert view["canStart"] is False and any("Нет связи с камерой" in text for text in view["blockers"])
    assert not stub._climate_run_start()
    assert "нет связи с камерой" in stub._climate_run_status


def test_test_mode_blocks_a_real_chamber(tmp_path: Path):
    stub = _ready(tmp_path)
    stub._climate_settings["driver"] = "espec"
    stub._chamber_board_only = True
    blockers = stub._climate_auto_blockers()
    assert any("тестовый режим" in text for text in blockers)
    stub._chamber_test_mode = False
    assert not any("тестовый режим" in text for text in stub._climate_auto_blockers())


def test_espec_alarm_limits_must_cover_the_nodes(tmp_path: Path):
    stub = _ready(tmp_path, "25, -40, 85")
    stub._climate_settings["driver"] = "espec"
    stub._chamber_board_only = True
    stub._chamber_test_mode = False
    _feed(stub, time.monotonic(), ChamberReading(actual_c=25.0, setpoint_c=25.0, running=False, alarm=0,
                                                 details={"high_c": 80.0, "low_c": -90.0}))
    assert any("не охватывают узлы" in text for text in stub._climate_auto_blockers())


def test_warnings_do_not_block(tmp_path: Path):
    stub = _ready(tmp_path)
    stub._climate_settings["run_labels"] = "0/0; 150/47"
    view = stub._climate_auto_view()
    warn = {item["key"]: item for item in view["checks"] if item["level"] == "warn"}
    assert "оператор" in warn["labels"]["text"]
    assert warn["telegram"]["ok"] is False
    assert view["canStart"] is True


# ------------------------------------------------------------------ полный прогон и итог

def test_full_run_reports_every_node_and_a_summary(tmp_path: Path):
    stub = _ready(tmp_path, "25, -40, 85")
    assert stub._climate_run_start()
    assert stub._climate_auto_state_path().is_file()
    _walk(stub)

    assert [node for node, _seconds in stub._climate_auto_durations] == [25.0, -40.0, 85.0]
    assert all(seconds > 0 for _node, seconds in stub._climate_auto_durations)
    passed = [text for text in stub.kinds() if "пройден за" in text]
    assert len(passed) == 3 and "Осталось примерно" in passed[0]
    summary = [text for text in stub.kinds() if text.startswith("ИТОГ ПРОГОНА")]
    assert len(summary) == 1
    assert "пройдено 3 из 3 температур" in summary[0] and "-40,0 °C - " in summary[0]
    # Прогон закончен: продолжать после перезапуска нечего.
    assert not stub._climate_auto_state_path().exists()


def test_progress_and_eta_in_the_view(tmp_path: Path):
    stub, start = _started(tmp_path, "25, -40")
    stub._climate_auto_on_node_done(25.0, start + 3600)
    stub._climate_run_index = 1
    view = stub._climate_auto_view()
    assert view["progress"] == 0.5
    assert "Узел 2 из 2" in view["progressText"] and "осталось ≈" in view["progressText"]
    assert view["nodesText"] == "+25,0 °C - 1:00"


# ------------------------------------------------------------------ сторож

def test_alarm_pauses_the_run(tmp_path: Path):
    stub, now = _started(tmp_path)
    _feed(stub, now, ChamberReading(actual_c=20.0, setpoint_c=-40.0, running=True, alarm=7,
                                    details={"alarms": ["7"]}))
    stub._climate_auto_tick(now)
    assert stub._climate_run_paused and stub._climate_auto_paused_by == "alarm"
    assert any("АВАРИЯ КАМЕРЫ (код 7)" in text for text in stub.kinds("bad"))
    # Повторный такт - без повторного сообщения.
    stub._climate_auto_tick(now + 1)
    assert sum("АВАРИЯ КАМЕРЫ" in text for text in stub.kinds()) == 1

    _feed(stub, now + 2, ChamberReading(actual_c=20.0, setpoint_c=-40.0, running=True, alarm=0))
    stub._climate_auto_tick(now + 2)
    assert any("авария камеры снята" in text for text in stub.kinds("ok"))
    assert stub._climate_run_paused, "после аварии продолжает человек"
    stub._climate_run_pause(False)
    assert stub._climate_auto_paused_by == ""


def test_stopped_chamber_is_restarted_then_paused(tmp_path: Path):
    stub, now = _started(tmp_path)
    stub._climate_run_stage = "reach"
    stopped = ChamberReading(actual_c=20.0, setpoint_c=-40.0, running=False, alarm=0)
    for second in (0, 31):
        _feed(stub, now + second, stopped)
        stub._climate_auto_tick(now + second)
    assert ("run", True) in stub._climate_link.commands
    assert any("камера остановилась" in text for text in stub.kinds("warn"))
    _feed(stub, now + 200, stopped)
    stub._climate_auto_tick(now + 200)
    assert stub._climate_run_paused and stub._climate_auto_paused_by == "stopped"


def test_changed_setpoint_is_restored(tmp_path: Path):
    stub, now = _started(tmp_path)
    stub._climate_run_stage = "settle"
    wrong = ChamberReading(actual_c=-40.0, setpoint_c=30.0, running=True, alarm=0)
    before = [cmd for cmd in stub._climate_link.commands if cmd[0] == "setpoint"]
    for second in (0, 61):
        _feed(stub, now + second, wrong)
        stub._climate_auto_tick(now + second)
    after = [cmd for cmd in stub._climate_link.commands if cmd[0] == "setpoint"]
    assert after[len(before):] == [("setpoint", -40.0)]
    _feed(stub, now + 200, wrong)
    stub._climate_auto_tick(now + 200)
    assert "setpoint" in stub._climate_auto_alerts
    _feed(stub, now + 201, ChamberReading(actual_c=-40.0, setpoint_c=-40.0, running=True, alarm=0))
    stub._climate_auto_tick(now + 201)
    assert "setpoint" not in stub._climate_auto_alerts
    assert any("снова совпадает" in text for text in stub.kinds("ok"))


def test_lost_link_and_return(tmp_path: Path):
    stub, now = _started(tmp_path)
    stub._climate_last_ok_s = now - 1000
    stub._climate_auto_tick(now)
    stub._climate_auto_tick(now + 130)
    assert "link" in stub._climate_auto_alerts
    _feed(stub, now + 131)
    stub._climate_auto_tick(now + 131)
    assert "link" not in stub._climate_auto_alerts
    assert any("связь с камерой восстановлена" in text for text in stub.kinds("ok"))


def test_silent_device_is_reported(tmp_path: Path):
    stub, now = _started(tmp_path)
    stub._climate_run_stage = "settle"
    stub._chamber_live_recent["board_temp"] = []
    stub._chamber_live_seen["board_temp"] = 0.0
    reading = ChamberReading(actual_c=-40.0, setpoint_c=-40.0, running=True, alarm=0)
    for second in (0, 61):
        _feed(stub, now + second, reading, board=False)
        stub._climate_auto_tick(now + second)
    assert any("прибор не присылает температуру платы" in text for text in stub.kinds("bad"))


def test_chamber_not_moving_is_noticed(tmp_path: Path):
    stub, now = _started(tmp_path)
    stub._climate_run_stage = "reach"
    stuck = ChamberReading(actual_c=10.0, setpoint_c=-40.0, running=True, alarm=0)
    for second in range(0, 1300, 10):
        _feed(stub, now + second, stuck)
        stub._climate_auto_tick(now + second)
    assert any("камера не идёт к уставке" in text for text in stub.kinds("warn"))


def test_scheduled_summary(tmp_path: Path):
    stub, now = _started(tmp_path)
    stub._climate_settings["report_every_min"] = 1.0
    stub._climate_auto_tick(now + 10)
    stub._climate_auto_tick(now + 70)
    summaries = [text for text in stub.kinds("info") if text.startswith("сводка: узел 1 из 1")]
    assert len(summaries) == 1 and "прошло" in summaries[0]


# ------------------------------------------------------------------ продолжение после перезапуска

def test_run_resumes_after_restart(tmp_path: Path):
    stub, now = _started(tmp_path, "25, -40, 85")
    stub._climate_auto_on_node_done(25.0, now + 1800)
    stub._climate_run_done.append(25.0)
    stub._climate_run_index = 1
    stub._climate_run_enter("settle", now + 1800)
    saved = json.loads(stub._climate_auto_state_path().read_text(encoding="utf-8"))
    assert saved["index"] == 1 and saved["durations"][0][0] == 25.0

    # Программа перезапущена: новый контроллер на тех же файлах.
    again = _SupStub(tmp_path)
    assert again._climate_auto_resume is not None
    assert any("запущена заново во время прогона" in text for text in again.kinds("warn"))
    view = again._climate_auto_view()
    assert "узел 2 из 3" in view["resume"]["text"]

    later = time.monotonic()
    _feed(again, later)
    again._climate_auto_tick(later)
    assert not again._climate_run_stage, "сначала связь должна продержаться"
    _feed(again, later + 31)
    again._climate_auto_tick(later + 31)
    assert again._climate_run_stage in ("setpoint", "reach")
    assert again._climate_run_index == 1 and again._climate_run_done == [25.0]
    assert again._climate_auto_durations == [(25.0, 1800.0)]
    assert any("продолжен после перезапуска" in text for text in again.kinds("ok"))
    assert ("setpoint", -40.0) in again._climate_link.commands


def test_resume_waits_for_the_operator_when_disabled(tmp_path: Path):
    stub, now = _started(tmp_path, "25, -40")
    again = _SupStub(tmp_path)
    again._climate_settings["auto_resume"] = False
    _feed(again, now)
    again._climate_auto_tick(now)
    again._climate_auto_tick(now + 60)
    assert not again._climate_run_stage
    _feed(again, now + 61)
    assert again._climate_auto_resume_now(now + 61)
    assert again._climate_run_stage


def test_discarded_run_is_forgotten(tmp_path: Path):
    _started(tmp_path, "25, -40")
    again = _SupStub(tmp_path)
    again._climate_auto_discard_resume()
    assert again._climate_auto_resume is None
    assert not again._climate_auto_state_path().exists()
    assert _SupStub(tmp_path)._climate_auto_resume is None


def test_stop_clears_the_saved_run(tmp_path: Path):
    stub, _now = _started(tmp_path, "25, -40")
    stub._climate_run_stop()
    assert not stub._climate_auto_state_path().exists()
