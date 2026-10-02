"""Климатическая камера в программе: связь, показания и автоматический прогон.

ЗАЧЕМ
Прогон в камере - это часы ожидания: камера идёт к уставке, плата догоняет
воздух, потом снимаются точки, потом следующая температура. Если программа
сама задаёт камере уставку и видит её температуру, оператору остаётся только
переключать эталоны, а с реле - вообще ничего.

ЧТО ДЕЛАЕТ
- Держит связь с камерой через общий драйвер (Modbus TCP, Modbus RTU или
  имитатор) и показывает её температуру, уставку, пуск и аварию. Температура
  камеры пишется и в журнал прогона рядом с температурой платы.
- Имитатор связывает с эмуляцией температуры прибора: в тестовом режиме прибор
  показывает температуру изделия из имитатора, и весь автоматический прогон
  отлаживается на столе, без камеры.
- Автоматический прогон по списку узлов. В каждом узле: задать уставку,
  дождаться, пока камера на неё выйдет, дождаться, пока устоится плата (то же
  правило, что у наблюдения: 5 минут медленнее 0,05 °C/мин), снять точки со
  всеми пометками и перейти к следующему узлу. Если пометок несколько, а реле
  нет, программа просит оператора переключить эталоны и ждёт «Продолжить», а
  порядок пометок чередует так, чтобы переключений было меньше.

Обо всём важном - выход на уставку, плата устоялась, нужно переключить
эталоны, нет связи, авария, прогон закончен - узнаёт и наблюдение издалека.
"""

from __future__ import annotations

import json
import pathlib
import threading
import time
from collections import deque

from PySide6.QtCore import QTimer

from ui.qml.climate_chamber import (
    DRIVER_MODBUS_RTU,
    DRIVER_MODBUS_TCP,
    DRIVER_NONE,
    DRIVER_SIMCON,
    DRIVER_SIMULATOR,
    ChamberLink,
    ModbusMap,
    make_driver,
)

from .contract import AppControllerContract
from .stability import is_stable, rate_and_spread

DRIVERS = (DRIVER_NONE, DRIVER_SIMULATOR, DRIVER_SIMCON, DRIVER_MODBUS_TCP, DRIVER_MODBUS_RTU)
DRIVER_TITLES = {
    DRIVER_NONE: "без связи",
    DRIVER_SIMULATOR: "имитатор",
    DRIVER_SIMCON: "Weiss SIMCON/32",
    DRIVER_MODBUS_TCP: "Modbus TCP",
    DRIVER_MODBUS_RTU: "Modbus RTU (RS-485)",
}


def _c(value) -> str:
    """Градусы для показа: со знаком и запятой."""
    if value is None:
        return "—"
    return f"{float(value):+.1f} °C".replace(".", ",")


def parse_nodes(text: str) -> list[float]:
    """Список температур из строки «25, -40, -20»."""
    nodes = []
    for part in str(text).replace(";", " ").replace(",", " ").split():
        cleaned = part.replace("°", "").replace("C", "").replace("С", "").strip()
        if not cleaned:
            continue
        nodes.append(float(cleaned))
    return nodes


def parse_labels(text: str) -> list[str]:
    """Пометки через точку с запятой: «0/0; 68/22; 150/47»."""
    return [part.strip() for part in str(text).split(";") if part.strip()]


