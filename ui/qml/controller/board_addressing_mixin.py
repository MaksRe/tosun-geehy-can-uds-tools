"""Мастер адресов плат: каждой новой подключённой плате - свой адрес на шине; трафик J1939 каждой платы.

ЗАЧЕМ
Для прогона нескольких плат в камере у каждой платы должен быть свой адрес на
шине CAN (SA). С завода адрес у всех плат одинаковый, и вместе они мешают друг
другу. Раньше адрес меняли вручную в разделе «Протокол» за четыре шага (сессия,
доступ, запись, проверка) - для каждой платы.

КАК
Оператор подключает платы к одной шине по одной. Адрес новой плате мастер
выбирает сам (режим «Автоматически»: следующий свободный от первого заданного)
или спрашивает у оператора (режим «Вручную»: найдя плату, ждёт адрес и имя,
подсказывая следующий свободный). Дальше мастер сам:
 1. находит новую плату - ту, что передаёт кадры J1939 (у настроенных плат
    передача выключена, поэтому новая видна сразу; две новые сразу - просьба
    подключать по одной);
 2. читает её адрес (DID 0x0011) - подтверждение, что плата отвечает;
 3. открывает расширенный сеанс (0x10 0x03);
 4. открывает доступ (0x27: seed, ключ);
 5. записывает новый адрес (0x2E DID 0x0011) - прибор применяет его сразу и
    сохраняет в EEPROM;
 6. читает адрес уже по новому адресу - проверка, что запись действительно
    прошла;
 7. возвращает обычный сеанс (0x10 0x01): иначе через 30 с без запросов прибор
    сбросил бы сеанс и сам включил бы передачу обратно;
 8. выключает передачу J1939 (CommunicationControl 0x28 0x01 0x01: RX вкл,
    TX выкл, с подтверждением) - чтобы она не мешала найти следующую плату;
 9. 3 секунды слушает шину: от платы не должно быть ни одного кадра J1939;
10. читает данные платы для карточки (температуры, контуры, профиль);
11. добавляет плату в «Платы в камере» и ждёт следующую.
На каждом шаге - таймаут 1,5 с и до 3 попыток; ответ «подождите» (NRC 0x78)
продлевает ожидание; отказ (другой NRC) или молчание - шаг не пройден, мастер
останавливается и показывает причину; «Повторить шаг» продолжает с него же.

КАРТОЧКА ПЛАТЫ
- Имя меняется прямо в карточке, адрес - тоже (те же шаги 2-7 с проверкой
  чтением по новому адресу; режим трафика платы при этом не меняется).
- Трафик J1939 платы - любой из четырёх режимов CommunicationControl (0x28):
  RX+TX, только RX, только TX, RX и TX выключены. Команда ждёт подтверждения
  платы (0x68), затем программа проверяет по шине: при выключенной передаче от
  платы нет кадров 2,5 с, при включённой - кадры идут. UDS-диагностика в любом
  режиме работает (прошивка пропускает её мимо этих запретов).
- На шине видно, передаёт ли плата кадры J1939 сейчас и сколько в секунду.

Режим трафика держится до перезагрузки питания платы (в обычном сеансе прибор
его не сбрасывает). Пока мастер запущен, настроенную плату с выключенной
передачей, которая снова начала передавать (перезапуск питания), он выключает
сам. Адрес до мастера, время назначения и режим трафика каждой платы хранятся
в config/board_addressing.json.
"""

from __future__ import annotations

import json
import time

from PySide6.QtCore import QTimer

from j1939.j1939_can_identifier import J1939CanIdentifier
from uds.uds_identifiers import UdsIdentifiers

from .bus_guard import background_request_recent, note_background_request, uds_exchange_busy
from .contract import AppControllerContract

# Шаги одной платы: ключ - подпись для окна.
ADDR_STEPS = (
    ("found", "Плата найдена на шине"),
    ("choose", "Адрес выбран"),
    ("identify", "Плата отвечает, адрес прочитан"),
    ("session", "Расширенный сеанс"),
    ("seed", "Доступ: запрос"),
    ("key", "Доступ: ключ принят"),
    ("write", "Новый адрес записан"),
    ("verify", "Проверено чтением по новому адресу"),
    ("default", "Обычный сеанс"),
    ("quiet", "Передача J1939 выключена (0x28)"),
    ("check_quiet", "Тишина на шине проверена"),
)
ADDR_STEP_TITLES = dict(ADDR_STEPS)
# Шаги смены адреса уже настроенной платы: без поиска и без выключения передачи.
READDRESS_STEPS = ("identify", "session", "seed", "key", "write", "verify", "default")
# Шаги с запросом к плате и ожиданием ответа.
ADDR_REQUEST_STEPS = ("identify", "session", "seed", "key", "write", "verify", "default", "quiet")
# Режимы выбора адреса: мастер сам или оператор для каждой платы.
ADDR_MODES = ("auto", "manual")
# Режимы CommunicationControl (0x28) прошивки: номер, кнопка, состояние, пояснение.
COMM_MODES = (
    (0x00, "RX+TX", "RX вкл · TX вкл", "Приём и передача J1939 включены - обычная работа платы."),
    (0x01, "RX", "RX вкл · TX выкл",
     "Только приём: плата не передаёт свои кадры J1939, входящие обрабатывает. Режим для камеры."),
    (0x02, "TX", "RX выкл · TX вкл",
     "Только передача: плата передаёт кадры J1939, входящие (кроме UDS) не обрабатывает."),
    (0x03, "Выкл", "RX выкл · TX выкл", "Приём и передача J1939 выключены. UDS-диагностика работает."),
)
COMM_STATE_TEXT = {mode: state for mode, _button, state, _hint in COMM_MODES}
# Данные платы для карточки: DID, ключ, размер в байтах, со знаком, делитель (0,1 °C -> °C).
ADDR_INFO_DIDS = (
    (0x003B, "boardTemp", 2, True, 10.0),
    (0x0019, "fuelTemp", 2, True, 10.0),
    (0x0014, "main", 2, False, 1.0),
    (0x0067, "media", 2, False, 1.0),
    (0x005E, "profileCrc", 2, False, 1.0),
    (0x005D, "profileGeneration", 2, False, 1.0),
    (0x0060, "profileStatus", 1, False, 1.0),
    (0x001A, "program", 1, False, 1.0),
)
# Что о плате хранится в файле: история адреса и выбранный режим трафика.
ADDR_KEPT_INFO = ("oldSa", "addressedAt", "comm")


def _parse_hex_sa(text: str) -> int | None:
    """Цель функции в разборе адреса, введённого человеком, затем «85», «0x85» и «85h» означают 0x85."""
    raw = str(text or "").strip().lower().replace(" ", "")
    if raw.startswith("0x"):
        raw = raw[2:]
    elif raw.endswith("h"):
        raw = raw[:-1]
    if not raw or len(raw) > 2:
        return None
    try:
        return int(raw, 16)
    except ValueError:
        return None


