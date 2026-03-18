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


APP_BASE_NAME = "tosun-geehy-can-uds-tools"
PROJECT_ROOT = Path(SPECPATH).resolve()
ENTRY_SCRIPT = PROJECT_ROOT / "main.py"
VERSION_STATE_FILE = PROJECT_ROOT / ".build_version"
WINDOWS_VERSION_FILE = PROJECT_ROOT / "build" / "version_info_auto.txt"


def _parse_version_parts(raw_text: str) -> tuple[int, int, int]:
    cleaned = str(raw_text or "").strip().replace(",", ".")
    parts = [part for part in cleaned.split(".") if part != ""]
    if len(parts) < 3:
        parts += ["0"] * (3 - len(parts))
    try:
        major = max(0, int(parts[0]))
        minor = max(0, int(parts[1]))
        patch = max(0, int(parts[2]))
    except (TypeError, ValueError):
        return (1, 0, 0)
    return (major, minor, patch)


def bump_build_version() -> tuple[str, tuple[int, int, int]]:
    if VERSION_STATE_FILE.exists():
        current = _parse_version_parts(VERSION_STATE_FILE.read_text(encoding="utf-8"))
    else:
        current = (1, 0, 0)

    major, minor, patch = current
    next_version = (major, minor, patch + 1)
    version_text = f"{next_version[0]}.{next_version[1]}.{next_version[2]}"
    VERSION_STATE_FILE.write_text(version_text + "\n", encoding="utf-8")
    return version_text, next_version


def write_windows_version_file(version_parts: tuple[int, int, int], version_text: str) -> str | None:
    if not IS_WINDOWS:
        return None
    WINDOWS_VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    major, minor, patch = version_parts
    WINDOWS_VERSION_FILE.write_text(
        f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'TOSUN'),
        StringStruct(u'FileDescription', u'{APP_BASE_NAME}'),
        StringStruct(u'FileVersion', u'{version_text}'),
        StringStruct(u'InternalName', u'{APP_BASE_NAME}'),
        StringStruct(u'LegalCopyright', u'Copyright (C) 2026'),
        StringStruct(u'OriginalFilename', u'{APP_BASE_NAME}.exe'),
        StringStruct(u'ProductName', u'{APP_BASE_NAME}'),
        StringStruct(u'ProductVersion', u'{version_text}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return str(WINDOWS_VERSION_FILE)


APP_VERSION_TEXT, APP_VERSION_PARTS = bump_build_version()
APP_NAME = f"{APP_BASE_NAME}_v{APP_VERSION_TEXT}"

QML_ROOT = PROJECT_ROOT / "ui" / "qml"
RESOURCES_ROOT = PROJECT_ROOT / "resources"
FIRMWARE_ROOT = PROJECT_ROOT / "firmware"
LOGS_ROOT = PROJECT_ROOT / "ui" / "logs"
LIB_TSCAN_ROOT = PROJECT_ROOT / "libTSCANAPI"
WINDOWS_LIB_ROOT = LIB_TSCAN_ROOT / "windows"
LINUX_LIB_ROOT = LIB_TSCAN_ROOT / "linux"

IS_WINDOWS = platform.system().lower().startswith("win")
IS_LINUX = platform.system().lower().startswith("linux")
WINDOWS_VERSION_PATH = write_windows_version_file(APP_VERSION_PARTS, APP_VERSION_TEXT)


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
    version=WINDOWS_VERSION_PATH,
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
