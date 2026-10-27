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

НА ШИНЕ ЛИ ПЛАТА
Пока раздел открыт, программа по кругу спрашивает адрес у каждой платы списка
(чтение 0x0011, раз в 0,4 с одной плате; плата с выключенной передачей молчит,
поэтому нужен именно запрос). Плата считается отключённой, только если не
ответила на два таких запроса подряд: паузы опроса (пока мастер работает с
другой платой) её не «теряют». Полные карточки - у плат на шине; платы, которым
адрес назначен, но которых сейчас нет на шине, не пропадают, а показываются
отдельной группой компактных карточек.

ДВЕ ПЛАТЫ НА ОДНОМ АДРЕСЕ
Если от адреса уже настроенной платы снова пошли кадры J1939, это либо та же
плата после перезапуска питания, либо новая плата, пришедшая с тем же адресом.
Мастер спрашивает адрес (0x0011) и считает ответы: один - перезапуск (передача
выключается, как раньше), два - конфликт. Тогда он разделяет платы: обеим -
расширенный сеанс и запрос seed (у плат он разный: считается от времени работы
платы), ключ - по первому seed, поэтому доступ открывается только одной плате,
и новый адрес записывает только она; проверка - по новому адресу отвечает ровно
одна плата; обеим - обычный сеанс. Какая плата переехала, видно по трафику:
новая передаёт кадры J1939, настроенная молчит. Переехала новая - она
добавляется в список с новым адресом и выключенной передачей. Переехала
настроенная - платы меняются местами тремя сменами адреса по одной плате
(новая - на временный свободный адрес, настроенная - обратно на свой, новая -
на назначенный). Итог всегда один: настроенная плата остаётся на своём
адресе, новая получает следующий по порядку.

