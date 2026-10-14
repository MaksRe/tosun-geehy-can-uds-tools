"""Публичный HTTPS-адрес для мини-приложения Telegram: туннель ngrok или Cloudflare.

ЗАЧЕМ
Telegram открывает мини-приложение только по адресу https:// из интернета, а
программа работает на ноутбуке у камеры за заводской сетью. Туннель выдаёт
такой адрес и проводит запросы к нашему маленькому серверу на этом компьютере.

ПОСТАВЩИКИ
- Tailscale Funnel (рекомендуется). Бесплатный план Personal, постоянный адрес
  https://<компьютер>.<сеть>.ts.net, без месячного лимита запросов. Tailscale
  ставится на компьютер у камеры один раз; Funnel держит сама служба Tailscale,
  программа только включает его для своего порта и узнаёт адрес.
- ngrok. Бесплатно - 20 000 запросов и 1 ГБ в месяц: мини-приложение,
  открытое на сутки, выбирает это за сутки. Бесплатная учётная запись на ngrok.com; агенту выдаётся
  постоянный адрес вида https://<слова>.ngrok-free.dev - он не меняется при
  перезапуске. Работает по обычному https (TCP 443), поэтому проходит почти
  любую заводскую сеть. В бесплатном тарифе одновременно может работать только
  один агент ngrok на учётную запись.
- Cloudflare (запасной). Без регистрации, но адрес меняется при каждом запуске,
  нужен исходящий TCP-порт 7844, а при частых запусках Cloudflare временно
  отказывает в новых адресах (ответ 429).

Что видно через туннель - только мини-приложение. Данные оно получает лишь
для одобренных в боте пользователей: каждый запрос подписан Telegram.

КАК УСТРОЕНО
Агент туннеля запускается отдельным процессом без окна; адрес берётся из его
вывода и отдаётся боту только когда туннель действительно соединился - иначе
Telegram откроет страницу ошибки. Весь вывод пишется в журнал для разбора.
Процесс завершился - через паузу запускается снова; после неудач пауза растёт.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

RESTART_PAUSE_S = 15.0
# Повторы после неудач: пауза удваивается до предела, чтобы не плодить запросы к поставщику.
MAX_RESTART_PAUSE_S = 15 * 60.0
# Поставщик ответил 429 - слишком много новых туннелей: первая пауза не меньше 2 минут.
RATE_LIMIT_PAUSE_S = 120.0
# Сколько ждать соединения после выдачи адреса, прежде чем назвать проблему, с.
REGISTER_WAIT_S = 40.0

CLOUDFLARE_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CLOUDFLARE_REGISTERED = "Registered tunnel connection"
NGROK_ERROR_CODE = re.compile(r"ERR_NGROK_\d+")
# ngrok повторяет присланный токен в тексте ошибки: его нельзя показывать в окне и писать в журнал.
TOKEN_ECHO = re.compile(r"(Your authtoken:\s*)\S+", re.IGNORECASE)
# Частые ошибки ngrok - словами, что делать.
NGROK_ERRORS = {
    "ERR_NGROK_4018": "ngrok не знает вашу учётную запись: впишите в поле «Токен ngrok» Authtoken со страницы "
                      "dashboard.ngrok.com/get-started/your-authtoken",
    "ERR_NGROK_105": "это не Authtoken: нужен именно Authtoken (не API Key и не Access Key) со страницы "
                     "dashboard.ngrok.com/get-started/your-authtoken",
    "ERR_NGROK_107": "Authtoken ngrok неверный или отозван: скопируйте его заново со страницы "
                     "dashboard.ngrok.com/get-started/your-authtoken",
    "ERR_NGROK_108": "с этой учётной записью ngrok уже работает другой агент (бесплатно - только один): "
                     "закройте ngrok на другом компьютере",
    "ERR_NGROK_334": "этот адрес ngrok уже занят другим запущенным агентом: закройте его",
    "ERR_NGROK_313": "свой адрес ngrok недоступен в бесплатном тарифе: оставьте поле «Адрес ngrok» пустым",
    "ERR_NGROK_15002": "свой адрес ngrok недоступен в бесплатном тарифе: оставьте поле «Адрес ngrok» пустым",
}


def find_tool(configured: str, names: tuple[str, ...]) -> str:
    """Путь к программе туннеля: из настроек (файл или папка), рядом с программой, в tools или в PATH."""
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    folders = []
    if configured:
        given = Path(configured.strip().strip('"'))
        if given.is_file():
            return str(given)
        folders.append(given)
    folders += [base, base / "tools"]
    for folder in folders:
        for name in names:
            if (folder / name).is_file():
                return str(folder / name)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return ""


def find_cloudflared(configured: str = "") -> str:
    """Путь к cloudflared. Пусто - не найден."""
    return find_tool(configured, ("cloudflared.exe", "cloudflared"))


def find_ngrok(configured: str = "") -> str:
    """Путь к ngrok. Пусто - не найден."""
    return find_tool(configured, ("ngrok.exe", "ngrok"))


def find_tailscale(configured: str = "") -> str:
    """Путь к tailscale (командная строка Tailscale). Пусто - не найден."""
    found = find_tool(configured, ("tailscale.exe", "tailscale"))
    if found:
        return found
    standard = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
    return str(standard) if standard.is_file() else ""


def ngrok_config_has_token() -> bool:
    """Записан ли токен в обычном файле настроек ngrok (команда «ngrok config add-authtoken»)."""
    folders = [os.environ.get("LOCALAPPDATA", ""), os.path.join(os.path.expanduser("~"), ".config"),
               os.path.join(os.path.expanduser("~"), "Library", "Application Support")]
    for folder in folders:
        if not folder:
            continue
        path = Path(folder) / "ngrok" / "ngrok.yml"
        try:
            if "authtoken:" in path.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def parse_url(line: str) -> str:
    """Адрес туннеля Cloudflare из строки вывода cloudflared или пусто."""
    match = CLOUDFLARE_URL.search(str(line))
    return match.group(0) if match else ""


def restart_pause(failures: int, rate_limited: bool) -> float:
    """Пауза перед следующим запуском: 15 с, 30 с, 1 мин... до 15 мин; при отказе 429 - от 2 мин."""
    base = RATE_LIMIT_PAUSE_S if rate_limited else RESTART_PAUSE_S
    return min(MAX_RESTART_PAUSE_S, base * (2 ** max(0, int(failures) - 1)))


def pause_text(seconds: float) -> str:
    """Пауза словами: «15 с» или «4 мин»."""
    return f"{int(seconds)} с" if seconds < 60 else f"{int(round(seconds / 60))} мин"


def tunnel_command(exe: str, port: int) -> list[str]:
    """Команда cloudflared: быстрый туннель к локальному порту по http2 (TCP), без автообновления.

    По умолчанию cloudflared пробует QUIC по UDP 7844, а в заводских сетях UDP
    часто закрыт: адрес выдаётся, но соединения нет («Error 1033»).
    """
    return [str(exe), "tunnel", "--no-autoupdate", "--protocol", "http2", "--url", f"http://127.0.0.1:{int(port)}"]


def ngrok_command(exe: str, port: int, domain: str = "") -> list[str]:
    """Команда ngrok: туннель к локальному порту, журнал в JSON на вывод; свой адрес - по желанию."""
    command = [str(exe), "http", f"http://127.0.0.1:{int(port)}", "--log=stdout", "--log-format=json",
               "--log-level=info"]
    domain = str(domain or "").strip()
    if domain:
        command += ["--url", domain if domain.startswith("https://") else "https://" + domain]
    return command


class TunnelProcess:
    """Общий каркас туннеля: процесс агента, журнал, адрес после соединения, повторы с паузой.

    Наследник задаёт команду, окружение и разбор строк вывода (parse_line).
    """

    NAME = "туннель"

    def __init__(self, on_url: Callable[[str], None], on_status: Callable[[str, bool], None],
                 log_path: Path | None = None):
        self._on_url = on_url
        self._on_status = on_status
        # Журнал вывода агента: по нему видно, почему туннель не соединился.
        self._log_path = Path(log_path) if log_path is not None else None
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._url = ""
        self._port = 0
        self._exe = ""
        self._options: dict = {}

    @property
    def url(self) -> str:
        with self._lock:
            return self._url

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: int, exe: str, **options):
        """Запускает туннель к http://127.0.0.1:port. Повторный вызов с теми же данными ничего не меняет."""
        if self.running and port == self._port and exe == self._exe and options == self._options:
            return
        self.stop()
        self._port = int(port)
        self._exe = str(exe)
        self._options = dict(options)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name=f"tunnel-{self.NAME}")
        self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            process = self._process
            self._process = None
            had_url = bool(self._url)
            self._url = ""
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    process.kill()
                except Exception:  # noqa: BLE001
                    pass
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        if had_url:
            self._on_url("")

    # ------------------------------------------------------------------ для наследников

    def command(self) -> list[str]:
        raise NotImplementedError

    def environment(self) -> dict | None:
        """Окружение процесса; None - как у программы."""
        return None

    def parse_line(self, line: str, state: dict):
        """Разбор строки вывода: заполняет state["url"], ["ready"], ["error"], ["rate_limited"]."""
        raise NotImplementedError

    def redact(self, text: str) -> str:
        """Строка без секретов (токен ngrok): для журнала и окна."""
        text = TOKEN_ECHO.sub(r"\1***", str(text))
        secret = str(self._options.get("authtoken", "") or "").strip()
        return text.replace(secret, "***") if len(secret) >= 8 else text

    def no_connection_text(self, state: dict) -> str:
        """Адрес выдан, а соединения нет: что сказать оператору."""
        return f"{self.NAME}: адрес выдан, но соединения нет. Последняя ошибка: {state.get('error') or 'нет'}"

    # ------------------------------------------------------------------ работа

    def _open_log(self):
        """Журнал заново при каждом запуске процесса. Нет журнала - не беда."""
        if self._log_path is None:
            return None
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            return self._log_path.open("w", encoding="utf-8")
        except OSError:
            return None

    def _watch_registration(self, process, state: dict):
        """Адрес выдан, а соединения всё нет: назвать вероятную причину, а не молчать."""
        if self._stop.wait(REGISTER_WAIT_S) or state.get("ready") or process.poll() is not None:
            return
        self._on_status(f"{self.no_connection_text(state)}. Подробности - в журнале "
                        f"{self._log_path or self.NAME}.", False)

    def _worker(self):
        # Неудачные запуски подряд (без соединения): от них растёт пауза перед повтором.
        failures = 0
        while not self._stop.is_set():
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                process = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, creationflags=flags, env=self.environment())
            except OSError as error:
                self._on_status(f"{self.NAME} не запустился: {error}", False)
                self._stop.wait(RESTART_PAUSE_S)
                continue
            with self._lock:
                self._process = process
            self._on_status(f"{self.NAME}: запускается, жду адрес...", True)
            log = self._open_log()
            # Адрес отдаётся боту только после соединения: иначе Telegram откроет страницу ошибки.
            state: dict = {"url": "", "ready": False, "error": "", "rate_limited": False}
            announced = ""
            for raw in iter(process.stdout.readline, b""):
                if self._stop.is_set():
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if log is not None:
                    try:
                        log.write(self.redact(line) + "\n")
                        log.flush()
                    except OSError:
                        pass
                self.parse_line(line, state)
                if state["url"] and not announced and not state["ready"]:
                    announced = state["url"]
                    self._on_status(f"{self.NAME}: адрес получен, туннель соединяется...", True)
                    threading.Thread(target=self._watch_registration, args=(process, state), daemon=True,
                                     name=f"tunnel-{self.NAME}-wait").start()
                if state["ready"] and state["url"] and self.url != state["url"]:
                    announced = state["url"]
                    with self._lock:
                        self._url = state["url"]
                    self._on_url(state["url"])
                    self._on_status(f"{self.NAME} работает: {state['url']}", True)
            process.wait()
            if log is not None:
                log.close()
            with self._lock:
                self._process = None
                lost = bool(self._url)
                self._url = ""
            if lost:
                self._on_url("")
            if self._stop.is_set():
                break
            failures = 0 if state["ready"] else failures + 1
            pause = restart_pause(max(1, failures), state["rate_limited"])
            self._on_status(f"{self._failure_text(state, process.returncode)}. Повтор через {pause_text(pause)}.",
                            False)
            self._stop.wait(pause)

    def _failure_text(self, state: dict, returncode) -> str:
        if state["rate_limited"]:
            return (f"{self.NAME} временно не даёт новый адрес: с этого компьютера слишком часто создавались "
                    "туннели (ответ 429). Это пройдёт само")
        if state["error"]:
            return f"{self.NAME} не работает: {state['error']}"
        if state["url"] and not state["ready"]:
            return self.no_connection_text(state)
        return f"{self.NAME} остановился (код {returncode})"


