import importlib.util
import json
import sys
from pathlib import Path

from bench_harness.meta import REQUIRED_META_KEYS
from bench_harness.tasks import TaskDefinition


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "models" / "trellis1" / "runner.py"
COMMON_PATH = REPO_ROOT / "models" / "common"
MODEL_SPEC_PATH = REPO_ROOT / "models" / "trellis1" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "trellis1" / "Dockerfile"
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


def _load_runner(monkeypatch):
    monkeypatch.setenv("TRELLIS1_WEIGHTS_PATH", "/workspace/weights/TRELLIS-image-large")
    sys.path.insert(0, str(COMMON_PATH))
    spec = importlib.util.spec_from_file_location("trellis1_runner", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["trellis1_runner"] = module
    spec.loader.exec_module(module)
    return module


def test_trellis1_model_spec_records_current_pins() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["id"] == "trellis1"
    assert spec["code_repo"] == "https://github.com/microsoft/TRELLIS"
    assert spec["code_commit"] == "442aa1e1afb9014e80681d3bf604e8d728a86ee7"
    assert spec["weights_repo"] == "microsoft/TRELLIS-image-large"
    assert spec["weights_revision"] == "25e0d31ffbebe4b5a97464dd851910efc3002d96"
    assert spec["default_parameters"]["sparse_structure_sampler_params"] == {
        "steps": 25,
        "cfg_strength": 5.0,
        "cfg_interval": [0.5, 1.0],
        "rescale_t": 3.0,
    }
    assert spec["default_parameters"]["slat_sampler_params"] == {
        "steps": 25,
        "cfg_strength": 5.0,
        "cfg_interval": [0.5, 1.0],
        "rescale_t": 3.0,
    }
    assert spec["default_parameters"]["formats"] == ["mesh", "gaussian", "radiance_field"]
    assert spec["default_parameters"]["attention_backend"] == "xformers"
    assert spec["default_parameters"]["spconv_algo"] == "native"
    assert spec["default_parameters"]["trellis1_weights_path"] == "/workspace/weights/TRELLIS-image-large"


def test_trellis1_dockerfile_uses_runtime_only_volume_paths() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04" in dockerfile
    assert "ARG TRELLIS_COMMIT=442aa1e1afb9014e80681d3bf604e8d728a86ee7" in dockerfile
    assert "ARG TRELLIS_WEIGHTS_REVISION=25e0d31ffbebe4b5a97464dd851910efc3002d96" in dockerfile
    assert "TRELLIS1_WEIGHTS_PATH=/workspace/weights/TRELLIS-image-large" in dockerfile
    assert "TORCH_HOME=/workspace/torch" in dockerfile
    assert "U2NET_HOME=/workspace/weights/rembg" in dockerfile
    assert "ATTN_BACKEND=xformers" in dockerfile
    assert "SPCONV_ALGO=native" in dockerfile
    assert 'TORCH_CUDA_ARCH_LIST="8.9"' in dockerfile
    assert 'TORCH_CUDA_ARCH_LIST="8.9;12.0"' not in dockerfile
    assert "snapshot_download(" not in dockerfile
    assert "RUN pip install" not in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "uv pip install --system --no-build-isolation /tmp/extensions/diffoctreerast" in dockerfile
    assert (
        "uv pip install --system --no-build-isolation "
        "/tmp/extensions/mip-splatting/submodules/diff-gaussian-rasterization"
    ) in dockerfile
    assert "uv pip install --system --no-build-isolation /tmp/extensions/nvdiffrast" in dockerfile
    assert "COPY bench/src /opt/bench/src" in dockerfile
    assert "COPY tasks /opt/3dgen-tasks" in dockerfile
    assert "COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py" in dockerfile
    assert "COPY models/trellis1/runner.py /opt/3dgen-runner/trellis1_runner.py" in dockerfile


def test_build_trellis1_command_uses_volume_pinned_weights(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner(monkeypatch)

    command = runner.build_trellis1_command(
        image_path=tmp_path / "input.png",
        raw_output_dir=tmp_path / "raw",
        seed=20260708,
        parameters=runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/3dgen-runner/trellis1_runner.py",
        "--infer-image",
        str(tmp_path / "input.png"),
        "--infer-output-dir",
        str(tmp_path / "raw"),
        "--infer-seed",
        "20260708",
        "--infer-simplify",
        "0.95",
        "--infer-texture-size",
        "1024",
        "--infer-trellis1-weights-path",
        "/workspace/weights/TRELLIS-image-large",
    ]


def test_trellis1_runner_requires_explicit_weight_env(monkeypatch) -> None:
    monkeypatch.delenv("TRELLIS1_WEIGHTS_PATH", raising=False)
    sys.path.insert(0, str(COMMON_PATH))
    spec = importlib.util.spec_from_file_location("trellis1_runner_missing_env", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["trellis1_runner_missing_env"] = module

    try:
        spec.loader.exec_module(module)
    except ValueError as exc:
        assert "TRELLIS1_WEIGHTS_PATH" in str(exc)
    else:
        raise AssertionError("runner import should fail without explicit weight env")


def test_prepare_task_output_writes_trellis1_contract_files(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner(monkeypatch)
    task = TaskDefinition(
        id="cartoon-apple",
        prompt="A stylized cartoon red apple",
        image="references/cartoon-apple.png",
        seed=20260708,
    )
    raw_output_dir = tmp_path / "raw"
    raw_output_dir.mkdir()
    (raw_output_dir / "output.glb").write_bytes(b"glTF")
    (raw_output_dir / "output_gaussian.ply").write_text("ply\n", encoding="utf-8")
    root_license = tmp_path / "LICENSE"
    weights_readme = tmp_path / "README.md"
    root_license.write_text("MIT\n", encoding="utf-8")
    weights_readme.write_text("model card\n", encoding="utf-8")
    task_output_dir = tmp_path / "out"

    runner.prepare_task_output(
        task=task,
        task_output_dir=task_output_dir,
        raw_output_dir=raw_output_dir,
        license_sources=[
            runner.LicenseSource("TRELLIS LICENSE", root_license),
            runner.LicenseSource("TRELLIS-image-large model card and license metadata", weights_readme),
        ],
        runtime=runner.RuntimeSnapshot(
            vram=_vram_measurement("NVIDIA GeForce RTX 4090", 1234),
            torch_version="2.4.0+cu121",
            torch_cuda_version="12.1",
            torch_cuda_arch_list=["sm_89"],
            attention_backend="xformers",
        ),
        wall_clock_seconds=1.25,
        retry_count=0,
        started_at="2026-07-09T00:00:00Z",
        finished_at="2026-07-09T00:00:02Z",
    )

    meta = json.loads((task_output_dir / "meta.json").read_text(encoding="utf-8"))
    assert set(meta) == REQUIRED_META_KEYS | {"vram_measurement"}
    assert meta["model_id"] == "trellis1"
    assert meta["vram_measurement"]["scope"] == "inference_process_group"
    assert meta["vram_measurement"]["gpu_uuid"] == "GPU-11111111-2222-3333-4444-555555555555"
    assert meta["model_git_commit"] == "442aa1e1afb9014e80681d3bf604e8d728a86ee7"
    assert meta["weights_revision"] == "25e0d31ffbebe4b5a97464dd851910efc3002d96"
    assert meta["parameters"] == runner.DEFAULT_PARAMETERS
    assert meta["parameters"]["spconv_algo"] == "native"
    assert meta["attention_backend"] == "xformers"
    assert (task_output_dir / "output.glb").read_bytes() == b"glTF"
    assert (task_output_dir / "raw" / "trellis1" / "output.glb").read_bytes() == b"glTF"
    assert (task_output_dir / "raw" / "trellis1" / "output_gaussian.ply").read_text(encoding="utf-8") == "ply\n"
    licenses = (task_output_dir / "LICENSES.txt").read_text(encoding="utf-8")
    assert "MIT" in licenses
    assert "model card" in licenses
