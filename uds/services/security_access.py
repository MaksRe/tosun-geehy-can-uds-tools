from app_can.CanDevice import CanDevice
from uds.uds_identifiers import UdsIdentifiers


class ServiceSecurityAccess:
    def __init__(self):
        self._seed: int = 0
        self._key: int = 0
        self._access = False
        self._seed_byte_order = "little-endian"

    @property
    def access(self) -> bool:
        return self._access

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def key(self) -> int:
        return self._key

    @property
    def seed_byte_order(self) -> str:
        return self._seed_byte_order

    def _calc_key(self) -> int:
        return ((self._seed ^ 0xAA55) | self._seed) & 0xFFFF

    def request_seed(self, tx_identifier: int | None = None):
        self._access = False
        self._seed = 0
        self._key = 0
        identifier = UdsIdentifiers.tx.identifier if tx_identifier is None else int(tx_identifier)
        CanDevice.instance().send_async(
            identifier,
            8,
            [0x02,              # Single Frame, request length
             0x27,              # SID: Security Access
             0x01,              # SubFunction: Request Seed
             0xFF, 0xFF, 0xFF, 0xFF, 0xFF])

    def request_check_key(self, tx_identifier: int | None = None):
        self._access = False
        identifier = UdsIdentifiers.tx.identifier if tx_identifier is None else int(tx_identifier)
        CanDevice.instance().send_async(
            identifier,
            8,
            [0x04,                                  # Single Frame, request length
             0x27,                                  # SID: Security Access
             0x02,                                  # SubFunction: Send Key
             (self._key >> 8) & 0xFF, self._key & 0xFF,
             0xFF, 0xFF, 0xFF])

    def get_session(self):
        CanDevice.instance().send_async(
            UdsIdentifiers.tx.identifier,
            8,
            [0x03,          # Single Frame, request length
             0x22,          # Service ReadDataById
             0x00, 0x16,    # Data Id - Current session
             0x00, 0x00, 0x00, 0x00])

    def verify_answer_request_seed(self, response_data) -> bool:
        if len(response_data) < 5:
            return False

        state = int(response_data[1]) & 0xFF
        sub_function = int(response_data[2]) & 0xFF
        if state == 0x67 and sub_function == 0x01:
            # Current MCU app uses charon_SecurityAccess.c where `seed` is sent
            # from packed uint16_t on a little-endian ARM target: seed_l, seed_h.
            self._seed = ((int(response_data[4]) & 0xFF) << 8) | (int(response_data[3]) & 0xFF)
            self._key = self._calc_key()
            return True
        return False

    def verify_answer_request_check_key(self, response_data) -> bool:
        if len(response_data) < 3:
            self._access = False
            return False

        state = int(response_data[1]) & 0xFF
        sub_function = int(response_data[2]) & 0xFF
        self._access = state == 0x67 and sub_function == 0x02
        return self._access
