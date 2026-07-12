from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_PATH = REPO_ROOT / "models" / "common"
MODEL_SPEC_PATH = REPO_ROOT / "models" / "direct3d-s2" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "direct3d-s2" / "Dockerfile"
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


def load_direct3d_s2_runner() -> ModuleType:
    sys.path.insert(0, str(COMMON_PATH))
    runner_path = REPO_ROOT / "models" / "direct3d-s2" / "runner.py"
    spec = importlib.util.spec_from_file_location("direct3d_s2_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runner from {runner_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_direct3d_s2_command_uses_1024_protocol_and_staged_weights(monkeypatch) -> None:
    monkeypatch.setenv("DIRECT3D_S2_WEIGHTS_PATH", "/workspace/weights/Direct3D-S2")
    runner = load_direct3d_s2_runner()

    command = runner.build_direct3d_s2_command(
        Path("/work/input/references/cartoon-apple.png"),
        Path("/work/output/_work/direct3d-s2/cartoon-apple/raw"),
        20260708,
        runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/3dgen-runner/direct3d_s2_runner.py",
        "--infer-image",
        "/work/input/references/cartoon-apple.png",
        "--infer-output-dir",
        "/work/output/_work/direct3d-s2/cartoon-apple/raw",
        "--infer-seed",
        "20260708",
        "--infer-sdf-resolution",
        "1024",
        "--infer-direct3d-s2-weights-path",
        "/workspace/weights/Direct3D-S2",
    ]


def test_prepare_direct3d_s2_task_output_writes_geometry_only_meta(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DIRECT3D_S2_WEIGHTS_PATH", "/workspace/weights/Direct3D-S2")
    runner = load_direct3d_s2_runner()
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "output.glb").write_bytes(b"glb")
    (raw / "output.obj").write_text("obj\n", encoding="utf-8")
    license_path = tmp_path / "LICENSE.txt"
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
        attention_backend="spatial_sparse_attention",
    )

    runner.prepare_task_output(
        task=task,
        task_output_dir=tmp_path / "task-output",
        raw_output_dir=raw,
        license_sources=[
            runner.LicenseSource("Direct3D-S2 LICENSE.txt", license_path),
            runner.LicenseSource("Direct3D-S2 model card and license metadata", model_card_path),
        ],
        runtime=runtime,
        wall_clock_seconds=123.4,
        retry_count=0,
        started_at="2026-07-09T06:00:00Z",
        finished_at="2026-07-09T06:02:03Z",
    )

    meta = json.loads((tmp_path / "task-output" / "meta.json").read_text(encoding="utf-8"))
    assert meta["model_id"] == "direct3d-s2"
    assert meta["vram_measurement"]["scope"] == "inference_process_group"
    assert meta["vram_measurement"]["gpu_uuid"] == "GPU-11111111-2222-3333-4444-555555555555"
    assert meta["parameters"]["sdf_resolution"] == 1024
    assert meta["parameters"]["geometry_only"] is True
    assert (tmp_path / "task-output" / "output.glb").read_bytes() == b"glb"
    assert (tmp_path / "task-output" / "raw" / "direct3d-s2" / "output.obj").read_text(encoding="utf-8") == "obj\n"


def test_direct3d_s2_model_spec_records_current_pins() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["id"] == "direct3d-s2"
    assert spec["code_repo"] == "https://github.com/DreamTechAI/Direct3D-S2"
    assert spec["code_commit"] == "a1cf235b2881cff04a91900060a9546b40e7ee5d"
    assert spec["weights_repo"] == "wushuang98/Direct3D-S2"
    assert spec["weights_revision"] == "8b04a8eddb7a56a0f4e89fe5f5b840c7d5610c00"
    assert spec["weights_subfolder"] == "direct3d-s2-v-1-1"
    assert spec["default_parameters"]["sdf_resolution"] == 1024
    assert spec["default_parameters"]["remove_interior"] is True
    assert spec["default_parameters"]["remesh"] is False
    assert spec["default_parameters"]["geometry_only"] is True


def test_direct3d_s2_dockerfile_uses_runtime_only_volume_paths() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04" in dockerfile
    assert "ARG DIRECT3D_S2_COMMIT=a1cf235b2881cff04a91900060a9546b40e7ee5d" in dockerfile
    assert "ARG DIRECT3D_S2_WEIGHTS_REVISION=8b04a8eddb7a56a0f4e89fe5f5b840c7d5610c00" in dockerfile
    assert "ARG TORCHSPARSE_COMMIT=385f5ce8718fcae93540511b7f5832f4e71fd835" in dockerfile
    assert "libsparsehash-dev" in dockerfile
    assert "flash-attn==2.8.3" in dockerfile
    assert "cd /opt/Direct3D-S2/third_party/voxelize" in dockerfile
    assert "import flash_attn" in dockerfile
    assert "import udf_ext" in dockerfile
    assert "uv pip install --system accelerate kornia prettytable" in dockerfile
    assert "DIRECT3D_S2_WEIGHTS_PATH=/workspace/weights/Direct3D-S2" in dockerfile
    assert "HF_HOME=/workspace/hf" in dockerfile
    assert "TORCH_HOME=/workspace/torch" in dockerfile
    assert 'TORCH_CUDA_ARCH_LIST="8.9;12.0"' in dockerfile
    assert "snapshot_download(" not in dockerfile
    assert "RUN pip install" not in dockerfile
    assert "|| echo" not in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "uv pip install --system --no-build-isolation /tmp/extensions/torchsparse" in dockerfile
    assert "COPY models/direct3d-s2/runner.py /opt/3dgen-runner/direct3d_s2_runner.py" in dockerfile
