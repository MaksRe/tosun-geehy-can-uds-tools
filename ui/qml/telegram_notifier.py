"""Уведомления о ходе прогона в Telegram.

ЗАЧЕМ
Прогон в камере длится часами, а рабочее место далеко. Оператору не нужно
каждые десять минут заглядывать в удалённый стол: о важном программа пишет
сама - плата устоялась, точка записана, прибор замолчал, профиль записан.

КАК УСТРОЕНО
Сообщения уходят в своём потоке через официальный HTTP-интерфейс Telegram
(api.telegram.org), окно при этом не замирает, даже если сеть медленная.
Сообщение, которое не ушло, повторяется несколько раз, а итог попыток
сообщается окну. Номер чата программа умеет найти сама: достаточно написать
боту любое сообщение и нажать «Найти чат».
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from pathlib import Path
from typing import Callable
from urllib import error as urlerror
from urllib import request as urlrequest

API_ROOT = "https://api.telegram.org"
REQUEST_TIMEOUT_S = 15.0
SEND_ATTEMPTS = 3
RETRY_PAUSE_S = 5.0
# Telegram не берёт файлы больше 50 МБ от бота.
MAX_DOCUMENT_BYTES = 49 * 1024 * 1024


class TelegramNotifier:
    """Очередь сообщений и файлов для одного бота и одного чата."""

    def __init__(self, status_callback: Callable[[str, bool], None] | None = None):
        self._status_callback = status_callback
        self._token = ""
        self._chat_id = ""
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="telegram-notifier")
        self._thread.start()

    def configure(self, token: str, chat_id: str):
        """Задаёт бота и чат. Пустые значения означают «не отправлять»."""
        self._token = str(token or "").strip()
        self._chat_id = str(chat_id or "").strip()

    @property
    def ready(self) -> bool:
        return bool(self._token) and bool(self._chat_id)

    def send_text(self, text: str):
        """Ставит сообщение в очередь."""
        if self.ready:
            self._queue.put(("text", str(text)))

    def send_document(self, path, caption: str = ""):
        """Ставит файл в очередь: журнал или профиль приходят прямо в чат."""
        if self.ready:
            self._queue.put(("document", (str(path), str(caption))))

    def find_chat(self, callback: Callable[[str, str], None]):
        """Ищет чат по последнему сообщению боту. Ответ: (номер чата, пояснение)."""
        token = self._token
        threading.Thread(target=self._find_chat_worker, args=(token, callback), daemon=True,
                         name="telegram-find-chat").start()

    def close(self):
        """Останавливает поток отправки."""
        self._stop.set()
        self._queue.put(None)
        if self._thread.is_alive():
            self._thread.join(timeout=1.5)

    # ------------------------------------------------------------------ поток

    def _emit(self, text: str, ok: bool):
        if self._status_callback is not None:
            self._status_callback(str(text), bool(ok))

    def _worker(self):
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
                    if kind == "text":
                        self._post_json("sendMessage", {"chat_id": self._chat_id, "text": payload,
                                                        "disable_web_page_preview": True})
                        self._emit("Telegram: сообщение отправлено.", True)
                    else:
                        path, caption = payload
                        self._post_document(Path(path), caption)
                        self._emit(f"Telegram: отправлен файл {Path(path).name}.", True)
                    last_error = ""
                    break
                except Exception as error:  # noqa: BLE001 - любая ошибка сети одинаково повод повторить
                    last_error = str(error)
                    if attempt + 1 < SEND_ATTEMPTS and not self._stop.wait(RETRY_PAUSE_S):
                        continue
            if last_error:
                self._emit(f"Telegram: не отправлено после {SEND_ATTEMPTS} попыток: {last_error}", False)

    # ------------------------------------------------------------------ обмен

    def _url(self, method: str, token: str | None = None) -> str:
        return f"{API_ROOT}/bot{token if token is not None else self._token}/{method}"

    @staticmethod
    def _read_answer(req) -> dict:
        try:
            with urlrequest.urlopen(req, timeout=REQUEST_TIMEOUT_S) as answer:
                payload = json.loads(answer.read().decode("utf-8"))
        except urlerror.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
            except Exception:
                raise RuntimeError(f"HTTP {error.code}") from None
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("description") or "Telegram отказал"))
        return payload

    def _post_json(self, method: str, data: dict, token: str | None = None) -> dict:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        req = urlrequest.Request(self._url(method, token), data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
        return self._read_answer(req)

    def _post_document(self, path: Path, caption: str):
        data = path.read_bytes()
        if len(data) > MAX_DOCUMENT_BYTES:
            raise RuntimeError(f"файл {path.name} больше 50 МБ")
        boundary = "----chamber" + uuid.uuid4().hex
        parts = []
        for name, value in (("chat_id", self._chat_id), ("caption", caption)):
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        parts.append(
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{path.name}\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n").encode("utf-8") + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        req = urlrequest.Request(self._url("sendDocument"), data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        self._read_answer(req)

    def _find_chat_worker(self, token: str, callback):
        if not token:
            callback("", "сначала впишите токен бота")
            return
        try:
            payload = self._post_json("getUpdates", {"limit": 50, "timeout": 0}, token=token)
        except Exception as error:  # noqa: BLE001
            callback("", f"Telegram не ответил: {error}")
            return
        chats = []
        for update in payload.get("result") or []:
            message = update.get("message") or update.get("channel_post") or {}
            chat = message.get("chat") or {}
            if "id" in chat:
                title = chat.get("title") or " ".join(
                    item for item in (chat.get("first_name"), chat.get("last_name")) if item) or chat.get("username") or ""
                chats.append((str(chat["id"]), str(title)))
        if not chats:
            callback("", "боту ещё никто не писал: напишите ему любое сообщение и повторите")
            return
        chat_id, title = chats[-1]
        callback(chat_id, f"найден чат «{title}»" if title else "чат найден")

