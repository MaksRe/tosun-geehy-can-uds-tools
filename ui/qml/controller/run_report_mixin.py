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

    def _run_report_data(self) -> dict:
        now = time.monotonic()
        scenario = getattr(self, "_climate_scenario", None) or {}
        check = bool(scenario.get("check_only", getattr(self, "_chamber_check_only", False)))
        collect = getattr(self, "_chamber_monitor_collect", None)
        monitor = collect() if collect is not None else []
        tone_of = getattr(self, "_chamber_monitor_tone", lambda value: "info")

        info = [("Сценарий", scenario.get("name") or "—"),
                ("Режим", "проверка профиля (сухая трубка, профиль не пишется)" if check else
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
        info.append(("Платы", ", ".join(board["label"] for board in monitor) or "—"))

        audit = (getattr(self, "_profile_audit", None) or {}).get("results") or {}
        rows, verdict_lines, worst_tone = [], [], "info"
        for board in monitor:
            result = audit.get(board.get("sa")) if board.get("sa") is not None else None
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
        if not monitor or all(board.get("worst") is None for board in monitor):
            verdict = {"tone": "info", "title": "Уровень за прогон не оценён: прибор не отдал уровень или трубка не "
                                                "была при +25 °C", "lines": verdict_lines}
        elif bad:
            verdict = {"tone": "bad", "title": f"Вне допуска ±1 %: {', '.join(bad)}", "lines": verdict_lines}
        elif edge:
            verdict = {"tone": "warn", "title": f"В допуске ±1 %, но на грани (больше 0,5 %): {', '.join(edge)}",
                       "lines": verdict_lines}
        else:
            verdict = {"tone": "ok", "title": "Все платы в допуске ±1 % с запасом (не больше 0,5 %)",
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
        return {
            "title": "Отчёт о прогоне в камере" + (": проверка профиля" if check else ""),
            "created": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "info": info, "verdict": verdict, "boards": rows,
            "nodes": {"title": "Средние по узлам температуры трубки: погрешность / сдвиг от +25 °C, %",
                      "columns": node_columns, "rows": node_rows,
                      "note": "В каждой ячейке - среднее за время, пока трубка была в узле (±3 °C). «—» - трубка в "
                              "узле не была или настоящий уровень неизвестен."},
            "charts": charts, "tables": tables, "results": results, "events": events,
        }

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
                    "на трубке: при нагреве она стекает и испаряется")
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
        path = self._run_report_write()
        if not path:
            return ""
        event = getattr(self, "_climate_event", None)
        if event is not None:
            event(f"отчёт PDF ({why}): {path.rsplit(chr(92), 1)[-1].rsplit('/', 1)[-1]}", "info")
        remote = getattr(self, "_remote_settings", {}) or {}
        telegram = getattr(self, "_remote_telegram", None)
        if telegram is not None and remote.get("telegram_enabled"):
            telegram.send_document(path, f"Отчёт о прогоне ({why})")
        return path
