"""Проверки связи при записи профиля и достоверного общего итога."""

import time

from tests.test_journal_assign_monitor import _mon_stub
from tests.test_multiboard import BOARDS, _stub
from tests.test_remote_monitor import _RemoteStub
from tests.test_chamber_auto import _ChainStub
from ui.qml import climate_scenario
from ui.qml.controller.run_report_mixin import AppControllerRunReportMixin


def test_profile_response_prevents_false_silence_alarm(tmp_path):
    """Чтобы пауза температур при сверке не выглядела обрывом, учитывает первый кадр ответа профиля."""
    stub = _RemoteStub(tmp_path)
    now = time.monotonic()
    stub._chamber_live_seen["main"] = now - 50
    stub._resolve_calibration_target_sa = lambda: 0x87
    stub._parse_calibration_response_identifier = lambda ident: (0xDA00, 0xF1, ident & 255)
    stub._remote_note_uds_response(0x18DAF187, [0x10, 31, 0x62, 0, 0x4D, 0, 0, 0])
    stub._remote_watch_device(now)
    assert not stub._remote_device_silent
    stub._remote_watch_device(now + 31)
    assert stub._remote_device_silent


def test_other_address_does_not_hide_real_silence(tmp_path):
    """Чтобы чужая плата не скрывала обрыв выбранной, проверяет адрес ответа перед отметкой связи."""
    stub = _RemoteStub(tmp_path)
    now = time.monotonic()
    stub._chamber_live_seen["main"] = now - 50
    stub._resolve_calibration_target_sa = lambda: 0x87
    stub._parse_calibration_response_identifier = lambda ident: (0xDA00, 0xF1, ident & 255)
    stub._remote_note_uds_response(0x18DAF188, [5, 0x62, 0, 0x3B, 250, 0, 0, 0])
    stub._remote_watch_device(now)
    assert stub._remote_device_silent


def test_any_participant_response_keeps_multi_device_connected(tmp_path):
    """Чтобы смена показанной платы не давала ложный обрыв, смотрит ответы всех участников."""
    stub = _RemoteStub(tmp_path)
    now = time.monotonic()
    stub._chamber_live_seen["main"] = now - 50
    stub._remote_multi = lambda: True
    stub._mb_polled_boards = lambda: [{"sa": 0x87}, {"sa": 0x88}]
    stub._mb_context_value = lambda sa, field: {"board_temp": now - 50}
    stub._mb_uds_seen = {0x88: now}
    stub._remote_watch_device(now)
    assert not stub._remote_device_silent


def test_broadcast_is_restored_only_after_all_profiles(tmp_path):
    """Чтобы рассылка не нагружала обмен таблицами, возвращает её после последней записи и сверки."""
    stub = _stub(tmp_path)
    sent = []
    stub._mb_quiet_on = True
    stub._mb_quiet_send = lambda enable_tx: sent.append(enable_tx) or True
    stub._chamber_auto_write = True
    for sa, *_ in BOARDS:
        with stub._mb_context(sa):
            stub._chamber_tables_complete = True

    def start(automatic=False):
        """Для проверки очереди начинает отдельную запись каждой платы."""
        stub._chamber_chain_stage = "write"
        stub._chamber_chain_steps = {"file": ""}
        return True

    stub._chamber_chain_start = start
    stub._climate_run_complete(" Камера остановлена.", stop=False)
    assert sent == [] and stub._mb_profiles_busy()
    now = time.monotonic()
    for _ in BOARDS:
        stub._mb_profile_tick(now)
        assert sent == []
        stub._chamber_chain_stage = ""
        stub._chamber_chain_steps = {"file": "ok"}
    stub._mb_profile_tick(now)
    assert sent == [True] and not stub._mb_profile_failures()


def test_profile_failure_makes_final_summary_bad(tmp_path):
    """Чтобы ошибка одной платы не давала зелёный общий итог, проверяет счётчик проблем и текст восстановления."""
    stub = _stub(tmp_path)
    now = time.monotonic()
    stub._climate_auto_finishing = True
    stub._climate_auto_finish_since = now - 100
    stub._climate_auto_finish_elapsed = 100
    stub._mb_profile_outcomes = {BOARDS[0][0]: False, BOARDS[1][0]: True, BOARDS[2][0]: True}
    events = []
    stub._climate_event = lambda text, level, **kwargs: events.append((level, text))
    stub._climate_auto_follow_finish(now)
    level, text = events[-1]
    assert level == "bad" and "Не подтверждена запись профилей: 0x80" in text
    assert "Проблем за прогон не было" not in text
    assert "повторите запись и сверку профиля" in text


def test_report_keeps_profile_failure_visible_during_board_training(tmp_path):
    """Чтобы скрытие процентов не скрывало сбой записи, оставляет ошибку профиля в PDF и сохранённом итоге."""
    stub = _mon_stub(tmp_path)
    stub.__class__ = type("FailedProfileReportStub", (AppControllerRunReportMixin, stub.__class__), {})
    stub._climate_scenario = climate_scenario.board_cycle_scenario()
    stub._mb_profile_outcomes = {BOARDS[0][0]: False}
    report = stub._run_report_data()
    assert report["verdict"]["tone"] == "bad" and "0x80" in report["verdict"]["title"]
    assert report["charts"] == []
    stub._run_report_frozen = report
    stub._mb_profile_outcomes = {BOARDS[0][0]: True}
    assert stub._run_report_data()["verdict"]["tone"] == "bad"


def test_successful_profiles_replace_waiting_status(tmp_path):
    """Чтобы после сверки окно не продолжало обещать запись, заменяет промежуточный статус итоговым."""
    stub = _stub(tmp_path)
    now = time.monotonic()
    stub._climate_auto_finishing = True
    stub._climate_auto_finish_since = now - 100
    stub._climate_auto_finish_elapsed = 100
    stub._mb_profile_outcomes = {sa: True for sa, *_ in BOARDS}
    stub._climate_auto_follow_finish(now)
    assert "Профили всех плат записаны, сверены и сохранены" in stub._climate_run_status


def test_manual_retry_updates_current_profile_outcome(tmp_path):
    """Чтобы удачная ручная запись снимала текущую ошибку, обновляет итог только нужной платы."""
    stub = _stub(tmp_path)
    sa = stub._mb_active_sa
    stub._mb_profile_outcomes = {sa: False}
    stub._mb_note_profile_result("Профиль записан, сверен и сохранён", True)
    assert not stub._mb_profile_failures()


def test_verification_failure_does_not_claim_write_was_interrupted(tmp_path):
    """Чтобы сообщение точно называло шаг сбоя, отличает передачу профиля от его последующей сверки."""
    stub = _ChainStub(tmp_path)
    stub._chamber_chain_fail("verify", "Не пришло продолжение ответа 0x004D")
    assert "Профиль отправлен, но сверка не завершена" in stub._chamber_chain_status
