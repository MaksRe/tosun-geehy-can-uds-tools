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

import csv
import json
import pathlib
import sys
import threading
import time
from collections import deque
from datetime import datetime

from PySide6.QtCore import QTimer

from ui.qml.climate_chamber import (
    DRIVER_ESPEC,
    DRIVER_MODBUS_RTU,
    DRIVER_MODBUS_TCP,
    DRIVER_NONE,
    DRIVER_SIMCON,
    DRIVER_SIMULATOR,
    ESPEC_COMMANDS,
    ESPEC_COMMANDS_BY_KEY,
    PORT_AUTO,
    ChamberError,
    ChamberLink,
    ModbusMap,
    build_espec_command,
    describe_espec_answer,
    espec_is_setting,
    espec_mode_text,
    list_serial_ports,
    make_driver,
    reading_text,
    resolve_port,
)
from ui.qml.climate_diag import ChamberDiagLog, environment_info, moxa_registry_info
from ui.qml.climate_scenario import DEFAULTS as SCENARIO_DEFAULTS

from .contract import AppControllerContract
from .stability import air_for_board, fit_board_model, is_stable, predict_final, rate_and_spread

DRIVERS = (DRIVER_NONE, DRIVER_ESPEC, DRIVER_SIMCON, DRIVER_SIMULATOR, DRIVER_MODBUS_TCP, DRIVER_MODBUS_RTU)

# Камеры, с которыми работает программа: у каждой своё назначение, чтобы их не путать.
# board_only - какой режим раздела «Прогон в камере» подходит этой камере.
CHAMBERS = {
    DRIVER_ESPEC: {
        "name": "ESPEC MC-811P",
        "purpose": "Испытания платы",
        "link": "RS-485, 4 провода",
        "accent": "#0f766e",
        "board_only": True,
    },
    DRIVER_SIMCON: {
        "name": "Weiss WK1-600/70",
        "purpose": "Изделие в сборе: плата с трубками в корпусе",
        "link": "RS-232",
        "accent": "#1d4ed8",
        "board_only": False,
    },
    DRIVER_SIMULATOR: {
        "name": "Имитатор камеры",
        "purpose": "Отладка порядка работы на столе",
        "link": "без камеры",
        "accent": "#9a3412",
        "board_only": None,
    },
    DRIVER_MODBUS_TCP: {
        "name": "Другая камера, Modbus TCP",
        "purpose": "Камера с картой регистров",
        "link": "Ethernet",
        "accent": "#64748b",
        "board_only": None,
    },
    DRIVER_MODBUS_RTU: {
        "name": "Другая камера, Modbus RTU",
        "purpose": "Камера с картой регистров",
        "link": "RS-485, 2 провода",
        "accent": "#64748b",
        "board_only": None,
    },
}
DRIVER_TITLES = {DRIVER_NONE: "не выбрана", **{key: value["name"] for key, value in CHAMBERS.items()}}

