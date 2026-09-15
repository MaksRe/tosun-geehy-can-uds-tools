"""Проверки раздела прогона в климатической камере.

Прогон длится часами и не переделывается. Если точка запишется с чужой
пометкой, потеряется при сохранении или расчёт запустится на неполных данных и
промолчит, весь выезд в камеру придётся повторять.

Тесты закрепляют: точка усредняется по нескольким замерам; журнал читается
обратно без потерь; расчёт отказывается работать молча и называет причину.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_fit
from ui.qml.controller.chamber_mixin import AppControllerChamberMixin


class _Signal:
    """Заглушка сигнала Qt: считает вызовы вместо реальной рассылки."""

    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _ChamberStub(AppControllerChamberMixin):
    """Носитель логики прогона без Qt и без CAN."""

    def __init__(self):
        self.chamberChanged = _Signal()
        self._chamber_label = ""
        self._chamber_points = []
        self._chamber_busy = False
        self._chamber_status = ""
        self._chamber_status_color = ""
        self._chamber_report = []
        self._chamber_file_path = ""
        self._chamber_samples = []
        self._chamber_samples_left = 0
        self._chamber_sample = {}
        self._chamber_pending = None
        self._chamber_queue = []
        self._chamber_extend_liquid = False
        self._chamber_span_main = None
        self._chamber_span_media = None
        self._chamber_rehearsal = False
        self._profile_status = ""
        self._profile_status_color = ""

    # Профиль в этих проверках подменён: важно, что расчёт до него доходит.
    def _profile_apply_chamber_format(self, payload):
        self.applied = payload
        return True

    def _profile_calc_crc(self):
        return 0x1234

    def _profile_set_status(self, text, color):
        self._profile_status = text
        self._profile_status_color = color


def _full_run_points() -> list[dict]:
    """Полный прогон: в каждом узле две ёмкости и оба состояния трубки."""
    points = []
    for node in chamber_fit.NODES_X10:
        for note, capacitance in (("0 пФ", 0.0), ("120 пФ", 120.0)):
            points.append({
                "time": "12:00:00", "note": note,
                "main": int(round(4820 + 40.9 * capacitance)), "media": 2400,
                "fuel_temp_x10": node, "board_temp_x10": node, "rehearsal": False,
            })
        for note, immersion in ((chamber_fit.AIR_NOTE, 0.0), (chamber_fit.LIQUID_NOTE, 1.0)):
            points.append({
                "time": "12:00:00", "note": note,
                "main": int(round(4820 + 40.9 * (60.0 + 60.0 * immersion))),
                "media": int(round(4820 + 40.9 * (30.0 + 30.0 * immersion))),
                "fuel_temp_x10": node, "board_temp_x10": node, "rehearsal": False,
            })
    return points


def test_point_is_the_average_of_several_samples():
    """Одна точка это среднее нескольких замеров: одиночный замер слишком шумный."""
    stub = _ChamberStub()
    stub._chamber_label = "300 пФ"
    stub._chamber_samples = [
        {"main": 7100, "media": 2400, "fuel_temp": 250, "board_temp": 250},
        {"main": 7104, "media": 2402, "fuel_temp": 250, "board_temp": 250},
        {"main": 7102, "media": 2401, "fuel_temp": 250, "board_temp": 250},
    ]
    stub._chamber_store_point()

    assert len(stub._chamber_points) == 1
    point = stub._chamber_points[0]
    assert point["main"] == 7102
    assert point["media"] == 2401
    assert point["note"] == "300 пФ"


def test_point_without_period_is_not_stored():
    """Без периода точка бесполезна, и записывать её нельзя даже как частичную."""
    stub = _ChamberStub()
    stub._chamber_label = "воздух"
    stub._chamber_samples = [{"media": 2400, "board_temp": 250}]
    stub._chamber_store_point()

    assert stub._chamber_points == []
    assert "не записана" in stub._chamber_status


def test_point_far_from_the_grid_is_stored_with_a_warning():
    """Точку между узлами записываем, но сразу говорим, что в расчёт она не пойдёт."""
    stub = _ChamberStub()
    stub._chamber_label = "300 пФ"
    stub._chamber_samples = [{"main": 7100, "media": 2400, "fuel_temp": 380, "board_temp": 380}]
    stub._chamber_store_point()

    assert len(stub._chamber_points) == 1
    assert "далеко от узлов" in stub._chamber_status


# ------------------------------------------------------------------ сам замер: запросы и ответы

class _FakeTimer:
    def __init__(self):
        self.active = False

    def start(self, *args):
        self.active = True

    def stop(self):
        self.active = False

    def isActive(self):
        return self.active


class _FakeRead:
    def __init__(self):
        self.sent = []

    def read_data_by_identifier(self, identifier, var):
        self.sent.append(var)
        return True


class _FakeCan:
    is_connect = True
    is_trace = True


class _CaptureStub(_ChamberStub):
    """Замер целиком: запрос, ответ прибора, пауза, следующий запрос."""

    def __init__(self):
        super().__init__()
        self.infoMessage = _Signal()
        self._can = _FakeCan()
        self._chamber_read_service = _FakeRead()
        self._chamber_gap_timer = _FakeTimer()
        self._chamber_timeout_timer = _FakeTimer()
        self._chamber_attempt = 0
        self._chamber_label = "проба на столе"

    def _build_calibration_tx_identifier(self):
        return 0x18DA6AF1

    def _is_calibration_response_identifier(self, identifier):
        return True


# Что прибор отвечает на каждую величину точки: периоды и температура -40 °C.
_DEVICE_VALUES = {"main": 13141, "media": 4672, "fuel_temp": -400, "board_temp": -400}


def _answer(stub):
    """Прибор отвечает на последний запрос, затем проходит пауза."""
    key, var, _signed = stub._chamber_pending
    size = int(var.size)
    raw = _DEVICE_VALUES[key] & ((1 << (8 * size)) - 1)
    did = int(var.pid)
    payload = [3 + size, 0x62, (did >> 8) & 0xFF, did & 0xFF] + list(raw.to_bytes(size, "little"))
    stub._chamber_handle = stub._handle_chamber_frame(0x18DAF16A, (payload + [0xFF] * 8)[:8])

    before = len(stub._chamber_read_service.sent)
    stub._on_chamber_gap_timeout()
    if stub._chamber_busy and len(stub._chamber_read_service.sent) == before:
        # Повтор закончен: пауза между повторами, затем первый запрос следующего.
        stub._on_chamber_gap_timeout()


def test_capture_finishes_the_point_after_all_samples():
    """Раньше пауза после последнего чтения повтора запускала тот же повтор заново.

    Точка не заканчивалась никогда: на пробной калибровке замер 15 секунд
    показывал «осталось повторов: 5», и этап не проходил.
    """
    stub = _CaptureStub()
    assert stub._chamber_capture_point()

    reads_per_sample = len(stub._chamber_vars())
    for _step in range(stub.CHAMBER_SAMPLES * reads_per_sample):
        assert stub._chamber_busy
        _answer(stub)

    assert not stub._chamber_busy
    assert len(stub._chamber_read_service.sent) == stub.CHAMBER_SAMPLES * reads_per_sample
    assert len(stub._chamber_points) == 1
    point = stub._chamber_points[0]
    assert point["main"] == 13141
    assert point["board_temp_x10"] == -400


def test_status_counts_the_samples_down():
    stub = _CaptureStub()
    stub._chamber_capture_point()
    for _step in range(len(stub._chamber_vars())):
        _answer(stub)
    assert "осталось повторов: 4" in stub._chamber_status


def test_lost_request_is_repeated_before_the_point_is_abandoned():
    """Прибор теряет запрос, если в тот же миг пришёл чужой: один такой случай не повод бросать точку."""
    stub = _CaptureStub()
    stub._chamber_capture_point()
    first = stub._chamber_read_service.sent[-1]

    for _attempt in range(stub.CHAMBER_RETRY_LIMIT):
        stub._on_chamber_timeout()
        assert stub._chamber_busy
        stub._on_chamber_gap_timeout()
        assert stub._chamber_read_service.sent[-1] is first

    stub._on_chamber_timeout()
    assert not stub._chamber_busy
    assert "повторов" in stub._chamber_status


def test_answer_after_a_repeat_continues_the_point():
    stub = _CaptureStub()
    stub._chamber_capture_point()
    stub._on_chamber_timeout()
    stub._on_chamber_gap_timeout()
    _answer(stub)
    assert stub._chamber_busy
    assert stub._chamber_attempt == 0
    assert len(stub._chamber_read_service.sent) == 3


def test_refusal_of_another_service_does_not_break_the_point():
    """Отказ на запись или смену сессии к чтению замера не относится."""
    stub = _CaptureStub()
    stub._chamber_capture_point()
    stub._handle_chamber_frame(0x18DAF16A, [0x03, 0x7F, 0x2E, 0x33, 0xFF, 0xFF, 0xFF, 0xFF])
    assert stub._chamber_busy
    assert stub._chamber_pending is not None


def test_last_point_can_be_taken_back():
    """Пометку легко перепутать, поэтому последнюю точку надо уметь убрать."""
    stub = _ChamberStub()
    stub._chamber_points = _full_run_points()
    before = len(stub._chamber_points)

    assert stub._chamber_remove_last_point()
    assert len(stub._chamber_points) == before - 1


def test_log_round_trip_keeps_every_point(tmp_path: Path):
    """Прогон прерывают на перерыв, поэтому журнал обязан читаться обратно без потерь."""
    stub = _ChamberStub()
    stub._chamber_points = _full_run_points()
    path = tmp_path / "run.csv"

    assert stub._chamber_save_file(str(path))

    restored = _ChamberStub()
    assert restored._chamber_load_file(str(path))
    assert restored._chamber_points == stub._chamber_points


def test_alien_file_is_refused(tmp_path: Path):
    """Чужой файл не должен молча превращаться в пустой прогон."""
    path = tmp_path / "alien.csv"
    path.write_text("что-то;совсем;другое\n1;2;3\n", encoding="utf-8")

    stub = _ChamberStub()
    assert not stub._chamber_load_file(str(path))
    assert stub._chamber_points == []


def test_calculation_fills_the_profile_when_data_is_complete():
    """Полный прогон обязан посчитаться и сразу попасть в таблицы профиля."""
    stub = _ChamberStub()
    stub._chamber_points = _full_run_points()

    assert stub._chamber_compute_tables()
    assert stub._chamber_report == []
    assert "ступень_платы" in stub.applied
    assert "посчитаны" in stub._profile_status


def test_calculation_refuses_and_names_the_reason():
    """Без опорной точки расчёт обязан отказаться и сказать, чего не хватило."""
    stub = _ChamberStub()
    stub._chamber_points = [
        point for point in _full_run_points()
        if point["board_temp_x10"] != chamber_fit.REFERENCE_X10
    ]

    assert not stub._chamber_compute_tables()
    assert any("опорной точке" in item for item in stub._chamber_report)


def test_empty_run_is_refused():
    """Считать по пустому журналу нечего, и молчать об этом нельзя."""
    stub = _ChamberStub()
    assert not stub._chamber_compute_tables()
    assert "не снято" in stub._chamber_status


def test_coverage_shows_what_is_missing():
    """Сводка полноты обязана показывать, в каких узлах чего не хватает."""
    stub = _ChamberStub()
    stub._chamber_points = [
        point for point in _full_run_points()
        if point["board_temp_x10"] != chamber_fit.NODES_X10[-1]
    ]

    rows = stub._chamber_coverage_rows()
    assert len(rows) == len(chamber_fit.NODES_X10)
    assert all(row["capsOk"] and row["tubeOk"] for row in rows[:-1])
    assert not rows[-1]["capsOk"]
    assert not rows[-1]["tubeOk"]
    assert rows[-1]["tube"] == "нет обеих"


def test_coverage_tells_which_tube_state_is_missing():
    """Оператору важно знать не «нет данных», а какого именно состояния не хватает."""
    stub = _ChamberStub()
    stub._chamber_points = [
        point for point in _full_run_points()
        if point["note"] != chamber_fit.LIQUID_NOTE
    ]

    rows = stub._chamber_coverage_rows()
    assert all(row["tube"] == "нет погружённой" for row in rows)


def test_trial_point_keeps_device_temperature_and_is_marked():
    """Пробная точка берёт температуру из прибора: при пробной калибровке её задаёт эмуляция в прошивке."""
    stub = _ChamberStub()
    stub._chamber_label = "300 пФ"
    stub._chamber_rehearsal = True
    stub._chamber_samples = [{"main": 7100, "media": 2400, "fuel_temp": -400, "board_temp": -400}]
    stub._chamber_store_point()

    point = stub._chamber_points[0]
    assert point["fuel_temp_x10"] == -400
    assert point["board_temp_x10"] == -400
    assert point["rehearsal"] is True
    assert point["main"] == 7100


def test_rehearsal_point_is_marked_in_the_status():
    """Оператор должен видеть в строке хода работы, что это репетиция, а не настоящий замер."""
    stub = _ChamberStub()
    stub._chamber_label = "воздух"
    stub._chamber_rehearsal = True
    stub._chamber_samples = [{"main": 4820, "media": 2400, "fuel_temp": 250, "board_temp": 250}]
    stub._chamber_store_point()

    assert "Пробная" in stub._chamber_status


def test_rehearsal_mark_survives_the_file(tmp_path: Path):
    """Пометка репетиции обязана переживать сохранение: иначе журнал сойдёт за настоящий."""
    stub = _ChamberStub()
    stub._chamber_points = _full_run_points()
    stub._chamber_points[0]["rehearsal"] = True
    for point in stub._chamber_points[1:]:
        point["rehearsal"] = False

    path = tmp_path / "run.csv"
    assert stub._chamber_save_file(str(path))

    restored = _ChamberStub()
    assert restored._chamber_load_file(str(path))
    assert restored._chamber_points[0]["rehearsal"] is True
    assert all(not point["rehearsal"] for point in restored._chamber_points[1:])


def test_rehearsal_warning_is_first_in_the_report():
    """Предупреждение о репетиции обязано стоять первым: это важнее любых других замечаний."""
    stub = _ChamberStub()
    stub._chamber_points = _full_run_points()
    for point in stub._chamber_points:
        point["rehearsal"] = True

    assert stub._chamber_compute_tables()
    assert stub._chamber_report
    assert "пробной калибровки" in stub._chamber_report[0]
