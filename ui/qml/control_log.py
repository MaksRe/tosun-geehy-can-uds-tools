"""Журнал действий управления камерой и прогоном: кто, когда, откуда, что сделал.

ЗАЧЕМ
Управлять камерой можно из окна программы, с сайта и из Telegram, и делают это
разные люди. Чтобы потом было ясно, кто остановил камеру или поменял шаг
сценария, каждое действие записывается вместе с именем человека, откуда оно
пришло, подробностями (что было и что стало) и итогом.

ГДЕ
logs/control/control_ГГГГ-ММ.csv - по файлу на месяц, разделитель «;»,
кодировка UTF-8 с меткой (открывается в Excel). Последние записи хранятся и в
памяти: их показывают окно программы, сайт и мини-приложение.
"""

from __future__ import annotations

import csv
import io
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

COLUMNS = ("Время", "Кто", "Откуда", "Действие", "Подробности", "Итог")
KEEP_IN_MEMORY = 200


class ControlLog:
    """Журнал действий: запись в файл месяца и последние записи в памяти. Потокобезопасно."""

    def __init__(self, folder: Path | None):
        self.folder = Path(folder) if folder is not None else None
        self._lock = threading.Lock()
        self._recent: deque = deque(maxlen=KEEP_IN_MEMORY)
        self._load_recent()

    def _path(self, moment: datetime) -> Path | None:
        if self.folder is None:
            return None
        return self.folder / f"control_{moment:%Y-%m}.csv"

    def _load_recent(self):
        """После перезапуска программы последние действия снова видны."""
        path = self._path(datetime.now())
        if path is None:
            return
        try:
            rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter=";"))
        except OSError:
            return
        for row in rows[1:][-KEEP_IN_MEMORY:]:
            if len(row) >= len(COLUMNS):
                self._recent.appendleft(self._entry(*row[:5], ok=row[5].startswith("выполнено"), result=row[5]))

    @staticmethod
    def _entry(time_text, who, channel, action, details, ok, result) -> dict:
        return {"time": str(time_text), "who": str(who), "channel": str(channel), "action": str(action),
                "details": str(details), "ok": bool(ok), "result": str(result)}

    def add(self, who: str, channel: str, action: str, details: str, ok: bool, result: str) -> dict:
        """Записывает действие. Сбой записи файла не мешает самому действию."""
        moment = datetime.now()
        outcome = ("выполнено" if ok else "не выполнено") + (f": {result}" if result else "")
        entry = self._entry(moment.strftime("%d.%m.%Y %H:%M:%S"), who, channel, action, details, ok, outcome)
        with self._lock:
            self._recent.appendleft(entry)
            path = self._path(moment)
            if path is not None:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    new = not path.exists()
                    with path.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as handle:
                        writer = csv.writer(handle, delimiter=";")
                        if new:
                            writer.writerow(COLUMNS)
                        writer.writerow([entry["time"], who, channel, action, details, outcome])
                except OSError:
                    pass
        return entry

    def recent(self, count: int = 30) -> list[dict]:
        """Последние действия, свежие первыми."""
        with self._lock:
            return [dict(entry) for entry in list(self._recent)[:count]]

    @property
    def current_path(self) -> str:
        path = self._path(datetime.now())
        return str(path) if path is not None else ""
