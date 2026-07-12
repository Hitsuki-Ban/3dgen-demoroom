from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_PATH = REPO_ROOT / "models" / "common"
MODEL_SPEC_PATH = REPO_ROOT / "models" / "trellis2" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "trellis2" / "Dockerfile"
sys.path.insert(0, str(COMMON_PATH))

import runner_utils  # noqa: E402


def _vram_measurement(gpu_name: str, peak_vram_bytes: int) -> runner_utils.VramMeasurement:
    return runner_utils.VramMeasurement(
        device=runner_utils.GpuDeviceIdentity(
            index=0,
            uuid="GPU-11111111-2222-3333-4444-555555555555",
            name=gpu_name,
            driver_model="N/A",
            mig_mode="N/A",
        ),
        peak_vram_bytes=peak_vram_bytes,
        device_baseline_bytes=0,
        mode=runner_utils.PROCESS_GROUP_VRAM_MODE,
        root_pid=1234,
        sample_interval_ms=500,
        sample_count=3,
        max_matched_process_count=1,
        pid_namespace_verified=True,
    )


def load_trellis2_runner() -> ModuleType:
    sys.path.insert(0, str(COMMON_PATH))
    runner_path = REPO_ROOT / "models" / "trellis2" / "runner.py"
    spec = importlib.util.spec_from_file_location("trellis2_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runner from {runner_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_trellis2_command_uses_seed_resolution_and_staged_weights(monkeypatch) -> None:
    monkeypatch.setenv("TRELLIS2_WEIGHTS_PATH", "/workspace/weights/TRELLIS.2-4B")
    monkeypatch.setenv("HF_HOME", "/workspace/hf")
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
    monkeypatch.setenv("HF_HOME", "/workspace/hf")
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
        vram=_vram_measurement("NVIDIA GeForce RTX 5090", 24 * 1024**3),
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

    meta = json.loads((tmp_path / "task-output" / "meta.json").read_text(encoding="utf-8"))
    assert meta["model_id"] == "trellis2"
    assert meta["vram_measurement"]["scope"] == "inference_process_group"
    assert meta["vram_measurement"]["gpu_uuid"] == "GPU-11111111-2222-3333-4444-555555555555"
    assert meta["parameters"]["resolution"] == "1024"
    assert meta["parameters"]["texture_size"] == 4096
    assert meta["external_weight_revisions"] == runner.EXTERNAL_WEIGHT_REVISIONS
    assert (tmp_path / "task-output" / "output.glb").read_bytes() == b"glb"
    assert (tmp_path / "task-output" / "raw" / "trellis2" / "output.glb").read_bytes() == b"glb"


def test_validate_staged_trellis2_dependencies_requires_pinned_refs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRELLIS2_WEIGHTS_PATH", "/workspace/weights/TRELLIS.2-4B")
    monkeypatch.setenv("HF_HOME", "/workspace/hf")
    runner = load_trellis2_runner()
    weights = tmp_path / "weights"
    hf_home = tmp_path / "hf"
    weights.mkdir()
    (weights / "pipeline.json").write_bytes(b"fixture")
    cache_requirements = {
        "facebook/dinov3-vitl16-pretrain-lvd1689m": (
            runner.DINO_V3_REVISION,
            ("LICENSE.md", "config.json", "model.safetensors"),
        ),
        "briaai/RMBG-2.0": (
            runner.RMBG_REVISION,
            ("README.md", "BiRefNet_config.py", "birefnet.py", "config.json", "model.safetensors"),
        ),
        "microsoft/TRELLIS-image-large": (
            runner.TRELLIS1_WEIGHTS_REVISION,
            ("README.md", "ckpts/ss_dec_conv3d_16l8_fp16.json", "ckpts/ss_dec_conv3d_16l8_fp16.safetensors"),
        ),
    }
    for repo_id, (revision, filenames) in cache_requirements.items():
        repo_dir = hf_home / "hub" / ("models--" + repo_id.replace("/", "--"))
        ref = repo_dir / "refs" / "main"
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(revision, encoding="utf-8")
        for filename in filenames:
            path = repo_dir / "snapshots" / revision / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")

    runner.validate_staged_dependencies(weights, hf_home)
    trellis1_ref = hf_home / "hub" / "models--microsoft--TRELLIS-image-large" / "refs" / "main"
    trellis1_ref.write_text("wrong", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="missing pinned HF main ref"):
        runner.validate_staged_dependencies(weights, hf_home)


def test_trellis2_model_spec_records_current_pins() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["id"] == "trellis2"
    assert spec["code_repo"] == "https://github.com/microsoft/TRELLIS.2"
    assert spec["code_commit"] == "75fbf0183001ed9876c8dbb35de6b68552ee08bd"
    assert spec["weights_repo"] == "microsoft/TRELLIS.2-4B"
    assert spec["weights_revision"] == "af44b45f2e35a493886929c6d786e563ec68364d"
    assert spec["default_parameters"]["pipeline_type"] == "1024_cascade"
    assert spec["default_parameters"]["texture_size"] == 4096
    assert spec["default_parameters"]["attention_backend"] == "flash_attn"
    assert spec["requires_hf_token"] is True
    assert "facebook/dinov3-vitl16-pretrain-lvd1689m" in spec["external_weight_dependencies"]
    assert "briaai/RMBG-2.0" in spec["external_weight_dependencies"]
    assert spec["external_weight_revisions"] == {
        "facebook/dinov3-vitl16-pretrain-lvd1689m": "ea8dc2863c51be0a264bab82070e3e8836b02d51",
        "briaai/RMBG-2.0": "5df4c9c76d8170882c34f6986e848ee07fd0ba43",
        "microsoft/TRELLIS-image-large": "25e0d31ffbebe4b5a97464dd851910efc3002d96",
    }


def test_trellis2_dockerfile_uses_runtime_only_volume_paths() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04" in dockerfile
    assert "ARG TRELLIS2_COMMIT=75fbf0183001ed9876c8dbb35de6b68552ee08bd" in dockerfile
    assert "ARG TRELLIS2_WEIGHTS_REVISION=af44b45f2e35a493886929c6d786e563ec68364d" in dockerfile
    assert "ARG NVDIFFRAST_COMMIT=253ac4fcea7de5f396371124af597e6cc957bfae" in dockerfile
    assert "ARG NVDIFFREC_COMMIT=b296927cc7fd01c2ac1087c8065c4d7248f72da4" in dockerfile
    assert "ARG CUMESH_COMMIT=12289e1062f0603f2f0d0771b02e1395d247f26f" in dockerfile
    assert "ARG FLEXGEMM_COMMIT=6dd94a859c26ee8246888502eada3dd8ad85532e" in dockerfile
    assert "xformers==0.0.31" in dockerfile
    assert "--no-build-isolation --no-deps /opt/TRELLIS.2/o-voxel" in dockerfile
    assert "uv pip install --system transformers==4.57.3" in dockerfile
    assert "flash-attn==2.8.3" in dockerfile
    assert "TRELLIS2_WEIGHTS_PATH=/workspace/weights/TRELLIS.2-4B" in dockerfile
    assert "HF_HOME=/workspace/hf" in dockerfile
    assert "TORCH_HOME=/workspace/torch" in dockerfile
    assert "ENV ATTN_BACKEND=flash_attn" in dockerfile
    assert 'TORCH_CUDA_ARCH_LIST="8.9;12.0"' in dockerfile
    assert "LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/lib64/stubs" in dockerfile
    assert "HF_TOKEN" not in dockerfile
    assert "snapshot_download(" not in dockerfile
    assert "RUN pip install" not in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "COPY bench/src /opt/bench/src" in dockerfile
    assert "COPY tasks /opt/3dgen-tasks" in dockerfile
    assert "COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py" in dockerfile
    assert "COPY models/trellis2/runner.py /opt/3dgen-runner/trellis2_runner.py" in dockerfile
