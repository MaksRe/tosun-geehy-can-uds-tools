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
    UdsOptionParameter(0x0017, 2, "Заполнение окна усреднения основного контура, промилле", AccessMode.READ),
    UdsOptionParameter(0x0018, 2, "Сырые данные уровня топлива", AccessMode.READ),
    UdsOptionParameter(0x0019, 2, "Сырые данные температуры", AccessMode.READ),
    UdsOptionParameter(0x001B, 2, "K1 температурной компенсации x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x001C, 2, "K0 температурной компенсации, count", AccessMode.READ_WRITE),
    UdsOptionParameter(0x001D, 1, "Режим температурной компенсации", AccessMode.READ_WRITE),
    UdsOptionParameter(0x001E, 2, "Гистерезис ветки нагрев/охлаждение, 0.1°C", AccessMode.READ_WRITE),
    UdsOptionParameter(0x001F, 2, "Граница сегментов S1/S2, 0.1°C", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0020, 2, "Граница сегментов S2/S3, 0.1°C", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0021, 2, "Граница сегментов S3/S4, 0.1°C", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0022, 2, "Граница сегментов S4/S5, 0.1°C", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0023, 2, "K1 охлаждения S1 x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0024, 2, "K1 охлаждения S2 x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0025, 2, "K1 охлаждения S3 x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0026, 2, "K1 охлаждения S4 x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0027, 2, "K1 охлаждения S5 x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0028, 2, "K1 нагрева S1 x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0029, 2, "K1 нагрева S2 x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x002A, 2, "K1 нагрева S3 x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x002B, 2, "K1 нагрева S4 x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x002C, 2, "K1 нагрева S5 x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x002D, 2, "Эксплуатационная подгонка 0% (zero trim), count", AccessMode.READ_WRITE),

    # Коррекция шкалы уровня по виду топлива. Настройки хранятся в EEPROM.
    UdsOptionParameter(0x002E, 1, "Коррекция по виду топлива: 0 выкл, 1 вкл", AccessMode.READ_WRITE,
                       "Включать только после калибровки плоского конденсатора"),
    UdsOptionParameter(0x002F, 2, "Плоский конденсатор в воздухе, count", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0030, 2, "Плоский конденсатор в эталонной жидкости, count", AccessMode.READ_WRITE,
                       "Должно быть больше значения в воздухе"),
    UdsOptionParameter(0x0031, 2, "Отношение h0/(h100-h0) x1000", AccessMode.READ_WRITE,
                       "0 при совпадении отметки 0% с низом трубки"),
    UdsOptionParameter(0x0032, 2, "Нижний предел коэффициента среды x1000", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0033, 2, "Верхний предел коэффициента среды x1000", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0034, 1, "Уровень (%), ниже которого R_F замораживается", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0035, 2, "Текущий коэффициент среды R_F x1000", AccessMode.READ),
    UdsOptionParameter(0x0036, 2, "Сырое измерение плоского конденсатора, count", AccessMode.READ),
    UdsOptionParameter(0x0037, 1, "Состояние коррекции по виду топлива", AccessMode.READ,
                       "Биты: 0 активна, 1 данные устарели, 2 заморожено, 3 отказ контура"),
    UdsOptionParameter(0x0038, 2, "Счётчик отбракованных значений R_F", AccessMode.READ),
    UdsOptionParameter(0x0039, 2, "Последний сохранённый R_F x1000", AccessMode.READ_WRITE,
                       "Восстанавливается при старте, 1000 это нейтраль"),

    # Второй датчик температуры и выбор источника компенсации тракта.
    UdsOptionParameter(0x003A, 1, "Источник температуры компенсации: 0 топливо, 1 плата", AccessMode.READ_WRITE,
                       "Переключать только вместе с повторным снятием температурного профиля"),
    UdsOptionParameter(0x003B, 2, "Температура платы, 0.1 °C", AccessMode.READ),
    UdsOptionParameter(0x003C, 2, "Сырой код АЦП датчика платы", AccessMode.READ),

    # Качество измерения ёмкостных контуров. Нужно для подбора фильтра захвата.
    UdsOptionParameter(0x003D, 2, "Размах последней серии, основной контур, count", AccessMode.READ),
    UdsOptionParameter(0x003E, 2, "Максимум размаха за окно, основной контур, count", AccessMode.READ,
                       "Основная мера дрожания, обновляется примерно раз в 3 с"),
    UdsOptionParameter(0x003F, 2, "Асимметрия половин заряда и разряда, count", AccessMode.READ,
                       "Значение со знаком, признак утечки через датчик"),
    UdsOptionParameter(0x0040, 2, "Перезахваты основного контура", AccessMode.READ,
                       "Растущий счётчик означает дребезг компараторов"),
    UdsOptionParameter(0x0041, 2, "Максимум размаха за окно, контур вида топлива, count", AccessMode.READ),
    UdsOptionParameter(0x0042, 2, "Перезахваты контура вида топлива", AccessMode.READ),

    # Ступень температурной компенсации платы. Нулевые коэффициенты означают,
    # что ступень выключена и прибор работает как прежде.
    UdsOptionParameter(0x0043, 2, "K1 ступени платы, основной контур, count/°C x100", AccessMode.READ_WRITE,
                       "Снимать на стенде по температуре платы, не по температуре топлива"),
    UdsOptionParameter(0x0044, 2, "K0 ступени платы, основной контур, count", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0045, 2, "K1 ступени платы, контур вида топлива, count/°C x100", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0046, 2, "K0 ступени платы, контур вида топлива, count", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0047, 2, "Период после ступени платы, основной контур", AccessMode.READ,
                       "Показывает вклад ступени платы отдельно от ступени трубки"),
    UdsOptionParameter(0x0048, 2, "Температура ступени трубки, 0.1 °C", AccessMode.READ,
                       "Значение со знаком, источник задаётся параметром 0x003A"),
    UdsOptionParameter(0x0049, 2, "Множитель ступени платы, основной контур, ppm/°C", AccessMode.READ_WRITE,
                       "Убирает растяжение показаний при нагреве, ноль означает без поправки"),
    UdsOptionParameter(0x004A, 2, "Множитель ступени платы, контур вида топлива, ppm/°C", AccessMode.READ_WRITE),

    # Температурные таблицы ступени платы. Семь узлов, между ними прямая.
    # Пока таблица канала нулевая, работают одиночные коэффициенты выше.
    UdsOptionParameter(0x004B, 14, "Температуры узлов таблицы ступени платы, 7 x 0.1 °C", AccessMode.READ_WRITE,
                       "Строго по возрастанию, иначе таблицы не применяются"),
    UdsOptionParameter(0x004C, 28, "Таблица ступени платы, основной контур", AccessMode.READ_WRITE,
                       "7 пар: сдвиг в отсчётах и растяжение в ppm"),
    UdsOptionParameter(0x004D, 28, "Таблица ступени платы, контур вида топлива", AccessMode.READ_WRITE,
                       "7 пар: сдвиг в отсчётах и растяжение в ppm"),
    UdsOptionParameter(0x004E, 1, "Что сейчас работает в обеих ступенях", AccessMode.READ,
                       "Биты: 0 и 1 таблицы платы, 2 сетка узлов неверна, 3 и 4 приведение трубки"),

    # Таблицы ступени трубки: приводят оба контура к общей шкале до расчёта
    # коэффициента среды. Пока оба ряда контура нулевые, приведение выключено.
    UdsOptionParameter(0x004F, 14, "Ступень трубки: основной контур на воздухе", AccessMode.READ_WRITE,
                       "7 значений в тех же узлах температуры"),
    UdsOptionParameter(0x0050, 14, "Ступень трубки: основной контур в опорной жидкости", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0051, 14, "Ступень трубки: контур вида топлива на воздухе", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0052, 14, "Ступень трубки: контур вида топлива в опорной жидкости", AccessMode.READ_WRITE),

    # Модель уровня по двум контурам. Прежняя модель верна только тогда, когда
    # обе отметки бака сняты на одном и том же топливе.
    UdsOptionParameter(0x0053, 1, "Модель расчёта уровня: 0 прежняя, 1 по двум контурам", AccessMode.READ_WRITE,
                       "Включать только после записи отметок вместе с показанием среды"),
    UdsOptionParameter(0x0054, 2, "Вид топлива при снятии отметки 0 %", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0055, 2, "Вид топлива при снятии отметки 100 %", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0056, 2, "Доля длины трубки для отметки 0 %, тысячные", AccessMode.READ_WRITE,
                       "Задаётся при монтаже, по двум отметкам не выводится"),
    UdsOptionParameter(0x0057, 2, "Доля длины трубки для отметки 100 %, тысячные", AccessMode.READ_WRITE),
    UdsOptionParameter(0x0058, 2, "Отношение чувствительностей K x1000", AccessMode.READ,
                       "Считается по отметкам, ноль означает неполную калибровку"),
    UdsOptionParameter(0x0059, 2, "Показание при нулевом погружении A", AccessMode.READ),
    UdsOptionParameter(0x005A, 2, "Погружённая доля x1000", AccessMode.READ),
    UdsOptionParameter(0x005B, 2, "Предсказанное показание для отметки 100 %", AccessMode.READ,
                       "Для сверки с независимым измерением, отметку не заменяет"),

    # Целостность температурного профиля. Таблицы пишутся по одной, и обрыв
    # связи оставил бы смесь старых и новых значений. Сумма пишется последней.
    UdsOptionParameter(0x005C, 2, "Алгоритм измерения при снятии коэффициентов", AccessMode.READ_WRITE,
                       "Не совпал с прошивкой - таблицы профиля не применяются"),
    UdsOptionParameter(0x005D, 2, "Номер поколения температурного профиля", AccessMode.READ_WRITE),
    UdsOptionParameter(0x005E, 2, "Записанная контрольная сумма профиля", AccessMode.READ_WRITE,
                       "Писать последней, после всех таблиц"),
    UdsOptionParameter(0x005F, 2, "Сумма, посчитанная прибором сейчас", AccessMode.READ,
                       "Расхождение с записанной означает недописанный профиль"),
    UdsOptionParameter(0x0060, 1, "Состояние температурного профиля", AccessMode.READ,
                       "Биты: 0 заполнен, 1 сумма сходится, 2 алгоритм совпадает, 3 применяется"),

    # Проверка на столе без климатической камеры.
    UdsOptionParameter(0x0061, 2, "Эмуляция температуры, 0.1 °C", AccessMode.READ_WRITE,
                       "Только ОЗУ, гаснет при перезапуске и выходе из сессии, 0x8000 выключает"),
    UdsOptionParameter(0x0062, 2, "Итоговый период после компенсации и подгонки нуля", AccessMode.READ,
                       "По нему считается уровень, на стенде сверяется с расчётом"),
    UdsOptionParameter(0x0063, 4, "Состояние записи в память прибора", AccessMode.READ,
                       "Не записано, флаги сбоя и сброса при включении, сброшено параметров, ошибки записи"),
    UdsOptionParameter(0x0064, 4, "Возраст последнего измерения контуров, мс", AccessMode.READ,
                       "По 2 байта: основной контур, контур вида топлива. 0xFFFF - измерений не было"),
    UdsOptionParameter(0x0065, 1, "Окно усреднения основного контура, с", AccessMode.READ_WRITE,
                       "1..60 с, по умолчанию 10. Основной контур идёт в уровень напрямую: длиннее "
                       "окно - спокойнее уровень на месте, но мелкое изменение догоняется всё время "
                       "окна. Действует сразу"),
    UdsOptionParameter(0x0066, 1, "Окно усреднения контура вида топлива, с", AccessMode.READ_WRITE,
                       "1..60 с, по умолчанию 30. В уровень идёт через двухминутный фильтр, поэтому "
                       "длинное окно реакцию уровня почти не портит. Действует сразу"),
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
