from __future__ import annotations

from app_can.CanDevice import CanDevice
from uds.uds_identifiers import UdsIdentifiers


class ServiceCommunicationControl:
    """Цель класса в формировании и проверке UDS Service 0x28, затем он управляет прикладной коммуникацией ECU."""

    SID = 0x28
    POSITIVE_SID = SID + 0x40

    def __init__(self):
        self._pending_control_type = 0
        self._pending_communication_type = 0
        self._pending_suppress_positive = False

    @staticmethod
    def _is_send_success(ret) -> bool:
        """Цель функции в единообразной проверке send_async, затем она считает успешным любой неотрицательный код."""
        if ret is None:
            return False
        if isinstance(ret, bool):
            return bool(ret)
        try:
            return int(ret) >= 0
        except Exception:
            return bool(ret)

    def request(
        self,
        *,
        control_type: int,
        communication_type: int,
        suppress_positive_response: bool = False,
        tx_identifier: int | None = None,
    ) -> bool:
        """Цель функции в отправке запроса 0x28, затем она запоминает параметры для валидации ответа."""
        normalized_control_type = int(control_type) & 0x7F
        normalized_communication_type = int(communication_type) & 0xFF
        normalized_spr = bool(suppress_positive_response)
        sub_function = normalized_control_type | (0x80 if normalized_spr else 0x00)

        self._pending_control_type = normalized_control_type
        self._pending_communication_type = normalized_communication_type
        self._pending_suppress_positive = normalized_spr

        identifier = int(UdsIdentifiers.tx.identifier) if tx_identifier is None else int(tx_identifier)
        ret = CanDevice.instance().send_async(
            identifier,
            8,
            [0x03, int(self.SID) & 0xFF, sub_function, normalized_communication_type, 0xFF, 0xFF, 0xFF, 0xFF],
        )
        return self._is_send_success(ret)

    @staticmethod
    def parse_single_frame_uds_payload(payload: list[int]) -> list[int]:
        """Цель функции в извлечении полезной UDS-части из ISO-TP SF, затем она возвращает список байт UDS."""
        if payload is None or len(payload) <= 1:
            return []
        pci_type = (int(payload[0]) >> 4) & 0x0F
        if pci_type != 0x0:
            return []
        sf_len = int(payload[0]) & 0x0F
        if sf_len <= 0:
            return []
        end_index = min(1 + sf_len, len(payload))
        return [int(item) & 0xFF for item in payload[1:end_index]]

    def is_expected_positive_response(self, uds_payload: list[int]) -> bool:
        """Цель функции в проверке позитивного ответа 0x68, затем она сверяет подфункцию с отправленным запросом."""
        if uds_payload is None or len(uds_payload) < 2:
            return False
        sid = int(uds_payload[0]) & 0xFF
        sub_function = int(uds_payload[1]) & 0x7F
        return sid == int(self.POSITIVE_SID) and sub_function == int(self._pending_control_type)

    @property
    def pending_control_type(self) -> int:
        return int(self._pending_control_type) & 0x7F

    @property
    def pending_communication_type(self) -> int:
        return int(self._pending_communication_type) & 0xFF

    @property
    def pending_suppress_positive(self) -> bool:
        return bool(self._pending_suppress_positive)
