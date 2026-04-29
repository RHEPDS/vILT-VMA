# PyInstaller — one-file binary (Windows: VMAnalytic.exe, Linux/macOS: dist/VMAnalytic)
# Requires: pip install pyinstaller
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# SPEC is defined by PyInstaller when loading this file
_root = Path(SPEC).parent.resolve()

_datas = [
    (str(_root / "helper_files"), "helper_files"),
    (str(_root / "web" / "templates"), "web/templates"),
    (str(_root / "web" / "static"), "web/static"),
]
# runner.exec() reads body_exec.py from disk — ship all vm_analysis/*.py
for _py in sorted((_root / "vm_analysis").glob("*.py")):
    _datas.append((str(_py), "vm_analysis"))
for pkg in ("matplotlib", "mpl_toolkits"):
    try:
        _datas += collect_data_files(pkg)
    except Exception:
        pass

try:
    _vm_sub = list(collect_submodules("vm_analysis"))
except Exception:
    _vm_sub = []

_hidden = _vm_sub + [
    "waitress",
    "web",
    "web.app",
    "flask",
    "jinja2",
    "werkzeug",
    "pandas",
    "numpy",
    "openpyxl",
    "PIL",
    "PIL.Image",
    "certifi",
    "matplotlib",
    "matplotlib.backends",
    "matplotlib.backends.backend_agg",
    "pyVim",
    "pyVmomi",
    "pyVmomi.vim",
]

a = Analysis(
    [str(_root / "local_server.py")],
    pathex=[str(_root)],
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="VMAnalytic",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
