from __future__ import annotations

import csv
from pathlib import Path


class CollectorCsvManager:
    """Writes collector values to a single per-node CSV file."""

    def __init__(self, node_hex: str, session_dir: Path):
        self._node_hex = str(node_hex).lower()
        session_dir.mkdir(parents=True, exist_ok=True)
        self._csv_path = session_dir / f"{self._node_hex}.csv"

        self._init_csv(
            self._csv_path,
            (
                "Время",
                "Период",
                "Температура (°C)",
                "Топливо (%)",
            ),
        )

    @staticmethod
    def _init_csv(csv_path: Path, header: tuple[str, ...]):
        with csv_path.open("w", newline="", encoding="utf-8") as file:
            csv.writer(file, delimiter=";").writerow(header)

    @staticmethod
    def _format_value(value: int | float | str) -> str:
        if isinstance(value, float):
            return f"{value:.1f}".replace(".", ",")
        if isinstance(value, int):
            return str(value)
        return str(value)

    @staticmethod
    def _append(csv_path: Path, row: tuple[str, ...]):
        with csv_path.open("a", newline="", encoding="utf-8") as file:
            csv.writer(file, delimiter=";").writerow(row)

    def append_metric(
        self,
        measurement_time: str,
        period_ticks: int,
        temperature_c: float,
        fuel_percent: float,
    ):
        row = (
            self._format_value(str(measurement_time)),
            self._format_value(int(period_ticks)),
            self._format_value(float(temperature_c)),
            self._format_value(float(fuel_percent)),
        )
        self._append(self._csv_path, row)


class CollectorCombinedCsvManager:
    """Writes one combined CSV with shared time column and per-node metrics."""

    def __init__(self, session_dir: Path, file_name: str = "all_nodes.csv"):
        session_dir.mkdir(parents=True, exist_ok=True)
        self._csv_path = session_dir / str(file_name)
        self._header: list[str] = ["Время"]
        self._node_columns: dict[str, tuple[str, str, str]] = {}
        self._ordered_nodes: list[str] = []
        self._init_csv()

    def _init_csv(self):
        with self._csv_path.open("w", newline="", encoding="utf-8") as file:
            csv.writer(file, delimiter=";").writerow(self._header)

    @staticmethod
    def _normalize_node_hex(node_hex: str) -> str:
        return str(node_hex).strip().lower()

    @staticmethod
    def _format_value(value: int | float | str) -> str:
        if isinstance(value, float):
            return f"{value:.1f}".replace(".", ",")
        if isinstance(value, int):
            return str(value)
        return str(value)

    @staticmethod
    def _column_names_for_node(node_hex: str) -> tuple[str, str, str]:
        normalized = CollectorCombinedCsvManager._normalize_node_hex(node_hex)
        return (
            f"{normalized} Период",
            f"{normalized} Топливо (%)",
            f"{normalized} Температура (°C)",
        )

    @staticmethod
    def _as_int(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _as_float(value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _expand_header_for_new_nodes(self, new_nodes: list[str]):
        if len(new_nodes) == 0:
            return

        old_header = list(self._header)
        new_columns: list[str] = []
        for node_hex in new_nodes:
            normalized = self._normalize_node_hex(node_hex)
            if normalized in self._node_columns:
                continue
            columns = self._column_names_for_node(normalized)
            self._node_columns[normalized] = columns
            self._ordered_nodes.append(normalized)
            new_columns.extend(columns)

        if len(new_columns) == 0:
            return

        self._header = old_header + new_columns

        existing_rows: list[dict[str, str]] = []
        with self._csv_path.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file, delimiter=";")
            for row in reader:
                existing_rows.append({column: str(row.get(column, "")) for column in old_header})

        with self._csv_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self._header, delimiter=";")
            writer.writeheader()
            for row in existing_rows:
                normalized_row = {column: str(row.get(column, "")) for column in self._header}
                writer.writerow(normalized_row)

    def _ensure_nodes(self, node_hexes: list[str]):
        new_nodes: list[str] = []
        for node_hex in node_hexes:
            normalized = self._normalize_node_hex(node_hex)
            if not normalized or normalized in self._node_columns:
                continue
            new_nodes.append(normalized)
        self._expand_header_for_new_nodes(new_nodes)

    def append_snapshot(self, measurement_time: str, nodes_snapshot: dict[str, dict[str, object]]):
        if len(nodes_snapshot) == 0:
            return

        normalized_snapshot: dict[str, dict[str, object]] = {}
        for raw_node_hex, raw_metrics in nodes_snapshot.items():
            node_hex = self._normalize_node_hex(raw_node_hex)
            if not node_hex or not isinstance(raw_metrics, dict):
                continue
            normalized_snapshot[node_hex] = raw_metrics

        if len(normalized_snapshot) == 0:
            return

        self._ensure_nodes(list(normalized_snapshot.keys()))
        row: dict[str, str] = {column: "" for column in self._header}
        row["Время"] = self._format_value(str(measurement_time))

        for node_hex in self._ordered_nodes:
            metrics = normalized_snapshot.get(node_hex)
            if metrics is None:
                continue
            period_column, fuel_column, temperature_column = self._node_columns[node_hex]
            row[period_column] = self._format_value(self._as_int(metrics.get("period", 0)))
            row[fuel_column] = self._format_value(self._as_float(metrics.get("fuel", 0.0)))
            row[temperature_column] = self._format_value(self._as_float(metrics.get("temperature", 0.0)))

        with self._csv_path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self._header, delimiter=";")
            writer.writerow(row)
