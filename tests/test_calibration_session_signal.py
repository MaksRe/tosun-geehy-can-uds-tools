"""Проверка уведомления о готовности сессии калибровки.

ЧТО БЫЛО СЛОМАНО
Запись параметров в прибор разрешает только запущенный сценарий калибровки.
Признак готовности сессии менялся простым присваиванием, и окна об этом не
узнавали. В разделе вида топлива предупреждение «запись закрыта» оставалось
висеть после запуска калибровки, кнопки сохранения так и не становились
доступными, хотя обмен с прибором уже шёл. Оператор видел живые показания и не
мог ничего сохранить.

Эти тесты закрепляют, что изменение признака рассылает уведомление, а повторная
установка того же значения лишних уведомлений не шлёт.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller.calibration_mixin import AppControllerCalibrationMixin
from ui.qml.controller.media_wizard_mixin import AppControllerMediaWizardMixin


class _Signal:
    """Заглушка сигнала Qt: считает вызовы вместо реальной рассылки."""

    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _SessionStub(AppControllerCalibrationMixin, AppControllerMediaWizardMixin):
    """Минимальный носитель признака готовности сессии без Qt и без CAN."""

    def __init__(self):
        self.calibrationStateChanged = _Signal()
        self._calibration_session_ready = False
        self._calibration_active = False


def test_setting_ready_notifies_windows():
    """Смена признака обязана рассылать уведомление, иначе окна не обновятся."""
    stub = _SessionStub()

    stub._set_calibration_session_ready(True)

    assert stub._calibration_session_ready is True
    assert stub.calibrationStateChanged.count == 1


def test_setting_the_same_value_does_not_notify():
    """Повторная установка того же значения лишних уведомлений не шлёт."""
    stub = _SessionStub()

    stub._set_calibration_session_ready(True)
    stub._set_calibration_session_ready(True)
    stub._set_calibration_session_ready(True)

    assert stub.calibrationStateChanged.count == 1


def test_write_access_follows_the_session():
    """Разрешение на запись обязано включаться вместе с готовой сессией."""
    stub = _SessionStub()
    assert not stub._media_wizard_write_allowed()

    stub._calibration_active = True
    assert not stub._media_wizard_write_allowed(), "одного запуска мало, сессия ещё не готова"

    stub._set_calibration_session_ready(True)
    assert stub._media_wizard_write_allowed()


def test_stopping_calibration_closes_write_access():
    """Остановка сценария снова закрывает запись, иначе оператор решит, что она открыта."""
    stub = _SessionStub()
    stub._calibration_active = True
    stub._set_calibration_session_ready(True)
    assert stub._media_wizard_write_allowed()

    stub._set_calibration_session_ready(False)
    assert not stub._media_wizard_write_allowed()
    assert stub.calibrationStateChanged.count == 2
