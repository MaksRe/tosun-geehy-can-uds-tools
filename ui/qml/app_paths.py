"""Где программа хранит свои данные: настройки (config) и журналы (logs).

ЗАЧЕМ
Собранная программа ставится каждой версией в свою папку:
...\\tosun-geehy-can-uds-tools\\tosun-geehy-can-uds-tools_v1.0.16\\, ..._v1.0.17\\ и т. д.
Раньше её данные лежали во внутренней папке _internal\\ui: их не было видно, а
при установке новой версии все настройки (токен бота, подписчики и их права,
настройки камеры и сайта) оставались в старой папке, и их приходилось вводить
заново. Журналы при этом расходились по двум местам: часть рядом с exe, часть
внутри _internal.

КАК ТЕПЕРЬ
- У собранной программы папка данных - папка с exe: рядом лежат config, logs,
  scenarios.
- При первом запуске новой версии (рядом с exe ещё нет config) настройки и
  сценарии копируются из самой свежей соседней версии той же программы. Старая
  папка не меняется, журналы не копируются.
- При запуске из исходников (разработка) всё как было: папка ui.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

LOG = logging.getLogger(__name__)
# Где в прежних версиях лежали настройки относительно папки версии.
OLD_CONFIG_PLACES = (Path("config"), Path("_internal") / "ui" / "config")


def data_root() -> Path:
    """Папка данных программы: у собранной - папка с exe, при разработке - папка ui."""
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
        try:
            migrate_previous_settings(root)
        except OSError as error:
            LOG.warning("настройки прошлой версии не перенесены: %s", error)
        return root
    return Path(__file__).resolve().parents[1]


def _product_prefix(folder: Path) -> str:
    """Имя программы без версии: «tosun-geehy-can-uds-tools» из «tosun-geehy-can-uds-tools_v1.0.17»."""
    name = folder.name
    return name.rsplit("_v", 1)[0] if "_v" in name else ""


def _newest_previous_config(root: Path) -> tuple[Path, Path] | None:
    """Папка соседней версии с самыми свежими настройками: (папка версии, её config) или None."""
    prefix = _product_prefix(root)
    if not prefix:
        return None
    best = None
    for sibling in root.parent.iterdir():
        if sibling == root or not sibling.is_dir() or _product_prefix(sibling) != prefix:
            continue
        for place in OLD_CONFIG_PLACES:
            config = sibling / place
            files = [item for item in config.glob("*.json") if item.is_file()] if config.is_dir() else []
            if files:
                newest = max(item.stat().st_mtime for item in files)
                if best is None or newest > best[0]:
                    best = (newest, sibling, config)
    return (best[1], best[2]) if best else None


def migrate_previous_settings(root: Path) -> str:
    """Первый запуск новой версии: копирует настройки и сценарии из прошлой версии.

    Ничего не делает, если рядом с exe уже есть config. Возвращает имя папки,
    откуда перенесено, или пустую строку.
    """
    if (root / "config").exists():
        return ""
    found = _newest_previous_config(root)
    if found is None:
        return ""
    sibling, config = found
    target = root / "config"
    target.mkdir(parents=True, exist_ok=True)
    for item in config.glob("*.json"):
        if item.is_file():
            shutil.copy2(item, target / item.name)
    scenarios = sibling / "scenarios"
    if scenarios.is_dir() and not (root / "scenarios").exists():
        (root / "scenarios").mkdir(parents=True, exist_ok=True)
        for item in scenarios.glob("*.json"):
            if item.is_file():
                shutil.copy2(item, root / "scenarios" / item.name)
    (target / "перенесено_из.txt").write_text(f"Настройки перенесены из {sibling}\n", encoding="utf-8")
    LOG.info("настройки перенесены из %s", sibling)
    return sibling.name
