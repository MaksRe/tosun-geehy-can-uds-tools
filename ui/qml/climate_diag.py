"""Журнал диагностики связи с климатической камерой.

ЗАЧЕМ
Связь с камерой рвётся по разным причинам: не тот режим порта Moxa, перевёрнутая
пара кабеля, не тот адрес или конец строки на пульте, отказ камеры, зависший
драйвер. По одному слову «нет связи» причину не найти. Журнал сохраняет всё, что
нужно для разбора, и его можно переслать разработчику одним файлом.

ЧТО ПИШЕТСЯ
- Начало сеанса: версия программы, Python, pyserial, Windows, настройки камеры,
  список COM-портов и режим портов Moxa UPort из реестра Windows.
- Открытие порта с фактическими параметрами, переподключения, смена связи
  «есть / нет», команды оператора, поиск камеры, проверка связи.
- Каждый обмен байтами (TX и RX в hex и тексте, задержка ответа, итог).
  Чтобы файл за сутки прогона не разрастался, по умолчанию обмены держит
  «чёрный ящик» в памяти и сбрасывает в файл только вокруг ошибки. Первые
  обмены после подключения пишутся всегда, а переключатель «каждый обмен в
  файл» пишет всё подряд.
- Раз в минуту - сводка: показание камеры и счётчики обмена.

Файлы: logs/chamber/chamber_ГГГГ-ММ-ДД.log (UTF-8), хранятся 30 дней. Отчёт
диагностики - logs/chamber/report_ГГГГ-ММ-ДД_ЧЧ-ММ-СС.txt.
"""

from __future__ import annotations

import json
import platform
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

# Режим порта Moxa UPort из значения SerInterface в реестре. Коды те же, что в
# драйвере Moxa для Linux (drivers/usb/serial/mxuport.c: MX_INT_RS232 = 0 ...).
MOXA_INTERFACES = {0: "RS-232", 1: "RS-485 2W", 2: "RS-422", 3: "RS-485 4W"}
# Режимы, в которых работает четырёхпроводная связь с камерой ESPEC.
MOXA_ESPEC_OK = (2, 3)


def hex_bytes(data: bytes) -> str:
    """Байты в hex через пробел: «31 2C 4D 4F 4E 3F 0D 0A»."""
    return " ".join(f"{byte:02X}" for byte in bytes(data or b""))


def show_bytes(data: bytes) -> str:
    """Байты как текст, концы строк и непечатные символы видны: «1,MON?\\r\\n»."""
    parts = []
    for byte in bytes(data or b""):
        if byte == 0x0D:
            parts.append("\\r")
        elif byte == 0x0A:
            parts.append("\\n")
        elif 0x20 <= byte <= 0x7E:
            parts.append(chr(byte))
        else:
            parts.append(f"\\x{byte:02x}")
    return "".join(parts)


def moxa_interface_text(code) -> str:
    """Код SerInterface словами: 3 - «RS-485 4W»."""
    try:
        return MOXA_INTERFACES.get(int(code), f"неизвестный код {code}")
    except (TypeError, ValueError):
        return "не задан"


def moxa_registry_info() -> list[dict]:
    """Настройки портов Moxa UPort из реестра Windows (только чтение).

    Главное здесь - режим интерфейса: из коробки RS-232, а камере ESPEC нужен
    RS-422 или RS-485 4W. Ветка HKLM\\SYSTEM\\CurrentControlSet\\Enum\\MXUPORT
    читается без прав администратора. Не Windows или нет Moxa - пустой список.
    """
    try:
        import winreg
    except ImportError:
        return []
    found = []

    def walk(path: str, depth: int):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        except OSError:
            return
        with key:
            if path.endswith("Device Parameters"):
                values = {}
                index = 0
                while True:
                    try:
                        name, value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    values[name] = value
                    index += 1
                if "PortName" in values:
                    code = values.get("SerInterface")
                    found.append({
                        "port": str(values.get("PortName")),
                        "interface_code": code,
                        "interface": moxa_interface_text(code),
                        "espec_ok": code is not None and int(code) in MOXA_ESPEC_OK,
                        "values": {name: value for name, value in values.items() if not isinstance(value, bytes)},
                        "key": "HKLM\\" + path,
                    })
                return
            if depth <= 0:
                return
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(key, index)
                except OSError:
                    break
                walk(f"{path}\\{name}", depth - 1)
                index += 1

    walk(r"SYSTEM\CurrentControlSet\Enum\MXUPORT", 3)
    return found


