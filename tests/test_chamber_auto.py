"""Проверки автоматики раздела «Прогон в камере».

Прогон длится часами, оператор стоит у камеры и не должен ходить по
разделам. Тесты закрепляют:
- точка берётся сразу из скользящего среднего, а смена эталона начинает окно заново;
- без среднего кнопка не теряет нажатие, а записывает точку сама, когда оно набралось;
- журнал сохраняется сам после каждой точки, «Очистить» не стирает прежний файл;
- таблицы пересчитываются сами и не меняются посреди записи профиля в прибор;
- профиль пишется в прибор цепочкой: доступ, запись, сверка, файл, и один и тот же
  профиль второй раз сам не пишется.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_fit
from ui.qml.controller.chamber_chain_mixin import AppControllerChamberChainMixin
from ui.qml.controller.chamber_live_mixin import AppControllerChamberLiveMixin
from tests.test_chamber_run import _ChamberStub, _full_run_points, _Signal


class _FakeCan:
    is_connect = True
    is_trace = True


class _FakeTimer:
    def __init__(self):
        self.active = False

    def start(self, *args):
        self.active = True

    def stop(self):
        self.active = False

    def isActive(self):
        return self.active


class _LiveStub(AppControllerChamberLiveMixin, _ChamberStub):
    """Прогон с живыми показаниями, но без Qt и без шины."""

    def __init__(self, root: Path | None = None):
        _ChamberStub.__init__(self)
        self.chamberLiveChanged = _Signal()
        self.infoMessage = _Signal()
        self._can = _FakeCan()
        self._chamber_live_reset()
        self._chamber_live_wanted = True
        self._chamber_window_s = 10.0
        self._chamber_capture_waiting = False
        self._chamber_capture_wait_since = 0.0
        self._project_root_directory = root


def _feed(stub, main=5000, media=4500, board=250, fuel=250, count=5, now=None):
    """Прибор отдал несколько показаний каждой величины подряд."""
    now = time.monotonic() if now is None else now
    for index in range(count):
        stamp = now - (count - index) * 0.3
        stub._chamber_live_note("main", main, stamp)
        stub._chamber_live_note("media", media, stamp)
        stub._chamber_live_note("board_temp", board, stamp)
        stub._chamber_live_note("fuel_temp", fuel, stamp)
    return now


# ------------------------------------------------------------------ скользящее среднее

def test_point_takes_the_running_average_at_once(tmp_path: Path):
    """Кнопка сразу кладёт в журнал средние из полей, без отдельного замера."""
    stub = _LiveStub(tmp_path)
    stub._chamber_label = "150/47"
    now = time.monotonic()
    for index, (main, media) in enumerate(((10950, 6440), (10956, 6442), (10954, 6441), (10952, 6443))):
        stamp = now - 2.0 + index * 0.4
        stub._chamber_live_note("main", main, stamp)
        stub._chamber_live_note("media", media, stamp)
        stub._chamber_live_note("board_temp", 251, stamp)
        stub._chamber_live_note("fuel_temp", 249, stamp)

    assert stub._chamber_capture_from_average()

    assert not stub._chamber_capture_waiting
    assert len(stub._chamber_points) == 1
    point = stub._chamber_points[0]
    assert point["note"] == "150/47"
    assert point["main"] == 10953
    assert point["media"] == 6442
    assert point["board_temp_x10"] == 251
    assert "среднее за" in stub._chamber_status


def test_new_reference_restarts_the_window():
    """После переключения эталона старые показания к новой точке не относятся."""
    stub = _LiveStub()
    now = time.monotonic()
    for index in range(6):
        stub._chamber_live_note("main", 5000, now - 3.0 + index * 0.2)
    for index in range(stub.CHAMBER_JUMP_CONFIRM):
        stub._chamber_live_note("main", 7600, now - 1.0 + index * 0.2)

    stats = stub._chamber_live_stats("main", now)
    assert round(stats["mean"]) == 7600
    assert stats["count"] == stub.CHAMBER_JUMP_CONFIRM


def test_single_spike_does_not_spoil_the_average():
    """Одиночный выброс в среднее не попадает."""
    stub = _LiveStub()
    now = time.monotonic()
    for index in range(6):
        stub._chamber_live_note("main", 5000, now - 3.0 + index * 0.2)
    stub._chamber_live_note("main", 5400, now - 1.5)
    stub._chamber_live_note("main", 5000, now - 1.3)

    stats = stub._chamber_live_stats("main", now)
    assert round(stats["mean"]) == 5000
    assert stats["spread"] == 0


def test_old_readings_leave_the_window():
    """Среднее считается только за окно, заданное оператором."""
    stub = _LiveStub()
    now = time.monotonic()
    stub._chamber_live_note("main", 4000, now - 30.0)
    stub._chamber_live_note("main", 5000, now - 1.0)
    stub._chamber_live_note("main", 5002, now - 0.5)

    stats = stub._chamber_live_stats("main", now)
    assert stats["count"] == 2
    assert round(stats["mean"]) == 5001


def test_press_without_average_waits_and_stores_by_itself(tmp_path: Path):
    """Нажатие до того, как среднее набралось, не теряется: точка запишется сама."""
    stub = _LiveStub(tmp_path)
    stub._chamber_label = "0/0"

    assert stub._chamber_capture_from_average()
    assert stub._chamber_capture_waiting
    assert stub._chamber_points == []
    assert "запишу сама" in stub._chamber_status.lower()

    now = _feed(stub)
    stub._chamber_live_check_waiting(now)

    assert not stub._chamber_capture_waiting
    assert len(stub._chamber_points) == 1


def test_waiting_gives_up_with_a_reason():
    """Если прибор молчит, ожидание кончается понятным отказом, а не висит вечно."""
    stub = _LiveStub()
    stub._chamber_label = "0/0"
    stub._chamber_capture_from_average()

    stub._chamber_live_check_waiting(time.monotonic() + stub.CHAMBER_WAIT_LIMIT_S + 1.0)

    assert not stub._chamber_capture_waiting
    assert "не записана" in stub._chamber_status
    assert stub._chamber_points == []


def test_firmware_without_media_channel_still_gives_points(tmp_path: Path):
    """Контура вида топлива нет в старой прошивке: точка пишется без него."""
    stub = _LiveStub(tmp_path)
    stub._chamber_label = "воздух"
    stub._chamber_live_missing.add("media")
    now = time.monotonic()
    for index in range(4):
        stub._chamber_live_note("main", 6000, now - 1.0 + index * 0.2)
        stub._chamber_live_note("board_temp", 250, now - 1.0 + index * 0.2)
        stub._chamber_live_note("fuel_temp", 250, now - 1.0 + index * 0.2)

    assert stub._chamber_capture_from_average()
    assert stub._chamber_points[0]["media"] is None


def test_answer_from_another_section_is_picked_up():
    """Ответ на тот же параметр, запрошенный другим разделом, тоже идёт в среднее."""
    stub = _LiveStub()
    stub._is_calibration_response_identifier = lambda identifier: True
    did = 0x0014
    value = 5123
    payload = [0x05, 0x62, (did >> 8) & 0xFF, did & 0xFF, value & 0xFF, (value >> 8) & 0xFF, 0, 0]

    stub._handle_chamber_live_frame(0x18DAF16A, payload)

    assert stub._chamber_live_last["main"] == 5123


def test_window_is_checked():
    stub = _LiveStub()
    assert not stub._chamber_live_set_window("0,5")
    assert stub._chamber_window_s == 10.0
    assert stub._chamber_live_set_window("30")
    assert stub._chamber_window_s == 30.0


# ------------------------------------------------------------------ журнал и расчёт сами

def test_journal_is_saved_after_every_point(tmp_path: Path):
    """Забытое сохранение или упавшая программа не должны стоить часов прогона."""
    stub = _LiveStub(tmp_path)
    stub._chamber_label = "0/0"
    _feed(stub)
    stub._chamber_capture_from_average()

    path = Path(stub._chamber_file_path)
    assert path.parent == tmp_path / "logs" / "chamber"
    assert path.exists()

    stub._chamber_label = "150/47"
    _feed(stub, main=10955, media=6441)
    stub._chamber_capture_from_average()

    restored = _ChamberStub()
    assert restored._chamber_load_file(str(path))
    assert [point["note"] for point in restored._chamber_points] == ["0/0", "150/47"]
    assert "сохранён" in stub._chamber_status


def test_removed_point_leaves_the_file_too(tmp_path: Path):
    stub = _LiveStub(tmp_path)
    for note in ("0/0", "68/22"):
        stub._chamber_label = note
        _feed(stub)
        stub._chamber_capture_from_average()

    stub._chamber_remove_last_point()

    restored = _ChamberStub()
    assert restored._chamber_load_file(stub._chamber_file_path)
    assert [point["note"] for point in restored._chamber_points] == ["0/0"]


def test_clearing_keeps_the_old_file_and_starts_a_new_one(tmp_path: Path):
    """Случайная «Очистить» не должна стирать прогон на диске."""
    stub = _LiveStub(tmp_path)
    stub._chamber_label = "0/0"
    _feed(stub)
    stub._chamber_capture_from_average()
    old_path = Path(stub._chamber_file_path)

    stub._chamber_clear_points()

    assert stub._chamber_file_path == ""
    restored = _ChamberStub()
    assert restored._chamber_load_file(str(old_path))
    assert len(restored._chamber_points) == 1


def test_tables_are_recomputed_after_each_point(tmp_path: Path):
    """Таблицы считаются сами: кнопка расчёта больше не обязательна."""
    stub = _LiveStub(tmp_path)
    points = _full_run_points()
    stub._chamber_points = points[:-1]
    last = points[-1]
    stub._chamber_label = last["note"]
    _feed(stub, main=last["main"], media=last["media"],
          board=last["board_temp_x10"], fuel=last["fuel_temp_x10"])

    stub._chamber_capture_from_average()

    assert getattr(stub, "applied", None) is not None
    assert stub._chamber_tables_complete
    assert "по всем узлам" in stub._chamber_tables_text


def test_incomplete_run_says_what_is_missing_without_touching_the_profile(tmp_path: Path):
    stub = _LiveStub(tmp_path)
    stub._chamber_label = "0/0"
    _feed(stub)
    stub._chamber_capture_from_average()

    assert getattr(stub, "applied", None) is None
    assert not stub._chamber_tables_complete
    assert "не считаются" in stub._chamber_tables_text
    assert stub._chamber_report


def test_tables_are_not_changed_while_the_profile_is_being_written(tmp_path: Path):
    """Таблицы на экране и есть то, что уходит в прибор: посреди записи их менять нельзя."""
    stub = _LiveStub(tmp_path)
    stub._chamber_points = _full_run_points()
    stub._profile_busy = True

    assert not stub._chamber_auto_compute()
    assert stub._chamber_tables_deferred
    assert getattr(stub, "applied", None) is None


def test_rehearsal_points_are_neither_saved_nor_computed(tmp_path: Path):
    """Пробная калибровка ведёт проверку сама, её точки не должны трогать файлы и профиль."""
    stub = _LiveStub(tmp_path)
    stub._chamber_rehearsal = True
    stub._chamber_label = "проба на столе"
    _feed(stub)
    stub._chamber_capture_from_average()

    assert stub._chamber_file_path == ""
    assert getattr(stub, "applied", None) is None


# ------------------------------------------------------------------ запись профиля цепочкой

class _ChainStub(AppControllerChamberChainMixin, _ChamberStub):
    """Цепочка записи профиля с подменённым прибором и разделом профиля."""

    def __init__(self, root: Path):
        _ChamberStub.__init__(self)
        self._project_root_directory = root
        self._can = _FakeCan()
        self._chamber_auto_write = True
        self._chamber_chain_stage = ""
        self._chamber_chain_steps = {key: "" for key, _title in self.CHAMBER_CHAIN_STEPS}
        self._chamber_chain_status = ""
        self._chamber_chain_color = ""
        self._chamber_chain_deadline = 0.0
        self._chamber_chain_crc = None
        self._chamber_written_crc = None
        self._chamber_chain_timer = _FakeTimer()
        self._chamber_points = _full_run_points()

        self._calibration_active = False
        self._calibration_session_ready = False
        self._service_access_target_sa = None
        self._service_security_unlocked = False
        self.toggled = 0

        self._profile_busy = False
        self._options_busy = False
        self._profile_verify = None
        self._profile_verify_report = []
        self._profile_last_result = None
        self.writes = 0
        self.saved_paths = []
        self.crc = 0x1234

    def _resolve_calibration_target_sa(self):
        return 0x6A

    def toggleCalibration(self):
        self.toggled += 1
        self._calibration_active = True

    def open_access(self):
        self._calibration_session_ready = True
        self._service_access_target_sa = 0x6A
        self._service_security_unlocked = True

    def _profile_calc_crc(self):
        return self.crc

    def _profile_validate(self):
        return []

    def _profile_write_to_device(self, allow_empty=False, verify=True):
        self.writes += 1
        self._profile_busy = True
        self._profile_last_result = None
        return True

    def _profile_save_file(self, path):
        self.saved_paths.append(path)
        return True


def test_chain_opens_access_writes_verifies_and_saves(tmp_path: Path):
    """Шаги 6-10 профиля идут сами и в правильном порядке."""
    stub = _ChainStub(tmp_path)
    stub._chamber_file_path = str(tmp_path / "logs" / "chamber" / "chamber_20260930_120000.csv")

    assert stub._chamber_chain_start()
    assert stub.toggled == 1
    assert stub._chamber_chain_stage == "access"

    # Доступ ещё не открыт: цепочка ждёт и ничего не пишет.
    stub._on_chamber_chain_tick()
    assert stub.writes == 0

    stub.open_access()
    stub._on_chamber_chain_tick()
    assert stub.writes == 1
    assert stub._chamber_chain_steps["access"] == "ok"

    # Запись кончилась, идёт сверка.
    stub._profile_verify = {}
    stub._on_chamber_chain_tick()
    assert stub._chamber_chain_steps["write"] == "ok"
    assert stub._chamber_chain_steps["verify"] == "run"

    stub._profile_verify = None
    stub._profile_busy = False
    stub._profile_last_result = "ok"
    stub._on_chamber_chain_tick()

    assert stub._chamber_chain_stage == ""
    assert all(state == "ok" for state in stub._chamber_chain_steps.values())
    assert stub.saved_paths == [str(tmp_path / "logs" / "chamber" / "chamber_20260930_120000_profile.json")]
    assert stub._chamber_written_crc == 0x1234
    assert "сверен" in stub._chamber_chain_status


def test_chain_names_the_verify_failure(tmp_path: Path):
    stub = _ChainStub(tmp_path)
    stub.open_access()
    stub._calibration_active = True
    stub._chamber_chain_start()
    stub._on_chamber_chain_tick()

    stub._profile_busy = False
    stub._profile_verify_report = ["Плата, основной, узел -40 °C: записано 5, в приборе 0"]
    stub._profile_last_result = "fail"
    stub._on_chamber_chain_tick()

    assert stub._chamber_chain_steps["verify"] == "fail"
    assert "записано 5" in stub._chamber_chain_status
    assert stub.saved_paths == []
    assert stub._chamber_written_crc is None


def test_chain_gives_up_when_access_does_not_open(tmp_path: Path):
    stub = _ChainStub(tmp_path)
    stub._chamber_chain_start()
    stub._chamber_chain_deadline = time.monotonic() - 1.0
    stub._on_chamber_chain_tick()

    assert stub._chamber_chain_steps["access"] == "fail"
    assert stub._chamber_chain_stage == ""
    assert stub.writes == 0


def test_same_profile_is_not_written_twice_by_itself(tmp_path: Path):
    """Сама цепочка пишет только изменившиеся таблицы: память прибора не изнашивается зря."""
    stub = _ChainStub(tmp_path)
    stub._chamber_tables_complete = True
    stub._chamber_written_crc = 0x1234

    stub._chamber_chain_maybe_auto()
    assert stub._chamber_chain_stage == ""

    stub.crc = 0x4321
    stub._chamber_chain_maybe_auto()
    assert stub._chamber_chain_stage == "access"


def test_rehearsal_tables_are_written_only_in_test_mode(tmp_path: Path):
    """Пробные таблицы в рабочий прибор не пишутся, а на стенде в тестовом режиме - пишутся."""
    stub = _ChainStub(tmp_path)
    stub._chamber_points[0]["rehearsal"] = True

    assert not stub._chamber_chain_start()
    assert "тестовом режиме" in stub._chamber_chain_status

    stub._chamber_test_mode = True
    assert stub._chamber_chain_start()


def test_auto_write_can_be_switched_off(tmp_path: Path):
    stub = _ChainStub(tmp_path)
    stub._chamber_tables_complete = True
    stub._chamber_auto_write = False

    stub._chamber_chain_maybe_auto()
    assert stub._chamber_chain_stage == ""


def test_complete_tables_start_the_chain_by_themselves(tmp_path: Path):
    """Полные таблицы после точки сами запускают запись профиля."""
    stub = _ChainStub(tmp_path)
    stub._profile_apply_chamber_format = lambda payload: True

    assert stub._chamber_compute_tables(quiet=True)
    assert stub._chamber_tables_complete
    assert stub._chamber_chain_stage == "access"
    assert stub.toggled == 1


def test_nodes_in_the_test_run_cover_the_grid():
    """Опора для проверок выше: полный прогон закрывает все узлы сетки."""
    nodes = {chamber_fit.nearest_node(point["board_temp_x10"]) for point in _full_run_points()}
    assert nodes == set(chamber_fit.NODES_X10)
