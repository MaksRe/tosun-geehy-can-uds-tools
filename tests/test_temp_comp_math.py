from ui.qml.controller.calibration_mixin import AppControllerCalibrationMixin
import pytest


def test_c_trunc_div_truncates_towards_zero():
    """Цель теста в проверке C-подобного деления, затем он подтверждает усечение к нулю для отрицательных значений."""
    assert AppControllerCalibrationMixin._c_trunc_div(7, 3) == 2
    assert AppControllerCalibrationMixin._c_trunc_div(-7, 3) == -2
    assert AppControllerCalibrationMixin._c_trunc_div(7, -3) == -2
    assert AppControllerCalibrationMixin._c_trunc_div(-7, -3) == 2


def test_decode_signed_value_for_16bit():
    """Цель теста в проверке знаковой интерпретации DID, затем он валидирует sign-extension для 16 бит."""
    assert AppControllerCalibrationMixin._decode_signed_value(0x0000, 16) == 0
    assert AppControllerCalibrationMixin._decode_signed_value(0x7FFF, 16) == 32767
    assert AppControllerCalibrationMixin._decode_signed_value(0x8000, 16) == -32768
    assert AppControllerCalibrationMixin._decode_signed_value(0xFFFF, 16) == -1


def test_saturate_int16_limits_range():
    """Цель теста в проверке защиты от переполнения, затем он подтверждает ограничение диапазона int16."""
    assert AppControllerCalibrationMixin._saturate_int16(123) == 123
    assert AppControllerCalibrationMixin._saturate_int16(40000) == 32767
    assert AppControllerCalibrationMixin._saturate_int16(-40000) == -32768


def test_apply_temperature_compensation_model_linear_mode():
    """Цель теста в проверке базовой формулы линейной компенсации, затем он подтверждает расчет Pcomp по K1 и K0."""
    # Pcomp = raw - (k1*(T-20.0C)/1000) + k0
    # raw=1000, T=30.0C -> dT=100 (x10), k1=50 => delta=5, k0=10 => 1000-5+10=1005
    result = AppControllerCalibrationMixin._apply_temperature_compensation_model(
        raw_period=1000,
        temperature_x10=300,
        k1_x100=50,
        k0_count=10,
    )
    assert result == 1005


def test_resolve_zero_trim_write_value_accepts_dec_and_hex():
    """Цель теста в проверке ввода DID 0x002D, затем он подтверждает корректный разбор decimal и hex для записи."""
    assert AppControllerCalibrationMixin._resolve_calibration_zero_trim_write_value("123", None) == 123
    assert AppControllerCalibrationMixin._resolve_calibration_zero_trim_write_value("-12", None) == -12
    assert AppControllerCalibrationMixin._resolve_calibration_zero_trim_write_value("0x000A", None) == 10
    assert AppControllerCalibrationMixin._resolve_calibration_zero_trim_write_value("0xFFFE", None) == -2


def test_resolve_zero_trim_write_value_rejects_invalid_range_and_empty_without_fallback():
    """Цель теста в проверке валидации DID 0x002D, затем он подтверждает ошибки для выхода за диапазон и пустого ввода."""
    with pytest.raises(ValueError):
        AppControllerCalibrationMixin._resolve_calibration_zero_trim_write_value("65535", None)
    with pytest.raises(ValueError):
        AppControllerCalibrationMixin._resolve_calibration_zero_trim_write_value("-40000", None)
    with pytest.raises(ValueError):
        AppControllerCalibrationMixin._resolve_calibration_zero_trim_write_value("", None)


def test_calculate_zero_trim_adjustment_reaches_zero_for_positive_level():
    """Цель теста в проверке расчета подгонки 0%-смещения, затем он подтверждает компенсацию положительного остатка к нулю."""
    delta, target, residual = AppControllerCalibrationMixin._calculate_zero_trim_adjustment(
        span_count=2000,
        current_level_x10=180,
        current_zero_trim=0,
    )
    assert delta == -360
    assert target == -360
    assert residual == 0


def test_calculate_zero_trim_adjustment_reaches_zero_for_negative_level():
    """Цель теста в проверке расчета подгонки 0%-смещения, затем он подтверждает компенсацию отрицательного остатка к нулю."""
    delta, target, residual = AppControllerCalibrationMixin._calculate_zero_trim_adjustment(
        span_count=2000,
        current_level_x10=-250,
        current_zero_trim=100,
    )
    assert delta == 500
    assert target == 600
    assert residual == 0