СБРОС АДРЕСОВ
«Сбросить адреса» возвращает каждой подключённой плате списка заводской адрес
0x6A (сеанс, доступ, запись 0x0011) и проверяет, что по старому адресу она
больше не отвечает; список плат и их история очищаются, и мастер снова
назначает адреса строго по порядку подключения от первого адреса. Платы,
которых при сбросе не было на шине, просто забываются: если такая плата потом
придёт со старым адресом и он окажется занят, мастер заметит две платы на
одном адресе и разведёт их сам (раздел выше).

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
    ("gone", "Старый адрес больше не отвечает"),
)
ADDR_STEP_TITLES = dict(ADDR_STEPS)
# Шаги разделения двух плат с одним адресом.
DUP_STEPS = (
    ("dup_probe", "Две платы на одном адресе"),
    ("dup_session", "Расширенный сеанс обеим"),
    ("dup_seed", "Получены разные seed"),
    ("dup_key", "Доступ открыт одной плате"),
    ("dup_write", "Новый адрес записан одной плате"),
    ("dup_verify", "По новому адресу отвечает одна плата"),
    ("dup_default", "Обычный сеанс обеим"),
    ("dup_observe", "Определено, какая плата новая"),
)
DUP_STEP_TITLES = dict(DUP_STEPS)
# Шаги смены адреса уже настроенной платы: без поиска и без выключения передачи.
READDRESS_STEPS = ("identify", "session", "seed", "key", "write", "verify", "default")
# Шаги сброса адреса к заводскому: проверка - старый адрес молчит (по заводскому могут ответить несколько плат).
RESET_STEPS = ("identify", "session", "seed", "key", "write", "gone")
# Шаги с запросом к плате и ожиданием ответа.
ADDR_REQUEST_STEPS = ("identify", "session", "seed", "key", "write", "verify", "default", "quiet", "gone")
# Заводской адрес плат (UDS_ECU_SA_DEFAULT прошивки): к нему возвращает сброс.
FACTORY_SA = 0x6A
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
    # Плата на шине, если ответила на запрос не раньше стольких секунд назад.
    ADDR_PRESENT_S = 6.0
    # Опрос «на шине ли»: одной плате раз в столько секунд; плату, ответившую недавно, не спрашиваем.
    ADDR_PING_EVERY_S = 0.4
    ADDR_PING_FRESH_S = 2.0
    # Ответ на запрос «на шине ли» ждём столько; столько запросов подряд без ответа - плата отключена.
    ADDR_PING_ANSWER_S = 1.0
    ADDR_PING_MISSES = 2
    # Сброс: сколько старый адрес должен молчать после записи заводского, с.
    ADDR_GONE_S = 1.2
    # Разделение двух плат с одним адресом: сколько собирать ответы на запрос, с; попыток на шаг;
    # сколько смотреть на трафик, чтобы понять, какая плата новая, с; повторная проверка адреса не чаще, с.
    ADDR_DUP_WAIT_S = 0.5
    ADDR_DUP_ATTEMPTS = 3
    ADDR_DUP_OBSERVE_S = 1.5
    ADDR_DUP_RECHECK_S = 10.0
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
        # Кто на шине: последний ответ на любой запрос по адресу платы; опрос - пока раздел открыт.
        self._addr_answered: dict[int, float] = {}
        self._addr_visible = False
        self._addr_visible_since = 0.0
        self._addr_ping_index = 0
        self._addr_ping_s = 0.0
        self._addr_pinged: dict[int, float] = {}
        # Запросы «на шине ли», ждущие ответа, и сколько подряд осталось без ответа.
        self._addr_ping_wait: dict[int, float] = {}
        self._addr_misses: dict[int, int] = {}
        # Сброс адресов: очередь плат и адреса плат, которых при сбросе не было на шине.
        self._addr_reset_queue: list[int] = []
        self._addr_probe: dict | None = None
        # Две платы на одном адресе: ход разделения, когда трафик адреса появился и когда его проверяли.
        self._addr_dup: dict | None = None
        self._addr_onset: dict[int, float] = {}
        self._addr_dup_checked: dict[int, float] = {}
        # Адрес, который новая плата сохраняет (она осталась на нём после разделения).
        self._addr_keep_sa: int | None = None
        # Обмен местами двух плат после разделения: оставшиеся смены адреса.
        self._addr_swap: dict | None = None
        self._addr_reset_done: list[str] = []
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
                                        "boards": boards},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
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
        return bool(self._addr_active) and self._addr_stage in ADDR_REQUEST_STEPS + ("check_quiet", "probe", "dup")

    def _addr_exchange_busy(self) -> bool:
        """Цель функции в признаке обмена мастера с платой, затем другие опросы не вклиниваются в него."""
        stepping = bool(self._addr_active) and self._addr_stage in ADDR_REQUEST_STEPS + ("probe", "dup")
        comm_waiting = self._addr_comm is not None and self._addr_comm.get("stage") == "ack"
        return stepping or comm_waiting or self._addr_info_sa is not None or self._addr_ping_pending()

    def _addr_ping_pending(self) -> bool:
        """Цель функции в признаке опроса «на шине ли», ответ на который ещё в пути."""
        return self._addr_clock() - self._addr_ping_s < 0.15

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

    def _addr_refuse(self, text: str) -> str:
        """Цель функции в показе отказа в строке состояния раздела, затем причину видно в том же окне."""
        message = str(text)[:1].upper() + str(text)[1:] + "."
        self._addr_set_status(message, "#dc2626")
        return message

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
            "gone": (cand, [0x22, 0x00, 0x11]),
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
        last = self._addr_seen.get(src)
        if last is None or now - last > self.ADDR_SEEN_S:
            # Адрес начал передавать (включение питания, новая плата): повод проверить, не две ли там платы.
            self._addr_onset[src] = now
        self._addr_seen[src] = now
        self._addr_misses[src] = 0
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
        # Любой ответ по адресу платы: она на шине (даже с выключенной передачей J1939).
        self._addr_answered[src] = now
        self._addr_misses[src] = 0
        self._addr_ping_wait.pop(src, None)
        dup = self._addr_dup
        if dup is not None and self._addr_stage == "dup" and src in (dup["sa"], dup.get("new")):
            # Разделение: ответы собираются целиком - их может быть два на один запрос.
            dup["rx"].append((src, body))
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
                "write": 0x2E, "verify": 0x22, "default": 0x10, "quiet": 0x28, "gone": 0x22}
        sid = sids[stage]
        # Ответ на запись адреса может прийти и со старого, и уже с нового адреса.
        if stage == "write":
            allowed = {cand, new}
        elif stage in ("identify", "session", "seed", "key", "gone"):
            allowed = {cand}
        else:
            allowed = {new}
        if src not in allowed:
            return
        if stage == "gone":
            # Сброс: по старому адресу никто не должен отвечать.
            if body[0] == 0x62 and len(body) >= 4 and body[1:3] == [0x00, 0x11]:
                self._addr_fail(f"Плата по-прежнему отвечает по старому адресу 0x{cand:02X}: сброс не прошёл.")
            return
        if body[0] == 0x7F and len(body) >= 3 and body[1] == sid:
            if body[2] == 0x78:
                # Прибор просит подождать: ожидание продлевается, попытка не тратится.
                self._addr_sent_s = now
                return
            self._addr_fail(f"{ADDR_STEP_TITLES.get(stage, stage)}: плата отказала, {self._addr_nrc_text(body[2])}.")
            return
        if stage in ("key", "write") and body[0] == 0x67 and len(body) >= 4 and body[1] == 0x01                 and ((body[3] << 8) | body[2]) != self._addr_seed:
            # Второй, другой seed по тому же адресу: отвечают несколько плат (например, все после сброса).
            # «Повторить шаг» начнёт доступ заново - с запроса seed.
            self._addr_steps[stage] = ""
            self._addr_stage = "seed"
            self._addr_fail(f"По адресу 0x{cand:02X} отвечают несколько плат. Оставьте на шине одну новую плату "
                            "и повторите шаг.")
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
            self._addr_step_ok("write", "gone" if self._addr_job == "reset" else "verify", now)
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
            elif self._addr_job == "swap":
                self._addr_steps["default"] = "ok"
                self._addr_swap_next()
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
        self._addr_presence_tick(now)
        if not self._addr_active:
            return
        stage = self._addr_stage
        if stage == "probe":
            self._addr_probe_tick(now)
            return
        if stage == "dup":
            self._addr_dup_tick(now)
            return
        if stage == "gone":
            if now - self._addr_sent_s >= self.ADDR_GONE_S:
                self._addr_steps["gone"] = "ok"
                self._addr_finish_reset_board()
            return
        if stage == "wait":
            if self._addr_check_known_traffic(now):
                return
            self._addr_requiet_done(now)
            self._addr_wait_board(now)
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
        if cand == FACTORY_SA or cand < int(self._addr_start_sa):
            # Заводской адрес новых плат в план не берётся; адрес из плана (плата пришла с ним) - снова свободен.
            self._addr_factory_sas.add(cand)
        if cand == self._addr_keep_sa:
            # После разделения новая плата осталась на освободившемся адресе: он и остаётся за ней.
            self._addr_new_sa = cand
            self._addr_keep_sa = None
        else:
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
        if self._addr_present(sa, self._addr_clock()):
            return None, f"0x{sa:02X} сейчас есть на шине: его использует другое устройство"
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
        # Адреса устройств, которые сейчас на шине, тоже заняты.
        now = self._addr_clock()
        used |= {sa for sa in set(self._addr_seen) | set(self._addr_answered) if self._addr_present(sa, now)}
        cand = self._addr_candidate_sa
        if cand is not None:
            if int(cand) in self._addr_factory_sas:
                used.add(int(cand))
            elif int(cand) not in self._addr_done_sas and not any(
                    int(board["sa"]) == int(cand) for board in getattr(self, "_mb_boards", []) or []):
                # Плата пришла со своим адресом из плана: если он как раз следующий по порядку - он за ней.
                used.discard(int(cand))
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
        self._addr_reset_queue = []
        self._addr_probe = None
        self._addr_dup = None
        self._addr_swap = None
        text = "Мастер остановлен."
        if was_stepping:
            text += " Плата, с которой шла работа, могла остаться с прежним адресом - проверьте её."
        self._addr_set_status(text, "#64748b")

    def _addr_retry(self) -> bool:
        """Цель функции в повторе непройденного шага, затем плата и адреса те же, что были."""
        if not self._addr_active or self._addr_stage != "failed":
            return False
        stage = self._addr_failed_stage or "wait"
        if self._addr_job == "conflict" and self._addr_candidate_sa is not None:
            # Разделение начинается заново - с проверки, сколько плат отвечает по адресу.
            self._addr_dup_start(int(self._addr_candidate_sa))
            return True
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
        if self._addr_job == "reset":
            # Плата не сбросилась: она забывается, сброс идёт к следующей (её адрес мастер разведёт при встрече).
            sa = int(self._addr_candidate_sa)
            self._addr_reset_done.append(f"{self._addr_board_name(sa)} пропущена и забыта (адрес не сброшен)")
            self._addr_reset_drop(sa)
            self._addr_reset_next()
            return True
        if self._addr_job == "swap":
            # Обмен местами прерван: платы на разных адресах, но не на задуманных - видно в карточках.
            self._addr_swap = None
            self._addr_dup_done()
            self._addr_set_status("Обмен адресами прерван: адреса плат разные, но не те, что задуманы. Проверьте "
                                  "карточки или сбросьте адреса.", "#d97706")
            return True
        if self._addr_job == "conflict":
            # Разделение отложено: мастер ждёт дальше, адрес перепроверится не раньше чем через 10 с.
            self._addr_dup_done()
            self._addr_set_status("Разделение отложено. Отключите одну из плат с одинаковым адресом и подключите её "
                                  "снова - мастер назначит ей свой адрес.", "#d97706")
            return True
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

    # ------------------------------------------------------------------ на шине ли плата

    def _addr_set_visible(self, visible: bool):
        """Цель функции в признаке открытого раздела, затем опрос «на шине ли» идёт только пока его видно."""
        visible = bool(visible)
        if visible and not self._addr_visible:
            self._addr_visible_since = self._addr_clock()
            self._addr_pinged = {}
        self._addr_visible = visible
        self._addr_changed()

    def _addr_present(self, sa: int, now: float) -> bool:
        """Цель функции в признаке «плата на шине»: недавно ответила на запрос или передавала кадры J1939."""
        answered = self._addr_answered.get(int(sa))
        seen = self._addr_seen.get(int(sa))
        return (answered is not None and now - answered <= self.ADDR_PRESENT_S) or \
            (seen is not None and now - seen <= self.ADDR_SEEN_S)

    def _addr_shown_present(self, sa: int, now: float) -> bool:
        """Цель функции в признаке «плата на шине» для окна: отключённой считается только не ответившая дважды.

        Время с последнего ответа здесь не решает: пока мастер работает с другой
        платой, опрос стоит, а плата с выключенной передачей молчит - по таймеру
        она пропадала бы с экрана, хотя на шине.
        """
        sa = int(sa)
        seen = self._addr_seen.get(sa)
        if seen is not None and now - seen <= self.ADDR_SEEN_S:
            return True
        if self._addr_misses.get(sa, 0) >= self.ADDR_PING_MISSES:
            return False
        return sa in self._addr_answered

    def _addr_first_round_s(self) -> float:
        """Цель функции во времени первого круга опроса, затем до его конца отсутствующие не объявляются."""
        count = len(getattr(self, "_mb_boards", []) or [])
        return max(1.5, count * self.ADDR_PING_EVERY_S + 1.0)

    def _addr_presence_tick(self, now: float):
        """Цель функции в опросе «на шине ли» по кругу, затем в окне видны только подключённые платы."""
        if not self._addr_visible:
            return
        # Запрос без ответа за 1 с - промах; два промаха подряд - плата отключена.
        for sa, sent in list(self._addr_ping_wait.items()):
            if now - sent > self.ADDR_PING_ANSWER_S:
                self._addr_ping_wait.pop(sa, None)
                self._addr_misses[sa] = self._addr_misses.get(sa, 0) + 1
                self._addr_changed()
        if now - self._addr_ping_s < self.ADDR_PING_EVERY_S:
            return
        boards = [int(board["sa"]) for board in getattr(self, "_mb_boards", []) or []]
        if not boards or self._addr_stepping() or self._addr_info_sa is not None:
            return
        if self._addr_comm is not None and self._addr_comm.get("stage") == "ack":
            return
        can = getattr(self, "_can", None)
        if can is not None and (not getattr(can, "is_connect", False) or not getattr(can, "is_trace", False)):
            return
        if getattr(self, "_climate_run_stage", ""):
            # В прогоне платы и так опрашиваются: их ответы отмечают присутствие.
            return
        if uds_exchange_busy(self, ignore=("board_addressing",)) or background_request_recent(self):
            return
        for _attempt in range(len(boards)):
            sa = boards[self._addr_ping_index % len(boards)]
            self._addr_ping_index += 1
            recent = max(self._addr_answered.get(sa, -1e9), self._addr_seen.get(sa, -1e9))
            if now - recent < self.ADDR_PING_FRESH_S and sa in self._addr_pinged:
                continue
            if sa in self._addr_ping_wait:
                # Прежний запрос ещё ждёт ответа: новый сбросил бы его ожидание, и промах не засчитался бы.
                continue
            self._addr_ping_s = now
            self._addr_pinged[sa] = now
            self._addr_ping_wait[sa] = now
            note_background_request(self)
            self._addr_send(sa, [0x22, 0x00, 0x11])
            return

    # ------------------------------------------------------------------ две платы на одном адресе

    def _addr_check_known_traffic(self, now: float) -> bool:
        """Цель функции в проверке адреса настроенной платы, который снова передаёт: перезапуск это или вторая плата.

        Возвращает True, если началась проверка (такт мастера на этом заканчивается).
        """
        for sa in sorted(self._addr_done_sas):
            stamp = self._addr_seen.get(sa)
            if stamp is None or now - stamp > self.ADDR_SEEN_S:
                continue
            onset = self._addr_onset.get(sa, stamp)
            checked = self._addr_dup_checked.get(sa)
            if checked is not None and (onset <= checked or now - checked < self.ADDR_DUP_RECHECK_S):
                continue
            self._addr_dup_start(sa, now)
            return True
        return False

    def _addr_dup_start(self, sa: int, now: float | None = None):
        """Цель функции в начале проверки адреса: запрос 0x0011 и подсчёт ответов."""
        now = self._addr_clock() if now is None else now
        self._addr_dup_checked[int(sa)] = now
        self._addr_job = "conflict"
        self._addr_stage = "dup"
        self._addr_candidate_sa = int(sa)
        self._addr_new_sa = None
        self._addr_dup = {"sa": int(sa), "new": None, "step": "", "rx": [], "sent": now, "attempt": 0,
                          "seed": 0, "since": now}
        self._addr_steps = {key: "" for key, _title in DUP_STEPS}
        self._addr_dup_send("dup_probe", now)

    def _addr_dup_send(self, step: str, now: float, retry: bool = False):
        """Цель функции в запросе шага разделения, затем ответы собираются 0,5 с."""
        dup = self._addr_dup
        sa, new = dup["sa"], dup.get("new")
        key = ((dup["seed"] ^ 0xAA55) | dup["seed"]) & 0xFFFF
        dup["attempt"] = dup["attempt"] + 1 if retry else 1
        dup["step"] = step
        dup["rx"] = []
        dup["sent"] = now
        self._addr_steps[step] = "run"
        requests = {
            "dup_probe": [(sa, [0x22, 0x00, 0x11])],
            "dup_session": [(sa, [0x10, 0x03])],
            "dup_seed": [(sa, [0x27, 0x01])],
            "dup_key": [(sa, [0x27, 0x02, (key >> 8) & 0xFF, key & 0xFF])],
            "dup_write": [(sa, [0x2E, 0x00, 0x11, int(new or 0) & 0xFF])],
            "dup_verify": [(new, [0x22, 0x00, 0x11])],
            "dup_default": [(new, [0x10, 0x01]), (sa, [0x10, 0x01])],
            "dup_observe": [],
        }
        for target, data in requests[step]:
            self._addr_send(int(target), data)
        self._addr_changed()

    def _addr_dup_answers(self, src: int, prefix: list[int]) -> list[list[int]]:
        """Цель функции в ответах шага разделения от адреса src, начинающихся с prefix."""
        return [body for answer_src, body in self._addr_dup["rx"]
                if answer_src == src and body[:len(prefix)] == prefix]

    def _addr_dup_retry_or_fail(self, now: float, text: str):
        """Цель функции в повторе шага разделения, затем после трёх попыток - остановка с причиной."""
        dup = self._addr_dup
        if dup["attempt"] < self.ADDR_DUP_ATTEMPTS:
            self._addr_dup_send(dup["step"], now, retry=True)
            return
        self._addr_steps[dup["step"]] = "fail"
        self._addr_fail(text)

    def _addr_dup_tick(self, now: float):
        """Цель функции в ходе разделения: по истечении окна ответов - решение и следующий шаг."""
        dup = self._addr_dup
        if dup is None or now - dup["sent"] < self.ADDR_DUP_WAIT_S:
            return
        sa, step = dup["sa"], dup["step"]
        if step == "dup_probe":
            answers = self._addr_dup_answers(sa, [0x62, 0x00, 0x11])
            if len(answers) >= 2:
                new = self._addr_next_free_sa()
                if new is None:
                    self._addr_fail(f"По адресу 0x{sa:02X} две платы, а свободных адресов не осталось.")
                    return
                dup["new"] = new
                self._addr_new_sa = new
                self._addr_steps["dup_probe"] = "ok"
                text = (f"По адресу 0x{sa:02X} отвечают две платы: разделяю - одной из них будет записан "
                        f"0x{new:02X}...")
                self._addr_set_status(text, "#d97706")
                self._addr_log(text, "#d97706")
                self._addr_dup_send("dup_session", now)
                return
            if not answers and dup["attempt"] < 2:
                self._addr_dup_send("dup_probe", now, retry=True)
                return
            # Одна плата (или никто): это перезапуск настроенной платы - как раньше.
            self._addr_dup_done()
            self._addr_requiet_s.pop(sa, None)
            self._addr_requiet_done(now)
            return
        if step == "dup_session":
            if self._addr_dup_answers(sa, [0x50, 0x03]):
                self._addr_steps[step] = "ok"
                self._addr_dup_send("dup_seed", now)
            else:
                self._addr_dup_retry_or_fail(now, f"Разделение: платы на 0x{sa:02X} не открыли расширенный сеанс.")
            return
        if step == "dup_seed":
            answers = self._addr_dup_answers(sa, [0x67, 0x01])
            seeds = []
            for body in answers:
                if len(body) >= 4:
                    seed = (body[3] << 8) | body[2]
                    if seed and seed not in seeds:
                        seeds.append(seed)
            if len(seeds) >= 2:
                dup["seed"] = seeds[0]
                self._addr_steps[step] = "ok"
                self._addr_dup_send("dup_key", now)
            elif len(answers) >= 2:
                self._addr_steps[step] = "fail"
                self._addr_fail(f"Платы на 0x{sa:02X} выдали одинаковый seed - разделить их программно нельзя. "
                                "Отключите одну из них, назначьте ей адрес отдельно и подключите снова.")
            else:
                self._addr_dup_retry_or_fail(now, f"Разделение: на запрос доступа ответила не каждая плата на "
                                                  f"0x{sa:02X}.")
            return
        if step == "dup_key":
            granted = self._addr_dup_answers(sa, [0x67, 0x02])
            if len(granted) == 1:
                self._addr_steps[step] = "ok"
                self._addr_dup_send("dup_write", now)
            else:
                # Ключ подошёл не ровно одной плате: доступ запрашивается заново, с новыми seed.
                dup["key_rounds"] = dup.get("key_rounds", 0) + 1
                if dup["key_rounds"] < self.ADDR_DUP_ATTEMPTS:
                    self._addr_steps[step] = ""
                    self._addr_dup_send("dup_seed", now)
                else:
                    self._addr_steps[step] = "fail"
                    self._addr_fail(f"Разделение: доступ открылся не ровно одной плате на 0x{sa:02X}.")
            return
        if step == "dup_write":
            written = [body for src, body in dup["rx"] if body[:3] == [0x6E, 0x00, 0x11]]
            if written:
                self._addr_steps[step] = "ok"
                self._addr_dup_send("dup_verify", now)
            else:
                self._addr_dup_retry_or_fail(now, f"Разделение: ни одна плата не записала адрес 0x{dup['new']:02X}.")
            return
        if step == "dup_verify":
            answers = self._addr_dup_answers(dup["new"], [0x62, 0x00, 0x11, dup["new"]])
            if len(answers) == 1:
                self._addr_steps[step] = "ok"
                self._addr_dup_send("dup_default", now)
            elif len(answers) >= 2:
                self._addr_steps[step] = "fail"
                self._addr_fail(f"По новому адресу 0x{dup['new']:02X} ответили обе платы - разделить их не удалось.")
            else:
                self._addr_dup_retry_or_fail(now, f"Разделение: по новому адресу 0x{dup['new']:02X} никто не "
                                                  "ответил.")
            return
        if step == "dup_default":
            self._addr_steps[step] = "ok"
            dup["since"] = now
            self._addr_dup_send("dup_observe", now)
            return
        if step == "dup_observe" and now - dup["since"] >= self.ADDR_DUP_OBSERVE_S:
            self._addr_steps[step] = "ok"
            self._addr_dup_finish(now)

    def _addr_dup_finish(self, now: float):
        """Цель функции в итоге разделения: по трафику видно, какая плата переехала.

        Переехала новая (она передаёт кадры) - она получает этот адрес. Переехала настроенная - платы
        меняются местами тремя сменами адреса по одной плате (новая - на временный адрес, настроенная -
        обратно на свой, новая - на назначенный): настроенная всегда остаётся на своём адресе, новая
        получает следующий по порядку.
        """
        dup = self._addr_dup
        old, new = int(dup["sa"]), int(dup["new"])
        moved_transmits = self._addr_seen.get(new, -1e9) >= dup["since"]
        if moved_transmits:
            name = self._addr_dup_adopt(old, new)
            text = (f"Две платы на 0x{old:02X} разделены: новая плата получила 0x{new:02X} («{name}»), передача "
                    f"J1939 у неё выключается; плата {self._addr_board_name(old)} осталась на 0x{old:02X}.")
            self._addr_dup_done()
            self._addr_set_status(text, "#16a34a")
            self._addr_log(text, "#16a34a")
            return
        self._addr_dup = None
        self._addr_candidate_sa = None
        temp = self._addr_next_free_sa_excluding({old, new})
        if temp is None:
            self._addr_job = "swap"
            self._addr_stage = "failed"
            self._addr_set_status("Нет свободного адреса, чтобы поменять платы местами.", "#dc2626")
            return
        self._addr_swap = {"old": old, "new": new, "temp": temp, "moves": [(old, temp), (new, old), (temp, new)],
                           "done": 0}
        self._addr_job = "swap"
        self._addr_log(f"на 0x{old:02X} доступ открылся прежней плате: меняю платы местами "
                       f"(новая 0x{old:02X} -> 0x{temp:02X}, прежняя 0x{new:02X} -> 0x{old:02X}, "
                       f"новая 0x{temp:02X} -> 0x{new:02X}).", "#d97706")
        self._addr_swap_next()

    def _addr_next_free_sa_excluding(self, extra: set[int]) -> int | None:
        """Цель функции в свободном адресе для временной стоянки платы, затем он не совпадёт ни с кем на шине."""
        used = self._addr_used_sas() | {int(sa) for sa in extra}
        start = int(self._addr_start_sa)
        for sa in list(range(start, 0xF0)) + list(range(0x01, start)):
            if sa not in used:
                return sa
        return None

    def _addr_swap_next(self):
        """Цель функции в очередной смене адреса при обмене местами, затем итог - когда все три сделаны."""
        swap = self._addr_swap
        if not swap["moves"]:
            old, new = swap["old"], swap["new"]
            self._addr_swap = None
            # Временного адреса больше нет: его недавние кадры не должны выглядеть новой платой.
            temp = swap.get("temp")
            if temp is not None:
                for table in (self._addr_seen, self._addr_frames, self._addr_answered, self._addr_onset):
                    table.pop(int(temp), None)
            name = self._addr_dup_adopt(old, new)
            text = (f"Две платы на 0x{old:02X} разделены: плата {self._addr_board_name(old)} осталась на "
                    f"0x{old:02X}, новая плата получила 0x{new:02X} («{name}»), передача J1939 у неё выключается.")
            self._addr_dup_done()
            self._addr_set_status(text, "#16a34a")
            self._addr_log(text, "#16a34a")
            return
        frm, to = swap["moves"].pop(0)
        swap["done"] += 1
        self._addr_candidate_sa = frm
        self._addr_new_sa = to
        self._addr_steps = {key: ("ok" if key in ("found", "choose") else "") for key, _title in ADDR_STEPS}
        self._addr_set_status(f"Меняю платы местами, шаг {swap['done']} из 3: 0x{frm:02X} -> 0x{to:02X}...",
                              "#0f6ab4")
        self._addr_enter("identify")

    def _addr_dup_adopt(self, old: int, new: int) -> str:
        """Цель функции в записи новой платы в список с её адресом и выключении у неё передачи J1939."""
        self._addr_board_number += 1
        name = f"П{self._addr_board_number}"
        add = getattr(self, "_mb_add_board", None)
        if add is not None:
            add(f"0x{new:02X}", name)
        self._addr_done_sas.add(new)
        # Кадры новой платы на её адресе - уже известны: проверять «не две ли там платы» не нужно.
        self._addr_dup_checked[new] = self._addr_clock()
        info = self._addr_info.setdefault(new, {})
        info.update({"oldSa": old, "addressedAt": time.strftime("%d.%m %H:%M")})
        self._addr_save_settings()
        self._addr_queue_info(new)
        self._addr_set_comm(new, 0x01)
        return name

    def _addr_dup_done(self):
        """Цель функции в возврате мастера к ожиданию плат после проверки или разделения адреса."""
        self._addr_dup = None
        self._addr_job = "new"
        self._addr_stage = "wait"
        self._addr_candidate_sa = None
        self._addr_new_sa = None
        self._addr_steps = {key: "" for key, _title in ADDR_STEPS}
        self._addr_changed()

    # ------------------------------------------------------------------ сброс адресов

    def _addr_reset_start(self) -> tuple[bool, str]:
        """Цель функции в сбросе адресов: подключённым платам - заводской адрес, список и история - заново."""
        if getattr(self, "_climate_run_stage", ""):
            return False, "идёт прогон в камере: адреса сбрасываются до или после него"
        if self._addr_stepping():
            return False, "мастер сейчас записывает адрес плате: дождитесь конца шага"
        can = getattr(self, "_can", None)
        if can is not None and (not getattr(can, "is_connect", False) or not getattr(can, "is_trace", False)):
            return False, "подключите адаптер CAN и включите трассировку"
        busy = uds_exchange_busy(self, ignore=("board_addressing",))
        if busy:
            return False, f"идёт обмен с прибором в другом разделе ({busy}): подождите"
        if self._addr_active or self._addr_stage:
            # Ждущий мастер (новая плата, ввод адреса, непройденный шаг) уступает сбросу.
            self._addr_stop()
        boards = [int(board["sa"]) for board in getattr(self, "_mb_boards", []) or []]
        now = self._addr_clock()
        # Сначала каждая плата списка спрашивается заново: сброс не должен решать по старым данным.
        self._addr_probe = {"boards": boards, "index": 0, "since": now, "sent": now}
        self._addr_job = "reset"
        self._addr_active = True
        self._addr_stage = "probe"
        self._addr_steps = {key: "" for key, _title in ADDR_STEPS}
        self._addr_set_status("Сброс адресов: проверяю, какие платы списка на шине...", "#0f6ab4")
        return True, "сброс адресов начат"

    def _addr_probe_tick(self, now: float):
        """Цель функции в опросе всех плат списка перед сбросом, затем сброс идёт только для ответивших."""
        probe = self._addr_probe
        if probe is None:
            return
        boards = probe["boards"]
        if probe["index"] < len(boards):
            sa = boards[probe["index"]]
            probe["index"] += 1
            probe["sent"] = now
            self._addr_send(sa, [0x22, 0x00, 0x11])
            return
        if now - probe["sent"] < 1.0:
            return
        self._addr_probe = None
        present = [sa for sa in boards if self._addr_answered.get(sa, -1e9) >= probe["since"]]
        self._addr_reset_plan(boards, present)

    def _addr_reset_plan(self, boards: list[int], present: list[int]):
        """Цель функции в очереди сброса по итогам опроса, затем платы не на шине просто забываются.

        Их адреса не держатся занятыми: нумерация после сброса идёт строго подряд, а если такая плата
        потом придёт с адресом, который уже занят, мастер заметит две платы на одном адресе и разведёт их.
        """
        self._addr_reset_done = []
        for sa in boards:
            if sa not in present:
                self._addr_reset_done.append(f"{self._addr_board_name(sa)} не на шине - забыта")
                self._addr_reset_drop(sa)
        self._addr_reset_queue = present
        self._addr_log("сброс адресов: " + (", ".join(f"0x{sa:02X}" for sa in present) or "плат на шине нет")
                       + f" -> 0x{FACTORY_SA:02X}.")
        self._addr_reset_next()

    def _addr_reset_next(self):
        """Цель функции в сбросе следующей платы очереди, затем итог, когда очередь кончилась."""
        if not self._addr_reset_queue:
            self._addr_reset_finish()
            return
        sa = self._addr_reset_queue.pop(0)
        self._addr_job = "reset"
        self._addr_return_active = False
        self._addr_active = True
        self._addr_candidate_sa = sa
        self._addr_new_sa = FACTORY_SA
        self._addr_steps = {key: "" for key, _title in ADDR_STEPS}
        self._addr_set_status(f"Сброс адреса платы {self._addr_board_name(sa)} на заводской 0x{FACTORY_SA:02X}...",
                              "#0f6ab4")
        self._addr_enter("identify")

    def _addr_reset_drop(self, sa: int):
        """Цель функции в удалении платы из списка камеры и её истории при сбросе."""
        remove = getattr(self, "_mb_remove_board", None)
        if remove is not None:
            remove(int(sa))
        self._addr_info.pop(int(sa), None)
        self._addr_done_sas.discard(int(sa))
        for table in (self._addr_seen, self._addr_frames, self._addr_requiet_s, self._addr_answered, self._addr_pinged,
                      self._addr_ping_wait, self._addr_misses):
            table.pop(int(sa), None)

    def _addr_finish_reset_board(self):
        """Цель функции в завершении сброса одной платы, затем она убрана из списка, сброс идёт дальше."""
        sa = int(self._addr_candidate_sa)
        name = self._addr_board_name(sa)
        self._addr_reset_done.append(f"{name} -> 0x{FACTORY_SA:02X}")
        self._addr_log(f"плата {name}: адрес сброшен на 0x{FACTORY_SA:02X}, старый адрес не отвечает.", "#16a34a")
        self._addr_reset_drop(sa)
        self._addr_reset_next()

    def _addr_reset_finish(self):
        """Цель функции в итоге сброса, затем мастер готов назначать адреса заново с П1."""
        self._addr_job = "new"
        self._addr_active = False
        self._addr_stage = ""
        self._addr_candidate_sa = None
        self._addr_new_sa = None
        self._addr_steps = {key: "" for key, _title in ADDR_STEPS}
        self._addr_board_number = 0
        self._addr_factory_sas = set()
        self._addr_save_settings()
        done = "; ".join(self._addr_reset_done) if self._addr_reset_done else "плат в списке не было"
        self._addr_set_status(f"Адреса сброшены ({done}). Отключите все платы, запустите мастер и подключайте "
                              "их по одной: адреса назначатся заново с П1.", "#16a34a")

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
        absent = []
        offline = []
        checking = self._addr_visible and now - self._addr_visible_since < self._addr_first_round_s()
        for board in getattr(self, "_mb_boards", []) or []:
            sa = int(board["sa"])
            info = self._addr_info.get(sa, {})
            # Пока раздел открыт, полные карточки - у плат на шине; остальные - компактной группой ниже.
            if self._addr_visible and not self._addr_shown_present(sa, now) and not (
                    self._addr_job in ("readdress", "reset") and self._addr_candidate_sa == sa):
                if not checking:
                    absent.append(f"«{board.get('name', '')}» (0x{sa:02X})")
                old = info.get("oldSa")
                offline.append({
                    "sa": sa, "saText": f"0x{sa:02X}", "name": str(board.get("name", "")),
                    "history": (f"прежний 0x{int(old):02X}" if old is not None else "история неизвестна")
                               + (f" · {info['addressedAt']}" if info.get("addressedAt") else ""),
                    "commText": COMM_STATE_TEXT.get(int(info["comm"]), "—") if info.get("comm") is not None
                    else "трафик не задавался",
                    "checking": bool(checking),
                })
                continue
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
        if self._addr_job == "conflict":
            steps = [{"key": key, "title": title, "state": self._addr_steps.get(key, "")} for key, title in DUP_STEPS]
            shown = ()
        elif self._addr_job in ("readdress", "swap"):
            shown = READDRESS_STEPS + ("found", "choose")
        elif self._addr_job == "reset":
            shown = RESET_STEPS
        else:
            shown = tuple(key for key, _title in ADDR_STEPS if key != "gone")
        if self._addr_job != "conflict":
            steps = [{"key": key, "title": title, "state": self._addr_steps.get(key, "")} for key, title in ADDR_STEPS
                     if key in shown]
        return {
            "active": bool(self._addr_active), "stage": self._addr_stage, "status": self._addr_status,
            "statusColor": self._addr_status_color, "steps": steps, "startText": f"0x{int(self._addr_start_sa):02X}",
            "candidate": "" if self._addr_candidate_sa is None else f"0x{self._addr_candidate_sa:02X}",
            "newSa": "" if self._addr_new_sa is None else f"0x{self._addr_new_sa:02X}",
            "failed": self._addr_stage == "failed", "waiting": self._addr_stage == "wait",
            "mode": self._addr_mode, "asking": self._addr_stage == "ask",
            "readdress": self._addr_job == "readdress", "conflict": self._addr_job == "conflict",
            "swap": self._addr_job == "swap",
            "suggestName": self._addr_pending_name if self._addr_stage == "ask" else "",
            "cards": cards, "boardNumber": int(self._addr_board_number), "editable": bool(editable),
            "absent": absent, "offline": offline, "checking": bool(checking),
            "listed": len(getattr(self, "_mb_boards", []) or []),
            "resetting": self._addr_job == "reset", "factorySa": f"0x{FACTORY_SA:02X}",
            "commModes": [{"mode": mode, "button": button, "state": state, "hint": hint}
                          for mode, button, state, hint in COMM_MODES],
        }
