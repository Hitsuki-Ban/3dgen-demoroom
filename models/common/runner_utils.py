from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNPOD_USER_AGENT = "3dgen-demoroom-bench-harness/0.1"


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


@dataclass(frozen=True)
class LicenseSource:
    title: str
    path: Path


@dataclass(frozen=True)
class RunnerSubprocessError(Exception):
    returncode: int
    command: list[str]
    output_tail: str | None = None

    def __str__(self) -> str:
        message = f"Command {self.command!r} returned non-zero exit status {self.returncode}."
        if self.output_tail:
            return f"{message}\n--- output tail ---\n{self.output_tail}"
        return message


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


def load_tasks(path: Path) -> list[TaskDefinition]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON array")
    tasks: list[TaskDefinition] = []
    seen: set[str] = set()
    required_keys = frozenset({"id", "prompt", "image", "seed"})
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"task[{index}] must be an object")
        keys = set(item)
        missing = required_keys - keys
        unknown = keys - required_keys
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


def parse_max_runtime_seconds(env: dict[str, str]) -> int:
    raw_value = env.get("MAX_RUNTIME_MIN")
    if raw_value is None:
        return 60 * 60
    minutes = require_int(raw_value, "MAX_RUNTIME_MIN")
    if minutes <= 0:
        raise ValueError("MAX_RUNTIME_MIN must be a positive integer")
    return minutes * 60


def upload_task_increment_if_configured(task_output_dir: Path, task_id: str, env: dict[str, str]) -> list[str]:
    target = env.get("RUNPOD_INCREMENTAL_S3_TARGET")
    if not target:
        return []
    from bench_harness.uploader import create_uploader

    uploader = create_uploader("s3", target, env=env)
    return uploader.upload_run(task_output_dir, task_id)


def write_task_failure(
    *,
    task: TaskDefinition,
    task_output_dir: Path,
    model_id: str,
    model_git_commit: str,
    weights_revision: str,
    parameters: dict[str, Any],
    error: Exception,
    retry_count: int,
    started_at: str,
    finished_at: str,
) -> None:
    task_output_dir.mkdir(parents=True, exist_ok=False)
    failure = {
        "status": "failed",
        "task_id": task.id,
        "model_id": model_id,
        "model_git_commit": model_git_commit,
        "weights_revision": weights_revision,
        "seed": task.seed,
        "parameters": parameters,
        "retry_count": retry_count,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "started_at": started_at,
        "finished_at": finished_at,
    }
    output_tail = getattr(error, "output_tail", None)
    if output_tail:
        failure["error_output_tail"] = output_tail
    returncode = getattr(error, "returncode", None)
    if returncode is not None:
        failure["error_returncode"] = returncode
    (task_output_dir / "failure.json").write_text(
        json.dumps(failure, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_license_bundle(destination: Path, sources: list[LicenseSource]) -> None:
    chunks: list[str] = []
    for source in sources:
        if not source.path.is_file():
            raise FileNotFoundError(f"missing license source: {source.path}")
        chunks.extend(
            [
                f"# {source.title}",
                f"Source: {source.path}",
                "",
                source.path.read_text(encoding="utf-8").rstrip(),
                "",
            ]
        )
    destination.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")


def collect_runtime_snapshot(peak_vram_bytes: int, attention_backend: str) -> RuntimeSnapshot:
    import torch

    return RuntimeSnapshot(
        gpu_name=query_gpu_name(),
        peak_vram_bytes=peak_vram_bytes,
        torch_version=torch.__version__,
        torch_cuda_version=str(torch.version.cuda),
        torch_cuda_arch_list=list(torch.cuda.get_arch_list()),
        attention_backend=attention_backend,
    )


def run_with_peak_vram(
    command: list[str],
    timeout_seconds: float,
    timeout_label: str,
    *,
    log_path: Path | None = None,
) -> int:
    log_handle = None
    try:
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("w", encoding="utf-8", buffering=1)
            process = subprocess.Popen(command, stdout=log_handle, stderr=subprocess.STDOUT, text=True)
        else:
            process = subprocess.Popen(command)
        deadline = time.monotonic() + timeout_seconds
        peak_mib = query_gpu_memory_mib()
        while process.poll() is None:
            if time.monotonic() >= deadline:
                process.kill()
                terminate_runpod_if_needed(os.environ)
                raise TimeoutError(f"MAX_RUNTIME_MIN exceeded while running {timeout_label}")
            peak_mib = max(peak_mib, query_gpu_memory_mib())
            time.sleep(0.5)
        if process.returncode != 0:
            if log_handle is not None:
                log_handle.flush()
            raise RunnerSubprocessError(
                returncode=process.returncode,
                command=command,
                output_tail=read_text_tail(log_path) if log_path is not None else None,
            )
        return peak_mib * 1024 * 1024
    finally:
        if log_handle is not None:
            log_handle.close()


def read_text_tail(path: Path, max_bytes: int = 12000) -> str:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes), os.SEEK_SET)
        return handle.read().decode("utf-8", errors="replace").strip()


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


def terminate_runpod_if_needed(env: dict[str, str]) -> None:
    pod_id = env.get("RUNPOD_POD_ID")
    if not pod_id:
        return
    api_key = env.get("RUNPOD_API_KEY")
    if not api_key:
        raise ValueError("RUNPOD_API_KEY is required when RUNPOD_POD_ID is set")

    request = urllib.request.Request(
        f"https://rest.runpod.io/v1/pods/{pod_id}",
        method="DELETE",
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": RUNPOD_USER_AGENT,
        },
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


def require_infer_arg(value: Any, flag: str) -> None:
    if value is None:
        raise ValueError(f"{flag} is required in infer mode")


def reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=False)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
