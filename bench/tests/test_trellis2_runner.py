from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_SPEC_PATH = REPO_ROOT / "models" / "trellis2" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "trellis2" / "Dockerfile"


def load_trellis2_runner() -> ModuleType:
    sys.path.insert(0, str(REPO_ROOT / "models" / "common"))
    runner_path = REPO_ROOT / "models" / "trellis2" / "runner.py"
    spec = importlib.util.spec_from_file_location("trellis2_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runner from {runner_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_trellis2_command_uses_seed_resolution_and_staged_weights(monkeypatch) -> None:
    monkeypatch.setenv("TRELLIS2_WEIGHTS_PATH", "/workspace/weights/TRELLIS.2-4B")
    runner = load_trellis2_runner()

    command = runner.build_trellis2_command(
        Path("/work/input/references/cartoon-apple.png"),
        Path("/work/output/_work/trellis2/cartoon-apple/raw"),
        20260708,
        runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/3dgen-runner/trellis2_runner.py",
        "--infer-image",
        "/work/input/references/cartoon-apple.png",
        "--infer-output-dir",
        "/work/output/_work/trellis2/cartoon-apple/raw",
        "--infer-seed",
        "20260708",
        "--infer-resolution",
        "1024",
        "--infer-trellis2-weights-path",
        "/workspace/weights/TRELLIS.2-4B",
    ]


def test_prepare_trellis2_task_output_writes_meta_with_official_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRELLIS2_WEIGHTS_PATH", "/workspace/weights/TRELLIS.2-4B")
    runner = load_trellis2_runner()
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
        peak_vram_bytes=24 * 1024**3,
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
            runner.LicenseSource("TRELLIS.2 LICENSE", license_path),
            runner.LicenseSource("TRELLIS.2-4B model card and license metadata", model_card_path),
        ],
        runtime=runtime,
        wall_clock_seconds=123.4,
        retry_count=0,
        started_at="2026-07-09T06:00:00Z",
        finished_at="2026-07-09T06:02:03Z",
    )

    meta = (tmp_path / "task-output" / "meta.json").read_text(encoding="utf-8")
    assert '"model_id": "trellis2"' in meta
    assert '"resolution": "1024"' in meta
    assert '"texture_size": 4096' in meta
    assert (tmp_path / "task-output" / "output.glb").read_bytes() == b"glb"
    assert (tmp_path / "task-output" / "raw" / "trellis2" / "output.glb").read_bytes() == b"glb"


def test_trellis2_model_spec_records_current_pins() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["id"] == "trellis2"
    assert spec["code_repo"] == "https://github.com/microsoft/TRELLIS.2"
    assert spec["code_commit"] == "75fbf0183001ed9876c8dbb35de6b68552ee08bd"
    assert spec["weights_repo"] == "microsoft/TRELLIS.2-4B"
    assert spec["weights_revision"] == "af44b45f2e35a493886929c6d786e563ec68364d"
    assert spec["default_parameters"]["pipeline_type"] == "1024_cascade"
    assert spec["default_parameters"]["texture_size"] == 4096
    assert spec["default_parameters"]["attention_backend"] == "xformers"
    assert spec["requires_hf_token"] is True
    assert "facebook/dinov3-vitl16-pretrain-lvd1689m" in spec["external_weight_dependencies"]
    assert "briaai/RMBG-2.0" in spec["external_weight_dependencies"]


def test_trellis2_dockerfile_uses_runtime_only_volume_paths() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04" in dockerfile
    assert "ARG TRELLIS2_COMMIT=75fbf0183001ed9876c8dbb35de6b68552ee08bd" in dockerfile
    assert "ARG TRELLIS2_WEIGHTS_REVISION=af44b45f2e35a493886929c6d786e563ec68364d" in dockerfile
    assert "TRELLIS2_WEIGHTS_PATH=/workspace/weights/TRELLIS.2-4B" in dockerfile
    assert "HF_HOME=/workspace/hf" in dockerfile
    assert "TORCH_HOME=/workspace/torch" in dockerfile
    assert "ATTN_BACKEND=xformers" in dockerfile
    assert 'TORCH_CUDA_ARCH_LIST="8.9;12.0"' in dockerfile
    assert "HF_TOKEN" not in dockerfile
    assert "snapshot_download(" not in dockerfile
    assert "RUN pip install" not in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "COPY bench/src /opt/bench/src" in dockerfile
    assert "COPY tasks /opt/3dgen-tasks" in dockerfile
    assert "COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py" in dockerfile
    assert "COPY models/trellis2/runner.py /opt/3dgen-runner/trellis2_runner.py" in dockerfile
