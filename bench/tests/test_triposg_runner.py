import importlib.util
import json
import sys
from pathlib import Path

from bench_harness.meta import REQUIRED_META_KEYS
from bench_harness.tasks import TaskDefinition


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "models" / "triposg" / "runner.py"
MODEL_SPEC_PATH = REPO_ROOT / "models" / "triposg" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "triposg" / "Dockerfile"


def _load_runner():
    spec = importlib.util.spec_from_file_location("triposg_runner", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["triposg_runner"] = module
    spec.loader.exec_module(module)
    return module


def test_triposg_model_spec_records_current_pins() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec == {
        "id": "triposg",
        "name": "TripoSG",
        "input": "image",
        "output": "geometry-mesh",
        "code_repo": "https://github.com/VAST-AI-Research/TripoSG",
        "code_commit": "fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c",
        "weights_repo": "VAST-AI/TripoSG",
        "weights_revision": "2c1c516d22d58db486a058d98d31bb6177344e06",
        "auxiliary_weights": {
            "rmbg_repo": "briaai/RMBG-1.4",
            "rmbg_revision": "2ceba5a5efaec153162aedea169f76caf9b46cf8",
        },
        "license": "MIT plus bundled third-party notices",
        "default_parameters": {
            "num_inference_steps": 50,
            "num_tokens": 2048,
            "guidance_scale": 7.0,
            "dense_octree_depth": 8,
            "hierarchical_octree_depth": 9,
            "flash_octree_depth": 9,
            "use_flash_decoder": True,
            "faces": -1,
            "dtype": "float16",
            "triposg_weights_path": "/opt/weights/TripoSG",
            "rmbg_weights_path": "/opt/weights/RMBG-1.4",
        },
    }


def test_triposg_dockerfile_uses_required_cuda_base_and_pins() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04" in dockerfile
    assert "ARG TRIPOSG_COMMIT=fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c" in dockerfile
    assert "ARG TRIPOSG_WEIGHTS_REVISION=2c1c516d22d58db486a058d98d31bb6177344e06" in dockerfile
    assert "ARG RMBG_WEIGHTS_REVISION=2ceba5a5efaec153162aedea169f76caf9b46cf8" in dockerfile
    assert 'revision=os.environ["TRIPOSG_WEIGHTS_REVISION"]' in dockerfile
    assert 'revision=os.environ["RMBG_WEIGHTS_REVISION"]' in dockerfile
    assert "torch==2.7.1" in dockerfile
    assert "torchvision==0.22.1" in dockerfile
    assert "https://download.pytorch.org/whl/cu128" in dockerfile
    assert "--no-build-isolation-package diso" in dockerfile
    assert "CUDA_HOME=/usr/local/cuda" in dockerfile
    assert "FORCE_CUDA=1" in dockerfile
    assert "CPATH=/usr/local/cuda/include" in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "RUN pip install" not in dockerfile


def test_build_triposg_command_uses_local_pinned_weights(tmp_path: Path) -> None:
    runner = _load_runner()
    command = runner.build_triposg_command(
        image_path=tmp_path / "input.png",
        raw_output_dir=tmp_path / "raw",
        seed=20260708,
        parameters=runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/3dgen-runner/triposg_runner.py",
        "--infer-image",
        str(tmp_path / "input.png"),
        "--infer-output-path",
        str(tmp_path / "raw" / "output.glb"),
        "--infer-seed",
        "20260708",
        "--infer-num-inference-steps",
        "50",
        "--infer-num-tokens",
        "2048",
        "--infer-guidance-scale",
        "7.0",
        "--infer-dense-octree-depth",
        "8",
        "--infer-hierarchical-octree-depth",
        "9",
        "--infer-flash-octree-depth",
        "9",
        "--infer-use-flash-decoder",
        "--infer-faces",
        "-1",
        "--infer-triposg-weights-path",
        "/opt/weights/TripoSG",
        "--infer-rmbg-weights-path",
        "/opt/weights/RMBG-1.4",
    ]


def test_prepare_task_output_writes_triposg_contract_files(tmp_path: Path) -> None:
    runner = _load_runner()
    task = TaskDefinition(
        id="cartoon-apple",
        prompt="A stylized cartoon red apple",
        image="references/cartoon-apple.png",
        seed=20260708,
    )
    raw_output_dir = tmp_path / "raw"
    raw_output_dir.mkdir()
    (raw_output_dir / "output.glb").write_bytes(b"glTF")
    license_sources = runner.LicenseSources(
        root_license=tmp_path / "LICENSE",
        notice=tmp_path / "NOTICE",
        bundled_license=tmp_path / "triposg_LICENSE",
    )
    license_sources.root_license.write_text("MIT\n", encoding="utf-8")
    license_sources.notice.write_text("NOTICE\n", encoding="utf-8")
    license_sources.bundled_license.write_text("Tencent\n", encoding="utf-8")
    task_output_dir = tmp_path / "out"

    runner.prepare_task_output(
        task=task,
        task_output_dir=task_output_dir,
        raw_output_dir=raw_output_dir,
        license_sources=license_sources,
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
    assert meta["model_id"] == "triposg"
    assert meta["model_git_commit"] == "fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c"
    assert meta["weights_revision"] == "2c1c516d22d58db486a058d98d31bb6177344e06"
    assert meta["parameters"] == runner.DEFAULT_PARAMETERS
    assert meta["license_file"] == "LICENSES.txt"
    assert (task_output_dir / "output.glb").read_bytes() == b"glTF"
    assert (task_output_dir / "raw" / "triposg" / "output.glb").read_bytes() == b"glTF"
    licenses = (task_output_dir / "LICENSES.txt").read_text(encoding="utf-8")
    assert "MIT" in licenses
    assert "NOTICE" in licenses
    assert "Tencent" in licenses
