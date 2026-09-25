"""Проверки единой таблицы окна параметров UDS.

Окно параметров объединяет одиночное и массовое чтение, запись и сверку в
одной таблице. Здесь закреплено, что таблица всегда показывает последнее
известное значение каждого параметра, правильно фильтруется, не теряет место
прокрутки при обновлении значений и не пропускает в прибор неверный ввод.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uds.option_values import INPUT_MODES, INPUT_VALUE
from uds.options_catalog import UDS_OPTIONS
from ui.qml.controller.options_mixin import AppControllerOptionsMixin
from ui.qml.options_table_model import OPTIONS_TABLE_FIELDS, OptionsTableModel


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _TableStub(AppControllerOptionsMixin):
    """Окно параметров без шины CAN: только таблица, кэш и выбор."""

    def __init__(self):
        self.optionsTableChanged = _Signal()
        self.optionSelectionChanged = _Signal()
        self.optionHistoryChanged = _Signal()
        self.infoMessage = _Signal()
        self._options_parameters = list(UDS_OPTIONS)
        self._options_values = {}
        self._options_filter_text = ""
        self._options_group_index = 0
        self._options_input_mode = INPUT_VALUE
        self._options_access_chain = False
        self._options_table_model = OptionsTableModel()
        self._selected_option_index = 0
        self._options_history = []
        self._options_history_next_id = 1
        self._options_write_verify = None
        self._options_target_node_sa = 0x2A
        self._service_security_unlocked = False
        self._service_access_target_sa = None
        self._service_access_busy = False
        self._refresh_options_selection(emit_signal=False)
        self._rebuild_options_table()

    @staticmethod
    def _uds_nrc_description(nrc: int) -> str:
        return {0x33: "Доступ безопасности запрещен"}.get(int(nrc), "Другой отказ")

    def rows(self):
        return self._options_table_model.rows()

    def row(self, did: int):
        return next(item for item in self.rows() if item["didInt"] == did)


def _group_index(stub: _TableStub, name: str) -> int:
    return stub._options_group_items().index(name)


# ------------------------------------------------------------------ кэш значений

def test_table_lists_every_parameter_as_unread_at_start():
    stub = _TableStub()
    assert len(stub.rows()) == len(UDS_OPTIONS)
    assert all(item["status"] == "Не читался" and item["value"] == "—" for item in stub.rows())


def test_read_result_appears_in_table_in_parameter_units():
    stub = _TableStub()
    stub._options_value_note_result(0x0065, "read", "single", True, b"\x0a", "ok")
    row = stub.row(0x0065)
    assert row["value"] == "10 с"
    assert row["status"] == "Прочитано"
    assert row["hasValue"] and row["time"]


def test_bulk_read_updates_the_same_table():
    """Массовое чтение пишет в ту же таблицу, что и одиночное: второй таблицы нет."""
    stub = _TableStub()
    stub._options_value_note_result(0x0066, "read", "bulk", True, b"\x1e", "ok")
    assert stub.row(0x0066)["value"] == "30 с"


def test_read_failure_keeps_old_value_and_explains_nrc():
    stub = _TableStub()
    stub._options_value_note_result(0x0065, "read", "single", True, b"\x0a", "ok")
    stub._options_value_note_result(0x0065, "read", "single", False, None, "Негативный ответ UDS (NRC=0x33)")
    row = stub.row(0x0065)
    assert row["status"] == "Ошибка чтения"
    assert row["value"] == "10 с"
    assert "Откройте доступ на запись" in row["details"]


def test_write_then_verify_marks_value_as_checked():
    stub = _TableStub()
    stub._options_value_note_result(0x0065, "write", "single_write", True, b"\x1e", "ok")
    assert stub.row(0x0065)["status"] == "Записано, сверка..."

    stub._options_write_verify = {"did": 0x0065, "bytes": b"\x1e", "target_sa": 0x2A}
    stub._finish_options_write_verify(True, b"\x1e", "ok")
    row = stub.row(0x0065)
    assert row["status"] == "Записано и проверено"
    assert row["value"] == "30 с"


def test_verify_mismatch_shows_what_device_keeps():
    stub = _TableStub()
    stub._options_write_verify = {"did": 0x0065, "bytes": b"\x1e", "target_sa": 0x2A}
    stub._finish_options_write_verify(True, b"\x06", "ok")
    row = stub.row(0x0065)
    assert row["status"] == "Не совпало"
    assert row["value"] == "6 с"


# ------------------------------------------------------------------ фильтр

def test_search_by_did_number():
    stub = _TableStub()
    stub._options_filter_text = "0065"
    stub._rebuild_options_table()
    assert [item["didInt"] for item in stub.rows()] == [0x0065]


def test_search_by_words_in_name():
    stub = _TableStub()
    stub._options_filter_text = "окно основного"
    stub._rebuild_options_table()
    assert [item["didInt"] for item in stub.rows()] == [0x0065]


def test_writable_group_shows_only_writable():
    stub = _TableStub()
    stub._options_group_index = _group_index(stub, stub.OPTIONS_GROUP_WRITABLE)
    stub._rebuild_options_table()
    assert stub.rows() and all(item["canWrite"] for item in stub.rows())


def test_group_filter_by_purpose():
    stub = _TableStub()
    stub._options_group_index = _group_index(stub, "Вид топлива")
    stub._rebuild_options_table()
    dids = {item["didInt"] for item in stub.rows()}
    assert 0x0066 in dids and 0x0035 in dids
    assert 0x0065 not in dids


def test_summary_counts_values_and_errors():
    stub = _TableStub()
    stub._options_value_note_result(0x0065, "read", "single", True, b"\x0a", "ok")
    stub._options_value_note_result(0x0066, "read", "single", False, None, "Таймаут")
    summary = stub._options_table_summary()
    assert f"Показано {len(UDS_OPTIONS)} из {len(UDS_OPTIONS)}" in summary
    assert "со значением 1" in summary
    assert "с ошибкой 1" in summary


# ------------------------------------------------------------------ модель и прокрутка

def test_value_update_changes_rows_without_reset():
    """Обновление значения не должно перестраивать таблицу: иначе прокрутка прыгает в начало."""
    stub = _TableStub()
    model = stub._options_table_model
    resets = []
    changes = []
    model.modelReset.connect(lambda: resets.append(1))
    model.dataChanged.connect(lambda first, last, roles=None: changes.append(first.row()))

    stub._options_value_note_result(0x0065, "read", "single", True, b"\x0a", "ok")

    assert resets == []
    assert changes == [next(i for i, item in enumerate(stub.rows()) if item["didInt"] == 0x0065)]


def test_filter_change_rebuilds_table():
    stub = _TableStub()
    model = stub._options_table_model
    resets = []
    model.modelReset.connect(lambda: resets.append(1))
    stub._options_filter_text = "0x0065"
    stub._rebuild_options_table()
    assert resets == [1]
    assert model.rowCount() == 1


def test_model_exposes_every_field_as_role():
    model = OptionsTableModel()
    names = {bytes(name).decode("ascii") for name in model.roleNames().values()}
    assert names == set(OPTIONS_TABLE_FIELDS)


# ------------------------------------------------------------------ выбранный параметр и запись

def test_selected_view_and_edit_text():
    stub = _TableStub()
    assert stub._options_select_did(0x0065)
    stub._options_value_note_result(0x0065, "read", "single", True, b"\x0a", "ok")
    view = stub._options_selected_view()
    assert view["didText"] == "0x0065"
    assert view["display"] == "10 с"
    assert view["editText"] == "10"
    assert view["canWrite"]
    assert "от 1 до 60" in view["inputHint"]


def test_preview_accepts_valid_and_rejects_out_of_range():
    stub = _TableStub()
    stub._options_select_did(0x0065)
    ok = stub._options_preview_input("30")
    assert ok["ok"] and "30 с" in ok["text"] and "1E" in ok["text"]
    bad = stub._options_preview_input("61")
    assert not bad["ok"] and "60" in bad["text"]


def test_selection_change_resets_input_mode_to_parameter_default():
    stub = _TableStub()
    stub._options_select_did(0xF195)
    assert stub._options_input_mode == "text"
    stub._options_select_did(0x0065)
    assert stub._options_input_mode == INPUT_VALUE
    assert [key for key, _title in INPUT_MODES][stub._options_selected_view()["inputModeIndex"]] == INPUT_VALUE


def test_read_only_parameter_has_no_write_preview():
    stub = _TableStub()
    stub._options_select_did(0x0035)
    assert stub._options_preview_input("1") == {"ok": False, "text": ""}


# ------------------------------------------------------------------ доступ на запись

def test_write_access_is_open_only_for_the_same_node():
    stub = _TableStub()
    assert not stub._options_write_access_open()
    stub._service_security_unlocked = True
    stub._service_access_target_sa = 0x2A
    assert stub._options_write_access_open()
    assert "0x2A" in stub._options_write_access_text()
    stub._service_access_target_sa = 0x10
    assert not stub._options_write_access_open()
    assert "другого узла" in stub._options_write_access_text()


def test_access_button_chains_session_then_security():
    stub = _TableStub()
    calls = []

    def fake_session():
        calls.append("session")
        stub._service_access_busy = True

    stub.applySelectedServiceSession = fake_session
    stub.requestSecurityAccess = lambda: calls.append("security")
    stub._service_session_index_for_value = lambda value: 2
    stub._selected_service_session_index = 0

    assert stub._start_options_write_access()
    assert stub._selected_service_session_index == 2
    stub._continue_options_access_after_session()
    stub._continue_options_access_after_session()
    assert calls == ["session", "security"], "доступ запрашивается ровно один раз после сессии"


def test_access_chain_is_dropped_when_session_is_refused():
    stub = _TableStub()
    stub.applySelectedServiceSession = lambda: None
    stub._service_session_index_for_value = lambda value: 2
    stub._selected_service_session_index = 0
    assert not stub._start_options_write_access()
    assert stub._options_access_chain is False


# ------------------------------------------------------------------ выгрузка

def test_export_writes_shown_rows(tmp_path, monkeypatch):
    stub = _TableStub()
    stub._options_value_note_result(0x0065, "read", "single", True, b"\x0a", "ok")
    stub._options_filter_text = "окно"
    stub._rebuild_options_table()
    monkeypatch.setattr(stub, "_options_export_directory", lambda: tmp_path)
    stub._resolve_options_target_sa = lambda: 0x2A

    path = stub._options_export_csv()

    assert path.name.startswith("options_SA2A_")
    with path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.reader(file, delimiter=";"))
    assert rows[0][:5] == ["DID", "Параметр", "Группа", "Доступ", "Значение"]
    exported = {row[0]: row for row in rows[1:]}
    assert exported["0x0065"][4] == "10 с"
    assert exported["0x0065"][7] == "0A"


@pytest.mark.parametrize("did", [item.did for item in UDS_OPTIONS])
def test_every_parameter_row_is_built(did):
    stub = _TableStub()
    row = stub.row(did)
    assert set(row) == set(OPTIONS_TABLE_FIELDS)