class NgrokTunnel(TunnelProcess):
    """Туннель ngrok: постоянный адрес учётной записи, работает по обычному https.

    Параметры start: authtoken (пусто - из настроек самого ngrok), domain (свой
    адрес; пусто - выданный учётной записи).
    """

    NAME = "ngrok"

    def command(self) -> list[str]:
        return ngrok_command(self._exe, self._port, self._options.get("domain", ""))

    def environment(self) -> dict | None:
        # Токен - через окружение, а не в командной строке: её видно в списке процессов.
        token = str(self._options.get("authtoken", "") or "").strip()
        if not token:
            return None
        return dict(os.environ, NGROK_AUTHTOKEN=token)

    def parse_line(self, line: str, state: dict):
        try:
            data = json.loads(line)
        except ValueError:
            data = None
        if isinstance(data, dict):
            if data.get("msg") == "started tunnel" and str(data.get("url", "")).startswith("https://"):
                state["url"] = str(data["url"])
                state["ready"] = True
            problem = str(data.get("err") or "")
            if data.get("lvl") in ("eror", "crit") and problem and problem != "<nil>":
                self._note_error(state, problem)
            return
        # Без JSON ngrok повторяет тяжёлую ошибку строками «ERROR: ...»; пустые и хвостовые не затирают причину.
        if line.startswith("ERROR"):
            text = line[len("ERROR:"):].strip() if line.startswith("ERROR:") else line
            if text:
                self._note_error(state, text)

    def _note_error(self, state: dict, text: str):
        """Запоминает причину: ошибка с кодом ngrok важнее любой строки без кода, первая - важнее следующих."""
        known = bool(NGROK_ERROR_CODE.search(text))
        if not state["error"] or (known and not state.get("error_known")):
            state["error"] = self.redact(self._explain(text))
            state["error_known"] = known

    @staticmethod
    def _explain(text: str) -> str:
        match = NGROK_ERROR_CODE.search(text)
        if match and match.group(0) in NGROK_ERRORS:
            return f"{NGROK_ERRORS[match.group(0)]} ({match.group(0)})"
        first = " ".join(str(text).split())
        return first[:200]


