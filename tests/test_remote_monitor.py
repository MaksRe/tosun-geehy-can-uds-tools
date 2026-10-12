"""Проверки наблюдения за прогоном издалека.

Рабочее место далеко от камеры, и наблюдение - единственный способ узнать, что
там происходит. Тесты закрепляют:
- мини-приложение отдаёт данные только одобренным пользователям бота по
  подписи Telegram; отладочный снимок закрыт без ключа; журналы скачиваются,
  а файлы вне разрешённых папок - нет;
- копия журнала доходит до сетевой папки целиком;
- бот: заявки и одобрение, код доступа, уровни уведомлений и переключатели
  у каждого пользователя, кнопки настроек; неудача отправки называется;
- «плата устоялась» объявляется один раз по правилу прогона, а «пошла» - когда
  камера сменила температуру;
- молчание прибора и его возвращение сообщаются по одному разу;
- настройки переживают перезапуск программы;
- снимок для страницы собирается и переводится в JSON.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import chamber_fit
from tests.test_chamber_run import _full_run_points
from tests.test_chamber_test_mode import _TestStub
from tests.test_chamber_run import _Signal
from ui.qml import telegram_bot
from ui.qml.controller.remote_monitor_mixin import AppControllerRemoteMonitorMixin, MiniAppAccess
from ui.qml.remote_file_sync import FileSyncConfig, RemoteFileSync
from ui.qml.remote_status_server import RemoteStatusServer
from ui.qml.telegram_bot import TelegramBot, TelegramUsers, sign_init_data, validate_init_data, wants


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# ------------------------------------------------------------------ страница

@pytest.fixture
def server(tmp_path: Path):
    instance = RemoteStatusServer("<html>страница</html>")
    folder = tmp_path / "chamber"
    folder.mkdir()
    (folder / "chamber_1.csv").write_text("Время;Что подключено\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("нельзя", encoding="utf-8")
    instance.set_folders({"прогон": folder})
    instance.set_snapshot({"run": {"points": 7}})
    # Снимок и файлы для отладки в сети - только по ключу; наблюдение идёт через мини-приложение.
    instance.set_key("k")
    assert instance.start(0) == ""
    yield instance
    instance.stop()


def _get(server, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}", timeout=5) as answer:
        return answer.status, answer.read()


def test_page_and_status_are_served(server):
    status, body = _get(server, "/")
    assert status == 200 and "страница" in body.decode("utf-8")

    status, body = _get(server, "/status.json?key=k")
    payload = json.loads(body.decode("utf-8"))
    assert payload["run"]["points"] == 7
    assert payload["files"][0]["name"] == "chamber_1.csv"


def test_journal_can_be_downloaded(server):
    status, body = _get(server, "/" + json.loads(_get(server, "/status.json?key=k")[1])["files"][0]["url"] + "&key=k")
    assert status == 200
    assert body.decode("utf-8").startswith("Время")


def test_files_outside_allowed_folders_are_refused(server):
    allowed = quote("прогон")
    for path in (f"/file?folder={allowed}&name=../secret.txt", f"/file?folder={quote('чужая')}&name=secret.txt",
                 f"/file?folder={allowed}&name=..%5Csecret.txt", f"/file?folder={allowed}&name=..%2Fsecret.txt"):
        with pytest.raises(urllib.error.HTTPError) as error:
            _get(server, path + "&key=k")
        assert error.value.code == 404


def test_key_protects_the_page(server):
    # Без ключа отладочный снимок закрыт совсем.
    server.set_key("")
    with pytest.raises(urllib.error.HTTPError) as error:
        _get(server, "/status.json")
    assert error.value.code == 403
    server.set_key("abc123")
    with pytest.raises(urllib.error.HTTPError) as error:
        _get(server, "/status.json")
    assert error.value.code == 403
    status, _body = _get(server, "/status.json?key=abc123")
    assert status == 200


def test_page_file_ships_with_the_program():
    """Мини-приложение лежит рядом с программой и попадает в сборку вместе с QML."""
    page = Path(__file__).resolve().parents[1] / "ui" / "qml" / "telegram_miniapp.html"
    text = page.read_text(encoding="utf-8")
    assert "telegram-web-app.js" in text and "api/state" in text and "X-Telegram-Init-Data" in text
    spec = (Path(__file__).resolve().parents[1] / "main.spec").read_text(encoding="utf-8")
    assert '"*.html"' in spec


# ------------------------------------------------------------------ копия журналов

def test_journal_copy_reaches_the_network_folder(tmp_path: Path):
    results = []
    sync = RemoteFileSync(lambda text, ok: results.append((text, ok)))
    try:
        target = tmp_path / "share"
        sync.configure(FileSyncConfig(enabled=True, folder=str(target)))
        source = tmp_path / "chamber_1.csv"
        source.write_text("первая версия", encoding="utf-8")
        sync.enqueue(source, "chamber")
        source.write_text("вторая версия", encoding="utf-8")
        sync.enqueue(source, "chamber")

        assert _wait(lambda: results)
        copied = target / "chamber" / "chamber_1.csv"
        assert copied.read_text(encoding="utf-8") == "вторая версия"
        assert not list((target / "chamber").glob("*.part"))
        assert results[-1][1] is True
    finally:
        sync.close()


def test_copy_without_target_says_what_is_missing(tmp_path: Path):
    results = []
    sync = RemoteFileSync(lambda text, ok: results.append((text, ok)))
    try:
        sync.configure(FileSyncConfig(enabled=True, folder=""))
        source = tmp_path / "a.csv"
        source.write_text("x", encoding="utf-8")
        sync.enqueue(source)
        assert _wait(lambda: results)
        assert results[-1][1] is False and "папка" in results[-1][0]
    finally:
        sync.close()


def test_disabled_copy_does_nothing(tmp_path: Path):
    sync = RemoteFileSync()
    try:
        sync.enqueue(tmp_path / "a.csv")
        assert sync._pending == {}
    finally:
        sync.close()


# ------------------------------------------------------------------ бот Telegram

TOKEN = "123:ABC"


def _drain(bot) -> list:
    """Всё, что бот поставил в очередь отправки (потоки бота уже остановлены)."""
    items = []
    while not bot._queue.empty():
        item = bot._queue.get_nowait()
        if item is not None:
            items.append(item)
    return items


def _messages(bot) -> list[tuple[str, str, dict | None]]:
    return [(payload["chat_id"], payload["text"], payload.get("reply_markup"))
            for kind, payload in _drain(bot) if kind == "send"]


@pytest.fixture
def bot(tmp_path: Path):
    """Бот без сети: потоки остановлены, отправки копятся в очереди."""
    instance = TelegramBot(TelegramUsers(tmp_path / "telegram_users.json"))
    instance.close()
    instance.configure(TOKEN, "1", "", {"level": "important", "points": True, "summaries": True, "files": True})
    _drain(instance)
    return instance


def _message(chat_id, text, name="Иван"):
    return {"message": {"chat": {"id": chat_id}, "from": {"first_name": name, "username": "ivan"}, "text": text}}


def _press(chat_id, data, message_id=10):
    return {"callback_query": {"id": "q", "data": data, "message": {"chat": {"id": chat_id}, "message_id": message_id}}}


def test_levels_decide_who_gets_what():
    user = {"approved": True, "level": "important", "points": True, "summaries": False, "files": True}
    assert not wants(user, "info") and wants(user, "ok") and wants(user, "bad")
    assert wants(user, "ok", "point") and not wants(user, "info", "summary") and wants(user, "info", "file")
    assert not wants(dict(user, level="alarms"), "warn") and wants(dict(user, level="alarms"), "bad")
    assert not wants(dict(user, level="alarms"), "ok", "point")
    assert wants(dict(user, level="all"), "info")
    assert not wants(dict(user, level="off"), "bad")
    assert not wants(dict(user, approved=False), "bad")


def test_admin_is_approved_by_the_settings(bot):
    admin = bot.users.get("1")
    assert admin["approved"] and admin["admin"] and admin["level"] == "all"


def test_new_user_waits_for_approval(bot):
    bot.handle_update(_message(5, "/start"))
    sent = _messages(bot)
    assert not bot.users.get("5")["approved"]
    assert any(chat == "5" and "Заявка" in text for chat, text, _markup in sent)
    request = [markup for chat, text, markup in sent if chat == "1"]
    assert request and request[0]["inline_keyboard"][0][0]["callback_data"] == "ok:5"

    # Без одобрения ни статуса, ни уведомлений.
    bot.handle_update(_message(5, "/status"))
    assert "Доступа пока нет" in _messages(bot)[0][1]
    bot.notify("АВАРИЯ", "bad")
    assert [chat for chat, _text, _markup in _messages(bot)] == ["1"]

    # Администратор нажимает «Одобрить» прямо в чате.
    bot.handle_update(_press(1, "ok:5"))
    assert bot.users.get("5")["approved"]
    assert any(chat == "5" and "одобрен" in text for chat, text, _markup in _messages(bot))


def test_access_code_connects_at_once(bot):
    bot.configure(TOKEN, "1", "K7Q", None)
    bot.handle_update(_message(6, "/start неверный"))
    assert not bot.users.get("6")["approved"]
    bot.handle_update(_message(7, "/start K7Q"))
    assert bot.users.get("7")["approved"] and bot.users.get("7")["level"] == "important"


def test_each_user_gets_messages_by_own_level(bot):
    bot.users.upsert("2", approved=True, level="all", points=False)
    bot.users.upsert("3", approved=True, level="alarms")
    bot.users.upsert("4", approved=True, level="off")
    _drain(bot)

    def to(level, kind="event"):
        bot.notify("x", level, kind)
        return sorted(chat for chat, _text, _markup in _messages(bot))

    assert to("info") == ["1", "2"]
    assert to("ok") == ["1", "2"]
    assert to("bad") == ["1", "2", "3"]
    assert to("ok", "point") == ["1"]
    assert to("info", "summary") == ["1", "2", "3"]
    bot.send_document(__file__, "журнал")
    assert sorted(chat for kind, (chat, _path, _caption) in _drain(bot) if kind == "document") == ["1", "2", "3"]


def test_settings_buttons_change_own_level(bot):
    bot.users.upsert("2", approved=True, level="important", points=True)
    bot.handle_update(_message(2, "/settings"))
    buttons = [button["callback_data"] for row in _messages(bot)[0][2]["inline_keyboard"] for button in row]
    assert "lvl:alarms" in buttons and "tog:points" in buttons

    bot.handle_update(_press(2, "lvl:alarms"))
    bot.handle_update(_press(2, "tog:points"))
    user = bot.users.get("2")
    assert user["level"] == "alarms" and user["points"] is False
    bot.handle_update(_message(2, "/stop"))
    assert bot.users.get("2")["level"] == "off"


def test_only_admin_manages_users(bot):
    bot.users.upsert("2", approved=True)
    bot.users.upsert("5", approved=False)
    bot.handle_update(_press(2, "ok:5"))
    assert not bot.users.get("5")["approved"]
    assert bot.admin_action("rm", "1") == "Администратора убрать нельзя"
    bot.admin_action("rm", "5")
    assert bot.users.get("5") is None


def test_users_survive_a_restart(bot, tmp_path: Path):
    bot.users.upsert("2", approved=True, level="alarms", files=False)
    restored = TelegramUsers(tmp_path / "telegram_users.json")
    assert restored.get("2")["level"] == "alarms" and restored.get("2")["files"] is False


def test_chat_is_found_by_the_last_message(bot):
    found = []
    bot.find_chat(lambda chat, note: found.append((chat, note)))
    assert found[0][0] == "" and "напишите" in found[0][1]
    bot.handle_update(_message(222, "/start", name="Оператор"))
    found.clear()
    bot.find_chat(lambda chat, note: found.append((chat, note)))
    assert found == [("222", "найден чат «Оператор»")]


def test_menu_button_opens_the_miniapp(bot):
    bot.set_app_url("https://abc.trycloudflare.com")
    calls = [payload for kind, payload in _drain(bot) if kind == "call"]
    menu = [data for method, data in calls if method == "setChatMenuButton"]
    assert menu[0]["menu_button"]["web_app"]["url"] == "https://abc.trycloudflare.com"


def test_send_failure_is_named(monkeypatch, tmp_path: Path):
    results = []
    monkeypatch.setattr(telegram_bot, "RETRY_PAUSE_S", 0.0)
    instance = TelegramBot(TelegramUsers(None), lambda text, ok: results.append((text, ok)))
    try:
        def broken(method, data, timeout=None):
            if method == "getUpdates":
                time.sleep(0.05)
                return {"ok": True, "result": []}
            raise RuntimeError("нет сети")
        instance._call = broken
        instance.configure(TOKEN, "1")
        instance.send_to("1", "проверка")
        assert _wait(lambda: any("нет сети" in text for text, _ok in results))
        assert not [ok for text, ok in results if "нет сети" in text][0]
    finally:
        instance.close()


# ------------------------------------------------------------------ мини-приложение

def test_init_data_signature_is_checked():
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 42, "first_name": "Иван"})}
    signed = sign_init_data(fields, TOKEN)
    assert validate_init_data(signed, TOKEN)["id"] == 42
    assert validate_init_data(signed, "999:OTHER") is None
    assert validate_init_data(signed.replace("42", "43"), TOKEN) is None
    old = sign_init_data(dict(fields, auth_date="1000"), TOKEN)
    assert validate_init_data(old, TOKEN) is None
    assert validate_init_data("", TOKEN) is None


def _init_data(chat_id):
    return sign_init_data({"auth_date": str(int(time.time())), "user": json.dumps({"id": chat_id})}, TOKEN)


def _api(server, path, chat_id=None, body=None):
    headers = {"Content-Type": "application/json"}
    if chat_id is not None:
        headers["X-Telegram-Init-Data"] = _init_data(chat_id)
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as answer:
        return json.loads(answer.read().decode("utf-8"))


def test_miniapp_shows_data_only_to_approved_users(server, bot):
    server.set_access(MiniAppAccess(bot, server._resolve_file))
    bot.users.upsert("2", approved=True, level="important")
    bot.users.upsert("5", approved=False)

    state = _api(server, "/api/state", 2)
    assert state["run"]["points"] == 7 and state["me"]["id"] == "2" and "users" not in state
    assert state["files"][0]["name"] == "chamber_1.csv"
    for chat_id in (None, 5, 999):
        with pytest.raises(urllib.error.HTTPError) as error:
            _api(server, "/api/state", chat_id)
        assert error.value.code == 401

    # Администратор видит пользователей.
    assert {user["id"] for user in _api(server, "/api/state", 1)["users"]} == {"1", "2", "5"}


def test_miniapp_changes_own_settings_and_sends_files(server, bot):
    server.set_access(MiniAppAccess(bot, server._resolve_file))
    bot.users.upsert("2", approved=True, level="important", points=True)

    me = _api(server, "/api/settings", 2, {"level": "alarms", "points": False, "admin": True})["me"]
    assert me["level"] == "alarms" and me["points"] is False and me["admin"] is False

    answer = _api(server, "/api/sendfile", 2, {"folder": "прогон", "name": "chamber_1.csv"})
    assert "отправлен" in answer["text"]
    documents = [payload for kind, payload in _drain(bot) if kind == "document"]
    assert documents[0][0] == "2" and documents[0][1].endswith("chamber_1.csv")
    assert _api(server, "/api/sendfile", 2, {"folder": "прогон", "name": "../x"})["text"] == "файл не найден"


def test_only_admin_manages_users_in_miniapp(server, bot):
    server.set_access(MiniAppAccess(bot, server._resolve_file))
    bot.users.upsert("2", approved=True)
    bot.users.upsert("5", approved=False)
    with pytest.raises(urllib.error.HTTPError) as error:
        _api(server, "/api/users", 2, {"action": "ok", "id": "5"})
    assert error.value.code == 404
    answer = _api(server, "/api/users", 1, {"action": "ok", "id": "5"})
    assert "одобрен" in answer["text"] and bot.users.get("5")["approved"]


# ------------------------------------------------------------------ события и устойчивость

class _FakeBot:
    """Бот без сети: запоминает, что и с какой важностью ушло бы пользователям."""

    def __init__(self):
        self.sent = []
        self.documents = []

    @property
    def texts(self):
        return [text for text, _level, _kind in self.sent]

    def notify(self, text, level="info", kind="event"):
        self.sent.append((text, level, kind))

    def send_document(self, path, caption="", chat_ids=None):
        self.documents.append((path, caption))

    def configure(self, *_args):
        pass

    def set_app_url(self, _url):
        pass

    def set_status_text(self, _text):
        pass


class _FakeSync:
    def __init__(self):
        self.queued = []

    def enqueue(self, path, subdir=""):
        self.queued.append((str(path), subdir))

    def configure(self, *_args):
        pass


class _RemoteStub(AppControllerRemoteMonitorMixin, _TestStub):
    """Наблюдение поверх прогона, без Qt, сети и сервера."""

    def __init__(self, root: Path):
        _TestStub.__init__(self, root)
        self.remoteMonitorChanged = _Signal()
        self._remote_lock = __import__("threading").Lock()
        self._remote_incoming = []
        self._remote_found_chat = None
        self._remote_settings = self._remote_default_settings()
        self._remote_settings.update({"telegram_enabled": True, "server_enabled": True, "sync_enabled": True})
        self._remote_events = deque(maxlen=self.REMOTE_EVENTS_KEPT)
        self._remote_history = deque(maxlen=2000)
        self._remote_last_history_s = 0.0
        self._remote_stable_announced = False
        self._remote_stable_text = ""
        self._remote_stable_ok = False
        self._remote_device_silent = False
        self._remote_adapter_lost = False
        self._remote_tables_were_complete = False
        self._remote_last_calibration_sync_s = 0.0
        self._remote_telegram = _FakeBot()
        self._remote_users = TelegramUsers(None)
        self._remote_public_url = ""
        self._remote_tunnel_status = ""
        self._remote_tunnel_ok = False
        self._remote_sync = _FakeSync()
        self._chamber_chain_steps = {key: "" for key, _title in self.CHAMBER_CHAIN_STEPS}
        self._chamber_chain_status = ""
        self._chamber_chain_color = ""


def _feed_board(stub, temps_c, step_s=10.0):
    """История платы: по значению на каждые step_s секунд, последнее - сейчас."""
    now = time.monotonic()
    stub._remote_history.clear()
    for index, value in enumerate(temps_c):
        stamp = now - (len(temps_c) - 1 - index) * step_s
        stub._remote_history.append((stamp, value, 5000.0, 4500.0))
        stub._remote_check_stability(stamp)
    return now


def test_board_settling_is_announced_once(tmp_path: Path):
    stub = _RemoteStub(tmp_path)
    # Камера доходит до -40 °C и стоит: 10 минут почти без изменений.
    _feed_board(stub, [-30 - index * 0.5 for index in range(20)] + [-40.0 + 0.001 * index for index in range(60)])

    assert stub._remote_stable_ok
    settled = [text for text in stub._remote_telegram.texts if "устоялась" in text]
    assert len(settled) == 1
    assert "узел -40 °C" in settled[0]


def test_short_history_is_not_called_stable(tmp_path: Path):
    """Две минуты ровной температуры ещё не означают, что плата прогрелась насквозь."""
    stub = _RemoteStub(tmp_path)
    _feed_board(stub, [25.0] * 12)
    assert not stub._remote_stable_ok
    assert not any("устоялась" in text for text in stub._remote_telegram.texts)


def test_moving_temperature_is_announced_after_settling(tmp_path: Path):
    stub = _RemoteStub(tmp_path)
    temps = [25.0] * 40 + [25.0 - index * 0.5 for index in range(1, 20)]
    _feed_board(stub, temps)

    assert any("пошла" in text for text in stub._remote_telegram.texts)
    assert not stub._remote_stable_ok


def test_silence_and_return_are_reported_once(tmp_path: Path):
    stub = _RemoteStub(tmp_path)
    now = time.monotonic()
    stub._chamber_live_seen["main"] = now - 40.0
    stub._remote_watch_device(now)
    stub._remote_watch_device(now + 1)
    assert sum("не отвечает" in text for text in stub._remote_telegram.texts) == 1

    stub._chamber_live_seen["main"] = now + 2
    stub._remote_watch_device(now + 2)
    assert any("снова отвечает" in text for text in stub._remote_telegram.texts)


def test_point_journal_and_profile_reach_the_workplace(tmp_path: Path):
    """Точка - сообщение, журнал - копия, записанный профиль - копия и файлы в чат."""
    stub = _RemoteStub(tmp_path)
    stub._chamber_label = "150/47"
    now = time.monotonic()
    for index in range(4):
        for key, value in (("main", 10955), ("media", 6441), ("board_temp", -400), ("fuel_temp", -400)):
            stub._chamber_live_note(key, value, now - 1 + index * 0.2)
    stub._chamber_capture_from_average()

    assert any("«150/47»" in text and "-40 °C" in text for text in stub._remote_telegram.texts)
    assert stub._remote_sync.queued[0] == (stub._chamber_file_path, "chamber")

    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    stub._remote_note_chain(True, "Профиль записан", str(profile))
    assert (str(profile), "chamber") in stub._remote_sync.queued
    assert [caption for _path, caption in stub._remote_telegram.documents] == ["Журнал прогона", "Записанный профиль"]


def test_point_goes_out_as_a_point(tmp_path: Path):
    """Точка уходит с видом «point»: бот пришлёт её только тем, у кого включены точки."""
    stub = _RemoteStub(tmp_path)
    point = dict(_full_run_points()[0])
    stub._chamber_points = [point]
    stub._remote_note_point(point)
    assert stub._remote_telegram.sent[-1][2] == "point"
    assert "записана" in stub._remote_events[0]["text"]


def test_view_lists_bot_users(tmp_path: Path):
    stub = _RemoteStub(tmp_path)
    stub._remote_users.upsert("1", approved=True, admin=True, name="Админ")
    stub._remote_users.upsert("5", name="Новый")
    view = stub._remote_view()
    assert [user["id"] for user in view["users"]] == ["1", "5"]
    assert view["users"][1]["levelTitle"] == "Важные"
    assert stub._remote_user_set("5", "level", "alarms") and stub._remote_users.get("5")["level"] == "alarms"
    assert not stub._remote_user_set("5", "level", "громко")
    assert stub._remote_user_set("5", "files", False) and stub._remote_users.get("5")["files"] is False


def test_complete_tables_are_announced_once(tmp_path: Path):
    stub = _RemoteStub(tmp_path)
    stub._remote_note_tables(True)
    stub._remote_note_tables(True)
    assert sum("хватило" in text for text in stub._remote_telegram.texts) == 1


def test_settings_survive_a_restart(tmp_path: Path):
    stub = _RemoteStub(tmp_path)
    stub._remote_apply_all = lambda: None
    assert stub._remote_set("telegram_chat", "777")
    assert stub._remote_set("server_port", "9000")
    assert not stub._remote_set("server_port", "99999")

    restored = _RemoteStub(tmp_path)
    loaded = restored._remote_load_settings()
    assert loaded["telegram_chat"] == "777"
    assert loaded["server_port"] == 9000


def test_snapshot_is_plain_json(tmp_path: Path):
    stub = _RemoteStub(tmp_path)
    stub._chamber_points = _full_run_points()
    stub._chamber_auto_write = True
    _feed_board(stub, [25.0] * 5)

    snapshot = stub._remote_snapshot()
    text = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["run"]["points"] == len(stub._chamber_points)
    assert len(snapshot["run"]["coverage"]) == len(chamber_fit.NODES_X10)
    assert len(snapshot["history"]["board"]) == 5
    assert json.loads(text)["device"]["node"] == "0x6A"


# ------------------------------------------------------------------ туннель Cloudflare

class _FakeProcess:
    """cloudflared без сети: выдаёт заданные строки вывода и завершается."""

    def __init__(self, lines, gate=None):
        import io as _io
        self._lines = [line.encode("utf-8") + b"\n" for line in lines]
        self._gate = gate
        self.returncode = None
        self.stdout = self
        self._buffer = _io.BytesIO()

    def readline(self):
        if not self._lines:
            if self._gate is not None:
                self._gate.wait(5)
            return b""
        return self._lines.pop(0)

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode

    def terminate(self):
        if self._gate is not None:
            self._gate.set()


def _run_tunnel(monkeypatch, tmp_path, lines):
    import threading
    from ui.qml import public_tunnel

    urls, statuses, commands = [], [], []
    gate = threading.Event()

    def fake_popen(command, **_kwargs):
        commands.append(command)
        return _FakeProcess(lines if len(commands) == 1 else [], gate)

    monkeypatch.setattr(public_tunnel.subprocess, "Popen", fake_popen)
    tunnel = public_tunnel.CloudflareTunnel(urls.append, lambda text, ok: statuses.append((text, ok)),
                                            tmp_path / "logs" / "cloudflared.log")
    tunnel.start(8765, "cloudflared.exe")
    _wait(lambda: any("соединяется" in text or "работает" in text for text, _ok in statuses))
    time.sleep(0.2)
    return tunnel, urls, statuses, commands, gate


def test_tunnel_url_is_given_only_after_connection(monkeypatch, tmp_path: Path):
    lines = ["INF |  https://quiet-river-test.trycloudflare.com  |",
             "INF Registered tunnel connection connIndex=0 protocol=http2"]
    tunnel, urls, statuses, commands, gate = _run_tunnel(monkeypatch, tmp_path, lines)
    try:
        assert "--protocol" in commands[0] and commands[0][commands[0].index("--protocol") + 1] == "http2"
        assert _wait(lambda: urls == ["https://quiet-river-test.trycloudflare.com"])
        assert tunnel.url == "https://quiet-river-test.trycloudflare.com"
        assert "Registered" in (tmp_path / "logs" / "cloudflared.log").read_text(encoding="utf-8")
    finally:
        gate.set()
        tunnel.stop()


def test_tunnel_without_connection_keeps_the_button_empty(monkeypatch, tmp_path: Path):
    """Адрес выдан, а соединения нет (закрыт порт 7844): боту адрес не отдаётся - иначе «Error 1033»."""
    lines = ["INF |  https://quiet-river-test.trycloudflare.com  |",
             "ERR Failed to dial a quic connection error=\"timeout: no recent network activity\""]
    tunnel, urls, statuses, _commands, gate = _run_tunnel(monkeypatch, tmp_path, lines)
    try:
        assert urls == [] and tunnel.url == ""
        assert any("соединяется" in text for text, _ok in statuses)
    finally:
        gate.set()
        tunnel.stop()


def test_restart_pause_grows_and_is_capped():
    from ui.qml.public_tunnel import MAX_RESTART_PAUSE_S, pause_text, restart_pause

    assert [restart_pause(n, False) for n in (1, 2, 3)] == [15.0, 30.0, 60.0]
    assert restart_pause(1, True) == 120.0 and restart_pause(2, True) == 240.0
    assert restart_pause(50, True) == MAX_RESTART_PAUSE_S
    assert pause_text(15) == "15 с" and pause_text(240) == "4 мин"


def test_rate_limit_is_named_and_waits_longer(monkeypatch, tmp_path: Path):
    """Cloudflare ответил 429: оператор видит причину, повтор не раньше чем через 2 минуты."""
    lines = ["INF Requesting new quick Tunnel on trycloudflare.com...",
             "quick tunnel provisioning failed with status 429"]
    from ui.qml import public_tunnel

    statuses = []
    monkeypatch.setattr(public_tunnel.subprocess, "Popen", lambda command, **_kwargs: _FakeProcess(list(lines)))
    tunnel = public_tunnel.CloudflareTunnel(lambda _url: None, lambda text, ok: statuses.append((text, ok)))
    tunnel.start(8765, "cloudflared.exe")
    try:
        assert _wait(lambda: any("429" in text for text, _ok in statuses))
        text, ok = [item for item in statuses if "429" in item[0]][0]
        assert not ok and "Повтор через 2 мин" in text
    finally:
        tunnel.stop()


# ------------------------------------------------------------------ туннель ngrok

def _ngrok_line(**fields):
    return json.dumps(dict({"t": "2026-10-12T16:20:00+0300", "lvl": "info"}, **fields))


def test_ngrok_command_keeps_the_token_out_of_the_command_line():
    from ui.qml.public_tunnel import NgrokTunnel, ngrok_command

    command = ngrok_command("ngrok.exe", 8765, "camera.ngrok-free.dev")
    assert command[:3] == ["ngrok.exe", "http", "http://127.0.0.1:8765"]
    assert "--log-format=json" in command and command[-2:] == ["--url", "https://camera.ngrok-free.dev"]
    assert "--url" not in ngrok_command("ngrok.exe", 8765, "")

    tunnel = NgrokTunnel(lambda _url: None, lambda _text, _ok: None)
    tunnel._exe, tunnel._port, tunnel._options = "ngrok.exe", 8765, {"authtoken": "SECRET", "domain": ""}
    assert "SECRET" not in " ".join(tunnel.command())
    assert tunnel.environment()["NGROK_AUTHTOKEN"] == "SECRET"
    tunnel._options = {"authtoken": "", "domain": ""}
    assert tunnel.environment() is None


def test_ngrok_url_comes_from_started_tunnel(monkeypatch, tmp_path: Path):
    import threading
    from ui.qml import public_tunnel

    lines = [_ngrok_line(msg="client session established"),
             _ngrok_line(msg="started tunnel", name="command_line", addr="http://127.0.0.1:8765",
                         url="https://quiet-river.ngrok-free.dev")]
    urls, statuses = [], []
    gate = threading.Event()
    monkeypatch.setattr(public_tunnel.subprocess, "Popen", lambda command, **_kwargs: _FakeProcess(list(lines), gate))
    tunnel = public_tunnel.NgrokTunnel(urls.append, lambda text, ok: statuses.append((text, ok)), tmp_path / "ngrok.log")
    tunnel.start(8765, "ngrok.exe", authtoken="", domain="")
    try:
        assert _wait(lambda: urls == ["https://quiet-river.ngrok-free.dev"])
        assert any("работает" in text and ok for text, ok in statuses)
    finally:
        gate.set()
        tunnel.stop()


def test_ngrok_errors_are_explained(monkeypatch):
    from ui.qml import public_tunnel

    lines = [_ngrok_line(lvl="eror", msg="session closing", err="authentication failed: Your account is limited to "
                                                                 "1 simultaneous ngrok agent sessions.\r\n\r\nERR_NGROK_108\r\n")]
    statuses = []
    monkeypatch.setattr(public_tunnel.subprocess, "Popen", lambda command, **_kwargs: _FakeProcess(list(lines)))
    tunnel = public_tunnel.NgrokTunnel(lambda _url: None, lambda text, ok: statuses.append((text, ok)))
    tunnel.start(8765, "ngrok.exe")
    try:
        assert _wait(lambda: any("ERR_NGROK_108" in text for text, _ok in statuses))
        text = [text for text, _ok in statuses if "ERR_NGROK_108" in text][0]
        assert "другой агент" in text and "Повтор через" in text
    finally:
        tunnel.stop()

    state = {"url": "", "ready": False, "error": "", "rate_limited": False}
    public_tunnel.NgrokTunnel(lambda _u: None, lambda _t, _o: None).parse_line(
        "ERROR:  authentication failed: Usage of ngrok requires a verified account and authtoken. ERR_NGROK_4018", state)
    assert "токен ngrok" in state["error"]


def test_tool_is_found_in_a_configured_folder(tmp_path: Path):
    from ui.qml.public_tunnel import find_ngrok

    (tmp_path / "ngrok.exe").write_bytes(b"")
    assert find_ngrok(str(tmp_path)) == str(tmp_path / "ngrok.exe")
    assert find_ngrok(f'"{tmp_path / "ngrok.exe"}"') == str(tmp_path / "ngrok.exe")

