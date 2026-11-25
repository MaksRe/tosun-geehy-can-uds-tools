"""Поиск молчащих плат: диапазон, чтение данных, сохранение настроек и освобождение шины."""

from types import SimpleNamespace

import pytest

from tests.test_board_addressing import _Board, _stub
from ui.qml.controller import board_scan_mixin as scan_module
from ui.qml.controller.bus_guard import uds_exchange_busy


def _scanner(tmp_path, monkeypatch, addresses=(0x81, 0x82, 0x86)):
    """Для поиска без CAN-адаптера подключает молчащие платы и отключает ожидание настоящих часов."""
    monkeypatch.setattr(scan_module, "background_request_recent", lambda *_args, **_kwargs: False)
    stub = _stub(tmp_path, monkeypatch)
    for index, sa in enumerate(addresses):
        board = _Board(sa, board_temp_x10=231 + index * 10)
        board.comm_on = False
        board.data[0x0018] = (-4 + index * 5, 2)
        stub.boards.append(board)
    return stub


def _requests(stub):
    """Для проверки отсутствия записи извлекает SID и данные отправленных одиночных запросов."""
    return [frame[1:1 + frame[0]] for _identifier, frame in stub.sent]


def test_finds_three_silent_boards_and_reads_signed_values(tmp_path, monkeypatch):
    """Чтобы найти платы с выключенным Tx, читает три адреса, обе температуры и знаковый уровень."""
    stub = _scanner(tmp_path, monkeypatch)
    assert stub._mb_boards == []
    assert stub._addr_scan_start("80", "86")[0]
    stub.run(15)
    view = stub._addr_view()
    scan = view["scan"]
    assert not scan["active"] and scan["found"] == 3
    assert {b["sa"] for b in stub._mb_boards} == {0x81, 0x82, 0x86}
    rows = {row["cells"]["sa"]: row["cells"] for row in scan["table"]["rows"]}
    assert rows["0x81"]["board"] == "+23,1"
    assert rows["0x81"]["tube"] == "−12,5"
    assert rows["0x81"]["level"] == "−0,4"
    assert {row["state"] for row in rows.values()} == {"отвечает"}
    assert all(request[0] == 0x22 for request in _requests(stub))
    assert all(not board.comm_on and board.eeprom_sa == board.sa for board in stub.boards)
    with stub._mb_context(0x81, notify=False):
        assert stub._chamber_live_last["board_temp"] == 231
        assert stub._chamber_live_last["level"] == -4


@pytest.mark.parametrize("start,end", [("86", "81"), ("GG", "90"), ("00", "FF"), ("", "81"), ("-1", "01")])
def test_invalid_range_sends_nothing(tmp_path, monkeypatch, start, end):
    """Чтобы ошибка ввода не вызвала запросы не тем узлам, отклоняет неверный диапазон до отправки."""
    stub = _scanner(tmp_path, monkeypatch)
    assert not stub._addr_scan_start(start, end)[0]
    assert not stub.sent and not stub._addr_scan["active"]


def test_skips_tester_and_broadcast_addresses(tmp_path, monkeypatch):
    """Чтобы не опрашивать собственный адрес и широковещательные узлы, исключает их из диапазона."""
    stub = _scanner(tmp_path, monkeypatch, ())
    assert stub._addr_scan_start("F0", "FD")[0]
    assert 0xF1 not in stub._addr_scan["addresses"]
    stub.run(30)
    assert all(identifier >> 8 & 0xFF not in (0xF1, 0xFE, 0xFF) for identifier, _frame in stub.sent)
    assert not stub._addr_scan["active"]


def test_zero_address_is_valid_for_reading(tmp_path, monkeypatch):
    """Чтобы нулевой адрес не принимался за пустое значение, находит отвечающую плату 0x00."""
    stub = _scanner(tmp_path, monkeypatch, (0,))
    assert stub._addr_scan_start("00", "00")[0]
    stub.run(3)
    assert stub._addr_scan_view()["found"] == 1


def test_no_response_is_retried_and_finishes(tmp_path, monkeypatch):
    """Чтобы поиск не зависал на пустом адресе, ограничивает повторы и переходит к завершению."""
    stub = _scanner(tmp_path, monkeypatch, ())
    assert stub._addr_scan_start("81", "81")[0]
    stub.run(5)
    assert _requests(stub) == [[0x22, 0, 0x11]] * stub.ADDR_SCAN_ATTEMPTS
    assert not stub._addr_scan["active"] and stub._addr_scan_view()["found"] == 0


