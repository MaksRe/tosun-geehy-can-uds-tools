"""Проверки прогона нескольких плат в камере одновременно.

Тесты закрепляют:
- у каждой платы свой набор полей: средние, журнал (свой файл), таблицы, профиль;
- опрос идёт по кругу по всем платам, ответ попадает в средние той платы, от
  которой пришёл (по адресу на шине);
- прогон на имитаторе с тремя платами: доводка по средней температуре плат,
  точки шага у каждой платы, у каждой - свой журнал;
- «тишина» на шине: CommunicationControl всем платам на время прогона и обратно;
- профили пишутся по очереди, по одной плате.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_fit
from tests.test_climate_scenario import _ScnStub
from ui.qml import climate_scenario as cs
from ui.qml.controller.multiboard_mixin import AppControllerMultiBoardMixin

BOARDS = ((0x80, "П1", 0.0, 5000), (0x81, "П2", 0.6, 5100), (0x82, "П3", -0.6, 5200))


class _MbStub(AppControllerMultiBoardMixin, _ScnStub):
    """Камера, прогон, сценарий и несколько плат без Qt и шины."""

    def __init__(self, root: Path):
        _ScnStub.__init__(self, root)
        self._project_root_directory = root
        self._chamber_test_mode = False
        self._init_multiboard_state()


def _stub(tmp_path: Path, temps=(25.0, -40.0)) -> _MbStub:
    stub = _MbStub(tmp_path)
    for sa, name, _offset, _main in BOARDS:
        assert stub._mb_add_board(f"0x{sa:02X}", name)[0]
    assert stub._mb_set_enabled(True)[0]
    assert stub._climate_scenario_new("board_cycle")
    stub._climate_scenario["steps"] = [cs.new_step(temp) for temp in temps]
    stub._climate_scenario["auto_write"] = False
    stub._chamber_label = "0/0"
    _feed(stub, time.monotonic())
    return stub


def _feed(stub, now):
    """Камера и все платы: у каждой своя температура (сдвиг) и свои показания контуров."""
    reading = stub.sim.read()
    stub._climate_reading = reading
    stub._climate_last_ok_s = now
    product = reading.product_c if reading.product_c is not None else 25.0
    for sa, _name, offset, main in BOARDS:
        with stub._mb_context(sa):
            for shift in (2.0, 1.0, 0.0):
                stamp = now - shift
                stub._chamber_live_note("board_temp", int(round((product + offset) * 10)), stamp)
                stub._chamber_live_note("fuel_temp", int(round((product + offset) * 10)), stamp)
                stub._chamber_live_note("main", main, stamp)
                stub._chamber_live_note("media", 4500, stamp)


def _walk(stub, limit=40000, step_s=30.0):
    start = time.monotonic()
    for step in range(limit):
        now = start + step * step_s
        stub.clock[0] = step * step_s
        _feed(stub, now)
        stub._climate_note_board(now)
        if stub._climate_run_stage:
            stub._climate_run_tick(now)
        stub._climate_auto_tick(now)
        if not stub._climate_run_stage and not stub._climate_auto_finishing:
            return now
    raise AssertionError("прогон не закончился")


def test_each_board_keeps_its_own_journal_through_a_run(tmp_path: Path):
    stub = _stub(tmp_path)
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    files = set()
    for sa, name, offset, main in BOARDS:
        with stub._mb_context(sa):
            nodes = sorted(chamber_fit.nearest_node(point["board_temp_x10"]) for point in stub._chamber_points)
            assert nodes == [-400, 250], (name, stub._chamber_points)
            assert all(point["main"] == main for point in stub._chamber_points), name
            assert f"_0x{sa:02X}" in Path(stub._chamber_file_path).name and Path(stub._chamber_file_path).exists()
            files.add(stub._chamber_file_path)
    assert len(files) == 3
    view = stub._mb_view()
    assert [row["points"] for row in view["boards"]] == [2, 2, 2]
    assert [row["active"] for row in view["boards"]] == [True, False, False], "показана одна плата"


def test_doctoring_follows_the_mean_of_boards(tmp_path: Path):
    """Платы на +0,6 и -0,6 от средней: доводка ведёт среднюю к узлу - все три в допуске."""
    stub = _stub(tmp_path, temps=(25.0, -40.0))
    stub.sim.self_heating_c = 6.0
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    for sa, name, _offset, _main in BOARDS:
        with stub._mb_context(sa):
            boards = [point["board_temp_x10"] / 10 for point in stub._chamber_points]
            assert all(abs(value - target) <= 2.0 for value, target in zip(boards, (25.0, -40.0))), (name, boards)


def test_start_needs_every_board(tmp_path: Path):
    stub = _stub(tmp_path)
    with stub._mb_context(0x81):
        stub._chamber_live_reset()
    blockers = stub._climate_auto_blockers()
    assert any("«П2» (0x81)" in text for text in blockers), blockers


def test_polling_goes_round_all_boards_and_answers_go_to_their_board(tmp_path: Path):
    stub = _stub(tmp_path)
    sent = []

    class _Read:
        def read_data_by_identifier(self, identifier, var):
            sent.append((identifier & 0xFF00) >> 8)

    stub._chamber_live_read = _Read()
    stub._build_calibration_tx_identifier = lambda: 0x18DA00F1 | (stub._calibration_target_node_sa << 8)
    stub._chamber_live_pending = None
    for _ in range(6):
        stub._chamber_live_pending = None
        stub._mb_live_tick(time.monotonic())
    assert sent[:3] == [0x80, 0x81, 0x82] and sent[3:6] == [0x80, 0x81, 0x82]

    # Ответ платы 0x81 на чтение основного контура (DID 0x0014 = 4321): только в её средние.
    stub._chamber_live_wanted = True
    stub._parse_calibration_response_identifier = lambda identifier: (0xDA00, 0xF1, identifier & 0xFF)
    stub._is_calibration_response_identifier = lambda identifier: (identifier & 0xFF) == stub._calibration_target_node_sa
    with stub._mb_context(0x81):
        stub._chamber_live_reset()
    stub._mb_handle_live_frame(0x18DAF181, [0x05, 0x62, 0x00, 0x14, 0xE1, 0x10, 0, 0])
    with stub._mb_context(0x81):
        assert stub._chamber_live_last["main"] == 4321
    with stub._mb_context(0x80):
        assert stub._chamber_live_last["main"] == 5000


def test_bus_is_quiet_during_the_run_and_released_after(tmp_path: Path):
    stub = _stub(tmp_path)
    requests = []

    class _Service:
        def request(self, **kwargs):
            requests.append(kwargs)
            return True

    stub._communication_control_service = _Service()
    stub._communication_control_busy = False
    stub._mb_quiet_keep(time.monotonic())
    assert requests == [], "без прогона шину не трогаем"
    assert stub._climate_run_start(), stub._climate_run_status
    stub._mb_quiet_keep(time.monotonic() + 100)
    assert requests[-1]["control_type"] == 1 and requests[-1]["suppress_positive_response"]
    assert (requests[-1]["tx_identifier"] >> 8) & 0xFFFF == 0xDBFF, "функционально - всем платам сразу"
    stub._climate_run_stop("тест")
    assert requests[-1]["control_type"] == 0


def test_profiles_are_written_one_board_after_another(tmp_path: Path):
    stub = _stub(tmp_path)
    started = []

    def chain_start(automatic=False):
        started.append(stub._calibration_target_node_sa)
        stub._chamber_chain_stage = "write"
        stub._chamber_chain_status = f"профиль записан в 0x{stub._calibration_target_node_sa:02X}"

    stub._chamber_chain_start = chain_start
    stub._chamber_auto_write = True
    for sa, *_rest in BOARDS:
        with stub._mb_context(sa):
            stub._chamber_tables_complete = True
    stub._mb_start_profiles()
    now = time.monotonic()
    for _ in range(3):
        stub._mb_profile_tick(now)
        assert stub._mb_profiles_busy()
        stub._chamber_chain_stage = ""
    stub._mb_profile_tick(now)
    assert started == [0x80, 0x81, 0x82] and not stub._mb_profiles_busy()
    assert "записан в 0x82" in stub._mb_profile_results[0x82]
    assert "«П2»: точек 0, профиль записан в 0x81" in stub._mb_summary_text()


def test_board_list_is_kept_and_checked(tmp_path: Path):
    stub = _stub(tmp_path)
    assert not stub._mb_add_board("0x80", "ещё")[0], "адрес уже есть"
    assert not stub._mb_add_board("0xF1", "тестер")[0], "адрес самой программы"
    assert not stub._mb_add_board("abc", "x")[0]
    again = _MbStub(tmp_path)
    assert [board["sa"] for board in again._mb_boards] == [0x80, 0x81, 0x82] and again._mb_on()
    assert stub._mb_remove_board(0x82)[0] and stub._mb_remove_board(0x81)[0]
    assert not stub._mb_on(), "одна плата - обычный режим"
