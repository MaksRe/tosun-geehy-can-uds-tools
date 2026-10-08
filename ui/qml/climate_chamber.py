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
- ESPEC (MC-811P) по RS-485 через переходник Moxa UPort 1150: порт «auto»
  находит переходник сам, поиск находит адрес, скорость и конец строки,
  каталог команд руководства даёт окну ручное управление камерой.
- Weiss WK1-600/70 (контроллер SIMCON/32, протокол ASCII-2) по RS-232.
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
import re
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from ui.qml.climate_diag import hex_bytes, moxa_registry_info, show_bytes

DRIVER_NONE = "none"
DRIVER_SIMULATOR = "simulator"
DRIVER_MODBUS_TCP = "modbus_tcp"
DRIVER_MODBUS_RTU = "modbus_rtu"
DRIVER_SIMCON = "simcon_ascii2"
DRIVER_ESPEC = "espec"

VALUE_TYPES = ("int16", "uint16", "int32", "uint32", "float32")


class ChamberError(Exception):
    """Камера не ответила или ответила ошибкой: текст годится для оператора."""


def pyserial_missing_text(link: str) -> str:
    """Что делать, если нет pyserial: точная команда для Python, из которого запущена программа."""
    if getattr(sys, "frozen", False):
        return (f"для {link} в сборке программы нет пакета pyserial: соберите программу заново из окружения, "
                f"где он установлен (pip install -r requirements.txt)")
    return (f"для {link} нужен пакет pyserial: выполните «\"{sys.executable}\" -m pip install pyserial==3.5» "
            f"и перезапустите программу")


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


# Флаги ошибок линии из ClearCommError (Windows): по ним видно, что сигнал на линии
# был, но не собрался в байты - перевёрнутая пара приёма или чужая скорость.
SERIAL_LINE_ERRORS = {
    0x0001: "RXOVER (переполнен приёмный буфер)",
    0x0002: "OVERRUN (байты потеряны в UART)",
    0x0004: "RXPARITY (ошибка чётности)",
    0x0008: "FRAME (ошибка кадра: нет стоп-бита)",
    0x0010: "BREAK (линия в «нуле» дольше кадра)",
}


def line_error_names(flags: int) -> list[str]:
    """Флаги ошибок линии словами."""
    return [name for bit, name in SERIAL_LINE_ERRORS.items() if int(flags) & bit]


def serial_line_errors(serial_port) -> list[str]:
    """Ошибки линии, накопленные портом с прошлого чтения (только Windows и pyserial).

    pyserial сам сбрасывает флаги в начале чтения, поэтому вызов сразу после
    чтения показывает, что происходило на линии, пока программа ждала ответ.
    Порт без дескриптора Windows (заглушки, другие ОС) - пустой список.
    """
    handle = getattr(serial_port, "_port_handle", None)
    if handle is None:
        return []
    try:
        import ctypes

        from serial import win32

        flags = win32.DWORD()
        comstat = win32.COMSTAT()
        if not win32.ClearCommError(handle, ctypes.byref(flags), ctypes.byref(comstat)):
            return []
        return line_error_names(flags.value)
    except Exception:  # noqa: BLE001 - флаги нужны только для журнала
        return []


@dataclass
class ChamberReading:
    """Одно показание камеры. None - камера эту величину не отдаёт."""

    actual_c: float | None = None
    setpoint_c: float | None = None
    running: bool | None = None
    alarm: int | None = None
    # Только у имитатора: температура изделия, которая отстаёт от воздуха.
    product_c: float | None = None
    # Подробности, которые отдаёт не каждая камера (ESPEC: режим, пределы аварии, нагреватель...).
    details: dict | None = None


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
                raise ChamberError(pyserial_missing_text("RS-485")) from None
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
    # Журнал диагностики (ChamberDiagLog) или None. Ставится окном при подключении.
    diag = None

    def read(self) -> ChamberReading:  # pragma: no cover
        raise NotImplementedError

    # Запись в журнал диагностики: без журнала (проверки, заглушки) ничего не делает.

    def _trace_event(self, kind: str, text: str, level: str = "INFO"):
        if self.diag is not None:
            self.diag.event(kind, text, level)

    def _trace_error(self, kind: str, text: str, with_traceback: bool = False):
        if self.diag is not None:
            self.diag.error(kind, text, with_traceback)

    def _trace_tx(self, port: str, data: bytes):
        if self.diag is not None:
            self.diag.wire("TX", f"{port} {len(data)} байт: {show_bytes(data)}  |  {hex_bytes(data)}")

    def _trace_rx(self, port: str, data: bytes, latency_ms: float, outcome: str, line_errors: list[str] | None = None):
        if self.diag is not None:
            errors = f", ошибки линии: {', '.join(line_errors)}" if line_errors else ""
            self.diag.wire("RX", f"{port} {len(data)} байт за {latency_ms:.0f} мс, итог {outcome}{errors}: "
                                 f"{show_bytes(data)}  |  {hex_bytes(data)}")

    def _trace_open(self, serial_port, port: str):
        """Фактические параметры открытого порта: по ним видно, что открылось именно задуманное."""
        if self.diag is None:
            return
        settings = {}
        getter = getattr(serial_port, "get_settings", None)
        if callable(getter):
            try:
                settings = dict(getter())
            except Exception:  # noqa: BLE001 - параметры только для журнала
                settings = {}
        text = ", ".join(f"{key}={value}" for key, value in settings.items()) or "параметры порт не отдал"
        self.diag.event("OPEN", f"порт {port} открыт: {text}")

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
                raise ChamberError(pyserial_missing_text("RS-232")) from None
            factory = serial.Serial
        self._trace_event("OPEN", f"открываю {self.port}: {self.baudrate} бод, 8N1, адрес {self.address}, "
                                  f"ожидание ответа {self.timeout_s:g} с")
        try:
            self._serial = factory(port=self.port, baudrate=self.baudrate, parity="N", stopbits=1,
                                   bytesize=8, timeout=self.timeout_s)
        except Exception as error:  # noqa: BLE001 - у pyserial свои классы ошибок
            self._trace_error("OPEN", f"{self.port} не открылся: {type(error).__name__}: {error}")
            raise serial_open_error(self.port, error) from None
        self._trace_open(self._serial, self.port)

    def _exchange(self, line: str) -> str:
        """Отправляет строку и читает ответ до <CR>, соблюдая паузу 5 с между строками."""
        self._connect()
        wait = self.MIN_INTERVAL_S - (self._clock() - self._last_send)
        if wait > 0:
            self._sleep(wait)
        try:
            self._serial.reset_input_buffer()
            data = line.encode("ascii")
            self._trace_tx(self.port, data)
            started = time.perf_counter()
            self._serial.write(data)
            self._last_send = self._clock()
            answer = self._serial.read_until(b"\r")
        except Exception as error:  # noqa: BLE001
            self._trace_error("SERIAL", f"обмен с {self.port} прервался: {type(error).__name__}: {error}",
                              with_traceback=True)
            if self.diag is not None:
                self.diag.note_exchange("error", None, str(error))
            self.close()
            raise ChamberError(f"обмен по RS-232 прервался: {error}") from None
        latency_ms = (time.perf_counter() - started) * 1000.0
        outcome = "ok" if answer and answer.endswith(b"\r") else ("silence" if not answer else "cut")
        self._trace_rx(self.port, answer, latency_ms, outcome)
        if self.diag is not None:
            self.diag.note_exchange(outcome, latency_ms, show_bytes(answer))
        if outcome != "ok":
            text = ("камера не ответила по RS-232: проверьте кабель (нуль-модем), скорость, "
                    "адрес и протокол ASCII-2 в меню пульта")
            self._trace_error("RX", text)
            raise ChamberError(text)
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


