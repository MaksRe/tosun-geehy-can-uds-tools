"""Прогон изделия в климатической камере и расчёт температурных таблиц.

ЗАЧЕМ ОТДЕЛЬНЫЙ РАЗДЕЛ
Снятие профиля это калибровка, а не наблюдение за шиной. Раньше пометка о том,
что подключено к прибору, стояла в окне коллектора, и это было неверно:
коллектор показывает, какие узлы есть на шине и что они передают, и ничего не
настраивает. Теперь прогон живёт в окне калибровки рядом с таблицами профиля.

КАК ЭТО РАБОТАЕТ
Оператор доводит камеру до нужной температуры, подключает к прибору эталонный
конденсатор или собранное изделие, пишет в поле пометку что именно подключено и
нажимает «Записать точку». Раздел всё время показывает текущие показания и их
скользящее среднее, и кнопка сразу кладёт это среднее в журнал прогона.

После каждой точки журнал сам сохраняется в файл, а обе ступени сами
пересчитываются и попадают в таблицу профиля. Когда данных хватает во всех
узлах, профиль сам записывается в прибор, сверяется и сохраняется в файл.
Отдельный скрипт и ручной перенос файлов больше не нужны.

ЧТО ЧИТАЕТСЯ В КАЖДОЙ ТОЧКЕ
Период основного контура, период контура вида топлива, температура топлива и
температура платы. Больше для расчёта ничего не нужно.

Оба периода читаются ДО температурной компенсации прибора (0x0014 и 0x0067):
расчёт сам применяет поправки так же, как прибор, и показание, уже поправленное
записанным профилем, было бы поправлено дважды.
"""

from __future__ import annotations

import csv
import json
import pathlib
import time
from datetime import datetime

from PySide6.QtCore import QTimer

import chamber_fit
from uds.data_identifiers import UdsData
from uds.services.read_data_by_id import ServiceReadDataById

from .bus_guard import BACKGROUND_GUARD_S, background_request_recent
from .contract import AppControllerContract


