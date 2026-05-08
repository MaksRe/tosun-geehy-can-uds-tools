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
        "fingerprint"       : UdsVar(0x1500, 2, "Отпечаток пальцев"),
        "type_session"      : UdsVar(0x0016, 1, "Тип сессии"),
        "k_fuel_level"      : UdsVar(0x0017, 2, "Коэффициент фильтра"),
        "raw_fuel_level"    : UdsVar(0x0018, 2, "Сырые данные уровня топлива"),
        "raw_temperature"   : UdsVar(0x0019, 2, "Сырые данные текущей температуры"),
        "fuel_temp_comp_k1_x100": UdsVar(0x001B, 2, "Температурная компенсация K1 x100"),
        "fuel_temp_comp_k0_count": UdsVar(0x001C, 2, "Температурная компенсация K0 count"),
        "fuel_temp_comp_mode": UdsVar(0x001D, 1, "Режим температурной компенсации"),
        "fuel_temp_comp_dir_hyst_x10": UdsVar(0x001E, 2, "Гистерезис ветки нагрев/охлаждение, 0.1°C"),
        "fuel_temp_comp_seg_t1_x10": UdsVar(0x001F, 2, "Граница сегментов S1/S2, 0.1°C"),
        "fuel_temp_comp_seg_t2_x10": UdsVar(0x0020, 2, "Граница сегментов S2/S3, 0.1°C"),
        "fuel_temp_comp_seg_t3_x10": UdsVar(0x0021, 2, "Граница сегментов S3/S4, 0.1°C"),
        "fuel_temp_comp_seg_t4_x10": UdsVar(0x0022, 2, "Граница сегментов S4/S5, 0.1°C"),
        "fuel_temp_comp_k1_cool_seg1_x100": UdsVar(0x0023, 2, "K1 охлаждения S1 x100"),
        "fuel_temp_comp_k1_cool_seg2_x100": UdsVar(0x0024, 2, "K1 охлаждения S2 x100"),
        "fuel_temp_comp_k1_cool_seg3_x100": UdsVar(0x0025, 2, "K1 охлаждения S3 x100"),
        "fuel_temp_comp_k1_cool_seg4_x100": UdsVar(0x0026, 2, "K1 охлаждения S4 x100"),
        "fuel_temp_comp_k1_cool_seg5_x100": UdsVar(0x0027, 2, "K1 охлаждения S5 x100"),
        "fuel_temp_comp_k1_heat_seg1_x100": UdsVar(0x0028, 2, "K1 нагрева S1 x100"),
        "fuel_temp_comp_k1_heat_seg2_x100": UdsVar(0x0029, 2, "K1 нагрева S2 x100"),
        "fuel_temp_comp_k1_heat_seg3_x100": UdsVar(0x002A, 2, "K1 нагрева S3 x100"),
        "fuel_temp_comp_k1_heat_seg4_x100": UdsVar(0x002B, 2, "K1 нагрева S4 x100"),
        "fuel_temp_comp_k1_heat_seg5_x100": UdsVar(0x002C, 2, "K1 нагрева S5 x100"),
        "fuel_zero_trim_count": UdsVar(0x002D, 2, "Эксплуатационная подгонка 0% (zero trim), count"),

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
    fuel_temp_comp_k1_x100 = vars.get("fuel_temp_comp_k1_x100")
    fuel_temp_comp_k0_count = vars.get("fuel_temp_comp_k0_count")
    fuel_temp_comp_mode = vars.get("fuel_temp_comp_mode")
    fuel_temp_comp_dir_hyst_x10 = vars.get("fuel_temp_comp_dir_hyst_x10")
    fuel_temp_comp_seg_t1_x10 = vars.get("fuel_temp_comp_seg_t1_x10")
    fuel_temp_comp_seg_t2_x10 = vars.get("fuel_temp_comp_seg_t2_x10")
    fuel_temp_comp_seg_t3_x10 = vars.get("fuel_temp_comp_seg_t3_x10")
    fuel_temp_comp_seg_t4_x10 = vars.get("fuel_temp_comp_seg_t4_x10")
    fuel_temp_comp_k1_cool_seg1_x100 = vars.get("fuel_temp_comp_k1_cool_seg1_x100")
    fuel_temp_comp_k1_cool_seg2_x100 = vars.get("fuel_temp_comp_k1_cool_seg2_x100")
    fuel_temp_comp_k1_cool_seg3_x100 = vars.get("fuel_temp_comp_k1_cool_seg3_x100")
    fuel_temp_comp_k1_cool_seg4_x100 = vars.get("fuel_temp_comp_k1_cool_seg4_x100")
    fuel_temp_comp_k1_cool_seg5_x100 = vars.get("fuel_temp_comp_k1_cool_seg5_x100")
    fuel_temp_comp_k1_heat_seg1_x100 = vars.get("fuel_temp_comp_k1_heat_seg1_x100")
    fuel_temp_comp_k1_heat_seg2_x100 = vars.get("fuel_temp_comp_k1_heat_seg2_x100")
    fuel_temp_comp_k1_heat_seg3_x100 = vars.get("fuel_temp_comp_k1_heat_seg3_x100")
    fuel_temp_comp_k1_heat_seg4_x100 = vars.get("fuel_temp_comp_k1_heat_seg4_x100")
    fuel_temp_comp_k1_heat_seg5_x100 = vars.get("fuel_temp_comp_k1_heat_seg5_x100")
    fuel_zero_trim_count = vars.get("fuel_zero_trim_count")

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