# ====================================================================== COM-порты и переходник Moxa UPort

# Код производителя Moxa на шине USB: по нему переходник UPort 1150 узнаётся среди других портов.
MOXA_USB_VID = 0x110A
# Значение поля порта, при котором программа сама находит переходник Moxa UPort.
PORT_AUTO = "auto"


def _port_number(device: str) -> int:
    """Номер из имени «COM12» для сортировки: COM2 идёт раньше COM10."""
    digits = "".join(char for char in str(device) if char.isdigit())
    return int(digits) if digits else 0


def list_serial_ports(comports=None) -> list[dict]:
    """Все COM-порты компьютера с пометкой, какой из них переходник Moxa UPort.

    Оператору не нужно искать номер порта в диспетчере устройств: переходник
    Moxa показывается первым и находится сам по коду производителя или имени.
    comports подменяется в проверках, чтобы обойтись без железа.
    """
    if comports is None:
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        comports = list_ports.comports
    ports = []
    for info in comports():
        text = " ".join(str(getattr(info, name, "") or "") for name in ("description", "manufacturer", "hwid", "product"))
        moxa = getattr(info, "vid", None) == MOXA_USB_VID or "moxa" in text.lower() or "uport" in text.lower()
        ports.append({"device": str(info.device), "description": str(getattr(info, "description", "") or ""),
                      "moxa": bool(moxa), "hwid": str(getattr(info, "hwid", "") or "")})
    ports.sort(key=lambda item: (not item["moxa"], _port_number(item["device"])))
    return ports


def resolve_port(port: str, comports=None) -> str:
    """Порт для открытия. Для «auto» - первый найденный переходник Moxa UPort."""
    if str(port).strip().lower() != PORT_AUTO:
        return str(port).strip()
    moxa = [item for item in list_serial_ports(comports) if item["moxa"]]
    if not moxa:
        # Windows помнит отключённый переходник в реестре: тогда понятно, что он просто не вставлен.
        try:
            known = [item["port"] for item in moxa_registry_info()]
        except Exception:  # noqa: BLE001 - реестр нужен только для подсказки
            known = []
        if known:
            raise ChamberError(f"переходник Moxa UPort не найден среди подключённых: раньше он был {', '.join(known)}, "
                               f"а сейчас не вставлен в USB или не определился - переподключите его")
        raise ChamberError("переходник Moxa UPort не найден: подключите его к USB и проверьте, что стоит драйвер Moxa "
                           "(в диспетчере устройств - «MOXA USB Serial Port»), или впишите номер порта вручную")
    return moxa[0]["device"]


# ====================================================================== ESPEC (MC-811P и родственные)

ESPEC_DELIMITERS = {"CRLF": "\r\n", "CR": "\r", "LF": "\n"}
ESPEC_BAUDS = (9600, 19200, 4800)

# Режимы из ответов MON? и MODE?, при которых камера держит температуру.
ESPEC_RUNNING_MODES = ("CONSTANT", "RUN", "RMT RUN")

# Режимы камеры словами (ответы MODE? и MON?, в том числе с DETAIL).
ESPEC_MODE_TEXTS = {
    "OFF": "панель выключена",
    "STANDBY": "стоп",
    "CONSTANT": "постоянный режим",
    "RUN": "программа",
    "RUN PAUSE": "программа на паузе",
    "RUN END HOLD": "программа кончилась, уставка держится",
    "RMT RUN": "удалённая программа",
    "RMT RUN PAUSE": "удалённая программа на паузе",
    "RMT RUN END HOLD": "удалённая программа кончилась, уставка держится",
}