class CloudflareTunnel(TunnelProcess):
    """Быстрый туннель Cloudflare: без регистрации, адрес меняется при каждом запуске."""

    NAME = "Туннель Cloudflare"

    def command(self) -> list[str]:
        return tunnel_command(self._exe, self._port)

    def parse_line(self, line: str, state: dict):
        if " ERR " in line:
            state["error"] = line.split(" ERR ", 1)[1][:160]
        if "status 429" in line or "Too Many Requests" in line:
            state["rate_limited"] = True
        url = parse_url(line)
        if url and not state["url"]:
            state["url"] = url
        if CLOUDFLARE_REGISTERED in line and state["url"]:
            state["ready"] = True
            state["error"] = ""

    def no_connection_text(self, state: dict) -> str:
        return (f"Cloudflare выдал адрес, но соединение с ним не установлено за {int(REGISTER_WAIT_S)} с: похоже, "
                f"сеть закрывает порт 7844 (TCP). Последняя ошибка: {state.get('error') or 'нет'}")

    def _failure_text(self, state: dict, returncode) -> str:
        if state["rate_limited"]:
            return ("Cloudflare временно не даёт новый адрес: с этого компьютера слишком часто создавались "
                    "туннели (ответ 429). Это пройдёт само")
        if state["url"] and not state["ready"]:
            return self.no_connection_text(state)
        return f"Туннель Cloudflare остановился (код {returncode})"


