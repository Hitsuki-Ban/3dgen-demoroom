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
    terminate_runpod_if_needed,
    upload_task_increment_if_configured,
    utc_now,
    write_license_bundle,
    write_task_failure,
)


MODEL_ID = "trellis2"
MODEL_GIT_COMMIT = "75fbf0183001ed9876c8dbb35de6b68552ee08bd"
WEIGHTS_REVISION = "af44b45f2e35a493886929c6d786e563ec68364d"
TRELLIS2_ROOT = Path("/opt/TRELLIS.2")
MAX_TASK_ATTEMPTS = 2


TRELLIS2_WEIGHTS_PATH = required_env("TRELLIS2_WEIGHTS_PATH")

DEFAULT_PARAMETERS = {
    "num_samples": 1,
    "resolution": "1024",
    "pipeline_type": "1024_cascade",
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
    "max_num_tokens": 49152,
    "simplify_faces": 16777216,
    "decimation_target": 1000000,
    "texture_size": 4096,
    "remesh": True,
    "remesh_band": 1,
    "remesh_project": 0,
    "export_webp": True,
    "attention_backend": "xformers",
    "trellis2_weights_path": TRELLIS2_WEIGHTS_PATH,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="trellis2-runner")
    parser.add_argument("--input-root", type=Path, default=Path("/work/input"))
    parser.add_argument("--output-root", type=Path, default=Path("/work/output"))
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--infer-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-output-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-resolution", type=str, help=argparse.SUPPRESS)
    parser.add_argument("--infer-trellis2-weights-path", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.infer_image is not None:
        run_trellis2_infer(args)
        return

    max_runtime_seconds = parse_max_runtime_seconds(os.environ)
    started_at = time.monotonic()
    tasks = load_tasks(args.input_root / "tasks.json")
    if args.task_limit is not None:
        if args.task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        tasks = tasks[: args.task_limit]

    license_sources = [
        LicenseSource("TRELLIS.2 LICENSE", TRELLIS2_ROOT / "LICENSE"),
        LicenseSource("TRELLIS.2-4B model card and license metadata", Path(TRELLIS2_WEIGHTS_PATH) / "README.md"),
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
        command = build_trellis2_command(image_path, raw_output_dir, task.seed, DEFAULT_PARAMETERS)
        try:
            peak_vram_bytes = run_with_peak_vram(
                command,
                timeout_seconds,
                "TRELLIS.2",
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


def build_trellis2_command(
    image_path: Path,
    raw_output_dir: Path,
    seed: int,
    parameters: dict[str, Any],
) -> list[str]:
    return [
        "python3",
        "/opt/3dgen-runner/trellis2_runner.py",
        "--infer-image",
        image_path.as_posix(),
        "--infer-output-dir",
        raw_output_dir.as_posix(),
        "--infer-seed",
        str(seed),
        "--infer-resolution",
        str(parameters["resolution"]),
        "--infer-trellis2-weights-path",
        str(parameters["trellis2_weights_path"]),
    ]


def run_trellis2_infer(args: argparse.Namespace) -> None:
    require_infer_arg(args.infer_output_dir, "--infer-output-dir")
    require_infer_arg(args.infer_seed, "--infer-seed")
    require_infer_arg(args.infer_resolution, "--infer-resolution")
    require_infer_arg(args.infer_trellis2_weights_path, "--infer-trellis2-weights-path")
    if not args.infer_image.is_file():
        raise FileNotFoundError(f"missing input image: {args.infer_image}")
    if args.infer_resolution != DEFAULT_PARAMETERS["resolution"]:
        raise ValueError("--infer-resolution must be 1024 for the wave 2 TRELLIS.2 protocol")
    weights_path = args.infer_trellis2_weights_path
    if not (weights_path / "pipeline.json").is_file():
        raise FileNotFoundError(f"missing TRELLIS.2 pipeline.json: {weights_path / 'pipeline.json'}")

    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    os.environ["ATTN_BACKEND"] = DEFAULT_PARAMETERS["attention_backend"]
    sys.path.insert(0, str(TRELLIS2_ROOT))

    from PIL import Image
    from trellis2.pipelines import Trellis2ImageTo3DPipeline
    import o_voxel

    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(str(weights_path))
    pipeline.cuda()
    image = Image.open(args.infer_image)
    outputs, latents = pipeline.run(
        image,
        num_samples=DEFAULT_PARAMETERS["num_samples"],
        seed=args.infer_seed,
        sparse_structure_sampler_params=DEFAULT_PARAMETERS["sparse_structure_sampler_params"],
        shape_slat_sampler_params=DEFAULT_PARAMETERS["shape_slat_sampler_params"],
        tex_slat_sampler_params=DEFAULT_PARAMETERS["tex_slat_sampler_params"],
        pipeline_type=DEFAULT_PARAMETERS["pipeline_type"],
        max_num_tokens=DEFAULT_PARAMETERS["max_num_tokens"],
        return_latent=True,
    )
    mesh = outputs[0]
    _, _, actual_resolution = latents
    mesh.simplify(DEFAULT_PARAMETERS["simplify_faces"])
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=DEFAULT_PARAMETERS["decimation_target"],
        texture_size=DEFAULT_PARAMETERS["texture_size"],
        remesh=DEFAULT_PARAMETERS["remesh"],
        remesh_band=DEFAULT_PARAMETERS["remesh_band"],
        remesh_project=DEFAULT_PARAMETERS["remesh_project"],
        verbose=True,
    )
    args.infer_output_dir.mkdir(parents=True, exist_ok=True)
    glb.export(args.infer_output_dir / "output.glb", extension_webp=DEFAULT_PARAMETERS["export_webp"])
    overrides = {
        "actual_resolution": actual_resolution,
        "attention_backend": DEFAULT_PARAMETERS["attention_backend"],
        "pipeline_type": DEFAULT_PARAMETERS["pipeline_type"],
        "seed": args.infer_seed,
        "trellis2_weights_path": str(weights_path),
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
        raise FileNotFoundError(f"TRELLIS.2 did not create expected GLB: {mesh_path}")

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
        print(f"trellis2-runner failed: {exc}", file=sys.stderr)
        raise
