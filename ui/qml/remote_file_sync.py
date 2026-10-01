"""Копия журналов прогона на рабочее место.

ЗАЧЕМ
Журналы пишутся на компьютере у камеры. Чтобы разбирать их на своём месте, не
дожидаясь конца прогона, каждый сохранённый файл сразу копируется туда, где его
видно издалека:
- в сетевую папку (общий ресурс Windows вида \\\\сервер\\папка или подключённый диск);
- или на сервер по SFTP.

КАК УСТРОЕНО
Копирование идёт в своём потоке, окно не ждёт сеть. Файл, поставленный в
очередь несколько раз подряд, копируется один раз - самой свежей версией. Не
скопированный из-за сети файл копируется заново при следующем сохранении: журнал
всегда пишется целиком, поэтому на той стороне всегда полная последняя версия.
"""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

MODE_FOLDER = "folder"
MODE_SFTP = "sftp"


@dataclass
class FileSyncConfig:
    """Куда копировать журналы."""

    enabled: bool = False
    mode: str = MODE_FOLDER
    folder: str = ""
    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""
    remote_dir: str = "/chamber"

    def problem(self) -> str:
        """Чего не хватает в настройке, или пустая строка."""
        if self.mode == MODE_SFTP:
            if not self.host.strip() or not self.username.strip():
                return "не заполнены сервер и имя пользователя SFTP"
            return ""
        if not self.folder.strip():
            return "не указана папка"
        return ""


class RemoteFileSync:
    """Очередь копирования файлов: каждая запись - (файл, подпапка назначения)."""

    def __init__(self, status_callback: Callable[[str, bool], None] | None = None):
        self._status_callback = status_callback
        self._config = FileSyncConfig()
        self._lock = threading.Lock()
        self._pending: dict[str, str] = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="remote-file-sync")
        self._thread.start()

    def configure(self, config: FileSyncConfig):
        with self._lock:
            self._config = FileSyncConfig(**config.__dict__)

    def enqueue(self, path, subdir: str = ""):
        """Ставит файл в очередь. Повтор того же файла заменяет прежний."""
        with self._lock:
            if not self._config.enabled:
                return
            self._pending[str(path)] = str(subdir or "")
        self._wake.set()

    def close(self):
        self._stop.set()
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.5)

    # ------------------------------------------------------------------ поток

    def _emit(self, text: str, ok: bool):
        if self._status_callback is not None:
            self._status_callback(str(text), bool(ok))

    def _worker(self):
        while not self._stop.is_set():
            self._wake.wait(timeout=0.5)
            self._wake.clear()
            with self._lock:
                batch = dict(self._pending)
                self._pending.clear()
                config = FileSyncConfig(**self._config.__dict__)
            if not batch:
                continue
            problem = config.problem()
            if problem:
                self._emit(f"Копия журналов не сделана: {problem}.", False)
                continue
            try:
                if config.mode == MODE_SFTP:
                    self._copy_sftp(config, batch)
                else:
                    self._copy_folder(config, batch)
                names = ", ".join(Path(item).name for item in batch)
                self._emit(f"Скопировано: {names}.", True)
            except Exception as error:  # noqa: BLE001 - любая ошибка сети одинаково значит «повторить позже»
                self._emit(f"Копия журналов не сделана: {error}. Повторю при следующем сохранении.", False)

    @staticmethod
    def _copy_folder(config: FileSyncConfig, batch: dict[str, str]):
        root = Path(config.folder.strip())
        for local, subdir in batch.items():
            source = Path(local)
            if not source.is_file():
                continue
            target_dir = root / subdir if subdir else root
            target_dir.mkdir(parents=True, exist_ok=True)
            # Сначала во временный файл: на той стороне никто не увидит половину журнала.
            temporary = target_dir / (source.name + ".part")
            shutil.copyfile(source, temporary)
            temporary.replace(target_dir / source.name)

    @staticmethod
    def _copy_sftp(config: FileSyncConfig, batch: dict[str, str]):
        try:
            import paramiko
        except ImportError:
            raise RuntimeError("пакет paramiko не установлен") from None

        transport = paramiko.Transport((config.host.strip(), int(config.port)))
        try:
            transport.connect(username=config.username.strip(), password=config.password)
            client = paramiko.SFTPClient.from_transport(transport)
            try:
                for local, subdir in batch.items():
                    source = Path(local)
                    if not source.is_file():
                        continue
                    base = config.remote_dir.strip().replace("\\", "/") or "/"
                    if not base.startswith("/"):
                        base = "/" + base
                    remote_dir = PurePosixPath(base) / subdir if subdir else PurePosixPath(base)
                    current = "/"
                    for part in [item for item in str(remote_dir).split("/") if item]:
                        current = str(PurePosixPath(current) / part)
                        try:
                            client.stat(current)
                        except OSError:
                            client.mkdir(current)
                    temporary = str(remote_dir / (source.name + ".part"))
                    final = str(remote_dir / source.name)
                    client.put(str(source), temporary)
                    try:
                        client.posix_rename(temporary, final)
                    except (OSError, AttributeError):
                        try:
                            client.remove(final)
                        except OSError:
                            pass
                        client.rename(temporary, final)
            finally:
                client.close()
        finally:
            transport.close()
