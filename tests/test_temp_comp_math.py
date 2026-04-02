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
