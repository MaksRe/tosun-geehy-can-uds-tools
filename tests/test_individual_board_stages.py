"""Проверки общего сценария камеры с разными этапами плат."""

import json
import time

import chamber_fit
from tests.test_multiboard import _MbStub
from tests.test_profile_audit import _audit_stub, _good_values, _serve
from tests.test_run_results import _p
from ui.qml import climate_scenario as cs
from ui.qml.controller.chamber_monitor_mixin import AppControllerChamberMonitorMixin


def _own_journal(stub, folder, sa, nodes):
    """Подготавливает журнал первого этапа конкретной платы с указанными узлами."""
    path = folder / f"chamber_previous_0x{sa:02X}.csv"
    with stub._mb_context(sa):
        stub._chamber_points = [_p("0/0", node / 10, node / 10, 5000, 4500) for node in nodes]
        stub._chamber_file_path = str(path)
        assert stub._chamber_write_csv(str(path)) is None
    return path


def _feed(stub, now, node, stages):
    """Имитирует разные температуры и уровни каждого физического образца."""
    for sa, stage in stages.items():
        with stub._mb_context(sa):
            tube = stage in ("assembly", "check")
            for shift in (4, 3, 2, 1, 0):
                for key, value in (("board_temp", 10 * (node + (5 if tube else 0))), ("fuel_temp", 10 * node),
                                   ("main", 14500 if tube else 5000), ("media", 12000 if tube else 4500),
                                   ("level", 4 if stage == "check" else 350), ("comp", 15000)):
                    stub._chamber_live_note(key, int(value), now - shift)


def test_common_steps_drive_six_boards_without_mixing_journals_and_writes(tmp_path):
    """Проверяет запуск, захват, результаты и очередь записи шести плат с четырьмя разными этапами."""
    stub = _audit_stub(tmp_path)
    stub.__class__ = type("MixedRun", (AppControllerChamberMonitorMixin, stub.__class__), {})
    assignments = {0x80: "board_cycle", 0x81: "board_cycle", 0x82: "board_cycle",
                   0x83: "refill", 0x84: "assembly", 0x85: "check"}
    for sa, stage in assignments.items():
        if stub._mb_board(sa) is None:
            assert stub._mb_add_board(f"0x{sa:02X}", str(sa))[0]
        assert stub._mb_set_stage(sa, stage)[0]
    previous = _own_journal(stub, tmp_path, 0x80, [250])
    verification_previous = _own_journal(stub, tmp_path, 0x85, [250])
    refill_path = _own_journal(stub, tmp_path, 0x83, [250, 0, 500, 700])
    assembly_path = _own_journal(stub, tmp_path, 0x84, chamber_fit.NODES_X10)
    stub._climate_scenario["steps"] = [cs.new_step(temp) for temp in (25, 50, 85)]
    stub._climate_scenario["auto_write"] = True
    now = time.monotonic()
    _feed(stub, now, 25, assignments)
    stub._climate_auto_checks()
    _serve(stub, {0x85: _good_values()})
    assert {sa for sa, _did, _origin in stub.sent} == {0x85}
    assert stub._climate_run_start(), stub._climate_run_status
    assert stub._climate_run_nodes == [25, 50, 85]
    assert stub._climate_run_setpoint() == 25
    assert not stub._mb_set_stage(0x85, "board_cycle")[0]
    assert all(stage["stage"] == assignments[sa] for sa, stage in stub._mb_run_stages.items())
    for index, node in enumerate(stub._climate_run_nodes):
        stamp = now + 60 * (index + 1)
        stub._climate_settings["sim_speed"] = 1
        stub._climate_run_steps[index]["settle_min"] = 0.5
        stub._climate_run_index = index
        stub._climate_run_enter("settle", stamp - 35)
        for delta in range(30, -1, -5):
            _feed(stub, stamp - delta, node, assignments)
        stub._climate_run_tick(stamp)
        assert stub._climate_run_stage == "points", stub._climate_run_status
        stub._climate_run_tick(stamp)
        assert stub._climate_run_stage == "capture"
        stub._climate_run_tick(stamp)
        assert stub._climate_run_stage == "points"
        stub._chamber_monitor_tick(stamp, force=True)
    for sa, stage in assignments.items():
        with stub._mb_context(sa):
            notes = [point["note"] for point in stub._chamber_points]
            if stage == "board_cycle":
                assert notes == ["0/0"] * 3 and stub._chamber_file_path != str(previous)
            elif stage == "refill":
                assert notes == ["0/0"] * 6
                assert stub._chamber_file_path == str(refill_path)
            elif stage == "assembly":
                assert notes == ["0/0"] * 7 + ["воздух"] * 3
                assert stub._chamber_file_path == str(assembly_path)
            else:
                assert notes == ["воздух"] * 3
                assert "_проверка" in stub._chamber_file_path and stub._chamber_file_path != str(verification_previous)
                assert not stub._chamber_tables_complete
            stub._chamber_tables_complete = True
    stub._chamber_monitor_session.gaps.update({str(0x80): 5, str(0x85): 1})
    view = stub._chamber_monitor_view()
    assert view["levelEnabled"] and [row["key"] for row in view["live"]] == [str(0x85)]
    assert view["gaps"] == 1
    result = stub._chamber_results_view()
    assert [row["sa"] for row in result["boards"] if row["levelTable"]] == ["0x85"]
    assert all(row["cells"].get("levelErr") is None for row in result["combined"]["rows"]
               if row["cells"]["sa"] != "0x85")
    saved = json.loads(stub._climate_auto_state_path().read_text(encoding="utf-8"))
    saved_boards = saved["chamber"]["boards"]
    assert len(saved_boards) == len(assignments)
    new = _MbStub(tmp_path)
    new._climate_auto_resume = saved
    new._climate_link = stub._climate_link
    new._climate_reading = stub._climate_reading
    new._climate_last_ok_s = time.monotonic()
    assert new._climate_auto_resume_now(), new._climate_run_status
    assert new._mb_run_stages == stub._mb_run_stages
    assert new._climate_run_connected == new._climate_run_labels[0]
    stored = json.loads(stub._mb_config_path().read_text(encoding="utf-8"))
    assert {board["sa"]: board["stage"] for board in stored["boards"]} == assignments
    stub._mb_start_profiles()
    assert stub._mb_profile_queue == [0x80, 0x81, 0x82, 0x83, 0x84]


