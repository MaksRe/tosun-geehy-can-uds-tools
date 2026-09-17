"""Проверки мастера калибровки контура вида топлива.

Живое показание плоского конденсатора это единственный способ понять, что
конденсатор погружён и число устоялось. Если оно замирает после неудачной
попытки снять точку, оператор видит старое значение и снимает точку вслепую,
а на экране кнопка обновления при этом выглядит включённой.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml.controller.media_wizard_mixin import AppControllerMediaWizardMixin
from uds.data_identifiers import UdsData


class _Signal:
    """Заглушка сигнала Qt: считает вызовы вместо реальной рассылки."""

    def __init__(self):
        self.count = 0

    def emit(self, *args):
        self.count += 1


class _FakeTimer:
    """Таймер Qt без Qt: помнит, запущен ли он и с каким интервалом."""

    def __init__(self):
        self.running = False
        self.interval = None

    def start(self, interval=None):
        self.running = True
        self.interval = interval

    def stop(self):
        self.running = False


class _WizardStub(AppControllerMediaWizardMixin):
    """Логика мастера без Qt и без CAN: запросы только записываются."""

    def __init__(self):
        self.mediaWizardChanged = _Signal()
        self._media_wizard_watching = False
        self._media_wizard_busy = False
        self._media_wizard_action = ""
        self._media_wizard_status = ""
        self._media_wizard_status_color = ""
        self._media_wizard_pending = None
        self._media_wizard_samples = []
        self._media_wizard_live_raw = None
        self._media_wizard_live_spread = None
        self._media_wizard_air = None
        self._media_wizard_cal = None
        self._media_wizard_enabled = None
        self._media_wizard_written = None
        self._media_wizard_gap_timer = _FakeTimer()
        self._media_wizard_timeout_timer = _FakeTimer()
        # Калибровка запущена: иначе мастер не пустит к снятию точки.
        self._calibration_active = True
        self._calibration_session_ready = True
        self.requests = []

    def _media_wizard_request(self, action, var, value=None):
        self.requests.append((action, int(var.pid) & 0xFFFF, value))
        self._media_wizard_pending = (action, var, value)
        return True

    # Учёт свежести проверяется отдельно, здесь он не мешает.
    def _live_note_value(self, key, value):
        pass

    def _live_age_due(self, key):
        return False


def test_live_readings_continue_after_a_failed_point():
    """Ошибка при снятии точки не должна останавливать обновление отсчётов."""
    stub = _WizardStub()
    stub._media_wizard_watching = True
    stub._media_wizard_capture("air")

    # Показание гуляет сильнее допуска: мастер отказывается писать такую точку.
    stub._media_wizard_samples = [1000, 1200] + [1100] * (stub.MEDIA_WIZARD_SAMPLES - 2)
    stub._media_wizard_apply_series()

    assert stub._media_wizard_busy is False
    assert "разброс" in stub._media_wizard_status
    assert stub._media_wizard_gap_timer.running, "живое показание обязано продолжиться"
    assert stub._media_wizard_gap_timer.interval == stub.MEDIA_WIZARD_WATCH_GAP_MS


def test_live_readings_stay_stopped_when_the_operator_turned_them_off():
    stub = _WizardStub()
    stub._media_wizard_watching = False
    stub._media_wizard_busy = True
    stub._media_wizard_finish("Готово.", stub.MEDIA_WIZARD_COLOR_OK)

    assert stub._media_wizard_gap_timer.running is False


def test_resumed_watch_asks_the_device_again():
    """После паузы наблюдение шлёт очередной запрос, а не молчит."""
    stub = _WizardStub()
    stub._media_wizard_watching = True
    stub._media_wizard_busy = True
    stub._media_wizard_finish("Прибор отказал.", stub.MEDIA_WIZARD_COLOR_BAD)
    stub.requests.clear()

    stub._on_media_wizard_gap_timeout()

    assert stub.requests == [("watch", int(UdsData.fuel_media_flatcap_raw.pid) & 0xFFFF, None)]
