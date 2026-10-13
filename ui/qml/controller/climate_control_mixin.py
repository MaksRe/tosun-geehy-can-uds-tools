"""Управление камерой и прогоном из окна, с сайта и из Telegram - с правами и журналом действий.

ЗАЧЕМ
Камерой управляют не только у пульта: из окна программы, с сайта и из
Telegram. Чтобы это было безопасно и прозрачно:
- управлять (экстренная остановка, режим камеры, уставка, старт, пауза и стоп
  прогона, переход по шагам, правка сценария на ходу) могут только админ и
  те, кому он дал право; смотреть может любой;
- каждое действие пишется в журнал logs/control вместе с именем человека,
  откуда пришло действие, подробностями «было → стало» и итогом;
- о важных действиях сразу узнают подписчики бота.

КАК УСТРОЕНО
Все действия идут через одну точку - _control_execute: проверка прав,
выполнение, журнал, уведомление. Действия с сайта и из бота приходят из их
потоков, а камера и прогон живут в потоке окна, поэтому такие действия
ставятся в очередь и выполняются по таймеру окна; поток сайта или бота ждёт
итог. Оператор у камеры (окно программы) считается админом: он за пультом.

ПРОГОН И РУЧНЫЕ КОМАНДЫ
Если во время автопрогона вручную меняют режим камеры или уставку, прогон
сам встаёт на паузу: иначе на следующем шаге программа перебила бы ручную
команду своей уставкой. Экстренная остановка останавливает прогон совсем и
переводит камеру в «Стоп» (ESPEC: MODE, STANDBY).

ПРАВКА СЦЕНАРИЯ НА ХОДУ
Пройденные шаги не меняются. Текущий шаг можно поправить (новая температура -
шаг начинается заново с новой уставкой), но не убрать. Будущие шаги можно
менять, добавлять и убирать. Режим испытания и пометки во время прогона не
меняются: прогон начат с ними.
"""

from __future__ import annotations

import copy
import getpass
import json
import pathlib
import threading
import time

from PySide6.QtCore import QTimer

from ui.qml import climate_scenario
from ui.qml.climate_chamber import DRIVER_ESPEC, espec_is_setting
from ui.qml.control_log import ControlLog
from ui.qml.telegram_bot import ROLE_TITLES, ROLES

from .contract import AppControllerContract

GUI_CHANNEL = "окно программы"
# Режимы ESPEC: ключ, надпись, команда.
ESPEC_MODES = (("constant", "Пуск", "MODE, CONSTANT"), ("standby", "Стоп", "MODE, STANDBY"),
               ("off", "Выключить", "MODE, OFF"))
GENERIC_MODES = (("run", "Пуск"), ("stop", "Стоп"))

ACTION_TITLES = {
    "estop": "экстренная остановка камеры",
    "mode": "режим камеры",
    "setpoint": "уставка камеры",
    "run_start": "старт автопрогона",
    "run_pause": "пауза автопрогона",
    "run_resume": "продолжение автопрогона",
    "run_stop": "остановка автопрогона",
    "run_operator": "эталоны переключены",
    "step_next": "следующий шаг сценария",
    "step_goto": "переход к шагу сценария",
    "scenario": "изменение сценария",
    "scenario_steps": "изменение шагов сценария",
    "role": "права управления",
}
# Кого будить сообщением: важность события для подписчиков бота.
NOTIFY_LEVEL = {"estop": "bad", "mode": "warn", "setpoint": "warn", "run_start": "ok", "run_pause": "warn",
                "run_resume": "ok", "run_stop": "warn", "run_operator": "info", "step_next": "warn",
                "step_goto": "warn", "scenario": "warn", "scenario_steps": "warn", "role": "info"}


def _temp(value) -> str:
    return f"{float(value):+g} °C".replace(".", ",")


