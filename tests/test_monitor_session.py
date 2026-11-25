"""Проверки постоянной истории, пиков уровня и неизменности завершённого прогона."""

import csv
import json
import time
import zipfile
from types import SimpleNamespace

from tests.test_journal_assign_monitor import BOARDS, _MonStub, _mon_stub, _monitor_feed
from ui.qml import climate_scenario
from ui.qml.controller.run_report_mixin import AppControllerRunReportMixin
from ui.qml.monitor_session import MonitorSession, thin_points


def _recording(tmp_path):
    """Для проверки без камеры начинает запись трёх плат с готовыми профилями."""
    stub = _mon_stub(tmp_path)
    stub.__class__ = type("_StoredReportStub", (AppControllerRunReportMixin, stub.__class__), {})
    stub._climate_scenario = climate_scenario.check_scenario()
    stub._chamber_check_only = True
    stub._mb_run_sas = [sa for sa, *_ in BOARDS]
    now = time.monotonic()
    stub._chamber_monitor_begin(now)
    return stub, now


def _feed_all(stub, now, level=0.4, tube=25.0):
    """Для сравнения плат подаёт одинаковые условия с разными адресами CAN."""
    for sa, *_ in BOARDS:
        _monitor_feed(stub, sa, now, tube, level, 15509)
    stub._chamber_monitor_tick(now, force=True)


def test_monitor_waits_for_first_readings_before_run(tmp_path):
    """Чтобы фоновый опрос до старта не падал, проверяет пустые показания и незаданное время начала."""
    stub = _mon_stub(tmp_path)
    now = time.monotonic()
    # Контракт контроллера возвращает None даже при указанном значении getattr по умолчанию.
    assert getattr(stub, "_chamber_monitor_started_s", now) is None
    for index in range(3):
        stub._chamber_monitor_tick(now + index * 10, force=True)
    view = stub._chamber_monitor_view()
    assert not view["hasRun"]
    assert len(view["live"]) == len(BOARDS)
    assert all(row["status"] == "нет свежих данных" for row in view["live"])


def test_live_timer_handles_no_readings_before_run(tmp_path):
    """Чтобы проверить путь из traceback, вызывает живой таймер без CAN для одной и нескольких плат."""
    for enabled in (False, True):
        stub = _mon_stub(tmp_path / str(enabled))
        assert stub._mb_set_enabled(enabled)[0]
        stub._can = SimpleNamespace(is_connect=False, is_trace=False)
        stub._chamber_live_wanted = True
        stub._on_chamber_live_tick()
        assert stub._chamber_monitor_session is None


def test_monitor_handles_explicit_none_start_time(tmp_path):
    """Чтобы пустое время не роняло монитор, проверяет None до первых измерений активного прогона."""
    stub, now = _recording(tmp_path)
    stub._chamber_monitor_started_s = None
    stub._chamber_monitor_tick(now, force=True)
    _feed_all(stub, now + 10)
    assert all(row["err"] == "+0,40" for row in stub._chamber_monitor_view()["live"])


def test_zero_start_time_still_records_missing_readings(tmp_path):
    """Чтобы защита от None не скрыла пропуски, сохраняет отсутствие данных при числовом времени 0."""
    stub, now = _recording(tmp_path)
    stub._chamber_monitor_started_s = 0.0
    stub._chamber_monitor_tick(now + stub._chamber_live_stale_s(), force=True)
    assert stub._chamber_monitor_view()["gaps"] == len(BOARDS)


