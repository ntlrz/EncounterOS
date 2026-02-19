# PyInstaller spec for EncounterOS — run: pyinstaller encounteros.spec
# Output: dist/EncounterOS/ (folder with .exe + bundled themes). Zip that folder for portability.

import sys

block_cipher = None

# Bundle themes so overlay finds them when frozen. Icons optional.
datas = [('themes', 'themes')]
try:
    from pathlib import Path
    icons = Path('icons')
    if icons.is_dir():
        datas.append(('icons', 'icons'))
except Exception:
    pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'gm_window', 'combat_tab', 'dialog_tab', 'notes_tab', 'encounters_tab',
        'rosters_tab', 'timers_tab', 'tracker_overlay', 'app_paths', 'helpers', 'styles',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='EncounterOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
