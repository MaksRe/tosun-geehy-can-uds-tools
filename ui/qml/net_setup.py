"""Сеть ноутбука для камеры по Ethernet (Zundar EEXTH1000U): адрес проводного адаптера в сети камеры.

Камера с контроллером AZ1000 подключается патч-кордом прямо в Ethernet ноутбука. Чтобы они
увидели друг друга, у проводного адаптера ноутбука должен быть постоянный адрес в той же сети,
что и у камеры (первые три числа совпадают): камера 192.168.0.100 - ноутбук 192.168.0.10, маска
255.255.255.0, без шлюза (иначе интернет Wi-Fi мог бы пойти в кабель).

Что делает модуль:
- находит проводные адаптеры (физические, Ethernet, не Wi-Fi) и их адреса IPv4 - через PowerShell;
- решает, нужно ли что-то менять: адрес в сети камеры уже есть - ничего не трогает;
- сам (при «Подключить») меняет только свободный адаптер: без адреса или с адресом 169.254.x -
  такой Windows ставит, когда кабель идёт прямо в камеру и раздавать адреса некому. Адаптер,
  подключённый к другой сети (рабочая сеть, роутер), сам не трогается: иначе ноутбук потерял бы
  ту сеть; его можно перенастроить только кнопкой, по решению человека;
- задаёт адрес командой netsh. Смена адреса требует прав администратора: Windows один раз
  спросит разрешение (окно UAC), без согласия ничего не меняется;
- возвращает адаптеру автоматический адрес (DHCP), когда камера больше не нужна.
"""

from __future__ import annotations

import ipaddress
import json
import subprocess
import sys
from dataclasses import dataclass

# Последнее число адреса ноутбука в сети камеры; если оно занято самой камерой - следующее.
LAPTOP_HOST = 10
PREFIX = 24
MASK = "255.255.255.0"

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass
class Adapter:
    """Проводной адаптер: имя в Windows, описание, кабель подключён, адреса IPv4 (адрес, длина маски)."""

    name: str
    description: str
    up: bool
    addresses: list

    def other_network(self) -> str:
        """Адрес в другой сети (не 169.254.x) - адаптер занят ею. Пусто - адаптер свободен."""
        for address, _prefix in self.addresses:
            try:
                ip = ipaddress.IPv4Address(address)
            except ValueError:
                continue
            if not ip.is_link_local:
                return address
        return ""


def _powershell(command: str, timeout_s: float = 20.0) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout_s, creationflags=_NO_WINDOW)


def _as_list(payload) -> list:
    if payload is None:
        return []
    return payload if isinstance(payload, list) else [payload]


def parse_adapters(adapters_json: str, addresses_json: str) -> list[Adapter]:
    """Разбор ответов PowerShell: Get-NetAdapter -Physical и Get-NetIPAddress -AddressFamily IPv4."""
    try:
        adapters = _as_list(json.loads(adapters_json or "null"))
        addresses = _as_list(json.loads(addresses_json or "null"))
    except ValueError:
        return []
    result = []
    for item in adapters:
        media = str(item.get("MediaType") or "")
        description = str(item.get("InterfaceDescription") or "")
        # Только проводной Ethernet: Wi-Fi («Native 802.11»), Bluetooth и прочее не годятся.
        if media and media != "802.3":
            continue
        if any(word in description.lower() for word in ("wi-fi", "wireless", "bluetooth", "802.11")):
            continue
        name = str(item.get("Name") or "")
        own = [(str(row.get("IPAddress")), int(row.get("PrefixLength") or 0)) for row in addresses
               if str(row.get("InterfaceAlias") or "") == name]
        status = str(item.get("Status") or "").lower()
        result.append(Adapter(name=name, description=description, up=status == "up", addresses=own))
    # Сначала адаптеры с подключённым кабелем, из них - свободные (без адреса другой сети).
    result.sort(key=lambda adapter: (not adapter.up, bool(adapter.other_network()), adapter.name))
    return result


def list_wired_adapters() -> list[Adapter]:
    """Проводные адаптеры ноутбука с адресами IPv4. Пустой список - PowerShell недоступен или адаптеров нет."""
    if sys.platform != "win32":
        return []
    try:
        adapters = _powershell("Get-NetAdapter -Physical | Select-Object Name,InterfaceDescription,Status,MediaType "
                               "| ConvertTo-Json -Compress")
        addresses = _powershell("Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias,IPAddress,"
                                "PrefixLength | ConvertTo-Json -Compress")
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_adapters(adapters.stdout, addresses.stdout)


def camera_network(host: str) -> ipaddress.IPv4Network | None:
    """Сеть /24 камеры по её адресу. None - адрес не IPv4."""
    try:
        return ipaddress.IPv4Network(f"{ipaddress.IPv4Address(str(host).strip())}/{PREFIX}", strict=False)
    except ValueError:
        return None


def laptop_address(host: str) -> str | None:
    """Адрес ноутбука в сети камеры: та же сеть, последнее число 10 (или 11, если 10 - у камеры)."""
    network = camera_network(host)
    if network is None:
        return None
    camera = ipaddress.IPv4Address(str(host).strip())
    last = LAPTOP_HOST if int(camera) & 0xFF != LAPTOP_HOST else LAPTOP_HOST + 1
    return str(ipaddress.IPv4Address((int(network.network_address) & ~0xFF) | last))