class TailscaleFunnel:
    """Tailscale Funnel: публичный https-адрес компьютера в сети Tailscale для порта программы.

    В отличие от ngrok и Cloudflare, туннель держит сама служба Tailscale: программа
    включает Funnel («tailscale funnel --bg --https=443 http://127.0.0.1:ПОРТ»), берёт
    адрес компьютера из «tailscale status --json» и раз в минуту проверяет, что
    Tailscale на связи. При остановке Funnel выключается. Если Funnel в сети Tailscale
    ещё не разрешён, tailscale печатает ссылку, по которой его разрешают в один клик, -
    она показывается в строке состояния.
    """

    NAME = "Tailscale Funnel"
    CHECK_EVERY_S = 60.0
    COMMAND_TIMEOUT_S = 40.0
    ENABLE_LINK = re.compile(r"https://login\.tailscale\.com/\S+")

    def __init__(self, on_url: Callable[[str], None], on_status: Callable[[str, bool], None],
                 log_path: Path | None = None):
        self._on_url = on_url
        self._on_status = on_status
        self._log_path = Path(log_path) if log_path is not None else None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._url = ""
        self._port = 0
        self._exe = ""
        self._options: dict = {}

    @property
    def url(self) -> str:
        with self._lock:
            return self._url

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, port: int, exe: str, **options):
        """Включает Funnel для порта. Повторный вызов с теми же данными ничего не меняет."""
        if self.running and port == self._port and exe == self._exe and options == self._options:
            return
        self.stop()
        self._port, self._exe, self._options = int(port), str(exe), dict(options)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="tunnel-tailscale")
        self._thread.start()

    def stop(self):
        """Выключает Funnel для порта программы."""
        was_running = self.running
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        had_url = bool(self.url)
        with self._lock:
            self._url = ""
        if was_running and self._exe and self._port:
            self._run(self._funnel_command() + ["off"])
        if had_url:
            self._on_url("")

    def _funnel_command(self) -> list[str]:
        return [self._exe, "funnel", "--bg", "--https=443", f"http://127.0.0.1:{self._port}"]

    def _run(self, command: list[str]) -> tuple[int, str]:
        """Команда tailscale: код возврата и вывод (вывод - в журнал)."""
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            done = subprocess.run(command, capture_output=True, timeout=self.COMMAND_TIMEOUT_S, creationflags=flags,
                                  stdin=subprocess.DEVNULL)
            output = (done.stdout + done.stderr).decode("utf-8", errors="replace")
            code = done.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            output, code = str(error), -1
        if self._log_path is not None:
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as log:
                    log.write(f"$ tailscale {' '.join(command[1:])}\n{output.strip()}\n(код {code})\n")
            except OSError:
                pass
        return code, output

    def _address(self) -> tuple[str, str]:
        """Адрес https компьютера в Tailscale и причина, если его нет."""
        code, output = self._run([self._exe, "status", "--json"])
        if code != 0 or "{" not in output:
            return "", "Tailscale не отвечает: запустите Tailscale и войдите в учётную запись"
        try:
            data = json.loads(output[output.index("{"):])
        except ValueError:
            return "", "Tailscale ответил непонятно"
        if data.get("BackendState") != "Running":
            return "", f"Tailscale не на связи (состояние {data.get('BackendState')}): войдите в учётную запись"
        name = str((data.get("Self") or {}).get("DNSName") or "").rstrip(".")
        if not name:
            return "", "у компьютера нет имени в Tailscale: включите MagicDNS в настройках сети Tailscale"
        return f"https://{name}/", ""

    def _enable(self) -> bool:
        """Включает Funnel. False - не вышло (причина уже в строке состояния)."""
        code, output = self._run(self._funnel_command())
        link = self.ENABLE_LINK.search(output)
        if link:
            self._on_status(f"Funnel в сети Tailscale ещё не разрешён: откройте {link.group(0)} и разрешите - "
                            "программа включит его сама.", False)
            return False
        if code != 0:
            self._on_status(f"Tailscale Funnel не включился: {' '.join(output.split())[:200]}", False)
            return False
        return True

    def _worker(self):
        self._on_status("Tailscale Funnel: включаю...", True)
        enabled = False
        while not self._stop.is_set():
            if not enabled:
                enabled = self._enable()
            if enabled:
                url, problem = self._address()
                if url and url != self.url:
                    with self._lock:
                        self._url = url
                    self._on_url(url)
                    self._on_status(f"Tailscale Funnel работает: {url}", True)
                elif problem:
                    if self.url:
                        with self._lock:
                            self._url = ""
                        self._on_url("")
                    self._on_status(problem, False)
                    enabled = False
            self._stop.wait(self.CHECK_EVERY_S)

