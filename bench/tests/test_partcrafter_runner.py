import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from bench_harness.meta import REQUIRED_META_KEYS
from bench_harness.tasks import TaskDefinition


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_PATH = REPO_ROOT / "models" / "common"
RUNNER_PATH = REPO_ROOT / "models" / "partcrafter" / "runner.py"
MODEL_SPEC_PATH = REPO_ROOT / "models" / "partcrafter" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "partcrafter" / "Dockerfile"
sys.path.insert(0, str(COMMON_PATH))

import runner_utils  # noqa: E402


def _load_runner(monkeypatch):
    monkeypatch.setenv("PARTCRAFTER_WEIGHTS_PATH", "/workspace/weights/PartCrafter")
    monkeypatch.setenv("RMBG_WEIGHTS_PATH", "/workspace/weights/RMBG-1.4")
    spec = importlib.util.spec_from_file_location("partcrafter_runner", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["partcrafter_runner"] = module
    spec.loader.exec_module(module)
    return module


def test_partcrafter_model_spec_records_current_pins() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec == {
        "id": "partcrafter",
        "name": "PartCrafter",
        "input": "image",
        "output": "part-aware-mesh",
        "code_repo": "https://github.com/wgsxm/PartCrafter",
        "code_commit": "3d773bf02fad51c7ab31a5615573fec93b287b30",
        "weights_repo": "wgsxm/PartCrafter",
        "weights_revision": "69a0ffc1dad5e48e7e5ed91c0609f2b1276eb31f",
        "auxiliary_weights": {
            "rmbg_repo": "briaai/RMBG-1.4",
            "rmbg_revision": "2ceba5a5efaec153162aedea169f76caf9b46cf8",
        },
        "license": "MIT plus bundled third-party notices",
        "default_parameters": {
            "num_parts": 3,
            "num_tokens": 1024,
            "num_inference_steps": 50,
            "guidance_scale": 7.0,
            "max_num_expanded_coords": 1000000000,
            "use_flash_decoder": False,
            "rmbg": True,
            "part_suggest": False,
            "style_transfer": False,
            "dtype": "float16",
            "partcrafter_weights_path": "/workspace/weights/PartCrafter",
            "rmbg_weights_path": "/workspace/weights/RMBG-1.4",
        },
    }


def test_partcrafter_dockerfile_uses_required_cuda_base_and_pins() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04" in dockerfile
    assert "ARG PARTCRAFTER_COMMIT=3d773bf02fad51c7ab31a5615573fec93b287b30" in dockerfile
    assert "ARG PARTCRAFTER_WEIGHTS_REVISION=69a0ffc1dad5e48e7e5ed91c0609f2b1276eb31f" in dockerfile
    assert "ARG RMBG_WEIGHTS_REVISION=2ceba5a5efaec153162aedea169f76caf9b46cf8" in dockerfile
    assert "snapshot_download(" not in dockerfile
    assert "PARTCRAFTER_WEIGHTS_PATH=/workspace/weights/PartCrafter" in dockerfile
    assert "RMBG_WEIGHTS_PATH=/workspace/weights/RMBG-1.4" in dockerfile
    assert "torch==2.7.0" in dockerfile
    assert "torchvision==0.22.0" in dockerfile
    assert "https://download.pytorch.org/whl/cu128" in dockerfile
    assert "https://data.pyg.org/whl/torch-2.7.0+cu128.html" in dockerfile
    assert "CUDA_HOME=/usr/local/cuda" in dockerfile
    assert "CPATH=/usr/local/cuda/include" in dockerfile
    assert "uv pip install" in dockerfile
    assert "RUN pip install" not in dockerfile
    assert "boto3" in dockerfile
    assert "openssh-server" in dockerfile
    assert "PYTHONPATH=/opt/bench/src" in dockerfile
    assert "COPY bench/src /opt/bench/src" in dockerfile
    assert "COPY tasks /opt/3dgen-tasks" in dockerfile
    assert "COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py" in dockerfile
    assert "COPY models/partcrafter/runner.py /opt/3dgen-runner/partcrafter_runner.py" in dockerfile


def test_build_partcrafter_command_uses_volume_pinned_weights_and_no_external_api(
    monkeypatch, tmp_path: Path
    ) -> None:
    runner = _load_runner(monkeypatch)
    assert runner.PARTCRAFTER_WEIGHTS_PATH == "/workspace/weights/PartCrafter"
    assert runner.RMBG_WEIGHTS_PATH == "/workspace/weights/RMBG-1.4"
    command = runner.build_partcrafter_command(
        image_path=tmp_path / "input.png",
        raw_output_dir=tmp_path / "raw",
        seed=20260708,
        parameters=runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/3dgen-runner/partcrafter_runner.py",
        "--infer-image",
        str(tmp_path / "input.png"),
        "--infer-output-dir",
        str(tmp_path / "raw"),
        "--infer-seed",
        "20260708",
        "--infer-num-parts",
        "3",
        "--infer-num-tokens",
        "1024",
        "--infer-num-inference-steps",
        "50",
        "--infer-guidance-scale",
        "7.0",
        "--infer-max-num-expanded-coords",
        "1000000000",
        "--infer-partcrafter-weights-path",
        "/workspace/weights/PartCrafter",
        "--infer-rmbg-weights-path",
        "/workspace/weights/RMBG-1.4",
        "--infer-rmbg",
    ]
    assert "--part_suggest" not in command
    assert "--style_transfer" not in command


def test_partcrafter_incremental_upload_uses_task_id_prefix(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner(monkeypatch)
    task_dir = tmp_path / "task-a"
    task_dir.mkdir()
    (task_dir / "meta.json").write_text("{}", encoding="utf-8")
    uploaded = []

    def fake_upload(self, source_dir: Path, relative_name: str = "") -> list[str]:
        uploaded.append((source_dir, relative_name))
        return ["runs/partcrafter/wave1/test/task-a/meta.json"]

    monkeypatch.setenv("RUNPOD_INCREMENTAL_S3_TARGET", "s3://3dgen-runs/runs/partcrafter/wave1/test")
    monkeypatch.setenv("R2_ENDPOINT", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret-key")
    monkeypatch.setattr("bench_harness.uploader.S3Uploader.upload_run", fake_upload)

    assert runner.upload_task_increment_if_configured(task_dir, "task-a", dict(os.environ)) == [
        "runs/partcrafter/wave1/test/task-a/meta.json",
    ]
    assert uploaded == [(task_dir, "task-a")]


def test_partcrafter_runner_requires_explicit_weight_env(monkeypatch) -> None:
    monkeypatch.delenv("PARTCRAFTER_WEIGHTS_PATH", raising=False)
    monkeypatch.delenv("RMBG_WEIGHTS_PATH", raising=False)

    spec = importlib.util.spec_from_file_location("partcrafter_runner_missing_env", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["partcrafter_runner_missing_env"] = module

    try:
        spec.loader.exec_module(module)
    except ValueError as exc:
        assert "PARTCRAFTER_WEIGHTS_PATH" in str(exc)
    else:
        raise AssertionError("runner import should fail without explicit weight env")


def test_prepare_task_output_writes_partcrafter_contract_files(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner(monkeypatch)
    task = TaskDefinition(
        id="cartoon-apple",
        prompt="A stylized cartoon red apple",
        image="references/cartoon-apple.png",
        seed=20260708,
    )
    raw_output_dir = tmp_path / "raw"
    raw_output_dir.mkdir()
    (raw_output_dir / "object.glb").write_bytes(b"glTF")
    (raw_output_dir / "part_00.glb").write_bytes(b"part0")
    (raw_output_dir / "part_01.glb").write_bytes(b"part1")
    (raw_output_dir / "part_02.glb").write_bytes(b"part2")
    (raw_output_dir / "manifest.json").write_text('{"num_parts": 3}\n', encoding="utf-8")
    license_sources = runner.LicenseSources(
        root_license=tmp_path / "LICENSE",
        rmbg_license=tmp_path / "RMBG_LICENSE",
    )
    license_sources.root_license.write_text("MIT\n", encoding="utf-8")
    license_sources.rmbg_license.write_text("RMBG\n", encoding="utf-8")
    task_output_dir = tmp_path / "out"

    runner.prepare_task_output(
        task=task,
        task_output_dir=task_output_dir,
        raw_output_dir=raw_output_dir,
        license_sources=license_sources,
        runtime=runner.RuntimeSnapshot(
            gpu_name="NVIDIA GeForce RTX 4070 Ti",
            peak_vram_bytes=1234,
            torch_version="2.7.0+cu128",
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
    assert set(meta) == REQUIRED_META_KEYS
    assert meta["model_id"] == "partcrafter"
    assert meta["model_git_commit"] == "3d773bf02fad51c7ab31a5615573fec93b287b30"
    assert meta["weights_revision"] == "69a0ffc1dad5e48e7e5ed91c0609f2b1276eb31f"
    assert meta["parameters"] == runner.DEFAULT_PARAMETERS
    assert meta["license_file"] == "LICENSES.txt"
    assert (task_output_dir / "output.glb").read_bytes() == b"glTF"
    assert (task_output_dir / "raw" / "partcrafter" / "object.glb").read_bytes() == b"glTF"
    assert (task_output_dir / "raw" / "partcrafter" / "part_02.glb").read_bytes() == b"part2"
    licenses = (task_output_dir / "LICENSES.txt").read_text(encoding="utf-8")
    assert "MIT" in licenses
    assert "RMBG" in licenses


def test_run_task_retries_once_and_records_retry_count(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner(monkeypatch)
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    (input_root / "input.png").write_bytes(b"png")
    license_sources = runner.LicenseSources(
        root_license=tmp_path / "LICENSE",
        rmbg_license=tmp_path / "RMBG_LICENSE",
    )
    license_sources.root_license.write_text("MIT\n", encoding="utf-8")
    license_sources.rmbg_license.write_text("RMBG\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run_with_peak_vram(
        command: list[str],
        timeout_seconds: float,
        timeout_label: str,
        *,
        log_path: Path | None = None,
    ) -> int:
        calls.append(command)
        if len(calls) == 1:
            raise RuntimeError("transient decoder failure")
        raw_output_dir = Path(command[command.index("--infer-output-dir") + 1])
        (raw_output_dir / "object.glb").write_bytes(b"glTF")
        (raw_output_dir / "part_00.glb").write_bytes(b"part0")
        (raw_output_dir / "part_01.glb").write_bytes(b"part1")
        (raw_output_dir / "part_02.glb").write_bytes(b"part2")
        (raw_output_dir / "manifest.json").write_text('{"num_parts": 3}\n', encoding="utf-8")
        return 1234

    monkeypatch.setattr(runner, "run_with_peak_vram", fake_run_with_peak_vram)
    monkeypatch.setattr(
        runner,
        "collect_runtime_snapshot",
        lambda peak, attention_backend: runner.RuntimeSnapshot(
            gpu_name="NVIDIA GeForce RTX 5090",
            peak_vram_bytes=peak,
            torch_version="2.7.0+cu128",
            torch_cuda_version="12.8",
            torch_cuda_arch_list=["sm_120"],
            attention_backend="sdpa",
        ),
    )

    runner.run_task(
        runner.TaskDefinition(id="cartoon-apple", prompt="apple", image="input.png", seed=20260708),
        input_root,
        output_root,
        license_sources,
        timeout_seconds=10,
    )

    meta = json.loads((output_root / "cartoon-apple" / "meta.json").read_text(encoding="utf-8"))
    assert len(calls) == 2
    assert meta["retry_count"] == 1
    assert (output_root / "cartoon-apple" / "output.glb").read_bytes() == b"glTF"


def test_run_task_upload_failure_does_not_retry_successful_partcrafter_task(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner(monkeypatch)
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    (input_root / "input.png").write_bytes(b"png")
    license_sources = runner.LicenseSources(
        root_license=tmp_path / "LICENSE",
        rmbg_license=tmp_path / "RMBG_LICENSE",
    )
    license_sources.root_license.write_text("MIT\n", encoding="utf-8")
    license_sources.rmbg_license.write_text("RMBG\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run_with_peak_vram(
        command: list[str],
        timeout_seconds: float,
        timeout_label: str,
        *,
        log_path: Path | None = None,
    ) -> int:
        calls.append(command)
        raw_output_dir = Path(command[command.index("--infer-output-dir") + 1])
        (raw_output_dir / "object.glb").write_bytes(b"glTF")
        (raw_output_dir / "part_00.glb").write_bytes(b"part0")
        (raw_output_dir / "part_01.glb").write_bytes(b"part1")
        (raw_output_dir / "part_02.glb").write_bytes(b"part2")
        (raw_output_dir / "manifest.json").write_text('{"num_parts": 3}\n', encoding="utf-8")
        return 1234

    monkeypatch.setattr(runner, "run_with_peak_vram", fake_run_with_peak_vram)
    monkeypatch.setattr(
        runner,
        "collect_runtime_snapshot",
        lambda peak, attention_backend: runner.RuntimeSnapshot(
            gpu_name="NVIDIA GeForce RTX 5090",
            peak_vram_bytes=peak,
            torch_version="2.7.0+cu128",
            torch_cuda_version="12.8",
            torch_cuda_arch_list=["sm_120"],
            attention_backend="sdpa",
        ),
    )
    monkeypatch.setattr(
        runner,
        "upload_task_increment_if_configured",
        lambda task_output_dir, task_id, env: (_ for _ in ()).throw(RuntimeError("r2 upload failed")),
    )

    try:
        runner.run_task(
            runner.TaskDefinition(id="cartoon-apple", prompt="apple", image="input.png", seed=20260708),
            input_root,
            output_root,
            license_sources,
            timeout_seconds=10,
        )
    except RuntimeError as exc:
        assert "r2 upload failed" in str(exc)
    else:
        raise AssertionError("incremental upload failure should fail the task run")

    assert len(calls) == 1
    assert (output_root / "cartoon-apple" / "meta.json").is_file()


def test_run_task_writes_failure_record_after_retry(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner(monkeypatch)
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    (input_root / "input.png").write_bytes(b"png")
    license_sources = runner.LicenseSources(
        root_license=tmp_path / "LICENSE",
        rmbg_license=tmp_path / "RMBG_LICENSE",
    )
    calls: list[list[str]] = []

    def fake_run_with_peak_vram(
        command: list[str],
        timeout_seconds: float,
        timeout_label: str,
        *,
        log_path: Path | None = None,
    ) -> int:
        calls.append(command)
        raise RuntimeError("persistent decoder failure")

    monkeypatch.setattr(runner, "run_with_peak_vram", fake_run_with_peak_vram)

    runner.run_task(
        runner.TaskDefinition(id="cartoon-apple", prompt="apple", image="input.png", seed=20260708),
        input_root,
        output_root,
        license_sources,
        timeout_seconds=10,
    )

    failure = json.loads((output_root / "cartoon-apple" / "failure.json").read_text(encoding="utf-8"))
    assert len(calls) == 2
    assert failure["status"] == "failed"
    assert failure["model_id"] == "partcrafter"
    assert failure["task_id"] == "cartoon-apple"
    assert failure["retry_count"] == 1
    assert failure["error_type"] == "RuntimeError"
    assert "persistent decoder failure" in failure["error_message"]


def test_run_task_timeout_writes_and_uploads_failure_before_reraising(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner(monkeypatch)
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()
    output_root.mkdir()
    (input_root / "input.png").write_bytes(b"png")
    license_sources = runner.LicenseSources(
        root_license=tmp_path / "LICENSE",
        rmbg_license=tmp_path / "RMBG_LICENSE",
    )
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
            output_tail="diffusion step timed out",
        )

    def fake_upload(task_output_dir: Path, task_id: str, env: dict[str, str]) -> list[str]:
        failure = json.loads((task_output_dir / "failure.json").read_text(encoding="utf-8"))
        assert failure["error_output_tail"] == "diffusion step timed out"
        assert (task_output_dir / "infer.log").read_text(encoding="utf-8") == "diffusion step timed out\n"
        uploads.append(task_id)
        return [f"{task_id}/failure.json", f"{task_id}/infer.log"]

    monkeypatch.setattr(runner, "run_with_peak_vram", fake_run_with_peak_vram)
    monkeypatch.setattr(runner, "upload_task_increment_if_configured", fake_upload)

    with pytest.raises(runner_utils.RunnerTimeoutError):
        runner.run_task(
            runner.TaskDefinition(id="cartoon-apple", prompt="apple", image="input.png", seed=20260708),
            input_root,
            output_root,
            license_sources,
            timeout_seconds=10,
        )

    failure = json.loads((output_root / "cartoon-apple" / "failure.json").read_text(encoding="utf-8"))
    assert len(calls) == 1
    assert uploads == ["cartoon-apple"]
    assert failure["retry_count"] == 0
    assert failure["error_type"] == "RunnerTimeoutError"
    assert (output_root / "cartoon-apple" / "infer.log").is_file()
