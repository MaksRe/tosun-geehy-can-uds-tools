"""Проверки управления камерой и прогоном: права, действия, правка сценария на ходу, журнал.

Управлять камерой можно из окна, с сайта и из Telegram, и делают это разные
люди. Тесты закрепляют:
- без права (наблюдатель) ничего не выполняется, отказ тоже в журнале;
- экстренная остановка останавливает прогон и переводит камеру в «Стоп»;
- ручной режим или уставка во время прогона ставят прогон на паузу;
- переход к следующему шагу и к шагу по номеру;
- правка сценария на ходу: пройденные шаги не меняются, текущий нельзя убрать,
  новая температура текущего шага - шаг заново с новой уставкой; режим
  испытания не меняется во время прогона;
- каждое действие пишется в журнал с именем, откуда пришло и «было → стало»;
- права раздаёт админ; назначить админа можно только в окне программы;
- сайт: действие без входа - отказ, с подписью Telegram или ссылкой входа -
  выполняется от имени человека; бот: /estop с подтверждением, /login.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from tests.test_climate_scenario import _ScnStub
from tests.test_climate_supervisor import _feed
from ui.qml import climate_scenario as cs
from ui.qml.control_log import ControlLog
from ui.qml.controller.climate_control_mixin import AppControllerClimateControlMixin, GUI_CHANNEL
from ui.qml.controller.remote_monitor_mixin import MiniAppAccess
from ui.qml.remote_status_server import RemoteStatusServer
from ui.qml.telegram_bot import TelegramBot, TelegramUsers, sign_init_data

TOKEN = "123:ABC"


class _Bot:
    """Бот без сети для уведомлений о правах."""

    def __init__(self):
        self.sent = []

    def send_to(self, chat_id, text, markup=None):
        self.sent.append((str(chat_id), text))


class _ControlStub(AppControllerClimateControlMixin, _ScnStub):
    """Камера, прогон, сценарий и управление без Qt."""

    def __init__(self, root: Path):
        _ScnStub.__init__(self, root)
        self._project_root_directory = root
        self._control_log = ControlLog(root / "logs" / "control")
        self._control_lock = threading.Lock()
        self._control_pending = []
        self._control_thread = threading.current_thread()
        self._remote_users = TelegramUsers(None)
        self._remote_telegram = _Bot()
        self._remote_users.upsert("1", name="Анна", username="anna", role="admin")
        self._remote_users.upsert("2", name="Борис", username="boris", role="operator")
        self._remote_users.upsert("3", name="Вера", role="viewer")


def _started(tmp_path: Path, espec: bool = False) -> _ControlStub:
    stub = _ControlStub(tmp_path)
    stub._climate_scenario_set(cs.board_cycle_scenario(), dirty=False)
    _feed(stub, time.monotonic())
    stub._chamber_label = "0/0"
    assert stub._climate_run_start(), stub._climate_run_status
    if espec:
        # Команды ESPEC: модель камеры та же, меняется только набор команд.
        stub._climate_settings["driver"] = "espec"
    return stub


def _log_rows(stub) -> list[list[str]]:
    text = Path(stub._control_log.current_path).read_text(encoding="utf-8-sig")
    return list(csv.reader(io.StringIO(text), delimiter=";"))[1:]


def _as(stub, chat_id, channel="Telegram"):
    return stub._control_actor(chat_id, channel)


# ------------------------------------------------------------------ права и журнал

def test_viewer_cannot_control_and_the_refusal_is_logged(tmp_path: Path):
    stub = _started(tmp_path)
    ok, text = stub._control_submit(_as(stub, "3"), "estop", {})
    assert not ok and "нет права" in text
    assert stub._climate_run_stage, "прогон не должен остановиться"
    row = _log_rows(stub)[-1]
    assert row[1] == "Вера" and row[2] == "Telegram" and row[5].startswith("не выполнено")


def test_emergency_stop_stops_run_and_chamber(tmp_path: Path):
    stub = _started(tmp_path, espec=True)
    ok, text = stub._control_submit(_as(stub, "2", "сайт"), "estop", {})
    assert ok and not stub._climate_run_stage
    assert ("raw", "MODE, STANDBY") in stub._climate_link.commands
    row = _log_rows(stub)[-1]
    assert row[1] == "Борис (@boris)" and row[2] == "сайт" and row[3] == "экстренная остановка камеры"
    assert any(level == "bad" and "Борис" in message and "экстренная остановка" in message
               for level, message in stub.events)


def test_manual_mode_and_setpoint_pause_the_run(tmp_path: Path):
    stub = _started(tmp_path, espec=True)
    ok, text = stub._control_submit(_as(stub, "2"), "mode", {"mode": "off"})
    assert ok and stub._climate_run_paused and "паузу" in text
    assert ("raw", "MODE, OFF") in stub._climate_link.commands

    stub._climate_run_pause(False)
    ok, _text = stub._control_submit(_as(stub, "2"), "setpoint", {"value": "30,5"})
    assert ok and stub._climate_run_paused
    ok, text = stub._control_submit(_as(stub, "2"), "setpoint", {"value": "500"})
    assert not ok and "пределов" in text


def test_steps_can_be_skipped_and_chosen(tmp_path: Path):
    stub = _started(tmp_path)
    ok, _text = stub._control_submit(_as(stub, "2"), "step_next", {})
    assert ok and stub._climate_run_index == 1
    assert stub._climate_link.commands[-1] == ("setpoint", -40.0)
    ok, _text = stub._control_submit(_as(stub, "1"), "step_goto", {"index": 5})
    assert ok and stub._climate_run_index == 5
    assert "шаг 2 (-40 °C) → шаг 6 (+70 °C)" in _log_rows(stub)[-1][4]
    ok, text = stub._control_submit(_as(stub, "1"), "step_goto", {"index": 9})
    assert not ok


def test_scenario_changes_during_run(tmp_path: Path):
    stub = _started(tmp_path)
    stub._control_submit(_as(stub, "2"), "step_goto", {"index": 2})
    steps = [dict(step) for step in stub._climate_run_steps]

    # Пройденные шаги не меняются, будущий - меняется, новый - добавляется.
    edited = [dict(step) for step in steps]
    edited[0]["temp"] = 30.0
    edited[4]["hold_min"] = 20.0
    edited.append(cs.new_step(60.0))
    ok, text = stub._control_submit(_as(stub, "2"), "scenario_steps", {"steps": edited})
    assert ok, text
    assert stub._climate_run_steps[0]["temp"] == 25.0
    assert stub._climate_run_steps[4]["hold_min"] == 20.0 and stub._climate_run_nodes[-1] == 60.0
    assert stub._climate_scenario["steps"][-1]["temp"] == 60.0
    details = _log_rows(stub)[-1][4]
    assert "шаг 5: выдержка 0 мин → 20 мин" in details and "добавлен шаг 8: +60 °C" in details

    # Новая температура текущего шага - шаг заново с новой уставкой.
    edited = [dict(step) for step in stub._climate_run_steps]
    edited[2]["temp"] = -15.0
    ok, text = stub._control_submit(_as(stub, "2"), "scenario_steps", {"steps": edited})
    assert ok and "начат заново" in text and stub._climate_link.commands[-1] == ("setpoint", -15.0)

    # Текущий шаг убрать нельзя; режим испытания во время прогона не меняется.
    ok, text = stub._control_submit(_as(stub, "2"), "scenario_steps", {"steps": edited[:2]})
    assert not ok and "убрать его нельзя" in text
    scenario = dict(stub._climate_scenario, board_only=False, labels=["68/22"])
    ok, _text = stub._control_submit(_as(stub, "2"), "scenario", {"scenario": json.dumps(scenario)})
    assert stub._climate_scenario["board_only"] is True


def test_gui_actions_are_logged_with_operator_name(tmp_path: Path):
    stub = _started(tmp_path)
    ok, _text = stub._control_gui("run_pause")
    assert ok and stub._climate_run_paused
    row = _log_rows(stub)[-1]
    assert row[1].startswith("оператор у камеры") and row[2] == GUI_CHANNEL and row[3] == "пауза автопрогона"


def test_scenario_edit_outside_run_is_logged_quietly(tmp_path: Path):
    stub = _ControlStub(tmp_path)
    stub._climate_scenario_set(cs.board_cycle_scenario(), dirty=False)
    changed = dict(stub._climate_scenario, finish_stop=True)
    assert stub._control_gui_scenario_update(json.dumps(changed))
    assert "остановить камеру в конце: нет → да" in _log_rows(stub)[-1][4]


def test_only_admin_grants_rights(tmp_path: Path):
    stub = _ControlStub(tmp_path)
    ok, text = stub._control_submit(_as(stub, "2"), "role", {"id": "3", "role": "operator"})
    assert not ok and "только админ" in text
    ok, _text = stub._control_submit(_as(stub, "1"), "role", {"id": "3", "role": "operator"})
    assert ok and stub._remote_users.get("3")["role"] == "operator"
    assert any(chat == "3" and "право управлять" in message for chat, message in stub._remote_telegram.sent)
    ok, text = stub._control_submit(_as(stub, "1"), "role", {"id": "3", "role": "admin"})
    assert not ok and "окне программы" in text
    ok, _text = stub._control_gui("role", {"id": "3", "role": "admin"})
    assert ok and stub._remote_users.get("3")["role"] == "admin"


def test_log_survives_a_restart(tmp_path: Path):
    log = ControlLog(tmp_path)
    log.add("Анна", "Telegram", "уставка камеры", "+30 °C", True, "задано")
    again = ControlLog(tmp_path)
    assert again.recent(1)[0]["who"] == "Анна" and again.recent(1)[0]["ok"] is True


def test_actions_from_other_threads_wait_for_the_window(tmp_path: Path):
    """Сайт и бот действуют из своих потоков: действие выполняется в потоке окна."""
    stub = _started(tmp_path)
    result = {}
    worker = threading.Thread(target=lambda: result.update(r=stub._control_submit(_as(stub, "2"), "run_pause", {})))
    worker.start()
    deadline = time.monotonic() + 5
    while worker.is_alive() and time.monotonic() < deadline:
        stub._control_take_pending()
        time.sleep(0.01)
    assert result["r"][0] and stub._climate_run_paused


# ------------------------------------------------------------------ сайт и бот

def _post(server, path, body, headers=None):
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", data=json.dumps(body).encode("utf-8"),
                                     headers=dict({"Content-Type": "application/json"}, **(headers or {})))
    with urllib.request.urlopen(request, timeout=5) as answer:
        return json.loads(answer.read().decode("utf-8"))


def _init(chat_id):
    return sign_init_data({"auth_date": str(int(time.time())), "user": json.dumps({"id": chat_id})}, TOKEN)


@pytest.fixture
def site(tmp_path: Path):
    users = TelegramUsers(tmp_path / "users.json")
    users.upsert("2", name="Борис", role="operator")
    users.upsert("3", name="Вера", role="viewer")
    bot = TelegramBot(users)
    bot.close()
    bot.configure(TOKEN)
    bot.set_app_url("https://camera.ngrok-free.dev")
    calls = []

    def control(chat_id, channel, action, params):
        user = users.get(chat_id) or {}
        if user.get("role") not in ("operator", "admin"):
            return False, "нет права управлять"
        calls.append((chat_id, channel, action, params))
        return True, "выполнено"

    server = RemoteStatusServer("<html></html>")
    server.set_access(MiniAppAccess(bot, server._resolve_file, control))
    assert server.start(0) == ""
    yield server, bot, calls
    server.stop()


def test_site_requires_a_known_person_for_actions(site):
    server, bot, calls = site
    with pytest.raises(urllib.error.HTTPError) as error:
        _post(server, "/api/control", {"action": "estop"})
    assert error.value.code == 403

    assert _post(server, "/api/control", {"action": "estop"}, {"X-Telegram-Init-Data": _init(3)})["ok"] is False
    answer = _post(server, "/api/control", {"action": "setpoint", "value": "30"}, {"X-Telegram-Init-Data": _init(2)})
    assert answer["ok"] and calls[-1] == ("2", "Telegram", "setpoint", {"value": "30"})

    # Обычный браузер: ссылка входа из бота.
    link = bot.login_link("2")
    token = link.split("#login=", 1)[1]
    assert _post(server, "/api/control", {"action": "run_pause"}, {"X-Web-Token": token})["ok"]
    assert calls[-1][1] == "сайт"
    # У наблюдателя ссылки входа нет; новая ссылка гасит старую.
    assert bot.login_link("3") == ""
    bot.login_link("2", renew=True)
    with pytest.raises(urllib.error.HTTPError):
        _post(server, "/api/control", {"action": "run_pause"}, {"X-Web-Token": token})


def test_bot_estop_asks_for_confirmation(tmp_path: Path):
    users = TelegramUsers(None)
    users.upsert("2", name="Борис", role="operator")
    users.upsert("3", name="Вера")
    bot = TelegramBot(users)
    bot.close()
    bot.configure(TOKEN)
    done = []
    bot.set_control_handler(lambda chat_id, action, params: done.append((chat_id, action)) or (True, "остановлено"))

    def drain():
        items = []
        while not bot._queue.empty():
            item = bot._queue.get_nowait()
            if item is not None and item[0] == "send":
                items.append(item[1])
        return items

    bot.handle_update({"message": {"chat": {"id": 3}, "from": {"first_name": "Вера"}, "text": "/estop"}})
    assert "Управлять камерой могут только" in drain()[0]["text"] and done == []

    bot.handle_update({"message": {"chat": {"id": 2}, "from": {"first_name": "Борис"}, "text": "/estop"}})
    confirm = drain()[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    assert confirm == "ctl!estop" and done == []
    bot.handle_update({"callback_query": {"id": "q", "data": confirm, "message": {"chat": {"id": 2}, "message_id": 5}}})
    assert done == [("2", "estop")]
