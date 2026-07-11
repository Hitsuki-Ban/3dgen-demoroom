from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from runner_utils import (
    LicenseSource,
    RuntimeSnapshot,
    TaskDefinition,
    collect_runtime_snapshot,
    load_tasks,
    parse_max_runtime_seconds,
    require_infer_arg,
    require_int,
    required_env,
    run_with_peak_vram,
    should_retry_task_error,
    upload_task_increment_if_configured,
    upload_task_increment_then_raise_timeout,
    utc_now,
    write_license_bundle,
    write_task_failure,
)


MODEL_ID = "hunyuan3d-21"
MODEL_GIT_COMMIT = "82920d643c0dc2f7bfd7255f45f62d386edfe60c"
WEIGHTS_REVISION = "0b94677654c57bb9a6b6845cd7b704ccf551d327"
DINOV2_REVISION = "611a9d42f2335e0f921f1e313ad3c1b7178d206d"
REALESRGAN_SHA256 = "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1"
HUNYUAN3D_ROOT = Path("/opt/Hunyuan3D-2.1")
MAX_TASK_ATTEMPTS = 1


HUNYUAN3D_21_WEIGHTS_PATH = required_env("HUNYUAN3D_21_WEIGHTS_PATH")

EXTERNAL_WEIGHT_REVISIONS = {
    "facebook/dinov2-giant": DINOV2_REVISION,
    "RealESRGAN_x4plus.pth": f"sha256:{REALESRGAN_SHA256}",
}

DEFAULT_PARAMETERS = {
    "shape_subfolder": "hunyuan3d-dit-v2-1",
    "texture_subfolder": "hunyuan3d-paintpbr-v2-1",
    "num_inference_steps": 50,
    "guidance_scale": 5.0,
    "octree_resolution": 384,
    "num_chunks": 8000,
    "texture": True,
    "texture_max_num_view": 6,
    "texture_resolution": 512,
    "texture_render_size": 2048,
    "texture_size": 4096,
    "attention_backend": "xformers",
    "hunyuan3d_21_weights_path": HUNYUAN3D_21_WEIGHTS_PATH,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="hunyuan3d-21-runner")
    parser.add_argument("--input-root", type=Path, default=Path("/work/input"))
    parser.add_argument("--output-root", type=Path, default=Path("/work/output"))
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--infer-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-output-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-num-inference-steps", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-guidance-scale", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--infer-octree-resolution", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-texture-resolution", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-hunyuan3d-21-weights-path", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.infer_image is not None:
        run_hunyuan3d_21_infer(args)
        return

    max_runtime_seconds = parse_max_runtime_seconds(os.environ)
    started_at = time.monotonic()
    tasks = load_tasks(args.input_root / "tasks.json")
    if args.task_limit is not None:
        if args.task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        tasks = tasks[: args.task_limit]

    license_sources = [
        LicenseSource("Hunyuan3D-2.1 LICENSE", HUNYUAN3D_ROOT / "LICENSE"),
        LicenseSource("Hunyuan3D-2.1 model card and license metadata", Path(HUNYUAN3D_21_WEIGHTS_PATH) / "README.md"),
    ]

    for task in tasks:
        remaining = max_runtime_seconds - (time.monotonic() - started_at)
        if remaining <= 0:
            raise TimeoutError("MAX_RUNTIME_MIN exceeded before starting next task")
        run_task(task, args.input_root, args.output_root, license_sources, remaining)


