"""Связь с климатической камерой: общий драйвер, Modbus TCP/RTU и имитатор.

ЗАЧЕМ
Программа у камеры должна знать, какая в камере температура, и уметь задать
следующую. Тогда прогон идёт сам: уставка, ожидание, точки, следующий узел.
Какой интерфейс у камеры, пока неизвестно, поэтому всё, что от него не
зависит, опирается на общий драйвер с одними и теми же действиями:
- прочитать фактическую температуру, уставку, работает ли камера, есть ли авария;
- задать уставку;
- пустить или остановить камеру.

ДРАЙВЕРЫ
- Modbus TCP (Ethernet) и Modbus RTU (RS-485 через переходник USB). Это самый
  распространённый протокол контроллеров камер. Адреса регистров задаются в
  настройках, а не в коде: остаётся вписать их из документации камеры.
- Имитатор. Ведёт себя как камера: воздух идёт к уставке с ограниченной
  скоростью, изделие отстаёт от воздуха. Ускоряется в 10 и 60 раз, чтобы
  автоматический прогон отлаживался на столе за минуты, а не за сутки.

Обмен с камерой медленный и может зависнуть, поэтому он идёт в своём потоке.
Окно получает готовые показания и никогда не ждёт камеру.
"""

from __future__ import annotations

import math
import queue
import random
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

DRIVER_NONE = "none"
DRIVER_SIMULATOR = "simulator"
DRIVER_MODBUS_TCP = "modbus_tcp"
DRIVER_MODBUS_RTU = "modbus_rtu"
DRIVER_SIMCON = "simcon_ascii2"
DRIVER_ESPEC = "espec"

VALUE_TYPES = ("int16", "uint16", "int32", "uint32", "float32")


class ChamberError(Exception):
    """Камера не ответила или ответила ошибкой: текст годится для оператора."""


def serial_open_error(port: str, error: Exception) -> "ChamberError":
    """Понятная причина, по которой COM-порт не открылся."""
    text = str(error)
    busy = "Access" in text or "PermissionError" in text or "Отказано" in text
    if "FileNotFound" in text or ("could not open port" in text and not busy):
        return ChamberError(f"порт {port} не найден: подключите переходник и проверьте номер порта "
                            "в диспетчере устройств Windows")
    if busy:
        return ChamberError(f"порт {port} занят другой программой: закройте её и подключитесь снова")
    return ChamberError(f"порт {port} не открылся: {text}")


@dataclass
class ChamberReading:
    """Одно показание камеры. None - камера эту величину не отдаёт."""

    actual_c: float | None = None
    setpoint_c: float | None = None
    running: bool | None = None
    alarm: int | None = None
    # Только у имитатора: температура изделия, которая отстаёт от воздуха.
    product_c: float | None = None


# ====================================================================== Modbus

