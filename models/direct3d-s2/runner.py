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


MODEL_ID = "direct3d-s2"
MODEL_GIT_COMMIT = "a1cf235b2881cff04a91900060a9546b40e7ee5d"
WEIGHTS_REVISION = "8b04a8eddb7a56a0f4e89fe5f5b840c7d5610c00"
DIRECT3D_S2_ROOT = Path("/opt/Direct3D-S2")
MAX_TASK_ATTEMPTS = 2


DIRECT3D_S2_WEIGHTS_PATH = required_env("DIRECT3D_S2_WEIGHTS_PATH")

DEFAULT_PARAMETERS = {
    "weights_subfolder": "direct3d-s2-v-1-1",
    "sdf_resolution": 1024,
    "dense_sampler_params": {"num_inference_steps": 50, "guidance_scale": 7.0},
    "sparse_512_sampler_params": {"num_inference_steps": 30, "guidance_scale": 7.0},
    "sparse_1024_sampler_params": {"num_inference_steps": 15, "guidance_scale": 7.0},
    "mc_threshold": 0.2,
    "remove_interior": True,
    "remesh": False,
    "simplify_ratio": 0.95,
    "geometry_only": True,
    "attention_backend": "spatial_sparse_attention",
    "direct3d_s2_weights_path": DIRECT3D_S2_WEIGHTS_PATH,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="direct3d-s2-runner")
    parser.add_argument("--input-root", type=Path, default=Path("/work/input"))
    parser.add_argument("--output-root", type=Path, default=Path("/work/output"))
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--infer-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-output-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-sdf-resolution", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-direct3d-s2-weights-path", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.infer_image is not None:
        run_direct3d_s2_infer(args)
        return

    max_runtime_seconds = parse_max_runtime_seconds(os.environ)
    started_at = time.monotonic()
    tasks = load_tasks(args.input_root / "tasks.json")
    if args.task_limit is not None:
        if args.task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        tasks = tasks[: args.task_limit]

    license_sources = [
        LicenseSource("Direct3D-S2 LICENSE", DIRECT3D_S2_ROOT / "LICENSE"),
        LicenseSource(
            "Direct3D-S2 model card and license metadata",
            Path(DIRECT3D_S2_WEIGHTS_PATH) / "README.md",
        ),
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
        command = build_direct3d_s2_command(image_path, raw_output_dir, task.seed, DEFAULT_PARAMETERS)
        try:
            peak_vram_bytes = run_with_peak_vram(
                command,
                timeout_seconds,
                "Direct3D-S2",
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


def build_direct3d_s2_command(
    image_path: Path,
    raw_output_dir: Path,
    seed: int,
    parameters: dict[str, Any],
) -> list[str]:
    return [
        "python3",
        "/opt/3dgen-runner/direct3d_s2_runner.py",
        "--infer-image",
        image_path.as_posix(),
        "--infer-output-dir",
        raw_output_dir.as_posix(),
        "--infer-seed",
        str(seed),
        "--infer-sdf-resolution",
        str(parameters["sdf_resolution"]),
        "--infer-direct3d-s2-weights-path",
        str(parameters["direct3d_s2_weights_path"]),
    ]


def run_direct3d_s2_infer(args: argparse.Namespace) -> None:
    require_infer_arg(args.infer_output_dir, "--infer-output-dir")
    require_infer_arg(args.infer_seed, "--infer-seed")
    require_infer_arg(args.infer_sdf_resolution, "--infer-sdf-resolution")
    require_infer_arg(args.infer_direct3d_s2_weights_path, "--infer-direct3d-s2-weights-path")
    if not args.infer_image.is_file():
        raise FileNotFoundError(f"missing input image: {args.infer_image}")
    sdf_resolution = require_int(args.infer_sdf_resolution, "--infer-sdf-resolution")
    if sdf_resolution != DEFAULT_PARAMETERS["sdf_resolution"]:
        raise ValueError("--infer-sdf-resolution must be 1024 for the wave 2 Direct3D-S2 protocol")
    model_dir = args.infer_direct3d_s2_weights_path / DEFAULT_PARAMETERS["weights_subfolder"]
    for filename in (
        "config.yaml",
        "model_dense.ckpt",
        "model_sparse_512.ckpt",
        "model_sparse_1024.ckpt",
        "model_refiner.ckpt",
        "model_refiner_1024.ckpt",
    ):
        path = model_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"missing Direct3D-S2 weight file: {path}")

    sys.path.insert(0, str(DIRECT3D_S2_ROOT))

    import torch
    from direct3d_s2.pipeline import Direct3DS2Pipeline

    pipeline = Direct3DS2Pipeline.from_pretrained(str(model_dir))
    pipeline.to("cuda:0")
    generator = torch.Generator(device="cuda").manual_seed(args.infer_seed)
    output = pipeline(
        str(args.infer_image),
        sdf_resolution=sdf_resolution,
        dense_sampler_params=DEFAULT_PARAMETERS["dense_sampler_params"],
        sparse_512_sampler_params=DEFAULT_PARAMETERS["sparse_512_sampler_params"],
        sparse_1024_sampler_params=DEFAULT_PARAMETERS["sparse_1024_sampler_params"],
        generator=generator,
        remesh=DEFAULT_PARAMETERS["remesh"],
        simplify_ratio=DEFAULT_PARAMETERS["simplify_ratio"],
        mc_threshold=DEFAULT_PARAMETERS["mc_threshold"],
        remove_interior=DEFAULT_PARAMETERS["remove_interior"],
    )
    mesh = output["mesh"]
    args.infer_output_dir.mkdir(parents=True, exist_ok=True)
    mesh.export(args.infer_output_dir / "output.obj", include_normals=True)
    mesh.export(args.infer_output_dir / "output.glb")
    overrides = {
        "direct3d_s2_weights_path": str(args.infer_direct3d_s2_weights_path),
        "seed": args.infer_seed,
        "sdf_resolution": sdf_resolution,
        "weights_subfolder": DEFAULT_PARAMETERS["weights_subfolder"],
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
    obj_path = raw_output_dir / "output.obj"
    if not mesh_path.is_file():
        raise FileNotFoundError(f"Direct3D-S2 did not create expected GLB: {mesh_path}")
    if not obj_path.is_file():
        raise FileNotFoundError(f"Direct3D-S2 did not create expected OBJ: {obj_path}")

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
        print(f"direct3d-s2-runner failed: {exc}", file=sys.stderr)
        raise
