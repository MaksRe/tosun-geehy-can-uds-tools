"""Проверки ожидания точки, времени прогона и общих результатов всех плат."""

import time

from tests.test_climate_run import _ClimateStub
from tests.test_climate_supervisor import _started
from tests.test_multiboard import BOARDS, _stub
from tests.test_remote_monitor import _RemoteStub
from tests.test_run_results import P6, _p
from ui.qml.chamber_results import board_results, combined_table, results_text


def test_stable_board_cannot_wait_for_forecast_after_timeout(tmp_path):
    """Чтобы прогон не зависал, проверяет выход из ожидания прогноза после предельного времени устаивания."""
    stub = _ClimateStub(tmp_path)
    now = time.monotonic()
    stub._climate_run_nodes = [85.0]
    stub._climate_run_steps = [{"temp": 85.0, "board_max_shift_c": 0.0}]
    stub._climate_run_labels = ["0/0"]
    stub._climate_settings.update(settle_min=1.0, settle_timeout_min=2.0, sim_speed=1.0)
    stub._climate_run_stage = "settle"
    stub._climate_run_since = now - 300
    stub._climate_board.extend((now - shift, 87.9) for shift in range(300, -1, -10))
    stub._climate_run_board_forecast = lambda stamp: 85.0
    stub._climate_run_board_early = lambda stamp, final: False
    stub._climate_run_tick(now)
    assert stub._climate_run_stage == "points", stub._climate_run_status
    assert any("Точка снимается при текущих условиях" in text for _, text in stub.events)


def test_live_forecast_still_waits_before_timeout(tmp_path):
    """Чтобы не снимать точку преждевременно, сохраняет ожидание прогноза до истечения тайм-аута."""
    stub = _ClimateStub(tmp_path)
    now = time.monotonic()
    stub._climate_run_nodes = [85.0]
    stub._climate_run_steps = [{"temp": 85.0}]
    stub._climate_settings.update(settle_min=1.0, settle_timeout_min=10.0, sim_speed=1.0)
    stub._climate_run_stage = "settle"
    stub._climate_run_since = now - 120
    stub._climate_board.extend((now - shift, 87.9) for shift in range(300, -1, -10))
    stub._climate_run_board_forecast = lambda stamp: 85.0
    stub._climate_run_board_early = lambda stamp, final: False
    stub._climate_run_tick(now)
    assert stub._climate_run_stage == "settle"
    assert "по прогнозу" in stub._climate_run_status


def test_point_event_uses_tube_temperature_and_logs_actual_values(tmp_path):
    """Чтобы не перепутать датчики второго этапа, проверяет узел по топливу и запись всех температур."""
    stub = _RemoteStub(tmp_path)
    point = _p("воздух", 88.4, 85.7, 15400, 11000, 84.9)
    stub._chamber_points = [point]
    stub._remote_board_prefix = lambda: "0x86 (П6): "
    diagnostic = []
    stub._climate_diag_event = lambda *args: diagnostic.append(args)
    stub._remote_note_point(point)
    text = stub._remote_events[0]["text"]
    assert "0x86 (П6)" in text and "узел +85 °C" in text
    assert "плата +88,4 °C" in text and "топливо +85,7 °C" in text and "камера +84,9 °C" in text
    assert diagnostic[0] == ("point", text, "INFO")
    # Для ручной точки при возврате камеры не обращаемся к уже пройденному шагу.
    stub._climate_run_stage = "finish"
    stub._remote_note_point(point)


def test_combined_results_keep_addresses_and_out_of_tolerance_points():
    """Для сводного анализа сохраняет адрес каждой платы и измерения, не попавшие в температурный узел."""
    boards = [board_results(P6, "П6", "0x86"), board_results(P6[:7], "П1", "0x81")]
    table = combined_table(boards)
    assert len(table["rows"]) == len(P6) + 7
    assert {row["cells"]["sa"] for row in table["rows"]} == {"0x86", "0x81"}
    hot = next(row["cells"] for row in table["rows"] if row["cells"]["tube"] == "+91,1")
    assert hot["status"] == "вне допуска ±3 °C" and hot["board"] == "+95,0"
    assert hot["mainChange"] == "+439" and hot["mainPct"] == "+2,84 %"
    assert "Все платы: измерения и результаты" in results_text({"boards": boards, "combined": table})


