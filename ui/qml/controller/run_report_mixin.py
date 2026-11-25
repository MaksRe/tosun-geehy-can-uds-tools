"""Итоговый отчёт прогона в PDF: данные для отчёта и когда его делать.

КОГДА
- сам - в конце прогона (узлы пройдены) и при остановке прогона: файл в logs/chamber, в Telegram -
  тем, у кого включены «файлы»;
- по запросу - кнопка «Отчёт PDF» в окне и в мини-приложении, команда бота /pdf;
- в архиве прогона (/all) - свежий отчёт рядом с итогами текстом.

ЧТО В НЁМ
Прогон (сценарий, длительность, узлы, платы), вывод против требования ±1 %, по каждой плате
худшая погрешность и что было записано в плате на старте, средние по узлам, графики погрешности
по времени и от температуры трубки, таблицы итогов и события прогона.
"""

from __future__ import annotations

import time
from copy import deepcopy
from datetime import datetime

import chamber_fit
from ui.qml import run_report_pdf

from .contract import AppControllerContract


def _pp(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}".replace(".", ",").replace("-", "−")


TONE_RANK = {"info": 0, "ok": 1, "warn": 2, "bad": 3}
TONE_WORD = {"ok": "в норме", "warn": "на грани", "bad": "вне допуска"}


