"""Проверки бота как запасной панели и туннеля Tailscale.

Если сайт и мини-приложение недоступны (кончился лимит туннеля), бот остаётся:
он сам ходит в Telegram. Тесты закрепляют:
- отчёты таблицами в <pre> (колонки ровные) и HTML-разметка сообщений;
- команды управления текстом превращаются в те же действия, что у сайта;
- опасные действия - с подтверждением кнопкой, параметры ждут в отложенном
  действии чата; наблюдателю управлять нельзя;
- Tailscale Funnel: просьба разрешить Funnel по ссылке, адрес из «status»;
- сервер сжимает ответы и отдаёт историю графиков только по «full=1».
"""

from __future__ import annotations

import gzip
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml import public_tunnel
from ui.qml import telegram_reports as reports
from ui.qml.remote_status_server import RemoteStatusServer
from ui.qml.telegram_bot import TelegramBot, TelegramUsers

TOKEN = "123:ABC"

SNAPSHOT = {
    "time": "14.10.2026 11:00:00",
    "live": {"boardTemp": {"now": "-19,7 °C", "avg": "-19,8 °C"}, "fuelTemp": {"now": "-22,1 °C"},
             "main": {"avg": "4532"}, "media": {"avg": "4431"}},
    "stability": {"text": "Плата устоялась", "ok": True},
    "run": {"points": 2, "rows": [{"time": "23:08:26", "boardTemp": "-19.7", "node": "-20 °C", "main": 4532, "media": 4430}]},
    "events": [{"time": "23:08:25", "level": "ok", "text": "плата дошла до шага"}],
    "climate": {
        "connected": True, "ok": True, "chamber": {"name": "ESPEC MC-811P"}, "actualText": "-28,5 °C",
        "setpointText": "-28,5 °C", "runningText": "работает", "alarmText": "нет", "espec": {"modeText": "постоянный режим"},
        "run": {"active": True, "stage": "плата устаивается", "status": "Узел 3 из 7", "auto": {"alerts": []}},
        "runIndex": 2, "scenarioName": "Цикл платы",
        "steps": [{"temp": 25.0, "hold_min": 0, "capture": True}, {"temp": -40.0, "hold_min": 0, "capture": True},
                  {"temp": -20.0, "hold_min": 0, "capture": True}],
        "control": {"modes": [{"key": "constant"}, {"key": "standby"}, {"key": "off"}],
                    "rules": [{"key": "board_max_shift_c", "title": "сдвигать уставку до", "unit": "°C", "value": 20.0}],
                    "scenarioFiles": [{"file": "cycle.json", "name": "Цикл платы"}], "log": [], "commands": [],
                    "answers": []},
        "history": {"t": list(range(500)), "actual": [1.5] * 500},
    },
    "history": {"t": list(range(500)), "board": [1.25] * 500},
}


def _bot(tmp_path: Path):
    users = TelegramUsers(tmp_path / "users.json")
    users.upsert("2", name="Борис", role="operator")
    users.upsert("3", name="Вера")
    bot = TelegramBot(users)
    bot.close()
    bot.configure(TOKEN)
    bot.set_snapshot(SNAPSHOT)
    calls = []
    bot.set_control_handler(lambda chat_id, action, params: calls.append((chat_id, action, params)) or (True, "выполнено"))
    return bot, calls


def _sent(bot):
    items = []
    while not bot._queue.empty():
        item = bot._queue.get_nowait()
        if item is not None and item[0] == "send":
            items.append(item[1])
    return items


def _say(bot, chat_id, text):
    bot.handle_update({"message": {"chat": {"id": chat_id}, "from": {"first_name": "x"}, "text": text}})


def test_reports_are_tables_in_pre():
    status = reports.status_report(SNAPSHOT)
    assert status.count("<pre>") == 1 and "ESPEC MC-811P" in status and "шаг 3/3" in status
    steps = reports.steps_report(SNAPSHOT)
    body = steps.split("<pre>")[1].split("</pre>")[0].splitlines()
    assert "ИДЁТ" in body[4] and "пройден" in body[2]
    # Колонки ровные: температура шага выровнена вправо - конец числа в одной позиции у всех строк.
    ends = {line.index(line.split()[1]) + len(line.split()[1]) for line in body[2:]}
    assert len(ends) == 1, body
    assert "board_max_shift_c = 20" in reports.rules_report(SNAPSHOT)
    assert "1. Цикл платы" in reports.scenarios_report(SNAPSHOT)


def test_view_commands_answer_with_html(tmp_path: Path):
    bot, _calls = _bot(tmp_path)
    _sent(bot)
    _say(bot, 3, "/steps")
    message = _sent(bot)[0]
    assert message["parse_mode"] == "HTML" and "<pre>" in message["text"]


