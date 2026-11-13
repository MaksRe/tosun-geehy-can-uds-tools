"""Почему плата «ещё не устоялась»: причина вместо одной скорости +0,000 °C/мин."""

from ui.qml.controller.remote_monitor_mixin import AppControllerRemoteMonitorMixin
from ui.qml.controller.stability import quiet_on_average, rate_and_spread, unstable_reason

WINDOW = 300.0
RATE = 0.05
SPREAD = 0.3


def _series(now, span, value):
    """Показания раз в 10 с за span секунд: value(t) - температура в момент t от начала."""
    return [(now - span + step, value(step)) for step in range(0, int(span) + 1, 10)]


def test_reason_names_noise_window_or_rate():
    """Чтобы было видно, что держит плату: скорость, неполное окно или скачки показания."""
    now = 10_000.0
    noisy = _series(now, WINDOW, lambda t: 72.0 + (0.25 if (t // 10) % 2 else -0.25))
    result = rate_and_spread(noisy, now, WINDOW)
    assert abs(result[0]) < RATE
    assert unstable_reason(result, WINDOW, RATE, SPREAD) == "скачет на 0,5 °C"

    short = _series(now, 120, lambda t: 72.0)
    assert unstable_reason(rate_and_spread(short, now, WINDOW), WINDOW, RATE, SPREAD) == "стоит 2 из 5 мин"

    moving = _series(now, WINDOW, lambda t: 70.0 + t / 60.0 * 0.2)
    assert unstable_reason(rate_and_spread(moving, now, WINDOW), WINDOW, RATE, SPREAD) == "+0,200 °C/мин"
    assert unstable_reason(None, WINDOW, RATE, SPREAD) == "истории мало"


def test_quiet_on_average_needs_three_windows():
    """Шумная плата считается стоящей, только если за три окна никуда не ушла."""
    now = 10_000.0
    noise = lambda t: 72.0 + (0.25 if (t // 10) % 2 else -0.25)
    assert quiet_on_average(_series(now, 3 * WINDOW, noise), now, WINDOW, RATE)
    assert not quiet_on_average(_series(now, WINDOW, noise), now, WINDOW, RATE)
    drifting = lambda t: 70.0 + t / 60.0 * 0.1
    assert not quiet_on_average(_series(now, 3 * WINDOW, drifting), now, WINDOW, RATE)


class _Boards(AppControllerRemoteMonitorMixin):
    """Три платы: ровная, шумная давно, шумная недавно."""

    def __init__(self, now):
        self._climate_scenario = {"settle_min": WINDOW / 60.0, "settle_rate": RATE}
        noise = lambda t: 72.0 + (0.25 if (t // 10) % 2 else -0.25)
        series = {0x81: lambda t: 71.7, 0x82: noise, 0x86: noise}
        self._remote_boards_history = []
        for stamp in range(0, int(3 * WINDOW) + 1, 10):
            temps = {sa: fn(stamp) for sa, fn in series.items()}
            if stamp < 2 * WINDOW:
                temps.pop(0x86)
            self._remote_boards_history.append((now - 3 * WINDOW + stamp, temps))
        self._remote_history = [(now, 72.0, None, None)]
        self._remote_stable_text = ""
        self._remote_stable_ok = False

    def _mb_board_temps(self, now):
        return {sa: (72.0, 70.0) for sa in (0x81, 0x82, 0x86)}

    def _mb_working_boards(self, now):
        return [{"sa": sa} for sa in (0x81, 0x82, 0x86)]

    def _mb_label(self, sa):
        return f"0x{sa:02X}"


def test_boards_summary_explains_unstable_board():
    """Сводка «устоялись N из M» называет причину, а шумная, но стоящая плата идёт в зачёт, как в прогоне."""
    now = 10_000.0
    stub = _Boards(now)
    stub._remote_check_boards_stability(now)
    state = stub._remote_boards_stability
    assert state[0x81][1:] == (True, "устоялась")
    assert state[0x82][1] is True and state[0x82][2].startswith("в среднем стоит, скачет на 0,5 °C")
    assert state[0x86][1] is False and state[0x86][2] == "скачет на 0,5 °C"
    assert stub._remote_stable_text.endswith("ещё меняются: 0x86 скачет на 0,5 °C.")
    assert "+0,000" not in stub._remote_stable_text
