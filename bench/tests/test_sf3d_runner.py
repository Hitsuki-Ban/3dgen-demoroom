from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from bench_harness.meta import REQUIRED_META_KEYS


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_SPEC_PATH = REPO_ROOT / "models" / "sf3d" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "sf3d" / "Dockerfile"


def load_sf3d_runner(monkeypatch) -> ModuleType:
    monkeypatch.setenv("SF3D_WEIGHTS_PATH", "/workspace/weights/stable-fast-3d")
    sys.path.insert(0, str(REPO_ROOT / "models" / "common"))
    runner_path = REPO_ROOT / "models" / "sf3d" / "runner.py"
    spec = importlib.util.spec_from_file_location("sf3d_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runner from {runner_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_sf3d_command_uses_official_defaults(monkeypatch) -> None:
    runner = load_sf3d_runner(monkeypatch)
    command = runner.build_sf3d_command(
        Path("/work/input/references/cartoon-apple.png"),
        Path("/work/output/_work/sf3d/cartoon-apple/raw"),
        20260708,
        runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/3dgen-runner/sf3d_runner.py",
        "--infer-image",
        "/work/input/references/cartoon-apple.png",
        "--infer-output-dir",
        "/work/output/_work/sf3d/cartoon-apple/raw",
        "--infer-seed",
        "20260708",
        "--infer-foreground-ratio",
        "0.85",
        "--infer-texture-resolution",
        "1024",
        "--infer-remesh",
        "none",
        "--infer-target-vertex-count",
        "-1",
        "--infer-sf3d-weights-path",
        "/workspace/weights/stable-fast-3d",
    ]


def test_prepare_sf3d_output_writes_contract_files(monkeypatch, tmp_path: Path) -> None:
    runner = load_sf3d_runner(monkeypatch)
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "output.glb").write_bytes(b"glb")
    (raw / "input.png").write_bytes(b"png")
    license_path = tmp_path / "LICENSE.md"
    license_path.write_text("license\n", encoding="utf-8")
    notice_path = tmp_path / "NOTICE.txt"
    notice_path.write_text("Powered by Stability AI.\n", encoding="utf-8")
    task = runner.TaskDefinition(
        id="cartoon-apple",
        prompt="cartoon apple",
        image="references/cartoon-apple.png",
        seed=20260708,
    )

    runner.prepare_task_output(
        task=task,
        task_output_dir=tmp_path / "task-output",
        raw_output_dir=raw,
        license_sources=[
            runner.LicenseSource("code", license_path),
            runner.LicenseSource("weights", license_path),
            runner.LicenseSource("notice", notice_path),
        ],
        runtime=runner.RuntimeSnapshot(
            gpu_name="NVIDIA GeForce RTX 4090",
            peak_vram_bytes=6 * 1024**3,
            torch_version="2.7.1+cu128",
            torch_cuda_version="12.8",
            torch_cuda_arch_list=["sm_89", "sm_120"],
            attention_backend="torch-default",
        ),
        wall_clock_seconds=2.0,
        retry_count=0,
        started_at="2026-07-10T00:00:00Z",
        finished_at="2026-07-10T00:00:02Z",
    )

    output = tmp_path / "task-output"
    meta = json.loads((output / "meta.json").read_text(encoding="utf-8"))
    assert set(meta) == REQUIRED_META_KEYS
    assert meta["model_id"] == "sf3d"
    assert meta["parameters"]["foreground_ratio"] == 0.85
    assert meta["parameters"]["texture_resolution"] == 1024
    assert (output / "output.glb").read_bytes() == b"glb"
    assert (output / "raw" / "sf3d" / "output.glb").read_bytes() == b"glb"
    assert "Powered by Stability AI" in (output / "LICENSES.txt").read_text(encoding="utf-8")


def test_sf3d_spec_and_dockerfile_pin_runtime_only_dependencies() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert spec["id"] == "sf3d"
    assert spec["code_commit"] == "ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2"
    assert spec["weights_revision"] == "f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778"
    assert spec["external_weight_dependencies"]["dinov2_large"]["revision"] == (
        "47b73eefe95e8d44ec3623f8890bd894b6ea2d6c"
    )
    assert spec["external_weight_dependencies"]["openclip"]["revision"] == (
        "1a25a446712ba5ee05982a381eed697ef9b435cf"
    )
    assert spec["default_parameters"]["remesh"] == "none"
    assert spec["default_parameters"]["target_vertex_count"] == -1
    assert "nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04" in dockerfile
    assert 'TORCH_CUDA_ARCH_LIST="8.9;12.0"' in dockerfile
    assert "SF3D_WEIGHTS_PATH=/workspace/weights/stable-fast-3d" in dockerfile
    assert "HF_HUB_OFFLINE=1" in dockerfile
    assert "snapshot_download(" not in dockerfile
    assert "HF_TOKEN" not in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "boto3" in dockerfile
    assert "openssh-server" in dockerfile


def test_require_staged_hf_snapshot_checks_main_ref_and_files(monkeypatch, tmp_path: Path) -> None:
    runner = load_sf3d_runner(monkeypatch)
    repo_cache = tmp_path / "hub" / "models--example--model"
    snapshot = repo_cache / "snapshots" / "revision-123"
    snapshot.mkdir(parents=True)
    (repo_cache / "refs").mkdir()
    (repo_cache / "refs" / "main").write_text("revision-123\n", encoding="utf-8")
    (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(b"weights")

    assert runner.require_staged_hf_snapshot(
        tmp_path,
        repo_cache_name="models--example--model",
        revision="revision-123",
        required_files=("config.json", "model.safetensors"),
    ) == snapshot
