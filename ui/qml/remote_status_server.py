"""Сервер сайта и мини-приложения Telegram: наблюдение за прогоном с телефона и компьютера.

ЗАЧЕМ
Камера стоит далеко от рабочего места. Удалённый рабочий стол даёт полный
доступ, но чтобы просто взглянуть, всё ли в порядке, он тяжёл, а с телефона
неудобен. Программа у камеры сама отдаёт страницу: её открывают по адресу в
любом браузере или кнопкой в боте Telegram, и на ней всё о камере, плате и
ходе прогона.

ДОСТУП
Смотреть может любой, кто знает адрес: без входа. Управлять камерой и
прогоном - только админ и те, кому он дал право. Кто это, сервер узнаёт по
подписи Telegram (мини-приложение, заголовок X-Telegram-Init-Data) или по
ключу личной ссылки входа из бота (/login, обычный браузер, заголовок
X-Web-Token). Права проверяет и действия записывает в журнал программа.

ЧТО ОТДАЁТ
- «/» и «/app» - страница;
- «/api/state» - состояние прогона, журнал действий, список журналов; если
  человек известен - его уведомления и права (админу - ещё подписчики);
- «/api/file» - скачать журнал;
- «/api/settings», «/api/sendfile» - свои уведомления, журнал в свой чат;
- «/api/control» - действие управления; «/api/role» - права (админ);
- «/api/login» - ссылка входа на сайт с правом управления.

КАК УСТРОЕНО
Сервер работает в своём потоке. Данные для него собирает поток окна и кладёт
готовым снимком под замок, поэтому сервер никогда не трогает объекты Qt.
"""

from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

# Сколько файлов каждой папки показывать на странице: свежие сверху.
FILES_PER_FOLDER = 30


class RemoteStatusServer:
    """Веб-сервер страницы состояния: запуск, остановка и свежий снимок данных."""

    def __init__(self, page_html: str):
        self._page_html = str(page_html)
        self._lock = threading.Lock()
        self._snapshot_text = "{}"
        self._folders: dict[str, Path] = {}
        # Связь с ботом: кто открыл страницу в Telegram, его настройки и чат (см. set_access).
        self._access = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port = 0
        self._host = ""

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
        """Связь с ботом: объект с методами user_for, update_settings, send_file, bot_info. None - без бота."""
        with self._lock:
            self._access = access

    # ------------------------------------------------------------------ запуск

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int:
        return self._port

    @property
    def host(self) -> str:
        return self._host

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
                    "url": "api/file?folder=" + quote(title) + "&name=" + quote(item.name),
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
                # Каждый запрос страницы раз в несколько секунд засорил бы консоль.
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

            def _telegram_user(self):
                """Кто открыл страницу: (связь с ботом, номер чата, откуда) или (связь, None, "")."""
                with owner._lock:
                    access = owner._access
                if access is None:
                    return None, None, ""
                chat_id = access.user_for(self.headers.get("X-Telegram-Init-Data", ""))
                if chat_id is not None:
                    return access, chat_id, "Telegram"
                token = self.headers.get("X-Web-Token", "")
                chat_id = access.user_for_token(token) if token else None
                return access, chat_id, ("сайт" if chat_id is not None else "")

            def _read_json(self) -> dict:
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 65536)
                    data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                    return data if isinstance(data, dict) else {}
                except (ValueError, OSError):
                    return {}

            def _send_file(self, target):
                """Файл журнала целиком, с именем для сохранения."""
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

            def do_POST(self):
                parsed = urlparse(self.path)
                access, chat_id, channel = self._telegram_user()
                if chat_id is None:
                    self._json(403, {"error": "нужно войти: откройте страницу кнопкой в боте или по ссылке /login"})
                    return
                body = self._read_json()
                if parsed.path == "/api/control":
                    ok, text = access.control(chat_id, channel, body)
                    self._json(200, {"ok": ok, "text": text})
                elif parsed.path == "/api/role":
                    ok, text = access.control(chat_id, channel, {"action": "role", "id": str(body.get("id", "")),
                                                                 "role": str(body.get("role", ""))})
                    self._json(200, {"ok": ok, "text": text, "users": access.users_view()})
                elif parsed.path == "/api/login":
                    link = access.login_link(chat_id, bool(body.get("renew")))
                    self._json(200, {"url": link, "text": "" if link else "нет права управлять или сайт без адреса"})
                elif parsed.path == "/api/settings":
                    self._json(200, {"me": access.update_settings(chat_id, body)})
                elif parsed.path == "/api/sendfile":
                    self._json(200, {"text": access.send_file(chat_id, str(body.get("folder", "")),
                                                              str(body.get("name", "")))})
                else:
                    self._json(404, {"error": "нет такого действия"})

            def do_GET(self):
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)

                if parsed.path in ("/", "/index.html", "/app"):
                    self._send(200, owner._page_html.encode("utf-8"), "text/html; charset=utf-8")
                    return

                if parsed.path in ("/api/state", "/status.json"):
                    with owner._lock:
                        text = owner._snapshot_text
                    payload = json.loads(text)
                    payload["files"] = owner._files_listing()
                    access, chat_id, channel = self._telegram_user()
                    if access is not None:
                        payload["bot"] = access.bot_info()
                        if chat_id is not None:
                            me = access.me(chat_id)
                            payload["me"] = dict(me, channel=channel)
                            if me.get("isAdmin"):
                                payload["users"] = access.users_view()
                    self._json(200, payload)
                    return

                if parsed.path in ("/api/file", "/file"):
                    self._send_file(owner._resolve_file((query.get("folder") or [""])[0],
                                                        (query.get("name") or [""])[0]))
                    return

                self._send(404, b"Not found", "text/plain; charset=utf-8")

        return Handler
