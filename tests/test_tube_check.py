"""Проверка монтажа по исходным отсчётам и журналу выбранной платы."""

import time
from types import SimpleNamespace

from tests.test_chamber_run import _ChamberStub
from tests.test_multiboard import _feed, _stub
from tests.test_run_results import _p
from ui.qml.controller.public_slots_mixin import AppControllerPublicSlotsMixin
from ui.qml.tube_check import bare_at_temperature, bare_board_curves


def test_bare_baseline_ignores_tubes_rehearsals_and_test_capacitors():
    """Для сравнения использует только рабочую ёмкость платы и учитывает её температуру."""
    points = [
        _p("0/0", 25, 24, 4637, 4498),
        _p("0/0", 25, 24, 4639, 4500),
        _p("0/0", 50, 46, 4640, 4511),
        _p("0/0", 30, 25, 20000, 12000, rehearsal=True),
        _p("150/47", 30, 25, 15000, 6000),
        _p("воздух", 30, 25, 16239, 10696),
    ]
    curves = bare_board_curves(points)
    assert curves["media"] == [(250, 4499), (500, 4511)]
    assert bare_at_temperature(curves["media"], 375) == (4505, (250, 500))
    assert bare_at_temperature(curves["media"], 257) is not None
    assert bare_at_temperature(curves["media"], 219) is None
    assert bare_at_temperature(curves["media"], 530) == (4511, (500,))


def test_tube_view_compares_same_board_without_replacing_run_journal(tmp_path):
    """Проверяет базу, прежний замер и свежие средние на примере монтажа трубок."""
    stub = _stub(tmp_path)
    stub._resolve_calibration_target_sa = lambda: stub._mb_active_sa
    _feed(stub, time.monotonic())
    stub._chamber_tube_sources = {}
    stub._can = SimpleNamespace(is_connect=True, is_trace=True)
    file = tmp_path / "chamber_test_0x80.csv"
    writer = _ChamberStub()
    writer._chamber_points = [
        _p("0/0", 25.3, 23.4, 4637, 4498),
        _p("0/0", 50.7, 48.5, 4640, 4511),
        _p("воздух", 27.6, 25.8, 16188, 10571),
    ]
    assert writer._chamber_write_csv(str(file)) is None
    current_file, current_points = stub._chamber_file_path, stub._chamber_points
    stub._chamber_journal_dirs = lambda: [tmp_path]
    assert not stub._chamber_tube_find()
    assert stub._chamber_file_path == current_file and stub._chamber_points is current_points

    stub._chamber_live_reset()
    now = time.monotonic()
    for delay in (0.2, 0.1, 0):
        for key, value in (("board_temp", 257), ("fuel_temp", 240), ("media", 10696), ("main", 16239)):
            stub._chamber_live_note(key, value, now - delay)
    view = stub._chamber_tube_view()
    media, main = view["rows"]
    assert (media["baseline"], media["current"], media["delta"], media["pf"]) == (4498, 10696, 6198, "151,5")
    assert "10571" in media["detail"] and "+125" in media["detail"]
    assert media["dryDelta"] == 125 and main["dryDelta"] == 51
    assert main["delta"] == 11602
    stub._chamber_live_seen["media"] = now - 60
    assert stub._chamber_tube_view()["rows"][0]["delta"] is None
    stub._chamber_test_mode = True
    assert not stub._chamber_tube_view()["rows"]
    stub._chamber_test_mode = False

    assert stub._mb_activate(0x81)
    assert not stub._chamber_tube_view()["baseline"]
    assert "0x80" in stub._chamber_tube_load(0x81, str(file))
    assert "недоступен" in stub._chamber_tube_load(0x83, str(file))
    assert not stub._chamber_tube_load(0x80, str(file))
    assert stub._mb_active_sa == 0x81
    assert stub._mb_activate(0x80)
    assert stub._chamber_tube_view()["baseline"] == str(file)


