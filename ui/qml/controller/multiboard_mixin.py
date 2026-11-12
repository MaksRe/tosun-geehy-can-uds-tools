"""Прогон нескольких плат в климатической камере одновременно.

ЗАЧЕМ
В камеру ставят сразу несколько плат (для начала три), чтобы за один прогон
снять температурную калибровку всех. Камера одна, температура воздуха общая, а
журнал точек, таблицы и профиль у каждой платы свои.

КАК УСТРОЕНО
- «Платы в камере» - список адресов на шине CAN (SA) с именами, хранится в
  config/chamber_boards.json. Адреса должны быть разными: их задают заранее
  операцией смены SA (подключая платы по одной).
- Контекст платы. Всё, что прогон хранит об одной плате (живой опрос и средние,
  журнал точек, таблицы, запись профиля), - набор полей контроллера. У каждой
  платы свой набор; программа подставляет его на время работы с платой, а
  «показанная» плата (её видно в окне) держит свой набор в полях постоянно.
- Опрос идёт по кругу по всем платам, такт короче, чем у одной платы.
- Шина освобождается: обычная рассылка J1939 у всех плат выключается одной
  функциональной командой CommunicationControl (0x28, «приём есть, передачи
  нет», без ответа) и повторяется раз в 10 с - прибор сам возвращает рассылку при
  сбросе диагностического сеанса. После прогона рассылка включается обратно.
- Доводка камеры - по средней температуре плат; точки снимаются у всех плат на
  каждом шаге; плата дальше ±3 °C от узла - предупреждение.
- Профиль пишется в каждую плату по очереди, когда прогон кончился.
"""

from __future__ import annotations

import copy
import json
import pathlib
import time
from contextlib import contextmanager
from datetime import datetime

import chamber_fit
from uds.uds_identifiers import UdsIdentifiers

from .bus_guard import note_background_request
from .chamber_mixin import is_stage1_point, journal_makeup, journal_sa, stage1_nodes
from .contract import AppControllerContract

# Поля одной платы: всё, что прогон в камере хранит о приборе. Подставляются целиком.
BOARD_ATTRS = (
    # Живой опрос и средние.
    "_chamber_live_last", "_chamber_live_seen", "_chamber_live_recent", "_chamber_live_outliers",
    "_chamber_live_restart_s", "_chamber_live_refusals", "_chamber_live_missing",
    # Очередная величина опроса: общий номер при 2, 3, 4 и 6 платах отдавал бы плате не все величины.
    "_chamber_live_index",
    "_chamber_capture_waiting", "_chamber_capture_wait_since",
    # Журнал точек и таблицы.
    "_chamber_points", "_chamber_file_path", "_chamber_report", "_chamber_status", "_chamber_status_color",
    "_chamber_tables_text", "_chamber_tables_color", "_chamber_tables_complete", "_chamber_tables_deferred",
    "_chamber_repeat_last",
    # 12.11.2026: откуда взят журнал платы (кнопка первого этапа, открыт из списка) - для таблицы журналов.
    "_chamber_journal_origin",
    # Размах «жидкость − воздух» у каждой платы свой: общее поле приходилось вписывать заново перед каждой.
    "_chamber_span_main", "_chamber_span_media",
    # Монитор отклонений: опора и история по узлам у каждой платы своя.
    "_chamber_monitor_ref", "_chamber_monitor_history", "_chamber_monitor_last_s",
    # Запись профиля одной операцией.
    "_chamber_chain_stage", "_chamber_chain_steps", "_chamber_chain_status", "_chamber_chain_color",
    "_chamber_chain_deadline", "_chamber_chain_crc", "_chamber_written_crc",
    # Профиль.
    "_profile_values", "_profile_generation", "_profile_device_crc", "_profile_device_crc_actual",
    "_profile_device_status", "_profile_status", "_profile_status_color", "_profile_last_result",
    "_profile_file_path", "_profile_verify", "_profile_verify_report",
)