# Каталог команд из руководства ESPEC «Network Guide RS-485, RS-232C, GPIB», глава 3.
# Окно строит по нему список команд, а кнопки ручного управления посылают команды по ключу.
# Поля: group - раздел списка; title и hint - что делает команда; command - шаблон строки
# без адреса, {имя} заменяется параметром; params - поля ввода; danger - нужна проверка
# оператором; new_only - только новая серия контроллера (модели на «2», например MC-812),
# MC-811P ответит на неё «NA:CMD_ERR».
ESPEC_COMMANDS: list[dict] = [
    # --- Показания ---
    {"key": "mon", "group": "Показания", "command": "MON?", "title": "Состояние камеры",
     "hint": "Температура в камере, режим работы и число аварий."},
    {"key": "temp", "group": "Показания", "command": "TEMP?", "title": "Температура, уставка и пределы",
     "hint": "Температура в камере, уставка и верхний и нижний пределы аварии."},
    {"key": "mode", "group": "Показания", "command": "MODE?", "title": "Режим работы",
     "hint": "Панель выключена, стоп, постоянный режим или программа."},
    {"key": "alarm", "group": "Показания", "command": "ALARM?", "title": "Аварии",
     "hint": "Число аварий и их номера. Номера ищутся в основной инструкции камеры."},
    {"key": "heater", "group": "Показания", "command": "%?", "title": "Мощность нагревателя",
     "hint": "Выход нагревателя в процентах: видно, греет камера или нет."},
    {"key": "ref", "group": "Показания", "command": "REF?", "title": "Работа холодильника",
     "hint": "Работает ли сейчас холодильный агрегат."},
    {"key": "set", "group": "Показания", "command": "SET?", "title": "Настройка холодильника",
     "hint": "REF9 - авто, REF0 - вручную выключен, REF1 - вручную включён."},
    {"key": "relay", "group": "Показания", "command": "RELAY?", "title": "Сигналы времени (реле)",
     "hint": "Какие сигналы времени (выходы реле) включены."},
    {"key": "keyprotect", "group": "Показания", "command": "KEYPROTECT?", "title": "Блокировка пульта",
     "hint": "ON - кнопки пульта заблокированы. Защиту от удалённого управления так не видно."},
    {"key": "rom", "group": "Показания", "command": "ROM?", "title": "Версия прошивки",
     "hint": "Тип и версия прошивки контроллера камеры."},
    {"key": "type", "group": "Показания", "command": "TYPE?", "title": "Тип контроллера",
     "hint": "Тип датчика, тип контроллера и верхний предел уставки."},
    {"key": "srq", "group": "Показания", "command": "SRQ?", "title": "Флаги событий (SRQ)",
     "hint": "8 флагов: 2-й - авария, 3-й - конец удалённой программы, 4-й - включение или выключение."},
    {"key": "mask", "group": "Показания", "command": "MASK?", "title": "Маска событий (SRQ)",
     "hint": "Какие события камера отмечает во флагах SRQ."},
    # --- Уставка и пределы ---
    {"key": "set_temp", "group": "Уставка и пределы", "command": "TEMP, S{temp}", "title": "Задать уставку",
     "hint": "Уставка постоянного режима. Должна быть внутри пределов аварии.",
     "params": [{"name": "temp", "label": "Уставка, °C", "kind": "temp", "default": "25.0"}]},
    {"key": "set_high", "group": "Уставка и пределы", "command": "TEMP, H{high}", "title": "Верхний предел аварии",
     "hint": "Выше этой температуры камера объявит аварию. Не ниже уставки.",
     "params": [{"name": "high", "label": "Верхний предел, °C", "kind": "temp", "default": "100.0"}]},
    {"key": "set_low", "group": "Уставка и пределы", "command": "TEMP, L{low}", "title": "Нижний предел аварии",
     "hint": "Ниже этой температуры камера объявит аварию. Не выше уставки.",
     "params": [{"name": "low", "label": "Нижний предел, °C", "kind": "temp", "default": "-50.0"}]},
    {"key": "set_all", "group": "Уставка и пределы", "command": "TEMP, S{temp} H{high} L{low}",
     "title": "Уставка и оба предела сразу",
     "hint": "Одной строкой: уставка, верхний и нижний пределы аварии.",
     "params": [{"name": "temp", "label": "Уставка, °C", "kind": "temp", "default": "25.0"},
                {"name": "high", "label": "Верхний предел, °C", "kind": "temp", "default": "100.0"},
                {"name": "low", "label": "Нижний предел, °C", "kind": "temp", "default": "-50.0"}]},
    {"key": "set_ref", "group": "Уставка и пределы", "command": "SET, REF{ref}", "title": "Режим холодильника",
     "hint": "0 - вручную выключен, 1 - вручную включён, 2...9 - авто (обычно 9).",
     "params": [{"name": "ref", "label": "REF 0...9", "kind": "int", "default": "9", "min": 0, "max": 9}]},
    # --- Режим работы ---
    {"key": "mode_constant", "group": "Режим работы", "command": "MODE, CONSTANT", "title": "Пуск: постоянный режим",
     "hint": "Камера идёт к уставке и держит её."},
    {"key": "mode_standby", "group": "Режим работы", "command": "MODE, STANDBY", "title": "Стоп",
     "hint": "Камера перестаёт греть и охлаждать, панель остаётся включённой."},
    {"key": "mode_off", "group": "Режим работы", "command": "MODE, OFF", "title": "Выключить панель", "danger": True,
     "hint": "Останавливает камеру и гасит панель. Включается командой «Включить панель»."},
    {"key": "power_on", "group": "Режим работы", "command": "POWER, ON", "title": "Включить панель",
     "hint": "Включает панель и сразу пускает постоянный режим."},
    {"key": "power_off", "group": "Режим работы", "command": "POWER, OFF", "title": "Выключить панель (POWER)",
     "danger": True, "hint": "Останавливает камеру и гасит панель."},
    # --- Удалённая программа ---
    {"key": "run_prgm", "group": "Удалённая программа", "command": "RUN PRGM, TEMP{start} GOTEMP{end} TIME{time}",
     "title": "Плавный переход", "slow": True,
     "hint": "Камера плавно ведёт температуру от начальной к конечной за заданное время и держит конечную.",
     "params": [{"name": "start", "label": "От, °C", "kind": "temp", "default": "25.0"},
                {"name": "end", "label": "До, °C", "kind": "temp", "default": "-40.0"},
                {"name": "time", "label": "За, ч:мм", "kind": "duration", "default": "1:00"}]},
    {"key": "run_prgm_mon", "group": "Удалённая программа", "command": "RUN PRGM MON?", "title": "Ход удалённой программы",
     "slow": True, "hint": "Уставка сейчас и сколько осталось. Пока программа не идёт, камера отвечает отказом."},
    {"key": "run_prgm_get", "group": "Удалённая программа", "command": "RUN PRGM?", "title": "Настройки удалённой программы",
     "slow": True, "hint": "Начальная и конечная температура и время последней удалённой программы."},
    {"key": "prgm_pause", "group": "Удалённая программа", "command": "PRGM, PAUSE", "title": "Пауза программы",
     "slow": True, "hint": "Останавливает ход программы, уставка замирает."},
    {"key": "prgm_continue", "group": "Удалённая программа", "command": "PRGM, CONTINUE", "title": "Продолжить программу",
     "slow": True, "hint": "Снимает программу с паузы."},
    {"key": "prgm_advance", "group": "Удалённая программа", "command": "PRGM, ADVANCE", "title": "Следующий шаг программы",
     "slow": True, "hint": "Только для программы с пульта: пропустить текущий шаг."},
    {"key": "prgm_end_hold", "group": "Удалённая программа", "command": "PRGM, END, HOLD",
     "title": "Закончить программу и держать уставку", "slow": True,
     "hint": "Программа кончается, последняя уставка держится."},
    {"key": "prgm_end_const", "group": "Удалённая программа", "command": "PRGM, END, CONST",
     "title": "Закончить программу и перейти в постоянный режим", "slow": True,
     "hint": "После программы камера держит уставку постоянного режима."},
    {"key": "prgm_end_standby", "group": "Удалённая программа", "command": "PRGM, END, STANDBY",
     "title": "Закончить программу и остановить", "slow": True, "hint": "После программы камера останавливается."},
    {"key": "prgm_end_off", "group": "Удалённая программа", "command": "PRGM, END, OFF",
     "title": "Закончить программу и выключить панель", "slow": True, "danger": True,
     "hint": "После программы камера останавливается и гасит панель."},
    # --- Пульт и служебные ---
    {"key": "key_on", "group": "Пульт и служебные", "command": "KEYPROTECT, ON", "title": "Заблокировать пульт",
     "hint": "Кнопки пульта перестают менять настройки и режим. При выключенной панели не принимается."},
    {"key": "key_off", "group": "Пульт и служебные", "command": "KEYPROTECT, OFF", "title": "Разблокировать пульт",
     "hint": "Кнопки пульта снова работают."},
    {"key": "relay_on", "group": "Пульт и служебные", "command": "RELAY, ON, {relays}", "title": "Включить сигналы времени",
     "hint": "Включает выходы реле с указанными номерами.",
     "params": [{"name": "relays", "label": "Номера через запятую", "kind": "list", "default": "1"}]},
    {"key": "relay_off", "group": "Пульт и служебные", "command": "RELAY, OFF, {relays}", "title": "Выключить сигналы времени",
     "hint": "Выключает выходы реле с указанными номерами.",
     "params": [{"name": "relays", "label": "Номера через запятую", "kind": "list", "default": "1"}]},
    {"key": "set_mask", "group": "Пульт и служебные", "command": "MASK, {mask}", "title": "Маска событий (SRQ)",
     "hint": "8 цифр 0/1: какие события отмечать во флагах SRQ. 01110000 - авария, конец программы, питание.",
     "params": [{"name": "mask", "label": "8 цифр 0/1", "kind": "bits", "default": "01110000"}]},
    {"key": "srq_reset", "group": "Пульт и служебные", "command": "SRQ, RESET", "title": "Сбросить флаги событий",
     "hint": "Обнуляет флаги SRQ."},
    # --- Только новая серия контроллера ---
    {"key": "date_get", "group": "Только новая серия", "command": "DATE?", "title": "Дата часов камеры", "new_only": True,
     "hint": "Дата внутреннего календаря."},
    {"key": "time_get", "group": "Только новая серия", "command": "TIME?", "title": "Время часов камеры", "new_only": True,
     "hint": "Время внутреннего календаря."},
    {"key": "date_set", "group": "Только новая серия", "command": "DATE, {date}", "title": "Задать дату", "new_only": True,
     "hint": "Дата в виде ГГ.ММ/ДД, например 26.10/06.",
     "params": [{"name": "date", "label": "ГГ.ММ/ДД", "kind": "date", "default": ""}]},
    {"key": "time_set", "group": "Только новая серия", "command": "TIME, {clock}", "title": "Задать время", "new_only": True,
     "hint": "Время в виде ЧЧ:ММ:СС.",
     "params": [{"name": "clock", "label": "ЧЧ:ММ:СС", "kind": "clock", "default": ""}]},
    {"key": "constant_set", "group": "Только новая серия", "command": "CONSTANT SET?, TEMP",
     "title": "Уставка постоянного режима №1", "new_only": True, "hint": "Уставка постоянного режима №1."},
    {"key": "prgm_mon", "group": "Только новая серия", "command": "PRGM MON?", "title": "Ход программы с пульта",
     "new_only": True, "slow": True, "hint": "Шаг, уставка, остаток времени и повторы программы с пульта."},
    {"key": "prgm_use", "group": "Только новая серия", "command": "PRGM USE?", "title": "Записанные программы",
     "new_only": True, "slow": True, "hint": "Сколько программ записано на пульте и их номера."},
    {"key": "mode_run", "group": "Только новая серия", "command": "MODE, RUN{pattern}", "title": "Пуск программы с пульта",
     "new_only": True, "slow": True, "hint": "Запускает программу пульта с указанным номером 1...8.",
     "params": [{"name": "pattern", "label": "Номер 1...8", "kind": "int", "default": "1", "min": 1, "max": 8}]},
]
ESPEC_COMMANDS_BY_KEY = {item["key"]: item for item in ESPEC_COMMANDS}