def test_mixed_preflight_requires_only_matching_training_journal(tmp_path):
    """Проверяет, что журнал для сборки и добора требуется по адресу, а этапу новой платы не нужен."""
    stub = _audit_stub(tmp_path)
    for sa, stage in ((0x80, "board_cycle"), (0x81, "assembly"), (0x82, "refill")):
        assert stub._mb_set_stage(sa, stage)[0]
    checks = {row["key"]: row for row in stub._climate_auto_checks()}
    assert "stage_journal_128" not in checks
    assert not checks["stage_journal_129"]["ok"] and not checks["stage_journal_130"]["ok"]
    wrong = _own_journal(stub, tmp_path, 0x80, chamber_fit.NODES_X10)
    with stub._mb_context(0x81):
        assert stub._chamber_load_file(str(wrong))
    checks = {row["key"]: row for row in stub._climate_auto_checks()}
    assert "именно этой платы" in checks["stage_journal_129"]["text"]


def _settle_group(tmp_path, stages, minutes=0.5):
    """Готовит шаг при +50 °C с назначениями плат и обычной скоростью часов."""
    from tests.test_multiboard import _stub
    stub = _stub(tmp_path, temps=(50, 25))
    stub._climate_settings["sim_speed"] = 1
    stub._climate_run_nodes = [50, 25]
    stub._climate_run_steps = [cs.new_step(t) for t in stub._climate_run_nodes]
    stub._climate_run_steps[0]["settle_min"] = minutes
    stub._climate_run_labels = ["по этапам плат"]
    stub._climate_run_connected = stub._climate_run_labels[0]
    for sa, stage in stages.items():
        assert stub._mb_set_stage(sa, stage)[0]
    now = time.monotonic()
    plan = stub._mb_stage_plan(now, stub._climate_run_plan())
    stub._mb_run_begin(now, {sa: plan[sa] for sa in stages})
    stub._climate_run_enter("settle", now)
    return stub, now


def _temperatures(stub, stamp, values):
    """Передаёт ответы датчиков от указанных адресов в заданный момент."""
    for sa, (board, tube) in values.items():
        with stub._mb_context(sa, notify=False):
            stub._chamber_live_note("board_temp", board, stamp)
            if tube is not None:
                stub._chamber_live_note("fuel_temp", tube, stamp)


def test_assembly_settles_on_tubes_with_short_live_window(tmp_path):
    """Подтверждает готовность сборок с горячими платами по непрерывной истории трубок."""
    stub, start = _settle_group(tmp_path, {0x81: "assembly", 0x82: "assembly"}, 12)
    for delta in range(0, 651, 2):
        _temperatures(stub, start + delta, {0x81: (527, 500), 0x82: (531, 500)})
        if delta in (20, 22):
            stub._climate_run_tick(start + delta)
            assert "До решения" in stub._climate_run_status and "0x82" in stub._climate_run_status
            assert ("10:28" if delta == 20 else "10:26") in stub._climate_run_status
    stub._climate_run_tick(start + 650)
    assert stub._climate_run_stage == "points" and stub._climate_run_board_attempts == 0


