"""Проверки мастера адресов плат.

Тесты закрепляют:
- платы подключаются по одной, все с одним заводским адресом: каждая получает
  свой адрес, он записан и проверен чтением по новому адресу, рассылка платы
  выключена и тишина на шине проверена, плата попала в «Платы в камере»;
- карточка платы заполняется прочитанными данными;
- две ненастроенные платы сразу - мастер просит подключать по одной и ждёт;
- молчание платы - 3 попытки по 1,5 с, затем остановка с причиной; «Повторить
  шаг» продолжает с того же шага;
- отказ платы (NRC) останавливает мастер с кодом; «подождите» (NRC 0x78)
  продлевает ожидание;
- плата, продолжающая рассылку после команды, не считается готовой;
- настроенная плата после перезапуска питания снова выключается сама;
- «Вернуть рассылку всем» - функциональный 0x28 0x00 и остановка мастера;
- пока мастер обменивается с платой, остальные разделы шину не трогают.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from j1939.j1939_can_identifier import J1939CanIdentifier
from tests.test_multiboard import _MbStub
from ui.qml.controller import board_addressing_mixin as bam
from ui.qml.controller.board_addressing_mixin import AppControllerBoardAddressingMixin
from ui.qml.controller.bus_guard import uds_exchange_busy

TESTER = 0xF1
BROADCAST_PGN = 0xFEF2


class _Board:
    """Прибор на шине: адрес, сеанс, доступ, рассылка и данные для карточки - как в прошивке."""

    def __init__(self, sa=0x80, seed=0x1234, board_temp_x10=231):
        self.sa = sa
        self.seed = seed
        self.session = 0x01
        self.unlocked = False
        self.comm_on = True
        self.eeprom_sa = sa
        self.silent_steps: set[int] = set()
        self.refuse: dict[int, int] = {}
        self.pending_first: set[int] = set()
        self.ignore_comm_control = False
        self.data = {0x003B: (board_temp_x10, 2), 0x0019: (-125, 2), 0x0014: (5123, 2), 0x0067: (4410, 2),
                     0x005E: (0x66E8, 2), 0x005D: (7, 2), 0x0060: (0x0F, 1), 0x001A: (0, 1)}

    def power_cycle(self):
        self.session = 0x01
        self.unlocked = False
        self.comm_on = True

    def handle(self, request: list[int]) -> list[int] | None:
        sid = request[0]
        if sid in self.silent_steps:
            return None
        if sid in self.refuse:
            return [0x7F, sid, self.refuse[sid]]
        if sid in self.pending_first:
            self.pending_first.discard(sid)
            return [0x7F, sid, 0x78]
        if sid == 0x22:
            did = (request[1] << 8) | request[2]
            if did == 0x0011:
                return [0x62, 0x00, 0x11, self.sa]
            if did not in self.data:
                return [0x7F, 0x22, 0x31]
            value, size = self.data[did]
            value &= (1 << (8 * size)) - 1
            return [0x62, request[1], request[2]] + [(value >> (8 * i)) & 0xFF for i in range(size)]
        if sid == 0x10:
            self.session = request[1]
            if request[1] == 0x01:
                self.unlocked = False
            return [0x50, request[1], 0x00, 0x32, 0x01, 0xF4]
        if sid == 0x27 and request[1] == 0x01:
            if self.session != 0x03:
                return [0x7F, 0x27, 0x7F]
            seed = 0 if self.unlocked else self.seed
            return [0x67, 0x01, seed & 0xFF, (seed >> 8) & 0xFF]
        if sid == 0x27 and request[1] == 0x02:
            key = ((self.seed ^ 0xAA55) | self.seed) & 0xFFFF
            if ((request[2] << 8) | request[3]) != key:
                return [0x7F, 0x27, 0x35]
            self.unlocked = True
            return [0x67, 0x02]
        if sid == 0x2E:
            if self.session != 0x03:
                return [0x7F, 0x2E, 0x7F]
            if not self.unlocked:
                return [0x7F, 0x2E, 0x33]
            self.sa = request[3]
            self.eeprom_sa = request[3]
            return [0x6E, 0x00, 0x11]
        if sid == 0x28:
            if self.ignore_comm_control:
                return [0x68, request[1] & 0x7F]
            self.comm_on = (request[1] & 0x7F) == 0x00
            return None if request[1] & 0x80 else [0x68, request[1] & 0x7F]
        return [0x7F, sid, 0x11]


class _AddrStub(AppControllerBoardAddressingMixin, _MbStub):
    """Мастер адресов и список плат камеры; шина и часы - свои, без адаптера и Qt-таймера."""

    def __init__(self, root: Path):
        _MbStub.__init__(self, root)
        self.now = 1000.0
        self.boards: list[_Board] = []
        self.sent: list[tuple[int, list[int]]] = []
        self.log: list[str] = []
        self._init_board_addressing_state()

    def _addr_start_timer(self):
        pass

    def _addr_clock(self) -> float:
        return self.now

    def _append_log(self, text, color=None):
        self.log.append(str(text))

    def _addr_bus_send(self, identifier: int, frame: list[int]) -> bool:
        self.sent.append((int(identifier), list(frame)))
        parsed = J1939CanIdentifier(int(identifier))
        dst = int(parsed.dst) & 0xFF
        request = list(frame[1:1 + (frame[0] & 0x0F)])
        functional = ((int(parsed.pgn) >> 8) & 0xFF) == 0xDB
        for board in list(self.boards):
            if not functional and board.sa != dst:
                continue
            old_sa = board.sa
            answers = [board.handle(request)]
            # «Подождите» (NRC 0x78), затем настоящий ответ - без нового запроса.
            if answers[0] is not None and answers[0][0] == 0x7F and answers[0][2] == 0x78:
                answers.append(board.handle(request))
            for answer in answers:
                if answer is None:
                    continue
                # Ответ на запись адреса прибор шлёт уже с нового адреса.
                src = board.sa if request[0] == 0x2E and answer[0] != 0x7F else old_sa
                payload = [len(answer)] + answer + [0xAA] * (7 - len(answer))
                self._handle_board_addressing_frame((0x18 << 24) | (0xDA << 16) | (TESTER << 8) | src, payload)
        return True

    def broadcast(self):
        """Обычная рассылка J1939 всех плат с включённой рассылкой."""
        for board in self.boards:
            if board.comm_on:
                self._handle_board_addressing_frame((0x18 << 24) | (BROADCAST_PGN << 8) | board.sa, [0] * 8)

    def run(self, seconds: float, step: float = 0.1):
        """Идёт время: платы шлют рассылку, мастер тикает."""
        for _ in range(int(round(seconds / step))):
            self.now += step
            self.broadcast()
            self._on_addr_tick()


def _stub(tmp_path: Path, monkeypatch) -> _AddrStub:
    # Защита фоновых запросов считает настоящие миллисекунды; в проверке время своё.
    monkeypatch.setattr(bam, "background_request_recent", lambda *_args, **_kw: False)
    return _AddrStub(tmp_path)


def _connect_and_wait(stub: _AddrStub, board: _Board, seconds: float = 8.0):
    stub.boards.append(board)
    stub.run(seconds)


def test_three_boards_one_by_one_get_own_addresses_and_go_quiet(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path, monkeypatch)
    ok, text = stub._addr_start("0x81")
    assert ok, text
    boards = [_Board(0x80, seed=0x1234 + i, board_temp_x10=230 + i) for i in range(3)]
    for index, board in enumerate(boards):
        _connect_and_wait(stub, board)
        assert stub._addr_stage == "wait", stub._addr_status
        assert board.sa == 0x81 + index and board.eeprom_sa == 0x81 + index
        assert board.session == 0x01, "плата оставлена в обычном сеансе"
        assert not board.comm_on, "рассылка платы выключена"
    assert [(b["sa"], b["name"]) for b in stub._mb_boards] == [(0x81, "П1"), (0x82, "П2"), (0x83, "П3")]
    view = stub._addr_view()
    assert all(step["state"] == "ok" for step in view["steps"])
    first = view["cards"][0]
    assert first["saText"] == "0x81" and first["oldSa"] == "0x80" and first["quiet"]
    assert first["boardTemp"] == "+23,0 °C" and first["fuelTemp"] == "-12,5 °C"
    assert first["main"] == "5123" and first["media"] == "4410"
    assert first["profileCrc"] == "0x66E8" and first["profileGeneration"] == "7"
    assert first["profileText"] == "применяется" and first["program"] == "основная"
    assert view["cards"][2]["boardTemp"] == "+23,2 °C"


def test_two_new_boards_at_once_ask_to_connect_one_by_one(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path, monkeypatch)
    assert stub._addr_start("")[0]
    first, second = _Board(0x80), _Board(0x90)
    stub.boards += [first, second]
    stub.run(2.0)
    assert stub._addr_stage == "wait"
    assert "по одной" in stub._addr_status
    assert first.sa == 0x80 and second.sa == 0x90
    stub.boards.remove(second)
    stub.run(8.0)
    assert first.sa == 0x81 and not first.comm_on


def test_silent_step_fails_after_three_attempts_and_retry_continues(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path, monkeypatch)
    assert stub._addr_start("")[0]
    board = _Board(0x80)
    board.silent_steps.add(0x27)
    _connect_and_wait(stub, board)
    assert stub._addr_stage == "failed"
    assert "не ответила за 3 попытки по 1,5 с" in stub._addr_status
    seeds = [frame for _ident, frame in stub.sent if frame[1:3] == [0x27, 0x01]]
    assert len(seeds) == 3
    board.silent_steps.clear()
    assert stub._addr_retry()
    stub.run(6.0)
    assert stub._addr_stage == "wait" and board.sa == 0x81 and not board.comm_on


def test_refusal_stops_with_code_and_pending_extends_wait(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path, monkeypatch)
    assert stub._addr_start("")[0]
    board = _Board(0x80)
    board.pending_first.add(0x2E)
    board.refuse[0x10] = 0x22
    _connect_and_wait(stub, board, 3.0)
    assert stub._addr_stage == "failed"
    assert "NRC 0x22" in stub._addr_status and "Расширенный сеанс" in stub._addr_status
    board.refuse.clear()
    assert stub._addr_retry()
    stub.run(6.0)
    # «Подождите» на записи не потратил попытку и не сорвал шаг.
    assert stub._addr_stage == "wait" and board.sa == 0x81
    assert len([frame for _ident, frame in stub.sent if frame[1] == 0x2E]) == 1


def test_board_that_keeps_broadcasting_is_not_ready(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path, monkeypatch)
    assert stub._addr_start("")[0]
    board = _Board(0x80)
    board.ignore_comm_control = True
    _connect_and_wait(stub, board, 12.0)
    assert stub._addr_stage == "failed"
    assert "продолжает рассылку" in stub._addr_status
    assert stub._mb_boards == []


def test_addressed_board_power_cycled_is_quieted_again(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path, monkeypatch)
    assert stub._addr_start("")[0]
    board = _Board(0x80)
    _connect_and_wait(stub, board)
    assert not board.comm_on
    board.power_cycle()
    stub.run(1.0)
    assert not board.comm_on, "мастер сам снова выключил рассылку"
    assert board.sa == 0x81 and stub._addr_stage == "wait"
    assert any("снова шлёт рассылку" in line for line in stub.log)


def test_factory_address_is_skipped_in_plan(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path, monkeypatch)
    assert stub._addr_start("0x80")[0]
    board = _Board(0x80)
    _connect_and_wait(stub, board)
    assert board.sa == 0x81


def test_release_all_sends_functional_enable_and_stops(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path, monkeypatch)
    assert stub._addr_start("")[0]
    boards = [_Board(0x80), _Board(0x80)]
    for board in boards:
        _connect_and_wait(stub, board)
    assert not any(board.comm_on for board in boards)
    assert stub._addr_release_all()
    assert all(board.comm_on for board in boards)
    assert not stub._addr_active
    ident, frame = stub.sent[-1]
    assert (ident >> 8) & 0xFFFF == 0xDBFF and frame[:4] == [0x03, 0x28, 0x80, 0x01]


def test_bus_guard_sees_wizard_exchange(tmp_path: Path, monkeypatch):
    stub = _stub(tmp_path, monkeypatch)
    assert stub._addr_start("")[0]
    board = _Board(0x80)
    board.silent_steps.add(0x10)
    stub.boards.append(board)
    stub.run(0.5)
    assert stub._addr_stage == "session"
    assert uds_exchange_busy(stub) == "board_addressing"
    assert uds_exchange_busy(stub, ignore=("board_addressing",)) == ""
    stub._addr_stop()
    assert uds_exchange_busy(stub) == ""
