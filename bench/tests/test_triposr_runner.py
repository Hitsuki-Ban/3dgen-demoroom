import importlib.util
import json
import sys
from pathlib import Path

import pytest

from bench_harness.meta import REQUIRED_META_KEYS
from bench_harness.tasks import TaskDefinition


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_PATH = REPO_ROOT / "models" / "common"
RUNNER_PATH = REPO_ROOT / "models" / "triposr" / "runner.py"
MODEL_SPEC_PATH = REPO_ROOT / "models" / "triposr" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "triposr" / "Dockerfile"
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


def _load_runner():
    spec = importlib.util.spec_from_file_location("triposr_runner", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["triposr_runner"] = module
    spec.loader.exec_module(module)
    return module


def test_triposr_model_spec_records_current_pins() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec == {
        "id": "triposr",
        "name": "TripoSR",
        "input": "image",
        "output": "textured-mesh",
        "code_repo": "https://github.com/VAST-AI-Research/TripoSR",
        "code_commit": "107cefdc244c39106fa830359024f6a2f1c78871",
        "weights_repo": "stabilityai/TripoSR",
        "weights_revision": "5b521936b01fbe1890f6f9baed0254ab6351c04a",
        "license": "MIT",
        "default_parameters": {
            "chunk_size": 8192,
            "foreground_ratio": 0.85,
            "mc_resolution": 256,
            "model_save_format": "glb",
            "pretrained_model_name_or_path": "/opt/weights/TripoSR",
        },
    }


def test_dockerfile_uses_required_cuda_base_and_pins() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04" in dockerfile
    assert "ARG TRIPOSR_COMMIT=107cefdc244c39106fa830359024f6a2f1c78871" in dockerfile
    assert "ARG TRIPOSR_WEIGHTS_REVISION=5b521936b01fbe1890f6f9baed0254ab6351c04a" in dockerfile
    assert 'revision=os.environ["TRIPOSR_WEIGHTS_REVISION"]' in dockerfile
    assert "rembg.new_session()" in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "RUN pip install" not in dockerfile
    assert "PYTHONPATH=/opt/bench/src" in dockerfile
    assert "COPY bench/src /opt/bench/src" in dockerfile
    assert "COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py" in dockerfile


def test_build_triposr_command_uses_local_pinned_weights_and_official_preprocessing(tmp_path: Path) -> None:
    runner = _load_runner()
    command = runner.build_triposr_command(
        image_path=tmp_path / "input.png",
        raw_output_dir=tmp_path / "raw",
        parameters=runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/TripoSR/run.py",
        str(tmp_path / "input.png"),
        "--pretrained-model-name-or-path",
        "/opt/weights/TripoSR",
        "--output-dir",
        str(tmp_path / "raw"),
        "--model-save-format",
        "glb",
        "--chunk-size",
        "8192",
        "--mc-resolution",
        "256",
        "--foreground-ratio",
        "0.85",
    ]
    assert "--no-remove-bg" not in command


def test_create_raw_output_dir_precreates_official_image_slot(tmp_path: Path) -> None:
    runner = _load_runner()
    raw_output_dir = tmp_path / "raw"

    runner.create_raw_output_dir(raw_output_dir)

    assert (raw_output_dir / "0").is_dir()


def test_prepare_task_output_writes_contract_files(tmp_path: Path) -> None:
    runner = _load_runner()
    task = TaskDefinition(
        id="cartoon-apple",
        prompt="A stylized cartoon red apple",
        image="references/cartoon-apple.png",
        seed=20260708,
    )
    raw_output_dir = tmp_path / "raw"
    raw_output_dir.mkdir()
    official_output_dir = raw_output_dir / "0"
    official_output_dir.mkdir()
    (official_output_dir / "mesh.glb").write_bytes(b"glTF")
    license_path = tmp_path / "LICENSE"
    license_path.write_text("MIT\n", encoding="utf-8")
    task_output_dir = tmp_path / "out"

    runner.prepare_task_output(
        task=task,
        task_output_dir=task_output_dir,
        raw_output_dir=raw_output_dir,
        license_path=license_path,
        runtime=runner.RuntimeSnapshot(
            vram=_vram_measurement("NVIDIA GeForce RTX 4070 Ti", 1234),
            torch_version="2.7.1+cu128",
            torch_cuda_version="12.8",
            torch_cuda_arch_list=["sm_89", "sm_120"],
            attention_backend="sdpa",
        ),
        wall_clock_seconds=1.25,
        retry_count=0,
        started_at="2026-07-08T00:00:00Z",
        finished_at="2026-07-08T00:00:02Z",
    )

    meta = json.loads((task_output_dir / "meta.json").read_text(encoding="utf-8"))
    assert set(meta) == REQUIRED_META_KEYS | {"vram_measurement"}
    assert meta["model_id"] == "triposr"
    assert meta["vram_measurement"]["scope"] == "inference_process_group"
    assert meta["vram_measurement"]["gpu_uuid"] == "GPU-11111111-2222-3333-4444-555555555555"
    assert meta["model_git_commit"] == "107cefdc244c39106fa830359024f6a2f1c78871"
    assert meta["weights_revision"] == "5b521936b01fbe1890f6f9baed0254ab6351c04a"
    assert meta["parameters"] == runner.DEFAULT_PARAMETERS
    assert (task_output_dir / "output.glb").read_bytes() == b"glTF"
    assert (task_output_dir / "LICENSE").read_text(encoding="utf-8") == "MIT\n"
    assert (task_output_dir / "raw" / "triposr" / "0" / "mesh.glb").read_bytes() == b"glTF"


def test_run_task_timeout_writes_and_uploads_failure_before_reraising(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner()
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    (input_root / "input.png").write_bytes(b"png")
    calls: list[list[str]] = []
    uploads: list[str] = []

    def fake_run_with_peak_vram(
        command: list[str],
        timeout_seconds: float,
        timeout_label: str,
        *,
        log_path: Path | None = None,
    ) -> int:
        calls.append(command)
        raise runner_utils.RunnerTimeoutError(
            command=command,
            timeout_label=timeout_label,
            output_tail="marching cubes timed out",
        )

    def fake_upload(task_output_dir: Path, task_id: str, env: dict[str, str]) -> list[str]:
        failure = json.loads((task_output_dir / "failure.json").read_text(encoding="utf-8"))
        assert failure["error_output_tail"] == "marching cubes timed out"
        assert (task_output_dir / "infer.log").read_text(encoding="utf-8") == "marching cubes timed out\n"
        uploads.append(task_id)
        return [f"{task_id}/failure.json", f"{task_id}/infer.log"]

    monkeypatch.setattr(runner, "run_with_peak_vram", fake_run_with_peak_vram)
    monkeypatch.setattr(runner, "upload_task_increment_if_configured", fake_upload)

    with pytest.raises(runner_utils.RunnerTimeoutError):
        runner.run_task(
            runner.TaskDefinition(id="cartoon-apple", prompt="apple", image="input.png", seed=20260708),
            input_root,
            output_root,
            timeout_seconds=10,
        )

    failure = json.loads((output_root / "cartoon-apple" / "failure.json").read_text(encoding="utf-8"))
    assert len(calls) == 1
    assert uploads == ["cartoon-apple"]
    assert failure["retry_count"] == 0
    assert failure["error_type"] == "RunnerTimeoutError"
    assert (output_root / "cartoon-apple" / "infer.log").is_file()
