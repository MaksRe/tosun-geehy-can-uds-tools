"""Публичный HTTPS-адрес для мини-приложения Telegram: туннель Cloudflare.

ЗАЧЕМ
Telegram открывает мини-приложение только по адресу https:// из интернета, а
программа работает на ноутбуке у камеры за заводской сетью. Бесплатный туннель
Cloudflare (cloudflared, без регистрации) выдаёт такой адрес вида
https://<слова>.trycloudflare.com и проводит запросы к нашему маленькому
серверу на этом компьютере. Адрес меняется при каждом запуске туннеля - бот сам
перенастраивает кнопку мини-приложения.

Что видно через туннель - только мини-приложение. Данные оно получает лишь
для одобренных в боте пользователей: каждый запрос подписан Telegram.

КАК УСТРОЕНО
cloudflared запускается отдельным процессом без окна; адрес берётся из его
вывода. Если процесс завершился, через паузу запускается снова.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
RESTART_PAUSE_S = 15.0


def find_cloudflared(configured: str = "") -> str:
    """Путь к cloudflared: из настроек, рядом с программой или в PATH. Пусто - не найден."""
    candidates = []
    if configured:
        candidates.append(Path(configured))
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    candidates += [base / "cloudflared.exe", base / "cloudflared", base / "tools" / "cloudflared.exe"]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("cloudflared")
    return found or ""


def parse_url(line: str) -> str:
    """Адрес туннеля из строки вывода cloudflared или пусто."""
    match = URL_PATTERN.search(str(line))
    return match.group(0) if match else ""


class CloudflareTunnel:
    """Туннель Cloudflare к локальному порту: запуск, адрес, перезапуск, остановка."""

    def __init__(self, on_url: Callable[[str], None], on_status: Callable[[str, bool], None]):
        self._on_url = on_url
        self._on_status = on_status
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._url = ""
        self._port = 0
        self._exe = ""

    @property
    def url(self) -> str:
        with self._lock:
            return self._url

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: int, exe: str):
        """Запускает туннель к http://127.0.0.1:port. Повторный вызов с теми же данными ничего не меняет."""
        if self.running and port == self._port and exe == self._exe:
            return
        self.stop()
        self._port = int(port)
        self._exe = str(exe)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="cloudflare-tunnel")
        self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            process = self._process
            self._process = None
            had_url = bool(self._url)
            self._url = ""
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    process.kill()
                except Exception:  # noqa: BLE001
                    pass
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        if had_url:
            self._on_url("")

    def _worker(self):
        while not self._stop.is_set():
            command = [self._exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self._port}"]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, creationflags=flags)
            except OSError as error:
                self._on_status(f"cloudflared не запустился: {error}", False)
                self._stop.wait(RESTART_PAUSE_S)
                continue
            with self._lock:
                self._process = process
            self._on_status("Туннель запускается: жду адрес от Cloudflare...", True)
            for raw in iter(process.stdout.readline, b""):
                if self._stop.is_set():
                    break
                url = parse_url(raw.decode("utf-8", errors="replace"))
                if url and url != self.url:
                    with self._lock:
                        self._url = url
                    self._on_url(url)
                    self._on_status(f"Туннель работает: {url}", True)
            process.wait()
            with self._lock:
                self._process = None
                lost = bool(self._url)
                self._url = ""
            if lost:
                self._on_url("")
            if not self._stop.is_set():
                self._on_status(f"Туннель остановился (код {process.returncode}), перезапуск через "
                                f"{int(RESTART_PAUSE_S)} с.", False)
                self._stop.wait(RESTART_PAUSE_S)
