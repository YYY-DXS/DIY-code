# -*- mode: python ; coding: utf-8 -*-

import os

# 代码签名要求 exe 带产品名/版本等元数据。CI 通过 PYI_VERSION_FILE 传入生成的版本资源；
# 本地不设置该变量时，构建行为与以前完全一致。
_version_file = os.environ.get("PYI_VERSION_FILE") or None


a = Analysis(
    ['pulse_panel.py'],
    pathex=[],
    binaries=[],
    datas=[('catalog.json', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DSH-Plugin-Pulse',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.ico'],
    version=_version_file,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DSH-Plugin-Pulse',
)
