"""Проверки логики окна «Проверка прибора».

Окно переводит числа телеметрии в короткий вердикт для оператора. Ошибка в
пороге или в разборе ответа означает, что исправный прибор объявят бракованным
или наоборот. Тесты ниже закрепляют пороги и разбор кадра.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller.diagnostics_mixin import AppControllerDiagnosticsMixin as Diag


class _FakeSignal:
    """Заглушка сигнала Qt: считает вызовы вместо реальной рассылки."""

    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _FakeTimer:
    """Заглушка QTimer: запоминает состояние вместо работы с циклом событий."""

    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self, *args):
        self.started += 1

    def stop(self):
        self.stopped += 1


class _DiagnosticsStub(Diag):
    """Минимальный носитель логики диагностики без Qt и без CAN."""

    def __init__(self):
        self.diagnosticsChanged = _FakeSignal()
        self._diagnostics_gap_timer = _FakeTimer()
        self._diagnostics_timeout_timer = _FakeTimer()
        self._diagnostics_running = True
        self._diagnostics_status = ""
        self._diagnostics_values = {}
        self._diagnostics_missing = set()
        self._diagnostics_queue = []
        self._diagnostics_pending = None
        self._diagnostics_cycles_done = 0
        self._diagnostics_counter_prev = {}
        self._diagnostics_counter_growing = {}
        self._diagnostics_counter_delta = {}
        self._diagnostics_j1939_raw = None
        self._diagnostics_j1939_seen_s = None
        self._diagnostics_rows = []
        self._diagnostics_summary_text = ""
        self._diagnostics_summary_color = Diag.DIAGNOSTICS_COLOR_IDLE

    def _is_calibration_response_identifier(self, identifier: int) -> bool:
        """В тестах любой кадр считается пришедшим от опрашиваемого прибора."""
        return True

    def _resolve_calibration_target_sa(self) -> int:
        """В тестах проверяется прибор с адресом 0x00."""
        return 0x00


def _verdict(result) -> str:
    """Возвращает только текст вердикта из тройки (вердикт, цвет, подсказка)."""
    return result[0]


def _color(result) -> str:
    """Возвращает только цвет из тройки (вердикт, цвет, подсказка)."""
    return result[1]


def test_signed_conversion_for_two_bytes():
    """Температура и асимметрия приходят знаковыми, старший бит должен давать минус."""
    assert Diag._diagnostics_to_signed(0x0000, 2) == 0
    assert Diag._diagnostics_to_signed(0x7FFF, 2) == 32767
    assert Diag._diagnostics_to_signed(0x8000, 2) == -32768
    assert Diag._diagnostics_to_signed(0xFFFF, 2) == -1
    assert Diag._diagnostics_to_signed(0xFFFF, 1) == -1


@pytest.mark.parametrize(
    "spread, expected_color",
    [
        (0, Diag.DIAGNOSTICS_COLOR_OK),
        (12, Diag.DIAGNOSTICS_COLOR_OK),
        (24, Diag.DIAGNOSTICS_COLOR_OK),
        (25, Diag.DIAGNOSTICS_COLOR_WARN),
        (48, Diag.DIAGNOSTICS_COLOR_WARN),
        (49, Diag.DIAGNOSTICS_COLOR_BAD),
    ],
)
def test_spread_thresholds(spread, expected_color):
    """Границы дрожания измерения не должны сдвигаться незаметно."""
    assert _color(Diag._diagnostics_spread_verdict(spread)) == expected_color


def test_spread_without_value_is_neutral():
    """Пока значение не прочитано, вердикта быть не должно."""
    assert _color(Diag._diagnostics_spread_verdict(None)) == Diag.DIAGNOSTICS_COLOR_IDLE


@pytest.mark.parametrize(
    "delta, expected_color",
    [
        (0, Diag.DIAGNOSTICS_COLOR_OK),
        (-20, Diag.DIAGNOSTICS_COLOR_OK),
        (21, Diag.DIAGNOSTICS_COLOR_WARN),
        (-60, Diag.DIAGNOSTICS_COLOR_WARN),
        (61, Diag.DIAGNOSTICS_COLOR_BAD),
    ],
)
def test_half_delta_thresholds(delta, expected_color):
    """Асимметрия оценивается по модулю: знак говорит лишь о том, какая половина длиннее."""
    assert _color(Diag._diagnostics_half_delta_verdict(delta)) == expected_color


def test_period_inside_calibration_range_is_normal():
    """Период между границами калибровки означает исправный контур уровня."""
    stub = _DiagnosticsStub()
    assert _color(stub._diagnostics_period_verdict(1500, 1000, 2000)) == Diag.DIAGNOSTICS_COLOR_OK


def test_period_far_below_range_looks_like_broken_wire():
    """Период сильно ниже нуля шкалы это обрыв, а не пустой бак."""
    stub = _DiagnosticsStub()
    assert _color(stub._diagnostics_period_verdict(500, 1000, 2000)) == Diag.DIAGNOSTICS_COLOR_BAD


def test_period_marker_of_failure_is_reported_as_failure():
    """Прошивка отдаёт 0xFFFF вместо измерения, это отказ контура."""
    stub = _DiagnosticsStub()
    assert _color(stub._diagnostics_period_verdict(0xFFFF, 1000, 2000)) == Diag.DIAGNOSTICS_COLOR_BAD


def test_period_without_calibration_is_warning_not_failure():
    """Без границ калибровки период оценить нельзя, но прибор не сломан."""
    stub = _DiagnosticsStub()
    assert _color(stub._diagnostics_period_verdict(1500, None, None)) == Diag.DIAGNOSTICS_COLOR_WARN


@pytest.mark.parametrize(
    "state, expected_color",
    [
        (0x00, Diag.DIAGNOSTICS_COLOR_IDLE),
        (0x01, Diag.DIAGNOSTICS_COLOR_OK),
        (0x04, Diag.DIAGNOSTICS_COLOR_WARN),
        (0x02, Diag.DIAGNOSTICS_COLOR_BAD),
        (0x08, Diag.DIAGNOSTICS_COLOR_BAD),
        (0x0F, Diag.DIAGNOSTICS_COLOR_BAD),
    ],
)
def test_media_state_bits_priority(state, expected_color):
    """Отказ и устаревшие данные важнее признака активности, их нельзя перекрывать."""
    stub = _DiagnosticsStub()
    assert _color(stub._diagnostics_media_state_verdict(state)) == expected_color


def test_media_ratio_outside_corridor_is_failure():
    """Коэффициент среды вне заданного коридора означает неверную калибровку контура."""
    stub = _DiagnosticsStub()
    assert _color(stub._diagnostics_rf_verdict(1500, 800, 1200)) == Diag.DIAGNOSTICS_COLOR_BAD
    assert _color(stub._diagnostics_rf_verdict(1100, 800, 1200)) == Diag.DIAGNOSTICS_COLOR_OK


def test_media_ratio_of_one_is_neutral():
    """Единица означает, что шкала не растянута, это не заслуга и не проблема."""
    stub = _DiagnosticsStub()
    assert _color(stub._diagnostics_rf_verdict(1000, 800, 1200)) == Diag.DIAGNOSTICS_COLOR_IDLE


@pytest.mark.parametrize(
    "temperature_x10, expected_color",
    [
        (250, Diag.DIAGNOSTICS_COLOR_OK),
        (-399, Diag.DIAGNOSTICS_COLOR_OK),
        (799, Diag.DIAGNOSTICS_COLOR_OK),
        (-400, Diag.DIAGNOSTICS_COLOR_BAD),
        (800, Diag.DIAGNOSTICS_COLOR_BAD),
    ],
)
def test_temperature_edges_are_treated_as_sensor_fault(temperature_x10, expected_color):
    """Упор в край таблицы NTC означает обрыв или замыкание датчика."""
    stub = _DiagnosticsStub()
    assert _color(stub._diagnostics_temperature_verdict(temperature_x10)) == expected_color


def _read_answer_frame(did: int, data_bytes: list[int]) -> list[int]:
    """Собирает одиночный кадр ISO-TP с положительным ответом на чтение DID."""
    body = [0x62, (did >> 8) & 0xFF, did & 0xFF] + list(data_bytes)
    frame = [len(body)] + body
    return frame + [0xFF] * (8 - len(frame))


def test_frame_parsing_stores_unsigned_value():
    """Ответ на чтение периода должен попасть в таблицу как есть."""
    stub = _DiagnosticsStub()
    var = Diag._diagnostics_cycle_vars(stub)[0]
    stub._diagnostics_pending = var

    # 1234 в порядке байтов прошивки: младший байт первым.
    stub._handle_diagnostics_frame(0x18DAF101, _read_answer_frame(0x0014, [0xD2, 0x04]))

    assert stub._diagnostics_values["cur_period"] == 1234
    assert stub._diagnostics_pending is None


def test_frame_parsing_applies_sign_for_temperature():
    """Отрицательная температура не должна превращаться в 6553.5 градуса."""
    stub = _DiagnosticsStub()
    pending = [item for item in Diag._diagnostics_cycle_vars(stub) if item[0] == "fuel_temp"][0]
    stub._diagnostics_pending = pending

    # -1 в дополнительном коде для двух байт.
    stub._handle_diagnostics_frame(0x18DAF101, _read_answer_frame(0x0019, [0xFF, 0xFF]))

    assert stub._diagnostics_values["fuel_temp"] == -1


def test_frame_with_other_did_is_ignored():
    """Ответ на чужой запрос не должен подменять ожидаемое значение."""
    stub = _DiagnosticsStub()
    pending = [item for item in Diag._diagnostics_cycle_vars(stub) if item[0] == "cur_period"][0]
    stub._diagnostics_pending = pending

    stub._handle_diagnostics_frame(0x18DAF101, _read_answer_frame(0x0018, [0x10, 0x00]))

    assert "cur_period" not in stub._diagnostics_values
    assert stub._diagnostics_pending is pending


def test_negative_answer_marks_parameter_as_missing():
    """Отказ прибора по DID не должен останавливать проверку остальных величин."""
    stub = _DiagnosticsStub()
    pending = [item for item in Diag._diagnostics_cycle_vars(stub) if item[0] == "media_rf"][0]
    stub._diagnostics_pending = pending

    stub._handle_diagnostics_frame(0x18DAF101, [0x03, 0x7F, 0x22, 0x31, 0xFF, 0xFF, 0xFF, 0xFF])

    assert "media_rf" in stub._diagnostics_missing
    assert stub._diagnostics_pending is None
    assert stub._diagnostics_gap_timer.started == 1


def test_counter_growth_is_detected_between_cycles():
    """Дребезг виден не значением счётчика, а его ростом между кругами опроса."""
    stub = _DiagnosticsStub()
    pending = [item for item in Diag._diagnostics_cycle_vars(stub) if item[0] == "main_overrun"][0]

    stub._diagnostics_pending = pending
    stub._handle_diagnostics_frame(0x18DAF101, _read_answer_frame(0x0040, [0x0A, 0x00]))
    assert "main_overrun" not in stub._diagnostics_counter_growing

    stub._diagnostics_pending = pending
    stub._handle_diagnostics_frame(0x18DAF101, _read_answer_frame(0x0040, [0x0A, 0x00]))
    assert stub._diagnostics_counter_growing["main_overrun"] is False

    stub._diagnostics_pending = pending
    stub._handle_diagnostics_frame(0x18DAF101, _read_answer_frame(0x0040, [0x0B, 0x00]))
    assert stub._diagnostics_counter_growing["main_overrun"] is True

    verdict = stub._diagnostics_counter_verdict("main_overrun", "Дребезг есть", "подсказка")
    assert _verdict(verdict) == "Дребезг есть"
    assert _color(verdict) == Diag.DIAGNOSTICS_COLOR_WARN


def test_summary_reports_worst_verdict_of_the_table():
    """Общий итог должен показывать худшее из найденного, а не среднее по прибору."""
    stub = _DiagnosticsStub()
    rows = [
        Diag._diagnostics_row("Группа", "Хорошо", "1", "", "Норма", Diag.DIAGNOSTICS_COLOR_OK, ""),
        Diag._diagnostics_row("Группа", "Внимание", "2", "", "Внимание", Diag.DIAGNOSTICS_COLOR_WARN, ""),
        Diag._diagnostics_row("Группа", "Отказ", "3", "", "Плохо", Diag.DIAGNOSTICS_COLOR_BAD, ""),
    ]
    stub._diagnostics_values = {"cur_period": 1}
    stub._rebuild_diagnostics_summary(rows)

    assert stub._diagnostics_summary_color == Diag.DIAGNOSTICS_COLOR_BAD
    assert "Отказ" in stub._diagnostics_summary_text


def test_enabled_media_correction_without_calibration_is_a_failure():
    """Включённая поправка на несуществующей калибровке искажает уровень, это отказ настройки."""
    stub = _DiagnosticsStub()
    stub._diagnostics_values = {
        "media_enable": 1,
        "media_air": 0,
        "media_cal": 0,
        "media_raw": 5000,
    }
    stub._rebuild_diagnostics_rows()

    row = [item for item in stub._diagnostics_rows if item["label"] == "Поправка по виду топлива"][0]
    assert row["color"] == Diag.DIAGNOSTICS_COLOR_BAD


class _FakeIdentifier:
    """Заглушка разобранного J1939-идентификатора."""

    def __init__(self, pgn: int, src: int):
        self.pgn = pgn
        self.src = src


def _level_row(stub: _DiagnosticsStub, label: str) -> dict:
    """Возвращает строку таблицы об уровне топлива по её подписи."""
    stub._rebuild_diagnostics_rows()
    return [row for row in stub._diagnostics_rows if row["label"] == label][0]


def test_bus_level_is_taken_from_pgn_fefc_second_byte():
    """Уровень в шине лежит во втором байте PGN 0xFEFC с шагом 0,4 процента."""
    stub = _DiagnosticsStub()
    stub._diagnostics_values = {"raw_level": 472}

    stub._handle_diagnostics_j1939_frame(_FakeIdentifier(0xFEFC, 0x00), [0xFF, 118, 0xFF, 0xFF])

    assert stub._diagnostics_j1939_raw == 118
    assert abs(stub._diagnostics_j1939_percent() - 47.2) < 0.001

    row = _level_row(stub, "Уровень в шине (J1939)")
    assert row["value"] == "47.2 %"
    assert row["color"] == Diag.DIAGNOSTICS_COLOR_OK


def test_bus_level_far_from_uds_answer_is_a_failure():
    """Если в шину уходит не то, что прибор отвечает на запрос, это ошибка передачи."""
    stub = _DiagnosticsStub()
    stub._diagnostics_values = {"raw_level": 200}

    stub._handle_diagnostics_j1939_frame(_FakeIdentifier(0xFEFC, 0x00), [0xFF, 118, 0xFF, 0xFF])

    row = _level_row(stub, "Уровень в шине (J1939)")
    assert row["color"] == Diag.DIAGNOSTICS_COLOR_BAD


def test_bus_level_marker_of_no_data_is_reported():
    """Значения 0xFE и 0xFF в J1939 означают «нет данных», а не 101 процент."""
    stub = _DiagnosticsStub()
    stub._handle_diagnostics_j1939_frame(_FakeIdentifier(0xFEFC, 0x00), [0xFF, 0xFF, 0xFF, 0xFF])

    assert stub._diagnostics_j1939_percent() is None
    row = _level_row(stub, "Уровень в шине (J1939)")
    assert row["color"] == Diag.DIAGNOSTICS_COLOR_BAD


def test_missing_bus_frames_are_reported_while_polling():
    """Отсутствие широковещательных кадров тоже неисправность: технике нечего читать."""
    stub = _DiagnosticsStub()
    row = _level_row(stub, "Уровень в шине (J1939)")

    assert row["color"] == Diag.DIAGNOSTICS_COLOR_WARN
    assert row["value"] == "-"


def test_frames_from_other_nodes_and_other_pgn_are_ignored():
    """Чужой узел или другой PGN не должны подменять уровень проверяемого прибора."""
    stub = _DiagnosticsStub()

    stub._handle_diagnostics_j1939_frame(_FakeIdentifier(0xFEFC, 0x2A), [0xFF, 100, 0xFF, 0xFF])
    stub._handle_diagnostics_j1939_frame(_FakeIdentifier(0xFDA2, 0x00), [0xFF, 100, 0xFF, 0xFF])

    assert stub._diagnostics_j1939_raw is None


def test_level_from_period_shows_contribution_of_corrections():
    """Расчёт из периода нужен, чтобы видеть, насколько поправки сдвинули уровень."""
    stub = _DiagnosticsStub()
    stub._diagnostics_values = {
        "cur_period": 7100,
        "empty_period": 4820,
        "full_period": 9640,
        "raw_level": 500,
    }

    assert abs(stub._diagnostics_period_percent() - 47.3) < 0.05

    row = _level_row(stub, "Уровень из периода")
    assert row["value"] == "47.3 %"
    # Ответ прибора 50.0 %, голый пересчёт 47.3 %, значит поправки дали +2.7 %.
    assert "+2.7" in row["detail"]


def test_counter_detail_shows_growth_per_cycle():
    """Во второй строке значения счётчика показывается прирост, а не само число."""
    stub = _DiagnosticsStub()
    pending = [item for item in Diag._diagnostics_cycle_vars(stub) if item[0] == "main_overrun"][0]

    stub._diagnostics_pending = pending
    stub._handle_diagnostics_frame(0x18DAF101, _read_answer_frame(0x0040, [0x64, 0x00]))
    stub._diagnostics_pending = pending
    stub._handle_diagnostics_frame(0x18DAF101, _read_answer_frame(0x0040, [0x6E, 0x00]))

    assert stub._diagnostics_counter_detail("main_overrun") == "+10 за круг опроса"


def test_rows_cover_all_three_blocks_of_the_device():
    """Таблица должна показывать оба контура и температуру, иначе проверка неполная."""
    stub = _DiagnosticsStub()
    stub._rebuild_diagnostics_rows()

    groups = {row["group"] for row in stub._diagnostics_rows}
    assert groups == {"Контур уровня топлива", "Контур вида топлива", "Температура"}
