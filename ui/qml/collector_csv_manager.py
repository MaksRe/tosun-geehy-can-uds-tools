from __future__ import annotations

import csv
from pathlib import Path

CSV_WRITE_ENCODING = "utf-8"
CSV_READ_ENCODING = "utf-8-sig"


class CollectorCsvManager:
    """Writes collector values to a single per-node CSV file."""

    # Порядок колонок: сначала то, что нужно для температурной калибровки, затем
    # расчётный уровень. Обе температуры названы полностью, иначе их невозможно
    # различить в журнале камеры. Список один на весь класс, чтобы заголовок
    # нельзя было обновить в одном месте и забыть в другом.
    _COLUMNS: tuple[str, ...] = (
        "Время",
        "Период основного контура",
        "Период контура вида топлива",
        "Температура топлива (°C)",
        "Температура платы (°C)",
        "Топливо (%)",
        "Топл.(J1939)",
        "Топливо из периода (%)",
    )


    def __init__(self, node_hex: str, session_dir: Path):
        self._node_hex = str(node_hex).lower()
        session_dir.mkdir(parents=True, exist_ok=True)
        self._csv_path = session_dir / f"{self._node_hex}.csv"
        self._empty_ticks = -1
        self._full_ticks = -1
        self._empty_known = False
        self._full_known = False

        self._init_csv(self._csv_path, self._COLUMNS)
        self._update_metadata_if_needed(0, 0, empty_known=False, full_known=False)

    @staticmethod
    def _init_csv(csv_path: Path, header: tuple[str, ...]):
        with csv_path.open("w", newline="", encoding=CSV_WRITE_ENCODING) as file:
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
        with csv_path.open("a", newline="", encoding=CSV_WRITE_ENCODING) as file:
            csv.writer(file, delimiter=";").writerow(row)

    def _metadata_rows(self) -> list[list[str]]:
        formula = "Топливо из периода (%)=((Период-empty)*100)/(full-empty)"
        empty_text = str(int(self._empty_ticks)) if self._empty_known else "не получено"
        full_text = str(int(self._full_ticks)) if self._full_known else "не получено"
        width = len(self._COLUMNS)
        title_row = [f"Узел {self._node_hex}"] + [""] * (width - 1)
        calibration_row = [f"Калибровка: empty={empty_text}; full={full_text}"]
        calibration_row += [""] * (width - 2) + [formula]
        return [title_row, calibration_row]

    @staticmethod
    def _looks_like_header_or_meta(row: list[str]) -> bool:
        if len(row) == 0:
            return True
        joined = ";".join(str(cell) for cell in row).strip().casefold()
        if not joined:
            return True
        markers = ("узел", "калибровк", "формул", "время", "период", "топлив", "температур", "time", "fuel", "temp")
        return any(marker in joined for marker in markers)

    def _read_data_rows(self) -> list[list[str]]:
        if not self._csv_path.exists():
            return []
        with self._csv_path.open("r", newline="", encoding=CSV_READ_ENCODING) as file:
            rows = list(csv.reader(file, delimiter=";"))
        data_rows: list[list[str]] = []
        for row in rows:
            normalized = [str(cell) for cell in row]
            if self._looks_like_header_or_meta(normalized):
                continue
            if len(normalized) < 6:
                normalized.extend([""] * (6 - len(normalized)))
            data_rows.append(normalized[:6])
        return data_rows

    def _rewrite_with_metadata(self):
        data_rows = self._read_data_rows()
        with self._csv_path.open("w", newline="", encoding=CSV_WRITE_ENCODING) as file:
            writer = csv.writer(file, delimiter=";")
            for meta_row in self._metadata_rows():
                writer.writerow(meta_row)
            writer.writerow(self._COLUMNS)
            for row in data_rows:
                writer.writerow(row)

    def _update_metadata_if_needed(self, empty_ticks: int, full_ticks: int, *, empty_known: bool, full_known: bool):
        normalized_empty = int(empty_ticks)
        normalized_full = int(full_ticks)
        normalized_empty_known = bool(empty_known)
        normalized_full_known = bool(full_known)
        if (
            normalized_empty == self._empty_ticks
            and normalized_full == self._full_ticks
            and normalized_empty_known == self._empty_known
            and normalized_full_known == self._full_known
            and self._csv_path.exists()
        ):
            return
        self._empty_ticks = normalized_empty
        self._full_ticks = normalized_full
        self._empty_known = normalized_empty_known
        self._full_known = normalized_full_known
        self._rewrite_with_metadata()

    def append_metric(
        self,
        measurement_time: str,
        period_ticks: int,
        temperature_c: float,
        fuel_percent: float,
        board_temperature_c: float | None = None,
        media_ticks: int | None = None,
        fuel_j1939_percent: float | None = None,
        fuel_from_period_x10: int | None = None,
        empty_ticks: int = 0,
        full_ticks: int = 0,
        empty_known: bool = False,
        full_known: bool = False,
    ):
        self._update_metadata_if_needed(empty_ticks, full_ticks, empty_known=empty_known, full_known=full_known)
        if fuel_from_period_x10 is None:
            fuel_from_period_x10 = int(round(float(fuel_percent) * 10.0))
        fuel_from_period_percent = float(fuel_from_period_x10) / 10.0
        row = (
            self._format_value(str(measurement_time)),
            self._format_value(int(period_ticks)),
            self._format_value(int(media_ticks)) if media_ticks is not None else "",
            self._format_value(float(temperature_c)),
            self._format_value(float(board_temperature_c)) if board_temperature_c is not None else "",
            self._format_value(float(fuel_percent)),
            self._format_value(float(fuel_j1939_percent)) if fuel_j1939_percent is not None else "",
            self._format_value(float(fuel_from_period_percent)),
        )
        self._append(self._csv_path, row)


