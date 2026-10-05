"""Тестовый режим прогона: камера на столе.

ЗАЧЕМ
Перед выездом в камеру нужно убедиться, что весь путь работает: точки
снимаются, журнал сохраняется, таблицы считаются, профиль пишется в прибор и
сверяется. Камера для этого не нужна. Прибор умеет эмулировать температуру
(параметр 0x0061): обе его температуры, платы и топлива, показывают заданное
число. Оператор кладёт плату на стол, подключает эталоны и проходит все узлы
сетки, задавая температуру из программы.

ЧТО ДАЁТ РЕЖИМ
- Кнопки узлов сетки и поле для любой температуры. Перед записью программа
  сама открывает доступ, после записи ждёт, пока прибор покажет заданное.
- Обход всех узлов с текущей пометкой: задать температуру, дождаться, записать
  точку, следующий узел. В конце эмуляция выключается.
- Имитация ухода. Настоящая плата на столе с температурой не меняется, и
  таблицы вышли бы нулевыми: проверять было бы нечего. Имитация добавляет к
  периодам точки известный уход, а после расчёта программа сверяет, что
  таблицы платы его восстановили.

Точки тестового режима помечаются в журнале как пробные, но, в отличие от
пробной калибровки, проходят весь путь: автосохранение, расчёт и запись в
прибор. Это и есть то, что режим проверяет. Писать такие таблицы можно только
пока режим включён.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer

import chamber_fit
from uds.data_identifiers import UdsData
from uds.services.write_data_by_id import ServiceWriteDataById

from .bus_guard import background_request_recent, note_background_request, uds_exchange_busy
from .contract import AppControllerContract

# Значение эмуляции «выключена» на проводе.
EMULATION_OFF_WIRE = 0x8000


def _temp_text(value_x10) -> str:
    """Температура в десятых градуса словами, с запятой."""
    if value_x10 is None:
        return "настоящая"
    return f"{int(value_x10) / 10:+.1f} °C".replace(".", ",")


class AppControllerChamberTestMixin(AppControllerContract):
    CHAMBER_TEST_TICK_MS = 150
    # Ожидание доступа, ответа на запись и того, что прибор покажет заданное, с.
    CHAMBER_TEST_ACCESS_TIMEOUT_S = 20.0
    CHAMBER_TEST_WRITE_TIMEOUT_S = 0.8
    CHAMBER_TEST_WRITE_RETRIES = 2
    CHAMBER_TEST_SETTLE_TIMEOUT_S = 10.0
    # Сколько показаний каждой температуры нужно, чтобы считать её установившейся.
    CHAMBER_TEST_SETTLE_SAMPLES = 2
    # Допуск совпадения показанной температуры с заданной, десятые градуса.
    CHAMBER_TEST_SETTLE_TOLERANCE_X10 = 1
    # Сколько ждать записи точки при обходе, с.
    CHAMBER_TEST_CAPTURE_TIMEOUT_S = 25.0

    # Имитация ухода платы: (растяжение, ppm на °C; сдвиг, отсчёты на °C) от +25 °C.
    # Контуры уходят по-разному, как у настоящей платы: у каждого своя электроника.
    CHAMBER_TEST_DRIFT = {
        "main": (80.0, 0.30),
        "media": (-60.0, -0.50),
    }
    # Допуск сверки восстановленных таблиц с заложенным уходом. Шум живых
    # показаний на столе даёт свой предел точности, порог с запасом.
    CHAMBER_TEST_CHECK_GAIN_PPM = 400.0
    CHAMBER_TEST_CHECK_OFFSET = 3.0

    # ------------------------------------------------------------------ состояние

    def _init_chamber_test_state(self):
        """Готовит тестовый режим. Вызывается один раз при создании контроллера."""
        self._chamber_test_write_service = ServiceWriteDataById()
        self._chamber_test_write_service.set_byte_order("big")

        self._chamber_test_mode = False
        self._chamber_test_drift_on = True
        # Что сейчас задано прибору: число в десятых градуса, None - эмуляция выключена.
        self._chamber_test_emulation = None
        self._chamber_test_target = None
        # Шаг смены температуры: "", "access", "write", "settle".
        self._chamber_test_stage = ""
        self._chamber_test_deadline = 0.0
        self._chamber_test_pending = False
        self._chamber_test_pending_s = 0.0
        self._chamber_test_attempt = 0
        self._chamber_test_status = "Тестовый режим выключен."
        self._chamber_test_color = "#64748b"

        # Обход узлов: оставшиеся узлы, текущий шаг и сколько точек было до записи.
        self._chamber_test_walk: list[int] = []
        self._chamber_test_walk_stage = ""
        self._chamber_test_walk_points = 0
        self._chamber_test_walk_deadline = 0.0
        self._chamber_test_walk_total = 0

        self._chamber_test_check_text = ""
        self._chamber_test_check_color = "#64748b"

        self._chamber_test_timer = QTimer(self)
        self._chamber_test_timer.setInterval(self.CHAMBER_TEST_TICK_MS)
        self._chamber_test_timer.timeout.connect(self._on_chamber_test_tick)

    def _chamber_test_set(self, text: str, color: str):
        """Строка хода тестового режима и уведомление окну."""
        self._chamber_test_status = str(text)
        self._chamber_test_color = str(color)
        self.chamberChanged.emit()

    def _chamber_test_busy(self) -> bool:
        """Идёт ли смена температуры или обход узлов."""
        return bool(self._chamber_test_stage) or bool(self._chamber_test_walk_stage)

    # ------------------------------------------------------------------ режим

    def _chamber_test_set_mode(self, enabled: bool) -> bool:
        """Включает или выключает тестовый режим. При выключении эмуляция гасится."""
        value = bool(enabled)
        if value == self._chamber_test_mode:
            return True
        if value and bool(getattr(self, "_trial_busy", False)):
            self._chamber_test_set("Идёт пробная калибровка: у неё своя эмуляция температуры.", "#d97706")
            return False
        self._chamber_test_mode = value
        if value:
            self._chamber_test_set(
                "Тестовый режим включён: точки помечаются как пробные. Задайте температуру кнопкой узла.",
                "#b45309")
            return True

        self._chamber_test_walk = []
        self._chamber_test_walk_stage = ""
        if self._chamber_test_emulation is not None or self._chamber_test_stage:
            # Режим выключают, а прибор остался бы на поддельной температуре.
            self._chamber_test_stage = ""
            self._chamber_test_start_set(None, force=True)
        else:
            self._chamber_test_set("Тестовый режим выключен.", "#64748b")
        return True

    def _chamber_test_set_drift(self, enabled: bool):
        """Включает имитацию ухода для следующих точек."""
        self._chamber_test_drift_on = bool(enabled)
        self.chamberChanged.emit()

    # ------------------------------------------------------------------ имитация ухода

    def _chamber_test_drift_counts(self, channel: str, value: int, board_temp_x10: int) -> int:
        """Период с добавленным уходом при заданной температуре платы."""
        gain_per_c, offset_per_c = self.CHAMBER_TEST_DRIFT[channel]
        delta_c = (int(board_temp_x10) - chamber_fit.REFERENCE_X10) / 10.0
        gain = gain_per_c * delta_c / 1_000_000.0
        return int(round(int(value) * (1.0 + gain) + offset_per_c * delta_c))

    def _chamber_test_drift_active(self) -> bool:
        return bool(self._chamber_test_mode) and bool(self._chamber_test_drift_on)

    def _chamber_test_apply_drift(self, point: dict) -> dict:
        """Добавляет к периодам точки имитацию ухода, если она включена."""
        if not self._chamber_test_drift_active():
            return point
        board = int(point["board_temp_x10"])
        result = dict(point)
        result["main"] = self._chamber_test_drift_counts("main", point["main"], board)
        if point.get("media") is not None:
            result["media"] = self._chamber_test_drift_counts("media", point["media"], board)
        return result

    def _chamber_test_expected_tables(self) -> dict:
        """Какие таблицы платы должен дать расчёт по заложенному уходу.

        Имитация растягивает период в (1 + g) раз и сдвигает на o отсчётов. Ступень
        платы должна вернуть растяжение g и сдвиг -o: тогда прибор снимет уход ровно.
        """
        expected = {}
        for channel, (gain_per_c, offset_per_c) in self.CHAMBER_TEST_DRIFT.items():
            rows = []
            for node in chamber_fit.NODES_X10:
                delta_c = (node - chamber_fit.REFERENCE_X10) / 10.0
                rows.append((-offset_per_c * delta_c, gain_per_c * delta_c))
            expected[channel] = rows
        return expected

    def _chamber_test_after_compute(self, result: dict):
        """Сверяет посчитанные таблицы платы с заложенным уходом."""
        if not self._chamber_test_drift_active():
            self._chamber_test_check_text = ""
            return
        if result.get("одна_ёмкость"):
            self._chamber_test_check_single(result)
            return
        expected = self._chamber_test_expected_tables()
        parts = []
        failed = False
        missing = []
        for channel, key, title in (("main", "ступень_платы", "основной"),
                                    ("media", "ступень_платы_вида", "вид топлива")):
            table = result.get(key) or []
            if len(table) != len(chamber_fit.NODES_X10):
                missing.append(title)
                continue
            worst_gain = max(abs(float(got[1]) - want[1]) for got, want in zip(table, expected[channel]))
            worst_offset = max(abs(float(got[0]) - want[0]) for got, want in zip(table, expected[channel]))
            parts.append(f"{title}: растяжение ±{worst_gain:.0f} ppm, сдвиг ±{worst_offset:.1f}".replace(".", ","))
            if worst_gain > self.CHAMBER_TEST_CHECK_GAIN_PPM or worst_offset > self.CHAMBER_TEST_CHECK_OFFSET:
                failed = True

        if not parts:
            self._chamber_test_check_text = "Сверка с имитацией: таблицы платы ещё не посчитаны."
            self._chamber_test_check_color = "#64748b"
            return
        tail = f"; не посчитан {', '.join(missing)}" if missing else ""
        if failed:
            self._chamber_test_check_text = (
                "Сверка с имитацией НЕ ПРОЙДЕНА: расчёт не восстановил заложенный уход ("
                + "; ".join(parts) + tail + "). Все точки должны быть сняты с включённой имитацией.")
            self._chamber_test_check_color = "#dc2626"
        else:
            self._chamber_test_check_text = (
                "Сверка с имитацией пройдена: таблицы платы восстановили заложенный уход ("
                + "; ".join(parts) + tail + ").")
            self._chamber_test_check_color = "#16a34a" if not missing else "#d97706"

    def _chamber_test_check_single(self, result: dict):
        """Сверка для одной ёмкости: после поправки показание в каждом узле равно опорному.

        Заложенный уход по одной ёмкости на сдвиг и растяжение не разделить, поэтому
        сравнивать таблицу с ним бессмысленно. Проверяется то, что такая таблица
        обязана давать: при этой ёмкости прибор показывает одно и то же при любой
        температуре.
        """
        parts = []
        failed = False
        for channel, key, title in (("main", "ступень_платы", "основной"),
                                    ("media", "ступень_платы_вида", "вид топлива")):
            table = result.get(key) or []
            by_node: dict[int, list[int]] = {}
            for point in self._chamber_points:
                node = chamber_fit.nearest_node(point["board_temp_x10"])
                if node is not None and point.get(channel) is not None:
                    by_node.setdefault(node, []).append(point[channel])
            if len(table) != len(chamber_fit.NODES_X10) or chamber_fit.REFERENCE_X10 not in by_node:
                continue
            reference = sum(by_node[chamber_fit.REFERENCE_X10]) / len(by_node[chamber_fit.REFERENCE_X10])
            worst = max(abs(chamber_fit.apply_board_table(sum(values) / len(values), table, node) - reference)
                        for node, values in by_node.items())
            parts.append(f"{title}: после поправки отличие от опорного {worst:.1f} отсч.".replace(".", ","))
            failed = failed or worst > self.CHAMBER_TEST_CHECK_OFFSET
        if not parts:
            self._chamber_test_check_text = "Сверка с имитацией: таблицы платы ещё не посчитаны."
            self._chamber_test_check_color = "#64748b"
            return
        verdict = "НЕ ПРОЙДЕНА" if failed else "пройдена"
        self._chamber_test_check_text = (
            f"Сверка с имитацией (одна ёмкость) {verdict}: " + "; ".join(parts)
            + ". Разделить уход на сдвиг и растяжение по одной ёмкости нельзя, это проверяется только вторым эталоном.")
        self._chamber_test_check_color = "#dc2626" if failed else "#16a34a"

    # ------------------------------------------------------------------ смена температуры

    def _chamber_test_problem(self) -> str:
        """Причина, по которой температуру сейчас задать нельзя, или пустая строка."""
        if not self._can.is_connect or not self._can.is_trace:
            return "нет связи: подключите адаптер и включите трассировку"
        if bool(getattr(self, "_trial_busy", False)):
            return "идёт пробная калибровка"
        if self._chamber_busy or self._chamber_capture_waiting:
            return "идёт снятие точки"
        if getattr(self, "_chamber_chain_stage", ""):
            return "идёт запись профиля в прибор"
        return ""

    def _chamber_test_start_set(self, target_x10, force: bool = False) -> bool:
        """Начинает смену эмулируемой температуры. None выключает эмуляцию."""
        if self._chamber_test_stage:
            return False
        if not force and not self._chamber_test_mode:
            self._chamber_test_set("Сначала включите тестовый режим.", "#dc2626")
            return False
        if target_x10 is not None and not (-400 <= int(target_x10) <= 850):
            self._chamber_test_set("Температура должна быть от -40 до +85 °C.", "#dc2626")
            return False
        problem = self._chamber_test_problem()
        if problem:
            self._chamber_test_set(f"Температура не задана: {problem}.", "#dc2626")
            return False

        self._chamber_test_target = None if target_x10 is None else int(target_x10)
        self._chamber_test_attempt = 0
        self._chamber_test_stage = "access"
        self._chamber_test_deadline = time.monotonic() + self.CHAMBER_TEST_ACCESS_TIMEOUT_S
        if not self._chamber_chain_write_ready() and not bool(self._calibration_active):
            # Эмуляция пишется в прибор, а запись открывает только сессия калибровки.
            self.toggleCalibration()
        self._chamber_test_set(
            f"Задаю прибору {_temp_text(self._chamber_test_target)}: открываю доступ на запись...", "#0f6ab4")
        self._chamber_test_timer.start()
        return True

    def _chamber_test_set_text(self, text: str) -> bool:
        """Разбирает температуру из поля ввода и задаёт её прибору."""
        cleaned = str(text).strip().replace(",", ".").replace("°", "").replace("C", "").replace("С", "").strip()
        try:
            value = float(cleaned)
        except ValueError:
            self._chamber_test_set("Температура задаётся числом градусов, например -12,5.", "#dc2626")
            return False
        return self._chamber_test_start_set(int(round(value * 10)))

    def _chamber_test_send_write(self, now: float) -> bool:
        """Отправляет запись эмуляции, если шина свободна."""
        if uds_exchange_busy(self) or background_request_recent(self):
            return False
        value = EMULATION_OFF_WIRE if self._chamber_test_target is None else int(self._chamber_test_target) & 0xFFFF
        try:
            sent = self._chamber_test_write_service.write_data(
                UdsData.temperature_emulation_x10, value, tx_identifier=self._build_calibration_tx_identifier())
        except Exception:
            sent = False
        if not sent:
            self._chamber_test_fail("запрос не ушёл в шину, проверьте подключение")
            return False
        note_background_request(self)
        self._chamber_test_pending = True
        self._chamber_test_pending_s = now
        return True

    def _on_chamber_test_tick(self):
        """Ведёт смену температуры и обход узлов."""
        now = time.monotonic()
        stage = self._chamber_test_stage

        if stage == "access":
            if self._chamber_chain_write_ready() and not background_request_recent(self):
                self._chamber_test_stage = "write"
                self._chamber_test_set(f"Задаю прибору {_temp_text(self._chamber_test_target)}...", "#0f6ab4")
                self._chamber_test_send_write(now)
            elif now > self._chamber_test_deadline:
                self._chamber_test_fail(
                    f"доступ на запись не открылся за {int(self.CHAMBER_TEST_ACCESS_TIMEOUT_S)} с. "
                    "Проверьте выбор прибора в шапке окна")
        elif stage == "write":
            if not self._chamber_test_pending:
                self._chamber_test_send_write(now)
            elif now - self._chamber_test_pending_s > self.CHAMBER_TEST_WRITE_TIMEOUT_S:
                self._chamber_test_pending = False
                if self._chamber_test_attempt >= self.CHAMBER_TEST_WRITE_RETRIES:
                    self._chamber_test_fail("прибор не ответил на запись эмуляции")
                else:
                    self._chamber_test_attempt += 1
        elif stage == "settle":
            self._chamber_test_follow_settle(now)

        if not self._chamber_test_stage:
            self._chamber_test_walk_tick(now)

        if not self._chamber_test_stage and not self._chamber_test_walk_stage:
            self._chamber_test_timer.stop()

    def _chamber_test_on_written(self):
        """Прибор принял температуру: старые показания температур в среднее больше не годятся."""
        self._chamber_test_pending = False
        self._chamber_test_emulation = self._chamber_test_target
        for key in ("fuel_temp", "board_temp"):
            self._chamber_live_recent[key] = []
            self._chamber_live_last[key] = None
            self._chamber_live_seen[key] = 0.0
        self._chamber_test_stage = "settle"
        self._chamber_test_deadline = time.monotonic() + self.CHAMBER_TEST_SETTLE_TIMEOUT_S
        self._chamber_test_set(
            f"Прибор принял {_temp_text(self._chamber_test_target)}, жду, пока он её покажет...", "#0f6ab4")

    def _chamber_test_settled(self, now: float) -> bool:
        """Показывает ли прибор заданную температуру по обоим датчикам."""
        for key in ("fuel_temp", "board_temp"):
            stats = self._chamber_live_stats(key, now)
            if stats is None or stats["count"] < self.CHAMBER_TEST_SETTLE_SAMPLES:
                return False
            if self._chamber_test_target is not None and \
                    abs(stats["mean"] - self._chamber_test_target) > self.CHAMBER_TEST_SETTLE_TOLERANCE_X10:
                return False
        return True

    def _chamber_test_follow_settle(self, now: float):
        if self._chamber_test_settled(now):
            self._chamber_test_stage = ""
            if self._chamber_test_target is None:
                self._chamber_test_set("Эмуляция выключена: прибор показывает настоящую температуру.", "#16a34a")
            else:
                self._chamber_test_set(
                    f"Прибор показывает {_temp_text(self._chamber_test_target)} по обоим датчикам. "
                    "Можно записывать точку.", "#16a34a")
            return
        if now > self._chamber_test_deadline:
            self._chamber_test_fail(
                f"за {int(self.CHAMBER_TEST_SETTLE_TIMEOUT_S)} с прибор так и не показал "
                f"{_temp_text(self._chamber_test_target)}. Раздел должен быть открыт: температуры читает он")

    def _chamber_test_fail(self, reason: str):
        """Останавливает смену температуры и обход, называет причину."""
        self._chamber_test_stage = ""
        self._chamber_test_pending = False
        walking = bool(self._chamber_test_walk_stage)
        self._chamber_test_walk = []
        self._chamber_test_walk_stage = ""
        prefix = "Обход узлов остановлен" if walking else "Температура не задана"
        self._chamber_test_set(f"{prefix}: {reason}.", "#dc2626")
        if walking:
            self._chamber_remote("_remote_note_test", f"{prefix.lower()}: {reason}.", False)

    def _handle_chamber_test_frame(self, identifier: int, payload):
        """Ответ прибора на запись эмуляции."""
        if not self._chamber_test_pending:
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
        did = int(UdsData.temperature_emulation_x10.pid) & 0xFFFF

        if body[0] == 0x7F and body[1] == 0x2E:
            if len(body) > 2 and body[2] == 0x78:
                return
            code = body[2] if len(body) > 2 else 0
            reason = ("прибор закрыл запись, запустите калибровку заново" if code == 0x33
                      else "в этой прошивке нет эмуляции температуры" if code == 0x31
                      else f"прибор отказал (код 0x{code:02X})")
            self._chamber_test_fail(reason)
            return

        if body[0] == 0x6E and len(body) >= 3 and did in ((body[1] << 8) | body[2], (body[2] << 8) | body[1]):
            self._chamber_test_on_written()

    # ------------------------------------------------------------------ обход узлов

    def _chamber_test_walk_start(self) -> bool:
        """Проходит все узлы сетки с текущей пометкой: температура, ожидание, точка."""
        if self._chamber_test_busy():
            return False
        if not self._chamber_test_mode:
            self._chamber_test_set("Сначала включите тестовый режим.", "#dc2626")
            return False
        if not str(self._chamber_label).strip():
            self._chamber_test_set("Сначала напишите, что подключено к прибору: пометка пойдёт во все точки обхода.",
                                   "#dc2626")
            return False
        self._chamber_test_walk = list(chamber_fit.NODES_X10)
        self._chamber_test_walk_total = len(self._chamber_test_walk)
        self._chamber_test_walk_stage = "next"
        self._chamber_test_set(
            f"Обход узлов с пометкой «{self._chamber_label}»: {self._chamber_test_walk_total} температур.", "#0f6ab4")
        self._chamber_test_timer.start()
        return True

    def _chamber_test_walk_stop(self):
        """Останавливает обход после текущего шага."""
        if not self._chamber_test_walk_stage:
            return
        self._chamber_test_walk = []
        self._chamber_test_walk_stage = ""
        self._chamber_test_set("Обход узлов остановлен оператором. Эмуляция оставлена как есть.", "#d97706")

    def _chamber_test_walk_tick(self, now: float):
        """Шаг обхода: вызывается, когда смена температуры не идёт."""
        stage = self._chamber_test_walk_stage
        if not stage:
            return

        if stage == "next":
            if not self._chamber_test_walk:
                # Все узлы пройдены: прибор возвращается к настоящей температуре.
                self._chamber_test_walk_stage = "finish"
                if not self._chamber_test_start_set(None, force=True):
                    self._chamber_test_walk_stage = ""
                return
            node = self._chamber_test_walk[0]
            if self._chamber_test_start_set(node):
                self._chamber_test_walk_stage = "settle"
            else:
                self._chamber_test_walk = []
                self._chamber_test_walk_stage = ""
            return

        if stage == "settle":
            # Смена температуры кончилась: удачно, если прибор показывает заданное.
            if self._chamber_test_emulation != self._chamber_test_walk[0]:
                return
            self._chamber_test_walk_points = len(self._chamber_points)
            self._chamber_test_walk_deadline = now + self.CHAMBER_TEST_CAPTURE_TIMEOUT_S
            if not self._chamber_capture_from_average():
                self._chamber_test_fail(f"точку при {_temp_text(self._chamber_test_walk[0])} записать не удалось")
                return
            self._chamber_test_walk_stage = "capture"
            return

        if stage == "capture":
            if len(self._chamber_points) > self._chamber_test_walk_points:
                done = self._chamber_test_walk_total - len(self._chamber_test_walk) + 1
                node = self._chamber_test_walk.pop(0)
                self._chamber_test_walk_stage = "next"
                self._chamber_test_set(
                    f"Обход: точка при {_temp_text(node)} записана ({done} из {self._chamber_test_walk_total}).",
                    "#0f6ab4")
                return
            if not self._chamber_capture_waiting or now > self._chamber_test_walk_deadline:
                self._chamber_test_fail(
                    f"точка при {_temp_text(self._chamber_test_walk[0])} не записалась: {self._chamber_status}")
            return

        if stage == "finish":
            self._chamber_test_walk_stage = ""
            self._chamber_test_set(
                f"Обход с пометкой «{self._chamber_label}» закончен: {self._chamber_test_walk_total} точек, "
                "эмуляция выключена. Подключите следующие эталоны и пройдите узлы снова.", "#16a34a")
            self._chamber_remote(
                "_remote_note_test",
                f"тестовый обход с пометкой «{self._chamber_label}» закончен: {self._chamber_test_walk_total} точек.",
                True)
            # Пока шёл обход, запись профиля ждала: таблицы могли стать полными на последней точке.
            chain = getattr(self, "_chamber_chain_maybe_auto", None)
            if chain is not None:
                chain()

    # ------------------------------------------------------------------ показ

    def _chamber_test_view(self) -> dict:
        """Состояние тестового режима для окна."""
        drift_lines = []
        for channel, title in (("main", "основной"), ("media", "вид топлива")):
            gain, offset = self.CHAMBER_TEST_DRIFT[channel]
            drift_lines.append(f"{title} {gain:+.0f} ppm/°C, {offset:+.2f} отсч./°C".replace(".", ","))
        return {
            "mode": bool(self._chamber_test_mode),
            "busy": bool(self._chamber_test_stage),
            "walking": bool(self._chamber_test_walk_stage),
            "emulationText": _temp_text(self._chamber_test_emulation),
            "status": str(self._chamber_test_status),
            "color": str(self._chamber_test_color),
            "drift": bool(self._chamber_test_drift_on),
            "driftText": "; ".join(drift_lines),
            "checkText": str(self._chamber_test_check_text),
            "checkColor": str(self._chamber_test_check_color),
            "nodes": [{"value": node, "text": chamber_fit.node_text(node),
                       "current": self._chamber_test_emulation == node}
                      for node in chamber_fit.NODES_X10],
        }