def test_live_average_restarts_when_single_node_changes(tmp_path):
    """Исключает остатки среднего другой платы из проверки сразу после смены CAN-адреса."""
    stub = _stub(tmp_path)
    target = [0x80]
    stub._resolve_calibration_target_sa = lambda: target[0]
    stub._chamber_live_reset()
    now = time.monotonic()
    stub._chamber_live_note("media", 10696, now)
    target[0] = 0x84
    stub._chamber_live_note("board_temp", 257, now + 0.1)
    assert stub._chamber_live_stats("media", now + 0.1) is None
    assert stub._chamber_live_source_sa == 0x84


def test_tube_table_keeps_measured_delta_between_replies(tmp_path):
    """Проверяет предварительное среднее, паузу, потерю связи и возобновление по новым данным."""
    stub = _stub(tmp_path)
    stub._resolve_calibration_target_sa = lambda: 0x80
    stub._can = SimpleNamespace(is_connect=True, is_trace=True)
    stub._chamber_tube_visible = True
    stub._chamber_tube_sources = {0x80: {"baseline": (tmp_path / "chamber_0x80.csv",
                                                       {"media": [(260, 4498)], "main": [(260, 4637)]})}}
    stub._chamber_live_reset()
    now = time.monotonic()
    for stamp in (now - 8, now):
        for key, raw in (("media", 10685), ("main", 16245), ("board_temp", 260)):
            stub._chamber_live_note(key, raw, stamp)
    for delay, note in ((0, "Предварительно"), (2.3, "Предварительно"),
                        (stub._chamber_live_stale_s() + .1, "Последний замер")):
        view = stub._chamber_tube_view(now + delay)
        assert [row["delta"] for row in view["rows"]] == [6187, 11608]
        assert note in view["displayNote"]
    assert not stub._chamber_tube_view(now + 60)["rows"]
    for offset in (61, 62, 63):
        for key, raw in (("media", 10690), ("main", 16240), ("board_temp", 260)):
            stub._chamber_live_note(key, raw, now + offset)
    view = stub._chamber_tube_view(now + 63)
    assert [row["delta"] for row in view["rows"]] == [6192, 11603]
    assert "displayNote" not in view


def test_group_uses_a_separate_baseline_for_each_board(tmp_path):
    """Чтобы сравнить все платы, сопоставляет их отсчёты со своими журналами и отмечает пропуски."""
    stub = _stub(tmp_path)
    stub._resolve_calibration_target_sa = lambda: stub._calibration_target_node_sa
    stub._can = SimpleNamespace(is_connect=True, is_trace=True)
    stub._chamber_journal_dirs = lambda: [tmp_path]
    stub._chamber_tube_sources = {}
    stub._mb_enabled = False
    stub._chamber_tube_visible = True
    _feed(stub, time.monotonic())
    writer = _ChamberStub()
    for sa, main, media, temp in [(0x80, 4500, 4000, 25), (0x81, 4800, 4400, 25.6)]:
        writer._chamber_points = [_p("0/0", temp, 25, main, media)]
        assert writer._chamber_write_csv(str(tmp_path / f"chamber_board_0x{sa:02X}.csv")) is None
    selected_file, selected_points = stub._chamber_file_path, stub._chamber_points
    find = AppControllerPublicSlotsMixin.findChamberTubeBaselines
    assert find(stub) == {"found": 2, "kept": 0, "missing": ["0x82"]}
    assert find(stub) == {"found": 0, "kept": 2, "missing": ["0x82"]}
    boards = {board["sa"]: board for board in stub._chamber_tube_group_view()["boards"]}
    assert {sa: [row["delta"] for row in board["rows"]] for sa, board in boards.items()} == {
        0x80: [500, 500], 0x81: [100, 300], 0x82: [None, None],
    }
    assert boards[0x82]["rows"][0]["current"] == 4500

    with stub._mb_context(0x81, notify=False):
        stub._chamber_live_seen["media"] = time.monotonic() - 30
    boards = {board["sa"]: board for board in stub._chamber_tube_group_view()["boards"]}
    assert boards[0x81]["rows"][0]["delta"] is None
    assert boards[0x80]["rows"][0]["delta"] == 500
    assert not stub._mb_on() and stub._mb_active_sa == 0x80
    assert stub._chamber_file_path == selected_file and stub._chamber_points is selected_points


