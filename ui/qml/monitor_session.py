"""Постоянная история проверки уровня: измерения, условия и неизменный итог прогона."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def thin_points(points: list, limit: int = 1000) -> list:
    """Чтобы длинный график не тормозил окно, сокращает данные с сохранением минимумов и максимумов."""
    if len(points) <= limit:
        return points
    step = max(1, (len(points) + limit // 4 - 1) // (limit // 4))
    result = []
    for offset in range(0, len(points), step):
        group = points[offset:offset + step]
        indices = {0, len(group) - 1,
                   min(range(len(group)), key=lambda i: group[i][1]),
                   max(range(len(group)), key=lambda i: group[i][1])}
        result.extend(group[index] for index in sorted(indices))
    return result


def write_json(path: Path, payload: dict) -> None:
    """Для сохранности предыдущего файла заменяет JSON только после полной записи новой версии."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class MonitorSession:
    """Хранит отдельную историю каждого прогона без ограничения живого буфера."""

    def __init__(self, folder: Path, metadata: dict):
        """Для восстановления прогона связывает его каталог, условия и историю плат."""
        self.folder = Path(folder)
        self.metadata = metadata
        self.histories: dict[str, list] = {}
        self.gaps: dict[str, int] = {}
        self.snapshot: dict = {}

    def level_gaps(self) -> int:
        """Считает пропуски проверки уровня, исключая учебные платы из смешанного прогона."""
        stages = self.metadata.get("board_stages") or {}
        return sum(count for key, count in self.gaps.items()
                   if not stages or stages.get(key, {}).get("check_only"))

    @classmethod
    def create(cls, base: Path, metadata: dict) -> "MonitorSession":
        """Для разделения испытаний создаёт новый каталог и указатель на последний прогон."""
        folder = Path(base) / f"level_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:6]}"
        folder.mkdir(parents=True)
        meta = dict(metadata, schema=1, active=True, started=datetime.now().isoformat(timespec="seconds"))
        session = cls(folder, meta)
        write_json(folder / "session.json", meta)
        with (folder / "measurements.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream, delimiter=";").writerow([
                "Время", "CAN-адрес", "Плата", "Состояние", "Уровень (%)", "Отклонение (%)",
                "Температура трубки (°C)", "Температура платы (°C)", "Температура камеры (°C)",
                "Исходный период", "Вид топлива", "Компенсированный период", "Шаг (°C)", "Этап",
            ])
        write_json(Path(base) / "last_level_run.json", {"folder": folder.name})
        return session

    @classmethod
    def load(cls, folder: Path) -> "MonitorSession":
        """Для продолжения испытания читает историю и отмечает повреждённые записи как пропуски."""
        folder = Path(folder)
        metadata = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        if metadata.get("schema") != 1 or not isinstance(metadata.get("boards"), list):
            raise ValueError("неизвестный формат истории уровня")
        session = cls(folder, metadata)
        session.metadata["damaged_records"] = 0
        source = folder / "measurements.jsonl"
        if source.exists():
            with source.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        record = json.loads(line)
                        key = str(record["key"])
                        sample = record.get("sample")
                        if sample is not None:
                            for field in ("wall", "level", "tube", "board", "comp"):
                                float(sample[field])
                            session.histories.setdefault(key, []).append(sample)
                        else:
                            session.gaps[key] = session.gaps.get(key, 0) + 1
                    except (ValueError, TypeError, KeyError):
                        session.metadata["damaged_records"] = session.metadata.get("damaged_records", 0) + 1
        snapshot = folder / "result.json"
        if snapshot.exists():
            session.snapshot = json.loads(snapshot.read_text(encoding="utf-8"))
        return session

    @classmethod
    def latest(cls, base: Path) -> "MonitorSession | None":
        """Для показа после перезапуска открывает последний прогон внутри папки журналов."""
        pointer = Path(base) / "last_level_run.json"
        if not pointer.exists():
            return None
        name = json.loads(pointer.read_text(encoding="utf-8"))["folder"]
        folder = (Path(base) / name).resolve()
        if folder.parent != Path(base).resolve():
            raise ValueError("история находится вне папки журналов")
        return cls.load(folder)

    def append(self, key: str, label: str, sample: dict | None, context: dict) -> None:
        """Для независимого пересчёта сразу дописывает измерение или пропуск в JSONL и CSV."""
        record = dict(context, key=key, label=label, sample=sample,
                      time=datetime.now().isoformat(timespec="milliseconds"))
        path = self.folder / "measurements.jsonl"
        # После обрыва питания новая запись начинается отдельно от недописанной строки.
        if path.exists() and path.stat().st_size:
            with path.open("rb") as stream:
                stream.seek(-1, 2)
                needs_newline = stream.read(1) != b"\n"
        else:
            needs_newline = False
        with path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(("\n" if needs_newline else "") + json.dumps(record, ensure_ascii=False) + "\n")
        data = sample or {}
        error = None if sample is None or sample.get("truth") is None else sample["level"] / 10 - sample["truth"]
        address = context.get("address")
        values = [record["time"], f"0x{address:02X}" if address is not None else key, label,
                  "измерение" if sample is not None else "нет свежих данных",
                  None if sample is None else sample["level"] / 10, error,
                  None if sample is None else sample["tube"] / 10,
                  None if sample is None else sample["board"] / 10,
                  context.get("chamber"), data.get("main"), data.get("media"), data.get("comp"),
                  context.get("node"), context.get("stage")]
        with (self.folder / "measurements.csv").open("a", encoding="utf-8", newline="") as stream:
            csv.writer(stream, delimiter=";").writerow([
                "" if value is None else str(value).replace(".", ",") if isinstance(value, float) else value
                for value in values
            ])
        if sample is None:
            self.gaps[key] = self.gaps.get(key, 0) + 1

    def finish(self, view: dict, report: dict, reason: str) -> None:
        """Для неизменного итога сохраняет снимок отчёта и закрывает сбор данных этого прогона."""
        self.snapshot = json.loads(json.dumps({"monitor": view, "report": report}, ensure_ascii=False))
        write_json(self.folder / "result.json", self.snapshot)
        self.metadata.update(active=False, ended=datetime.now().isoformat(timespec="seconds"), reason=reason)
        write_json(self.folder / "session.json", self.metadata)
