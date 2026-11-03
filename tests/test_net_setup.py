"""Сеть ноутбука для камеры по Ethernet: адрес проводного адаптера в сети камеры Zundar.

Тесты закрепляют:
- из ответа PowerShell берутся только проводные адаптеры (Wi-Fi и Bluetooth - нет), с кабелем - первыми;
- адрес ноутбука - в сети /24 камеры, последнее число 10 (11, если 10 - у камеры), без шлюза;
- уже настроенный адаптер не трогается (окно разрешения не появляется); нет кабеля - сказано;
- команды netsh: постоянный адрес и возврат DHCP; отказ в правах - сеть не меняется;
- «Подключить» камеру Zundar само проверяет и настраивает сеть - один раз для этого адреса камеры.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml import net_setup
from ui.qml.net_setup import Adapter

ADAPTERS = json.dumps([
    {"Name": "Беспроводная сеть", "InterfaceDescription": "Intel(R) Wi-Fi 6 AX201", "Status": "Up",
     "MediaType": "Native 802.11"},
    {"Name": "Ethernet", "InterfaceDescription": "Realtek PCIe GbE Family Controller", "Status": "Up",
     "MediaType": "802.3"},
    {"Name": "Ethernet 2", "InterfaceDescription": "ASIX AX88179 USB 3.0 to Gigabit Ethernet", "Status": "Disconnected",
     "MediaType": "802.3"},
], ensure_ascii=False)
ADDRESSES = json.dumps([
    {"InterfaceAlias": "Беспроводная сеть", "IPAddress": "10.20.0.57", "PrefixLength": 24},
    {"InterfaceAlias": "Ethernet", "IPAddress": "169.254.12.7", "PrefixLength": 16},
], ensure_ascii=False)


def test_only_wired_adapters_with_cable_first():
    adapters = net_setup.parse_adapters(ADAPTERS, ADDRESSES)
    assert [adapter.name for adapter in adapters] == ["Ethernet", "Ethernet 2"]
    assert adapters[0].up and adapters[0].addresses == [("169.254.12.7", 16)]
    # Один адаптер PowerShell отдаёт объектом, а не списком.
    single = net_setup.parse_adapters(json.dumps(json.loads(ADAPTERS)[1]), "null")
    assert [adapter.name for adapter in single] == ["Ethernet"]
    assert net_setup.parse_adapters("не json", "") == []


def test_laptop_address_is_in_the_camera_network():
    assert net_setup.laptop_address("192.168.0.100") == "192.168.0.10"
    assert net_setup.laptop_address("192.168.5.10") == "192.168.5.11"
    assert net_setup.laptop_address("камера") is None


def test_plan_sets_the_address_or_says_why_not():
    adapters = net_setup.parse_adapters(ADAPTERS, ADDRESSES)
    step = net_setup.plan("192.168.0.100", adapters)
    assert step["action"] == "set" and step["adapter"] == "Ethernet" and step["address"] == "192.168.0.10"
    ready = [Adapter("Ethernet", "", True, [("192.168.0.10", 24)])]
    assert net_setup.plan("192.168.0.100", ready)["action"] == "ok", "уже настроено - не трогать"
    unplugged = [Adapter("Ethernet", "", False, [])]
    step = net_setup.plan("192.168.0.100", unplugged)
    assert step["action"] == "error" and "кабель не подключён" in step["text"]
    assert "не найден" in net_setup.plan("192.168.0.100", [])["text"]
    assert "не IPv4" in net_setup.plan("abc", adapters)["text"]


def test_adapter_on_another_network_is_not_touched_by_itself():
    """Проводной адаптер в рабочей сети (не 169.254.x): сама программа его не меняет - только по кнопке."""
    office = [Adapter("Ethernet 5", "Realtek", True, [("192.168.19.31", 24)])]
    step = net_setup.plan("192.168.0.100", office)
    assert step["action"] == "error" and "уже в другой сети (192.168.19.31)" in step["text"]
    assert net_setup.plan("192.168.0.100", office, force=True)["action"] == "set"
    # Свободный адаптер (кабель прямо в камеру) - выбирается раньше занятого.
    both = net_setup.parse_adapters(json.dumps([
        {"Name": "Офис", "InterfaceDescription": "Intel I219", "Status": "Up", "MediaType": "802.3"},
        {"Name": "Камера", "InterfaceDescription": "ASIX USB", "Status": "Up", "MediaType": "802.3"}]),
        json.dumps([{"InterfaceAlias": "Офис", "IPAddress": "10.1.1.5", "PrefixLength": 24},
                    {"InterfaceAlias": "Камера", "IPAddress": "169.254.3.3", "PrefixLength": 16}]))
    assert net_setup.plan("192.168.0.100", both)["adapter"] == "Камера"


def test_netsh_commands_have_no_gateway():
    static = net_setup.netsh_static("Ethernet 2", "192.168.0.10")
    assert static == ["interface", "ipv4", "set", "address", 'name="Ethernet 2"', "source=static",
                      "address=192.168.0.10", "mask=255.255.255.0"]
    assert not any("gateway" in part for part in static)
    assert net_setup.netsh_dhcp("Ethernet")[-1] == "source=dhcp"


def test_apply_and_restore(monkeypatch):
    state = {"adapters": net_setup.parse_adapters(ADAPTERS, ADDRESSES), "calls": []}
    monkeypatch.setattr(net_setup, "list_wired_adapters", lambda: state["adapters"])

    def elevated(arguments):
        state["calls"].append(arguments)
        if "source=static" in arguments:
            state["adapters"] = [Adapter("Ethernet", "", True, [("192.168.0.10", 24)])]
        return True, "готово"
    monkeypatch.setattr(net_setup, "run_elevated_netsh", elevated)
    ok, text = net_setup.apply("192.168.0.100")
    assert ok and "192.168.0.10" in text and len(state["calls"]) == 1
    ok, text = net_setup.apply("192.168.0.100")
    assert ok and text.startswith("Сеть уже настроена") and len(state["calls"]) == 1, "второй раз - без окна"
    ok, text = net_setup.restore("192.168.0.100")
    assert ok and "DHCP" in text and state["calls"][-1][-1] == "source=dhcp"
    monkeypatch.setattr(net_setup, "run_elevated_netsh",
                        lambda arguments: (False, "Windows не дала прав администратора"))
    state["adapters"] = net_setup.parse_adapters(ADAPTERS, ADDRESSES)
    ok, text = net_setup.apply("192.168.0.100")
    assert not ok and "прав администратора" in text


def test_connect_to_zundar_sets_up_the_network_once(tmp_path, monkeypatch):
    from tests.test_climate_supervisor import _SupStub

    calls = []
    monkeypatch.setattr(net_setup, "apply",
                        lambda host, force=False: (calls.append((host, force)), (True, "Сеть настроена."))[1])
    stub = _SupStub(tmp_path)
    stub._climate_link = None
    assert stub._climate_set("driver", "zundar_az1000")
    started = []
    monkeypatch.setattr("ui.qml.controller.climate_chamber_mixin.ChamberLink",
                        lambda *args, **kwargs: started.append(args) or type("L", (), {"close": lambda self: None,
                                                                                     "driver": None})())
    stub._climate_connect()
    stub._climate_connect()
    for _ in range(100):
        if calls and not stub._climate_net_busy:
            break
        stub._climate_take_incoming(0.0)
        __import__("time").sleep(0.02)
    assert calls == [("192.168.0.100", False)], "сама - не чаще раза для адреса камеры и без перенастройки чужой сети"
    assert stub._climate_net_ok is True and stub._climate_net_status == "Сеть настроена."
    stub._climate_link = None