def modbus_crc(data: bytes) -> int:
    """CRC-16 Modbus RTU: полином 0xA001, начальное 0xFFFF."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


MODBUS_EXCEPTIONS = {
    1: "функция не поддерживается",
    2: "нет такого адреса регистра",
    3: "недопустимое значение",
    4: "сбой в контроллере камеры",
    5: "команда принята, выполняется",
    6: "контроллер занят",
}


@dataclass
class RegisterSpec:
    """Где лежит величина: таблица, адрес, тип, масштаб.

    Адрес - номер регистра с нуля, как он уходит в запрос. В документации часто
    пишут 40001 или 30001: тогда здесь 0. Масштаб переводит число из регистра в
    градусы: 0,1 означает «в регистре десятые доли градуса».
    """

    enabled: bool = True
    table: str = "holding"  # holding | input | coil
    address: int = 0
    value_type: str = "int16"
    scale: float = 0.1
    # Порядок слов 32-битного значения: True - старшее слово первым.
    high_word_first: bool = True
    # Для пуска и остановки: что писать, чтобы пустить и чтобы остановить.
    on_value: int = 1
    off_value: int = 0

    def register_count(self) -> int:
        return 2 if self.value_type in ("int32", "uint32", "float32") else 1

    @classmethod
    def from_dict(cls, payload: dict) -> "RegisterSpec":
        spec = cls()
        for key, value in (payload or {}).items():
            if not hasattr(spec, key):
                continue
            current = getattr(spec, key)
            if isinstance(current, bool):
                # Из окна и файла признак приходит и словом, а bool("false") был бы истиной.
                value = value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "да")
            try:
                setattr(spec, key, type(current)(value))
            except (TypeError, ValueError):
                continue
        if spec.value_type not in VALUE_TYPES:
            spec.value_type = "int16"
        return spec

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def decode_registers(spec: RegisterSpec, registers: list[int]) -> float:
    """Регистры камеры -> число в градусах (или как есть, если масштаб 1)."""
    if spec.register_count() == 2:
        high, low = (registers[0], registers[1]) if spec.high_word_first else (registers[1], registers[0])
        raw_bytes = struct.pack(">HH", high & 0xFFFF, low & 0xFFFF)
        if spec.value_type == "float32":
            raw = struct.unpack(">f", raw_bytes)[0]
        elif spec.value_type == "int32":
            raw = struct.unpack(">i", raw_bytes)[0]
        else:
            raw = struct.unpack(">I", raw_bytes)[0]
    else:
        raw = registers[0] & 0xFFFF
        if spec.value_type == "int16" and raw >= 0x8000:
            raw -= 0x10000
    return float(raw) * float(spec.scale)


def encode_registers(spec: RegisterSpec, value: float) -> list[int]:
    """Число в градусах -> регистры для записи."""
    scaled = float(value) / float(spec.scale) if spec.scale else float(value)
    if spec.value_type == "float32":
        raw_bytes = struct.pack(">f", scaled)
    elif spec.value_type in ("int32", "uint32"):
        raw_bytes = struct.pack(">i" if spec.value_type == "int32" else ">I", int(round(scaled)))
    else:
        raw = int(round(scaled))
        if spec.value_type == "int16" and not (-32768 <= raw <= 32767):
            raise ChamberError(f"значение {value} не помещается в регистр")
        return [raw & 0xFFFF]
    high, low = struct.unpack(">HH", raw_bytes)
    return [high, low] if spec.high_word_first else [low, high]


class ModbusClient:
    """Минимальный Modbus: чтение регистров и катушек, запись регистров и катушки.

    Транспорт (TCP или RTU) отдаёт только «послать PDU, получить PDU». Своя
    реализация вместо библиотеки: нужны пять функций протокола, а лишняя
    зависимость - лишний повод для сбоя сборки.
    """

    def __init__(self, unit: int):
        self.unit = int(unit) & 0xFF

    def transact(self, pdu: bytes) -> bytes:  # pragma: no cover - у транспорта
        raise NotImplementedError

    def close(self):
        pass

    @staticmethod
    def _check(pdu: bytes, function: int) -> bytes:
        if not pdu:
            raise ChamberError("пустой ответ камеры")
        if pdu[0] == (function | 0x80):
            code = pdu[1] if len(pdu) > 1 else 0
            raise ChamberError(f"камера ответила ошибкой Modbus {code}: {MODBUS_EXCEPTIONS.get(code, 'неизвестная')}")
        if pdu[0] != function:
            raise ChamberError(f"камера ответила на другую функцию ({pdu[0]})")
        return pdu

    def read_registers(self, table: str, address: int, count: int) -> list[int]:
        function = 4 if table == "input" else 3
        answer = self._check(self.transact(struct.pack(">BHH", function, address, count)), function)
        if len(answer) < 2 or answer[1] != 2 * count or len(answer) < 2 + 2 * count:
            raise ChamberError("ответ камеры короче ожидаемого")
        return list(struct.unpack(f">{count}H", answer[2:2 + 2 * count]))

    def read_coil(self, address: int) -> bool:
        answer = self._check(self.transact(struct.pack(">BHH", 1, address, 1)), 1)
        if len(answer) < 3:
            raise ChamberError("ответ камеры короче ожидаемого")
        return bool(answer[2] & 0x01)

    def write_registers(self, address: int, values: list[int]):
        if len(values) == 1:
            self._check(self.transact(struct.pack(">BHH", 6, address, values[0] & 0xFFFF)), 6)
            return
        body = struct.pack(">BHHB", 16, address, len(values), 2 * len(values))
        body += b"".join(struct.pack(">H", value & 0xFFFF) for value in values)
        self._check(self.transact(body), 16)

    def write_coil(self, address: int, on: bool):
        self._check(self.transact(struct.pack(">BHH", 5, address, 0xFF00 if on else 0x0000)), 5)


class ModbusTcpClient(ModbusClient):
    """Modbus TCP: заголовок MBAP и PDU поверх TCP-соединения."""

    def __init__(self, host: str, port: int, unit: int, timeout_s: float = 2.0):
        super().__init__(unit)
        self.host = str(host)
        self.port = int(port)
        self.timeout_s = float(timeout_s)
        self._socket: socket.socket | None = None
        self._transaction = 0

    def _connect(self):
        if self._socket is not None:
            return
        try:
            self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout_s)
        except OSError as error:
            raise ChamberError(f"нет соединения с {self.host}:{self.port}: {error}") from None
        self._socket.settimeout(self.timeout_s)

    def _receive(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = self._socket.recv(size - len(data))
            if not chunk:
                raise ChamberError("камера закрыла соединение")
            data += chunk
        return data

    def transact(self, pdu: bytes) -> bytes:
        self._connect()
        self._transaction = (self._transaction + 1) & 0xFFFF
        frame = struct.pack(">HHHB", self._transaction, 0, len(pdu) + 1, self.unit) + pdu
        try:
            self._socket.sendall(frame)
            header = self._receive(7)
            transaction, protocol, length, _unit = struct.unpack(">HHHB", header)
            body = self._receive(length - 1)
        except (OSError, ChamberError) as error:
            self.close()
            if isinstance(error, ChamberError):
                raise
            raise ChamberError(f"камера не ответила: {error}") from None
        if transaction != self._transaction or protocol != 0:
            self.close()
            raise ChamberError("ответ камеры не на тот запрос")
        return body

    def close(self):
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        self._socket = None


class ModbusRtuClient(ModbusClient):
    """Modbus RTU по RS-485: адрес, PDU и CRC через последовательный порт."""

    def __init__(self, port: str, baudrate: int, parity: str, stopbits: int, unit: int, timeout_s: float = 1.0,
                 serial_factory=None):
        super().__init__(unit)
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.parity = str(parity or "N").upper()[:1]
        self.stopbits = int(stopbits)
        self.timeout_s = float(timeout_s)
        self._serial_factory = serial_factory
        self._serial = None

    def _connect(self):
        if self._serial is not None:
            return
        factory = self._serial_factory
        if factory is None:
            try:
                import serial  # pyserial
            except ImportError:
                raise ChamberError("для RS-485 нужен пакет pyserial: pip install pyserial") from None
            factory = serial.Serial
        try:
            self._serial = factory(port=self.port, baudrate=self.baudrate, parity=self.parity,
                                   stopbits=self.stopbits, bytesize=8, timeout=self.timeout_s)
        except Exception as error:  # noqa: BLE001 - у pyserial свои классы ошибок
            raise serial_open_error(self.port, error) from None

    def _read_exact(self, size: int) -> bytes:
        data = self._serial.read(size)
        if len(data) < size:
            raise ChamberError("камера не ответила по RS-485 (проверьте адрес, скорость и провода A/B)")
        return data

    def transact(self, pdu: bytes) -> bytes:
        self._connect()
        frame = bytes([self.unit]) + pdu
        frame += struct.pack("<H", modbus_crc(frame))
        try:
            self._serial.reset_input_buffer()
            self._serial.write(frame)
            head = self._read_exact(2)
            function = head[1]
            if function & 0x80:
                rest = self._read_exact(3)
            elif function in (1, 2, 3, 4):
                count = self._read_exact(1)
                rest = count + self._read_exact(count[0] + 2)
            else:
                rest = self._read_exact(6)
        except ChamberError:
            raise
        except Exception as error:  # noqa: BLE001
            self.close()
            raise ChamberError(f"обмен по RS-485 прервался: {error}") from None
        answer = head + rest
        if modbus_crc(answer[:-2]) != struct.unpack("<H", answer[-2:])[0]:
            raise ChamberError("ответ камеры испорчен (не сошлась контрольная сумма)")
        if answer[0] != self.unit:
            raise ChamberError(f"ответил чужой адрес {answer[0]}")
        return answer[1:-2]

    def close(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass
        self._serial = None


# ====================================================================== драйверы

class ChamberDriver:
    """Общий вид драйвера камеры. Методы вызываются только из потока связи."""

    title = "камера"
    can_set = False
    can_run = False

    def read(self) -> ChamberReading:  # pragma: no cover
        raise NotImplementedError

    def set_setpoint(self, value_c: float):
        raise ChamberError("эта камера не даёт задавать уставку")

    def set_running(self, on: bool):
        raise ChamberError("эта камера не даёт пускать и останавливать себя")

    def close(self):
        pass


@dataclass
class ModbusMap:
    """Где у камеры лежат её величины."""

    actual: RegisterSpec = field(default_factory=lambda: RegisterSpec(table="input", address=0))
    setpoint: RegisterSpec = field(default_factory=lambda: RegisterSpec(table="holding", address=1))
    run: RegisterSpec = field(default_factory=lambda: RegisterSpec(enabled=False, table="coil", address=0,
                                                                   value_type="uint16", scale=1.0))
    alarm: RegisterSpec = field(default_factory=lambda: RegisterSpec(enabled=False, table="holding", address=2,
                                                                     value_type="uint16", scale=1.0))

    @classmethod
    def from_dict(cls, payload: dict) -> "ModbusMap":
        result = cls()
        for name in ("actual", "setpoint", "run", "alarm"):
            if isinstance((payload or {}).get(name), dict):
                base = getattr(result, name).to_dict()
                base.update(payload[name])
                setattr(result, name, RegisterSpec.from_dict(base))
        return result

    def to_dict(self) -> dict:
        return {name: getattr(self, name).to_dict() for name in ("actual", "setpoint", "run", "alarm")}


class ModbusChamber(ChamberDriver):
    """Камера с Modbus: величины читаются и пишутся по карте регистров."""

    def __init__(self, client: ModbusClient, register_map: ModbusMap, title: str):
        self.client = client
        self.map = register_map
        self.title = title
        self.can_set = bool(register_map.setpoint.enabled)
        self.can_run = bool(register_map.run.enabled)

    def _read_value(self, spec: RegisterSpec) -> float:
        if spec.table == "coil":
            return 1.0 if self.client.read_coil(spec.address) else 0.0
        return decode_registers(spec, self.client.read_registers(spec.table, spec.address, spec.register_count()))

    def read(self) -> ChamberReading:
        reading = ChamberReading()
        if self.map.actual.enabled:
            reading.actual_c = self._read_value(self.map.actual)
        if self.map.setpoint.enabled:
            reading.setpoint_c = self._read_value(self.map.setpoint)
        if self.map.run.enabled:
            reading.running = int(round(self._read_value(self.map.run))) == int(self.map.run.on_value)
        if self.map.alarm.enabled:
            reading.alarm = int(round(self._read_value(self.map.alarm)))
        return reading

    def set_setpoint(self, value_c: float):
        spec = self.map.setpoint
        if not spec.enabled:
            raise ChamberError("адрес уставки не задан")
        if spec.table != "holding":
            raise ChamberError("уставка должна лежать в регистрах хранения (holding)")
        self.client.write_registers(spec.address, encode_registers(spec, value_c))

    def set_running(self, on: bool):
        spec = self.map.run
        if not spec.enabled:
            raise ChamberError("адрес пуска не задан")
        if spec.table == "coil":
            self.client.write_coil(spec.address, bool(on))
        else:
            self.client.write_registers(spec.address, [int(spec.on_value if on else spec.off_value)])

    def close(self):
        self.client.close()


class SimulatedChamber(ChamberDriver):
    """Камера без камеры: для отладки автоматического прогона на столе.

    Воздух идёт к уставке не быстрее заданной скорости и мягко подходит к ней.
    Изделие догоняет воздух с постоянной времени в несколько минут: так плата в
    корпусе с компаундом и отстаёт от камеры. Ускорение сжимает время.
    """

    title = "имитатор"
    can_set = True
    can_run = True

    AMBIENT_C = 23.0
    RAMP_C_PER_MIN = 2.0
    AIR_TAU_MIN = 1.5
    PRODUCT_TAU_MIN = 8.0
    NOISE_C = 0.03

    def __init__(self, speed: float = 1.0, clock: Callable[[], float] = time.monotonic, seed: int | None = None):
        self.speed = max(0.1, float(speed))
        self._clock = clock
        self._random = random.Random(seed)
        self.air_c = self.AMBIENT_C
        self.product_c = self.AMBIENT_C
        self.setpoint_c = 25.0
        self.running = False
        self._last = clock()

    def advance(self, minutes: float):
        """Проводит модель вперёд на заданное число минут модельного времени."""
        target = self.setpoint_c if self.running else self.AMBIENT_C
        remaining = float(minutes)
        step = 0.05
        while remaining > 1e-9:
            dt = min(step, remaining)
            # Мягкий подход к цели, но не быстрее предельной скорости камеры.
            wanted = (target - self.air_c) * (1.0 - math.exp(-dt / self.AIR_TAU_MIN))
            limit = self.RAMP_C_PER_MIN * dt
            self.air_c += max(-limit, min(limit, wanted))
            self.product_c += (self.air_c - self.product_c) * (1.0 - math.exp(-dt / self.PRODUCT_TAU_MIN))
            remaining -= dt

    def _sync(self):
        now = self._clock()
        self.advance((now - self._last) / 60.0 * self.speed)
        self._last = now

    def read(self) -> ChamberReading:
        self._sync()
        noise = self._random.uniform(-self.NOISE_C, self.NOISE_C)
        return ChamberReading(actual_c=round(self.air_c + noise, 2), setpoint_c=self.setpoint_c,
                              running=self.running, alarm=0, product_c=round(self.product_c, 3))

    def set_setpoint(self, value_c: float):
        self._sync()
        self.setpoint_c = float(value_c)

    def set_running(self, on: bool):
        self._sync()
        self.running = bool(on)


# ====================================================================== Weiss SIMCON/32

def simcon_ascii1_checksum(text: str) -> str:
    """Контрольная сумма протокола ASCII-1 контроллера SIMCON/32.

    По инструкции: дополнение остатка от деления суммы кодов всех символов
    строки на 256, включая STX, без ETX и самой суммы; две заглавные
    шестнадцатеричные цифры. Пример инструкции: STX "1?" -> "8E".
    """
    value = 0
    for char in text:
        value = (value - ord(char)) & 0xFF
    return f"{value:02X}"


@dataclass
class SimconState:
    """Разобранный ответ SIMCON/32 на запрос «I» протокола ASCII-2."""

    temp_setpoint: float
    temp_actual: float
    humidity_setpoint: float
    humidity_actual: float
    fan_setpoint: float
    fan_actual: float
    pt100: list
    digital: str

    @property
    def running(self) -> bool:
        # Канал 0 не используется, канал 1 - «Старт», канал 2 - «Влажность».
        return len(self.digital) > 1 and self.digital[1] == "1"


def parse_simcon_state(line: str) -> SimconState:
    """Разбирает ответ на «$xxI»: 14 чисел и строка цифровых каналов из нулей и единиц.

    Порядок по инструкции SIMCON/32 (приложение «Interface protocol», 2.4.2):
    уставка и факт температуры, уставка и факт влажности, задание и факт
    вентилятора, затем четыре пары «не используется / Pt100-n» и цифровые каналы.
    """
    tokens = str(line).replace("\r", " ").replace("\n", " ").split()
    numbers = []
    digital = ""
    for token in tokens:
        # Отзыв адреса, если контроллер его добавит, к данным не относится.
        if token.startswith("$"):
            continue
        if len(token) >= 3 and set(token) <= {"0", "1"} and len(numbers) >= 6:
            digital = token
            continue
        try:
            numbers.append(float(token.replace(",", ".")))
        except ValueError:
            raise ChamberError(f"камера ответила непонятно: {line.strip()[:60]}") from None
    if len(numbers) < 4:
        raise ChamberError(f"в ответе камеры мало чисел: {line.strip()[:60]}")
    while len(numbers) < 14:
        numbers.append(0.0)
    return SimconState(
        temp_setpoint=numbers[0], temp_actual=numbers[1],
        humidity_setpoint=numbers[2], humidity_actual=numbers[3],
        fan_setpoint=numbers[4], fan_actual=numbers[5],
        pt100=[numbers[7], numbers[9], numbers[11], numbers[13]],
        digital=digital,
    )


def simcon_number(value: float) -> str:
    """Число в виде протокола ASCII-2: шесть знаков с одной цифрой после точки, «0023.0», «-040.0»."""
    return f"{float(value):06.1f}"


def build_simcon_setpoints(address: int, temp: float, humidity: float, fan: float, digital: str) -> str:
    """Строка «$xxE»: уставки температуры, влажности, вентилятора и все цифровые каналы сразу.

    Команда задаёт всё одной строкой, поэтому влажность, вентилятор и каналы
    берутся из последнего ответа камеры: менять их программа не должна.
    """
    unused = " ".join(simcon_number(0.0) for _ in range(4))
    return (f"${int(address):02d}E {simcon_number(temp)} {simcon_number(humidity)} {simcon_number(fan)} "
            f"{unused} {digital}\r")


class SimconAscii2Chamber(ChamberDriver):
    """Камера Weiss с контроллером SIMCON/32, протокол ASCII-2 по RS-232.

    По инструкции (приложение «Interface protocol», раздел 2):
    - запрос «$xxI<CR>» возвращает уставки, факты и цифровые каналы одной строкой;
    - «$xxE ...<CR>» задаёт уставки и цифровые каналы, камера отвечает строкой с <CR>;
    - строки нельзя слать чаще одной в 5 секунд: иначе страдает регулирование;
    - чтобы компьютер мог задавать уставку, на пульте включается режим EXTERN.
    Пуск и остановка - цифровой канал 1 «Старт».
    """

    title = "SIMCON/32 (Weiss, RS-232)"
    can_set = True
    can_run = True
    # Пауза между строками, с. Её требует инструкция, сокращать нельзя.
    MIN_INTERVAL_S = 5.0

    def __init__(self, port: str, baudrate: int, address: int, timeout_s: float = 3.0, serial_factory=None,
                 sleep=time.sleep, clock=time.monotonic):
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.address = int(address)
        self.timeout_s = float(timeout_s)
        self._serial_factory = serial_factory
        self._serial = None
        self._sleep = sleep
        self._clock = clock
        self._last_send = -1e9
        self.last_state: SimconState | None = None
        self.title = f"Weiss на {self.port}"

    def _connect(self):
        if self._serial is not None:
            return
        factory = self._serial_factory
        if factory is None:
            try:
                import serial  # pyserial
            except ImportError:
                raise ChamberError("для RS-232 нужен пакет pyserial: pip install pyserial") from None
            factory = serial.Serial
        try:
            self._serial = factory(port=self.port, baudrate=self.baudrate, parity="N", stopbits=1,
                                   bytesize=8, timeout=self.timeout_s)
        except Exception as error:  # noqa: BLE001 - у pyserial свои классы ошибок
            raise serial_open_error(self.port, error) from None

    def _exchange(self, line: str) -> str:
        """Отправляет строку и читает ответ до <CR>, соблюдая паузу 5 с между строками."""
        self._connect()
        wait = self.MIN_INTERVAL_S - (self._clock() - self._last_send)
        if wait > 0:
            self._sleep(wait)
        try:
            self._serial.reset_input_buffer()
            self._serial.write(line.encode("ascii"))
            self._last_send = self._clock()
            answer = self._serial.read_until(b"\r")
        except Exception as error:  # noqa: BLE001
            self.close()
            raise ChamberError(f"обмен по RS-232 прервался: {error}") from None
        if not answer or not answer.endswith(b"\r"):
            raise ChamberError("камера не ответила по RS-232: проверьте кабель (нуль-модем), скорость, "
                               "адрес и протокол ASCII-2 в меню пульта")
        return answer.decode("ascii", errors="replace").strip()

    def read(self) -> ChamberReading:
        state = parse_simcon_state(self._exchange(f"${self.address:02d}I\r"))
        self.last_state = state
        return ChamberReading(actual_c=state.temp_actual, setpoint_c=state.temp_setpoint,
                              running=state.running, alarm=None)

    def _current(self) -> SimconState:
        return self.last_state if self.last_state is not None else parse_simcon_state(
            self._exchange(f"${self.address:02d}I\r"))

    def _send_setpoints(self, temp: float, digital: str):
        state = self._current()
        if not digital:
            raise ChamberError("камера не отдала цифровые каналы, задать уставку безопасно нельзя")
        self._exchange(build_simcon_setpoints(self.address, temp, state.humidity_setpoint,
                                              state.fan_setpoint, digital))

    def set_setpoint(self, value_c: float):
        state = self._current()
        self._send_setpoints(value_c, state.digital)

    def set_running(self, on: bool):
        state = self._current()
        digital = state.digital
        if len(digital) < 2:
            raise ChamberError("камера не отдала цифровые каналы, пустить её нельзя")
        digital = digital[0] + ("1" if on else "0") + digital[2:]
        self._exchange(build_simcon_setpoints(self.address, state.temp_setpoint, state.humidity_setpoint,
                                              state.fan_setpoint, digital))

    def raw(self, text: str) -> str:
        """Строка оператора как есть, для проверки на месте: «$01I» и т. п."""
        line = str(text)
        if not line.endswith("\r"):
            line += "\r"
        return self._exchange(line)

    def close(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass
        self._serial = None


# ====================================================================== ESPEC (MC-811P и родственные)

ESPEC_DELIMITERS = {"CRLF": "\r\n", "CR": "\r", "LF": "\n"}

# Режимы из ответов MON? и MODE?, при которых камера держит температуру.
ESPEC_RUNNING_MODES = ("CONSTANT", "RUN")


def parse_espec_temp(answer: str) -> tuple[float, float]:
    """Ответ на TEMP?: факт, уставка, верхний и нижний предел аварии. Возвращает (факт, уставка)."""
    parts = [part.strip() for part in str(answer).split(",")]
    try:
        return float(parts[0]), float(parts[1])
    except (IndexError, ValueError):
        raise ChamberError(f"камера ответила непонятно на TEMP?: {str(answer).strip()[:60]}") from None


def parse_espec_mon(answer: str) -> tuple[float, str, int]:
    """Ответ на MON?: факт температуры, [влажность], режим, число аварий.

    Влажности у температурных камер в ответе нет, поэтому режим ищется как
    первое нечисловое поле, а число аварий - последнее поле.
    """
    parts = [part.strip() for part in str(answer).split(",") if part.strip()]
    try:
        actual = float(parts[0])
        alarms = int(float(parts[-1]))
        mode = next(part for part in parts[1:-1] if not part.replace(".", "", 1).lstrip("-").isdigit())
    except (IndexError, ValueError, StopIteration):
        raise ChamberError(f"камера ответила непонятно на MON?: {str(answer).strip()[:60]}") from None
    return actual, " ".join(mode.split()).upper(), alarms


class EspecChamber(ChamberDriver):
    """Камера ESPEC (MC-811P и другие с тем же протоколом) по RS-485.

    По руководству ESPEC «Network Guide RS-485, RS-232C, GPIB»:
    - строка команды: «адрес,команда[,параметры]» и разделитель (по умолчанию CR LF);
    - TEMP? - факт, уставка и пределы аварии; MON? - факт, режим, число аварий;
    - «TEMP, S-40.0» задаёт уставку, «MODE, CONSTANT» и «MODE, STANDBY» - пуск и стоп;
    - ответ на настройку - «OK:...» или «NA:причина»;
    - после запроса пауза не меньше 0,3 с, после настройки - не меньше 0,5 с.
    Интерфейс камеры четырёхпроводный: со стороны компьютера это обычный COM-порт
    переходника USB-RS-422/485 с раздельными парами передачи и приёма.
    """

    can_set = True
    can_run = True
    MONITOR_PAUSE_S = 0.3
    SETTING_PAUSE_S = 0.5

    def __init__(self, port: str, baudrate: int, address: int, delimiter: str = "CRLF", timeout_s: float = 2.0,
                 serial_factory=None, sleep=time.sleep, clock=time.monotonic):
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.address = int(address)
        self.delimiter = ESPEC_DELIMITERS.get(str(delimiter).upper(), "\r\n")
        self.timeout_s = float(timeout_s)
        self._serial_factory = serial_factory
        self._serial = None
        self._sleep = sleep
        self._clock = clock
        self._ready_at = -1e9
        self.title = f"ESPEC на {self.port}, адрес {self.address}"

    def _connect(self):
        if self._serial is not None:
            return
        factory = self._serial_factory
        if factory is None:
            try:
                import serial  # pyserial
            except ImportError:
                raise ChamberError("для RS-485 нужен пакет pyserial: pip install pyserial") from None
            factory = serial.Serial
        try:
            self._serial = factory(port=self.port, baudrate=self.baudrate, parity="N", stopbits=1,
                                   bytesize=8, timeout=self.timeout_s)
        except Exception as error:  # noqa: BLE001 - у pyserial свои классы ошибок
            raise serial_open_error(self.port, error) from None

    def _read_line(self) -> str:
        end = self.delimiter[-1].encode("ascii")
        data = self._serial.read_until(end)
        if not data or not data.endswith(end):
            raise ChamberError("камера не ответила по RS-485: проверьте адрес, скорость, разделитель и "
                               "4-проводное подключение (TX± переходника на RD± камеры, RX± на SD±)")
        return data.decode("ascii", errors="replace").strip()

    def _exchange(self, command: str, setting: bool = False) -> str:
        """Отправляет команду с адресом и возвращает ответ, соблюдая паузы руководства."""
        self._connect()
        wait = self._ready_at - self._clock()
        if wait > 0:
            self._sleep(wait)
        line = f"{self.address},{command}{self.delimiter}"
        try:
            self._serial.reset_input_buffer()
            self._serial.write(line.encode("ascii"))
            answer = self._read_line()
            # Протокол OLD с эхом: сначала приходит «OK:команда», данные - следующей строкой.
            if not setting and answer.upper().startswith("OK:"):
                answer = self._read_line()
        except ChamberError:
            raise
        except Exception as error:  # noqa: BLE001
            self.close()
            raise ChamberError(f"обмен по RS-485 прервался: {error}") from None
        finally:
            self._ready_at = self._clock() + (self.SETTING_PAUSE_S if setting else self.MONITOR_PAUSE_S)
        if answer.upper().startswith("NA:"):
            raise ChamberError(self._refusal_text(answer[3:].strip()))
        return answer

    @staticmethod
    def _refusal_text(reason: str) -> str:
        """Отказ камеры словами: что именно мешает и что сделать."""
        hints = {
            "PROTECT ON": "на пульте включена защита от удалённого управления, выключите её",
            "DATA OUT OF RANGE": "значение вне пределов аварии камеры, поправьте пределы на пульте",
            "CMD_ERR": "камера не поняла команду",
            "COMMAND ERR": "камера не поняла команду",
            "CHB NOT READY": "камера сейчас не может выполнить команду (выключена панель?)",
        }
        key = next((name for name in hints if name in reason.upper()), None)
        return f"камера отказала ({reason})" + (f": {hints[key]}" if key else "")

    def read(self) -> ChamberReading:
        actual, mode, alarms = parse_espec_mon(self._exchange("MON?"))
        _actual, setpoint = parse_espec_temp(self._exchange("TEMP?"))
        alarm_code = alarms
        if alarms:
            # Номер первой аварии полезнее их числа: по нему авария ищется в инструкции камеры.
            try:
                numbers = [part.strip() for part in self._exchange("ALARM?").split(",")]
                alarm_code = int(numbers[1]) if len(numbers) > 1 else alarms
            except (ChamberError, ValueError):
                alarm_code = alarms
        running = any(mode.startswith(name) for name in ESPEC_RUNNING_MODES)
        return ChamberReading(actual_c=actual, setpoint_c=setpoint, running=running, alarm=alarm_code)

    def set_setpoint(self, value_c: float):
        self._exchange(f"TEMP, S{float(value_c):.1f}", setting=True)

    def set_running(self, on: bool):
        self._exchange("MODE, CONSTANT" if on else "MODE, STANDBY", setting=True)

    def raw(self, text: str) -> str:
        """Команда оператора как есть, адрес добавляется сам: «TEMP?», «MON?»."""
        command = str(text).strip()
        # Адрес, если оператор написал его сам, второй раз не добавляется.
        head, _, rest = command.partition(",")
        if rest and head.strip().isdigit():
            command = rest.strip()
        is_setting = not command.endswith("?")
        return self._exchange(command, setting=is_setting)

    def close(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass
        self._serial = None


def make_driver(settings: dict) -> ChamberDriver | None:
    """Драйвер по настройкам раздела. None - связь с камерой выключена."""
    kind = settings.get("driver", DRIVER_NONE)
    register_map = ModbusMap.from_dict(settings.get("map") or {})
    unit = int(settings.get("unit", 1))
    if kind == DRIVER_SIMULATOR:
        return SimulatedChamber(speed=float(settings.get("sim_speed", 1.0)))
    if kind == DRIVER_MODBUS_TCP:
        client = ModbusTcpClient(settings.get("tcp_host", ""), int(settings.get("tcp_port", 502)), unit)
        return ModbusChamber(client, register_map, f"Modbus TCP {settings.get('tcp_host', '')}")
    if kind == DRIVER_ESPEC:
        return EspecChamber(settings.get("espec_port", ""), int(settings.get("espec_baud", 9600)),
                            int(settings.get("espec_address", 1)), str(settings.get("espec_delimiter", "CRLF")))
    if kind == DRIVER_SIMCON:
        return SimconAscii2Chamber(settings.get("weiss_port", ""), int(settings.get("weiss_baud", 9600)),
                                   int(settings.get("simcon_address", 0)))
    if kind == DRIVER_MODBUS_RTU:
        client = ModbusRtuClient(settings.get("rtu_port", ""), int(settings.get("rtu_baud", 9600)),
                                 settings.get("rtu_parity", "N"), int(settings.get("rtu_stopbits", 1)), unit)
        return ModbusChamber(client, register_map, f"Modbus RTU {settings.get('rtu_port', '')}")
    return None


# ====================================================================== поток связи

class ChamberLink:
    """Поток связи с камерой: опрос по таймеру и команды из окна.

    Окно ставит команды в очередь и забирает итог через обратный вызов. Связь,
    оборванная ошибкой, восстанавливается сама через паузу.
    """

    RECONNECT_PAUSE_S = 5.0

    def __init__(self, driver: ChamberDriver, poll_s: float,
                 on_state: Callable[[dict], None]):
        self.driver = driver
        # Камере, которой нельзя слать строки чаще заданного, опрос чаще и не нужен.
        self.poll_s = max(0.2, float(poll_s), float(getattr(driver, "MIN_INTERVAL_S", 0.0)))
        self._on_state = on_state
        self._commands: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="climate-chamber-link")
        self._thread.start()

    def command(self, name: str, value=None):
        """Ставит команду: "setpoint" с градусами или "run" с True/False."""
        self._commands.put((str(name), value))

    def close(self):
        self._stop.set()
        self._commands.put(None)
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)
        try:
            self.driver.close()
        except Exception:  # noqa: BLE001
            pass

    def _worker(self):
        next_poll = 0.0
        while not self._stop.is_set():
            timeout = max(0.0, next_poll - time.monotonic())
            try:
                task = self._commands.get(timeout=timeout)
            except queue.Empty:
                task = ("poll", None)
            if task is None:
                break
            name, value = task
            try:
                if name == "setpoint":
                    self.driver.set_setpoint(float(value))
                    self._on_state({"kind": "command", "ok": True, "text": f"уставка {value:+.1f} °C принята"})
                elif name == "run":
                    self.driver.set_running(bool(value))
                    self._on_state({"kind": "command", "ok": True, "text": "камера пущена" if value else "камера остановлена"})
                elif name == "raw":
                    raw = getattr(self.driver, "raw", None)
                    if raw is None:
                        raise ChamberError("эта связь не умеет посылать строки как есть")
                    answer = raw(str(value))
                    self._on_state({"kind": "raw", "ok": True, "sent": str(value), "text": answer})
                # После команды показание читается сразу: окно видит её итог.
                reading = self.driver.read()
                self._on_state({"kind": "reading", "ok": True, "reading": reading})
                next_poll = time.monotonic() + self.poll_s
            except ChamberError as error:
                kind = "reading" if name == "poll" else ("raw" if name == "raw" else "command")
                self._on_state({"kind": kind, "ok": False, "sent": str(value or ""), "text": str(error)})
                next_poll = time.monotonic() + self.RECONNECT_PAUSE_S
            except Exception as error:  # noqa: BLE001 - поток связи не должен падать
                self._on_state({"kind": "reading", "ok": False, "text": f"сбой связи: {error}"})
                next_poll = time.monotonic() + self.RECONNECT_PAUSE_S