def environment_info(project_root: Path | None = None) -> dict:
    """Окружение программы: версия, Python, библиотеки, ОС - без них отчёт не разобрать."""
    info = {
        "время": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "версия программы": "",
        "собранная программа (exe)": bool(getattr(sys, "frozen", False)),
        "python": sys.version.split()[0],
        "python.exe": sys.executable,
        "windows": platform.platform(),
        "pyserial": "не установлен",
        "pyside6": "",
    }
    if project_root is not None:
        try:
            info["версия программы"] = (Path(project_root) / ".build_version").read_text(encoding="utf-8").strip()
        except OSError:
            info["версия программы"] = "неизвестна"
    if getattr(sys, "frozen", False) and info["версия программы"] in ("", "неизвестна"):
        # У собранной программы версия - в имени exe: tosun-geehy-can-uds-tools_v1.0.13.exe.
        stem = Path(sys.executable).stem
        info["версия программы"] = stem.rsplit("_v", 1)[1] if "_v" in stem else stem
    try:
        import serial

        info["pyserial"] = str(getattr(serial, "VERSION", "?"))
    except ImportError:
        pass
    try:
        import PySide6

        info["pyside6"] = str(PySide6.__version__)
    except ImportError:
        info["pyside6"] = "нет"
    return info


class ChamberDiagLog:
    """Журнал связи с камерой: файл по дням, память для окна, чёрный ящик обменов и счётчики.

    Вызывается и из окна, и из потока связи, поэтому всё под одним замком.
    directory=None - только память (проверки и заглушки).
    """

    MEMORY_LINES = 400
    BLACKBOX_LINES = 60
    # Сколько обменов после подключения пишется в файл всегда: начало связи разбирается чаще всего.
    SESSION_WIRE_LINES = 40
    SUMMARY_EVERY_S = 60.0
    KEEP_DAYS = 30

    def __init__(self, directory: Path | None, now=datetime.now, monotonic=time.monotonic):
        self.directory = Path(directory) if directory is not None else None
        self._now = now
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self.verbose = False
        self._lines: deque = deque(maxlen=self.MEMORY_LINES)
        self._events: deque = deque(maxlen=self.MEMORY_LINES)
        self._blackbox: deque = deque(maxlen=self.BLACKBOX_LINES)
        self._seq = 0
        self._dumped_seq = 0
        self._session_wire = 0
        self._last_summary = -1e9
        self.write_error = ""
        self.last_report = ""
        self.reset_stats()
        self._cleanup()

    # ------------------------------------------------------------------ счётчики

    def reset_stats(self):
        """Счётчики обмена с начала сеанса связи."""
        self.stats = {
            "exchanges": 0, "answers": 0, "silence": 0, "garbage": 0, "delimiter": 0, "cut": 0,
            "refused": 0, "errors": 0, "opens": 0, "open_errors": 0,
            "latency_sum_ms": 0.0, "latency_max_ms": 0.0,
            "last_ok": "", "last_error": "", "last_error_time": "",
        }

    def note_exchange(self, outcome: str, latency_ms: float | None = None, detail: str = ""):
        """Итог одного обмена: ok, silence, garbage, delimiter, cut, refused или error."""
        with self._lock:
            stats = self.stats
            stats["exchanges"] += 1
            if outcome in ("ok", "refused"):
                stats["answers"] += 1
                if latency_ms is not None:
                    stats["latency_sum_ms"] += float(latency_ms)
                    stats["latency_max_ms"] = max(stats["latency_max_ms"], float(latency_ms))
                stats["last_ok"] = self._now().strftime("%H:%M:%S")
            key = outcome if outcome in stats else "errors"
            if outcome != "ok":
                stats[key] += 1
                stats["last_error"] = detail or outcome
                stats["last_error_time"] = self._now().strftime("%H:%M:%S")

    def stats_text(self) -> str:
        """Счётчики одной строкой для окна и сводки."""
        stats = self.stats
        answers = stats["answers"]
        average = stats["latency_sum_ms"] / answers if answers else 0.0
        return (f"обменов {stats['exchanges']}, ответов {answers}, молчаний {stats['silence']}, "
                f"мусора {stats['garbage']}, другой конец строки {stats['delimiter']}, обрывов {stats['cut']}, "
                f"отказов {stats['refused']}, сбоев {stats['errors']}; задержка ответа средняя {average:.0f} мс, "
                f"наибольшая {stats['latency_max_ms']:.0f} мс")

    # ------------------------------------------------------------------ запись

    def file_path(self) -> Path | None:
        if self.directory is None:
            return None
        return self.directory / f"chamber_{self._now().strftime('%Y-%m-%d')}.log"

    def _stamp(self) -> str:
        return self._now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def _format(self, level: str, kind: str, text: str) -> str:
        return f"{self._stamp()} [{level:<5}] [{kind:<7}] {text}"

    def _write(self, lines: list[str]):
        """Дописывает строки в файл дня. Ошибка записи не ломает связь, а показывается в окне."""
        path = self.file_path()
        if path is None or not lines:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(lines) + "\n")
            self.write_error = ""
        except OSError as error:
            self.write_error = f"журнал камеры не пишется: {error}"

    def event(self, kind: str, text: str, level: str = "INFO"):
        """Событие: в файл, в память и в список окна."""
        line = self._format(level, kind, text)
        with self._lock:
            self._lines.append(line)
            self._events.append(line)
            self._write([line])

    def wire(self, kind: str, text: str):
        """Обмен байтами (TX/RX): в чёрный ящик, а в файл - если включено или идёт начало сеанса."""
        line = self._format("WIRE", kind, text)
        with self._lock:
            self._seq += 1
            self._blackbox.append((self._seq, line))
            if self.verbose or self._session_wire > 0:
                self._session_wire = max(0, self._session_wire - 1)
                self._dumped_seq = self._seq
                self._lines.append(line)
                self._write([line])

    def error(self, kind: str, text: str, with_traceback: bool = False):
        """Ошибка: сначала последние обмены из чёрного ящика (ещё не записанные), затем сама ошибка."""
        line = self._format("ERROR", kind, text)
        lines = []
        with self._lock:
            fresh = [entry for seq, entry in self._blackbox if seq > self._dumped_seq]
            if fresh:
                lines.append(self._format("INFO", "BLACKBX", f"последние обмены перед ошибкой ({len(fresh)}):"))
                lines.extend(fresh)
                self._dumped_seq = self._seq
            lines.append(line)
            if with_traceback:
                trace = traceback.format_exc().rstrip()
                if trace and trace != "NoneType: None":
                    lines.extend("    " + part for part in trace.splitlines())
            self._lines.extend(lines)
            self._events.append(line)
            self._write(lines)

    def session_start(self, title: str, info: dict):
        """Начало сеанса связи: заголовок с окружением, настройками и портами."""
        self.reset_stats()
        with self._lock:
            self._session_wire = self.SESSION_WIRE_LINES
            self._last_summary = self._monotonic()
        self.event("SESSION", "=" * 20 + f" подключение: {title} " + "=" * 20)
        for name, value in info.items():
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
            self.event("SESSION", f"{name}: {text}")

    def maybe_summary(self, reading_text: str):
        """Раз в минуту - сводка: показание камеры и счётчики. По ней видно, когда начались сбои."""
        now = self._monotonic()
        with self._lock:
            if now - self._last_summary < self.SUMMARY_EVERY_S:
                return
            self._last_summary = now
        self.event("SUMMARY", f"{reading_text}; {self.stats_text()}")

    # ------------------------------------------------------------------ окно и отчёт

    def recent_events(self, count: int = 30) -> list[str]:
        with self._lock:
            return list(self._events)[-count:]

    def view(self) -> dict:
        """Состояние журнала для окна."""
        path = self.file_path()
        return {
            "path": "" if path is None else str(path),
            "directory": "" if self.directory is None else str(self.directory),
            "verbose": bool(self.verbose),
            "stats": self.stats_text(),
            "lastOk": self.stats["last_ok"],
            "lastError": self.stats["last_error"],
            "lastErrorTime": self.stats["last_error_time"],
            "writeError": self.write_error,
            "events": list(reversed(self.recent_events(30))),
            "report": self.last_report,
        }

    def report_text(self, sections: dict) -> str:
        """Отчёт для разработчика: окружение и состояние разделами, затем весь журнал из памяти."""
        out = ["ОТЧЁТ ДИАГНОСТИКИ СВЯЗИ С КЛИМАТИЧЕСКОЙ КАМЕРОЙ",
               f"Создан: {self._now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
        for title, value in sections.items():
            out.append(f"== {title} ==")
            if isinstance(value, str):
                out.append(value)
            elif isinstance(value, list):
                out.extend(str(item) if isinstance(item, str) else json.dumps(item, ensure_ascii=False, default=str)
                           for item in value)
            else:
                out.append(json.dumps(value, ensure_ascii=False, indent=2, default=str))
            out.append("")
        out.append("== Статистика обмена с начала сеанса ==")
        out.append(self.stats_text())
        out.append(f"последний ответ: {self.stats['last_ok'] or '—'}; последняя ошибка: "
                   f"{self.stats['last_error_time'] or '—'} {self.stats['last_error']}")
        out.append("")
        with self._lock:
            lines = list(self._lines)
            blackbox = [entry for _seq, entry in self._blackbox]
        out.append(f"== Журнал из памяти (последние {len(lines)} строк) ==")
        out.extend(lines)
        out.append("")
        out.append(f"== Чёрный ящик: последние обмены байтами ({len(blackbox)}) ==")
        out.extend(blackbox)
        return "\n".join(out) + "\n"

    def save_report(self, sections: dict) -> Path | None:
        """Сохраняет отчёт рядом с журналами и возвращает путь к нему."""
        if self.directory is None:
            return None
        path = self.directory / f"report_{self._now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
        text = self.report_text(sections)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        self.last_report = str(path)
        self.event("REPORT", f"отчёт диагностики сохранён: {path}")
        return path

    def _cleanup(self):
        """Удаляет журналы и отчёты старше KEEP_DAYS дней, чтобы папка не росла бесконечно."""
        if self.directory is None or not self.directory.exists():
            return
        border = self._now() - timedelta(days=self.KEEP_DAYS)
        for path in list(self.directory.glob("chamber_*.log")) + list(self.directory.glob("report_*.txt")):
            try:
                if datetime.fromtimestamp(path.stat().st_mtime) < border:
                    path.unlink()
            except OSError:
                continue
