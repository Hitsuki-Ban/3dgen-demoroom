from __future__ import annotations

import argparse
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
    required_env,
    run_with_peak_vram,
    should_retry_task_error,
    upload_task_increment_if_configured,
    upload_task_increment_then_raise_timeout,
    utc_now,
    write_license_bundle,
    write_task_failure,
)


MODEL_ID = "step1x-3d"
MODEL_GIT_COMMIT = "cb5ac944709c6c913109070c7b90c3447f57f3d4"
WEIGHTS_REVISION = "bf7084495b3a72222f36549b7942948aa4d9daa7"
DINOV2_REVISION = "e4c89a4e05589de9b3e188688a303d0f3c04d0f3"
SDXL_REVISION = "462165984030d82259a11f4367a4eed129e94a7b"
SDXL_VAE_REVISION = "207b116dae70ace3637169f1ddd2434b91b3a8cd"
BIREFNET_REVISION = "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4"
STEP1X_3D_ROOT = Path("/opt/Step1X-3D")
MAX_TASK_ATTEMPTS = 1


STEP1X_3D_WEIGHTS_PATH = required_env("STEP1X_3D_WEIGHTS_PATH")

EXTERNAL_WEIGHT_REVISIONS = {
    "facebook/dinov2-with-registers-large": DINOV2_REVISION,
    "stabilityai/stable-diffusion-xl-base-1.0": SDXL_REVISION,
    "madebyollin/sdxl-vae-fp16-fix": SDXL_VAE_REVISION,
    "ZhengPeng7/BiRefNet": BIREFNET_REVISION,
}

