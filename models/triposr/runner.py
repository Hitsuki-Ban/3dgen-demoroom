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
    RuntimeSnapshot,
    TaskDefinition,
    VramMeasurementError,
    collect_runtime_snapshot,
    load_tasks,
    parse_max_runtime_seconds,
    run_with_peak_vram,
    upload_task_increment_if_configured,
    upload_task_increment_then_raise,
    utc_now,
    write_task_failure,
)


MODEL_ID = "triposr"
MODEL_GIT_COMMIT = "107cefdc244c39106fa830359024f6a2f1c78871"
WEIGHTS_REVISION = "5b521936b01fbe1890f6f9baed0254ab6351c04a"
TRIPOSR_ROOT = Path("/opt/TripoSR")
TRIPOSR_WEIGHTS_PATH = "/opt/weights/TripoSR"
TRIPOSR_WEIGHTS = Path(TRIPOSR_WEIGHTS_PATH)
LICENSE_PATH = TRIPOSR_ROOT / "LICENSE"

DEFAULT_PARAMETERS = {
    "chunk_size": 8192,
    "foreground_ratio": 0.85,
    "mc_resolution": 256,
    "model_save_format": "glb",
    "pretrained_model_name_or_path": TRIPOSR_WEIGHTS_PATH,
}

def main() -> None:
    parser = argparse.ArgumentParser(prog="triposr-runner")
    parser.add_argument("--input-root", type=Path, default=Path("/work/input"))
    parser.add_argument("--output-root", type=Path, default=Path("/work/output"))
    parser.add_argument("--task-limit", type=int)
    args = parser.parse_args()

    max_runtime_seconds = parse_max_runtime_seconds(os.environ)
    started_at = time.monotonic()
    tasks = load_tasks(args.input_root / "tasks.json")
    if args.task_limit is not None:
        if args.task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        tasks = tasks[: args.task_limit]

    for task in tasks:
        remaining = max_runtime_seconds - (time.monotonic() - started_at)
        if remaining <= 0:
            raise TimeoutError("MAX_RUNTIME_MIN exceeded before starting next task")
        run_task(task, args.input_root, args.output_root, remaining)


def run_task(task: TaskDefinition, input_root: Path, output_root: Path, timeout_seconds: float) -> None:
    image_path = input_root / task.image
    if not image_path.is_file():
        raise FileNotFoundError(f"missing input image for {task.id}: {image_path}")

    task_output_dir = output_root / task.id
    if task_output_dir.exists():
        raise FileExistsError(f"task output already exists: {task_output_dir}")

    work_dir = output_root / "_work" / MODEL_ID / task.id
    first_started_iso = utc_now()
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=False)
    raw_output_dir = work_dir / "raw"
    create_raw_output_dir(raw_output_dir)

    started_iso = utc_now()
    started_monotonic = time.monotonic()
    command = build_triposr_command(image_path, raw_output_dir, DEFAULT_PARAMETERS)
    try:
        vram_measurement = run_with_peak_vram(
            command,
            timeout_seconds,
            "TripoSR",
            log_path=raw_output_dir / "infer.log",
        )
        wall_clock_seconds = time.monotonic() - started_monotonic
        finished_iso = utc_now()
        runtime = collect_runtime_snapshot(vram_measurement, "sdpa")
        prepare_task_output(
            task=task,
            task_output_dir=task_output_dir,
            raw_output_dir=raw_output_dir,
            license_path=LICENSE_PATH,
            runtime=runtime,
            wall_clock_seconds=wall_clock_seconds,
            retry_count=0,
            started_at=started_iso,
            finished_at=finished_iso,
        )
        shutil.rmtree(work_dir)
    except Exception as exc:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        if task_output_dir.exists():
            shutil.rmtree(task_output_dir)
        write_task_failure(
            task=task,
            task_output_dir=task_output_dir,
            model_id=MODEL_ID,
            model_git_commit=MODEL_GIT_COMMIT,
            weights_revision=WEIGHTS_REVISION,
            parameters=DEFAULT_PARAMETERS,
            error=exc,
            retry_count=0,
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


def build_triposr_command(image_path: Path, raw_output_dir: Path, parameters: dict[str, Any]) -> list[str]:
    command = [
        "python3",
        "/opt/TripoSR/run.py",
        str(image_path),
        "--pretrained-model-name-or-path",
        str(parameters["pretrained_model_name_or_path"]),
        "--output-dir",
        str(raw_output_dir),
        "--model-save-format",
        str(parameters["model_save_format"]),
        "--chunk-size",
        str(parameters["chunk_size"]),
        "--mc-resolution",
        str(parameters["mc_resolution"]),
        "--foreground-ratio",
        str(parameters["foreground_ratio"]),
    ]
    return command


def create_raw_output_dir(raw_output_dir: Path) -> None:
    (raw_output_dir / "0").mkdir(parents=True, exist_ok=False)


def prepare_task_output(
    *,
    task: TaskDefinition,
    task_output_dir: Path,
    raw_output_dir: Path,
    license_path: Path,
    runtime: RuntimeSnapshot,
    wall_clock_seconds: float,
    retry_count: int,
    started_at: str,
    finished_at: str,
) -> None:
    if task_output_dir.exists():
        raise FileExistsError(f"task output already exists: {task_output_dir}")
    mesh_path = raw_output_dir / "0" / "mesh.glb"
    if not mesh_path.is_file():
        raise FileNotFoundError(f"TripoSR did not create expected mesh: {mesh_path}")
    if not license_path.is_file():
        raise FileNotFoundError(f"missing TripoSR license file: {license_path}")

    task_output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(mesh_path, task_output_dir / "output.glb")
    shutil.copy2(license_path, task_output_dir / "LICENSE")
    shutil.copytree(raw_output_dir, task_output_dir / "raw" / MODEL_ID)
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
        "license_file": "LICENSE",
    }
    (task_output_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"triposr-runner failed: {exc}", file=sys.stderr)
        raise