class AppControllerRunReportMixin(AppControllerContract):
    """Отчёт PDF о прогоне."""

    def _run_report_level_visibility(self, result: dict) -> dict:
        """Чтобы этапы обучения не давали ложный допуск, исключает оценку уровня до проверки готового профиля."""
        context_of = getattr(self, "_chamber_monitor_level_context", None)
        context = context_of() if callable(context_of) else {}
        if context.get("levelEnabled") is not False:
            failures = result.get("profileFailures") or []
            if failures:
                previous = result.get("verdict") or {}
                lines = [previous["title"]] + previous.get("lines", []) if previous.get("title") else []
                result["verdict"] = {"tone": "bad", "title": "Не подтверждена запись профилей: " + ", ".join(failures),
                                     "lines": lines + ["Температурные точки сохранены. Повторите запись и сверку профиля из таблиц."]}
            return result
        error = getattr(self, "_chamber_monitor_storage_error", "")
        result["verdict"] = {"tone": "warn" if error else "info", "title": "Уровень топлива на этом этапе не оценивается",
                             "lines": [context.get("levelReason", "")] + ([error] if error else [])}
        result["boards"] = []
        result["charts"] = []
        result.setdefault("nodes", {})["rows"] = []
        result["tables"] = [table for table in result.get("tables", []) if table
                            and not str(table.get("id", "")).startswith("monitor")]
        for board in result.get("results", []):
            board["tables"] = [table for table in board.get("tables", []) if table.get("id") != "level"]
        failures = result.get("profileFailures") or []
        if failures:
            result["verdict"] = {"tone": "bad", "title": "Не подтверждена запись профилей: " + ", ".join(failures),
                                 "lines": result["verdict"]["lines"] + ["Температурные точки сохранены. Повторите запись и сверку профиля из таблиц."]}
        return result

    def _run_report_data(self) -> dict:
        """Для повторной выгрузки возвращает сохранённый итог, а во время прогона собирает текущие данные."""
        frozen = getattr(self, "_run_report_frozen", None)
        if frozen is not None:
            result = deepcopy(frozen)
            error = getattr(self, "_chamber_monitor_storage_error", "")
            if error and result.get("verdict", {}).get("tone") != "bad":
                result["verdict"] = {"tone": "warn", "title": "Ошибка сохранения истории уровня", "lines": [error]}
            return self._run_report_level_visibility(result)
        now = time.monotonic()
        scenario = getattr(self, "_climate_scenario", None) or {}
        session = getattr(self, "_chamber_monitor_session", None)
        if session is not None:
            scenario = session.metadata.get("scenario") or scenario
        check = bool(scenario.get("check_only", getattr(self, "_chamber_check_only", False)))
        stages = (session.metadata.get("board_stages") or {}) if session is not None else {}
        if stages:
            check = any(stage["check_only"] for stage in stages.values())
        collect = getattr(self, "_chamber_monitor_collect", None)
        monitor = collect() if collect is not None else []
        tone_of = getattr(self, "_chamber_monitor_tone", lambda value: "info")

        info = [("Сценарий", scenario.get("name") or "—"),
                ("Режим", "этапы назначены по платам" if stages else
                 "проверка профиля (пустая трубка после калибровки, профиль не пишется)" if check else
                 ("второй этап (трубка)" if any(str(label).casefold() in (chamber_fit.AIR_NOTE, chamber_fit.LIQUID_NOTE)
                                               for label in scenario.get("labels") or []) else "первый этап (плата)"))]
        settings = getattr(self, "_climate_settings", None) or {}
        if settings.get("driver"):
            info.append(("Камера", str(settings.get("driver"))))
        elapsed = getattr(self, "_climate_auto_finish_elapsed", None)
        if not elapsed and callable(getattr(self, "_climate_auto_elapsed", None)):
            try:
                elapsed = self._climate_auto_elapsed(now)
            except Exception:
                elapsed = None
        if elapsed:
            from .climate_supervisor_mixin import duration_text
            info.append(("Длительность", duration_text(elapsed)))
        nodes_text = getattr(self, "_climate_auto_nodes_text", None)
        if callable(nodes_text):
            try:
                text = nodes_text()
            except Exception:
                text = ""
            if text:
                info.append(("Узлы", text))
        labels = [board["label"] for board in session.metadata["boards"]] if stages else [board["label"] for board in monitor]
        info.append(("Платы", ", ".join(labels) or "—"))
        if check:
            info.append(("Условия", "Без погружения после калибровки. Возможна плёнка топлива; её вклад не вычитается."))
        profile_failures_of = getattr(self, "_mb_profile_failures", None)
        profile_failures = profile_failures_of() if callable(profile_failures_of) else []
        if not getattr(self, "_mb_on", lambda: False)() and getattr(self, "_chamber_auto_write", False) and getattr(self, "_profile_last_result", None) == "fail":
            profile_failures = ["выбранная плата"]
        if profile_failures:
            info.append(("Запись профиля", "Не подтверждена: " + ", ".join(profile_failures)))

        audit = (getattr(self, "_profile_audit", None) or {}).get("results") or {}
        session = getattr(self, "_chamber_monitor_session", None)
        if session is not None:
            audit = (session.metadata.get("profile_audit") or {}).get("results") or {}
        rows, verdict_lines, worst_tone = [], [], "info"
        for board in monitor:
            result = (audit.get(board.get("sa")) or audit.get(str(board.get("sa")))) if board.get("sa") is not None else None
            profile = "—"
            if result is not None:
                profile = result.get("error") or result.get("summary") or "прочитан"
            worst = board.get("worst")
            tone = board.get("tone", "info")
            worst_tone = max(worst_tone, tone, key=lambda item: TONE_RANK.get(item, 0))
            rows.append({"label": board["label"], "state": board.get("state", ""), "worst": board["row"]["worst"],
                         "errNow": board["row"]["err"], "shiftNow": board["row"]["dev"], "profile": profile,
                         "tone": tone})
            if worst is not None:
                verdict_lines.append(f"{board['label']}: худшее {board['row']['worst']} - {board.get('state', '')}")
            film = self._run_report_film_hint(board)
            if film:
                verdict_lines.append(f"{board['label']}: {film}")
        bad = [row["label"] for row in rows if row["tone"] == "bad"]
        edge = [row["label"] for row in rows if row["tone"] == "warn"]
        missing = [board["label"] for board in monitor if board.get("worst") is None]
        session = getattr(self, "_chamber_monitor_session", None)
        gaps = session.level_gaps() + session.metadata.get("damaged_records", 0) if session is not None else 0
        storage_error = getattr(self, "_chamber_monitor_storage_error", "")
        expected = {node for step in scenario.get("steps", []) if step.get("temp") is not None and step.get("capture", True)
                    if (node := chamber_fit.nearest_node(int(round(step["temp"] * 10)))) is not None}
        uncovered = [board["label"] for board in monitor if expected - set(board.get("stats") or {})] if check else []
        if not monitor or all(board.get("worst") is None for board in monitor):
            verdict = {"tone": "info", "title": "Уровень за прогон не оценён: прибор не отдал уровень или трубка не "
                                                "была при +25 °C", "lines": verdict_lines}
        elif bad:
            verdict = {"tone": "bad", "title": f"Вне допуска ±1 %: {', '.join(bad)}", "lines": verdict_lines}
        elif missing or gaps or storage_error:
            verdict = {"tone": "warn", "title": "Проверка не полная: есть пропуски показаний или ошибка сохранения",
                       "lines": verdict_lines + (["Нет уровня: " + ", ".join(missing)] if missing else [])
                       + ([f"Пропусков показаний: {gaps}"] if gaps else []) + ([storage_error] if storage_error else [])}
        elif uncovered:
            verdict = {"tone": "warn", "title": "Проверены не все температуры: " + ", ".join(uncovered),
                       "lines": verdict_lines}
        elif edge:
            verdict = {"tone": "warn", "title": f"В допуске ±1 %, но на грани (больше 0,5 %): {', '.join(edge)}",
                       "lines": verdict_lines}
        else:
            tested = "Все платы этапа «Проверка профиля»" if stages else "Все платы"
            verdict = {"tone": "ok", "title": tested + " в допуске ±1 % с запасом (не больше 0,5 %)",
                       "lines": verdict_lines}

        # Средние по узлам: погрешность / сдвиг от +25 °C.
        node_columns = [("label", "Плата")] + [(str(node), chamber_fit.node_text(node)) for node in chamber_fit.NODES_X10]
        node_rows = []
        for board in monitor:
            row = {"label": board["label"]}
            tone = "info"
            for node in chamber_fit.NODES_X10:
                bucket = (board.get("stats") or {}).get(node) or {}
                errors, shifts = bucket.get("error") or [], bucket.get("shift") or []
                if not errors and not shifts:
                    row[str(node)] = "—"
                    continue
                err = sum(errors) / len(errors) if errors else None
                shift = sum(shifts) / len(shifts) if shifts else None
                row[str(node)] = f"{_pp(err)} / {_pp(shift)}"
                for value in (err, shift):
                    if value is not None:
                        tone = max(tone, tone_of(value), key=lambda item: TONE_RANK.get(item, 0))
            row["tone"] = tone
            node_rows.append(row)

        charts = self._run_report_charts(monitor)
        view = {}
        results_view = getattr(self, "_chamber_results_view", None)
        if results_view is not None:
            try:
                view = results_view()
            except Exception:
                view = {}
        monitor_view = getattr(self, "_chamber_monitor_view", None)
        tables = []
        if view.get("overview"):
            tables.append(view["overview"])
        if monitor_view is not None:
            try:
                tables.append(monitor_view().get("detail"))
            except Exception:
                pass
        results = [{"label": f"{board.get('sa', '')} ({board.get('name', '')})".strip(), "tone": board.get("tone"),
                    "verdict": board.get("verdict", ""),
                    "summary": [{"label": item.get("label", ""), "value": item.get("value", ""),
                                 "tone": item.get("tone", "info")} for item in board.get("summary") or []],
                    "tables": board.get("tables") or []} for board in view.get("boards") or []]
        events = list(getattr(self, "_remote_events", []) or [])[:80]
        events.reverse()
        return self._run_report_level_visibility({
            "title": "Отчёт о прогоне в камере" + (": проверка профиля" if check else ""),
            "created": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "info": info, "verdict": verdict, "boards": rows, "profileFailures": profile_failures,
            "nodes": {"title": "Средние по узлам температуры трубки: погрешность / сдвиг от +25 °C, %",
                      "columns": node_columns, "rows": node_rows,
                      "note": "В каждой ячейке - среднее сохранённых показаний в окне ±3 °C от узла. "
                              "Сохраняются изменения уровня и контрольные записи каждые 5 с. «—» - данных нет. "
                              "Вклад остаточной плёнки не вычитается."},
            "charts": charts, "tables": tables, "results": results, "events": events,
        })

    @staticmethod
    def _run_report_film_hint(board: dict) -> str:
        """Холодные узлы завышены, горячие нет - похоже на плёнку топлива на трубке (прогон 11-12.11.2026)."""
        stats = board.get("stats") or {}

        def mean(nodes):
            values = [value for node in nodes for value in (stats.get(node) or {}).get("shift") or []]
            return sum(values) / len(values) if values else None
        cold, hot = mean((-400, -200, 0)), mean((700, 850))
        if cold is not None and hot is not None and cold > 0.3 and abs(hot) < 0.15:
            return (f"холодные узлы завышены ({_pp(cold)} %), горячие нет ({_pp(hot)} %) - похоже на плёнку топлива "
                    "на трубке. По этому графику нельзя отделить её вклад от температурного дрейфа")
        return ""

    def _run_report_charts(self, monitor: list[dict]) -> list[dict]:
        colors = run_report_pdf.BOARD_COLORS
        by_time, by_temp, temps = [], [], []
        known = any(sample.get("truth") is not None for board in monitor for sample in board.get("history") or [])
        walls = [sample["wall"] for board in monitor for sample in board.get("history") or []]
        start = min(walls, default=None)
        # Короткое наблюдение - в минутах, длинное - в часах.
        minutes = bool(walls) and max(walls) - start < 2 * 3600
        unit_s, unit = (60.0, "минуты") if minutes else (3600.0, "часы")
        for index, board in enumerate(monitor):
            ref = board.get("ref")
            color = colors[index % len(colors)]
            points_time, points_temp, points_tube = [], [], []
            for sample in board.get("history") or []:
                if known:
                    value = None if sample.get("truth") is None else sample["level"] / 10.0 - float(sample["truth"])
                else:
                    value = None if ref is None else (sample["level"] - ref["level"]) / 10.0
                hours = (sample["wall"] - start) / unit_s
                points_tube.append((hours, sample["tube"] / 10.0))
                if value is None:
                    continue
                points_time.append((hours, value))
                points_temp.append((sample["tube"] / 10.0, value))
            by_time.append({"name": board["label"], "color": color, "points": points_time})
            by_temp.append({"name": board["label"], "color": color, "points": points_temp, "dots": True})
            temps.append({"name": board["label"], "color": color, "points": points_tube})
        if not any(item["points"] for item in by_time):
            return []
        what = "Погрешность уровня" if known else "Сдвиг уровня от +25 °C"
        return [
            {"title": f"{what} по времени", "chartTitle": f"{what}, %", "xLabel": f"{unit} от начала наблюдения",
             "yLabel": "%", "series": by_time,
             "note": "Зелёная полоса - до ±0,5 % (в норме), жёлтая - до ±1 % (на грани), выше - вне допуска."},
            {"title": f"{what} от температуры трубки", "chartTitle": f"{what}, %", "xLabel": "температура трубки, °C",
             "yLabel": "%", "series": by_temp},
            {"title": "Температура трубки по времени", "chartTitle": "Температура трубки, °C",
             "xLabel": f"{unit} от начала наблюдения", "yLabel": "°C", "series": temps, "bands": ()},
        ]

    def _run_report_write(self) -> str:
        """Отчёт PDF в logs/chamber; путь или пусто (причина - в журнал программы)."""
        try:
            folder = self._climate_logs_directory()
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"отчёт_прогона_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            run_report_pdf.write_pdf(path, self._run_report_data())
            return str(path)
        except Exception as error:  # отчёт не должен ронять прогон
            self._climate_command_status = f"Отчёт PDF не собрался: {error}"
            return ""

    def _run_report_finish(self, why: str = "конец прогона"):
        """Отчёт PDF в конце прогона: файл и - тем, у кого в Telegram включены «файлы»."""
        freeze = getattr(self, "_chamber_monitor_finish", None)
        if freeze is not None:
            freeze(why)
        path = self._run_report_write()
        if not path:
            return ""
        event = getattr(self, "_climate_event", None)
        if event is not None:
            event(f"отчёт PDF ({why}): {path.rsplit(chr(92), 1)[-1].rsplit('/', 1)[-1]}", "info", kind="journal")
        remote = getattr(self, "_remote_settings", {}) or {}
        telegram = getattr(self, "_remote_telegram", None)
        if telegram is not None and remote.get("telegram_enabled"):
            telegram.send_document(path, f"Отчёт о прогоне ({why})")
        return path