def test_calculate_zero_trim_adjustment_accounts_for_saturation():
    """Цель теста в проверке насыщения int16, затем он подтверждает корректный расчет остатка при ограничении целевого значения."""
    delta, target, residual = AppControllerCalibrationMixin._calculate_zero_trim_adjustment(
        span_count=1000,
        current_level_x10=-1000,
        current_zero_trim=32760,
    )
    assert delta == 1000
    assert target == 32767
    assert residual == -993


class _FakeTimer:
    """Цель класса в подмене QTimer для unit-тестов, затем он сохраняет факт запуска и переданный интервал."""

    def __init__(self):
        """Цель конструктора в инициализации состояния таймера, затем он готовит поля для проверок в ассертах."""
        self.started = False
        self.last_interval = None

    def start(self, interval_ms):
        """Цель метода в имитации запуска таймера, затем он запоминает последний интервал."""
        self.started = True
        self.last_interval = int(interval_ms)


class _ZeroTrimVerifyTimeoutContext:
    """Цель класса в эмуляции контекста автопроверки zero trim, затем он собирает статусы и side-effect вызовы."""

    def __init__(self, *, retries_left: int, request_ok: bool):
        """Цель конструктора в подготовке сценария таймаута, затем он задает исходные флаги и заглушки."""
        self._calibration_temp_comp_zero_trim_verify_pending = True
        self._calibration_temp_comp_zero_trim_verify_retries_left = int(retries_left)
        self._calibration_temp_comp_zero_trim_verify_timeout_ms = 1500
        self._calibration_temp_comp_zero_trim_verify_timeout_timer = _FakeTimer()
        self._request_ok = bool(request_ok)
        self._request_count = 0
        self._status_calls = []
        self._last_report_kwargs = None
        self._reset_called = False
        self._logs = []
        self._calibration_temp_comp_zero_trim_count_current = 10
        self._calibration_temp_comp_zero_trim_count_next = 12
        self._calibration_temp_comp_zero_trim_residual_x10 = 15

    def _request_calibration_temp_comp_raw_level_read(self):
        """Цель метода в имитации повторного чтения DID 0x0018, затем он возвращает преднастроенный исход отправки."""
        self._request_count += 1
        return bool(self._request_ok)

    def _set_calibration_temp_comp_operation_status(self, text, **kwargs):
        """Цель метода в фиксации статуса операции, затем он складывает текст и параметры в список проверок."""
        self._status_calls.append({"text": str(text), **dict(kwargs)})

    def _append_log(self, text, color):
        """Цель метода в фиксации логов сценария, затем он сохраняет текст и цвет без зависимости от UI."""
        self._logs.append((str(text), color))

    def _set_calibration_temp_comp_zero_trim_last_report(self, **kwargs):
        """Цель метода в перехвате итогового отчета, затем он сохраняет аргументы для последующего ассерта."""
        self._last_report_kwargs = dict(kwargs)

    def _reset_calibration_temp_comp_zero_trim_verify_state(self):
        """Цель метода в имитации сброса состояния автопроверки, затем он выставляет конечные флаги завершения."""
        self._reset_called = True
        self._calibration_temp_comp_zero_trim_verify_pending = False
        self._calibration_temp_comp_zero_trim_verify_retries_left = 0


class _ZeroTrimReadStepTimeoutContext:
    """Цель класса в эмуляции таймаута шага чтения DID, затем он проверяет корректный reset и статус оператора."""

    def __init__(self):
        """Цель конструктора в подготовке активной операции, затем он инициализирует перехваты вызовов."""
        self._calibration_temp_comp_zero_trim_air_zero_adjust_active = True
        self._reset_called = False
        self._status_calls = []
        self._logs = []

    def _reset_calibration_temp_comp_zero_trim_air_zero_adjust_state(self):
        """Цель метода в фиксации reset после таймаута, затем он переводит флаг активности в false."""
        self._reset_called = True
        self._calibration_temp_comp_zero_trim_air_zero_adjust_active = False

    def _set_calibration_temp_comp_operation_status(self, text, **kwargs):
        """Цель метода в перехвате статуса операции, затем он сохраняет все аргументы для проверок."""
        self._status_calls.append({"text": str(text), **dict(kwargs)})

    def _append_log(self, text, color):
        """Цель метода в фиксации диагностического лога, затем он сохраняет текст и цвет сообщения."""
        self._logs.append((str(text), color))


