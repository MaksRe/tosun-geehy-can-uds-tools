"""Отогрев не быстрее N °C/мин, роса на плате и чужие подключения к камере.

Изделие в сборе (плата в корпусе с компаундом) отстаёт от воздуха камеры. При скачке
уставки с холода к теплу воздух теплеет быстрее платы, а влаги в нём прибавляет иней
испарителя: плата оказывается холоднее точки росы, и на ней оседает вода.

Тесты закрепляют:
- точка росы по формуле Магнуса;
- правило «отогревать камеру не быстрее»: уставка к теплу растёт ступенями с этой
  скоростью (на шагах и при возврате в конце), охлаждение - сразу; по умолчанию (0) -
  как раньше, одной уставкой; сторож не путает ступень с чужой уставкой и не зовёт
  медленный отогрев «камера почти не греет»; пауза не даёт скачка;
- плата холоднее точки росы: предупреждение сторожа, строка в окне, сайте и боте, а
  отогрев стоит, пока плата не прогреется (не дольше 30 мин);
- при отказе связи с Zundar программа смотрит, кто ещё с этого ноутбука держит камеру.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_climate_supervisor import _feed, _ready, _walk
from ui.qml import climate_scenario as cs
from ui.qml import net_setup, telegram_menus, telegram_reports
from ui.qml.climate_chamber import ChamberReading, dew_point_c
from ui.qml.controller.climate_control_mixin import SCENARIO_RULES


def _setpoints(stub):
    """Уставки, что программа задала камере: [(минута модели, значение)]."""
    log = []
    original = stub.sim.set_setpoint

    def record(value):
        log.append((stub.clock[0] / 60.0, float(value)))
        original(value)

    stub.sim.set_setpoint = record
    return log


def _texts(stub, word):
    return [text for _level, text in stub.events if word in text and not text.startswith("сводка")]


# ---------------------------------------------------------------- точка росы

def test_dew_point_by_magnus():
    assert abs(dew_point_c(25.0, 50.0) - 13.9) < 0.1
    assert abs(dew_point_c(20.0, 100.0) - 20.0) < 0.01
    assert abs(dew_point_c(30.0, 80.0) - 26.2) < 0.1
    assert dew_point_c(25.0, 0.0) is None and dew_point_c(25.0, 120.0) is None and dew_point_c(None, 50) is None


# ---------------------------------------------------------------- отогрев

def test_warming_goes_in_steps_no_faster_than_the_rule(tmp_path: Path):
    stub = _ready(tmp_path, "25, -20, 50")
    stub._climate_settings["warm_ramp_c_min"] = 1.0
    stub._climate_settings["finish_setpoint"] = 25.0
    log = _setpoints(stub)
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    values = [value for _minute, value in log]
    # Охлаждение к -20 - сразу одной уставкой.
    assert -20.0 in values
    cold = values.index(-20.0)
    assert values[cold - 1] > 20.0, values[:cold + 1]
    # Отогрев -20 -> +50: ступени не больше 0,5 °C, в среднем не быстрее 1 °C/мин.
    end = values.index(50.0)
    ramp = log[cold + 1:end + 1]
    assert len(ramp) > 100, ramp[:5]
    steps = [b[1] - a[1] for a, b in zip(ramp, ramp[1:])]
    assert all(0.0 < step <= 0.55 for step in steps), max(steps)
    minutes = ramp[-1][0] - ramp[0][0]
    assert (ramp[-1][1] - ramp[0][1]) / minutes <= 1.05, minutes
    # Возврат в конце +50 -> +25 - охлаждение: сразу.
    assert values[-1] == 25.0 and values[-2] == 50.0
    assert _texts(stub, "отогрев не быстрее 1 °C/мин") and _texts(stub, "отогрев закончен")
    # Ступень - это заданная уставка, а не чужая с пульта; медленный по правилу отогрев - не поломка.
    assert not _texts(stub, "не совпадает с заданной") and not _texts(stub, "почти не греет"), stub.events
    assert stub._climate_ramp is None


def test_return_at_the_end_from_cold_is_ramped(tmp_path: Path):
    stub = _ready(tmp_path, "25, -20")
    stub._climate_settings["warm_ramp_c_min"] = 2.0
    stub._climate_settings["finish_setpoint"] = 25.0
    log = _setpoints(stub)
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    values = [value for _minute, value in log]
    tail = values[values.index(-20.0) + 1:]
    assert len(tail) > 20 and tail[-1] == 25.0 and tail[0] < -15.0, tail[:3]
    assert any("Возвращаю камеру" in event for _level, event in stub.events) or stub._climate_run_status


def test_without_the_rule_warming_is_one_setpoint(tmp_path: Path):
    stub = _ready(tmp_path, "25, -20, 50")
    log = _setpoints(stub)
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    values = [value for _minute, value in log]
    assert values[values.index(-20.0) + 1] == 50.0, values
    assert not _texts(stub, "отогрев не быстрее")


def test_pause_does_not_jump_the_ramp(tmp_path: Path):
    stub = _ready(tmp_path, "25")
    stub._climate_settings["warm_ramp_c_min"] = 1.0
    now = time.monotonic()
    stub.sim.air_c = -30.0
    _feed(stub, now)
    first = stub._climate_ramp_begin(40.0, now)
    assert abs(first - (-29.0)) < 0.2 and stub._climate_ramp is not None
    # Час паузы: ступень стоит.
    stub._climate_ramp_hold(now + 3600.0)
    assert stub._climate_ramp_tick(now + 3630.0)
    assert stub._climate_run_commanded() <= first + 0.6


def test_ramp_is_not_needed_for_a_small_warming(tmp_path: Path):
    stub = _ready(tmp_path, "25")
    stub._climate_settings["warm_ramp_c_min"] = 1.0
    now = time.monotonic()
    _feed(stub, now)
    actual = stub._climate_reading.actual_c
    assert stub._climate_ramp_begin(actual + 2.0, now) == actual + 2.0 and stub._climate_ramp is None
    assert stub._climate_ramp_begin(actual - 30.0, now) == actual - 30.0 and stub._climate_ramp is None


# ---------------------------------------------------------------- роса на плате

def _humid(stub, now, air=25.0, humidity=60.0, board=10.0):
    stub._climate_reading = ChamberReading(actual_c=air, setpoint_c=air, running=True, alarm=0,
                                           details={"humidity_c": humidity})
    stub._climate_last_ok_s = now
    stub._chamber_live_note("board_temp", int(round(board * 10)), time.monotonic())


def test_board_colder_than_dew_point_is_named(tmp_path: Path):
    stub = _ready(tmp_path, "25, 50")
    assert stub._climate_run_start(), stub._climate_run_status
    now = time.monotonic()
    _humid(stub, now)  # +25 °C и 60 %: точка росы +16,7 °C, плата +10
    dew = stub._climate_dew(now)
    assert dew["danger"] and abs(dew["dew"] - 16.7) < 0.1 and abs(dew["margin"] + 6.7) < 0.1
    view = stub._climate_view()["dew"]
    assert view["visible"] and view["danger"] and "оседает влага" in view["text"] and "+16,7" in view["text"]
    stub._climate_auto_dew_watch(now)
    assert not _texts(stub, "роса на плате"), "минута ещё не прошла"
    _humid(stub, now + 61.0)
    stub._climate_auto_dew_watch(now + 61.0)
    alerts = _texts(stub, "роса на плате")
    assert len(alerts) == 1 and "не быстрее" in alerts[0], stub.events
    _humid(stub, now + 90.0, board=20.0)
    stub._climate_auto_dew_watch(now + 90.0)
    assert _texts(stub, "теплее точки росы")
    assert not stub._climate_dew(now + 90.0)["danger"] and "запас 3,3 °C" in stub._climate_dew(now + 90.0)["text"]


def test_dew_point_is_not_counted_without_humidity_or_below_zero(tmp_path: Path):
    stub = _ready(tmp_path, "25")
    now = time.monotonic()
    _feed(stub, now)  # имитатор без датчика влажности
    assert stub._climate_dew(now) is None and stub._climate_view()["dew"]["visible"] is False
    _humid(stub, now, air=-5.0, humidity=80.0, board=-20.0)
    assert stub._climate_dew(now) is None, "ниже нуля датчик влажности не точен"


def test_ramp_waits_while_the_board_is_below_the_dew_point(tmp_path: Path):
    stub = _ready(tmp_path, "25")
    stub._climate_settings["warm_ramp_c_min"] = 1.0
    now = time.monotonic()
    _humid(stub, now, air=5.0, humidity=90.0, board=0.0)  # точка росы +3,5: плата 0 - опасно
    stub._climate_ramp_begin(40.0, now)
    start = stub._climate_run_commanded()
    for minute in range(1, 31):
        _humid(stub, now + minute * 60.0, air=5.0, humidity=90.0, board=0.0)
        assert stub._climate_ramp_tick(now + minute * 60.0)
    assert stub._climate_run_commanded() == start and "стоит" in stub._climate_ramp_text()
    assert _texts(stub, "отогрев приостановлен")
    # 30 минут прошло: отогрев идёт дальше и так.
    for minute in range(31, 34):
        _humid(stub, now + minute * 60.0, air=5.0, humidity=90.0, board=0.0)
        stub._climate_ramp_tick(now + minute * 60.0)
    assert stub._climate_run_commanded() > start and _texts(stub, "отогрев продолжен")


def test_dew_point_reaches_the_bot_status():
    snapshot = {"climate": {"connected": True, "ok": True, "chamber": {"name": "Zundar"}, "actualText": "+25,0 °C",
                            "dew": {"visible": True, "danger": True, "text": "Плата +10,0 °C холоднее точки росы"}}}
    text = telegram_reports.status_report(snapshot)
    assert "Роса" in text and "⚠ Плата +10,0 °C" in text


# ---------------------------------------------------------------- правило в сценарии

def test_warm_ramp_rule_is_in_the_scenario():
    clean, problems = cs.normalize(cs.board_cycle_scenario())
    assert problems == [] and clean["warm_ramp_c_min"] == 0.0
    assembly, problems = cs.normalize(cs.assembly_scenario())
    assert problems == [] and assembly["warm_ramp_c_min"] == cs.ASSEMBLY_WARM_RAMP_C_MIN == 1.0
    clean, problems = cs.normalize({"name": "проба", "warm_ramp_c_min": "0,5", "steps": [{"temp": 25}]})
    assert clean["warm_ramp_c_min"] == 0.5
    assert any(key == "warm_ramp_c_min" for key, _title, _unit in cs.DIFF_GENERAL)
    assert "warm_ramp_c_min" in SCENARIO_RULES and "warm_ramp_c_min" in telegram_menus.RULE_SHORT


# ---------------------------------------------------------------- чужие подключения

def test_connections_parse_and_words():
    payload = ('[{"State":"Established","LocalPort":50001,"Pid":100,"Name":"python","Path":"C:\\\\Python313\\\\python.exe"},'
               '{"State":"Established","LocalPort":50002,"Pid":7,"Name":"ModbusPoll","Path":"C:\\\\mp.exe"},'
               '{"State":"TimeWait","LocalPort":50003,"Pid":0,"Name":"Idle","Path":""}]')
    rows = net_setup.parse_connections(payload, own_pid=100)
    assert [row["pid"] for row in rows] == [7, 0]
    text = net_setup.connections_text(rows, "192.168.0.100", 502)
    assert "уже подключено: ModbusPoll, PID 7" in text and "Idle" not in text
    other = net_setup.parse_connections(payload, own_pid=1)
    assert "вторая копия этой программы (python)" in net_setup.connections_text(other, "192.168.0.100", 502)
    assert "больше никто не подключён" in net_setup.connections_text([], "192.168.0.100", 502)
    assert "Не удалось" in net_setup.connections_text(None, "192.168.0.100", 502)
    assert net_setup.parse_connections("не json") == [] and net_setup.parse_connections('{"State":"Listen","Pid":5}')[0]["pid"] == 5
    assert net_setup.camera_connections("камера; Remove-Item", 502) is None, "адрес - только IPv4"


def test_refused_link_looks_for_other_connections(tmp_path: Path, monkeypatch):
    stub = _ready(tmp_path, "25")
    stub._climate_settings["driver"] = "zundar_az1000"
    stub._climate_settings["zundar_host"] = "192.168.0.100"
    calls = []

    def fake(host, port, own_pid=None):
        calls.append((host, port))
        return [{"state": "Established", "local_port": 1, "pid": 9, "name": "ModbusPoll", "path": ""}]

    monkeypatch.setattr(net_setup, "camera_connections", fake)
    now = time.monotonic()
    stub._climate_queue_state({"kind": "reading", "ok": False, "text": "отверг"})
    stub._climate_take_incoming(now)
    deadline = time.monotonic() + 5.0
    while not stub._climate_incoming and time.monotonic() < deadline:
        time.sleep(0.02)
    stub._climate_take_incoming(now + 1.0)
    assert calls == [("192.168.0.100", 502)]
    assert "ModbusPoll, PID 9" in stub._climate_view()["net"]["peers"]
    assert _texts(stub, "камера занята")
    # Повторный отказ сразу - без новой проверки; связь вернулась - строка убрана.
    stub._climate_queue_state({"kind": "reading", "ok": False, "text": "отверг"})
    stub._climate_take_incoming(now + 2.0)
    assert len(calls) == 1
    stub._climate_queue_state({"kind": "reading", "ok": True, "reading": ChamberReading(actual_c=25.0)})
    stub._climate_take_incoming(now + 3.0)
    assert stub._climate_peers_text == ""
