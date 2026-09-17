class UdsVar:

    def __init__(self, pid, size, description):
        self._pid: int = pid
        self._size: int = size
        self._description: str = description

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def size(self) -> int:
        return self._size

    @property
    def description(self) -> str:
        return self._description


class UdsData:
    vars = {
        "can_baud_rate"     : UdsVar(0x0010, 1, "Скорость CAN шины"),
        "can_sa"            : UdsVar(0x0011, 1, "Адрес источника данных"),
        "empty_fuel_tank"   : UdsVar(0x0012, 2, "Пустой бак"),
        "full_fuel_tank"    : UdsVar(0x0013, 2, "Полный бак"),
        "curr_fuel_tank"    : UdsVar(0x0014, 2, "Текущий уровень"),
        "fingerprint"       : UdsVar(0x0015, 2, "Отпечаток пальцев"),
        "type_session"      : UdsVar(0x0016, 1, "Тип сессии"),
        "k_fuel_level"      : UdsVar(0x0017, 2, "Коэффициент фильтра"),
        "raw_fuel_level"    : UdsVar(0x0018, 2, "Сырые данные уровня топлива"),
        "raw_temperature"   : UdsVar(0x0019, 2, "Сырые данные текущей температуры"),

        # Номера 0x001B..0x002C освободились после удаления прежней температурной
        # компенсации (K1, K0 и сегментные таблицы). Занимать их заново нельзя:
        # в приборах с прежней прошивкой по этим номерам лежат старые параметры.
        "fuel_zero_trim_count": UdsVar(0x002D, 2, "Эксплуатационная подгонка 0% (zero trim), count"),

        # Коррекция шкалы по виду топлива: настройки, чтение и запись.
        "fuel_media_comp_enable": UdsVar(0x002E, 1, "Коррекция по виду топлива: 0 выкл, 1 вкл"),
        "fuel_media_flatcap_air_count": UdsVar(0x002F, 2, "Плоский конденсатор в воздухе, count"),
        "fuel_media_flatcap_cal_count": UdsVar(0x0030, 2, "Плоский конденсатор в эталонной жидкости, count"),
        "fuel_media_h0_ratio_x1000": UdsVar(0x0031, 2, "Отношение h0/(h100-h0) x1000"),
        "fuel_media_rf_min_x1000": UdsVar(0x0032, 2, "Нижний предел коэффициента среды x1000"),
        "fuel_media_rf_max_x1000": UdsVar(0x0033, 2, "Верхний предел коэффициента среды x1000"),
        "fuel_media_freeze_level_pct": UdsVar(0x0034, 1, "Уровень (%), ниже которого R_F замораживается"),
        "fuel_media_rf_last_x1000": UdsVar(0x0039, 2, "Последний сохранённый R_F x1000"),
        "fuel_temp_comp_source": UdsVar(0x003A, 1, "Источник температуры компенсации: 0 топливо, 1 плата"),

        # Коррекция по виду топлива: телеметрия из ОЗУ, только чтение.
        "fuel_media_rf_x1000": UdsVar(0x0035, 2, "Текущий коэффициент среды R_F x1000"),
        "fuel_media_flatcap_raw": UdsVar(0x0036, 2, "Сырое измерение плоского конденсатора, count"),
        "fuel_media_state": UdsVar(0x0037, 1, "Состояние коррекции: активна, устарело, заморожено, отказ"),
        "fuel_media_rejected_cnt": UdsVar(0x0038, 2, "Счётчик отбракованных значений R_F"),

        # Второй датчик температуры, только чтение.
        "raw_board_temperature": UdsVar(0x003B, 2, "Температура платы, 0.1 °C"),
        "board_temperature_adc": UdsVar(0x003C, 2, "Сырой код АЦП датчика платы"),

        # Качество измерения ёмкостных контуров, только чтение.
        "cap_main_burst_spread": UdsVar(0x003D, 2, "Размах последней серии, основной контур, count"),
        "cap_main_spread_max": UdsVar(0x003E, 2, "Максимум размаха за окно, основной контур, count"),
        "cap_main_half_delta": UdsVar(0x003F, 2, "Асимметрия половин заряда и разряда, count"),
        "cap_main_overrun_cnt": UdsVar(0x0040, 2, "Перезахваты основного контура"),
        "cap_media_spread_max": UdsVar(0x0041, 2, "Максимум размаха за окно, контур вида топлива, count"),
        "cap_media_overrun_cnt": UdsVar(0x0042, 2, "Перезахваты контура вида топлива"),

        # Ступень температурной компенсации платы: убирает дрейф электроники.
        "fuel_board_comp_k1_main_x100": UdsVar(0x0043, 2, "K1 ступени платы, основной контур"),
        "fuel_board_comp_k0_main_count": UdsVar(0x0044, 2, "K0 ступени платы, основной контур"),
        "fuel_board_comp_k1_media_x100": UdsVar(0x0045, 2, "K1 ступени платы, контур вида топлива"),
        "fuel_board_comp_k0_media_count": UdsVar(0x0046, 2, "K0 ступени платы, контур вида топлива"),
        "fuel_board_stage_period": UdsVar(0x0047, 2, "Период после ступени платы, основной контур"),
        "fuel_tube_stage_temperature": UdsVar(0x0048, 2, "Температура ступени трубки, 0.1 °C"),
        "fuel_board_comp_ka_main_ppm": UdsVar(0x0049, 2, "Множитель ступени платы, основной контур, ppm/°C"),
        "fuel_board_comp_ka_media_ppm": UdsVar(0x004A, 2, "Множитель ступени платы, контур вида топлива, ppm/°C"),
        "fuel_board_lut_nodes": UdsVar(0x004B, 14, "Температуры узлов таблицы ступени платы"),
        "fuel_board_lut_main": UdsVar(0x004C, 28, "Таблица ступени платы, основной контур"),
        "fuel_board_lut_media": UdsVar(0x004D, 28, "Таблица ступени платы, контур вида топлива"),
        "fuel_board_stage_mode": UdsVar(0x004E, 1, "Источник поправки ступени платы"),
        "fuel_tube_lut_air_main": UdsVar(0x004F, 14, "Ступень трубки: основной контур на воздухе"),
        "fuel_tube_lut_full_main": UdsVar(0x0050, 14, "Ступень трубки: основной контур в жидкости"),
        "fuel_tube_lut_air_media": UdsVar(0x0051, 14, "Ступень трубки: контур вида топлива на воздухе"),
        "fuel_tube_lut_full_media": UdsVar(0x0052, 14, "Ступень трубки: контур вида топлива в жидкости"),

        # Модель уровня по двум контурам: отметки бака вместе с показанием среды.
        "fuel_tank_model": UdsVar(0x0053, 1, "Модель расчёта уровня"),
        "fuel_tank_zero_media_count": UdsVar(0x0054, 2, "Вид топлива при снятии отметки 0 %"),
        "fuel_tank_full_media_count": UdsVar(0x0055, 2, "Вид топлива при снятии отметки 100 %"),
        "fuel_tank_h0_x1000": UdsVar(0x0056, 2, "Доля длины трубки для отметки 0 %"),
        "fuel_tank_h100_x1000": UdsVar(0x0057, 2, "Доля длины трубки для отметки 100 %"),
        "fuel_tank_k_x1000": UdsVar(0x0058, 2, "Отношение чувствительностей K x1000"),
        "fuel_tank_a_count": UdsVar(0x0059, 2, "Показание при нулевом погружении A"),
        "fuel_tank_immersion_x1000": UdsVar(0x005A, 2, "Погружённая доля x1000"),
        "fuel_tank_full_main_pred": UdsVar(0x005B, 2, "Предсказанное показание для отметки 100 %"),

        # Целостность температурного профиля: сумма пишется последней.
        "fuel_measurement_algorithm_id": UdsVar(0x005C, 2, "Алгоритм измерения при снятии коэффициентов"),
        "fuel_thermal_profile_generation": UdsVar(0x005D, 2, "Номер поколения температурного профиля"),
        "fuel_thermal_profile_crc": UdsVar(0x005E, 2, "Записанная контрольная сумма профиля"),
        "fuel_thermal_profile_crc_actual": UdsVar(0x005F, 2, "Сумма, посчитанная прибором сейчас"),
        "fuel_thermal_profile_status": UdsVar(0x0060, 1, "Состояние температурного профиля"),

        # Проверка на столе без климатической камеры. Эмуляция живёт только в ОЗУ
        # прибора и гаснет при перезапуске и выходе из сессии.
        "temperature_emulation_x10": UdsVar(0x0061, 2, "Эмуляция температуры, 0.1 °C, 0x8000 выключено"),
        "fuel_compensated_period": UdsVar(0x0062, 2, "Итоговый период после компенсации и подгонки нуля"),
        # Состояние записи в память прибора: не записано, флаги, сброшено при включении, ошибки.
        "eeprom_state": UdsVar(0x0063, 4, "Состояние записи в память прибора"),
        # Возраст последнего измерения основного контура и контура вида топлива, мс.
        "measurement_age": UdsVar(0x0064, 4, "Возраст последнего измерения контуров"),

        "vmecusndid"        : UdsVar(0xF188, 18, "Номер ПО ЭБУ изготовителя ТС"),
        "vmecusvndid"       : UdsVar(0xF189, 32, "Номер версии ПО ЭБУ изготовителя ТС"),
        "ssiddid"           : UdsVar(0xF18A, 32, "Название поставщика системы и информация об адресе"),
        "ecumddid"          : UdsVar(0xF18B, 16, "Дата изготовления ЭБУ"),
        "ecusndid"          : UdsVar(0xF18C, 253, "Серийный номер ЭБУ"),
        "vindid"            : UdsVar(0xF190, 17, "VIN-номер"),
        "vmecuhndid"        : UdsVar(0xF191, 32, "Номер аппаратного обеспечения, определенного ЭБУ изготовителя ТС"),
        "ssecuhwndid"       : UdsVar(0xF192, 32, "Номер аппаратного обеспечения, определенного ЭБУ поставщика системы"),
        "ssecuhwvndid"      : UdsVar(0xF193, 16, "Номер версии аппаратного обеспечения"),
        "ssecuswndid"       : UdsVar(0xF194, 128, "Номер программного обеспечения"),
        "ssecuswvndid"      : UdsVar(0xF195, 128, "Версия программного обеспечения"),
        "erotandid"         : UdsVar(0xF196, 64, "Норма выхлопных газов или номер официального утверждения типа"),
        "snoetdid"          : UdsVar(0xF197, 64, "Наименование системы или тип двигателя"),
        "rscotsndid"        : UdsVar(0xF198, 32, "Код ремонтной мастерской или серийный номер тестера"),
        "pddid"             : UdsVar(0xF199, 16, "Дата последнего перепрограммирования устройства"),
        "eiddid"            : UdsVar(0xF19D, 16, "Дата установки ЭБУ в транспортное средство"),
        "vmecuscndid"       : UdsVar(0xF1A0, 18, "Номер конфигурации программного обеспечения ЭБУ изготовителя ТС"),
        "vmecuscvndid"      : UdsVar(0xF1A1, 32, "Номер версии конфигурации ПО ЭБУ изготовителя ТС"),
        "idoptvms"          : UdsVar(0xF1A2, 256, "Опции идентификации определенного устройства/ТС производителем ТС"),
        "idoptsss"          : UdsVar(0xF1F0, 256, "Опции идентификации определенного устройства/ТС поставщиком системы")
    }

    can_baud_rate       = vars.get("can_baud_rate")
    can_sa              = vars.get("can_sa")
    empty_fuel_tank     = vars.get("empty_fuel_tank")
    full_fuel_tank      = vars.get("full_fuel_tank")
    curr_fuel_tank      = vars.get("curr_fuel_tank")
    fingerprint         = vars.get("fingerprint")
    type_session        = vars.get("type_session")
    k_fuel_level        = vars.get("k_fuel_level")
    raw_fuel_level      = vars.get("raw_fuel_level")
    raw_temperature     = vars.get("raw_temperature")
    fuel_zero_trim_count = vars.get("fuel_zero_trim_count")

    fuel_media_comp_enable = vars.get("fuel_media_comp_enable")
    fuel_media_flatcap_air_count = vars.get("fuel_media_flatcap_air_count")
    fuel_media_flatcap_cal_count = vars.get("fuel_media_flatcap_cal_count")
    fuel_media_h0_ratio_x1000 = vars.get("fuel_media_h0_ratio_x1000")
    fuel_media_rf_min_x1000 = vars.get("fuel_media_rf_min_x1000")
    fuel_media_rf_max_x1000 = vars.get("fuel_media_rf_max_x1000")
    fuel_media_freeze_level_pct = vars.get("fuel_media_freeze_level_pct")
    fuel_media_rf_last_x1000 = vars.get("fuel_media_rf_last_x1000")
    fuel_temp_comp_source = vars.get("fuel_temp_comp_source")

    fuel_media_rf_x1000 = vars.get("fuel_media_rf_x1000")
    fuel_media_flatcap_raw = vars.get("fuel_media_flatcap_raw")
    fuel_media_state = vars.get("fuel_media_state")
    fuel_media_rejected_cnt = vars.get("fuel_media_rejected_cnt")

    raw_board_temperature = vars.get("raw_board_temperature")
    board_temperature_adc = vars.get("board_temperature_adc")

    cap_main_burst_spread = vars.get("cap_main_burst_spread")
    cap_main_spread_max = vars.get("cap_main_spread_max")
    cap_main_half_delta = vars.get("cap_main_half_delta")
    cap_main_overrun_cnt = vars.get("cap_main_overrun_cnt")
    cap_media_spread_max = vars.get("cap_media_spread_max")
    cap_media_overrun_cnt = vars.get("cap_media_overrun_cnt")

    fuel_board_comp_k1_main_x100 = vars.get("fuel_board_comp_k1_main_x100")
    fuel_board_comp_k0_main_count = vars.get("fuel_board_comp_k0_main_count")
    fuel_board_comp_k1_media_x100 = vars.get("fuel_board_comp_k1_media_x100")
    fuel_board_comp_k0_media_count = vars.get("fuel_board_comp_k0_media_count")
    fuel_board_stage_period = vars.get("fuel_board_stage_period")
    fuel_tube_stage_temperature = vars.get("fuel_tube_stage_temperature")
    fuel_board_comp_ka_main_ppm = vars.get("fuel_board_comp_ka_main_ppm")
    fuel_board_comp_ka_media_ppm = vars.get("fuel_board_comp_ka_media_ppm")
    fuel_board_lut_nodes = vars.get("fuel_board_lut_nodes")
    fuel_board_lut_main = vars.get("fuel_board_lut_main")
    fuel_board_lut_media = vars.get("fuel_board_lut_media")
    fuel_board_stage_mode = vars.get("fuel_board_stage_mode")
    fuel_tube_lut_air_main = vars.get("fuel_tube_lut_air_main")
    fuel_tube_lut_full_main = vars.get("fuel_tube_lut_full_main")
    fuel_tube_lut_air_media = vars.get("fuel_tube_lut_air_media")
    fuel_tube_lut_full_media = vars.get("fuel_tube_lut_full_media")

    fuel_tank_model = vars.get("fuel_tank_model")
    fuel_tank_zero_media_count = vars.get("fuel_tank_zero_media_count")
    fuel_tank_full_media_count = vars.get("fuel_tank_full_media_count")
    fuel_tank_h0_x1000 = vars.get("fuel_tank_h0_x1000")
    fuel_tank_h100_x1000 = vars.get("fuel_tank_h100_x1000")
    fuel_tank_k_x1000 = vars.get("fuel_tank_k_x1000")
    fuel_tank_a_count = vars.get("fuel_tank_a_count")
    fuel_tank_immersion_x1000 = vars.get("fuel_tank_immersion_x1000")
    fuel_tank_full_main_pred = vars.get("fuel_tank_full_main_pred")

    fuel_measurement_algorithm_id = vars.get("fuel_measurement_algorithm_id")
    fuel_thermal_profile_generation = vars.get("fuel_thermal_profile_generation")
    fuel_thermal_profile_crc = vars.get("fuel_thermal_profile_crc")
    fuel_thermal_profile_crc_actual = vars.get("fuel_thermal_profile_crc_actual")
    fuel_thermal_profile_status = vars.get("fuel_thermal_profile_status")
    temperature_emulation_x10 = vars.get("temperature_emulation_x10")
    fuel_compensated_period = vars.get("fuel_compensated_period")
    eeprom_state = vars.get("eeprom_state")
    measurement_age = vars.get("measurement_age")

    vmecusndid          = vars.get("vmecusndid")
    vmecusvndid         = vars.get("vmecusvndid")
    ssiddid             = vars.get("ssiddid")
    ecumddid            = vars.get("ecumddid")
    ecusndid            = vars.get("ecusndid")
    vindid              = vars.get("vindid")
    vmecuhndid          = vars.get("vmecuhndid")
    ssecuhwndid         = vars.get("ssecuhwndid")
    ssecuhwvndid        = vars.get("ssecuhwvndid")
    ssecuswndid         = vars.get("ssecuswndid")
    ssecuswvndid        = vars.get("ssecuswvndid")
    erotandid           = vars.get("erotandid")
    snoetdid            = vars.get("snoetdid")
    rscotsndid          = vars.get("rscotsndid")
    pddid               = vars.get("pddid")
    eiddid              = vars.get("eiddid")
    vmecuscndid         = vars.get("vmecuscndid")
    vmecuscvndid        = vars.get("vmecuscvndid")
    idoptvms            = vars.get("idoptvms")
    idoptsss            = vars.get("idoptsss")

    @classmethod
    def get_pid(cls, index: int) -> int | None:
        if index > len(cls.vars) or index < 0:
            return None
        return list(cls.vars.values())[index].pid

    @classmethod
    def get_var(cls, index) -> UdsVar | None:
        if index > len(cls.vars) or index < 0:
            return None
        return list(cls.vars.values())[index]

    @classmethod
    def get_var_by_pid(cls, pid: int) -> UdsVar | None:
        """Цель функции в поиске параметра по DID, затем она возвращает объект UdsVar или None при отсутствии."""
        target_pid = int(pid) & 0xFFFF
        for var in cls.vars.values():
            if int(var.pid) & 0xFFFF == target_pid:
                return var
        return None

    @classmethod
    def descriptions(cls) -> list:
        return [var.description for var in cls.vars.values()]