DEFAULT_PARAMETERS = {
    "geometry_subfolder": "Step1X-3D-Geometry-1300m",
    "texture_subfolder": "Step1X-3D-Texture",
    "num_inference_steps": 50,
    "guidance_scale": 7.5,
    "octree_resolution": 384,
    "max_facenum": 200000,
    "texture": True,
    "texture_seed_source": "benchmark_task_seed",
    "step1x_3d_weights_path": STEP1X_3D_WEIGHTS_PATH,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="step1x-3d-runner")
    parser.add_argument("--input-root", type=Path, default=Path("/work/input"))
    parser.add_argument("--output-root", type=Path, default=Path("/work/output"))
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--infer-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-output-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-geometry-subfolder", type=str, help=argparse.SUPPRESS)
    parser.add_argument("--infer-texture-subfolder", type=str, help=argparse.SUPPRESS)
    parser.add_argument("--infer-step1x-3d-weights-path", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.infer_image is not None:
        run_step1x_3d_infer(args)
        return

    max_runtime_seconds = parse_max_runtime_seconds(os.environ)
    started_at = time.monotonic()
    tasks = load_tasks(args.input_root / "tasks.json")
    if args.task_limit is not None:
        if args.task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        tasks = tasks[: args.task_limit]

    license_sources = [
        LicenseSource("Step1X-3D LICENSE", STEP1X_3D_ROOT / "LICENSE"),
        LicenseSource("Step1X-3D model card and license metadata", Path(STEP1X_3D_WEIGHTS_PATH) / "README.md"),
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
        command = build_step1x_3d_command(image_path, raw_output_dir, task.seed, DEFAULT_PARAMETERS)
        try:
            peak_vram_bytes = run_with_peak_vram(
                command,
                timeout_seconds,
                "Step1X-3D",
                log_path=raw_output_dir / "infer.log",
            )
            wall_clock_seconds = time.monotonic() - started_monotonic
            finished_iso = utc_now()
            runtime = collect_runtime_snapshot(peak_vram_bytes, "official")
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


def build_step1x_3d_command(
    image_path: Path,
    raw_output_dir: Path,
    seed: int,
    parameters: dict[str, Any],
) -> list[str]:
    return [
        "python3",
        "/opt/3dgen-runner/step1x_3d_runner.py",
        "--infer-image",
        image_path.as_posix(),
        "--infer-output-dir",
        raw_output_dir.as_posix(),
        "--infer-seed",
        str(seed),
        "--infer-geometry-subfolder",
        str(parameters["geometry_subfolder"]),
        "--infer-texture-subfolder",
        str(parameters["texture_subfolder"]),
        "--infer-step1x-3d-weights-path",
        str(parameters["step1x_3d_weights_path"]),
    ]


def run_step1x_3d_infer(args: argparse.Namespace) -> None:
    require_infer_arg(args.infer_output_dir, "--infer-output-dir")
    require_infer_arg(args.infer_seed, "--infer-seed")
    require_infer_arg(args.infer_geometry_subfolder, "--infer-geometry-subfolder")
    require_infer_arg(args.infer_texture_subfolder, "--infer-texture-subfolder")
    require_infer_arg(args.infer_step1x_3d_weights_path, "--infer-step1x-3d-weights-path")
    if not args.infer_image.is_file():
        raise FileNotFoundError(f"missing input image: {args.infer_image}")
    if args.infer_geometry_subfolder != DEFAULT_PARAMETERS["geometry_subfolder"]:
        raise ValueError("--infer-geometry-subfolder must be Step1X-3D-Geometry-1300m for the wave 2 protocol")
    if args.infer_texture_subfolder != DEFAULT_PARAMETERS["texture_subfolder"]:
        raise ValueError("--infer-texture-subfolder must be Step1X-3D-Texture for the wave 2 protocol")

    weights_path = args.infer_step1x_3d_weights_path
    geometry_dir = weights_path / args.infer_geometry_subfolder
    texture_dir = weights_path / args.infer_texture_subfolder
    for path in (geometry_dir / "model_index.json", texture_dir / "step1x-3d-ig2v.safetensors"):
        if not path.is_file():
            raise FileNotFoundError(f"missing Step1X-3D weight file: {path}")

    hf_home = Path(required_env("HF_HOME"))
    require_staged_hf_snapshot(
        hf_home,
        repo_cache_name="models--facebook--dinov2-with-registers-large",
        revision=DINOV2_REVISION,
        required_files=("config.json", "model.safetensors", "preprocessor_config.json"),
    )
    require_staged_hf_snapshot(
        hf_home,
        repo_cache_name="models--stabilityai--stable-diffusion-xl-base-1.0",
        revision=SDXL_REVISION,
        required_files=(
            "model_index.json",
            "scheduler/scheduler_config.json",
            "text_encoder/config.json",
            "text_encoder/model.safetensors",
            "text_encoder_2/config.json",
            "text_encoder_2/model.safetensors",
            "tokenizer/merges.txt",
            "tokenizer/tokenizer_config.json",
            "tokenizer/vocab.json",
            "tokenizer_2/merges.txt",
            "tokenizer_2/tokenizer_config.json",
            "tokenizer_2/vocab.json",
            "unet/config.json",
            "unet/diffusion_pytorch_model.safetensors",
        ),
    )
    require_staged_hf_snapshot(
        hf_home,
        repo_cache_name="models--madebyollin--sdxl-vae-fp16-fix",
        revision=SDXL_VAE_REVISION,
        required_files=("config.json", "diffusion_pytorch_model.safetensors"),
    )
    require_staged_hf_snapshot(
        hf_home,
        repo_cache_name="models--ZhengPeng7--BiRefNet",
        revision=BIREFNET_REVISION,
        required_files=("BiRefNet_config.py", "birefnet.py", "config.json", "model.safetensors"),
    )

    sys.path.insert(0, str(STEP1X_3D_ROOT))

    import torch
    import trimesh
    from step1x3d_geometry.models.pipelines.pipeline import Step1X3DGeometryPipeline
    from step1x3d_geometry.models.pipelines.pipeline_utils import reduce_face, remove_degenerate_face
    from step1x3d_texture.pipelines.step1x_3d_texture_synthesis_pipeline import Step1X3DTexturePipeline

    args.infer_output_dir.mkdir(parents=True, exist_ok=True)
    geometry_path = args.infer_output_dir / "geometry.glb"
    output_path = args.infer_output_dir / "output.glb"

    geometry_pipeline = Step1X3DGeometryPipeline.from_pretrained(
        str(weights_path),
        subfolder=args.infer_geometry_subfolder,
    ).to("cuda")
    generator = torch.Generator(device=geometry_pipeline.device)
    generator.manual_seed(args.infer_seed)
    geometry_output = geometry_pipeline(
        str(args.infer_image),
        guidance_scale=DEFAULT_PARAMETERS["guidance_scale"],
        num_inference_steps=DEFAULT_PARAMETERS["num_inference_steps"],
        octree_resolution=DEFAULT_PARAMETERS["octree_resolution"],
        max_facenum=DEFAULT_PARAMETERS["max_facenum"],
        generator=generator,
    )
    geometry_output.mesh[0].export(geometry_path)
    geometry_pipeline.to("cpu")
    del geometry_pipeline
    torch.cuda.empty_cache()

    mesh = trimesh.load(geometry_path)
    texture_pipeline = Step1X3DTexturePipeline.from_pretrained(
        str(weights_path),
        subfolder=args.infer_texture_subfolder,
    )
    mesh = remove_degenerate_face(mesh)
    mesh = reduce_face(mesh)
    textured_mesh = texture_pipeline(str(args.infer_image), mesh, seed=args.infer_seed)
    textured_mesh.export(output_path)

    overrides = {
        "geometry_subfolder": args.infer_geometry_subfolder,
        "guidance_scale": DEFAULT_PARAMETERS["guidance_scale"],
        "max_facenum": DEFAULT_PARAMETERS["max_facenum"],
        "num_inference_steps": DEFAULT_PARAMETERS["num_inference_steps"],
        "octree_resolution": DEFAULT_PARAMETERS["octree_resolution"],
        "seed": args.infer_seed,
        "step1x_3d_weights_path": str(weights_path),
        "texture_subfolder": args.infer_texture_subfolder,
    }
    (args.infer_output_dir / "inference_overrides.json").write_text(
        json.dumps(overrides, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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
        raise FileNotFoundError(f"Step1X-3D did not create expected textured GLB: {mesh_path}")
    if not geometry_path.is_file():
        raise FileNotFoundError(f"Step1X-3D did not create expected raw geometry GLB: {geometry_path}")

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
        print(f"step1x-3d-runner failed: {exc}", file=sys.stderr)
        raise
