"""Температурный профиль прибора: чтение, запись, файл.

ЗАЧЕМ ОТДЕЛЬНОЕ ОКНО
Профиль это семь таблиц по семь значений. Записать их через обычное окно
параметров нельзя: там пришлось бы вводить руками блоки по 14 и 28 байт и самому
считать контрольную сумму. На практике этого не сделает никто.

ЧТО ДЕЛАЕТ ЭТОТ МОДУЛЬ
Показывает таблицы числами, сам считает контрольную сумму и записывает всё в
прибор в единственно правильном порядке: сначала таблицы, затем номер алгоритма,
затем поколение, и в самую последнюю очередь сумма. Пока сумма не записана,
прибор профиль не применяет, поэтому оборванная запись в работу не попадёт.

Плюс выгрузка в файл и загрузка из файла. Это даёт откат, если снятый в камере
набор окажется неудачным, и позволяет перенести профиль на другой прибор.
Загружается и файл, который выдаёт расчёт по журналу камеры.

КАК УСТРОЕН ОБМЕН
Таблицы длиннее восьми байт, поэтому идут мультипакетом. Своей реализации здесь
нет: используется та же машинерия, что и в окне параметров, а результат
возвращается сюда по признаку происхождения запроса.
"""

from __future__ import annotations

import json
import pathlib
import struct

from PySide6.QtCore import QTimer

from uds.options_catalog import get_option_by_did

# Признак происхождения запроса: по нему ответы окна параметров попадают сюда.
PROFILE_ORIGIN_PREFIX = "profile_"

# Число температурных узлов профиля.
PROFILE_POINTS = 7

# Номера параметров прибора.
DID_NODES = 0x004B
DID_BOARD_MAIN = 0x004C
DID_BOARD_MEDIA = 0x004D
DID_TUBE_AIR_MAIN = 0x004F
DID_TUBE_FULL_MAIN = 0x0050
DID_TUBE_AIR_MEDIA = 0x0051
DID_TUBE_FULL_MEDIA = 0x0052
DID_ALGORITHM = 0x005C
DID_GENERATION = 0x005D
DID_CRC = 0x005E
DID_CRC_ACTUAL = 0x005F
DID_STATUS = 0x0060

# Номер алгоритма измерения из прошивки. Должен совпадать, иначе прибор
# отвергнет коэффициенты как снятые при другом измерении.
PROFILE_ALGORITHM_ID = 1


