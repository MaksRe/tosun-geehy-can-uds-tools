"""Наблюдение за прогоном издалека: страница состояния, Telegram, копия журналов.

ЗАЧЕМ
Камера стоит далеко от рабочего места. Вся работа идёт на компьютере у камеры,
а этот модуль даёт видеть её издалека, не держа открытым удалённый стол:
- страница состояния в браузере: температуры, контуры, ход прогона, история,
  события и журналы для скачивания;
- сообщения в Telegram о важном: плата устоялась, точка записана, прибор
  замолчал, профиль записан;
- копия каждого сохранённого журнала в сетевую папку или на сервер по SFTP.

Связь здесь только для наблюдения. Пропала сеть - прогон идёт дальше, а
сообщения и копии догонят, когда сеть вернётся.

ЧТО СЧИТАЕТСЯ СОБЫТИЕМ
- плата устоялась: за последние 5 минут температура платы меняется медленнее
  0,05 °C в минуту - то же правило, что в порядке прогона;
- температура платы пошла: камера перешла к следующей уставке;
- точка записана, данных хватило во всех узлах, профиль записан или нет;
- прибор не отвечает дольше 30 с, адаптер отключён, и их возвращение;
- обход узлов тестового режима закончен или остановлен.

Настройки хранятся в config/remote_monitor.json рядом с программой, чтобы
после перезапуска наблюдение включалось само.
"""

from __future__ import annotations

import json
import pathlib
import secrets
import socket
import threading
import time
from collections import deque
from datetime import datetime

from PySide6.QtCore import QTimer

import chamber_fit
from ui.qml.remote_file_sync import MODE_FOLDER, MODE_SFTP, FileSyncConfig, RemoteFileSync
from ui.qml.remote_status_server import RemoteStatusServer, local_addresses
from ui.qml.telegram_notifier import TelegramNotifier

from .contract import AppControllerContract
from .stability import is_stable, rate_and_spread

# Запасная страница, если файл страницы не нашёлся рядом с программой.
FALLBACK_PAGE = ("<!doctype html><meta charset='utf-8'><title>Прогон в камере</title>"
                 "<p>Файл страницы не найден. Данные: <a href='status.json'>status.json</a></p>")


