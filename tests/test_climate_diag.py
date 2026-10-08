"""Проверки журнала диагностики связи с климатической камерой.

Журнал нужен, чтобы проблему со связью можно было разобрать по файлу, не стоя
у камеры. Тесты закрепляют:
- обмены байтами видны в hex и тексте, с задержкой и итогом (ok, молчание, мусор...);
- по умолчанию обмены держит чёрный ящик и сбрасывает их в файл только вокруг
  ошибки, без повторов; первые обмены сеанса пишутся всегда; подробный режим пишет всё;
- счётчики считают ответы, молчания, мусор, отказы и задержку;
- начало сеанса пишет окружение и настройки, раз в минуту пишется сводка;
- отчёт содержит все разделы, журнал и чёрный ящик и сохраняется в файл;
- старые журналы удаляются, режим порта Moxa из реестра называется словами;
- раздел программы показывает диагностику, проверку связи и проверку режима Moxa.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_espec import _driver, _FakeEspec
from ui.qml.climate_chamber import ChamberLink, ChamberReading, EspecChamber
from ui.qml.climate_diag import (
    ChamberDiagLog,
    environment_info,
    hex_bytes,
    moxa_interface_text,
    moxa_registry_info,
    show_bytes,
)


class _Clock:
    """Модельное время для сводки раз в минуту."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _diag(tmp_path, clock=None):
    return ChamberDiagLog(tmp_path / "logs" / "chamber", monotonic=clock or time.monotonic)


def _file_text(diag) -> str:
    path = diag.file_path()
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_bytes_are_shown_as_text_and_hex():
    assert show_bytes(b"1,MON?\r\n") == "1,MON?\\r\\n"
    assert show_bytes(b"\x8f!") == "\\x8f!"
    assert hex_bytes(b"1,\r\n") == "31 2C 0D 0A"


def test_moxa_interface_codes():
    assert moxa_interface_text(0) == "RS-232"
    assert moxa_interface_text(2) == "RS-422"
    assert moxa_interface_text(3) == "RS-485 4W"
    assert moxa_interface_text(None) == "не задан"
    assert isinstance(moxa_registry_info(), list)


def test_environment_names_versions(tmp_path: Path):
    (tmp_path / ".build_version").write_text("1.0.13", encoding="utf-8")
    info = environment_info(tmp_path)
    assert info["версия программы"] == "1.0.13"
    assert info["python"] and info["pyserial"]


def test_exchanges_are_logged_with_latency_and_outcome(tmp_path: Path):
    diag = _diag(tmp_path)
    diag.session_start("ESPEC на COM2", {"настройки": {"espec_baud": 9600}})
    port = _FakeEspec()
    driver = _driver(port)
    driver.diag = diag
    driver.read()
    text = _file_text(diag)
    assert "подключение: ESPEC на COM2" in text and "espec_baud" in text
    # Начало сеанса пишется всегда: TX и RX с hex, задержкой и итогом.
    assert "[TX     ] COM5 8 байт: 1,MON?\\r\\n  |  31 2C 4D 4F 4E 3F 0D 0A" in text
    assert "итог ok: 24.8, STANDBY, 0\\r\\n" in text
    assert diag.stats["answers"] == 4 and diag.stats["exchanges"] == 4


def test_blackbox_goes_to_file_only_around_errors(tmp_path: Path):
    diag = _diag(tmp_path)
    port = _FakeEspec()
    driver = _driver(port)
    driver.diag = diag
    for _ in range(3):
        driver.read()
    # Без начала сеанса и подробного режима обмены в файл не идут.
    assert "[TX" not in _file_text(diag)
    port.silent = True
    try:
        driver.read()
    except Exception:  # noqa: BLE001
        pass
    text = _file_text(diag)
    assert "последние обмены перед ошибкой" in text
    assert "итог silence" in text and "камера молчит" in text
    assert diag.stats["silence"] == 1
    count_before = text.count("[TX")
    # Вторая ошибка не повторяет уже записанные обмены.
    try:
        driver.read()
    except Exception:  # noqa: BLE001
        pass
    assert _file_text(diag).count("[TX") == count_before + 1


def test_verbose_writes_every_exchange(tmp_path: Path):
    diag = _diag(tmp_path)
    diag.verbose = True
    port = _FakeEspec()
    driver = _driver(port)
    driver.diag = diag
    driver.read()
    driver.read()
    assert _file_text(diag).count("[TX") == len(port.sent)


