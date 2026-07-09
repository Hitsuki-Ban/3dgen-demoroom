from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_SPEC_PATH = REPO_ROOT / "models" / "pixal3d" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "pixal3d" / "Dockerfile"


def load_pixal3d_runner() -> ModuleType:
    sys.path.insert(0, str(REPO_ROOT / "models" / "common"))
    runner_path = REPO_ROOT / "models" / "pixal3d" / "runner.py"
    spec = importlib.util.spec_from_file_location("pixal3d_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runner from {runner_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_pixal3d_command_uses_standard_1536_without_low_vram(monkeypatch) -> None:
    monkeypatch.setenv("PIXAL3D_WEIGHTS_PATH", "/workspace/weights/Pixal3D")
    runner = load_pixal3d_runner()

    command = runner.build_pixal3d_command(
        Path("/work/input/references/cartoon-apple.png"),
        Path("/work/output/_work/pixal3d/cartoon-apple/raw"),
        20260708,
        runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/3dgen-runner/pixal3d_runner.py",
        "--infer-image",
        "/work/input/references/cartoon-apple.png",
        "--infer-output-dir",
        "/work/output/_work/pixal3d/cartoon-apple/raw",
        "--infer-seed",
        "20260708",
        "--infer-resolution",
        "1536",
        "--infer-pixal3d-weights-path",
        "/workspace/weights/Pixal3D",
    ]
    assert "--low_vram" not in command
    assert "--infer-low-vram" not in command


def test_prepare_pixal3d_task_output_writes_meta_with_standard_protocol(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIXAL3D_WEIGHTS_PATH", "/workspace/weights/Pixal3D")
    runner = load_pixal3d_runner()
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "output.glb").write_bytes(b"glb")
    license_path = tmp_path / "LICENSE"
    license_path.write_text("license\n", encoding="utf-8")
    model_card_path = tmp_path / "README.md"
    model_card_path.write_text("model card\n", encoding="utf-8")
    task = runner.TaskDefinition(
        id="cartoon-apple",
        prompt="cartoon apple",
        image="references/cartoon-apple.png",
        seed=20260708,
    )
    runtime = runner.RuntimeSnapshot(
        gpu_name="NVIDIA GeForce RTX 5090",
        peak_vram_bytes=28 * 1024**3,
        torch_version="2.7.1+cu128",
        torch_cuda_version="12.8",
        torch_cuda_arch_list=["sm_120"],
        attention_backend="flash_attn",
    )

    runner.prepare_task_output(
        task=task,
        task_output_dir=tmp_path / "task-output",
        raw_output_dir=raw,
        license_sources=[
            runner.LicenseSource("Pixal3D LICENSE", license_path),
            runner.LicenseSource("Pixal3D model card and license metadata", model_card_path),
        ],
        runtime=runtime,
        wall_clock_seconds=240.0,
        retry_count=0,
        started_at="2026-07-09T06:00:00Z",
        finished_at="2026-07-09T06:04:00Z",
    )

    meta = json.loads((tmp_path / "task-output" / "meta.json").read_text(encoding="utf-8"))
    assert meta["model_id"] == "pixal3d"
    assert meta["parameters"]["resolution"] == 1536
    assert meta["parameters"]["pipeline_type"] == "1536_cascade"
    assert meta["parameters"]["low_vram"] is False
    assert (tmp_path / "task-output" / "output.glb").read_bytes() == b"glb"
    assert (tmp_path / "task-output" / "raw" / "pixal3d" / "output.glb").read_bytes() == b"glb"


def test_pixal3d_model_spec_records_current_pins_and_standard_protocol() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["id"] == "pixal3d"
    assert spec["code_repo"] == "https://github.com/TencentARC/Pixal3D"
    assert spec["code_commit"] == "cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af"
    assert spec["weights_repo"] == "TencentARC/Pixal3D"
    assert spec["weights_revision"] == "0b31f9160aa400719af409098bff7936a932f726"
    assert spec["default_parameters"]["resolution"] == 1536
    assert spec["default_parameters"]["pipeline_type"] == "1536_cascade"
    assert spec["default_parameters"]["low_vram"] is False
    assert "camenduru/dinov3-vitl16-pretrain-lvd1689m" in spec["external_weight_dependencies"]
    assert "Ruicheng/moge-2-vitl" in spec["external_weight_dependencies"]


def test_pixal3d_dockerfile_uses_runtime_only_volume_paths() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04" in dockerfile
    assert "ARG PIXAL3D_COMMIT=cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af" in dockerfile
    assert "ARG PIXAL3D_WEIGHTS_REVISION=0b31f9160aa400719af409098bff7936a932f726" in dockerfile
    assert "PIXAL3D_WEIGHTS_PATH=/workspace/weights/Pixal3D" in dockerfile
    assert "HF_HOME=/workspace/hf" in dockerfile
    assert "TORCH_HOME=/workspace/torch" in dockerfile
    assert 'TORCH_CUDA_ARCH_LIST="8.9;12.0"' in dockerfile
    assert "snapshot_download(" not in dockerfile
    assert "HF_TOKEN" not in dockerfile
    assert "RUN pip install" not in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "natten==0.21.0" in dockerfile
    assert "utils3d-0.0.2-py3-none-any.whl" in dockerfile
    assert "COPY models/pixal3d/runner.py /opt/3dgen-runner/pixal3d_runner.py" in dockerfile