class AppControllerClimateChamberMixin(AppControllerContract):
    CLIMATE_TICK_MS = 500
    # Показание камеры старше этого считается устаревшим, с.
    CLIMATE_STALE_S = 15.0
    # Как часто класть температуру платы в историю для правила устойчивости, с.
    CLIMATE_BOARD_STEP_S = 5.0
    # Мост имитатора с эмуляцией: шаг температуры и пауза между записями.
    CLIMATE_BRIDGE_STEP_X10 = 1
    CLIMATE_BRIDGE_PAUSE_S = 1.0
    # Повторы точки, которая не записалась, и пауза между ними.
    CLIMATE_CAPTURE_RETRIES = 3
    CLIMATE_CAPTURE_RETRY_S = 10.0
    CLIMATE_STABLE_SPREAD_C = 0.3

    # ------------------------------------------------------------------ состояние

    def _init_climate_state(self):
        """Готовит раздел камеры и подключается, если так было в прошлый раз."""
        self._climate_lock = threading.Lock()
        self._climate_incoming: list[dict] = []
        self._climate_settings = self._climate_default_settings()
        self._climate_settings.update(self._climate_load_settings())

        self._climate_link: ChamberLink | None = None
        self._climate_reading = None
        self._climate_last_ok_s = 0.0
        self._climate_status = "Связь с камерой выключена."
        self._climate_ok = False
        self._climate_command_status = ""
        self._climate_lost_reported = False
        self._climate_alarm_reported = 0

        self._climate_history: deque = deque(maxlen=int(3 * 3600 / self.CLIMATE_BOARD_STEP_S))
        self._climate_board: deque = deque(maxlen=int(3 * 3600 / self.CLIMATE_BOARD_STEP_S))
        self._climate_last_board_s = 0.0
        self._climate_bridge_last_s = 0.0
        self._climate_bridge_status = ""
        # Строки оператора камере и её ответы: для проверки связи на месте.
        self._climate_raw_log: deque = deque(maxlen=20)

        self._climate_run_reset()

        self._climate_timer = QTimer(self)
        self._climate_timer.setInterval(self.CLIMATE_TICK_MS)
        self._climate_timer.timeout.connect(self._on_climate_tick)
        self._climate_timer.start()

        if self._climate_settings["autoconnect"] and self._climate_settings["driver"] != DRIVER_NONE:
            self._climate_connect()

    def _climate_run_reset(self):
        """Прогон не идёт: всё, что относится к нему, в исходном виде."""
        self._climate_run_stage = ""
        self._climate_run_nodes: list[float] = []
        self._climate_run_index = 0
        self._climate_run_labels: list[str] = []
        self._climate_run_order: list[str] = []
        self._climate_run_label_index = 0
        self._climate_run_connected = ""
        self._climate_run_since = 0.0
        self._climate_run_warned = False
        self._climate_run_paused = False
        self._climate_run_points = 0
        self._climate_run_attempts = 0
        self._climate_run_retry_at = 0.0
        self._climate_run_done: list[float] = []
        self._climate_run_status = "Автоматический прогон не идёт."
        self._climate_run_color = "#64748b"

    @staticmethod
    def _climate_default_settings() -> dict:
        return {
            "driver": DRIVER_NONE,
            "autoconnect": True,
            "poll_s": 2.0,
            "unit": 1,
            "tcp_host": "192.168.100.2",
            "tcp_port": 502,
            "rtu_port": "COM3",
            "rtu_baud": 9600,
            "rtu_parity": "N",
            "rtu_stopbits": 1,
            # Адрес камеры Weiss из меню пульта «Address», по умолчанию там 0.
            "simcon_address": 0,
            "sim_speed": 1.0,
            "sim_bridge": True,
            "map": ModbusMap().to_dict(),
            "min_c": -45.0,
            "max_c": 90.0,
            "run_nodes": "25, -40, -20, 0, 50, 70, 85",
            "run_labels": "",
            "reach_tolerance_c": 1.0,
            "reach_timeout_min": 120.0,
            "settle_min": 5.0,
            "settle_rate": 0.05,
            "settle_timeout_min": 180.0,
            "finish_setpoint": 25.0,
            "finish_stop": False,
        }

    def _climate_settings_path(self) -> pathlib.Path:
        root = getattr(self, "_project_root_directory", None) or pathlib.Path.cwd()
        return pathlib.Path(root) / "config" / "climate_chamber.json"

    def _climate_load_settings(self) -> dict:
        """Читает сохранённые настройки. Испорченный файл не мешает запуску."""
        try:
            payload = json.loads(self._climate_settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        defaults = self._climate_default_settings()
        result = {}
        for key, default in defaults.items():
            if key not in payload:
                continue
            value = payload[key]
            if isinstance(default, bool) and isinstance(value, bool):
                result[key] = value
            elif isinstance(default, (int, float)) and not isinstance(default, bool) \
                    and isinstance(value, (int, float)) and not isinstance(value, bool):
                result[key] = type(default)(value)
            elif isinstance(default, (str, dict)) and isinstance(value, type(default)):
                result[key] = value
        return result

    def _climate_save_settings(self):
        try:
            path = self._climate_settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._climate_settings, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            self._climate_command_status = f"Настройки камеры не сохранились: {error}"

    # ------------------------------------------------------------------ настройки

    def _climate_set(self, key: str, value) -> bool:
        """Меняет настройку. Настройки связи переподключают камеру."""
        settings = self._climate_settings
        if key.startswith("map."):
            _prefix, name, field = (key.split(".") + ["", ""])[:3]
            register_map = ModbusMap.from_dict(settings["map"]).to_dict()
            if name not in register_map or field not in register_map[name]:
                return False
            entry = dict(register_map[name])
            entry[field] = value
            register_map[name] = entry
            settings["map"] = ModbusMap.from_dict(register_map).to_dict()
            reconnect = True
        else:
            if key not in settings:
                return False
            default = self._climate_default_settings()[key]
            try:
                if isinstance(default, bool):
                    value = value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "да")
                elif isinstance(default, int):
                    value = int(str(value).strip())
                elif isinstance(default, float):
                    value = float(str(value).strip().replace(",", "."))
                else:
                    value = str(value).strip()
            except ValueError:
                self._climate_command_status = "Это поле задаётся числом."
                self.climateChanged.emit()
                return False
            if key == "driver" and value not in DRIVERS:
                return False
            if settings[key] == value:
                return True
            settings[key] = value
            reconnect = key in ("driver", "poll_s", "unit", "tcp_host", "tcp_port", "rtu_port", "rtu_baud",
                                "rtu_parity", "rtu_stopbits", "sim_speed", "simcon_address")
        self._climate_save_settings()
        if reconnect and self._climate_link is not None:
            self._climate_connect()
        self.climateChanged.emit()
        return True

    # ------------------------------------------------------------------ связь

    def _climate_connect(self) -> bool:
        """Подключается к камере по текущим настройкам. Прежняя связь закрывается."""
        self._climate_disconnect(quiet=True)
        driver = make_driver(self._climate_settings)
        if driver is None:
            self._climate_status = "Выберите, как подключена камера."
            self._climate_ok = False
            self.climateChanged.emit()
            return False
        self._climate_link = ChamberLink(driver, float(self._climate_settings["poll_s"]), self._climate_queue_state)
        self._climate_apply_live()
        self._climate_status = f"Подключаюсь: {driver.title}..."
        self._climate_ok = False
        self._climate_lost_reported = False
        self.climateChanged.emit()
        return True

    def _climate_disconnect(self, quiet: bool = False):
        link = self._climate_link
        self._climate_link = None
        if link is not None:
            link.close()
        self._climate_reading = None
        self._climate_apply_live()
        if not quiet:
            self._climate_status = "Связь с камерой выключена."
            self._climate_ok = False
            self.climateChanged.emit()

    def _climate_keeps_live(self) -> bool:
        """Прибор нужно опрашивать всегда, пока подключена камера: прогону нужна температура платы."""
        return self._climate_link is not None or bool(self._climate_run_stage)

    def _climate_apply_live(self):
        apply_live = getattr(self, "_chamber_live_apply_wanted", None)
        if apply_live is not None:
            apply_live()

    def _climate_queue_state(self, state: dict):
        """Итог потока связи. Окно заберёт его в свой такт."""
        with self._climate_lock:
            self._climate_incoming.append(state)

    def _climate_take_incoming(self, now: float) -> bool:
        with self._climate_lock:
            incoming = list(self._climate_incoming)
            self._climate_incoming.clear()
        for state in incoming:
            if state.get("kind") == "reading" and state.get("ok"):
                self._climate_reading = state["reading"]
                self._climate_last_ok_s = now
                title = self._climate_link.driver.title if self._climate_link is not None else "камера"
                self._climate_status = f"Связь есть: {title}."
                self._climate_ok = True
                if self._climate_lost_reported:
                    self._climate_lost_reported = False
                    self._climate_event("связь с камерой восстановлена.", "ok")
                self._climate_watch_alarm()
            elif state.get("kind") == "raw":
                self._climate_raw_log.appendleft({
                    "time": time.strftime("%H:%M:%S"),
                    "sent": str(state.get("sent", "")),
                    "answer": str(state.get("text", "")),
                    "ok": bool(state.get("ok")),
                })
            elif state.get("kind") == "reading":
                self._climate_status = f"Нет связи с камерой: {state.get('text')}. Повторяю..."
                self._climate_ok = False
            else:
                self._climate_command_status = ("Камера: " if state.get("ok") else "Камера не выполнила: ") + \
                    str(state.get("text"))
                if not state.get("ok"):
                    self._climate_event(f"камера не выполнила команду: {state.get('text')}.", "bad")
        return bool(incoming)

    def _climate_fresh(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self._climate_reading is not None and now - self._climate_last_ok_s <= self.CLIMATE_STALE_S

    def _climate_watch_alarm(self):
        alarm = getattr(self._climate_reading, "alarm", None)
        if alarm and alarm != self._climate_alarm_reported:
            self._climate_event(f"АВАРИЯ КАМЕРЫ: код {alarm}. Проверьте камеру.", "bad")
        self._climate_alarm_reported = alarm or 0

    def _climate_event(self, text: str, level: str = "info"):
        """Событие камеры: в журнал программы и наблюдению издалека."""
        handler = getattr(self, "_remote_event", None)
        if handler is not None:
            handler(text, level)

    def _climate_send_setpoint(self, value_c: float) -> bool:
        """Уставка камере, с проверкой пределов из настроек."""
        if self._climate_link is None:
            self._climate_command_status = "Камера не подключена."
            self.climateChanged.emit()
            return False
        low, high = float(self._climate_settings["min_c"]), float(self._climate_settings["max_c"])
        if not (low <= float(value_c) <= high):
            self._climate_command_status = f"Уставка вне допустимых пределов {low:+.0f}...{high:+.0f} °C."
            self.climateChanged.emit()
            return False
        if not self._climate_link.driver.can_set:
            self._climate_command_status = "Эта камера не даёт задавать уставку: адрес уставки не задан."
            self.climateChanged.emit()
            return False
        self._climate_link.command("setpoint", float(value_c))
        self._climate_command_status = f"Задаю уставку {_c(value_c)}..."
        self.climateChanged.emit()
        return True

    def _climate_send_run(self, on: bool) -> bool:
        if self._climate_link is None or not self._climate_link.driver.can_run:
            self._climate_command_status = "Пуск и остановка камеры из программы не настроены."
            self.climateChanged.emit()
            return False
        self._climate_link.command("run", bool(on))
        self.climateChanged.emit()
        return True

    def _climate_send_raw(self, text: str) -> bool:
        """Строка камере как есть: проверка протокола на месте, например «$00I»."""
        line = str(text).strip()
        if not line:
            return False
        if self._climate_link is None:
            self._climate_command_status = "Камера не подключена."
            self.climateChanged.emit()
            return False
        self._climate_link.command("raw", line)
        self._climate_command_status = f"Отправляю «{line}»: ответ придёт не раньше чем через 5 с после прошлой строки."
        self.climateChanged.emit()
        return True

    def _climate_set_setpoint_text(self, text: str) -> bool:
        try:
            value = float(str(text).replace(",", ".").replace("°", "").replace("C", "").strip())
        except ValueError:
            self._climate_command_status = "Уставка задаётся числом градусов."
            self.climateChanged.emit()
            return False
        return self._climate_send_setpoint(value)

    def _climate_point_temperature(self):
        """Температура камеры для строки журнала прогона, в десятых градуса, или None."""
        if not self._climate_fresh() or self._climate_reading.actual_c is None:
            return None
        return int(round(float(self._climate_reading.actual_c) * 10))

    # ------------------------------------------------------------------ такт

    def _on_climate_tick(self):
        now = time.monotonic()
        changed = self._climate_take_incoming(now)
        if self._climate_link is not None:
            changed = True
            if not self._climate_fresh(now) and self._climate_last_ok_s > 0.0 and not self._climate_lost_reported:
                self._climate_lost_reported = True
                self._climate_event(f"нет связи с камерой дольше {int(self.CLIMATE_STALE_S)} с.", "bad")
            self._climate_note_history(now)
            self._climate_bridge(now)
        self._climate_note_board(now)
        if self._climate_run_stage:
            self._climate_run_tick(now)
            changed = True
        if changed:
            self.climateChanged.emit()

    def _climate_note_history(self, now: float):
        if not self._climate_fresh(now):
            return
        if self._climate_history and now - self._climate_history[-1][0] < self.CLIMATE_BOARD_STEP_S:
            return
        reading = self._climate_reading
        self._climate_history.append((now, reading.actual_c, reading.setpoint_c))

    def _climate_note_board(self, now: float):
        """Температура платы из прибора для правила «устоялась»."""
        if now - self._climate_last_board_s < self.CLIMATE_BOARD_STEP_S:
            return
        self._climate_last_board_s = now
        if not self._chamber_live_fresh("board_temp", now):
            return
        self._climate_board.append((now, int(self._chamber_live_last["board_temp"]) / 10.0))

    def _climate_speed(self) -> float:
        """Ускорение времени: у имитатора правило устойчивости сжимается вместе с ним."""
        if self._climate_settings["driver"] == DRIVER_SIMULATOR:
            return max(0.1, float(self._climate_settings["sim_speed"]))
        return 1.0

    # ------------------------------------------------------------------ мост с эмуляцией

    def _climate_bridge_active(self) -> bool:
        return (self._climate_settings["driver"] == DRIVER_SIMULATOR and bool(self._climate_settings["sim_bridge"])
                and bool(getattr(self, "_chamber_test_mode", False)))

    def _climate_bridge(self, now: float):
        """Имитатор задаёт прибору температуру изделия через эмуляцию тестового режима."""
        if self._climate_settings["driver"] != DRIVER_SIMULATOR or not self._climate_settings["sim_bridge"]:
            self._climate_bridge_status = ""
            return
        if not getattr(self, "_chamber_test_mode", False):
            self._climate_bridge_status = ("Чтобы прибор показывал температуру имитатора, включите тестовый режим "
                                           "в разделе «Прогон в камере».")
            return
        reading = self._climate_reading
        if reading is None or reading.product_c is None or not self._climate_fresh(now):
            return
        target = int(round(float(reading.product_c) * 10))
        self._climate_bridge_status = f"Прибору задаётся температура изделия из имитатора: {_c(target / 10)}."
        if self._chamber_test_busy() or self._chamber_busy or self._chamber_capture_waiting:
            return
        if now - self._climate_bridge_last_s < self.CLIMATE_BRIDGE_PAUSE_S:
            return
        current = getattr(self, "_chamber_test_emulation", None)
        if current is not None and abs(int(current) - target) < self.CLIMATE_BRIDGE_STEP_X10:
            return
        self._climate_bridge_last_s = now
        self._chamber_test_start_set(max(-400, min(850, target)))

    # ------------------------------------------------------------------ автоматический прогон

    def _climate_run_set(self, text: str, color: str = "#0f6ab4"):
        self._climate_run_status = str(text)
        self._climate_run_color = str(color)

    def _climate_run_start(self) -> bool:
        """Запускает прогон по списку узлов из настроек."""
        if self._climate_run_stage:
            return False
        if self._climate_link is None or not self._climate_fresh():
            self._climate_run_set("Прогон не запущен: нет связи с камерой.", "#dc2626")
            self.climateChanged.emit()
            return False
        if not self._climate_link.driver.can_set:
            self._climate_run_set("Прогон не запущен: камера не даёт задавать уставку.", "#dc2626")
            self.climateChanged.emit()
            return False
        try:
            nodes = parse_nodes(self._climate_settings["run_nodes"])
        except ValueError:
            self._climate_run_set("Прогон не запущен: список температур не разобрался.", "#dc2626")
            self.climateChanged.emit()
            return False
        low, high = float(self._climate_settings["min_c"]), float(self._climate_settings["max_c"])
        if not nodes or any(not (low <= node <= high) for node in nodes):
            self._climate_run_set(f"Прогон не запущен: температуры должны быть от {low:+.0f} до {high:+.0f} °C.",
                                  "#dc2626")
            self.climateChanged.emit()
            return False
        labels = parse_labels(self._climate_settings["run_labels"]) or [str(self._chamber_label).strip()]
        if not labels[0]:
            self._climate_run_set("Прогон не запущен: напишите, что подключено к прибору, или список пометок.",
                                  "#dc2626")
            self.climateChanged.emit()
            return False

        self._climate_run_reset()
        self._climate_run_nodes = nodes
        self._climate_run_labels = labels
        self._climate_run_connected = str(self._chamber_label).strip()
        self._climate_run_stage = "setpoint"
        self._climate_event(
            f"автоматический прогон начат: {len(nodes)} температур, пометки {', '.join(labels)}.", "info")
        self._climate_run_tick(time.monotonic())
        self.climateChanged.emit()
        return True

    def _climate_run_stop(self, reason: str = "остановлен оператором"):
        if not self._climate_run_stage:
            return
        self._climate_run_stage = ""
        self._climate_run_set(f"Автоматический прогон {reason}. Уставка камеры оставлена как есть.", "#d97706")
        self._climate_event(f"автоматический прогон {reason}.", "warn")
        self.climateChanged.emit()

    def _climate_run_pause(self, paused: bool):
        if not self._climate_run_stage:
            return
        self._climate_run_paused = bool(paused)
        self.climateChanged.emit()

    def _climate_run_continue(self):
        """Оператор переключил эталоны: прогон идёт дальше."""
        if self._climate_run_stage != "operator":
            return
        self._climate_run_connected = self._climate_run_order[self._climate_run_label_index]
        self._climate_run_stage = "window"
        self._climate_run_since = time.monotonic()
        self.climateChanged.emit()

    def _climate_run_node(self) -> float:
        return self._climate_run_nodes[self._climate_run_index]

    def _climate_run_enter(self, stage: str, now: float):
        self._climate_run_stage = stage
        self._climate_run_since = now
        self._climate_run_warned = False

    def _climate_run_tick(self, now: float):
        """Шаг прогона. Каждый этап ждёт своего условия и переходит к следующему."""
        if self._climate_run_paused:
            self._climate_run_set("Прогон на паузе. Нажмите «Продолжить прогон».", "#d97706")
            return
        stage = self._climate_run_stage
        node = self._climate_run_node()
        where = f"{self._climate_run_index + 1} из {len(self._climate_run_nodes)}, {_c(node)}"

        if stage == "setpoint":
            if self._climate_send_setpoint(node):
                if self._climate_link.driver.can_run and not getattr(self._climate_reading, "running", True):
                    self._climate_send_run(True)
                self._climate_run_enter("reach", now)
                self._climate_run_set(f"Узел {where}: уставка задана, камера идёт к ней.")
            else:
                self._climate_run_stop(f"остановлен: {self._climate_command_status}")
            return

        if stage == "reach":
            actual = getattr(self._climate_reading, "actual_c", None) if self._climate_fresh(now) else None
            tolerance = float(self._climate_settings["reach_tolerance_c"])
            if actual is not None and abs(actual - node) <= tolerance:
                self._climate_event(f"камера вышла на {_c(node)}, жду, пока устоится плата.", "info")
                self._climate_run_enter("settle", now)
                return
            self._climate_run_set(f"Узел {where}: камера идёт к уставке, сейчас {_c(actual)}.")
            self._climate_run_timeout(now, "reach_timeout_min", f"камера не вышла на {_c(node)}")
            return

        if stage == "settle":
            speed = self._climate_speed()
            window_s = float(self._climate_settings["settle_min"]) * 60.0 / speed
            rate_limit = float(self._climate_settings["settle_rate"]) * speed
            result = rate_and_spread(self._climate_board, now, window_s)
            if is_stable(result, window_s, rate_limit, self.CLIMATE_STABLE_SPREAD_C):
                board = self._climate_board[-1][1]
                self._climate_event(f"плата устоялась при {_c(board)} (узел {_c(node)}), снимаю точки.", "ok")
                self._climate_run_label_index = 0
                self._climate_run_order = self._climate_label_order()
                self._climate_run_enter("points", now)
                return
            rate = "—" if result is None else f"{result[0] / speed:+.3f} °C/мин".replace(".", ",")
            self._climate_run_set(f"Узел {where}: камера на уставке, жду, пока устоится плата ({rate}).")
            self._climate_run_timeout(now, "settle_timeout_min", f"плата не устоялась при {_c(node)}")
            return

        if stage == "points":
            if self._climate_run_label_index >= len(self._climate_run_order):
                self._climate_run_done.append(node)
                self._climate_run_index += 1
                if self._climate_run_index >= len(self._climate_run_nodes):
                    self._climate_run_finish()
                else:
                    self._climate_run_enter("setpoint", now)
                return
            label = self._climate_run_order[self._climate_run_label_index]
            if label != self._climate_run_connected:
                self._climate_run_enter("operator", now)
                self._climate_run_set(f"Узел {where}: переключите эталоны на «{label}» и нажмите «Эталоны переключены».",
                                      "#d97706")
                self._climate_event(f"нужен оператор: переключите эталоны на «{label}» при {_c(node)}.", "warn")
                return
            self._climate_run_attempts = 0
            self._climate_run_enter("capture", now)
            return

        if stage == "operator":
            return

        if stage == "window":
            # После переключения эталона среднее набирается заново: ждём целое окно.
            if now - self._climate_run_since >= float(self._chamber_window_s):
                self._climate_run_attempts = 0
                self._climate_run_enter("capture", now)
            else:
                left = int(float(self._chamber_window_s) - (now - self._climate_run_since))
                self._climate_run_set(f"Узел {where}: эталоны переключены, среднее набирается ещё {left} с.")
            return

        if stage == "capture":
            if now < self._climate_run_retry_at:
                return
            label = self._climate_run_order[self._climate_run_label_index]
            self._chamber_label = label
            self.chamberChanged.emit()
            self._climate_run_points = len(self._chamber_points)
            if self._chamber_capture_from_average():
                self._climate_run_enter("capturing", now)
                self._climate_run_set(f"Узел {where}: записываю точку «{label}».")
            else:
                self._climate_run_capture_failed(now)
            return

        if stage == "capturing":
            if len(self._chamber_points) > self._climate_run_points:
                self._climate_run_label_index += 1
                self._climate_run_enter("points", now)
                return
            if not self._chamber_capture_waiting:
                self._climate_run_capture_failed(now)

    def _climate_run_capture_failed(self, now: float):
        """Точка не записалась: несколько повторов, затем пауза и зов оператора."""
        self._climate_run_attempts += 1
        if self._climate_run_attempts >= self.CLIMATE_CAPTURE_RETRIES:
            self._climate_run_paused = True
            self._climate_run_enter("capture", now)
            self._climate_event(f"точка не записалась {self.CLIMATE_CAPTURE_RETRIES} раза подряд: "
                                f"{self._chamber_status} Прогон на паузе.", "bad")
            return
        self._climate_run_stage = "capture"
        self._climate_run_retry_at = now + self.CLIMATE_CAPTURE_RETRY_S

    def _climate_run_timeout(self, now: float, key: str, what: str):
        """Этап затянулся: предупреждение один раз, прогон ждёт дальше."""
        limit_s = float(self._climate_settings[key]) * 60.0 / self._climate_speed()
        if not self._climate_run_warned and now - self._climate_run_since > limit_s:
            self._climate_run_warned = True
            self._climate_event(f"{what} за {float(self._climate_settings[key]):.0f} мин. Прогон ждёт дальше, "
                                "проверьте камеру.", "warn")

    def _climate_label_order(self) -> list[str]:
        """Порядок пометок в узле: начинаем с уже подключённой, чтобы переключать реже."""
        labels = list(self._climate_run_labels)
        if self._climate_run_connected in labels and labels[0] != self._climate_run_connected:
            if labels[-1] == self._climate_run_connected:
                labels.reverse()
            else:
                index = labels.index(self._climate_run_connected)
                labels = labels[index:] + labels[:index]
        return labels

    def _climate_run_finish(self):
        self._climate_run_stage = ""
        finish = self._climate_settings["finish_setpoint"]
        tail = ""
        if finish is not None and self._climate_link is not None and self._climate_link.driver.can_set:
            self._climate_send_setpoint(float(finish))
            tail = f" Камере задано {_c(finish)}."
        if self._climate_settings["finish_stop"]:
            self._climate_send_run(False)
            tail += " Камера остановлена."
        self._climate_run_set(f"Автоматический прогон закончен: пройдено {len(self._climate_run_done)} температур.{tail}",
                              "#16a34a")
        self._climate_event(f"автоматический прогон закончен: {len(self._climate_run_done)} температур.{tail}", "ok")

    # ------------------------------------------------------------------ показ

    def _climate_view(self) -> dict:
        now = time.monotonic()
        settings = self._climate_settings
        reading = self._climate_reading if self._climate_fresh(now) else None
        register_map = ModbusMap.from_dict(settings["map"]).to_dict()
        link = self._climate_link

        nodes = []
        try:
            planned = self._climate_run_nodes or parse_nodes(settings["run_nodes"])
        except ValueError:
            planned = []
        for index, node in enumerate(planned):
            if self._climate_run_stage and index < self._climate_run_index:
                state = "done"
            elif self._climate_run_stage and index == self._climate_run_index:
                state = "run"
            else:
                state = ""
            nodes.append({"text": _c(node), "state": state})

        stage_titles = {
            "setpoint": "уставка", "reach": "выход на уставку", "settle": "плата устаивается",
            "points": "точки", "operator": "ждёт оператора", "window": "среднее набирается",
            "capture": "запись точки", "capturing": "запись точки",
        }
        return {
            "driver": settings["driver"],
            "drivers": [{"key": key, "title": DRIVER_TITLES[key]} for key in DRIVERS],
            "connected": link is not None,
            "ok": bool(self._climate_ok) and reading is not None,
            "status": self._climate_status,
            "commandStatus": self._climate_command_status,
            "canSet": bool(link is not None and link.driver.can_set),
            "canRun": bool(link is not None and link.driver.can_run),
            "actualText": _c(getattr(reading, "actual_c", None)),
            "setpointText": _c(getattr(reading, "setpoint_c", None)),
            "runningText": ("—" if getattr(reading, "running", None) is None
                            else ("работает" if reading.running else "остановлена")),
            "alarmText": ("—" if getattr(reading, "alarm", None) is None
                          else ("нет" if not reading.alarm else f"АВАРИЯ, код {reading.alarm}")),
            "alarm": bool(getattr(reading, "alarm", 0)),
            "productText": _c(getattr(reading, "product_c", None)),
            "rawLog": list(self._climate_raw_log),
            "bridgeStatus": self._climate_bridge_status,
            "settings": {key: (value if not isinstance(value, float) else f"{value:g}".replace(".", ","))
                         for key, value in settings.items() if key != "map"},
            "map": register_map,
            "run": {
                "active": bool(self._climate_run_stage),
                "paused": bool(self._climate_run_paused),
                "operator": self._climate_run_stage == "operator",
                "stage": stage_titles.get(self._climate_run_stage, ""),
                "status": self._climate_run_status,
                "color": self._climate_run_color,
                "nodes": nodes,
            },
            "history": {
                "t": [round(stamp - now, 1) for stamp, *_rest in self._climate_history],
                "actual": [None if actual is None else round(float(actual), 2)
                           for _stamp, actual, _sp in self._climate_history],
                "setpoint": [None if sp is None else round(float(sp), 2) for _stamp, _actual, sp in self._climate_history],
            },
        }

    def _climate_shutdown(self):
        """Закрывает связь с камерой вместе с программой."""
        self._climate_disconnect(quiet=True)

