from uds.services.read_data_by_id import ServiceReadDataById


def test_is_send_success_accepts_non_negative_codes():
    """Цель теста в проверке трактовки кодов send_async, затем он подтверждает, что неотрицательные коды считаются успешной отправкой."""
    assert ServiceReadDataById._is_send_success(0) is True
    assert ServiceReadDataById._is_send_success(5) is True
    assert ServiceReadDataById._is_send_success(1) is True


def test_is_send_success_rejects_none_and_negative_codes():
    """Цель теста в проверке ошибок отправки, затем он подтверждает отклонение None и отрицательных кодов."""
    assert ServiceReadDataById._is_send_success(None) is False
    assert ServiceReadDataById._is_send_success(-1) is False


def test_is_send_success_handles_non_integer_return_values():
    """Цель теста в проверке экзотических ответов драйвера, затем он подтверждает fallback-логику для bool-значений."""
    assert ServiceReadDataById._is_send_success(True) is True
    assert ServiceReadDataById._is_send_success(False) is False
