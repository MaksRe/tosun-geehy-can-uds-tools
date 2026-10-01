"""Живые показания раздела «Прогон в камере» и точка по среднему.

ЗАЧЕМ
Раньше «Записать точку» только запускала замер: программа опрашивала прибор
пять раз подряд и складывала среднее, а оператор до нажатия не видел, что
сейчас показывает прибор и успокоились ли показания. Теперь раздел сам
опрашивает прибор, пока открыт, и рядом с текущим показанием каждого контура
держит скользящее среднее за окно - как блок «Основной контур: период уровня»
в разделе «Уровень и вид топлива». Кнопка кладёт в журнал это среднее сразу.

КАК УСРЕДНЯЕТСЯ
Каждый контур и обе температуры копят показания за последние N секунд (окно
задаёт оператор). Если показание контура резко ушло от среднего несколько раз
подряд, значит к входу подключили другой эталон: старое среднее к новой точке
не относится, и окно начинается заново с новых показаний. Одиночный выброс в
среднее не попадает.

КАК ОПРАШИВАЕТСЯ
Прибор держит один канал ISO-TP, поэтому за такт уходит один запрос и только
когда шину не занимает другой раздел. Ответы на те же параметры подхватываются
из любого обмена, кто бы их ни запросил.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer

from uds.services.read_data_by_id import ServiceReadDataById

from .bus_guard import background_request_recent, note_background_request, uds_exchange_busy
from .contract import AppControllerContract


def _decimal(value: float, digits: int) -> str:
    """Число с запятой вместо точки: так его читает оператор."""
    return f"{value:.{digits}f}".replace(".", ",")


class AppControllerChamberLiveMixin(AppControllerContract):
    # Такт опроса, мс. За такт уходит один запрос.
    CHAMBER_LIVE_PERIOD_MS = 150
    # Сколько ждать ответа, прежде чем считать запрос потерянным, с.
    CHAMBER_LIVE_PENDING_S = 0.7
    # Порядок опроса: контуры спрашиваются чаще температур, те меняются медленно.
    CHAMBER_LIVE_ORDER = ("main", "media", "main", "media", "fuel_temp", "board_temp")
    # После стольких отказов подряд параметр считается отсутствующим в прошивке.
    CHAMBER_LIVE_REFUSAL_LIMIT = 2

    # Окно скользящего среднего, с: по умолчанию и допустимые пределы.
    CHAMBER_WINDOW_DEFAULT_S = 10.0
    CHAMBER_WINDOW_MIN_S = 2.0
    CHAMBER_WINDOW_MAX_S = 120.0

    # Сколько показаний контура нужно, чтобы среднее годилось для точки.
    CHAMBER_MIN_SAMPLES = 3
    # Показание старше этого не считается текущим, с.
    CHAMBER_LIVE_STALE_S = 3.0

    # Смена эталона: отклонение больше порога столько раз подряд начинает окно заново.
    # Порог как у прошивки: 1/400 показания, но не меньше 12 отсчётов.
    CHAMBER_JUMP_MIN_COUNTS = 12
    CHAMBER_JUMP_DIVISOR = 400
    CHAMBER_JUMP_CONFIRM = 3

    # Сколько ждать среднего после нажатия «Записать точку», с.
    CHAMBER_WAIT_LIMIT_S = 20.0

    # Ключи, у которых ищется смена эталона: у температур её не бывает.
    CHAMBER_CHANNEL_KEYS = ("main", "media")

    # ------------------------------------------------------------------ состояние

    def _init_chamber_live_state(self):
        """Готовит живой опрос раздела. Вызывается один раз при создании контроллера."""
        self._chamber_live_read = ServiceReadDataById()
        # Для этого МК номер DID в запросе 0x22 всегда идёт в стандартном порядке.
        self._chamber_live_read.set_byte_order("big")
        self._chamber_live_reset()

        self._chamber_live_wanted = False
        self._chamber_window_s = float(self.CHAMBER_WINDOW_DEFAULT_S)

        # Ожидание среднего после нажатия «Записать точку».
        self._chamber_capture_waiting = False
        self._chamber_capture_wait_since = 0.0

        self._chamber_live_timer = QTimer(self)
        self._chamber_live_timer.setInterval(self.CHAMBER_LIVE_PERIOD_MS)
        self._chamber_live_timer.timeout.connect(self._on_chamber_live_tick)
        self._chamber_live_timer.start()

    def _chamber_live_reset(self):
        """Забывает все накопленные показания: новый прибор или новое подключение."""
        keys = [key for key, _var, _signed in self._chamber_vars()]
        self._chamber_live_last = {key: None for key in keys}
        self._chamber_live_seen = {key: 0.0 for key in keys}
        self._chamber_live_recent = {key: [] for key in keys}
        self._chamber_live_outliers = {key: [] for key in keys}
        self._chamber_live_restart_s = {key: 0.0 for key in keys}
        self._chamber_live_refusals = {}
        self._chamber_live_missing = set()
        self._chamber_live_pending = None
        self._chamber_live_pending_s = 0.0
        self._chamber_live_index = 0

    # ------------------------------------------------------------------ накопление

    def _chamber_live_note(self, key: str, value: int, now: float | None = None):
        """Кладёт показание в окно среднего и отслеживает смену эталона."""
        now = time.monotonic() if now is None else float(now)
        value = int(value)
        self._chamber_live_last[key] = value
        self._chamber_live_seen[key] = now

        window = float(self._chamber_window_s)
        recent = [(stamp, sample) for stamp, sample in self._chamber_live_recent.get(key, [])
                  if now - stamp <= window]

        if key in self.CHAMBER_CHANNEL_KEYS and len(recent) >= self.CHAMBER_MIN_SAMPLES:
            mean = sum(sample for _stamp, sample in recent) / float(len(recent))
            limit = max(float(self.CHAMBER_JUMP_MIN_COUNTS), abs(mean) / self.CHAMBER_JUMP_DIVISOR)
            if abs(value - mean) > limit:
                # Выброс в среднее не идёт. Несколько выбросов подряд - это новый эталон.
                outliers = [(stamp, sample) for stamp, sample in self._chamber_live_outliers.get(key, [])
                            if now - stamp <= window]
                outliers.append((now, value))
                if len(outliers) >= self.CHAMBER_JUMP_CONFIRM:
                    self._chamber_live_recent[key] = outliers
                    self._chamber_live_outliers[key] = []
                    self._chamber_live_restart_s[key] = now
                else:
                    self._chamber_live_recent[key] = recent
                    self._chamber_live_outliers[key] = outliers
                return
            self._chamber_live_outliers[key] = []

        recent.append((now, value))
        # Предел длины нужен только от разрастания при очень длинном окне.
        self._chamber_live_recent[key] = recent[-1000:]

    def _chamber_live_stats(self, key: str, now: float | None = None) -> dict | None:
        """Среднее, число показаний, разброс и охват окна по одной величине."""
        now = time.monotonic() if now is None else float(now)
        window = float(self._chamber_window_s)
        recent = [(stamp, sample) for stamp, sample in self._chamber_live_recent.get(key, [])
                  if now - stamp <= window]
        if not recent:
            return None
        samples = [sample for _stamp, sample in recent]
        return {
            "mean": sum(samples) / float(len(samples)),
            "count": len(samples),
            "spread": max(samples) - min(samples),
            "span_s": now - recent[0][0],
        }

    def _chamber_live_fresh(self, key: str, now: float) -> bool:
        """Есть ли у величины показание не старше нескольких секунд."""
        if self._chamber_live_last.get(key) is None:
            return False
        return now - float(self._chamber_live_seen.get(key, 0.0)) <= self.CHAMBER_LIVE_STALE_S

    def _chamber_live_point(self, now: float | None = None):
        """Собирает точку из средних. Возвращает (точка, пояснение) или (None, чего не хватает)."""
        now = time.monotonic() if now is None else float(now)

        main = self._chamber_live_stats("main", now)
        if main is None or main["count"] < self.CHAMBER_MIN_SAMPLES or not self._chamber_live_fresh("main", now):
            return None, "среднее основного контура ещё набирается"

        media = None
        if "media" not in self._chamber_live_missing:
            media = self._chamber_live_stats("media", now)
            if media is None or media["count"] < self.CHAMBER_MIN_SAMPLES or not self._chamber_live_fresh("media", now):
                return None, "среднее контура вида топлива ещё набирается"

        temps = {}
        for key in ("fuel_temp", "board_temp"):
            stats = self._chamber_live_stats(key, now)
            if stats is None or not self._chamber_live_fresh(key, now):
                return None, "прибор ещё не отдал температуру"
            temps[key] = stats

        point = {
            "main": int(round(main["mean"])),
            "media": None if media is None else int(round(media["mean"])),
            "fuel_temp_x10": int(round(temps["fuel_temp"]["mean"])),
            "board_temp_x10": int(round(temps["board_temp"]["mean"])),
        }
        detail = f"среднее за {_decimal(main['span_s'], 0)} с по {main['count']} показаниям, разброс {main['spread']}"
        if media is not None:
            detail += f" / {media['spread']}"

        # Тестовый режим на столе: к периодам добавляется заложенный уход платы.
        drift = getattr(self, "_chamber_test_apply_drift", None)
        if drift is not None:
            drifted = drift(point)
            if drifted is not point:
                point = drifted
                detail += ", с имитацией ухода"
        return point, detail

    # ------------------------------------------------------------------ точка по среднему

    def _chamber_capture_from_average(self) -> bool:
        """Кладёт в журнал текущие средние. Если их ещё нет, ждёт и записывает сама."""
        if self._chamber_busy or self._chamber_capture_waiting:
            return False

        if not str(self._chamber_label).strip():
            self.infoMessage.emit(
                "Прогон в камере",
                "Сначала напишите, что подключено к прибору. Без пометки точка бесполезна.",
            )
            return False

        if self._chamber_live_try_store():
            return True

        if not self._can.is_connect:
            self.infoMessage.emit("Прогон в камере", "Сначала подключите CAN-адаптер.")
            return False

        if not self._can.is_trace:
            self.infoMessage.emit("Прогон в камере", "Сначала включите трассировку CAN.")
            return False

        _point, reason = self._chamber_live_point()
        self._chamber_capture_waiting = True
        self._chamber_capture_wait_since = time.monotonic()
        self._chamber_set_status(
            f"Точка «{self._chamber_label}»: {reason}. Запишу сама, как только оно будет.", "#0f6ab4")
        return True

    def _chamber_live_try_store(self) -> bool:
        """Записывает точку по средним, если они уже годятся."""
        point, detail = self._chamber_live_point()
        if point is None:
            return False
        self._chamber_capture_waiting = False
        self._chamber_append_point(point, detail)
        return True

    def _chamber_live_check_waiting(self, now: float):
        """Продолжает ожидание среднего после нажатия кнопки."""
        if not self._chamber_capture_waiting:
            return
        if self._chamber_live_try_store():
            return
        if now - self._chamber_capture_wait_since > self.CHAMBER_WAIT_LIMIT_S:
            self._chamber_capture_waiting = False
            _point, reason = self._chamber_live_point(now)
            self._chamber_set_status(
                f"Точка не записана: за {int(self.CHAMBER_WAIT_LIMIT_S)} с {reason}. "
                "Проверьте связь с прибором и повторите.", "#dc2626")

    # ------------------------------------------------------------------ опрос

    def _chamber_live_set_enabled(self, enabled: bool):
        """Просьба раздела: опрашивать прибор, пока раздел открыт."""
        self._chamber_live_section = bool(enabled)
        self._chamber_live_apply_wanted()

    def _chamber_live_apply_wanted(self):
        """Опрос идёт, пока открыт раздел или пока включено наблюдение издалека.

        Наблюдению опрос нужен всегда: оператор у камеры может переключить окно
        на другой раздел, а страница и сообщения должны жить дальше.
        """
        value = bool(getattr(self, "_chamber_live_section", False))
        # Наблюдению и связи с камерой опрос нужен, даже когда раздел закрыт.
        for name in ("_remote_keeps_live", "_climate_keeps_live"):
            keeps = getattr(self, name, None)
            value = value or bool(keeps is not None and keeps())
        if value == self._chamber_live_wanted:
            return
        self._chamber_live_wanted = value
        if not value:
            self._chamber_live_pending = None
            if self._chamber_capture_waiting:
                # Без опроса среднее не наберётся, и ожидание висело бы до возвращения в раздел.
                self._chamber_capture_waiting = False
                self._chamber_set_status("Точка не записана: раздел закрыли, пока набиралось среднее.", "#d97706")
        self.chamberLiveChanged.emit()

    def _chamber_live_set_window(self, text: str) -> bool:
        """Меняет окно среднего. Накопленные показания при этом не теряются."""
        cleaned = str(text).strip().replace(",", ".")
        try:
            value = float(cleaned)
        except ValueError:
            self._chamber_set_status("Окно среднего задаётся числом секунд.", "#dc2626")
            return False
        if not (self.CHAMBER_WINDOW_MIN_S <= value <= self.CHAMBER_WINDOW_MAX_S):
            self._chamber_set_status(
                f"Окно среднего должно быть от {int(self.CHAMBER_WINDOW_MIN_S)} "
                f"до {int(self.CHAMBER_WINDOW_MAX_S)} с.", "#dc2626")
            return False
        self._chamber_window_s = value
        self.chamberLiveChanged.emit()
        return True

    def _chamber_live_next_request(self):
        """Следующая величина по кругу опроса, пропуская те, которых нет в прошивке."""
        variables = {key: (var, signed) for key, var, signed in self._chamber_vars()}
        for _attempt in range(len(self.CHAMBER_LIVE_ORDER)):
            key = self.CHAMBER_LIVE_ORDER[self._chamber_live_index % len(self.CHAMBER_LIVE_ORDER)]
            self._chamber_live_index += 1
            if key in self._chamber_live_missing or key not in variables:
                continue
            var, signed = variables[key]
            return key, var, signed
        return None

    def _on_chamber_live_tick(self):
        """Такт опроса: один запрос, если шина свободна, и обновление показа."""
        if not self._chamber_live_wanted:
            return
        now = time.monotonic()
        # Возраст показаний меняется и без ответов, поэтому показ обновляется каждый такт.
        self.chamberLiveChanged.emit()
        self._chamber_live_check_waiting(now)

        if not self._can.is_connect or not self._can.is_trace:
            return
        # Замер пробной калибровки ведёт свой обмен теми же запросами.
        if self._chamber_busy:
            return
        if self._chamber_live_pending is not None and now - self._chamber_live_pending_s < self.CHAMBER_LIVE_PENDING_S:
            return
        if uds_exchange_busy(self) or background_request_recent(self):
            return
        # Пока калибровка открывает сессию и доступ, лишние запросы на шину не нужны.
        if bool(getattr(self, "_calibration_active", False)) and not bool(getattr(self, "_calibration_session_ready", True)):
            return

        picked = self._chamber_live_next_request()
        if picked is None:
            return
        self._chamber_live_pending = picked
        self._chamber_live_pending_s = now
        note_background_request(self)
        try:
            self._chamber_live_read.read_data_by_identifier(self._build_calibration_tx_identifier(), picked[1])
        except Exception:
            self._chamber_live_pending = None

    @staticmethod
    def _chamber_live_decode(data, var, signed: bool) -> int:
        """Число из байтов ответа, младший байт первым."""
        size = max(1, int(var.size))
        raw = 0
        for shift, byte_value in enumerate(list(data)[:size]):
            raw |= (int(byte_value) & 0xFF) << (8 * shift)
        if not signed:
            return int(raw)
        limit = 1 << (size * 8)
        return int(raw - limit if raw >= (limit >> 1) else raw)

    def _handle_chamber_live_frame(self, identifier: int, payload):
        """Подхватывает показания точки из любого ответа прибора, кто бы их ни запросил."""
        if not self._chamber_live_wanted:
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
            pending = self._chamber_live_pending
            # Отказ на чтение сразу после своего запроса: скорее всего параметра нет в прошивке.
            if body[1] != 0x22 or pending is None or now - self._chamber_live_pending_s > self.CHAMBER_LIVE_PENDING_S:
                return
            if len(body) > 2 and body[2] == 0x78:
                return
            self._chamber_live_pending = None
            key = pending[0]
            count = self._chamber_live_refusals.get(key, 0) + 1
            self._chamber_live_refusals[key] = count
            if count >= self.CHAMBER_LIVE_REFUSAL_LIMIT:
                self._chamber_live_missing.add(key)
            return

        if body[0] != 0x62 or length < 4:
            return

        answered = {(body[1] << 8) | body[2], (body[2] << 8) | body[1]}
        for key, var, signed in self._chamber_vars():
            if (int(var.pid) & 0xFFFF) not in answered:
                continue
            self._chamber_live_note(key, self._chamber_live_decode(body[3:], var, signed), now)
            self._chamber_live_refusals.pop(key, None)
            if self._chamber_live_pending is not None and self._chamber_live_pending[0] == key:
                self._chamber_live_pending = None
            self.chamberLiveChanged.emit()
            return

    # ------------------------------------------------------------------ показ

    def _chamber_live_view(self) -> dict:
        """Живые показания для окна: текущее, среднее и пояснение по каждой величине."""
        now = time.monotonic()
        connected = bool(self._can.is_connect) and bool(self._can.is_trace)

        def channel(key: str) -> dict:
            if key in self._chamber_live_missing:
                return {"now": "нет", "avg": "нет", "info": "в этой прошивке контур не отдаётся", "ok": False}
            last = self._chamber_live_last.get(key)
            fresh = self._chamber_live_fresh(key, now)
            stats = self._chamber_live_stats(key, now)
            now_text = "—" if last is None else str(int(last))
            if stats is None or stats["count"] < 2:
                return {"now": now_text, "avg": "—", "info": "среднее набирается", "ok": False}
            info = f"показаний {stats['count']} · разброс {stats['spread']}"
            restarted = now - float(self._chamber_live_restart_s.get(key, 0.0)) <= float(self._chamber_window_s)
            if restarted:
                info += " · окно начато заново"
            return {
                "now": now_text,
                "avg": str(int(round(stats["mean"]))),
                "info": info if fresh else "показание устарело",
                "ok": fresh and stats["count"] >= self.CHAMBER_MIN_SAMPLES,
            }

        def temperature(key: str) -> dict:
            last = self._chamber_live_last.get(key)
            stats = self._chamber_live_stats(key, now)
            return {
                "now": "—" if last is None else f"{_decimal(int(last) / 10.0, 1)} °C",
                "avg": "—" if stats is None else f"{_decimal(stats['mean'] / 10.0, 1)} °C",
                "ok": self._chamber_live_fresh(key, now),
            }

        main_view = channel("main")
        media_view = channel("media")

        seen = [float(stamp) for stamp in self._chamber_live_seen.values() if stamp > 0.0]
        if not connected:
            fresh_text = "Нет связи: подключите адаптер и включите трассировку"
            fresh_ok = False
        elif not seen:
            fresh_text = "Жду первый ответ прибора..."
            fresh_ok = False
        else:
            age = now - max(seen)
            fresh_ok = age <= self.CHAMBER_LIVE_STALE_S
            fresh_text = (f"Последний ответ {_decimal(age, 1)} с назад" if fresh_ok
                          else f"Прибор молчит уже {int(age)} с")

        point, _detail = self._chamber_live_point(now)
        # С имитацией ухода в точку идёт не то, что показывает прибор: оператор видит оба числа.
        drift_on = bool(getattr(self, "_chamber_test_drift_active", lambda: False)())
        if drift_on and point is not None:
            main_view = dict(main_view)
            main_view["info"] = f"в точку с имитацией ухода: {point['main']}"
            if point.get("media") is not None:
                media_view = dict(media_view)
                media_view["info"] = f"в точку с имитацией ухода: {point['media']}"
        return {
            "enabled": bool(self._chamber_live_wanted),
            "main": main_view,
            "media": media_view,
            "fuelTemp": temperature("fuel_temp"),
            "boardTemp": temperature("board_temp"),
            "windowText": _decimal(float(self._chamber_window_s), 0),
            "freshText": fresh_text,
            "freshOk": fresh_ok,
            "ready": point is not None,
            "waiting": bool(self._chamber_capture_waiting),
        }