def test_results_include_boards_with_saved_data_without_live_connection(tmp_path):
    """Чтобы отключённые узлы не исчезали из итогов, проверяет сводку сохранённых контекстов всех адресов."""
    stub = _stub(tmp_path)
    for sa, _, _, _ in BOARDS:
        with stub._mb_context(sa, notify=False):
            stub._chamber_points = list(P6[:7])
    with stub._mb_context(BOARDS[1][0], notify=False):
        stub._chamber_live_reset()
    view = stub._chamber_results_view()
    assert len(view["boards"]) == len(BOARDS)
    assert len(view["combined"]["rows"]) == 7 * len(BOARDS)


def test_run_timing_has_total_and_finish_and_suppresses_finish_on_pause(tmp_path):
    """Для планирования работы проверяет общее время, срок завершения и отмену прогноза на паузе."""
    stub, start = _started(tmp_path, "25, -40")
    stub._climate_auto_on_node_done(25.0, start + 3600)
    stub._climate_run_index = 1
    view = stub._climate_auto_view()
    assert view["elapsedText"] and view["remainingText"] != "—" and view["totalText"] != "—"
    assert view["finishText"] and view["hasRun"]
    stub._climate_run_paused = True
    assert stub._climate_auto_view()["finishText"] == ""



def test_board_channels_keep_current_separate_from_average(tmp_path):
    """Чтобы не скрывать скачки, проверяет отдельную передачу последнего измерения и среднего каждой платы."""
    from ui.qml.controller.remote_monitor_mixin import AppControllerRemoteMonitorMixin

    stub = _stub(tmp_path)
    now = time.monotonic()
    for sa, _, _, main in BOARDS:
        with stub._mb_context(sa, notify=False):
            stub._chamber_live_note("main", main + 12, now)
            stub._chamber_live_note("media", 4508, now)
    stub._remote_multi = lambda: True
    stub._remote_boards_stability = {}
    stub._remote_history = []
    snapshot = AppControllerRemoteMonitorMixin._remote_boards_snapshot(stub, now)
    rows = {row["sa"]: row for row in snapshot["rows"]}
    assert set(rows) == {sa for sa, _, _, _ in BOARDS}
    for sa, _, _, main in BOARDS:
        assert rows[sa]["mainNow"] == str(main + 12)
        assert rows[sa]["main"] == str(main + 3)
        assert rows[sa]["mediaNow"] == "4508"
        assert rows[sa]["media"] == "4502"


def test_missing_current_measurement_is_not_replaced_with_average(tmp_path):
    """Чтобы не выдавать среднее за измерение, проверяет отсутствие текущего значения отдельно от накопленной истории."""
    stub = _stub(tmp_path)
    sa = BOARDS[1][0]
    with stub._mb_context(sa, notify=False):
        stub._chamber_live_last.pop("main", None)
    row = next(row for row in stub._mb_view()["boards"] if row["sa"] == sa)
    assert row["mainNow"] == "—"
    assert row["main"] == str(BOARDS[1][3])


def test_unknown_measurement_note_does_not_confirm_calibration():
    """Чтобы не засчитывать посторонние записи, проверяет неизвестную пометку и отсутствие опорного изменения."""
    result = board_results([_p("manual", 25, 25, 1000, 1000),
                            _p("manual", 50, 50, 1010, 1020)], "Плата", "0x82")
    assert result["stage1"] == result["stage2"] == "—"
    table = result["tables"][-1]
    for row in table["rows"]:
        assert row["tone"] == "warn"
        assert row["cells"]["status"] == "пометка не распознана"
        assert row["cells"]["mainChange"] == row["cells"]["mediaPct"] == "—"


def test_measurement_tolerance_does_not_claim_complete_calibration():
    """Чтобы отличать допуск температуры от готовности таблиц, проверяет рабочую точку, промах и пробу."""
    result = board_results([_p("0/0", 25, 25, 1000, 1000),
                            _p("0/0", 40, 40, 1010, 1020),
                            _p("0/0", 25, 25, 2000, 2000, rehearsal=True)])
    table = result["tables"][-1]
    assert [row["cells"]["status"] for row in table["rows"]] == [
        "в допуске ±3 °C", "вне допуска ±3 °C", "проба"]
    assert table["rows"][0]["cells"]["mainChange"] == "опора"
    assert table["rows"][1]["cells"]["mainChange"] == "+10"
    assert table["rows"][2]["cells"]["mainChange"] == "—"
    status = next(column for column in table["columns"] if column["key"] == "status")
    assert "не подтверждает готовность" in status["tip"]
