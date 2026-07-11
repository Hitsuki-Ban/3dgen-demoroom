from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_SPEC_PATH = REPO_ROOT / "models" / "pixal3d" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "pixal3d" / "Dockerfile"


def load_pixal3d_runner() -> ModuleType:
    sys.path.insert(0, str(REPO_ROOT / "models" / "common"))
    runner_path = REPO_ROOT / "models" / "pixal3d" / "runner.py"
    spec = importlib.util.spec_from_file_location("pixal3d_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runner from {runner_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_pixal3d_command_uses_standard_1536_without_low_vram(monkeypatch) -> None:
    monkeypatch.setenv("PIXAL3D_WEIGHTS_PATH", "/workspace/weights/Pixal3D")
    monkeypatch.setenv("HF_HOME", "/workspace/hf")
    monkeypatch.setenv("TORCH_HOME", "/workspace/torch")
    runner = load_pixal3d_runner()

    command = runner.build_pixal3d_command(
        Path("/work/input/references/cartoon-apple.png"),
        Path("/work/output/_work/pixal3d/cartoon-apple/raw"),
        20260708,
        runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/3dgen-runner/pixal3d_runner.py",
        "--infer-image",
        "/work/input/references/cartoon-apple.png",
        "--infer-output-dir",
        "/work/output/_work/pixal3d/cartoon-apple/raw",
        "--infer-seed",
        "20260708",
        "--infer-resolution",
        "1536",
        "--infer-pixal3d-weights-path",
        "/workspace/weights/Pixal3D",
    ]
    assert "--low_vram" not in command
    assert "--infer-low-vram" not in command


def test_prepare_pixal3d_task_output_writes_meta_with_standard_protocol(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIXAL3D_WEIGHTS_PATH", "/workspace/weights/Pixal3D")
    monkeypatch.setenv("HF_HOME", "/workspace/hf")
    monkeypatch.setenv("TORCH_HOME", "/workspace/torch")
    runner = load_pixal3d_runner()
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
        gpu_name="NVIDIA GeForce RTX 5090",
        peak_vram_bytes=28 * 1024**3,
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
            runner.LicenseSource("Pixal3D LICENSE", license_path),
            runner.LicenseSource("Pixal3D model card and license metadata", model_card_path),
        ],
        runtime=runtime,
        wall_clock_seconds=240.0,
        retry_count=0,
        started_at="2026-07-09T06:00:00Z",
        finished_at="2026-07-09T06:04:00Z",
    )

    meta = json.loads((tmp_path / "task-output" / "meta.json").read_text(encoding="utf-8"))
    assert meta["model_id"] == "pixal3d"
    assert meta["parameters"]["resolution"] == 1536
    assert meta["parameters"]["pipeline_type"] == "1536_cascade"
    assert meta["parameters"]["low_vram"] is False
    assert meta["external_weight_revisions"] == runner.EXTERNAL_WEIGHT_REVISIONS
    assert meta["external_code_revisions"] == runner.EXTERNAL_CODE_REVISIONS
    assert (tmp_path / "task-output" / "output.glb").read_bytes() == b"glb"
    assert (tmp_path / "task-output" / "raw" / "pixal3d" / "output.glb").read_bytes() == b"glb"


