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
    require_int,
    required_env,
    run_with_peak_vram,
    terminate_runpod_if_needed,
    upload_task_increment_if_configured,
    utc_now,
    write_license_bundle,
    write_task_failure,
)


MODEL_ID = "pixal3d"
MODEL_GIT_COMMIT = "cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af"
WEIGHTS_REVISION = "0b31f9160aa400719af409098bff7936a932f726"
PIXAL3D_ROOT = Path("/opt/Pixal3D")
MAX_TASK_ATTEMPTS = 1


PIXAL3D_WEIGHTS_PATH = required_env("PIXAL3D_WEIGHTS_PATH")

DEFAULT_PARAMETERS = {
    "resolution": 1536,
    "pipeline_type": "1536_cascade",
    "low_vram": False,
    "manual_fov": -1.0,
    "image_resolution": 512,
    "max_num_tokens": 49152,
    "sparse_structure_sampler_params": {
        "steps": 12,
        "guidance_strength": 7.5,
        "guidance_rescale": 0.7,
        "rescale_t": 5.0,
    },
    "shape_slat_sampler_params": {
        "steps": 12,
        "guidance_strength": 7.5,
        "guidance_rescale": 0.5,
        "rescale_t": 3.0,
    },
    "tex_slat_sampler_params": {
        "steps": 12,
        "guidance_strength": 1.0,
        "guidance_rescale": 0.0,
        "rescale_t": 3.0,
    },
    "decimation_target": 1000000,
    "texture_size": 4096,
    "remesh": True,
    "remesh_band": 1,
    "remesh_project": 0,
    "export_webp": True,
    "attention_backend": "flash_attn",
    "pixal3d_weights_path": PIXAL3D_WEIGHTS_PATH,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="pixal3d-runner")
    parser.add_argument("--input-root", type=Path, default=Path("/work/input"))
    parser.add_argument("--output-root", type=Path, default=Path("/work/output"))
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--infer-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-output-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-resolution", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-pixal3d-weights-path", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.infer_image is not None:
        run_pixal3d_infer(args)
        return

    max_runtime_seconds = parse_max_runtime_seconds(os.environ)
    started_at = time.monotonic()
    tasks = load_tasks(args.input_root / "tasks.json")
    if args.task_limit is not None:
        if args.task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        tasks = tasks[: args.task_limit]

    license_sources = [
        LicenseSource("Pixal3D LICENSE", PIXAL3D_ROOT / "LICENSE"),
        LicenseSource("Pixal3D model card and license metadata", Path(PIXAL3D_WEIGHTS_PATH) / "README.md"),
    ]

    for task in tasks:
        remaining = max_runtime_seconds - (time.monotonic() - started_at)
        if remaining <= 0:
            terminate_runpod_if_needed(os.environ)
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
        command = build_pixal3d_command(image_path, raw_output_dir, task.seed, DEFAULT_PARAMETERS)
        try:
            peak_vram_bytes = run_with_peak_vram(
                command,
                timeout_seconds,
                "Pixal3D",
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
            if attempt_index + 1 < MAX_TASK_ATTEMPTS:
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
            upload_task_increment_if_configured(task_output_dir, task.id, os.environ)
            return
        else:
            upload_task_increment_if_configured(task_output_dir, task.id, os.environ)
            return


def build_pixal3d_command(
    image_path: Path,
    raw_output_dir: Path,
    seed: int,
    parameters: dict[str, Any],
) -> list[str]:
    return [
        "python3",
        "/opt/3dgen-runner/pixal3d_runner.py",
        "--infer-image",
        image_path.as_posix(),
        "--infer-output-dir",
        raw_output_dir.as_posix(),
        "--infer-seed",
        str(seed),
        "--infer-resolution",
        str(parameters["resolution"]),
        "--infer-pixal3d-weights-path",
        str(parameters["pixal3d_weights_path"]),
    ]


def run_pixal3d_infer(args: argparse.Namespace) -> None:
    require_infer_arg(args.infer_output_dir, "--infer-output-dir")
    require_infer_arg(args.infer_seed, "--infer-seed")
    require_infer_arg(args.infer_resolution, "--infer-resolution")
    require_infer_arg(args.infer_pixal3d_weights_path, "--infer-pixal3d-weights-path")
    if not args.infer_image.is_file():
        raise FileNotFoundError(f"missing input image: {args.infer_image}")
    resolution = require_int(args.infer_resolution, "--infer-resolution")
    if resolution != DEFAULT_PARAMETERS["resolution"]:
        raise ValueError("--infer-resolution must be 1536 for the wave 2 Pixal3D standard protocol")
    weights_path = args.infer_pixal3d_weights_path
    if not (weights_path / "pipeline.json").is_file():
        raise FileNotFoundError(f"missing Pixal3D pipeline.json: {weights_path / 'pipeline.json'}")

    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    os.environ["ATTN_BACKEND"] = DEFAULT_PARAMETERS["attention_backend"]
    os.environ["SPARSE_ATTN_BACKEND"] = DEFAULT_PARAMETERS["attention_backend"]
    os.environ["FLEX_GEMM_AUTOTUNE_CACHE_PATH"] = str(PIXAL3D_ROOT / "autotune_cache.json")
    os.environ["FLEX_GEMM_AUTOTUNER_VERBOSE"] = "1"
    sys.path.insert(0, str(PIXAL3D_ROOT))

    from inference import run_inference

    args.infer_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.infer_output_dir / "output.glb"
    run_inference(
        image_path=str(args.infer_image),
        output_path=str(output_path),
        seed=args.infer_seed,
        model_path=str(weights_path),
        manual_fov=DEFAULT_PARAMETERS["manual_fov"],
        low_vram=DEFAULT_PARAMETERS["low_vram"],
        resolution=resolution,
        image_resolution=DEFAULT_PARAMETERS["image_resolution"],
        max_num_tokens=DEFAULT_PARAMETERS["max_num_tokens"],
    )

    overrides = {
        "attention_backend": DEFAULT_PARAMETERS["attention_backend"],
        "low_vram": DEFAULT_PARAMETERS["low_vram"],
        "manual_fov": DEFAULT_PARAMETERS["manual_fov"],
        "pixal3d_weights_path": str(weights_path),
        "pipeline_type": DEFAULT_PARAMETERS["pipeline_type"],
        "resolution": resolution,
        "seed": args.infer_seed,
    }
    (args.infer_output_dir / "inference_overrides.json").write_text(
        json.dumps(overrides, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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
    if not mesh_path.is_file():
        raise FileNotFoundError(f"Pixal3D did not create expected GLB: {mesh_path}")

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
    }
    (task_output_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"pixal3d-runner failed: {exc}", file=sys.stderr)
        raise