class AppControllerProfileMixin:
    """Работа с температурным профилем: таблицы, контрольная сумма, файл."""

    # Порядок таблиц зафиксирован: в нём же прибор считает контрольную сумму.
    PROFILE_TABLES = (
        ("nodes", DID_NODES, "Температуры узлов, 0.1 °C", 1),
        ("board_main", DID_BOARD_MAIN, "Плата, основной", 2),
        ("board_media", DID_BOARD_MEDIA, "Плата, вид топлива", 2),
        ("tube_air_main", DID_TUBE_AIR_MAIN, "Трубка, основной на воздухе", 1),
        ("tube_full_main", DID_TUBE_FULL_MAIN, "Трубка, основной в жидкости", 1),
        ("tube_air_media", DID_TUBE_AIR_MEDIA, "Трубка, вид топлива на воздухе", 1),
        ("tube_full_media", DID_TUBE_FULL_MEDIA, "Трубка, вид топлива в жидкости", 1),
    )

    PROFILE_DEFAULT_NODES = (-400, -200, 0, 250, 500, 700, 850)

    # Сколько раз повторить таблицу, на которую прибор не ответил. Длинную запись
    # обрывает любой посторонний запрос к прибору, а повтор той же таблицы безопасен.
    PROFILE_TIMEOUT_RETRY_LIMIT = 2

    # ------------------------------------------------------------------ состояние

    def _init_profile_state(self):
        """Готовит окно профиля. Вызывается один раз при создании контроллера."""
        self._profile_values: dict[str, list[int]] = {}
        for name, _did, _title, width in self.PROFILE_TABLES:
            self._profile_values[name] = [0] * (PROFILE_POINTS * width)
        self._profile_values["nodes"] = list(self.PROFILE_DEFAULT_NODES)

        self._profile_generation = 0
        self._profile_algorithm_id = PROFILE_ALGORITHM_ID
        self._profile_device_crc = None
        self._profile_device_crc_actual = None
        self._profile_device_status = None

        self._profile_busy = False
        # Пока идёт проверка записи, прочитанное складывается сюда, а не в
        # таблицы на экране: иначе сравнивать было бы уже не с чем.
        self._profile_verify: dict | None = None
        self._profile_verify_report: list[str] = []
        self._profile_queue: list[tuple[str, int, object]] = []
        self._profile_retries_used = 0
        self._profile_status = "Профиль не прочитан."
        self._profile_status_color = "#64748b"
        self._profile_file_path = ""

        # Следующая операция очереди отправляется не сразу, а следующим тактом.
        # Причина: ответ приходит внутрь завершения предыдущей операции, и всё,
        # что отправлено оттуда, тут же затирается уборкой состояния обмена.
        # Из-за этого второй запрос уходил в шину, но ответа на него уже никто
        # не ждал, и чтение профиля висело вечно.
        # Таймер без родителя: модуль подмешивается и в контроллер, и в проверки,
        # где объекта Qt нет вовсе. Ссылку держит сам контроллер.
        self._profile_step_timer = QTimer()
        self._profile_step_timer.setSingleShot(True)
        self._profile_step_timer.setInterval(40)
        self._profile_step_timer.timeout.connect(self._on_profile_step_timeout)

    # ------------------------------------------------------------------ контрольная сумма

    @staticmethod
    def _profile_crc16(data: bytes) -> int:
        """CRC-16/CCITT-FALSE, тот же расчёт и тот же порядок, что в приборе."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else ((crc << 1) & 0xFFFF)
        return crc

    @staticmethod
    def _profile_pack(values) -> bytes:
        """Значения таблицы как двухбайтовые со знаком, младший байт вперёд."""
        return b"".join(struct.pack("<h", int(item)) for item in values)

    def _profile_calc_crc(self) -> int:
        """Считает сумму по всем таблицам в порядке, принятом в приборе."""
        payload = b""
        for name, _did, _title, _width in self.PROFILE_TABLES:
            payload += self._profile_pack(self._profile_values[name])
        return self._profile_crc16(payload)

    # ------------------------------------------------------------------ проверки

    def _profile_validate(self) -> list[str]:
        """Возвращает список причин, по которым профиль записывать нельзя."""
        problems: list[str] = []

        nodes = self._profile_values["nodes"]
        for index in range(1, PROFILE_POINTS):
            if nodes[index] <= nodes[index - 1]:
                problems.append(
                    f"температуры узлов должны возрастать: узел {index + 1} "
                    f"({nodes[index] / 10:.1f} °C) не выше предыдущего"
                )
                break

        for name in ("board_main", "board_media"):
            for value in self._profile_values[name]:
                if not (-32768 <= int(value) <= 32767):
                    problems.append("значение не помещается в два байта")
                    break

        filled = any(
            any(value != 0 for value in self._profile_values[name])
            for name, _did, _title, _width in self.PROFILE_TABLES
            if name != "nodes"
        )
        if not filled:
            problems.append("все таблицы пустые: записывать нечего")

        return problems

    # ------------------------------------------------------------------ обмен с прибором

    def _profile_set_status(self, text: str, color: str):
        self._profile_status = str(text)
        self._profile_status_color = str(color)
        self.profileChanged.emit()

    def _profile_start_queue(self, queue, status: str) -> bool:
        """Запускает очередь операций. Значение None означает чтение."""
        if self._profile_busy:
            return False
        if self._options_busy:
            self._profile_set_status(
                "Окно параметров занято другой операцией. Дождитесь её завершения.", "#d97706")
            return False

        self._profile_queue = list(queue)
        self._profile_retries_used = 0
        self._profile_busy = True
        self._profile_set_status(status, "#64748b")
        return self._profile_send_next()

    def _profile_send_next(self) -> bool:
        """Отправляет следующую операцию очереди."""
        if not self._profile_queue:
            self._profile_busy = False
            self._profile_step_timer.stop()
            if self._profile_verify is not None:
                self._profile_finish_verify()
            else:
                self._profile_set_status("Готово.", "#16a34a")
            return True

        name, did, payload = self._profile_queue[0]
        parameter = get_option_by_did(did)
        if parameter is None:
            self._profile_finish_with_error(f"параметр 0x{did:04X} отсутствует в каталоге")
            return False

        origin = f"{PROFILE_ORIGIN_PREFIX}{name}"
        if payload is None:
            started = self._start_options_read_request(parameter, request_origin=origin, append_history=False)
        else:
            started = self._start_options_write_multiframe_request(
                parameter, bytes(payload), request_origin=origin, append_history=False)

        if not started:
            self._profile_finish_with_error(f"не удалось отправить запрос по 0x{did:04X}")
            return False

        return True

    def _on_profile_step_timeout(self):
        """Отправляет следующую операцию очереди отдельным тактом."""
        if not self._profile_busy:
            return
        self._profile_send_next()

    def _profile_finish_with_error(self, reason: str):
        self._profile_busy = False
        self._profile_queue = []
        self._profile_verify = None
        self._profile_step_timer.stop()
        self._profile_set_status(f"Операция прервана: {reason}", "#dc2626")

    def _handle_profile_options_result(self, *, success: bool, request_origin: str,
                                       pending_action: str, pending_did, value_bytes, message: str):
        """Принимает ответ прибора на операцию профиля и продолжает очередь."""
        if not str(request_origin or "").startswith(PROFILE_ORIGIN_PREFIX):
            return
        if not self._profile_busy or not self._profile_queue:
            return

        name = str(request_origin)[len(PROFILE_ORIGIN_PREFIX):]

        if not success:
            did = int(pending_did) & 0xFFFF if pending_did is not None else 0
            if "таймаут" in str(message).lower() and self._profile_retries_used < self.PROFILE_TIMEOUT_RETRY_LIMIT:
                self._profile_retries_used += 1
                self._profile_set_status(
                    f"Прибор не ответил по 0x{did:04X}, повтор {self._profile_retries_used} из "
                    f"{self.PROFILE_TIMEOUT_RETRY_LIMIT}...", "#d97706")
                self._profile_step_timer.start()
                return
            hint = ""
            if name == self.PROFILE_TABLES[0][0]:
                # Первая же таблица не читается: чаще всего в приборе прошивка,
                # в которой температурного профиля ещё нет.
                hint = " Похоже, в приборе старая прошивка без температурного профиля."
            self._profile_finish_with_error(f"0x{did:04X} - {message}.{hint}")
            return

        if pending_action == "read":
            self._profile_store_read(name, bytes(value_bytes or b""))

        self._profile_queue.pop(0)
        self._profile_retries_used = 0
        self._profile_step_timer.start()

    def _profile_store_read(self, name: str, payload: bytes):
        """Раскладывает прочитанные байты по таблицам и служебным полям."""
        if self._profile_verify is not None:
            self._profile_store_verify(name, payload)
            return

        if name in self._profile_values:
            count = len(self._profile_values[name])
            if len(payload) >= count * 2:
                self._profile_values[name] = list(struct.unpack(f"<{count}h", payload[:count * 2]))
            self.profileChanged.emit()
            return

        value = int.from_bytes(payload[:2], "little", signed=False) if len(payload) >= 2 else (
            payload[0] if payload else 0)

        if name == "algorithm":
            self._profile_algorithm_id = value
        elif name == "generation":
            self._profile_generation = value
        elif name == "crc":
            self._profile_device_crc = value
        elif name == "crc_actual":
            self._profile_device_crc_actual = value
        elif name == "status":
            self._profile_device_status = payload[0] if payload else 0

        self.profileChanged.emit()

    def _profile_store_verify(self, name: str, payload: bytes):
        """Складывает прочитанное в отдельное место, не трогая таблицы на экране."""
        if name in self._profile_values:
            count = len(self._profile_values[name])
            if len(payload) >= count * 2:
                self._profile_verify[name] = list(struct.unpack(f"<{count}h", payload[:count * 2]))
            return

        if name == "status":
            self._profile_verify[name] = payload[0] if payload else 0
            return

        self._profile_verify[name] = (
            int.from_bytes(payload[:2], "little", signed=False) if len(payload) >= 2
            else (payload[0] if payload else 0))

    def _profile_finish_verify(self):
        """Сверяет прочитанное из прибора с тем, что на экране, и называет расхождения."""
        read = dict(self._profile_verify or {})
        self._profile_verify = None
        problems: list[str] = []

        for name, _did, title, width in self.PROFILE_TABLES:
            expected = list(self._profile_values[name])
            actual = read.get(name)
            if actual is None:
                problems.append(f"{title}: прибор не отдал таблицу")
                continue
            for index, (want, got) in enumerate(zip(expected, actual)):
                if want == got:
                    continue
                node = self._profile_values["nodes"][index // width]
                problems.append(
                    f"{title}, узел {node / 10:+.0f} °C: записано {want}, в приборе {got}")
                break

        crc = self._profile_calc_crc()
        if read.get("crc") != crc:
            problems.append(
                f"сумма профиля: записано 0x{crc:04X}, в приборе "
                f"0x{int(read.get('crc') or 0):04X}")
        if read.get("crc_actual") is not None and read.get("crc_actual") != crc:
            problems.append(
                f"прибор сам посчитал сумму 0x{int(read['crc_actual']):04X}, а ожидалась 0x{crc:04X}")
        if read.get("algorithm") != PROFILE_ALGORITHM_ID:
            problems.append(
                f"номер алгоритма: ожидался {PROFILE_ALGORITHM_ID}, в приборе {read.get('algorithm')}")
        if read.get("generation") != int(self._profile_generation):
            problems.append(
                f"поколение: записано {int(self._profile_generation)}, в приборе {read.get('generation')}")

        # Состояние применения важнее всего: прибор мог принять запись и всё равно
        # не взять таблицы в работу.
        self._profile_device_crc = read.get("crc")
        self._profile_device_crc_actual = read.get("crc_actual")
        self._profile_device_status = read.get("status")

        self._profile_verify_report = problems
        if problems:
            self._profile_set_status(
                f"Проверка записи не пройдена, расхождений: {len(problems)}. Смотрите список ниже.",
                "#dc2626")
        else:
            self._profile_set_status(
                "Проверка записи пройдена: в приборе лежит ровно то, что на экране.", "#16a34a")
        self.profileChanged.emit()

    # ------------------------------------------------------------------ команды

    def _profile_verify_on_device(self) -> bool:
        """Читает профиль обратно и сверяет его с таблицами на экране.

        Отдельная операция, а не часть записи: прибор подтверждает приём каждой
        таблицы, но подтверждение не означает, что в памяти лежит именно то, что
        отправлено. Перед выездом в камеру это стоит проверить явно.
        """
        queue = [(name, did, None) for name, did, _title, _width in self.PROFILE_TABLES]
        queue += [
            ("algorithm", DID_ALGORITHM, None),
            ("generation", DID_GENERATION, None),
            ("crc", DID_CRC, None),
            ("crc_actual", DID_CRC_ACTUAL, None),
            ("status", DID_STATUS, None),
        ]
        self._profile_verify = {}
        self._profile_verify_report = []
        if not self._profile_start_queue(queue, "Проверяю, что записалось в прибор..."):
            self._profile_verify = None
            return False
        return True

    def _profile_read_from_device(self) -> bool:
        """Читает из прибора весь профиль и его состояние."""
        queue = [(name, did, None) for name, did, _title, _width in self.PROFILE_TABLES]
        queue += [
            ("algorithm", DID_ALGORITHM, None),
            ("generation", DID_GENERATION, None),
            ("crc", DID_CRC, None),
            ("crc_actual", DID_CRC_ACTUAL, None),
            ("status", DID_STATUS, None),
        ]
        return self._profile_start_queue(queue, "Читаю профиль из прибора...")

    def _profile_write_to_device(self, allow_empty: bool = False) -> bool:
        """Записывает профиль в прибор в правильном порядке.

        Сумма идёт последней намеренно: пока её нет, прибор таблицы не применяет,
        поэтому оборванная на середине запись не попадёт в работу.
        """
        problems = self._profile_validate()
        if allow_empty:
            # Возврат запомненных настроек: пустой профиль там законный, он выключает таблицы.
            problems = [item for item in problems if "пустые" not in item]
        if problems:
            self._profile_set_status("Записывать нельзя: " + problems[0], "#dc2626")
            return False

        crc = self._profile_calc_crc()
        generation = (int(self._profile_generation) + 1) & 0xFFFF

        queue = [
            (name, did, self._profile_pack(self._profile_values[name]))
            for name, did, _title, _width in self.PROFILE_TABLES
        ]
        queue += [
            ("algorithm", DID_ALGORITHM, struct.pack("<H", PROFILE_ALGORITHM_ID)),
            ("generation", DID_GENERATION, struct.pack("<H", generation)),
            ("crc", DID_CRC, struct.pack("<H", crc)),
        ]

        self._profile_generation = generation
        return self._profile_start_queue(
            queue, f"Записываю профиль, поколение {generation}, сумма 0x{crc:04X}...")

    # ------------------------------------------------------------------ файл

    def _profile_to_dict(self) -> dict:
        """Собирает профиль в вид, пригодный для файла."""
        return {
            "формат": 1,
            "алгоритм_измерения": PROFILE_ALGORITHM_ID,
            "поколение": int(self._profile_generation),
            "контрольная_сумма": self._profile_calc_crc(),
            "таблицы": {name: list(self._profile_values[name])
                        for name, _did, _title, _width in self.PROFILE_TABLES},
        }

    def _profile_save_file(self, path: str) -> bool:
        """Сохраняет профиль в файл. Это и есть откат: файл можно вернуть обратно."""
        try:
            target = pathlib.Path(str(path))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(self._profile_to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            self._profile_set_status(f"Не удалось сохранить файл: {error}", "#dc2626")
            return False

        self._profile_file_path = str(path)
        self._profile_set_status(f"Профиль сохранён в {path}", "#16a34a")
        return True

    def _profile_load_file(self, path: str) -> bool:
        """Загружает профиль из файла.

        Принимает и свой файл, и тот, что выдаёт расчёт по журналу камеры: у них
        разные имена полей, поэтому разбираются оба вида.
        """
        try:
            payload = json.loads(pathlib.Path(str(path)).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            self._profile_set_status(f"Не удалось прочитать файл: {error}", "#dc2626")
            return False

        loaded = self._profile_apply_own_format(payload) or self._profile_apply_chamber_format(payload)
        if not loaded:
            self._profile_set_status(
                "Файл не похож ни на профиль, ни на результат расчёта по журналу камеры.", "#dc2626")
            return False

        self._profile_file_path = str(path)
        self._profile_set_status(
            f"Профиль загружен из файла, сумма 0x{self._profile_calc_crc():04X}. "
            "В прибор он ещё не записан.", "#d97706")
        return True

    def _profile_apply_own_format(self, payload) -> bool:
        """Разбирает файл, сохранённый этим же окном."""
        if not isinstance(payload, dict) or "таблицы" not in payload:
            return False

        tables = payload.get("таблицы") or {}
        for name, _did, _title, width in self.PROFILE_TABLES:
            values = tables.get(name)
            expected = PROFILE_POINTS * width
            if isinstance(values, list) and len(values) == expected:
                self._profile_values[name] = [int(item) for item in values]

        self._profile_generation = int(payload.get("поколение", 0)) & 0xFFFF
        self.profileChanged.emit()
        return True

    def _profile_apply_chamber_format(self, payload) -> bool:
        """Разбирает файл, который выдаёт расчёт по журналу камеры."""
        if not isinstance(payload, dict) or "ступень_платы" not in payload:
            return False

        nodes = payload.get("узлы_x10")
        if isinstance(nodes, list) and len(nodes) == PROFILE_POINTS:
            self._profile_values["nodes"] = [int(item) for item in nodes]

        board = payload.get("ступень_платы")
        if isinstance(board, list) and len(board) == PROFILE_POINTS:
            flat: list[int] = []
            for pair in board:
                flat.extend([int(pair[0]), int(pair[1])])
            self._profile_values["board_main"] = flat

        tube = payload.get("ступень_трубки") or {}
        mapping = {
            "tube_air_main": "air_main",
            "tube_full_main": "full_main",
            "tube_air_media": "air_media",
            "tube_full_media": "full_media",
        }
        for name, key in mapping.items():
            values = tube.get(key)
            if isinstance(values, list) and len(values) == PROFILE_POINTS:
                self._profile_values[name] = [int(item) for item in values]

        self.profileChanged.emit()
        return True

    # ------------------------------------------------------------------ вид для окна

    def _profile_rows(self) -> list:
        """Готовит таблицы для показа: строка на каждую величину."""
        rows = []
        nodes = self._profile_values["nodes"]

        rows.append({
            "title": "Температура узла, °C",
            "values": [f"{value / 10:.0f}" for value in nodes],
            "editable": False,
        })

        for name, _did, title, width in self.PROFILE_TABLES:
            if name == "nodes":
                continue
            values = self._profile_values[name]
            if width == 2:
                rows.append({
                    "title": f"{title}: сдвиг",
                    "values": [str(values[index * 2]) for index in range(PROFILE_POINTS)],
                    "editable": True,
                })
                rows.append({
                    "title": f"{title}: растяжение, ppm",
                    "values": [str(values[index * 2 + 1]) for index in range(PROFILE_POINTS)],
                    "editable": True,
                })
            else:
                rows.append({
                    "title": title,
                    "values": [str(value) for value in values],
                    "editable": True,
                })

        return rows

    def _profile_set_cell(self, row: int, column: int, text: str) -> bool:
        """Меняет одно значение таблицы по её месту в показанном списке строк.

        Первая строка это температуры узлов, её править нельзя: сетка задаётся
        расчётом по журналу камеры, а руками в неё легко внести противоречие.
        """
        if not (0 <= column < PROFILE_POINTS):
            return False

        try:
            value = int(str(text).strip().replace(" ", ""))
        except ValueError:
            self._profile_set_status("Значение должно быть целым числом.", "#dc2626")
            return False

        if not (-32768 <= value <= 32767):
            self._profile_set_status("Значение не помещается в два байта.", "#dc2626")
            return False

        index = 1
        for name, _did, _title, width in self.PROFILE_TABLES:
            if name == "nodes":
                continue
            for part in range(width):
                if index == row:
                    self._profile_values[name][column * width + part] = value
                    self._profile_set_status(
                        f"Значение изменено, новая сумма 0x{self._profile_calc_crc():04X}. "
                        "В прибор изменение ещё не записано.", "#d97706")
                    return True
                index += 1

        return False

    def _profile_device_status_text(self) -> str:
        """Расшифровывает состояние профиля, прочитанное из прибора."""
        status = self._profile_device_status
        if status is None:
            return "Состояние из прибора не читалось"

        if not (status & 0x01):
            return "В приборе профиль пустой, работают прежние коэффициенты"

        parts = []
        parts.append("сумма сходится" if (status & 0x02) else "СУММА НЕ СХОДИТСЯ")
        parts.append("алгоритм совпадает" if (status & 0x04) else "АЛГОРИТМ НЕ ТОТ")
        parts.append("таблицы применяются" if (status & 0x08) else "ТАБЛИЦЫ НЕ ПРИМЕНЯЮТСЯ")
        return "; ".join(parts)
