"""Эмуляция полной автоматической пробной калибровки: настоящий контроллер и модель прибора."""
import struct
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

app = QGuiApplication(sys.argv[:1])

import profile_model  # noqa: E402
from uds.data_identifiers import UdsData  # noqa: E402
from uds.options_catalog import get_option_by_did  # noqa: E402
from ui.qml.app_controller import AppController  # noqa: E402
from ui.qml.controller import profile_mixin as pm  # noqa: E402
from ui.qml.controller import trial_mixin as tm  # noqa: E402

LATENCY_MS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
RUN_S = float(sys.argv[2]) if len(sys.argv) > 2 else 240.0
PENDING_S = float(sys.argv[3]) if len(sys.argv) > 3 else 0.12
# Сколько прибор молчит после команды перезапуска, прежде чем ответит загрузчик.
REBOOT_S = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
# 1 - после перезапуска прибор остаётся в загрузчике навсегда.
STUCK_IN_BOOT = len(sys.argv) > 5 and sys.argv[5] == "1"

RX_ID = 0x18DAF16A
RAW_MAIN = 13141
RAW_MEDIA = 4672
T0 = time.monotonic()
EVENTS = []


def stamp():
    return f"{(time.monotonic() - T0):7.2f} с"


def pid(var):
    return int(var.pid) & 0xFFFF


PROFILE_ORDER = [(name, did) for name, did, _title, _width in pm.AppControllerProfileMixin.PROFILE_TABLES]
PROFILE_SIZES = {did: 14 * width for _name, did, _title, width in pm.AppControllerProfileMixin.PROFILE_TABLES}
PROFILE_SIZES[pm.DID_NODES] = 14


