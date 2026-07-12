import importlib.util
import json
import sys
from pathlib import Path

from bench_harness.meta import REQUIRED_META_KEYS
from bench_harness.tasks import TaskDefinition


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "models" / "3dtopia-xl" / "runner.py"
COMMON_PATH = REPO_ROOT / "models" / "common"
MODEL_SPEC_PATH = REPO_ROOT / "models" / "3dtopia-xl" / "model.json"
DOCKERFILE_PATH = REPO_ROOT / "models" / "3dtopia-xl" / "Dockerfile"
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
    monkeypatch.setenv("TOPIA_XL_WEIGHTS_PATH", "/workspace/weights/3DTopia-XL")
    sys.path.insert(0, str(COMMON_PATH))
    spec = importlib.util.spec_from_file_location("topia_xl_runner", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["topia_xl_runner"] = module
    spec.loader.exec_module(module)
    return module


def test_3dtopia_xl_model_spec_records_current_pins() -> None:
    spec = json.loads(MODEL_SPEC_PATH.read_text(encoding="utf-8"))

    assert spec["id"] == "3dtopia-xl"
    assert spec["code_repo"] == "https://github.com/3DTopia/3DTopia-XL"
    assert spec["code_commit"] == "4017e5bfbaab7f73632b47311a92a434abb9d2fc"
    assert spec["weights_repo"] == "FrozenBurning/3DTopia-XL"
    assert spec["weights_revision"] == "8a348b850d36d6354a26917d531eb8f2a5633515"
    assert spec["default_parameters"]["ddim"] == 25
    assert spec["default_parameters"]["cfg"] == 6
    assert spec["default_parameters"]["precision"] == "fp16"
    assert spec["default_parameters"]["checkpoint_path"] == (
        "/workspace/weights/3DTopia-XL/model_sview_dit_fp16.pt"
    )
    assert spec["default_parameters"]["vae_checkpoint_path"] == "/workspace/weights/3DTopia-XL/model_vae_fp16.pt"


def test_3dtopia_xl_dockerfile_uses_runtime_only_volume_paths() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04" in dockerfile
    assert "ARG TOPIA_XL_COMMIT=4017e5bfbaab7f73632b47311a92a434abb9d2fc" in dockerfile
    assert "ARG TOPIA_XL_WEIGHTS_REVISION=8a348b850d36d6354a26917d531eb8f2a5633515" in dockerfile
    assert "ARG NVDIFFRAST_COMMIT=253ac4fcea7de5f396371124af597e6cc957bfae" in dockerfile
    assert "ARG CUBVH_COMMIT=757b913bfbf19ed65e3a379d159391a8e29efa0f" in dockerfile
    assert "ARG PYTORCH3D_COMMIT=33824be3cbc87a7dd1db0f6a9a9de9ac81b2d0ba" in dockerfile
    assert "ARG PYTHON_VERSION=3.9.23" in dockerfile
    assert "uv python install ${PYTHON_VERSION}" in dockerfile
    assert "uv venv --python ${PYTHON_VERSION} /opt/venv" in dockerfile
    assert 'uv pip install --python /opt/venv/bin/python "setuptools<81" wheel' in dockerfile
    assert "PATH=/opt/venv/bin:$PATH" in dockerfile
    assert "TOPIA_XL_WEIGHTS_PATH=/workspace/weights/3DTopia-XL" in dockerfile
    assert "TORCH_HOME=/workspace/torch" in dockerfile
    assert "U2NET_HOME=/workspace/weights/rembg" in dockerfile
    assert 'TORCH_CUDA_ARCH_LIST="8.9"' in dockerfile
    assert 'TORCH_CUDA_ARCH_LIST="8.9;12.0"' not in dockerfile
    assert "grep -R --include='setup.py' -q -- \"sm_70\" dva/mvp/extensions simple-knn" in dockerfile
    assert "sed -i 's/sm_70/sm_89/g'" in dockerfile
    assert 'grep -R --include=\'setup.py\' -q -- "sm_70" dva/mvp/extensions simple-knn; then exit 1' in dockerfile
    assert "snapshot_download(" not in dockerfile
    assert "RUN pip install" not in dockerfile
    assert "uv pip install --python /opt/venv/bin/python" in dockerfile
    assert "'rembg[cpu]'" in dockerfile
    assert "from torch.utils.cpp_extension import BuildExtension, CUDAExtension" in dockerfile
    assert "uv pip install --python /opt/venv/bin/python --no-build-isolation /tmp/extensions/nvdiffrast" in dockerfile
    assert "git clone https://github.com/facebookresearch/pytorch3d.git /tmp/extensions/pytorch3d" in dockerfile
    assert "MAX_JOBS=1 uv pip install --python /opt/venv/bin/python --no-build-isolation /tmp/extensions/pytorch3d" in dockerfile
    assert "git clone --recurse-submodules https://github.com/ashawkey/cubvh.git /tmp/extensions/cubvh" in dockerfile
    assert "git submodule update --init --recursive" in dockerfile
    assert "uv pip install --python /opt/venv/bin/python --no-build-isolation /tmp/extensions/cubvh" in dockerfile
    assert "uv pip install --python /opt/venv/bin/python --no-build-isolation /opt/3DTopia-XL/simple-knn" in dockerfile
    assert "torch==2.1.2" in dockerfile
    assert "xformers==0.0.23.post1" in dockerfile
    assert "numpy==1.26.4" in dockerfile
    assert "COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py" in dockerfile
    assert "COPY models/3dtopia-xl/runner.py /opt/3dgen-runner/3dtopia_xl_runner.py" in dockerfile
    assert (
        'ENTRYPOINT ["python", "-m", "bench_harness.container_entrypoint", "--model-id", '
        '"3dtopia-xl", "--runner-path", "/opt/3dgen-runner/3dtopia_xl_runner.py"]'
        in dockerfile
    )


def test_build_3dtopia_xl_command_uses_volume_pinned_weights(monkeypatch, tmp_path: Path) -> None:
    runner = _load_runner(monkeypatch)

    command = runner.build_3dtopia_xl_command(
        image_path=tmp_path / "input.png",
        raw_output_dir=tmp_path / "raw",
        seed=20260708,
        parameters=runner.DEFAULT_PARAMETERS,
    )

    assert command == [
        "python3",
        "/opt/3dgen-runner/3dtopia_xl_runner.py",
        "--infer-image",
        str(tmp_path / "input.png"),
        "--infer-output-dir",
        str(tmp_path / "raw"),
        "--infer-seed",
        "20260708",
        "--infer-topia-xl-weights-path",
        "/workspace/weights/3DTopia-XL",
    ]


def test_3dtopia_xl_runner_requires_explicit_weight_env(monkeypatch) -> None:
    monkeypatch.delenv("TOPIA_XL_WEIGHTS_PATH", raising=False)
    sys.path.insert(0, str(COMMON_PATH))
    spec = importlib.util.spec_from_file_location("topia_xl_runner_missing_env", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["topia_xl_runner_missing_env"] = module

    try:
        spec.loader.exec_module(module)
    except ValueError as exc:
        assert "TOPIA_XL_WEIGHTS_PATH" in str(exc)
    else:
        raise AssertionError("runner import should fail without explicit weight env")


def test_prepare_task_output_writes_3dtopia_xl_contract_files(monkeypatch, tmp_path: Path) -> None:
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
    (raw_output_dir / "inference_overrides.json").write_text("{}\n", encoding="utf-8")
    root_license = tmp_path / "LICENSE.txt"
    weights_readme = tmp_path / "README.md"
    root_license.write_text("Apache-2.0\n", encoding="utf-8")
    weights_readme.write_text("model card\n", encoding="utf-8")
    task_output_dir = tmp_path / "out"

    runner.prepare_task_output(
        task=task,
        task_output_dir=task_output_dir,
        raw_output_dir=raw_output_dir,
        license_sources=[
            runner.LicenseSource("3DTopia-XL LICENSE", root_license),
            runner.LicenseSource("3DTopia-XL model card and license metadata", weights_readme),
        ],
        runtime=runner.RuntimeSnapshot(
            vram=_vram_measurement("NVIDIA GeForce RTX 4090", 1234),
            torch_version="2.1.2+cu118",
            torch_cuda_version="11.8",
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
    assert meta["model_id"] == "3dtopia-xl"
    assert meta["vram_measurement"]["scope"] == "inference_process_group"
    assert meta["vram_measurement"]["gpu_uuid"] == "GPU-11111111-2222-3333-4444-555555555555"
    assert meta["model_git_commit"] == "4017e5bfbaab7f73632b47311a92a434abb9d2fc"
    assert meta["weights_revision"] == "8a348b850d36d6354a26917d531eb8f2a5633515"
    assert meta["parameters"] == runner.DEFAULT_PARAMETERS
    assert (task_output_dir / "output.glb").read_bytes() == b"glTF"
    assert (task_output_dir / "raw" / "3dtopia-xl" / "output.glb").read_bytes() == b"glTF"
    assert (task_output_dir / "raw" / "3dtopia-xl" / "inference_overrides.json").is_file()
    licenses = (task_output_dir / "LICENSES.txt").read_text(encoding="utf-8")
    assert "Apache-2.0" in licenses
    assert "model card" in licenses
