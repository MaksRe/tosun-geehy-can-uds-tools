"""Автономный прогон в климатической камере: проверка, сторож, сводки, продолжение, итог.

ЗАЧЕМ
Полный температурный профиль снимается сутки и больше. Человек рядом с камерой
всё это время не сидит, поэтому программа должна сама:
- до старта проверить, что всё готово, и не дать начать прогон, который
  заведомо не получится (нет связи, авария, тестовый режим, пределы камеры);
- во время прогона следить за камерой и прибором и сразу сообщать о бедах:
  авария, пропала связь, камеру остановили или сменили уставку на пульте,
  камера не греет и не охлаждает, температура ушла, плата не догоняет воздух,
  этап завис;
- раз в час (настраивается) присылать сводку: где прогон, что с камерой и
  платой, сколько прошло и сколько осталось;
- пережить перезапуск программы: состояние прогона лежит в файле, после
  запуска прогон продолжается с того же узла, как только есть связь;
- в конце дождаться записи профиля в прибор и прислать итог: время по узлам,
  таблицы, профиль, все проблемы; при проблемах - отчёт диагностики файлом.

КАК УСТРОЕНО
Сам порядок прогона (уставка, выход, плата устоялась, точки) живёт в модуле
камеры. Этот модуль подключается к нему в нескольких местах: старт, смена
этапа, узел пройден, финиш, остановка и общий такт. Каждая беда - это
«проблема» с ключом: о её появлении и о том, что она прошла, сообщается по
одному разу, без потока одинаковых сообщений.

Все события идут в события камеры: в окно, на страницу наблюдения, в Telegram
и в журнал диагностики logs/chamber.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import time
from collections import deque

import chamber_fit
from ui.qml import climate_scenario
from ui.qml.climate_chamber import DRIVER_ESPEC, DRIVER_SIMULATOR

from .contract import AppControllerContract
from .stability import rate_and_spread

# Этапы, на которых камера уже должна держать уставку узла.
ACTIVE_STAGES = ("reach", "settle", "hold", "points", "operator", "window", "capture", "capturing")
# Этапы после выхода на уставку: температура камеры не должна уходить.
HOLD_STAGES = ("settle", "hold", "points", "operator", "window", "capture", "capturing")

# Испытание одной платы на своих ёмкостях за один цикл: все узлы сетки прибора,
# первым - опорный +25 °C, затем -20 и -40 (к -40 - уже с холодной точкой), потом вверх до +85.
BOARD_CYCLE_NODES = "25, -20, -40, 0, 50, 70, 85"


def duration_text(seconds: float | None) -> str:
    """Длительность для человека: «2:05» (часы:минуты) или «—»."""
    if seconds is None:
        return "—"
    minutes = int(max(0.0, float(seconds)) // 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def _c(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):+.1f} °C".replace(".", ",")


class AppControllerClimateSupervisorMixin(AppControllerContract):
    # Сколько без связи с камерой, прежде чем это проблема прогона, с.
    AUTO_LINK_LOST_S = 120.0
    # Сколько прибор может молчать о температуре платы, с.
    AUTO_BOARD_LOST_S = 60.0
    # Камера остановилась: через сколько пустить её снова и через сколько поставить прогон на паузу, с.
    AUTO_STOPPED_RETRY_S = 30.0
    AUTO_STOPPED_PAUSE_S = 180.0
    # Уставка на пульте отличается от узла больше чем на столько, °C.
    AUTO_SETPOINT_TOLERANCE_C = 0.3
    AUTO_SETPOINT_RESEND_S = 60.0
    AUTO_SETPOINT_ALERT_S = 180.0
    # Камера не идёт к уставке: за окно расстояние до уставки сократилось меньше чем на столько.
    AUTO_PROGRESS_WINDOW_S = 1200.0
    AUTO_PROGRESS_MIN_C = 1.0
    # Температура ушла с уставки дольше чем на столько, с.
    AUTO_DRIFT_HOLD_S = 300.0
    # Плата не догоняет воздух дольше чем столько после выхода на уставку, с.
    AUTO_GAP_HOLD_S = 600.0
    # «Плата не догоняет воздух» - только если она почти не движется к нему: инертная плата догоняет медленно.
    AUTO_GAP_MIN_RATE_C_MIN = 0.05
    # Плата не дальше стольких градусов от места по модели «воздух -> плата» - отставание обычное.
    AUTO_GAP_MODEL_C = 3.0
    AUTO_GAP_RATE_WINDOW_S = 300.0
    # Как часто напоминать о паузе и ожидании оператора, с.
    AUTO_REMIND_S = 1800.0
    # Как часто сохранять состояние прогона, с.
    AUTO_SAVE_EVERY_S = 60.0
    # Свободное место для журналов, МБ.
    AUTO_DISK_MIN_MB = 200
    # Сколько после последнего узла ждать записи профиля в прибор, с.
    AUTO_FINISH_WAIT_S = 600.0
    # Сколько связь с камерой и прибором должна держаться, прежде чем продолжить прерванный прогон, с.
    AUTO_RESUME_STEADY_S = 30.0

    # ------------------------------------------------------------------ состояние

    def _climate_auto_init(self):
        """Готовит сторожа и подхватывает прогон, прерванный перезапуском программы."""
        self._climate_auto_reset()
        self._climate_auto_resume = None
        self._climate_auto_resume_since = None
        saved = self._climate_auto_load()
        if saved:
            self._climate_auto_resume = saved
            node_count = len(saved.get("nodes") or [])
            index = int(saved.get("index", 0))
            tail = ("Продолжу сам, как только будут связь с камерой и прибором."
                    if self._climate_settings.get("auto_resume", True)
                    else "Нажмите «Продолжить прогон», когда всё будет готово.")
            self._climate_event(f"программа запущена заново во время прогона: он был прерван на узле "
                                f"{min(index + 1, node_count)} из {node_count}. {tail}", "warn")

    def _climate_auto_reset(self):
        """Всё, что относится к одному прогону, в исходном виде."""
        self._climate_auto_alerts: dict = {}
        self._climate_auto_watch: dict = {}
        self._climate_auto_progress: deque = deque(maxlen=2000)
        self._climate_auto_durations: list = []
        # Шаги, оставленные вручную без точки (кнопка «следующий шаг», переход к шагу): узел и время на нём.
        self._climate_auto_skipped: list = []
        self._climate_auto_elapsed_before = 0.0
        self._climate_auto_session_start = None
        self._climate_auto_node_start = None
        self._climate_auto_last_report = None
        self._climate_auto_last_save = 0.0
        self._climate_auto_finishing = False
        self._climate_auto_finish_since = 0.0
        self._climate_auto_problems: list = []
        self._climate_auto_paused_by = ""
        self._climate_auto_last_remind = None

    # ------------------------------------------------------------------ сохранение прогона

    def _climate_auto_state_path(self) -> pathlib.Path:
        return self._climate_settings_path().with_name("climate_run_state.json")

    def _climate_auto_load(self) -> dict | None:
        """Прерванный прогон из файла. Испорченный файл означает «прерванного прогона нет»."""
        try:
            payload = json.loads(self._climate_auto_state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or not payload.get("active") or not payload.get("nodes"):
            return None
        try:
            payload["nodes"] = [float(node) for node in payload["nodes"]]
            payload["index"] = int(payload.get("index", 0))
        except (TypeError, ValueError):
            return None
        if payload["index"] >= len(payload["nodes"]):
            return None
        return payload

    def _climate_auto_save(self, now: float | None = None):
        """Состояние прогона на диск: после перезапуска программа продолжит с этого узла."""
        if not self._climate_run_stage:
            return
        now = time.monotonic() if now is None else now
        payload = {
            "active": True,
            "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "nodes": list(self._climate_run_nodes),
            "steps": [dict(step) for step in getattr(self, "_climate_run_steps", []) or []],
            "scenario": str((getattr(self, "_climate_scenario", None) or {}).get("name", "")),
            "index": int(self._climate_run_index),
            # Доводка платы на текущем шаге: сдвиг уставки и сколько попыток уже было.
            "offset": float(getattr(self, "_climate_run_offset", 0.0)),
            "board_attempts": int(getattr(self, "_climate_run_board_attempts", 0)),
            "board_pairs": list(getattr(self, "_climate_run_board_pairs", []) or []),
            # Сколько точек журнала было до прогона: новые точки прогона - после них (для перехода на полный цикл).
            "journal_base": int(getattr(self, "_climate_run_journal_base", 0) or 0),
            "labels": list(self._climate_run_labels),
            "done": list(self._climate_run_done),
            "stage": self._climate_run_stage,
            "paused": bool(self._climate_run_paused),
            "paused_by": self._climate_auto_paused_by,
            "elapsed_s": round(self._climate_auto_elapsed(now), 1),
            "durations": [[node, round(seconds, 1)] for node, seconds in self._climate_auto_durations],
            "skipped": [[node, round(seconds, 1)] for node, seconds in self._climate_auto_skipped],
            "problems": list(self._climate_auto_problems[-50:]),
            "chamber": {
                "board_only": bool(getattr(self, "_chamber_board_only", False)),
                "single_model": str(getattr(self, "_chamber_single_model", "")),
                "label": str(getattr(self, "_chamber_label", "")),
                "journal": str(getattr(self, "_chamber_file_path", "") or ""),
                "auto_write": bool(getattr(self, "_chamber_auto_write", False)),
            },
        }
        path = self._climate_auto_state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except OSError as error:
            self._climate_diag_event("RUN", f"состояние прогона не сохранилось: {error}", "WARN")
        self._climate_auto_last_save = now

    def _climate_auto_clear_file(self):
        try:
            self._climate_auto_state_path().unlink()
        except OSError:
            pass

    # ------------------------------------------------------------------ проверка перед стартом

    def _climate_auto_checks(self) -> list[dict]:
        """Готовность к автономному прогону: что мешает (block) и что стоит знать (warn)."""
        checks = []

        def add(key: str, ok: bool, text: str, level: str = "block"):
            checks.append({"key": key, "ok": bool(ok), "level": level, "text": text})

        settings = self._climate_settings
        reading = self._climate_reading if self._climate_fresh() else None
        link = self._climate_link
        chamber_ok = link is not None and reading is not None
        add("chamber", chamber_ok, "Камера на связи" if chamber_ok else "Нет связи с камерой: подключитесь")
        if reading is not None:
            alarm = getattr(reading, "alarm", None)
            add("alarm", not alarm, "Аварий камеры нет" if not alarm else f"Авария камеры, код {alarm}")
        if link is not None:
            add("can_set", bool(link.driver.can_set),
                "Камера принимает уставку" if link.driver.can_set else "Камера не даёт задавать уставку")

        try:
            plan = self._climate_run_plan()
        except ValueError:
            plan = {"steps": [], "nodes": [], "labels": []}
        nodes = plan["nodes"]
        # Узлы, в которых снимается точка: только они идут в таблицу.
        capture_nodes = [float(step["temp"]) for step in plan["steps"] if step.get("capture", True)]
        low, high = float(settings["min_c"]), float(settings["max_c"])
        nodes_ok = bool(nodes) and all(low <= node <= high for node in nodes)
        add("nodes", nodes_ok,
            f"Температуры: {', '.join(_c(node) for node in nodes)}" if nodes_ok
            else f"Список температур пуст или выходит за пределы {low:+.0f}...{high:+.0f} °C")

        if nodes_ok:
            # Узел, в который попадёт точка; None - температура дальше ±3 °C от любого узла.
            mapped = {node: chamber_fit.nearest_node(int(round(node * 10))) for node in capture_nodes}
            covered = {grid for grid in mapped.values() if grid is not None}
            off_grid = [node for node, grid in mapped.items() if grid is None]
            # Точки уже открытого журнала (добор к прошлому прогону): их узлы тоже идут в таблицу.
            journal = [point for point in getattr(self, "_chamber_points", []) or [] if not point.get("rehearsal")]
            in_journal = {node for node in (chamber_fit.nearest_node(point["board_temp_x10"]) for point in journal)
                          if node is not None}
            missing = [node for node in chamber_fit.NODES_X10 if node not in covered | in_journal]
            reference = chamber_fit.REFERENCE_X10 in covered | in_journal
            add("reference", reference, "Опорный узел +25 °C в списке" if reference
                else "Нет узла +25 °C: это опорная точка, без неё таблица платы не посчитается")
            refill = str((getattr(self, "_climate_scenario", None) or {}).get("name", "")) == climate_scenario.REFILL_NAME
            if refill and not journal:
                add("refill", False, "Сценарий добора: сначала откройте журнал прошлого прогона (Прогон в камере -> "
                                      "Журналы) - новые точки допишутся к нему")
            journal_text = f" вместе с открытым журналом ({len(journal)} точек)" if journal else ""
            if off_grid:
                add("grid", False, f"Температуры {', '.join(_c(node) for node in off_grid)} не попадают в узлы "
                                   f"прибора (±3 °C): точки там не войдут в таблицу", "warn")
            elif missing:
                add("grid", False, f"Не все узлы прибора{journal_text}: нет "
                                   f"{', '.join(chamber_fit.node_text(node) for node in missing)}. "
                                   f"Таблица будет неполной, профиль сам не запишется", "warn")
            else:
                add("grid", True, f"Все 7 узлов прибора{journal_text}: таблица будет полной", "warn")
            repeat = sorted(covered & in_journal)
            if repeat:
                add("repeat", True, f"Узлы {', '.join(chamber_fit.node_text(node) for node in repeat)} уже есть в "
                                    "журнале: новые точки сверятся со старыми (повторяемость) и усреднятся", "warn")

        details = (getattr(reading, "details", None) or {}) if reading is not None else {}
        if settings["driver"] == DRIVER_ESPEC and nodes and details.get("high_c") is not None:
            alarm_low, alarm_high = float(details["low_c"]), float(details["high_c"])
            inside = alarm_low < min(nodes) and max(nodes) < alarm_high
            add("espec_limits", inside,
                f"Пределы аварии камеры {_c(alarm_low)} ... {_c(alarm_high)} охватывают все узлы" if inside
                else f"Пределы аварии камеры {_c(alarm_low)} ... {_c(alarm_high)} не охватывают узлы: камера "
                     f"откажет в уставке. Поправьте их в «Ручном управлении ESPEC»")

        board_fresh = self._chamber_live_fresh("board_temp", time.monotonic())
        add("device", board_fresh,
            "Прибор на связи, температура платы приходит" if board_fresh
            else "Прибор не присылает температуру платы: подключите адаптер CAN и откройте прибор")

        test_on = bool(getattr(self, "_chamber_test_mode", False))
        if settings["driver"] == DRIVER_SIMULATOR:
            add("test", test_on, "Имитатор: тестовый режим включён" if test_on
                else "С имитатором нужен тестовый режим в «Прогоне в камере»", "warn")
        else:
            add("test", not test_on, "Тестовый режим выключен" if not test_on
                else "Включён тестовый режим: точки будут пробными. Выключите его в «Прогоне в камере»")

        hint = self._climate_mode_hint()
        add("mode", not hint, "Режим расчёта подходит камере" if not hint else hint)

        labels = [label for label in plan["labels"] if label]
        if not labels:
            add("labels", False, "Не задано, что подключено к прибору: впишите пометку, например 0/0")
        elif len(labels) > 1:
            add("labels", True, f"Пометок {len(labels)} ({'; '.join(labels)}): в каждом узле понадобится "
                                f"оператор, чтобы переключить эталоны", "warn")
        else:
            add("labels", True, f"Пометка «{labels[0]}»: оператор не нужен")
        if getattr(self, "_chamber_board_only", False) and labels and labels != ["0/0"]:
            add("board_label", False, "В режиме «только плата» пометка должна быть «0/0»", "warn")

        auto_write = bool(getattr(self, "_chamber_auto_write", False))
        add("auto_write", auto_write, "Профиль запишется в прибор сам, когда данных хватит во всех узлах"
            if auto_write else "Автозапись профиля выключена: в конце профиль придётся записать вручную", "warn")

        remote = getattr(self, "_remote_settings", {}) or {}
        users = getattr(self, "_remote_users", None)
        telegram = bool(remote.get("telegram_enabled")) and bool(remote.get("telegram_token")) \
            and users is not None and bool(users.all())
        add("telegram", telegram, "Telegram включён: события будут приходить подписчикам бота" if telegram
            else "Telegram не настроен или никто не подписан (/start в боте): о бедах узнаете только у камеры",
            "warn")

        try:
            directory = self._climate_logs_directory()
            directory.mkdir(parents=True, exist_ok=True)
            free_mb = shutil.disk_usage(directory).free // (1024 * 1024)
            add("disk", free_mb >= self.AUTO_DISK_MIN_MB, f"Место для журналов: {free_mb} МБ",
                "warn")
        except OSError:
            pass

        points = len(getattr(self, "_chamber_points", []) or [])
        if points:
            name = pathlib.Path(str(getattr(self, "_chamber_file_path", "") or "")).name
            add("journal", True, f"В журнале{f' {name}' if name else ''} уже {points} точек: новые допишутся к ним. "
                                 "Для нового профиля начните новый журнал («Прогон в камере» -> «Журналы»)", "warn")
        return checks

    def _climate_auto_blockers(self) -> list[str]:
        """Что не даёт начать прогон."""
        return [item["text"] for item in self._climate_auto_checks() if item["level"] == "block" and not item["ok"]]

    # ------------------------------------------------------------------ точки входа из прогона

    def _climate_auto_on_start(self, now: float):
        """Прогон начат: время, план и первое сохранение."""
        self._climate_auto_reset()
        self._climate_auto_session_start = now
        self._climate_auto_node_start = now
        self._climate_auto_last_report = now
        self._climate_auto_clear_resume()
        self._climate_auto_save(now)
        plan = ", ".join(_c(node) for node in self._climate_run_nodes)
        self._climate_diag_event("RUN", f"план прогона: {plan}; пометки {self._climate_run_labels}")

    def _climate_auto_on_stage(self, stage: str, now: float):
        """Этап сменился: зависание считается заново; новый узел - слежение за узлом с нуля."""
        self._climate_auto_alert("hang", False, "")
        if stage == "setpoint":
            # Новый узел: всё, что относилось к прошлой уставке, больше не действует.
            self._climate_auto_progress.clear()
            for key in ("stopped_since", "stopped_retry", "setpoint_since", "setpoint_resent", "drift_since",
                        "gap_since"):
                self._climate_auto_watch.pop(key, None)
            for key in ("progress", "drift", "gap", "setpoint", "stopped", "stopped_hard"):
                self._climate_auto_alert(key, False, "")
        self._climate_diag_event("RUN", f"этап {stage}, узел {self._climate_run_index + 1}")
        if self._climate_run_stage and self._climate_run_stage != "finish":
            self._climate_auto_save(now)

    def _climate_auto_on_node_done(self, node: float, now: float):
        """Узел пройден: его время идёт в итог и в оценку оставшегося."""
        started = self._climate_auto_node_start if self._climate_auto_node_start is not None else now
        seconds = (now - started) * self._climate_speed()
        self._climate_auto_durations.append((float(node), seconds))
        self._climate_auto_node_start = now
        left = self._climate_auto_eta(now)
        tail = f" Осталось примерно {duration_text(left)}." if left is not None else ""
        self._climate_event(f"узел {_c(node)} пройден за {duration_text(seconds)} "
                            f"({len(self._climate_auto_durations)} из {len(self._climate_run_nodes)}).{tail}", "ok")

    def _climate_auto_on_node_left(self, node: float, now: float, who: str = ""):
        """Шаг оставлен вручную без точки: его время - отдельной строкой, отсчёт следующего шага - с нуля.

        Иначе часы, проведённые на пропущенном шаге, приписывались следующему: на стенде
        13.10 шаг -20 «шёл» 7:51, хотя 6:47 из них прогон стоял на -40, и оценка
        оставшегося времени выросла с 2:38 до 21 часа.
        """
        started = self._climate_auto_node_start if self._climate_auto_node_start is not None else now
        seconds = (now - started) * self._climate_speed()
        self._climate_auto_skipped.append((float(node), seconds))
        self._climate_auto_node_start = now
        self._climate_auto_problems.append(
            f"{time.strftime('%d.%m %H:%M')} шаг {_c(node)} оставлен без точки через {duration_text(seconds)}"
            + (f" ({who})" if who else ""))

    def _climate_auto_on_finish(self, now: float | None = None):
        """Узлы пройдены: дальше ждём запись профиля и присылаем итог."""
        now = time.monotonic() if now is None else now
        self._climate_auto_finishing = True
        self._climate_auto_finish_since = now
        self._climate_auto_finish_elapsed = self._climate_auto_elapsed(now)
        self._climate_auto_clear_file()

    def _climate_auto_on_stop(self, reason: str):
        """Прогон остановлен: файл состояния больше не нужен, итог - что успели."""
        self._climate_auto_clear_file()
        done = len(self._climate_auto_durations)
        if done:
            self._climate_event(f"до остановки пройдено узлов: {done} из {len(self._climate_run_nodes)} - "
                                f"{self._climate_auto_nodes_text()}.", "info")
        self._climate_auto_alerts.clear()

    # ------------------------------------------------------------------ такт

    def _climate_auto_tick(self, now: float):
        """Раз в такт окна: продолжение прерванного прогона, итог, сторож, сводка, сохранение."""
        if self._climate_auto_resume is not None and not self._climate_run_stage:
            self._climate_auto_try_resume(now)
        if self._climate_auto_finishing:
            self._climate_auto_follow_finish(now)
        if not self._climate_run_stage:
            return
        # Возврат камеры после последнего шага: шагов больше нет - сторожить и сохранять нечего.
        if self._climate_run_stage == "finish":
            return
        self._climate_auto_watchdog(now)
        self._climate_auto_maybe_report(now)
        if now - self._climate_auto_last_save >= self.AUTO_SAVE_EVERY_S:
            self._climate_auto_save(now)

    # ------------------------------------------------------------------ сторож

    def _climate_auto_alert(self, key: str, active: bool, text: str, level: str = "warn",
                            cleared: str = "") -> bool:
        """Поднимает или снимает проблему. Сообщение - один раз при появлении и один раз, когда прошла."""
        alerts = self._climate_auto_alerts
        if active:
            if key in alerts:
                alerts[key]["text"] = text
                return False
            alerts[key] = {"text": text, "level": level, "time": time.strftime("%H:%M")}
            self._climate_auto_problems.append(f"{time.strftime('%d.%m %H:%M')} {text}")
            self._climate_event(text, "bad" if level == "bad" else "warn")
            return True
        if key in alerts:
            alerts.pop(key)
            if cleared:
                self._climate_event(cleared, "ok")
        return False

    def _climate_auto_since(self, key: str, condition: bool, now: float) -> float:
        """Сколько секунд подряд держится условие (0 - не держится)."""
        watch = self._climate_auto_watch
        if not condition:
            watch.pop(key, None)
            return 0.0
        watch.setdefault(key, now)
        return now - watch[key]

    def _climate_auto_pause(self, by: str, text: str):
        """Ставит прогон на паузу из-за беды: продолжать после проверки должен человек."""
        if not self._climate_run_paused:
            self._climate_run_paused = True
            self._climate_auto_paused_by = by
            self._climate_auto_last_remind = None
            self._climate_run_set(f"Прогон на паузе: {text}", "#dc2626")
            self._climate_auto_save()

    def _climate_auto_watchdog(self, now: float):
        """Сторож прогона: связь, авария, камера стоит, уставка, нет хода, уход, плата, зависание."""
        speed = self._climate_speed()
        stage = self._climate_run_stage
        index = self._climate_run_index
        node = self._climate_run_nodes[index] if 0 <= index < len(self._climate_run_nodes) else None
        fresh = self._climate_fresh(now)
        reading = self._climate_reading if fresh else None
        settings = self._climate_settings

        # Связь с камерой.
        lost = self._climate_auto_since("link_lost", self._climate_link is None or not fresh, now)
        self._climate_auto_alert(
            "link", lost >= self.AUTO_LINK_LOST_S,
            f"нет связи с камерой {int(lost // 60)} мин: прогон ждёт. Проверьте кабель, Moxa и камеру.", "bad",
            "связь с камерой восстановлена, прогон идёт дальше.")

        # Авария камеры: прогон на паузу, продолжать после осмотра.
        alarm = getattr(reading, "alarm", None) if reading is not None else None
        if alarm:
            codes = ", ".join((getattr(reading, "details", None) or {}).get("alarms") or []) or str(alarm)
            if self._climate_auto_alert("alarm", True, f"АВАРИЯ КАМЕРЫ (код {codes}): прогон поставлен на паузу. "
                                                       f"Осмотрите камеру и нажмите «Продолжить прогон».", "bad"):
                self._climate_auto_pause("alarm", f"авария камеры, код {codes}.")
        elif reading is not None and "alarm" in self._climate_auto_alerts:
            self._climate_auto_alert("alarm", False, "", cleared="авария камеры снята. Прогон на паузе: проверьте "
                                                                 "камеру и нажмите «Продолжить прогон».")

        # Прибор: без температуры платы прогон не выйдет из ожидания.
        board_fresh = self._chamber_live_fresh("board_temp", time.monotonic())
        silent = self._climate_auto_since("board_lost", stage in ACTIVE_STAGES and not board_fresh, now)
        self._climate_auto_alert(
            "board", silent >= self.AUTO_BOARD_LOST_S,
            f"прибор не присылает температуру платы {int(silent)} с: плата не устоится и точки не снимутся. "
            f"Проверьте адаптер CAN и прибор.", "bad", "прибор снова присылает температуру платы.")

        # Остальное - только когда прогон идёт сам и камера на связи.
        if self._climate_run_paused or reading is None or node is None or stage not in ACTIVE_STAGES:
            self._climate_auto_remind_paused(now)
            return

        # Камеру остановили (с пульта или сама): пустить снова, не вышло - пауза.
        stopped = self._climate_auto_since("stopped_since", getattr(reading, "running", None) is False, now)
        link = self._climate_link
        if stopped >= self.AUTO_STOPPED_RETRY_S and not self._climate_auto_watch.get("stopped_retry") \
                and link is not None and link.driver.can_run:
            self._climate_auto_watch["stopped_retry"] = True
            self._climate_auto_alert("stopped", True, f"камера остановилась во время прогона (узел {_c(node)}): "
                                                      f"пускаю её снова.", "warn",)
            self._climate_send_run(True)
        if stopped >= self.AUTO_STOPPED_PAUSE_S:
            if self._climate_auto_alert("stopped_hard", True, "камера не пускается: прогон поставлен на паузу. "
                                                              "Проверьте пульт камеры.", "bad"):
                self._climate_auto_pause("stopped", "камера не пускается.")
        if stopped == 0.0:
            self._climate_auto_alert("stopped", False, "", cleared="камера снова работает.")
            self._climate_auto_alert("stopped_hard", False, "")

        # Уставку сменили на пульте: вернуть узел, не вышло - проблема. Сдвиг доводкой платы - не ошибка.
        target = self._climate_run_setpoint() if hasattr(self, "_climate_run_setpoint") else node
        setpoint = getattr(reading, "setpoint_c", None)
        wrong = setpoint is not None and abs(float(setpoint) - target) > self.AUTO_SETPOINT_TOLERANCE_C
        wrong_s = self._climate_auto_since("setpoint_since", wrong, now)
        if wrong_s >= self.AUTO_SETPOINT_RESEND_S and not self._climate_auto_watch.get("setpoint_resent"):
            self._climate_auto_watch["setpoint_resent"] = True
            self._climate_event(f"уставка камеры {_c(setpoint)} не совпадает с узлом {_c(target)}: задаю узел снова.",
                                "warn")
            self._climate_send_setpoint(target)
        self._climate_auto_alert(
            "setpoint", wrong_s >= self.AUTO_SETPOINT_ALERT_S,
            f"уставка камеры {_c(setpoint)} так и не стала {_c(node)}: её меняют с пульта или камера отказывает.",
            "bad", "уставка камеры снова совпадает с узлом.")

        actual = getattr(reading, "actual_c", None)
        tolerance = self._climate_run_param("reach_tolerance_c")
        if actual is not None:
            distance = abs(float(actual) - target)
            # Камера не идёт к уставке: за 20 минут расстояние почти не сократилось.
            if stage == "reach":
                step = 10.0 / speed
                if not self._climate_auto_progress or now - self._climate_auto_progress[-1][0] >= step:
                    self._climate_auto_progress.append((now, distance))
                window = self.AUTO_PROGRESS_WINDOW_S / speed
                old = [item for item in self._climate_auto_progress if now - item[0] >= window]
                if old and distance > tolerance:
                    gained = old[-1][1] - distance
                    self._climate_auto_alert(
                        "progress", gained < self.AUTO_PROGRESS_MIN_C,
                        f"камера не идёт к уставке {_c(node)}: за {int(self.AUTO_PROGRESS_WINDOW_S // 60)} мин "
                        f"приблизилась на {gained:.1f} °C, сейчас {_c(actual)}. {self._climate_auto_hardware_text()}",
                        "warn", "камера снова идёт к уставке.")
            # Температура ушла с уставки после выхода на неё.
            drift_limit = max(2.0 * tolerance, 2.0)
            drifting = self._climate_auto_since("drift_since", stage in HOLD_STAGES and distance > drift_limit, now)
            self._climate_auto_alert(
                "drift", drifting >= self.AUTO_DRIFT_HOLD_S / speed,
                f"температура камеры ушла с уставки: {_c(actual)} при узле {_c(node)}. "
                f"{self._climate_auto_hardware_text()}", "warn", "температура камеры вернулась к уставке.")

            # Плата далеко от воздуха камеры: датчик или установка платы.
            board = self._chamber_live_last.get("board_temp") if board_fresh else None
            gap_limit = float(settings.get("board_gap_c", 10.0))
            gap = None if board is None else abs(int(board) / 10.0 - float(actual))
            # Скорость, с которой плата идёт к воздуху (°C/мин): идёт - значит, просто инертная, а не застряла.
            trend = rate_and_spread(self._climate_board, now, self.AUTO_GAP_RATE_WINDOW_S / speed)
            approach = None
            if trend is not None and board is not None:
                toward = 1.0 if float(actual) > int(board) / 10.0 else -1.0
                approach = toward * trend[0] / speed
            stuck = approach is None or approach < self.AUTO_GAP_MIN_RATE_C_MIN
            # Плата в коробке на холоде отстаёт от воздуха на 15-17 °C - это её обычное место по модели
            # «воздух -> плата» этого прогона, а не беда (стенд 19.10, шаг -40). Беда - если она далеко от модели.
            # Модели верим, только если в ней есть другие шаги: построенная по одному этому шагу, она
            # «объяснила» бы любую беду самой собой (плата застряла - модель так и запомнит).
            model_fn = getattr(self, "_climate_run_board_model", None)
            other_steps = any(pair.get("step") != self._climate_run_index
                              for pair in getattr(self, "_climate_run_board_pairs", []) or [])
            model = model_fn() if model_fn is not None and board is not None and other_steps else None
            if model is not None and abs(model[0] * float(actual) + model[1] - int(board) / 10.0) <= self.AUTO_GAP_MODEL_C:
                stuck = False
            far = self._climate_auto_since(
                "gap_since", stage == "settle" and gap is not None and gap > gap_limit and stuck, now)
            approach_text = "" if approach is None else f", а к воздуху она идёт лишь {approach:+.3f} °C/мин".replace(".", ",")
            self._climate_auto_alert(
                "gap", far >= self.AUTO_GAP_HOLD_S / speed,
                f"плата не догоняет воздух камеры: разница {gap if gap is None else round(gap, 1)} °C дольше "
                f"{int(self.AUTO_GAP_HOLD_S // 60)} мин{approach_text}. Проверьте, что плата в камере и датчик исправен.",
                "warn", "плата догнала воздух камеры или снова идёт к нему.")

        # Этап завис вдвое дольше предупреждения.
        limit_key = {"reach": "reach_timeout_min", "settle": "settle_timeout_min"}.get(stage)
        if limit_key:
            limit_s = 2.0 * self._climate_run_param(limit_key) * 60.0 / speed
            hang = now - self._climate_run_since >= limit_s
            what = "камера не выходит на уставку" if stage == "reach" else "плата не устаивается"
            self._climate_auto_alert(
                "hang", hang, f"{what} уже {duration_text(limit_s * speed)} (узел {_c(node)}). Прогон ждёт; "
                              f"если так и задумано, увеличьте время в настройках прогона.", "bad")

        # Оператор нужен для переключения эталонов: напоминание раз в полчаса.
        if stage == "operator":
            last = self._climate_auto_watch.get("operator_remind")
            if last is not None and now - last >= self.AUTO_REMIND_S:
                self._climate_event(f"всё ещё жду оператора: переключите эталоны при {_c(node)}.", "warn")
                self._climate_auto_watch["operator_remind"] = now
            elif last is None:
                self._climate_auto_watch["operator_remind"] = now

    def _climate_auto_remind_paused(self, now: float):
        """Прогон на паузе: напоминание раз в полчаса, чтобы пауза не тянулась незаметно."""
        if not self._climate_run_paused:
            self._climate_auto_last_remind = None
            return
        if self._climate_auto_last_remind is None:
            self._climate_auto_last_remind = now
            return
        if now - self._climate_auto_last_remind >= self.AUTO_REMIND_S:
            self._climate_auto_last_remind = now
            self._climate_event("прогон всё ещё на паузе. Проверьте камеру и нажмите «Продолжить прогон».", "warn")

    def _climate_auto_hardware_text(self) -> str:
        """Что делает камера сама: нагреватель и холодильник ESPEC - по ним видна неисправность."""
        if self._climate_settings["driver"] != DRIVER_ESPEC:
            return ""
        espec = self._climate_espec_view(self._climate_reading)
        return (f"Режим {espec['modeText']}, нагреватель {espec['heaterText']}, холодильник {espec['refText']}.")

    # ------------------------------------------------------------------ сводка и время

    def _climate_auto_elapsed(self, now: float) -> float:
        """Сколько идёт прогон с начала, с учётом времени до перезапуска программы, с."""
        if self._climate_auto_session_start is None:
            return self._climate_auto_elapsed_before
        return self._climate_auto_elapsed_before + (now - self._climate_auto_session_start) * self._climate_speed()

    def _climate_auto_eta(self, now: float) -> float | None:
        """Сколько примерно осталось: среднее время пройденных узлов на оставшиеся узлы, с."""
        if not self._climate_auto_durations or not self._climate_run_nodes:
            return None
        average = sum(seconds for _node, seconds in self._climate_auto_durations) / len(self._climate_auto_durations)
        # Осталось: текущий шаг и все после него (переход назад или вперёд меняет это число).
        remaining = max(0, len(self._climate_run_nodes) - max(0, int(self._climate_run_index)))
        current = 0.0
        if self._climate_auto_node_start is not None and self._climate_run_stage:
            current = min(average, (now - self._climate_auto_node_start) * self._climate_speed())
        return max(0.0, average * remaining - current)

    def _climate_auto_nodes_text(self) -> str:
        parts = [", ".join(f"{_c(node)} - {duration_text(seconds)}" for node, seconds in self._climate_auto_durations)]
        skipped = getattr(self, "_climate_auto_skipped", None) or []
        if skipped:
            parts.append("Без точки (оставлены вручную): " + ", ".join(
                f"{_c(node)} - {duration_text(seconds)}" for node, seconds in skipped))
        return ". ".join(part for part in parts if part)

    def _climate_auto_summary_text(self, now: float) -> str:
        """Сводка для Telegram: где прогон, камера, плата, точки, время."""
        nodes = self._climate_run_nodes
        index = min(self._climate_run_index, len(nodes) - 1)
        reading = self._climate_reading if self._climate_fresh(now) else None
        board = self._chamber_live_last.get("board_temp") if self._chamber_live_fresh("board_temp", time.monotonic()) \
            else None
        eta = self._climate_auto_eta(now)
        parts = [
            f"сводка: узел {index + 1} из {len(nodes)} ({_c(nodes[index])}), {self._climate_run_status}",
            f"камера {_c(getattr(reading, 'actual_c', None))} при уставке {_c(getattr(reading, 'setpoint_c', None))}",
            f"плата {_c(None if board is None else int(board) / 10.0)}",
            f"точек в журнале {len(getattr(self, '_chamber_points', []) or [])}",
            f"прошло {duration_text(self._climate_auto_elapsed(now))}"
            + (f", осталось ≈ {duration_text(eta)}" if eta is not None else ""),
        ]
        if self._climate_auto_alerts:
            parts.append("проблемы: " + "; ".join(item["text"] for item in self._climate_auto_alerts.values()))
        return ". ".join(parts) + "."

    def _climate_auto_maybe_report(self, now: float):
        """Сводка по расписанию: раз в N минут (0 - не присылать)."""
        every_min = float(self._climate_settings.get("report_every_min", 60.0))
        if every_min <= 0:
            return
        if self._climate_auto_last_report is None:
            self._climate_auto_last_report = now
            return
        if now - self._climate_auto_last_report >= every_min * 60.0 / self._climate_speed():
            self._climate_auto_last_report = now
            self._climate_event(self._climate_auto_summary_text(now), "info", kind="summary")

    # ------------------------------------------------------------------ итог

    def _climate_auto_follow_finish(self, now: float):
        """После последнего узла: дождаться записи профиля и прислать итог прогона."""
        chain_busy = bool(getattr(self, "_chamber_chain_stage", ""))
        waited = now - self._climate_auto_finish_since
        if chain_busy and waited < self.AUTO_FINISH_WAIT_S:
            return
        if waited < 2.0 and getattr(self, "_chamber_auto_write", False) and getattr(self, "_chamber_tables_complete",
                                                                                     False):
            # Запись профиля запускается из расчёта таблиц: дать ей начаться.
            return
        self._climate_auto_finishing = False
        elapsed = getattr(self, "_climate_auto_finish_elapsed", self._climate_auto_elapsed(now))
        tables = str(getattr(self, "_chamber_tables_text", "") or "")
        chain = str(getattr(self, "_chamber_chain_status", "") or "")
        problems = self._climate_auto_problems
        text = (f"ИТОГ ПРОГОНА: пройдено {len(self._climate_auto_durations)} из {len(self._climate_run_nodes)} "
                f"температур за {duration_text(elapsed)}. Точек в журнале: "
                f"{len(getattr(self, '_chamber_points', []) or [])}. По узлам: {self._climate_auto_nodes_text()}. "
                f"Таблицы: {tables} Профиль: {chain} "
                + (f"Проблем за прогон: {len(problems)}." if problems else "Проблем за прогон не было."))
        self._climate_event(text, "ok" if not problems and getattr(self, "_chamber_tables_complete", False) else "warn")
        if problems:
            self._climate_auto_send_report()

    def _climate_auto_send_report(self):
        """Были проблемы: отчёт диагностики файлом - в Telegram тем, у кого включены «файлы»."""
        path = self._climate_save_report()
        remote = getattr(self, "_remote_settings", {}) or {}
        telegram = getattr(self, "_remote_telegram", None)
        if path and telegram is not None and remote.get("telegram_enabled"):
            telegram.send_document(path, "Отчёт диагностики камеры за прогон")

    # ------------------------------------------------------------------ продолжение после перезапуска

    def _climate_auto_clear_resume(self):
        self._climate_auto_resume = None
        self._climate_auto_resume_since = None

    def _climate_auto_ready_to_resume(self, now: float) -> bool:
        """Камера на связи без аварии и прибор присылает температуру платы."""
        reading = self._climate_reading if self._climate_fresh(now) else None
        return (self._climate_link is not None and reading is not None and not getattr(reading, "alarm", None)
                and self._chamber_live_fresh("board_temp", time.monotonic()))

    def _climate_auto_try_resume(self, now: float):
        if not self._climate_settings.get("auto_resume", True):
            return
        if not self._climate_auto_ready_to_resume(now):
            self._climate_auto_resume_since = None
            return
        if self._climate_auto_resume_since is None:
            self._climate_auto_resume_since = now
            return
        if now - self._climate_auto_resume_since >= self.AUTO_RESUME_STEADY_S:
            self._climate_auto_resume_now(now)

    def _climate_auto_resume_now(self, now: float | None = None) -> bool:
        """Продолжает прерванный прогон с того узла, на котором он остановился."""
        saved = self._climate_auto_resume
        if saved is None or self._climate_run_stage:
            return False
        now = time.monotonic() if now is None else now
        if self._climate_link is None or not self._climate_fresh(now):
            self._climate_run_set("Продолжить нельзя: нет связи с камерой.", "#dc2626")
            self.climateChanged.emit()
            return False
        self._climate_auto_restore_chamber(saved.get("chamber") or {})
        self._climate_run_reset()
        self._climate_auto_reset()
        self._climate_run_nodes = list(saved["nodes"])
        steps = saved.get("steps") or []
        self._climate_run_steps = ([dict(step) for step in steps] if len(steps) == len(self._climate_run_nodes)
                                   else [{"temp": node} for node in self._climate_run_nodes])
        self._climate_run_index = int(saved["index"])
        # Доводка платы на этом шаге продолжается с того же сдвига уставки.
        self._climate_run_offset = float(saved.get("offset", 0.0) or 0.0)
        self._climate_run_board_attempts = int(saved.get("board_attempts", 0) or 0)
        self._climate_run_journal_base = int(saved.get("journal_base", 0) or 0)
        self._climate_run_repeat_retries = {}
        self._climate_run_board_pairs = [dict(pair) for pair in saved.get("board_pairs") or []
                                         if isinstance(pair, dict) and {"air", "board", "step", "attempt"} <= set(pair)]
        self._climate_run_labels = list(saved.get("labels") or []) or [str(self._chamber_label).strip()]
        self._climate_run_done = [float(node) for node in saved.get("done") or []]
        self._climate_run_connected = str(self._chamber_label).strip()
        self._climate_auto_durations = [(float(node), float(seconds)) for node, seconds in saved.get("durations") or []]
        self._climate_auto_skipped = [(float(node), float(seconds)) for node, seconds in saved.get("skipped") or []]
        self._climate_auto_elapsed_before = float(saved.get("elapsed_s", 0.0))
        self._climate_auto_problems = list(saved.get("problems") or [])
        self._climate_auto_session_start = now
        self._climate_auto_node_start = now
        self._climate_auto_last_report = now
        self._climate_auto_clear_resume()
        # Узел начинается заново с уставки: за время перезапуска камера могла уйти.
        self._climate_run_enter("setpoint", now)
        if saved.get("paused"):
            self._climate_run_paused = True
            self._climate_auto_paused_by = str(saved.get("paused_by", ""))
        node = self._climate_run_nodes[self._climate_run_index]
        self._climate_event(f"прогон продолжен после перезапуска программы: узел {self._climate_run_index + 1} из "
                            f"{len(self._climate_run_nodes)} ({_c(node)}) начинается заново.", "ok")
        self._climate_run_tick(now)
        self.climateChanged.emit()
        return True

    def _climate_auto_restore_chamber(self, chamber: dict):
        """Возвращает настройки прогона и журнал точек, какими они были до перезапуска.

        Без этого продолженный прогон начал бы новый журнал без точек прошлых
        узлов (и без опорной +25 °C), а таблицу считал бы не в том режиме.
        """
        if not chamber:
            return
        set_board = getattr(self, "_chamber_set_board_only", None)
        if set_board is not None:
            set_board(bool(chamber.get("board_only")))
        set_model = getattr(self, "_chamber_set_single_model", None)
        if set_model is not None and chamber.get("single_model"):
            set_model(str(chamber["single_model"]))
        if chamber.get("label"):
            self._chamber_label = str(chamber["label"])
        if "auto_write" in chamber:
            self._chamber_auto_write = bool(chamber["auto_write"])
        journal = str(chamber.get("journal") or "")
        if journal and journal != str(getattr(self, "_chamber_file_path", "") or ""):
            loader = getattr(self, "_chamber_load_file", None)
            if loader is not None and pathlib.Path(journal).is_file() and loader(journal):
                self._climate_event(f"журнал прогона загружен обратно: {len(self._chamber_points)} точек из {journal}. "
                                    "Новые точки допишутся в него.", "ok")
            else:
                self._climate_event(f"журнал прогона не загрузился ({journal}): точки до перезапуска не войдут "
                                    "в таблицу. Загрузите его вручную в «Прогоне в камере».", "bad")
        changed = getattr(self, "chamberChanged", None)
        if changed is not None:
            changed.emit()

    def _climate_auto_board_preset(self) -> str:
        """Быстрая настройка: испытание одной платы на своих ёмкостях за один цикл.

        Все 7 узлов прибора (первым опорный +25 °C), режим «только плата», пометка
        «0/0», без пометок для переключения, автозапись профиля, тестовый режим
        выключен (кроме имитатора). Возвращает, что сделано, для строки окна.
        """
        if self._climate_run_stage:
            return "Во время прогона настройки не меняются."
        use_scenario = getattr(self, "_climate_scenario_use_board_cycle", None)
        if use_scenario is not None:
            return use_scenario()
        self._climate_set("run_nodes", BOARD_CYCLE_NODES)
        self._climate_set("run_labels", "")
        set_board = getattr(self, "_chamber_set_board_only", None)
        if set_board is not None:
            set_board(True)
        self._chamber_label = "0/0"
        self._chamber_auto_write = True
        if self._climate_settings["driver"] != DRIVER_SIMULATOR:
            set_test = getattr(self, "_chamber_test_set_mode", None)
            if set_test is not None:
                set_test(False)
        changed = getattr(self, "chamberChanged", None)
        if changed is not None:
            changed.emit()
        text = ("Настроено испытание платы за один цикл: узлы " + BOARD_CYCLE_NODES + " °C, «только плата», "
                "пометка «0/0», автозапись профиля.")
        self._climate_command_status = text
        self._climate_diag_event("RUN", text)
        self.climateChanged.emit()
        return text

    def _climate_auto_discard_resume(self):
        """Оператор не хочет продолжать прерванный прогон."""
        if self._climate_auto_resume is None:
            return
        self._climate_auto_clear_resume()
        self._climate_auto_clear_file()
        self._climate_event("прерванный прогон забыт по решению оператора.", "info")
        self.climateChanged.emit()

    # ------------------------------------------------------------------ показ

    def _climate_auto_view(self) -> dict:
        """Автономный прогон для окна и страницы наблюдения."""
        now = time.monotonic()
        active = bool(self._climate_run_stage)
        checks = [] if active else self._climate_auto_checks()
        blockers = [item for item in checks if item["level"] == "block" and not item["ok"]]
        nodes = self._climate_run_nodes
        done = len(self._climate_auto_durations)
        eta = self._climate_auto_eta(now) if active else None
        resume = self._climate_auto_resume
        resume_view = None
        if resume is not None:
            index = int(resume["index"])
            count = len(resume["nodes"])
            resume_view = {
                "text": f"Прогон был прерван перезапуском программы: узел {index + 1} из {count} "
                        f"({_c(resume['nodes'][index])}), прошло {duration_text(resume.get('elapsed_s'))}, "
                        f"сохранено {resume.get('saved', '')}.",
                "auto": bool(self._climate_settings.get("auto_resume", True)),
            }
        level_rank = {"bad": 0, "warn": 1}
        alerts = sorted(self._climate_auto_alerts.values(), key=lambda item: level_rank.get(item["level"], 2))
        return {
            "checks": checks,
            "canStart": not blockers,
            "blockers": [item["text"] for item in blockers],
            "progress": (done / len(nodes)) if active and nodes else 0.0,
            "progressText": (f"Узел {min(self._climate_run_index + 1, len(nodes))} из {len(nodes)}  ·  прошло "
                             f"{duration_text(self._climate_auto_elapsed(now))}"
                             + (f"  ·  осталось ≈ {duration_text(eta)}" if eta is not None else
                                "  ·  оценка времени - после первого узла")) if active and nodes else "",
            "nodesText": self._climate_auto_nodes_text(),
            "alerts": alerts,
            "problems": len(self._climate_auto_problems),
            "finishing": bool(self._climate_auto_finishing),
            "resume": resume_view,
            "pausedBy": self._climate_auto_paused_by,
            # Как плата отстаёт от воздуха в этом прогоне: по ней упреждение и доводка.
            "boardModel": self._climate_run_board_model_text() if hasattr(self, "_climate_run_board_model_text") else "",
        }
