"""Сервер мини-приложения Telegram: наблюдение за прогоном с телефона.

ЗАЧЕМ
Камера стоит далеко от рабочего места. Удалённый рабочий стол даёт полный
доступ, но чтобы просто взглянуть, всё ли в порядке, он тяжёл, а с телефона
неудобен. Программа у камеры сама отдаёт мини-приложение: его открывают кнопкой
в боте Telegram, и в нём всё о камере, плате и ходе прогона.

ЧТО ОТДАЁТ
- «/» и «/app» - само мини-приложение;
- «/api/state» - состояние прогона, настройки пользователя (и список
  пользователей - администратору);
- «/api/settings» - пользователь меняет свои уведомления;
- «/api/users» - администратор одобряет и убирает пользователей;
- «/api/sendfile» - прислать журнал или профиль в чат пользователя.
Запросы к «/api/...» несут данные запуска Telegram (заголовок
X-Telegram-Init-Data); без верной подписи и одобрения в боте данных нет.
Для отладки в сети по ключу доступа остаются «/status.json» и «/file».

Страница только показывает. Управлять прибором через неё нельзя намеренно:
любое действие идёт через удалённый рабочий стол, где оператор видит всё окно.

КАК УСТРОЕНО
Сервер работает в своём потоке. Данные для него собирает поток окна и кладёт
готовым снимком под замок, поэтому сервер никогда не трогает объекты Qt.
Если задан ключ доступа, без него в адресе страница не открывается.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

# Сколько файлов каждой папки показывать на странице: свежие сверху.
FILES_PER_FOLDER = 30


def local_addresses() -> list[str]:
    """Адреса этого компьютера в сети: по ним страницу открывают с других машин."""
    found: list[str] = []
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = str(item[4][0])
            if not address.startswith("127.") and address not in found:
                found.append(address)
    except OSError:
        pass
    # Адрес, через который компьютер выходит в сеть: соединение UDP ничего не отправляет.
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 1))
            address = str(probe.getsockname()[0])
            if not address.startswith("127.") and address not in found:
                found.insert(0, address)
        finally:
            probe.close()
    except OSError:
        pass
    return found


class RemoteStatusServer:
    """Веб-сервер страницы состояния: запуск, остановка и свежий снимок данных."""

    def __init__(self, page_html: str):
        self._page_html = str(page_html)
        self._lock = threading.Lock()
        self._snapshot_text = "{}"
        self._folders: dict[str, Path] = {}
        self._key = ""
        # Доступ мини-приложения: проверка подписи Telegram и действия пользователя (см. set_access).
        self._access = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port = 0

    # ------------------------------------------------------------------ данные

    def set_snapshot(self, snapshot: dict):
        """Кладёт свежий снимок состояния. Вызывается из потока окна."""
        text = json.dumps(snapshot, ensure_ascii=False)
        with self._lock:
            self._snapshot_text = text

    def set_folders(self, folders: dict[str, Path]):
        """Папки, из которых разрешено скачивать журналы: подпись -> путь."""
        with self._lock:
            self._folders = {str(title): Path(path) for title, path in folders.items()}

    def set_access(self, access):
        """Доступ мини-приложения: объект с методами user_for, update_settings, admin_action,
        users_view, send_file. None - мини-приложение без данных."""
        with self._lock:
            self._access = access

    def set_key(self, key: str):
        """Ключ доступа. Пустой ключ означает открытый доступ из сети."""
        with self._lock:
            self._key = str(key or "")

    # ------------------------------------------------------------------ запуск

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int:
        return self._port

    @property
    def host(self) -> str:
        return getattr(self, "_host", "")

    def start(self, port: int, host: str = "0.0.0.0") -> str:
        """Запускает сервер. host 127.0.0.1 - только для туннеля, из сети не виден.
        Возвращает пустую строку или текст ошибки."""
        self.stop()
        handler = self._make_handler()
        try:
            server = ThreadingHTTPServer((str(host), int(port)), handler)
        except OSError as error:
            return f"порт {int(port)} занят или недоступен: {error}"
        server.daemon_threads = True
        self._server = server
        # Порт 0 означает «любой свободный»: запоминается тот, что выдала система.
        self._port = int(server.server_address[1])
        self._host = str(host)
        self._thread = threading.Thread(target=server.serve_forever, daemon=True, name="remote-status-server")
        self._thread.start()
        return ""

    def stop(self):
        """Останавливает сервер, если он запущен."""
        server = self._server
        self._server = None
        if server is None:
            return
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    # ------------------------------------------------------------------ ответы

    def _files_listing(self) -> list[dict]:
        """Свежие файлы разрешённых папок: подпись папки, имя, размер, время."""
        with self._lock:
            folders = dict(self._folders)
        listing = []
        for title, folder in folders.items():
            try:
                files = [item for item in folder.iterdir() if item.is_file()]
            except OSError:
                continue
            files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
            for item in files[:FILES_PER_FOLDER]:
                stat = item.stat()
                listing.append({
                    "folder": title,
                    "name": item.name,
                    "size": int(stat.st_size),
                    "mtime": float(stat.st_mtime),
                    "url": "file?folder=" + quote(title) + "&name=" + quote(item.name),
                })
        return listing

    def _resolve_file(self, folder_title: str, name: str) -> Path | None:
        """Файл из разрешённой папки или None. Пути с переходом наверх отвергаются."""
        with self._lock:
            folder = self._folders.get(str(folder_title))
        if folder is None or not name or "/" in name or "\\" in name or name in (".", ".."):
            return None
        candidate = (folder / name).resolve()
        try:
            candidate.relative_to(folder.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _make_handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ChamberStatus/1.0"

            def log_message(self, *_args):
                # Каждый запрос страницы раз в две секунды засорил бы консоль.
                return

            def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for name, value in (extra or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, payload):
                self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")

            def _miniapp_user(self):
                """Пользователь мини-приложения по подписанным данным запуска или None."""
                with owner._lock:
                    access = owner._access
                if access is None:
                    return None, None
                init_data = self.headers.get("X-Telegram-Init-Data", "")
                found = access.user_for(init_data)
                return (access, found) if found else (access, None)

            def _read_json(self) -> dict:
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 65536)
                    data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                    return data if isinstance(data, dict) else {}
                except (ValueError, OSError):
                    return {}

            def do_POST(self):
                parsed = urlparse(self.path)
                access, found = self._miniapp_user()
                if found is None:
                    self._json(401, {"error": "нет доступа: откройте через бота и дождитесь одобрения"})
                    return
                chat_id, user = found
                body = self._read_json()
                if parsed.path == "/api/settings":
                    self._json(200, {"me": access.update_settings(chat_id, body)})
                elif parsed.path == "/api/users" and user.get("admin"):
                    text = access.admin_action(chat_id, str(body.get("action", "")), str(body.get("id", "")))
                    self._json(200, {"text": text, "users": access.users_view()})
                elif parsed.path == "/api/sendfile":
                    self._json(200, {"text": access.send_file(chat_id, str(body.get("folder", "")),
                                                              str(body.get("name", "")))})
                else:
                    self._json(404, {"error": "нет такого действия"})

            def do_GET(self):
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)

                # Мини-приложение отдаётся всем: данные - только через «/api/...» с подписью Telegram.
                if parsed.path in ("/", "/index.html", "/app"):
                    self._send(200, owner._page_html.encode("utf-8"), "text/html; charset=utf-8")
                    return

                if parsed.path == "/api/state":
                    access, found = self._miniapp_user()
                    if found is None:
                        self._json(401, {"error": "нет доступа: откройте через бота и дождитесь одобрения"})
                        return
                    chat_id, user = found
                    with owner._lock:
                        text = owner._snapshot_text
                    payload = json.loads(text)
                    payload["me"] = dict(user, id=chat_id)
                    payload["files"] = owner._files_listing()
                    if user.get("admin"):
                        payload["users"] = access.users_view()
                    self._json(200, payload)
                    return

                # Отладка в сети: снимок и файлы только по ключу доступа; без ключа - закрыто.
                with owner._lock:
                    key = owner._key
                given = (query.get("key") or [""])[0]
                if not key or not secrets.compare_digest(given, key):
                    self._send(403, "Наблюдение - через мини-приложение в Telegram.".encode("utf-8"),
                               "text/plain; charset=utf-8")
                    return

                if parsed.path == "/status.json":
                    with owner._lock:
                        text = owner._snapshot_text
                    payload = json.loads(text)
                    payload["files"] = owner._files_listing()
                    self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                               "application/json; charset=utf-8")
                    return

                if parsed.path == "/file":
                    target = owner._resolve_file((query.get("folder") or [""])[0], (query.get("name") or [""])[0])
                    if target is None:
                        self._send(404, "Файл не найден.".encode("utf-8"), "text/plain; charset=utf-8")
                        return
                    try:
                        data = target.read_bytes()
                    except OSError:
                        self._send(500, "Файл не читается.".encode("utf-8"), "text/plain; charset=utf-8")
                        return
                    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                    self._send(200, data, content_type, {
                        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(target.name)})
                    return

                self._send(404, b"Not found", "text/plain; charset=utf-8")

        return Handler