def run_task(
    task: TaskDefinition,
    input_root: Path,
    output_root: Path,
    license_sources: list[LicenseSource],
    timeout_seconds: float,
) -> None:
    image_path = input_root / task.image
    if not image_path.is_file():
        raise FileNotFoundError(f"missing input image for {task.id}: {image_path}")

    task_output_dir = output_root / task.id
    if task_output_dir.exists():
        raise FileExistsError(f"task output already exists: {task_output_dir}")

    work_dir = output_root / "_work" / MODEL_ID / task.id
    first_started_iso = utc_now()
    for attempt_index in range(MAX_TASK_ATTEMPTS):
        if work_dir.exists():
            shutil.rmtree(work_dir)
        if task_output_dir.exists():
            shutil.rmtree(task_output_dir)
        work_dir.mkdir(parents=True, exist_ok=False)
        raw_output_dir = work_dir / "raw"
        raw_output_dir.mkdir(parents=True, exist_ok=False)

        started_iso = utc_now()
        started_monotonic = time.monotonic()
        command = build_hunyuan3d_21_command(image_path, raw_output_dir, task.seed, DEFAULT_PARAMETERS)
        try:
            peak_vram_bytes = run_with_peak_vram(
                command,
                timeout_seconds,
                "Hunyuan3D-2.1",
                log_path=raw_output_dir / "infer.log",
            )
            wall_clock_seconds = time.monotonic() - started_monotonic
            finished_iso = utc_now()
            runtime = collect_runtime_snapshot(peak_vram_bytes, DEFAULT_PARAMETERS["attention_backend"])
            prepare_task_output(
                task=task,
                task_output_dir=task_output_dir,
                raw_output_dir=raw_output_dir,
                license_sources=license_sources,
                runtime=runtime,
                wall_clock_seconds=wall_clock_seconds,
                retry_count=attempt_index,
                started_at=started_iso,
                finished_at=finished_iso,
            )
            shutil.rmtree(work_dir)
        except Exception as exc:
            if work_dir.exists():
                shutil.rmtree(work_dir)
            if task_output_dir.exists():
                shutil.rmtree(task_output_dir)
            if should_retry_task_error(exc, attempt_index, MAX_TASK_ATTEMPTS):
                continue
            write_task_failure(
                task=task,
                task_output_dir=task_output_dir,
                model_id=MODEL_ID,
                model_git_commit=MODEL_GIT_COMMIT,
                weights_revision=WEIGHTS_REVISION,
                parameters=DEFAULT_PARAMETERS,
                error=exc,
                retry_count=attempt_index,
                started_at=first_started_iso,
                finished_at=utc_now(),
            )
            if isinstance(exc, TimeoutError):
                upload_task_increment_then_raise_timeout(
                    task_output_dir,
                    task.id,
                    os.environ,
                    exc,
                    upload=upload_task_increment_if_configured,
                )
            upload_task_increment_if_configured(task_output_dir, task.id, os.environ)
            return
        else:
            upload_task_increment_if_configured(task_output_dir, task.id, os.environ)
            return


def build_hunyuan3d_21_command(
    image_path: Path,
    raw_output_dir: Path,
    seed: int,
    parameters: dict[str, Any],
) -> list[str]:
    return [
        "python3",
        "/opt/3dgen-runner/hunyuan3d_21_runner.py",
        "--infer-image",
        image_path.as_posix(),
        "--infer-output-dir",
        raw_output_dir.as_posix(),
        "--infer-seed",
        str(seed),
        "--infer-num-inference-steps",
        str(parameters["num_inference_steps"]),
        "--infer-guidance-scale",
        str(parameters["guidance_scale"]),
        "--infer-octree-resolution",
        str(parameters["octree_resolution"]),
        "--infer-texture-resolution",
        str(parameters["texture_resolution"]),
        "--infer-hunyuan3d-21-weights-path",
        str(parameters["hunyuan3d_21_weights_path"]),
    ]