# Список команд ESPEC для окна: каталог драйвера в виде, удобном QML.
ESPEC_COMMAND_LIST = [
    {
        "key": item["key"],
        "group": item["group"],
        "title": item["title"],
        "hint": item.get("hint", ""),
        "command": item["command"],
        "params": [{"name": param["name"], "label": param["label"], "default": str(param.get("default", ""))}
                   for param in item.get("params", [])],
        "setting": espec_is_setting(item["command"]),
        "danger": bool(item.get("danger")),
        "newOnly": bool(item.get("new_only")),
    }
    for item in ESPEC_COMMANDS
]


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
        self._climate_raw_log: deque = deque(maxlen=50)
        self._climate_ports_reset()
        self._climate_diag_reset(self._climate_logs_directory())

        self._climate_run_reset()
        # Сценарий прогона: последний открытый или собранный из прежних настроек.
        self._climate_hook("_climate_scenario_init")
        # Автономный прогон: сторож, сводки и продолжение прогона, прерванного перезапуском.
        self._climate_hook("_climate_auto_init")

        self._climate_timer = QTimer(self)
        self._climate_timer.setInterval(self.CLIMATE_TICK_MS)
        self._climate_timer.timeout.connect(self._on_climate_tick)
        self._climate_timer.start()

        if self._climate_settings["autoconnect"] and self._climate_settings["driver"] != DRIVER_NONE:
            self._climate_connect()

    def _climate_ports_reset(self):
        """COM-порты компьютера и поиск камеры ESPEC: исходное состояние и первый список портов."""
        self._climate_ports: list[dict] = []
        self._climate_scan_active = False
        self._climate_scan_status = ""
        try:
            self._climate_ports = list_serial_ports()
        except Exception:  # noqa: BLE001 - без списка портов программа работает, порт вписывается руками
            self._climate_ports = []

    def _climate_logs_directory(self) -> pathlib.Path:
        """Папка журналов камеры: logs/chamber рядом с программой.

        У собранной программы - рядом с exe, а не во внутренней папке _internal:
        там журналы не видно и они пропадают при замене версии.
        """
        if getattr(sys, "frozen", False):
            return pathlib.Path(sys.executable).resolve().parent / "logs" / "chamber"
        root = getattr(self, "_project_root_directory", None) or pathlib.Path.cwd()
        return pathlib.Path(root) / "logs" / "chamber"

    def _climate_diag_reset(self, directory: pathlib.Path | None):
        """Журнал диагностики связи, режим портов Moxa из реестра и итог проверки связи."""
        self._climate_diag = ChamberDiagLog(directory)
        self._climate_diag.verbose = bool(self._climate_settings.get("diag_verbose", False))
        self._climate_selftest = {"active": False, "text": "", "results": []}
        self._climate_moxa: list[dict] = []
        try:
            self._climate_moxa = moxa_registry_info()
        except Exception:  # noqa: BLE001 - реестр нужен только для подсказки
            self._climate_moxa = []

    def _climate_diag_event(self, kind: str, text: str, level: str = "INFO"):
        diag = getattr(self, "_climate_diag", None)
        if diag is not None:
            diag.event(kind, text, level)

    def _climate_run_reset(self):
        """Прогон не идёт: всё, что относится к нему, в исходном виде."""
        self._climate_run_stage = ""
        self._climate_run_nodes: list[float] = []
        # Шаги сценария рядом с температурами: у шага свои выдержка, критерии и «снимать ли точку».
        self._climate_run_steps: list[dict] = []
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
        # Пары «уставка камеры - где устоялась плата» за прогон: из них модель «воздух → плата».
        self._climate_run_board_pairs: list[dict] = []
        self._climate_run_reset_board()
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
            # ESPEC MC-811P: адрес 1...16, разделитель строк как в меню пульта камеры.
            # Порт «auto» - программа сама находит переходник Moxa UPort 1150.
            "espec_port": PORT_AUTO,
            "espec_baud": 9600,
            "espec_address": 1,
            "espec_delimiter": "CRLF",
            # Weiss WK1-600/70: свой COM-порт, чтобы настройки двух камер не путались.
            "weiss_port": "COM3",
            "weiss_baud": 9600,
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
            # Продолжать прогон, прерванный перезапуском программы, когда вернётся связь.
            "auto_resume": True,
            # Сводка в Telegram раз в столько минут, 0 - не присылать.
            "report_every_min": 60.0,
            # Плата дальше от воздуха камеры, чем на столько, - проблема установки или датчика, °C.
            "board_gap_c": 10.0,
            # Журнал диагностики: каждый обмен байтами в файл (иначе - только вокруг ошибок).
            "diag_verbose": False,
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
            if key == "espec_delimiter":
                value = str(value).upper()
                if value not in ("CRLF", "CR", "LF"):
                    return False
            if key == "espec_address" and not (1 <= int(value) <= 16):
                self._climate_command_status = "Адрес камеры ESPEC - от 1 до 16, как в меню её пульта."
                self.climateChanged.emit()
                return False
            if settings[key] == value:
                return True
            self._climate_diag_event("SET", f"{key}: {settings[key]} → {value}")
            if getattr(self, "_control_log", None) is not None:
                # Пределы уставки и правила прогона влияют на камеру: смена записывается с именем оператора.
                self._control_note("настройка камеры", f"{key}: {settings[key]} → {value}", True)
            settings[key] = value
            if key == "diag_verbose" and getattr(self, "_climate_diag", None) is not None:
                self._climate_diag.verbose = bool(value)
            reconnect = key in ("driver", "poll_s", "unit", "tcp_host", "tcp_port", "rtu_port", "rtu_baud",
                                "rtu_parity", "rtu_stopbits", "sim_speed", "simcon_address",
                                "espec_port", "espec_baud", "espec_address", "espec_delimiter",
                                "weiss_port", "weiss_baud")
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
        diag = getattr(self, "_climate_diag", None)
        if diag is not None:
            diag.session_start(driver.title, self._climate_session_info())
        self._climate_link = ChamberLink(driver, float(self._climate_settings["poll_s"]), self._climate_queue_state,
                                         diag=diag)
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
        if self._climate_scan_active:
            self._climate_scan_active = False
            self._climate_scan_status = "Поиск камеры прерван."
        if getattr(self, "_climate_selftest", {}).get("active"):
            self._climate_selftest = {"active": False, "text": "Проверка связи прервана.", "results": []}
        if link is not None and not quiet:
            self._climate_diag_event("LINK", "отключено оператором")
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
                sent, answer = str(state.get("sent", "")), str(state.get("text", ""))
                explain = ""
                if state.get("ok") and self._climate_settings["driver"] == DRIVER_ESPEC:
                    explain = describe_espec_answer(sent, answer)
                self._climate_raw_log.appendleft({
                    "time": time.strftime("%H:%M:%S"),
                    "sent": sent,
                    "answer": answer,
                    "explain": explain,
                    "ok": bool(state.get("ok")),
                })
            elif state.get("kind") == "scan":
                self._climate_take_scan(state)
            elif state.get("kind") == "selftest":
                self._climate_take_selftest(state)
            elif state.get("kind") == "reading":
                self._climate_status = f"Нет связи с камерой: {state.get('text')}. Повторяю..."
                self._climate_ok = False
            else:
                self._climate_command_status = ("Камера: " if state.get("ok") else "Камера не выполнила: ") + \
                    str(state.get("text"))
                if not state.get("ok"):
                    self._climate_event(f"камера не выполнила команду: {state.get('text')}.", "bad")
        return bool(incoming)

    def _climate_take_scan(self, state: dict):
        """Ход и итог поиска камеры. Найденные настройки сохраняются без переподключения: связь уже на них."""
        self._climate_scan_status = str(state.get("text", ""))
        if not state.get("done"):
            return
        self._climate_scan_active = False
        found = state.get("found")
        if state.get("ok") and found:
            settings = self._climate_settings
            settings["espec_baud"] = int(found["baud"])
            settings["espec_address"] = int(found["address"])
            settings["espec_delimiter"] = str(found["delimiter"])
            self._climate_save_settings()
            self._climate_scan_status = (f"Камера найдена: адрес {found['address']}, {found['baud']} бод, конец строки "
                                         f"{found['delimiter']}. Настройки сохранены. Прошивка: {found.get('rom', '')}")
            self._climate_event(f"камера ESPEC найдена: адрес {found['address']}, {found['baud']} бод.", "ok")
        elif not state.get("ok"):
            self._climate_scan_status = f"Камера не найдена: {state.get('text')}."

    def _climate_fresh(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self._climate_reading is not None and now - self._climate_last_ok_s <= self.CLIMATE_STALE_S

    def _climate_watch_alarm(self):
        alarm = getattr(self._climate_reading, "alarm", None)
        if alarm and alarm != self._climate_alarm_reported:
            self._climate_event(f"АВАРИЯ КАМЕРЫ: код {alarm}. Проверьте камеру.", "bad")
        self._climate_alarm_reported = alarm or 0

    def _climate_event(self, text: str, level: str = "info", kind: str = "event"):
        """Событие камеры: в журнал программы, наблюдению издалека и в журнал диагностики камеры.

        kind «summary» - сводка по расписанию: бот пришлёт её только тем, у кого включены сводки.
        """
        self._climate_diag_event("EVENT", str(text), {"bad": "ERROR", "warn": "WARN"}.get(level, "INFO"))
        handler = getattr(self, "_remote_event", None)
        if handler is not None:
            handler(text, level, kind=kind)

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
        if self._climate_settings["driver"] == DRIVER_ESPEC:
            head, _, rest = line.partition(",")
            command = rest.strip() if rest and head.strip().isdigit() else line
            if espec_is_setting(command) and not self._climate_manual_allowed():
                return False
            self._climate_link.command("raw", line)
            self._climate_command_status = f"Отправляю «{line}»..."
        else:
            self._climate_link.command("raw", line)
            self._climate_command_status = f"Отправляю «{line}»: ответ придёт не раньше чем через 5 с после прошлой строки."
        self.climateChanged.emit()
        return True

    def _climate_manual_allowed(self) -> bool:
        """Можно ли оператору менять настройки камеры: во время прогона камерой управляет программа."""
        if self._climate_run_stage and not self._climate_run_paused:
            self._climate_command_status = ("Идёт автоматический прогон: камерой управляет программа. "
                                            "Поставьте прогон на паузу или остановите его.")
            self._climate_diag_event("CMD", "ручная команда не отправлена: идёт автоматический прогон", "WARN")
            self.climateChanged.emit()
            return False
        return True

    def _climate_send_espec(self, key: str, values_json: str = "") -> bool:
        """Команда камере ESPEC из каталога: кнопки ручного управления и список команд окна.

        Параметры приходят из окна строкой JSON. Строку команды собирает и
        проверяет драйвер, уставки дополнительно сверяются с пределами из настроек.
        """
        if self._climate_settings["driver"] != DRIVER_ESPEC or self._climate_link is None:
            self._climate_command_status = "Сначала подключите камеру ESPEC."
            self.climateChanged.emit()
            return False
        try:
            values = json.loads(values_json) if str(values_json).strip() else {}
        except ValueError:
            values = {}
        if not isinstance(values, dict):
            values = {}
        try:
            command = build_espec_command(str(key), values)
        except ChamberError as error:
            self._climate_command_status = f"Команда не отправлена: {error}."
            self._climate_diag_event("CMD", f"«{key}» не отправлена: {error}; параметры {values}", "WARN")
            self.climateChanged.emit()
            return False
        if espec_is_setting(command):
            if not self._climate_manual_allowed():
                return False
            item = ESPEC_COMMANDS_BY_KEY[str(key)]
            low, high = float(self._climate_settings["min_c"]), float(self._climate_settings["max_c"])
            for param in item.get("params", []):
                if param["name"] not in ("temp", "start", "end"):
                    continue
                value = float(str(values.get(param["name"], param.get("default"))).replace(",", "."))
                if not (low <= value <= high):
                    self._climate_command_status = (f"«{param['label']}» вне допустимых пределов "
                                                    f"{low:+.0f}...{high:+.0f} °C (пределы уставки в настройках).")
                    self._climate_diag_event("CMD", f"«{command}» не отправлена: {self._climate_command_status}", "WARN")
                    self.climateChanged.emit()
                    return False
        self._climate_link.command("raw", command)
        self._climate_command_status = f"Отправляю «{command}»..."
        self.climateChanged.emit()
        return True

    def _climate_refresh_ports(self):
        """Обновляет список COM-портов и режим портов Moxa из реестра: переходник Moxa UPort первым."""
        try:
            self._climate_ports = list_serial_ports()
        except Exception:  # noqa: BLE001
            self._climate_ports = []
        try:
            self._climate_moxa = moxa_registry_info()
        except Exception:  # noqa: BLE001
            self._climate_moxa = []
        self._climate_diag_event("PORTS", f"порты: {self._climate_ports}; Moxa в реестре: "
                                          f"{[(item['port'], item['interface']) for item in self._climate_moxa]}")
        self.climateChanged.emit()

    # ------------------------------------------------------------------ диагностика

    def _climate_session_info(self) -> dict:
        """Всё об окружении и настройках для начала сеанса в журнале и для отчёта."""
        root = getattr(self, "_project_root_directory", None)
        return {
            "окружение": environment_info(pathlib.Path(root) if root else None),
            "настройки": {key: value for key, value in self._climate_settings.items() if key != "map"},
            "COM-порты": self._climate_ports,
            "Moxa в реестре": [{key: item[key] for key in ("port", "interface", "interface_code", "values")}
                               for item in self._climate_moxa],
        }

    def _climate_moxa_check(self) -> dict:
        """Режим порта Moxa, который выбран для ESPEC: годится ли он для четырёх проводов."""
        if self._climate_settings["driver"] != DRIVER_ESPEC or not self._climate_moxa:
            return {"text": "", "ok": True}
        link = self._climate_link
        port = str(getattr(link.driver, "port", "")) if link is not None else ""
        if not port or port.lower() == PORT_AUTO:
            try:
                port = resolve_port(self._climate_settings["espec_port"], lambda: [])
            except ChamberError:
                port = ""
            if not port or port.lower() == PORT_AUTO:
                moxa = [item["device"] for item in self._climate_ports if item.get("moxa")]
                port = moxa[0] if moxa else ""
        if not port:
            # Переходник есть только в реестре: Windows его помнит, но сейчас он не вставлен.
            known = ", ".join(f"{entry['port']} ({entry['interface']})" for entry in self._climate_moxa)
            return {"text": f"Moxa UPort сейчас не подключён к USB. Windows помнит его как {known}.", "ok": False}
        item = next((entry for entry in self._climate_moxa if entry["port"].upper() == port.upper()), None)
        if item is None:
            return {"text": "", "ok": True}
        if item["espec_ok"]:
            return {"text": f"Moxa {item['port']}: режим {item['interface']} (код {item['interface_code']}) - подходит "
                            f"для камеры ESPEC.", "ok": True}
        return {"text": f"Moxa {item['port']}: режим {item['interface']} (код {item['interface_code']}) - камере ESPEC "
                        f"нужен RS-422 или RS-485 4W. Переключите в диспетчере устройств: свойства порта Moxa.",
                "ok": False}

    def _climate_selftest_start(self) -> bool:
        """Проверка связи: набор запросов к камере с ответом, задержкой и итогом по каждому."""
        if self._climate_link is None:
            self._climate_selftest = {"active": False, "text": "Сначала подключите камеру.", "results": []}
            self.climateChanged.emit()
            return False
        self._climate_link.command("selftest")
        self._climate_selftest = {"active": True, "text": "Проверяю связь: запросы идут по очереди...", "results": []}
        self.climateChanged.emit()
        return True

    def _climate_take_selftest(self, state: dict):
        """Итог проверки связи для окна: по каждому запросу ответ и его смысл словами."""
        results = []
        for item in state.get("results") or []:
            explain = ""
            if item.get("ok") and self._climate_settings["driver"] == DRIVER_ESPEC:
                explain = describe_espec_answer(item["query"], item["answer"])
            results.append({**item, "explain": explain})
        text = str(state.get("text", ""))
        if not state.get("results") and not state.get("ok"):
            text = f"проверка не выполнена: {text}"
        self._climate_selftest = {"active": False, "text": text[:1].upper() + text[1:] + ".", "results": results}

    def _climate_report_sections(self) -> dict:
        """Разделы отчёта диагностики: всё, что нужно, чтобы разобрать проблему без доступа к компьютеру."""
        link = self._climate_link
        reading = self._climate_reading
        info = self._climate_session_info()
        return {
            "Программа и окружение": info["окружение"],
            "Настройки камеры": info["настройки"],
            "Выбранная камера": self._climate_chamber_card(),
            "Состояние связи": {
                "подключена": link is not None,
                "связь есть": bool(self._climate_ok),
                "драйвер": getattr(link.driver, "title", "") if link is not None else "",
                "порт": getattr(link.driver, "port", "") if link is not None else "",
                "состояние": self._climate_status,
                "последняя команда": self._climate_command_status,
                "поиск камеры": self._climate_scan_status,
                "проверка режима Moxa": self._climate_moxa_check().get("text", ""),
            },
            "Последнее показание камеры": {
                "текстом": reading_text(reading),
                "подробности": getattr(reading, "details", None),
            },
            "COM-порты": info["COM-порты"],
            "Moxa в реестре Windows": info["Moxa в реестре"],
            "Проверка связи (последняя)": self._climate_selftest,
            "Команды из окна и ответы камеры": [f"{item['time']} {item['sent']} → {item['answer']}"
                                                f"{'  (' + item.get('explain', '') + ')' if item.get('explain') else ''}"
                                                f"{'' if item['ok'] else '  [ОШИБКА]'}"
                                                for item in list(self._climate_raw_log)],
            "Автоматический прогон": {"этап": self._climate_run_stage, "состояние": self._climate_run_status},
        }

    def _climate_save_report(self) -> str:
        """Сохраняет отчёт диагностики в logs/chamber и возвращает путь к нему."""
        diag = getattr(self, "_climate_diag", None)
        if diag is None:
            return ""
        try:
            path = diag.save_report(self._climate_report_sections())
        except OSError as error:
            self._climate_command_status = f"Отчёт не сохранился: {error}"
            self.climateChanged.emit()
            return ""
        self._climate_command_status = f"Отчёт диагностики сохранён: {path}"
        self.climateChanged.emit()
        return "" if path is None else str(path)

    def _climate_espec_scan(self) -> bool:
        """Поиск адреса, скорости и конца строки камеры ESPEC: настройки пульта угадывать не нужно."""
        if self._climate_settings["driver"] != DRIVER_ESPEC:
            return False
        if self._climate_run_stage:
            self._climate_scan_status = "Во время автоматического прогона камеру не ищут."
            self.climateChanged.emit()
            return False
        if self._climate_link is None and not self._climate_connect():
            return False
        self._climate_link.command("scan")
        self._climate_scan_active = True
        self._climate_scan_status = "Ищу камеру: адреса 1...16, скорости 9600, 19200 и 4800. Это до минуты."
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
        if self._climate_hook("_climate_auto_tick", now) is not None or getattr(self, "_climate_auto_finishing", False):
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
        """Температура платы из прибора для правила «устоялась» - среднее за окно усреднения.

        Одиночное показание датчика скачет на ±0,1...0,2 °C (шаг 0,1 и шум): по таким
        точкам разброс за 5 минут не опускается ниже 0,3 °C, и плата «не устаивается»
        никогда, хотя стоит. Среднее за окно - то же, по чему судит наблюдение и
        снимается точка.
        """
        if now - self._climate_last_board_s < self.CLIMATE_BOARD_STEP_S:
            return
        self._climate_last_board_s = now
        if not self._chamber_live_fresh("board_temp", now):
            return
        stats = self._chamber_live_stats("board_temp", now)
        value = stats["mean"] if stats is not None else int(self._chamber_live_last["board_temp"])
        self._climate_board.append((now, round(float(value) / 10.0, 3)))

    def _climate_board_mean(self, now: float, span_s: float) -> float:
        """Средняя температура платы за последние span_s секунд (по средним за окно усреднения)."""
        values = [value for stamp, value in self._climate_board if now - stamp <= span_s]
        return round(sum(values) / len(values), 2) if values else self._climate_board[-1][1]

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

    def _climate_hook(self, name: str, *args):
        """Точка входа автономного прогона: вызывает его, если он подключён к контроллеру."""
        handler = getattr(self, name, None)
        return handler(*args) if handler is not None else None

    def _climate_run_plan(self) -> dict:
        """Что пройдёт прогон: шаги сценария, а без сценария - температуры из настроек.

        Возвращает {"steps", "nodes", "labels"}. ValueError - список температур не разобрался.
        """
        scenario = getattr(self, "_climate_scenario", None)
        if scenario:
            steps = [dict(step) for step in scenario.get("steps") or []]
            labels = list(scenario.get("labels") or [])
        else:
            steps = [{"temp": node} for node in parse_nodes(self._climate_settings["run_nodes"])]
            labels = parse_labels(self._climate_settings["run_labels"])
        label = str(getattr(self, "_chamber_label", "")).strip()
        return {"steps": steps, "nodes": [float(step["temp"]) for step in steps],
                "labels": labels or ([label] if label else [])}

    def _climate_run_step(self) -> dict:
        steps = self._climate_run_steps
        return steps[self._climate_run_index] if 0 <= self._climate_run_index < len(steps) else {}

    def _climate_run_param(self, key: str) -> float:
        """Параметр текущего шага: свой у шага, иначе общий сценария, иначе из настроек прогона."""
        value = self._climate_run_step().get(key)
        if value is None:
            scenario = getattr(self, "_climate_scenario", None)
            if scenario and scenario.get(key) is not None:
                value = scenario[key]
            else:
                value = self._climate_settings.get(key, SCENARIO_DEFAULTS.get(key, 0.0))
        return float(value)

    # Шкала датчика платы в приборе (прошивка, ntc_table.h): за краями показание упирается в предел.
    # С расширенными таблицами NTC это -55...+125 C, и узлы -40 и +85 лежат внутри шкалы.
    # В прошивке до расширения шкала была -40...+85: такие приборы перед прогоном перепрошить.
    BOARD_SENSOR_RANGE_C = (-55.0, 125.0)
    # Цель у края шкалы - внутрь на столько: показание ровно на пределе не отличить от упора.
    BOARD_SENSOR_MARGIN_C = 0.5
    # Шаг сдвига уставки при упоре датчика в предел, если модели «воздух → плата» ещё нет.
    BOARD_CLAMP_STEP_C = 3.0

    def _climate_run_reset_board(self):
        """Новый шаг: доводки ещё не было, уставка камеры - температура шага."""
        self._climate_run_offset = 0.0
        self._climate_run_board_attempts = 0
        self._climate_run_board_since = 0.0
        self._climate_run_board_preset_done = False
        self._climate_run_quiet_since = None

    def _climate_board_clamped(self, value) -> bool:
        """Показание платы на пределе шкалы датчика: настоящая температура может быть за ним."""
        low, high = self.BOARD_SENSOR_RANGE_C
        return value is not None and (float(value) <= low + 0.05 or float(value) >= high - 0.05)

    def _climate_run_board_target(self, node: float) -> float:
        """Куда вести плату: температура шага, а у края шкалы датчика (-55, +125) - чуть внутрь.

        Иначе плату, ушедшую за край, датчик покажет ровно на пределе, и это сочтётся попаданием.
        """
        low, high = self.BOARD_SENSOR_RANGE_C
        return min(max(float(node), low + self.BOARD_SENSOR_MARGIN_C), high - self.BOARD_SENSOR_MARGIN_C)

    def _climate_run_target_text(self, node: float, target: float) -> str:
        return "" if abs(target - node) < 0.05 else f", у края шкалы датчика цель {_c(target)}"

    def _climate_run_note_pair(self, board: float):
        """Где плата при этой уставке камеры (замер или прогноз): пара для модели «воздух → плата».

        На одну попытку шага - одна пара, последняя: прогноз уточняется, потом его сменяет замер.
        Показание на пределе шкалы датчика в модель не идёт: настоящей температуры оно не говорит.
        """
        if self._climate_board_clamped(board):
            return
        key = (int(self._climate_run_index), int(self._climate_run_board_attempts))
        pairs = [pair for pair in self._climate_run_board_pairs if (pair["step"], pair["attempt"]) != key]
        pairs.append({"step": key[0], "attempt": key[1], "air": round(self._climate_run_setpoint(), 2),
                      "board": round(float(board), 2)})
        self._climate_run_board_pairs = pairs[-40:]

    def _climate_run_board_model(self, near: float | None = None):
        """Модель «плата ≈ k × воздух + b» по парам этого прогона около температуры near или None."""
        if near is None and 0 <= self._climate_run_index < len(self._climate_run_nodes):
            near = self._climate_run_board_target(self._climate_run_node())
        return fit_board_model([(pair["air"], pair["board"]) for pair in self._climate_run_board_pairs], near=near)

    def _climate_run_board_model_text(self) -> str:
        model = self._climate_run_board_model()
        if model is None:
            return ""
        gain, offset, count = model
        return (f"плата ≈ {gain:.2f} × воздух {offset:+.1f} °C по {count} "
                f"{'точке' if count == 1 else 'точкам'}").replace(".", ",")

    def _climate_run_wanted_offset(self, node: float, target: float, fallback: float) -> float:
        """Сдвиг уставки, при котором плата придёт к цели: по модели, а без неё - fallback."""
        model = self._climate_run_board_model(target)
        return air_for_board(model, target) - node if model is not None else fallback

    def _climate_run_clamp_offset(self, node: float, offset: float) -> float:
        """Сдвиг в пределах «сдвигать уставку до» и пределов уставки камеры."""
        max_shift = self._climate_run_param("board_max_shift_c")
        low, high = float(self._climate_settings["min_c"]), float(self._climate_settings["max_c"])
        offset = max(-max_shift, min(max_shift, offset))
        return round(max(low, min(high, node + offset)) - node, 1)

    def _climate_run_board_preset(self):
        """Упреждение: новый шаг сразу с поправленной уставкой - по опыту прошлых шагов этого прогона.

        Плата отстаёт от воздуха одинаково от шага к шагу (самонагрев, утечка тепла по
        кабелю), поэтому модель «воздух → плата» с прошлых шагов говорит, какой воздух
        нужен сейчас. Так доводка почти не нужна, а шаг короче на часы. Шаг без точки -
        как задан.
        """
        if self._climate_run_board_preset_done:
            return
        self._climate_run_board_preset_done = True
        if self._climate_run_offset or self._climate_run_board_attempts:
            return
        if not bool(self._climate_run_step().get("capture", True)) or self._climate_run_param("board_max_shift_c") <= 0:
            return
        model = self._climate_run_board_model()
        if model is None:
            return
        node = self._climate_run_node()
        target = self._climate_run_board_target(node)
        # Плата и без поправки придёт к цели в пределах допуска - уставку не трогаем: поправка на шум не нужна.
        gain, base, _count = model
        if abs(gain * node + base - target) <= self._climate_run_param("board_tolerance_c"):
            return
        offset = self._climate_run_clamp_offset(node, air_for_board(model, target) - node)
        if abs(offset) < 0.3:
            return
        self._climate_run_offset = offset
        text = (f"упреждение по прошлым шагам ({self._climate_run_board_model_text()}): уставка камеры сразу "
                f"{_c(self._climate_run_setpoint())} вместо {_c(node)}, чтобы плата пришла к {_c(target)}.")
        self._climate_event(text, "info")
        self._climate_run_board_note(f"шаг {self._climate_run_index + 1} ({_c(node)})", True, text,
                                     "упреждение уставки")

    def _climate_run_setpoint(self) -> float:
        """Уставка камеры на этом шаге: температура шага плюс сдвиг доводки платы."""
        return self._climate_run_node() + self._climate_run_offset

    def _climate_run_board_note(self, details: str, ok: bool, result: str, title: str = "доводка платы"):
        """Доводка платы и упреждение - в журнал действий: их делает программа, но меняют уставку камеры."""
        log = getattr(self, "_control_log", None)
        if log is not None:
            log.add("программа (автопрогон)", "автопрогон", title, details, ok, result)

    # Прогноз предела платы: не раньше чем через столько минут устаивания, и сверка с прогнозом 5 минут назад.
    CLIMATE_FORECAST_MIN_S = 20 * 60.0
    CLIMATE_FORECAST_CHECK_S = 5 * 60.0
    CLIMATE_FORECAST_AGREE_C = 0.5

    def _climate_run_board_forecast(self, now: float) -> float | None:
        """Где устоится плата на этом шаге (°C) или None, если прогнозу пока нельзя верить.

        Данные - с начала устаивания (камера уже на уставке, плата подходит к своему
        пределу по экспоненте). Прогноз считается дважды: по всем данным и по данным
        5 минут назад; если они расходятся больше чем на 0,5 °C - кривая ещё не
        ясна, прогноза нет.
        """
        speed = self._climate_speed()
        start = self._climate_run_since
        if now - start < self.CLIMATE_FORECAST_MIN_S / speed:
            return None
        samples = list(self._climate_board)
        max_tau = 600 * 60.0 / speed
        latest = predict_final(samples, start, now, max_tau_s=max_tau)
        earlier = predict_final(samples, start, now - self.CLIMATE_FORECAST_CHECK_S / speed, max_tau_s=max_tau)
        if latest is None or earlier is None or abs(latest[0] - earlier[0]) > self.CLIMATE_FORECAST_AGREE_C:
            return None
        return round(latest[0], 2)

    def _climate_run_board_early(self, now: float, final: float) -> bool:
        """Прогноз говорит, что плата не дойдёт до цели: доводка сразу, не дожидаясь её устаивания.

        Только для шага с точкой, пока есть попытки и куда двигать уставку. True - уставка сдвинута.
        """
        node = self._climate_run_node()
        target = self._climate_run_board_target(node)
        if not bool(self._climate_run_step().get("capture", True)):
            return False
        board = self._climate_board[-1][1] if self._climate_board else final
        # Показание на пределе шкалы - прогноз по нему не настоящий: решит проверка при устаивании.
        if self._climate_board_clamped(board):
            return False
        tolerance = self._climate_run_param("board_tolerance_c")
        if abs(target - final) <= tolerance:
            return False
        attempts = int(round(self._climate_run_param("board_attempts")))
        if self._climate_run_board_attempts >= attempts or self._climate_run_param("board_max_shift_c") <= 0:
            return False
        self._climate_run_note_pair(final)
        wanted = self._climate_run_wanted_offset(node, target, self._climate_run_offset + (target - final))
        return self._climate_run_board_shift(now, node, target, wanted,
                                             f"плата сейчас {_c(board)} и по прогнозу устоится при {_c(final)}")

    def _climate_run_board_shift(self, now: float, node: float, target: float, wanted: float, measured: str) -> bool:
        """Сдвиг уставки камеры на wanted (от температуры шага), чтобы плата пришла к цели. True - сдвинута.

        В пределах «сдвигать уставку до» и пределов уставки камеры.
        """
        attempts = int(round(self._climate_run_param("board_attempts")))
        tolerance = self._climate_run_param("board_tolerance_c")
        offset = self._climate_run_clamp_offset(node, wanted)
        if abs(offset - self._climate_run_offset) < 0.1:
            return False
        before = self._climate_run_setpoint()
        self._climate_run_board_attempts += 1
        self._climate_run_offset = offset
        self._climate_run_board_since = now
        self._climate_run_quiet_since = None
        model = self._climate_run_board_model_text()
        text = (f"{measured}, а шаг {_c(node)} (допуск ±{tolerance:g} °C{self._climate_run_target_text(node, target)}): "
                f"довожу - уставка камеры {_c(before)} → {_c(self._climate_run_setpoint())}, попытка "
                f"{self._climate_run_board_attempts} из {attempts}" + (f" ({model})" if model else "") + ".")
        self._climate_event(text, "warn")
        self._climate_run_board_note(f"шаг {self._climate_run_index + 1} ({_c(node)})", True, text)
        self._climate_run_enter("setpoint", now)
        return True

    def _climate_run_board_ok(self, now: float, board: float | None, final: float | None = None):
        """Доводка платы: плата должна устояться у температуры шага в пределах допуска.

        Плата греется сама, её тянет к комнате, и устаивается она не там, где воздух.
        Если она устоялась дальше допуска, уставка камеры сдвигается (по модели
        «воздух → плата», не дальше предела сдвига и пределов уставки) и прогон снова
        ждёт камеру и плату. Если датчик платы упёрся в предел шкалы (-55 или +125),
        настоящая температура за пределом - уставка сдвигается внутрь шкалы. Не вышло за
        заданное число попыток - предупреждение в события и журнал, и точка снимается
        при текущих условиях. Шаг без точки не доводится.

        final - прогноз, где плата устоится (None - прогноза нет). Возвращает True - можно
        идти к выдержке и точкам, False - уставка сдвинута, None - плата ещё идёт к цели
        и по прогнозу дойдёт: ждать.
        """
        node = self._climate_run_node()
        target = self._climate_run_board_target(node)
        if board is not None:
            # Где плата при этой уставке - опыт для модели, даже на шаге без точки.
            self._climate_run_note_pair(final if final is not None else board)
        if board is None or not bool(self._climate_run_step().get("capture", True)):
            return True
        tolerance = self._climate_run_param("board_tolerance_c")
        where = f"шаг {self._climate_run_index + 1} ({_c(node)})"
        clamped = self._climate_board_clamped(board)
        if not clamped:
            if abs(target - float(board)) > tolerance and final is not None and abs(target - final) <= tolerance:
                return None
            if abs(target - float(board)) <= tolerance:
                if self._climate_run_board_attempts:
                    text = (f"плата дошла до шага: {_c(board)} при {_c(node)} (допуск ±{tolerance:g} °C"
                            f"{self._climate_run_target_text(node, target)}), уставка камеры {_c(self._climate_run_setpoint())}.")
                    self._climate_event(text, "ok")
                    self._climate_run_board_note(where, True, text)
                return True
            # Промах - по пределу платы, если он известен: текущее значение у инертной платы ещё не конец.
            value = final if final is not None else float(board)
            wanted = self._climate_run_wanted_offset(node, target, self._climate_run_offset + (target - value))
            measured = f"плата устоялась при {_c(board)}" + (
                f" и по прогнозу придёт к {_c(final)}" if final is not None and abs(final - float(board)) >= 0.1 else "")
        else:
            # Упор в предел шкалы: насколько плата за краем, неизвестно - сдвиг внутрь не меньше шага.
            inward = -1.0 if float(board) >= self.BOARD_SENSOR_RANGE_C[1] - 0.05 else 1.0
            step = self._climate_run_offset + inward * self.BOARD_CLAMP_STEP_C
            model = self._climate_run_wanted_offset(node, target, step)
            wanted = min(model, step) if inward < 0 else max(model, step)
            measured = f"датчик платы упёрся в предел шкалы ({_c(board)}): настоящая температура за ним"
        attempts = int(round(self._climate_run_param("board_attempts")))
        max_shift = self._climate_run_param("board_max_shift_c")
        low, high = float(self._climate_settings["min_c"]), float(self._climate_settings["max_c"])
        reason = f"попыток доводки было {self._climate_run_board_attempts} из {attempts}"
        if self._climate_run_board_attempts < attempts and max_shift > 0:
            if self._climate_run_board_shift(now, node, target, wanted, measured):
                return False
            shift = f"{self._climate_run_offset:+g}".replace(".", ",")
            reason = (f"уставку двигать некуда: сдвиг уже {shift} °C при пределе ±{max_shift:g} °C "
                      f"и пределах уставки {low:+.0f}...{high:+.0f} °C")
        clamp_note = " Датчик платы на пределе шкалы: точка недостоверна." if clamped else ""
        text = (f"плата не дошла до шага {_c(node)}: устоялась при {_c(board)} (допуск ±{tolerance:g} °C"
                f"{self._climate_run_target_text(node, target)}), {reason}. Точка снимается при текущих условиях, "
                f"прогон идёт дальше.{clamp_note}")
        alert = getattr(self, "_climate_auto_alert", None)
        if alert is not None:
            alert("board_miss", True, text, "warn")
        else:
            self._climate_event(text, "warn")
        self._climate_run_board_note(where, False, text)
        return True

    # Журнал хода прогона: строка раз в столько секунд.
    CLIMATE_TRACE_S = 10.0
    TRACE_COLUMNS = ("Время", "Шаг", "Температура шага (°C)", "Этап", "Уставка камеры (°C)", "Воздух камеры (°C)",
                     "Плата (°C)", "Топливо (°C)", "Основной контур", "Контур вида топлива", "Сдвиг доводки (°C)",
                     "Попытка доводки", "Пауза")

    def _climate_run_trace(self, now: float):
        """Ход прогона по времени в CSV рядом с журналом точек: по нему потом разбирают, что было.

        Раз в 10 с: шаг, этап, уставка и воздух камеры, плата и топливо (средние за окно),
        оба контура, сдвиг и попытка доводки. Файл - logs/chamber/run_ГГГГММДД_ЧЧММСС.csv.
        """
        if now - (getattr(self, "_climate_trace_last_s", None) or 0.0) < self.CLIMATE_TRACE_S / self._climate_speed():
            return
        self._climate_trace_last_s = now
        path = getattr(self, "_climate_trace_path", None)
        if path is None:
            return
        reading = self._climate_reading if self._climate_fresh(now) else None

        def live(key, scale=1.0):
            stats = self._chamber_live_stats(key, time.monotonic()) if self._chamber_live_fresh(key, time.monotonic()) else None
            return "" if stats is None else f"{stats['mean'] / scale:.2f}".replace(".", ",")

        def number(value):
            return "" if value is None else f"{float(value):.2f}".replace(".", ",")

        index = self._climate_run_index
        node = self._climate_run_nodes[index] if 0 <= index < len(self._climate_run_nodes) else None
        row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(index + 1), number(node), self._climate_run_stage,
               number(getattr(reading, "setpoint_c", None)), number(getattr(reading, "actual_c", None)),
               live("board_temp", 10.0), live("fuel_temp", 10.0), live("main"), live("media"),
               number(self._climate_run_offset), str(self._climate_run_board_attempts),
               "да" if self._climate_run_paused else ""]
        try:
            new = not path.exists()
            with path.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                if new:
                    writer.writerow(self.TRACE_COLUMNS)
                writer.writerow(row)
        except OSError:
            pass

    def _climate_run_set(self, text: str, color: str = "#0f6ab4"):
        self._climate_run_status = str(text)
        self._climate_run_color = str(color)

    def _climate_run_start(self) -> bool:
        """Запускает прогон по списку узлов из настроек."""
        if self._climate_run_stage:
            return False
        # Режим расчёта, пометка и автозапись берутся из сценария: проверка перед стартом видит их уже такими.
        self._climate_hook("_climate_scenario_apply_chamber")
        blockers = self._climate_hook("_climate_auto_blockers") or []
        if blockers:
            self._climate_run_set("Прогон не запущен: " + blockers[0][:1].lower() + blockers[0][1:] + ".", "#dc2626")
            self.climateChanged.emit()
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
            plan = self._climate_run_plan()
        except ValueError:
            self._climate_run_set("Прогон не запущен: список температур не разобрался.", "#dc2626")
            self.climateChanged.emit()
            return False
        nodes = plan["nodes"]
        low, high = float(self._climate_settings["min_c"]), float(self._climate_settings["max_c"])
        if not nodes or any(not (low <= node <= high) for node in nodes):
            self._climate_run_set(f"Прогон не запущен: температуры должны быть от {low:+.0f} до {high:+.0f} °C.",
                                  "#dc2626")
            self.climateChanged.emit()
            return False
        labels = plan["labels"] or [""]
        if not labels[0]:
            self._climate_run_set("Прогон не запущен: напишите, что подключено к прибору, или список пометок.",
                                  "#dc2626")
            self.climateChanged.emit()
            return False

        self._climate_run_reset()
        try:
            folder = self._climate_logs_directory()
            folder.mkdir(parents=True, exist_ok=True)
            self._climate_trace_path = folder / f"run_{datetime.now():%Y%m%d_%H%M%S}.csv"
        except OSError:
            self._climate_trace_path = None
        self._climate_run_nodes = nodes
        self._climate_run_steps = plan["steps"]
        self._climate_run_labels = labels
        self._climate_run_connected = str(self._chamber_label).strip()
        self._climate_run_stage = "setpoint"
        self._climate_event(
            f"автоматический прогон начат: {len(nodes)} температур ({', '.join(_c(node) for node in nodes)}), "
            f"пометки {', '.join(labels)}.", "info")
        started = time.monotonic()
        self._climate_hook("_climate_auto_on_start", started)
        self._climate_run_tick(started)
        self.climateChanged.emit()
        return True

    def _climate_run_stop(self, reason: str = "остановлен оператором"):
        if not self._climate_run_stage:
            return
        self._climate_run_stage = ""
        self._climate_run_set(f"Автоматический прогон {reason}. Уставка камеры оставлена как есть.", "#d97706")
        self._climate_event(f"автоматический прогон {reason}.", "warn")
        self._climate_hook("_climate_auto_on_stop", reason)
        self.climateChanged.emit()

    def _climate_run_pause(self, paused: bool):
        if not self._climate_run_stage:
            return
        self._climate_run_paused = bool(paused)
        if not paused:
            # Оператор сам продолжил: пауза из-за беды снята.
            self._climate_auto_paused_by = ""
        self._climate_event("прогон поставлен на паузу оператором." if paused else "прогон продолжен оператором.",
                            "info")
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
        self._climate_hook("_climate_auto_on_stage", stage, now)

    def _climate_run_tick(self, now: float):
        """Шаг прогона. Каждый этап ждёт своего условия и переходит к следующему."""
        if self._climate_run_paused:
            self._climate_run_set("Прогон на паузе. Нажмите «Продолжить прогон».", "#d97706")
            return
        stage = self._climate_run_stage
        self._climate_run_trace(now)
        if stage == "finish":
            self._climate_run_finish_tick(now)
            return
        node = self._climate_run_node()
        where = f"{self._climate_run_index + 1} из {len(self._climate_run_nodes)}, {_c(node)}"

        if stage == "setpoint":
            self._climate_run_board_preset()
            setpoint = self._climate_run_setpoint()
            if self._climate_send_setpoint(setpoint):
                if self._climate_link.driver.can_run and not getattr(self._climate_reading, "running", True):
                    self._climate_send_run(True)
                self._climate_run_enter("reach", now)
                shifted = f" (доводка платы: уставка {_c(setpoint)})" if self._climate_run_offset else ""
                self._climate_run_set(f"Узел {where}: уставка задана, камера идёт к ней{shifted}.")
            else:
                self._climate_run_stop(f"остановлен: {self._climate_command_status}")
            return

        if stage == "reach":
            actual = getattr(self._climate_reading, "actual_c", None) if self._climate_fresh(now) else None
            tolerance = self._climate_run_param("reach_tolerance_c")
            setpoint = self._climate_run_setpoint()
            if actual is not None and abs(actual - setpoint) <= tolerance:
                self._climate_event(f"камера вышла на {_c(setpoint)}, жду, пока устоится плата.", "info")
                self._climate_run_enter("settle", now)
                return
            self._climate_run_set(f"Узел {where}: камера идёт к уставке {_c(setpoint)}, сейчас {_c(actual)}.")
            self._climate_run_timeout(now, "reach_timeout_min", f"камера не вышла на {_c(setpoint)}")
            return

        if stage == "settle":
            speed = self._climate_speed()
            window_s = self._climate_run_param("settle_min") * 60.0 / speed
            rate_limit = self._climate_run_param("settle_rate") * speed
            result = rate_and_spread(self._climate_board, now, window_s)
            # Где устоится плата: у инертной платы правило скорости срабатывает за градусы до её предела.
            final = self._climate_run_board_forecast(now)
            if final is not None and self._climate_run_board_early(now, final):
                return
            # После сдвига уставки доводкой плата должна устояться заново: старое ровное окно не в счёт.
            fresh_window = not self._climate_run_board_attempts or now - self._climate_run_board_since >= window_s
            stable = fresh_window and is_stable(result, window_s, rate_limit, self.CLIMATE_STABLE_SPREAD_C)
            # Плата в среднем стоит, но показание колеблется (шум датчика у края шкалы): скорость по окну
            # втрое длиннее мала - тоже «устоялась». Так было на стенде при -40: -38,6...-39,6 три часа.
            long_s = 3.0 * window_s
            long = rate_and_spread(self._climate_board, now, long_s)
            quiet_long = (not self._climate_run_board_attempts or now - self._climate_run_board_since >= long_s)                 and now - self._climate_run_since >= long_s and long is not None and long[2] >= long_s * 0.9                 and abs(long[0]) < rate_limit
            # Не висеть: устаивание дольше «предупредить, если не устоялась за» - решение по текущему среднему.
            overdue = now - self._climate_run_since >= self._climate_run_param("settle_timeout_min") * 60.0 / speed
            if (stable or quiet_long or overdue) and self._climate_board:
                board = self._climate_board_mean(now, 60.0 / speed)
                if not stable:
                    if quiet_long:
                        why = (f"плата колеблется (разброс {long[1]:.1f} °C), но в среднем стоит при "
                               f"{_c(board)}: считаю устоявшейся.").replace(".", ",", 1)
                    else:
                        why = (f"плата не устоялась за {self._climate_run_param('settle_timeout_min'):g} мин: решаю по "
                               f"текущему среднему {_c(board)}.")
                        final = None
                    self._climate_event(why, "info" if quiet_long else "warn")
                decision = self._climate_run_board_ok(now, board, final)
                if decision is False:
                    return
                if decision is None:
                    self._climate_run_set(f"Узел {where}: плата почти устоялась ({_c(board)}), но ещё идёт к шагу: "
                                          f"по прогнозу придёт к {_c(final)}. Жду.")
                    self._climate_run_timeout(now, "settle_timeout_min", f"плата не устоялась при {_c(node)}")
                    return
                hold = self._climate_run_param("hold_min")
                capture = bool(self._climate_run_step().get("capture", True))
                then = (f"выдержка {hold:g} мин" if hold > 0
                        else ("снимаю точки" if capture else "точка на этом шаге не снимается"))
                self._climate_event(f"плата устоялась при {_c(board)} (узел {_c(node)}), {then}.", "ok")
                if hold > 0:
                    self._climate_run_enter("hold", now)
                else:
                    self._climate_run_after_hold(now)
                return
            rate = "—" if result is None else f"{result[0] / speed:+.3f} °C/мин".replace(".", ",")
            forecast = f", по прогнозу придёт к {_c(final)}" if final is not None else ""
            self._climate_run_set(f"Узел {where}: камера на уставке, жду, пока устоится плата ({rate}{forecast}).")
            self._climate_run_timeout(now, "settle_timeout_min", f"плата не устоялась при {_c(node)}")
            return

        if stage == "hold":
            hold_s = self._climate_run_param("hold_min") * 60.0 / self._climate_speed()
            left = hold_s - (now - self._climate_run_since)
            if left <= 0:
                self._climate_run_after_hold(now)
            else:
                self._climate_run_set(f"Узел {where}: плата устоялась, выдержка ещё "
                                      f"{max(1, int(left * self._climate_speed() // 60))} мин.")
            return

        if stage == "points":
            if self._climate_run_label_index >= len(self._climate_run_order):
                self._climate_run_node_done(now)
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

    def _climate_run_after_hold(self, now: float):
        """После устойчивости и выдержки: точки, а у шага без точки - сразу следующий шаг."""
        if not bool(self._climate_run_step().get("capture", True)):
            self._climate_run_node_done(now)
            return
        self._climate_run_label_index = 0
        self._climate_run_order = self._climate_label_order()
        self._climate_run_enter("points", now)

    def _climate_run_node_done(self, now: float):
        """Шаг пройден: следующий шаг или конец прогона."""
        node = self._climate_run_node()
        self._climate_run_done.append(node)
        self._climate_hook("_climate_auto_on_node_done", node, now)
        self._climate_run_index += 1
        self._climate_run_reset_board()
        # Недоведённая плата - беда этого шага; на следующем шаге её больше нет.
        self._climate_hook("_climate_auto_alert", "board_miss", False, "")
        if self._climate_run_index >= len(self._climate_run_nodes):
            self._climate_run_finish(now)
        else:
            self._climate_run_enter("setpoint", now)

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
        minutes = self._climate_run_param(key)
        limit_s = minutes * 60.0 / self._climate_speed()
        if not self._climate_run_warned and now - self._climate_run_since > limit_s:
            self._climate_run_warned = True
            self._climate_event(f"{what} за {minutes:.0f} мин. Прогон ждёт дальше, проверьте камеру.", "warn")

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

    def _climate_run_finish(self, now: float | None = None):
        """Все шаги пройдены: вернуть камеру к температуре «в конце» и только потом остановить.

        Остановленная камера температуру не держит: если остановить её сразу после
        уставки +25 °C, она остывает с +85 сама и часами (на стенде к утру было +35,7).
        Поэтому этап «возврат камеры» ждёт, пока воздух выйдет на уставку (не дольше
        «предупредить, если не вышла на уставку за»), и лишь затем останавливает камеру.
        """
        scenario = getattr(self, "_climate_scenario", None)
        finish = scenario.get("finish_setpoint") if scenario else self._climate_settings["finish_setpoint"]
        finish_stop = bool(scenario.get("finish_stop")) if scenario else bool(self._climate_settings["finish_stop"])
        self._climate_run_finish_stop = finish_stop
        if finish is not None and self._climate_link is not None and self._climate_link.driver.can_set \
                and self._climate_send_setpoint(float(finish)):
            self._climate_run_finish_target = float(finish)
            self._climate_run_enter("finish", time.monotonic() if now is None else now)
            then = ", затем остановлю её" if finish_stop else ""
            self._climate_run_set(f"Все шаги пройдены. Возвращаю камеру к {_c(finish)}{then}.", "#16a34a")
            self._climate_event(f"все шаги пройдены ({len(self._climate_run_done)} температур): возвращаю камеру к "
                                f"{_c(finish)}{then}.", "info")
            return
        self._climate_run_complete("")

    def _climate_run_finish_tick(self, now: float):
        """Возврат камеры: воздух вышел на уставку «в конце» (или время вышло) - конец прогона."""
        target = self._climate_run_finish_target
        actual = getattr(self._climate_reading, "actual_c", None) if self._climate_fresh(now) else None
        tolerance = max(1.0, self._climate_run_param("reach_tolerance_c"))
        limit_s = self._climate_run_param("reach_timeout_min") * 60.0 / self._climate_speed()
        if actual is not None and abs(float(actual) - target) <= tolerance:
            self._climate_run_complete(f" Камера вышла на {_c(target)}.")
        elif now - self._climate_run_since >= limit_s:
            self._climate_run_complete(f" Камера не вышла на {_c(target)} за "
                                       f"{self._climate_run_param('reach_timeout_min'):g} мин (сейчас {_c(actual)}).")
        else:
            then = ", затем остановлю её" if self._climate_run_finish_stop else ""
            self._climate_run_set(f"Все шаги пройдены. Возвращаю камеру к {_c(target)}{then}: сейчас {_c(actual)}.",
                                  "#16a34a")

    def _climate_run_complete(self, tail: str):
        """Конец прогона: остановить камеру, если так задано в сценарии, итог - в события."""
        self._climate_run_stage = ""
        if getattr(self, "_climate_run_finish_stop", False):
            self._climate_send_run(False)
            tail += " Камера остановлена."
        self._climate_run_set(f"Автоматический прогон закончен: пройдено {len(self._climate_run_done)} температур.{tail}",
                              "#16a34a")
        self._climate_event(f"автоматический прогон закончен: {len(self._climate_run_done)} температур.{tail}", "ok")
        self._climate_hook("_climate_auto_on_finish")

    # ------------------------------------------------------------------ показ

    def _climate_view(self) -> dict:
        now = time.monotonic()
        settings = self._climate_settings
        link = self._climate_link
        # Без связи показания не показываются: старое число легко принять за текущее.
        reading = self._climate_reading if (link is not None and self._climate_fresh(now)) else None
        register_map = ModbusMap.from_dict(settings["map"]).to_dict()

        nodes = []
        try:
            planned = self._climate_run_nodes or self._climate_run_plan()["nodes"]
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
            "setpoint": "уставка", "reach": "выход на уставку", "settle": "плата устаивается", "hold": "выдержка",
            "points": "точки", "operator": "ждёт оператора", "window": "среднее набирается",
            "capture": "запись точки", "capturing": "запись точки", "finish": "возврат камеры",
        }
        return {
            "driver": settings["driver"],
            "drivers": [{"key": key, "title": DRIVER_TITLES[key]} for key in DRIVERS],
            "chamber": self._climate_chamber_card(),
            "modeHint": self._climate_mode_hint(),
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
            "ports": list(self._climate_ports),
            "scan": {"active": bool(self._climate_scan_active), "status": self._climate_scan_status},
            "diag": self._climate_diag.view() if getattr(self, "_climate_diag", None) is not None else {},
            "moxaCheck": self._climate_moxa_check(),
            "selftest": dict(getattr(self, "_climate_selftest", {"active": False, "text": "", "results": []})),
            "espec": self._climate_espec_view(reading),
            "commands": ESPEC_COMMAND_LIST if settings["driver"] == DRIVER_ESPEC else [],
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
                "auto": self._climate_hook("_climate_auto_view") or {},
            },
            "scenario": self._climate_hook("_climate_scenario_view") or {},
            # Режимы камеры для кнопок и журнал действий управления.
            "control": self._climate_hook("_control_view") or {},
            "history": {
                "t": [round(stamp - now, 1) for stamp, *_rest in self._climate_history],
                "actual": [None if actual is None else round(float(actual), 2)
                           for _stamp, actual, _sp in self._climate_history],
                "setpoint": [None if sp is None else round(float(sp), 2) for _stamp, _actual, sp in self._climate_history],
            },
        }

    def _climate_chamber_card(self) -> dict:
        """Выбранная камера для шапки раздела: имя, назначение и как подключена."""
        settings = self._climate_settings
        driver = settings["driver"]
        info = CHAMBERS.get(driver)
        if info is None:
            return {"name": "Камера не выбрана", "purpose": "Выберите камеру ниже", "link": "",
                    "accent": "#94a3b8", "summary": ""}
        if driver == DRIVER_ESPEC:
            summary = (f"{self._climate_espec_port_text()} · {settings['espec_baud']} бод · "
                       f"адрес {settings['espec_address']} · разделитель {settings['espec_delimiter']}")
        elif driver == DRIVER_SIMCON:
            summary = f"{settings['weiss_port']} · {settings['weiss_baud']} бод · адрес {settings['simcon_address']}"
        elif driver == DRIVER_SIMULATOR:
            summary = f"ускорение ×{float(settings['sim_speed']):g}"
        elif driver == DRIVER_MODBUS_TCP:
            summary = f"{settings['tcp_host']}:{settings['tcp_port']} · устройство {settings['unit']}"
        else:
            summary = f"{settings['rtu_port']} · {settings['rtu_baud']} бод · устройство {settings['unit']}"
        return {**{key: info[key] for key in ("name", "purpose", "link", "accent")}, "summary": summary}

    def _climate_espec_port_text(self) -> str:
        """Порт ESPEC для шапки: при «auto» - какой переходник Moxa найден."""
        port = str(self._climate_settings["espec_port"])
        if port.strip().lower() != PORT_AUTO:
            return port
        link = self._climate_link
        if link is not None and str(getattr(link.driver, "port", PORT_AUTO)).lower() != PORT_AUTO:
            return f"Moxa UPort на {link.driver.port}"
        moxa = [item["device"] for item in self._climate_ports if item.get("moxa")]
        return f"Moxa UPort на {moxa[0]}" if moxa else "Moxa UPort (не найден)"

    def _climate_espec_view(self, reading) -> dict:
        """Подробное состояние камеры ESPEC для блока ручного управления."""
        details = dict(getattr(reading, "details", None) or {}) if reading is not None else {}
        mode = str(details.get("mode") or "")
        high, low = details.get("high_c"), details.get("low_c")
        heater = details.get("heater_pct")
        ref_running = details.get("ref_running")
        ref_setting = str(details.get("ref_setting") or "")
        if ref_setting == "REF0":
            ref_mode = "вручную выключен"
        elif ref_setting == "REF1":
            ref_mode = "вручную включён"
        elif ref_setting.startswith("REF"):
            ref_mode = "авто"
        else:
            ref_mode = ""
        ref_parts = [] if ref_running is None else ["работает" if ref_running else "стоит"]
        if ref_mode:
            ref_parts.append(ref_mode)
        key_protect = details.get("key_protect")
        return {
            "mode": mode,
            "modeText": espec_mode_text(mode) if mode else "—",
            "highText": "—" if high is None else _c(high),
            "lowText": "—" if low is None else _c(low),
            "heaterText": "—" if heater is None else f"{float(heater):.1f} %".replace(".", ","),
            "refText": ", ".join(ref_parts) if ref_parts else "—",
            "refSetting": ref_setting,
            "keyText": "—" if key_protect is None else ("заблокирован" if key_protect else "не заблокирован"),
            "keyProtect": bool(key_protect),
            "identity": " · ".join(str(part) for part in (details.get("rom"), details.get("type")) if part) or "—",
            "alarmsText": ", ".join(str(code) for code in (details.get("alarms") or [])),
            "programText": str(details.get("program") or ""),
            "program": "RUN" in mode,
            "paused": "PAUSE" in mode,
            "powerOff": mode == "OFF",
        }

    def _climate_mode_hint(self) -> str:
        """Подсказка, если режим раздела «Прогон в камере» не подходит выбранной камере."""
        info = CHAMBERS.get(self._climate_settings["driver"])
        want = None if info is None else info["board_only"]
        board_only = bool(getattr(self, "_chamber_board_only", False))
        if want is True and not board_only:
            return ("В ESPEC испытывается одна плата: включите «Только плата» в разделе «Прогон в камере».")
        if want is False and board_only:
            return ("В Weiss испытывается изделие в сборе: выключите «Только плата» в разделе «Прогон в камере».")
        return ""

    def _climate_shutdown(self):
        """Закрывает связь с камерой вместе с программой."""
        self._climate_disconnect(quiet=True)