def test_text_commands_become_control_actions(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    _sent(bot)
    _say(bot, 2, "/setpoint -55")
    _say(bot, 2, "/mode стоп")
    _say(bot, 2, "/step 2 -40 15")
    _say(bot, 2, "/rule board_max_shift_c 25")
    _say(bot, 2, "/limits -60 110")
    _say(bot, 2, "/cmd set_ref ref=9")
    _say(bot, 2, "/report")
    assert calls[0] == ("2", "setpoint", {"value": "-55"})
    assert calls[1] == ("2", "mode", {"mode": "standby"})
    assert calls[2][1] == "scenario_steps" and calls[2][2]["steps"][1] == {"temp": -40.0, "hold_min": 15.0, "capture": True}
    assert calls[3] == ("2", "scenario_rules", {"board_max_shift_c": "25"})
    assert calls[4] == ("2", "limits", {"min": "-60", "max": "110"})
    assert calls[-1] == ("2", "send_file", {"which": "report"})
    # /cmd - опасное: ждёт подтверждения, в обработчик ещё не ушло.
    assert not any(call[1] == "espec_command" for call in calls)


def test_dangerous_commands_wait_for_confirmation(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    _sent(bot)
    _say(bot, 2, "/goto 3")
    confirm = _sent(bot)[0]
    assert confirm["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "ctl!pending" and calls == []
    bot.handle_update({"callback_query": {"id": "q", "data": "ctl!pending", "message": {"chat": {"id": 2}, "message_id": 9}}})
    assert calls == [("2", "step_goto", {"index": 2})]
    # Повторное нажатие той же кнопки ничего не делает.
    bot.handle_update({"callback_query": {"id": "q", "data": "ctl!pending", "message": {"chat": {"id": 2}, "message_id": 9}}})
    assert len(calls) == 1


def test_viewer_cannot_control_by_text(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    _sent(bot)
    _say(bot, 3, "/setpoint -55")
    assert calls == [] and "только админ" in _sent(bot)[0]["text"]


def test_bad_arguments_get_an_example(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    _sent(bot)
    _say(bot, 2, "/goto три")
    _say(bot, 2, "/step 9 -40")
    texts = [item["text"] for item in _sent(bot)]
    assert calls == [] and "Пример: /goto 3" in texts[0] and "Шага 9 нет" in texts[1]


# ------------------------------------------------------------------ Tailscale

class _Done:
    def __init__(self, code, text):
        self.returncode = code
        self.stdout = text.encode("utf-8")
        self.stderr = b""


def test_tailscale_funnel_asks_to_enable_then_gives_the_address(monkeypatch, tmp_path: Path):
    answers = {"enabled": False}

    def run(command, **_kwargs):
        if command[1] == "funnel":
            if answers["enabled"]:
                return _Done(0, "Available on the internet")
            return _Done(1, "Funnel is not enabled on your tailnet.\nTo enable, visit:\n\n"
                            "         https://login.tailscale.com/f/funnel?node=abc\n")
        return _Done(0, json.dumps({"BackendState": "Running", "Self": {"DNSName": "lab-pc.tail1234.ts.net."}}))

    monkeypatch.setattr(public_tunnel.subprocess, "run", run)
    monkeypatch.setattr(public_tunnel.TailscaleFunnel, "CHECK_EVERY_S", 0.05)
    urls, statuses = [], []
    funnel = public_tunnel.TailscaleFunnel(urls.append, lambda text, ok: statuses.append((text, ok)), tmp_path / "ts.log")
    funnel.start(8765, "tailscale.exe")
    try:
        deadline = time.monotonic() + 5
        while not any("login.tailscale.com/f/funnel" in text for text, _ok in statuses) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not urls
        answers["enabled"] = True
        while not urls and time.monotonic() < deadline:
            time.sleep(0.02)
        assert urls == ["https://lab-pc.tail1234.ts.net/"]
    finally:
        funnel.stop()


# ------------------------------------------------------------------ сервер: трафик

def test_server_compresses_and_sends_history_only_on_full():
    server = RemoteStatusServer("<html></html>")
    server.set_snapshot(SNAPSHOT)
    assert server.start(0) == ""
    try:
        def get(path):
            request = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", headers={"Accept-Encoding": "gzip"})
            with urllib.request.urlopen(request, timeout=5) as answer:
                raw = answer.read()
                encoding = answer.headers.get("Content-Encoding")
            return json.loads(gzip.decompress(raw) if encoding == "gzip" else raw), encoding, len(raw)
        light, encoding, light_size = get("/api/state")
        full, _encoding, full_size = get("/api/state?full=1")
        assert "history" not in light and "history" not in light["climate"]
        assert full["history"]["board"][0] == 1.25 and full["climate"]["history"]["actual"]
        assert encoding == "gzip" and light_size < full_size
    finally:
        server.stop()
