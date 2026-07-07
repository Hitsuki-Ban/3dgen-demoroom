from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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

REQUIRED_TASK_KEYS = frozenset({"id", "prompt", "image", "seed"})


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    prompt: str
    image: str
    seed: int


@dataclass(frozen=True)
class RuntimeSnapshot:
    gpu_name: str
    peak_vram_bytes: int
    torch_version: str
    torch_cuda_version: str
    torch_cuda_arch_list: list[str]
    attention_backend: str


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
            terminate_runpod_if_needed(os.environ)
            raise TimeoutError("MAX_RUNTIME_MIN exceeded before starting next task")
        run_task(task, args.input_root, args.output_root, remaining)


def load_tasks(path: Path) -> list[TaskDefinition]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON array")
    tasks: list[TaskDefinition] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"task[{index}] must be an object")
        keys = set(item)
        missing = REQUIRED_TASK_KEYS - keys
        unknown = keys - REQUIRED_TASK_KEYS
        if missing:
            raise ValueError(f"task[{index}] missing field(s): {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"task[{index}] unknown field(s): {', '.join(sorted(unknown))}")
        task = TaskDefinition(
            id=require_string(item["id"], f"task[{index}].id"),
            prompt=require_string(item["prompt"], f"task[{index}].prompt"),
            image=require_string(item["image"], f"task[{index}].image"),
            seed=require_int(item["seed"], f"task[{index}].seed"),
        )
        if task.id in seen:
            raise ValueError(f"duplicate task id: {task.id}")
        seen.add(task.id)
        tasks.append(task)
    return tasks


def run_task(task: TaskDefinition, input_root: Path, output_root: Path, timeout_seconds: float) -> None:
    image_path = input_root / task.image
    if not image_path.is_file():
        raise FileNotFoundError(f"missing input image for {task.id}: {image_path}")

    task_output_dir = output_root / task.id
    if task_output_dir.exists():
        raise FileExistsError(f"task output already exists: {task_output_dir}")

    work_dir = output_root / "_work" / MODEL_ID / task.id
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=False)
    raw_output_dir = work_dir / "raw"
    create_raw_output_dir(raw_output_dir)

    started_iso = utc_now()
    started_monotonic = time.monotonic()
    command = build_triposr_command(image_path, raw_output_dir, DEFAULT_PARAMETERS)
    peak_vram_bytes = run_with_peak_vram(command, timeout_seconds)
    wall_clock_seconds = time.monotonic() - started_monotonic
    finished_iso = utc_now()
    runtime = collect_runtime_snapshot(peak_vram_bytes)
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


def collect_runtime_snapshot(peak_vram_bytes: int) -> RuntimeSnapshot:
    import torch

    return RuntimeSnapshot(
        gpu_name=query_gpu_name(),
        peak_vram_bytes=peak_vram_bytes,
        torch_version=torch.__version__,
        torch_cuda_version=str(torch.version.cuda),
        torch_cuda_arch_list=list(torch.cuda.get_arch_list()),
        attention_backend="sdpa",
    )


def run_with_peak_vram(command: list[str], timeout_seconds: float) -> int:
    process = subprocess.Popen(command)
    deadline = time.monotonic() + timeout_seconds
    peak_mib = query_gpu_memory_mib()
    while process.poll() is None:
        if time.monotonic() >= deadline:
            process.kill()
            terminate_runpod_if_needed(os.environ)
            raise TimeoutError("MAX_RUNTIME_MIN exceeded while running TripoSR")
        peak_mib = max(peak_mib, query_gpu_memory_mib())
        time.sleep(0.5)
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, command)
    return peak_mib * 1024 * 1024


def query_gpu_memory_mib() -> int:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        text=True,
    )
    values = [int(line.strip()) for line in output.splitlines() if line.strip()]
    if not values:
        raise RuntimeError("nvidia-smi returned no GPU memory values")
    return max(values)


def query_gpu_name() -> str:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        text=True,
    )
    names = [line.strip() for line in output.splitlines() if line.strip()]
    if not names:
        raise RuntimeError("nvidia-smi returned no GPU name")
    return names[0]


def parse_max_runtime_seconds(env: dict[str, str]) -> int:
    raw_value = env.get("MAX_RUNTIME_MIN")
    if raw_value is None:
        return 60 * 60
    minutes = require_int(raw_value, "MAX_RUNTIME_MIN")
    if minutes <= 0:
        raise ValueError("MAX_RUNTIME_MIN must be a positive integer")
    return minutes * 60


def terminate_runpod_if_needed(env: dict[str, str]) -> None:
    pod_id = env.get("RUNPOD_POD_ID")
    if not pod_id:
        return
    api_key = env.get("RUNPOD_API_KEY")
    if not api_key:
        raise ValueError("RUNPOD_API_KEY is required when RUNPOD_POD_ID is set")

    import urllib.request

    request = urllib.request.Request(
        f"https://rest.runpod.io/v1/pods/{pod_id}",
        method="DELETE",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status >= 300:
            raise RuntimeError(f"RunPod termination failed with HTTP {response.status}")


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def require_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"triposr-runner failed: {exc}", file=sys.stderr)
        raise