def test_assembly_shift_requires_new_history(tmp_path):
    """Проверяет доводку по трубкам, новую историю после сдвига и запрет команд в режиме пульта."""
    stub, start = _settle_group(tmp_path, {0x81: "assembly"})
    for delta in range(31):
        _temperatures(stub, start + delta, {0x81: (535, 520)})
    stub._climate_run_follow = True
    stub._climate_run_settle_stages(start + 30, 50, "1", 30, .03)
    assert stub._climate_run_stage == "settle" and "пульта" in stub._climate_run_status
    stub._climate_run_follow = False
    stub._climate_run_tick(start + 30)
    assert stub._climate_run_stage == "setpoint" and stub._climate_run_setpoint() == 48
    stub._climate_run_enter("settle", start + 32)
    _temperatures(stub, start + 33, {0x81: (530, 500)})
    stub._climate_run_tick(start + 33)
    assert stub._climate_run_stage == "settle" and "набирается история" in stub._climate_run_status


def test_timeout_excludes_only_board_without_tube_response(tmp_path):
    """Отделяет пропуск по тайм-ауту от подтверждённой точки исправной платы."""
    stub, start = _settle_group(tmp_path, {0x81: "assembly", 0x82: "assembly"})
    stub._climate_scenario["settle_timeout_min"] = 1
    for delta in range(61):
        _temperatures(stub, start + delta, {0x81: (530, 500), 0x82: (530, None)})
    stub._climate_run_tick(start + 60)
    assert stub._climate_run_stage == "points" and stub._mb_stage_excluded == {0x82}
    assert any("0x82" in problem and "нет свежего ответа CAN" in problem for problem in stub._climate_auto_problems)
    for sa in (0x81, 0x82):
        with stub._mb_context(sa):
            for delta in range(58, 61):
                for key in ("main", "media"):
                    stub._chamber_live_note(key, 5000, start + delta)
    stub._climate_run_tick(start + 60)
    stub._climate_run_tick(start + 60)
    assert len(stub._mb_context_value(0x81, "_chamber_points")) == 1
    assert not stub._mb_context_value(0x82, "_chamber_points")


def test_mixed_steering_uses_selected_group_and_rejects_gaps(tmp_path):
    """Проверяет выбор группы, обрыв связи и набор свежего окна после восстановления."""
    stub, start = _settle_group(tmp_path, {0x81: "board_cycle", 0x82: "assembly"})
    stub._climate_scenario["mixed_steering"] = "fuel_temp"
    for delta in range(31):
        _temperatures(stub, start + delta, {0x81: (500, None), 0x82: (530, 520)})
    _temperatures(stub, start + 58, {0x81: (500, None), 0x82: (530, 520)})
    stub._climate_run_tick(start + 58)
    assert stub._climate_run_stage == "settle" and "набирается история" in stub._climate_run_status
    for delta in range(59, 90):
        _temperatures(stub, start + delta, {0x81: (500, None), 0x82: (530, 520)})
    stub._climate_run_tick(start + 89)
    assert stub._climate_run_setpoint() == 48 and stub._climate_run_stage == "setpoint"


def test_fixed_mixed_group_skips_out_of_range_and_checks_again_at_capture(tmp_path):
    """Проверяет раздельный допуск и повторную проверку при изменении температуры после выдержки."""
    stub, start = _settle_group(tmp_path, {0x81: "board_cycle", 0x82: "assembly"})
    assert cs.normalize(dict(stub._climate_scenario, mixed_steering="fuel_temp"))[0]["mixed_steering"] == "fuel_temp"
    for delta in range(31):
        _temperatures(stub, start + delta, {0x81: (500, None), 0x82: (530, 520)})
    stub._climate_run_tick(start + 30)
    assert stub._mb_stage_excluded == {0x82} and stub._climate_run_board_attempts == 0
    stub._climate_run_tick(start + 30)
    assert stub._climate_run_stage == "capture"
    _temperatures(stub, start + 31, {0x81: (524, None)})
    stub._climate_run_tick(start + 31)
    assert not stub._mb_captured and "0x81" in stub._climate_run_status
    stub._climate_run_tick(start + 31 + stub.MB_CAPTURE_WAIT_S)
    assert stub._climate_run_index == 1 and not stub._climate_run_done


