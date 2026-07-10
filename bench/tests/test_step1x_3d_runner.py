from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_SPEC_PATH = REPO_ROOT / "models" / "step1x-3d" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "step1x-3d" / "Dockerfile"


def load_step1x_3d_runner() -> ModuleType:
    sys.path.insert(0, str(REPO_ROOT / "models" / "common"))
    runner_path = REPO_ROOT / "models" / "step1x-3d" / "runner.py"
    spec = importlib.util.spec_from_file_location("step1x_3d_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runner from {runner_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_step1x_3d_command_uses_official_geometry_texture_and_staged_weights(monkeypatch) -> None:
    monkeypatch.setenv("STEP1X_3D_WEIGHTS_PATH", "/workspace/weights/Step1X-3D")
    runner = load_step1x_3d_runner()

    command = runner.build_step1x_3d_command(
        Path("/work/input/references/cartoon-apple.png"),
        Path("/work/output/_work/step1x-3d/cartoon-apple/raw"),
        20260708,
        runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/3dgen-runner/step1x_3d_runner.py",
        "--infer-image",
        "/work/input/references/cartoon-apple.png",
        "--infer-output-dir",
        "/work/output/_work/step1x-3d/cartoon-apple/raw",
        "--infer-seed",
        "20260708",
        "--infer-geometry-subfolder",
        "Step1X-3D-Geometry-1300m",
        "--infer-texture-subfolder",
        "Step1X-3D-Texture",
        "--infer-step1x-3d-weights-path",
        "/workspace/weights/Step1X-3D",
    ]


def test_prepare_step1x_3d_task_output_writes_textured_meta_and_raw_geometry(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("STEP1X_3D_WEIGHTS_PATH", "/workspace/weights/Step1X-3D")
    runner = load_step1x_3d_runner()
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "output.glb").write_bytes(b"textured-glb")
    (raw / "geometry.glb").write_bytes(b"geometry-glb")
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
        peak_vram_bytes=29 * 1024**3,
        torch_version="2.7.1+cu128",
        torch_cuda_version="12.8",
        torch_cuda_arch_list=["sm_120"],
        attention_backend="official",
    )

    runner.prepare_task_output(
        task=task,
        task_output_dir=tmp_path / "task-output",
        raw_output_dir=raw,
        license_sources=[
            runner.LicenseSource("Step1X-3D LICENSE", license_path),
            runner.LicenseSource("Step1X-3D model card and license metadata", model_card_path),
        ],
        runtime=runtime,
        wall_clock_seconds=152.0,
        retry_count=0,
        started_at="2026-07-09T06:00:00Z",
        finished_at="2026-07-09T06:02:32Z",
    )

    meta = json.loads((tmp_path / "task-output" / "meta.json").read_text(encoding="utf-8"))
    assert meta["model_id"] == "step1x-3d"
    assert meta["parameters"]["geometry_subfolder"] == "Step1X-3D-Geometry-1300m"
    assert meta["parameters"]["texture_subfolder"] == "Step1X-3D-Texture"
    assert meta["parameters"]["num_inference_steps"] == 50
    assert meta["parameters"]["guidance_scale"] == 7.5
    assert meta["parameters"]["texture"] is True
    assert meta["external_weight_revisions"] == runner.EXTERNAL_WEIGHT_REVISIONS
    assert (tmp_path / "task-output" / "output.glb").read_bytes() == b"textured-glb"
    assert (tmp_path / "task-output" / "raw" / "step1x-3d" / "geometry.glb").read_bytes() == b"geometry-glb"


def test_step1x_3d_model_spec_records_current_pins() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["id"] == "step1x-3d"
    assert spec["code_repo"] == "https://github.com/stepfun-ai/Step1X-3D"
    assert spec["code_commit"] == "cb5ac944709c6c913109070c7b90c3447f57f3d4"
    assert spec["weights_repo"] == "stepfun-ai/Step1X-3D"
    assert spec["weights_revision"] == "bf7084495b3a72222f36549b7942948aa4d9daa7"
    assert spec["external_weight_dependencies"] == [
        "facebook/dinov2-with-registers-large",
        "stabilityai/stable-diffusion-xl-base-1.0",
        "madebyollin/sdxl-vae-fp16-fix",
        "ZhengPeng7/BiRefNet",
    ]
    assert spec["external_weight_revisions"] == {
        "facebook/dinov2-with-registers-large": "e4c89a4e05589de9b3e188688a303d0f3c04d0f3",
        "stabilityai/stable-diffusion-xl-base-1.0": "462165984030d82259a11f4367a4eed129e94a7b",
        "madebyollin/sdxl-vae-fp16-fix": "207b116dae70ace3637169f1ddd2434b91b3a8cd",
        "ZhengPeng7/BiRefNet": "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4",
    }
    assert spec["default_parameters"]["geometry_subfolder"] == "Step1X-3D-Geometry-1300m"
    assert spec["default_parameters"]["texture_subfolder"] == "Step1X-3D-Texture"
    assert spec["default_parameters"]["num_inference_steps"] == 50
    assert spec["default_parameters"]["guidance_scale"] == 7.5
    assert spec["default_parameters"]["texture"] is True


def test_step1x_3d_dockerfile_uses_runtime_only_volume_paths() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "ARG STEP1X_3D_COMMIT=cb5ac944709c6c913109070c7b90c3447f57f3d4" in dockerfile
    assert "ARG STEP1X_3D_WEIGHTS_REVISION=bf7084495b3a72222f36549b7942948aa4d9daa7" in dockerfile
    assert "STEP1X_3D_WEIGHTS_PATH=/workspace/weights/Step1X-3D" in dockerfile
    assert "HF_HOME=/workspace/hf" in dockerfile
    assert "TORCH_HOME=/workspace/torch" in dockerfile
    assert "snapshot_download(" not in dockerfile
    assert "HF_TOKEN" not in dockerfile
    assert "RUN pip install" not in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "MAX_JOBS=1 uv pip install --system --no-build-isolation -r /opt/Step1X-3D/requirements.txt" in dockerfile
    assert "custom_rasterizer" in dockerfile
    assert "differentiable_renderer" in dockerfile
    assert "COPY models/step1x-3d/runner.py /opt/3dgen-runner/step1x_3d_runner.py" in dockerfile


def test_require_staged_hf_snapshot_checks_main_ref_and_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STEP1X_3D_WEIGHTS_PATH", "/workspace/weights/Step1X-3D")
    runner = load_step1x_3d_runner()
    repo_cache = tmp_path / "hub" / "models--example--model"
    snapshot = repo_cache / "snapshots" / "revision-123"
    snapshot.mkdir(parents=True)
    (repo_cache / "refs").mkdir()
    (repo_cache / "refs" / "main").write_text("revision-123\n", encoding="utf-8")
    (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(b"weights")

    assert runner.require_staged_hf_snapshot(
        tmp_path,
        repo_cache_name="models--example--model",
        revision="revision-123",
        required_files=("config.json", "model.safetensors"),
    ) == snapshot

    (repo_cache / "refs" / "main").write_text("unexpected\n", encoding="utf-8")
    try:
        runner.require_staged_hf_snapshot(
            tmp_path,
            repo_cache_name="models--example--model",
            revision="revision-123",
            required_files=("config.json", "model.safetensors"),
        )
    except ValueError as exc:
        assert "unexpected staged Hugging Face revision" in str(exc)
    else:
        raise AssertionError("revision mismatch should fail before inference")