class Device:
    """Прибор: память параметров, расчёт уровня и компенсации, один канал ISO-TP."""

    def __init__(self):
        self.store = {}
        self.emul = None
        self.pending_until = 0.0
        self.dropped = 0
        self.resets = 0
        self.nrc = 0
        # После перезапуска: до offline_until прибор молчит, до boot_until отвечает загрузчик.
        self.offline_until = 0.0
        self.boot_until = 0.0

        self.put(pid(UdsData.empty_fuel_tank), struct.pack("<H", 12128))
        self.put(pid(UdsData.full_fuel_tank), struct.pack("<H", 16128))
        self.put(pid(UdsData.fuel_zero_trim_count), struct.pack("<h", 0))
        self.put(pid(UdsData.fuel_media_comp_enable), bytes([0]))
        self.put(pid(UdsData.fuel_media_flatcap_air_count), struct.pack("<H", 0))
        self.put(pid(UdsData.fuel_media_flatcap_cal_count), struct.pack("<H", 0))
        self.put(pid(tm.VAR_FREEZE_PCT), bytes([40]))
        self.put(pid(tm.VAR_TANK_MODEL), bytes([0]))
        for name, did in PROFILE_ORDER:
            if name == "nodes":
                self.put(did, struct.pack("<7h", *pm.AppControllerProfileMixin.PROFILE_DEFAULT_NODES))
            else:
                self.put(did, bytes(PROFILE_SIZES[did]))
        self.put(pm.DID_ALGORITHM, struct.pack("<H", 1))
        self.put(pm.DID_GENERATION, struct.pack("<H", 1))
        self.put(pm.DID_CRC, struct.pack("<H", self.actual_crc()))

        self.resp_timer = QTimer()
        self.resp_timer.setSingleShot(True)
        self.resp_timer.timeout.connect(self.send_response)
        self.next_response = None
        self.rx_buffer = None
        self.rx_total = 0
        self.tx_cfs = []

    # ------------------------------------------------------------------ память и расчёт

    def put(self, did, data):
        self.store[did] = bytes(data)

    def u16(self, did):
        return struct.unpack("<H", self.store[did][:2])[0]

    def s16(self, did):
        return struct.unpack("<h", self.store[did][:2])[0]

    def profile(self):
        result = {}
        for name, did in PROFILE_ORDER:
            data = self.store[did]
            result[name] = list(struct.unpack(f"<{len(data) // 2}h", data))
        return result

    def actual_crc(self):
        return pm.AppControllerProfileMixin._profile_crc16(b"".join(self.store[did] for _name, did in PROFILE_ORDER))

    def trusted(self):
        return self.u16(pm.DID_CRC) == self.actual_crc() and self.u16(pm.DID_ALGORITHM) == 1

    def temps(self):
        if self.emul is not None:
            return self.emul, self.emul
        return 275, 309

    def chain(self):
        fuel_t, board_t = self.temps()
        return profile_model.predict_main(
            RAW_MAIN, self.profile(), board_temp_x10=board_t, tube_temp_x10=fuel_t,
            trusted=self.trusted(), zero_trim=self.s16(pid(UdsData.fuel_zero_trim_count)))

    def level(self):
        empty, full = self.u16(pid(UdsData.empty_fuel_tank)), self.u16(pid(UdsData.full_fuel_tank))
        comp = self.chain()["compensated"]
        if full <= empty:
            return 0
        return max(0, min(1000, (comp - empty) * 1000 // (full - empty)))

    def rf(self):
        enable = self.store[pid(UdsData.fuel_media_comp_enable)][0]
        air = self.u16(pid(UdsData.fuel_media_flatcap_air_count))
        cal = self.u16(pid(UdsData.fuel_media_flatcap_cal_count))
        freeze = self.store[pid(tm.VAR_FREEZE_PCT)][0]
        if not enable or cal <= air or self.level() < freeze * 10:
            return 1000
        return (RAW_MEDIA - air) * 1000 // (cal - air)

    def read(self, did):
        fuel_t, board_t = self.temps()
        mode = (profile_model.MODE_MAIN_LUT | profile_model.MODE_TUBE_MAIN) if self.trusted() else 0
        computed = {
            pid(UdsData.curr_fuel_tank): struct.pack("<H", RAW_MAIN),
            pid(UdsData.fuel_media_flatcap_raw): struct.pack("<H", RAW_MEDIA),
            pid(UdsData.raw_temperature): struct.pack("<h", fuel_t),
            pid(UdsData.raw_board_temperature): struct.pack("<h", board_t),
            pid(UdsData.temperature_emulation_x10): struct.pack("<H", 0x8000 if self.emul is None else self.emul & 0xFFFF),
            pid(UdsData.fuel_compensated_period): struct.pack("<H", self.chain()["compensated"]),
            pid(UdsData.fuel_board_stage_period): struct.pack("<H", self.chain()["board_stage"]),
            pid(UdsData.fuel_board_stage_mode): bytes([mode]),
            pid(UdsData.raw_fuel_level): struct.pack("<h", self.level()),
            pid(UdsData.fuel_media_rf_x1000): struct.pack("<H", self.rf()),
            pid(UdsData.fuel_thermal_profile_status): bytes([0x01 | 0x02 | 0x04 | (0x08 if self.trusted() else 0)]
                                                            if self.trusted() else [0x01]),
            pm.DID_CRC_ACTUAL: struct.pack("<H", self.actual_crc()),
            pid(UdsData.eeprom_state): bytes([2 if time.monotonic() < self.pending_until else 0, 0, 0, 0]),
            pid(tm.VAR_ACTIVE_PROGRAM): bytes([0]),
        }
        if did in computed:
            return computed[did]
        return self.store.get(did)

    def write(self, did, data):
        if did == pid(UdsData.temperature_emulation_x10):
            value = struct.unpack("<h", bytes(data[:2]))[0]
            self.emul = None if (value & 0xFFFF) == 0x8000 else value
            return None
        if did not in self.store:
            return 0x31
        value = struct.unpack("<H", bytes(data[:2]))[0] if len(data) >= 2 else 0
        if did == pid(UdsData.empty_fuel_tank) and value >= self.u16(pid(UdsData.full_fuel_tank)):
            return 0x22
        if did == pid(UdsData.full_fuel_tank) and value <= self.u16(pid(UdsData.empty_fuel_tank)):
            return 0x22
        size = len(self.store[did])
        self.put(did, (bytes(data) + bytes(size))[:size])
        self.pending_until = time.monotonic() + PENDING_S
        return None

    # ------------------------------------------------------------------ ISO-TP

    def on_frame(self, data):
        if time.monotonic() < self.offline_until:
            return
        pci = data[0] >> 4
        if pci == 0:
            if self.rx_buffer is not None:
                self.dropped += 1
                EVENTS.append(f"{stamp()}  !!! короткий запрос оборвал приём длинной записи")
                self.rx_buffer = None
            self.accept(list(data[1:1 + (data[0] & 0x0F)]))
        elif pci == 1:
            if self.rx_buffer is not None:
                self.dropped += 1
                EVENTS.append(f"{stamp()}  !!! новая длинная запись оборвала прежнюю")
            self.rx_total = ((data[0] & 0x0F) << 8) | data[1]
            self.rx_buffer = list(data[2:8])
            self.later(1, [0x30, 0x08, 0x00])
        elif pci == 2:
            if self.rx_buffer is None:
                return
            self.rx_buffer += list(data[1:8])
            if len(self.rx_buffer) >= self.rx_total:
                body = self.rx_buffer[:self.rx_total]
                self.rx_buffer = None
                self.accept(body)
        elif pci == 3 and self.tx_cfs:
            frames, self.tx_cfs = self.tx_cfs, []
            for index, frame in enumerate(frames):
                self.later(1 + index, frame)

    def accept(self, body):
        sid = body[0]
        in_boot = (STUCK_IN_BOOT and self.resets > 0) or time.monotonic() < self.boot_until
        if sid == 0x22:
            did = (body[1] << 8) | body[2]
            if in_boot:
                # Загрузчик знает только тип активной программы и адрес.
                data = bytes([1]) if did == pid(tm.VAR_ACTIVE_PROGRAM) else None
            else:
                data = self.read(did)
            response = [0x7F, 0x22, 0x31] if data is None else [0x62, body[1], body[2]] + list(data)
        elif sid == 0x2E:
            did = (body[1] << 8) | body[2]
            nrc = self.write(did, body[3:])
            response = [0x6E, body[1], body[2]] if nrc is None else [0x7F, 0x2E, nrc]
        elif sid == 0x11:
            response = [0x51, body[1]]
        elif sid in (0x10, 0x27, 0x3E):
            response = [sid + 0x40] + body[1:2]
        else:
            return
        if response[0] == 0x7F:
            self.nrc += 1
            EVENTS.append(f"{stamp()}  отказ {' '.join(f'{b:02X}' for b in response)} на {' '.join(f'{b:02X}' for b in body[:3])}")
        if self.resp_timer.isActive() or self.tx_cfs:
            self.dropped += 1
            EVENTS.append(f"{stamp()}  !!! запрос {' '.join(f'{b:02X}' for b in body[:3])} затёр неотправленный ответ "
                          f"{' '.join(f'{b:02X}' for b in (self.next_response or [])[:3])}")
            self.tx_cfs = []
        self.next_response = response
        self.resp_timer.start(LATENCY_MS)

    def send_response(self):
        payload = self.next_response
        self.next_response = None
        if payload[0] == 0x51:
            self.resets += 1
            self.emul = None
            self.offline_until = time.monotonic() + REBOOT_S
            self.boot_until = self.offline_until + 1.0
        if len(payload) <= 7:
            self.deliver([len(payload)] + payload)
            return
        total = len(payload)
        self.deliver([0x10 | ((total >> 8) & 0x0F), total & 0xFF] + payload[:6])
        frames, sn, index = [], 1, 6
        while index < total:
            frames.append([0x20 | sn] + payload[index:index + 7])
            index += 7
            sn = (sn + 1) & 0x0F
        self.tx_cfs = frames

    def later(self, ms, frame):
        QTimer.singleShot(ms, lambda f=list(frame): self.deliver(f))

    def deliver(self, frame):
        payload = (list(frame) + [0xFF] * 8)[:8]
        ctrl._on_can_message(f"{time.perf_counter():.6f}", hex(RX_ID), "Rx", "8", payload)


device = Device()
ctrl = AppController()
can = ctrl._can
can._is_connect = True
can._is_trace = True


def fake_send(iden, dlc, data):
    iden = int(iden) & 0x1FFFFFFF
    if ((iden >> 16) & 0xFF) == 0xDA and ((iden >> 8) & 0xFF) == 0x6A:
        device.on_frame([int(b) & 0xFF for b in data[:8]])
    return 0


can.send_async = fake_send

ctrl._calibration_active = True
ctrl._calibration_session_ready = True
ctrl._service_security_unlocked = True
ctrl._service_access_target_sa = 0x6A
ctrl._start_calibration_poll_timer()
ctrl._trial_set_live_enabled(True)

assert ctrl._trial_auto_start(), "автоматический прогон не запустился"
started = time.monotonic()


def check():
    if ctrl._trial_auto_active and time.monotonic() - started < RUN_S:
        return
    poll.stop()
    print(f"задержка ответа {LATENCY_MS} мс, запись в память {PENDING_S:.2f} с, прошло {time.monotonic() - started:.1f} с")
    print("ИТОГ:", ctrl._trial_status)
    for row in ctrl._trial_step_rows():
        print(f"{row['number']:>2}. {row['statusText']:<15} {row['duration']:>7}  {row['title']}")
        if row["status"] in ("fail", "warn"):
            for line in row["detail"].splitlines():
                print("      ", line)
    print("затёрто запросов:", device.dropped, "| отказов прибора:", device.nrc, "| перезапусков:", device.resets)
    print("шапка памяти:", ctrl._eeprom_commit_view()["text"])
    print("--- события")
    for line in EVENTS[:40]:
        print(line)
    app.quit()


poll = QTimer()
poll.setInterval(200)
poll.timeout.connect(check)
poll.start()
sys.exit(app.exec())