class AppControllerRemoteMonitorMixin(AppControllerContract):
    REMOTE_TICK_MS = 1000
    REMOTE_DEFAULT_PORT = 8765
    # История для графика: шаг и длительность, с.
    REMOTE_HISTORY_STEP_S = 10.0
    REMOTE_HISTORY_SPAN_S = 3 * 3600.0
    # Правило «плата устоялась»: окно, предел скорости и разброса.
    REMOTE_STABLE_WINDOW_S = 300.0
    REMOTE_STABLE_RATE_C_MIN = 0.05
    REMOTE_STABLE_SPREAD_C = 0.3
    # С какой скорости считать, что температура пошла снова, °C/мин.
    REMOTE_MOVING_RATE_C_MIN = 0.15
    # Сколько молчания прибора считать бедой, с.
    REMOTE_SILENCE_S = 30.0
    # Как часто копировать идущий журнал калибровки, с.
    REMOTE_CALIBRATION_LOG_SYNC_S = 60.0
    REMOTE_EVENTS_KEPT = 60

    # ------------------------------------------------------------------ состояние

    def _init_remote_monitor_state(self):
        """Готовит наблюдение и включает то, что было включено в прошлый раз."""
        self._remote_lock = threading.Lock()
        self._remote_incoming: list[tuple[str, str, bool]] = []
        self._remote_found_chat = None

        self._remote_settings = self._remote_default_settings()
        self._remote_settings.update(self._remote_load_settings())

        self._remote_events: deque = deque(maxlen=self.REMOTE_EVENTS_KEPT)
        self._remote_history: deque = deque(maxlen=int(self.REMOTE_HISTORY_SPAN_S / self.REMOTE_HISTORY_STEP_S))
        self._remote_last_history_s = 0.0
        self._remote_stable_announced = False
        self._remote_stable_text = "Температура платы: истории ещё мало."
        self._remote_stable_ok = False
        self._remote_device_silent = False
        self._remote_adapter_lost = False
        self._remote_tables_were_complete = False
        self._remote_last_calibration_sync_s = 0.0

        self._remote_server_status = "Страница выключена."
        self._remote_server_ok = False
        self._remote_telegram_status = "Telegram выключен."
        self._remote_telegram_ok = False
        self._remote_sync_status = "Копия журналов выключена."
        self._remote_sync_ok = False

        page_path = pathlib.Path(__file__).resolve().parent.parent / "remote_status_page.html"
        try:
            page = page_path.read_text(encoding="utf-8")
        except OSError:
            page = FALLBACK_PAGE
        self._remote_server = RemoteStatusServer(page)
        self._remote_telegram = TelegramNotifier(
            lambda text, ok: self._remote_queue_status("telegram", text, ok))
        self._remote_sync = RemoteFileSync(lambda text, ok: self._remote_queue_status("sync", text, ok))

        self._remote_timer = QTimer(self)
        self._remote_timer.setInterval(self.REMOTE_TICK_MS)
        self._remote_timer.timeout.connect(self._on_remote_tick)
        self._remote_timer.start()

        self._remote_apply_all()

    @staticmethod
    def _remote_default_settings() -> dict:
        return {
            "server_enabled": False,
            "server_port": AppControllerRemoteMonitorMixin.REMOTE_DEFAULT_PORT,
            "server_key": "",
            "telegram_enabled": False,
            "telegram_token": "",
            "telegram_chat": "",
            "telegram_points": True,
            "telegram_files": True,
            "sync_enabled": False,
            "sync_mode": MODE_FOLDER,
            "sync_folder": "",
            "sync_host": "",
            "sync_port": 22,
            "sync_user": "",
            "sync_password": "",
            "sync_remote_dir": "/chamber",
        }

    def _remote_settings_path(self) -> pathlib.Path:
        root = getattr(self, "_project_root_directory", None) or pathlib.Path.cwd()
        return pathlib.Path(root) / "config" / "remote_monitor.json"

    def _remote_load_settings(self) -> dict:
        """Читает сохранённые настройки. Испорченный файл не мешает запуску."""
        try:
            payload = json.loads(self._remote_settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        defaults = self._remote_default_settings()
        return {key: payload[key] for key in defaults if key in payload
                and isinstance(payload[key], type(defaults[key]))}

    def _remote_save_settings(self):
        """Сохраняет настройки: после перезапуска наблюдение включится само."""
        try:
            path = self._remote_settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._remote_settings, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            self._remote_event(f"Настройки наблюдения не сохранились: {error}", "warn", telegram=False)

    # ------------------------------------------------------------------ настройки

    def _remote_set(self, key: str, value) -> bool:
        """Меняет одну настройку, сохраняет и применяет."""
        if key not in self._remote_settings:
            return False
        default = self._remote_default_settings()[key]
        try:
            if isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int):
                value = int(str(value).strip())
                if key.endswith("port") and not (1 <= value <= 65535):
                    raise ValueError
            else:
                value = str(value).strip() if key not in ("sync_password",) else str(value)
        except (TypeError, ValueError):
            self._remote_event("Порт задаётся числом от 1 до 65535.", "bad", telegram=False)
            self.remoteMonitorChanged.emit()
            return False
        if key == "sync_mode" and value not in (MODE_FOLDER, MODE_SFTP):
            return False
        if self._remote_settings[key] == value:
            return True
        self._remote_settings[key] = value
        self._remote_save_settings()
        self._remote_apply_all()
        return True

    def _remote_new_key(self):
        """Придумывает ключ доступа к странице."""
        self._remote_set("server_key", secrets.token_urlsafe(9))

    def _remote_active(self) -> bool:
        """Нужен ли постоянный опрос прибора: что-то из наблюдения включено."""
        settings = self._remote_settings
        return bool(settings["server_enabled"]) or bool(settings["telegram_enabled"])

    def _remote_keeps_live(self) -> bool:
        """Прогону: держать живой опрос, даже если раздел в окне не открыт."""
        return self._remote_active()

    def _remote_apply_all(self):
        """Приводит сервер, бота и копирование в соответствие с настройками."""
        settings = self._remote_settings

        if settings["server_enabled"]:
            self._remote_server.set_key(settings["server_key"])
            self._remote_server.set_folders(self._remote_folders())
            if not self._remote_server.running or self._remote_server.port != int(settings["server_port"]):
                problem = self._remote_server.start(int(settings["server_port"]))
                if problem:
                    self._remote_server_status = f"Страница не запущена: {problem}."
                    self._remote_server_ok = False
                else:
                    self._remote_server_status = "Страница работает. Адреса ниже открываются из любого браузера в сети."
                    self._remote_server_ok = True
        else:
            self._remote_server.stop()
            self._remote_server_status = "Страница выключена."
            self._remote_server_ok = False

        if settings["telegram_enabled"]:
            self._remote_telegram.configure(settings["telegram_token"], settings["telegram_chat"])
            if not settings["telegram_token"] or not settings["telegram_chat"]:
                self._remote_telegram_status = "Впишите токен бота и номер чата (кнопка «Найти чат»)."
                self._remote_telegram_ok = False
            elif not self._remote_telegram_ok:
                self._remote_telegram_status = "Telegram включён. Проверьте связь кнопкой «Проверить»."
        else:
            self._remote_telegram.configure("", "")
            self._remote_telegram_status = "Telegram выключен."
            self._remote_telegram_ok = False

        self._remote_sync.configure(FileSyncConfig(
            enabled=bool(settings["sync_enabled"]),
            mode=str(settings["sync_mode"]),
            folder=str(settings["sync_folder"]),
            host=str(settings["sync_host"]),
            port=int(settings["sync_port"]),
            username=str(settings["sync_user"]),
            password=str(settings["sync_password"]),
            remote_dir=str(settings["sync_remote_dir"]),
        ))
        if not settings["sync_enabled"]:
            self._remote_sync_status = "Копия журналов выключена."
            self._remote_sync_ok = False
        elif not self._remote_sync_ok:
            problem = FileSyncConfig(mode=settings["sync_mode"], folder=settings["sync_folder"],
                                     host=settings["sync_host"], username=settings["sync_user"]).problem()
            self._remote_sync_status = (f"Копия включена, но {problem}." if problem
                                        else "Копия включена: журнал скопируется при следующем сохранении.")

        # Живой опрос прогона нужен странице и сообщениям, даже когда раздел закрыт.
        apply_live = getattr(self, "_chamber_live_apply_wanted", None)
        if apply_live is not None:
            apply_live()
        self.remoteMonitorChanged.emit()

    def _remote_folders(self) -> dict:
        """Папки журналов, которые можно скачать со страницы."""
        root = pathlib.Path(getattr(self, "_project_root_directory", None) or pathlib.Path.cwd())
        folders = {"прогон": root / "logs" / "chamber"}
        directory = getattr(self, "_calibration_log_directory", None)
        if directory is not None:
            try:
                folders["калибровка"] = pathlib.Path(directory())
            except Exception:
                pass
        return folders

    # ------------------------------------------------------------------ события

    def _remote_event(self, text: str, level: str = "info", telegram: bool = True):
        """Запоминает событие для страницы и, если нужно, шлёт его в Telegram."""
        self._remote_events.appendleft({
            "time": datetime.now().strftime("%H:%M:%S"),
            "text": str(text),
            "level": str(level),
        })
        if telegram and self._remote_settings["telegram_enabled"]:
            mark = {"ok": "✅", "warn": "⚠️", "bad": "❌"}.get(level, "ℹ️")
            self._remote_telegram.send_text(f"{mark} Камера: {text}")
        self.remoteMonitorChanged.emit()

    def _remote_queue_status(self, channel: str, text: str, ok: bool):
        """Итог работы фонового потока. Окно заберёт его в свой такт."""
        with self._remote_lock:
            self._remote_incoming.append((channel, str(text), bool(ok)))

    def _remote_note_point(self, point: dict):
        """Точка записана: событие для страницы и, по желанию, сообщение."""
        node = chamber_fit.nearest_node(point["board_temp_x10"])
        where = chamber_fit.node_text(node) if node is not None else "вне сетки"
        media = "-" if point.get("media") is None else point["media"]
        trial = " (проба)" if point.get("rehearsal") else ""
        self._remote_event(
            f"точка «{point['note']}»{trial} записана: узел {where}, основной {point['main']}, "
            f"вид топлива {media}. Всего точек: {len(self._chamber_points)}.",
            "ok", telegram=bool(self._remote_settings["telegram_points"]))

    def _remote_note_journal_saved(self, path: str):
        """Журнал прогона сохранён: его копия уходит на рабочее место."""
        self._remote_sync.enqueue(path, "chamber")

    def _remote_note_tables(self, complete: bool):
        """Данных стало хватать во всех узлах: об этом стоит знать сразу."""
        if complete and not self._remote_tables_were_complete:
            self._remote_event("данных хватило во всех узлах, таблицы посчитаны полностью.", "ok")
        self._remote_tables_were_complete = bool(complete)

    def _remote_note_chain(self, ok: bool, text: str, profile_path: str = ""):
        """Запись профиля закончилась: итог, копии и файлы в Telegram."""
        self._remote_event(text, "ok" if ok else "bad")
        if not ok:
            return
        journal = str(self._chamber_file_path or "")
        for path in (journal, profile_path):
            if path:
                self._remote_sync.enqueue(path, "chamber")
        if self._remote_settings["telegram_enabled"] and self._remote_settings["telegram_files"]:
            for path, caption in ((journal, "Журнал прогона"), (profile_path, "Записанный профиль")):
                if path and pathlib.Path(path).is_file():
                    self._remote_telegram.send_document(path, caption)

    def _remote_note_test(self, text: str, ok: bool):
        """Обход узлов тестового режима закончился."""
        self._remote_event(text, "ok" if ok else "warn")

    # ------------------------------------------------------------------ такт

    def _on_remote_tick(self):
        """Раз в секунду: итоги фоновых потоков, история, события и снимок для страницы."""
        changed = self._remote_take_incoming()
        if self._remote_active():
            now = time.monotonic()
            self._remote_watch_history(now)
            self._remote_watch_device(now)
            self._remote_sync_calibration_log(now)
            if self._remote_server.running:
                self._remote_server.set_snapshot(self._remote_snapshot())
            changed = True
        if changed:
            self.remoteMonitorChanged.emit()

    def _remote_take_incoming(self) -> bool:
        """Забирает итоги фоновых потоков: отправки, копирования, поиска чата."""
        with self._remote_lock:
            incoming = list(self._remote_incoming)
            self._remote_incoming.clear()
            found = self._remote_found_chat
            self._remote_found_chat = None
        for channel, text, ok in incoming:
            if channel == "telegram":
                self._remote_telegram_status = text
                self._remote_telegram_ok = ok
            else:
                self._remote_sync_status = text
                self._remote_sync_ok = ok
        if found is not None:
            chat_id, note = found
            if chat_id:
                self._remote_set("telegram_chat", chat_id)
                self._remote_telegram_status = f"Telegram: {note}, номер {chat_id}. Нажмите «Проверить»."
                self._remote_telegram_ok = True
            else:
                self._remote_telegram_status = f"Telegram: {note}."
                self._remote_telegram_ok = False
        return bool(incoming) or found is not None

    def _remote_find_chat(self):
        """Ищет номер чата по последнему сообщению боту."""
        token = self._remote_settings["telegram_token"]
        self._remote_telegram.configure(token, self._remote_settings["telegram_chat"])
        self._remote_telegram_status = "Telegram: ищу чат..."
        self.remoteMonitorChanged.emit()

        def done(chat_id, note):
            with self._remote_lock:
                self._remote_found_chat = (chat_id, note)
        self._remote_telegram.find_chat(done)

    def _remote_test_message(self):
        """Пробное сообщение: проверка бота, чата и сети у камеры."""
        settings = self._remote_settings
        if not settings["telegram_token"] or not settings["telegram_chat"]:
            self._remote_telegram_status = "Впишите токен бота и номер чата."
            self._remote_telegram_ok = False
            self.remoteMonitorChanged.emit()
            return
        self._remote_telegram.configure(settings["telegram_token"], settings["telegram_chat"])
        self._remote_telegram.send_text(
            f"ℹ️ Камера: проверка связи. Программа на компьютере {socket.gethostname()} на связи.")
        self._remote_telegram_status = "Telegram: пробное сообщение отправляется..."
        self.remoteMonitorChanged.emit()

    def _remote_sync_now(self):
        """Копирует журнал прогона и журнал калибровки прямо сейчас."""
        journal = str(self._chamber_file_path or "")
        if journal:
            self._remote_sync.enqueue(journal, "chamber")
        log = getattr(self, "_calibration_log", None)
        if log is not None:
            self._remote_sync.enqueue(str(log.path), "calibration")
        if not journal and log is None:
            self._remote_sync_status = "Копировать пока нечего: журнал прогона ещё не сохранялся."
            self._remote_sync_ok = False
        else:
            self._remote_sync_status = "Копирую журналы..."
        self.remoteMonitorChanged.emit()

    def _remote_sync_calibration_log(self, now: float):
        """Журнал калибровки пишется построчно, поэтому копируется раз в минуту."""
        log = getattr(self, "_calibration_log", None)
        if log is None or not self._remote_settings["sync_enabled"]:
            return
        if now - self._remote_last_calibration_sync_s < self.REMOTE_CALIBRATION_LOG_SYNC_S:
            return
        self._remote_last_calibration_sync_s = now
        self._remote_sync.enqueue(str(log.path), "calibration")

    # ------------------------------------------------------------------ история и устойчивость

    def _remote_watch_history(self, now: float):
        """Раз в 10 с кладёт температуру платы и оба контура в историю и проверяет устойчивость."""
        if now - self._remote_last_history_s < self.REMOTE_HISTORY_STEP_S:
            return
        self._remote_last_history_s = now

        def fresh(key):
            if not self._chamber_live_fresh(key, now):
                return None
            stats = self._chamber_live_stats(key, now)
            return None if stats is None else stats["mean"]

        board = fresh("board_temp")
        self._remote_history.append((now, None if board is None else board / 10.0, fresh("main"), fresh("media")))
        self._remote_check_stability(now)

    def _remote_board_rate(self, now: float):
        """Скорость и разброс температуры платы за окно устойчивости: (°C/мин, °C, охват с) или None."""
        return rate_and_spread(((stamp, board) for stamp, board, _main, _media in self._remote_history),
                               now, self.REMOTE_STABLE_WINDOW_S)

    def _remote_check_stability(self, now: float):
        """Правило прогона: плата устоялась, если 5 минут меняется медленнее 0,05 °C/мин."""
        result = self._remote_board_rate(now)
        if result is None:
            self._remote_stable_text = "Температура платы: истории ещё мало."
            self._remote_stable_ok = False
            return
        rate, spread, covered = result
        rate_text = f"{rate:+.3f} °C/мин".replace(".", ",")
        full_window = covered >= self.REMOTE_STABLE_WINDOW_S * 0.9
        stable = is_stable(result, self.REMOTE_STABLE_WINDOW_S, self.REMOTE_STABLE_RATE_C_MIN,
                           self.REMOTE_STABLE_SPREAD_C)
        board = self._remote_history[-1][1]

        if stable:
            self._remote_stable_text = f"Плата устоялась: {rate_text} за 5 мин. Можно снимать точки."
            self._remote_stable_ok = True
            if not self._remote_stable_announced:
                self._remote_stable_announced = True
                node = None if board is None else chamber_fit.nearest_node(int(round(board * 10)))
                where = f"узел {chamber_fit.node_text(node)}" if node is not None else "вне узлов сетки"
                board_text = "?" if board is None else f"{board:+.1f}".replace(".", ",")
                self._remote_event(f"плата устоялась при {board_text} °C ({where}). Можно снимать точки.", "ok")
            return

        self._remote_stable_ok = False
        wait = "" if full_window else f", окно заполнено на {int(covered / self.REMOTE_STABLE_WINDOW_S * 100)} %"
        self._remote_stable_text = f"Плата ещё меняется: {rate_text}{wait}."
        if self._remote_stable_announced and abs(rate) > self.REMOTE_MOVING_RATE_C_MIN:
            self._remote_stable_announced = False
            self._remote_event(f"температура платы пошла: {rate_text}. Камера меняет температуру.", "info")

    def _remote_watch_device(self, now: float):
        """Следит за адаптером и прибором: о пропаже и возвращении сообщает один раз."""
        connected = bool(self._can.is_connect) and bool(self._can.is_trace)
        if not connected:
            if not self._remote_adapter_lost:
                self._remote_adapter_lost = True
                self._remote_event("адаптер CAN отключён или трассировка выключена: прибор не опрашивается.", "bad")
            return
        if self._remote_adapter_lost:
            self._remote_adapter_lost = False
            self._remote_event("адаптер CAN снова подключён.", "ok")

        seen = [float(stamp) for stamp in self._chamber_live_seen.values() if stamp > 0.0]
        if not seen:
            return
        silent = now - max(seen) > self.REMOTE_SILENCE_S
        if silent and not self._remote_device_silent:
            self._remote_device_silent = True
            self._remote_event(f"прибор не отвечает дольше {int(self.REMOTE_SILENCE_S)} с.", "bad")
        elif not silent and self._remote_device_silent:
            self._remote_device_silent = False
            self._remote_event("прибор снова отвечает.", "ok")

    # ------------------------------------------------------------------ снимок

    def _remote_snapshot(self) -> dict:
        """Всё, что показывает страница, одним набором простых значений."""
        now = time.monotonic()
        live = self._chamber_live_view()
        history = list(self._remote_history)

        def rounded(value, digits):
            return None if value is None else round(float(value), digits)

        write_open = getattr(self, "_chamber_chain_write_ready", None)
        return {
            "time": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "device": {
                "connected": bool(self._can.is_connect) and bool(self._can.is_trace),
                "freshText": live.get("freshText", ""),
                "freshOk": bool(live.get("freshOk")),
                "node": f"0x{int(self._resolve_calibration_target_sa()) & 0xFF:02X}",
                "writeOpen": bool(write_open()) if write_open is not None else False,
            },
            "live": {key: live.get(key) for key in ("main", "media", "fuelTemp", "boardTemp", "windowText")},
            "stability": {"text": self._remote_stable_text, "ok": self._remote_stable_ok},
            "run": {
                "points": len(self._chamber_points),
                "file": pathlib.Path(self._chamber_file_path).name if self._chamber_file_path else "",
                "status": str(self._chamber_status),
                "statusColor": str(self._chamber_status_color),
                "tablesText": str(self._chamber_tables_text),
                "tablesColor": str(self._chamber_tables_color),
                "coverage": self._chamber_coverage_rows(),
                "report": [str(item) for item in self._chamber_report],
                "rows": self._chamber_rows()[:15],
            },
            "chain": self._chamber_chain_view(),
            "climate": self._remote_climate_snapshot(),
            "test": self._chamber_test_view(),
            "history": {
                "t": [round(stamp - now, 1) for stamp, *_rest in history],
                "board": [rounded(board, 2) for _stamp, board, _main, _media in history],
                "main": [rounded(main, 1) for _stamp, _board, main, _media in history],
                "media": [rounded(media, 1) for _stamp, _board, _main, media in history],
            },
            "events": list(self._remote_events)[:30],
        }

    def _remote_climate_snapshot(self) -> dict:
        """Камера для страницы: температура, уставка, авария и ход автопрогона."""
        view = getattr(self, "_climate_view", None)
        if view is None:
            return {}
        climate = view()
        return {key: climate.get(key) for key in (
            "connected", "ok", "status", "chamber", "actualText", "setpointText", "runningText", "alarmText", "alarm",
            "run", "history")}

    def _remote_view(self) -> dict:
        """Состояние наблюдения для окна программы."""
        settings = self._remote_settings
        key = settings["server_key"]
        suffix = f"/?key={key}" if key else "/"
        addresses = [f"http://{address}:{int(settings['server_port'])}{suffix}" for address in local_addresses()]
        addresses.append(f"http://localhost:{int(settings['server_port'])}{suffix}")
        return {
            "serverEnabled": bool(settings["server_enabled"]),
            "serverPort": str(settings["server_port"]),
            "serverKey": str(key),
            "serverStatus": self._remote_server_status,
            "serverOk": self._remote_server_ok,
            "serverUrls": addresses if settings["server_enabled"] else [],
            "telegramEnabled": bool(settings["telegram_enabled"]),
            "telegramToken": str(settings["telegram_token"]),
            "telegramChat": str(settings["telegram_chat"]),
            "telegramPoints": bool(settings["telegram_points"]),
            "telegramFiles": bool(settings["telegram_files"]),
            "telegramStatus": self._remote_telegram_status,
            "telegramOk": self._remote_telegram_ok,
            "syncEnabled": bool(settings["sync_enabled"]),
            "syncMode": str(settings["sync_mode"]),
            "syncFolder": str(settings["sync_folder"]),
            "syncHost": str(settings["sync_host"]),
            "syncPort": str(settings["sync_port"]),
            "syncUser": str(settings["sync_user"]),
            "syncPassword": str(settings["sync_password"]),
            "syncRemoteDir": str(settings["sync_remote_dir"]),
            "syncStatus": self._remote_sync_status,
            "syncOk": self._remote_sync_ok,
            "stableText": self._remote_stable_text,
            "stableOk": self._remote_stable_ok,
            "events": list(self._remote_events)[:12],
            "settingsPath": str(self._remote_settings_path()),
        }

    def _remote_shutdown(self):
        """Останавливает сервер и фоновые потоки при закрытии программы."""
        self._remote_server.stop()
        self._remote_telegram.close()
        self._remote_sync.close()
