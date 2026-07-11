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
    VramMeasurementError,
    collect_runtime_snapshot,
    load_tasks,
    parse_max_runtime_seconds,
    require_infer_arg,
    require_int,
    required_env,
    run_with_peak_vram,
    should_retry_task_error,
    upload_task_increment_if_configured,
    upload_task_increment_then_raise,
    utc_now,
    write_license_bundle,
    write_task_failure,
)


MODEL_ID = "trellis1"
MODEL_GIT_COMMIT = "442aa1e1afb9014e80681d3bf604e8d728a86ee7"
WEIGHTS_REVISION = "25e0d31ffbebe4b5a97464dd851910efc3002d96"
TRELLIS_ROOT = Path("/opt/TRELLIS")
MAX_TASK_ATTEMPTS = 2


TRELLIS1_WEIGHTS_PATH = required_env("TRELLIS1_WEIGHTS_PATH")

DEFAULT_PARAMETERS = {
    "num_samples": 1,
    "sparse_structure_sampler_params": {
        "steps": 25,
        "cfg_strength": 5.0,
        "cfg_interval": [0.5, 1.0],
        "rescale_t": 3.0,
    },
    "slat_sampler_params": {
        "steps": 25,
        "cfg_strength": 5.0,
        "cfg_interval": [0.5, 1.0],
        "rescale_t": 3.0,
    },
    "formats": ["mesh", "gaussian", "radiance_field"],
    "preprocess_image": True,
    "simplify": 0.95,
    "texture_size": 1024,
    "attention_backend": "xformers",
    "spconv_algo": "native",
    "trellis1_weights_path": TRELLIS1_WEIGHTS_PATH,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="trellis1-runner")
    parser.add_argument("--input-root", type=Path, default=Path("/work/input"))
    parser.add_argument("--output-root", type=Path, default=Path("/work/output"))
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--infer-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-output-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-simplify", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--infer-texture-size", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-trellis1-weights-path", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.infer_image is not None:
        run_trellis1_infer(args)
        return

    max_runtime_seconds = parse_max_runtime_seconds(os.environ)
    started_at = time.monotonic()
    tasks = load_tasks(args.input_root / "tasks.json")
    if args.task_limit is not None:
        if args.task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        tasks = tasks[: args.task_limit]

    license_sources = [
        LicenseSource("TRELLIS LICENSE", TRELLIS_ROOT / "LICENSE"),
        LicenseSource("TRELLIS-image-large model card and license metadata", Path(TRELLIS1_WEIGHTS_PATH) / "README.md"),
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
        command = build_trellis1_command(image_path, raw_output_dir, task.seed, DEFAULT_PARAMETERS)
        try:
            vram_measurement = run_with_peak_vram(
                command,
                timeout_seconds,
                "TRELLIS v1",
                log_path=raw_output_dir / "infer.log",
            )
            wall_clock_seconds = time.monotonic() - started_monotonic
            finished_iso = utc_now()
            runtime = collect_runtime_snapshot(vram_measurement, DEFAULT_PARAMETERS["attention_backend"])
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
            if isinstance(exc, (TimeoutError, VramMeasurementError)):
                upload_task_increment_then_raise(
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


def build_trellis1_command(
    image_path: Path,
    raw_output_dir: Path,
    seed: int,
    parameters: dict[str, Any],
) -> list[str]:
    return [
        "python3",
        "/opt/3dgen-runner/trellis1_runner.py",
        "--infer-image",
        str(image_path),
        "--infer-output-dir",
        str(raw_output_dir),
        "--infer-seed",
        str(seed),
        "--infer-simplify",
        str(parameters["simplify"]),
        "--infer-texture-size",
        str(parameters["texture_size"]),
        "--infer-trellis1-weights-path",
        str(parameters["trellis1_weights_path"]),
    ]


def run_trellis1_infer(args: argparse.Namespace) -> None:
    require_infer_arg(args.infer_output_dir, "--infer-output-dir")
    require_infer_arg(args.infer_seed, "--infer-seed")
    require_infer_arg(args.infer_simplify, "--infer-simplify")
    require_infer_arg(args.infer_texture_size, "--infer-texture-size")
    require_infer_arg(args.infer_trellis1_weights_path, "--infer-trellis1-weights-path")
    if not args.infer_image.is_file():
        raise FileNotFoundError(f"missing input image: {args.infer_image}")
    if args.infer_simplify < 0 or args.infer_simplify >= 1:
        raise ValueError("--infer-simplify must be in [0, 1)")
    texture_size = require_int(args.infer_texture_size, "--infer-texture-size")
    if texture_size <= 0:
        raise ValueError("--infer-texture-size must be positive")

    os.environ["ATTN_BACKEND"] = DEFAULT_PARAMETERS["attention_backend"]
    os.environ["SPCONV_ALGO"] = DEFAULT_PARAMETERS["spconv_algo"]
    sys.path.insert(0, str(TRELLIS_ROOT))

    from PIL import Image
    from trellis.pipelines import TrellisImageTo3DPipeline
    from trellis.utils import postprocessing_utils

    pipeline = TrellisImageTo3DPipeline.from_pretrained(str(args.infer_trellis1_weights_path))
    pipeline.cuda()
    image = Image.open(args.infer_image)
    outputs = pipeline.run(
        image,
        num_samples=DEFAULT_PARAMETERS["num_samples"],
        seed=args.infer_seed,
        sparse_structure_sampler_params=DEFAULT_PARAMETERS["sparse_structure_sampler_params"],
        slat_sampler_params=DEFAULT_PARAMETERS["slat_sampler_params"],
        formats=DEFAULT_PARAMETERS["formats"],
        preprocess_image=DEFAULT_PARAMETERS["preprocess_image"],
    )
    glb = postprocessing_utils.to_glb(
        outputs["gaussian"][0],
        outputs["mesh"][0],
        simplify=args.infer_simplify,
        texture_size=texture_size,
    )
    args.infer_output_dir.mkdir(parents=True, exist_ok=True)
    glb.export(args.infer_output_dir / "output.glb")
    outputs["gaussian"][0].save_ply(args.infer_output_dir / "output_gaussian.ply")


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
    gaussian_path = raw_output_dir / "output_gaussian.ply"
    if not mesh_path.is_file():
        raise FileNotFoundError(f"TRELLIS v1 did not create expected mesh: {mesh_path}")
    if not gaussian_path.is_file():
        raise FileNotFoundError(f"TRELLIS v1 did not create expected Gaussian PLY: {gaussian_path}")

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
        "vram_measurement": runtime.vram.to_meta(),
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
        print(f"trellis1-runner failed: {exc}", file=sys.stderr)
        raise
