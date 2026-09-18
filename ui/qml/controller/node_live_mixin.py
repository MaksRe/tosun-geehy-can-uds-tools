"""Текущие данные узла: что сейчас происходит с прибором.

ЗАЧЕМ
После калибровки в колбе нужно сразу видеть, какой уровень показывает прибор, и
понимать, что происходит с узлом: мерят ли оба контура, откуда температура,
какие отметки и поправки работают, не сбрасывалась ли память. Раньше отсчёты
были только в панели пробной калибровки, а остальное приходилось читать по
одному параметру в окне параметров.

КАК ОПРАШИВАЕТСЯ
Прибор держит один канал ISO-TP, поэтому параметры спрашиваются по одному раз в
200 мс и только когда шину не занимает другой раздел. У каждого параметра свой
желаемый период: период уровня и плоский конденсатор раз в секунду, температуры
раз в несколько секунд, отметки и счётчики раз в 15 с. Каждый такт спрашивается
тот, кто сильнее всех просрочил свой период; если все не успевают, все
замедляются одинаково.

Ответы на эти параметры подхватываются из любого обмена, кто бы их ни запросил.
Параметр, на который прибор дважды ответил отказом, больше не спрашивается: его
нет в этой прошивке. Уровень J1939 берётся из широковещательных кадров узла.
Опрос идёт, только пока раздел открыт.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer

from uds.data_identifiers import UdsData, UdsVar
from uds.services.read_data_by_id import ServiceReadDataById

from .bus_guard import background_request_recent, note_background_request, uds_exchange_busy
from .contract import AppControllerContract
from .eeprom_commit_mixin import (
    EEPROM_FLAG_SPI_ERROR,
    EEPROM_FLAG_VERIFY_ERROR,
    decode_eeprom_state,
    eeprom_boot_warning,
)

# Значение эмуляции «выключена»: 0x8000, прочитанное со знаком.
EMULATION_OFF_VALUE = -32768

VAR_ACTIVE_PROGRAM = UdsVar(0x001A, 1, "Тип активной программы: 0 основная, 1 загрузчик")

# Уровень топлива в широковещательном кадре J1939: PGN 65276, SPN 96, 0,4 % на единицу.
J1939_PGN_DASH_DISPLAY = 0xFEFC
J1939_FUEL_LEVEL_STEP = 0.4
J1939_NOT_AVAILABLE = 251

# (ключ, параметр, со знаком, желаемый период опроса, с)
NODE_LIVE_VARS = (
    ("main_raw", UdsData.curr_fuel_tank, False, 1.0),
    ("media", UdsData.fuel_media_flatcap_raw, False, 1.0),
    ("level", UdsData.raw_fuel_level, True, 1.0),
    ("main_comp", UdsData.fuel_compensated_period, False, 2.0),
    ("age", UdsData.measurement_age, False, 3.0),
    ("fuel_t", UdsData.raw_temperature, True, 4.0),
    ("board_t", UdsData.raw_board_temperature, True, 4.0),
    ("emul", UdsData.temperature_emulation_x10, True, 4.0),
    ("rf", UdsData.fuel_media_rf_x1000, False, 4.0),
    ("media_state", UdsData.fuel_media_state, False, 4.0),
    ("empty", UdsData.empty_fuel_tank, False, 15.0),
    ("full", UdsData.full_fuel_tank, False, 15.0),
    ("zero_trim", UdsData.fuel_zero_trim_count, True, 15.0),
    ("tank_model", UdsData.fuel_tank_model, False, 15.0),
    ("media_enable", UdsData.fuel_media_comp_enable, False, 15.0),
    ("rf_rejected", UdsData.fuel_media_rejected_cnt, False, 15.0),
    ("board_stage", UdsData.fuel_board_stage_period, False, 15.0),
    ("stage_mode", UdsData.fuel_board_stage_mode, False, 15.0),
    ("profile_status", UdsData.fuel_thermal_profile_status, False, 15.0),
    ("main_spread", UdsData.cap_main_spread_max, False, 15.0),
    ("main_overrun", UdsData.cap_main_overrun_cnt, False, 15.0),
    ("media_spread", UdsData.cap_media_spread_max, False, 15.0),
    ("media_overrun", UdsData.cap_media_overrun_cnt, False, 15.0),
    ("eeprom", UdsData.eeprom_state, False, 15.0),
    ("session", UdsData.type_session, False, 15.0),
    ("program", VAR_ACTIVE_PROGRAM, False, 15.0),
)

# Что пробная калибровка подмешивает в свои замеры: сырой и итоговый период и плоский конденсатор.
NODE_LIVE_INJECT_VARS = (
    ("main_raw", UdsData.curr_fuel_tank, False),
    ("main_comp", UdsData.fuel_compensated_period, False),
    ("media", UdsData.fuel_media_flatcap_raw, False),
)
NODE_LIVE_INJECT_S = 1.0

TONE_NORMAL = "normal"
TONE_OK = "ok"
TONE_WARN = "warn"
TONE_BAD = "bad"


def _decimal(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def media_state_text(state: int) -> tuple[str, str]:
    """Биты состояния поправки по виду топлива (0x0037) словами."""
    parts = []
    tone = TONE_OK
    if state & 0x08:
        parts.append("отказ контура")
        tone = TONE_BAD
    if state & 0x02:
        parts.append("контур молчит")
        tone = TONE_BAD
    if state & 0x04:
        parts.append("обновление заморожено")
        if tone == TONE_OK:
            tone = TONE_WARN
    if state & 0x01:
        parts.insert(0, "применяется")
    elif not parts:
        return "не применяется", TONE_NORMAL
    return ", ".join(parts), tone


def stage_mode_text(mode: int) -> tuple[str, str]:
    """Биты режима ступеней компенсации (0x004E) словами."""
    if mode & 0x04:
        return "сетка узлов неверна, таблицы не работают", TONE_BAD
    parts = []
    if mode & 0x01:
        parts.append("плата основного")
    if mode & 0x02:
        parts.append("плата вида топлива")
    if mode & 0x08:
        parts.append("трубка основного")
    if mode & 0x10:
        parts.append("трубка вида топлива")
    if not parts:
        return "не работают: профиль пуст или не применяется", TONE_NORMAL
    return ", ".join(parts), TONE_OK


def profile_status_text(status: int) -> tuple[str, str]:
    """Биты состояния температурного профиля (0x0060) словами."""
    if not status & 0x01:
        return "пустой", TONE_NORMAL
    if status & 0x08:
        return "таблицы применяются", TONE_OK
    problems = []
    if not status & 0x02:
        problems.append("сумма не сходится")
    if not status & 0x04:
        problems.append("алгоритм не тот")
    return "не применяется: " + (", ".join(problems) if problems else "причина неизвестна"), TONE_BAD


def eeprom_text(data) -> tuple[str, str]:
    """Состояние памяти прибора (0x0063) словами."""
    state = decode_eeprom_state(data)
    if state is None:
        return "—", TONE_NORMAL
    warning = eeprom_boot_warning(state)
    if warning:
        return warning, TONE_BAD
    if state["flags"] & (EEPROM_FLAG_SPI_ERROR | EEPROM_FLAG_VERIFY_ERROR):
        return f"сбой записи, ошибок с включения {state['errors']}", TONE_BAD
    if state["pending"]:
        return f"пишется, осталось параметров {state['pending']}", TONE_WARN
    if state["errors"]:
        return f"всё записано, ошибок с включения {state['errors']}", TONE_WARN
    return "всё записано", TONE_OK


class AppControllerNodeLiveMixin(AppControllerContract):
    NODE_LIVE_PERIOD_MS = 200
    # Ответ на запрос засчитывается отказом, если пришёл не позже этого, с.
    NODE_LIVE_REFUSAL_WINDOW_S = 1.0
    NODE_LIVE_REFUSAL_LIMIT = 2
    # Свежим число считается, пока не старше нескольких своих периодов, но не меньше этого, с.
    NODE_LIVE_STALE_MIN_S = 3.0
    NODE_LIVE_STALE_PERIODS = 3

    def _init_node_live_state(self):
        """Готовит показ текущих данных. Вызывается один раз при создании контроллера."""
        self._node_live_read = ServiceReadDataById()
        self._node_live_read.set_byte_order("big")

        self._node_live: dict = {key: None for key, _var, _signed, _period in NODE_LIVE_VARS}
        self._node_live_seen: dict = {key: 0.0 for key, _var, _signed, _period in NODE_LIVE_VARS}
        self._node_live_asked: dict = {key: 0.0 for key, _var, _signed, _period in NODE_LIVE_VARS}
        self._node_live_refusals: dict = {}
        self._node_live_missing: set = set()
        self._node_live_pending_key = None
        self._node_live_pending_s = 0.0
        self._node_live_j1939 = None
        self._node_live_j1939_seen = 0.0

        self._node_live_enabled = False
        # Чего просит раздел: сам опрос может идти и без него, ради журнала калибровки.
        self._node_live_wanted = False
        self._node_live_last_inject = 0.0
        self._node_live_last_poll = 0.0
        self._node_live_suspend_until = 0.0

        self._node_live_timer = QTimer(self)
        self._node_live_timer.setInterval(self.NODE_LIVE_PERIOD_MS)
        self._node_live_timer.timeout.connect(self._on_node_live_tick)
        self._node_live_timer.start()

    # ------------------------------------------------------------------ ответы

    @staticmethod
    def _node_live_decode(data, var, signed: bool):
        """Число из байтов ответа, младший байт первым. Состояние памяти остаётся списком байтов."""
        size = max(1, int(var.size))
        values = [int(item) & 0xFF for item in list(data)[:size]]
        if size > 2:
            return values
        raw = 0
        for shift, byte_value in enumerate(values):
            raw |= byte_value << (8 * shift)
        if not signed:
            return int(raw)
        limit = 1 << (size * 8)
        return int(raw - limit if raw >= (limit >> 1) else raw)

    def _handle_node_live_frame(self, identifier: int, payload):
        """Подхватывает данные узла из любого ответа прибора, кто бы их ни запросил."""
        if not self._node_live_enabled:
            return
        if not isinstance(payload, (list, tuple)) or len(payload) < 4:
            return
        if not self._is_calibration_response_identifier(identifier):
            return
        if ((int(payload[0]) >> 4) & 0x0F) != 0x00:
            return
        length = int(payload[0]) & 0x0F
        if length < 3 or length > (len(payload) - 1):
            return
        body = [int(value) & 0xFF for value in payload[1:1 + length]]
        now = time.monotonic()

        if body[0] == 0x7F:
            # Отказ на чтение сразу после своего запроса: скорее всего параметра нет в прошивке.
            pending = self._node_live_pending_key
            if body[1] == 0x22 and pending is not None and now - self._node_live_pending_s <= self.NODE_LIVE_REFUSAL_WINDOW_S:
                if len(body) > 2 and body[2] == 0x78:
                    return
                self._node_live_pending_key = None
                count = self._node_live_refusals.get(pending, 0) + 1
                self._node_live_refusals[pending] = count
                if count >= self.NODE_LIVE_REFUSAL_LIMIT:
                    self._node_live_missing.add(pending)
                    self.nodeLiveChanged.emit()
            return

        if body[0] != 0x62 or length < 4:
            return

        answered = {(body[1] << 8) | body[2], (body[2] << 8) | body[1]}
        for key, var, signed, _period in NODE_LIVE_VARS:
            if (int(var.pid) & 0xFFFF) not in answered:
                continue
            value = self._node_live_decode(body[3:], var, signed)
            self._node_live[key] = value
            self._node_live_seen[key] = now
            self._node_live_refusals.pop(key, None)
            if self._node_live_pending_key == key:
                self._node_live_pending_key = None
            # Те же отсчёты, что в разделе калибровки: свежесть у них общая.
            if key == "main_raw":
                self._live_note_value("level", value)
            elif key == "media":
                self._live_note_value("flatcap", value)
            # История для графиков и строка журнала, если он пишется.
            self._node_trend_note(key, value, now)
            self._calibration_log_note(key)
            self.nodeLiveChanged.emit()
            return

    def _handle_node_live_j1939_frame(self, parsed_id, payload):
        """Берёт уровень из широковещательного кадра выбранного узла."""
        try:
            pgn = int(parsed_id.pgn) & 0x3FFFF
            src = int(parsed_id.src) & 0xFF
        except Exception:
            return
        if pgn != J1939_PGN_DASH_DISPLAY or not isinstance(payload, (list, tuple)) or len(payload) < 2:
            return
        if src != (int(self._resolve_calibration_target_sa()) & 0xFF):
            return
        raw = int(payload[1]) & 0xFF
        self._node_live_j1939 = None if raw >= J1939_NOT_AVAILABLE else raw * J1939_FUEL_LEVEL_STEP
        self._node_live_j1939_seen = time.monotonic()
        self._calibration_log_note("j1939")

    # ------------------------------------------------------------------ опрос

    def _node_live_pick(self, now: float):
        """Параметр, сильнее всех просрочивший свой период, или None."""
        best = None
        best_ratio = -1.0
        for key, var, _signed, period in NODE_LIVE_VARS:
            if key in self._node_live_missing:
                continue
            if key == "age" and self._live_age["supported"] is False:
                continue
            ratio = (now - float(self._node_live_asked[key])) / float(period)
            if ratio > best_ratio:
                best = (key, var)
                best_ratio = ratio
        return best

    def _on_node_live_tick(self):
        """Спрашивает очередной параметр, пока шину не занимает никто другой."""
        if not self._node_live_enabled:
            return
        # Возраст данных меняется и без новых ответов, поэтому показ обновляется каждый такт.
        self.nodeLiveChanged.emit()

        if not self._can.is_connect or not self._can.is_trace:
            return
        if uds_exchange_busy(self) or background_request_recent(self):
            return
        # Пока калибровка открывает сессию и доступ, лишние запросы на шину не нужны.
        if bool(self._calibration_active) and not bool(self._calibration_session_ready):
            return
        now = time.monotonic()
        if now < self._node_live_suspend_until:
            return

        picked = self._node_live_pick(now)
        if picked is None:
            return
        key, var = picked
        if key == "age":
            self._live_age_note_request()
        self._node_live_asked[key] = now
        self._node_live_pending_key = key
        self._node_live_pending_s = now
        self._node_live_last_poll = now
        note_background_request(self)
        try:
            self._node_live_read.read_data_by_identifier(self._build_calibration_tx_identifier(), var)
        except Exception:
            pass

    def _node_live_set_enabled(self, enabled: bool):
        """Просьба раздела: опрашивать узел, пока раздел открыт."""
        self._node_live_wanted = bool(enabled)
        self._node_live_apply_enabled()

    def _node_live_apply_enabled(self):
        """Включает опрос, если его просит раздел или пишется журнал калибровки.

        Журнал важнее видимости раздела: оператор уходит к отметкам, а журнал
        обязан писать дальше, иначе в файле окажется дыра ровно на время работы.
        """
        value = bool(self._node_live_wanted) or self._calibration_log is not None
        if value == self._node_live_enabled:
            return
        self._node_live_enabled = value
        self.nodeLiveChanged.emit()

    # ------------------------------------------------------------------ показ

    def _node_live_fresh(self, key: str, now: float) -> bool:
        if self._node_live[key] is None:
            return False
        period = next(item[3] for item in NODE_LIVE_VARS if item[0] == key)
        limit = max(self.NODE_LIVE_STALE_MIN_S, self.NODE_LIVE_STALE_PERIODS * period)
        return (now - self._node_live_seen[key]) <= limit

    def _node_live_rows(self, now: float) -> dict:
        """Отладочные строки по ключам: значение словами, свежесть и тон."""
        live = self._node_live
        rows = {}

        def put(key, text, tone=TONE_NORMAL, fresh_key=None):
            source = fresh_key or key
            if source in self._node_live_missing:
                rows[key] = {"value": "нет в прошивке", "fresh": False, "tone": TONE_NORMAL}
                return
            rows[key] = {"value": text, "fresh": self._node_live_fresh(source, now), "tone": tone}

        def number(key, suffix=""):
            value = live[key]
            put(key, "—" if value is None else f"{int(value)}{suffix}")

        number("empty")
        number("full")
        number("zero_trim")

        model = live["tank_model"]
        put("tank_model", "—" if model is None else {0: "прежняя", 1: "по двум контурам"}.get(int(model), f"неизвестная ({int(model)})"))

        enable = live["media_enable"]
        put("media_enable", "—" if enable is None else ("включена" if int(enable) else "выключена"))

        rf = live["rf"]
        put("rf", "—" if rf is None else _decimal(int(rf) / 1000.0, 3))

        state = live["media_state"]
        if state is None:
            put("media_state", "—")
        else:
            text, tone = media_state_text(int(state))
            put("media_state", text, tone)

        rejected = live["rf_rejected"]
        put("rf_rejected", "—" if rejected is None else str(int(rejected)),
            TONE_WARN if rejected else TONE_NORMAL)

        number("board_stage")

        mode = live["stage_mode"]
        if mode is None:
            put("stage_mode", "—")
        else:
            text, tone = stage_mode_text(int(mode))
            put("stage_mode", text, tone)

        status = live["profile_status"]
        if status is None:
            put("profile_status", "—")
        else:
            text, tone = profile_status_text(int(status))
            put("profile_status", text, tone)

        emul = live["emul"]
        if emul is None:
            put("emul", "—")
        elif int(emul) == EMULATION_OFF_VALUE:
            put("emul", "выключена")
        else:
            put("emul", f"включена, {_decimal(int(emul) / 10.0, 1)} °C", TONE_WARN)

        number("main_spread", " отсч.")
        number("main_overrun")
        number("media_spread", " отсч.")
        number("media_overrun")

        main_ms = self._live_age["main_ms"]
        media_ms = self._live_age["media_ms"]
        if self._live_age["supported"] is False:
            rows["age"] = {"value": "нет в прошивке", "fresh": False, "tone": TONE_NORMAL}
        elif main_ms is None or media_ms is None:
            put("age", "—")
        else:
            def age_part(value):
                return "нет измерений" if int(value) >= 0xFFFF else f"{int(value)} мс"
            silent = int(main_ms) > 1000 or int(media_ms) > 1000
            received = self._live_age["received_s"]
            rows["age"] = {
                "value": f"основной {age_part(main_ms)}, вид топлива {age_part(media_ms)}",
                "fresh": received is not None and now - float(received) <= 10.0,
                "tone": TONE_BAD if silent else TONE_OK,
            }

        session = live["session"]
        put("session", "—" if session is None else {
            1: "обычная", 2: "программирование", 3: "расширенная"}.get(int(session), f"0x{int(session):02X}"))

        program = live["program"]
        if program is None:
            put("program", "—")
        elif int(program) == 0:
            put("program", "основная", TONE_OK)
        else:
            put("program", "загрузчик", TONE_BAD)

        data = live["eeprom"]
        if data is None:
            put("eeprom", "—")
        else:
            text, tone = eeprom_text(data)
            put("eeprom", text, tone)

        return rows

    def _node_live_view(self) -> dict:
        """Готовит всё для раздела: карточки, строки и состояние опроса."""
        now = time.monotonic()
        live = self._node_live

        def number(key):
            value = live[key]
            return "—" if value is None else str(int(value))

        def temperature(key):
            value = live[key]
            return "—" if value is None else f"{int(value) / 10:+.1f} °C"

        emul = live["emul"]
        emulation_on = emul is not None and int(emul) != EMULATION_OFF_VALUE
        if emul is None:
            temp_source = "эмуляция: нет данных"
        elif emulation_on:
            temp_source = "задана эмуляцией"
        else:
            temp_source = "с датчика"

        level = live["level"]
        level_text = "—" if level is None else _decimal(int(level) / 10.0, 1) + " %"
        level_out_of_range = level is not None and not (0 <= int(level) <= 1000)

        if self._node_live_j1939_seen and now - self._node_live_j1939_seen <= 5.0:
            j1939_text = ("J1939: нет данных у прибора" if self._node_live_j1939 is None
                          else "J1939: " + _decimal(float(self._node_live_j1939), 1) + " %")
        else:
            j1939_text = "J1939: кадров уровня нет"

        seen = [self._node_live_seen[key] for key in ("main_raw", "media", "level") if live[key] is not None]
        if not self._node_live_enabled:
            state_text = "опрос выключен"
        elif not seen:
            state_text = "ждём первых ответов прибора"
        else:
            state_text = "обновлено " + _decimal(now - max(seen), 1) + " с назад"

        return {
            "enabled": self._node_live_enabled,
            "stateText": state_text,
            "levelText": level_text,
            "levelFresh": self._node_live_fresh("level", now),
            "levelWarn": level_out_of_range,
            "levelJ1939Text": j1939_text,
            "mainRaw": number("main_raw"),
            "mainComp": number("main_comp"),
            "media": number("media"),
            "mainFresh": self._node_live_fresh("main_raw", now),
            "mediaFresh": self._node_live_fresh("media", now),
            "fuelTemp": temperature("fuel_t"),
            "boardTemp": temperature("board_t"),
            "fuelTempFresh": self._node_live_fresh("fuel_t", now),
            "boardTempFresh": self._node_live_fresh("board_t", now),
            "emulationOn": emulation_on,
            "tempSource": temp_source,
            # Приходят ли ответы и мерит ли контур сам: застывшее число без этого не понять.
            "mainFreshness": self._live_freshness_view("level", 1.5),
            "mediaFreshness": self._live_freshness_view("flatcap", 1.5),
            "rows": self._node_live_rows(now),
        }