def _espec_param(param: dict, raw) -> str:
    """Один параметр команды в виде, который принимает камера, или ChamberError с причиной."""
    label = param.get("label", param["name"])
    text = str(raw if raw is not None else "").strip().replace(",", ".") if param["kind"] in ("temp", "int") \
        else str(raw if raw is not None else "").strip()
    kind = param["kind"]
    if kind == "temp":
        try:
            value = float(text.replace("°", "").replace("C", "").strip())
        except ValueError:
            raise ChamberError(f"«{label}»: нужно число градусов") from None
        return f"{value:.1f}"
    if kind == "int":
        try:
            value = int(float(text))
        except ValueError:
            raise ChamberError(f"«{label}»: нужно целое число") from None
        low, high = param.get("min"), param.get("max")
        if (low is not None and value < low) or (high is not None and value > high):
            raise ChamberError(f"«{label}»: от {low} до {high}")
        return str(value)
    if kind == "duration":
        match = re.fullmatch(r"(\d{1,4}):([0-5]\d)", text)
        if not match or (int(match.group(1)) == 0 and int(match.group(2)) == 0):
            raise ChamberError(f"«{label}»: время в виде часы:минуты, например 1:30")
        return f"{int(match.group(1))}:{match.group(2)}"
    if kind == "list":
        numbers = [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
        if not numbers or not all(part.isdigit() for part in numbers):
            raise ChamberError(f"«{label}»: номера через запятую, например 1, 2")
        return ", ".join(str(int(part)) for part in numbers)
    if kind == "bits":
        if not re.fullmatch(r"[01]{8}", text):
            raise ChamberError(f"«{label}»: ровно 8 цифр 0 или 1")
        return text
    if kind == "date":
        if not re.fullmatch(r"\d{2}\.\d{2}/\d{2}", text):
            raise ChamberError(f"«{label}»: дата в виде ГГ.ММ/ДД, например 26.10/06")
        return text
    if kind == "clock":
        if not re.fullmatch(r"\d{1,2}:[0-5]\d:[0-5]\d", text):
            raise ChamberError(f"«{label}»: время в виде ЧЧ:ММ:СС")
        return text
    raise ChamberError(f"«{label}»: неизвестный вид параметра")


def build_espec_command(key: str, values: dict | None = None) -> str:
    """Строка команды из каталога по ключу и значениям параметров, без адреса и конца строки."""
    item = ESPEC_COMMANDS_BY_KEY.get(str(key))
    if item is None:
        raise ChamberError(f"нет такой команды: {key}")
    values = values or {}
    filled = {param["name"]: _espec_param(param, values.get(param["name"], param.get("default")))
              for param in item.get("params", [])}
    return item["command"].format(**filled)


def espec_is_setting(command: str) -> bool:
    """Команда настройки (а не запрос): у запросов главная команда кончается на «?»."""
    head = str(command).split(",")[0].strip()
    return not head.endswith("?")


def espec_mode_text(mode: str | None) -> str:
    """Режим камеры словами: «CONSTANT» - «постоянный режим»."""
    if not mode:
        return "—"
    key = " ".join(str(mode).split()).upper()
    return ESPEC_MODE_TEXTS.get(key, key)


def _numbers(answer: str) -> list[str]:
    return [part.strip() for part in str(answer).split(",") if part.strip()]


def _deg(text: str) -> str:
    try:
        return f"{float(text):+.1f} °C".replace(".", ",")
    except ValueError:
        return str(text)


def describe_espec_answer(command: str, answer: str) -> str:
    """Ответ камеры словами для журнала обмена. Пустая строка - пояснить нечего."""
    answer = str(answer).strip()
    upper = answer.upper()
    if upper.startswith("NA:"):
        return EspecChamber._refusal_text(answer[3:].strip())
    if upper.startswith("OK:"):
        return "принято"
    text = str(command).strip()
    first, _, rest = text.partition(",")
    if rest and first.strip().isdigit():
        text = rest.strip()
    head = text.split(",")[0].strip().upper()
    parts = _numbers(answer)
    try:
        if head == "MON?":
            actual, mode, alarms = parse_espec_mon(answer)
            tail = "аварий нет" if not alarms else f"аварий: {alarms}"
            return f"в камере {_deg(str(actual))}, {espec_mode_text(mode)}, {tail}"
        if head == "TEMP?":
            return (f"в камере {_deg(parts[0])}, уставка {_deg(parts[1])}, "
                    f"пределы аварии {_deg(parts[3])} ... {_deg(parts[2])}")
        if head == "MODE?":
            return espec_mode_text(answer)
        if head == "ALARM?":
            count = int(float(parts[0]))
            return "аварий нет" if count == 0 else f"аварий {count}, номера: {', '.join(parts[1:])}"
        if head == "%?":
            return "нагреватель: " + ", ".join(f"{value.replace('.', ',')} %" for value in parts[1:])
        if head == "REF?":
            return "холодильник стоит" if parts[0] == "0" else f"холодильник работает ({', '.join(parts[1:])})"
        if head == "SET?":
            return espec_ref_text(answer)
        if head == "KEYPROTECT?":
            return "пульт заблокирован" if upper == "ON" else "пульт не заблокирован"
        if head == "RELAY?":
            count = int(float(parts[0]))
            return "сигналы времени выключены" if count == 0 else f"включены сигналы: {', '.join(parts[1:])}"
        if head == "TYPE?":
            return f"датчик {parts[0]}, контроллер {parts[-2]}, предел уставки {_deg(parts[-1])}"
        if head == "ROM?":
            return f"прошивка {answer}"
        if head in ("SRQ?", "MASK?"):
            names = {1: "авария", 2: "конец удалённой программы", 3: "включение/выключение"}
            raised = [names[index] for index, bit in enumerate(answer[:8]) if bit == "1" and index in names]
            return "отмечено: " + (", ".join(raised) if raised else "ничего")
        if head == "RUN PRGM MON?":
            return f"уставка сейчас {_deg(parts[1])}, осталось {parts[-2]} (ч:мм)"
    except (ChamberError, IndexError, ValueError):
        return ""
    return ""


def espec_ref_text(answer: str) -> str:
    """Настройка холодильника из ответа SET?: «REF9» - «авто»."""
    text = str(answer).strip().upper()
    if text == "REF0":
        return "холодильник вручную выключен"
    if text == "REF1":
        return "холодильник вручную включён"
    if text.startswith("REF"):
        return f"холодильник: авто ({text})"
    return text


def parse_espec_temp(answer: str) -> tuple[float, float]:
    """Ответ на TEMP?: факт, уставка, верхний и нижний предел аварии. Возвращает (факт, уставка)."""
    parts = [part.strip() for part in str(answer).split(",")]
    try:
        return float(parts[0]), float(parts[1])
    except (IndexError, ValueError):
        raise ChamberError(f"камера ответила непонятно на TEMP?: {str(answer).strip()[:60]}") from None


def parse_espec_limits(answer: str) -> tuple[float | None, float | None]:
    """Пределы аварии из ответа TEMP?: (верхний, нижний). None - камера их не прислала."""
    parts = [part.strip() for part in str(answer).split(",")]
    try:
        return float(parts[2]), float(parts[3])
    except (IndexError, ValueError):
        return None, None


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


def espec_printable(data: bytes) -> bool:
    """Похожи ли байты на ответ ESPEC: только печатные ASCII-символы и концы строк.

    Перевёрнутая пара приёма или чужая скорость дают байты вне этого набора.
    """
    return all(0x20 <= byte <= 0x7E or byte in (0x09, 0x0A, 0x0D) for byte in data)


# Подсказки, какую пару кабеля Moxa UPort - камера проверить (клеммы переходника Mini DB9F-to-TB).
ESPEC_SILENCE_HINT = ("проверьте по порядку: режим порта Moxa в диспетчере устройств - RS-422 или RS-485 4W, "
                      "а не RS-232; адрес, скорость и конец строки - как на пульте (или «Найти камеру»); "
                      "пару 1 - клеммы 1 TxD+ и 2 TxD− переходника на контакты 3 RD+ и 4 RD− камеры. "
                      "Если всё верно - поменяйте местами провода на клеммах 1 и 2")
ESPEC_GARBAGE_HINT = ("скорее всего перевёрнута пара 2: поменяйте местами провода на клеммах 3 RxD+ и 4 RxD− "
                      "переходника (к контактам 1 SD+ и 2 SD− камеры). Реже - на пульте не 8 бит без чётности")


def espec_rx_outcome(data: bytes, delimiter_name: str) -> str:
    """Итог чтения ответа для журнала и счётчиков: ok, silence, garbage, delimiter или cut."""
    data = bytes(data or b"")
    end = ESPEC_DELIMITERS.get(delimiter_name, "\r\n")[-1].encode("ascii")
    if not data:
        return "silence"
    if not espec_printable(data):
        return "garbage"
    if data.endswith(end):
        return "ok"
    if data.endswith((b"\r", b"\n")):
        return "delimiter"
    return "cut"


def espec_no_answer_text(data: bytes, delimiter_name: str) -> str:
    """Почему ответа нет, словами: камера молчит, прислала мусор или другой конец строки.

    Различие подсказывает, какую пару кабеля проверить: молчание - пару 1 (команда
    не доходит до камеры), мусор - пару 2 (ответ камеры искажается по дороге).
    """
    data = bytes(data or b"")
    if not data:
        return "камера молчит: в ответ не пришло ни одного байта. " + ESPEC_SILENCE_HINT
    if not espec_printable(data):
        shown = " ".join(f"{byte:02X}" for byte in data[:12]) + (" ..." if len(data) > 12 else "")
        return f"вместо ответа пришли непонятные байты ({shown}): " + ESPEC_GARBAGE_HINT
    text = data.decode("ascii").strip()
    if data.endswith(b"\r\n"):
        other = "CRLF"
    elif data.endswith(b"\r"):
        other = "CR"
    elif data.endswith(b"\n"):
        other = "LF"
    else:
        other = ""
    if other and other != delimiter_name:
        return (f"камера ответила «{text[:40]}», но её конец строки - {other}, а в программе {delimiter_name}: "
                f"выберите {other} в настройках связи")
    return (f"ответ камеры оборвался: «{text[:40]}». Проверьте конец строки (сейчас {delimiter_name}) и "
            f"надёжность пары 2 - клеммы 3 и 4 переходника")


class EspecChamber(ChamberDriver):
    """Камера ESPEC (MC-811P и другие с тем же протоколом) по RS-485.

    По руководству ESPEC «Network Guide RS-485, RS-232C, GPIB»:
    - строка команды: «адрес,команда[,параметры]» и разделитель (по умолчанию CR LF);
    - TEMP? - факт, уставка и пределы аварии; MON? - факт, режим, число аварий;
    - «TEMP, S-40.0» задаёт уставку, «MODE, CONSTANT» и «MODE, STANDBY» - пуск и стоп;
    - ответ на настройку - «OK:...» или «NA:причина»;
    - после запроса пауза не меньше 0,3 с, после настройки - не меньше 0,5 с;
      у команд программы - 0,5 и 1 с.
    Интерфейс камеры четырёхпроводный: со стороны компьютера это обычный COM-порт
    переходника USB-RS-422/485 с раздельными парами передачи и приёма, например
    Moxa UPort 1150 в режиме RS-422 или RS-485 4W. Порт «auto» находит его сам.

    Кроме главного опроса (MON?, TEMP?) за каждый опрос читается ещё одна
    подробность по кругу: нагреватель, холодильник, его настройка, блокировка
    пульта, ход удалённой программы. Так окно видит всё состояние камеры, а
    опрос остаётся коротким. Версия прошивки и тип контроллера читаются один раз.
    """

    can_set = True
    can_run = True
    MONITOR_PAUSE_S = 0.3
    SETTING_PAUSE_S = 0.5
    PROGRAM_MONITOR_PAUSE_S = 0.5
    PROGRAM_SETTING_PAUSE_S = 1.0
    # Ожидание ответа при поиске настроек связи: молчание на чужом адресе не должно тянуться долго.
    SCAN_TIMEOUT_S = 0.4
    DETAIL_QUERIES = ("%?", "REF?", "SET?", "KEYPROTECT?")
    # Проверка связи из окна: все запросы, которые MC-811P обязана понимать.
    SELFTEST_QUERIES = ("ROM?", "TYPE?", "MON?", "TEMP?", "MODE?", "ALARM?", "%?", "REF?", "SET?", "KEYPROTECT?")

    def __init__(self, port: str, baudrate: int, address: int, delimiter: str = "CRLF", timeout_s: float = 2.0,
                 serial_factory=None, sleep=time.sleep, clock=time.monotonic, comports=None):
        self.port_setting = str(port)
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.address = int(address)
        self.delimiter = ESPEC_DELIMITERS.get(str(delimiter).upper(), "\r\n")
        self.timeout_s = float(timeout_s)
        self._serial_factory = serial_factory
        self._comports = comports
        self._serial = None
        self._sleep = sleep
        self._clock = clock
        self._ready_at = -1e9
        self._details: dict = {}
        self._detail_index = 0
        self._identity_read = False
        # Итог последнего неудачного поиска словами и шаги, где вместо ответа пришёл мусор.
        self.scan_hint = ""
        self._scan_noise: list[tuple[int, int]] = []
        self.title = self._make_title()

    def _make_title(self) -> str:
        auto = self.port_setting.strip().lower() == PORT_AUTO
        if auto and self.port.strip().lower() == PORT_AUTO:
            return f"ESPEC через Moxa UPort (порт ищется), адрес {self.address}"
        return f"ESPEC на {self.port}{' (Moxa UPort)' if auto else ''}, адрес {self.address}"

    @property
    def delimiter_name(self) -> str:
        return next(name for name, value in ESPEC_DELIMITERS.items() if value == self.delimiter)

    def _connect(self):
        if self._serial is not None:
            return
        factory = self._serial_factory
        if factory is None:
            try:
                import serial  # pyserial
            except ImportError:
                raise ChamberError(pyserial_missing_text("RS-485")) from None
            factory = serial.Serial
        try:
            self.port = resolve_port(self.port_setting, self._comports)
        except ChamberError as error:
            self._trace_error("OPEN", str(error))
            raise
        self.title = self._make_title()
        self._trace_event("OPEN", f"открываю {self.port} (в настройках «{self.port_setting}»): {self.baudrate} бод, "
                                  f"8N1, адрес {self.address}, конец строки {self.delimiter_name}, "
                                  f"ожидание ответа {self.timeout_s:g} с")
        try:
            self._serial = factory(port=self.port, baudrate=self.baudrate, parity="N", stopbits=1,
                                   bytesize=8, timeout=self.timeout_s)
        except Exception as error:  # noqa: BLE001 - у pyserial свои классы ошибок
            self._trace_error("OPEN", f"{self.port} не открылся: {type(error).__name__}: {error}")
            raise serial_open_error(self.port, error) from None
        self._trace_open(self._serial, self.port)

    def _read_line(self, started: float | None = None) -> str:
        """Читает строку ответа до конца строки. В журнал - байты, задержка и итог: ok, молчание, мусор..."""
        end = self.delimiter[-1].encode("ascii")
        started = time.perf_counter() if started is None else started
        data = self._serial.read_until(end)
        latency_ms = (time.perf_counter() - started) * 1000.0
        line_errors = serial_line_errors(self._serial)
        outcome = espec_rx_outcome(data, self.delimiter_name)
        if outcome == "silence" and line_errors and not all(name.startswith(("RXOVER", "OVERRUN"))
                                                           for name in line_errors):
            # Байтов нет, но линия шевелилась: сигнал есть, а в байты не собирается.
            outcome = "garbage"
        self._trace_rx(self.port, data, latency_ms, outcome, line_errors)
        if outcome == "ok":
            if self.diag is not None:
                refused = data.decode("ascii").strip().upper().startswith("NA:")
                self.diag.note_exchange("refused" if refused else "ok", latency_ms, data.decode("ascii").strip())
            return data.decode("ascii").strip()
        if not data and outcome == "garbage":
            text = (f"байтов в ответ нет, но порт отметил ошибки линии ({', '.join(line_errors)}): сигнал от камеры, "
                    f"похоже, есть, но не собирается в байты - " + ESPEC_GARBAGE_HINT + ", или не совпадает скорость")
        else:
            text = espec_no_answer_text(data, self.delimiter_name)
        if self.diag is not None:
            self.diag.note_exchange(outcome, latency_ms, text)
        self._trace_error("RX", text)
        raise ChamberError(text)

    def _pause_after(self, command: str, setting: bool) -> float:
        """Пауза руководства после команды: у команд программы она длиннее."""
        program = "PRGM" in str(command).upper()
        if setting:
            return self.PROGRAM_SETTING_PAUSE_S if program else self.SETTING_PAUSE_S
        return self.PROGRAM_MONITOR_PAUSE_S if program else self.MONITOR_PAUSE_S

    def _exchange(self, command: str, setting: bool = False) -> str:
        """Отправляет команду с адресом и возвращает ответ, соблюдая паузы руководства."""
        self._connect()
        wait = self._ready_at - self._clock()
        if wait > 0:
            self._sleep(wait)
        line = f"{self.address},{command}{self.delimiter}"
        try:
            self._serial.reset_input_buffer()
            data = line.encode("ascii")
            self._trace_tx(self.port, data)
            started = time.perf_counter()
            self._serial.write(data)
            answer = self._read_line(started)
            # Протокол OLD с эхом: сначала приходит «OK:команда», данные - следующей строкой.
            if not setting and answer.upper().startswith("OK:"):
                answer = self._read_line()
        except ChamberError:
            raise
        except Exception as error:  # noqa: BLE001
            self._trace_error("SERIAL", f"обмен с {self.port} прервался на «{command}»: "
                                        f"{type(error).__name__}: {error}; порт закрыт, будет открыт заново",
                              with_traceback=True)
            if self.diag is not None:
                self.diag.note_exchange("error", None, str(error))
            self.close()
            raise ChamberError(f"обмен по RS-485 прервался: {error}") from None
        finally:
            self._ready_at = self._clock() + self._pause_after(command, setting)
        if answer.upper().startswith("NA:"):
            text = self._refusal_text(answer[3:].strip())
            self._trace_event("REFUSE", f"«{command}» → {answer}: {text}", "WARN")
            raise ChamberError(text)
        return answer

    @staticmethod
    def _refusal_text(reason: str) -> str:
        """Отказ камеры словами: что именно мешает и что сделать."""
        hints = {
            "PROTECT ON": "на пульте включена защита от удалённого управления, выключите её",
            "DATA OUT OF RANGE": "значение вне допустимых пределов, поправьте пределы аварии",
            "CMD_ERR": "камера не знает такой команды (у MC-811P нет команд новой серии)",
            "COMMAND ERR": "камера не знает такой команды (у MC-811P нет команд новой серии)",
            "PARA ERR": "у команды не хватает параметра или он записан не так",
            "PARAMETER ERR": "у команды не хватает параметра или он записан не так",
            "CHB NOT READY": "камера сейчас не может выполнить команду: не тот режим или выключена панель",
            "CONTROLLER NOT READY": "камера сейчас не может выполнить команду: не тот режим или нет такой функции",
            # Так отвечает контроллер MC-811P (SCP220), например на RELAY? без сигналов времени.
            "CONT NOT READY": "камера сейчас не может выполнить команду: не тот режим или нет такой функции",
            "INVALID REQ": "у этой камеры нет такой функции",
            "DATA NOT READY": "нужных данных нет: программа или таймер не записаны",
        }
        key = next((name for name in hints if name in reason.upper()), None)
        return f"камера отказала ({reason})" + (f": {hints[key]}" if key else "")

    def read(self) -> ChamberReading:
        mon = self._exchange("MON?")
        actual, mode, alarms = parse_espec_mon(mon)
        temp = self._exchange("TEMP?")
        _actual, setpoint = parse_espec_temp(temp)
        high, low = parse_espec_limits(temp)
        details = self._details
        details.update({"mode": mode, "high_c": high, "low_c": low, "alarm_count": alarms})
        alarm_code = alarms
        details["alarms"] = []
        if alarms:
            # Номер первой аварии полезнее их числа: по нему авария ищется в инструкции камеры.
            try:
                numbers = _numbers(self._exchange("ALARM?"))
                details["alarms"] = numbers[1:]
                alarm_code = int(numbers[1]) if len(numbers) > 1 else alarms
            except (ChamberError, ValueError):
                alarm_code = alarms
        self._read_more(mode)
        running = any(mode.startswith(name) for name in ESPEC_RUNNING_MODES)
        return ChamberReading(actual_c=actual, setpoint_c=setpoint, running=running, alarm=alarm_code,
                              details=dict(details))

    def _read_more(self, mode: str):
        """Одна подробность за опрос по кругу, версия и тип контроллера - один раз.

        Отказ или молчание на подробность связь не рвёт: главное уже прочитано.
        """
        queries = list(self.DETAIL_QUERIES)
        if "RUN" in mode:
            queries.append("RUN PRGM MON?" if mode.startswith("RMT") else "PRGM MON?")
        else:
            self._details["program"] = None
        if not self._identity_read:
            self._identity_read = True
            queries_now = ["ROM?", "TYPE?"]
        else:
            queries_now = [queries[self._detail_index % len(queries)]]
            self._detail_index += 1
        for query in queries_now:
            try:
                answer = self._exchange(query)
            except ChamberError:
                continue
            self._note_detail(query, answer)

    def _note_detail(self, query: str, answer: str):
        """Раскладывает ответ подробного запроса по полям состояния."""
        parts = _numbers(answer)
        details = self._details
        try:
            if query == "%?":
                details["heater_pct"] = float(parts[1]) if len(parts) > 1 else None
            elif query == "REF?":
                details["ref_running"] = parts[0] != "0"
            elif query == "SET?":
                details["ref_setting"] = answer.strip().upper()
            elif query == "KEYPROTECT?":
                details["key_protect"] = answer.strip().upper() == "ON"
            elif query == "ROM?":
                details["rom"] = answer.strip()
            elif query == "TYPE?":
                details["type"] = answer.strip()
            elif query in ("RUN PRGM MON?", "PRGM MON?"):
                details["program"] = describe_espec_answer("RUN PRGM MON?", answer) or answer.strip()
        except (IndexError, ValueError):
            pass

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
        return self._exchange(command, setting=espec_is_setting(command))

    def scan(self, should_stop: Callable[[], bool] = lambda: False,
             progress: Callable[[str], None] = lambda text: None) -> dict | None:
        """Ищет скорость, адрес и конец строки, на которых камера отвечает.

        Зачем: если настройки связи на пульте неизвестны, их не нужно перебирать
        руками. Как: на каждом адресе и скорости уходит «адрес,ROM?» с CR LF.
        Камера с концом строки CR или LF тоже видит в нём конец команды и
        отвечает (данными или отказом), а свой конец строки ставит в ответ - по
        нему и узнаётся разделитель. Затем находка проверяется обычным обменом.
        Возвращает {"baud", "address", "delimiter", "rom"} или None.
        """
        addresses = [self.address] + [number for number in range(1, 17) if number != self.address]
        bauds = [self.baudrate] + [baud for baud in ESPEC_BAUDS if baud != self.baudrate]
        total = len(addresses) * len(bauds)
        step = 0
        old_timeout = self.timeout_s
        before = (self.address, self.baudrate, self.delimiter)
        found = None
        self._scan_noise = []
        self.scan_hint = ""
        self._trace_event("SCAN", f"поиск камеры: адреса {addresses[0]}, затем 1...16; скорости {bauds}; "
                                  f"порт {self.port_setting}")
        try:
            for address in addresses:
                for baud in bauds:
                    if should_stop():
                        break
                    step += 1
                    progress(f"Проверяю адрес {address}, {baud} бод ({step} из {total})")
                    found = self._probe(address, baud)
                    if found is not None:
                        self._trace_event("SCAN", f"камера найдена: {found}")
                        return found
                if should_stop():
                    break
        finally:
            if found is None:
                # Камера не нашлась: связь остаётся на прежних настройках.
                if self.baudrate != before[1]:
                    self.close()
                self.address, self.baudrate, self.delimiter = before
                self.scan_hint = self._scan_failure_text()
                self._trace_error("SCAN", f"камера не найдена за {step} шагов из {total}: {self.scan_hint}")
            self.timeout_s = old_timeout
            if self._serial is not None:
                try:
                    self._serial.timeout = old_timeout
                except Exception:  # noqa: BLE001
                    pass
        return None

    def _scan_failure_text(self) -> str:
        """Итог неудачного поиска: мусор на каких-то шагах указывает на пару 2, полное молчание - на пару 1."""
        noise = self._scan_noise
        if noise:
            where = ", ".join(f"адрес {address} на {baud} бод" for address, baud in noise[:3])
            return (f"камера не найдена, но на шагах ({where}) вместо ответа пришли непонятные байты: камера, "
                    f"похоже, отвечает, а ответ искажается - {ESPEC_GARBAGE_HINT}")
        return "камера молчит на всех адресах и скоростях: " + ESPEC_SILENCE_HINT + ". И что на пульте включён RS-485"

    def _probe(self, address: int, baud: int) -> dict | None:
        """Один шаг поиска: ответит ли камера на этом адресе и скорости."""
        if baud != self.baudrate:
            self.close()
            self.baudrate = baud
        self.timeout_s = self.SCAN_TIMEOUT_S
        self._connect()
        self._serial.timeout = self.SCAN_TIMEOUT_S
        wait = self._ready_at - self._clock()
        if wait > 0:
            self._sleep(wait)
        try:
            self._serial.reset_input_buffer()
            probe = f"{address},ROM?\r\n".encode("ascii")
            self._trace_tx(f"{self.port}@{baud}", probe)
            started = time.perf_counter()
            self._serial.write(probe)
            data = self._serial.read_until(b"\n")
            if data and not data.endswith(b"\n"):
                # Камера с концом строки CR: ответ кончится на CR, LF после него не будет.
                data += self._serial.read_until(b"\r") if not data.endswith(b"\r") else b""
            line_errors = serial_line_errors(self._serial)
            outcome = "silence" if not data else ("garbage" if not espec_printable(data) else "answer")
            self._trace_rx(f"{self.port}@{baud}", data, (time.perf_counter() - started) * 1000.0, outcome, line_errors)
            if not data and any(name.startswith(("FRAME", "BREAK", "RXPARITY")) for name in line_errors):
                # Байтов нет, но линия шевелилась: камера, похоже, отвечает, а пара приёма перевёрнута.
                self._scan_noise.append((int(address), int(baud)))
        except Exception as error:  # noqa: BLE001 - на поиске любой сбой значит «здесь камеры нет»
            self._trace_error("SCAN", f"адрес {address}, {baud} бод: {type(error).__name__}: {error}",
                              with_traceback=True)
            self.close()
            return None
        finally:
            self._ready_at = self._clock() + self.MONITOR_PAUSE_S
        if data and not espec_printable(data):
            # Байты пришли, но не текст: камера на этом адресе, похоже, есть, а пара приёма перевёрнута.
            self._scan_noise.append((int(address), int(baud)))
            return None
        if data.endswith(b"\r\n"):
            delimiter = "CRLF"
        elif data.endswith(b"\n"):
            delimiter = "LF"
        elif data.endswith(b"\r"):
            delimiter = "CR"
        else:
            return None
        # Проверка найденного обычным обменом: случайный мусор на линии так не пройдёт.
        self.address = int(address)
        self.delimiter = ESPEC_DELIMITERS[delimiter]
        try:
            rom = self._exchange("ROM?")
        except ChamberError as error:
            text = str(error)
            if "непонятные байты" in text:
                self._scan_noise.append((int(address), int(baud)))
            if "отказала" not in text:
                return None
            rom = text
        self.title = self._make_title()
        self._identity_read = False
        return {"baud": self.baudrate, "address": self.address, "delimiter": delimiter, "rom": rom}

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

def reading_text(reading: ChamberReading | None) -> str:
    """Показание одной строкой для журнала: факт, уставка, состояние, авария, режим ESPEC."""
    if reading is None:
        return "показания нет"
    parts = [f"в камере {reading.actual_c}", f"уставка {reading.setpoint_c}",
             "работает" if reading.running else ("остановлена" if reading.running is not None else "состояние ?"),
             f"авария {reading.alarm}"]
    details = reading.details or {}
    if details.get("mode"):
        parts.append(f"режим {details['mode']}")
    return ", ".join(str(part) for part in parts)


class ChamberLink:
    """Поток связи с камерой: опрос по таймеру и команды из окна.

    Окно ставит команды в очередь и забирает итог через обратный вызов. Связь,
    оборванная ошибкой, восстанавливается сама через паузу. Если задан журнал
    диагностики, в него пишутся команды, их итоги, переходы «связь есть / нет»,
    неожиданные сбои с трассировкой и раз в минуту сводка.
    """

    RECONNECT_PAUSE_S = 5.0

    def __init__(self, driver: ChamberDriver, poll_s: float,
                 on_state: Callable[[dict], None], diag=None):
        self.driver = driver
        self.diag = diag
        if diag is not None:
            driver.diag = diag
        # Камере, которой нельзя слать строки чаще заданного, опрос чаще и не нужен.
        self.poll_s = max(0.2, float(poll_s), float(getattr(driver, "MIN_INTERVAL_S", 0.0)))
        self._on_state = on_state
        self._link_ok: bool | None = None
        self._commands: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="climate-chamber-link")
        self._thread.start()

    def command(self, name: str, value=None):
        """Ставит команду: "setpoint" с градусами, "run" с True/False, "raw" со строкой, "scan" - поиск связи,
        "selftest" - проверка связи набором запросов."""
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
        self._event("LINK", "связь закрыта")

    def _event(self, kind: str, text: str, level: str = "INFO"):
        if self.diag is not None:
            self.diag.event(kind, text, level)

    def _error(self, kind: str, text: str, with_traceback: bool = False):
        if self.diag is not None:
            self.diag.error(kind, text, with_traceback)

    def _note_link(self, ok: bool, text: str = "", reading: ChamberReading | None = None):
        """Переход «связь есть / нет» - один раз на смену, а не на каждый опрос."""
        if ok and self._link_ok is not True:
            self._event("LINK", f"связь есть: {reading_text(reading)}")
        elif not ok and self._link_ok is not False:
            self._error("LINK", f"связь потеряна: {text}")
        self._link_ok = ok
        if ok and self.diag is not None:
            self.diag.maybe_summary(reading_text(reading))

    def _selftest(self) -> list[dict]:
        """Проверка связи: запросы по списку драйвера, у каждого ответ, задержка и итог."""
        queries = tuple(getattr(self.driver, "SELFTEST_QUERIES", ()))
        raw = getattr(self.driver, "raw", None)
        results = []
        self._event("SELFTEST", f"проверка связи: {', '.join(queries) or 'чтение показания'}")
        if raw is None or not queries:
            started = time.perf_counter()
            try:
                answer, ok = reading_text(self.driver.read()), True
            except ChamberError as error:
                answer, ok = str(error), False
            results.append({"query": "показание", "ok": ok, "answer": answer,
                            "ms": round((time.perf_counter() - started) * 1000.0)})
        else:
            for query in queries:
                if self._stop.is_set():
                    break
                started = time.perf_counter()
                try:
                    answer, ok = raw(query), True
                except ChamberError as error:
                    answer, ok = str(error), False
                results.append({"query": query, "ok": ok, "answer": answer,
                                "ms": round((time.perf_counter() - started) * 1000.0)})
        for item in results:
            self._event("SELFTEST", f"{item['query']} → {'ok' if item['ok'] else 'ОШИБКА'} за {item['ms']} мс: "
                                    f"{item['answer']}", "INFO" if item["ok"] else "WARN")
        passed = sum(1 for item in results if item["ok"])
        self._event("SELFTEST", f"итог: {passed} из {len(results)} запросов прошли")
        return results

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
            if name != "poll":
                self._event("CMD", f"{name}" + ("" if value is None else f": {value}"))
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
                    self._event("CMD", f"«{value}» → {answer}")
                    self._on_state({"kind": "raw", "ok": True, "sent": str(value), "text": answer})
                elif name == "scan":
                    scan = getattr(self.driver, "scan", None)
                    if scan is None:
                        raise ChamberError("эта камера не умеет искать настройки связи")
                    found = scan(should_stop=self._stop.is_set,
                                 progress=lambda text: self._on_state({"kind": "scan", "ok": True, "done": False,
                                                                      "text": text}))
                    if found is None:
                        raise ChamberError(getattr(self.driver, "scan_hint", "") or
                                           "камера не ответила ни на одном адресе и скорости: проверьте кабель, "
                                           "режим порта Moxa (RS-422 или RS-485 4W) и что на пульте включён RS-485")
                    self._on_state({"kind": "scan", "ok": True, "done": True, "found": found,
                                    "text": f"камера найдена: адрес {found['address']}, {found['baud']} бод, "
                                            f"конец строки {found['delimiter']}"})
                elif name == "selftest":
                    results = self._selftest()
                    passed = sum(1 for item in results if item["ok"])
                    self._on_state({"kind": "selftest", "ok": passed == len(results), "done": True,
                                    "results": results, "text": f"прошли {passed} из {len(results)} запросов"})
                # После команды показание читается сразу: окно видит её итог.
                reading = self.driver.read()
                self._note_link(True, reading=reading)
                self._on_state({"kind": "reading", "ok": True, "reading": reading})
                next_poll = time.monotonic() + self.poll_s
            except ChamberError as error:
                kind = {"poll": "reading", "raw": "raw", "scan": "scan", "selftest": "selftest"}.get(name, "command")
                if name == "poll":
                    self._note_link(False, str(error))
                else:
                    self._error("CMD", f"{name} не выполнена: {error}")
                self._on_state({"kind": kind, "ok": False, "done": True, "sent": str(value or ""), "text": str(error)})
                next_poll = time.monotonic() + self.RECONNECT_PAUSE_S
            except Exception as error:  # noqa: BLE001 - поток связи не должен падать
                self._error("LINK", f"сбой в потоке связи на «{name}»: {type(error).__name__}: {error}",
                            with_traceback=True)
                self._link_ok = False
                kind = {"scan": "scan", "selftest": "selftest"}.get(name, "reading")
                self._on_state({"kind": kind, "ok": False, "done": True, "text": f"сбой связи: {error}"})
                next_poll = time.monotonic() + self.RECONNECT_PAUSE_S
