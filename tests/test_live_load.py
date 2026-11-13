"""Нагрузка на поток окна в долгом прогоне нескольких плат (13.11.2026).

Через сутки прогона трёх плат программа тормозила, а связь с платами «пропадала»: окно на каждом
такте опроса и каждом ответе платы заново собирало монитор (проход по всей истории каждой платы) и
ленту плат (десятки переключений полей контроллера). Закрепляем:
- «показания обновились» - не чаще двух раз в секунду;
- итоги истории монитора пересчитываются только при новой записи или новом показании при +25 °C;
- «плата на шине» узнаётся без переключения полей на плату.
"""

import time

from tests.test_multiboard import BOARDS, _stub
from ui.qml.controller.chamber_live_mixin import AppControllerChamberLiveMixin
from ui.qml.controller.chamber_monitor_mixin import AppControllerChamberMonitorMixin


class _Signal:
    def __init__(self):
        self.count = 0

    def emit(self):
        self.count += 1


class _Live(AppControllerChamberLiveMixin):
    def __init__(self):
        self.chamberLiveChanged = _Signal()


def test_live_notify_at_most_twice_a_second():
    """Такт опроса идёт раз в 0,1 с, а окно перечитывает показания не чаще раза в 0,5 с."""
    live = _Live()
    start = 1000.0
    for step in range(30):
        live._chamber_live_notify(start + step * 0.1)
    assert live.chamberLiveChanged.count == 6


class _Monitor(AppControllerChamberMonitorMixin):
    pass


def _sample(index, tube=700):
    return {"wall": 1000.0 + index, "clock": "13.11 00:00", "tube": tube, "board": tube, "level": index % 5,
            "comp": 15000, "main": 15000, "truth": None}


def test_monitor_summary_recomputed_only_on_new_sample(monkeypatch):
    """Итоги по узлам и худшие значения - из кэша, пока в истории нет новой записи."""
    monitor = _Monitor()
    history = [_sample(index) for index in range(500)]
    ref = dict(_sample(0, 250), auto=True)
    passes = []
    import chamber_fit
    real = chamber_fit.nearest_node
    monkeypatch.setattr(chamber_fit, "nearest_node", lambda value: passes.append(1) or real(value))

    first = monitor._chamber_monitor_summary("0x81", history, ref)
    count = len(passes)
    assert count == 500
    assert monitor._chamber_monitor_summary("0x81", list(history), ref) is first
    assert len(passes) == count
    # У другой платы - свои итоги.
    monitor._chamber_monitor_summary("0x82", history, ref)
    assert len(passes) == 2 * count
    # Новая запись или новое показание при +25 °C - пересчёт.
    history.append(_sample(500))
    stats, worst_shift, _worst_error = monitor._chamber_monitor_summary("0x81", history, ref)
    assert len(passes) == 3 * count + 1
    assert worst_shift[0] == 0.4
    monitor._chamber_monitor_summary("0x81", history, dict(ref, level=2, auto=False))
    assert len(passes) == 4 * count + 2


def test_on_bus_does_not_switch_board_fields(tmp_path):
    """Проверка «плата на шине» читает её поля из сохранённого контекста, без подмены полей окна."""
    stub = _stub(tmp_path)
    now = time.monotonic()
    restores = []
    real = stub._mb_restore
    stub._mb_restore = lambda sa: restores.append(sa) or real(sa)
    assert all(stub._mb_on_bus(sa, now) for sa, _name, _offset, _main in BOARDS)
    assert len(stub._mb_working_boards(now)) == len(BOARDS)
    assert restores == []
    assert not stub._mb_on_bus(0x99, now)
