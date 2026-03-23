from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AccessMode(str, Enum):
    READ = "Чтение"
    WRITE = "Запись"
    READ_WRITE = "Чтение/Запись"
    UNSUPPORTED = "Не поддерживается"


@dataclass(frozen=True)
class UdsOptionParameter:
    did: int
    size: int
    name: str
    access: AccessMode
    note: str = ""

    @property
    def can_read(self) -> bool:
        return self.access in (AccessMode.READ, AccessMode.READ_WRITE)

    @property
    def can_write(self) -> bool:
        return self.access in (AccessMode.WRITE, AccessMode.READ_WRITE)


# Карта параметров синхронизирована с прошивкой:
# d:\revkovms\dev\_Embedded\Embedded_git\apm32f103cbt7_fuel_intake_iar\src\app\uds\reader_var.h
# d:\revkovms\dev\_Embedded\Embedded_git\apm32f103cbt7_fuel_intake_iar\src\app\uds\reader_var.c
# d:\revkovms\dev\_Embedded\Embedded_git\apm32f103cbt7_fuel_intake_iar\src\app\uds\services\read_data_by_id.c
# d:\revkovms\dev\_Embedded\Embedded_git\apm32f103cbt7_fuel_intake_iar\src\app\uds\services\write_data_by_id.c
UDS_OPTIONS: list[UdsOptionParameter] = [
    UdsOptionParameter(0x0010, 1, "Скорость CAN шины", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0011, 1, "Адрес источника данных (CAN SA)", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0012, 2, "Пустой бак (период 0%)", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0013, 2, "Полный бак (период 100%)", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0014, 2, "Текущий уровень (период)", AccessMode.READ),
    UdsOptionParameter(0x0015, 2, "Отпечаток пальцев", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0016, 1, "Текущая сессия", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0017, 2, "Коэффициент фильтра уровня топлива", AccessMode.READ),
    UdsOptionParameter(0x0018, 2, "Сырые данные уровня топлива", AccessMode.READ),
    UdsOptionParameter(0x0019, 2, "Сырые данные температуры", AccessMode.READ),
    UdsOptionParameter(0x001B, 2, "K1 температурной компенсации x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x001C, 2, "K0 температурной компенсации, count", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF188, 18, "Номер ПО ЭБУ", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF189, 32, "Версия ПО ЭБУ", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF18A, 32, "Поставщик системы и адрес", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF18B, 16, "Дата изготовления ЭБУ", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF18C, 253, "Серийный номер ЭБУ", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF190, 17, "VIN", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF191, 32, "Номер аппаратного обеспечения (OEM)", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF192, 32, "Номер аппаратного обеспечения (Supplier)", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF193, 16, "Версия аппаратного обеспечения", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF194, 128, "Номер программного обеспечения", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF195, 128, "Версия программного обеспечения", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF196, 64, "Норма выхлопных газов/номер утверждения", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF197, 64, "Наименование системы/тип двигателя", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF198, 32, "Код мастерской/серийный номер тестера", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF199, 16, "Дата последнего перепрограммирования", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF19D, 16, "Дата установки ЭБУ", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF1A0, 18, "Конфигурация ПО ЭБУ", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF1A1, 32, "Версия конфигурации ПО ЭБУ", AccessMode.READ_WRITE),
    UdsOptionParameter(0xF1A2, 256, "Опции идентификации OEM", AccessMode.UNSUPPORTED, "В прошивке помечено как TODO"),
    UdsOptionParameter(0xF1F0, 256, "Опции идентификации Supplier", AccessMode.UNSUPPORTED, "В прошивке помечено как TODO"),
]


def get_option_by_did(did: int) -> UdsOptionParameter | None:
    target = int(did) & 0xFFFF
    for item in UDS_OPTIONS:
        if int(item.did) == target:
            return item
    return None


def get_option_by_index(index: int) -> UdsOptionParameter | None:
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return None

    if idx < 0 or idx >= len(UDS_OPTIONS):
        return None
    return UDS_OPTIONS[idx]


def build_option_caption(item: UdsOptionParameter) -> str:
    return f"0x{int(item.did) & 0xFFFF:04X} | {item.name} | {item.access.value}"
