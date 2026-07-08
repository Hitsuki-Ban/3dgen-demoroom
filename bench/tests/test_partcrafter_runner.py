import importlib.util
import json
import sys
from pathlib import Path

from bench_harness.meta import REQUIRED_META_KEYS
from bench_harness.tasks import TaskDefinition


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "models" / "partcrafter" / "runner.py"
MODEL_SPEC_PATH = REPO_ROOT / "models" / "partcrafter" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "partcrafter" / "Dockerfile"


def _load_runner():
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
            "partcrafter_weights_path": "/opt/weights/PartCrafter",
            "rmbg_weights_path": "/opt/weights/RMBG-1.4",
        },
    }


def test_partcrafter_dockerfile_uses_required_cuda_base_and_pins() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04" in dockerfile
    assert "ARG PARTCRAFTER_COMMIT=3d773bf02fad51c7ab31a5615573fec93b287b30" in dockerfile
    assert "ARG PARTCRAFTER_WEIGHTS_REVISION=69a0ffc1dad5e48e7e5ed91c0609f2b1276eb31f" in dockerfile
    assert "ARG RMBG_WEIGHTS_REVISION=2ceba5a5efaec153162aedea169f76caf9b46cf8" in dockerfile
    assert 'revision=os.environ["PARTCRAFTER_WEIGHTS_REVISION"]' in dockerfile
    assert 'revision=os.environ["RMBG_WEIGHTS_REVISION"]' in dockerfile
    assert "torch==2.7.0" in dockerfile
    assert "torchvision==0.22.0" in dockerfile
    assert "https://download.pytorch.org/whl/cu128" in dockerfile
    assert "https://data.pyg.org/whl/torch-2.7.0+cu128.html" in dockerfile
    assert "CUDA_HOME=/usr/local/cuda" in dockerfile
    assert "CPATH=/usr/local/cuda/include" in dockerfile
    assert "uv pip install" in dockerfile
    assert "RUN pip install" not in dockerfile


def test_build_partcrafter_command_uses_local_pinned_weights_and_no_external_api(tmp_path: Path) -> None:
    runner = _load_runner()
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
        "/opt/weights/PartCrafter",
        "--infer-rmbg-weights-path",
        "/opt/weights/RMBG-1.4",
        "--infer-rmbg",
    ]
    assert "--part_suggest" not in command
    assert "--style_transfer" not in command


def test_prepare_task_output_writes_partcrafter_contract_files(tmp_path: Path) -> None:
    runner = _load_runner()
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
