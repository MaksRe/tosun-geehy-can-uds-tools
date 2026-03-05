# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for tosun-geehy-can-uds-tools.

Build target:
- `onedir`, because the app depends on external CAN adapter libraries and QML.
- Keeps the `libTSCANAPI/...` folder layout intact so runtime DLL loading works.
"""

from __future__ import annotations

import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


APP_NAME = "tosun-geehy-can-uds-tools"
PROJECT_ROOT = Path(SPECPATH).resolve()
ENTRY_SCRIPT = PROJECT_ROOT / "main.py"

QML_ROOT = PROJECT_ROOT / "ui" / "qml"
RESOURCES_ROOT = PROJECT_ROOT / "resources"
FIRMWARE_ROOT = PROJECT_ROOT / "firmware"
LOGS_ROOT = PROJECT_ROOT / "ui" / "logs"
LIB_TSCAN_ROOT = PROJECT_ROOT / "libTSCANAPI"
WINDOWS_LIB_ROOT = LIB_TSCAN_ROOT / "windows"
LINUX_LIB_ROOT = LIB_TSCAN_ROOT / "linux"

IS_WINDOWS = platform.system().lower().startswith("win")
IS_LINUX = platform.system().lower().startswith("linux")


def collect_tree(src_root: Path, dst_root: str, patterns: tuple[str, ...]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if not src_root.exists():
        return items

    for pattern in patterns:
        for src_file in src_root.rglob(pattern):
            if not src_file.is_file():
                continue
            relative_parent = src_file.relative_to(src_root).parent
            dst_dir = Path(dst_root) / relative_parent
            items.append((str(src_file), str(dst_dir)))

    return items


datas: list[tuple[str, str]] = []

# QML UI and related assets loaded from filesystem by main.py.
datas += collect_tree(
    QML_ROOT,
    "ui/qml",
    ("*.qml", "*.js", "*.json", "*.png", "*.svg", "*.qm", "*.ttf", "*.otf"),
)

# Static resources used by the Python side and icon helpers.
datas += collect_tree(
    RESOURCES_ROOT,
    "resources",
    ("*.qrc", "*.svg", "*.png", "*.ico", "*.json"),
)

# Optional firmware examples shipped with the app.
datas += collect_tree(FIRMWARE_ROOT, "firmware", ("*.bin", "*.hex"))

# Ship docs alongside the build output.
for doc_name in ("README.md", "requirements.txt"):
    doc_path = PROJECT_ROOT / doc_name
    if doc_path.exists():
        datas.append((str(doc_path), "."))

# Ensure the logs folder exists in the packaged app if the source tree has it.
if LOGS_ROOT.exists():
    datas += collect_tree(LOGS_ROOT, "ui/logs", ("*.gitkeep", "*.txt", "*.log"))


binaries: list[tuple[str, str]] = []

# Keep the original library layout because libTSCANAPI/TSDirver.py resolves DLL/SO
# paths relative to the libTSCANAPI package directory.
if IS_WINDOWS:
    binaries += collect_tree(WINDOWS_LIB_ROOT, "libTSCANAPI/windows", ("*.dll",))
elif IS_LINUX:
    binaries += collect_tree(LINUX_LIB_ROOT, "libTSCANAPI/linux", ("*.so",))
else:
    binaries += collect_tree(WINDOWS_LIB_ROOT, "libTSCANAPI/windows", ("*.dll",))
    binaries += collect_tree(LINUX_LIB_ROOT, "libTSCANAPI/linux", ("*.so",))


hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "app_can",
    "app_can.CanDevice",
    "app_can.BaseTranslator",
    "j1939",
    "j1939.j1939_can_identifier",
    "libTSCANAPI",
    "libTSCANAPI.TSCommon",
    "libTSCANAPI.TSDirver",
    "libTSCANAPI.TSMasterDevice",
    "resources",
    "resources.icons",
    "ui",
    "ui.qml",
    "ui.qml.app_controller",
    "ui.qml.collector_csv_manager",
    "uds",
    "uds.bootloader",
    "uds.data_identifiers",
    "uds.options_catalog",
    "uds.uds_identifiers",
]
hiddenimports += collect_submodules("libTSCANAPI")
hiddenimports += collect_submodules("ui.qml.controller")
hiddenimports += collect_submodules("uds.services")

excludes = [
    "PyQt5",
    "PyQt6",
    "tkinter",
    "matplotlib",
    "matplotlib.tests",
    "numpy.tests",
]


a = Analysis(
    [str(ENTRY_SCRIPT)],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