def adapter_in_network(adapters: list[Adapter], host: str) -> Adapter | None:
    """Адаптер, у которого уже есть адрес в сети камеры (кроме адреса самой камеры)."""
    network = camera_network(host)
    if network is None:
        return None
    for adapter in adapters:
        for address, _prefix in adapter.addresses:
            try:
                if ipaddress.IPv4Address(address) in network and address != str(host).strip():
                    return adapter
            except ValueError:
                continue
    return None


def plan(host: str, adapters: list[Adapter], force: bool = False) -> dict:
    """Что сделать: ok - уже настроено; set - задать адрес адаптеру; error - почему нельзя.

    force - решение человека (кнопка): перенастроить и адаптер, подключённый к другой сети.
    """
    network = camera_network(host)
    if network is None:
        return {"action": "error", "text": f"адрес камеры «{host}» - не IPv4: впишите IP камеры, например 192.168.0.100"}
    ready = adapter_in_network(adapters, host)
    if ready is not None:
        address = next(address for address, _prefix in ready.addresses
                       if ipaddress.IPv4Address(address) in network)
        return {"action": "ok", "adapter": ready.name,
                "text": f"сеть уже настроена: «{ready.name}» {address} в сети камеры {network}"}
    if not adapters:
        return {"action": "error", "text": "проводной адаптер Ethernet не найден: подключите кабель или переходник "
                                           "USB-Ethernet"}
    adapter = adapters[0]
    if not adapter.up:
        return {"action": "error", "text": f"кабель не подключён к «{adapter.name}»: вставьте патч-корд от разъёма LAN "
                                           "камеры и включите камеру"}
    busy = adapter.other_network()
    if busy and not force:
        return {"action": "error", "text": f"«{adapter.name}» уже в другой сети ({busy}): сама его не перенастраиваю, "
                                           "чтобы ноутбук не потерял ту сеть. Если кабель камеры вставлен в этот разъём, "
                                           "нажмите «Настроить сеть ноутбука»"}
    return {"action": "set", "adapter": adapter.name, "address": laptop_address(host), "mask": MASK,
            "text": f"задам «{adapter.name}» адрес {laptop_address(host)}, маска {MASK}, без шлюза"}


def netsh_static(adapter: str, address: str, mask: str = MASK) -> list[str]:
    """Команда netsh: постоянный адрес без шлюза."""
    return ["interface", "ipv4", "set", "address", f'name="{adapter}"', "source=static",
            f"address={address}", f"mask={mask}"]


def netsh_dhcp(adapter: str) -> list[str]:
    """Команда netsh: вернуть автоматический адрес (DHCP)."""
    return ["interface", "ipv4", "set", "address", f'name="{adapter}"', "source=dhcp"]


def run_elevated_netsh(arguments: list[str], timeout_s: float = 90.0) -> tuple[bool, str]:
    """netsh с правами администратора: Windows спрашивает разрешение. (успех, текст)."""
    if sys.platform != "win32":
        return False, "настройка сети - только в Windows"
    joined = " ".join(arguments).replace("'", "''")
    command = (f"try {{ $p = Start-Process -FilePath netsh.exe -ArgumentList '{joined}' -Verb RunAs -Wait "
               f"-PassThru -WindowStyle Hidden; exit $p.ExitCode }} catch {{ exit 1223 }}")
    try:
        result = _powershell(command, timeout_s)
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"не удалось запустить netsh: {error}"
    if result.returncode == 1223:
        return False, "Windows не дала прав администратора (отказ в окне разрешения): сеть не изменена"
    if result.returncode != 0:
        return False, f"netsh завершился с кодом {result.returncode}: сеть не изменена"
    return True, "готово"


def apply(host: str, force: bool = False) -> tuple[bool, str]:
    """Настроить сеть ноутбука для камеры host. (успех, текст для человека). force - по кнопке."""
    adapters = list_wired_adapters()
    step = plan(host, adapters, force)
    if step["action"] == "ok":
        return True, step["text"][:1].upper() + step["text"][1:] + "."
    if step["action"] == "error":
        return False, step["text"][:1].upper() + step["text"][1:] + "."
    ok, text = run_elevated_netsh(netsh_static(step["adapter"], step["address"], step["mask"]))
    if not ok:
        return False, text[:1].upper() + text[1:] + "."
    again = adapter_in_network(list_wired_adapters(), host)
    if again is None:
        return False, (f"Адрес {step['address']} задан «{step['adapter']}», но Windows его ещё не показывает: "
                       "подождите несколько секунд и нажмите «Подключить».")
    return True, f"Сеть настроена: «{step['adapter']}» {step['address']}, маска {MASK}. Камера {host} в той же сети."


def restore(host: str) -> tuple[bool, str]:
    """Вернуть автоматический адрес адаптеру, настроенному для камеры host."""
    adapter = adapter_in_network(list_wired_adapters(), host)
    if adapter is None:
        return True, "Адаптера с адресом в сети камеры нет: возвращать нечего."
    ok, text = run_elevated_netsh(netsh_dhcp(adapter.name))
    if not ok:
        return False, text[:1].upper() + text[1:] + "."
    return True, f"«{adapter.name}» снова получает адрес автоматически (DHCP)."