def test_zero_trim_verify_timeout_requests_retry_when_retries_left():
    """Цель теста в проверке повторного запроса DID 0x0018, затем он подтверждает запуск таймера и промежуточный статус."""
    ctx = _ZeroTrimVerifyTimeoutContext(retries_left=1, request_ok=True)
    AppControllerCalibrationMixin._on_calibration_temp_comp_zero_trim_verify_timeout(ctx)

    assert ctx._request_count == 1
    assert ctx._calibration_temp_comp_zero_trim_verify_retries_left == 0
    assert ctx._calibration_temp_comp_zero_trim_verify_timeout_timer.started is True
    assert ctx._reset_called is False
    assert ctx._last_report_kwargs is None
    assert len(ctx._status_calls) > 0
    assert "повторный запрос" in ctx._status_calls[-1]["text"]
    assert ctx._status_calls[-1]["busy"] is True


def test_zero_trim_verify_timeout_finishes_when_no_retries_left():
    """Цель теста в проверке финальной ветки таймаута, затем он подтверждает запись отчета и сброс состояния."""
    ctx = _ZeroTrimVerifyTimeoutContext(retries_left=0, request_ok=False)
    AppControllerCalibrationMixin._on_calibration_temp_comp_zero_trim_verify_timeout(ctx)

    assert ctx._request_count == 0
    assert ctx._reset_called is True
    assert ctx._last_report_kwargs is not None
    assert ctx._last_report_kwargs["status_text"] == "таймаут автопроверки, нужен повтор"
    assert ctx._last_report_kwargs["write_csv"] is True
    assert len(ctx._status_calls) > 0
    assert "не завершена" in ctx._status_calls[-1]["text"]
    assert ctx._status_calls[-1]["busy"] is False


def test_zero_trim_verify_timeout_finishes_when_retry_send_failed():
    """Цель теста в проверке отказа повторной отправки DID 0x0018, затем он подтверждает переход в финальный статус ошибки."""
    ctx = _ZeroTrimVerifyTimeoutContext(retries_left=1, request_ok=False)
    AppControllerCalibrationMixin._on_calibration_temp_comp_zero_trim_verify_timeout(ctx)

    assert ctx._request_count == 1
    assert ctx._reset_called is True
    assert ctx._last_report_kwargs is not None
    assert ctx._last_report_kwargs["status_text"] == "таймаут автопроверки, нужен повтор"
    assert len(ctx._status_calls) > 0
    assert "не завершена" in ctx._status_calls[-1]["text"]


def test_zero_trim_read_step_timeout_sets_error_status_and_resets_state():
    """Цель теста в проверке таймаута чтения DID для автоподгонки, затем он подтверждает reset и понятный текст статуса."""
    ctx = _ZeroTrimReadStepTimeoutContext()
    AppControllerCalibrationMixin._on_calibration_temp_comp_zero_trim_air_zero_adjust_timeout(ctx)

    assert ctx._reset_called is True
    assert len(ctx._status_calls) > 0
    assert "остановлена по таймауту" in ctx._status_calls[-1]["text"]
    assert ctx._status_calls[-1]["busy"] is False


def test_classify_zero_trim_verification_result_success_on_tolerance_border():
    """Цель теста в проверке границы допуска, затем он подтверждает статус success при остатке ровно в tolerance."""
    result = AppControllerCalibrationMixin._classify_zero_trim_verification_result(
        residual_x10=10,
        tolerance_x10=10,
        repeat_threshold_x10=25,
    )
    assert result == "success"


def test_classify_zero_trim_verification_result_repeat_between_thresholds():
    """Цель теста в проверке промежуточной зоны, затем он подтверждает статус repeat между tolerance и repeat-threshold."""
    result = AppControllerCalibrationMixin._classify_zero_trim_verification_result(
        residual_x10=-18,
        tolerance_x10=10,
        repeat_threshold_x10=25,
    )
    assert result == "repeat"


def test_classify_zero_trim_verification_result_mechanics_above_repeat_threshold():
    """Цель теста в проверке большого остатка, затем он подтверждает статус mechanics при выходе за repeat-threshold."""
    result = AppControllerCalibrationMixin._classify_zero_trim_verification_result(
        residual_x10=30,
        tolerance_x10=10,
        repeat_threshold_x10=25,
    )
    assert result == "mechanics"