def test_records_absolute_error_and_keeps_fuel_film(tmp_path):
    """Чтобы плёнка не скрывалась обнулением, сохраняет исходные +0,4 % и адрес каждой платы."""
    stub, now = _recording(tmp_path)
    _feed_all(stub, now)
    session = stub._chamber_monitor_session
    assert session is not None
    view = stub._chamber_monitor_view()
    assert all(row["err"] == "+0,40" for row in view["live"])
    assert stub._chamber_monitor_set_reference()[0] is False
    stub._chamber_monitor_reset()
    assert all(row["err"] == "+0,40" for row in stub._chamber_monitor_view()["live"])
    with (session.folder / "measurements.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    assert {row["CAN-адрес"] for row in rows} == {f"0x{sa:02X}" for sa, *_ in BOARDS}
    assert {row["Отклонение (%)"] for row in rows} == {"0,4"}


def test_capture_keeps_brief_excursion_instead_of_average(tmp_path):
    """Чтобы усреднение не спрятало нарушение допуска, сохраняет одиночное показание +1,2 %."""
    stub, now = _recording(tmp_path)
    _feed_all(stub, now, level=0.0)
    with stub._mb_context(BOARDS[0][0], notify=False):
        stub._chamber_live_note("level", 12, now + 0.1)
        stub._chamber_live_note("level", 0, now + 0.2)
        assert any(sample["level"] == 12 for sample in stub._chamber_monitor_history)
    row = stub._chamber_monitor_view()["live"][0]
    assert row["tone"] == "bad" and "+1,20" in row["worst"]


def test_tolerance_uses_zero_instead_of_shift(tmp_path):
    """Чтобы сдвиг не давал ложный брак, сравнивает +0,9 и −0,9 % именно с нулём."""
    stub, now = _recording(tmp_path)
    _feed_all(stub, now, level=0.9)
    _feed_all(stub, now + 30, level=-0.9, tube=-40)
    rows = stub._chamber_monitor_view()["live"]
    assert all(row["tone"] == "warn" for row in rows)
    assert all(row["dev"] == "−1,80" for row in rows)


def test_finished_run_survives_late_export_and_restart(tmp_path):
    """Для выгрузки после выходных сохраняет один итог несмотря на новые показания и перезапуск."""
    stub, now = _recording(tmp_path)
    _feed_all(stub, now)
    _feed_all(stub, now + 30, level=0.7, tube=-40)
    stub._chamber_monitor_finish()
    original = stub._run_report_data()
    view = stub._chamber_monitor_view()
    session = stub._chamber_monitor_session
    before = (session.folder / "measurements.jsonl").read_bytes()
    _feed_all(stub, now + 100000, level=4.0, tube=85)
    assert stub._run_report_data() == original
    assert stub._chamber_monitor_view() == view
    assert (session.folder / "measurements.jsonl").read_bytes() == before
    again = _MonStub(tmp_path)
    again.__class__ = type("_RestoredReportStub", (AppControllerRunReportMixin, again.__class__), {})
    again._chamber_monitor_restore()
    assert again._chamber_monitor_view() == view
    assert again._run_report_data() == original


def test_active_history_does_not_drop_old_temperatures(tmp_path):
    """Чтобы длинный прогон не вытеснял холодные точки, сохраняет больше лимита живого буфера."""
    stub, now = _recording(tmp_path)
    stub.CHAMBER_MONITOR_KEEP = 2
    for index in range(4):
        _feed_all(stub, now + index * 30, level=index / 10, tube=25 + index * 10)
    for sa, *_ in BOARDS:
        with stub._mb_context(sa, notify=False):
            assert len(stub._chamber_monitor_history) >= 4
            assert stub._chamber_monitor_history[0]["tube"] == 250


def test_restart_resumes_the_same_files_and_marks_gap(tmp_path):
    """Для честного продолжения сохраняет прежние точки и отмечает перерыв в измерениях."""
    stub, now = _recording(tmp_path)
    _feed_all(stub, now)
    session = stub._chamber_monitor_session
    before = (session.folder / "measurements.jsonl").read_bytes()
    again = _MonStub(tmp_path)
    again._chamber_monitor_restore()
    assert again._chamber_monitor_suspended
    again._chamber_monitor_resume(session.folder)
    _feed_all(again, now + 30, level=0.7)
    assert again._chamber_monitor_session.folder == session.folder
    assert (session.folder / "measurements.jsonl").read_bytes().startswith(before)
    assert again._chamber_monitor_view()["gaps"] == 3


def test_missing_board_remains_in_view_and_in_report(tmp_path):
    """Чтобы потеря связи не превращалась в успешный итог, оставляет молчащую плату в результатах."""
    stub, now = _recording(tmp_path)
    _monitor_feed(stub, BOARDS[0][0], now, 25, 0.2, 15509)
    stub._chamber_monitor_tick(now, force=True)
    view = stub._chamber_monitor_view()
    assert len(view["live"]) == 3
    assert view["live"][1]["status"] == "нет свежих данных"
    report = stub._run_report_data()
    assert report["verdict"]["tone"] == "warn" and "не полная" in report["verdict"]["title"]


def test_storage_failure_is_visible(tmp_path, monkeypatch):
    """Чтобы ошибка диска не осталась незаметной, выводит её в монитор и итог проверки."""
    stub, now = _recording(tmp_path)
    _feed_all(stub, now)
    # Для отказа записи подменяет только файловую операцию, сохраняя работающий опрос.
    def fail(*args, **kwargs):
        """Для проверки отказа диска возвращает ошибку записи."""
        raise OSError("диск заполнен")
    monkeypatch.setattr(stub._chamber_monitor_session, "append", fail)
    _feed_all(stub, now + 30)
    assert "диск заполнен" in stub._chamber_monitor_view()["storageError"]
    assert stub._run_report_data()["verdict"]["tone"] == "warn"


def test_partial_record_does_not_destroy_following_measurements(tmp_path):
    """После обрыва записи восстанавливает целые строки и сохраняет следующее измерение отдельно."""
    session = MonitorSession.create(tmp_path, {"boards": [{"sa": None, "label": "плата"}]})
    sample = {"wall": 1, "level": 4, "tube": 250, "board": 250, "comp": 15500, "truth": 0}
    session.append("single", "плата", sample, {})
    with (session.folder / "measurements.jsonl").open("a", encoding="utf-8") as stream:
        stream.write('{"key":')
    session.append("single", "плата", dict(sample, level=7), {})
    restored = MonitorSession.load(session.folder)
    assert [point["level"] for point in restored.histories["single"]] == [4, 7]
    assert restored.metadata["damaged_records"] == 1


def test_shortened_plot_retains_peaks_and_latest_value():
    """Чтобы сокращение графика не скрыло нарушение допуска, сохраняет оба пика и последнюю точку."""
    points = [[index, 0.2] for index in range(50000)]
    points[12345][1] = 1.2
    points[40001][1] = -1.4
    reduced = thin_points(points)
    assert len(reduced) <= 1000
    assert max(p[1] for p in reduced) == 1.2
    assert min(p[1] for p in reduced) == -1.4
    assert reduced[-1] == points[-1]


def test_archive_contains_independent_measurements_and_frozen_result(tmp_path):
    """Для разбора без программы включает в архив исходную историю и сохранённый итог прогона."""
    from tests.test_multiboard import _with_control
    stub, now = _recording(tmp_path)
    stub = _with_control(stub)
    _feed_all(stub, now)
    stub._chamber_monitor_finish()
    stub._climate_save_report = lambda: ""
    bundle = stub._control_run_bundle()
    assert bundle
    with zipfile.ZipFile(bundle) as archive:
        for filename in ("measurements.csv", "measurements.jsonl", "session.json", "result.json"):
            assert "история_уровня/" + filename in archive.namelist()
        manifest = json.loads(archive.read("история_уровня/session.json").decode("utf-8"))
        assert manifest["active"] is False and len(manifest["boards"]) == 3


def test_report_does_not_pass_unvisited_temperatures(tmp_path):
    """Чтобы одна хорошая точка не подтверждала весь диапазон, отмечает непроверенные температуры."""
    stub, now = _recording(tmp_path)
    _feed_all(stub, now, level=0.1)
    report = stub._run_report_data()
    assert report["verdict"]["tone"] == "warn"
    assert "не все температуры" in report["verdict"]["title"]


def test_long_history_updates_totals_without_full_rescan(tmp_path, monkeypatch):
    """Чтобы долгий прогон не задерживал опрос CAN, при добавлении точки обрабатывает только её."""
    stub, now = _recording(tmp_path)
    history = [{"wall": i, "tube": 250, "level": 4, "truth": 0, "clock": "00:00"} for i in range(50000)]
    stub._chamber_monitor_summary("плата", history, None)
    calls = []
    original = stub._chamber_monitor_error
    # Для подсчёта работы отмечает каждую обработанную запись истории.
    def counted(sample):
        """Для проверки скорости считает обращения к сохранённым показаниям."""
        calls.append(sample)
        return original(sample)
    monkeypatch.setattr(stub, "_chamber_monitor_error", counted)
    history.append(dict(history[-1], wall=50000, level=12))
    _, _, worst = stub._chamber_monitor_summary("плата", history, None)
    assert len(calls) == 1
    assert worst[0] == 1.2
