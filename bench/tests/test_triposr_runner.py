import importlib.util
import json
import sys
from pathlib import Path

from bench_harness.meta import REQUIRED_META_KEYS
from bench_harness.tasks import TaskDefinition


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "models" / "triposr" / "runner.py"
MODEL_SPEC_PATH = REPO_ROOT / "models" / "triposr" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "triposr" / "Dockerfile"


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
            "no_remove_bg": True,
            "pretrained_model_name_or_path": "/opt/weights/TripoSR",
        },
    }


def test_dockerfile_uses_required_cuda_base_and_pins() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04" in dockerfile
    assert "ARG TRIPOSR_COMMIT=107cefdc244c39106fa830359024f6a2f1c78871" in dockerfile
    assert "ARG TRIPOSR_WEIGHTS_REVISION=5b521936b01fbe1890f6f9baed0254ab6351c04a" in dockerfile
    assert 'revision=os.environ["TRIPOSR_WEIGHTS_REVISION"]' in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "RUN pip install" not in dockerfile


def test_build_triposr_command_uses_local_pinned_weights(tmp_path: Path) -> None:
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
        "--no-remove-bg",
    ]


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
            gpu_name="NVIDIA GeForce RTX 4070 Ti",
            peak_vram_bytes=1234,
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
    assert set(meta) == REQUIRED_META_KEYS
    assert meta["model_id"] == "triposr"
    assert meta["model_git_commit"] == "107cefdc244c39106fa830359024f6a2f1c78871"
    assert meta["weights_revision"] == "5b521936b01fbe1890f6f9baed0254ab6351c04a"
    assert meta["parameters"] == runner.DEFAULT_PARAMETERS
    assert (task_output_dir / "output.glb").read_bytes() == b"glTF"
    assert (task_output_dir / "LICENSE").read_text(encoding="utf-8") == "MIT\n"
    assert (task_output_dir / "raw" / "triposr" / "0" / "mesh.glb").read_bytes() == b"glTF"