def run_hunyuan3d_21_infer(args: argparse.Namespace) -> None:
    require_infer_arg(args.infer_output_dir, "--infer-output-dir")
    require_infer_arg(args.infer_seed, "--infer-seed")
    require_infer_arg(args.infer_num_inference_steps, "--infer-num-inference-steps")
    require_infer_arg(args.infer_guidance_scale, "--infer-guidance-scale")
    require_infer_arg(args.infer_octree_resolution, "--infer-octree-resolution")
    require_infer_arg(args.infer_texture_resolution, "--infer-texture-resolution")
    require_infer_arg(args.infer_hunyuan3d_21_weights_path, "--infer-hunyuan3d-21-weights-path")
    if not args.infer_image.is_file():
        raise FileNotFoundError(f"missing input image: {args.infer_image}")

    num_inference_steps = require_int(args.infer_num_inference_steps, "--infer-num-inference-steps")
    guidance_scale = float(args.infer_guidance_scale)
    octree_resolution = require_int(args.infer_octree_resolution, "--infer-octree-resolution")
    texture_resolution = require_int(args.infer_texture_resolution, "--infer-texture-resolution")
    if num_inference_steps != DEFAULT_PARAMETERS["num_inference_steps"]:
        raise ValueError("--infer-num-inference-steps must be 50 for the wave 2 Hunyuan3D-2.1 protocol")
    if guidance_scale != DEFAULT_PARAMETERS["guidance_scale"]:
        raise ValueError("--infer-guidance-scale must be 5.0 for the wave 2 Hunyuan3D-2.1 protocol")
    if octree_resolution != DEFAULT_PARAMETERS["octree_resolution"]:
        raise ValueError("--infer-octree-resolution must be 384 for the wave 2 Hunyuan3D-2.1 protocol")
    if texture_resolution != DEFAULT_PARAMETERS["texture_resolution"]:
        raise ValueError("--infer-texture-resolution must be 512 for the wave 2 Hunyuan3D-2.1 protocol")

    weights_path = args.infer_hunyuan3d_21_weights_path
    required_paths = [
        weights_path / DEFAULT_PARAMETERS["shape_subfolder"],
        weights_path / DEFAULT_PARAMETERS["texture_subfolder"],
        weights_path / "RealESRGAN_x4plus.pth",
    ]
    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(f"missing Hunyuan3D-2.1 staged asset: {path}")
    require_file_sha256(weights_path / "RealESRGAN_x4plus.pth", REALESRGAN_SHA256)
    require_staged_hf_snapshot(
        Path(required_env("HF_HOME")),
        repo_cache_name="models--facebook--dinov2-giant",
        revision=DINOV2_REVISION,
        required_files=("config.json", "model.safetensors", "preprocessor_config.json"),
    )

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_MODULES_CACHE"] = str(args.infer_output_dir / "hf-modules")
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    os.environ["ATTN_BACKEND"] = DEFAULT_PARAMETERS["attention_backend"]
    sys.path.insert(0, str(HUNYUAN3D_ROOT))
    sys.path.insert(0, str(HUNYUAN3D_ROOT / "hy3dshape"))
    sys.path.insert(0, str(HUNYUAN3D_ROOT / "hy3dpaint"))

    install_local_snapshot_download(weights_path)
    prepare_local_diffusers_module(weights_path)

    import torch
    from PIL import Image
    from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
    from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline

    args.infer_output_dir.mkdir(parents=True, exist_ok=True)
    geometry_glb = args.infer_output_dir / "geometry.glb"
    geometry_obj = args.infer_output_dir / "geometry.obj"
    textured_obj = args.infer_output_dir / "textured_mesh.obj"
    textured_glb = args.infer_output_dir / "textured_mesh.glb"
    output_glb = args.infer_output_dir / "output.glb"

    image = Image.open(args.infer_image).convert("RGBA")
    shape_pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        str(weights_path),
        subfolder=DEFAULT_PARAMETERS["shape_subfolder"],
        use_safetensors=False,
        device="cuda",
    )
    generator = torch.Generator(device="cuda").manual_seed(args.infer_seed)
    mesh = shape_pipeline(
        image=image,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        generator=generator,
        octree_resolution=octree_resolution,
        num_chunks=DEFAULT_PARAMETERS["num_chunks"],
        output_type="trimesh",
    )[0]
    mesh.export(geometry_glb)
    mesh.export(geometry_obj)
    del shape_pipeline
    torch.cuda.empty_cache()

    paint_config = Hunyuan3DPaintConfig(
        DEFAULT_PARAMETERS["texture_max_num_view"],
        texture_resolution,
    )
    paint_config.multiview_pretrained_path = str(weights_path)
    paint_config.realesrgan_ckpt_path = str(weights_path / "RealESRGAN_x4plus.pth")
    paint_config.multiview_cfg_path = str(HUNYUAN3D_ROOT / "hy3dpaint" / "cfgs" / "hunyuan-paint-pbr.yaml")
    paint_config.custom_pipeline = str(HUNYUAN3D_ROOT / "hy3dpaint" / "hunyuanpaintpbr")
    paint_pipeline = Hunyuan3DPaintPipeline(paint_config)
    paint_pipeline(
        mesh_path=str(geometry_glb),
        image_path=image,
        output_mesh_path=str(textured_obj),
        save_glb=True,
    )
    if not textured_glb.is_file():
        raise FileNotFoundError(f"Hunyuan3D-2.1 paint pipeline did not create expected GLB: {textured_glb}")
    shutil.copy2(textured_glb, output_glb)

    overrides = {
        "guidance_scale": guidance_scale,
        "hunyuan3d_21_weights_path": str(weights_path),
        "num_chunks": DEFAULT_PARAMETERS["num_chunks"],
        "num_inference_steps": num_inference_steps,
        "octree_resolution": octree_resolution,
        "seed": args.infer_seed,
        "shape_subfolder": DEFAULT_PARAMETERS["shape_subfolder"],
        "texture_resolution": texture_resolution,
        "texture_subfolder": DEFAULT_PARAMETERS["texture_subfolder"],
    }
    (args.infer_output_dir / "inference_overrides.json").write_text(
        json.dumps(overrides, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def install_local_snapshot_download(weights_path: Path) -> None:
    import huggingface_hub

    staged_root = str(weights_path)
    original_snapshot_download = huggingface_hub.snapshot_download

    def snapshot_download(repo_id: str, *args: Any, **kwargs: Any) -> str:
        if repo_id == staged_root:
            return staged_root
        return original_snapshot_download(repo_id, *args, **kwargs)

    huggingface_hub.snapshot_download = snapshot_download


def prepare_local_diffusers_module(weights_path: Path) -> None:
    component_root = weights_path / DEFAULT_PARAMETERS["texture_subfolder"] / "unet"
    for filename in ("attn_processor.py", "modules.py"):
        path = component_root / filename
        if not path.is_file():
            raise FileNotFoundError(f"missing staged Hunyuan Diffusers module: {path}")

    from diffusers.utils.dynamic_modules_utils import get_class_from_dynamic_module

    model_class = get_class_from_dynamic_module(
        str(component_root),
        module_file="modules.py",
        class_name="UNet2p5DConditionModel",
    )
    if model_class.__name__ != "UNet2p5DConditionModel":
        raise RuntimeError(f"unexpected staged Hunyuan Diffusers class: {model_class.__name__}")


def require_staged_hf_snapshot(
    hf_home: Path,
    *,
    repo_cache_name: str,
    revision: str,
    required_files: tuple[str, ...],
) -> Path:
    repo_cache = hf_home / "hub" / repo_cache_name
    main_ref = repo_cache / "refs" / "main"
    if not main_ref.is_file():
        raise FileNotFoundError(f"missing staged Hugging Face main ref: {main_ref}")
    actual_revision = main_ref.read_text(encoding="utf-8").strip()
    if actual_revision != revision:
        raise ValueError(f"unexpected staged Hugging Face revision for {repo_cache_name}: {actual_revision}")
    snapshot = repo_cache / "snapshots" / revision
    for required_file in required_files:
        path = snapshot / required_file
        if not path.is_file():
            raise FileNotFoundError(f"missing staged Hugging Face file: {path}")
    return snapshot


def require_file_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError(f"unexpected SHA-256 for {path}: {actual}")


def prepare_task_output(
    *,
    task: TaskDefinition,
    task_output_dir: Path,
    raw_output_dir: Path,
    license_sources: list[LicenseSource],
    runtime: RuntimeSnapshot,
    wall_clock_seconds: float,
    retry_count: int,
    started_at: str,
    finished_at: str,
) -> None:
    if task_output_dir.exists():
        raise FileExistsError(f"task output already exists: {task_output_dir}")
    mesh_path = raw_output_dir / "output.glb"
    geometry_path = raw_output_dir / "geometry.glb"
    if not mesh_path.is_file():
        raise FileNotFoundError(f"Hunyuan3D-2.1 did not create expected textured GLB: {mesh_path}")
    if not geometry_path.is_file():
        raise FileNotFoundError(f"Hunyuan3D-2.1 did not create expected raw geometry GLB: {geometry_path}")

    task_output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(mesh_path, task_output_dir / "output.glb")
    shutil.copytree(raw_output_dir, task_output_dir / "raw" / MODEL_ID)
    write_license_bundle(task_output_dir / "LICENSES.txt", license_sources)
    meta = {
        "task_id": task.id,
        "model_id": MODEL_ID,
        "model_git_commit": MODEL_GIT_COMMIT,
        "weights_revision": WEIGHTS_REVISION,
        "gpu_name": runtime.gpu_name,
        "wall_clock_seconds": wall_clock_seconds,
        "peak_vram_bytes": runtime.peak_vram_bytes,
        "seed": task.seed,
        "parameters": DEFAULT_PARAMETERS,
        "retry_count": retry_count,
        "torch_version": runtime.torch_version,
        "torch_cuda_version": runtime.torch_cuda_version,
        "torch_cuda_arch_list": runtime.torch_cuda_arch_list,
        "attention_backend": runtime.attention_backend,
        "started_at": started_at,
        "finished_at": finished_at,
        "license_file": "LICENSES.txt",
        "external_weight_revisions": EXTERNAL_WEIGHT_REVISIONS,
    }
    (task_output_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"hunyuan3d-21-runner failed: {exc}", file=sys.stderr)
        raise
