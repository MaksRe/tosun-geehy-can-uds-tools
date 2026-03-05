from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from uds.firmware import Firmware, FirmwareState


class FirmwareLoadWorker(QObject):
    finished = Signal(str, bool, bytes, str)

    def __init__(self, file_path: str):
        super().__init__()
        self._file_path = file_path

    @Slot()
    def run(self):
        firmware = Firmware(self._file_path)
        if firmware.state == FirmwareState.successfully_uploaded and firmware.binary_content is not None:
            self.finished.emit(self._file_path, True, firmware.binary_content, "")
            return
        self.finished.emit(self._file_path, False, b"", "Не удалось открыть BIN файл.")

class UdsOptionProxy:
    def __init__(self, did: int, size: int, _name: str):
        self.pid = int(did) & 0xFFFF
        self.size = int(size)
