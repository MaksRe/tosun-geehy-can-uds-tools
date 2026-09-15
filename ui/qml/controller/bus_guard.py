"""Кто сейчас ведёт обмен с прибором.

Прибор держит один канал ISO-TP: запрос, пришедший раньше ответа на прежний,
затирает его, и прежний остаётся без ответа. Поэтому фоновые опросы (текущий
период в калибровке, отсчёты пробной калибровки, состояние памяти, живое
показание вида топлива, сборщик) спрашивают здесь, свободна ли шина, и молчат,
если её занимает другой раздел или только что ушёл другой фоновый запрос.
"""

from __future__ import annotations

import time

# Сколько после фонового запроса не слать следующий: ответ прибора приходит за десятки миллисекунд.
BACKGROUND_GUARD_S = 0.08


def uds_exchange_busy(ctrl, ignore: tuple[str, ...] = ()) -> str:
    """Название раздела, который сейчас обменивается с прибором, или пустая строка."""
    def flag(name, default=False):
        return getattr(ctrl, name, default)

    sections = (
        ("options", bool(flag("_options_busy") or flag("_options_bulk_busy"))),
        ("profile", bool(flag("_profile_busy"))),
        ("chamber", bool(flag("_chamber_busy"))),
        ("trial", bool(flag("_trial_busy"))),
        ("media_wizard", bool(flag("_media_wizard_busy")) or flag("_media_wizard_pending", None) is not None),
        ("diagnostics", bool(flag("_diagnostics_running"))),
        ("calibration", bool(str(flag("_calibration_sequence_waiting_action", "") or ""))
         or bool(flag("_calibration_write_verify_pending", {}))
         or bool(flag("_calibration_restore_active"))
         or bool(flag("_calibration_dump_capture_active"))
         or bool(flag("_calibration_backup_all_nodes_active"))),
        ("source_address", bool(flag("_source_address_busy"))),
        ("programming", bool(flag("_programming_active"))),
        ("eeprom_commit", float(flag("_eeprom_commit_request_s", 0.0) or 0.0) > 0.0),
    )
    for name, busy in sections:
        if busy and name not in ignore:
            return name
    return ""


def note_background_request(ctrl):
    """Отмечает, что фоновый запрос только что ушёл в шину."""
    ctrl._uds_background_tx_s = time.monotonic()


def background_request_recent(ctrl, window_s: float = BACKGROUND_GUARD_S) -> bool:
    """Ушёл ли фоновый запрос так недавно, что ответ на него ещё в пути."""
    return time.monotonic() - float(getattr(ctrl, "_uds_background_tx_s", 0.0) or 0.0) < window_s