def test_tube_scan_is_one_pass_even_with_repeat_enabled(tmp_path, monkeypatch):
    """Чтобы поиск трубок освободил шину для замеров, завершает один проход и сохраняет настройку повтора."""
    stub = _scanner(tmp_path, monkeypatch, (0x81,))
    assert stub._addr_scan_start("81", "81", repeat=True, auto=True, one_pass=True)[0]
    stub.run(10)
    assert not stub._addr_scan["active"] and stub._addr_scan_view()["found"] == 1
    assert stub._addr_scan["repeat"] and stub._addr_scan["auto"]


def test_missing_level_is_not_replaced_by_zero(tmp_path, monkeypatch):
    """Чтобы неподдерживаемый DID не стал ложным нулём, показывает прочерк и сохраняет найденную плату."""
    stub = _scanner(tmp_path, monkeypatch, (0x81,))
    del stub.boards[0].data[0x0018]
    assert stub._addr_scan_start("81", "81")[0]
    stub.run(3)
    row = stub._addr_scan_view()["table"]["rows"][0]["cells"]
    assert row["level"] == "—" and "часть данных недоступна" in row["state"]
    assert stub._addr_scan_view()["found"] == 1


def test_wrong_source_or_did_cannot_discover_board(tmp_path, monkeypatch):
    """Чтобы чужой кадр не добавил плату, не принимает несовпадающие адрес и идентификатор параметра."""
    stub = _scanner(tmp_path, monkeypatch, ())
    assert stub._addr_scan_start("81", "81")[0]
    stub._on_addr_tick()
    assert not stub._addr_scan_answer(0x82, [0x62, 0, 0x11, 0x82], stub.now)
    assert not stub._addr_scan_answer(0x81, [0x62, 0, 0x3B, 0x81], stub.now)
    assert not stub._addr_scan_answer(0x81, [0x62, 0, 0x11], stub.now)
    assert stub._addr_scan_answer(0x81, [0x62, 0, 0x11, 0x82], stub.now)
    assert not stub._mb_boards


def test_stop_drains_pending_request_without_starting_next_address(tmp_path, monkeypatch):
    """Чтобы остановка не смешала UDS-ответы, дожидается текущего запроса без дальнейшего опроса."""
    stub = _scanner(tmp_path, monkeypatch, ())
    assert stub._addr_scan_start("81", "86")[0]
    stub._on_addr_tick()
    assert uds_exchange_busy(stub) == "board_addressing"
    stub._addr_scan_stop()
    assert stub._addr_scan["active"] and stub._addr_scan["stopping"]
    stub.run(2)
    assert not stub._addr_scan["active"]
    assert len(stub.sent) == 1 and not uds_exchange_busy(stub)


def test_range_and_auto_search_survive_restart(tmp_path, monkeypatch):
    """Чтобы после перезапуска найти молчащие платы, возвращает диапазон и запускает поиск при открытии."""
    stub = _scanner(tmp_path, monkeypatch, (0x86,))
    assert stub._addr_scan_configure("85", "86", False, True)[0]
    again = _scanner(tmp_path, monkeypatch, (0x86,))
    scan = again._addr_scan_view()
    assert (scan["startText"], scan["endText"], scan["auto"]) == ("0x85", "0x86", True)
    again._addr_set_visible(True)
    again.run(6)
    assert again._addr_scan_view()["found"] == 1
    assert not again._addr_scan["active"]


def test_repeat_finds_new_board_and_notices_disconnection(tmp_path, monkeypatch):
    """Для повторного поиска обновляет состав шины, сохраняя прежние имена и настройки плат."""
    stub = _scanner(tmp_path, monkeypatch, (0x81,))
    assert stub._addr_scan_start("81", "82", True)[0]
    stub.run(5)
    removed = stub.boards.pop()
    new = _Board(0x82)
    new.comm_on = False
    new.data[0x0018] = (7, 2)
    stub.boards.append(new)
    stub.run(9)
    rows = {row["cells"]["sa"]: row["cells"] for row in stub._addr_scan_view()["table"]["rows"]}
    assert rows["0x81"]["state"] == "нет ответа"
    assert rows["0x82"]["state"] == "отвечает"
    assert removed.sa == 0x81 and not removed.comm_on