def test_garbage_and_refusal_are_counted(tmp_path: Path):
    diag = _diag(tmp_path)
    port = _FakeEspec()
    driver = _driver(port)
    driver.diag = diag
    port.protect = True
    try:
        driver.set_setpoint(-40.0)
    except Exception:  # noqa: BLE001
        pass
    port.protect = False
    port.garbage = b"\x8f\xf3\x00\r\n"
    try:
        driver.read()
    except Exception:  # noqa: BLE001
        pass
    assert diag.stats["refused"] == 1 and diag.stats["garbage"] == 1
    text = _file_text(diag)
    assert "[REFUSE ]" in text and "PROTECT ON" in text
    assert "8F F3 00 0D 0A" in text
    assert "мусора 1" in diag.stats_text() and "отказов 1" in diag.stats_text()


def test_open_failure_is_logged(tmp_path: Path):
    diag = _diag(tmp_path)

    def factory(**kwargs):
        raise OSError("could not open port 'COM9': FileNotFoundError(2, 'x')")

    driver = EspecChamber("COM9", 9600, 1, serial_factory=factory, sleep=lambda s: None)
    driver.diag = diag
    try:
        driver.read()
    except Exception:  # noqa: BLE001
        pass
    text = _file_text(diag)
    assert "[OPEN   ] открываю COM9" in text and "COM9 не открылся: OSError" in text


def test_summary_once_a_minute(tmp_path: Path):
    clock = _Clock()
    diag = _diag(tmp_path, clock)
    diag.session_start("камера", {})
    diag.maybe_summary("в камере 20.0")
    clock.now += 61.0
    diag.maybe_summary("в камере 21.0")
    diag.maybe_summary("в камере 22.0")
    text = _file_text(diag)
    assert "в камере 20.0" not in text and text.count("[SUMMARY]") == 1 and "в камере 21.0" in text


def test_report_has_everything(tmp_path: Path):
    diag = _diag(tmp_path)
    port = _FakeEspec()
    driver = _driver(port)
    driver.diag = diag
    driver.read()
    path = diag.save_report({"Программа и окружение": {"python": "3.13"}, "COM-порты": [{"device": "COM2"}]})
    text = path.read_text(encoding="utf-8")
    for title in ("ОТЧЁТ ДИАГНОСТИКИ", "== Программа и окружение ==", "== COM-порты ==",
                  "== Статистика обмена", "== Журнал из памяти", "== Чёрный ящик"):
        assert title in text
    assert "1,MON?" in text and path.name.startswith("report_")
    assert diag.view()["report"] == str(path)


def test_old_logs_are_removed(tmp_path: Path):
    directory = tmp_path / "logs" / "chamber"
    directory.mkdir(parents=True)
    old = directory / "chamber_2020-01-01.log"
    fresh = directory / "chamber_2026-10-06.log"
    old.write_text("x", encoding="utf-8")
    fresh.write_text("x", encoding="utf-8")
    stamp = (datetime.now() - timedelta(days=40)).timestamp()
    os.utime(old, (stamp, stamp))
    ChamberDiagLog(directory)
    assert not old.exists() and fresh.exists()


def test_link_logs_transitions_commands_and_selftest(tmp_path: Path):
    import threading

    diag = _diag(tmp_path)
    states = []
    done = threading.Event()
    port = _FakeEspec()
    driver = _driver(port)

    def on_state(state):
        states.append(state)
        if state.get("kind") == "selftest":
            done.set()

    link = ChamberLink(driver, 60.0, on_state, diag=diag)
    link.command("selftest")
    assert done.wait(10.0)
    link.close()
    result = [state for state in states if state["kind"] == "selftest"][-1]
    assert result["ok"] is True and len(result["results"]) == len(EspecChamber.SELFTEST_QUERIES)
    assert result["results"][0]["query"] == "ROM?" and result["results"][0]["answer"] == "JMIC -S1.00"
    text = _file_text(diag)
    assert "[LINK   ] связь есть" in text
    assert "[CMD    ] selftest" in text and "итог: 10 из 10 запросов прошли" in text
    assert "[LINK   ] связь закрыта" in text


