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


MODEL_ID = "3dtopia-xl"
MODEL_GIT_COMMIT = "4017e5bfbaab7f73632b47311a92a434abb9d2fc"
WEIGHTS_REVISION = "8a348b850d36d6354a26917d531eb8f2a5633515"
TOPIA_ROOT = Path("/opt/3DTopia-XL")
MAX_TASK_ATTEMPTS = 2


TOPIA_XL_WEIGHTS_PATH = required_env("TOPIA_XL_WEIGHTS_PATH")

DEFAULT_PARAMETERS = {
    "ddim": 25,
    "cfg": 6,
    "precision": "fp16",
    "export_glb": True,
    "fast_unwrap": False,
    "decimate": 100000,
    "mc_resolution": 256,
    "batch_size": 8192,
    "remesh": False,
    "image_height": 518,
    "image_width": 518,
    "checkpoint_path": f"{TOPIA_XL_WEIGHTS_PATH}/model_sview_dit_fp16.pt",
    "vae_checkpoint_path": f"{TOPIA_XL_WEIGHTS_PATH}/model_vae_fp16.pt",
    "topia_xl_weights_path": TOPIA_XL_WEIGHTS_PATH,
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="3dtopia-xl-runner")
    parser.add_argument("--input-root", type=Path, default=Path("/work/input"))
    parser.add_argument("--output-root", type=Path, default=Path("/work/output"))
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--infer-image", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-output-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--infer-seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--infer-topia-xl-weights-path", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.infer_image is not None:
        run_3dtopia_xl_infer(args)
        return

    max_runtime_seconds = parse_max_runtime_seconds(os.environ)
    started_at = time.monotonic()
    tasks = load_tasks(args.input_root / "tasks.json")
    if args.task_limit is not None:
        if args.task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        tasks = tasks[: args.task_limit]

    license_sources = [
        LicenseSource("3DTopia-XL LICENSE", TOPIA_ROOT / "LICENSE.txt"),
        LicenseSource("3DTopia-XL model card and license metadata", Path(TOPIA_XL_WEIGHTS_PATH) / "README.md"),
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
        command = build_3dtopia_xl_command(image_path, raw_output_dir, task.seed, DEFAULT_PARAMETERS)
        try:
            peak_vram_bytes = run_with_peak_vram(
                command,
                timeout_seconds,
                "3DTopia-XL",
                log_path=raw_output_dir / "infer.log",
            )
            wall_clock_seconds = time.monotonic() - started_monotonic
            finished_iso = utc_now()
            runtime = collect_runtime_snapshot(peak_vram_bytes, "xformers")
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


def build_3dtopia_xl_command(
    image_path: Path,
    raw_output_dir: Path,
    seed: int,
    parameters: dict[str, Any],
) -> list[str]:
    return [
        "python3",
        "/opt/3dgen-runner/3dtopia_xl_runner.py",
        "--infer-image",
        str(image_path),
        "--infer-output-dir",
        str(raw_output_dir),
        "--infer-seed",
        str(seed),
        "--infer-topia-xl-weights-path",
        str(parameters["topia_xl_weights_path"]),
    ]


def run_3dtopia_xl_infer(args: argparse.Namespace) -> None:
    require_infer_arg(args.infer_output_dir, "--infer-output-dir")
    require_infer_arg(args.infer_seed, "--infer-seed")
    require_infer_arg(args.infer_topia_xl_weights_path, "--infer-topia-xl-weights-path")
    if not args.infer_image.is_file():
        raise FileNotFoundError(f"missing input image: {args.infer_image}")

    weights_path = args.infer_topia_xl_weights_path
    checkpoint_path = weights_path / "model_sview_dit_fp16.pt"
    vae_checkpoint_path = weights_path / "model_vae_fp16.pt"
    for path in (checkpoint_path, vae_checkpoint_path):
        if not path.is_file():
            raise FileNotFoundError(f"missing 3DTopia-XL weight file: {path}")

    input_dir = args.infer_output_dir / "input"
    run_root = args.infer_output_dir / "runs"
    input_dir.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)
    task_image = input_dir / "task.png"
    shutil.copy2(args.infer_image, task_image)

    command = [
        "python3",
        str(TOPIA_ROOT / "inference.py"),
        str(TOPIA_ROOT / "configs" / "inference_dit.yml"),
        f"root_data_dir={run_root}",
        f"checkpoint_path={checkpoint_path}",
        f"model.vae_checkpoint_path={vae_checkpoint_path}",
        f"inference.input_dir={input_dir}",
        f"inference.seed={args.infer_seed}",
        "inference.export_glb=True",
    ]
    import subprocess

    subprocess.run(command, cwd=TOPIA_ROOT, check=True)
    generated_glb = run_root / "inference" / "3dtopia-xl-sview" / "inference_folder" / "task" / "pbr_mesh.glb"
    if not generated_glb.is_file():
        raise FileNotFoundError(f"3DTopia-XL did not create expected GLB: {generated_glb}")
    shutil.copy2(generated_glb, args.infer_output_dir / "output.glb")
    overrides = {
        "root_data_dir": str(run_root),
        "checkpoint_path": str(checkpoint_path),
        "model.vae_checkpoint_path": str(vae_checkpoint_path),
        "inference.input_dir": str(input_dir),
        "inference.seed": args.infer_seed,
        "inference.export_glb": True,
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
    overrides_path = raw_output_dir / "inference_overrides.json"
    if not mesh_path.is_file():
        raise FileNotFoundError(f"3DTopia-XL did not create expected mesh: {mesh_path}")
    if not overrides_path.is_file():
        raise FileNotFoundError(f"3DTopia-XL did not write inference overrides: {overrides_path}")

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
        print(f"3dtopia-xl-runner failed: {exc}", file=sys.stderr)
        raise