class AppControllerChamberMixin(AppControllerContract):
    # Пауза между запросами и таймаут ответа, мс.
    CHAMBER_REQUEST_GAP_MS = 40
    CHAMBER_TIMEOUT_MS = 700

    # Сколько раз опросить прибор в одной точке. Среднее по ним и попадает в журнал.
    CHAMBER_SAMPLES = 5

    # Сколько раз повторить запрос, оставшийся без ответа. Прибор теряет запрос,
    # если в тот же миг к нему пришёл чужой, и один такой случай не повод бросать точку.
    CHAMBER_RETRY_LIMIT = 2

    # Сколько строк журнала показывать в окне. Остальные есть в файле.
    CHAMBER_VISIBLE_ROWS = 120

    CHAMBER_COLUMNS = (
        "Время",
        "Что подключено",
        "Период основного контура",
        "Период контура вида топлива",
        "Температура топлива (°C)",
        "Температура платы (°C)",
        "Режим",
        "Температура камеры (°C)",
    )
    # Журналы до связи с камерой: без последнего столбца. Читаются так же.
    CHAMBER_LEGACY_COLUMNS = 7

    # Пометка пробной точки в журнале. По ней видно, что температуру задавала эмуляция.
    CHAMBER_REHEARSAL_MARK = "репетиция"

    def _chamber_vars(self):
        """Величины одной точки. True означает, что значение знаковое."""
        return (
            ("main", UdsData.curr_fuel_tank, False),
            ("media", UdsData.fuel_media_raw_period, False),
            ("fuel_temp", UdsData.raw_temperature, True),
            ("board_temp", UdsData.raw_board_temperature, True),
        )

    # ------------------------------------------------------------------ состояние

    def _init_chamber_state(self):
        """Готовит раздел прогона. Вызывается один раз при создании контроллера."""
        self._chamber_read_service = ServiceReadDataById()
        # Для этого МК номер DID в запросе 0x22 всегда идёт в стандартном порядке.
        self._chamber_read_service.set_byte_order("big")

        self._chamber_label = ""
        self._chamber_points: list[dict] = []
        self._chamber_busy = False
        self._chamber_status = "Точки ещё не снимались."
        self._chamber_status_color = "#64748b"
        self._chamber_report: list[str] = []
        self._chamber_file_path = ""

        # Итог последнего расчёта таблиц: он идёт сам после каждой точки.
        self._chamber_tables_text = "Таблицы посчитаются сами, когда появятся точки."
        self._chamber_tables_color = "#64748b"
        # Данных хватило во всех узлах, и таблицы можно писать в прибор.
        self._chamber_tables_complete = False
        # Расчёт отложен, пока профиль пишется в прибор: таблицы нельзя менять посреди записи.
        self._chamber_tables_deferred = False

        # Признак пробной калибровки. Его ставит раздел пробной калибровки на время
        # прогона с эмуляцией температуры в самом приборе, и снятые точки помечаются.
        self._chamber_rehearsal = False

        # Достройка строк «в жидкости» по постоянному размаху. Нужна, когда в
        # камеру нельзя ставить топливо и погружение при каждой температуре не
        # снять. Пустой размах означает «взять из узла, где пара снята».
        self._chamber_extend_liquid = False
        self._chamber_span_main: int | None = None
        self._chamber_span_media: int | None = None

        self._chamber_queue: list[tuple[str, object, bool]] = []
        self._chamber_pending = None
        self._chamber_sample: dict[str, int] = {}
        self._chamber_samples: list[dict[str, int]] = []
        self._chamber_samples_left = 0
        # Сколько раз уже повторён текущий запрос.
        self._chamber_attempt = 0

        self._chamber_gap_timer = QTimer(self)
        self._chamber_gap_timer.setSingleShot(True)
        self._chamber_gap_timer.setInterval(self.CHAMBER_REQUEST_GAP_MS)
        self._chamber_gap_timer.timeout.connect(self._on_chamber_gap_timeout)

        self._chamber_timeout_timer = QTimer(self)
        self._chamber_timeout_timer.setSingleShot(True)
        self._chamber_timeout_timer.setInterval(self.CHAMBER_TIMEOUT_MS)
        self._chamber_timeout_timer.timeout.connect(self._on_chamber_timeout)

    def _chamber_remote(self, name: str, *args):
        """Сообщает наблюдению издалека о событии прогона, если наблюдение есть."""
        handler = getattr(self, name, None)
        if handler is not None:
            handler(*args)

    def _chamber_test_on(self) -> bool:
        """Включён ли тестовый режим: точки снимаются с эмуляцией температуры на столе."""
        return bool(getattr(self, "_chamber_test_mode", False))

    def _chamber_set_status(self, text: str, color: str):
        """Записывает строку хода работы и рассылает уведомление окну."""
        self._chamber_status = str(text)
        self._chamber_status_color = str(color)
        self.chamberChanged.emit()

    # ------------------------------------------------------------------ снятие точки

    def _chamber_capture_point(self) -> bool:
        """Запускает замер одной точки. Возвращает False, если сейчас нельзя."""
        if self._chamber_busy:
            return False

        if not self._can.is_connect:
            self.infoMessage.emit("Прогон в камере", "Сначала подключите CAN-адаптер.")
            return False

        if not self._can.is_trace:
            self.infoMessage.emit("Прогон в камере", "Сначала включите трассировку CAN.")
            return False

        # Проверка прибора ведёт собственный обмен теми же сервисами, параллельно нельзя.
        if getattr(self, "_diagnostics_running", False):
            self.infoMessage.emit(
                "Прогон в камере",
                "Идёт проверка прибора. Остановите её и повторите замер.",
            )
            return False

        if not str(self._chamber_label).strip():
            self.infoMessage.emit(
                "Прогон в камере",
                "Сначала напишите, что подключено к прибору. Без пометки точка бесполезна.",
            )
            return False

        self._chamber_samples = []
        self._chamber_samples_left = int(self.CHAMBER_SAMPLES)
        self._chamber_attempt = 0
        self._chamber_busy = True
        if background_request_recent(self):
            # Ответ на только что ушедший фоновый запрос ещё в пути: первый запрос его затёр бы.
            self._chamber_sample = {}
            self._chamber_queue = list(self._chamber_vars())
            self._chamber_gap_timer.start(int(BACKGROUND_GUARD_S * 1000))
        else:
            self._chamber_start_sample()
        self._chamber_set_status(
            f"Замер точки «{self._chamber_label}», осталось повторов: {self._chamber_samples_left}.",
            "#0f6ab4",
        )
        return True

    def _chamber_start_sample(self):
        """Готовит очередь одного повтора замера."""
        self._chamber_sample = {}
        self._chamber_queue = list(self._chamber_vars())
        self._send_next_chamber_request()

    def _send_next_chamber_request(self) -> bool:
        """Отправляет следующий запрос. Пустая очередь завершает повтор."""
        if not self._chamber_busy:
            return False

        if not self._chamber_queue:
            self._chamber_finish_sample()
            return True

        key, var, signed = self._chamber_queue.pop(0)
        self._chamber_pending = (key, var, signed)

        try:
            sent = self._chamber_read_service.read_data_by_identifier(
                self._build_calibration_tx_identifier(), var
            )
        except Exception:
            sent = False

        if not sent:
            self._chamber_abort("Не удалось отправить запрос. Проверьте подключение к шине.")
            return False

        self._chamber_timeout_timer.start(self.CHAMBER_TIMEOUT_MS)
        return True

    def _chamber_finish_sample(self):
        """Повтор замера закончен: либо берём следующий, либо складываем точку."""
        self._chamber_samples.append(dict(self._chamber_sample))
        self._chamber_samples_left -= 1

        if self._chamber_samples_left > 0:
            self._chamber_set_status(
                f"Замер точки «{self._chamber_label}», осталось повторов: {self._chamber_samples_left}.",
                "#0f6ab4",
            )
            # Очередь следующего повтора готовится сразу. Раньше пауза после последнего
            # чтения повтора запускала тот же повтор заново, и точка не заканчивалась никогда.
            self._chamber_sample = {}
            self._chamber_queue = list(self._chamber_vars())
            self._chamber_gap_timer.start(self.CHAMBER_REQUEST_GAP_MS)
            return

        self._chamber_store_point()

    def _chamber_store_point(self):
        """Усредняет повторы и добавляет точку в журнал прогона."""
        self._chamber_busy = False
        self._chamber_pending = None
        self._chamber_queue = []

        def mean(key):
            values = [item[key] for item in self._chamber_samples if key in item]
            if not values:
                return None
            return int(round(sum(values) / float(len(values))))

        main = mean("main")
        fuel_temp = mean("fuel_temp")
        board_temp = mean("board_temp")

        if main is None or fuel_temp is None or board_temp is None:
            self._chamber_set_status(
                "Точка не записана: прибор не отдал период или температуру.", "#dc2626")
            return

        self._chamber_append_point({
            "main": int(main),
            "media": mean("media"),
            "fuel_temp_x10": int(fuel_temp),
            "board_temp_x10": int(board_temp),
        }, f"среднее {len(self._chamber_samples)} замеров")

    def _chamber_append_point(self, values: dict, detail: str = ""):
        """Добавляет точку в журнал, сохраняет журнал и пересчитывает таблицы.

        Общая часть для обоих способов снятия: по средним живого опроса и по
        серии замеров пробной калибровки.
        """
        # Температура всегда берётся из прибора. При пробной калибровке и в тестовом
        # режиме её задаёт эмуляция в самой прошивке, поэтому точка честно попадает
        # в свой узел, но помечается как пробная.
        rehearsal = bool(self._chamber_rehearsal) or self._chamber_test_on()

        point = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "note": str(self._chamber_label).strip(),
            "main": int(values["main"]),
            "media": None if values.get("media") is None else int(values["media"]),
            "fuel_temp_x10": int(values["fuel_temp_x10"]),
            "board_temp_x10": int(values["board_temp_x10"]),
            "rehearsal": rehearsal,
        }
        # Температура воздуха камеры рядом с температурой платы: видно, насколько плата отстала.
        chamber_temp = getattr(self, "_climate_point_temperature", None)
        chamber_x10 = chamber_temp() if chamber_temp is not None else None
        if chamber_x10 is not None:
            point["chamber_temp_x10"] = int(chamber_x10)
        self._chamber_points.append(point)

        node = chamber_fit.nearest_node(point["board_temp_x10"])
        if node is None:
            hint = (
                f"температура платы {point['board_temp_x10'] / 10:+.1f} °C далеко от узлов сетки, "
                "в расчёт ступени платы точка не попадёт"
            )
            color = "#d97706"
        else:
            hint = f"узел {chamber_fit.node_text(node)}"
            color = "#16a34a"

        prefix = "Пробная точка" if rehearsal else "Точка"
        how = f" ({detail})" if detail else ""
        saved = self._chamber_after_change()
        if not self._chamber_rehearsal:
            self._chamber_remote("_remote_note_point", point)
        self._chamber_set_status(
            f"{prefix} «{point['note']}» записана{how}, {hint}. Всего точек: {len(self._chamber_points)}.{saved}",
            color,
        )

    def _chamber_abort(self, message: str):
        """Прерывает замер и сообщает причину."""
        self._chamber_busy = False
        self._chamber_pending = None
        self._chamber_queue = []
        self._chamber_gap_timer.stop()
        self._chamber_timeout_timer.stop()
        self._chamber_set_status(message, "#dc2626")

    def _on_chamber_gap_timeout(self):
        """Пауза между запросами вышла: следующий запрос, а пустая очередь закрывает повтор."""
        if not self._chamber_busy:
            return
        self._send_next_chamber_request()

    def _on_chamber_timeout(self):
        """Прибор не ответил на запрос за отведённое время."""
        if (not self._chamber_busy) or (self._chamber_pending is None):
            return
        pending = self._chamber_pending
        _key, var, _signed = pending
        if self._chamber_attempt < self.CHAMBER_RETRY_LIMIT:
            self._chamber_attempt += 1
            self._chamber_pending = None
            self._chamber_queue.insert(0, pending)
            self._chamber_gap_timer.start(self.CHAMBER_REQUEST_GAP_MS)
            return
        self._chamber_abort(
            f"Прибор не ответил на DID 0x{int(var.pid) & 0xFFFF:04X} и после "
            f"{self.CHAMBER_RETRY_LIMIT} повторов. Точка не записана."
        )

    def _handle_chamber_frame(self, identifier: int, payload):
        """Разбирает ответ прибора на запрос замера."""
        if (not self._chamber_busy) or (self._chamber_pending is None):
            return
        if not isinstance(payload, (list, tuple)) or len(payload) < 4:
            return
        if not self._is_calibration_response_identifier(identifier):
            return

        key, var, signed = self._chamber_pending
        expected_did = int(var.pid) & 0xFFFF

        # Ответ короткий, поэтому ждём одиночный кадр ISO-TP.
        if ((int(payload[0]) >> 4) & 0x0F) != 0x00:
            return

        body_length = int(payload[0]) & 0x0F
        if body_length < 3 or body_length > (len(payload) - 1):
            return

        body = [int(value) & 0xFF for value in payload[1:1 + body_length]]

        # Отрицательный ответ: параметра нет либо он закрыт в текущей сессии.
        if body[0] == 0x7F:
            # Отказ на чужую службу (запись, сессию) к этому чтению не относится.
            if body[1] != 0x22:
                return
            self._chamber_timeout_timer.stop()
            self._chamber_attempt = 0
            self._chamber_pending = None
            # Контур вида топлива есть не во всех сборках, без него расчёт возможен.
            if key == "media":
                self._chamber_gap_timer.start(self.CHAMBER_REQUEST_GAP_MS)
                return
            code = body[2] if len(body) > 2 else 0
            self._chamber_abort(
                f"DID 0x{expected_did:04X}: прибор ответил отказом (код 0x{code:02X}). Точка не записана."
            )
            return

        if body[0] != 0x62 or len(body) < 4:
            return

        # Номер DID принимаем в обоих порядках байтов: сборки прошивки отвечают по-разному.
        answer_big = (body[1] << 8) | body[2]
        answer_little = (body[2] << 8) | body[1]
        if expected_did not in (answer_big, answer_little):
            return

        raw = 0
        shift = 0
        for byte_value in body[3:]:
            raw |= byte_value << shift
            shift += 8

        if signed:
            bits = max(8, int(var.size) * 8)
            limit = 1 << bits
            raw &= limit - 1
            value = raw - limit if raw >= (limit >> 1) else raw
        else:
            value = raw

        self._chamber_timeout_timer.stop()
        self._chamber_pending = None
        self._chamber_attempt = 0
        self._chamber_sample[key] = int(value)
        self._chamber_gap_timer.start(self.CHAMBER_REQUEST_GAP_MS)

    # ------------------------------------------------------------------ журнал

    def _chamber_remove_last_point(self) -> bool:
        """Убирает последнюю точку: обычно она снята с неверной пометкой."""
        if not self._chamber_points:
            self._chamber_set_status("Убирать нечего, журнал пуст.", "#d97706")
            return False
        removed = self._chamber_points.pop()
        saved = self._chamber_after_change()
        self._chamber_set_status(
            f"Точка «{removed['note']}» убрана. Осталось точек: {len(self._chamber_points)}.{saved}",
            "#0f6ab4",
        )
        return True

    def _chamber_clear_points(self):
        """Очищает журнал прогона целиком.

        Файл прежнего журнала не трогается: следующая точка начнёт новый файл,
        и случайно нажатая «Очистить» не сотрёт часы прогона на диске.
        """
        self._chamber_points = []
        self._chamber_report = []
        self._chamber_file_path = ""
        self._chamber_tables_complete = False
        self._chamber_tables_text = "Таблицы посчитаются сами, когда появятся точки."
        self._chamber_tables_color = "#64748b"
        self._chamber_set_status("Журнал прогона очищен. Следующая точка начнёт новый файл.", "#64748b")

    def _chamber_after_change(self) -> str:
        """После каждой правки журнала: сохраняет его в файл и пересчитывает таблицы.

        Возвращает хвост строки хода работы: куда сохранён журнал. Точки пробной
        калибровки не сохраняются и не считаются: их таблицы в прибор писать нельзя,
        а проверку она ведёт сама.
        """
        if self._chamber_rehearsal:
            self.chamberChanged.emit()
            return ""
        path = self._chamber_autosave()
        self._chamber_auto_compute()
        self.chamberChanged.emit()
        if not path:
            return " Журнал сохранить не удалось, сохраните его вручную."
        return f" Журнал сохранён: {pathlib.Path(path).name}."

    def _chamber_autosave_directory(self):
        """Папка журналов прогона: logs/chamber рядом с программой, или None."""
        root = getattr(self, "_project_root_directory", None)
        if root is None:
            return None
        return pathlib.Path(root) / "logs" / "chamber"

    def _chamber_autosave(self) -> str:
        """Сохраняет журнал в его файл, а у нового прогона сначала заводит файл сам.

        Прогон длится часами: забытое сохранение или упавшая программа не должны
        стоить снятых точек. Возвращает путь или пустую строку при неудаче.
        """
        path = str(self._chamber_file_path or "")
        if not path:
            folder = self._chamber_autosave_directory()
            if folder is None:
                return ""
            path = str(folder / f"chamber_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        if self._chamber_write_csv(path) is not None:
            return ""
        self._chamber_file_path = path
        self._chamber_remote("_remote_note_journal_saved", path)
        return path

    def _chamber_write_csv(self, path: str):
        """Пишет журнал в CSV. Возвращает None или текст ошибки."""
        try:
            target = pathlib.Path(str(path))
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file, delimiter=";")
                writer.writerow(self.CHAMBER_COLUMNS)
                for point in self._chamber_points:
                    writer.writerow((
                        point["time"],
                        point["note"],
                        point["main"],
                        "" if point["media"] is None else point["media"],
                        f"{point['fuel_temp_x10'] / 10:.1f}".replace(".", ","),
                        f"{point['board_temp_x10'] / 10:.1f}".replace(".", ","),
                        self.CHAMBER_REHEARSAL_MARK if point.get("rehearsal") else "",
                        "" if point.get("chamber_temp_x10") is None
                        else f"{point['chamber_temp_x10'] / 10:.1f}".replace(".", ","),
                    ))
        except OSError as error:
            return str(error)
        return None

    def _chamber_save_file(self, path: str) -> bool:
        """Сохраняет журнал прогона в выбранный файл. Дальше автосохранение пишет туда же."""
        if not self._chamber_points:
            self._chamber_set_status("Сохранять нечего, журнал пуст.", "#d97706")
            return False
        error = self._chamber_write_csv(path)
        if error is not None:
            self._chamber_set_status(f"Не удалось записать файл: {error}", "#dc2626")
            return False

        self._chamber_file_path = str(path)
        self._chamber_set_status(f"Журнал прогона сохранён: {path}", "#16a34a")
        return True

    def _chamber_load_file(self, path: str) -> bool:
        """Читает журнал прогона обратно, чтобы продолжить прерванный прогон."""
        try:
            text = pathlib.Path(str(path)).read_text(encoding="utf-8-sig")
        except OSError as error:
            self._chamber_set_status(f"Не удалось прочитать файл: {error}", "#dc2626")
            return False

        rows = list(csv.reader(text.splitlines(), delimiter=";"))
        header = [cell.strip() for cell in rows[0]] if rows else []
        legacy = list(self.CHAMBER_COLUMNS[:self.CHAMBER_LEGACY_COLUMNS])
        if not rows or (header != list(self.CHAMBER_COLUMNS) and header != legacy):
            self._chamber_set_status(
                "Файл не похож на журнал прогона: не совпали названия колонок.", "#dc2626")
            return False

        def number(cell):
            cleaned = str(cell).strip().replace(",", ".")
            if not cleaned:
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None

        points: list[dict] = []
        for row in rows[1:]:
            if len(row) < self.CHAMBER_LEGACY_COLUMNS:
                continue
            main = number(row[2])
            fuel_temp = number(row[4])
            board_temp = number(row[5])
            if main is None or fuel_temp is None or board_temp is None:
                continue
            media = number(row[3])
            point = {
                "time": str(row[0]).strip(),
                "note": str(row[1]).strip(),
                "main": int(round(main)),
                "media": None if media is None else int(round(media)),
                "fuel_temp_x10": int(round(fuel_temp * 10)),
                "board_temp_x10": int(round(board_temp * 10)),
                "rehearsal": str(row[6]).strip().casefold() == self.CHAMBER_REHEARSAL_MARK,
            }
            chamber_temp = number(row[7]) if len(row) > 7 else None
            if chamber_temp is not None:
                point["chamber_temp_x10"] = int(round(chamber_temp * 10))
            points.append(point)

        if not points:
            self._chamber_set_status("В файле нет ни одной пригодной точки.", "#dc2626")
            return False

        self._chamber_points = points
        self._chamber_file_path = str(path)
        self._chamber_report = []
        self._chamber_set_status(f"Загружено точек: {len(points)}.", "#16a34a")
        # Загруженный журнал сразу пересчитывается: таблицы профиля должны ему соответствовать.
        self._chamber_auto_compute()
        self.chamberChanged.emit()
        return True

    # ------------------------------------------------------------------ расчёт

    def _chamber_set_tables_state(self, text: str, color: str, complete: bool = False):
        """Запоминает итог расчёта таблиц для строки рядом с кнопкой расчёта."""
        self._chamber_tables_text = str(text)
        self._chamber_tables_color = str(color)
        self._chamber_tables_complete = bool(complete)
        self._chamber_remote("_remote_note_tables", bool(complete))

    def _chamber_auto_compute(self) -> bool:
        """Пересчёт таблиц после правки журнала, без сообщений в строке хода работы."""
        if not self._chamber_points:
            self._chamber_report = []
            self._chamber_set_tables_state("Таблицы посчитаются сами, когда появятся точки.", "#64748b")
            return False
        return self._chamber_compute_tables(quiet=True)

    def _chamber_compute_tables(self, quiet: bool = False) -> bool:
        """Считает обе ступени по снятым точкам и кладёт результат в таблицу профиля.

        quiet=True означает пересчёт после точки: итог идёт в строку у кнопки
        расчёта, а строка хода работы остаётся за точкой.
        """
        def report_status(text: str, color: str):
            if not quiet:
                self._chamber_set_status(text, color)

        if not self._chamber_points:
            self._chamber_set_tables_state("Считать нечего: не снято ни одной точки.", "#64748b")
            report_status("Считать нечего: не снято ни одной точки.", "#dc2626")
            return False

        # Таблицы на экране и есть то, что сейчас уходит в прибор. Менять их посреди записи нельзя.
        if bool(getattr(self, "_profile_busy", False)):
            self._chamber_tables_deferred = True
            self._chamber_set_tables_state(
                "Пересчёт отложен: идёт обмен профилем с прибором. Таблицы пересчитаются после него.",
                "#d97706", self._chamber_tables_complete)
            report_status("Идёт обмен профилем с прибором, пересчёт выполнится после него.", "#d97706")
            return False
        self._chamber_tables_deferred = False

        try:
            result = chamber_fit.compute_tables(
                self._chamber_points,
                extend_liquid=bool(self._chamber_extend_liquid),
                span_main=self._chamber_span_main,
                span_media=self._chamber_span_media)
        except Exception as error:
            self._chamber_set_tables_state(f"Расчёт не выполнен: {error}", "#dc2626")
            report_status(f"Расчёт не выполнен: {error}", "#dc2626")
            return False

        self._chamber_report = list(result.get("замечания") or [])
        # Полнота считается по замечаниям самого расчёта: предупреждение о пробных
        # точках в тестовом режиме ожидаемо и запись на стенде не запрещает.
        data_complete = not self._chamber_report
        rehearsal = any(point.get("rehearsal") for point in self._chamber_points)
        if rehearsal:
            self._chamber_report.insert(0, (
                "в прогоне есть точки пробной калибровки с эмуляцией температуры. "
                "Эти таблицы годятся только для проверки порядка работы, "
                "в рабочий прибор их писать нельзя"
            ))
        complete = data_complete and (not rehearsal or self._chamber_test_on())

        # В тестовом режиме с имитацией ухода таблицы сверяются с заложенным уходом.
        check = getattr(self, "_chamber_test_after_compute", None)
        if check is not None:
            check(result)

        if not result.get("ступень_платы") and not result.get("ступень_платы_вида"):
            self._chamber_set_tables_state(
                "Таблицы пока не считаются: ступени платы не хватает данных. Чего не хватает - в списке ниже.",
                "#d97706")
            report_status(
                "Ступень платы не посчитана ни для одного контура, таблицы не заполнены. "
                "Смотрите список ниже.", "#dc2626")
            return False

        self._profile_apply_chamber_format(result)
        crc = self._profile_calc_crc()
        self._profile_set_status(
            f"Таблицы посчитаны по прогону, сумма 0x{crc:04X}. "
            "В прибор они ещё не записаны.", "#d97706")

        if not complete:
            self._chamber_set_tables_state(
                f"Таблицы пересчитаны и перенесены в профиль (сумма 0x{crc:04X}), "
                f"но данных хватило не везде: замечаний {len(self._chamber_report)}.", "#d97706")
            report_status(
                "Таблицы посчитаны, но данных хватило не везде. Смотрите список ниже.", "#d97706")
        else:
            test = " Тестовый прогон: таблицы годятся только для стенда." if rehearsal else ""
            self._chamber_set_tables_state(
                f"Таблицы посчитаны по всем узлам и перенесены в профиль, сумма 0x{crc:04X}.{test}",
                "#16a34a", complete=True)
            report_status(
                "Таблицы посчитаны и перенесены в профиль. Данных хватило везде.", "#16a34a")
            # Данных хватило везде: профиль можно писать в прибор без оператора.
            chain = getattr(self, "_chamber_chain_maybe_auto", None)
            if chain is not None:
                chain()
        return True

    def _chamber_export_tables(self, path: str) -> bool:
        """Сохраняет посчитанные таблицы тем же файлом, что выдаёт скрипт прошивки."""
        if not self._chamber_points:
            self._chamber_set_status("Сохранять нечего: не снято ни одной точки.", "#dc2626")
            return False
        try:
            result = chamber_fit.compute_tables(
                self._chamber_points,
                extend_liquid=bool(self._chamber_extend_liquid),
                span_main=self._chamber_span_main,
                span_media=self._chamber_span_media)
            result["контрольная_сумма"] = 0
            pathlib.Path(str(path)).write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError) as error:
            self._chamber_set_status(f"Не удалось записать файл: {error}", "#dc2626")
            return False

        self._chamber_set_status(f"Таблицы сохранены: {path}", "#16a34a")
        return True

    # ------------------------------------------------------------------ показ

    def _chamber_set_span(self, which: str, text: str) -> bool:
        """Разбирает введённый размах. Пустая строка означает «взять из измерения»."""
        cleaned = str(text).strip().replace(",", ".")
        if not cleaned:
            value = None
        else:
            try:
                value = int(round(float(cleaned)))
            except ValueError:
                self._chamber_set_status(
                    "Размах должен быть числом в отсчётах. Оставьте поле пустым, "
                    "чтобы взять его из снятой пары состояний.", "#dc2626")
                return False
            if value <= 0:
                self._chamber_set_status("Размах должен быть больше нуля.", "#dc2626")
                return False

        if which == "media":
            self._chamber_span_media = value
        else:
            self._chamber_span_main = value
        # Размах меняет строки «в жидкости», поэтому таблицы сразу пересчитываются.
        if self._chamber_extend_liquid:
            self._chamber_auto_compute()
        self.chamberChanged.emit()
        return True

    def _chamber_rows(self) -> list:
        """Готовит журнал прогона для показа: последние строки сверху."""
        rows = []
        for point in reversed(self._chamber_points[-self.CHAMBER_VISIBLE_ROWS:]):
            node = chamber_fit.nearest_node(point["board_temp_x10"])
            rows.append({
                "time": point["time"],
                "note": point["note"] + (" (проба)" if point.get("rehearsal") else ""),
                "main": str(point["main"]),
                "media": "-" if point["media"] is None else str(point["media"]),
                "fuelTemp": f"{point['fuel_temp_x10'] / 10:+.1f}",
                "boardTemp": f"{point['board_temp_x10'] / 10:+.1f}",
                "chamberTemp": ("-" if point.get("chamber_temp_x10") is None
                                else f"{point['chamber_temp_x10'] / 10:+.1f}"),
                "node": "вне сетки" if node is None else chamber_fit.node_text(node),
                "nodeOk": node is not None,
            })
        return rows

    def _chamber_coverage_rows(self) -> list:
        """Показывает, чего не хватает: по каждому узлу сетки что уже снято."""
        counts: dict[int, dict[str, int]] = {}
        for point in self._chamber_points:
            node = chamber_fit.nearest_node(point["board_temp_x10"])
            if node is None:
                continue
            bucket = counts.setdefault(node, {"main": set(), "media": set(), "air": 0, "liquid": 0})
            references = chamber_fit.parse_references(point["note"])
            note = str(point["note"]).strip().casefold()
            if references["main"] is not None or references["media"] is not None:
                for channel in ("main", "media"):
                    if references[channel] is not None:
                        bucket[channel].add(references[channel])
            elif note == chamber_fit.AIR_NOTE:
                bucket["air"] += 1
            elif note == chamber_fit.LIQUID_NOTE:
                bucket["liquid"] += 1

        rows = []
        for node in chamber_fit.NODES_X10:
            bucket = counts.get(node, {"main": set(), "media": set(), "air": 0, "liquid": 0})
            main_caps = len(bucket["main"])
            media_caps = len(bucket["media"])
            # Таблица платы нужна обоим контурам: у каждого свои эталоны.
            board_ok = min(main_caps, media_caps) >= chamber_fit.MIN_REFERENCES_PER_NODE
            tube_ok = bucket["air"] > 0 and bucket["liquid"] > 0
            rows.append({
                "node": chamber_fit.node_text(node),
                # Сколько разных эталонов снято у основного контура и у контура вида топлива.
                "caps": f"эталоны {main_caps} · {media_caps}",
                "capsOk": board_ok,
                "tube": ("есть" if tube_ok else
                         ("нет обеих" if (bucket["air"] == 0 and bucket["liquid"] == 0) else
                          ("нет погружённой" if bucket["liquid"] == 0 else "нет сухой"))),
                "tubeOk": tube_ok,
            })
        return rows
