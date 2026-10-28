"""Проверки прогона нескольких плат в камере одновременно.

Тесты закрепляют:
- у каждой платы свой набор полей: средние, журнал (свой файл), таблицы, профиль;
- опрос идёт по кругу по всем платам, ответ попадает в средние той платы, от
  которой пришёл (по адресу на шине);
- прогон на имитаторе с тремя платами: доводка по средней температуре плат,
  точки шага у каждой платы, у каждой - свой журнал;
- «тишина» на шине: CommunicationControl всем платам на время прогона и обратно;
- профили пишутся по очереди, по одной плате; перед каждой платой калибровка
  прежней платы закрывается, доступ открывается для этой; запись и сверка идут
  на адрес платы камеры, а не узла раздела «Параметры»;
- каждая плата получает все величины опроса при любом числе плат;
- после перезапуска программы журнал каждой платы возвращается в её же поля;
- лента плат: на плитке - узлы с точками и профиль (из этого сеанса или
  прочитанный из самой платы); показанную плату нельзя переключить посреди
  пробной калибровки, причина видна в ленте; проверка перед прогоном
  предупреждает, если плат несколько, а режим выключен;
- полный прогон трёх плат по семи узлам: у каждой платы точки во всех узлах,
  полные таблицы и запись профиля в очереди после прогона;
- точка вручную снимается у всех плат, кнопка записи профиля ставит в очередь
  все платы с полными таблицами, новый журнал - у всех плат, точки всех плат
  одним списком для сайта;
- состояние прогона без журналов каждой платы (его сохранила прежняя версия):
  программа это замечает и при продолжении находит журнал каждой платы по
  файлам на диске - каждый в свою плату;
- сайт: подробности каждой платы (узлы, журнал, таблицы), команда «показать
  плату в программе», запись точки с сайта - у всех плат;
- пока режим выключен (показанной платы нет), просмотр таблицы плат не отдаёт
  поля последней платы первой: после включения у каждой платы своё окно среднего.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_fit
from tests.test_climate_scenario import _ScnStub
from ui.qml import climate_scenario as cs
from ui.qml.controller.multiboard_mixin import AppControllerMultiBoardMixin

BOARDS = ((0x80, "П1", 0.0, 5000), (0x81, "П2", 0.6, 5100), (0x82, "П3", -0.6, 5200))


class _MbStub(AppControllerMultiBoardMixin, _ScnStub):
    """Камера, прогон, сценарий и несколько плат без Qt и шины."""

    def __init__(self, root: Path):
        _ScnStub.__init__(self, root)
        self._project_root_directory = root
        self._chamber_test_mode = False
        self._init_multiboard_state()


def _stub(tmp_path: Path, temps=(25.0, -40.0)) -> _MbStub:
    stub = _MbStub(tmp_path)
    for sa, name, _offset, _main in BOARDS:
        assert stub._mb_add_board(f"0x{sa:02X}", name)[0]
    assert stub._mb_set_enabled(True)[0]
    assert stub._climate_scenario_new("board_cycle")
    stub._climate_scenario["steps"] = [cs.new_step(temp) for temp in temps]
    stub._climate_scenario["auto_write"] = False
    stub._chamber_label = "0/0"
    _feed(stub, time.monotonic())
    return stub


def _feed(stub, now):
    """Камера и все платы: у каждой своя температура (сдвиг) и свои показания контуров."""
    reading = stub.sim.read()
    stub._climate_reading = reading
    stub._climate_last_ok_s = now
    product = reading.product_c if reading.product_c is not None else 25.0
    for sa, _name, offset, main in BOARDS:
        with stub._mb_context(sa):
            for shift in (2.0, 1.0, 0.0):
                stamp = now - shift
                stub._chamber_live_note("board_temp", int(round((product + offset) * 10)), stamp)
                stub._chamber_live_note("fuel_temp", int(round((product + offset) * 10)), stamp)
                stub._chamber_live_note("main", main, stamp)
                stub._chamber_live_note("media", 4500, stamp)


def _walk(stub, limit=40000, step_s=30.0):
    start = time.monotonic()
    for step in range(limit):
        now = start + step * step_s
        stub.clock[0] = step * step_s
        _feed(stub, now)
        stub._climate_note_board(now)
        if stub._climate_run_stage:
            stub._climate_run_tick(now)
        stub._climate_auto_tick(now)
        if not stub._climate_run_stage and not stub._climate_auto_finishing:
            return now
    raise AssertionError("прогон не закончился")


def test_each_board_keeps_its_own_journal_through_a_run(tmp_path: Path):
    stub = _stub(tmp_path)
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    files = set()
    for sa, name, offset, main in BOARDS:
        with stub._mb_context(sa):
            nodes = sorted(chamber_fit.nearest_node(point["board_temp_x10"]) for point in stub._chamber_points)
            assert nodes == [-400, 250], (name, stub._chamber_points)
            assert all(point["main"] == main for point in stub._chamber_points), name
            assert f"_0x{sa:02X}" in Path(stub._chamber_file_path).name and Path(stub._chamber_file_path).exists()
            files.add(stub._chamber_file_path)
    assert len(files) == 3
    view = stub._mb_view()
    assert [row["points"] for row in view["boards"]] == [2, 2, 2]
    assert [row["active"] for row in view["boards"]] == [True, False, False], "показана одна плата"


def test_doctoring_follows_the_mean_of_boards(tmp_path: Path):
    """Платы на +0,6 и -0,6 от средней: доводка ведёт среднюю к узлу - все три в допуске."""
    stub = _stub(tmp_path, temps=(25.0, -40.0))
    stub.sim.self_heating_c = 6.0
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    for sa, name, _offset, _main in BOARDS:
        with stub._mb_context(sa):
            boards = [point["board_temp_x10"] / 10 for point in stub._chamber_points]
            assert all(abs(value - target) <= 2.0 for value, target in zip(boards, (25.0, -40.0))), (name, boards)


def test_start_needs_every_board(tmp_path: Path):
    stub = _stub(tmp_path)
    with stub._mb_context(0x81):
        stub._chamber_live_reset()
    blockers = stub._climate_auto_blockers()
    assert any("«П2» (0x81)" in text for text in blockers), blockers


def test_polling_goes_round_all_boards_and_answers_go_to_their_board(tmp_path: Path):
    stub = _stub(tmp_path)
    sent = []

    class _Read:
        def read_data_by_identifier(self, identifier, var):
            sent.append((identifier & 0xFF00) >> 8)

    stub._chamber_live_read = _Read()
    stub._build_calibration_tx_identifier = lambda: 0x18DA00F1 | (stub._calibration_target_node_sa << 8)
    stub._chamber_live_pending = None
    for _ in range(6):
        stub._chamber_live_pending = None
        stub._mb_live_tick(time.monotonic())
    assert sent[:3] == [0x80, 0x81, 0x82] and sent[3:6] == [0x80, 0x81, 0x82]

    # Ответ платы 0x81 на чтение основного контура (DID 0x0014 = 4321): только в её средние.
    stub._chamber_live_wanted = True
    stub._parse_calibration_response_identifier = lambda identifier: (0xDA00, 0xF1, identifier & 0xFF)
    stub._is_calibration_response_identifier = lambda identifier: (identifier & 0xFF) == stub._calibration_target_node_sa
    with stub._mb_context(0x81):
        stub._chamber_live_reset()
    stub._mb_handle_live_frame(0x18DAF181, [0x05, 0x62, 0x00, 0x14, 0xE1, 0x10, 0, 0])
    with stub._mb_context(0x81):
        assert stub._chamber_live_last["main"] == 4321
    with stub._mb_context(0x80):
        assert stub._chamber_live_last["main"] == 5000


def test_bus_is_quiet_during_the_run_and_released_after(tmp_path: Path):
    stub = _stub(tmp_path)
    requests = []

    class _Service:
        def request(self, **kwargs):
            requests.append(kwargs)
            return True

    stub._communication_control_service = _Service()
    stub._communication_control_busy = False
    stub._mb_quiet_keep(time.monotonic())
    assert requests == [], "без прогона шину не трогаем"
    assert stub._climate_run_start(), stub._climate_run_status
    stub._mb_quiet_keep(time.monotonic() + 100)
    assert requests[-1]["control_type"] == 1 and requests[-1]["suppress_positive_response"]
    assert (requests[-1]["tx_identifier"] >> 8) & 0xFFFF == 0xDBFF, "функционально - всем платам сразу"
    stub._climate_run_stop("тест")
    assert requests[-1]["control_type"] == 0


def test_profiles_are_written_one_board_after_another(tmp_path: Path):
    stub = _stub(tmp_path)
    started = []

    def chain_start(automatic=False):
        started.append(stub._calibration_target_node_sa)
        stub._chamber_chain_stage = "write"
        stub._chamber_chain_status = f"профиль записан в 0x{stub._calibration_target_node_sa:02X}"

    stub._chamber_chain_start = chain_start
    stub._chamber_auto_write = True
    for sa, *_rest in BOARDS:
        with stub._mb_context(sa):
            stub._chamber_tables_complete = True
    stub._mb_start_profiles()
    now = time.monotonic()
    for _ in range(3):
        stub._mb_profile_tick(now)
        assert stub._mb_profiles_busy()
        stub._chamber_chain_stage = ""
    stub._mb_profile_tick(now)
    assert started == [0x80, 0x81, 0x82] and not stub._mb_profiles_busy()
    assert "записан в 0x82" in stub._mb_profile_results[0x82]
    assert "«П2»: точек 0, профиль записан в 0x81" in stub._mb_summary_text()


def test_board_list_is_kept_and_checked(tmp_path: Path):
    stub = _stub(tmp_path)
    assert not stub._mb_add_board("0x80", "ещё")[0], "адрес уже есть"
    assert not stub._mb_add_board("0xF1", "тестер")[0], "адрес самой программы"
    assert not stub._mb_add_board("abc", "x")[0]
    again = _MbStub(tmp_path)
    assert [board["sa"] for board in again._mb_boards] == [0x80, 0x81, 0x82] and again._mb_on()
    assert stub._mb_remove_board(0x82)[0] and stub._mb_remove_board(0x81)[0]
    assert not stub._mb_on(), "одна плата - обычный режим"


def test_every_board_gets_every_value_for_any_board_count(tmp_path: Path):
    """Общий номер величины при 3 платах отдавал бы первой плате только контуры."""
    stub = _stub(tmp_path)
    asked: dict[int, set] = {}

    class _Read:
        def read_data_by_identifier(self, identifier, var):
            asked.setdefault((identifier >> 8) & 0xFF, set()).add(int(var.pid))

    stub._chamber_live_read = _Read()
    stub._build_calibration_tx_identifier = lambda: 0x18DA00F1 | (stub._calibration_target_node_sa << 8)
    for _ in range(3 * 6):
        stub._chamber_live_pending = None
        stub._mb_live_tick(time.monotonic())
    wanted = {0x0014, 0x0067, 0x0019, 0x003B}
    assert all(asked.get(sa) == wanted for sa, *_rest in BOARDS), asked


def test_stale_limit_grows_with_the_polling_round(tmp_path: Path):
    stub = _stub(tmp_path)
    # 3 платы: круг одной величины 6 x 3 x 90 мс = 1,62 с, порог - 2,5 круга.
    assert abs(stub._chamber_live_stale_s() - 4.05) < 1e-6
    assert stub._mb_set_enabled(False)[0]
    assert stub._chamber_live_stale_s() == stub.CHAMBER_LIVE_STALE_S


def test_profile_requests_go_to_the_chamber_board(tmp_path: Path):
    from ui.qml.controller.profile_mixin import AppControllerProfileMixin

    stub = _stub(tmp_path)
    with stub._mb_context(0x82):
        assert AppControllerProfileMixin._profile_target_override(stub) == 0x82
    assert AppControllerProfileMixin._profile_target_override(stub) == 0x80
    assert stub._mb_set_enabled(False)[0]
    assert AppControllerProfileMixin._profile_target_override(stub) is None, "одна плата - как раньше"


def test_calibration_of_previous_board_is_closed_before_next_profile(tmp_path: Path):
    stub = _stub(tmp_path)
    started, stops = [], []

    def chain_start(automatic=False):
        started.append(stub._calibration_target_node_sa)
        stub._chamber_chain_stage = "write"
        # Цепочка сама открывает калибровку и доступ для своей платы.
        stub._calibration_active = True
        stub._service_security_unlocked = True
        stub._service_access_target_sa = stub._calibration_target_node_sa
        stub._chamber_chain_status = f"записан в 0x{stub._calibration_target_node_sa:02X}"
        return True

    def stop_calibration():
        stops.append(stub._service_access_target_sa)
        stub._calibration_active = False
        stub._calibration_waiting_session = True

    stub._chamber_chain_start = chain_start
    stub.stopCalibration = stop_calibration
    stub._calibration_waiting_session = False
    # Оператор до этого открыл калибровку для 0x82.
    stub._calibration_active, stub._service_security_unlocked, stub._service_access_target_sa = True, True, 0x82
    stub._chamber_auto_write = True
    for sa, *_rest in BOARDS:
        with stub._mb_context(sa):
            stub._chamber_tables_complete = True
    stub._mb_start_profiles()
    now = time.monotonic()
    for _ in range(12):
        stub._mb_profile_tick(now)
        # Прибор подтвердил возврат сеанса; запись профиля текущей платы закончилась.
        stub._calibration_waiting_session = False
        stub._chamber_chain_stage = ""
    assert started == [0x80, 0x81, 0x82]
    assert stops == [0x82, 0x80, 0x81, 0x82], "перед каждой платой и после последней калибровка закрыта"
    assert not stub._mb_profiles_busy()


def test_silent_previous_board_does_not_block_the_queue(tmp_path: Path):
    stub = _stub(tmp_path)
    started = []
    stub._chamber_chain_start = lambda automatic=False: started.append(stub._calibration_target_node_sa) or True
    stub.stopCalibration = lambda: setattr(stub, "_calibration_waiting_session", True) or         setattr(stub, "_calibration_active", False)
    stub._finish_calibration_deactivation = lambda _text: setattr(stub, "_calibration_waiting_session", False)
    stub._calibration_active, stub._calibration_waiting_session = True, False
    stub._service_security_unlocked, stub._service_access_target_sa = True, 0x99
    stub._chamber_auto_write = True
    for sa, *_rest in BOARDS:
        with stub._mb_context(sa):
            stub._chamber_tables_complete = True
    stub._mb_start_profiles()
    now = time.monotonic()
    stub._mb_profile_tick(now)
    stub._mb_profile_tick(now + 5)
    assert started == []
    stub._mb_profile_tick(now + 16)
    stub._mb_profile_tick(now + 16.2)
    assert started == [0x80]


def test_failed_chain_start_is_reported_and_queue_moves_on(tmp_path: Path):
    stub = _stub(tmp_path)
    stub._chamber_chain_start = lambda automatic=False: False
    stub._chamber_chain_problem = lambda: "в журнале нет ни одной точки"
    stub._chamber_auto_write = True
    for sa, *_rest in BOARDS:
        with stub._mb_context(sa):
            stub._chamber_tables_complete = True
    stub._mb_start_profiles()
    for _ in range(4):
        stub._mb_profile_tick(time.monotonic())
    assert not stub._mb_profiles_busy()
    assert all("нет ни одной точки" in stub._mb_profile_results[sa] for sa, *_rest in BOARDS)


def test_restart_returns_each_journal_to_its_own_board(tmp_path: Path):
    stub = _stub(tmp_path)
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    saved = stub._mb_journals()
    assert len({item["journal"] for item in saved}) == 3
    # После перезапуска показана другая плата: журналы всё равно идут каждый в свою.
    again = _MbStub(tmp_path)
    assert again._mb_activate(0x82, force=True)
    events = again._mb_restore_journals(saved)
    assert len(events) == 3 and not any("не загрузился" in text for text in events), events
    for sa, name, _offset, main in BOARDS:
        with again._mb_context(sa):
            assert again._chamber_points and all(point["main"] == main for point in again._chamber_points), name


def test_boards_do_not_share_fields_after_enabling(tmp_path: Path):
    """Как у оператора: П1 и П5 показывали одни и те же числа - писали в одно окно среднего."""
    stub = _MbStub(tmp_path)
    for sa, name, _offset, _main in BOARDS:
        assert stub._mb_add_board(f"0x{sa:02X}", name)[0]
    assert stub._mb_active_sa is None and not stub._mb_on()
    # Окно показывает таблицу плат, пока режим выключен.
    stub._mb_view()
    stub._mb_view()
    assert stub._mb_set_enabled(True)[0]
    now = time.monotonic()
    for sa, _name, _offset, main in BOARDS:
        with stub._mb_context(sa):
            stub._chamber_live_note("main", main, now)
    for sa, name, _offset, main in BOARDS:
        with stub._mb_context(sa):
            assert stub._chamber_live_last["main"] == main, name
            assert [value for _stamp, value in stub._chamber_live_recent["main"]] == [main], name


def test_strip_tiles_show_nodes_and_profile_in_the_board(tmp_path: Path):
    stub = _stub(tmp_path, temps=(25.0, -40.0))
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    stub._addr_info = {0x81: {"profileStatus": 0x0F, "profileCrc": 0x66E8}, 0x82: {"profileStatus": 0x05}}
    rows = {row["sa"]: row for row in stub._mb_view()["boards"]}
    marks = {mark["short"]: mark["count"] for mark in rows[0x80]["nodes"]}
    assert marks["-40"] == 1 and marks["25"] == 1 and marks["85"] == 0
    assert rows[0x80]["profileState"] == "не записан"
    assert rows[0x81]["profileState"] == "в плате 0x66E8" and rows[0x81]["profileTone"] == "ok"
    assert rows[0x82]["profileState"] == "в плате не применяется"


def test_shown_board_is_not_switched_during_trial(tmp_path: Path):
    stub = _stub(tmp_path)
    stub._trial_busy = True
    assert not stub._mb_activate(0x81)
    view = stub._mb_view()
    assert view["shownSa"] == "0x80" and "пробная калибровка" in view["switchNote"]
    stub._trial_busy = False
    assert stub._mb_activate(0x81) and stub._mb_view()["switchNote"] == ""


def test_run_check_warns_when_several_boards_but_mode_off(tmp_path: Path):
    stub = _stub(tmp_path)
    assert stub._mb_set_enabled(False)[0]
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert not checks["boards"]["ok"] and "выключено" in checks["boards"]["text"]
    assert stub._mb_set_enabled(True)[0]
    stub._chamber_auto_write = True
    checks = {item["key"]: item for item in stub._climate_auto_checks()}
    assert checks["boards"]["ok"] and "по очереди" in checks["boards"]["text"]


ALL_NODES = (25.0, -40.0, -20.0, 0.0, 50.0, 70.0, 85.0)


def test_full_run_gives_every_board_all_nodes_and_queues_every_profile(tmp_path: Path):
    stub = _stub(tmp_path, temps=ALL_NODES)
    stub._chamber_set_board_only(True)
    stub._climate_scenario["auto_write"] = True
    stub._chamber_auto_write = True
    queued = []
    stub._mb_profile_tick = lambda now: queued.extend(stub._mb_profile_queue) or stub._mb_profile_queue.clear()
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    for sa, name, _offset, main in BOARDS:
        with stub._mb_context(sa):
            nodes = sorted({chamber_fit.nearest_node(point["board_temp_x10"]) for point in stub._chamber_points})
            assert nodes == sorted(chamber_fit.NODES_X10), (name, nodes)
            assert stub._chamber_tables_complete, (name, stub._chamber_tables_text)
            assert all(point["main"] == main for point in stub._chamber_points), name
    assert sorted(queued or stub._mb_profile_queue) == [sa for sa, *_rest in BOARDS], "профиль - в каждую плату"


def test_manual_capture_takes_a_point_from_every_board(tmp_path: Path):
    stub = _stub(tmp_path)
    ok, text = stub._mb_manual_capture_start()
    assert ok and "3 плат" in text
    stub._mb_manual_capture_tick(time.monotonic())
    for sa, name, _offset, main in BOARDS:
        with stub._mb_context(sa):
            assert len(stub._chamber_points) == 1 and stub._chamber_points[0]["main"] == main, name
    assert stub._mb_manual_capture is None and "у 3 из 3 плат" in stub._mb_status
    rows = stub._mb_all_rows()
    assert sorted((row["board"], row["sa"]) for row in rows) == sorted((name, sa) for sa, name, *_rest in BOARDS)


def test_profile_button_queues_every_board_with_complete_tables(tmp_path: Path):
    stub = _stub(tmp_path)
    stub._chamber_auto_write = False
    for sa, *_rest in BOARDS:
        with stub._mb_context(sa):
            stub._chamber_tables_complete = sa != 0x81
    text = stub._mb_start_profiles(manual=True)
    assert stub._mb_profile_queue == [0x80, 0x82] and "П1" in text and "П3" in text
    assert "неполные" in stub._mb_profile_results[0x81]


def test_new_journal_for_every_board(tmp_path: Path):
    stub = _stub(tmp_path)
    assert stub._mb_manual_capture_start()[0]
    stub._mb_manual_capture_tick(time.monotonic())
    stub._mb_clear_journals()
    for sa, name, *_rest in BOARDS:
        with stub._mb_context(sa):
            assert stub._chamber_points == [], name


def _with_control(stub):
    """Команды сайта (их обработчики) - поверх заглушки плат."""
    from ui.qml.controller.climate_control_mixin import AppControllerClimateControlMixin

    stub.__class__ = type("_CtlMbStub", (AppControllerClimateControlMixin, stub.__class__), {})
    return stub


def test_site_gets_details_of_every_board_and_can_show_one(tmp_path: Path):
    stub = _with_control(_stub(tmp_path, temps=(25.0, -40.0)))
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    details = stub._mb_board_details()
    for sa, name, *_rest in BOARDS:
        item = details[sa]
        assert len(item["coverage"]) == 7 and f"_0x{sa:02X}" in item["file"] and item["lastPoint"], name
    ok, text, who = stub._control_do_board_show({}, {"sa": "0x82"})
    assert ok and stub._mb_active_sa == 0x82 and "П3" in text
    ok, text, _who = stub._control_do_board_show({}, {"sa": "0x99"})
    assert not ok and "нет в списке" in text


def test_capture_command_from_site_takes_every_board(tmp_path: Path):
    stub = _with_control(_stub(tmp_path))
    stub._can = type("Can", (), {"is_connect": True, "is_trace": True})()
    ok, text, details = stub._control_do_capture({}, {"label": "0/0"})
    assert ok and "у всех 3 плат" in text, text
    stub._mb_manual_capture_tick(time.monotonic())
    for sa, name, *_rest in BOARDS:
        with stub._mb_context(sa):
            assert len(stub._chamber_points) == 1, name


def test_state_without_boards_line_is_noticed_and_journals_are_found_on_disk(tmp_path: Path):
    stub = _stub(tmp_path, temps=(25.0, -40.0))
    assert stub._climate_run_start(), stub._climate_run_status
    _walk(stub)
    files = {}
    for sa, *_rest in BOARDS:
        with stub._mb_context(sa):
            files[sa] = stub._chamber_file_path
    # Как сохраняла прежняя версия: журнал только показанной платы (здесь - П2), строки «boards» нет.
    saved = {"saved": time.strftime("%Y-%m-%d %H:%M:%S"), "elapsed_s": 3600,
             "chamber": {"journal": files[0x81], "label": "0/0", "board_only": False}}
    note = stub._climate_auto_boards_note(saved)
    assert "нет журналов каждой платы" in note
    assert "есть журналы 3 плат" in stub._climate_auto_boards_note(
        {"chamber": {"boards": [{"sa": sa, "journal": path} for sa, path in files.items()]}})

    # Перезапуск: новая программа, режим нескольких плат включён, показана первая плата.
    again = _MbStub(tmp_path)
    events = []
    again._climate_event = lambda text, level="info": events.append((level, text))
    again._climate_auto_restore_chamber(saved["chamber"], again._climate_auto_run_since(saved))
    for sa, name, _offset, main in BOARDS:
        with again._mb_context(sa):
            assert again._chamber_file_path == files[sa], name
            assert again._chamber_points and all(point["main"] == main for point in again._chamber_points), name
    assert any("найдены по файлам" in text for _level, text in events), events
