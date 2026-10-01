"""Проверки наблюдения за прогоном издалека.

Рабочее место далеко от камеры, и наблюдение - единственный способ узнать, что
там происходит. Тесты закрепляют:
- страница отдаёт состояние, без ключа не открывается, журналы скачиваются, а
  файлы вне разрешённых папок - нет;
- копия журнала доходит до сетевой папки целиком;
- сообщения в Telegram уходят, неудача повторяется и называется;
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
from ui.qml import telegram_notifier
from ui.qml.controller.remote_monitor_mixin import AppControllerRemoteMonitorMixin
from ui.qml.remote_file_sync import FileSyncConfig, RemoteFileSync
from ui.qml.remote_status_server import RemoteStatusServer
from ui.qml.telegram_notifier import TelegramNotifier


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
    assert instance.start(0) == ""
    yield instance
    instance.stop()


def _get(server, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{path}", timeout=5) as answer:
        return answer.status, answer.read()


def test_page_and_status_are_served(server):
    status, body = _get(server, "/")
    assert status == 200 and "страница" in body.decode("utf-8")

    status, body = _get(server, "/status.json")
    payload = json.loads(body.decode("utf-8"))
    assert payload["run"]["points"] == 7
    assert payload["files"][0]["name"] == "chamber_1.csv"


def test_journal_can_be_downloaded(server):
    status, body = _get(server, "/" + json.loads(_get(server, "/status.json")[1])["files"][0]["url"])
    assert status == 200
    assert body.decode("utf-8").startswith("Время")


def test_files_outside_allowed_folders_are_refused(server):
    allowed = quote("прогон")
    for path in (f"/file?folder={allowed}&name=../secret.txt", f"/file?folder={quote('чужая')}&name=secret.txt",
                 f"/file?folder={allowed}&name=..%5Csecret.txt", f"/file?folder={allowed}&name=..%2Fsecret.txt"):
        with pytest.raises(urllib.error.HTTPError) as error:
            _get(server, path)
        assert error.value.code == 404


def test_key_protects_the_page(server):
    server.set_key("abc123")
    with pytest.raises(urllib.error.HTTPError) as error:
        _get(server, "/status.json")
    assert error.value.code == 403
    status, _body = _get(server, "/status.json?key=abc123")
    assert status == 200


def test_page_file_ships_with_the_program():
    """Страница лежит рядом с программой и попадает в сборку вместе с QML."""
    page = Path(__file__).resolve().parents[1] / "ui" / "qml" / "remote_status_page.html"
    text = page.read_text(encoding="utf-8")
    assert "status.json" in text
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


# ------------------------------------------------------------------ Telegram

def test_message_is_sent_and_failure_is_named(monkeypatch):
    sent = []
    results = []
    notifier = TelegramNotifier(lambda text, ok: results.append((text, ok)))
    monkeypatch.setattr(telegram_notifier, "RETRY_PAUSE_S", 0.0)
    try:
        notifier.configure("TOKEN", "42")
        notifier._post_json = lambda method, data, token=None: sent.append((method, data)) or {"ok": True}
        notifier.send_text("плата устоялась")
        assert _wait(lambda: results)
        assert sent[0] == ("sendMessage", {"chat_id": "42", "text": "плата устоялась",
                                           "disable_web_page_preview": True})
        assert results[-1][1] is True

        def broken(*_args, **_kwargs):
            raise RuntimeError("нет сети")
        notifier._post_json = broken
        results.clear()
        notifier.send_text("ещё")
        assert _wait(lambda: results)
        assert results[-1][1] is False
        assert "нет сети" in results[-1][0] and "3 попыток" in results[-1][0]
    finally:
        notifier.close()


def test_nothing_is_sent_without_chat():
    notifier = TelegramNotifier()
    try:
        notifier.configure("TOKEN", "")
        notifier.send_text("x")
        assert notifier._queue.empty()
    finally:
        notifier.close()


def test_chat_is_found_by_the_last_message():
    notifier = TelegramNotifier()
    found = []
    try:
        notifier._post_json = lambda method, data, token=None: {"ok": True, "result": [
            {"message": {"chat": {"id": 111, "first_name": "Старый"}}},
            {"message": {"chat": {"id": 222, "first_name": "Оператор", "last_name": "Камеры"}}},
        ]}
        notifier._find_chat_worker("TOKEN", lambda chat, note: found.append((chat, note)))
        assert found == [("222", "найден чат «Оператор Камеры»")]

        found.clear()
        notifier._post_json = lambda method, data, token=None: {"ok": True, "result": []}
        notifier._find_chat_worker("TOKEN", lambda chat, note: found.append((chat, note)))
        assert found[0][0] == "" and "напишите" in found[0][1]
    finally:
        notifier.close()


# ------------------------------------------------------------------ события и устойчивость

class _FakeNotifier:
    def __init__(self):
        self.texts = []
        self.documents = []

    def send_text(self, text):
        self.texts.append(text)

    def send_document(self, path, caption=""):
        self.documents.append((path, caption))

    def configure(self, *_args):
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
        self._remote_telegram = _FakeNotifier()
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


def test_points_can_be_kept_out_of_the_chat(tmp_path: Path):
    stub = _RemoteStub(tmp_path)
    stub._remote_settings["telegram_points"] = False
    point = dict(_full_run_points()[0])
    stub._chamber_points = [point]
    stub._remote_note_point(point)
    assert stub._remote_telegram.texts == []
    assert "записана" in stub._remote_events[0]["text"]


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