def test_lost_link_is_logged_once(tmp_path: Path):
    import threading

    diag = _diag(tmp_path)
    port = _FakeEspec()
    port.silent = True
    failures = []
    two = threading.Event()

    def on_state(state):
        if state.get("kind") == "reading" and not state.get("ok"):
            failures.append(state)
            if len(failures) >= 2:
                two.set()

    link = ChamberLink(_driver(port), 0.2, on_state, diag=diag)
    link.RECONNECT_PAUSE_S = 0.05
    assert two.wait(10.0)
    link.close()
    assert _file_text(diag).count("связь потеряна") == 1


# ------------------------------------------------------------------ раздел программы

def test_section_shows_diagnostics(tmp_path: Path):
    from tests.test_espec import _espec_stub

    stub = _espec_stub(tmp_path)
    stub._climate_diag_reset(tmp_path / "logs" / "chamber")
    stub._climate_moxa = [{"port": "COM2", "interface_code": 0, "interface": "RS-232", "espec_ok": False,
                           "values": {"SerInterface": 0}, "key": "HKLM\\x"}]
    stub._climate_ports = [{"device": "COM2", "description": "MOXA USB Serial Port", "moxa": True, "hwid": "MXUPORT"}]
    # Не подключена: порт «auto» - первый найденный Moxa, его режим и проверяется.
    stub._climate_link = None
    view = stub._climate_view()
    assert view["moxaCheck"]["ok"] is False and "RS-232" in view["moxaCheck"]["text"]
    stub._climate_moxa[0].update({"interface_code": 3, "interface": "RS-485 4W", "espec_ok": True})
    assert stub._climate_view()["moxaCheck"]["ok"] is True
    assert stub._climate_set("diag_verbose", True)
    assert stub._climate_diag.verbose is True
    assert "diag_verbose: False → True" in _file_text(stub._climate_diag)
    assert "stats" in view["diag"] and view["selftest"]["active"] is False


def test_selftest_result_is_explained_and_report_saved(tmp_path: Path):
    from tests.test_espec import _espec_stub

    stub = _espec_stub(tmp_path)
    stub._climate_diag_reset(tmp_path / "logs" / "chamber")
    assert stub._climate_selftest_start()
    assert stub._climate_link.commands[-1] == ("selftest", None)
    stub._climate_queue_state({"kind": "selftest", "ok": False, "done": True, "text": "прошли 1 из 2 запросов",
                               "results": [{"query": "MON?", "ok": True, "answer": "-39.8, CONSTANT, 0", "ms": 40},
                                           {"query": "TEMP?", "ok": False, "answer": "камера молчит", "ms": 2000}]})
    stub._climate_take_incoming(0.0)
    selftest = stub._climate_view()["selftest"]
    assert selftest["text"] == "Прошли 1 из 2 запросов."
    assert selftest["results"][0]["explain"] == "в камере -39,8 °C, постоянный режим, аварий нет"
    stub._climate_reading = ChamberReading(actual_c=-39.8, setpoint_c=-40.0, running=True, alarm=0)
    path = Path(stub._climate_save_report())
    text = path.read_text(encoding="utf-8")
    assert "== Настройки камеры ==" in text and "== Проверка связи (последняя) ==" in text
    assert "== Moxa в реестре Windows ==" in text and "в камере -39.8" in text
    assert "Отчёт диагностики сохранён" in stub._climate_command_status


# ------------------------------------------------------------------ флаги ошибок линии

def test_line_error_flags_are_named():
    from ui.qml.climate_chamber import line_error_names, serial_line_errors

    assert line_error_names(0x0008 | 0x0010) == ["FRAME (ошибка кадра: нет стоп-бита)", "BREAK (линия в «нуле» дольше кадра)"]
    assert line_error_names(0) == []
    # Заглушка без дескриптора Windows: флагов нет, связь не ломается.
    assert serial_line_errors(object()) == []


def test_silence_with_line_errors_points_to_receive_pair(tmp_path: Path, monkeypatch):
    import ui.qml.climate_chamber as chamber

    monkeypatch.setattr(chamber, "serial_line_errors", lambda port: ["FRAME (ошибка кадра: нет стоп-бита)"])
    diag = _diag(tmp_path)
    port = _FakeEspec()
    port.silent = True
    driver = _driver(port)
    driver.diag = diag
    try:
        driver.read()
        raise AssertionError("должна быть ошибка")
    except chamber.ChamberError as error:
        assert "ошибки линии" in str(error) and "клеммах 3 RxD+ и 4 RxD−" in str(error)
    text = _file_text(diag)
    assert "итог garbage, ошибки линии: FRAME" in text
    assert diag.stats["garbage"] == 1 and diag.stats["silence"] == 0