class AppControllerClimateControlMixin(AppControllerContract):
    CONTROL_TICK_MS = 150
    # Сколько поток сайта или бота ждёт, пока окно выполнит действие, с.
    CONTROL_WAIT_S = 10.0
    CONTROL_LOG_SHOWN = 40

    # ------------------------------------------------------------------ состояние

    def _init_control_state(self):
        """Журнал действий, очередь действий с сайта и из бота, исполнитель для бота."""
        root = pathlib.Path(getattr(self, "_project_root_directory", None) or pathlib.Path.cwd())
        self._control_log = ControlLog(root / "logs" / "control")
        self._control_lock = threading.Lock()
        self._control_pending: list = []
        self._control_thread = threading.current_thread()
        self._control_timer = QTimer(self)
        self._control_timer.setInterval(self.CONTROL_TICK_MS)
        self._control_timer.timeout.connect(self._control_take_pending)
        self._control_timer.start()
        telegram = getattr(self, "_remote_telegram", None)
        if telegram is not None and hasattr(telegram, "set_control_handler"):
            telegram.set_control_handler(self._control_from_chat)

    # ------------------------------------------------------------------ кто действует

    @staticmethod
    def _control_gui_actor() -> dict:
        """Оператор у камеры: окно программы. Он за пультом, поэтому может всё."""
        try:
            user = getpass.getuser()
        except Exception:  # noqa: BLE001
            user = ""
        return {"id": "", "name": f"оператор у камеры ({user})" if user else "оператор у камеры",
                "username": "", "channel": GUI_CHANNEL, "role": "admin"}

    def _control_actor(self, chat_id: str, channel: str) -> dict:
        """Подписчик бота как действующее лицо: имя, @ник и права."""
        users = getattr(self, "_remote_users", None)
        user = users.get(chat_id) if users is not None else None
        user = user or {}
        return {"id": str(chat_id), "name": user.get("name") or f"чат {chat_id}",
                "username": user.get("username") or "", "channel": str(channel),
                "role": user.get("role") or "viewer"}

    @staticmethod
    def _control_who(actor: dict) -> str:
        return actor["name"] + (f" (@{actor['username']})" if actor.get("username") else "")

    # ------------------------------------------------------------------ очередь

    def _control_from_chat(self, chat_id: str, action: str, params: dict) -> tuple[bool, str]:
        """Действие из чата бота (поток бота)."""
        return self._control_submit(self._control_actor(chat_id, "Telegram"), action, params)

    def _control_submit(self, actor: dict, action: str, params: dict | None = None) -> tuple[bool, str]:
        """Действие из любого потока: в потоке окна - сразу, из потоков сайта и бота - через очередь."""
        if threading.current_thread() is self._control_thread:
            return self._control_execute(actor, action, params or {})
        done = threading.Event()
        box: dict = {}
        with self._control_lock:
            self._control_pending.append((actor, action, dict(params or {}), done, box))
        if not done.wait(self.CONTROL_WAIT_S):
            return False, "программа у камеры не ответила вовремя: проверьте журнал действий"
        return box.get("result", (False, "нет ответа"))

    def _control_take_pending(self):
        """Таймер окна: выполнить действия, пришедшие с сайта и из бота."""
        with self._control_lock:
            items = list(self._control_pending)
            self._control_pending.clear()
        for actor, action, params, done, box in items:
            try:
                box["result"] = self._control_execute(actor, action, params)
            except Exception as error:  # noqa: BLE001 - сбой одного действия не должен ронять окно
                box["result"] = (False, f"ошибка: {error}")
            done.set()

    # ------------------------------------------------------------------ исполнение

    def _control_execute(self, actor: dict, action: str, params: dict) -> tuple[bool, str]:
        """Права, действие, журнал, уведомление. Возвращает (успех, текст для человека)."""
        title = ACTION_TITLES.get(str(action))
        who = self._control_who(actor)
        if title is None:
            return False, "неизвестное действие"
        if actor.get("channel") != GUI_CHANNEL and actor.get("role") not in ("operator", "admin"):
            self._control_log.add(who, actor.get("channel", ""), title, "", False, "нет права управлять")
            return False, "нет права управлять: его даёт админ"
        run_active = bool(self._climate_run_stage)
        handler = getattr(self, f"_control_do_{action}")
        ok, text, details = handler(actor, dict(params or {}))
        self._control_log.add(who, actor.get("channel", ""), title, details, ok, text)
        diag = getattr(self, "_climate_diag_event", None)
        if diag is not None:
            diag("CONTROL", f"{who} [{actor.get('channel', '')}]: {title}. {details} -> {text}",
                 "INFO" if ok else "WARN")
        level = NOTIFY_LEVEL.get(action)
        # Правка сценария вне прогона - рабочая подготовка: только журнал, без сообщений подписчикам.
        notify = ok and level is not None and (run_active or not action.startswith("scenario"))
        event = getattr(self, "_remote_event", None)
        if event is not None and ok and text != "изменений нет":
            event(f"{who} ({actor.get('channel', '')}): {title}" + (f" - {details}" if details else "") + f". {text}",
                  level or "info", telegram=notify)
        self.climateChanged.emit()
        changed = getattr(self, "remoteMonitorChanged", None)
        if changed is not None:
            changed.emit()
        return ok, text

    def _control_gui(self, action: str, params: dict | None = None) -> tuple[bool, str]:
        """Действие оператора из окна программы."""
        return self._control_submit(self._control_gui_actor(), action, params or {})

    def _control_note(self, action_title: str, details: str, ok: bool, text: str = ""):
        """Запись в журнал действия окна, которое выполняется своим путём (команды из каталога, файлы)."""
        actor = self._control_gui_actor()
        self._control_log.add(self._control_who(actor), GUI_CHANNEL, action_title, details, ok, text)
        changed = getattr(self, "remoteMonitorChanged", None)
        if changed is not None:
            changed.emit()

    # ------------------------------------------------------------------ камера

    def _control_hold_run(self) -> str:
        """Ручная команда во время прогона: прогон на паузу, чтобы программа не перебила её своей уставкой."""
        if self._climate_run_stage and not self._climate_run_paused:
            self._climate_run_pause(True)
            return " Автопрогон поставлен на паузу, чтобы не перебить ручную команду."
        return ""

    def _control_modes(self) -> list[dict]:
        """Режимы камеры, которые можно переключать из программы."""
        if self._climate_settings.get("driver") == DRIVER_ESPEC:
            return [{"key": key, "title": title} for key, title, _command in ESPEC_MODES]
        link = self._climate_link
        if link is not None and link.driver.can_run:
            return [{"key": key, "title": title} for key, title in GENERIC_MODES]
        return []

    def _control_do_estop(self, actor: dict, params: dict):
        parts = []
        if self._climate_run_stage:
            self._climate_run_stop(f"экстренно остановлен: {self._control_who(actor)}")
            parts.append("автопрогон остановлен")
        link = self._climate_link
        if link is None:
            parts.append("камера не подключена к программе - ОСТАНОВИТЕ ЕЁ НА ПУЛЬТЕ")
            return False, "; ".join(parts) + ".", ""
        if self._climate_settings.get("driver") == DRIVER_ESPEC:
            link.command("raw", "MODE, STANDBY")
            parts.append("камере отправлен «Стоп» (MODE, STANDBY)")
        elif link.driver.can_run:
            link.command("run", False)
            parts.append("камере отправлена остановка")
        else:
            parts.append("эта камера не даёт останавливать себя из программы - ОСТАНОВИТЕ ЕЁ НА ПУЛЬТЕ")
            return False, "; ".join(parts) + ".", ""
        self._climate_command_status = "Экстренная остановка: " + "; ".join(parts) + "."
        return True, "; ".join(parts) + ".", ""

    def _control_do_mode(self, actor: dict, params: dict):
        mode = str(params.get("mode", ""))
        link = self._climate_link
        if link is None:
            return False, "камера не подключена", mode
        if self._climate_settings.get("driver") == DRIVER_ESPEC:
            found = [(title, command) for key, title, command in ESPEC_MODES if key == mode]
            if not found:
                return False, "неизвестный режим", mode
            title, command = found[0]
            paused = self._control_hold_run()
            link.command("raw", command)
        else:
            found = [title for key, title in GENERIC_MODES if key == mode]
            if not found or not link.driver.can_run:
                return False, "эта камера не даёт переключать режим из программы", mode
            title = found[0]
            paused = self._control_hold_run()
            link.command("run", mode == "run")
        self._climate_command_status = f"Режим «{title}» отправлен камере."
        return True, f"режим «{title}» отправлен камере.{paused}", f"«{title}»"

    def _control_do_setpoint(self, actor: dict, params: dict):
        try:
            value = float(str(params.get("value", "")).replace(",", ".").strip())
        except ValueError:
            return False, "уставка - это число, °C", str(params.get("value", ""))
        low, high = float(self._climate_settings["min_c"]), float(self._climate_settings["max_c"])
        if not (low <= value <= high):
            return False, f"уставка вне допустимых пределов {low:+.0f}...{high:+.0f} °C", _temp(value)
        if self._climate_link is None:
            return False, "камера не подключена", _temp(value)
        paused = self._control_hold_run()
        ok = self._climate_send_setpoint(value)
        return ok, (f"камере задано {_temp(value)}." if ok else self._climate_command_status) + paused, _temp(value)

    # ------------------------------------------------------------------ прогон

    def _control_do_run_start(self, actor: dict, params: dict):
        if self._climate_run_stage:
            return False, "автопрогон уже идёт", ""
        ok = self._climate_run_start()
        return ok, self._climate_run_status, (getattr(self, "_climate_scenario", None) or {}).get("name", "")

    def _control_do_run_pause(self, actor: dict, params: dict):
        if not self._climate_run_stage:
            return False, "автопрогон не идёт", ""
        if self._climate_run_paused:
            return False, "автопрогон уже на паузе", ""
        self._climate_run_pause(True)
        return True, "автопрогон на паузе.", ""

    def _control_do_run_resume(self, actor: dict, params: dict):
        if not self._climate_run_stage:
            return False, "автопрогон не идёт", ""
        if not self._climate_run_paused:
            return False, "автопрогон не на паузе", ""
        self._climate_run_pause(False)
        return True, "автопрогон продолжен.", ""

    def _control_do_run_stop(self, actor: dict, params: dict):
        if not self._climate_run_stage:
            return False, "автопрогон не идёт", ""
        self._climate_run_stop(f"остановлен: {self._control_who(actor)}")
        return True, "автопрогон остановлен, уставка камеры оставлена как есть.", ""

    def _control_do_run_operator(self, actor: dict, params: dict):
        if self._climate_run_stage != "operator":
            return False, "прогон не ждёт переключения эталонов", ""
        self._climate_run_continue()
        return True, "прогон снимает следующую точку.", ""

    def _climate_run_goto(self, index: int):
        """Прогон переходит к шагу index: уставка шага задаётся заново, точки шага снимаются с начала."""
        now = time.monotonic()
        self._climate_run_index = int(index)
        self._climate_run_reset_board()
        self._climate_run_label_index = 0
        self._climate_run_attempts = 0
        self._climate_run_retry_at = 0.0
        self._climate_run_enter("setpoint", now)
        if not self._climate_run_paused:
            self._climate_run_tick(now)
        self._climate_hook("_climate_auto_save", now)

    def _control_step_text(self, index: int) -> str:
        return f"шаг {index + 1} ({_temp(self._climate_run_nodes[index])})"

    def _control_do_step_next(self, actor: dict, params: dict):
        if not self._climate_run_stage:
            return False, "автопрогон не идёт", ""
        index = self._climate_run_index
        if index + 1 >= len(self._climate_run_nodes):
            return False, "это последний шаг: чтобы закончить раньше, остановите прогон", ""
        details = f"{self._control_step_text(index)} → {self._control_step_text(index + 1)}"
        self._climate_run_goto(index + 1)
        return True, f"прогон перешёл к шагу {index + 2}.", details

    def _control_do_step_goto(self, actor: dict, params: dict):
        if not self._climate_run_stage:
            return False, "автопрогон не идёт", ""
        try:
            target = int(params.get("index"))
        except (TypeError, ValueError):
            return False, "номер шага не понят", ""
        if not (0 <= target < len(self._climate_run_nodes)):
            return False, f"шага {target + 1} нет", ""
        if target == self._climate_run_index:
            return False, "этот шаг уже идёт", ""
        details = f"{self._control_step_text(self._climate_run_index)} → {self._control_step_text(target)}"
        self._climate_run_goto(target)
        return True, f"прогон перешёл к шагу {target + 1}.", details

    # ------------------------------------------------------------------ сценарий

    def _control_do_scenario(self, actor: dict, params: dict):
        data = params.get("scenario")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError as error:
                return False, f"сценарий не прочитан: {error}", ""
        return self._control_apply_scenario(data)

    def _control_do_scenario_steps(self, actor: dict, params: dict):
        steps = params.get("steps")
        if not isinstance(steps, list):
            return False, "шаги не прочитаны", ""
        base = copy.deepcopy(getattr(self, "_climate_scenario", None) or climate_scenario.empty_scenario())
        base["steps"] = steps
        return self._control_apply_scenario(base)

    def _control_apply_scenario(self, data) -> tuple[bool, str, str]:
        """Новый сценарий целиком; во время прогона - к идущему прогону, не трогая пройденные шаги."""
        clean, problems = climate_scenario.normalize(data)
        if not clean["steps"]:
            return False, "в сценарии нет годных шагов", ""
        old = copy.deepcopy(getattr(self, "_climate_scenario", None) or climate_scenario.empty_scenario())
        active = bool(self._climate_run_stage)
        index = self._climate_run_index if active else 0
        temp_changed = False
        if active:
            run_steps = [dict(step) for step in self._climate_run_steps]
            if len(clean["steps"]) <= index:
                return False, (f"шаг {index + 1} сейчас идёт: убрать его нельзя. Чтобы закончить раньше - "
                               "остановите прогон"), ""
            # Режим испытания и пометки - основа идущего прогона: во время него не меняются.
            for key in ("board_only", "single_model", "labels", "auto_write"):
                clean[key] = old.get(key, clean[key])
            clean["steps"] = run_steps[:index] + clean["steps"][index:]
            temp_changed = float(clean["steps"][index]["temp"]) != float(run_steps[index]["temp"])
        low, high = float(self._climate_settings["min_c"]), float(self._climate_settings["max_c"])
        for number, step in enumerate(clean["steps"][index:], start=index + 1):
            if not (low <= float(step["temp"]) <= high):
                return False, f"шаг {number}: {_temp(step['temp'])} вне допустимых пределов {low:+.0f}...{high:+.0f} °C", ""
        lines = climate_scenario.diff(old, clean)
        if not lines:
            return True, "изменений нет", ""
        self._climate_scenario_set(clean, path=self._climate_scenario_path, dirty=True,
                                   status="Сценарий изменён" + (" во время прогона." if active else "."))
        text = "сценарий изменён."
        if active:
            steps = [dict(step) for step in self._climate_scenario["steps"]]
            self._climate_run_steps = steps
            self._climate_run_nodes = [float(step["temp"]) for step in steps]
            if temp_changed:
                self._climate_run_goto(index)
                text += f" Текущий шаг {index + 1} начат заново с уставкой {_temp(steps[index]['temp'])}."
            else:
                self._climate_hook("_climate_auto_save")
            text += " Идущий прогон пойдёт по новым шагам."
        if problems:
            text += " Замечания: " + "; ".join(problems[:3]) + "."
        return True, text, "; ".join(lines)

    def _control_gui_scenario_update(self, text: str) -> bool:
        """Правка сценария из формы вне прогона: как раньше, плюс запись изменений в журнал."""
        old = copy.deepcopy(getattr(self, "_climate_scenario", None) or {})
        ok = self._climate_scenario_update(text)
        if ok:
            lines = climate_scenario.diff(old, self._climate_scenario)
            if lines:
                self._control_note(ACTION_TITLES["scenario"], "; ".join(lines), True)
        return ok

    # ------------------------------------------------------------------ права

    def _control_do_role(self, actor: dict, params: dict):
        chat_id = str(params.get("id", ""))
        role = str(params.get("role", ""))
        users = getattr(self, "_remote_users", None)
        target = users.get(chat_id) if users is not None else None
        if target is None:
            return False, "такого подписчика нет", chat_id
        name = target.get("name") or chat_id
        if role not in ROLES:
            return False, "неизвестные права", name
        from_gui = actor.get("channel") == GUI_CHANNEL
        if not from_gui:
            if actor.get("role") != "admin":
                return False, "права раздаёт только админ", name
            if role == "admin" or target.get("role") == "admin":
                return False, "назначить или снять админа можно только в окне программы у камеры", name
        before = target.get("role", "viewer")
        if before == role:
            return True, "изменений нет", name
        fields = {"role": role}
        if role == "viewer":
            # Права сняты - ссылка входа на сайт больше не работает.
            fields["web_token"] = ""
        users.upsert(chat_id, **fields)
        telegram = getattr(self, "_remote_telegram", None)
        if telegram is not None and hasattr(telegram, "send_to"):
            message = (f"Вам дали право управлять камерой и прогоном ({ROLE_TITLES[role]}). Команды: /control, "
                       "/estop, /login. Все действия записываются в журнал с вашим именем."
                       if role != "viewer" else "Право управлять камерой снято: теперь вы только наблюдаете.")
            telegram.send_to(chat_id, message)
        return True, f"{name}: {ROLE_TITLES[before]} → {ROLE_TITLES[role]}.", name

    # ------------------------------------------------------------------ показ

    def _control_view(self) -> dict:
        """Режимы камеры и журнал действий для окна, сайта и мини-приложения."""
        log = getattr(self, "_control_log", None)
        return {
            "modes": self._control_modes(),
            "espec": self._climate_settings.get("driver") == DRIVER_ESPEC,
            "limits": {"min": float(self._climate_settings["min_c"]), "max": float(self._climate_settings["max_c"])},
            "log": log.recent(self.CONTROL_LOG_SHOWN) if log is not None else [],
            "logPath": log.current_path if log is not None else "",
        }


def is_setting_command(text: str) -> bool:
    """Команда ESPEC меняет что-то (а не спрашивает): такие пишутся в журнал действий."""
    line = str(text).strip()
    head, _, rest = line.partition(",")
    command = rest.strip() if rest and head.strip().isdigit() else line
    return bool(command) and espec_is_setting(command)
