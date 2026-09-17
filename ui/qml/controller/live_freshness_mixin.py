"""Свежесть живых показаний: приходит ли ответ, меняется ли число, мерит ли контур.

ЗАЧЕМ
Живое число в окне может стоять на месте по трём разным причинам: прибор не
отвечает; прибор отвечает, и число действительно то же; прибор отвечает, но сам
измерительный контур перестал мерить и отдаёт последнее отфильтрованное
значение. На экране все три выглядят одинаково, и непонятно, завис ли контур.

КАК РАЗДЕЛЯЕТСЯ
- Время каждого ответа и каждого изменения числа программа запоминает сама.
- Возраст последнего измерения каждого контура прибор отдаёт в 0x0064. В
  прошивке он растёт раз в 100 мс и обнуляется только обработанной серией,
  поэтому не застывает вместе с контуром. Опрос спрашивает его вместо очередного
  чтения числа: раздел калибровки каждый четвёртый раз, живое показание вида
  топлива каждый восьмой, раздел текущих данных узла раз в три секунды.
- Прошивка без 0x0064 его не отдаёт. После трёх запросов без ответа программа
  перестаёт спрашивать и пишет, что прибор этого не сообщает.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer

from .contract import AppControllerContract

# Ответ свежий, пока не старше нескольких периодов опроса, но не меньше этого, с.
FRESH_PERIODS = 3
FRESH_MIN_S = 2.0

# Дольше этого ответа нет: опрос встал или прибор молчит, с.
LATE_PERIODS = 8
LATE_MIN_S = 5.0

# С какого времени стоит сказать, что число не меняется, с.
UNCHANGED_NOTE_S = 10.0

# Возраст измерения, выше которого контур считается молчащим, мс.
# Прошивка мерит каждый контур раз в 200 мс, запас на задержки основного цикла.
DEVICE_SILENT_MS = 1000

# Сведения о контуре без нового ответа сами устаревают, с.
DEVICE_INFO_STALE_S = 10.0

# Сколько запросов возраста без ответа означают, что прошивка его не знает.
DEVICE_AGE_MISSES_LIMIT = 3

# Прошивка отдаёт это число, если измерений не было или прошло больше 65 с.
AGE_UNKNOWN = 0xFFFF

COLOR_OK = "#16a34a"
COLOR_WARN = "#d97706"
COLOR_BAD = "#dc2626"
COLOR_IDLE = "#94a3b8"


def seconds_text(value: float) -> str:
    """Секунды для окна: с десятыми до 10 с, дальше целыми."""
    if value < 10.0:
        return f"{value:.1f}".replace(".", ",") + " с"
    return f"{int(value)} с"


class LiveTrack:
    """Одно живое число: когда пришёл последний ответ и когда число менялось."""

    def __init__(self):
        self.value = None
        self.received_s = None
        self.changed_s = None

    def update(self, value: int, now: float):
        if self.value is None or int(value) != int(self.value):
            self.changed_s = now
        self.value = int(value)
        self.received_s = now


def response_view(track: LiveTrack, now: float, poll_gap_s: float) -> tuple[str, str]:
    """Цвет и текст про ответы прибора на это число."""
    if track.received_s is None:
        return COLOR_IDLE, "ответов ещё не было"

    age = max(0.0, now - track.received_s)
    fresh_limit = max(FRESH_MIN_S, FRESH_PERIODS * poll_gap_s)
    late_limit = max(LATE_MIN_S, LATE_PERIODS * poll_gap_s)
    if age > late_limit:
        return COLOR_BAD, f"нет ответа {seconds_text(age)}"

    text = f"ответ {seconds_text(age)} назад"
    if age > fresh_limit:
        return COLOR_WARN, text

    unchanged = max(0.0, now - track.changed_s)
    if unchanged >= UNCHANGED_NOTE_S:
        text += f", число то же {seconds_text(unchanged)}"
    return COLOR_OK, text


def device_view(age_ms, received_s, supported, now: float) -> tuple[str, str]:
    """Цвет и текст про то, мерит ли контур сам."""
    if supported is False:
        return COLOR_IDLE, "прошивка не сообщает, мерит ли контур"
    if received_s is None or age_ms is None:
        return COLOR_IDLE, "проверяю, мерит ли контур..."

    since = max(0.0, now - received_s)
    if since > DEVICE_INFO_STALE_S:
        return COLOR_IDLE, f"о контуре нет сведений {seconds_text(since)}"
    if int(age_ms) >= AGE_UNKNOWN:
        return COLOR_BAD, "контур не мерит больше 65 с"
    if int(age_ms) > DEVICE_SILENT_MS:
        return COLOR_BAD, f"контур не мерит {seconds_text(int(age_ms) / 1000.0 + since)}"
    return COLOR_OK, "контур мерит"


class AppControllerLiveFreshnessMixin(AppControllerContract):
    # Каждый который запрос опроса заменяется запросом возраста измерений.
    LIVE_AGE_EVERY = {"level": 4, "flatcap": 8}
    LIVE_FRESHNESS_TICK_MS = 500

    def _init_live_freshness_state(self):
        """Готовит учёт свежести. Вызывается один раз при создании контроллера."""
        self._live_tracks = {"level": LiveTrack(), "flatcap": LiveTrack()}
        self._live_age = {"main_ms": None, "media_ms": None, "received_s": None, "supported": None, "misses": 0}
        self._live_age_counters = {"level": 0, "flatcap": 0}

        # Возраст ответа растёт и без новых данных, поэтому окна перечитывают его по таймеру.
        self._live_freshness_timer = QTimer(self)
        self._live_freshness_timer.setInterval(self.LIVE_FRESHNESS_TICK_MS)
        self._live_freshness_timer.timeout.connect(self._on_live_freshness_tick)
        self._live_freshness_timer.start()

    def _on_live_freshness_tick(self):
        if any(track.received_s is not None for track in self._live_tracks.values()):
            self.liveFreshnessChanged.emit()

    def _live_note_value(self, key: str, value: int):
        """Отмечает ответ с живым числом."""
        self._live_tracks[key].update(int(value), time.monotonic())

    def _live_age_due(self, key: str) -> bool:
        """Пора ли вместо очередного числа спросить возраст измерения."""
        if self._live_age["supported"] is False:
            return False
        self._live_age_counters[key] += 1
        if self._live_age_counters[key] < self.LIVE_AGE_EVERY[key]:
            return False
        self._live_age_counters[key] = 0
        return True

    def _live_age_note_request(self):
        """Отмечает запрос возраста. Без ответов подряд прошивка считается не знающей его."""
        self._live_age["misses"] += 1
        if self._live_age["supported"] is not True and self._live_age["misses"] >= DEVICE_AGE_MISSES_LIMIT:
            self._live_age["supported"] = False

    def _handle_live_age_frame(self, identifier: int, payload):
        """Забирает ответ с возрастом измерений, какой бы раздел его ни запросил."""
        if not isinstance(payload, (list, tuple)) or len(payload) < 8:
            return
        if not self._is_calibration_response_identifier(identifier):
            return
        # Ответ одним кадром: 62 00 64 и четыре байта возраста.
        if int(payload[0]) != 0x07:
            return
        if int(payload[1]) != 0x62 or int(payload[2]) != 0x00 or int(payload[3]) != 0x64:
            return

        self._live_age.update({
            "main_ms": int(payload[4]) | (int(payload[5]) << 8),
            "media_ms": int(payload[6]) | (int(payload[7]) << 8),
            "received_s": time.monotonic(),
            "supported": True,
            "misses": 0,
        })

    def _live_freshness_view(self, key: str, poll_gap_s: float) -> dict:
        """Две строки для окна: про ответы прибора и про сам контур."""
        now = time.monotonic()
        color, text = response_view(self._live_tracks[key], now, poll_gap_s)
        age_ms = self._live_age["main_ms"] if key == "level" else self._live_age["media_ms"]
        device_color, device_text = device_view(
            age_ms, self._live_age["received_s"], self._live_age["supported"], now)
        return {"color": color, "text": text, "deviceColor": device_color, "deviceText": device_text}
