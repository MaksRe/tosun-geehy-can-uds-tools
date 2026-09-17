"""Пробная калибровка на столе: весь порядок работы до выезда в камеру.

ЗАЧЕМ
Выезд в климатическую камеру стоит дорого и не переделывается. Если что-то в
программе или в приборе отработает неверно, это выяснится только на месте. Здесь
тот же порядок проходится на столе: плата подключена к шине, на каждом контуре
висит по одному постоянному конденсатору, а температуру прибору задаёт эмуляция в
самой прошивке.

КАК ЗАПУСКАЕТСЯ
Каждый этап можно выполнить отдельно, а можно все подряд одной кнопкой. При
автоматическом прогоне этапы идут по порядку. Если этап не пройден после того,
как настройки прибора запомнены, программа сразу возвращает их и
останавливается: прибор не остаётся с пробной калибровкой.

ПОЧЕМУ ХВАТАЕТ ОДНОГО КОНДЕНСАТОРА НА КОНТУР
Отметки бака и точки вида топлива программа ставит сама вокруг показания того
конденсатора, что уже подключён, и так, чтобы прибор обязан был выдать заранее
известный результат: уровень 25 % и коэффициент среды 1,100.

Таблицы температурного профиля по одной ёмкости посчитать нельзя: сдвиг и
растяжение показания по одной точке неразличимы. Поэтому их запись и применение
проверяются на проверочном профиле с заранее известными поправками.

ЖУРНАЛ И ОТСЧЁТЫ
Каждый этап пишет в журнал, что он делает и зачем, какие числа получил и чем
закончился. Отсчёты обоих контуров показываются постоянно. Пока идёт проверка,
их чтение подмешивается в очередь этапа только на границах его замеров, чтобы не
разорвать серию и не сбить сверку.

КАК УСТРОЕН ОБМЕН
Каждый этап это очередь простых операций: прочитать, записать, подождать,
вызвать другой раздел и дождаться его. Ответы разбираются здесь же, по номеру
параметра. Итог этапа решает отдельный обработчик, когда очередь закончилась.
"""

from __future__ import annotations

import json
import pathlib
import time
from datetime import datetime

from PySide6.QtCore import QTimer

import chamber_fit
import profile_model
from app_can.CanDevice import CanDevice
from uds.data_identifiers import UdsData, UdsVar
from uds.services.read_data_by_id import ServiceReadDataById
from uds.services.write_data_by_id import ServiceWriteDataById

from .bus_guard import background_request_recent, note_background_request, uds_exchange_busy
from .contract import AppControllerContract
from .eeprom_commit_mixin import EEPROM_FLAG_SPI_ERROR, decode_eeprom_state, eeprom_boot_warning

# На шине «эмуляция выключена» передаётся как 0x8000, а читается как -32768.
TRIAL_EMULATION_OFF_WIRE = 0x8000
TRIAL_EMULATION_OFF_VALUE = -32768

# Параметры, которых нет среди готовых имён каталога. Номера те же, что в прошивке.
VAR_LEGACY_K1 = UdsVar(0x001B, 2, "Прежний K1, в новой прошивке отсутствует")
VAR_FREEZE_PCT = UdsVar(0x0034, 1, "Порог заморозки коэффициента среды, %")
VAR_TANK_MODEL = UdsVar(0x0053, 1, "Модель уровня")
VAR_ALGORITHM = UdsVar(0x005C, 2, "Алгоритм измерения")
VAR_GENERATION = UdsVar(0x005D, 2, "Поколение профиля")
VAR_CRC = UdsVar(0x005E, 2, "Сумма профиля")
# Есть и в основной программе (ответ 0), и в загрузчике (ответ 1): по нему видно, кто отвечает.
VAR_ACTIVE_PROGRAM = UdsVar(0x001A, 1, "Тип активной программы: 0 основная, 1 загрузчик")