def test_moving_tube_has_same_reason_in_run_and_remote_tiles(tmp_path):
    """Сверяет причину ожидания автоматики и плитки для движущейся трубки при устойчивой плате."""
    from ui.qml.controller.remote_monitor_mixin import AppControllerRemoteMonitorMixin
    stub, start = _settle_group(tmp_path, {0x81: "assembly"})
    for delta in range(31):
        _temperatures(stub, start + delta, {0x81: (530, 480 + delta)})
    stub._climate_run_tick(start + 30)
    stub._remote_stable_rule = lambda: (30, 0.03)
    AppControllerRemoteMonitorMixin._remote_check_boards_stability(stub, start + 30)
    _, ready, reason = stub._remote_boards_stability[0x81]
    assert not ready and reason in stub._climate_run_status and "трубка — скорость" in reason
    assert "0 из 1" in stub._remote_stable_text


def test_sparse_group_counts_require_three_fresh_readings_after_gap(tmp_path):
    """Проверяет запись при медленном опросе и новый набор отсчётов после обрыва."""
    stub, start = _settle_group(tmp_path, {0x80: "assembly", 0x81: "assembly", 0x82: "assembly"})
    stub._chamber_window_s = 2.0
    with stub._mb_context(0x81):
        for delta in (1, 5, 9):
            for key, value in (("main", 15955), ("media", 11027), ("board_temp", 530), ("fuel_temp", 500)):
                stub._chamber_live_note(key, value, start + delta)
        point, detail = stub._chamber_live_point(start + 9)
        assert point and point["samples"] == 3, detail
        assert stub._chamber_live_point(start + 25)[0] is None
        stub._chamber_live_note("main", 15956, start + 26)
        point, detail = stub._chamber_live_point(start + 26)
        assert point is None and "1 из 3" in detail


def test_warm_tube_after_hold_triggers_correction_before_capture(tmp_path):
    """Возвращает камеру к доводке по трубке, если за выдержку температура ушла выше допуска."""
    stub, start = _settle_group(tmp_path, {0x81: "assembly"})
    stub._climate_run_steps[0]["hold_min"] = 1
    for delta in range(31):
        _temperatures(stub, start + delta, {0x81: (530, 500)})
    stub._climate_run_tick(start + 30)
    assert stub._climate_run_stage == "hold"
    for delta in range(31, 91):
        _temperatures(stub, start + delta, {0x81: (546, 532)})
    stub._climate_run_tick(start + 90)
    assert stub._climate_run_stage == "setpoint" and stub._climate_run_setpoint() == 46.8
    assert not stub._mb_context_value(0x81, "_chamber_points")





def test_silent_tube_does_not_delay_trim_of_other_boards(tmp_path):
    """Проверяет доводку исправной сборки при потере датчика второй сборки."""
    stub, start = _settle_group(tmp_path, {0x81: "assembly", 0x82: "assembly"})
    for delta in range(65):
        _temperatures(stub, start + delta, {0x81: (535, 520), 0x82: (535, None)})
    stub._climate_run_tick(start + 64)
    assert stub._climate_run_stage == "setpoint"
    assert stub._climate_run_setpoint() == 48


def test_loss_of_all_required_tube_sensors_pauses_current_step(tmp_path):
    """Проверяет сохранение текущего шага при обрыве обоих датчиков трубок."""
    stub, start = _settle_group(tmp_path, {0x81: "assembly", 0x82: "assembly"})
    _temperatures(stub, start + 61, {0x81: (510, None), 0x82: (512, None)})
    stub._climate_run_tick(start + 61)
    assert stub._climate_run_paused and stub._climate_auto_paused_by == "sensors"
    assert stub._climate_run_index == 0 and not stub._mb_captured


def test_second_trim_uses_measured_response_of_same_tubes(tmp_path):
    """Проверяет расчёт второго сдвига по измеренному отклику трубок на первый."""
    stub, start = _settle_group(tmp_path, {0x81: "assembly"})
    for delta in range(31):
        _temperatures(stub, start + delta, {0x81: (560, 540)})
    stub._climate_run_tick(start + 30)
    assert stub._climate_run_setpoint() == 46
    stub._climate_run_enter("settle", start + 32)
    for delta in range(33, 65):
        _temperatures(stub, start + delta, {0x81: (540, 520)})
    stub._climate_run_tick(start + 64)
    assert stub._climate_run_setpoint() == 42


def test_large_spread_on_one_side_still_allows_partial_trim(tmp_path):
    """Проверяет, что общий перегрев двух разных изделий допускает доводку ближайшего."""
    stub, start = _settle_group(tmp_path, {0x81: "assembly", 0x82: "assembly"})
    for delta in range(31):
        _temperatures(stub, start + delta, {0x81: (535, 520), 0x82: (590, 570)})
    stub._climate_run_tick(start + 30)
    assert stub._climate_run_setpoint() == 48
