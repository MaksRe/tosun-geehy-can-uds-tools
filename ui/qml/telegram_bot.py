"""Telegram-бот наблюдения за прогоном: пользователи, уровни уведомлений, команды, мини-приложение.

ЗАЧЕМ
За прогоном следят несколько человек, и каждому нужно своё: технологу - всё
подряд, начальнику - только итог и аварии, дежурному ночью - только аварии.
Бот ведёт список пользователей, у каждого свой уровень уведомлений и свои
переключатели (точки, сводки, файлы). Посмотреть всё подробно можно в
мини-приложении прямо в Telegram.

ДОСТУП
- Администратор - чат, указанный в настройках программы. Он одобряет новых
  пользователей кнопками прямо в чате или в окне программы.
- Новый пользователь пишет боту /start. Если он прислал код доступа
  («/start КОД»), он одобрен сразу; иначе администратору приходит заявка.
- Мини-приложение отдаёт данные только одобренным: Telegram подписывает
  данные запуска (initData) токеном бота, программа проверяет подпись.

УРОВНИ УВЕДОМЛЕНИЙ
- «Все события» - всё, что пишет программа;
- «Важные» - выход на этапы, итоги, предупреждения и аварии, без мелочей;
- «Только аварии» - только беды: авария камеры, нет связи, прогон встал;
- «Без уведомлений» - ничего, только по запросу (/status, мини-приложение).
Отдельно: «точки» (сообщение о каждой точке), «сводки» (раз в час), «файлы»
(журнал, профиль, отчёт).

КАК УСТРОЕНО
Два своих потока: приём команд (длинный опрос getUpdates) и отправка
(очередь с повторами). Окно не ждёт сеть. Пользователи хранятся в JSON-файле.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import queue
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


def default_user(level: str = "important", points: bool = True, summaries: bool = True, files: bool = True) -> dict:
    """Настройки нового пользователя: уровень и переключатели по умолчанию из программы."""
    return {"name": "", "username": "", "approved": False, "admin": False,
            "level": level if level in LEVELS else "important",
            "points": bool(points), "summaries": bool(summaries), "files": bool(files),
            "since": time.strftime("%Y-%m-%d %H:%M")}


def wants(user: dict, level: str, kind: str = "event") -> bool:
    """Нужно ли пользователю это сообщение: по одобрению, уровню и переключателям.

    kind: «event» - событие, «point» - точка записана, «summary» - сводка,
    «file» - файл. level: info, ok, warn, bad.
    """
    if not user.get("approved"):
        return False
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

    По документации Telegram: секрет = HMAC-SHA256(ключ «WebAppData», токен бота),
    подпись = HMAC-SHA256(секрет, строка «ключ=значение» всех полей кроме hash,
    по алфавиту, через перевод строки).
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
    """Пользователи бота в JSON-файле: одобрение, уровень, переключатели. Потокобезопасно."""

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
                if user["level"] not in LEVELS:
                    user["level"] = "important"
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

    def upsert(self, chat_id, **fields) -> dict:
        """Создаёт или обновляет пользователя; возвращает его настройки."""
        with self._lock:
            user = self._users.get(str(chat_id))
            if user is None:
                user = default_user()
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

    def recipients(self, level: str, kind: str = "event") -> list[str]:
        """Кому отправить: одобренные пользователи, которым это сообщение нужно."""
        with self._lock:
            return [chat_id for chat_id, user in self._users.items() if wants(user, level, kind)]


class TelegramBot:
    """Бот наблюдения: приём команд, рассылка по пользователям, кнопка мини-приложения."""

    def __init__(self, users: TelegramUsers, status_callback: Callable[[str, bool], None] | None = None):
        self.users = users
        self._status_callback = status_callback
        self._lock = threading.Lock()
        self._token = ""
        self._admin = ""
        self._access_code = ""
        self._app_url = ""
        self._defaults = default_user()
        self._status_text = "Данных пока нет."
        self._menu_url_sent = ""
        # Последний чат, который писал боту: из него «Найти чат» берёт администратора.
        self._last_chat: tuple[str, str] | None = None
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._poll_generation = 0
        self._sender = threading.Thread(target=self._send_worker, daemon=True, name="telegram-bot-send")
        self._sender.start()
        self._poller = threading.Thread(target=self._poll_worker, daemon=True, name="telegram-bot-poll")
        self._poller.start()

    # ------------------------------------------------------------------ настройка

    def configure(self, token: str, admin_chat: str, access_code: str = "", defaults: dict | None = None):
        """Бот, администратор, код доступа и настройки новых пользователей. Пустой токен - бот молчит."""
        token = str(token or "").strip()
        admin = str(admin_chat or "").strip()
        with self._lock:
            if token != self._token:
                self._poll_generation += 1
                self._menu_url_sent = ""
            self._token = token
            self._admin = admin
            self._access_code = str(access_code or "").strip()
            if defaults:
                self._defaults = default_user(defaults.get("level", "important"), defaults.get("points", True),
                                              defaults.get("summaries", True), defaults.get("files", True))
        if admin and token:
            current = self.users.get(admin)
            if current is None or not current.get("approved") or not current.get("admin"):
                self.users.upsert(admin, approved=True, admin=True, name=(current or {}).get("name") or "администратор",
                                  level=(current or {}).get("level", "all"))
        self._sync_menu()

    def set_app_url(self, url: str):
        """Адрес мини-приложения: кнопка меню бота открывает его. Пусто - кнопки нет."""
        with self._lock:
            self._app_url = str(url or "").strip()
        self._sync_menu()

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
    def app_url(self) -> str:
        with self._lock:
            return self._app_url

    def close(self):
        self._stop.set()
        self._queue.put(None)
        for thread in (self._sender, self._poller):
            if thread.is_alive():
                thread.join(timeout=1.5)

    # ------------------------------------------------------------------ рассылка

    def notify(self, text: str, level: str = "info", kind: str = "event"):
        """Событие всем, кому оно нужно по их уровню и переключателям."""
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

    def test(self):
        """Проверка: сообщение администратору."""
        if self._admin:
            self.send_to(self._admin, "Связь с ботом наблюдения есть. Команды: /status, /settings, /app.")

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
                    if "chat not found" in last_error or "bot was blocked" in last_error:
                        break
                    if attempt + 1 < SEND_ATTEMPTS and not self._stop.wait(RETRY_PAUSE_S):
                        continue
            if last_error:
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
            if not token:
                self._stop.wait(1.0)
                continue
            if current != generation:
                generation = current
                offset = 0
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
        with self._lock:
            self._last_chat = (chat_id, str(name))
        command, _, argument = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        user = self.users.get(chat_id)

        if command == "/start":
            self._start(chat_id, name, username, argument.strip(), user)
            return
        if user is None or not user.get("approved"):
            self.send_to(chat_id, "Доступа пока нет. Отправьте /start и дождитесь одобрения администратора "
                                  "или пришлите /start КОД, если вам дали код доступа.")
            return
        if command == "/status":
            with self._lock:
                status = self._status_text
            self.send_to(chat_id, status, self._app_markup())
        elif command == "/settings":
            self.send_to(chat_id, self._settings_text(chat_id), self._settings_markup(chat_id))
        elif command == "/app":
            markup = self._app_markup()
            self.send_to(chat_id, "Мини-приложение: всё о прогоне и камере." if markup
                         else "Мини-приложение ещё не включено в программе у камеры.", markup)
        elif command == "/users" and user.get("admin"):
            self._send_users(chat_id)
        elif command == "/stop":
            self.users.upsert(chat_id, level="off")
            self.send_to(chat_id, "Уведомления выключены. Включить снова - /settings.")
        else:
            self.send_to(chat_id, self._help_text(user))

    def _start(self, chat_id: str, name: str, username: str, code: str, user: dict | None):
        with self._lock:
            access_code = self._access_code
            admin = self._admin
            defaults = dict(self._defaults)
        if user is not None and user.get("approved"):
            self.users.upsert(chat_id, name=name, username=username)
            self.send_to(chat_id, f"Вы уже подключены. Уровень уведомлений: {LEVEL_TITLES[user['level']]}.\n"
                                  + self._help_text(user), self._app_markup())
            return
        approved = bool(access_code) and code == access_code
        fields = {key: defaults[key] for key in ("level", "points", "summaries", "files")}
        self.users.upsert(chat_id, name=name, username=username, approved=approved, **fields)
        if approved:
            self._emit(f"Telegram: подключён {name} (по коду доступа).", True)
            self.send_to(chat_id, f"Готово, вы подключены. Уровень уведомлений: {LEVEL_TITLES[fields['level']]}.\n"
                                  "Изменить - /settings.", self._app_markup())
            return
        self.send_to(chat_id, "Заявка отправлена администратору. Как только он её одобрит, начнут приходить "
                              "уведомления о прогоне.")
        self._emit(f"Telegram: заявка на доступ от {name}.", True)
        if admin:
            self.send_to(admin, f"Заявка на доступ к наблюдению: {name}" + (f" (@{username})" if username else "")
                         + f", чат {chat_id}.",
                         {"inline_keyboard": [[{"text": "Одобрить", "callback_data": f"ok:{chat_id}"},
                                               {"text": "Отклонить", "callback_data": f"rm:{chat_id}"}]]})

    def _handle_callback(self, callback: dict):
        data = str(callback.get("data") or "")
        message = callback.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        user = self.users.get(chat_id)
        answer = ""
        if user is not None and user.get("approved"):
            if data.startswith("lvl:") and data[4:] in LEVELS:
                self.users.upsert(chat_id, level=data[4:])
                answer = f"Уровень: {LEVEL_TITLES[data[4:]]}"
            elif data.startswith("tog:") and data[4:] in OPTIONS:
                key = data[4:]
                self.users.upsert(chat_id, **{key: not user.get(key)})
                answer = OPTIONS[key] + (": выкл" if user.get(key) else ": вкл")
            elif user.get("admin") and data[:3] in ("ok:", "rm:", "ad:"):
                answer = self.admin_action(data[:2], data[3:])
                if "message_id" in message:
                    self._queue.put(("call", ("editMessageReplyMarkup",
                                              {"chat_id": chat_id, "message_id": message["message_id"],
                                               "reply_markup": {"inline_keyboard": []}})))
            if data.startswith(("lvl:", "tog:")) and "message_id" in message:
                self._queue.put(("call", ("editMessageText", {
                    "chat_id": chat_id, "message_id": message["message_id"],
                    "text": self._settings_text(chat_id), "reply_markup": self._settings_markup(chat_id)})))
        self._queue.put(("call", ("answerCallbackQuery", {"callback_query_id": callback.get("id", ""),
                                                          "text": answer})))

    def admin_action(self, action: str, chat_id: str) -> str:
        """Действие администратора над пользователем: ok - одобрить, rm - убрать, ad - сделать администратором."""
        user = self.users.get(chat_id)
        if user is None:
            return "Пользователь не найден"
        name = user.get("name") or chat_id
        if action == "ok":
            self.users.upsert(chat_id, approved=True)
            self.send_to(chat_id, f"Доступ одобрен. Уровень уведомлений: {LEVEL_TITLES[user['level']]}. "
                                  "Изменить - /settings.", self._app_markup())
            self._emit(f"Telegram: {name} одобрен.", True)
            return f"{name}: одобрен"
        if action == "rm":
            if chat_id == self._admin:
                return "Администратора убрать нельзя"
            self.users.remove(chat_id)
            self._emit(f"Telegram: {name} убран из наблюдения.", True)
            return f"{name}: убран"
        if action == "ad":
            self.users.upsert(chat_id, admin=not user.get("admin"), approved=True)
            return f"{name}: " + ("администратор" if not user.get("admin") else "обычный пользователь")
        return ""

    # ------------------------------------------------------------------ тексты и кнопки

    def _help_text(self, user: dict) -> str:
        lines = ["Команды:", "/status - что сейчас с прогоном", "/settings - уровень уведомлений и что присылать",
                 "/app - мини-приложение с подробностями", "/stop - выключить уведомления"]
        if user.get("admin"):
            lines.append("/users - пользователи и заявки")
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

    def _send_users(self, chat_id: str):
        users = self.users.all()
        if not users:
            self.send_to(chat_id, "Пользователей нет.")
            return
        for other_id, user in users.items():
            state = "администратор" if user.get("admin") else ("одобрен" if user.get("approved") else "ждёт одобрения")
            text = f"{user.get('name') or other_id}" + (f" (@{user['username']})" if user.get("username") else "") \
                + f": {state}, {LEVEL_TITLES[user['level']]}."
            buttons = []
            if not user.get("approved"):
                buttons.append({"text": "Одобрить", "callback_data": f"ok:{other_id}"})
            if other_id != self._admin:
                buttons.append({"text": "Убрать", "callback_data": f"rm:{other_id}"})
                buttons.append({"text": "Админ ±", "callback_data": f"ad:{other_id}"})
            self.send_to(chat_id, text, {"inline_keyboard": [buttons]} if buttons else None)

    def _sync_menu(self):
        """Кнопка меню бота открывает мини-приложение; список команд - в меню «/»."""
        with self._lock:
            token = self._token
            url = self._app_url
            if not token or url == self._menu_url_sent:
                return
            self._menu_url_sent = url
        commands = [{"command": "status", "description": "что сейчас с прогоном"},
                    {"command": "settings", "description": "уровень уведомлений"},
                    {"command": "app", "description": "мини-приложение"},
                    {"command": "users", "description": "пользователи (для администратора)"},
                    {"command": "stop", "description": "выключить уведомления"}]
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

    def find_chat(self, callback: Callable[[str, str], None]):
        """Чат администратора: последний, кто писал боту. Бот сам принимает сообщения,
        поэтому отдельный запрос к Telegram не нужен (он бы помешал приёму команд)."""
        with self._lock:
            last = self._last_chat
            token = self._token
        if not token:
            callback("", "сначала впишите токен бота и включите Telegram")
        elif last is None:
            callback("", "боту ещё никто не писал: напишите ему /start и повторите")
        else:
            callback(last[0], f"найден чат «{last[1]}»")