class AppControllerTrialMixin(AppControllerContract):
    TRIAL_REQUEST_GAP_MS = 40
    TRIAL_TIMEOUT_MS = 800
    # После смены эмулируемой температуры: прибор пересчитывает цепочку раз в 50 мс.
    TRIAL_SETTLE_MS = 400
    # Первый взгляд после команды перезапуска: загрузчик ждёт 1 с, затем стартует основная программа.
    TRIAL_RESET_WAIT_MS = 1500
    # Сколько ждать возвращения прибора в основную программу и как часто спрашивать.
    TRIAL_REBOOT_TIMEOUT_S = 15.0
    TRIAL_REBOOT_POLL_MS = 300
    TRIAL_SAMPLES = 5
    TRIAL_PERIOD_TOLERANCE = 3
    TRIAL_LEVEL_TOLERANCE_PERMILLE = 30
    TRIAL_RF_TOLERANCE_X1000 = 15
    TRIAL_RF_TIMEOUT_MS = 30000
    TRIAL_PROFILE_TIMEOUT_MS = 30000
    TRIAL_CHAMBER_TIMEOUT_MS = 15000
    TRIAL_ACCESS_TIMEOUT_MS = 20000
    # Сколько ждать, пока прибор перенесёт принятые значения в микросхему памяти.
    TRIAL_COMMIT_TIMEOUT_S = 5.0
    TRIAL_COMMIT_POLL_MS = 150
    # Пауза между этапами автоматического прогона: итог успевает отобразиться.
    TRIAL_AUTO_PAUSE_MS = 400

    # Отметки бака ставятся вокруг показания конденсатора несимметрично, чтобы
    # перепутанные местами отметки дали другой уровень: 25 % против 75 %.
    # Уровень обязан быть выше порога заморозки вида топлива, иначе прибор не
    # обновляет коэффициент среды и следующий этап проверить нельзя. Поэтому
    # берётся первый уровень из списка, который выше порога с запасом.
    TRIAL_LEVEL_SPAN = 4000
    TRIAL_LEVEL_TARGETS_PERMILLE = (250, 750, 900)
    TRIAL_LEVEL_FREEZE_MARGIN_PERMILLE = 50
    TRIAL_LEVEL_EXPECTED_PERMILLE = 250

    # Точки вида топлива ставятся так, чтобы коэффициент среды стал 1,100, а не
    # единицей: единица совпадает с нейтральным значением, и по ней не видно,
    # считает ли прибор коэффициент на самом деле.
    TRIAL_MEDIA_SPAN = 1000
    TRIAL_MEDIA_TARGET_X1000 = 1100

    # Пометка точек, снятых на столе, и допустимый разброс одного конденсатора.
    TRIAL_CHAMBER_LABEL = "проба на столе"
    TRIAL_CHAMBER_SPREAD_LIMIT = 20

    # Температуры проверки применения: все узлы и точки между ними.
    TRIAL_APPLY_TEMPS_X10 = (-400, -300, -200, 0, 125, 250, 375, 500, 700, 850)

    # Постоянный показ отсчётов: что читается, как часто и когда данные считаются несвежими.
    TRIAL_LIVE_VARS = (
        ("main_raw", UdsData.curr_fuel_tank, False),
        ("main_comp", UdsData.fuel_compensated_period, False),
        ("media", UdsData.fuel_media_flatcap_raw, False),
        ("fuel_t", UdsData.raw_temperature, True),
        ("board_t", UdsData.raw_board_temperature, True),
        ("emul", UdsData.temperature_emulation_x10, True),
    )
    TRIAL_LIVE_PERIOD_MS = 200
    TRIAL_LIVE_GUARD_MS = 150
    TRIAL_LIVE_STALE_S = 3.0
    TRIAL_LIVE_INJECT_S = 1.0
    TRIAL_LOG_LIMIT = 600

    COLOR_IDLE = "#64748b"
    COLOR_RUN = "#0f6ab4"
    COLOR_OK = "#16a34a"
    COLOR_WARN = "#d97706"
    COLOR_FAIL = "#dc2626"

    TRIAL_STEPS = (
        ("link", "Прибор на связи, прошивка новая",
         "Только читает. Убеждается, что прибор отвечает, в нём есть эмуляция температуры и контроль "
         "записи в память, нет прежней компенсации K1, а память при включении не сбрасывалась."),
        ("backup", "Запомнить текущие настройки",
         "Читает отметки бака, подгонку нуля, точки вида топлива и профиль и сохраняет копию в файл. "
         "В конце пробной калибровки всё это вернётся в прибор."),
        ("access", "Открыть запись в прибор",
         "Если калибровка не запущена, запускает её, как кнопка «Начать калибровку», и ждёт, пока "
         "прибор откроет доступ на запись."),
        ("emulation", "Эмуляция температуры работает",
         "Задаёт прибору -40 °C, затем +85 °C. Оба датчика обязаны показать ровно это, после чего "
         "эмуляция выключается."),
        ("level", "Отметки бака записываются и применяются",
         "Ставит отметки 0 % и 100 % вокруг показания конденсатора на основном контуре так, что "
         "уровень обязан стать заранее известным: 25 %, а если порог заморозки вида топлива выше, "
         "то 75 или 90 %."),
        ("media", "Вид топлива записывается и применяется",
         "Ставит точки «воздух» и «топливо» вокруг показания конденсатора на контуре вида топлива так, "
         "что коэффициент среды обязан стать 1,100. Идёт после отметок бака: пока уровень ниже порога "
         "заморозки, коэффициент среды не обновляется."),
        ("chamber", "Снятие точек с эмуляцией температуры",
         "Задаёт прибору все семь температур сетки и снимает точку при каждой. Каждая точка обязана "
         "попасть в свой узел, а показание одного и того же конденсатора не должно гулять."),
        ("profile", "Профиль записывается без потерь",
         "Пишет проверочный профиль с крупными поправками и читает его обратно. Таблицы по одному "
         "конденсатору не посчитать: для этого нужны две разные ёмкости."),
        ("apply", "Прибор применяет таблицы правильно",
         "При десяти температурах сверяет период после ступени платы и итоговый период прибора с "
         "расчётом по формулам прошивки."),
        ("restore", "Вернуть как было",
         "Записывает обратно то, что пробная калибровка поменяла, и сверяет все запомненные настройки. "
         "Эмуляция выключается."),
        ("persist", "Всё сохраняется после перезагрузки",
         "Перезапускает прибор и читает записанное заново. Эмуляция после перезапуска обязана быть "
         "выключена. После этого калибровку нужно запустить снова."),
    )

    STATUS_WORDS = {
        "pending": ("не проверено", "#64748b"),
        "running": ("идёт проверка", "#0f6ab4"),
        "pass": ("пройдено", "#16a34a"),
        "warn": ("есть замечания", "#d97706"),
        "fail": ("не пройдено", "#dc2626"),
        "skip": ("пропущено", "#94a3b8"),
    }
    FINAL_STATUSES = ("pass", "warn", "fail", "skip")

    # ------------------------------------------------------------------ состояние

    def _init_trial_state(self):
        """Готовит раздел пробной калибровки. Вызывается один раз при создании контроллера."""
        self._trial_read = ServiceReadDataById()
        self._trial_read.set_byte_order("big")
        self._trial_write = ServiceWriteDataById()
        self._trial_write.set_byte_order("big")

        self._trial_steps_state = {key: {"status": "pending", "detail": "", "duration": None}
                                   for key, _t, _h in self.TRIAL_STEPS}
        self._trial_step_started_s: dict[str, float] = {}
        self._trial_busy = False
        self._trial_status = "Пробная калибровка не запускалась."
        self._trial_status_color = self.COLOR_IDLE
        self._trial_log: list[dict] = []

        self._trial_ops: list[dict] = []
        self._trial_pending: dict | None = None
        self._trial_results: dict = {}
        self._trial_done_handler: str | None = None

        self._trial_backup: dict | None = None
        self._trial_expected: dict = {}
        self._trial_level_reading: dict | None = None
        self._trial_media_points: dict | None = None
        self._trial_rf_deadline = 0.0

        self._trial_chamber_plan: list[int] = []
        self._trial_chamber_index = 0
        self._trial_chamber_outcome: tuple[str, str] | None = None
        self._trial_applied_profile: dict | None = None
        # Что пробная калибровка успела поменять в приборе: при возврате пишется только это.
        self._trial_dirty: set[str] = set()
        # Обязан ли прибор после перезапуска держать профиль в работе.
        self._trial_expect_trusted = False
        # Итог этапа, который объявится после записи в микросхему памяти.
        self._trial_commit_ctx: dict | None = None
        # Счётчик ошибок записи памяти на момент последней проверки.
        self._trial_ee_errors: int | None = None
        # Ход ожидания прибора после перезапуска.
        self._trial_reboot: dict | None = None

        self._trial_auto_active = False
        self._trial_auto_queue: list[str] = []
        self._trial_auto_current: str | None = None
        self._trial_auto_last: tuple[str, str] | None = None
        self._trial_auto_stop_requested = False
        self._trial_auto_backup_ok = False
        self._trial_auto_failed = False

        self._trial_live: dict = {key: None for key, _var, _signed in self.TRIAL_LIVE_VARS}
        self._trial_live_seen: dict = {key: 0.0 for key, _var, _signed in self.TRIAL_LIVE_VARS}
        self._trial_live_enabled = False
        self._trial_live_index = 0
        self._trial_live_last_inject = 0.0
        self._trial_live_last_poll = 0.0
        self._trial_live_suspend_until = 0.0

        self._trial_gap_timer = QTimer(self)
        self._trial_gap_timer.setSingleShot(True)
        self._trial_gap_timer.timeout.connect(self._trial_next_op)

        self._trial_wait_timer = QTimer(self)
        self._trial_wait_timer.setSingleShot(True)
        self._trial_wait_timer.timeout.connect(self._trial_next_op)

        self._trial_timeout_timer = QTimer(self)
        self._trial_timeout_timer.setSingleShot(True)
        self._trial_timeout_timer.timeout.connect(self._on_trial_timeout)

        self._trial_poll_timer = QTimer(self)
        self._trial_poll_timer.setSingleShot(True)
        self._trial_poll_timer.timeout.connect(self._on_trial_poll)

        self._trial_auto_timer = QTimer(self)
        self._trial_auto_timer.setSingleShot(True)
        self._trial_auto_timer.timeout.connect(self._on_trial_auto_timer)

        self._trial_live_timer = QTimer(self)
        self._trial_live_timer.setInterval(self.TRIAL_LIVE_PERIOD_MS)
        self._trial_live_timer.timeout.connect(self._on_trial_live_tick)
        self._trial_live_timer.start()

    # ------------------------------------------------------------------ операции очереди

    @staticmethod
    def _op_read(key: str, var, signed: bool = False) -> dict:
        return {"kind": "read", "key": key, "var": var, "signed": bool(signed)}

    @staticmethod
    def _op_write(key: str, var, value: int) -> dict:
        return {"kind": "write", "key": key, "var": var, "value": int(value)}

    @staticmethod
    def _op_wait(ms: int) -> dict:
        return {"kind": "wait", "key": "", "ms": int(ms)}

    @staticmethod
    def _op_call(key: str, fn: str) -> dict:
        return {"kind": "call", "key": key, "fn": fn}

    @staticmethod
    def _op_await(kind: str, key: str, ms: int) -> dict:
        return {"kind": kind, "key": key, "ms": int(ms)}

    @staticmethod
    def _op_reset(key: str) -> dict:
        return {"kind": "reset", "key": key}

    def _trial_emulation_op(self, key: str, temperature_x10) -> dict:
        """Операция записи эмуляции. None означает «выключить»."""
        value = TRIAL_EMULATION_OFF_WIRE if temperature_x10 is None else int(temperature_x10)
        return self._op_write(key, UdsData.temperature_emulation_x10, value)

    # ------------------------------------------------------------------ исполнение очереди

    def _trial_start_ops(self, ops, done_handler: str) -> bool:
        """Запускает очередь. По её окончании вызывается обработчик с результатами."""
        if self._trial_busy:
            return False
        if not self._can.is_connect:
            self.infoMessage.emit("Пробная калибровка", "Сначала подключите CAN-адаптер.")
            return False
        if not self._can.is_trace:
            self.infoMessage.emit("Пробная калибровка", "Сначала включите трассировку CAN.")
            return False

        self._trial_ops = list(ops)
        self._trial_results = {}
        self._trial_done_handler = done_handler
        self._trial_pending = None
        self._trial_busy = True
        self.trialChanged.emit()
        # Ответ на только что отправленный опрос отсчётов ещё в пути. Отказ старой
        # прошивки на него этап принял бы за ответ на свой запрос, поэтому пауза.
        last_background = max(float(self._trial_live_last_poll), float(getattr(self, "_uds_background_tx_s", 0.0) or 0.0))
        if time.monotonic() - last_background < self.TRIAL_LIVE_GUARD_MS / 1000.0:
            self._trial_gap_timer.start(self.TRIAL_LIVE_GUARD_MS)
        else:
            self._trial_next_op()
        return True

    def _trial_inject_live_reads(self):
        """Подмешивает чтение отсчётов в очередь этапа, если они давно не обновлялись.

        Только перед записью или паузой: это границы замеров этапа. Перед
        чтением подмешивать нельзя, иначе между сырым и итоговым периодом
        вклинится лишний запрос и сверка применения станет менее точной.
        """
        if not self._trial_live_enabled or not self._trial_ops:
            return
        if self._trial_ops[0]["kind"] not in ("write", "wait"):
            return
        now = time.monotonic()
        if now < self._trial_live_suspend_until or now - self._trial_live_last_inject < self.TRIAL_LIVE_INJECT_S:
            return
        self._trial_live_last_inject = now
        reads = [self._op_read(f"_live_{key}", var, signed) for key, var, signed in self.TRIAL_LIVE_VARS[:3]]
        self._trial_ops[0:0] = reads

    def _trial_next_op(self):
        """Берёт следующую операцию очереди. Пустая очередь передаёт итог обработчику."""
        if not self._trial_busy:
            return

        if not self._trial_ops:
            self._trial_busy = False
            self._trial_pending = None
            handler = self._trial_done_handler
            self._trial_done_handler = None
            results = dict(self._trial_results)
            self.trialChanged.emit()
            if handler:
                getattr(self, handler)(results)
            return

        self._trial_inject_live_reads()
        op = self._trial_ops.pop(0)
        kind = op["kind"]

        if kind == "wait":
            self._trial_wait_timer.start(max(1, int(op["ms"])))
            return

        if kind == "call":
            getattr(self, op["fn"])()
            self._trial_gap_timer.start(self.TRIAL_REQUEST_GAP_MS)
            return

        if kind == "reset":
            # Программный сброс основного ПО, как кнопка в окне прошивки, но в выбранный узел.
            try:
                CanDevice.instance().send_async(
                    self._build_calibration_tx_identifier(), 8,
                    [0x02, 0x11, 0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
                self._trial_results[op["key"]] = True
            except Exception as error:
                self._trial_results[op["key"]] = ("error", str(error))
            # Пока прибор перезапускается, отсчёты не опрашиваются: запросы ушли бы в пустоту.
            self._trial_live_suspend_until = time.monotonic() + (self.TRIAL_RESET_WAIT_MS + 500) / 1000.0
            self._trial_wait_timer.start(self.TRIAL_RESET_WAIT_MS)
            return

        if kind in ("await_profile", "await_chamber", "await_write_ready"):
            op["deadline"] = time.monotonic() + op["ms"] / 1000.0
            self._trial_pending = op
            self._trial_poll_timer.start(100)
            return

        self._trial_pending = op
        try:
            if kind == "read":
                sent = self._trial_read.read_data_by_identifier(self._build_calibration_tx_identifier(), op["var"])
            else:
                mask = (1 << (8 * int(op["var"].size))) - 1
                sent = self._trial_write.write_data(
                    op["var"], int(op["value"]) & mask, tx_identifier=self._build_calibration_tx_identifier())
        except Exception:
            sent = False

        if not sent:
            self._trial_pending = None
            self._trial_results[op["key"]] = ("error", "запрос не отправлен")
            self._trial_gap_timer.start(self.TRIAL_REQUEST_GAP_MS)
            return

        self._trial_timeout_timer.start(self.TRIAL_TIMEOUT_MS)

    def _trial_finish_op(self, value):
        """Записывает результат текущей операции и переходит к следующей."""
        op = self._trial_pending
        self._trial_pending = None
        self._trial_timeout_timer.stop()
        if op is not None:
            self._trial_results[op["key"]] = value
        self._trial_gap_timer.start(self.TRIAL_REQUEST_GAP_MS)

    def _on_trial_timeout(self):
        op = self._trial_pending
        if (not self._trial_busy) or op is None or op["kind"] not in ("read", "write"):
            return
        self._trial_finish_op(("timeout",))

    def _on_trial_poll(self):
        """Ждёт, пока другой раздел закончит свою работу или откроется доступ на запись."""
        op = self._trial_pending
        if (not self._trial_busy) or op is None:
            return
        if op["kind"] == "await_profile":
            waiting = bool(self._profile_busy)
        elif op["kind"] == "await_chamber":
            waiting = bool(self._chamber_busy)
        elif op["kind"] == "await_write_ready":
            waiting = not self._trial_write_ready()
        else:
            return

        if not waiting:
            self._trial_finish_op(True)
            return
        if time.monotonic() > op["deadline"]:
            self._trial_finish_op(("timeout",))
            return
        self._trial_poll_timer.start(100)

    def _handle_trial_frame(self, identifier: int, payload):
        """Разбирает ответ прибора на операцию пробной калибровки."""
        op = self._trial_pending
        if (not self._trial_busy) or op is None or op["kind"] not in ("read", "write"):
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
        did = int(op["var"].pid) & 0xFFFF

        if body[0] == 0x7F:
            expected_sid = 0x22 if op["kind"] == "read" else 0x2E
            if len(body) > 1 and body[1] != expected_sid:
                return
            self._trial_finish_op(("nrc", body[2] if len(body) > 2 else 0))
            return

        answered = ((body[1] << 8) | body[2], (body[2] << 8) | body[1])

        if op["kind"] == "read":
            if body[0] != 0x62 or len(body) < 4 or did not in answered:
                return
            self._trial_finish_op(self._trial_decode(body[3:], op["var"], op["signed"]))
            return

        if body[0] != 0x6E or did not in answered:
            return
        self._trial_finish_op(True)

    @staticmethod
    def _trial_decode(data, var, signed: bool) -> int:
        """Собирает число из байтов ответа, младший байт первым."""
        raw = 0
        shift = 0
        for byte_value in list(data)[:max(1, int(var.size))]:
            raw |= int(byte_value) << shift
            shift += 8
        if not signed:
            return int(raw)
        bits = max(8, int(var.size) * 8)
        limit = 1 << bits
        raw &= limit - 1
        return int(raw - limit if raw >= (limit >> 1) else raw)

    # ------------------------------------------------------------------ постоянный показ отсчётов

    def _handle_trial_live_frame(self, identifier: int, payload):
        """Подхватывает отсчёты из любого ответа прибора, кто бы их ни запросил.

        Отсчёты читают и этапы проверки, и прогон, и калибровка. Разбирая все
        ответы, показ обновляется даже тогда, когда шина занята другим разделом.
        """
        if not self._trial_live_enabled:
            return
        if not isinstance(payload, (list, tuple)) or len(payload) < 5:
            return
        if not self._is_calibration_response_identifier(identifier):
            return
        if ((int(payload[0]) >> 4) & 0x0F) != 0x00:
            return
        length = int(payload[0]) & 0x0F
        if length < 4 or length > (len(payload) - 1):
            return
        body = [int(value) & 0xFF for value in payload[1:1 + length]]
        if body[0] != 0x62:
            return

        answered = {(body[1] << 8) | body[2], (body[2] << 8) | body[1]}
        for key, var, signed in self.TRIAL_LIVE_VARS:
            if (int(var.pid) & 0xFFFF) in answered:
                self._trial_live[key] = self._trial_decode(body[3:], var, signed)
                self._trial_live_seen[key] = time.monotonic()
                # Те же отсчёты, что в разделах калибровки: свежесть у них общая.
                if key == "main_raw":
                    self._live_note_value("level", self._trial_live[key])
                elif key == "media":
                    self._live_note_value("flatcap", self._trial_live[key])
                self.trialLiveChanged.emit()
                return

    def _on_trial_live_tick(self):
        """Опрашивает отсчёты по кругу, пока шину не занимает никто другой."""
        if not self._trial_live_enabled:
            return
        # Возраст данных меняется и без новых ответов, поэтому показ обновляется каждый такт.
        self.trialLiveChanged.emit()

        if not self._can.is_connect or not self._can.is_trace:
            return
        if uds_exchange_busy(self) or background_request_recent(self):
            return
        # Пока калибровка открывает сессию и доступ, лишние запросы на шину не нужны.
        if bool(self._calibration_active) and not bool(self._calibration_session_ready):
            return
        if time.monotonic() < self._trial_live_suspend_until:
            return

        if self._live_age_due("trial"):
            # Сырой период застывает вместе с контуром: раз за круг спрашиваем возраст измерения.
            var = UdsData.measurement_age
            self._live_age_note_request()
        else:
            _key, var, _signed = self.TRIAL_LIVE_VARS[self._trial_live_index]
            self._trial_live_index = (self._trial_live_index + 1) % len(self.TRIAL_LIVE_VARS)
        self._trial_live_last_poll = time.monotonic()
        note_background_request(self)
        try:
            self._trial_read.read_data_by_identifier(self._build_calibration_tx_identifier(), var)
        except Exception:
            pass

    def _trial_set_live_enabled(self, enabled: bool):
        value = bool(enabled)
        if value == self._trial_live_enabled:
            return
        self._trial_live_enabled = value
        self.trialLiveChanged.emit()

    def _trial_live_view(self) -> dict:
        """Готовит отсчёты для показа: числа, свежесть и состояние эмуляции."""
        now = time.monotonic()

        def fresh(key):
            return self._trial_live[key] is not None and (now - self._trial_live_seen[key]) <= self.TRIAL_LIVE_STALE_S

        def number(key):
            value = self._trial_live[key]
            return "—" if value is None else str(int(value))

        def temperature(key):
            value = self._trial_live[key]
            return "—" if value is None else f"{int(value) / 10:+.1f} °C"

        emul = self._trial_live["emul"]
        emulation_on = emul is not None and emul != TRIAL_EMULATION_OFF_VALUE
        if emul is None:
            emulation_text = "нет данных"
        elif emulation_on:
            emulation_text = f"включена, {int(emul) / 10:+.1f} °C"
        else:
            emulation_text = "выключена"

        # Каждый отсчёт спрашивается раз за круг: шесть отсчётов и возраст измерения.
        live_round_s = self.TRIAL_LIVE_PERIOD_MS * (len(self.TRIAL_LIVE_VARS) + 1) / 1000.0

        seen = [self._trial_live_seen[key] for key in ("main_raw", "media") if self._trial_live[key] is not None]
        if not self._trial_live_enabled:
            age_text = "опрос выключен"
        elif not seen:
            age_text = "ждём первых ответов прибора"
        else:
            age = now - max(seen)
            age_text = f"обновлено {age:.1f} с назад".replace(".", ",")

        return {
            "mainRaw": number("main_raw"),
            "mainComp": number("main_comp"),
            "media": number("media"),
            "mainFresh": fresh("main_raw"),
            "mediaFresh": fresh("media"),
            "fuelTemp": temperature("fuel_t"),
            "boardTemp": temperature("board_t"),
            "emulation": emulation_text,
            "emulationOn": emulation_on,
            "age": age_text,
            "enabled": self._trial_live_enabled,
            # Приходят ли ответы и мерит ли контур сам: застывшее число без этого не понять.
            "mainFreshness": self._live_freshness_view("level", live_round_s),
            "mediaFreshness": self._live_freshness_view("flatcap", live_round_s),
        }

    # ------------------------------------------------------------------ разбор результатов

    @staticmethod
    def _trial_value(results: dict, key: str):
        """Число из результата либо None, если вместо числа отказ или молчание."""
        value = results.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return int(value)

    @staticmethod
    def _trial_error_text(results: dict, key: str) -> str:
        """Объясняет простыми словами, почему операция не удалась."""
        value = results.get(key)
        if value is None:
            return "нет ответа"
        if isinstance(value, tuple):
            if value[0] == "nrc":
                code = int(value[1])
                reason = {
                    0x33: "нет доступа на запись, запустите калибровку",
                    0x22: "условия не выполнены",
                    0x31: "параметр вне диапазона или отсутствует в прошивке",
                    0x13: "неверная длина данных",
                }.get(code, "")
                return f"прибор отказал, код 0x{code:02X}" + (f" ({reason})" if reason else "")
            if value[0] == "timeout":
                return "прибор не ответил"
            return str(value[-1])
        return str(value)

    def _trial_mean(self, results: dict, prefix: str, count: int):
        values = [self._trial_value(results, f"{prefix}{index}") for index in range(count)]
        values = [value for value in values if value is not None]
        if not values:
            return None
        return int(round(sum(values) / float(len(values))))

    @staticmethod
    def _trial_temp_text(value_x10) -> str:
        return "нет данных" if value_x10 is None else f"{int(value_x10) / 10:+.1f} °C"

    # ------------------------------------------------------------------ журнал и состояние этапов

    def _trial_title(self, key: str) -> str:
        for step_key, title, _hint in self.TRIAL_STEPS:
            if step_key == key:
                return title
        return key

    def _trial_hint(self, key: str) -> str:
        for step_key, _title, hint in self.TRIAL_STEPS:
            if step_key == key:
                return hint
        return ""

    def _trial_log_add(self, level: str, text: str):
        """Добавляет строку журнала. Уровень задаёт цвет: step, info, ok, warn, fail, detail."""
        stamp = datetime.now().strftime("%H:%M:%S")
        lines = str(text).splitlines() or [""]
        for index, line in enumerate(lines):
            self._trial_log.append({"time": stamp if index == 0 else "",
                                    "level": level if index == 0 else "detail",
                                    "text": line})
        if len(self._trial_log) > self.TRIAL_LOG_LIMIT:
            self._trial_log = self._trial_log[-self.TRIAL_LOG_LIMIT:]

    def _trial_clear_log(self):
        self._trial_log = []
        self.trialChanged.emit()

    def _trial_set_step(self, key: str, status: str, detail: str):
        """Записывает итог этапа, строку хода работы и строки журнала."""
        started = self._trial_step_started_s.pop(key, None) if status in self.FINAL_STATUSES else None
        previous = self._trial_steps_state.get(key, {})
        duration = (time.monotonic() - started) if started is not None else previous.get("duration")
        self._trial_steps_state[key] = {"status": status, "detail": str(detail), "duration": duration}

        word, color = self.STATUS_WORDS.get(status, self.STATUS_WORDS["pending"])
        title = self._trial_title(key)
        self._trial_status = f"{title}: {word}."
        self._trial_status_color = color

        level = {"pass": "ok", "warn": "warn", "fail": "fail", "skip": "info"}.get(status, "info")
        lines = str(detail).splitlines()
        head = f"{title}: {word}." + (f" {lines[0]}" if lines else "")
        self._trial_log_add(level, "\n".join([head] + lines[1:]))
        self.trialChanged.emit()

        if status in self.FINAL_STATUSES:
            self._trial_auto_on_step_final(key, status)

    def _trial_mark_running(self, key: str, text: str):
        previous = self._trial_steps_state.get(key, {})
        self._trial_steps_state[key] = {"status": "running", "detail": str(text), "duration": previous.get("duration")}
        self._trial_step_started_s.setdefault(key, time.monotonic())
        self._trial_status = str(text)
        self._trial_status_color = self.COLOR_RUN
        self._trial_log_add("info", text)
        self.trialChanged.emit()

    def _trial_write_ready(self) -> bool:
        """Открыт ли доступ на запись в выбранный прибор."""
        if not (bool(self._calibration_active) and bool(self._calibration_session_ready)):
            return False
        if self._service_access_target_sa is None or not self._service_security_unlocked:
            return False
        return (int(self._service_access_target_sa) & 0xFF) == (int(self._resolve_calibration_target_sa()) & 0xFF)

    def _trial_require_write(self, key: str) -> bool:
        if self._trial_write_ready():
            return True
        self._trial_set_step(
            key, "fail",
            "Запись закрыта. Выполните этап «Открыть запись в прибор» или нажмите «Начать калибровку» в шапке окна.")
        return False

    def _trial_reset_steps(self):
        for key, _title, _hint in self.TRIAL_STEPS:
            self._trial_steps_state[key] = {"status": "pending", "detail": "", "duration": None}
        self._trial_step_started_s = {}
        self._trial_expected = {}
        self._trial_level_reading = None
        self._trial_media_points = None
        self._trial_chamber_plan = []
        self._trial_chamber_index = 0
        self._trial_chamber_outcome = None
        self._trial_applied_profile = None
        self._trial_expect_trusted = False
        # Список изменённого не сбрасывается: сброс отметок не возвращает настройки в прибор.
        self._trial_status = "Отметки этапов сброшены."
        self._trial_status_color = self.COLOR_IDLE
        self.trialChanged.emit()

    def _trial_runners(self) -> dict:
        return {
            "link": self._trial_run_link,
            "backup": self._trial_run_backup,
            "access": self._trial_run_access,
            "emulation": self._trial_run_emulation,
            "level": self._trial_run_level,
            "media": self._trial_run_media,
            "chamber": self._trial_run_chamber,
            "profile": self._trial_run_profile,
            "apply": self._trial_run_apply,
            "restore": self._trial_run_restore,
            "persist": self._trial_run_persist,
        }

    def _trial_run_step(self, key: str) -> bool:
        """Запускает один этап: пишет в журнал, что он делает и зачем, и следит, что он не завис."""
        runner = self._trial_runners().get(str(key))
        if runner is None or self._trial_busy:
            return False

        self._trial_step_started_s[key] = time.monotonic()
        self._trial_log_add("step", self._trial_title(key))
        self._trial_log_add("info", self._trial_hint(key))

        started = bool(runner())
        status = self._trial_steps_state.get(key, {}).get("status")
        if not started and status not in self.FINAL_STATUSES:
            # Этап не смог даже начать обмен и сам итог не объявил: объявляем за него.
            self._trial_set_step(
                key, "fail",
                "Этап не запустился: адаптер CAN не подключён или трассировка не включена.")
        return started

    # ------------------------------------------------------------------ автоматический прогон

    def _trial_auto_start(self) -> bool:
        """Запускает все этапы подряд."""
        if self._trial_busy or self._trial_auto_active:
            return False
        if not self._can.is_connect:
            self.infoMessage.emit("Пробная калибровка", "Сначала подключите CAN-адаптер.")
            return False
        if not self._can.is_trace:
            self.infoMessage.emit("Пробная калибровка", "Сначала включите трассировку CAN.")
            return False

        self._trial_reset_steps()
        self._trial_auto_active = True
        self._trial_auto_stop_requested = False
        self._trial_auto_backup_ok = False
        self._trial_auto_failed = False
        self._trial_auto_last = None
        self._trial_auto_current = None
        self._trial_auto_queue = [key for key, _title, _hint in self.TRIAL_STEPS]
        self._trial_log_add("step", "Автоматическая пробная калибровка запущена")
        self._trial_log_add(
            "info",
            "Этапы идут по порядку. Если этап не пройден после того, как настройки прибора запомнены, "
            "программа сразу вернёт их и остановится.")
        self.trialChanged.emit()
        self._trial_auto_next()
        return True

    def _trial_auto_stop(self):
        """Просит остановиться после текущего этапа, не обрывая его на середине."""
        if not self._trial_auto_active or self._trial_auto_stop_requested:
            return
        self._trial_auto_stop_requested = True
        self._trial_log_add("warn", "Остановка запрошена: прогон закончится после текущего этапа.")
        self.trialChanged.emit()

    def _trial_auto_next(self):
        if not self._trial_auto_active:
            return
        if self._trial_auto_stop_requested:
            self._trial_auto_finish(stopped=True)
            return
        if not self._trial_auto_queue:
            self._trial_auto_finish()
            return
        key = self._trial_auto_queue.pop(0)
        self._trial_auto_current = key
        self.trialChanged.emit()
        self._trial_run_step(key)

    def _trial_auto_on_step_final(self, key: str, status: str):
        """Этап закончился: при автоматическом прогоне через паузу берётся следующий."""
        if not self._trial_auto_active or key != self._trial_auto_current:
            return
        self._trial_auto_last = (key, status)
        self._trial_auto_timer.start(self.TRIAL_AUTO_PAUSE_MS)

    def _trial_skip_remaining(self, keep=()):
        for key in list(self._trial_auto_queue):
            if key in keep:
                continue
            self._trial_steps_state[key] = {"status": "skip", "detail": "Пропущено: предыдущий этап не пройден.",
                                            "duration": None}

    def _on_trial_auto_timer(self):
        if not self._trial_auto_active or self._trial_auto_last is None:
            return
        key, status = self._trial_auto_last
        self._trial_auto_last = None

        if key == "backup" and status in ("pass", "warn"):
            self._trial_auto_backup_ok = True

        if status == "fail":
            self._trial_auto_failed = True
            if key == "restore":
                self._trial_skip_remaining()
                self._trial_auto_finish(
                    note="Настройки вернуть не удалось: в приборе осталась пробная калибровка. "
                         "Верните их вручную строкой «Вернуть как было» или из файла копии.")
                return
            if key == "persist":
                self._trial_auto_queue = []
                self._trial_auto_finish()
                return
            if self._trial_auto_backup_ok and "restore" in self._trial_auto_queue:
                self._trial_skip_remaining(keep=("restore",))
                self._trial_auto_queue = ["restore"]
                self._trial_log_add("warn", "Этап не пройден. Возвращаю запомненные настройки и останавливаюсь.")
            else:
                self._trial_skip_remaining()
                self._trial_auto_queue = []
                self._trial_auto_finish(note="До записи в прибор дело не дошло, настройки прибора не менялись.")
                return

        self._trial_auto_next()

    def _trial_auto_finish(self, stopped: bool = False, note: str = ""):
        self._trial_auto_active = False
        self._trial_auto_current = None
        self._trial_auto_queue = []
        self._trial_auto_stop_requested = False
        summary = self._trial_summary()

        if stopped:
            text = f"Автоматическая проверка остановлена. {summary}."
            if self._trial_auto_backup_ok and self._trial_steps_state["restore"]["status"] != "pass":
                text += " В приборе может остаться пробная калибровка: выполните строку «Вернуть как было»."
            level, color = "warn", self.COLOR_WARN
        elif self._trial_auto_failed:
            text = f"Автоматическая проверка завершена с ошибками. {summary}."
            level, color = "fail", self.COLOR_FAIL
        else:
            text = f"Автоматическая проверка завершена. {summary}."
            level, color = "ok", self.COLOR_OK
        if note:
            text += " " + note

        self._trial_log_add(level, text)
        self._trial_status = text
        self._trial_status_color = color
        self.trialChanged.emit()

    def _trial_auto_progress(self) -> str:
        if not self._trial_auto_active:
            return ""
        keys = [key for key, _title, _hint in self.TRIAL_STEPS]
        # Номер строки таблицы, а не число законченных: пропущенные этапы сбили бы счёт.
        if self._trial_auto_current in keys:
            text = (f"Этап {keys.index(self._trial_auto_current) + 1} из {len(keys)}: "
                    f"{self._trial_title(self._trial_auto_current)}")
        else:
            text = f"Этапов {len(keys)}, перехожу к следующему"
        if self._trial_auto_stop_requested:
            text += " (остановка после этапа)"
        return text

    # ------------------------------------------------------------------ запись в память

    @staticmethod
    def _trial_ee_decode(raw) -> dict | None:
        """Состояние памяти из числа, прочитанного младшим байтом вперёд."""
        if raw is None:
            return None
        return decode_eeprom_state(int(raw).to_bytes(4, "little", signed=False))

    def _trial_commit_then(self, key: str, status: str, detail: str):
        """Объявляет итог этапа только после того, как прибор записал всё в микросхему памяти.

        Прибор отвечает на запись сразу, как принял значение в оперативную память, и
        чтение обратно возвращает то же самое. Выключи прибор в этот момент, и значение
        пропадёт. Поэтому этап ждёт, пока прибор перенесёт всё в микросхему и проверит
        её чтением.
        """
        self._trial_commit_ctx = {
            "key": key, "status": status, "detail": detail,
            "deadline": time.monotonic() + self.TRIAL_COMMIT_TIMEOUT_S,
        }
        self._trial_mark_running(
            key, "Прибор принял значения. Жду, пока он запишет их в микросхему памяти и проверит чтением...")
        if not self._trial_start_ops([self._op_read("ee", UdsData.eeprom_state)], "_trial_commit_poll"):
            self._trial_set_step(key, "fail", "Проверить запись в память не удалось: обмен не запустился. " + detail)

    def _trial_commit_poll(self, res: dict):
        ctx = self._trial_commit_ctx
        key = ctx["key"]
        accepted = f" Прибор принял значения: {ctx['detail']}"
        ee = self._trial_ee_decode(self._trial_value(res, "ee"))

        if ee is None:
            self._trial_set_step(
                key, "fail",
                f"Прибор не сообщил, записано ли это в память ({self._trial_error_text(res, 'ee')})." + accepted)
            return
        if ee["flags"] & EEPROM_FLAG_SPI_ERROR:
            self._trial_set_step(
                key, "fail", "Микросхема памяти прибора не отвечает: записанное пропадёт при выключении." + accepted)
            return
        if ee["pending"] > 0:
            if time.monotonic() < ctx["deadline"]:
                self._trial_start_ops(
                    [self._op_wait(self.TRIAL_COMMIT_POLL_MS), self._op_read("ee", UdsData.eeprom_state)],
                    "_trial_commit_poll")
                return
            self._trial_set_step(
                key, "fail",
                f"За {self.TRIAL_COMMIT_TIMEOUT_S:.0f} с прибор не записал в память параметров: {ee['pending']}."
                + accepted)
            return

        status, detail = ctx["status"], ctx["detail"]
        baseline = self._trial_ee_errors
        if baseline is not None and ee["errors"] > baseline:
            status = "warn"
            detail += (f" Записано в память, но микросхема подтвердила запись не с первого раза "
                       f"(повторов: {ee['errors'] - baseline}): проверьте питание платы.")
        else:
            detail += " Записано в память прибора и проверено чтением из неё."
        self._trial_ee_errors = ee["errors"]
        self._trial_commit_ctx = None
        self._trial_set_step(key, status, detail)

    # ------------------------------------------------------------------ этап: связь

    def _trial_run_link(self) -> bool:
        ops = [
            self._op_read("status", UdsData.fuel_thermal_profile_status),
            self._op_read("emul", UdsData.temperature_emulation_x10, signed=True),
            self._op_read("legacy", VAR_LEGACY_K1),
            self._op_read("fuel_t", UdsData.raw_temperature, signed=True),
            self._op_read("board_t", UdsData.raw_board_temperature, signed=True),
            self._op_read("ee", UdsData.eeprom_state),
        ]
        self._trial_mark_running(
            "link", "Читаю состояние профиля, эмуляцию, номер прежнего K1, обе температуры и состояние памяти...")
        return self._trial_start_ops(ops, "_trial_link_done")

    def _trial_link_done(self, res: dict):
        problems = []
        notes = []

        if self._trial_value(res, "status") is None:
            problems.append(f"прибор не отдал состояние профиля ({self._trial_error_text(res, 'status')})")
        emul = self._trial_value(res, "emul")
        if emul is None:
            problems.append("в прошивке нет эмуляции температуры, прошейте новую версию")
        elif emul != TRIAL_EMULATION_OFF_VALUE:
            notes.append(f"эмуляция осталась включённой на {self._trial_temp_text(emul)}")
        if self._trial_value(res, "legacy") is not None:
            problems.append("прибор отвечает на номер прежнего K1 (0x001B): в нём старая прошивка")

        for key, name in (("fuel_t", "топлива"), ("board_t", "платы")):
            value = self._trial_value(res, key)
            if value is None:
                problems.append(f"нет температуры {name}")
            elif not (-400 <= value <= 850):
                problems.append(f"температура {name} {self._trial_temp_text(value)} вне рабочего диапазона")

        ee = self._trial_ee_decode(self._trial_value(res, "ee"))
        if ee is None:
            problems.append("в прошивке нет контроля записи в память (параметр 0x0063), прошейте новую версию")
        else:
            self._trial_ee_errors = ee["errors"]
            if ee["flags"] & EEPROM_FLAG_SPI_ERROR:
                problems.append("микросхема памяти прибора не отвечает: записанное не сохранится")
            warning = eeprom_boot_warning(ee)
            if warning:
                notes.append(warning[0].lower() + warning[1:].rstrip("."))
            if ee["errors"] > 0:
                notes.append(f"с включения прибор уже отметил ошибок записи в память: {ee['errors']}")

        summary = (f"температура топлива {self._trial_temp_text(self._trial_value(res, 'fuel_t'))}, "
                   f"платы {self._trial_temp_text(self._trial_value(res, 'board_t'))}")
        if problems:
            self._trial_set_step("link", "fail", "; ".join(problems) + ".")
        elif notes:
            self._trial_set_step("link", "warn", summary + "; " + "; ".join(notes) + ".")
        else:
            self._trial_set_step("link", "pass", summary + ", прошивка новая, эмуляция выключена.")

    # ------------------------------------------------------------------ этап: запомнить настройки

    BACKUP_VARS = (
        ("empty", UdsData.empty_fuel_tank, False),
        ("full", UdsData.full_fuel_tank, False),
        ("zero_trim", UdsData.fuel_zero_trim_count, True),
        ("media_enable", UdsData.fuel_media_comp_enable, False),
        ("media_air", UdsData.fuel_media_flatcap_air_count, False),
        ("media_cal", UdsData.fuel_media_flatcap_cal_count, False),
    )

    def _trial_dirty_text(self) -> str:
        names = {"level": "отметки бака", "media": "точки вида топлива", "profile": "профиль"}
        return ", ".join(names[key] for key in ("level", "media", "profile") if key in self._trial_dirty)

    def _trial_run_backup(self) -> bool:
        if self._trial_dirty and self._trial_backup:
            # В приборе ещё пробные значения прошлого прогона: перечитав их, программа
            # запомнила бы пробу вместо настоящих настроек.
            self._trial_set_step(
                "backup", "warn",
                f"Настройки не перечитаны: в приборе остались пробные значения прошлого прогона "
                f"({self._trial_dirty_text()}). Использую копию от {self._trial_backup['saved_at']}, "
                "в конце вернётся она.")
            return True
        ops = [self._op_read(f"b_{key}", var, signed) for key, var, signed in self.BACKUP_VARS]
        ops += [
            self._op_call("profile_started", "_trial_backup_profile_call"),
            self._op_await("await_profile", "profile_read", self.TRIAL_PROFILE_TIMEOUT_MS),
        ]
        self._trial_mark_running("backup", "Читаю отметки бака, подгонку нуля, точки вида топлива, затем профиль...")
        return self._trial_start_ops(ops, "_trial_backup_done")

    def _trial_backup_profile_call(self):
        self._trial_results["profile_started"] = bool(self._profile_read_from_device())

    def _trial_backup_done(self, res: dict):
        values = {}
        missing = []
        for key, _var, _signed in self.BACKUP_VARS:
            value = self._trial_value(res, f"b_{key}")
            if value is None:
                missing.append(key)
            else:
                values[key] = value

        if missing:
            self._trial_set_step("backup", "fail",
                                 f"Прибор отдал не все настройки, нет: {', '.join(missing)}. Дальше идти нельзя.")
            return
        if res.get("profile_started") is not True or res.get("profile_read") is not True \
                or str(self._profile_status).startswith("Операция прервана"):
            self._trial_set_step("backup", "fail", f"Профиль из прибора не прочитался: {self._profile_status}")
            return

        self._trial_backup = {
            "values": values,
            "profile": {name: list(table) for name, table in self._profile_values.items()},
            "generation": int(self._profile_generation),
            "crc": int(self._profile_calc_crc()),
            # Сумма и состояние так, как их хранит сам прибор: у нетронутого профиля сумма бывает нулевой.
            "device_crc": self._profile_device_crc,
            "device_status": self._profile_device_status,
            "saved_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "node": int(self._resolve_calibration_target_sa()) & 0xFF,
        }

        file_text = ""
        status = "pass"
        try:
            folder = self._resolve_calibration_backup_all_nodes_directory()
            path = pathlib.Path(folder) / (
                f"trial_backup_0x{self._trial_backup['node']:02X}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            path.write_text(json.dumps(self._trial_backup, ensure_ascii=False, indent=2), encoding="utf-8")
            file_text = f"\nКопия сохранена в файл {path}"
        except Exception as error:
            status = "warn"
            file_text = f"\nФайл копии записать не удалось: {error}. Настройки запомнены только в программе."

        self._trial_set_step(
            "backup", status,
            f"Запомнено: 0 % = {values['empty']}, 100 % = {values['full']}, подгонка нуля {values['zero_trim']}, "
            f"вид топлива {values['media_air']} / {values['media_cal']}, поправка по виду топлива "
            f"{'включена' if values['media_enable'] else 'выключена'}, сумма профиля "
            f"0x{self._trial_backup['crc']:04X}." + file_text)

    # ------------------------------------------------------------------ этап: доступ на запись

    def _trial_run_access(self) -> bool:
        if self._trial_write_ready():
            self._trial_access_pass()
            return True
        ops = []
        if not bool(self._calibration_active):
            ops.append(self._op_call("calibration_started", "_trial_access_start_call"))
            text = "Калибровка не запущена. Запускаю её, как кнопка «Начать калибровку», и жду доступа на запись..."
        else:
            text = "Калибровка запущена, жду, пока прибор откроет доступ на запись..."
        ops.append(self._op_await("await_write_ready", "write_ready", self.TRIAL_ACCESS_TIMEOUT_MS))
        self._trial_mark_running("access", text)
        return self._trial_start_ops(ops, "_trial_access_done")

    def _trial_access_start_call(self):
        self.toggleCalibration()
        self._trial_results["calibration_started"] = True

    def _trial_access_pass(self):
        sa = int(self._resolve_calibration_target_sa()) & 0xFF
        self._trial_set_step("access", "pass", f"Сессия калибровки запущена, запись в прибор 0x{sa:02X} открыта.")

    def _trial_access_done(self, res: dict):
        if self._trial_write_ready():
            self._trial_access_pass()
            return
        if not bool(self._calibration_active):
            reason = "сценарий калибровки не запустился"
        elif not bool(self._calibration_session_ready):
            reason = "прибор не подтвердил сессию"
        else:
            reason = "Security Access открыт не для выбранного прибора"
        self._trial_set_step(
            "access", "fail",
            f"Запись не открылась за {self.TRIAL_ACCESS_TIMEOUT_MS // 1000} с: {reason}. Проверьте выбор прибора "
            "в шапке окна и сообщения калибровки в общем журнале.")

    # ------------------------------------------------------------------ этап: эмуляция

    def _trial_run_emulation(self) -> bool:
        if not self._trial_require_write("emulation"):
            return False
        ops = []
        for tag, value in (("cold", -400), ("hot", 850)):
            ops += [
                self._trial_emulation_op(f"w_{tag}", value),
                self._op_wait(self.TRIAL_SETTLE_MS),
                self._op_read(f"f_{tag}", UdsData.raw_temperature, signed=True),
                self._op_read(f"b_{tag}", UdsData.raw_board_temperature, signed=True),
                self._op_read(f"e_{tag}", UdsData.temperature_emulation_x10, signed=True),
            ]
        ops += [
            self._trial_emulation_op("w_off", None),
            self._op_wait(self.TRIAL_SETTLE_MS),
            self._op_read("f_off", UdsData.raw_temperature, signed=True),
            self._op_read("b_off", UdsData.raw_board_temperature, signed=True),
            self._op_read("e_off", UdsData.temperature_emulation_x10, signed=True),
        ]
        self._trial_mark_running("emulation", "Задаю прибору -40 °C, затем +85 °C, затем выключаю эмуляцию...")
        return self._trial_start_ops(ops, "_trial_emulation_done")

    def _trial_emulation_done(self, res: dict):
        problems = []
        for tag, value in (("cold", -400), ("hot", 850)):
            if res.get(f"w_{tag}") is not True:
                problems.append(f"запись {self._trial_temp_text(value)}: {self._trial_error_text(res, f'w_{tag}')}")
                continue
            got = [self._trial_value(res, f"{name}_{tag}") for name in ("f", "b", "e")]
            if got != [value, value, value]:
                problems.append(
                    f"задано {self._trial_temp_text(value)}, прибор показал топливо "
                    f"{self._trial_temp_text(got[0])}, плату {self._trial_temp_text(got[1])}")

        if res.get("w_off") is not True:
            problems.append(f"выключение эмуляции: {self._trial_error_text(res, 'w_off')}")
        elif self._trial_value(res, "e_off") != TRIAL_EMULATION_OFF_VALUE:
            problems.append("после выключения прибор всё ещё сообщает о включённой эмуляции")

        real_fuel = self._trial_value(res, "f_off")
        real_board = self._trial_value(res, "b_off")
        if problems:
            self._trial_set_step("emulation", "fail", "; ".join(problems) + ".")
        else:
            self._trial_set_step(
                "emulation", "pass",
                f"Прибор принял -40 и +85 °C по обоим датчикам и вернулся к настоящей температуре: "
                f"топливо {self._trial_temp_text(real_fuel)}, плата {self._trial_temp_text(real_board)}.")

    # ------------------------------------------------------------------ этап: отметки бака

    def _trial_level_target(self, freeze_pct) -> int | None:
        """Уровень проверки в десятых процента: первый из списка выше порога заморозки. None - не подобрать."""
        floor = (int(freeze_pct) * 10 if freeze_pct is not None else 0) + self.TRIAL_LEVEL_FREEZE_MARGIN_PERMILLE
        for target in self.TRIAL_LEVEL_TARGETS_PERMILLE:
            if target >= floor:
                return target
        return None

    def _trial_level_marks(self, compensated: int,
                           target_permille: int = TRIAL_LEVEL_EXPECTED_PERMILLE) -> tuple[int, int]:
        """Отметки 0 % и 100 % вокруг показания конденсатора, при которых уровень равен заданному."""
        below = self.TRIAL_LEVEL_SPAN * int(target_permille) // 1000
        return int(compensated) - below, int(compensated) + (self.TRIAL_LEVEL_SPAN - below)

    def _trial_level_order(self, current_full, new_empty: int, new_full: int) -> list[dict]:
        """Порядок записи отметок, который прибор примет.

        Прибор отвергает отметку 0 %, если она не ниже текущей отметки 100 %, и
        наоборот. Поэтому сначала пишется та отметка, которая с текущей другой
        отметкой уже совместима.
        """
        write_empty = self._op_write("w_empty", UdsData.empty_fuel_tank, new_empty)
        write_full = self._op_write("w_full", UdsData.full_fuel_tank, new_full)
        if current_full is not None and new_empty < int(current_full):
            return [write_empty, write_full]
        return [write_full, write_empty]

    def _trial_run_level(self) -> bool:
        if not self._trial_require_write("level"):
            return False
        ops = [self._trial_emulation_op("emul_off", None), self._op_wait(self.TRIAL_SETTLE_MS)]
        for index in range(self.TRIAL_SAMPLES):
            ops.append(self._op_read(f"raw{index}", UdsData.curr_fuel_tank))
            ops.append(self._op_read(f"comp{index}", UdsData.fuel_compensated_period))
        ops += [self._op_read("cur_full", UdsData.full_fuel_tank), self._op_read("tank_model", VAR_TANK_MODEL),
                self._op_read("freeze", VAR_FREEZE_PCT)]
        self._trial_mark_running("level", f"Снимаю показание основного контура, {self.TRIAL_SAMPLES} замеров подряд...")
        return self._trial_start_ops(ops, "_trial_level_stage2")

    def _trial_level_stage2(self, res: dict):
        raw = self._trial_mean(res, "raw", self.TRIAL_SAMPLES)
        comp = self._trial_mean(res, "comp", self.TRIAL_SAMPLES)
        if raw is None or comp is None:
            self._trial_set_step(
                "level", "fail",
                "Прибор не отдал период основного контура. Проверьте, что конденсатор подключён и шина работает.")
            return

        freeze = self._trial_value(res, "freeze")
        target = self._trial_level_target(freeze)
        if target is None:
            limit = (self.TRIAL_LEVEL_TARGETS_PERMILLE[-1] - self.TRIAL_LEVEL_FREEZE_MARGIN_PERMILLE) // 10
            self._trial_set_step(
                "level", "fail",
                f"Порог заморозки вида топлива {freeze} % слишком высокий: уровень выше него на столе не "
                f"поставить, и коэффициент среды не проверить. Временно уменьшите порог (параметр 0x0034) "
                f"до {limit} % или ниже.")
            return

        empty, full = self._trial_level_marks(comp, target)
        if empty < 1 or full > 0xFFFF:
            self._trial_set_step(
                "level", "fail",
                f"Показание {comp} слишком близко к краю шкалы, отметки вокруг него не помещаются. "
                "Возьмите конденсатор другого номинала.")
            return

        self._trial_level_reading = {
            "raw": raw, "comp": comp, "empty": empty, "full": full, "target": target, "freeze": freeze,
            "tank_model": self._trial_value(res, "tank_model"),
        }
        # Отметки меняются с первой же записи, поэтому возвращать их нужно и при отказе на середине.
        self._trial_dirty.add("level")
        ops = self._trial_level_order(self._trial_value(res, "cur_full"), empty, full)
        ops += [
            self._op_wait(self.TRIAL_SETTLE_MS),
            self._op_read("rb_empty", UdsData.empty_fuel_tank),
            self._op_read("rb_full", UdsData.full_fuel_tank),
        ]
        ops += [self._op_read(f"lvl{index}", UdsData.raw_fuel_level, signed=True)
                for index in range(self.TRIAL_SAMPLES)]
        self._trial_mark_running(
            "level",
            f"Итоговый период {comp}, сырой {raw}, порог заморозки вида топлива "
            f"{'нет данных' if freeze is None else f'{freeze} %'}. Ставлю отметки 0 % = {empty} и "
            f"100 % = {full}, при них уровень обязан стать {target / 10:.0f} %...")
        self._trial_start_ops(ops, "_trial_level_done")

    def _trial_level_done(self, res: dict):
        reading = self._trial_level_reading
        empty, full = reading["empty"], reading["full"]
        problems = []
        notes = []

        for key, word in (("w_empty", "0 %"), ("w_full", "100 %")):
            if res.get(key) is not True:
                problems.append(f"запись отметки {word}: {self._trial_error_text(res, key)}")

        for key, want, word in (("rb_empty", empty, "0 %"), ("rb_full", full, "100 %")):
            got = self._trial_value(res, key)
            if got != want:
                problems.append(f"в приборе отметка {word} = {got}, а записывали {want}")

        level = self._trial_mean(res, "lvl", self.TRIAL_SAMPLES)
        expected = int(reading.get("target", self.TRIAL_LEVEL_EXPECTED_PERMILLE))
        model = reading["tank_model"]
        if model == 0:
            if level is None:
                problems.append("прибор не отдал уровень")
            elif abs(level - expected) > self.TRIAL_LEVEL_TOLERANCE_PERMILLE:
                problems.append(f"уровень {level / 10:.1f} %, а по отметкам вокруг конденсатора должен быть "
                                f"{expected / 10:.1f} %")
            else:
                notes.append(f"уровень {level / 10:.1f} % при расчётных {expected / 10:.1f} %")
                if reading.get("freeze") is not None:
                    notes.append(f"это выше порога заморозки вида топлива {reading['freeze']} %")
        elif model is not None:
            notes.append("выбрана модель уровня по двум контурам, уровень здесь не сверяется")

        # Отметки ставятся по итоговому периоду: по нему прибор и считает уровень.
        warning = ""
        drift = abs(reading["raw"] - reading["comp"])
        if drift > self.TRIAL_PERIOD_TOLERANCE:
            warning = (f"итоговый период отличается от сырого на {drift} отсчётов: раздел «Уровень бака» "
                       "снимает отметки по сырому периоду, и при таком расхождении уровень там сместится")

        if problems:
            self._trial_set_step("level", "fail", "; ".join(problems) + ".")
            return

        self._trial_expected.update({"empty": empty, "full": full})
        text = (f"Показание конденсатора {reading['comp']}, отметки 0 % = {empty} и 100 % = {full} записаны "
                f"и прочитаны обратно; " + "; ".join(notes))
        if warning:
            self._trial_commit_then("level", "warn", text + "; " + warning + ".")
        else:
            self._trial_commit_then("level", "pass", text + ".")

    # ------------------------------------------------------------------ этап: вид топлива

    def _trial_media_points_for(self, flatcap: int) -> tuple[int, int]:
        """Точки «воздух» и «топливо», при которых коэффициент среды ровно 1,100."""
        air = int(flatcap) - (self.TRIAL_MEDIA_SPAN * self.TRIAL_MEDIA_TARGET_X1000) // 1000
        return air, air + self.TRIAL_MEDIA_SPAN

    def _trial_run_media(self) -> bool:
        if not self._trial_require_write("media"):
            return False
        ops = [self._trial_emulation_op("emul_off", None), self._op_wait(self.TRIAL_SETTLE_MS)]
        ops += [self._op_read(f"m{index}", UdsData.fuel_media_flatcap_raw) for index in range(self.TRIAL_SAMPLES)]
        ops += [self._op_read("level", UdsData.raw_fuel_level, signed=True), self._op_read("freeze", VAR_FREEZE_PCT)]
        self._trial_mark_running(
            "media", f"Снимаю показание контура вида топлива, {self.TRIAL_SAMPLES} замеров подряд, и проверяю уровень...")
        return self._trial_start_ops(ops, "_trial_media_stage2")

    def _trial_media_stage2(self, res: dict):
        flatcap = self._trial_mean(res, "m", self.TRIAL_SAMPLES)
        if flatcap is None:
            self._trial_set_step(
                "media", "fail",
                "Прибор не отдал показание контура вида топлива. Проверьте, что конденсатор подключён.")
            return

        level = self._trial_value(res, "level")
        freeze = self._trial_value(res, "freeze")
        if level is not None and freeze is not None and level < int(freeze) * 10:
            if self._trial_steps_state["level"]["status"] in ("pass", "warn"):
                advice = ("Этап «Отметки бака» ставил уровень выше порога, а сейчас он ниже: проверьте "
                          "конденсатор на основном контуре и повторите оба этапа.")
            else:
                advice = "Сначала выполните этап «Отметки бака»: он поднимает уровень выше порога."
            self._trial_set_step(
                "media", "fail",
                f"Уровень {level / 10:.1f} % ниже порога заморозки {freeze} %, поэтому прибор не обновляет "
                f"коэффициент среды. {advice}")
            return

        air, cal = self._trial_media_points_for(flatcap)
        if air < 1:
            self._trial_set_step(
                "media", "fail",
                f"Показание {flatcap} слишком мало для проверки: нужен конденсатор, у которого показание "
                f"больше {self.TRIAL_MEDIA_SPAN * self.TRIAL_MEDIA_TARGET_X1000 // 1000} отсчётов.")
            return

        self._trial_media_points = {"flatcap": flatcap, "air": air, "cal": cal}
        self._trial_dirty.add("media")
        ops = [
            self._op_write("w_air", UdsData.fuel_media_flatcap_air_count, air),
            self._op_write("w_cal", UdsData.fuel_media_flatcap_cal_count, cal),
            self._op_write("w_en", UdsData.fuel_media_comp_enable, 1),
            self._op_wait(self.TRIAL_SETTLE_MS),
            self._op_read("rb_air", UdsData.fuel_media_flatcap_air_count),
            self._op_read("rb_cal", UdsData.fuel_media_flatcap_cal_count),
            self._op_read("rb_en", UdsData.fuel_media_comp_enable),
        ]
        self._trial_mark_running(
            "media",
            f"Показание {flatcap}, уровень {'нет данных' if level is None else f'{level / 10:.1f} %'}. Ставлю "
            f"«воздух» = {air} и «топливо» = {cal}, при них коэффициент среды обязан стать "
            f"{self.TRIAL_MEDIA_TARGET_X1000 / 1000:.3f}...")
        self._trial_start_ops(ops, "_trial_media_stage3")

    def _trial_media_stage3(self, res: dict):
        points = self._trial_media_points
        problems = []

        for key, word in (("w_air", "«воздух»"), ("w_cal", "«топливо»"), ("w_en", "включение поправки")):
            if res.get(key) is not True:
                problems.append(f"запись {word}: {self._trial_error_text(res, key)}")
        for key, want, word in (("rb_air", points["air"], "«воздух»"), ("rb_cal", points["cal"], "«топливо»"),
                                ("rb_en", 1, "включение")):
            got = self._trial_value(res, key)
            if got != want:
                problems.append(f"в приборе {word} = {got}, а записывали {want}")

        if problems:
            self._trial_set_step("media", "fail", "; ".join(problems) + ".")
            return

        self._trial_expected.update({"media_air": points["air"], "media_cal": points["cal"], "media_enable": 1})
        self._trial_rf_deadline = time.monotonic() + self.TRIAL_RF_TIMEOUT_MS / 1000.0
        self._trial_mark_running(
            "media",
            f"Точки записаны и прочитаны обратно. Коэффициент среды сглаживается прибором, жду до "
            f"{self.TRIAL_RF_TIMEOUT_MS // 1000} с, пока он станет {self.TRIAL_MEDIA_TARGET_X1000 / 1000:.3f}...")
        self._trial_start_ops([self._op_read("rf", UdsData.fuel_media_rf_x1000), self._op_wait(500)],
                              "_trial_media_rf_poll")

    def _trial_media_rf_poll(self, res: dict):
        points = self._trial_media_points
        target = self.TRIAL_MEDIA_TARGET_X1000
        rf = self._trial_value(res, "rf")
        if rf is not None and abs(rf - target) <= self.TRIAL_RF_TOLERANCE_X1000:
            self._trial_commit_then(
                "media", "pass",
                f"Показание конденсатора {points['flatcap']}, точки «воздух» = {points['air']} и «топливо» = "
                f"{points['cal']} записаны и прочитаны обратно; коэффициент среды {rf / 1000:.3f} при "
                f"расчётном {target / 1000:.3f}.")
            return
        if time.monotonic() < self._trial_rf_deadline:
            self._trial_start_ops([self._op_read("rf", UdsData.fuel_media_rf_x1000), self._op_wait(500)],
                                  "_trial_media_rf_poll")
            return
        shown = "нет данных" if rf is None else f"{rf / 1000:.3f}"
        self._trial_set_step(
            "media", "fail",
            f"Точки записались, но коэффициент среды за {self.TRIAL_RF_TIMEOUT_MS // 1000} с не сошёлся к "
            f"{target / 1000:.3f}, последнее значение {shown}.")

    # ------------------------------------------------------------------ этап: снятие точек

    def _trial_run_chamber(self) -> bool:
        if not self._trial_require_write("chamber"):
            return False
        self._trial_chamber_plan = list(chamber_fit.NODES_X10)
        self._trial_chamber_index = 0
        self._trial_chamber_outcome = None
        self._chamber_clear_points()
        self._chamber_rehearsal = True
        return self._trial_chamber_capture_current()

    def _trial_chamber_capture_current(self) -> bool:
        node = self._trial_chamber_plan[self._trial_chamber_index]
        ops = [
            self._trial_emulation_op("w_node", node),
            self._op_wait(self.TRIAL_SETTLE_MS),
            self._op_call("capture_started", "_trial_chamber_capture_call"),
            self._op_await("await_chamber", "captured", self.TRIAL_CHAMBER_TIMEOUT_MS),
        ]
        self._trial_mark_running(
            "chamber",
            f"Задаю {chamber_fit.node_text(node)} и снимаю точку "
            f"{self._trial_chamber_index + 1} из {len(self._trial_chamber_plan)}...")
        return self._trial_start_ops(ops, "_trial_chamber_capture_done")

    def _trial_chamber_capture_call(self):
        self._chamber_label = self.TRIAL_CHAMBER_LABEL
        self._trial_results["capture_started"] = bool(self._chamber_capture_point())

    def _trial_chamber_capture_done(self, res: dict):
        node = self._trial_chamber_plan[self._trial_chamber_index]
        number = self._trial_chamber_index + 1
        total = len(self._trial_chamber_plan)
        problem = None

        if res.get("w_node") is not True:
            problem = (f"прибор не принял температуру {chamber_fit.node_text(node)} "
                       f"({self._trial_error_text(res, 'w_node')})")
        elif res.get("capture_started") is not True or res.get("captured") is not True:
            problem = f"точка {number} не снята: {self._chamber_status}"
        else:
            point = self._chamber_points[-1] if self._chamber_points else None
            if point is None or point["note"] != self.TRIAL_CHAMBER_LABEL:
                problem = f"точка {number} не записалась в журнал: {self._chamber_status}"
            elif chamber_fit.nearest_node(point["board_temp_x10"]) != node:
                problem = (f"точка {number}: задана температура {chamber_fit.node_text(node)}, а прибор сообщил "
                           f"{self._trial_temp_text(point['board_temp_x10'])}. Эмуляция не дошла до измерения")
            else:
                media = "нет данных" if point.get("media") is None else point["media"]
                self._trial_log_add(
                    "detail",
                    f"{chamber_fit.node_text(node)}: основной {point['main']}, вид топлива {media}, "
                    f"температура платы {self._trial_temp_text(point['board_temp_x10'])}")

        if problem:
            self._trial_chamber_outcome = ("fail", problem + ".")
            self._trial_chamber_finish_start()
            return

        self._trial_chamber_index += 1
        if self._trial_chamber_index < total:
            self._trial_chamber_capture_current()
            return

        periods = [point["main"] for point in self._chamber_points if point["note"] == self.TRIAL_CHAMBER_LABEL]
        spread = max(periods) - min(periods) if periods else 0
        if spread > self.TRIAL_CHAMBER_SPREAD_LIMIT:
            self._trial_chamber_outcome = (
                "warn",
                f"Все {total} точек попали в свои узлы, но показание одного и того же конденсатора гуляло на "
                f"{spread} отсчётов. Проверьте проводки и контакт.")
        else:
            self._trial_chamber_outcome = (
                "pass",
                f"Все {total} точек попали в свои узлы, показание конденсатора стабильно, разброс {spread} "
                "отсчётов. Точки записаны в журнал прогона с пометкой пробы.")
        self._trial_chamber_finish_start()

    def _trial_chamber_finish_start(self):
        """Выключает эмуляцию после снятия точек и только потом объявляет итог."""
        self._chamber_rehearsal = False
        if not self._trial_start_ops([self._trial_emulation_op("emul_off", None)], "_trial_chamber_finish"):
            _status, detail = self._trial_chamber_outcome
            self._trial_set_step("chamber", "fail", detail + " Эмуляцию после снятия выключить не удалось.")

    def _trial_chamber_finish(self, res: dict):
        status, detail = self._trial_chamber_outcome
        if res.get("emul_off") is not True:
            status = "fail"
            detail += f" Эмуляцию после снятия выключить не удалось ({self._trial_error_text(res, 'emul_off')})."
        self._trial_set_step("chamber", status, detail)

    # ------------------------------------------------------------------ этап: запись профиля

    def _trial_run_profile(self) -> bool:
        if not self._trial_require_write("profile"):
            return False
        self._trial_applied_profile = None
        ops = [
            self._trial_emulation_op("emul_off", None),
            self._op_call("loaded", "_trial_profile_load_call"),
            self._op_call("write_started", "_trial_profile_write_call"),
            self._op_await("await_profile", "written", self.TRIAL_PROFILE_TIMEOUT_MS),
            self._op_call("write_status", "_trial_profile_status_call"),
            self._op_call("verify_started", "_trial_profile_verify_call"),
            self._op_await("await_profile", "verified", self.TRIAL_PROFILE_TIMEOUT_MS),
            self._op_read("status", UdsData.fuel_thermal_profile_status),
        ]
        self._trial_mark_running(
            "profile", "Пишу проверочный профиль: семь таблиц, номер алгоритма, поколение и в конце сумму. "
                       "Затем читаю всё обратно...")
        return self._trial_start_ops(ops, "_trial_profile_done")

    def _trial_profile_load_call(self):
        profile = profile_model.build_test_profile(self._profile_values["nodes"])
        for name, values in profile.items():
            self._profile_values[name] = [int(value) for value in values]
        self.profileChanged.emit()
        self._trial_results["loaded"] = True

    def _trial_profile_write_call(self):
        # С этой минуты профиль в приборе считается изменённым, даже если запись оборвётся.
        self._trial_dirty.add("profile")
        self._trial_results["write_started"] = bool(self._profile_write_to_device(verify=False))

    def _trial_profile_verify_call(self):
        self._trial_results["verify_started"] = bool(self._profile_verify_on_device())

    def _trial_profile_status_call(self):
        self._trial_results["write_status"] = str(self._profile_status)

    def _trial_profile_verdict(self, res: dict, what: str) -> list[str]:
        """Общая проверка записи и сверки профиля для записи профиля и возврата настроек."""
        problems = []
        if res.get("write_started") is not True:
            problems.append(f"запись {what} не началась: {self._profile_status}")
            return problems
        if res.get("written") is not True:
            problems.append(f"запись {what} не закончилась за {self.TRIAL_PROFILE_TIMEOUT_MS // 1000} с")
            return problems
        if str(res.get("write_status", "")).startswith("Операция прервана"):
            problems.append(f"запись {what} прервана: {res.get('write_status')}")
            return problems
        if res.get("verify_started") is not True or res.get("verified") is not True:
            problems.append(f"сверка {what} не выполнена: {self._profile_status}")
            return problems
        problems.extend(self._profile_verify_report)

        status = self._trial_value(res, "status")
        if status is None:
            problems.append("прибор не отдал состояние профиля")
        elif not (status & profile_model.STATUS_TRUSTED):
            problems.append(f"прибор не взял таблицы в работу, состояние 0x{status:02X}")
        return problems

    def _trial_profile_done(self, res: dict):
        problems = self._trial_profile_verdict(res, "проверочного профиля")
        if problems:
            self._trial_applied_profile = None
            self._trial_set_step("profile", "fail", "; ".join(problems) + ".")
            return

        # Снимок того, что лежит в приборе: по нему применение сверяется даже тогда,
        # когда таблицы на экране потом кто-то поправит.
        self._trial_applied_profile = {name: list(values) for name, values in self._profile_values.items()}
        self._trial_expected.update({
            "crc": self._profile_calc_crc(),
            "generation": int(self._profile_generation),
            "algorithm": 1,
        })
        self._trial_expect_trusted = True
        self._trial_commit_then(
            "profile", "pass",
            f"Проверочный профиль записан: все семь таблиц совпали с прочитанными из прибора, сумма "
            f"0x{self._profile_calc_crc():04X} сошлась, прибор взял таблицы в работу.")

    # ------------------------------------------------------------------ этап: применение

    def _trial_run_apply(self) -> bool:
        if not self._trial_require_write("apply"):
            return False
        if self._trial_applied_profile is None:
            self._trial_set_step(
                "apply", "fail",
                "Сначала выполните этап записи профиля: он пишет проверочный профиль, по которому идёт сверка.")
            return False
        ops = [
            self._trial_emulation_op("emul_off", None),
            self._op_read("status", UdsData.fuel_thermal_profile_status),
            self._op_read("zero_trim", UdsData.fuel_zero_trim_count, signed=True),
        ]
        for index, temperature in enumerate(self.TRIAL_APPLY_TEMPS_X10):
            ops += [
                self._trial_emulation_op(f"w{index}", temperature),
                self._op_wait(self.TRIAL_SETTLE_MS),
                self._op_read(f"raw_a{index}", UdsData.curr_fuel_tank),
                self._op_read(f"board{index}", UdsData.fuel_board_stage_period),
                self._op_read(f"comp{index}", UdsData.fuel_compensated_period),
                self._op_read(f"raw_b{index}", UdsData.curr_fuel_tank),
                self._op_read(f"mode{index}", UdsData.fuel_board_stage_mode),
            ]
        ops.append(self._trial_emulation_op("emul_off_end", None))
        self._trial_mark_running(
            "apply",
            f"Прохожу {len(self.TRIAL_APPLY_TEMPS_X10)} температур: при каждой читаю сырой период, период после "
            "ступени платы и итоговый, и сверяю с расчётом по формулам прошивки...")
        return self._trial_start_ops(ops, "_trial_apply_done")

    def _trial_apply_compare(self, res: dict) -> tuple[list[str], list[str]]:
        """Сверяет цепочку прибора с расчётом. Возвращает (расхождения, строки отчёта)."""
        problems = []
        lines = []
        status = self._trial_value(res, "status") or 0
        trusted = bool(status & profile_model.STATUS_TRUSTED)
        zero_trim = self._trial_value(res, "zero_trim") or 0
        profile = self._trial_applied_profile
        tolerance = self.TRIAL_PERIOD_TOLERANCE

        if not trusted:
            problems.append(f"прибор не применяет профиль, состояние 0x{status:02X}")

        for index, temperature in enumerate(self.TRIAL_APPLY_TEMPS_X10):
            place = self._trial_temp_text(temperature)
            if res.get(f"w{index}") is not True:
                problems.append(f"{place}: прибор не принял температуру ({self._trial_error_text(res, f'w{index}')})")
                continue

            raw_a = self._trial_value(res, f"raw_a{index}")
            raw_b = self._trial_value(res, f"raw_b{index}")
            board = self._trial_value(res, f"board{index}")
            comp = self._trial_value(res, f"comp{index}")
            mode = self._trial_value(res, f"mode{index}")
            if None in (raw_a, raw_b, board, comp, mode):
                problems.append(f"{place}: прибор отдал не все величины")
                continue

            # Сырой период читается до и после: цепочку прибор мог пересчитать между запросами.
            predictions = [
                profile_model.predict_main(raw, profile, board_temp_x10=temperature, tube_temp_x10=temperature,
                                           trusted=trusted, zero_trim=zero_trim)
                for raw in (raw_a, raw_b)
            ]
            board_lo = min(p["board_stage"] for p in predictions) - tolerance
            board_hi = max(p["board_stage"] for p in predictions) + tolerance
            comp_lo = min(p["compensated"] for p in predictions) - tolerance
            comp_hi = max(p["compensated"] for p in predictions) + tolerance
            expected_comp = predictions[0]["compensated"]

            lines.append(f"{place}: сырой {raw_a}, после платы {board}, итог прибора {comp}, по расчёту {expected_comp}")

            if not (board_lo <= board <= board_hi):
                problems.append(
                    f"{place}: после ступени платы {board}, а по расчёту {predictions[0]['board_stage']}")
            if not (comp_lo <= comp <= comp_hi):
                problems.append(f"{place}: итоговый период {comp}, а по расчёту {expected_comp}")
            needed = profile_model.MODE_MAIN_LUT | profile_model.MODE_TUBE_MAIN
            if (mode & needed) != needed:
                problems.append(f"{place}: прибор не сообщил о работе обеих ступеней, признаки 0x{mode:02X}")

        return problems, lines

    def _trial_apply_done(self, res: dict):
        mismatches, lines = self._trial_apply_compare(res)
        if res.get("emul_off_end") is not True:
            mismatches.append("эмуляция после проверки не выключилась")

        detail = "\n".join(lines)
        if mismatches:
            self._trial_set_step("apply", "fail", "; ".join(mismatches) + ".\n" + detail)
        else:
            self._trial_set_step(
                "apply", "pass",
                f"При всех {len(self.TRIAL_APPLY_TEMPS_X10)} температурах итоговый период прибора совпал с "
                f"расчётом по формулам прошивки в пределах {self.TRIAL_PERIOD_TOLERANCE} отсчётов.\n" + detail)

    # ------------------------------------------------------------------ этап: вернуть как было

    def _trial_run_restore(self) -> bool:
        if not self._trial_backup:
            self._trial_set_step(
                "restore", "fail", "Возвращать нечего: сначала выполните этап «Запомнить текущие настройки».")
            return False
        if not self._trial_require_write("restore"):
            return False
        ops = [
            self._trial_emulation_op("emul_off", None),
            self._op_read("cur_full", UdsData.full_fuel_tank),
        ]
        self._trial_mark_running("restore", f"Возвращаю настройки, запомненные {self._trial_backup['saved_at']}...")
        return self._trial_start_ops(ops, "_trial_restore_stage2")

    def _trial_restore_stage2(self, res: dict):
        values = self._trial_backup["values"]
        dirty = set(self._trial_dirty)
        # Обратно пишется только то, что пробная калибровка поменяла: лишняя запись это
        # износ памяти прибора и лишний шанс оборваться. Сверяется всё.
        ops = []
        if "level" in dirty:
            ops += self._trial_level_order(self._trial_value(res, "cur_full"), values["empty"], values["full"])
            # Подгонка нуля пишется вместе с отметками: её смысл привязан к ним.
            ops.append(self._op_write("w_zero_trim", UdsData.fuel_zero_trim_count, values["zero_trim"]))
        if "media" in dirty:
            ops += [
                self._op_write("w_media_air", UdsData.fuel_media_flatcap_air_count, values["media_air"]),
                self._op_write("w_media_cal", UdsData.fuel_media_flatcap_cal_count, values["media_cal"]),
                self._op_write("w_media_enable", UdsData.fuel_media_comp_enable, values["media_enable"]),
            ]
        if "profile" in dirty:
            ops += [
                self._op_call("profile_loaded", "_trial_restore_profile_load_call"),
                self._op_call("write_started", "_trial_restore_profile_write_call"),
                self._op_await("await_profile", "written", self.TRIAL_PROFILE_TIMEOUT_MS),
                self._op_call("write_status", "_trial_profile_status_call"),
                self._op_call("verify_started", "_trial_profile_verify_call"),
                self._op_await("await_profile", "verified", self.TRIAL_PROFILE_TIMEOUT_MS),
                self._op_read("status", UdsData.fuel_thermal_profile_status),
            ]
        else:
            ops.append(self._op_read("crc_now", VAR_CRC))
        ops += [self._op_read(f"r_{key}", var, signed) for key, var, signed in self.BACKUP_VARS]

        what = self._trial_dirty_text()
        self._trial_mark_running(
            "restore",
            (f"Пишу обратно: {what}. " if what else "Пробная калибровка настройки не меняла, писать нечего. ")
            + "Затем читаю все запомненные настройки для сверки...")
        self._trial_start_ops(ops, "_trial_restore_done")

    def _trial_restore_profile_load_call(self):
        for name, table in self._trial_backup["profile"].items():
            self._profile_values[name] = [int(value) for value in table]
        self._profile_generation = int(self._trial_backup["generation"])
        self.profileChanged.emit()
        self._trial_results["profile_loaded"] = True

    def _trial_restore_profile_write_call(self):
        # Запомненный профиль мог быть пустым, а пустой профиль окно профиля писать отказывается.
        self._trial_results["write_started"] = bool(self._profile_write_to_device(allow_empty=True, verify=False))

    def _trial_restore_done(self, res: dict):
        values = self._trial_backup["values"]
        problems = []
        names = {"empty": "отметка 0 %", "full": "отметка 100 %", "zero_trim": "подгонка нуля",
                 "media_enable": "поправка по виду топлива", "media_air": "«воздух»", "media_cal": "«топливо»"}
        for key, _var, _signed in self.BACKUP_VARS:
            got = self._trial_value(res, f"r_{key}")
            if got != values[key]:
                problems.append(f"{names[key]}: в приборе {got}, а запомнено {values[key]}")
        rewrote_profile = "write_started" in res
        device_crc = self._trial_backup.get("device_crc")
        if rewrote_profile:
            # Пустой профиль прибор считает доверенным, поэтому признак проверяется так же.
            problems.extend(self._trial_profile_verdict(res, "запомненного профиля"))
        elif device_crc is not None:
            # Профиль не перезаписывался: достаточно, что сумма в приборе прежняя.
            crc_now = self._trial_value(res, "crc_now")
            if crc_now != int(device_crc):
                shown = "нет данных" if crc_now is None else f"0x{crc_now:04X}"
                problems.append(f"сумма профиля в приборе {shown}, а до пробы была 0x{int(device_crc):04X}")

        if problems:
            self._trial_set_step("restore", "fail", "; ".join(problems) + ".")
            return

        written = self._trial_dirty_text()
        self._trial_dirty = set()
        # После возврата перезапуск проверяет, что в памяти остались именно исходные настройки.
        self._trial_applied_profile = None
        self._trial_expected = {
            "empty": values["empty"], "full": values["full"], "media_enable": values["media_enable"],
            "media_air": values["media_air"], "media_cal": values["media_cal"],
        }
        if rewrote_profile:
            self._trial_expected.update(
                {"crc": self._profile_calc_crc(), "generation": int(self._profile_generation), "algorithm": 1})
            self._trial_expect_trusted = True
        else:
            if device_crc is not None:
                self._trial_expected["crc"] = int(device_crc)
            status = self._trial_backup.get("device_status")
            self._trial_expect_trusted = status is not None and bool(int(status) & profile_model.STATUS_TRUSTED)

        head = f"Возвращено: {written}. " if written else "Пробная калибровка настройки не меняла, писать было нечего. "
        # Пустой профиль после возврата выглядит как потеря записи, поэтому это называется прямо.
        tail = ""
        if not any(value for name, table in self._trial_backup["profile"].items() if name != "nodes" for value in table):
            tail = " Профиль до пробы был пустым, поэтому в приборе он снова пустой: так и должно быть."
        self._trial_commit_then(
            "restore", "pass",
            head + f"Все настройки совпали с запомненными {self._trial_backup['saved_at']}, эмуляция выключена." + tail)

    # ------------------------------------------------------------------ этап: сохранение

    PERSIST_VARS = (
        ("empty", UdsData.empty_fuel_tank, False),
        ("full", UdsData.full_fuel_tank, False),
        ("media_enable", UdsData.fuel_media_comp_enable, False),
        ("media_air", UdsData.fuel_media_flatcap_air_count, False),
        ("media_cal", UdsData.fuel_media_flatcap_cal_count, False),
        ("crc", VAR_CRC, False),
        ("generation", VAR_GENERATION, False),
        ("algorithm", VAR_ALGORITHM, False),
    )

    def _trial_run_persist(self) -> bool:
        if not self._trial_expected:
            self._trial_set_step(
                "persist", "fail",
                "Сверять нечего: сначала выполните этапы с записью в прибор или возврат настроек.")
            return False
        # Сначала прибор опрашивается, пока не ответит из основной программы. Иначе чтения
        # уйдут в пустоту или в загрузчик, и по ним не понять, что с прибором.
        self._trial_reboot = {"started": None, "deadline": None, "boot_seen": False, "last": "", "elapsed": None}
        ops = [self._op_reset("reset"), self._op_read("boot", VAR_ACTIVE_PROGRAM)]
        self._trial_mark_running(
            "persist",
            f"Перезапускаю прибор и жду, пока он вернётся в основную программу, до "
            f"{self.TRIAL_REBOOT_TIMEOUT_S:.0f} с...")
        return self._trial_start_ops(ops, "_trial_persist_wait")

    def _trial_persist_read_ops(self) -> list[dict]:
        ops = [self._op_read(f"p_{key}", var, signed) for key, var, signed in self.PERSIST_VARS]
        ops += [
            self._op_read("p_status", UdsData.fuel_thermal_profile_status),
            self._op_read("p_emul", UdsData.temperature_emulation_x10, signed=True),
            self._op_read("p_ee", UdsData.eeprom_state),
        ]
        return ops

    def _trial_persist_wait(self, res: dict):
        """Ждёт ответа основной программы после перезапуска и называет, что с прибором, если его нет."""
        ctx = self._trial_reboot
        now = time.monotonic()
        if ctx["started"] is None:
            if res.get("reset") is not True:
                self._trial_set_step(
                    "persist", "fail", f"Команда перезапуска не отправлена ({self._trial_error_text(res, 'reset')}).")
                return
            ctx["started"] = now - self.TRIAL_RESET_WAIT_MS / 1000.0
            ctx["deadline"] = ctx["started"] + self.TRIAL_REBOOT_TIMEOUT_S

        program = self._trial_value(res, "boot")
        if program == 0:
            ctx["elapsed"] = now - ctx["started"]
            self._trial_live_suspend_until = 0.0
            self._trial_mark_running(
                "persist",
                f"Прибор вернулся в основную программу через {ctx['elapsed']:.1f} с. "
                .replace(".", ",", 1) + "Читаю записанное заново...")
            self._trial_start_ops(self._trial_persist_read_ops(), "_trial_persist_done")
            return

        if program == 1:
            ctx["boot_seen"] = True
            ctx["last"] = "отвечает загрузчик"
        elif program is None:
            ctx["last"] = self._trial_error_text(res, "boot")
        else:
            ctx["last"] = f"непонятный тип программы {program}"

        if now < ctx["deadline"]:
            # Пока прибор перезапускается, отсчёты не опрашиваются: запросы только мешали бы.
            self._trial_live_suspend_until = ctx["deadline"]
            self._trial_start_ops(
                [self._op_wait(self.TRIAL_REBOOT_POLL_MS), self._op_read("boot", VAR_ACTIVE_PROGRAM)],
                "_trial_persist_wait")
            return

        self._trial_live_suspend_until = 0.0
        self._invalidate_calibration_session_after_nrc(
            "Калибровка: прибор перезапущен пробной калибровкой. Для дальнейшей записи запустите калибровку заново.")
        timeout = f"{self.TRIAL_REBOOT_TIMEOUT_S:.0f}"
        boot_answer = res.get("boot")
        if program == 1:
            detail = (f"За {timeout} с прибор не вернулся в основную программу: отвечает загрузчик, он не запустил "
                      "основную программу после перезапуска. Выключите и включите питание платы. Если прибор и после "
                      "этого остаётся в загрузчике, залейте прошивку заново через раздел прошивки.")
        elif ctx["boot_seen"]:
            detail = (f"Прибор ответил из загрузчика, потом замолчал ({ctx['last']}) и за {timeout} с так и не "
                      "вернулся в основную программу. Выключите и включите питание платы и сохраните протокол.")
        elif isinstance(boot_answer, tuple) and boot_answer and boot_answer[0] == "nrc":
            detail = f"Прибор после перезапуска отвечает, но отказом: {ctx['last']}. Сохраните протокол."
        else:
            detail = (f"Прибор не отвечает {timeout} с после команды перезапуска: ни основная программа, ни загрузчик. "
                      "Похоже, он завис при перезапуске. Выключите и включите питание платы. Если после этого прибор "
                      "отвечает, сохраните протокол: по нему будет видно, на каком шаге он замолчал.")
        self._trial_set_step("persist", "fail", detail)

    def _trial_persist_done(self, res: dict):
        problems = []
        lines = []
        names = {"empty": "отметка 0 %", "full": "отметка 100 %", "media_enable": "поправка по виду топлива",
                 "media_air": "«воздух»", "media_cal": "«топливо»", "crc": "сумма профиля",
                 "generation": "поколение профиля", "algorithm": "номер алгоритма"}

        # Перезапуск подтверждён ещё при ожидании прибора: чтения идут уже отдельной очередью.
        reboot_started = (self._trial_reboot or {}).get("started") is not None
        if res.get("reset") is not True and not reboot_started:
            problems.append(f"команда перезапуска не отправлена ({self._trial_error_text(res, 'reset')})")

        for key, want in self._trial_expected.items():
            got = self._trial_value(res, f"p_{key}")
            name = names.get(key, key)
            if got is None:
                problems.append(f"{name}: после перезапуска {self._trial_error_text(res, f'p_{key}')}")
            elif got != want:
                problems.append(f"{name}: после перезапуска {got}, а было записано {want}")
            else:
                lines.append(f"{name} {got}")

        emul = self._trial_value(res, "p_emul")
        if emul is None:
            problems.append(f"эмуляция: после перезапуска {self._trial_error_text(res, 'p_emul')}")
        elif emul != TRIAL_EMULATION_OFF_VALUE:
            problems.append("эмуляция температуры пережила перезапуск, а должна гаснуть")

        # Оборванная перезапуском запись видна при включении: прибор сбрасывает повреждённое к заводским.
        ee = self._trial_ee_decode(self._trial_value(res, "p_ee"))
        if ee is None:
            problems.append(f"состояние памяти: после перезапуска {self._trial_error_text(res, 'p_ee')}")
        else:
            warning = eeprom_boot_warning(ee)
            if warning:
                problems.append("после перезапуска: " + warning[0].lower() + warning[1:].rstrip("."))
            if ee["flags"] & EEPROM_FLAG_SPI_ERROR:
                problems.append("после перезапуска микросхема памяти не отвечает")
        if self._trial_expect_trusted:
            status = self._trial_value(res, "p_status")
            if status is None or not (status & profile_model.STATUS_TRUSTED):
                problems.append("после перезапуска прибор не взял профиль в работу")

        # Сессия калибровки на приборе закончилась вместе с перезапуском.
        self._invalidate_calibration_session_after_nrc(
            "Калибровка: прибор перезапущен пробной калибровкой. Для дальнейшей записи запустите калибровку заново.")

        elapsed = (self._trial_reboot or {}).get("elapsed")
        back = (f"Прибор вернулся в основную программу через {elapsed:.1f} с. ".replace(".", ",", 1)
                if elapsed is not None else "")
        if problems:
            self._trial_set_step("persist", "fail", back + "; ".join(problems) + ".")
        else:
            self._trial_set_step(
                "persist", "pass",
                back + "После перезапуска на месте: " + ", ".join(lines) + ". Эмуляция погашена. "
                "Для дальнейшей записи запустите калибровку заново.")

    # ------------------------------------------------------------------ выключение эмуляции

    def _trial_emulation_off_run(self) -> bool:
        ops = [self._trial_emulation_op("w_off", None),
               self._op_read("e_off", UdsData.temperature_emulation_x10, signed=True)]
        self._trial_log_add("info", "Выключаю эмуляцию температуры по кнопке...")
        return self._trial_start_ops(ops, "_trial_emulation_off_done")

    def _trial_emulation_off_done(self, res: dict):
        if res.get("w_off") is True and self._trial_value(res, "e_off") == TRIAL_EMULATION_OFF_VALUE:
            self._trial_status = "Эмуляция температуры выключена, прибор работает по настоящим датчикам."
            self._trial_status_color = self.COLOR_OK
            self._trial_log_add("ok", self._trial_status)
        else:
            self._trial_status = f"Выключить эмуляцию не удалось: {self._trial_error_text(res, 'w_off')}."
            self._trial_status_color = self.COLOR_FAIL
            self._trial_log_add("fail", self._trial_status)
        self.trialChanged.emit()

    # ------------------------------------------------------------------ протокол и показ

    @staticmethod
    def _trial_duration_text(duration) -> str:
        if duration is None:
            return ""
        return f"{float(duration):.1f} с".replace(".", ",")

    def _trial_step_rows(self) -> list[dict]:
        rows = []
        for number, (key, title, hint) in enumerate(self.TRIAL_STEPS, start=1):
            state = self._trial_steps_state.get(key, {"status": "pending", "detail": "", "duration": None})
            word, color = self.STATUS_WORDS.get(state["status"], self.STATUS_WORDS["pending"])
            detail = str(state["detail"])
            rows.append({
                "key": key, "number": number, "title": title, "hint": hint,
                "status": state["status"], "statusText": word, "statusColor": color,
                "detail": detail, "summary": detail.splitlines()[0] if detail else "",
                "duration": self._trial_duration_text(state.get("duration")),
                "current": key == self._trial_auto_current,
            })
        return rows

    def _trial_log_rows(self) -> list[dict]:
        return list(self._trial_log)

    def _trial_summary(self) -> str:
        states = [state["status"] for state in self._trial_steps_state.values()]
        passed = sum(1 for status in states if status == "pass")
        warned = sum(1 for status in states if status == "warn")
        failed = sum(1 for status in states if status == "fail")
        text = f"Пройдено {passed} из {len(states)}"
        if warned:
            text += f", с замечаниями {warned}"
        if failed:
            text += f", не пройдено {failed}"
        return text

    def _trial_save_protocol(self, path: str) -> bool:
        lines = [
            f"Протокол пробной калибровки, {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            f"Прибор 0x{int(self._resolve_calibration_target_sa()) & 0xFF:02X}. {self._trial_summary()}.",
            "",
            "Этапы:",
        ]
        for row in self._trial_step_rows():
            time_text = f", {row['duration']}" if row["duration"] else ""
            lines.append(f"{row['number']:>2}. {row['title']}: {row['statusText']}{time_text}")
            for detail_line in str(row["detail"]).splitlines():
                lines.append(f"    {detail_line}")
        lines += ["", "Журнал:"]
        for entry in self._trial_log:
            indent = "    " if entry["level"] == "detail" else ""
            lines.append(f"{entry['time']:>8}  {indent}{entry['text']}")
        try:
            pathlib.Path(str(path)).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as error:
            self._trial_status = f"Не удалось сохранить протокол: {error}"
            self._trial_status_color = self.COLOR_FAIL
            self.trialChanged.emit()
            return False
        self._trial_status = f"Протокол сохранён: {path}"
        self._trial_status_color = self.COLOR_OK
        self._trial_log_add("ok", self._trial_status)
        self.trialChanged.emit()
        return True