def test_run_task_records_explicit_protocol_retry_count(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIXAL3D_WEIGHTS_PATH", "/workspace/weights/Pixal3D")
    monkeypatch.setenv("HF_HOME", "/workspace/hf")
    monkeypatch.setenv("TORCH_HOME", "/workspace/torch")
    runner = load_pixal3d_runner()
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    image_path = input_root / "references" / "old-oak-tree.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"png")
    license_path = tmp_path / "LICENSE"
    license_path.write_text("license\n", encoding="utf-8")
    task = runner.TaskDefinition(
        id="old-oak-tree",
        prompt="old oak tree",
        image="references/old-oak-tree.png",
        seed=20260708,
    )
    runtime = runner.RuntimeSnapshot(
        gpu_name="NVIDIA RTX PRO 6000 Blackwell Workstation Edition",
        peak_vram_bytes=64 * 1024**3,
        torch_version="2.7.1+cu128",
        torch_cuda_version="12.8",
        torch_cuda_arch_list=["sm_120"],
        attention_backend="flash_attn",
    )

    def fake_run_with_peak_vram(command, timeout_seconds, label, *, log_path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        (log_path.parent / "output.glb").write_bytes(b"glb")
        return runtime.peak_vram_bytes

    monkeypatch.setattr(runner, "run_with_peak_vram", fake_run_with_peak_vram)
    monkeypatch.setattr(runner, "collect_runtime_snapshot", lambda *_: runtime)
    monkeypatch.setattr(runner, "upload_task_increment_if_configured", lambda *_: None)

    runner.run_task(
        task,
        input_root,
        output_root,
        [runner.LicenseSource("license", license_path)],
        timeout_seconds=60,
        retry_count=1,
    )

    meta = json.loads((output_root / task.id / "meta.json").read_text(encoding="utf-8"))
    assert meta["retry_count"] == 1
    assert meta["seed"] == 20260708
    assert meta["parameters"]["resolution"] == 1536
    assert meta["parameters"]["low_vram"] is False


def test_pixal3d_model_spec_records_current_pins_and_standard_protocol() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["id"] == "pixal3d"
    assert spec["code_repo"] == "https://github.com/TencentARC/Pixal3D"
    assert spec["code_commit"] == "cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af"
    assert spec["weights_repo"] == "TencentARC/Pixal3D"
    assert spec["weights_revision"] == "0b31f9160aa400719af409098bff7936a932f726"
    assert spec["default_parameters"]["resolution"] == 1536
    assert spec["default_parameters"]["pipeline_type"] == "1536_cascade"
    assert spec["default_parameters"]["low_vram"] is False
    assert "camenduru/dinov3-vitl16-pretrain-lvd1689m" in spec["external_weight_dependencies"]
    assert "Ruicheng/moge-2-vitl" in spec["external_weight_dependencies"]
    assert "briaai/RMBG-2.0" in spec["external_weight_dependencies"]
    assert "valeoai/NAF" in spec["external_weight_dependencies"]
    assert spec["external_weight_revisions"] == {
        "camenduru/dinov3-vitl16-pretrain-lvd1689m": "3c276edd87d6f6e569ff0c4400e086807d0f3881",
        "Ruicheng/moge-2-vitl": "39c4d5e957afe587e04eec59dc2bcc3be5ecd968",
        "briaai/RMBG-2.0": "5df4c9c76d8170882c34f6986e848ee07fd0ba43",
        "valeoai/NAF": "37f2dfc180f2de53d98bd601109c0da0dd6b0f43",
    }
    assert spec["external_code_revisions"] == {
        "microsoft/MoGe": "07444410f1e33f402353b99d6ccd26bd31e469e8"
    }
    assert "ZhengPeng7/BiRefNet" not in spec["external_weight_dependencies"]
    assert "black-forest-labs/FLUX.1-dev" not in spec["external_weight_dependencies"]


def test_pixal3d_dockerfile_uses_runtime_only_volume_paths() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "3dgen-natten-wheel@sha256:bcbadc4205c6c80282d8360a3eeb4eeeae0f9d6c4b5f17f91cccff7281bdafb4 AS natten-wheel" in dockerfile
    assert "3dgen-trellis2-runtime@sha256:680f4189db4fa6d02c6cda75512fe98faacd9c9dabaa2e08a0afe3aea0b110ed" in dockerfile
    assert "ARG PIXAL3D_COMMIT=cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af" in dockerfile
    assert "ARG PIXAL3D_WEIGHTS_REVISION=0b31f9160aa400719af409098bff7936a932f726" in dockerfile
    assert "ARG MOGE_COMMIT=07444410f1e33f402353b99d6ccd26bd31e469e8" in dockerfile
    assert "PIXAL3D_WEIGHTS_PATH=/workspace/weights/Pixal3D" in dockerfile
    assert "HF_HOME=/workspace/hf" in dockerfile
    assert "TORCH_HOME=/workspace/torch" in dockerfile
    assert 'TORCH_CUDA_ARCH_LIST="8.9;12.0"' in dockerfile
    assert "snapshot_download(" not in dockerfile
    assert "HF_TOKEN" not in dockerfile
    assert "RUN pip install" not in dockerfile
    assert "uv pip install --system" in dockerfile
    assert "ARG NATTEN_WHEEL_SHA256=a0bccfb8da194fc909eddaf77573b6a12303839a4bc70964240a7b10546631c0" in dockerfile
    assert "COPY --from=natten-wheel /natten-0.21.0-cp310-cp310-linux_x86_64.whl" in dockerfile
    assert "uv pip install --system /tmp/natten-0.21.0-cp310-cp310-linux_x86_64.whl" in dockerfile
    assert "NATTEN_N_WORKERS" not in dockerfile
    assert "uv pip uninstall --system opencv-python" in dockerfile
    assert "uv pip install --system --reinstall opencv-python-headless==4.12.0.88" in dockerfile
    assert 'assert cv2.__version__ == "4.12.0"' in dockerfile
    assert 'assert version("natten") == "0.21.0"' in dockerfile
    assert "flash-attn==" not in dockerfile
    assert "git+https://github.com/microsoft/MoGe.git@${MOGE_COMMIT}" in dockerfile
    assert "utils3d-0.0.2-py3-none-any.whl" in dockerfile
    assert "COPY models/pixal3d/runner.py /opt/3dgen-runner/pixal3d_runner.py" in dockerfile


def test_validate_staged_pixal3d_dependencies_requires_pinned_refs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIXAL3D_WEIGHTS_PATH", "/workspace/weights/Pixal3D")
    monkeypatch.setenv("HF_HOME", "/workspace/hf")
    monkeypatch.setenv("TORCH_HOME", "/workspace/torch")
    runner = load_pixal3d_runner()
    weights = tmp_path / "weights"
    hf_home = tmp_path / "hf"
    torch_home = tmp_path / "torch"

    for relative in runner.REQUIRED_WEIGHT_FILES:
        path = weights / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    cache_requirements = {
        "camenduru/dinov3-vitl16-pretrain-lvd1689m": (
            runner.DINO_V3_REVISION,
            ("README.md", "config.json", "model.safetensors"),
        ),
        "Ruicheng/moge-2-vitl": (runner.MOGE_WEIGHTS_REVISION, ("README.md", "model.pt")),
        "briaai/RMBG-2.0": (
            runner.RMBG_REVISION,
            ("README.md", "BiRefNet_config.py", "birefnet.py", "config.json", "model.safetensors"),
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

    naf_checkpoint_bytes = b"fixture checkpoint"
    monkeypatch.setattr(runner, "NAF_CHECKPOINT_SHA256", hashlib.sha256(naf_checkpoint_bytes).hexdigest())
    naf_files = {
        "hub/valeoai_NAF_main/hubconf.py": b"fixture",
        "hub/valeoai_NAF_main/LICENSE": b"fixture",
        "hub/valeoai_NAF_main/src/model/naf.py": b"fixture",
        "hub/valeoai_NAF_main/src/layers/attentions.py": b"fixture",
        "hub/valeoai_NAF_main/.git-revision": runner.NAF_REVISION.encode(),
        "hub/checkpoints/naf_release.pth": naf_checkpoint_bytes,
    }
    for relative, contents in naf_files.items():
        path = torch_home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    runner.validate_staged_dependencies(weights, hf_home, torch_home)
    dino_ref = hf_home / "hub" / "models--camenduru--dinov3-vitl16-pretrain-lvd1689m" / "refs" / "main"
    dino_ref.write_text("wrong", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="missing pinned HF main ref"):
        runner.validate_staged_dependencies(weights, hf_home, torch_home)

    dino_ref.write_text(runner.DINO_V3_REVISION, encoding="utf-8")
    (torch_home / "hub" / "checkpoints" / "naf_release.pth").write_bytes(b"wrong")
    with pytest.raises(ValueError, match="NAF checkpoint SHA-256 mismatch"):
        runner.validate_staged_dependencies(weights, hf_home, torch_home)
