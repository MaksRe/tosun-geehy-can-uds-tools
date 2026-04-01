from __future__ import annotations

from dataclasses import dataclass
import fnmatch
from pathlib import Path, PurePosixPath
import queue
import threading
from typing import Callable


@dataclass
class CollectorSftpConfig:
    """Хранит параметры SFTP-подключения для фоновой выгрузки CSV."""

    enabled: bool = False
    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""
    remote_dir: str = "/incoming/csv"

    def is_ready(self) -> bool:
        """Проверяет, что конфигурация заполнена для выполнения выгрузки."""
        return bool(self.enabled and self.host.strip() and self.username.strip() and self.remote_dir.strip())


class CollectorSftpUploader:
    """Выполняет фоновую выгрузку CSV-файлов сессии коллектора по SFTP."""

    def __init__(self, status_callback: Callable[[str, bool], None] | None = None):
        self._status_callback = status_callback
        self._config = CollectorSftpConfig()
        self._queue: queue.Queue[Path | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="collector-sftp-uploader")
        self._thread.start()

    @property
    def config(self) -> CollectorSftpConfig:
        """Возвращает текущую конфигурацию SFTP-выгрузки."""
        return self._config

    def update_config(self, config: CollectorSftpConfig):
        """Обновляет конфигурацию выгрузки и сохраняет её для следующих задач."""
        self._config = CollectorSftpConfig(
            enabled=bool(config.enabled),
            host=str(config.host),
            port=int(config.port),
            username=str(config.username),
            password=str(config.password),
            remote_dir=str(config.remote_dir),
        )

    def enqueue_session_directory(self, session_directory: Path):
        """Добавляет каталог сессии в очередь на выгрузку CSV-файлов."""
        self._queue.put(Path(session_directory))

    def close(self):
        """Останавливает фоновый поток и завершает обработку очереди."""
        self._stop_event.set()
        self._queue.put(None)
        if self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def _emit_status(self, text: str, busy: bool):
        if self._status_callback is None:
            return
        self._status_callback(str(text), bool(busy))

    @staticmethod
    def _iter_csv_files(base_directory: Path) -> list[Path]:
        files: list[Path] = []
        for item in base_directory.rglob("*"):
            if not item.is_file():
                continue
            if fnmatch.fnmatch(item.name.lower(), "*.csv"):
                files.append(item)
        return sorted(files)

    @staticmethod
    def _join_remote_path(base_remote_dir: str, session_name: str, file_name: str) -> str:
        base = str(base_remote_dir).strip().replace("\\", "/")
        if not base.startswith("/"):
            base = "/" + base
        normalized_base = str(PurePosixPath(base))
        return str(PurePosixPath(normalized_base) / session_name / file_name)

    @staticmethod
    def _ensure_remote_dir(sftp_client, remote_dir: str):
        normalized = str(PurePosixPath(remote_dir))
        parts = [part for part in normalized.split("/") if part]
        current = "/"
        for part in parts:
            current = str(PurePosixPath(current) / part)
            try:
                sftp_client.stat(current)
            except Exception:
                sftp_client.mkdir(current)

    def _upload_directory(self, session_directory: Path):
        config = self._config
        if not config.is_ready():
            self._emit_status("SFTP: выгрузка пропущена, конфиг не заполнен.", False)
            return

        files = self._iter_csv_files(session_directory)
        if len(files) <= 0:
            self._emit_status("SFTP: CSV-файлы для выгрузки не найдены.", False)
            return

        self._emit_status("SFTP: идет выгрузка CSV...", True)
        try:
            import paramiko
        except Exception:
            self._emit_status("SFTP: пакет paramiko не установлен.", False)
            return

        transport = None
        sftp_client = None
        try:
            transport = paramiko.Transport((config.host.strip(), int(config.port)))
            transport.connect(username=config.username.strip(), password=config.password)
            sftp_client = paramiko.SFTPClient.from_transport(transport)

            session_name = session_directory.name
            target_root = self._join_remote_path(config.remote_dir, session_name, "")
            self._ensure_remote_dir(sftp_client, target_root)

            uploaded_count = 0
            for local_file in files:
                remote_file = self._join_remote_path(config.remote_dir, session_name, local_file.name)
                sftp_client.put(str(local_file), remote_file)
                uploaded_count += 1

            self._emit_status(f"SFTP: выгружено CSV: {uploaded_count}.", False)
        except Exception as exc:
            self._emit_status(f"SFTP: ошибка выгрузки: {str(exc)}", False)
        finally:
            try:
                if sftp_client is not None:
                    sftp_client.close()
            except Exception:
                pass
            try:
                if transport is not None:
                    transport.close()
            except Exception:
                pass

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if task is None:
                self._queue.task_done()
                break
            try:
                self._upload_directory(Path(task))
            finally:
                self._queue.task_done()
