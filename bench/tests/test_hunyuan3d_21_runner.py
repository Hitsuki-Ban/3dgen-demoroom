from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_SPEC_PATH = REPO_ROOT / "models" / "hunyuan3d-21" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "hunyuan3d-21" / "Dockerfile"


def load_hunyuan3d_21_runner() -> ModuleType:
    sys.path.insert(0, str(REPO_ROOT / "models" / "common"))
    runner_path = REPO_ROOT / "models" / "hunyuan3d-21" / "runner.py"
    spec = importlib.util.spec_from_file_location("hunyuan3d_21_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runner from {runner_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_hunyuan3d_21_command_uses_shape_texture_defaults_and_staged_weights(monkeypatch) -> None:
    monkeypatch.setenv("HUNYUAN3D_21_WEIGHTS_PATH", "/workspace/weights/Hunyuan3D-2.1")
    runner = load_hunyuan3d_21_runner()

    command = runner.build_hunyuan3d_21_command(
        Path("/work/input/references/cartoon-apple.png"),
        Path("/work/output/_work/hunyuan3d-21/cartoon-apple/raw"),
        20260708,
        runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/3dgen-runner/hunyuan3d_21_runner.py",
        "--infer-image",
        "/work/input/references/cartoon-apple.png",
        "--infer-output-dir",
        "/work/output/_work/hunyuan3d-21/cartoon-apple/raw",
        "--infer-seed",
        "20260708",
        "--infer-num-inference-steps",
        "50",
        "--infer-guidance-scale",
        "5.0",
        "--infer-octree-resolution",
        "384",
        "--infer-texture-resolution",
        "512",
        "--infer-hunyuan3d-21-weights-path",
        "/workspace/weights/Hunyuan3D-2.1",
    ]


def test_prepare_hunyuan3d_21_task_output_writes_textured_meta_and_raw_geometry(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HUNYUAN3D_21_WEIGHTS_PATH", "/workspace/weights/Hunyuan3D-2.1")
    runner = load_hunyuan3d_21_runner()
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "output.glb").write_bytes(b"textured-glb")
    (raw / "geometry.glb").write_bytes(b"geometry-glb")
    (raw / "textured_mesh.obj").write_text("obj\n", encoding="utf-8")
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
        gpu_name="NVIDIA RTX 6000 Ada Generation",
        peak_vram_bytes=29 * 1024**3,
        torch_version="2.5.1+cu124",
        torch_cuda_version="12.4",
        torch_cuda_arch_list=["sm_89"],
        attention_backend="xformers",
    )

    runner.prepare_task_output(
        task=task,
        task_output_dir=tmp_path / "task-output",
        raw_output_dir=raw,
        license_sources=[
            runner.LicenseSource("Hunyuan3D-2.1 LICENSE", license_path),
            runner.LicenseSource("Hunyuan3D-2.1 model card and license metadata", model_card_path),
        ],
        runtime=runtime,
        wall_clock_seconds=300.0,
        retry_count=0,
        started_at="2026-07-09T06:00:00Z",
        finished_at="2026-07-09T06:05:00Z",
    )

    meta = json.loads((tmp_path / "task-output" / "meta.json").read_text(encoding="utf-8"))
    assert meta["model_id"] == "hunyuan3d-21"
    assert meta["parameters"]["shape_subfolder"] == "hunyuan3d-dit-v2-1"
    assert meta["parameters"]["texture_subfolder"] == "hunyuan3d-paintpbr-v2-1"
    assert meta["parameters"]["num_inference_steps"] == 50
    assert meta["parameters"]["guidance_scale"] == 5.0
    assert meta["parameters"]["octree_resolution"] == 384
    assert meta["parameters"]["texture_resolution"] == 512
    assert meta["parameters"]["texture"] is True
    assert (tmp_path / "task-output" / "output.glb").read_bytes() == b"textured-glb"
    assert (tmp_path / "task-output" / "raw" / "hunyuan3d-21" / "geometry.glb").read_bytes() == b"geometry-glb"


def test_hunyuan3d_21_model_spec_records_current_pins_and_region_policy() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["id"] == "hunyuan3d-21"
    assert spec["code_repo"] == "https://github.com/tencent-hunyuan/hunyuan3d-2.1"
    assert spec["code_commit"] == "82920d643c0dc2f7bfd7255f45f62d386edfe60c"
    assert spec["weights_repo"] == "tencent/Hunyuan3D-2.1"
    assert spec["weights_revision"] == "0b94677654c57bb9a6b6845cd7b704ccf551d327"
    assert spec["default_parameters"]["shape_subfolder"] == "hunyuan3d-dit-v2-1"
    assert spec["default_parameters"]["texture_subfolder"] == "hunyuan3d-paintpbr-v2-1"
    assert spec["default_parameters"]["texture"] is True
    assert spec["default_parameters"]["texture_resolution"] == 512
    assert spec["distribution_restrictions"]["block_regions"] == ["EU27", "GB", "KR"]
    assert spec["runpod_policy"]["preferred_data_center_id"] == "US-KS-2"


def test_hunyuan3d_21_dockerfile_uses_runtime_only_volume_paths() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "ARG HUNYUAN3D_21_COMMIT=82920d643c0dc2f7bfd7255f45f62d386edfe60c" in dockerfile
    assert "ARG HUNYUAN3D_21_WEIGHTS_REVISION=0b94677654c57bb9a6b6845cd7b704ccf551d327" in dockerfile
    assert "HUNYUAN3D_21_WEIGHTS_PATH=/workspace/weights/Hunyuan3D-2.1" in dockerfile
    assert "HF_HOME=/workspace/hf" in dockerfile
    assert "TORCH_HOME=/workspace/torch" in dockerfile
    assert "RUN wget" not in dockerfile
    assert "snapshot_download(" not in dockerfile
    assert "HF_TOKEN" not in dockerfile
    assert "RUN pip install" not in dockerfile
    assert 'TORCH_CUDA_ARCH_LIST="8.0;8.9"' in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "bpy-4.0.0-cp310-cp310-manylinux_2_28_x86_64.whl" in dockerfile
    assert "python3 -m pybind11 --includes" in dockerfile
    assert "hunyuan3d-21-requirements-constraints.txt" in dockerfile
    assert "MAX_JOBS=1 uv pip install --system --no-build-isolation" in dockerfile
    assert "--index-strategy unsafe-best-match" in dockerfile
    assert "--constraint /tmp/hunyuan3d-21-requirements-constraints.txt" in dockerfile
    assert "custom_rasterizer" in dockerfile
    assert "compile_mesh_painter.sh" in dockerfile
    assert "uv pip install --system boto3" in dockerfile
    assert "COPY models/hunyuan3d-21/runner.py /opt/3dgen-runner/hunyuan3d_21_runner.py" in dockerfile
