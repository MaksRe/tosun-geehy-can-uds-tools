"""Пробная калибровка на столе: весь порядок работы до выезда в камеру.

ЗАЧЕМ
Выезд в климатическую камеру стоит дорого и не переделывается. Если что-то в
программе или в приборе отработает неверно, это выяснится только на месте. Здесь
тот же порядок проходится на столе: плата подключена к шине, на каждом контуре
висит по одному постоянному конденсатору, а температуру прибору задаёт эмуляция в
самой прошивке.

ПОЧЕМУ ХВАТАЕТ ОДНОГО КОНДЕНСАТОРА НА КОНТУР
Перепаивать проводки на столе неудобно, поэтому ни один шаг не требует менять
ёмкость. Отметки бака и точки вида топлива программа ставит сама вокруг показания
того конденсатора, что уже подключён, и так, чтобы прибор обязан был выдать
заранее известный результат: уровень 25 % и коэффициент среды 1,100.

Таблицы температурного профиля по одной ёмкости посчитать нельзя: сдвиг и
растяжение показания по одной точке неразличимы. Поэтому их запись и применение
проверяются на проверочном профиле с заранее известными поправками, а сам расчёт
таблиц закреплён автотестами.

ЧТО ПРОВЕРЯЕТСЯ
Не только то, что данные записались, но и то, что прибор их применяет:
- отметки бака: записались, читаются обратно, уровень ровно 25 %;
- вид топлива: точки записались, коэффициент среды сошёлся к 1,100;
- снятие точек: при семи эмулируемых температурах точка попадает в свой узел;
- профиль: записался без потерь, прибор посчитал ту же сумму;
- применение: при десяти температурах итоговый период прибора совпадает с
  расчётом по формулам прошивки до пары отсчётов;
- сохранение: после перезапуска всё записанное на месте, а эмуляция погашена.

КАК УСТРОЕН ОБМЕН
Каждый шаг это очередь простых операций: прочитать, записать, подождать,
вызвать другой раздел и дождаться его. Ответы разбираются здесь же, по номеру
параметра. Итог шага решает отдельный обработчик, когда очередь закончилась.

БЕЗОПАСНОСТЬ
Пробная калибровка перезаписывает настоящую калибровку прибора. Поэтому есть
«Запомнить текущие настройки» до начала и «Вернуть как было» в конце. Запомненное
дополнительно сохраняется в файл.
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

from .contract import AppControllerContract

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


class AppControllerTrialMixin(AppControllerContract):
    TRIAL_REQUEST_GAP_MS = 40
    TRIAL_TIMEOUT_MS = 800
    # После смены эмулируемой температуры: прибор пересчитывает цепочку раз в 50 мс.
    TRIAL_SETTLE_MS = 400
    TRIAL_RESET_WAIT_MS = 4000
    TRIAL_SAMPLES = 5
    TRIAL_PERIOD_TOLERANCE = 3
    TRIAL_LEVEL_TOLERANCE_PERMILLE = 30
    TRIAL_RF_TOLERANCE_X1000 = 15
    TRIAL_RF_TIMEOUT_MS = 30000
    TRIAL_PROFILE_TIMEOUT_MS = 30000
    TRIAL_CHAMBER_TIMEOUT_MS = 15000

    # Отметки бака ставятся вокруг показания конденсатора несимметрично: уровень
    # обязан стать ровно 25 %, а перепутанные местами отметки дали бы 75 %.
    TRIAL_LEVEL_BELOW = 1000
    TRIAL_LEVEL_ABOVE = 3000
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

    COLOR_IDLE = "#64748b"
    COLOR_RUN = "#0f6ab4"
    COLOR_OK = "#16a34a"
    COLOR_WARN = "#d97706"
    COLOR_FAIL = "#dc2626"

    TRIAL_STEPS = (
        ("link", "Прибор на связи, прошивка новая",
         "Подключите плату к шине. Проверка только читает, в приборе ничего не меняет."),
        ("access", "Запись в прибор открыта",
         "Нажмите «Начать калибровку» в шапке окна и дождитесь зелёной надписи о доступе."),
        ("emulation", "Эмуляция температуры работает",
         "Прибор должен поверить, что он при -40 и +85 °C, и затем вернуться к настоящей температуре."),
        ("level", "Отметки бака записываются и применяются",
         "Хватает одного конденсатора на основном контуре. Программа ставит отметки 0 % и 100 % "
         "вокруг его показания так, что уровень обязан стать ровно 25 %."),
        ("media", "Вид топлива записывается и применяется",
         "Хватает одного конденсатора на контуре вида топлива. Программа ставит точки «воздух» и "
         "«топливо» так, что коэффициент среды обязан стать 1,100. Сначала пройдите шаг 4: при пустом "
         "баке коэффициент среды заморожен."),
        ("chamber", "Снятие точек с эмуляцией температуры",
         "Программа сама задаёт прибору все семь температур сетки и снимает точку при каждой. Каждая "
         "обязана попасть в свой узел. Конденсаторы трогать не нужно."),
        ("profile", "Профиль записывается без потерь",
         "Пишет проверочный профиль с крупными поправками и читает его обратно. Таблицы по одному "
         "конденсатору не посчитать: для этого нужны две разные ёмкости."),
        ("apply", "Прибор применяет таблицы правильно",
         "При десяти температурах сверяет итоговый период прибора с расчётом по формулам прошивки. "
         "Нужен пройденный шаг 7."),
        ("persist", "Всё сохраняется после перезагрузки",
         "Перезапускает прибор и читает всё записанное заново. После этого сессию калибровки "
         "нужно запустить снова."),
    )

    STATUS_WORDS = {
        "pending": ("не проверено", "#64748b"),
        "running": ("идёт проверка", "#0f6ab4"),
        "pass": ("пройдено", "#16a34a"),
        "warn": ("есть замечания", "#d97706"),
        "fail": ("не пройдено", "#dc2626"),
    }

    # ------------------------------------------------------------------ состояние

    def _init_trial_state(self):
        """Готовит раздел пробной калибровки. Вызывается один раз при создании контроллера."""
        self._trial_read = ServiceReadDataById()
        self._trial_read.set_byte_order("big")
        self._trial_write = ServiceWriteDataById()
        self._trial_write.set_byte_order("big")

        self._trial_steps_state = {key: {"status": "pending", "detail": ""} for key, _t, _h in self.TRIAL_STEPS}
        self._trial_busy = False
        self._trial_status = "Пробная калибровка не запускалась."
        self._trial_status_color = self.COLOR_IDLE
        self._trial_log: list[str] = []

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
        self._trial_next_op()
        return True

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
            self._trial_wait_timer.start(self.TRIAL_RESET_WAIT_MS)
            return

        if kind in ("await_profile", "await_chamber"):
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
        """Ждёт, пока другой раздел закончит свою очередь."""
        op = self._trial_pending
        if (not self._trial_busy) or op is None or op["kind"] not in ("await_profile", "await_chamber"):
            return

        busy = self._profile_busy if op["kind"] == "await_profile" else self._chamber_busy
        if not busy:
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
            raw = 0
            shift = 0
            for byte_value in body[3:]:
                raw |= byte_value << shift
                shift += 8
            if op["signed"]:
                bits = max(8, int(op["var"].size) * 8)
                limit = 1 << bits
                raw &= limit - 1
                value = raw - limit if raw >= (limit >> 1) else raw
            else:
                value = raw
            self._trial_finish_op(int(value))
            return

        if body[0] != 0x6E or did not in answered:
            return
        self._trial_finish_op(True)

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

    # ------------------------------------------------------------------ состояние шагов

    def _trial_title(self, key: str) -> str:
        for step_key, title, _hint in self.TRIAL_STEPS:
            if step_key == key:
                return title
        return key

    def _trial_log_line(self, text: str):
        self._trial_log.append(f"{datetime.now().strftime('%H:%M:%S')}  {text}")
        if len(self._trial_log) > 500:
            self._trial_log = self._trial_log[-500:]

    def _trial_set_step(self, key: str, status: str, detail: str):
        """Записывает итог шага, строку хода работы и строку протокола."""
        self._trial_steps_state[key] = {"status": status, "detail": str(detail)}
        word, color = self.STATUS_WORDS.get(status, self.STATUS_WORDS["pending"])
        title = self._trial_title(key)
        self._trial_status = f"{title}: {word}."
        self._trial_status_color = color
        self._trial_log_line(f"{title}: {word}. {detail}")
        self.trialChanged.emit()

    def _trial_mark_running(self, key: str, text: str):
        self._trial_steps_state[key] = {"status": "running", "detail": str(text)}
        self._trial_status = str(text)
        self._trial_status_color = self.COLOR_RUN
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
            "Запись закрыта. Нажмите «Начать калибровку» в шапке окна и повторите шаг 2.")
        return False

    def _trial_reset_steps(self):
        for key, _title, _hint in self.TRIAL_STEPS:
            self._trial_steps_state[key] = {"status": "pending", "detail": ""}
        self._trial_expected = {}
        self._trial_level_reading = None
        self._trial_media_points = None
        self._trial_chamber_plan = []
        self._trial_chamber_index = 0
        self._trial_chamber_outcome = None
        self._trial_applied_profile = None
        self._trial_status = "Отметки шагов сброшены."
        self._trial_status_color = self.COLOR_IDLE
        self.trialChanged.emit()

    # ------------------------------------------------------------------ шаг 1: связь

    def _trial_run_link(self) -> bool:
        ops = [
            self._op_read("status", UdsData.fuel_thermal_profile_status),
            self._op_read("emul", UdsData.temperature_emulation_x10, signed=True),
            self._op_read("legacy", VAR_LEGACY_K1),
            self._op_read("fuel_t", UdsData.raw_temperature, signed=True),
            self._op_read("board_t", UdsData.raw_board_temperature, signed=True),
        ]
        self._trial_mark_running("link", "Проверяю связь и версию прошивки...")
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

        summary = (f"температура топлива {self._trial_temp_text(self._trial_value(res, 'fuel_t'))}, "
                   f"платы {self._trial_temp_text(self._trial_value(res, 'board_t'))}")
        if problems:
            self._trial_set_step("link", "fail", "; ".join(problems) + ".")
        elif notes:
            self._trial_set_step("link", "warn", summary + "; " + "; ".join(notes) + ".")
        else:
            self._trial_set_step("link", "pass", summary + ", прошивка новая, эмуляция выключена.")

    # ------------------------------------------------------------------ шаг 2: доступ

    def _trial_run_access(self) -> bool:
        if self._trial_write_ready():
            sa = int(self._resolve_calibration_target_sa()) & 0xFF
            self._trial_set_step("access", "pass", f"Сессия калибровки запущена, запись в прибор 0x{sa:02X} открыта.")
            return True
        if not bool(self._calibration_active):
            reason = "сценарий калибровки не запущен"
        elif not bool(self._calibration_session_ready):
            reason = "сессия ещё не подтверждена прибором"
        else:
            reason = "Security Access открыт не для выбранного прибора"
        self._trial_set_step("access", "fail", f"Запись закрыта: {reason}. Нажмите «Начать калибровку» в шапке окна.")
        return False

    # ------------------------------------------------------------------ шаг 3: эмуляция

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
        self._trial_mark_running("emulation", "Задаю прибору -40 °C, затем +85 °C...")
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

    # ------------------------------------------------------------------ шаг 4: отметки бака

    def _trial_level_marks(self, compensated: int) -> tuple[int, int]:
        """Отметки 0 % и 100 % вокруг показания конденсатора, при которых уровень ровно 25 %."""
        return int(compensated) - self.TRIAL_LEVEL_BELOW, int(compensated) + self.TRIAL_LEVEL_ABOVE

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
        ops += [self._op_read("cur_full", UdsData.full_fuel_tank), self._op_read("tank_model", VAR_TANK_MODEL)]
        self._trial_mark_running("level", "Снимаю показание конденсатора на основном контуре...")
        return self._trial_start_ops(ops, "_trial_level_stage2")

    def _trial_level_stage2(self, res: dict):
        raw = self._trial_mean(res, "raw", self.TRIAL_SAMPLES)
        comp = self._trial_mean(res, "comp", self.TRIAL_SAMPLES)
        if raw is None or comp is None:
            self._trial_set_step(
                "level", "fail",
                "Прибор не отдал период основного контура. Проверьте, что конденсатор подключён и шина работает.")
            return

        empty, full = self._trial_level_marks(comp)
        if empty < 1 or full > 0xFFFF:
            self._trial_set_step(
                "level", "fail",
                f"Показание {comp} слишком близко к краю шкалы, отметки вокруг него не помещаются. "
                "Возьмите конденсатор другого номинала.")
            return

        self._trial_level_reading = {
            "raw": raw, "comp": comp, "empty": empty, "full": full,
            "tank_model": self._trial_value(res, "tank_model"),
        }
        ops = self._trial_level_order(self._trial_value(res, "cur_full"), empty, full)
        ops += [
            self._op_wait(self.TRIAL_SETTLE_MS),
            self._op_read("rb_empty", UdsData.empty_fuel_tank),
            self._op_read("rb_full", UdsData.full_fuel_tank),
        ]
        ops += [self._op_read(f"lvl{index}", UdsData.raw_fuel_level, signed=True)
                for index in range(self.TRIAL_SAMPLES)]
        self._trial_mark_running("level", f"Показание {comp}. Записываю отметки {empty} и {full}...")
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
        expected = self.TRIAL_LEVEL_EXPECTED_PERMILLE
        model = reading["tank_model"]
        if model == 0:
            if level is None:
                problems.append("прибор не отдал уровень")
            elif abs(level - expected) > self.TRIAL_LEVEL_TOLERANCE_PERMILLE:
                problems.append(f"уровень {level / 10:.1f} %, а по отметкам вокруг конденсатора должен быть "
                                f"{expected / 10:.1f} %")
            else:
                notes.append(f"уровень {level / 10:.1f} % при расчётных {expected / 10:.1f} %")
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
            self._trial_set_step("level", "warn", text + "; " + warning + ".")
        else:
            self._trial_set_step("level", "pass", text + ".")

    # ------------------------------------------------------------------ шаг 5: вид топлива

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
        self._trial_mark_running("media", "Снимаю показание конденсатора на контуре вида топлива...")
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
            self._trial_set_step(
                "media", "fail",
                f"Уровень {level / 10:.1f} % ниже порога заморозки {freeze} %, коэффициент среды не "
                "обновляется. Сначала пройдите шаг 4: он ставит уровень 25 %.")
            return

        air, cal = self._trial_media_points_for(flatcap)
        if air < 1:
            self._trial_set_step(
                "media", "fail",
                f"Показание {flatcap} слишком мало для проверки: нужен конденсатор, у которого показание "
                f"больше {self.TRIAL_MEDIA_SPAN * self.TRIAL_MEDIA_TARGET_X1000 // 1000} отсчётов.")
            return

        self._trial_media_points = {"flatcap": flatcap, "air": air, "cal": cal}
        ops = [
            self._op_write("w_air", UdsData.fuel_media_flatcap_air_count, air),
            self._op_write("w_cal", UdsData.fuel_media_flatcap_cal_count, cal),
            self._op_write("w_en", UdsData.fuel_media_comp_enable, 1),
            self._op_wait(self.TRIAL_SETTLE_MS),
            self._op_read("rb_air", UdsData.fuel_media_flatcap_air_count),
            self._op_read("rb_cal", UdsData.fuel_media_flatcap_cal_count),
            self._op_read("rb_en", UdsData.fuel_media_comp_enable),
        ]
        self._trial_mark_running("media", f"Показание {flatcap}. Записываю «воздух» = {air} и «топливо» = {cal}...")
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
        self._trial_mark_running("media", "Точки записаны. Жду, пока коэффициент среды сойдётся к 1,100...")
        self._trial_start_ops([self._op_read("rf", UdsData.fuel_media_rf_x1000), self._op_wait(500)],
                              "_trial_media_rf_poll")

    def _trial_media_rf_poll(self, res: dict):
        points = self._trial_media_points
        target = self.TRIAL_MEDIA_TARGET_X1000
        rf = self._trial_value(res, "rf")
        if rf is not None and abs(rf - target) <= self.TRIAL_RF_TOLERANCE_X1000:
            self._trial_set_step(
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

    # ------------------------------------------------------------------ шаг 6: снятие точек

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
            f"Температура {chamber_fit.node_text(node)}: снимаю точку "
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
            status, detail = self._trial_chamber_outcome
            self._trial_set_step("chamber", "fail", detail + " Эмуляцию после снятия выключить не удалось.")

    def _trial_chamber_finish(self, res: dict):
        status, detail = self._trial_chamber_outcome
        if res.get("emul_off") is not True:
            status = "fail"
            detail += f" Эмуляцию после снятия выключить не удалось ({self._trial_error_text(res, 'emul_off')})."
        self._trial_set_step("chamber", status, detail)

    def _trial_chamber_progress(self) -> str:
        total = len(self._trial_chamber_plan)
        if total == 0:
            return ""
        if self._trial_chamber_index >= total:
            return f"Сняты все {total} точек"
        return f"Точка {self._trial_chamber_index + 1} из {total}"

    # ------------------------------------------------------------------ шаг 7: запись профиля

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
        self._trial_mark_running("profile", "Пишу проверочный профиль и читаю его обратно...")
        return self._trial_start_ops(ops, "_trial_profile_done")

    def _trial_profile_load_call(self):
        profile = profile_model.build_test_profile(self._profile_values["nodes"])
        for name, values in profile.items():
            self._profile_values[name] = [int(value) for value in values]
        self.profileChanged.emit()
        self._trial_results["loaded"] = True

    def _trial_profile_write_call(self):
        self._trial_results["write_started"] = bool(self._profile_write_to_device())

    def _trial_profile_verify_call(self):
        self._trial_results["verify_started"] = bool(self._profile_verify_on_device())

    def _trial_profile_status_call(self):
        self._trial_results["write_status"] = str(self._profile_status)

    def _trial_profile_verdict(self, res: dict, what: str) -> list[str]:
        """Общая проверка записи и сверки профиля для шага 7 и возврата настроек."""
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

        # Снимок того, что лежит в приборе: по нему шаг 8 предсказывает результат,
        # даже если таблицы на экране потом кто-то поправит.
        self._trial_applied_profile = {name: list(values) for name, values in self._profile_values.items()}
        self._trial_expected.update({
            "crc": self._profile_calc_crc(),
            "generation": int(self._profile_generation),
            "algorithm": 1,
        })
        self._trial_set_step(
            "profile", "pass",
            f"Проверочный профиль записан: все семь таблиц совпали с прочитанными из прибора, сумма "
            f"0x{self._profile_calc_crc():04X} сошлась, прибор взял таблицы в работу. В приборе остался "
            "проверочный профиль, в конце верните настройки.")

    # ------------------------------------------------------------------ шаг 8: применение

    def _trial_run_apply(self) -> bool:
        if not self._trial_require_write("apply"):
            return False
        if self._trial_applied_profile is None:
            self._trial_set_step(
                "apply", "fail",
                "Сначала пройдите шаг 7: он записывает проверочный профиль, по которому идёт сверка.")
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
        self._trial_mark_running("apply", "Прохожу десять температур и сверяю итоговый период с расчётом...")
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

            lines.append(f"{place}: сырой {raw_a}, итог прибора {comp}, по расчёту {expected_comp}")

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

    # ------------------------------------------------------------------ шаг 9: сохранение

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
            self._trial_set_step("persist", "fail", "Сверять нечего: сначала пройдите шаги 4, 5 и 7.")
            return False
        ops = [self._op_reset("reset")]
        ops += [self._op_read(f"p_{key}", var, signed) for key, var, signed in self.PERSIST_VARS]
        ops += [
            self._op_read("p_status", UdsData.fuel_thermal_profile_status),
            self._op_read("p_emul", UdsData.temperature_emulation_x10, signed=True),
        ]
        self._trial_mark_running("persist", "Перезапускаю прибор и читаю записанное заново...")
        return self._trial_start_ops(ops, "_trial_persist_done")

    def _trial_persist_done(self, res: dict):
        problems = []
        lines = []
        names = {"empty": "отметка 0 %", "full": "отметка 100 %", "media_enable": "поправка по виду топлива",
                 "media_air": "«воздух»", "media_cal": "«топливо»", "crc": "сумма профиля",
                 "generation": "поколение профиля", "algorithm": "номер алгоритма"}

        if res.get("reset") is not True:
            problems.append(f"команда перезапуска не отправлена ({self._trial_error_text(res, 'reset')})")

        for key, want in self._trial_expected.items():
            got = self._trial_value(res, f"p_{key}")
            name = names.get(key, key)
            if got is None:
                problems.append(f"{name}: прибор после перезапуска не ответил")
            elif got != want:
                problems.append(f"{name}: после перезапуска {got}, а было записано {want}")
            else:
                lines.append(f"{name} {got}")

        emul = self._trial_value(res, "p_emul")
        if emul != TRIAL_EMULATION_OFF_VALUE:
            problems.append("эмуляция температуры пережила перезапуск, а должна гаснуть")
        if "crc" in self._trial_expected:
            status = self._trial_value(res, "p_status")
            if status is None or not (status & profile_model.STATUS_TRUSTED):
                problems.append("после перезапуска прибор не взял профиль в работу")

        # Сессия калибровки на приборе закончилась вместе с перезапуском.
        self._invalidate_calibration_session_after_nrc(
            "Калибровка: прибор перезапущен пробной калибровкой. Для дальнейшей записи запустите калибровку заново.")

        if problems:
            self._trial_set_step("persist", "fail", "; ".join(problems) + ".")
        else:
            self._trial_set_step(
                "persist", "pass",
                "После перезапуска на месте: " + ", ".join(lines) + ". Эмуляция погашена. "
                "Для дальнейшей записи запустите калибровку заново.")

    # ------------------------------------------------------------------ запомнить и вернуть

    BACKUP_VARS = (
        ("empty", UdsData.empty_fuel_tank, False),
        ("full", UdsData.full_fuel_tank, False),
        ("zero_trim", UdsData.fuel_zero_trim_count, True),
        ("media_enable", UdsData.fuel_media_comp_enable, False),
        ("media_air", UdsData.fuel_media_flatcap_air_count, False),
        ("media_cal", UdsData.fuel_media_flatcap_cal_count, False),
    )

    def _trial_backup_run(self) -> bool:
        ops = [self._op_read(f"b_{key}", var, signed) for key, var, signed in self.BACKUP_VARS]
        ops += [
            self._op_call("profile_started", "_trial_backup_profile_call"),
            self._op_await("await_profile", "profile_read", self.TRIAL_PROFILE_TIMEOUT_MS),
        ]
        self._trial_status = "Запоминаю текущие настройки прибора..."
        self._trial_status_color = self.COLOR_RUN
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

        if missing or res.get("profile_started") is not True or res.get("profile_read") is not True \
                or str(self._profile_status).startswith("Операция прервана"):
            self._trial_status = "Не удалось запомнить настройки: прибор отдал не всё. Пробную калибровку не начинайте."
            self._trial_status_color = self.COLOR_FAIL
            self._trial_log_line(self._trial_status)
            self.trialChanged.emit()
            return

        self._trial_backup = {
            "values": values,
            "profile": {name: list(table) for name, table in self._profile_values.items()},
            "generation": int(self._profile_generation),
            "saved_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "node": int(self._resolve_calibration_target_sa()) & 0xFF,
        }

        path_text = ""
        try:
            folder = self._resolve_calibration_backup_all_nodes_directory()
            path = pathlib.Path(folder) / (
                f"trial_backup_0x{self._trial_backup['node']:02X}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            path.write_text(json.dumps(self._trial_backup, ensure_ascii=False, indent=2), encoding="utf-8")
            path_text = f" Копия в файле {path}."
        except Exception as error:
            path_text = f" Файл копии записать не удалось: {error}."

        self._trial_status = "Текущие настройки запомнены." + path_text
        self._trial_status_color = self.COLOR_OK
        self._trial_log_line(self._trial_status)
        self.trialChanged.emit()

    def _trial_restore_run(self) -> bool:
        if not self._trial_backup:
            self._trial_status = "Возвращать нечего: настройки перед началом не запоминались."
            self._trial_status_color = self.COLOR_FAIL
            self.trialChanged.emit()
            return False
        if not self._trial_write_ready():
            self._trial_status = "Запись закрыта. Нажмите «Начать калибровку» и повторите возврат."
            self._trial_status_color = self.COLOR_FAIL
            self.trialChanged.emit()
            return False
        ops = [
            self._trial_emulation_op("emul_off", None),
            self._op_read("cur_full", UdsData.full_fuel_tank),
        ]
        self._trial_status = "Возвращаю настройки прибора..."
        self._trial_status_color = self.COLOR_RUN
        return self._trial_start_ops(ops, "_trial_restore_stage2")

    def _trial_restore_stage2(self, res: dict):
        values = self._trial_backup["values"]
        ops = self._trial_level_order(self._trial_value(res, "cur_full"), values["empty"], values["full"])
        ops += [
            self._op_write("w_zero_trim", UdsData.fuel_zero_trim_count, values["zero_trim"]),
            self._op_write("w_media_air", UdsData.fuel_media_flatcap_air_count, values["media_air"]),
            self._op_write("w_media_cal", UdsData.fuel_media_flatcap_cal_count, values["media_cal"]),
            self._op_write("w_media_enable", UdsData.fuel_media_comp_enable, values["media_enable"]),
            self._op_call("profile_loaded", "_trial_restore_profile_load_call"),
            self._op_call("write_started", "_trial_restore_profile_write_call"),
            self._op_await("await_profile", "written", self.TRIAL_PROFILE_TIMEOUT_MS),
            self._op_call("write_status", "_trial_profile_status_call"),
            self._op_call("verify_started", "_trial_profile_verify_call"),
            self._op_await("await_profile", "verified", self.TRIAL_PROFILE_TIMEOUT_MS),
            self._op_read("status", UdsData.fuel_thermal_profile_status),
        ]
        ops += [self._op_read(f"r_{key}", var, signed) for key, var, signed in self.BACKUP_VARS]
        self._trial_start_ops(ops, "_trial_restore_done")

    def _trial_restore_profile_load_call(self):
        for name, table in self._trial_backup["profile"].items():
            self._profile_values[name] = [int(value) for value in table]
        self._profile_generation = int(self._trial_backup["generation"])
        self.profileChanged.emit()
        self._trial_results["profile_loaded"] = True

    def _trial_restore_profile_write_call(self):
        # Запомненный профиль мог быть пустым, а пустой профиль окно профиля писать отказывается.
        self._trial_results["write_started"] = bool(self._profile_write_to_device(allow_empty=True))

    def _trial_restore_done(self, res: dict):
        values = self._trial_backup["values"]
        problems = []
        for key, _var, _signed in self.BACKUP_VARS:
            got = self._trial_value(res, f"r_{key}")
            if got != values[key]:
                problems.append(f"{key}: в приборе {got}, а запомнено {values[key]}")
        # Пустой профиль прибор считает доверенным, поэтому признак проверяется так же.
        problems.extend(self._trial_profile_verdict(res, "запомненного профиля"))

        if problems:
            self._trial_status = "Вернуть всё не удалось: " + "; ".join(problems) + "."
            self._trial_status_color = self.COLOR_FAIL
        else:
            self._trial_status = (f"Настройки на {self._trial_backup['saved_at']} возвращены и прочитаны обратно, "
                                  "эмуляция выключена.")
            self._trial_status_color = self.COLOR_OK
            self._trial_expected = {}
            self._trial_applied_profile = None
        self._trial_log_line(self._trial_status)
        self.trialChanged.emit()

    def _trial_emulation_off_run(self) -> bool:
        ops = [self._trial_emulation_op("w_off", None),
               self._op_read("e_off", UdsData.temperature_emulation_x10, signed=True)]
        return self._trial_start_ops(ops, "_trial_emulation_off_done")

    def _trial_emulation_off_done(self, res: dict):
        if res.get("w_off") is True and self._trial_value(res, "e_off") == TRIAL_EMULATION_OFF_VALUE:
            self._trial_status = "Эмуляция температуры выключена, прибор работает по настоящим датчикам."
            self._trial_status_color = self.COLOR_OK
        else:
            self._trial_status = f"Выключить эмуляцию не удалось: {self._trial_error_text(res, 'w_off')}."
            self._trial_status_color = self.COLOR_FAIL
        self._trial_log_line(self._trial_status)
        self.trialChanged.emit()

    # ------------------------------------------------------------------ протокол и показ

    def _trial_step_rows(self) -> list[dict]:
        rows = []
        for number, (key, title, hint) in enumerate(self.TRIAL_STEPS, start=1):
            state = self._trial_steps_state.get(key, {"status": "pending", "detail": ""})
            word, color = self.STATUS_WORDS.get(state["status"], self.STATUS_WORDS["pending"])
            rows.append({
                "key": key, "number": number, "title": title, "hint": hint,
                "status": state["status"], "statusText": word, "statusColor": color,
                "detail": state["detail"],
            })
        return rows

    def _trial_summary(self) -> str:
        states = [state["status"] for state in self._trial_steps_state.values()]
        passed = sum(1 for status in states if status == "pass")
        failed = sum(1 for status in states if status == "fail")
        text = f"Пройдено {passed} из {len(states)}"
        if failed:
            text += f", не пройдено {failed}"
        return text

    def _trial_save_protocol(self, path: str) -> bool:
        lines = [
            f"Протокол пробной калибровки, {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            f"Прибор 0x{int(self._resolve_calibration_target_sa()) & 0xFF:02X}. {self._trial_summary()}.",
            "",
        ]
        for row in self._trial_step_rows():
            lines.append(f"{row['number']}. {row['title']}: {row['statusText']}")
            if row["detail"]:
                for detail_line in str(row["detail"]).splitlines():
                    lines.append(f"   {detail_line}")
        lines += ["", "Ход работы:"] + list(self._trial_log)
        try:
            pathlib.Path(str(path)).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as error:
            self._trial_status = f"Не удалось сохранить протокол: {error}"
            self._trial_status_color = self.COLOR_FAIL
            self.trialChanged.emit()
            return False
        self._trial_status = f"Протокол сохранён: {path}"
        self._trial_status_color = self.COLOR_OK
        self.trialChanged.emit()
        return True
