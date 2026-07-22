# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


project_root = Path(SPECPATH).parent
source_root = project_root / "src"

# 显式收集原生库，防止 ONNX Runtime 和 libsndfile 的动态依赖漏入安装包。
onnx_datas = collect_data_files("onnxruntime", include_py_files=False)
onnx_binaries = collect_dynamic_libs("onnxruntime")
soundfile_datas = collect_data_files("_soundfile_data", include_py_files=False)
soundfile_binaries = collect_dynamic_libs("_soundfile_data")

datas = [
    *onnx_datas,
    *soundfile_datas,
    (
        str(project_root / "src/listening_cloze/ui/qml"),
        "listening_cloze/ui/qml",
    ),
    (
        str(project_root / "src/listening_cloze/data/content.db"),
        "listening_cloze/data",
    ),
    (
        str(project_root / "src/listening_cloze/data/quality-report.json"),
        "listening_cloze/data",
    ),
    (
        str(project_root / "src/listening_cloze/data/sources.json"),
        "listening_cloze/data",
    ),
    (
        str(project_root / "THIRD_PARTY_NOTICES.md"),
        ".",
    ),
    (
        str(project_root / "src/listening_cloze/data/supertonic-3"),
        "listening_cloze/data/supertonic-3",
    ),
]

analysis = Analysis(
    [str(project_root / "src/listening_cloze/__main__.py")],
    pathex=[str(source_root)],
    binaries=[*onnx_binaries, *soundfile_binaries],
    datas=datas,
    hiddenimports=[
        "PySide6.QtMultimedia",
        "onnxruntime.capi._pybind_state",
        "soundfile",
        "_soundfile",
        "supertonic.config",
        "supertonic.core",
        "supertonic.loader",
        "supertonic.pipeline",
        "supertonic.utils",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ListeningCloze",
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
)

application = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ListeningCloze",
)