class CollectorCombinedCsvManager:
    """Writes one combined CSV with shared time column and per-node metrics."""

    # Порядок метрик на узел. Обе температуры названы полностью: в журнале
    # камеры их иначе не различить. Период контура вида топлива нужен для
    # расчёта коэффициентов, без него прогон в камере бесполезен.
    _NODE_METRIC_LABELS: tuple[str, ...] = (
        "Период основного контура",
        "Период контура вида топлива",
        "Температура топлива (°C)",
        "Температура платы (°C)",
        "Топливо (%)",
        "Топл.(J1939)",
        "Топливо из периода (%)",
    )

    def __init__(self, session_dir: Path, file_name: str = "all_nodes.csv"):
        session_dir.mkdir(parents=True, exist_ok=True)
        self._csv_path = session_dir / str(file_name)
        self._header: list[str] = ["Время"]
        self._node_columns: dict[str, tuple[str, ...]] = {}
        self._node_calibration: dict[str, tuple[int, int, bool, bool]] = {}
        self._ordered_nodes: list[str] = []
        self._init_csv()

    def _init_csv(self):
        self._write_full_file([])

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
    def _column_names_for_node(node_hex: str) -> tuple[str, ...]:
        normalized = CollectorCombinedCsvManager._normalize_node_hex(node_hex)
        return tuple(
            f"{normalized} {label}" for label in CollectorCombinedCsvManager._NODE_METRIC_LABELS
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

    @staticmethod
    def _as_bool(value: object, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return bool(default)
        text = str(value).strip().casefold()
        if text in ("1", "true", "yes", "on", "да", "истина"):
            return True
        if text in ("0", "false", "no", "off", "нет", "ложь"):
            return False
        return bool(default)

    @staticmethod
    def _is_header_like(cell: str, *, allow_node: bool = False) -> bool:
        normalized = str(cell).strip().casefold()
        if not normalized:
            return False
        keywords = ("время", "период", "топлив", "температур", "time", "fuel", "temp")
        if any(keyword in normalized for keyword in keywords):
            return True
        if allow_node and ("узел" in normalized or "node" in normalized):
            return True
        return False

    def _group_header_row(self) -> list[str]:
        row: list[str] = ["Время"]
        for node_hex in self._ordered_nodes:
            row.extend([f"Узел {node_hex}"] + [""] * (len(self._NODE_METRIC_LABELS) - 1))
        return row

    def _calibration_row(self) -> list[str]:
        row: list[str] = [""]
        formula = "Топливо из периода (%)=((Период-empty)*100)/(full-empty)"
        for node_hex in self._ordered_nodes:
            empty_ticks, full_ticks, empty_known, full_known = self._node_calibration.get(
                node_hex, (0, 0, False, False)
            )
            empty_text = str(int(empty_ticks)) if empty_known else "не получено"
            full_text = str(int(full_ticks)) if full_known else "не получено"
            calibration = [f"empty={empty_text}", f"full={full_text}"]
            calibration += [""] * (len(self._NODE_METRIC_LABELS) - len(calibration) - 1) + [formula]
            row.extend(calibration)
        return row

    def _columns_header_row(self) -> list[str]:
        row: list[str] = [""]
        for _ in self._ordered_nodes:
            row.extend(list(self._NODE_METRIC_LABELS))
        return row

    @staticmethod
    def _is_columns_header_row(row: list[str]) -> bool:
        """Точный признак строки колонок: пустое время и первая метрика узла следом.

        Сравнение точное, а не по ключевым словам: в данных может встретиться
        любой текст, и по совпадению слов живая строка исчезла бы из файла.
        """
        if len(row) < 2:
            return False
        first_metric = CollectorCombinedCsvManager._NODE_METRIC_LABELS[0]
        return str(row[0]).strip() == "" and str(row[1]).strip().casefold() == first_metric.casefold()

    def _read_existing_rows(self, header: list[str]) -> list[dict[str, str]]:
        if not self._csv_path.exists():
            return []

        with self._csv_path.open("r", newline="", encoding=CSV_READ_ENCODING) as file:
            rows = list(csv.reader(file, delimiter=";"))

        if len(rows) == 0:
            return []

        start_index = 0
        while start_index < len(rows):
            first_cell = rows[start_index][0] if len(rows[start_index]) > 0 else ""
            joined = ";".join(str(cell) for cell in rows[start_index]).casefold()
            if self._is_columns_header_row(rows[start_index]):
                start_index += 1
                continue
            if self._is_header_like(first_cell, allow_node=True) or self._is_header_like(joined, allow_node=True):
                start_index += 1
                continue
            if "калибровк" in joined or "формул" in joined or "empty=" in joined or "full=" in joined:
                start_index += 1
                continue
            break

        data_rows: list[dict[str, str]] = []
        for raw_row in rows[start_index:]:
            if len(raw_row) == 0:
                continue
            if not any(str(cell).strip() for cell in raw_row):
                continue
            normalized = {column: str(raw_row[index]) if index < len(raw_row) else "" for index, column in enumerate(header)}
            data_rows.append(normalized)

        return data_rows

    def _write_full_file(self, rows: list[dict[str, str]]):
        with self._csv_path.open("w", newline="", encoding=CSV_WRITE_ENCODING) as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow(self._group_header_row())
            writer.writerow(self._calibration_row())
            writer.writerow(self._columns_header_row())

            dict_writer = csv.DictWriter(file, fieldnames=self._header, delimiter=";")
            for raw_row in rows:
                normalized_row = {column: str(raw_row.get(column, "")) for column in self._header}
                dict_writer.writerow(normalized_row)

    def _resolve_fuel_period_percent(self, metrics: dict[str, object]) -> float:
        raw_value = metrics.get("fuelPeriodX10")
        try:
            return float(int(raw_value)) / 10.0
        except (TypeError, ValueError):
            fallback_fuel = self._as_float(metrics.get("fuel", 0.0))
            return float(fallback_fuel)

    def _update_node_calibration(self, snapshot: dict[str, dict[str, object]]) -> bool:
        changed = False
        for node_hex, metrics in snapshot.items():
            empty_ticks = self._as_int(metrics.get("emptyPeriod", 0))
            full_ticks = self._as_int(metrics.get("fullPeriod", 0))
            empty_known = self._as_bool(metrics.get("emptyKnown", False))
            full_known = self._as_bool(metrics.get("fullKnown", False))
            previous = self._node_calibration.get(node_hex, (0, 0, False, False))
            current = (empty_ticks, full_ticks, empty_known, full_known)
            if previous != current:
                self._node_calibration[node_hex] = current
                changed = True
        return changed

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
            self._node_calibration.setdefault(normalized, (0, 0, False, False))
            self._ordered_nodes.append(normalized)
            new_columns.extend(columns)

        if len(new_columns) == 0:
            return

        self._header = old_header + new_columns

        existing_rows = self._read_existing_rows(old_header)
        self._write_full_file(existing_rows)

    def _ensure_nodes(self, node_hexes: list[str]):
        new_nodes: list[str] = []
        for node_hex in node_hexes:
            normalized = self._normalize_node_hex(node_hex)
            if not normalized or normalized in self._node_columns:
                continue
            new_nodes.append(normalized)
        self._expand_header_for_new_nodes(new_nodes)

    def append_snapshot(self, measurement_time: str, nodes_snapshot: dict[str, dict[str, object]],
):
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
        calibration_changed = self._update_node_calibration(normalized_snapshot)
        if calibration_changed:
            existing_rows = self._read_existing_rows(self._header)
            self._write_full_file(existing_rows)
        row: dict[str, str] = {column: "" for column in self._header}
        row["Время"] = self._format_value(str(measurement_time))

        for node_hex in self._ordered_nodes:
            metrics = normalized_snapshot.get(node_hex)
            if metrics is None:
                continue
            (period_column, media_column, temperature_column, board_temperature_column,
             fuel_column, fuel_j1939_column, fuel_period_x10_column) = self._node_columns[node_hex]

            row[period_column] = self._format_value(self._as_int(metrics.get("period", 0)))
            row[media_column] = (
                self._format_value(self._as_int(metrics.get("mediaRaw", 0)))
                if self._as_bool(metrics.get("mediaRawKnown", False)) else ""
            )
            row[temperature_column] = self._format_value(self._as_float(metrics.get("temperature", 0.0)))
            row[board_temperature_column] = (
                self._format_value(self._as_float(metrics.get("boardTemperature", 0.0)))
                if self._as_bool(metrics.get("boardTemperatureKnown", False)) else ""
            )
            row[fuel_column] = self._format_value(self._as_float(metrics.get("fuel", 0.0)))
            if self._as_bool(metrics.get("fuelJ1939Known", False)):
                row[fuel_j1939_column] = self._format_value(self._as_float(metrics.get("fuelJ1939", 0.0)))
            else:
                row[fuel_j1939_column] = ""
            row[fuel_period_x10_column] = self._format_value(self._resolve_fuel_period_percent(metrics))

        with self._csv_path.open("a", newline="", encoding=CSV_WRITE_ENCODING) as file:
            writer = csv.DictWriter(file, fieldnames=self._header, delimiter=";")
            writer.writerow(row)
