"""Участники прогона и опрос плат, которые отвечают только на UDS-запросы."""

import time

from tests.test_multiboard import BOARDS, _MbStub, _stub


def _uds_only(tmp_path):
    """Для проверки первого опроса добавляет три платы без единого кадра рассылки J1939."""
    stub = _MbStub(tmp_path)
    for sa, name, *_ in BOARDS:
        assert stub._mb_add_board(f"0x{sa:02X}", name)[0]
    assert stub._mb_set_enabled(True)[0]
    stub._chamber_live_wanted = True
    stub._parse_calibration_response_identifier = lambda identifier: (0xDA00, 0xF1, identifier & 0xFF)
    stub._is_calibration_response_identifier = lambda identifier: (identifier & 0xFF) == stub._calibration_target_node_sa
    stub._build_calibration_tx_identifier = lambda: 0x18DA00F1 | (stub._calibration_target_node_sa << 8)
    return stub


def test_visible_boards_are_not_dropped_at_start_when_temperature_is_delayed(tmp_path):
    """Чтобы старт не убирал видимые плитки, сохраняет три недавно отвечавшие платы при задержке температуры."""
    stub = _stub(tmp_path)
    now = time.monotonic()
    for sa, *_ in BOARDS:
        with stub._mb_context(sa, notify=False):
            stub._chamber_live_seen["board_temp"] = now - 15
    assert len(stub._mb_working_boards(now)) == 3
    assert not stub._climate_auto_blockers(), stub._climate_auto_blockers()
    assert stub._climate_run_start(), stub._climate_run_status
    assert stub._mb_run_sas == [sa for sa, *_ in BOARDS]
    assert all(board["working"] for board in stub._mb_view()["boards"])


def test_uds_replies_keep_board_present_during_other_reads(tmp_path):
    """Чтобы чтение профиля не прятало плату, учитывает её ответы UDS при задержке температурных запросов."""
    stub = _stub(tmp_path)
    sa = BOARDS[0][0]
    with stub._mb_context(sa, notify=False):
        stub._chamber_live_seen["board_temp"] = time.monotonic() - 90
    stub._parse_calibration_response_identifier = lambda identifier: (0xDA00, 0xF1, identifier & 0xFF)
    stub._is_calibration_response_identifier = lambda identifier: (identifier & 0xFF) == stub._calibration_target_node_sa
    stub._mb_handle_live_frame(0x18DAF100 | sa, [4, 0x62, 0x00, 0x11, sa, 0, 0, 0])
    assert stub._mb_on_bus(sa)
    assert sa in [board["sa"] for board in stub._mb_working_boards()]


def test_first_uds_poll_requests_board_temperature_for_each_silent_node(tmp_path):
    """Чтобы молчащие платы быстро появились, сначала читает температуру каждой платы без рассылки CAN."""
    stub = _uds_only(tmp_path)
    requests = []

    class Reader:
        """Отвечает только на физические запросы чтения, без фоновых кадров J1939."""
        def read_data_by_identifier(self, identifier, var):
            """Для проверки маршрутизации возвращает температуру от адреса запроса."""
            sa, did = identifier >> 8 & 0xFF, int(var.pid)
            requests.append((sa, did))
            raw = 250
            stub._mb_handle_live_frame(0x18DAF100 | sa, [5, 0x62, did >> 8, did & 0xFF, raw & 255, raw >> 8, 0, 0])

    stub._chamber_live_read = Reader()
    for index in range(3):
        stub._mb_live_tick(time.monotonic() + index * 0.1)
    assert requests == [(sa, 0x003B) for sa, *_ in BOARDS]
    assert {board["sa"] for board in stub._mb_working_boards()} == {sa for sa, *_ in BOARDS}


def test_uds_present_without_temperature_waits_for_data_instead_of_claiming_no_bus(tmp_path):
    """Чтобы отсутствие температуры отличалось от отсутствия платы, показывает ожидание данных UDS."""
    stub = _uds_only(tmp_path)
    for sa, *_ in BOARDS:
        stub._mb_handle_live_frame(0x18DAF100 | sa, [4, 0x62, 0, 0x11, sa, 0, 0, 0])
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert not checks["device"]["ok"]
    assert "отвечают на UDS" in checks["device"]["text"]


def test_run_keeps_disconnected_participant_visible_and_polled(tmp_path):
    """Чтобы временная потеря связи не меняла состав прогона, сохраняет плитку и очередь опроса участника."""
    stub = _stub(tmp_path)
    assert stub._climate_run_start()
    sa = BOARDS[1][0]
    with stub._mb_context(sa, notify=False):
        stub._chamber_live_seen = {}
        stub._chamber_live_last = {}
    assert sa in stub._mb_run_sas
    assert sa in [board["sa"] for board in stub._mb_polled_boards()]
    row = next(board for board in stub._mb_view()["boards"] if board["sa"] == sa)
    assert row["working"] and not row["fresh"]
