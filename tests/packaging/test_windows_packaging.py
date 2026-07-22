from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from tools.assets.build_release_manifest import write_release_metadata
from tools.assets.fetch_supertonic3 import load_asset_manifest, model_url

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "package-windows.yml"
ASSET_MANIFEST = ROOT / "tools" / "assets" / "supertonic3_assets.json"
PYINSTALLER_SPEC = ROOT / "packaging" / "listening_cloze.spec"
INNO_SETUP = ROOT / "packaging" / "listening_cloze.iss"
REMOTE_BUILD = ROOT / "packaging" / "windows_build.py"

MODEL_REVISION = "724fb5abbf5502583fb520898d45929e62f02c0b"
OFFICIAL_ONNX_HASHES = {
    "onnx/duration_predictor.onnx": (
        "c3eb91414d5ff8a7a239b7fe9e34e7e2bf8a8140d8375ffb14718b1c639325db"
    ),
    "onnx/text_encoder.onnx": ("c7befd5ea8c3119769e8a6c1486c4edc6a3bc8365c67621c881bbb774b9902ff"),
    "onnx/vector_estimator.onnx": (
        "883ac868ea0275ef0e991524dc64f16b3c0376efd7c320af6b53f5b780d7c61c"
    ),
    "onnx/vocoder.onnx": ("085de76dd8e8d5836d6ca66826601f615939218f90e519f70ee8a36ed2a4c4ba"),
}


def test_workflow_has_pinned_windows_toolchain_and_minimal_permissions() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert 'tags: ["v*"]' in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "runs-on: windows-2025" in workflow
    assert 'python-version: "3.12"' in workflow
    assert 'version: "0.9.28"' in workflow
    assert "uv sync --locked --all-groups" in workflow
    assert "uv run python tools/run_tests.py" in workflow
    assert "$env:PACKAGE_VERSION = $version" in workflow


def test_downloaded_model_writes_a_runtime_hash_manifest() -> None:
    downloader = (ROOT / "tools/assets/fetch_supertonic3.py").read_text(encoding="utf-8")

    assert '"asset-manifest.json"' in downloader


def test_workflow_builds_and_uploads_a_verified_installer() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    required_fragments = (
        "tools/assets/fetch_supertonic3.py",
        "packaging/listening_cloze.spec",
        "ISCC.exe",
        "tools/assets/build_release_manifest.py",
        "actions/upload-artifact@v4",
        "retention-days: 14",
        "ListeningClozeSetup.exe",
        "SHA256SUMS.txt",
        "build-manifest.json",
        "--smoke-test",
        "QT_QPA_PLATFORM",
        "Start-Process",
        "-Wait",
        "-PassThru",
        ".ExitCode",
    )
    for fragment in required_fragments:
        assert fragment in workflow


def test_supertonic_manifest_is_complete_and_revision_pinned() -> None:
    manifest = load_asset_manifest(ASSET_MANIFEST)
    files = {item.path: item.sha256 for item in manifest.files}

    assert manifest.repository == "Supertone/supertonic-3"
    assert manifest.revision == MODEL_REVISION
    assert OFFICIAL_ONNX_HASHES.items() <= files.items()
    assert {
        "onnx/tts.json",
        "onnx/unicode_indexer.json",
        "LICENSE",
        *(f"voice_styles/F{number}.json" for number in range(1, 6)),
        *(f"voice_styles/M{number}.json" for number in range(1, 6)),
    }.issubset(files)
    assert all("main" not in model_url(manifest, item.path) for item in manifest.files)
    assert all(MODEL_REVISION in model_url(manifest, item.path) for item in manifest.files)
    assert all(item.sha256 is not None for item in manifest.files)


def test_supertonic_manifest_rejects_unpinned_revision(tmp_path: Path) -> None:
    manifest = json.loads(ASSET_MANIFEST.read_text(encoding="utf-8"))
    manifest["revision"] = "main"
    path = tmp_path / "assets.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="完整的提交 SHA"):
        load_asset_manifest(path)


def test_pyinstaller_spec_collects_runtime_data_and_native_dependencies() -> None:
    spec = PYINSTALLER_SPEC.read_text(encoding="utf-8")

    assert "src/listening_cloze/__main__.py" in spec
    assert "src/listening_cloze/ui/qml" in spec
    assert "src/listening_cloze/data/content.db" in spec
    assert "src/listening_cloze/data/sources.json" in spec
    assert "THIRD_PARTY_NOTICES.md" in spec
    assert "src/listening_cloze/data/supertonic-3" in spec
    assert "listening_cloze/data/supertonic-3" in spec
    assert "onnxruntime" in spec
    assert 'collect_all("onnxruntime")' not in spec
    assert "soundfile" in spec
    assert "_soundfile_data" in spec
    assert '"PySide6.QtMultimedia"' in spec
    assert "console=False" in spec
    assert "exclude_binaries=True" in spec


def test_inno_setup_builds_unsigned_installer_and_preserves_data_by_default() -> None:
    setup = INNO_SETUP.read_text(encoding="utf-8")

    assert "OutputBaseFilename=ListeningClozeSetup" in setup
    assert 'Source: "dist\\ListeningCloze\\*"' in setup
    assert "PrivilegesRequired=lowest" in setup
    assert "Uninstallable=yes" in setup
    assert "InitializeUninstall" in setup
    assert "CurUninstallStepChanged" in setup
    assert "usPostUninstall" in setup
    assert "MB_YESNO" in setup
    assert "IDNO" in setup
    assert "{localappdata}\\ListeningCloze" in setup
    assert "SignTool" not in setup


def test_release_metadata_contains_reproducible_checksums(tmp_path: Path) -> None:
    installer = tmp_path / "ListeningClozeSetup.exe"
    installer.write_bytes(b"offline-installer")
    output = tmp_path / "release"

    manifest_path, sums_path = write_release_metadata(
        inputs=[installer],
        output_directory=output,
        version="v0.1.0",
        commit="a" * 40,
        source_ref="refs/tags/v0.1.0",
        runner="Windows-X64",
        model_manifest_path=ASSET_MANIFEST,
        built_at_utc="2026-07-22T00:00:00Z",
    )

    expected_sha = hashlib.sha256(b"offline-installer").hexdigest()
    release_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert release_manifest["source"]["commit"] == "a" * 40
    assert release_manifest["model"]["revision"] == MODEL_REVISION
    assert release_manifest["files"] == [
        {
            "name": "ListeningClozeSetup.exe",
            "sha256": expected_sha,
            "size": len(b"offline-installer"),
        }
    ]
    assert sums_path.read_text(encoding="utf-8") == (f"{expected_sha}  ListeningClozeSetup.exe\n")


def test_remote_windows_build_cli_uses_gh_without_shell_expansion() -> None:
    script = REMOTE_BUILD.read_text(encoding="utf-8")

    assert "gh workflow run package-windows.yml" not in script
    assert '["gh", "workflow", "run"' in script
    assert re.search(r'"gh",\s*"run",\s*"download"', script)
    assert "shell=True" not in script
