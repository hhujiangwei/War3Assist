# -*- mode: python ; coding: utf-8 -*-
# 单文件打包配置：War3Assist
# 图标：assets/app_icon.ico（EXE 壳图标）；同时打包 jpeg 供运行时窗口图标。
# 用法：pyinstaller --clean --noconfirm War3Assist.spec

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/app_icon.ico', 'assets'),
        ('assets/app_icon.jpeg', 'assets'),
        ('config.json', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='War3Assist',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI 应用，不弹控制台
    icon='assets/app_icon.ico',
)