"""Telegram-бот наблюдения за прогоном: подписчики, уровни уведомлений, команды, мини-приложение.

ЗАЧЕМ
За прогоном следят несколько человек. Бот присылает им события прогона, а
подробности видны в мини-приложении прямо в Telegram или на сайте.

ДОСТУП
Смотреть может любой: кто написал боту /start - подписан и получает
уведомления; /stop - отписан. Управлять камерой и прогоном (экстренная
остановка, режимы, уставка, шаги сценария) могут только админ и те, кому он
дал право («управляет»). Первого админа назначают в окне программы у камеры.
Каждое действие управления записывается в журнал с именем человека.

Для управления с сайта в обычном браузере команда /login присылает личную
ссылку входа; /login new - новая, прежние перестают работать.

УВЕДОМЛЕНИЯ
Каждый подписчик сам выбирает (/settings), что ему присылать:
- «Все события» - всё, что пишет программа;
- «Важные» - выход на этапы, итоги, предупреждения и аварии, без мелочей;
- «Только аварии» - только беды: авария камеры, нет связи, прогон встал;
- «Без уведомлений» - ничего, только по запросу (/status, мини-приложение).
Отдельно: «точки» (сообщение о каждой точке), «сводки» (по расписанию),
«файлы» (журнал, профиль, отчёт).

КАК УСТРОЕНО
Два своих потока: приём команд (длинный опрос getUpdates) и отправка
(очередь с повторами). Окно не ждёт сеть. Подписчики хранятся в JSON-файле.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import queue
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Callable
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import parse_qsl

API_ROOT = "https://api.telegram.org"
REQUEST_TIMEOUT_S = 15.0
POLL_TIMEOUT_S = 25
SEND_ATTEMPTS = 3
RETRY_PAUSE_S = 5.0
MAX_DOCUMENT_BYTES = 49 * 1024 * 1024
# Сколько действительны данные запуска мини-приложения.
INIT_DATA_MAX_AGE_S = 24 * 3600

LEVELS = ("all", "important", "alarms", "off")
LEVEL_TITLES = {
    "all": "Все события",
    "important": "Важные",
    "alarms": "Только аварии",
    "off": "Без уведомлений",
}
# Важность события: info - ход работы, ok - итоги этапов, warn - предупреждения, bad - беды.
EVENT_RANK = {"info": 0, "ok": 1, "warn": 2, "bad": 3}
LEVEL_MIN_RANK = {"all": 0, "important": 1, "alarms": 3, "off": 99}
EVENT_MARK = {"ok": "✅", "warn": "⚠️", "bad": "❌", "info": "ℹ️"}
OPTIONS = {"points": "Каждая точка", "summaries": "Сводки", "files": "Файлы"}
# Права: наблюдатель только смотрит, «управляет» - может управлять камерой и прогоном, админ - ещё и раздаёт права.
ROLES = ("viewer", "operator", "admin")
ROLE_TITLES = {"viewer": "наблюдатель", "operator": "управляет", "admin": "админ"}
# Панель управления в чате: действие - надпись кнопки. Опасные - с подтверждением.
CONTROL_BUTTONS = (("estop", "⛔ Экстренная остановка"), ("run_pause", "⏸ Пауза прогона"),
                   ("run_resume", "▶ Продолжить прогон"), ("step_next", "⏭ Следующий шаг"))
CONFIRM_ACTIONS = {"estop": "Экстренно остановить камеру? Автопрогон тоже остановится.",
                   "step_next": "Перейти к следующему шагу сценария, не дожидаясь точек текущего?"}
# Ответы Telegram, после которых писать в чат бессмысленно: человек заблокировал бота или удалил чат.
GONE_MARKS = ("chat not found", "bot was blocked", "user is deactivated")


def default_user(level: str = "important", points: bool = True, summaries: bool = True, files: bool = True) -> dict:
    """Настройки нового подписчика: уровень и переключатели по умолчанию из программы."""
    return {"name": "", "username": "",
            "level": level if level in LEVELS else "important",
            "points": bool(points), "summaries": bool(summaries), "files": bool(files),
            "since": time.strftime("%Y-%m-%d %H:%M"),
            # Права и ключ личной ссылки входа на сайт (только у тех, кто управляет).
            "role": "viewer", "web_token": ""}


def can_control(user: dict | None) -> bool:
    """Может ли человек управлять камерой и прогоном."""
    return bool(user) and user.get("role") in ("operator", "admin")


def public_user(user: dict) -> dict:
    """Подписчик для показа: без ключа ссылки входа."""
    shown = dict(user)
    shown.pop("web_token", None)
    return shown


def wants(user: dict, level: str, kind: str = "event") -> bool:
    """Нужно ли подписчику это сообщение: по уровню и переключателям.

    kind: «event» - событие, «point» - точка записана, «summary» - сводка,
    «file» - файл. level: info, ok, warn, bad.
    """
    mode = user.get("level", "important")
    if mode == "off":
        return False
    if kind == "point":
        return bool(user.get("points")) and mode in ("all", "important")
    if kind == "summary":
        return bool(user.get("summaries"))
    if kind == "file":
        return bool(user.get("files"))
    return EVENT_RANK.get(level, 0) >= LEVEL_MIN_RANK.get(mode, 1)


def validate_init_data(init_data: str, token: str, now: float | None = None,
                       max_age_s: float = INIT_DATA_MAX_AGE_S) -> dict | None:
    """Проверяет подпись данных запуска мини-приложения. Возвращает пользователя Telegram или None.

    Нужна, чтобы мини-приложение знало, чьи настройки уведомлений показывать и
    в какой чат прислать файл. По документации Telegram: секрет =
    HMAC-SHA256(ключ «WebAppData», токен бота), подпись = HMAC-SHA256(секрет,
    строка «ключ=значение» всех полей кроме hash, по алфавиту, через перевод строки).
    """
    if not init_data or not token:
        return None
    try:
        fields = dict(parse_qsl(str(init_data), keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received = fields.pop("hash", "")
    if not received:
        return None
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", str(token).encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return None
    try:
        auth_date = int(fields.get("auth_date", "0"))
        user = json.loads(fields.get("user", "{}"))
    except ValueError:
        return None
    current = time.time() if now is None else now
    if current - auth_date > max_age_s or not isinstance(user, dict) or "id" not in user:
        return None
    return user


def sign_init_data(fields: dict, token: str) -> str:
    """Подписывает данные запуска так же, как Telegram: нужно проверкам и отладке на столе."""
    from urllib.parse import urlencode

    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", str(token).encode("utf-8"), hashlib.sha256).digest()
    signed = dict(fields)
    signed["hash"] = hmac.new(secret, check.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(signed)


class TelegramUsers:
    """Подписчики бота в JSON-файле: уровень и переключатели. Потокобезопасно."""

    def __init__(self, path: Path | None):
        self.path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._users: dict[str, dict] = {}
        self.load()

    def load(self):
        if self.path is None:
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        users = {}
        for chat_id, data in (payload.get("users") or {}).items() if isinstance(payload, dict) else []:
            if isinstance(data, dict):
                user = default_user()
                user.update({key: data[key] for key in user if key in data})
                if "role" not in data and data.get("admin"):
                    # Файл прежней версии: админ записан флагом «admin» - права сохраняются.
                    user["role"] = "admin"
                if user["level"] not in LEVELS:
                    user["level"] = "important"
                if user["role"] not in ROLES:
                    user["role"] = "viewer"
                users[str(chat_id)] = user
        with self._lock:
            self._users = users

    def _save_locked(self):
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"users": self._users}, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            pass

    def get(self, chat_id) -> dict | None:
        with self._lock:
            user = self._users.get(str(chat_id))
            return dict(user) if user else None

    def all(self) -> dict[str, dict]:
        with self._lock:
            return {chat_id: dict(user) for chat_id, user in self._users.items()}

    def upsert(self, chat_id, defaults: dict | None = None, **fields) -> dict:
        """Создаёт (с настройками defaults) или обновляет подписчика; возвращает его настройки."""
        with self._lock:
            user = self._users.get(str(chat_id))
            if user is None:
                user = default_user()
                user.update({key: value for key, value in (defaults or {}).items() if key in user})
                self._users[str(chat_id)] = user
            for key, value in fields.items():
                if key in user:
                    user[key] = value
            if user["level"] not in LEVELS:
                user["level"] = "important"
            self._save_locked()
            return dict(user)

    def remove(self, chat_id) -> bool:
        with self._lock:
            found = self._users.pop(str(chat_id), None) is not None
            if found:
                self._save_locked()
            return found

    def find_by_token(self, token: str) -> str | None:
        """Номер чата по ключу ссылки входа или None. Сравнение - без утечки по времени."""
        token = str(token or "")
        if len(token) < 16:
            return None
        with self._lock:
            for chat_id, user in self._users.items():
                stored = str(user.get("web_token") or "")
                if stored and hmac.compare_digest(stored, token):
                    return chat_id
        return None

    def recipients(self, level: str, kind: str = "event") -> list[str]:
        """Кому отправить: подписчики, которым это сообщение нужно."""
        with self._lock:
            return [chat_id for chat_id, user in self._users.items() if wants(user, level, kind)]


class TelegramBot:
    """Бот наблюдения: подписка, рассылка по подписчикам, кнопка мини-приложения."""

    def __init__(self, users: TelegramUsers, status_callback: Callable[[str, bool], None] | None = None):
        self.users = users
        self._status_callback = status_callback
        self._lock = threading.Lock()
        self._token = ""
        self._username = ""
        self._app_url = ""
        self._defaults = default_user()
        self._status_text = "Данных пока нет."
        self._menu_url_sent = ""
        # Исполнитель действий управления (см. set_control_handler): (номер чата, действие, параметры) -> (успех, текст).
        self._control_handler: Callable[[str, str, dict], tuple[bool, str]] | None = None
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._poll_generation = 0
        self._sender = threading.Thread(target=self._send_worker, daemon=True, name="telegram-bot-send")
        self._sender.start()
        self._poller = threading.Thread(target=self._poll_worker, daemon=True, name="telegram-bot-poll")
        self._poller.start()

    # ------------------------------------------------------------------ настройка

    def configure(self, token: str, defaults: dict | None = None):
        """Токен бота и настройки новых подписчиков. Пустой токен - бот молчит."""
        token = str(token or "").strip()
        with self._lock:
            if token != self._token:
                self._poll_generation += 1
                self._menu_url_sent = ""
                self._username = ""
            self._token = token
            if defaults:
                self._defaults = default_user(defaults.get("level", "important"), defaults.get("points", True),
                                              defaults.get("summaries", True), defaults.get("files", True))
        self._sync_menu()

    def set_app_url(self, url: str):
        """Адрес мини-приложения и сайта: кнопка меню бота открывает его. Пусто - кнопки нет."""
        with self._lock:
            self._app_url = str(url or "").strip()
        self._sync_menu()

    def set_control_handler(self, handler: Callable[[str, str, dict], tuple[bool, str]] | None):
        """Кто выполняет действия управления из чата: программа проверит права и запишет в журнал."""
        self._control_handler = handler

    def login_link(self, chat_id: str, renew: bool = False) -> str:
        """Личная ссылка входа на сайт с правом управления. Пусто - нет права или нет адреса сайта.

        renew - новый ключ: прежние ссылки перестают работать. Ключ стоит после «#»:
        браузер не отправляет эту часть адреса на сервер, она не попадает в журналы.
        """
        user = self.users.get(chat_id)
        base = self.app_url
        if not can_control(user) or not base:
            return ""
        token = str(user.get("web_token") or "")
        if renew or not token:
            token = secrets.token_urlsafe(24)
            self.users.upsert(chat_id, web_token=token)
        return f"{base.rstrip('/')}/#login={token}"

    def set_status_text(self, text: str):
        """Текст для /status. Вызывается из потока окна, читается потоком бота."""
        with self._lock:
            self._status_text = str(text)

    @property
    def ready(self) -> bool:
        return bool(self._token)

    @property
    def token(self) -> str:
        with self._lock:
            return self._token

    @property
    def username(self) -> str:
        """Имя бота (без @), как его узнал Telegram; пусто - ещё не узнали."""
        with self._lock:
            return self._username

    @property
    def app_url(self) -> str:
        with self._lock:
            return self._app_url

    def subscribe(self, chat_id, name: str = "", username: str = "") -> dict:
        """Подписывает чат с настройками по умолчанию (или обновляет имя уже подписанного)."""
        with self._lock:
            defaults = dict(self._defaults)
        fields = {}
        if name:
            fields["name"] = name
        if username:
            fields["username"] = username
        return self.users.upsert(chat_id, defaults={key: defaults[key] for key in ("level", "points", "summaries",
                                                                                   "files")}, **fields)

    def reset_menu_now(self, timeout: float = 2.0):
        """При закрытии программы: кнопка меню снова - список команд, а не мёртвый адрес туннеля.

        Отправляется сразу, без очереди: потоки бота вот-вот остановятся. Нет сети - не беда.
        """
        with self._lock:
            had_app = bool(self._token) and bool(self._menu_url_sent)
        if not had_app:
            return
        try:
            self._call("setChatMenuButton", {"menu_button": {"type": "commands"}}, timeout=timeout)
            with self._lock:
                self._menu_url_sent = ""
        except Exception:  # noqa: BLE001 - закрытие программы не должно зависеть от сети
            pass

    def close(self):
        self._stop.set()
        self._queue.put(None)
        for thread in (self._sender, self._poller):
            if thread.is_alive():
                thread.join(timeout=1.5)

    # ------------------------------------------------------------------ рассылка

    def notify(self, text: str, level: str = "info", kind: str = "event"):
        """Событие всем подписчикам, кому оно нужно по их уровню и переключателям."""
        if not self.ready:
            return
        mark = EVENT_MARK.get(level, "ℹ️")
        body = f"{mark} {text}"
        for chat_id in self.users.recipients(level, kind):
            self._queue.put(("send", {"chat_id": chat_id, "text": body, "disable_web_page_preview": True}))

    def send_document(self, path, caption: str = "", chat_ids: list[str] | None = None):
        """Файл тем, кто включил «файлы» (или в указанные чаты)."""
        if not self.ready:
            return
        targets = chat_ids if chat_ids is not None else self.users.recipients("info", "file")
        for chat_id in targets:
            self._queue.put(("document", (str(chat_id), str(path), str(caption))))

    def send_to(self, chat_id, text: str, markup: dict | None = None):
        """Сообщение одному чату (ответ на команду, проверка связи)."""
        payload = {"chat_id": str(chat_id), "text": str(text), "disable_web_page_preview": True}
        if markup:
            payload["reply_markup"] = markup
        self._queue.put(("send", payload))

    def test(self) -> int:
        """Проверка связи: сообщение всем подписчикам. Возвращает, скольким."""
        subscribers = list(self.users.all())
        for chat_id in subscribers:
            self.send_to(chat_id, "ℹ️ Проверка связи: бот наблюдения на связи. Команды: /status, /settings, /app.")
        return len(subscribers)

    # ------------------------------------------------------------------ потоки

    def _emit(self, text: str, ok: bool):
        if self._status_callback is not None:
            self._status_callback(str(text), bool(ok))

    def _send_worker(self):
        while not self._stop.is_set():
            try:
                task = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if task is None:
                break
            kind, payload = task
            last_error = ""
            for attempt in range(SEND_ATTEMPTS):
                try:
                    if kind == "send":
                        self._call("sendMessage", payload)
                    elif kind == "call":
                        method, data = payload
                        self._call(method, data)
                    else:
                        chat_id, path, caption = payload
                        self._post_document(chat_id, Path(path), caption)
                    last_error = ""
                    break
                except Exception as error:  # noqa: BLE001 - любая ошибка сети одинаково повод повторить
                    last_error = str(error)
                    if any(mark in last_error for mark in GONE_MARKS):
                        break
                    if attempt + 1 < SEND_ATTEMPTS and not self._stop.wait(RETRY_PAUSE_S):
                        continue
            if last_error and any(mark in last_error for mark in GONE_MARKS) and kind in ("send", "document"):
                # Человек заблокировал бота или удалил чат - он больше не подписчик.
                chat_id = payload["chat_id"] if kind == "send" else payload[0]
                if self.users.remove(chat_id):
                    self._emit(f"Telegram: подписчик {chat_id} заблокировал бота и отписан.", True)
            elif last_error:
                self._emit(f"Telegram: не отправлено: {last_error}", False)
            elif kind in ("send", "document"):
                self._emit("Telegram: сообщения уходят.", True)

    def _poll_worker(self):
        """Длинный опрос getUpdates: команды и нажатия кнопок."""
        offset = 0
        generation = -1
        while not self._stop.is_set():
            with self._lock:
                token = self._token
                current = self._poll_generation
                known = self._username
            if not token:
                self._stop.wait(1.0)
                continue
            if current != generation:
                generation = current
                offset = 0
            if not known:
                self._learn_username()
            try:
                answer = self._call("getUpdates", {"offset": offset, "timeout": POLL_TIMEOUT_S,
                                                   "allowed_updates": ["message", "callback_query"]},
                                    timeout=POLL_TIMEOUT_S + 10)
            except Exception as error:  # noqa: BLE001
                self._emit(f"Telegram: бот не получает команды: {error}", False)
                self._stop.wait(10.0)
                continue
            for update in answer.get("result") or []:
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                try:
                    self.handle_update(update)
                except Exception as error:  # noqa: BLE001 - одна странная команда не должна ронять бота
                    self._emit(f"Telegram: команда не обработана: {error}", False)

    def _learn_username(self):
        """Имя бота для ссылки «подписаться» на сайте и в окне программы."""
        try:
            name = str((self._call("getMe", {}).get("result") or {}).get("username") or "")
        except Exception:  # noqa: BLE001 - без имени всё работает, просто без ссылки
            return
        with self._lock:
            self._username = name
        if name:
            self._emit(f"Бот @{name} работает. Чтобы получать уведомления, напишите ему /start.", True)

    # ------------------------------------------------------------------ команды

    def handle_update(self, update: dict):
        """Разбор одного обновления: сообщение с командой или нажатие кнопки."""
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
            return
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if "id" not in chat:
            return
        chat_id = str(chat["id"])
        text = str(message.get("text") or "").strip()
        sender = message.get("from") or {}
        name = " ".join(part for part in (sender.get("first_name"), sender.get("last_name")) if part) \
            or chat.get("title") or sender.get("username") or chat_id
        username = str(sender.get("username") or "")
        command = text.partition(" ")[0].split("@", 1)[0].lower()

        if command == "/start":
            known = self.users.get(chat_id) is not None
            user = self.subscribe(chat_id, name, username)
            if not known:
                self._emit(f"Telegram: подписался {name}.", True)
            self.send_to(chat_id, ("Вы подписаны на уведомления о прогоне. " if not known else "Вы уже подписаны. ")
                         + f"Что присылать: {LEVEL_TITLES[user['level']]} - изменить /settings.\n\n"
                         + self._help_text(user), self._app_markup())
        elif command == "/stop":
            user = self.users.get(chat_id)
            if can_control(user):
                # Права управления не теряются от отписки: выключаются только уведомления.
                self.users.upsert(chat_id, level="off")
                self.send_to(chat_id, "Уведомления выключены. Право управлять камерой сохранено. Включить снова - /settings.")
            else:
                self.users.remove(chat_id)
                self.send_to(chat_id, "Вы отписаны: уведомления больше не придут. Подписаться снова - /start.")
            self._emit(f"Telegram: отписался {name}.", True)
        elif command in ("/login", "/estop", "/control"):
            self._control_command(chat_id, command, text.partition(" ")[2].strip().lower())
        elif command == "/status":
            with self._lock:
                status = self._status_text
            self.send_to(chat_id, status, self._app_markup())
        elif command == "/settings":
            self.subscribe(chat_id, name, username)
            self.send_to(chat_id, self._settings_text(chat_id), self._settings_markup(chat_id))
        elif command == "/app":
            markup = self._app_markup()
            url = self.app_url
            self.send_to(chat_id, f"Всё о прогоне и камере: кнопка ниже или в браузере {url}" if markup
                         else "Мини-приложение ещё не включено в программе у камеры.", markup)
        else:
            self.send_to(chat_id, self._help_text(self.users.get(chat_id)))

    def _control_command(self, chat_id: str, command: str, argument: str):
        """Команды управления: вход на сайт, экстренная остановка, панель кнопок. Только для тех, у кого есть право."""
        user = self.users.get(chat_id)
        if not can_control(user):
            self.send_to(chat_id, "Управлять камерой могут только админ и те, кому он дал право. "
                                  "Смотреть можно без права: /status и /app.")
            return
        if command == "/login":
            link = self.login_link(chat_id, renew=argument in ("new", "новая", "новый"))
            self.send_to(chat_id, ("Личная ссылка входа на сайт с правом управления:\n" + link
                                   + "\n\nНе пересылайте её. Если ушла не туда - /login new выдаст новую, "
                                     "прежние перестанут работать.") if link
                         else "Сайт ещё не включён в программе у камеры.")
        elif command == "/estop":
            self.send_to(chat_id, CONFIRM_ACTIONS["estop"],
                         {"inline_keyboard": [[{"text": "⛔ Да, остановить", "callback_data": "ctl!estop"},
                                               {"text": "Отмена", "callback_data": "ctl!cancel"}]]})
        else:
            rows = [[{"text": title, "callback_data": f"ctl:{action}"}] for action, title in CONTROL_BUTTONS]
            app = self._app_button()
            if app:
                rows.append([app])
            self.send_to(chat_id, "Управление камерой и прогоном. Режимы, уставка и шаги сценария - в мини-приложении.",
                         {"inline_keyboard": rows})

    def _run_control(self, chat_id: str, action: str, params: dict | None = None) -> str:
        """Действие управления через программу: она проверит права, выполнит и запишет в журнал."""
        if self._control_handler is None:
            return "управление недоступно: программа не готова"
        try:
            ok, text = self._control_handler(chat_id, action, dict(params or {}))
        except Exception as error:  # noqa: BLE001 - сбой одного действия не должен ронять бота
            return f"не выполнено: {error}"
        return ("✅ " if ok else "❌ ") + text

    def _handle_callback(self, callback: dict):
        data = str(callback.get("data") or "")
        message = callback.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        answer = ""
        user = self.users.get(chat_id)
        if data.startswith(("ctl:", "ctl!")):
            action = data[4:]
            if action == "cancel":
                answer = "Отменено"
            elif not can_control(user):
                answer = "Нет права управлять камерой"
            elif data.startswith("ctl:") and action in CONFIRM_ACTIONS:
                # Опасное действие - сначала подтверждение отдельным сообщением.
                self.send_to(chat_id, CONFIRM_ACTIONS[action],
                             {"inline_keyboard": [[{"text": "Да", "callback_data": f"ctl!{action}"},
                                                   {"text": "Отмена", "callback_data": "ctl!cancel"}]]})
            else:
                result = self._run_control(chat_id, action)
                answer = result[:190]
                self.send_to(chat_id, result)
            if "message_id" in message and data.startswith("ctl!"):
                self._queue.put(("call", ("editMessageReplyMarkup", {"chat_id": chat_id,
                                                                     "message_id": message["message_id"],
                                                                     "reply_markup": {"inline_keyboard": []}})))
        elif user is not None:
            if data.startswith("lvl:") and data[4:] in LEVELS:
                self.users.upsert(chat_id, level=data[4:])
                answer = f"Уровень: {LEVEL_TITLES[data[4:]]}"
            elif data.startswith("tog:") and data[4:] in OPTIONS:
                key = data[4:]
                self.users.upsert(chat_id, **{key: not user.get(key)})
                answer = OPTIONS[key] + (": выкл" if user.get(key) else ": вкл")
            if data.startswith(("lvl:", "tog:")) and "message_id" in message:
                self._queue.put(("call", ("editMessageText", {
                    "chat_id": chat_id, "message_id": message["message_id"],
                    "text": self._settings_text(chat_id), "reply_markup": self._settings_markup(chat_id)})))
        else:
            answer = "Сначала подпишитесь: /start"
        self._queue.put(("call", ("answerCallbackQuery", {"callback_query_id": callback.get("id", ""),
                                                          "text": answer})))

    # ------------------------------------------------------------------ тексты и кнопки

    @staticmethod
    def _help_text(user: dict | None = None) -> str:
        lines = ["Команды:", "/status - что сейчас с прогоном",
                 "/settings - что присылать", "/app - мини-приложение и сайт с подробностями",
                 "/stop - отписаться"]
        if can_control(user):
            lines += ["", f"Вы {ROLE_TITLES[user['role']]}: можете управлять камерой и прогоном.",
                      "/control - кнопки управления", "/estop - экстренная остановка камеры",
                      "/login - ссылка входа на сайт с правом управления"]
        return "\n".join(lines)

    def _settings_text(self, chat_id: str) -> str:
        user = self.users.get(chat_id) or default_user()
        flags = ", ".join(f"{title}: {'да' if user.get(key) else 'нет'}" for key, title in OPTIONS.items())
        return f"Уровень уведомлений: {LEVEL_TITLES[user['level']]}.\n{flags}."

    def _settings_markup(self, chat_id: str) -> dict:
        user = self.users.get(chat_id) or default_user()
        levels = [{"text": ("✓ " if user["level"] == level else "") + LEVEL_TITLES[level],
                   "callback_data": f"lvl:{level}"} for level in LEVELS]
        toggles = [{"text": ("✓ " if user.get(key) else "✗ ") + title, "callback_data": f"tog:{key}"}
                   for key, title in OPTIONS.items()]
        rows = [levels[:2], levels[2:], toggles]
        app = self._app_button()
        if app:
            rows.append([app])
        return {"inline_keyboard": rows}

    def _app_button(self) -> dict | None:
        url = self.app_url
        return {"text": "Открыть мини-приложение", "web_app": {"url": url}} if url else None

    def _app_markup(self) -> dict | None:
        button = self._app_button()
        return {"inline_keyboard": [[button]]} if button else None

    def _sync_menu(self):
        """Кнопка меню бота открывает мини-приложение; список команд - в меню «/»."""
        with self._lock:
            token = self._token
            url = self._app_url
            if not token or url == self._menu_url_sent:
                return
            self._menu_url_sent = url
        commands = [{"command": "status", "description": "что сейчас с прогоном"},
                    {"command": "settings", "description": "что присылать"},
                    {"command": "app", "description": "мини-приложение и сайт"},
                    {"command": "control", "description": "управление (для назначенных)"},
                    {"command": "estop", "description": "экстренная остановка (для назначенных)"},
                    {"command": "login", "description": "вход на сайт с управлением (для назначенных)"},
                    {"command": "stop", "description": "отписаться"}]
        self._queue.put(("call", ("setMyCommands", {"commands": commands})))
        button = ({"type": "web_app", "text": "Камера", "web_app": {"url": url}} if url else {"type": "commands"})
        self._queue.put(("call", ("setChatMenuButton", {"menu_button": button})))

    # ------------------------------------------------------------------ обмен

    def _call(self, method: str, data: dict, timeout: float = REQUEST_TIMEOUT_S) -> dict:
        with self._lock:
            token = self._token
        if not token:
            raise RuntimeError("токен бота не задан")
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        req = urlrequest.Request(f"{API_ROOT}/bot{token}/{method}", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
        return self._read_answer(req, timeout)

    @staticmethod
    def _read_answer(req, timeout: float) -> dict:
        try:
            with urlrequest.urlopen(req, timeout=timeout) as answer:
                payload = json.loads(answer.read().decode("utf-8"))
        except urlerror.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
            except Exception:
                raise RuntimeError(f"HTTP {error.code}") from None
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("description") or "Telegram отказал"))
        return payload

    def _post_document(self, chat_id: str, path: Path, caption: str):
        data = path.read_bytes()
        if len(data) > MAX_DOCUMENT_BYTES:
            raise RuntimeError(f"файл {path.name} больше 50 МБ")
        with self._lock:
            token = self._token
        boundary = "----chamber" + uuid.uuid4().hex
        parts = []
        for name, value in (("chat_id", chat_id), ("caption", caption)):
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        parts.append(
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{path.name}\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n").encode("utf-8") + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        req = urlrequest.Request(f"{API_ROOT}/bot{token}/sendDocument", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        self._read_answer(req, REQUEST_TIMEOUT_S)