def test_search_refuses_address_changes_and_other_busy_work(tmp_path, monkeypatch):
    """Чтобы поиск оставался чтением, не совмещает его с мастером, записью адресов и командами Tx."""
    stub = _scanner(tmp_path, monkeypatch, (0x81,))
    stub._programming_active = True
    assert not stub._addr_scan_start("81", "81")[0]
    assert not stub.sent
    stub._programming_active = False
    assert stub._addr_scan_start("81", "81")[0]
    stub._on_addr_tick()
    assert not stub._addr_start("85")[0]
    assert not stub._addr_set_comm(0x81, 0)[0]
    assert not stub._addr_comm_all(0)
    assert not stub._addr_reset_start()[0]
    assert all(request[0] == 0x22 for request in _requests(stub))


def test_can_disconnect_stops_search(tmp_path, monkeypatch):
    """Чтобы отключённый адаптер не создавал ложный поиск, проверяет отказ старта и остановку при потере CAN."""
    stub = _scanner(tmp_path, monkeypatch, ())
    stub._can = SimpleNamespace(is_connect=False, is_trace=False)
    assert not stub._addr_scan_start("81", "86")[0]
    stub._can.is_connect = stub._can.is_trace = True
    assert stub._addr_scan_start("81", "86")[0]
    stub._on_addr_tick()
    stub._can.is_connect = False
    stub._on_addr_tick()
    assert not stub._addr_scan["active"] and "потеряна" in stub._addr_scan["status"]


def test_response_pending_cannot_hold_search_forever(tmp_path, monkeypatch):
    """Чтобы бесконечное NRC 0x78 не заняло шину, ограничивает общее ожидание адреса."""
    stub = _scanner(tmp_path, monkeypatch, ())
    assert stub._addr_scan_start("81", "81")[0]
    stub._on_addr_tick()
    for _ in range(50):
        stub.now += 0.1
        stub._addr_scan_answer(0x81, [0x7F, 0x22, 0x78], stub.now)
        stub._on_addr_tick()
    assert not stub._addr_scan["active"]
    assert stub._addr_scan_view()["found"] == 0


def test_closing_section_stops_repeated_search(tmp_path, monkeypatch):
    """Чтобы скрытый раздел не занимал шину, останавливает повторный поиск после закрытия."""
    stub = _scanner(tmp_path, monkeypatch, ())
    stub._addr_set_visible(True)
    assert stub._addr_scan_start("81", "86", True)[0]
    stub._on_addr_tick()
    stub._addr_set_visible(False)
    stub.run(2)
    assert not stub._addr_scan["active"] and len(stub.sent) == 1


def test_finished_search_does_not_keep_disconnected_board_online(tmp_path, monkeypatch):
    """Чтобы прежний результат поиска не показывал отключённую плату, учитывает текущую проверку присутствия."""
    stub = _scanner(tmp_path, monkeypatch, (0x81,))
    stub._addr_set_visible(True)
    assert stub._addr_scan_start("81", "81")[0]
    stub.run(3)
    stub.boards.clear()
    stub.run(6)
    view = stub._addr_scan_view()
    assert view["found"] == 0
    assert view["table"]["rows"][0]["cells"]["state"] == "нет ответа"


def test_search_yields_to_other_operation_between_requests(tmp_path, monkeypatch):
    """Чтобы взаимное ожидание не остановило обмен, уступает шину другому разделу между запросами."""
    stub = _scanner(tmp_path, monkeypatch, ())
    assert stub._addr_scan_start("81", "81")[0]
    stub._programming_active = True
    stub._on_addr_tick()
    assert not stub.sent
    assert not uds_exchange_busy(stub, ignore=("programming",))
    assert "ждёт завершения" in stub._addr_scan["status"]
    stub._programming_active = False
    stub._on_addr_tick()
    assert len(stub.sent) == 1


def test_auto_search_waits_for_can_connection(tmp_path, monkeypatch):
    """Чтобы автопоиск работал после запуска программы, ждёт подключение адаптера и затем находит плату."""
    stub = _scanner(tmp_path, monkeypatch, (0x81,))
    assert stub._addr_scan_configure("81", "81", False, True)[0]
    stub._can = SimpleNamespace(is_connect=False, is_trace=False)
    stub._addr_set_visible(True)
    stub.run(2)
    assert not stub.sent
    stub._can.is_connect = stub._can.is_trace = True
    stub.run(4)
    assert stub._addr_scan_view()["found"] == 1


def test_chamber_start_waits_for_search_completion(tmp_path, monkeypatch):
    """Чтобы прогон не менял состав плат во время поиска, отмечает незавершённый поиск в проверке старта."""
    stub = _scanner(tmp_path, monkeypatch)
    assert stub._addr_scan_start("81", "86")[0]
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert checks["board_scan"]["ok"] is False
    stub._addr_scan_stop()
    assert all(item["key"] != "board_scan" for item in stub._climate_auto_checks())