class AppControllerBoardAddressingMixin(AppControllerContract):
    ADDR_STEP_TIMEOUT_S = 1.5
    ADDR_ATTEMPTS = 3
    # Сколько слушать шину после выключения передачи: ни одного кадра от платы.
    ADDR_QUIET_CHECK_S = 3.0
    # Кадр, пришедший в первые мгновения после команды, ещё мог быть в пути.
    ADDR_QUIET_GRACE_S = 0.3
    # Плата «на шине», если её кадр J1939 был не раньше стольких секунд назад.
    ADDR_SEEN_S = 2.0
    # Настроенная плата снова передаёт: повтор выключения не чаще, с.
    ADDR_REQUIET_EVERY_S = 2.0
    # Ответ на чтение данных для карточки ждём столько, с.
    ADDR_INFO_WAIT_S = 0.6
    # Проверка режима трафика по шине после подтверждения платы, с.
    ADDR_COMM_CHECK_S = 2.5
    # Окно подсчёта кадров J1939 платы в секунду, с.
    ADDR_RATE_WINDOW_S = 2.0
    ADDR_TICK_MS = 100

    # ------------------------------------------------------------------ состояние

    def _init_board_addressing_state(self):
        """Цель функции в подготовке мастера адресов, затем его таймер тикает и работает, только когда мастер запущен."""
        self._addr_active = False
        self._addr_stage = ""
        self._addr_failed_stage = ""
        self._addr_steps: dict[str, str] = {}
        self._addr_status = "Мастер не запущен."
        self._addr_status_color = "#64748b"
        self._addr_candidate_sa: int | None = None
        self._addr_new_sa: int | None = None
        self._addr_start_sa = 0x81
        self._addr_seen: dict[int, float] = {}
        self._addr_frames: dict[int, list[float]] = {}
        self._addr_done_sas: set[int] = set()
        self._addr_factory_sas: set[int] = set()
        self._addr_requiet_s: dict[int, float] = {}
        self._addr_attempt = 0
        self._addr_quiet_retries = 0
        self._addr_quiet_since = 0.0
        self._addr_sent_s = 0.0
        self._addr_seed = 0
        self._addr_board_number = 0
        self._addr_info: dict[int, dict] = {}
        self._addr_info_queue: list[tuple] = []
        self._addr_info_sa: int | None = None
        self._addr_info_current: tuple | None = None
        self._addr_info_sent_s = 0.0
        self._addr_mode = "auto"
        self._addr_pending_name = ""
        self._addr_skipped: set[int] = set()
        # Смена адреса настроенной платы из карточки: что было с мастером до неё.
        self._addr_job = "new"
        self._addr_return_active = False
        # Команды трафика платам из карточек: очередь и текущая.
        self._addr_comm_queue: list[tuple[int, int]] = []
        self._addr_comm: dict | None = None
        self._addr_load_settings()
        self._addr_start_timer()

    def _addr_settings_path(self):
        """Цель функции в файле настроек мастера рядом со списком плат камеры, затем выбор режима не теряется."""
        base = getattr(self, "_mb_config_path", None)
        return None if base is None else base().parent / "board_addressing.json"

    def _addr_load_settings(self):
        """Цель функции в режиме, первом адресе и истории плат с прошлого раза; испорченный файл не мешает запуску."""
        path = self._addr_settings_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) if path is not None else {}
        except (OSError, ValueError):
            return
        if payload.get("mode") in ADDR_MODES:
            self._addr_mode = payload["mode"]
        for key, item in (payload.get("boards") or {}).items():
            try:
                sa = int(key) & 0xFF
            except (TypeError, ValueError):
                continue
            if isinstance(item, dict):
                kept = {name: item[name] for name in ADDR_KEPT_INFO if item.get(name) is not None}
                self._addr_info.setdefault(sa, {}).update(kept)
        try:
            start = int(payload.get("start_sa", self._addr_start_sa))
        except (TypeError, ValueError):
            return
        if 0x01 <= start <= 0xEF and start not in self._addr_tester_sas():
            self._addr_start_sa = start

    def _addr_save_settings(self):
        """Цель функции в сохранении режима, первого адреса и истории плат, затем после перезапуска они те же."""
        path = self._addr_settings_path()
        if path is None:
            return
        boards = {}
        for sa, info in self._addr_info.items():
            kept = {name: info[name] for name in ADDR_KEPT_INFO if info.get(name) is not None}
            if kept:
                boards[str(int(sa))] = kept
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"mode": self._addr_mode, "start_sa": int(self._addr_start_sa),
                                        "boards": boards}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _addr_start_timer(self):
        """Цель функции в такте мастера раз в 100 мс, затем таймауты и проверки идут без участия оператора."""
        self._addr_timer = QTimer(self)
        self._addr_timer.setInterval(self.ADDR_TICK_MS)
        self._addr_timer.timeout.connect(self._on_addr_tick)
        self._addr_timer.start()

    @staticmethod
    def _addr_clock() -> float:
        """Цель функции в часах мастера, затем проверки подменяют их и не ждут настоящие секунды."""
        return time.monotonic()

    def _addr_tester_sas(self) -> set[int]:
        """Цель функции в адресах самой программы на шине, затем их не принимают за плату."""
        return {int(UdsIdentifiers.tx.src) & 0xFF, int(UdsIdentifiers.rx.dst) & 0xFF}

    def _addr_stepping(self) -> bool:
        """Цель функции в признаке шага с платой (адрес или выключение передачи), затем ничто не вклинивается."""
        return bool(self._addr_active) and self._addr_stage in ADDR_REQUEST_STEPS + ("check_quiet",)

    def _addr_exchange_busy(self) -> bool:
        """Цель функции в признаке обмена мастера с платой, затем другие опросы не вклиниваются в него."""
        stepping = bool(self._addr_active) and self._addr_stage in ADDR_REQUEST_STEPS
        comm_waiting = self._addr_comm is not None and self._addr_comm.get("stage") == "ack"
        return stepping or comm_waiting or self._addr_info_sa is not None

    def _addr_set_status(self, text: str, color: str = "#0f6ab4"):
        """Цель функции в строке состояния мастера, затем окно показывает, что он делает или ждёт."""
        self._addr_status = str(text)
        self._addr_status_color = str(color)
        self._addr_changed()

    def _addr_changed(self):
        """Цель функции в оповещении окна, затем шаги и карточки перерисовываются."""
        signal = getattr(self, "boardAddressingChanged", None)
        if signal is not None:
            signal.emit()

    def _addr_log(self, text: str, color: str = "#0f6ab4"):
        """Цель функции в записи события мастера в общий журнал, затем его видно и после."""
        log = getattr(self, "_append_log", None)
        if log is None:
            return
        try:
            log(f"Адреса плат: {text}", color)
        except Exception:
            pass

    def _addr_board_name(self, sa: int) -> str:
        """Цель функции в имени платы для сообщений, затем человек видит «П1», а не только адрес."""
        board_of = getattr(self, "_mb_board", None)
        board = board_of(sa) if board_of is not None else None
        return f"«{board['name']}» (0x{int(sa):02X})" if board else f"0x{int(sa):02X}"

    # ------------------------------------------------------------------ обмен

    def _addr_tx_identifier(self, sa: int) -> int:
        """Цель функции в идентификаторе физического запроса плате sa, затем ответит только она."""
        tx = J1939CanIdentifier(int(UdsIdentifiers.tx.identifier))
        tx.dst = int(sa) & 0xFF
        return int(tx.identifier)

    def _addr_functional_identifier(self) -> int:
        """Цель функции в функциональном CAN ID 0x18DBFFxx, затем команда уходит сразу всем платам."""
        tx_identifier = int(UdsIdentifiers.tx.identifier)
        return (((tx_identifier >> 26) & 0x07) << 26) | (0xDBFF << 8) | (tx_identifier & 0xFF)

    def _addr_bus_send(self, identifier: int, frame: list[int]) -> bool:
        """Цель функции в отправке кадра в шину через адаптер, затем ошибка адаптера не роняет мастер."""
        from app_can.CanDevice import CanDevice

        try:
            CanDevice.instance().send_async(int(identifier), 8, list(frame)[:8])
        except Exception:
            return False
        return True

    def _addr_send(self, sa: int, data: list[int]) -> bool:
        """Цель функции в отправке одиночного кадра UDS плате sa, затем кадр: длина, данные, добивка 0xFF."""
        frame = [len(data) & 0x0F] + [int(byte) & 0xFF for byte in data]
        frame += [0xFF] * (8 - len(frame))
        return self._addr_bus_send(self._addr_tx_identifier(sa), frame)

    def _addr_key(self) -> int:
        """Цель функции в ключе доступа по seed, затем расчёт тот же, что у прибора и в разделе «Протокол»."""
        seed = int(self._addr_seed) & 0xFFFF
        return ((seed ^ 0xAA55) | seed) & 0xFFFF

    def _addr_request(self, now: float):
        """Цель функции в запросе текущего шага (первый раз или повтор), затем отсчитывается его таймаут."""
        stage = self._addr_stage
        cand, new = self._addr_candidate_sa, self._addr_new_sa
        key = self._addr_key()
        requests = {
            "identify": (cand, [0x22, 0x00, 0x11]),
            "session": (cand, [0x10, 0x03]),
            "seed": (cand, [0x27, 0x01]),
            "key": (cand, [0x27, 0x02, (key >> 8) & 0xFF, key & 0xFF]),
            "write": (cand, [0x2E, 0x00, 0x11, int(new or 0) & 0xFF]),
            "verify": (new, [0x22, 0x00, 0x11]),
            "default": (new, [0x10, 0x01]),
            "quiet": (new, [0x28, 0x01, 0x01]),
        }
        if stage not in requests:
            return
        sa, data = requests[stage]
        self._addr_attempt += 1
        self._addr_sent_s = now
        self._addr_send(int(sa), data)

    def _addr_enter(self, stage: str, now: float | None = None):
        """Цель функции в переходе к шагу, затем его запрос уходит сразу."""
        now = self._addr_clock() if now is None else now
        self._addr_stage = stage
        self._addr_attempt = 0
        if stage in ADDR_STEP_TITLES:
            self._addr_steps[stage] = "run"
        if stage == "check_quiet":
            self._addr_quiet_since = now
        self._addr_changed()
        self._addr_request(now)

    def _addr_step_ok(self, stage: str, next_stage: str, now: float, text: str = ""):
        """Цель функции в отметке пройденного шага, затем мастер переходит к следующему."""
        self._addr_steps[stage] = "ok"
        if text:
            self._addr_set_status(text, "#0f6ab4")
        self._addr_enter(next_stage, now)

    def _addr_fail(self, text: str):
        """Цель функции в остановке на непройденном шаге, затем оператор видит причину и может повторить шаг."""
        if self._addr_stage in ADDR_STEP_TITLES:
            self._addr_steps[self._addr_stage] = "fail"
        self._addr_failed_stage = self._addr_stage
        self._addr_stage = "failed"
        self._addr_set_status(text, "#dc2626")
        self._addr_log(text, "#dc2626")

    def _addr_nrc_text(self, code: int) -> str:
        """Цель функции в коде отказа прибора словами, затем причина понятна без справочника."""
        nrc = f"NRC 0x{int(code):02X}"
        describe = getattr(self, "_uds_nrc_description", None)
        if describe is not None:
            try:
                nrc += f" ({describe(int(code))})"
            except Exception:
                pass
        return nrc

    # ------------------------------------------------------------------ кадры с шины

    def _addr_note_traffic(self, src: int, now: float):
        """Цель функции в учёте кадров J1939 платы, затем видно, передаёт ли она и сколько кадров в секунду."""
        self._addr_seen[src] = now
        stamps = self._addr_frames.setdefault(src, [])
        stamps.append(now)
        if len(stamps) > 64:
            limit = now - self.ADDR_RATE_WINDOW_S
            self._addr_frames[src] = [stamp for stamp in stamps if stamp >= limit]

    def _handle_board_addressing_frame(self, identifier: int, payload):
        """Цель функции в разборе кадра с шины, затем кадр J1939 отмечает трафик платы, а ответ UDS двигает шаг."""
        try:
            parsed = J1939CanIdentifier(int(identifier))
        except Exception:
            return
        src = int(parsed.src) & 0xFF
        pgn = int(parsed.pgn) & 0x3FFFF
        now = self._addr_clock()
        if (pgn >> 8) & 0xFF not in (0xDA, 0xDB):
            # Обычный кадр J1939: плата src передаёт.
            if src not in self._addr_tester_sas():
                self._addr_note_traffic(src, now)
            return
        if pgn != (int(UdsIdentifiers.rx.pgn) & 0x3FFFF):
            return
        if not isinstance(payload, (list, tuple)) or len(payload) < 2 or ((int(payload[0]) >> 4) & 0x0F) != 0:
            return
        length = int(payload[0]) & 0x0F
        body = [int(value) & 0xFF for value in payload[1:1 + length]]
        if not body:
            return
        comm = self._addr_comm
        if comm is not None and comm.get("stage") == "ack" and src == comm["sa"] and \
                (body[0] == 0x68 or (body[0] == 0x7F and len(body) >= 2 and body[1] == 0x28)):
            self._addr_comm_answer(body, now)
            return
        if self._addr_info_sa is not None and src == self._addr_info_sa:
            self._addr_info_answer(body)
            return
        if self._addr_active and self._addr_stage in ADDR_REQUEST_STEPS:
            self._addr_answer(src, body, now)

    def _addr_answer(self, src: int, body: list[int], now: float):
        """Цель функции в разборе ответа на запрос шага, затем подтверждение, отказ или «подождите»."""
        stage = self._addr_stage
        cand, new = self._addr_candidate_sa, self._addr_new_sa
        sids = {"identify": 0x22, "session": 0x10, "seed": 0x27, "key": 0x27,
                "write": 0x2E, "verify": 0x22, "default": 0x10, "quiet": 0x28}
        sid = sids[stage]
        # Ответ на запись адреса может прийти и со старого, и уже с нового адреса.
        if stage == "write":
            allowed = {cand, new}
        elif stage in ("identify", "session", "seed", "key"):
            allowed = {cand}
        else:
            allowed = {new}
        if src not in allowed:
            return
        if body[0] == 0x7F and len(body) >= 3 and body[1] == sid:
            if body[2] == 0x78:
                # Прибор просит подождать: ожидание продлевается, попытка не тратится.
                self._addr_sent_s = now
                return
            self._addr_fail(f"{ADDR_STEP_TITLES.get(stage, stage)}: плата отказала, {self._addr_nrc_text(body[2])}.")
            return
        if body[0] != (sid | 0x40):
            return
        if stage == "identify" and len(body) >= 4 and body[1:3] == [0x00, 0x11]:
            self._addr_step_ok("identify", "session", now,
                               f"Плата 0x{cand:02X} отвечает. Записываю адрес 0x{new:02X}...")
        elif stage == "session" and len(body) >= 2 and body[1] == 0x03:
            self._addr_step_ok("session", "seed", now)
        elif stage == "seed" and len(body) >= 4 and body[1] == 0x01:
            # Прибор шлёт seed младшим байтом вперёд: 67 01 seed_lo seed_hi.
            self._addr_seed = (body[3] << 8) | body[2]
            if self._addr_seed == 0:
                # Нулевой seed - доступ уже открыт: ключ не нужен.
                self._addr_steps["key"] = "ok"
                self._addr_step_ok("seed", "write", now)
            else:
                self._addr_step_ok("seed", "key", now)
        elif stage == "key" and len(body) >= 2 and body[1] == 0x02:
            self._addr_step_ok("key", "write", now)
        elif stage == "write" and len(body) >= 3 and body[1:3] == [0x00, 0x11]:
            self._addr_step_ok("write", "verify", now)
        elif stage == "verify" and len(body) >= 4 and body[1:3] == [0x00, 0x11]:
            if body[3] != new:
                self._addr_fail(f"Проверка не пройдена: плата сообщает адрес 0x{body[3]:02X}, "
                                f"а записывали 0x{new:02X}.")
                return
            self._addr_step_ok("verify", "default", now, f"Адрес 0x{new:02X} записан и проверен чтением.")
        elif stage == "default" and len(body) >= 2 and body[1] == 0x01:
            if self._addr_job == "readdress":
                self._addr_steps["default"] = "ok"
                self._addr_finish_readdress()
            else:
                self._addr_step_ok("default", "quiet", now)
        elif stage == "quiet" and len(body) >= 2 and body[1] == 0x01:
            self._addr_step_ok("quiet", "check_quiet", now)

    # ------------------------------------------------------------------ такт

    def _on_addr_tick(self):
        """Цель функции в такте мастера, затем таймауты, поиск новой платы, проверка тишины, трафик и карточки."""
        now = self._addr_clock()
        self._addr_comm_tick(now)
        self._addr_info_tick(now)
        if not self._addr_active:
            return
        stage = self._addr_stage
        if stage == "wait":
            self._addr_requiet_done(now)
            self._addr_wait_board(now)
        elif stage == "ask":
            self._addr_requiet_done(now)
        elif stage == "check_quiet":
            self._addr_check_quiet(now)
        elif stage in ADDR_REQUEST_STEPS:
            if now - self._addr_sent_s < self.ADDR_STEP_TIMEOUT_S:
                return
            if self._addr_attempt >= self.ADDR_ATTEMPTS:
                timeout = str(self.ADDR_STEP_TIMEOUT_S).replace(".", ",")
                self._addr_fail(f"{ADDR_STEP_TITLES.get(stage, stage)}: плата не ответила за "
                                f"{self.ADDR_ATTEMPTS} попытки по {timeout} с.")
                return
            self._addr_request(now)

    def _addr_check_quiet(self, now: float):
        """Цель функции в проверке тишины после команды, затем трафик платы не мешает искать следующую."""
        noisy = [sa for sa in (self._addr_new_sa, self._addr_candidate_sa)
                 if sa is not None and self._addr_seen.get(sa, 0.0) > self._addr_quiet_since + self.ADDR_QUIET_GRACE_S]
        if noisy:
            if self._addr_quiet_retries < self.ADDR_ATTEMPTS - 1:
                # Кадры ещё идут: команда повторяется (отдельный счёт, чтобы не зациклиться).
                self._addr_quiet_retries += 1
                self._addr_seen.pop(noisy[0], None)
                self._addr_steps["check_quiet"] = ""
                self._addr_enter("quiet", now)
                return
            self._addr_fail(f"Плата 0x{noisy[0]:02X} продолжает передавать кадры J1939 после команды выключить "
                            "передачу.")
            return
        if now - self._addr_quiet_since >= self.ADDR_QUIET_CHECK_S:
            self._addr_steps["check_quiet"] = "ok"
            self._addr_finish_board()

    def _addr_wants_quiet(self, sa: int) -> bool:
        """Цель функции в выбранном режиме трафика платы, затем мастер не выключает то, что включили нарочно."""
        mode = self._addr_info.get(int(sa), {}).get("comm")
        return mode is None or (int(mode) & 0x01) == 0x01

    def _addr_requiet_done(self, now: float):
        """Цель функции в повторном выключении передачи у настроенной платы, если она снова передаёт (перезапуск)."""
        for sa in sorted(self._addr_done_sas):
            stamp = self._addr_seen.get(sa)
            if stamp is None or now - stamp > self.ADDR_SEEN_S or not self._addr_wants_quiet(sa):
                continue
            if now - self._addr_requiet_s.get(sa, 0.0) < self.ADDR_REQUIET_EVERY_S:
                continue
            self._addr_requiet_s[sa] = now
            mode = int(self._addr_info.get(sa, {}).get("comm", 0x01) or 0x01)
            # 0x28 с подавлением ответа: шаг мастера не ждёт его.
            self._addr_send(sa, [0x28, 0x80 | mode, 0x01])
            self._addr_log(f"плата {self._addr_board_name(sa)} снова передаёт кадры J1939 (перезапуск питания?) - "
                           "выключаю передачу повторно.", "#d97706")

    def _addr_wait_board(self, now: float):
        """Цель функции в поиске новой платы, затем мастер берёт ту, что передаёт кадры и ещё не настроена."""
        # Пропущенная плата не берётся снова, пока её не отключат (кадры от неё прервутся).
        self._addr_skipped = {sa for sa in self._addr_skipped
                              if now - self._addr_seen.get(sa, 0.0) <= self.ADDR_SEEN_S}
        fresh = sorted(sa for sa, stamp in self._addr_seen.items()
                       if now - stamp <= self.ADDR_SEEN_S and sa not in self._addr_done_sas
                       and sa not in self._addr_tester_sas() and sa not in self._addr_skipped)
        if not fresh:
            return
        if len(fresh) > 1:
            listed = ", ".join(f"0x{sa:02X}" for sa in fresh)
            text = (f"На шине несколько ненастроенных плат ({listed}). Подключайте платы по одной: "
                    "отключите лишние.")
            if self._addr_status != text:
                self._addr_set_status(text, "#d97706")
            return
        cand = fresh[0]
        self._addr_job = "new"
        self._addr_candidate_sa = cand
        self._addr_factory_sas.add(cand)
        self._addr_new_sa = self._addr_next_free_sa()
        if self._addr_new_sa is None:
            self._addr_fail("Свободных адресов не осталось.")
            return
        self._addr_board_number += 1
        self._addr_quiet_retries = 0
        self._addr_pending_name = f"П{self._addr_board_number}"
        self._addr_steps = {key: "" for key, _title in ADDR_STEPS}
        self._addr_steps["found"] = "ok"
        if self._addr_mode == "manual":
            # Ручной режим: мастер ждёт адрес и имя от оператора, подсказывая следующий свободный.
            self._addr_stage = "ask"
            self._addr_steps["choose"] = "run"
            self._addr_set_status(f"Плата {self._addr_board_number} найдена, её адрес сейчас 0x{cand:02X}. "
                                  "Введите новый адрес и имя, затем «Назначить».", "#0f6ab4")
            self._addr_log(f"плата {self._addr_board_number} найдена на шине: 0x{cand:02X}, жду адрес от оператора.")
            return
        self._addr_begin_write(now)

    def _addr_begin_write(self, now: float | None = None):
        """Цель функции в начале шагов с платой после выбора адреса, затем мастер дальше идёт сам."""
        self._addr_steps["choose"] = "ok"
        self._addr_set_status(f"Плата {self._addr_board_number}: 0x{self._addr_candidate_sa:02X} -> "
                              f"0x{self._addr_new_sa:02X}. Проверяю связь...", "#0f6ab4")
        self._addr_log(f"плата {self._addr_board_number}: назначаю 0x{self._addr_new_sa:02X} "
                       f"(было 0x{self._addr_candidate_sa:02X}).")
        self._addr_enter("identify", now)

    def _addr_check_sa(self, text: str, current: int | None = None) -> tuple[int | None, str]:
        """Цель функции в проверке адреса, введённого вручную, затем занятый или заводской адрес не запишется.

        current - адрес платы, которой меняют адрес из карточки (None - новая плата мастера).
        """
        sa = _parse_hex_sa(text)
        if sa is None:
            return None, "адрес - шестнадцатеричное число, например 85 или 0x85"
        if sa in self._addr_tester_sas():
            return None, f"0x{sa:02X} - адрес самой программы на шине"
        if not 0x01 <= sa <= 0xEF:
            return None, "адрес - от 0x01 до 0xEF"
        if current is not None and sa == int(current):
            return None, f"у платы уже адрес 0x{sa:02X}"
        if (current is None and sa == self._addr_candidate_sa) or sa in self._addr_factory_sas:
            return None, f"0x{sa:02X} - заводской адрес: с ним придёт следующая плата"
        board_of = getattr(self, "_mb_board", None)
        board = board_of(sa) if board_of is not None else None
        if board is not None or sa in self._addr_done_sas:
            owner = f"плата «{board['name']}»" if board is not None else "уже настроенная плата"
            return None, f"0x{sa:02X} уже занят: {owner}"
        if sa in self._addr_seen:
            return None, f"0x{sa:02X} уже есть на шине: его использует другое устройство"
        return sa, ""

    def _addr_confirm(self, sa_text: str, name: str = "") -> tuple[bool, str]:
        """Цель функции в адресе и имени от оператора (ручной режим), затем мастер записывает их сам."""
        if not self._addr_active or self._addr_stage != "ask" or self._addr_candidate_sa is None:
            return False, "мастер не ждёт адрес: он спрашивает его, когда находит новую плату"
        sa, error = self._addr_check_sa(sa_text)
        if sa is None:
            return False, error
        self._addr_new_sa = sa
        self._addr_pending_name = str(name or "").strip()[:24] or f"П{self._addr_board_number}"
        self._addr_begin_write()
        return True, f"назначаю 0x{sa:02X}"

    def _addr_set_mode(self, mode: str) -> bool:
        """Цель функции в выборе режима (автоматически или вручную), затем ждущая плата идёт по новому режиму."""
        mode = str(mode)
        if mode not in ADDR_MODES:
            return False
        self._addr_mode = mode
        self._addr_save_settings()
        if mode == "auto" and self._addr_active and self._addr_stage == "ask":
            # Плата ждала адрес от оператора: дальше - с подсказанным адресом.
            self._addr_begin_write()
        else:
            self._addr_changed()
        return True

    def _addr_used_sas(self) -> set[int]:
        """Цель функции в занятых адресах, затем новый адрес не совпадёт ни с одной платой и программой."""
        used = set(self._addr_done_sas) | set(self._addr_factory_sas) | self._addr_tester_sas()
        used |= {int(board["sa"]) for board in getattr(self, "_mb_boards", []) or []}
        # Адреса, замеченные на шине (другие устройства), тоже заняты.
        used |= set(self._addr_seen)
        if self._addr_candidate_sa is not None:
            used.add(int(self._addr_candidate_sa))
        return used

    def _addr_next_free_sa(self) -> int | None:
        """Цель функции в следующем свободном адресе от первого заданного, затем заводской адрес новых плат пропускается."""
        used = self._addr_used_sas()
        start = int(self._addr_start_sa)
        for sa in list(range(start, 0xF0)) + list(range(0x01, start)):
            if sa not in used:
                return sa
        return None

    def _addr_finish_board(self):
        """Цель функции в завершении платы, затем она в «Платах в камере», данные читаются, мастер ждёт следующую."""
        new, old = int(self._addr_new_sa), int(self._addr_candidate_sa)
        # Старый (заводской) адрес в настроенные не попадает: следующая плата придёт с ним же.
        self._addr_done_sas.add(new)
        self._addr_seen.pop(old, None)
        self._addr_frames.pop(old, None)
        name = self._addr_pending_name or f"П{self._addr_board_number}"
        board_of = getattr(self, "_mb_board", None)
        add = getattr(self, "_mb_add_board", None)
        if add is not None and board_of is not None and board_of(new) is None:
            add(f"0x{new:02X}", name)
        board = board_of(new) if board_of is not None else None
        name = board["name"] if board else name
        info = self._addr_info.setdefault(new, {})
        info.update({"oldSa": old, "comm": 0x01, "addressedAt": time.strftime("%d.%m %H:%M"),
                     "commResult": "подтверждено мастером: кадров J1939 нет 3 с", "commTone": "ok"})
        self._addr_save_settings()
        self._addr_queue_info(new)
        self._addr_stage = "wait"
        self._addr_candidate_sa = None
        self._addr_new_sa = None
        self._addr_set_status(f"Плата «{name}» готова: адрес 0x{new:02X}, передача J1939 выключена (RX вкл · TX "
                              f"выкл). Подключите плату {self._addr_board_number + 1}.", "#16a34a")
        self._addr_log(f"плата «{name}»: 0x{old:02X} -> 0x{new:02X}, записано, проверено, передача J1939 выключена.",
                       "#16a34a")

    # ------------------------------------------------------------------ смена адреса из карточки

    def _addr_readdress(self, sa: int, sa_text: str) -> tuple[bool, str]:
        """Цель функции в смене адреса уже настроенной платы, затем те же шаги с проверкой, что у мастера."""
        sa = int(sa) & 0xFF
        board_of = getattr(self, "_mb_board", None)
        if board_of is None or board_of(sa) is None:
            return False, f"платы 0x{sa:02X} нет в списке"
        if getattr(self, "_climate_run_stage", ""):
            return False, "идёт прогон в камере: адреса меняются до или после него"
        if self._addr_stepping() or self._addr_stage in ("ask", "failed"):
            return False, "мастер сейчас работает с другой платой: дождитесь конца или остановите его"
        busy = uds_exchange_busy(self, ignore=("board_addressing",))
        if busy:
            return False, f"идёт обмен с прибором в другом разделе ({busy}): подождите"
        new, error = self._addr_check_sa(sa_text, current=sa)
        if new is None:
            return False, error
        self._addr_return_active = bool(self._addr_active)
        self._addr_job = "readdress"
        self._addr_active = True
        self._addr_candidate_sa = sa
        self._addr_new_sa = new
        self._addr_steps = {key: ("ok" if key in ("found", "choose") else "") for key, _title in ADDR_STEPS}
        self._addr_set_status(f"Меняю адрес платы {self._addr_board_name(sa)} на 0x{new:02X}...", "#0f6ab4")
        self._addr_log(f"смена адреса платы {self._addr_board_name(sa)} на 0x{new:02X}.")
        self._addr_enter("identify")
        return True, f"меняю адрес на 0x{new:02X}"

    def _addr_finish_readdress(self):
        """Цель функции в завершении смены адреса, затем у платы в списке камеры новый адрес, остальное - её же."""
        old, new = int(self._addr_candidate_sa), int(self._addr_new_sa)
        name = self._addr_board_name(old)
        change = getattr(self, "_mb_change_sa", None)
        if change is not None:
            change(old, new)
        info = self._addr_info.pop(old, {})
        info["oldSa"] = old
        info["addressedAt"] = time.strftime("%d.%m %H:%M")
        self._addr_info[new] = info
        self._addr_done_sas.discard(old)
        self._addr_done_sas.add(new)
        for table in (self._addr_seen, self._addr_frames, self._addr_requiet_s):
            table.pop(old, None)
        self._addr_save_settings()
        self._addr_queue_info(new)
        self._addr_restore_after_job()
        self._addr_set_status(f"Адрес платы {name} изменён на 0x{new:02X}: записан и проверен чтением.", "#16a34a")
        self._addr_log(f"плата {name}: адрес изменён на 0x{new:02X}, проверен чтением.", "#16a34a")

    def _addr_restore_after_job(self):
        """Цель функции в возврате мастера к тому, что было до смены адреса из карточки."""
        self._addr_job = "new"
        self._addr_candidate_sa = None
        self._addr_new_sa = None
        self._addr_steps = {key: "" for key, _title in ADDR_STEPS}
        self._addr_active = bool(self._addr_return_active)
        self._addr_stage = "wait" if self._addr_active else ""
        self._addr_return_active = False

    def _addr_rename(self, sa: int, name: str) -> tuple[bool, str]:
        """Цель функции в смене имени платы из карточки, затем оно же в журналах и списке камеры."""
        rename = getattr(self, "_mb_rename_board", None)
        text = str(name or "").strip()
        if not text:
            return False, "имя не может быть пустым"
        if rename is None or not rename(int(sa), text):
            return False, f"платы 0x{int(sa) & 0xFF:02X} нет в списке"
        self._addr_changed()
        return True, "имя изменено"

    # ------------------------------------------------------------------ трафик J1939 платы

    def _addr_set_comm(self, sa: int, mode: int) -> tuple[bool, str]:
        """Цель функции в режиме трафика J1939 одной платы (0x28), затем команда ждёт подтверждения и проверки."""
        sa, mode = int(sa) & 0xFF, int(mode)
        if mode not in COMM_STATE_TEXT:
            return False, "неизвестный режим трафика"
        board_of = getattr(self, "_mb_board", None)
        if board_of is None or board_of(sa) is None:
            return False, f"платы 0x{sa:02X} нет в списке"
        self._addr_comm_queue = [item for item in self._addr_comm_queue if item[0] != sa]
        self._addr_comm_queue.append((sa, mode))
        info = self._addr_info.setdefault(sa, {})
        info["commResult"] = f"отправляю: {COMM_STATE_TEXT[mode]}..."
        info["commTone"] = "normal"
        self._addr_changed()
        return True, "команда поставлена в очередь"

    def _addr_comm_tick(self, now: float):
        """Цель функции в ходе команды трафика: отправка, ожидание 0x68, проверка по шине."""
        comm = self._addr_comm
        if comm is None:
            if not self._addr_comm_queue or self._addr_stepping() or self._addr_info_sa is not None:
                return
            if uds_exchange_busy(self, ignore=("board_addressing",)) or background_request_recent(self):
                return
            sa, mode = self._addr_comm_queue.pop(0)
            self._addr_comm = comm = {"sa": sa, "mode": mode, "stage": "ack", "attempt": 0, "sent": 0.0}
            self._addr_comm_send(now)
            return
        if comm["stage"] == "ack":
            if now - comm["sent"] < self.ADDR_STEP_TIMEOUT_S:
                return
            if comm["attempt"] >= self.ADDR_ATTEMPTS:
                self._addr_comm_done("плата не подтвердила команду 0x28 за 3 попытки", "bad")
                return
            self._addr_comm_send(now)
            return
        # Проверка по шине: передача выключена - кадров нет, включена - кадры идут.
        sa, tx_on = comm["sa"], (comm["mode"] & 0x01) == 0
        last = self._addr_seen.get(sa, 0.0)
        if tx_on and last > comm["since"]:
            self._addr_comm_done(f"подтверждено {time.strftime('%H:%M:%S')}: кадры J1939 идут", "ok")
        elif not tx_on and last > comm["since"] + self.ADDR_QUIET_GRACE_S:
            self._addr_comm_done("плата подтвердила, но кадры J1939 от неё идут", "bad")
        elif now - comm["since"] >= self.ADDR_COMM_CHECK_S:
            if tx_on:
                self._addr_comm_done("плата подтвердила, но кадров J1939 от неё нет", "warn")
            else:
                self._addr_comm_done(f"подтверждено {time.strftime('%H:%M:%S')}: кадров J1939 нет "
                                     f"{str(self.ADDR_COMM_CHECK_S).replace('.', ',')} с", "ok")

    def _addr_comm_send(self, now: float):
        """Цель функции в отправке 0x28 <режим> 0x01 с ответом, затем отсчитывается таймаут."""
        comm = self._addr_comm
        comm["attempt"] += 1
        comm["sent"] = now
        note_background_request(self)
        self._addr_send(comm["sa"], [0x28, comm["mode"] & 0x7F, 0x01])

    def _addr_comm_answer(self, body: list[int], now: float):
        """Цель функции в разборе ответа на 0x28, затем подтверждённый режим проверяется по шине."""
        comm = self._addr_comm
        if body[0] == 0x7F:
            if len(body) >= 3 and body[2] == 0x78:
                comm["sent"] = now
                return
            code = body[2] if len(body) >= 3 else 0
            self._addr_comm_done(f"плата отказала: {self._addr_nrc_text(code)}", "bad")
            return
        if len(body) < 2 or body[1] != (comm["mode"] & 0x7F):
            return
        info = self._addr_info.setdefault(comm["sa"], {})
        info["comm"] = comm["mode"]
        self._addr_save_settings()
        comm["stage"] = "check"
        comm["since"] = now
        info["commResult"] = "плата подтвердила, проверяю по шине..."
        info["commTone"] = "normal"
        self._addr_changed()

    def _addr_comm_done(self, text: str, tone: str):
        """Цель функции в итоге команды трафика на карточке и в журнале."""
        comm = self._addr_comm
        self._addr_comm = None
        info = self._addr_info.setdefault(comm["sa"], {})
        info["commResult"] = text
        info["commTone"] = tone
        color = {"ok": "#16a34a", "bad": "#dc2626", "warn": "#d97706"}.get(tone, "#0f6ab4")
        self._addr_log(f"плата {self._addr_board_name(comm['sa'])}, трафик {COMM_STATE_TEXT[comm['mode']]}: {text}.",
                       color)
        self._addr_changed()

    def _addr_comm_all(self, mode: int) -> bool:
        """Цель функции в режиме трафика сразу всем платам (функционально, без ответа)."""
        mode = int(mode)
        if mode not in COMM_STATE_TEXT:
            return False
        if not self._addr_bus_send(self._addr_functional_identifier(), [0x03, 0x28, 0x80 | mode, 0x01,
                                                                         0xFF, 0xFF, 0xFF, 0xFF]):
            return False
        for board in getattr(self, "_mb_boards", []) or []:
            info = self._addr_info.setdefault(int(board["sa"]), {})
            info["comm"] = mode
            info["commResult"] = "команда всем платам, без подтверждения"
            info["commTone"] = "normal"
        self._addr_save_settings()
        self._addr_set_status(f"Всем платам отправлено: трафик J1939 {COMM_STATE_TEXT[mode]}.", "#0f6ab4")
        self._addr_log(f"всем платам отправлено: трафик J1939 {COMM_STATE_TEXT[mode]}.")
        return True

    def _addr_release_all(self) -> bool:
        """Цель функции в возврате обычного трафика всем платам (RX+TX), затем мастер останавливается."""
        if self._addr_active and not self._addr_stepping():
            # Мастер не должен тут же выключить передачу обратно.
            self._addr_stop()
        return self._addr_comm_all(0x00)

    # ------------------------------------------------------------------ данные для карточки

    def _addr_queue_info(self, sa: int):
        """Цель функции в очереди чтения данных платы для карточки, затем DID читаются по одному с таймаутом."""
        sa = int(sa) & 0xFF
        self._addr_info_queue = [item for item in self._addr_info_queue if item[0] != sa]
        self._addr_info_queue += [(sa,) + item for item in ADDR_INFO_DIDS]
        self._addr_changed()

    def _addr_info_tick(self, now: float):
        """Цель функции в очередном чтении для карточки, затем оно не мешает шагам мастера и другим разделам."""
        if self._addr_info_sa is not None:
            if now - self._addr_info_sent_s < self.ADDR_INFO_WAIT_S:
                return
            # Не ответила - значение остаётся прежним, очередь идёт дальше.
            self._addr_info_sa = None
            if not self._addr_info_queue:
                self._addr_changed()
        if not self._addr_info_queue:
            return
        if self._addr_stepping() or (self._addr_comm is not None and self._addr_comm.get("stage") == "ack"):
            return
        if uds_exchange_busy(self, ignore=("board_addressing",)) or background_request_recent(self):
            return
        sa, did, key, size, signed, divider = self._addr_info_queue.pop(0)
        self._addr_info_sa = sa
        self._addr_info_current = (did, key, size, signed, divider)
        self._addr_info_sent_s = now
        note_background_request(self)
        self._addr_send(sa, [0x22, (did >> 8) & 0xFF, did & 0xFF])

    def _addr_info_answer(self, body: list[int]):
        """Цель функции в разборе ответа на чтение для карточки, затем число попадает в карточку платы."""
        if self._addr_info_current is None:
            self._addr_info_sa = None
            return
        did, key, size, signed, divider = self._addr_info_current
        if body[0] == 0x7F:
            # «Подождите» - ждём дальше; другой отказ - параметра нет, очередь идёт дальше.
            if len(body) >= 3 and body[1] == 0x22 and body[2] != 0x78:
                self._addr_info_sa = None
            return
        if body[0] != 0x62 or len(body) < 3 + size or did not in ((body[1] << 8) | body[2], (body[2] << 8) | body[1]):
            return
        sa = self._addr_info_sa
        self._addr_info_sa = None
        raw = 0
        for shift, byte in enumerate(body[3:3 + size]):
            raw |= (int(byte) & 0xFF) << (8 * shift)
        if signed:
            limit = 1 << (8 * size)
            if raw >= limit >> 1:
                raw -= limit
        info = self._addr_info.setdefault(sa, {})
        info[key] = raw / divider if divider != 1.0 else raw
        info["readAt"] = time.strftime("%H:%M:%S")
        self._addr_changed()

    # ------------------------------------------------------------------ управление

    def _addr_start(self, start_text: str = "") -> tuple[bool, str]:
        """Цель функции в запуске мастера, затем он ждёт первую плату и назначает адреса с заданного."""
        if self._addr_active:
            return False, "мастер уже запущен"
        text = str(start_text or "").strip()
        if text:
            start = _parse_hex_sa(text)
            if start is None:
                return False, "первый адрес - шестнадцатеричное число, например 81 или 0x81"
            if not 0x01 <= start <= 0xEF:
                return False, "первый адрес - от 0x01 до 0xEF"
            if start in self._addr_tester_sas():
                return False, f"0x{start:02X} - адрес самой программы на шине"
            self._addr_start_sa = start
            self._addr_save_settings()
        can = getattr(self, "_can", None)
        if can is not None and (not getattr(can, "is_connect", False) or not getattr(can, "is_trace", False)):
            return False, "подключите адаптер CAN и включите трассировку"
        if getattr(self, "_climate_run_stage", ""):
            return False, "идёт прогон в камере: адреса меняются до или после него"
        busy = uds_exchange_busy(self, ignore=("board_addressing",))
        if busy:
            return False, f"идёт обмен с прибором в другом разделе ({busy}): подождите"
        self._addr_active = True
        self._addr_job = "new"
        self._addr_seen = {}
        self._addr_requiet_s = {}
        self._addr_done_sas = {int(board["sa"]) for board in getattr(self, "_mb_boards", []) or []}
        self._addr_steps = {key: "" for key, _title in ADDR_STEPS}
        self._addr_board_number = len(self._addr_done_sas)
        self._addr_candidate_sa = None
        self._addr_new_sa = None
        self._addr_skipped = set()
        self._addr_stage = "wait"
        how = (f"Адреса - с 0x{self._addr_start_sa:02X}." if self._addr_mode == "auto"
               else "Адрес и имя каждой найденной плате введёте сами.")
        self._addr_set_status(f"Подключите новую плату {self._addr_board_number + 1} к шине CAN и подайте питание. "
                              f"{how}", "#0f6ab4")
        self._addr_log("мастер запущен, " + (f"адреса с 0x{self._addr_start_sa:02X}." if self._addr_mode == "auto"
                                             else "адреса вводит оператор."))
        return True, "мастер запущен"

    def _addr_stop(self):
        """Цель функции в остановке мастера, затем назначенные адреса и режимы трафика остаются как есть."""
        was_stepping = self._addr_stepping()
        self._addr_active = False
        self._addr_stage = ""
        self._addr_job = "new"
        self._addr_return_active = False
        self._addr_candidate_sa = None
        self._addr_new_sa = None
        text = "Мастер остановлен."
        if was_stepping:
            text += " Плата, с которой шла работа, могла остаться с прежним адресом - проверьте её."
        self._addr_set_status(text, "#64748b")

    def _addr_retry(self) -> bool:
        """Цель функции в повторе непройденного шага, затем плата и адреса те же, что были."""
        if not self._addr_active or self._addr_stage != "failed":
            return False
        stage = self._addr_failed_stage or "wait"
        if stage not in ADDR_REQUEST_STEPS + ("check_quiet",) or self._addr_candidate_sa is None:
            self._addr_stage = "wait"
            self._addr_set_status("Жду плату...", "#0f6ab4")
            return True
        if stage == "check_quiet":
            stage = "quiet"
            self._addr_quiet_retries = 0
        self._addr_set_status(f"Повторяю шаг «{ADDR_STEP_TITLES.get(stage, stage)}»...", "#0f6ab4")
        self._addr_enter(stage)
        return True

    def _addr_skip(self) -> bool:
        """Цель функции в пропуске платы после сбоя или без выбора адреса, затем мастер ждёт новую плату."""
        if not self._addr_active or self._addr_stage not in ("failed", "ask"):
            return False
        if self._addr_job == "readdress":
            # Смена адреса из карточки отменена: мастер возвращается к тому, что было.
            self._addr_restore_after_job()
            self._addr_set_status("Смена адреса отменена. Проверьте адрес платы: «Обновить» в её карточке.",
                                  "#d97706")
            return True
        # Плата могла остаться и со старым, и уже с новым адресом: оба не берутся, пока она на шине.
        for sa in (self._addr_candidate_sa, self._addr_new_sa):
            if sa is not None:
                self._addr_skipped.add(int(sa))
        self._addr_candidate_sa = None
        self._addr_new_sa = None
        self._addr_board_number = max(0, self._addr_board_number - 1)
        self._addr_steps = {key: "" for key, _title in ADDR_STEPS}
        self._addr_stage = "wait"
        self._addr_set_status(f"Плата пропущена. Отключите её и подключите плату {self._addr_board_number + 1}.",
                              "#d97706")
        return True

    def _addr_refresh_info(self, sa: int | None = None):
        """Цель функции в повторном чтении данных карточек (одной платы или всех), затем видно свежие значения."""
        boards = [int(board["sa"]) for board in getattr(self, "_mb_boards", []) or []]
        for board_sa in boards if sa is None else [int(sa) & 0xFF]:
            self._addr_queue_info(board_sa)

    # ------------------------------------------------------------------ показ

    def _addr_traffic(self, sa: int, now: float) -> tuple[bool, str]:
        """Цель функции в трафике платы, наблюдаемом на шине, затем видно, передаёт ли она кадры J1939 сейчас."""
        last = self._addr_seen.get(int(sa))
        if last is None or now - last > self.ADDR_SEEN_S:
            return False, "кадров J1939 нет"
        recent = [stamp for stamp in self._addr_frames.get(int(sa), []) if now - stamp <= self.ADDR_RATE_WINDOW_S]
        rate = len(recent) / self.ADDR_RATE_WINDOW_S
        return True, f"кадры J1939 идут, {rate:.1f} кадр/с".replace(".", ",")

    def _addr_view(self) -> dict:
        """Цель функции в данных мастера и карточек плат для окна, затем окно ничего не считает само."""
        now = self._addr_clock()

        def temp(value):
            return "—" if value is None else f"{float(value):+.1f} °C".replace(".", ",")

        def number(value):
            return "—" if value is None else str(int(value))

        can = getattr(self, "_can", None)
        listening = can is None or (bool(getattr(can, "is_connect", False)) and bool(getattr(can, "is_trace", False)))
        editable = not self._addr_stepping() and self._addr_stage not in ("ask", "failed") \
            and not getattr(self, "_climate_run_stage", "")
        comm_sa = None if self._addr_comm is None else self._addr_comm["sa"]
        queued = {sa for sa, _mode in self._addr_comm_queue}
        cards = []
        for board in getattr(self, "_mb_boards", []) or []:
            sa = int(board["sa"])
            info = self._addr_info.get(sa, {})
            status = info.get("profileStatus")
            crc = info.get("profileCrc")
            old = info.get("oldSa")
            if status is None:
                profile_text, profile_tone = "—", "normal"
            elif not int(status) & 0x01:
                profile_text, profile_tone = "пустой", "normal"
            elif int(status) & 0x08:
                profile_text, profile_tone = "применяется", "ok"
            else:
                profile_text, profile_tone = "не применяется", "bad"
            program = info.get("program")
            comm = info.get("comm")
            on_bus, traffic_text = self._addr_traffic(sa, now)
            history = []
            if old is not None:
                history.append(f"прежний адрес 0x{int(old):02X}")
            if info.get("addressedAt"):
                history.append(f"назначен {info['addressedAt']}")
            cards.append({
                "sa": sa, "saText": f"0x{sa:02X}", "name": str(board.get("name", "")),
                "history": " · ".join(history) if history else "назначен не мастером: история адреса неизвестна",
                "boardTemp": temp(info.get("boardTemp")), "fuelTemp": temp(info.get("fuelTemp")),
                "main": number(info.get("main")), "media": number(info.get("media")),
                "profileCrc": "—" if crc is None else f"0x{int(crc):04X}",
                "profileGeneration": number(info.get("profileGeneration")),
                "profileText": profile_text, "profileTone": profile_tone,
                "program": "—" if program is None else ("основная" if int(program) == 0 else "загрузчик"),
                "readAt": str(info.get("readAt", "")),
                "reading": any(item[0] == sa for item in self._addr_info_queue) or self._addr_info_sa == sa,
                "comm": -1 if comm is None else int(comm),
                "commText": "не задавался" if comm is None else COMM_STATE_TEXT.get(int(comm), "—"),
                "commResult": str(info.get("commResult", "")), "commTone": str(info.get("commTone", "normal")),
                "commBusy": sa == comm_sa or sa in queued,
                "listening": listening, "onBus": bool(on_bus), "trafficText": traffic_text if listening
                else "нет связи с шиной",
                "readdressing": self._addr_job == "readdress" and self._addr_candidate_sa == sa,
            })
        steps = [{"key": key, "title": title, "state": self._addr_steps.get(key, "")} for key, title in ADDR_STEPS
                 if self._addr_job != "readdress" or key in READDRESS_STEPS + ("found", "choose")]
        return {
            "active": bool(self._addr_active), "stage": self._addr_stage, "status": self._addr_status,
            "statusColor": self._addr_status_color, "steps": steps, "startText": f"0x{int(self._addr_start_sa):02X}",
            "candidate": "" if self._addr_candidate_sa is None else f"0x{self._addr_candidate_sa:02X}",
            "newSa": "" if self._addr_new_sa is None else f"0x{self._addr_new_sa:02X}",
            "failed": self._addr_stage == "failed", "waiting": self._addr_stage == "wait",
            "mode": self._addr_mode, "asking": self._addr_stage == "ask",
            "readdress": self._addr_job == "readdress",
            "suggestName": self._addr_pending_name if self._addr_stage == "ask" else "",
            "cards": cards, "boardNumber": int(self._addr_board_number), "editable": bool(editable),
            "commModes": [{"mode": mode, "button": button, "state": state, "hint": hint}
                          for mode, button, state, hint in COMM_MODES],
        }
