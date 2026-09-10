"""Проверки температурного профиля.

Прибор применяет таблицы профиля только если записанная сумма сходится с той,
которую он считает сам. Значит программа обязана считать её ровно так же и
подавать данные в том же порядке. Расхождение приведёт к тому, что правильно
снятый в камере профиль прибор молча отвергнет.

Тесты закрепляют три вещи: алгоритм суммы, порядок данных и то, что файл профиля
читается обратно без потерь.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller.profile_mixin import PROFILE_POINTS, AppControllerProfileMixin


class _Signal:
    """Заглушка сигнала Qt: считает вызовы вместо реальной рассылки."""

    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _ProfileStub(AppControllerProfileMixin):
    """Носитель логики профиля без Qt и без CAN."""

    def __init__(self):
        self.profileChanged = _Signal()
        self._options_busy = False
        self._init_profile_state()


def test_crc_matches_the_standard_algorithm():
    """Расчёт обязан совпадать с общепринятым: для «123456789» сумма равна 0x29B1."""
    assert AppControllerProfileMixin._profile_crc16(b"123456789") == 0x29B1


def test_default_profile_crc_matches_firmware():
    """Сумма профиля по умолчанию должна совпасть с той, что считает прошивка.

    Число 0xC4BA получено скриптом прошивки tools/verify_profile_crc.py для
    состояния «сетка узлов заполнена, таблицы пустые». Расхождение означало бы,
    что программа и прибор считают сумму по-разному, и записанный профиль был бы
    отвергнут.
    """
    stub = _ProfileStub()
    assert stub._profile_calc_crc() == 0xC4BA


def test_every_value_changes_the_crc():
    """Изменение любого значения обязано менять сумму, иначе она ничего не защищает."""
    stub = _ProfileStub()
    base = stub._profile_calc_crc()

    seen = set()
    for name, _did, _title, width in stub.PROFILE_TABLES:
        for index in range(PROFILE_POINTS * width):
            original = stub._profile_values[name][index]
            stub._profile_values[name][index] = original + 1
            seen.add(stub._profile_calc_crc())
            stub._profile_values[name][index] = original

    assert base not in seen, "нашлось значение, которое не влияет на сумму"


def test_write_is_refused_while_tables_are_empty():
    """Пустой профиль писать бессмысленно, и программа обязана это сказать."""
    stub = _ProfileStub()
    problems = stub._profile_validate()
    assert any("пустые" in item for item in problems)


def test_write_is_refused_when_nodes_do_not_grow():
    """Сетка узлов обязана возрастать: иначе прибор таблицы просто не применит."""
    stub = _ProfileStub()
    stub._profile_values["board_main"][0] = 5
    stub._profile_values["nodes"] = [-400, -200, 0, 0, 500, 700, 850]

    problems = stub._profile_validate()
    assert any("возрастать" in item for item in problems)


def test_file_round_trip_keeps_every_value(tmp_path: Path):
    """Файл профиля это откат, поэтому он обязан читаться обратно без потерь."""
    stub = _ProfileStub()
    stub._profile_values["board_main"] = list(range(-7, 7))
    stub._profile_values["tube_air_main"] = [4700, 4740, 4780, 4820, 4870, 4910, 4940]
    stub._profile_values["tube_full_main"] = [9500, 9560, 9600, 9640, 9700, 9750, 9790]
    saved_crc = stub._profile_calc_crc()

    path = tmp_path / "profile.json"
    assert stub._profile_save_file(str(path))

    restored = _ProfileStub()
    assert restored._profile_load_file(str(path))
    assert restored._profile_values == stub._profile_values
    assert restored._profile_calc_crc() == saved_crc


def test_chamber_result_file_is_accepted(tmp_path: Path):
    """Файл расчёта по журналу камеры должен загружаться напрямую, без правки руками."""
    payload = {
        "узлы_x10": [-400, -200, 0, 250, 500, 700, 850],
        "ступень_платы": [[10, -2576], [8, -1732], [4, -1016], [0, 0], [-3, 1062], [-7, 1836], [-9, 2468]],
        "ступень_трубки": {
            "air_main": [7220, 7238, 7254, 7274, 7295, 7311, 7323],
            "full_main": [9542, 9599, 9656, 9728, 9800, 9856, 9899],
            "air_media": [6047, 6048, 6047, 6047, 6047, 6047, 6047],
            "full_media": [7273, 7275, 7274, 7274, 7274, 7274, 7274],
        },
        "контрольная_сумма": 0,
        "замечания": [],
    }
    path = tmp_path / "tables.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    stub = _ProfileStub()
    assert stub._profile_load_file(str(path))
    assert stub._profile_values["board_main"][0] == 10
    assert stub._profile_values["board_main"][1] == -2576
    assert stub._profile_values["tube_full_main"][-1] == 9899
    assert not stub._profile_validate()


def test_unknown_file_is_rejected(tmp_path: Path):
    """Чужой файл не должен молча превращаться в пустой профиль."""
    path = tmp_path / "alien.json"
    path.write_text(json.dumps({"что-то": 1}), encoding="utf-8")

    stub = _ProfileStub()
    assert not stub._profile_load_file(str(path))


def test_next_step_is_not_sent_inside_the_previous_answer():
    """Следующий запрос обязан уходить отдельным тактом, а не изнутри ответа.

    Ответ приходит внутрь завершения предыдущей операции окна параметров, и всё,
    что отправлено оттуда, тут же затирается уборкой состояния обмена. Из-за
    этого второй запрос уходил в шину, ответа на него никто не ждал, и чтение
    профиля висело вечно.
    """
    stub = _ProfileStub()
    sent: list[str] = []
    stub._start_options_read_request = (
        lambda parameter, request_origin, append_history: sent.append(request_origin) or True
    )

    assert stub._profile_read_from_device()
    assert len(sent) == 1, "первый запрос уходит сразу"

    before = len(stub._profile_queue)
    stub._handle_profile_options_result(
        success=True, request_origin=sent[0], pending_action="read",
        pending_did=0x004B, value_bytes=bytes(14), message="ok")

    assert len(sent) == 1, "второй запрос не должен уходить изнутри ответа"
    assert len(stub._profile_queue) == before - 1, "очередь обязана продвинуться"
    assert stub._profile_busy, "очередь не закончена, окно остаётся занятым"

    # Продолжение приходит отдельным тактом. В проверках цикла событий нет,
    # поэтому вызываем обработчик таймера вручную.
    stub._on_profile_step_timeout()
    assert len(sent) == 2, "следующий запрос уходит отдельным тактом"


def test_failed_step_stops_the_queue():
    """Отказ прибора обязан прерывать очередь, а не оставлять окно в ожидании."""
    stub = _ProfileStub()
    stub._start_options_read_request = lambda *args, **kwargs: True

    assert stub._profile_read_from_device()
    stub._handle_profile_options_result(
        success=False, request_origin="profile_nodes", pending_action="read",
        pending_did=0x004B, value_bytes=None, message="таймаут")

    assert not stub._profile_busy
    assert stub._profile_queue == []

    # Даже если такт продолжения уже был назначен, он ничего не отправит.
    stub._on_profile_step_timeout()
    assert stub._profile_queue == []


def test_write_order_puts_checksum_last():
    """Сумма пишется последней: пока её нет, недописанный профиль в работу не попадёт."""
    stub = _ProfileStub()
    stub._profile_values["board_main"][0] = 5

    sent: list[str] = []
    stub._start_options_write_multiframe_request = (
        lambda parameter, payload, request_origin, append_history: sent.append(request_origin) or True
    )
    stub._start_options_read_request = lambda *args, **kwargs: True

    assert stub._profile_write_to_device()
    # Очередь отправляется по одной операции, поэтому проверяем её состав целиком.
    order = [name for name, _did, _payload in stub._profile_queue]
    assert order[-1] == "crc"
    assert order[-2] == "generation"
    assert order[-3] == "algorithm"
    assert order[0] == "nodes"


def test_generation_grows_on_every_write():
    """Номер поколения растёт при каждой записи: по нему видно, какой набор в приборе."""
    stub = _ProfileStub()
    stub._profile_values["board_main"][0] = 5
    stub._start_options_write_multiframe_request = lambda *args, **kwargs: True
    stub._start_options_read_request = lambda *args, **kwargs: True

    before = stub._profile_generation
    stub._profile_write_to_device()
    assert stub._profile_generation == before + 1


@pytest.mark.parametrize("text", ["abc", "", "1.5", "40000"])
def test_bad_cell_input_is_refused(text: str):
    """Нецелое или слишком большое значение не должно попасть в таблицу."""
    stub = _ProfileStub()
    original = list(stub._profile_values["board_main"])
    assert not stub._profile_set_cell(1, 0, text)
    assert stub._profile_values["board_main"] == original


def test_cell_edit_changes_the_value_and_the_crc():
    """Правка ячейки меняет значение и пересчитывает сумму."""
    stub = _ProfileStub()
    before = stub._profile_calc_crc()
    assert stub._profile_set_cell(1, 3, "-42")
    assert stub._profile_values["board_main"][6] == -42
    assert stub._profile_calc_crc() != before
