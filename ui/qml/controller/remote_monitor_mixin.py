"""Наблюдение за прогоном издалека: бот Telegram, мини-приложение, копия журналов.

ЗАЧЕМ
Камера стоит далеко от рабочего места. Вся работа идёт на компьютере у камеры,
а этот модуль даёт видеть её издалека, не держа открытым удалённый стол:
- бот Telegram: кто написал ему /start - подписан; у каждого подписчика свой
  уровень уведомлений (все / важные / только аварии / без уведомлений) и
  переключатели (точки, сводки, файлы). Ни одобрений, ни администраторов;
- сайт и мини-приложение Telegram (одна страница): температуры, контуры,
  графики, ход прогона, проблемы, события, журналы. Открывается по адресу в
  любом браузере или кнопкой в боте, без входа и ключей; адрес https даёт
  туннель ngrok или Cloudflare, или свой сервер;
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
import socket
import threading
import time
from collections import deque
from datetime import datetime

from PySide6.QtCore import QTimer

import chamber_fit
from ui.qml.remote_file_sync import MODE_FOLDER, MODE_SFTP, FileSyncConfig, RemoteFileSync
from ui.qml.public_tunnel import (CloudflareTunnel, NgrokTunnel, TailscaleFunnel, find_cloudflared, find_ngrok,
                                  find_tailscale, ngrok_config_has_token)
from ui.qml.remote_status_server import RemoteStatusServer
from ui.qml.telegram_bot import (LEVEL_TITLES, LEVELS, OPTIONS, ROLE_TITLES, TelegramBot, TelegramUsers, can_control,
                                 public_user, validate_init_data)

from .contract import AppControllerContract
from .stability import is_stable, rate_and_spread

# Откуда адрес https мини-приложения: ngrok (основной), туннель Cloudflare или свой сервер.
MINIAPP_MODES = ("tailscale", "ngrok", "tunnel", "manual")
# Режимы, в которых адрес даёт туннель, запущенный программой.
TUNNEL_MODES = ("tailscale", "ngrok", "tunnel")


class MiniAppAccess:
    """Связь сайта с ботом: кто открыл страницу, его уведомления, права и действия управления.

    Смотреть сайт может любой. Кто это - сайт узнаёт по подписи Telegram
    (мини-приложение) или по ключу личной ссылки входа (/login в боте, обычный
    браузер). Управлять могут только админ и те, кому он дал право: действие
    уходит в программу (control), она проверит права, выполнит и запишет в
    журнал. Методы вызываются из потоков сервера, поэтому работают только с
    потокобезопасными подписчиками и очередями бота и программы.
    """

    def __init__(self, bot: TelegramBot, resolve_file, control=None):
        self.bot = bot
        self._resolve_file = resolve_file
        # Исполнитель действий управления: (номер чата, откуда, действие, параметры) -> (успех, текст).
        self._control = control
        # Имена из подписи Telegram: пригодятся, если человек подпишется прямо со страницы.
        self._names: dict[str, tuple[str, str]] = {}

    def user_for(self, init_data: str):
        """Номер чата того, кто открыл страницу в Telegram, или None (обычный браузер)."""
        user = validate_init_data(init_data, self.bot.token)
        if user is None:
            return None
        chat_id = str(user["id"])
        name = " ".join(part for part in (user.get("first_name"), user.get("last_name")) if part)
        self._names[chat_id] = (name, str(user.get("username") or ""))
        return chat_id

    def user_for_token(self, token: str):
        """Номер чата по ключу ссылки входа (обычный браузер) - только у тех, кто управляет."""
        chat_id = self.bot.users.find_by_token(token)
        return chat_id if chat_id is not None and can_control(self.bot.users.get(chat_id)) else None

    def me(self, chat_id: str) -> dict:
        """Подписан ли человек, что ему присылать и может ли он управлять."""
        user = self.bot.users.get(chat_id)
        if user is None:
            return {"id": chat_id, "subscribed": False, "role": "viewer", "canControl": False, "isAdmin": False}
        role = user.get("role", "viewer")
        return dict(public_user(user), id=chat_id, subscribed=True, roleTitle=ROLE_TITLES.get(role, ""),
                    canControl=can_control(user), isAdmin=role == "admin")

    def control(self, chat_id: str, channel: str, body: dict) -> tuple[bool, str]:
        """Действие управления от этого человека: права проверит программа."""
        if self._control is None:
            return False, "управление недоступно"
        params = {key: value for key, value in body.items() if key != "action"}
        return self._control(chat_id, channel, str(body.get("action", "")), params)

    def login_link(self, chat_id: str, renew: bool = False) -> str:
        return self.bot.login_link(chat_id, renew)

    def users_view(self) -> list[dict]:
        """Подписчики и их права - админу, чтобы раздавать право управлять."""
        return [{"id": chat_id, "name": user.get("name") or chat_id, "username": user.get("username", ""),
                 "role": user.get("role", "viewer"), "roleTitle": ROLE_TITLES.get(user.get("role", "viewer"), "")}
                for chat_id, user in sorted(self.bot.users.all().items(), key=lambda item: item[1].get("since", ""))]

    def update_settings(self, chat_id: str, payload: dict) -> dict:
        """Подписаться, отписаться или поменять свои уведомления прямо со страницы."""
        if payload.get("subscribed") is False:
            self.bot.users.remove(chat_id)
            return self.me(chat_id)
        name, username = self._names.get(chat_id, ("", ""))
        self.bot.subscribe(chat_id, name, username)
        fields = {}
        if payload.get("level") in LEVELS:
            fields["level"] = payload["level"]
        for key in OPTIONS:
            if key in payload:
                fields[key] = bool(payload[key])
        if fields:
            self.bot.users.upsert(chat_id, **fields)
        return self.me(chat_id)

    def send_file(self, chat_id: str, folder: str, name: str) -> str:
        path = self._resolve_file(folder, name)
        if path is None:
            return "файл не найден"
        self.bot.send_document(path, f"{folder}: {name}", [chat_id])
        return f"файл {name} отправлен в чат"

    def bot_info(self) -> dict:
        """Имя бота и ссылка «подписаться» для сайта."""
        name = self.bot.username
        return {"username": name, "link": f"https://t.me/{name}" if name else ""}


# Запасная страница, если файл мини-приложения не нашёлся рядом с программой.
FALLBACK_PAGE = ("<!doctype html><meta charset='utf-8'><title>Прогон в камере</title>"
                 "<p>Файл мини-приложения telegram_miniapp.html не найден рядом с программой.</p>")


class AppControllerRemoteMonitorMixin(AppControllerContract):
    REMOTE_TICK_MS = 1000
    REMOTE_DEFAULT_PORT = 8765
    # История для графика: шаг и длительность, с.
    REMOTE_HISTORY_STEP_S = 10.0
    REMOTE_HISTORY_SPAN_S = 3 * 3600.0
    # Правило «плата устоялась»: окно, предел скорости и разброса. Окно и скорость берутся из
    # текущего сценария (те же, по которым судит прогон), эти - если сценария нет.
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

        self._remote_server_status = "Сайт выключен."
        self._remote_server_ok = False
        self._remote_tunnel_status = ""
        self._remote_tunnel_ok = False
        self._remote_public_url = ""
        self._remote_telegram_status = "Telegram выключен."
        self._remote_telegram_ok = False
        self._remote_sync_status = "Копия журналов выключена."
        self._remote_sync_ok = False

        page_path = pathlib.Path(__file__).resolve().parent.parent / "telegram_miniapp.html"
        try:
            page = page_path.read_text(encoding="utf-8")
        except OSError:
            page = FALLBACK_PAGE
        self._remote_server = RemoteStatusServer(page)
        self._remote_users = TelegramUsers(self._remote_settings_path().with_name("telegram_users.json"))
        self._remote_telegram = TelegramBot(self._remote_users,
                                            lambda text, ok: self._remote_queue_status("telegram", text, ok))
        self._remote_server.set_access(MiniAppAccess(self._remote_telegram, self._remote_server._resolve_file,
                                                     self._remote_control))
        root = pathlib.Path(getattr(self, "_project_root_directory", None) or pathlib.Path.cwd())

        def tunnel(kind, mode, log_name):
            # Итоги каждого туннеля помечены режимом: окно учитывает только выбранный.
            return kind(lambda url: self._remote_queue_status(f"tunnel_url:{mode}", url, True),
                        lambda text, ok: self._remote_queue_status(f"tunnel:{mode}", text, ok),
                        root / "logs" / log_name)
        self._remote_tunnels = {"tailscale": tunnel(TailscaleFunnel, "tailscale", "tailscale.log"),
                                "ngrok": tunnel(NgrokTunnel, "ngrok", "ngrok.log"),
                                "tunnel": tunnel(CloudflareTunnel, "tunnel", "cloudflared.log")}
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
            "telegram_enabled": False,
            "telegram_token": "",
            "telegram_points": True,
            "telegram_files": True,
            # Новые подписчики бота: уровень и сводки по умолчанию.
            "telegram_default_level": "important",
            "telegram_summaries": True,
            # Рассылка только админам: на время тестов и экспериментов остальным ничего не уходит.
            "telegram_admin_only": False,
            # Мини-приложение: адрес https от туннеля Cloudflare или свой.
            "miniapp_mode": "tailscale",
            "miniapp_url": "",
            "cloudflared_path": "",
            # ngrok: путь, токен учётной записи (пусто - из настроек ngrok) и свой адрес (пусто - выданный).
            "ngrok_path": "",
            # Tailscale Funnel: путь к tailscale.exe (пусто - стандартная установка или PATH).
            "tailscale_path": "",
            "ngrok_authtoken": "",
            "ngrok_domain": "",
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
                if key in ("cloudflared_path", "ngrok_path", "tailscale_path"):
                    value = value.strip('"')
        except (TypeError, ValueError):
            self._remote_event("Порт задаётся числом от 1 до 65535.", "bad", telegram=False)
            self.remoteMonitorChanged.emit()
            return False
        if key == "sync_mode" and value not in (MODE_FOLDER, MODE_SFTP):
            return False
        if key == "telegram_default_level" and value not in LEVELS:
            return False
        if key == "miniapp_mode" and value not in MINIAPP_MODES:
            return False
        if key == "miniapp_url" and value and not value.startswith("https://"):
            self._remote_event("Адрес мини-приложения должен начинаться с https://", "bad", telegram=False)
            self.remoteMonitorChanged.emit()
            return False
        if self._remote_settings[key] == value:
            return True
        self._remote_settings[key] = value
        self._remote_save_settings()
        self._remote_apply_all()
        return True

    def _remote_user_remove(self, chat_id: str) -> bool:
        """Отписать подписчика из окна программы (например, если подписался по ошибке)."""
        user = self._remote_users.get(chat_id)
        removed = self._remote_users.remove(chat_id)
        if removed:
            self._remote_telegram_status = f"Telegram: {(user or {}).get('name') or chat_id} отписан."
        self.remoteMonitorChanged.emit()
        return removed

    def _remote_user_set(self, chat_id: str, key: str, value) -> bool:
        """Уровень или переключатель пользователя из окна программы."""
        if key == "level" and value not in LEVELS:
            return False
        if key != "level" and key not in OPTIONS:
            return False
        if self._remote_users.get(chat_id) is None:
            return False
        self._remote_users.upsert(chat_id, **{key: value if key == "level" else bool(value)})
        self.remoteMonitorChanged.emit()
        return True

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

        mode = settings["miniapp_mode"]
        tunnel = mode in TUNNEL_MODES
        if settings["server_enabled"]:
            self._remote_server.set_folders(self._remote_folders())
            # Для туннеля сервер слушает только этот компьютер: снаружи он виден лишь через туннель.
            host = "127.0.0.1" if tunnel else "0.0.0.0"
            if (not self._remote_server.running or self._remote_server.port != int(settings["server_port"])
                    or self._remote_server.host != host):
                problem = self._remote_server.start(int(settings["server_port"]), host)
                if problem:
                    self._remote_server_status = f"Сайт не запущен: {problem}."
                    self._remote_server_ok = False
                else:
                    self._remote_server_status = "Сайт работает."
                    self._remote_server_ok = True
            self._remote_apply_tunnels(mode if tunnel and self._remote_server.running else "")
        else:
            self._remote_server.stop()
            self._remote_apply_tunnels("")
            self._remote_server_status = "Сайт выключен."
            self._remote_server_ok = False
            self._remote_tunnel_status = ""
        self._remote_apply_app_url()

        if settings["telegram_enabled"]:
            defaults = {"level": settings["telegram_default_level"], "points": settings["telegram_points"],
                        "summaries": settings["telegram_summaries"], "files": settings["telegram_files"]}
            self._remote_telegram.configure(settings["telegram_token"], defaults)
            self._remote_telegram.set_admin_only(settings["telegram_admin_only"])
            if not settings["telegram_token"]:
                self._remote_telegram_status = "Впишите токен бота."
                self._remote_telegram_ok = False
            elif not self._remote_telegram_ok:
                self._remote_telegram_status = "Бот работает. Чтобы получать уведомления, напишите ему /start."
        else:
            self._remote_telegram.configure("")
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

    def _remote_apply_tunnels(self, active: str):
        """Запускает выбранный туннель и останавливает остальные. active пусто - все остановлены."""
        settings = self._remote_settings
        for mode, tunnel in self._remote_tunnels.items():
            if mode != active:
                tunnel.stop()
        self._remote_tunnel_status = ""
        self._remote_tunnel_ok = False
        if not active:
            return
        if active == "tailscale":
            exe = find_tailscale(settings["tailscale_path"])
            missing = ("Не найден Tailscale: установите его с tailscale.com/download, войдите в учётную запись "
                       "(бесплатный план Personal) и включите программу снова.")
            options = {}
        elif active == "ngrok":
            exe = find_ngrok(settings["ngrok_path"])
            missing = ("Не найден ngrok.exe: скачайте его с ngrok.com/download и положите рядом с программой "
                       "(или в папку tools) или укажите путь.")
            options = {"authtoken": settings["ngrok_authtoken"], "domain": settings["ngrok_domain"]}
        else:
            exe = find_cloudflared(settings["cloudflared_path"])
            missing = ("Не найден cloudflared.exe: скачайте его с github.com/cloudflare/cloudflared/releases и "
                       "положите рядом с программой или укажите путь.")
            options = {}
        if not exe:
            self._remote_tunnels[active].stop()
            self._remote_tunnel_status = missing
            return
        if active == "ngrok" and not settings["ngrok_authtoken"] and not ngrok_config_has_token():
            self._remote_tunnel_status = ("Для ngrok нужен токен учётной записи: зарегистрируйтесь на ngrok.com "
                                          "и впишите «Your Authtoken» в поле «Токен ngrok».")
        self._remote_tunnels[active].start(self._remote_server.port, exe, **options)

    def _remote_active_tunnel(self):
        """Туннель выбранного режима или None (свой адрес)."""
        return self._remote_tunnels.get(self._remote_settings["miniapp_mode"])

    def _remote_apply_app_url(self):
        """Адрес мини-приложения для кнопки бота: от туннеля или свой."""
        settings = self._remote_settings
        tunnel = self._remote_active_tunnel()
        if not settings["server_enabled"]:
            url = ""
        elif tunnel is not None:
            url = tunnel.url
        else:
            url = str(settings["miniapp_url"])
        self._remote_public_url = url
        self._remote_telegram.set_app_url(url)

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

    def _remote_event(self, text: str, level: str = "info", telegram: bool = True, kind: str = "event"):
        """Запоминает событие для мини-приложения и рассылает его в Telegram.

        Кому - решает бот: по одобрению, уровню и переключателям каждого
        пользователя. kind: «event», «point» (точка записана), «summary» (сводка).
        """
        self._remote_events.appendleft({
            "time": datetime.now().strftime("%H:%M:%S"),
            "text": str(text),
            "level": str(level),
        })
        if telegram and self._remote_settings["telegram_enabled"]:
            self._remote_telegram.notify(f"Камера: {text}", level, kind)
        self.remoteMonitorChanged.emit()

    def _remote_control(self, chat_id: str, channel: str, action: str, params: dict) -> tuple[bool, str]:
        """Действие управления с сайта или из мини-приложения (поток сервера): права и журнал - в программе."""
        submit = getattr(self, "_control_submit", None)
        if submit is None:
            return False, "управление недоступно"
        return submit(self._control_actor(chat_id, channel), action, params)

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
            "ok", kind="point")

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
        if self._remote_settings["telegram_enabled"]:
            # Файлы получают те, у кого включены «файлы».
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
            snapshot = self._remote_snapshot()
            if self._remote_server.running:
                self._remote_server.set_snapshot(snapshot)
            self._remote_telegram.set_status_text(self._remote_status_text(snapshot))
            # Отчёты бота (/status, /steps, /points...) - по тому же снимку, что видит мини-приложение.
            set_snapshot = getattr(self._remote_telegram, "set_snapshot", None)
            if set_snapshot is not None:
                set_snapshot(snapshot)
            changed = True
        if changed:
            self.remoteMonitorChanged.emit()

    def _remote_take_incoming(self) -> bool:
        """Забирает итоги фоновых потоков: отправки, туннеля, копирования."""
        with self._remote_lock:
            incoming = list(self._remote_incoming)
            self._remote_incoming.clear()
        for channel, text, ok in incoming:
            if channel == "telegram":
                self._remote_telegram_status = text
                self._remote_telegram_ok = ok
            elif channel.startswith("tunnel:"):
                # Запоздалые итоги остановленного туннеля не затирают состояние выбранного.
                if channel == f"tunnel:{self._remote_settings['miniapp_mode']}":
                    self._remote_tunnel_status = text
                    self._remote_tunnel_ok = ok
            elif channel.startswith("tunnel_url:"):
                self._remote_apply_app_url()
                if text:
                    self._remote_event(f"сайт доступен: {text}", "info", telegram=False)
            else:
                self._remote_sync_status = text
                self._remote_sync_ok = ok
        return bool(incoming)

    def _remote_test_message(self):
        """Пробное сообщение всем подписчикам: проверка бота и сети у камеры."""
        settings = self._remote_settings
        if not settings["telegram_enabled"] or not settings["telegram_token"]:
            self._remote_telegram_status = "Включите бота и впишите его токен."
            self._remote_telegram_ok = False
        elif self._remote_telegram.test() == 0:
            self._remote_telegram_status = ("Включена рассылка «только админу», а админов среди подписчиков нет: "
                                            "назначьте админа или выключите «только админу»."
                                            if settings["telegram_admin_only"] else
                                            "Подписчиков пока нет: напишите боту /start в Telegram и повторите.")
            self._remote_telegram_ok = False
        else:
            self._remote_telegram_status = (f"Telegram: пробное сообщение с компьютера {socket.gethostname()} "
                                            "отправляется подписчикам...")
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
                               now, self._remote_stable_rule()[0])

    def _remote_stable_rule(self) -> tuple[float, float]:
        """Окно (с) и предел скорости (°C/мин) признака «плата устоялась»: как в правилах сценария.

        Иначе сайт говорил бы «устоялась» по 5 мин и 0,05 °C/мин, пока прогон ждёт по своим правилам.
        """
        scenario = getattr(self, "_climate_scenario", None) or {}
        try:
            window = float(scenario.get("settle_min")) * 60.0
            rate = float(scenario.get("settle_rate"))
        except (TypeError, ValueError):
            return self.REMOTE_STABLE_WINDOW_S, self.REMOTE_STABLE_RATE_C_MIN
        return (window, rate) if window > 0 and rate > 0 else (self.REMOTE_STABLE_WINDOW_S, self.REMOTE_STABLE_RATE_C_MIN)

    def _remote_check_stability(self, now: float):
        """Правило прогона: плата устоялась, если за окно сценария меняется медленнее его порога."""
        window_s, rate_limit = self._remote_stable_rule()
        result = self._remote_board_rate(now)
        if result is None:
            self._remote_stable_text = "Температура платы: истории ещё мало."
            self._remote_stable_ok = False
            return
        rate, spread, covered = result
        rate_text = f"{rate:+.3f} °C/мин".replace(".", ",")
        full_window = covered >= window_s * 0.9
        stable = is_stable(result, window_s, rate_limit, self.REMOTE_STABLE_SPREAD_C)
        board = self._remote_history[-1][1]

        if stable:
            self._remote_stable_text = f"Плата устоялась: {rate_text} за {window_s / 60:g} мин. Можно снимать точки."
            self._remote_stable_ok = True
            if not self._remote_stable_announced:
                self._remote_stable_announced = True
                node = None if board is None else chamber_fit.nearest_node(int(round(board * 10)))
                where = f"узел {chamber_fit.node_text(node)}" if node is not None else "вне узлов сетки"
                board_text = "?" if board is None else f"{board:+.1f}".replace(".", ",")
                self._remote_event(f"плата устоялась при {board_text} °C ({where}). Можно снимать точки.", "ok")
            return

        self._remote_stable_ok = False
        wait = "" if full_window else f", окно заполнено на {int(covered / window_s * 100)} %"
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
            "stability": {"text": self._remote_stable_text, "ok": self._remote_stable_ok,
                          # Правило для графика скорости: окно, с, и порог, °C/мин - как у прогона.
                          "windowS": self._remote_stable_rule()[0], "rate": self._remote_stable_rule()[1]},
            "run": {
                "points": len(self._chamber_points),
                # Что подключено к прибору: с этой пометкой запишется ручная точка.
                "label": str(self._chamber_label),
                "file": pathlib.Path(self._chamber_file_path).name if self._chamber_file_path else "",
                "status": str(self._chamber_status),
                "statusColor": str(self._chamber_status_color),
                "tablesText": str(self._chamber_tables_text),
                "tablesColor": str(self._chamber_tables_color),
                "coverage": self._chamber_coverage_rows(),
                "report": [str(item) for item in self._chamber_report],
                # Точки журнала (свежие сверху, с номером и временем - по ним точку убирают издалека).
                "rows": self._chamber_rows()[:40],
                # Журналы на диске: свои и прошлых версий - открыть одной кнопкой с сайта и из бота.
                # Несколько плат в камере: у каждой свои показания, точки и профиль.
                "boards": [{key: row[key] for key in ("name", "saText", "active", "fresh", "boardTemp", "main", "media",
                                                      "points", "tablesComplete", "profile")}
                           for row in self._remote_boards_rows()],
                "journals": [{key: item[key] for key in ("id", "name", "folder", "points", "modified", "current")}
                             for item in self._chamber_journals()],
            },
            "chain": self._chamber_chain_view(),
            # Рассылка бота: всем или только админу (показ и переключатель у админа на сайте).
            "telegram": {"adminOnly": bool(self._remote_settings.get("telegram_admin_only"))},
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

    def _remote_status_text(self, snapshot: dict) -> str:
        """Что сейчас с прогоном - ответ бота на /status."""
        climate = snapshot.get("climate") or {}
        run = (climate.get("run") or {})
        auto = run.get("auto") or {}
        live = snapshot.get("live") or {}
        board = (live.get("boardTemp") or {}).get("now") or "—"
        lines = [f"Прогон {snapshot.get('time', '')}"]
        if climate:
            name = (climate.get("chamber") or {}).get("name", "камера")
            lines.append(f"{name}: {'на связи' if climate.get('ok') else 'нет связи'}; в камере "
                         f"{climate.get('actualText', '—')}, уставка {climate.get('setpointText', '—')}, "
                         f"{climate.get('runningText', '—')}, авария {climate.get('alarmText', '—')}.")
        lines.append(f"Плата {board}. {snapshot.get('stability', {}).get('text', '')}")
        if run.get("active"):
            lines.append(auto.get("progressText") or run.get("status", ""))
            lines.append(run.get("status", ""))
            for alert in auto.get("alerts") or []:
                lines.append(("❌ " if alert.get("level") == "bad" else "⚠️ ") + alert.get("text", ""))
        else:
            lines.append("Автопрогон не идёт.")
        lines.append(f"Точек в журнале: {(snapshot.get('run') or {}).get('points', 0)}.")
        return "\n".join(line for line in lines if line)

    def _remote_boards_rows(self) -> list[dict]:
        """Платы в камере для страницы и бота - только когда идёт работа с несколькими платами."""
        multi = getattr(self, "_mb_on", None)
        if not callable(multi) or not multi():
            return []
        return list(self._mb_view()["boards"])

    def _remote_climate_snapshot(self) -> dict:
        """Камера для страницы: температура, уставка, авария и ход автопрогона."""
        view = getattr(self, "_climate_view", None)
        if view is None:
            return {}
        climate = view()
        scenario = (climate.get("scenario") or {}).get("scenario") or {}
        active = bool(self._climate_run_stage)
        # Шаги для показа и правки: идущего прогона или текущего сценария.
        steps = [dict(step) for step in (self._climate_run_steps if active else scenario.get("steps") or [])]
        return {key: climate.get(key) for key in (
            "connected", "ok", "status", "chamber", "actualText", "setpointText", "runningText", "alarmText", "alarm",
            "run", "history", "espec", "control")} | {
            "scenario": (climate.get("scenario") or {}).get("summary", ""),
            "scenarioName": scenario.get("name", ""),
            "steps": steps,
            "runIndex": int(self._climate_run_index) if active else -1,
            "setpointValue": getattr(self._climate_reading, "setpoint_c", None) if getattr(self, "_climate_reading", None) else None,
        }

    def _remote_view(self) -> dict:
        """Состояние наблюдения для окна программы."""
        settings = self._remote_settings
        users = [dict(public_user(user), id=chat_id, levelTitle=LEVEL_TITLES.get(user["level"], ""),
                      roleTitle=ROLE_TITLES.get(user.get("role", "viewer"), ""))
                 for chat_id, user in self._remote_users.all().items()]
        control_view = getattr(self, "_control_view", None)
        control = control_view() if callable(control_view) else None
        users.sort(key=lambda item: item.get("since", ""))
        return {
            "users": users,
            "levels": [{"key": key, "title": LEVEL_TITLES[key]} for key in LEVELS],
            "botUsername": self._remote_telegram.username,
            "telegramDefaultLevel": str(settings["telegram_default_level"]),
            "telegramSummaries": bool(settings["telegram_summaries"]),
            "miniappMode": str(settings["miniapp_mode"]),
            "miniappUrl": str(settings["miniapp_url"]),
            "cloudflaredPath": str(settings["cloudflared_path"]),
            "cloudflaredFound": find_cloudflared(settings["cloudflared_path"]),
            "ngrokPath": str(settings["ngrok_path"]),
            "tailscalePath": str(settings["tailscale_path"]),
            "tailscaleFound": find_tailscale(settings["tailscale_path"]),
            "ngrokFound": find_ngrok(settings["ngrok_path"]),
            "ngrokAuthtoken": str(settings["ngrok_authtoken"]),
            "ngrokConfigured": bool(settings["ngrok_authtoken"]) or ngrok_config_has_token(),
            "ngrokDomain": str(settings["ngrok_domain"]),
            "publicUrl": self._remote_public_url,
            "tunnelStatus": self._remote_tunnel_status,
            "tunnelOk": self._remote_tunnel_ok,
            "serverEnabled": bool(settings["server_enabled"]),
            "serverPort": str(settings["server_port"]),
            "serverStatus": self._remote_server_status,
            "serverOk": self._remote_server_ok,
            "telegramEnabled": bool(settings["telegram_enabled"]),
            "telegramToken": str(settings["telegram_token"]),
            "telegramPoints": bool(settings["telegram_points"]),
            "telegramFiles": bool(settings["telegram_files"]),
            "telegramAdminOnly": bool(settings["telegram_admin_only"]),
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
            "controlLog": (control or {}).get("log", [])[:15],
            "controlLogPath": (control or {}).get("logPath", ""),
        }

    def _remote_shutdown(self):
        """Останавливает сервер и фоновые потоки при закрытии программы."""
        self._remote_server.stop()
        for tunnel in self._remote_tunnels.values():
            tunnel.stop()
        self._remote_telegram.reset_menu_now()
        self._remote_telegram.close()
        self._remote_sync.close()
