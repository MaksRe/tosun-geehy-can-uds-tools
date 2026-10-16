"""Проверки бота кнопками: всё управление и отчёты без набора команд с «/».

Тесты закрепляют:
- /start присылает постоянную клавиатуру (у назначенных - с камерой, прогоном и
  экстренной остановкой, у наблюдателя - только отчёты) и меню кнопками;
- меню листается на месте (перерисовывается то же сообщение);
- опасное действие - через «Да», которое срабатывает один раз;
- значение (своя уставка, правило) бот просит прислать обычным сообщением;
  неверное - просит ещё раз;
- права проверяются при нажатии: человек без права управлять кнопкой не управляет;
- кнопки шагов и правил собирают те же действия, что и текстовые команды.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_bot_reports import SNAPSHOT, TOKEN
from ui.qml import telegram_menus as menus
from ui.qml.telegram_bot import TelegramBot, TelegramUsers

RULES = [{"key": "board_max_shift_c", "title": "сдвигать уставку при доводке до", "unit": "°C", "value": 20.0},
         {"key": "finish_stop", "title": "в конце остановить камеру", "unit": "", "value": False}]


def _snapshot():
    snapshot = {key: (dict(value) if isinstance(value, dict) else value) for key, value in SNAPSHOT.items()}
    climate = dict(snapshot["climate"])
    climate["control"] = dict(climate["control"], rules=RULES, espec=True, limits={"min": -60.0, "max": 110.0},
                              modes=[{"key": "constant", "title": "Пуск"}, {"key": "standby", "title": "Стоп"}],
                              commands=[{"key": "set_ref", "group": "Холодильник", "title": "Ступень холодильника",
                                         "hint": "", "danger": True,
                                         "params": [{"name": "ref", "label": "ступень", "default": "9"}]}])
    climate["setpointValue"] = -28.5
    climate["run"] = dict(climate["run"], paused=False)
    snapshot["climate"] = climate
    return snapshot


def _bot(tmp_path: Path):
    users = TelegramUsers(tmp_path / "users.json")
    users.upsert("2", name="Борис", role="operator")
    users.upsert("3", name="Вера")
    bot = TelegramBot(users)
    bot.close()
    bot.configure(TOKEN)
    bot.set_snapshot(_snapshot())
    bot.menu_refresh_s = 0
    calls = []
    bot.set_control_handler(lambda chat_id, action, params: calls.append((chat_id, action, params)) or (True, "выполнено"))
    return bot, calls


def _drain(bot):
    """Всё, что бот поставил в очередь: («send», сообщение) и («call», (метод, данные))."""
    items = []
    while not bot._queue.empty():
        item = bot._queue.get_nowait()
        if item is not None:
            items.append(item)
    return items


def _messages(items):
    return [payload for kind, payload in items if kind == "send"]


def _edits(items):
    return [data for kind, payload in items if kind == "call" for method, data in [payload]
            if method == "editMessageText"]


def _buttons(payload):
    return [button for row in (payload.get("reply_markup") or {}).get("inline_keyboard", []) for button in row]


def _press(bot, chat_id, payload, title, message_id=100):
    """Нажать кнопку, надпись которой начинается с title."""
    button = next(button for button in _buttons(payload) if button["text"].startswith(title))
    bot.handle_update({"callback_query": {"id": "q", "data": button["callback_data"],
                                          "message": {"chat": {"id": int(chat_id)}, "message_id": message_id}}})
    return _drain(bot)


def _say(bot, chat_id, text):
    bot.handle_update({"message": {"chat": {"id": int(chat_id)}, "from": {"first_name": "x"}, "text": text}})
    return _drain(bot)


def test_start_gives_keyboard_and_menu(tmp_path: Path):
    bot, _calls = _bot(tmp_path)
    _drain(bot)
    operator = _messages(_say(bot, 2, "/start"))
    keys = [button["text"] for row in operator[0]["reply_markup"]["keyboard"] for button in row]
    assert menus.KB_ESTOP in keys and menus.KB_CAMERA in keys and menus.KB_RUN in keys
    titles = [button["text"] for button in _buttons(operator[1])]
    assert "🌡 Камера" in titles and "⚖ Правила" in titles and "⛔ Экстренная остановка" in titles
    viewer = _messages(_say(bot, 3, "/start"))
    keys = [button["text"] for row in viewer[0]["reply_markup"]["keyboard"] for button in row]
    assert menus.KB_ESTOP not in keys and menus.KB_CAMERA not in keys and menus.KB_STATUS in keys
    assert "🌡 Камера" not in [button["text"] for button in _buttons(viewer[1])]


def test_menu_is_turned_in_place(tmp_path: Path):
    bot, _calls = _bot(tmp_path)
    menu = _messages(_say(bot, 2, "/menu"))[0]
    edits = _edits(_press(bot, "2", menu, "🌡 Камера", message_id=55))
    assert edits and edits[0]["message_id"] == 55 and "<b>Камера</b>" in edits[0]["text"]
    titles = [button["text"] for button in _buttons(edits[0])]
    assert "Пуск" in titles and "-40" in titles and "+1" in titles and "✏️ Своя уставка" in titles


def test_confirmed_action_runs_once_and_refreshes_menu(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    camera = _edits(_press(bot, "2", _messages(_say(bot, 2, "/menu"))[0], "🌡 Камера", message_id=55))[0]
    confirm = _messages(_press(bot, "2", camera, "-40", message_id=55))
    assert calls == [] and "Задать камере уставку -40 °C?" in confirm[0]["text"] and "паузу" in confirm[0]["text"]
    after = _press(bot, "2", confirm[0], "✅ Да", message_id=77)
    assert calls == [("2", "setpoint", {"value": "-40"})]
    edits = _edits(after)
    assert edits[0]["message_id"] == 77 and "выполнено" in edits[0]["text"]
    assert any(edit["message_id"] == 55 and "<b>Камера</b>" in edit["text"] for edit in edits)
    # Повторное «Да» ничего не делает: кнопка уже израсходована.
    _press(bot, "2", confirm[0], "✅ Да", message_id=77)
    assert len(calls) == 1


def test_value_is_asked_without_slash(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    camera = _edits(_press(bot, "2", _messages(_say(bot, 2, "/menu"))[0], "🌡 Камера"))[0]
    prompt = _messages(_press(bot, "2", camera, "✏️ Своя уставка"))[0]
    assert prompt["reply_markup"]["force_reply"] is True
    retry = _messages(_say(bot, 2, "минус сорок"))[0]
    assert "Пример: /setpoint" in retry["text"] and calls == []
    _say(bot, 2, "-55,5")
    assert calls == [("2", "setpoint", {"value": "-55,5"})]
    # Ожидание ввода закончилось: следующее число - не уставка.
    _say(bot, 2, "-60")
    assert len(calls) == 1


def test_keyboard_buttons_open_screens(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    run = _messages(_say(bot, 2, menus.KB_RUN))
    assert "<b>Прогон</b>" in run[0]["text"] and "⏸ Пауза" in [button["text"] for button in _buttons(run[0])]
    status = _messages(_say(bot, 3, menus.KB_STATUS))
    assert "<pre>" in status[0]["text"] and "⟳ Обновить" in [button["text"] for button in _buttons(status[0])]
    # Наблюдателю «Камера» не открывается: вместо неё главное меню без управления.
    viewer = _messages(_say(bot, 3, menus.KB_CAMERA))
    assert "<b>Меню</b>" in viewer[0]["text"] and "🌡 Камера" not in [button["text"] for button in _buttons(viewer[0])]
    estop = _messages(_say(bot, 2, menus.KB_ESTOP))
    assert "Экстренно остановить" in estop[0]["text"] and calls == []


def test_rights_are_checked_on_press(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    run = _messages(_say(bot, 2, menus.KB_RUN))[0]
    bot.users.upsert("2", role="viewer")
    answers = [data for kind, payload in _press(bot, "2", run, "⏸ Пауза") if kind == "call"
               for method, data in [payload] if method == "answerCallbackQuery"]
    assert calls == [] and answers[0]["text"] == "Нет права управлять камерой"


def test_rule_and_step_buttons_build_scenario_actions(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    menu = _messages(_say(bot, 2, "/menu"))[0]
    rules = _edits(_press(bot, "2", menu, "⚖ Правила"))[0]
    _press(bot, "2", rules, "✗ В конце остановить")
    assert calls[-1] == ("2", "scenario_rules", {"finish_stop": "да"})
    _press(bot, "2", rules, "Сдвиг уставки до: 20 °C")
    _say(bot, 2, "25")
    assert calls[-1] == ("2", "scenario_rules", {"board_max_shift_c": "25"})
    steps = _edits(_press(bot, "2", menu, "🧾 Сценарий"))[0]
    steps = _edits(_press(bot, "2", steps, "✏️ Шаги"))[0]
    step = _edits(_press(bot, "2", steps, "✏️ 2 · -40 °C"))[0]
    assert "<b>Шаг 2</b> · пройден" in step["text"]
    _press(bot, "2", step, "15 мин")
    action, params = calls[-1][1], calls[-1][2]
    assert action == "scenario_steps" and params["steps"][1]["hold_min"] == 15.0 and params["steps"][0]["temp"] == 25.0
    _press(bot, "2", step, "🌡 Температура")
    _say(bot, 2, "-45 10")
    assert calls[-1][2]["steps"][1] == {"temp": -45.0, "hold_min": 10.0, "capture": True}


def test_espec_command_with_defaults_and_own_params(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    menu = _messages(_say(bot, 2, "/menu"))[0]
    espec = _edits(_press(bot, "2", menu, "🛠 Команды ESPEC"))[0]
    group = _edits(_press(bot, "2", espec, "Холодильник"))[0]
    command = _edits(_press(bot, "2", group, "⚠ Ступень холодильника"))[0]
    confirm = _messages(_press(bot, "2", command, "▶ Отправить"))[0]
    _press(bot, "2", confirm, "✅ Да")
    assert calls[-1] == ("2", "espec_command", {"key": "set_ref", "values": {"ref": "9"}})
    _press(bot, "2", command, "✏️ Свои параметры")
    confirm = _messages(_say(bot, 2, "ref=5"))[0]
    _press(bot, "2", confirm, "Да")
    assert calls[-1] == ("2", "espec_command", {"key": "set_ref", "values": {"ref": "5"}})


def test_stale_button_gives_fresh_menu(tmp_path: Path):
    bot, _calls = _bot(tmp_path)
    _drain(bot)
    bot.handle_update({"callback_query": {"id": "q", "data": "b:ffff", "message": {"chat": {"id": 2}, "message_id": 5}}})
    items = _drain(bot)
    assert "<b>Меню</b>" in _messages(items)[0]["text"]
    assert any(kind == "call" and payload[1].get("text") == "Кнопка устарела - вот свежее меню" for kind, payload in items)


def test_add_and_delete_step_by_text(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    _say(bot, 2, "/addstep -30 5")
    assert calls[-1][2]["steps"][-1] == {"temp": -30.0, "hold_min": 5.0, "capture": True}
    confirm = _messages(_say(bot, 2, "/delstep 2"))[0]
    assert "Удалить шаг 2" in confirm["text"]
    bot.handle_update({"callback_query": {"id": "q", "data": "ctl!pending", "message": {"chat": {"id": 2}, "message_id": 9}}})
    assert [step["temp"] for step in calls[-1][2]["steps"]] == [25.0, -20.0]


def test_admin_only_broadcast_reaches_only_admins(tmp_path: Path):
    """Режим «только админу»: уведомления и файлы - только админам, ответы на команды - всем."""
    bot, calls = _bot(tmp_path)
    bot.users.upsert("1", name="Анна", role="admin", level="all", keyboard="1:control")
    _drain(bot)
    bot.notify("плата дошла до шага", "warn")
    assert sorted(item["chat_id"] for item in _messages(_drain(bot))) == ["1", "2", "3"]
    bot.set_admin_only(True)
    bot.notify("плата дошла до шага", "warn")
    bot.send_document(tmp_path / "report.txt", "отчёт")
    items = _drain(bot)
    assert [item["chat_id"] for item in _messages(items)] == ["1"]
    assert [payload[0] for kind, payload in items if kind == "document"] == ["1"]
    # Наблюдатель по-прежнему получает ответы на свои команды.
    assert _messages(_say(bot, 3, "/status"))[0]["chat_id"] == "3"


def test_quiet_command_and_admin_menu_button(tmp_path: Path):
    bot, calls = _bot(tmp_path)
    bot.users.upsert("1", name="Анна", role="admin", keyboard="1:control")
    _say(bot, 1, "/quiet on")
    assert calls[-1] == ("1", "notify_scope", {"admin_only": True})
    assert "Сейчас: всем подписчикам" in _messages(_say(bot, 1, "/quiet"))[0]["text"]
    menu = _messages(_say(bot, 1, "/menu"))[0]
    _press(bot, "1", menu, "🔔 Рассылка: всем")
    assert calls[-1] == ("1", "notify_scope", {"admin_only": True})
    bot.set_admin_only(True)
    menu = _messages(_say(bot, 1, "/menu"))[0]
    assert "только админу" in menu["text"]
    _press(bot, "1", menu, "🔕 Рассылка: только админу")
    assert calls[-1] == ("1", "notify_scope", {"admin_only": False})
    # У оператора такой кнопки нет.
    titles = [button["text"] for button in _buttons(_messages(_say(bot, 2, "/menu"))[0])]
    assert not any("Рассылка" in title for title in titles)


def test_check_message_respects_admin_only(tmp_path: Path):
    bot, _calls = _bot(tmp_path)
    bot.users.upsert("1", name="Анна", role="admin")
    _drain(bot)
    assert bot.test() == 3
    _drain(bot)
    bot.set_admin_only(True)
    assert bot.test() == 1 and [item["chat_id"] for item in _messages(_drain(bot))] == ["1"]
