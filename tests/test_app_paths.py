"""Проверки папки данных и переноса настроек при установке новой версии.

Собранная программа ставится каждой версией в свою папку. Тесты закрепляют:
- данные собранной программы - рядом с exe, при разработке - папка ui;
- первый запуск новой версии забирает настройки и сценарии из самой свежей
  соседней версии той же программы (и из старого места _internal\\ui\\config);
- уже заведённые настройки не перезаписываются, чужие папки не трогаются.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.qml import app_paths

APP = "tosun-geehy-can-uds-tools"


def _version(root: Path, version: str, config_place: str | None, files: dict, age_s: float = 0.0) -> Path:
    folder = root / f"{APP}_v{version}"
    folder.mkdir(parents=True)
    (folder / f"{APP}_v{version}.exe").write_bytes(b"")
    if config_place is not None:
        config = folder / config_place
        config.mkdir(parents=True)
        stamp = time.time() - age_s
        for name, text in files.items():
            path = config / name
            path.write_text(text, encoding="utf-8")
            os.utime(path, (stamp, stamp))
    return folder


def _frozen(monkeypatch, exe: Path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))


def test_dev_root_is_ui_folder():
    assert app_paths.data_root() == Path(app_paths.__file__).resolve().parents[1]
    assert app_paths.data_root().name == "ui"


def test_new_version_takes_settings_from_the_newest_previous(tmp_path: Path, monkeypatch):
    _version(tmp_path, "1.0.15", "_internal/ui/config", {"remote_monitor.json": "старые"}, age_s=3600)
    old = _version(tmp_path, "1.0.16", "_internal/ui/config",
                   {"remote_monitor.json": "свежие", "telegram_users.json": "{}"}, age_s=60)
    (old / "scenarios").mkdir()
    (old / "scenarios" / "Цикл.json").write_text("{}", encoding="utf-8")
    _version(tmp_path, "9.9.9", None, {})
    (tmp_path / "другая_программа_v1.0.0" / "config").mkdir(parents=True)
    (tmp_path / "другая_программа_v1.0.0" / "config" / "remote_monitor.json").write_text("чужие", encoding="utf-8")
    new = _version(tmp_path, "1.0.17", None, {})
    _frozen(monkeypatch, new / f"{APP}_v1.0.17.exe")

    assert app_paths.data_root() == new
    assert (new / "config" / "remote_monitor.json").read_text(encoding="utf-8") == "свежие"
    assert (new / "config" / "telegram_users.json").exists()
    assert (new / "scenarios" / "Цикл.json").exists()
    assert "1.0.16" in (new / "config" / "перенесено_из.txt").read_text(encoding="utf-8")
    # Старая папка не тронута.
    assert (old / "_internal" / "ui" / "config" / "remote_monitor.json").read_text(encoding="utf-8") == "свежие"


def test_existing_settings_are_not_overwritten(tmp_path: Path, monkeypatch):
    _version(tmp_path, "1.0.17", "config", {"remote_monitor.json": "предыдущая"}, age_s=10)
    new = _version(tmp_path, "1.0.18", "config", {"remote_monitor.json": "свои"})
    _frozen(monkeypatch, new / f"{APP}_v1.0.18.exe")
    assert app_paths.data_root() == new
    assert (new / "config" / "remote_monitor.json").read_text(encoding="utf-8") == "свои"
    assert not (new / "config" / "перенесено_из.txt").exists()


def test_folder_without_version_is_left_alone(tmp_path: Path, monkeypatch):
    _version(tmp_path, "1.0.16", "_internal/ui/config", {"remote_monitor.json": "x"})
    plain = tmp_path / "камера"
    plain.mkdir()
    _frozen(monkeypatch, plain / "app.exe")
    assert app_paths.data_root() == plain and not (plain / "config").exists()