def test_group_routes_reads_with_chamber_multiboard_mode_off(tmp_path):
    """Чтобы проверка трубок не меняла режим прогона, опрашивает адреса только при открытой вкладке."""
    stub = _stub(tmp_path)
    stub._resolve_calibration_target_sa = lambda: stub._calibration_target_node_sa
    stub._can = SimpleNamespace(is_connect=True, is_trace=True)
    stub._mb_enabled = False
    stub._chamber_tube_visible = True
    stub._chamber_live_wanted = True
    sent = []
    stub._chamber_live_read = SimpleNamespace(read_data_by_identifier=lambda tx_id, did: sent.append((tx_id, did.pid)))
    stub._build_calibration_tx_identifier = lambda: 0x18DA00F1 | (stub._calibration_target_node_sa << 8)
    stub._parse_calibration_response_identifier = lambda identifier: (0xDA00, 0xF1, identifier & 0xFF)
    stub._is_calibration_response_identifier = lambda identifier: (identifier & 0xFF) == stub._calibration_target_node_sa
    stub._chamber_live_pending = None
    for sa in (0x80, 0x81, 0x82):
        stub._mb_live_tick(time.monotonic())
        tx_id, did = sent[-1]
        assert (tx_id >> 8 & 0xFF, did) == (sa, 0x0014)
        stub._handle_chamber_live_frame(0x18DAF100 | sa, [5, 0x62, 0, 0x14, sa, 0x3F, 0, 0])
        assert stub._chamber_live_pending is None
        assert stub._mb_context_value(sa, "_chamber_live_last")["main"] == 0x3F00 | sa
    assert stub._calibration_target_node_sa == 0x80
    stub._climate_run_stage = "settle"
    assert not stub._mb_live_group()
    stub._climate_run_stage = ""
    stub._chamber_tube_visible = False
    assert not stub._mb_live_group()


def test_selected_board_keeps_live_averages_and_absent_board_is_hidden(tmp_path):
    """Проверяет одиночный старт, сохранение среднего и отказ от неподтверждённого адреса."""
    stub = _stub(tmp_path)
    stub._mb_active_sa = None
    stub._mb_enabled = False
    stub._calibration_target_node_sa = 0x84
    stub._resolve_calibration_target_sa = lambda: stub._calibration_target_node_sa
    stub._can = SimpleNamespace(is_connect=True, is_trace=True)
    stub._chamber_live_reset()
    now = time.monotonic()
    for offset in (2, 1):
        stub._chamber_live_note("main", 16000, now - offset)
    stub._chamber_tube_visible = True
    with stub._mb_live_context(0x84):
        stub._chamber_live_note("board_temp", 260, now)
        stub._chamber_live_note("main", 16003, now)
    with stub._mb_live_context(0x81):
        stub._chamber_live_note("board_temp", 251, now - 1)
    stub._mb_uds_seen[0x81] = now
    stub._addr_scan = {"missed_at": {0x81: now}}
    assert stub._chamber_tube_addresses(now) == [0x84]
    view = stub._chamber_live_view()
    assert view["main"]["avg"] == "16001" and view["boardTemp"]["ok"]
    stub._addr_scan.update(active=True, before_scan=(0x84, view))
    stub._chamber_live_recent["main"].clear()
    frozen = stub._chamber_live_view()
    assert frozen["main"]["avg"] == "16001" and frozen["main"]["info"] == "перед поиском"
    assert not frozen["freshOk"] and not frozen["ready"]
    stub._addr_scan["active"] = False
    for _ in range(3):
        stub._chamber_live_note("main", 16010, now)
    assert stub._chamber_live_view()["main"]["avg"] == "16010"