class AppControllerMultiBoardMixin(AppControllerContract):
    # Такт опроса при нескольких платах, мс: чуть длиннее защитного интервала фоновых запросов (80 мс),
    # чтобы каждый такт уходил запрос; по кругу каждой плате - примерно запрос в 0,3 с.
    MB_LIVE_PERIOD_MS = 90
    # Как часто повторять «тишину» на шине (CommunicationControl), с.
    MB_QUIET_EVERY_S = 10.0
    # Сколько ждать среднего от платы при снятии точек шага, с; потом шаг идёт дальше без неё.
    MB_CAPTURE_WAIT_S = 60.0
    # Сколько ждать записи профиля одной платы, с.
    MB_CHAIN_WAIT_S = 600.0
    # Сколько ждать закрытия калибровки прежней платы перед записью профиля в следующую, с.
    MB_SWITCH_WAIT_S = 15.0
    # Показание считается текущим, пока не старше стольких кругов опроса своей величины.
    MB_STALE_ROUNDS = 2.5
    # Плата «на шине», если присылала температуру не позже стольких секунд назад.
    MB_PRESENT_S = 60.0

    # ------------------------------------------------------------------ состояние

    def _init_multiboard_state(self):
        """Готовит прогон нескольких плат. Идёт после прогона, живого опроса и записи профиля."""
        # Чистый набор полей платы: из него заводится новая плата.
        self._mb_template = {name: copy.deepcopy(getattr(self, name, None)) for name in BOARD_ATTRS}
        self._mb_boards: list[dict] = []
        self._mb_enabled = False
        self._mb_quiet_bus = True
        self._mb_contexts: dict[int, dict] = {}
        self._mb_active_sa: int | None = None
        self._mb_temp_depth = 0
        self._mb_poll_index = 0
        self._mb_pending_sa: int | None = None
        self._mb_quiet_last_s = 0.0
        self._mb_quiet_on = False
        self._mb_capture_stage_since: float | None = None
        self._mb_captured: set[int] = set()
        self._mb_profile_queue: list[int] = []
        self._mb_profile_current: int | None = None
        self._mb_profile_since = 0.0
        self._mb_profile_results: dict[int, str] = {}
        self._mb_switch_since: float | None = None
        self._mb_status = ""
        # Отчёт последнего нажатия «Журналы первого этапа всем платам»: строка на плату.
        # Сколько очередей опроса подряд пропущено у плат, которых нет на шине.
        self._mb_silent_turns: dict[int, int] = {}
        self._mb_stage1_report: list[dict] = []
        self._mb_stage1_at = ""
        # Лента плат над разделами калибровки видна: опрос всех плат нужен и вне раздела прогона.
        self._mb_strip_visible = False
        # Почему не удалось переключить показанную плату - строка в ленте, видна 8 с.
        self._mb_switch_note = ""
        self._mb_switch_note_s = 0.0
        # Точка вручную («Записать точку» в окне, на сайте, в боте): у всех плат, когда она началась.
        self._mb_manual_capture: float | None = None
        # Адреса плат, у которых снимается эта точка вручную (погружение - только у показанной).
        self._mb_manual_boards: list[int] = []
        # Участники прогона: платы списка, которые были на шине при старте. Остальные платы списка
        # (снятые, в другой камере) прогону не мешают. None - прогона с участниками ещё не было.
        self._mb_run_sas: list[int] | None = None
        self._mb_load()
        self._mb_apply_period()

    def _mb_config_path(self) -> pathlib.Path:
        root = getattr(self, "_project_root_directory", None) or pathlib.Path.cwd()
        return pathlib.Path(root) / "config" / "chamber_boards.json"

    def _mb_load(self):
        """Список плат с прошлого раза. Испорченный файл не мешает запуску."""
        try:
            payload = json.loads(self._mb_config_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        boards = []
        for item in payload.get("boards") or []:
            try:
                sa = int(item.get("sa")) & 0xFF
            except (TypeError, ValueError, AttributeError):
                continue
            if sa not in [board["sa"] for board in boards]:
                board = {"sa": sa, "name": str(item.get("name") or f"0x{sa:02X}")[:24]}
                # Размах платы помнится между запусками: его меряют на столе один раз.
                for key in ("span_main", "span_media"):
                    try:
                        value = item.get(key)
                        if value is not None and int(value) > 0:
                            board[key] = int(value)
                    except (TypeError, ValueError):
                        pass
                boards.append(board)
        self._mb_boards = boards
        self._mb_enabled = bool(payload.get("enabled", False)) and len(boards) >= 2
        self._mb_quiet_bus = bool(payload.get("quiet_bus", True))
        if self._mb_enabled:
            self._mb_activate(boards[0]["sa"], force=True)

    def _mb_save(self):
        try:
            path = self._mb_config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"enabled": self._mb_enabled, "quiet_bus": self._mb_quiet_bus,
                                        "boards": self._mb_boards}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _mb_on(self) -> bool:
        """Идёт ли работа с несколькими платами: включено и плат в списке не меньше двух."""
        return bool(getattr(self, "_mb_enabled", False)) and len(getattr(self, "_mb_boards", []) or []) >= 2

    def _mb_board(self, sa: int) -> dict | None:
        return next((board for board in self._mb_boards if board["sa"] == int(sa) & 0xFF), None)

    def _mb_name(self, sa: int | None) -> str:
        board = self._mb_board(sa) if sa is not None else None
        return board["name"] if board else ("—" if sa is None else f"0x{int(sa) & 0xFF:02X}")

    def _mb_label(self, sa: int | None) -> str:
        """Цель функции в плате для сообщений: адрес узла - привязка, имя - пометка в скобках («0x82 (П2)»).

        09.11.2026: имя платы - произвольная подпись (две платы были названы «П6»), а адрес узла на шине
        однозначен; поэтому в событиях, предупреждениях и статусах плата называется по адресу.
        """
        if sa is None:
            return "—"
        sa = int(sa) & 0xFF
        board = self._mb_board(sa)
        address = f"0x{sa:02X}"
        return f"{address} ({board['name']})" if board and board["name"] and board["name"] != address else address

    # ------------------------------------------------------------------ контекст платы

    def _mb_store(self, sa: int):
        self._mb_contexts[int(sa)] = {name: getattr(self, name, None) for name in BOARD_ATTRS}

    def _mb_restore(self, sa: int):
        context = self._mb_contexts.get(int(sa))
        if context is None:
            context = copy.deepcopy(self._mb_template)
            board = self._mb_board(sa) or {}
            context["_chamber_span_main"] = board.get("span_main")
            context["_chamber_span_media"] = board.get("span_media")
            self._mb_contexts[int(sa)] = context
        for name, value in context.items():
            setattr(self, name, value)

    def _mb_remember_spans(self):
        """Размах показанной платы - в список плат на диске: его меряют на столе один раз."""
        if not self._mb_on() or self._mb_active_sa is None:
            return
        board = self._mb_board(self._mb_active_sa)
        if board is None:
            return
        for key, value in (("span_main", getattr(self, "_chamber_span_main", None)),
                           ("span_media", getattr(self, "_chamber_span_media", None))):
            if value is None:
                board.pop(key, None)
            else:
                board[key] = int(value)
        self._mb_save()

    def _mb_busy(self) -> bool:
        """Идёт обмен, который держит поля текущей платы: подменять их нельзя."""
        return (bool(getattr(self, "_chamber_busy", False)) or bool(getattr(self, "_profile_busy", False))
                or bool(getattr(self, "_chamber_chain_stage", "")))

    @contextmanager
    def _mb_context(self, sa: int, notify: bool = True):
        """Поля платы sa на время блока; потом - снова поля показанной платы.

        На время блока сигналы контроллера придержаны: иначе окно перечитало бы показания, пока в
        полях стоит чужая плата, и верхняя панель «мигала» бы данными других плат. После блока
        (notify=True) окно получает одно «показания обновились» - уже с полями показанной платы.
        Если показанной платы нет, свободные поля сохраняются и возвращаются: иначе плата, с которой
        работали последней, «забрала» бы их, и при включении режима две платы писали бы в одно окно.
        """
        sa = int(sa) & 0xFF
        previous_target = getattr(self, "_calibration_target_node_sa", None)
        if sa == self._mb_active_sa:
            self._calibration_target_node_sa = sa
            try:
                yield
            finally:
                self._calibration_target_node_sa = previous_target
            return
        active = self._mb_active_sa
        free = None
        if active is not None:
            self._mb_store(active)
        else:
            free = {name: getattr(self, name, None) for name in BOARD_ATTRS}
        outer = self._mb_temp_depth == 0
        block = getattr(self, "blockSignals", None)
        blocked = outer and block is not None and not self.signalsBlocked()
        if blocked:
            block(True)
        self._mb_restore(sa)
        self._mb_active_sa = sa
        self._calibration_target_node_sa = sa
        self._mb_temp_depth += 1
        try:
            yield
        finally:
            self._mb_temp_depth -= 1
            self._mb_store(sa)
            if active is not None:
                self._mb_restore(active)
            else:
                for name, value in free.items():
                    setattr(self, name, value)
            self._mb_active_sa = active
            self._calibration_target_node_sa = previous_target
            if blocked:
                block(False)
                if notify:
                    signal = getattr(self, "chamberLiveChanged", None)
                    if signal is not None:
                        signal.emit()

    def _mb_activate(self, sa: int, force: bool = False) -> bool:
        """Показать плату sa: её журнал, таблицы и профиль - в окне. Нельзя посреди обмена с прибором."""
        sa = int(sa) & 0xFF
        if self._mb_active_sa == sa:
            self._calibration_target_node_sa = sa
            return True
        if not force and (self._mb_busy() or bool(getattr(self, "_trial_busy", False))):
            # Причина - в ленте плат (она в том же окне), а не всплывающей подсказкой главного окна.
            what = "идёт пробная калибровка" if getattr(self, "_trial_busy", False) else "идёт обмен с прибором"
            self._mb_switch_note = (f"Переключиться на {self._mb_label(sa)} сейчас нельзя: {what} с "
                                    f"{self._mb_label(self._mb_active_sa)}. Подождите конца.")
            self._mb_switch_note_s = time.monotonic()
            self._mb_changed()
            return False
        self._mb_switch_note = ""
        if self._mb_active_sa is not None:
            self._mb_store(self._mb_active_sa)
            self._mb_restore(sa)
        else:
            # Первая показанная плата забирает то, что уже было в полях (открытый журнал).
            self._mb_store(sa)
        self._mb_active_sa = sa
        self._calibration_target_node_sa = sa
        # «Текущие данные узла» теперь про другую плату: прежние значения и графики сбрасываются.
        forget = getattr(self, "_node_live_forget", None)
        if forget is not None:
            forget()
        for name in ("chamberChanged", "chamberLiveChanged", "profileChanged"):
            signal = getattr(self, name, None)
            if signal is not None:
                signal.emit()
        return True

    # ------------------------------------------------------------------ список плат

    def _mb_set_enabled(self, enabled: bool) -> tuple[bool, str]:
        if getattr(self, "_climate_run_stage", ""):
            return False, "идёт прогон: режим нескольких плат меняется после него"
        if enabled and len(self._mb_boards) < 2:
            return False, "добавьте хотя бы две платы с разными адресами"
        if enabled and self._mb_busy():
            return False, "дождитесь конца обмена с прибором"
        self._mb_enabled = bool(enabled)
        if self._mb_enabled:
            self._mb_activate(self._mb_boards[0]["sa"], force=True)
        else:
            self._mb_quiet_release()
        self._mb_apply_period()
        self._mb_save()
        self._mb_changed()
        return True, "несколько плат: " + ("включено" if self._mb_enabled else "выключено")

    def _mb_add_board(self, sa_text, name: str = "") -> tuple[bool, str]:
        try:
            text = str(sa_text).strip()
            sa = int(text, 16) if text.lower().startswith("0x") else int(text)
        except (TypeError, ValueError):
            return False, "адрес - число, например 0x80 или 128"
        if not 0 <= sa <= 0xFD:
            return False, "адрес на шине - от 0x00 до 0xFD"
        testers = {int(UdsIdentifiers.tx.src) & 0xFF, int(UdsIdentifiers.rx.dst) & 0xFF}
        if sa in testers:
            return False, f"0x{sa:02X} - адрес самой программы на шине"
        if self._mb_board(sa) is not None:
            return False, f"плата 0x{sa:02X} уже в списке"
        if getattr(self, "_climate_run_stage", ""):
            return False, "идёт прогон: список плат меняется после него"
        name = str(name or "").strip()[:24] or f"Плата {len(self._mb_boards) + 1}"
        self._mb_boards.append({"sa": sa, "name": name})
        self._mb_save()
        self._mb_changed()
        return True, f"плата «{name}» (0x{sa:02X}) добавлена"

    def _mb_remove_board(self, sa: int) -> tuple[bool, str]:
        sa = int(sa) & 0xFF
        board = self._mb_board(sa)
        if board is None:
            return False, "такой платы нет"
        if getattr(self, "_climate_run_stage", ""):
            return False, "идёт прогон: список плат меняется после него"
        if self._mb_active_sa == sa:
            others = [item["sa"] for item in self._mb_boards if item["sa"] != sa]
            if others and not self._mb_activate(others[0]):
                return False, "дождитесь конца обмена с прибором"
            if not others:
                self._mb_active_sa = None
        self._mb_boards.remove(board)
        self._mb_contexts.pop(sa, None)
        if len(self._mb_boards) < 2 and self._mb_enabled:
            self._mb_enabled = False
            self._mb_quiet_release()
            self._mb_apply_period()
        self._mb_save()
        self._mb_changed()
        return True, f"плата {self._mb_label(board['sa'])} убрана из списка"

    def _mb_rename_board(self, sa: int, name: str) -> bool:
        board = self._mb_board(sa)
        if board is None or not str(name).strip():
            return False
        board["name"] = str(name).strip()[:24]
        self._mb_save()
        self._mb_changed()
        return True

    def _mb_change_sa(self, old: int, new: int) -> bool:
        """Цель функции в новом адресе платы после его смены в приборе, затем её журнал, таблицы и профиль - с ней."""
        old, new = int(old) & 0xFF, int(new) & 0xFF
        board = self._mb_board(old)
        if board is None or self._mb_board(new) is not None or getattr(self, "_climate_run_stage", ""):
            return False
        board["sa"] = new
        if old in self._mb_contexts:
            self._mb_contexts[new] = self._mb_contexts.pop(old)
        if old in self._mb_profile_results:
            self._mb_profile_results[new] = self._mb_profile_results.pop(old)
        if self._mb_active_sa == old:
            self._mb_active_sa = new
            self._calibration_target_node_sa = new
        self._mb_save()
        self._mb_changed()
        return True

    def _mb_bus_candidates(self) -> list[int]:
        """Адреса плат, замеченные на шине: из них удобно набрать список."""
        testers = {int(UdsIdentifiers.tx.src) & 0xFF, int(UdsIdentifiers.rx.dst) & 0xFF}
        found = set()
        for raw in list(getattr(self, "_observed_candidate_values", []) or []) + \
                list(getattr(self, "_collector_node_order", []) or []):
            try:
                found.add(int(raw) & 0xFF)
            except (TypeError, ValueError):
                continue
        return sorted(sa for sa in found - testers if self._mb_board(sa) is None)

    def _mb_changed(self):
        for name in ("chamberChanged", "climateChanged", "boardAddressingChanged"):
            signal = getattr(self, name, None)
            if signal is not None:
                signal.emit()

    def _mb_apply_period(self):
        timer = getattr(self, "_chamber_live_timer", None)
        if timer is not None:
            timer.setInterval(self.MB_LIVE_PERIOD_MS if self._mb_on() else self.CHAMBER_LIVE_PERIOD_MS)

    # ------------------------------------------------------------------ опрос по кругу

    # ------------------------------------------------------------------ какие платы в работе

    def _mb_run_active(self) -> bool:
        return bool(getattr(self, "_climate_run_stage", "")) and self._mb_run_sas is not None

    def _mb_on_bus(self, sa: int, now: float | None = None) -> bool:
        """Плата присылала температуру за последнюю минуту."""
        now = time.monotonic() if now is None else now
        with self._mb_context(sa, notify=False):
            seen = float((self._chamber_live_seen or {}).get("board_temp", 0.0) or 0.0)
        return seen > 0.0 and now - seen <= self.MB_PRESENT_S

    def _mb_working_boards(self, now: float | None = None) -> list[dict]:
        """Платы, с которыми идёт работа: в прогоне - его участники, вне прогона - те, что на шине.

        Список плат камеры - все платы, когда-либо поставленные в камеру; в этот раз их может
        быть меньше (7 плат без трубок, затем 3 в корпусе в другой камере). Точки, средняя
        температура, профили, сайт и бот - только по работающим платам.
        """
        if self._mb_run_active():
            return [board for board in self._mb_boards if board["sa"] in self._mb_run_sas]
        return [board for board in self._mb_boards if self._mb_on_bus(board["sa"], now)]

    def _mb_polled_boards(self) -> list[dict]:
        """Кого опрашивать: в прогоне - только участников (опрос чаще), иначе всех - чтобы найти, кто на шине."""
        if self._mb_run_active():
            return [board for board in self._mb_boards if board["sa"] in self._mb_run_sas] or list(self._mb_boards)
        return list(self._mb_boards)

    def _mb_profile_boards(self) -> list[dict]:
        """Кому писать профиль и о ком итог: участникам прогона (после него - тем из них, кто на шине)."""
        working = self._mb_working_boards()
        if self._mb_run_active() or self._mb_run_sas is None:
            return working
        return [board for board in working if board["sa"] in self._mb_run_sas] or working

    def _mb_run_begin(self, now: float) -> tuple[list[str], list[str]]:
        """Старт прогона: участники - платы, приславшие температуру. (кто вошёл, кто без связи)."""
        alive, silent = [], []
        for board in self._mb_boards:
            with self._mb_context(board["sa"], notify=False):
                fresh = self._chamber_live_fresh("board_temp", now)
            (alive if fresh else silent).append(board)
        self._mb_run_sas = [int(board["sa"]) for board in alive]
        self._mb_changed()
        return ([self._mb_label(board["sa"]) for board in alive],
                [self._mb_label(board["sa"]) for board in silent])

    def _mb_set_run_boards(self, sas):
        """После перезапуска программы: участники прогона - те, чьи журналы сохранены в состоянии."""
        wanted = {int(sa) & 0xFF for sa in sas or []}
        self._mb_run_sas = [int(board["sa"]) for board in self._mb_boards if int(board["sa"]) in wanted] or None
        self._mb_changed()

    def _mb_stale_s(self, base: float, order_length: int) -> float:
        """Цель функции в пороге «показание устарело» при нескольких платах: опрос по кругу идёт дольше.

        Каждая плата получает запрос раз в (число плат) тактов, а температура - одна из шести величин
        круга; при пяти платах её показание обновляется раз в 2,7 с, и прежний порог 3 с давал бы
        ложное «прибор не отдал температуру» от одного потерянного ответа.
        """
        if not self._mb_on():
            return float(base)
        round_s = float(order_length) * len(self._mb_polled_boards()) * self.MB_LIVE_PERIOD_MS / 1000.0
        return max(float(base), self.MB_STALE_ROUNDS * round_s)

    def _mb_live_tick(self, now: float):
        """Такт опроса нескольких плат: очередная величина очередной платы."""
        if self._mb_busy() or bool(getattr(self, "_mb_profile_current", None) is not None):
            return
        self._mb_quiet_keep(now)
        if self._chamber_live_pending is not None and now - self._chamber_live_pending_s < self.CHAMBER_LIVE_PENDING_S:
            return
        boards = [board["sa"] for board in self._mb_polled_boards()]
        for _attempt in range(len(boards)):
            sa = boards[self._mb_poll_index % len(boards)]
            self._mb_poll_index += 1
            if self._mb_skip_silent(sa, now):
                continue
            with self._mb_context(sa, notify=False):
                picked = self._chamber_live_next_request()
                if picked is None:
                    continue
                self._chamber_live_pending = picked
                self._chamber_live_pending_s = now
                self._mb_pending_sa = sa
                note_background_request(self)
                try:
                    self._chamber_live_read.read_data_by_identifier(self._build_calibration_tx_identifier(), picked[1])
                except Exception:
                    self._chamber_live_pending = None
                    self._mb_pending_sa = None
            return

    # Плату, которой нет на шине, вне прогона спрашивать раз в столько её очередей: она ищется,
    # но не удлиняет круг опроса живых плат (11.11.2026: три платы на шине из шести в списке).
    MB_SILENT_EVERY = 8

    def _mb_skip_silent(self, sa: int, now: float) -> bool:
        """Пропустить очередь платы, которой нет на шине: в прогоне - никогда, иначе 7 очередей из 8."""
        if self._mb_run_active() or self._mb_on_bus(sa, now):
            self._mb_silent_turns.pop(int(sa), None)
            return False
        turns = self._mb_silent_turns.get(int(sa), 0) + 1
        self._mb_silent_turns[int(sa)] = turns
        return turns % self.MB_SILENT_EVERY != 1

    def _mb_handle_live_frame(self, identifier: int, payload) -> bool:
        """Ответ одной из плат: в её средние. True - кадр от платы из списка (разобран)."""
        parsed = self._parse_calibration_response_identifier(identifier)
        if parsed is None:
            return False
        _pgn, _dst, src = parsed
        if self._mb_board(src) is None:
            return False
        pending = self._chamber_live_pending
        mine = self._mb_pending_sa == (int(src) & 0xFF)
        with self._mb_context(src):
            if not mine:
                self._chamber_live_pending = None
            self._chamber_live_frame_apply(identifier, payload)
            answered = self._chamber_live_pending is None
        if mine:
            self._chamber_live_pending = None if answered else pending
            if answered:
                self._mb_pending_sa = None
        else:
            self._chamber_live_pending = pending
        return True

    def _mb_board_temp_x10(self, now: float, key: str = "board_temp") -> float | None:
        """Средняя температура плат (0,1 °C) - по ней прогон судит об устаивании и доводке.

        key - какой датчик: платы или, во втором этапе, топлива (трубки).
        """
        values = []
        for board in self._mb_working_boards(now):
            with self._mb_context(board["sa"], notify=False):
                if not self._chamber_live_fresh(key, now):
                    continue
                stats = self._chamber_live_stats(key, now)
                values.append(stats["mean"] if stats is not None else float(self._chamber_live_last[key]))
        return sum(values) / len(values) if values else None

    def _mb_silent_boards(self, now: float) -> list[str]:
        """Платы, которые не присылают температуру: без них прогон не начать."""
        silent = []
        for board in self._mb_boards:
            with self._mb_context(board["sa"], notify=False):
                if not self._chamber_live_fresh("board_temp", now):
                    silent.append(self._mb_label(board["sa"]))
        return silent

    # ------------------------------------------------------------------ тишина на шине

    def _mb_quiet_frame_identifier(self) -> int:
        """Функциональный CAN ID 0x18DBFFxx: команда сразу всем платам."""
        tx_identifier = int(UdsIdentifiers.tx.identifier)
        priority = (tx_identifier >> 26) & 0x07
        return int((priority << 26) | (0xDBFF << 8) | (tx_identifier & 0xFF))

    def _mb_quiet_send(self, enable_tx: bool) -> bool:
        service = getattr(self, "_communication_control_service", None)
        if service is None or bool(getattr(self, "_communication_control_busy", False)):
            return False
        try:
            return bool(service.request(control_type=0 if enable_tx else 1, communication_type=0x01,
                                        suppress_positive_response=True,
                                        tx_identifier=self._mb_quiet_frame_identifier()))
        except Exception:
            return False

    def _mb_quiet_keep(self, now: float):
        """Пока идёт прогон нескольких плат - их рассылка J1939 выключена (повтор раз в 10 с).

        Только на время прогона: после него (и при остановке) рассылка возвращается, иначе
        платы молчали бы до перезагрузки питания, даже когда программа закрыта.
        """
        if not self._mb_quiet_bus or not self._mb_on() or not getattr(self, "_climate_run_stage", ""):
            return
        if now - self._mb_quiet_last_s < self.MB_QUIET_EVERY_S:
            return
        self._mb_quiet_last_s = now
        if self._mb_quiet_send(enable_tx=False):
            self._mb_quiet_on = True

    def _mb_quiet_release(self):
        """Вернуть платам обычную рассылку."""
        if self._mb_quiet_on and self._mb_quiet_send(enable_tx=True):
            self._mb_quiet_on = False
        self._mb_quiet_last_s = 0.0

    # ------------------------------------------------------------------ точки шага

    def _mb_run_capture(self, now: float, node: float, only: list[int] | None = None) -> bool:
        """Снять точку шага у всех плат (или у плат only). True - все сняты (или время ожидания вышло)."""
        if self._mb_capture_stage_since is None:
            self._mb_capture_stage_since = now
            self._mb_captured = set()
        wanted = None if node is None else chamber_fit.nearest_node(int(round(float(node) * 10)))
        boards = [board for board in self._mb_working_boards(now) if only is None or board["sa"] in only]
        waiting = []
        for board in boards:
            sa = board["sa"]
            if sa in self._mb_captured:
                continue
            with self._mb_context(sa, notify=False):
                point, detail = self._chamber_live_point(now)
                if point is None:
                    waiting.append(f"{self._mb_label(sa)}: {detail or 'среднее ещё не готово'}")
                    continue
                self._chamber_append_point(point, detail)
                self._mb_captured.add(sa)
                # Узел точки - по тому датчику, по которому её разложит расчёт (трубка - по датчику топлива).
                steer = getattr(self, "_climate_steer_key", None)
                field = "fuel_temp_x10" if steer is not None and steer() == "fuel_temp" else "board_temp_x10"
                got = chamber_fit.nearest_node(point[field])
                if wanted is not None and got != wanted:
                    what = "трубки" if field == "fuel_temp_x10" else "платы"
                    self._climate_event(f"плата {self._mb_label(sa)}: точка при {point[field] / 10:+.1f} °C ({what}) - "
                                        f"не в узле {chamber_fit.node_text(wanted)} (±3 °C), в таблицу узла не "
                                        "попадёт.", "warn")
        left = max(0, int(self.MB_CAPTURE_WAIT_S - (now - self._mb_capture_stage_since)))
        self._mb_status = (f"Точки записаны у {sum(board['sa'] in self._mb_captured for board in boards)} "
                           f"из {len(boards)} плат."
                           + (f" Жду до {left} с: " + "; ".join(waiting) if waiting else ""))
        self._mb_changed()
        missing = [board for board in boards if board["sa"] not in self._mb_captured]
        if not missing:
            self._mb_capture_stage_since = None
            return True
        if now - self._mb_capture_stage_since >= self.MB_CAPTURE_WAIT_S:
            names = ", ".join(self._mb_label(board["sa"]) for board in missing)
            self._climate_event(f"нет среднего от плат {names} за {self.MB_CAPTURE_WAIT_S:g} с: точка шага у них не "
                                "снята, прогон идёт дальше. Проверьте их связь.", "warn")
            self._mb_capture_stage_since = None
            return True
        return False

    # ------------------------------------------------------------------ профили после прогона

    def _mb_hold_chain(self) -> bool:
        """При нескольких платах профиль сам не пишется посреди прогона: только по очереди в конце."""
        return self._mb_on() and (self._mb_temp_depth > 0 or self._mb_profile_current is None)

    def _mb_manual_capture_start(self) -> tuple[bool, str]:
        """Цель функции в точке вручную у всех плат сразу: каждой - по её средним, ждём не дольше минуты."""
        if self._mb_manual_capture is not None:
            return False, "точка у плат уже записывается"
        if self._mb_capture_stage_since is not None:
            return False, "точки плат сейчас снимает прогон"
        now = time.monotonic()
        label = str(getattr(self, "_chamber_label", "") or "").strip()
        if label.casefold() == chamber_fit.LIQUID_NOTE and self._mb_active_sa is not None:
            # Трубку погружают по одной: «жидкость» у всех плат записала бы сухие трубки как погружённые.
            self._mb_manual_boards = [self._mb_active_sa]
            name = self._mb_name(self._mb_active_sa)
            self._mb_manual_capture = now
            self._mb_captured = set()
            self._mb_status = f"Записываю точку «{label}» у показанной платы «{name}»..."
            self._mb_manual_capture_tick(now)
            return True, (f"точка «{label}» записывается только у показанной платы «{name}»: погружают по одной "
                          "трубке. Для следующей платы покажите её в ленте плат и запишите точку снова")
        working = self._mb_working_boards(now)
        if not working:
            return False, "ни одна плата из списка не присылает температуру: точку снимать не у кого"
        self._mb_manual_boards = [board["sa"] for board in working]
        self._mb_manual_capture = now
        self._mb_captured = set()
        self._mb_status = f"Записываю точку у {len(working)} плат по их средним..."
        self._mb_manual_capture_tick(now)
        return True, (f"точка записывается у всех {len(working)} плат на шине по их средним; плата без среднего "
                      f"ждётся до {self.MB_CAPTURE_WAIT_S:g} с")

    def _mb_manual_capture_tick(self, now: float):
        """Цель функции в ходе точки вручную: каждая плата записывается, как только у неё готово среднее."""
        if self._mb_manual_capture is None or not self._mb_on():
            self._mb_manual_capture = None
            return
        only = list(self._mb_manual_boards) or [board["sa"] for board in self._mb_working_boards(now)]
        if not self._mb_run_capture(now, None, only):
            return
        self._mb_manual_capture = None
        wanted = [board for board in self._mb_boards if board["sa"] in only]
        done = [board["name"] for board in wanted if board["sa"] in self._mb_captured]
        missing = [board["name"] for board in wanted if board["sa"] not in self._mb_captured]
        label = str(getattr(self, "_chamber_label", "") or "").strip()
        if len(wanted) == 1:
            self._mb_status = (f"Точка «{label}» записана у платы «{wanted[0]['name']}»." if done else
                               f"Точка «{label}» у платы «{wanted[0]['name']}» не записана: нет среднего.")
            self._mb_changed()
            return
        self._mb_status = (f"Точка «{label}» записана у {len(done)} из {len(wanted)} плат"
                           + (f"; без среднего: {', '.join(missing)}" if missing else "") + ".")
        self._mb_changed()

    def _mb_start_profiles(self, manual: bool = False) -> str:
        """Запись профиля в каждую плату, у которой таблицы полные (конец прогона или кнопка). Возвращает итог."""
        if not self._mb_on():
            return ""
        if not manual and not bool(getattr(self, "_chamber_auto_write", False)):
            return ""
        if self._mb_profiles_busy():
            return "профили уже пишутся"
        queue = []
        for board in self._mb_profile_boards():
            with self._mb_context(board["sa"], notify=False):
                if self._chamber_tables_complete:
                    queue.append(board["sa"])
                else:
                    self._mb_profile_results[board["sa"]] = "таблицы неполные - профиль не записан"
        self._mb_profile_queue = queue
        self._mb_profile_current = None
        names = ", ".join(self._mb_label(sa) for sa in queue)
        text = (f"пишу профиль по очереди в платы с полными таблицами: {names}" if queue
                else "ни у одной платы таблицы не полные - писать нечего")
        self._mb_status = text[:1].upper() + text[1:] + "."
        self._mb_changed()
        return text

    def _mb_clear_journals(self):
        """Цель функции в новом журнале у всех плат сразу: следующая точка каждой начнёт новый файл."""
        for board in self._mb_working_boards():
            with self._mb_context(board["sa"], notify=False):
                self._chamber_clear_points()
        self._mb_changed()

    def _mb_board_temps(self, now: float) -> dict[int, tuple]:
        """Цель функции в средних температурах платы и топлива каждой платы (°C или None), для сайта и истории."""
        temps = {}
        for board in self._mb_working_boards(now):
            with self._mb_context(board["sa"], notify=False):
                values = []
                for key in ("board_temp", "fuel_temp"):
                    stats = self._chamber_live_stats(key, now) if self._chamber_live_fresh(key, now) else None
                    values.append(None if stats is None else stats["mean"] / 10.0)
                temps[int(board["sa"])] = tuple(values)
        return temps

    def _mb_board_details(self) -> dict[int, dict]:
        """Цель функции в подробностях каждой платы для сайта: что снято в узлах, журнал, итог таблиц, последняя точка."""
        details = {}
        for board in self._mb_working_boards():
            with self._mb_context(board["sa"], notify=False):
                points = list(self._chamber_points)
                details[int(board["sa"])] = {
                    "coverage": self._chamber_coverage_rows(),
                    "file": pathlib.Path(self._chamber_file_path).name if self._chamber_file_path else "",
                    "tablesText": str(self._chamber_tables_text or ""),
                    "lastPoint": str(points[-1].get("time", "")) if points else "",
                }
        return details

    def _mb_all_rows(self, limit: int = 60) -> list[dict]:
        """Цель функции в точках журналов всех плат одним списком (свежие сверху), с именем и адресом платы."""
        rows = []
        for board in self._mb_working_boards():
            with self._mb_context(board["sa"], notify=False):
                for row in self._chamber_rows():
                    rows.append(dict(row, board=str(board["name"]), sa=int(board["sa"])))
        rows.sort(key=lambda row: str(row.get("time", "")), reverse=True)
        return rows[:limit]

    def _mb_profiles_busy(self) -> bool:
        return bool(self._mb_profile_queue) or self._mb_profile_current is not None

    def _mb_profile_tick(self, now: float):
        """Очередь записи профилей: по одной плате, следующая - когда предыдущая записана.

        Перед каждой платой калибровка (сеанс и Security Access), открытая для другой
        платы, закрывается: доступ на запись открывается заново - для этой платы.
        """
        if not self._mb_on():
            return
        current = self._mb_profile_current
        if current is not None:
            stage = str(getattr(self, "_chamber_chain_stage", "") or "")
            if stage and now - self._mb_profile_since < self.MB_CHAIN_WAIT_S:
                return
            self._mb_profile_results[current] = str(getattr(self, "_chamber_chain_status", "") or "")
            self._mb_profile_current = None
            if stage:
                self._mb_profile_results[current] = "запись профиля не закончилась вовремя"
            self._mb_changed()
            reread = getattr(self, "_addr_queue_info", None)
            if reread is not None:
                reread(current)
            if not self._mb_profile_queue:
                # Последняя плата: калибровка закрывается, плата возвращается в обычный сеанс.
                self._mb_calibration_close()
        if not self._mb_profile_queue or self._mb_profile_current is not None:
            return
        sa = self._mb_profile_queue[0]
        if not self._mb_calibration_free_for(sa, now):
            return
        self._mb_profile_queue.pop(0)
        if not self._mb_activate(sa):
            self._mb_profile_queue.insert(0, sa)
            return
        self._mb_status = f"Пишу профиль в плату {self._mb_label(sa)}..."
        if self._chamber_chain_start(automatic=True) is False:
            # Цепочка не запустилась: причина - в итог платы, очередь идёт дальше.
            problem_of = getattr(self, "_chamber_chain_problem", None)
            problem = problem_of() if problem_of is not None else ""
            self._mb_profile_results[sa] = (f"профиль не записан: {problem}" if problem
                                            else "этот профиль уже записан в плату ранее")
            self._mb_changed()
            return
        self._mb_profile_current = sa
        self._mb_profile_since = now
        self._mb_changed()

    def _mb_calibration_free_for(self, sa: int, now: float) -> bool:
        """Цель функции в проверке, что калибровка не держит другую плату, затем запись профиля откроет доступ сама.

        Калибровка, запущенная для прежней платы, останавливается (прежняя плата
        возвращается в обычный сеанс); пока прибор не ответил - ожидание, не дольше 15 с.
        """
        active = bool(getattr(self, "_calibration_active", False))
        waiting = bool(getattr(self, "_calibration_waiting_session", False))
        if not active and not waiting:
            self._mb_switch_since = None
            return True
        if active and not waiting:
            target = getattr(self, "_service_access_target_sa", None)
            if bool(getattr(self, "_service_security_unlocked", False)) and target is not None \
                    and (int(target) & 0xFF) == (int(sa) & 0xFF):
                self._mb_switch_since = None
                return True
            self._mb_switch_since = now
            stop = getattr(self, "stopCalibration", None)
            if stop is not None:
                stop()
            return False
        if self._mb_switch_since is None:
            self._mb_switch_since = now
        if now - self._mb_switch_since >= self.MB_SWITCH_WAIT_S:
            # Прибор не подтвердил возврат сеанса: калибровка закрывается локально, плата сама
            # вернётся в обычный сеанс через 30 с без запросов.
            finish = getattr(self, "_finish_calibration_deactivation", None)
            if finish is not None:
                finish("Калибровка закрыта: прибор не ответил на возврат сеанса, следующая плата.")
            self._calibration_active = False
            self._mb_switch_since = None
        return False

    def _mb_calibration_close(self):
        """Цель функции в закрытии калибровки после последней платы, затем плата возвращается в обычный сеанс."""
        if bool(getattr(self, "_calibration_active", False)) and not bool(getattr(self, "_calibration_waiting_session", False)):
            stop = getattr(self, "stopCalibration", None)
            if stop is not None:
                stop()

    def _mb_journals(self) -> list[dict]:
        """Цель функции в журналах всех плат для сохранения состояния прогона, затем перезапуск вернёт каждой свой."""
        if not self._mb_on():
            return []
        result = []
        for board in self._mb_working_boards():
            with self._mb_context(board["sa"], notify=False):
                result.append({"sa": int(board["sa"]), "journal": str(self._chamber_file_path or "")})
        return result

    def _mb_find_run_journals(self, since: float | None) -> list[dict]:
        """Цель функции в журналах плат этого прогона на диске, когда их нет в сохранённом состоянии прогона.

        Состояние, сохранённое прежней версией, помнит журнал только показанной платы. Журнал каждой
        платы - файл chamber_<время>_<имя>_0x<адрес>.csv: берётся самый свежий файл с адресом платы,
        изменённый после начала прогона (since - время начала по часам компьютера, с запасом).
        """
        lister = getattr(self, "_chamber_journals", None)
        journals = lister(fresh=True) if lister is not None else []
        found = []
        for board in self._mb_boards:
            sa = int(board["sa"])
            tail = f"_0x{sa:02x}.csv"
            candidates = [item for item in journals if str(item.get("name", "")).lower().endswith(tail)
                          and (since is None or float(item.get("stamp", 0.0)) >= since)]
            if candidates:
                newest = max(candidates, key=lambda item: float(item.get("stamp", 0.0)))
                found.append({"sa": sa, "journal": str(newest["path"])})
        return found

    def _mb_open_journal_paths(self) -> dict[str, list[int]]:
        """Какой файл журнала у какой платы открыт сейчас: полный путь -> адреса плат."""
        result: dict[str, list[int]] = {}
        for board in self._mb_boards:
            sa = int(board["sa"])
            path = str(self._mb_context_value(sa, "_chamber_file_path") or "")
            if not path:
                continue
            try:
                key = str(pathlib.Path(path).resolve())
            except OSError:
                key = path
            result.setdefault(key, []).append(sa)
        return result

    def _mb_journals_table(self) -> dict:
        """Таблица назначения журналов для окна (вид таблицы итогов: ResultsTable.qml)."""
        rows = self._mb_journal_assignments()

        def column(key, title, tip, width, align="left"):
            return {"key": key, "title": title, "tip": tip, "width": width, "align": align}

        return {
            "title": "Какой журнал у какой платы",
            "tip": ("Журнал, в который пишутся точки каждой платы, - по её адресу. Строка жёлтая, если в журнале "
                    "что-то не так: точки трубки разных дней (усреднятся в одном узле), неполный первый этап, "
                    "тот же файл у другой платы, в имени файла адрес другой платы."),
            "columns": [
                column("label", "Плата", "Адрес узла на шине и подпись платы. Привязка журнала - по адресу", 120),
                column("file", "Журнал", "Файл, в который допишутся новые точки этой платы", 300),
                column("stage1", "Этап 1", "Узлов первого этапа (плата с эталонами) из 7", 70, "center"),
                column("air", "Сухая трубка", "Точек «воздух» в журнале (второй этап)", 80, "center"),
                column("liquid", "Жидкость", "Точек «жидкость» в журнале", 74, "center"),
                column("days", "Дни трубки", "Даты точек трубки: больше одной даты - точки разных прогонов", 110),
                column("span", "Размах осн. / вид", "Размах «жидкость − воздух» этой платы, заданный вручную", 120, "center"),
                column("origin", "Откуда взят", "Как журнал попал к плате: кнопкой первого этапа (по адресу или по "
                       "сумме профиля), из списка, заведён прогоном", 320),
                column("status", "Состояние", "В порядке / проверьте / журнала нет", 110, "center"),
                column("warnings", "Что не так", "Почему строка жёлтая", 360),
            ],
            "rows": [{"tone": row["tone"], "cells": {
                "label": row["label"] + (" ●" if row["shown"] else "") + ("" if row["working"] else " (нет на шине)"),
                "file": row["file"], "stage1": row["stage1"], "air": str(row["air"]),
                "liquid": str(row["liquid"]), "days": row["days"] or "—", "span": row["span"],
                "origin": row["origin"], "status": row["state"], "warnings": row["warnings"] or "—"}}
                for row in rows],
        }

    def _mb_context_value(self, sa: int, name: str):
        """Поле платы без переключения на неё: у показанной - текущее, у остальных - из её контекста."""
        if int(sa) == self._mb_active_sa:
            return getattr(self, name, None)
        context = self._mb_contexts.get(int(sa))
        if context is None:
            board = self._mb_board(sa) or {}
            return {"_chamber_span_main": board.get("span_main"),
                    "_chamber_span_media": board.get("span_media")}.get(name)
        return context.get(name)

    def _mb_open_stage1_journals(self) -> tuple[bool, str]:
        """Каждой плате на шине - её журнал первого этапа одной кнопкой (перед вторым этапом).

        Журнал платы - файл с её адресом в имени (…_0x82.csv) или журнал, по которому посчитан
        профиль, записанный сейчас в плату (сумма в <журнал>_profile.json): так находится журнал
        первой платы, снятый, когда она была одна и адреса в имени ещё не было. Ищется в любой папке
        списка, в том числе прошлых версий. Из них берётся тот, где больше узлов первого этапа (при
        равенстве - журнал профиля платы, потом свежий): копия «на 3 точки» не перебьёт полный журнал.

        12.11.2026: если в журнале кроме первого этапа есть другие точки (второй этап прошлого прогона,
        стендовые «воздух» и «жидкость»), плате заводится НОВЫЙ журнал только с точками первого этапа.
        Раньше открывался сам файл: точки нового прогона усреднялись в узле со старыми, а прогон
        дописывал в файл прошлого прогона. Исходный файл не меняется. Плата, у которой уже открыт
        журнал ровно с первым этапом на все узлы, не трогается.
        """
        if not self._mb_on():
            return False, "кнопка - для нескольких плат в камере: у одной платы откройте журнал из списка"
        if getattr(self, "_climate_run_stage", ""):
            return False, "идёт прогон: журналы открываются до него"
        if self._mb_busy():
            return False, "дождитесь конца обмена с прибором"
        journals = self._chamber_journal_index(fresh=True)
        working = self._mb_working_boards() or list(self._mb_boards)
        report, all_ok = [], True
        for board in working:
            sa = int(board["sa"])
            with self._mb_context(sa, notify=False):
                entry = self._mb_assign_stage1(sa, journals)
            all_ok = all_ok and entry["ok"]
            report.append(entry)
        self._chamber_journals_cache = None
        self._mb_stage1_report = report
        self._mb_stage1_at = datetime.now().strftime("%d.%m %H:%M")
        parts = [f"«{self._mb_name(entry['sa'])}»: {entry['text']}" for entry in report]
        self._mb_status = "Журналы первого этапа: " + "; ".join(parts) + "."
        self._mb_changed()
        signal = getattr(self, "chamberLiveChanged", None)
        if signal is not None:
            signal.emit()
        return all_ok, "журналы первого этапа: " + "; ".join(parts)

    def _mb_assign_stage1(self, sa: int, journals: list[dict]) -> dict:
        """Журнал первого этапа одной плате (вызывается в её поле). Итог - строка отчёта кнопки."""
        total = len(chamber_fit.NODES_X10)
        current = pathlib.Path(self._chamber_file_path).name if self._chamber_file_path else ""
        makeup = journal_makeup(self._chamber_points)
        entry = {"sa": sa, "label": self._mb_label(sa), "ok": False, "tone": "bad", "source": "",
                 "journal": current, "nodes": makeup["stage1"], "dropped": 0, "how": "", "text": ""}
        if makeup["stage1"] == total and makeup["air"] + makeup["liquid"] + makeup["other"] == 0:
            entry.update(ok=True, tone="ok", how="уже был открыт", source=current,
                         text=f"уже открыт {current} - {total} из {total} узлов, других точек нет")
            return entry

        crc = ((getattr(self, "_addr_info", {}) or {}).get(sa, {}) or {}).get("profileCrc")
        crc = None if crc is None else int(crc) & 0xFFFF

        def own_profile(item) -> bool:
            return crc not in (None, 0) and item.get("profile_crc") == crc

        candidates = [item for item in journals if item.get("sa") == sa
                      or (item.get("sa") is None and own_profile(item))]
        best = max(candidates, key=lambda item: (int(item.get("nodes", 0)), own_profile(item),
                                                 float(item.get("stamp", 0.0))), default=None)
        # Открытый журнал платы годится в источник, если он не хуже найденного на диске.
        use_current = makeup["stage1"] > 0 and (best is None or int(best.get("nodes", 0)) <= makeup["stage1"])
        if not use_current and (best is None or int(best.get("nodes", 0)) == 0):
            why = ("" if crc is not None else
                   ", а профиль в плате ещё не прочитан (по нему узнаётся журнал без адреса в имени)")
            entry.update(how="не найден", text=(
                f"журнала первого этапа с адресом 0x{sa:02X} на диске нет{why} - первый этап для этой "
                "платы не проходил или журнал лежит в другой папке (откройте его кнопкой «Открыть» в списке)"))
            return entry

        if use_current:
            source_name, source_points = current, list(self._chamber_points)
            how = "из открытого журнала платы"
        else:
            source_name = str(best["name"])
            how = "по сумме профиля в плате" if best.get("sa") is None else "по адресу в имени файла"
            try:
                text = pathlib.Path(best["path"]).read_text(encoding="utf-8-sig")
            except OSError as error:
                entry.update(how="не прочитан", text=f"журнал {source_name} не прочитан: {error}")
                return entry
            source_points = self._chamber_parse_journal(text) or []
        source = journal_makeup(source_points)
        extra = source["air"] + source["liquid"] + source["other"]
        if extra == 0 and not use_current:
            # Чистый журнал первого этапа: открывается как есть (журнал прошлой версии - копией).
            ok, text = self._chamber_open_journal(best["path"])
            if not ok:
                entry.update(how="не открыт", text=text)
                return entry
        else:
            # В журнале есть точки прошлых прогонов или стендовые: новый журнал только с первым этапом.
            self._chamber_points = [dict(point) for point in source_points if is_stage1_point(point)]
            self._chamber_file_path = ""
            self._chamber_after_change()
        self._chamber_journal_origin = {"how": how, "source": source_name, "dropped": extra,
                                        "at": datetime.now().strftime("%d.%m %H:%M")}
        nodes = len(stage1_nodes(self._chamber_points))
        journal = pathlib.Path(self._chamber_file_path).name if self._chamber_file_path else ""
        full = nodes == total
        tail = "" if full else " (журнал неполный)"
        if extra:
            text = (f"новый журнал {journal} - первый этап из {source_name} ({how}), {nodes} из {total} узлов"
                    f"{tail}; не перенесено точек прошлых прогонов и стендовых: {extra}, исходный файл не изменён")
        else:
            why = " - по нему посчитан профиль в плате" if how == "по сумме профиля в плате" else ""
            text = f"открыт {journal}{why} - {nodes} из {total} узлов{tail}"
        entry.update(ok=full, tone="ok" if full else "warn", source=source_name, journal=journal,
                     nodes=nodes, dropped=extra, how=how, text=text)
        return entry

    def _mb_journal_assignments(self) -> list[dict]:
        """Таблица «какой журнал у какой платы»: файл, состав, откуда взят и что в нём не так.

        Считается по полям каждой платы при показе - не по кэшу списка журналов.
        """
        holders = self._mb_open_journal_paths()
        working = {int(board["sa"]) for board in self._mb_working_boards()}
        total = len(chamber_fit.NODES_X10)
        rows = []
        for board in self._mb_boards:
            sa = int(board["sa"])
            path = str(self._mb_context_value(sa, "_chamber_file_path") or "")
            points = list(self._mb_context_value(sa, "_chamber_points") or [])
            makeup = journal_makeup(points)
            origin = dict(self._mb_context_value(sa, "_chamber_journal_origin") or {})
            try:
                key = str(pathlib.Path(path).resolve()) if path else ""
            except OSError:
                key = path
            name = pathlib.Path(path).name if path else ""
            warnings = []
            shared = [other for other in holders.get(key, []) if other != sa] if key else []
            if shared:
                warnings.append("тот же файл открыт у " + ", ".join(self._mb_label(other) for other in shared))
            if points and makeup["stage1"] < total:
                warnings.append(f"первый этап неполный: {makeup['stage1']} из {total} узлов")
            if len(makeup["days"]) > 1:
                warnings.append("точки трубки разных дней (" + ", ".join(makeup["days"])
                                + ") - в одном узле они усреднятся")
            owner = journal_sa(name) if name else None
            if owner is not None and owner != sa:
                warnings.append(f"в имени файла адрес другой платы: 0x{owner:02X}")
            if not points:
                state, tone = "журнала нет", "bad"
            elif not path:
                state, tone = "файл заведётся с первой точкой", "warn"
            elif warnings:
                state, tone = "проверьте", "warn"
            else:
                state, tone = "в порядке", "ok"
            if origin.get("how"):
                how = origin["how"]
                if origin.get("source") and origin["source"] != name:
                    how += f": {origin['source']}"
                if origin.get("dropped"):
                    how += f", не перенесено точек: {origin['dropped']}"
                if origin.get("at"):
                    how += f" ({origin['at']})"
            else:
                how = "заведён прогоном" if path else "—"
            span_main = self._mb_context_value(sa, "_chamber_span_main")
            span_media = self._mb_context_value(sa, "_chamber_span_media")
            rows.append({
                "sa": f"0x{sa:02X}", "label": self._mb_label(sa), "working": sa in working,
                "shown": sa == self._mb_active_sa,
                "file": name or "—", "points": len(points),
                "stage1": f"{makeup['stage1']} из {total}", "stage1Ok": makeup["stage1"] == total,
                "air": makeup["air"], "liquid": makeup["liquid"], "days": ", ".join(makeup["days"]),
                "origin": how, "state": state, "tone": tone, "warnings": "; ".join(warnings),
                "span": ("—" if span_main is None and span_media is None else
                         f"{'—' if span_main is None else span_main} / {'—' if span_media is None else span_media}"),
            })
        return rows

    def _mb_restore_journals(self, boards) -> list[str]:
        """Цель функции в загрузке журнала каждой платы в её же поля, затем точки до перезапуска войдут в её таблицы."""
        events = []
        loader = getattr(self, "_chamber_load_file", None)
        for item in boards or []:
            try:
                sa = int(item.get("sa")) & 0xFF
            except (TypeError, ValueError, AttributeError):
                continue
            journal = str(item.get("journal") or "")
            if self._mb_board(sa) is None or not journal:
                continue
            with self._mb_context(sa, notify=False):
                if journal == str(self._chamber_file_path or ""):
                    continue
                if loader is not None and pathlib.Path(journal).is_file() and loader(journal):
                    events.append(f"{self._mb_label(sa)}: {len(self._chamber_points)} точек")
                else:
                    events.append(f"{self._mb_label(sa)}: журнал {journal} не загрузился")
        return events

    def _mb_summary_text(self) -> str:
        """Итог по платам для сообщения о конце прогона."""
        if not self._mb_on():
            return ""
        parts = []
        for board in self._mb_profile_boards():
            with self._mb_context(board["sa"], notify=False):
                points = len(self._chamber_points)
            result = self._mb_profile_results.get(board["sa"], "")
            parts.append(f"{self._mb_label(board['sa'])}: точек {points}" + (f", {result}" if result else ""))
        return " По платам: " + "; ".join(parts) + "."

    # ------------------------------------------------------------------ показ

    def _mb_view(self) -> dict:
        """Платы в камере для окна, сайта и бота: показания, точки, таблицы, профиль."""
        now = time.monotonic()
        # Показанная плата - до перебора: внутри контекста платы «показана» на время она сама.
        shown = self._mb_active_sa
        rows = []
        working = {int(board["sa"]) for board in self._mb_working_boards(now)}
        for board in self._mb_boards:
            with self._mb_context(board["sa"], notify=False):
                temp = self._chamber_live_stats("board_temp", now)
                main = self._chamber_live_stats("main", now)
                media = self._chamber_live_stats("media", now)
                fresh = self._chamber_live_fresh("board_temp", now)
                profile_state, profile_tone = self._mb_profile_state(board["sa"])
                marks = self._mb_node_marks()
                rows.append({
                    "sa": board["sa"], "saText": f"0x{board['sa']:02X}", "name": board["name"],
                    "active": board["sa"] == shown,
                    "fresh": bool(fresh),
                    # В работе: участник прогона, а вне прогона - на шине. Лента, сайт и бот - только такие.
                    "working": int(board["sa"]) in working,
                    "boardTemp": "—" if temp is None else f"{temp['mean'] / 10.0:+.1f} °C".replace(".", ","),
                    "main": "—" if main is None else str(int(round(main["mean"]))),
                    "media": "—" if media is None else str(int(round(media["mean"]))),
                    # Для различения скачка и усреднения передаём последние измерения отдельно от средних.
                    "mainNow": "—" if self._chamber_live_last.get("main") is None
                               else str(int(self._chamber_live_last["main"])),
                    "mediaNow": "—" if self._chamber_live_last.get("media") is None
                                else str(int(self._chamber_live_last["media"])),
                    "points": len(self._chamber_points),
                    "file": pathlib.Path(self._chamber_file_path).name if self._chamber_file_path else "",
                    "tables": str(self._chamber_tables_text or ""),
                    "tablesComplete": bool(self._chamber_tables_complete),
                    "profile": self._mb_profile_results.get(board["sa"], str(self._chamber_chain_status or "")),
                    "profileState": profile_state, "profileTone": profile_tone,
                    "nodes": marks,
                    "stages": self._mb_assembly_state(marks),
                })
        shown_board = self._mb_board(shown) if shown is not None else None
        return {"enabled": self._mb_on(), "configured": bool(self._mb_enabled), "quietBus": bool(self._mb_quiet_bus),
                "boards": rows, "candidates": [f"0x{sa:02X}" for sa in self._mb_bus_candidates()],
                "workingCount": len(working), "runBoards": self._mb_run_active(),
                "offline": [str(row["name"]) for row in rows if not row["working"]],
                "status": self._mb_status,
                # 12.11.2026: какой журнал у какой платы - таблицей, а не строкой статуса.
                "journals": self._mb_journals_table() if self._mb_on() else {},
                "stage1Report": list(self._mb_stage1_report), "stage1At": self._mb_stage1_at,
                "shownName": "" if shown_board is None else str(shown_board["name"]),
                "switchNote": self._mb_switch_note if now - self._mb_switch_note_s < 8.0 else "",
                "shownSa": "" if shown is None else f"0x{int(shown):02X}"}

    def _mb_profile_state(self, sa: int | None = None) -> tuple[str, str]:
        """Цель функции в кратком состоянии профиля платы для плитки: пишется, записан, ошибка, что в самой плате.

        Сначала - запись в этом сеансе программы; если её не было, то, что прочитано из самой платы
        (профиль мог быть записан раньше): применяется с суммой, не применяется или пустой.
        """
        if getattr(self, "_chamber_chain_stage", ""):
            return "пишется", "run"
        written = getattr(self, "_chamber_written_crc", None)
        if written is not None:
            return f"записан 0x{int(written):04X}", "ok"
        if str(getattr(self, "_chamber_chain_color", "")) == "#dc2626":
            return "ошибка записи", "bad"
        info = (getattr(self, "_addr_info", {}) or {}).get(int(sa), {}) if sa is not None else {}
        status = info.get("profileStatus")
        if status is not None:
            crc = info.get("profileCrc")
            if int(status) & 0x08:
                return (f"в плате 0x{int(crc):04X}" if crc is not None else "в плате, применяется"), "ok"
            if int(status) & 0x01:
                return "в плате не применяется", "bad"
            return "в плате пустой", "normal"
        return "не записан", "normal"

    def _mb_node_marks(self) -> list[dict]:
        """Цель функции в узлах температуры для плитки: что снято у платы в каждом узле - по двум этапам.

        board - первый этап (плата с эталонами, узел по датчику платы); air - второй этап, изделие в сборе:
        сухая трубка «воздух», узел по датчику трубки (±3 °C), как в расчёте строк трубки; liquid - «жидкость».
        08.11.2026: раньше плитка красила узел по любой точке, и после второго этапа нельзя было понять,
        где трубка снята, а где точка ушла мимо узла.
        """
        buckets = self._chamber_node_buckets(skip_rehearsal=True) if hasattr(self, "_chamber_node_buckets") else {}
        marks = []
        for node in chamber_fit.NODES_X10:
            bucket = buckets.get(node) or {"main": set(), "media": set(), "air": 0, "liquid": 0}
            board = bool(bucket["main"] or bucket["media"])
            air, liquid = int(bucket["air"]), int(bucket["liquid"])
            text = chamber_fit.node_text(node)
            marks.append({
                "node": text, "short": str(int(node) // 10),
                "count": int(board) + air + liquid,
                "board": board, "air": air, "liquid": liquid,
                "tip": (f"{text}: плата - {'снята' if board else 'нет точки'}; в сборе - сухая трубка "
                        f"{'есть' if air else 'нет'}" + (f", в жидкости {liquid}" if liquid else "")),
            })
        return marks

    def _mb_assembly_state(self, marks: list[dict]) -> dict:
        """Цель функции в сводке второго этапа для плитки: сколько узлов с сухой трубкой и снята ли «жидкость»."""
        return {"air": sum(1 for mark in marks if mark["air"]), "liquid": any(mark["liquid"] for mark in marks),
                "board": sum(1 for mark in marks if mark["board"]), "total": len(marks)}

    def _mb_keeps_live(self) -> bool:
        """Цель функции в признаке «лента плат видна», затем опрос всех плат идёт в любом разделе калибровки."""
        return bool(self._mb_strip_visible) and self._mb_on()

    def _mb_set_strip_visible(self, visible: bool):
        """Цель функции в признаке видимой ленты плат, затем опрос включается или выключается сразу."""
        self._mb_strip_visible = bool(visible)
        # Профиль в самой плате ещё не читали - прочитать (для плитки), по одному параметру, не мешая опросу.
        queue = getattr(self, "_addr_queue_info", None)
        info = getattr(self, "_addr_info", {}) or {}
        if visible and self._mb_on() and queue is not None:
            for board in self._mb_boards:
                if info.get(int(board["sa"]), {}).get("profileStatus") is None:
                    queue(int(board["sa"]))
        apply_live = getattr(self, "_chamber_live_apply_wanted", None)
        if apply_live is not None:
            apply_live()

    def _mb_journal_suffix(self) -> str:
        """Хвост имени файла журнала: у каждой платы свой файл."""
        if not self._mb_on() or self._mb_active_sa is None:
            return ""
        name = "".join(ch if ch.isalnum() else "_" for ch in self._mb_name(self._mb_active_sa)).strip("_")
        return f"_{name or 'plata'}_0x{self._mb_active_sa:02X}"
