from __future__ import annotations

import csv
import io
import json
import os
import platform
import re
import signal
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, NoReturn


BENCH_GPU_UUID_ENV = "BENCH_GPU_UUID"
BENCH_PID_NAMESPACE_ENV = "BENCH_PID_NAMESPACE"
BENCH_VRAM_MEASUREMENT_MODE_ENV = "BENCH_VRAM_MEASUREMENT_MODE"
HOST_PID_NAMESPACE = "host"
PROCESS_GROUP_VRAM_MODE = "process_group"
RUNPOD_EXCLUSIVE_DEVICE_VRAM_MODE = "runpod_exclusive_device"
VRAM_SAMPLE_INTERVAL_SECONDS = 0.5
VRAM_SAMPLE_INTERVAL_MS = 500
NVIDIA_SMI_QUERY_TIMEOUT_SECONDS = 10.0
MIB_BYTES = 1024 * 1024
VRAM_MEASUREMENT_SCHEMA_VERSION = 1
GPU_UUID_PATTERN = re.compile(
    r"GPU-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
DEFAULT_MPS_PIPE_DIRECTORY = Path("/tmp/nvidia-mps")
MPS_CONTROL_PID_FILENAME = "nvidia-cuda-mps-control.pid"


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    prompt: str
    image: str
    seed: int


@dataclass(frozen=True)
class GpuDeviceIdentity:
    index: int
    uuid: str
    name: str
    driver_model: str
    mig_mode: str


@dataclass(frozen=True)
class VramMeasurement:
    device: GpuDeviceIdentity
    peak_vram_bytes: int
    device_baseline_bytes: int
    mode: str
    root_pid: int
    sample_interval_ms: int
    sample_count: int
    max_matched_process_count: int
    pid_namespace_verified: bool

    def to_meta(self) -> dict[str, Any]:
        if self.mode == PROCESS_GROUP_VRAM_MODE:
            method = "nvidia_smi_compute_process_mib_sampled_sum"
            scope = "inference_process_group"
            device_baseline_included = False
            co_resident_processes_included = False
        elif self.mode == RUNPOD_EXCLUSIVE_DEVICE_VRAM_MODE:
            method = "nvidia_smi_device_memory_mib_sampled"
            scope = "runpod_exclusive_device"
            device_baseline_included = True
            co_resident_processes_included = True
        else:
            raise VramConfigurationError(f"unsupported VRAM measurement mode: {self.mode}")
        return {
            "schema_version": VRAM_MEASUREMENT_SCHEMA_VERSION,
            "method": method,
            "scope": scope,
            "gpu_uuid": self.device.uuid,
            "gpu_index": self.device.index,
            "cuda_device_ordinal": 0,
            "root_pid": self.root_pid,
            "sample_interval_ms": self.sample_interval_ms,
            "sample_count": self.sample_count,
            "max_matched_process_count": self.max_matched_process_count,
            "pid_namespace_verified": self.pid_namespace_verified,
            "device_baseline_bytes": self.device_baseline_bytes,
            "device_baseline_included": device_baseline_included,
            "co_resident_processes_included": co_resident_processes_included,
        }


@dataclass(frozen=True)
class RuntimeSnapshot:
    vram: VramMeasurement
    torch_version: str
    torch_cuda_version: str
    torch_cuda_arch_list: list[str]
    attention_backend: str

    @property
    def gpu_name(self) -> str:
        return self.vram.device.name

    @property
    def peak_vram_bytes(self) -> int:
        return self.vram.peak_vram_bytes


@dataclass(frozen=True)
class GpuComputeProcess:
    gpu_uuid: str
    pid: int
    process_name: str
    used_memory_mib: int


@dataclass(frozen=True)
class VramMeasurementTarget:
    device: GpuDeviceIdentity
    mode: str
    device_baseline_bytes: int


class VramMeasurementError(RuntimeError):
    pass


class VramConfigurationError(VramMeasurementError):
    pass


class VramQueryError(VramMeasurementError):
    pass


class VramProcessScopeError(VramMeasurementError):
    pass


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


@dataclass(frozen=True)
class RunnerTimeoutError(TimeoutError):
    command: list[str]
    timeout_label: str
    output_tail: str | None = None

    def __str__(self) -> str:
        message = f"MAX_RUNTIME_MIN exceeded while running {self.timeout_label}"
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


def select_tasks(
    tasks: list[TaskDefinition],
    *,
    task_ids: list[str],
    task_limit: int | None,
) -> list[TaskDefinition]:
    if task_limit is not None and task_ids:
        raise ValueError("--task-limit and --task-id are mutually exclusive")
    if task_limit is not None:
        if task_limit <= 0:
            raise ValueError("--task-limit must be a positive integer")
        return tasks[:task_limit]
    if not task_ids:
        return tasks
    if any(not task_id.strip() for task_id in task_ids):
        raise ValueError("--task-id must not be empty")
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("--task-id must not contain duplicates")

    tasks_by_id = {task.id: task for task in tasks}
    missing = [task_id for task_id in task_ids if task_id not in tasks_by_id]
    if missing:
        raise ValueError(f"unknown --task-id value(s): {', '.join(missing)}")
    return [tasks_by_id[task_id] for task_id in task_ids]


def parse_max_runtime_seconds(env: dict[str, str]) -> int:
    raw_value = env.get("MAX_RUNTIME_MIN")
    if raw_value is None:
        return 60 * 60
    minutes = require_int(raw_value, "MAX_RUNTIME_MIN")
    if minutes <= 0:
        raise ValueError("MAX_RUNTIME_MIN must be a positive integer")
    return minutes * 60


def should_retry_task_error(error: Exception, attempt_index: int, max_attempts: int) -> bool:
    return not isinstance(error, (TimeoutError, VramMeasurementError)) and attempt_index + 1 < max_attempts


def upload_task_increment_if_configured(task_output_dir: Path, task_id: str, env: dict[str, str]) -> list[str]:
    target = env.get("RUNPOD_INCREMENTAL_S3_TARGET")
    if not target:
        return []
    from bench_harness.uploader import create_uploader

    uploader = create_uploader("s3", target, env=env)
    return uploader.upload_run(task_output_dir, task_id)


def upload_task_increment_then_raise(
    task_output_dir: Path,
    task_id: str,
    env: dict[str, str],
    error: Exception,
    *,
    upload: Callable[[Path, str, dict[str, str]], list[str]],
) -> NoReturn:
    try:
        upload(task_output_dir, task_id, env)
    except BaseException as upload_error:
        raise error from upload_error
    raise error


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
        (task_output_dir / "infer.log").write_text(output_tail.rstrip() + "\n", encoding="utf-8")
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


def collect_runtime_snapshot(vram_measurement: VramMeasurement, attention_backend: str) -> RuntimeSnapshot:
    import torch

    return RuntimeSnapshot(
        vram=vram_measurement,
        torch_version=torch.__version__,
        torch_cuda_version=str(torch.version.cuda),
        torch_cuda_arch_list=list(torch.cuda.get_arch_list()),
        attention_backend=attention_backend,
    )


class _PeakVramSampler:
    def __init__(self, target: VramMeasurementTarget, root_pid: int) -> None:
        self.target = target
        self.root_pid = root_pid
        self.peak_vram_bytes = target.device_baseline_bytes
        self.sample_count = 0
        self.max_matched_process_count = 0
        self.saw_target_process = False

    def sample(self) -> None:
        processes = query_gpu_compute_processes(self.target.device)
        reject_mps_compute_processes(processes)
        if self.target.mode == PROCESS_GROUP_VRAM_MODE:
            process_group_pids = query_process_group_pids(self.root_pid)
            matched = [process for process in processes if process.pid in process_group_pids]
            current_vram_bytes = sum(process.used_memory_mib for process in matched) * MIB_BYTES
            if matched:
                self.saw_target_process = True
            self.max_matched_process_count = max(self.max_matched_process_count, len(matched))
        elif self.target.mode == RUNPOD_EXCLUSIVE_DEVICE_VRAM_MODE:
            current_vram_bytes = query_gpu_device_memory_bytes(self.target.device)
        else:
            raise VramConfigurationError(f"unsupported VRAM measurement mode: {self.target.mode}")
        self.sample_count += 1
        self.peak_vram_bytes = max(self.peak_vram_bytes, current_vram_bytes)

    def finish(self) -> VramMeasurement:
        if self.sample_count == 0:
            raise VramQueryError("inference exited before any VRAM sample was collected")
        if self.target.mode == PROCESS_GROUP_VRAM_MODE and not self.saw_target_process:
            raise VramProcessScopeError(
                "no inference process-group PID was observed in the target GPU compute-process query"
            )
        if (
            self.target.mode == RUNPOD_EXCLUSIVE_DEVICE_VRAM_MODE
            and self.peak_vram_bytes <= self.target.device_baseline_bytes
        ):
            raise VramProcessScopeError("target GPU memory never rose above the pre-inference device baseline")
        return VramMeasurement(
            device=self.target.device,
            peak_vram_bytes=self.peak_vram_bytes,
            device_baseline_bytes=self.target.device_baseline_bytes,
            mode=self.target.mode,
            root_pid=self.root_pid,
            sample_interval_ms=VRAM_SAMPLE_INTERVAL_MS,
            sample_count=self.sample_count,
            max_matched_process_count=self.max_matched_process_count,
            pid_namespace_verified=self.saw_target_process,
        )


def run_with_peak_vram(
    command: list[str],
    timeout_seconds: float,
    timeout_label: str,
    *,
    log_path: Path | None = None,
) -> VramMeasurement:
    target = prepare_vram_measurement_target(os.environ)
    child_env = dict(os.environ)
    child_env["CUDA_VISIBLE_DEVICES"] = target.device.uuid
    log_handle = None
    try:
        process_group_options = _process_group_popen_options()
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("w", encoding="utf-8", buffering=1)
            process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                env=child_env,
                **process_group_options,
            )
        else:
            process = subprocess.Popen(command, env=child_env, **process_group_options)
        deadline = time.monotonic() + timeout_seconds
        sampler = _PeakVramSampler(target, process.pid)
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    if log_handle is not None:
                        log_handle.flush()
                        log_handle.close()
                        log_handle = None
                    raise RunnerTimeoutError(
                        command=command,
                        timeout_label=timeout_label,
                        output_tail=read_text_tail(log_path) if log_path is not None else None,
                    )
                sampler.sample()
                time.sleep(VRAM_SAMPLE_INTERVAL_SECONDS)
            if process.returncode != 0:
                if log_handle is not None:
                    log_handle.flush()
                    log_handle.close()
                    log_handle = None
                raise RunnerSubprocessError(
                    returncode=process.returncode,
                    command=command,
                    output_tail=read_text_tail(log_path) if log_path is not None else None,
                )
            return sampler.finish()
        except BaseException as error:
            try:
                _kill_process_group_and_wait(process)
            except BaseException as cleanup_error:
                raise error from cleanup_error
            raise
    finally:
        if log_handle is not None:
            log_handle.close()


def _process_group_popen_options() -> dict[str, Any]:
    if os.name == "posix":
        return {"start_new_session": True}
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    raise RuntimeError(f"unsupported subprocess platform: {os.name}")


def _kill_process_group_and_wait(process: subprocess.Popen[Any]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif os.name == "nt":
            if process.poll() is None:
                process.kill()
        else:
            raise RuntimeError(f"unsupported subprocess platform: {os.name}")
    except ProcessLookupError:
        pass
    process.wait()


def read_text_tail(path: Path, max_bytes: int = 12000) -> str:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes), os.SEEK_SET)
        return handle.read().decode("utf-8", errors="replace").strip()


def prepare_vram_measurement_target(env: Mapping[str, str]) -> VramMeasurementTarget:
    mode = env.get(BENCH_VRAM_MEASUREMENT_MODE_ENV)
    if mode not in {PROCESS_GROUP_VRAM_MODE, RUNPOD_EXCLUSIVE_DEVICE_VRAM_MODE}:
        raise VramConfigurationError(
            f"{BENCH_VRAM_MEASUREMENT_MODE_ENV} must be one of "
            f"{PROCESS_GROUP_VRAM_MODE!r} or {RUNPOD_EXCLUSIVE_DEVICE_VRAM_MODE!r}"
        )
    reject_active_mps_control(env)
    if is_wsl():
        raise VramConfigurationError(
            "canonical VRAM measurement is unavailable under WSL because NVIDIA does not support "
            "active-compute-process queries there"
        )

    if mode == PROCESS_GROUP_VRAM_MODE:
        if env.get(BENCH_PID_NAMESPACE_ENV) != HOST_PID_NAMESPACE:
            raise VramConfigurationError(
                f"{BENCH_PID_NAMESPACE_ENV} must equal {HOST_PID_NAMESPACE!r} for process_group measurement"
            )
        if os.name != "posix" or not Path("/proc").is_dir():
            raise VramConfigurationError("process_group VRAM measurement requires Linux /proc")
    elif not env.get("RUNPOD_POD_ID"):
        raise VramConfigurationError("RUNPOD_POD_ID is required for runpod_exclusive_device measurement")

    device = select_target_gpu(query_gpu_inventory(), env.get(BENCH_GPU_UUID_ENV))
    if device.driver_model.upper() == "WDDM":
        raise VramConfigurationError(
            "per-process NVIDIA memory accounting is unavailable under WDDM; "
            "run the benchmark on Linux/TCC or an explicitly supported RunPod"
        )
    if device.mig_mode.lower() == "enabled":
        raise VramConfigurationError("MIG devices are not supported by the VRAM measurement contract")

    preexisting_processes = query_gpu_compute_processes(device)
    validate_preexisting_compute_processes(mode, preexisting_processes)
    device_baseline_bytes = (
        query_gpu_device_memory_bytes(device) if mode == RUNPOD_EXCLUSIVE_DEVICE_VRAM_MODE else 0
    )
    return VramMeasurementTarget(device=device, mode=mode, device_baseline_bytes=device_baseline_bytes)


def query_gpu_inventory() -> list[GpuDeviceIdentity]:
    output = _query_nvidia_smi(
        [
            "--query-gpu=index,uuid,name,driver_model.current,mig.mode.current",
            "--format=csv,noheader,nounits",
        ]
    )
    return parse_gpu_inventory(output)


def parse_gpu_inventory(output: str) -> list[GpuDeviceIdentity]:
    devices: list[GpuDeviceIdentity] = []
    indexes: set[int] = set()
    uuids: set[str] = set()
    for row_index, row in enumerate(csv.reader(io.StringIO(output))):
        if not row or not any(value.strip() for value in row):
            continue
        if len(row) != 5:
            raise VramQueryError(f"GPU inventory row {row_index} must have 5 columns")
        index = _parse_nonnegative_int(row[0], f"GPU inventory row {row_index} index")
        uuid = row[1].strip()
        name = row[2].strip()
        driver_model = _normalize_nvidia_value(row[3])
        mig_mode = _normalize_nvidia_value(row[4])
        if GPU_UUID_PATTERN.fullmatch(uuid) is None or not name:
            raise VramQueryError(f"GPU inventory row {row_index} has invalid UUID or name")
        if index in indexes or uuid in uuids:
            raise VramQueryError("nvidia-smi returned duplicate GPU index or UUID")
        indexes.add(index)
        uuids.add(uuid)
        devices.append(
            GpuDeviceIdentity(
                index=index,
                uuid=uuid,
                name=name,
                driver_model=driver_model,
                mig_mode=mig_mode,
            )
        )
    if not devices:
        raise VramQueryError("nvidia-smi returned no GPU inventory rows")
    return devices


def select_target_gpu(devices: list[GpuDeviceIdentity], requested_uuid: str | None) -> GpuDeviceIdentity:
    if requested_uuid is not None:
        requested_uuid = requested_uuid.strip()
        if not requested_uuid:
            raise VramConfigurationError(f"{BENCH_GPU_UUID_ENV} must not be empty")
        if requested_uuid.startswith("MIG-"):
            raise VramConfigurationError("MIG UUIDs are not supported by the VRAM measurement contract")
        matches = [device for device in devices if device.uuid == requested_uuid]
        if len(matches) != 1:
            raise VramConfigurationError(
                f"{BENCH_GPU_UUID_ENV} must exactly match one visible full GPU UUID: {requested_uuid}"
            )
        return matches[0]
    if len(devices) != 1:
        raise VramConfigurationError(
            f"{BENCH_GPU_UUID_ENV} is required when nvidia-smi exposes {len(devices)} GPUs"
        )
    return devices[0]


def query_gpu_compute_processes(device: GpuDeviceIdentity) -> list[GpuComputeProcess]:
    output = _query_nvidia_smi(
        [
            f"--id={device.uuid}",
            "--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    return parse_gpu_compute_processes(output, device.uuid)


def parse_gpu_compute_processes(output: str, expected_gpu_uuid: str) -> list[GpuComputeProcess]:
    processes: list[GpuComputeProcess] = []
    pids: set[int] = set()
    for row_index, row in enumerate(csv.reader(io.StringIO(output))):
        if not row or not any(value.strip() for value in row):
            continue
        if len(row) != 4:
            raise VramQueryError(f"compute-process row {row_index} must have 4 columns")
        gpu_uuid = row[0].strip()
        if gpu_uuid != expected_gpu_uuid:
            raise VramQueryError(
                f"compute-process row {row_index} belongs to {gpu_uuid}, expected {expected_gpu_uuid}"
            )
        pid = _parse_positive_int(row[1], f"compute-process row {row_index} PID")
        process_name = _normalize_nvidia_value(row[2])
        used_memory_mib = _parse_nonnegative_int(row[3], f"compute-process row {row_index} used memory")
        if pid in pids:
            raise VramQueryError(f"nvidia-smi returned duplicate compute PID {pid} for {expected_gpu_uuid}")
        pids.add(pid)
        processes.append(
            GpuComputeProcess(
                gpu_uuid=gpu_uuid,
                pid=pid,
                process_name=process_name,
                used_memory_mib=used_memory_mib,
            )
        )
    return processes


def reject_mps_compute_processes(processes: list[GpuComputeProcess]) -> None:
    mps_pids = sorted(
        process.pid
        for process in processes
        if Path(process.process_name).name.casefold() == "nvidia-cuda-mps-server"
    )
    if mps_pids:
        raise VramConfigurationError(
            "CUDA MPS is not supported by the VRAM measurement contract; "
            f"nvidia-cuda-mps-server PID(s): {', '.join(str(pid) for pid in mps_pids)}"
        )


def validate_preexisting_compute_processes(mode: str, processes: list[GpuComputeProcess]) -> None:
    reject_mps_compute_processes(processes)
    if mode not in {PROCESS_GROUP_VRAM_MODE, RUNPOD_EXCLUSIVE_DEVICE_VRAM_MODE}:
        raise VramConfigurationError(f"unsupported VRAM measurement mode: {mode}")
    if mode == RUNPOD_EXCLUSIVE_DEVICE_VRAM_MODE and processes:
        pids = ", ".join(str(process.pid) for process in processes)
        raise VramProcessScopeError(f"target GPU is not idle before inference; compute PID(s): {pids}")


def reject_active_mps_control(env: Mapping[str, str]) -> None:
    configured_directory = env.get("CUDA_MPS_PIPE_DIRECTORY")
    pipe_directory = Path(configured_directory) if configured_directory else DEFAULT_MPS_PIPE_DIRECTORY
    control_pid_file = pipe_directory / MPS_CONTROL_PID_FILENAME
    if control_pid_file.exists():
        raise VramConfigurationError(
            "CUDA MPS is not supported by the VRAM measurement contract; "
            f"MPS control PID file exists: {control_pid_file}"
        )


def is_wsl() -> bool:
    return "microsoft" in platform.release().casefold()


def query_gpu_device_memory_bytes(device: GpuDeviceIdentity) -> int:
    output = _query_nvidia_smi(
        [
            f"--id={device.uuid}",
            "--query-gpu=uuid,memory.used",
            "--format=csv,noheader,nounits",
        ]
    )
    rows = [row for row in csv.reader(io.StringIO(output)) if row and any(value.strip() for value in row)]
    if len(rows) != 1 or len(rows[0]) != 2:
        raise VramQueryError("target-device memory query must return exactly one 2-column row")
    uuid = rows[0][0].strip()
    if uuid != device.uuid:
        raise VramQueryError(f"device-memory row belongs to {uuid}, expected {device.uuid}")
    return _parse_nonnegative_int(rows[0][1], "target-device used memory") * MIB_BYTES


def query_process_group_pids(process_group_id: int, proc_root: Path = Path("/proc")) -> set[int]:
    if process_group_id <= 0:
        raise VramProcessScopeError("inference process group ID must be positive")
    if not proc_root.is_dir():
        raise VramProcessScopeError(f"process filesystem is unavailable: {proc_root}")
    pids: set[int] = set()
    try:
        entries = list(proc_root.iterdir())
    except OSError as exc:
        raise VramProcessScopeError(f"failed to enumerate process filesystem: {proc_root}") from exc
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            stat_line = (entry / "stat").read_text(encoding="utf-8")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        pid, pgrp = parse_proc_stat_identity(stat_line)
        if pgrp == process_group_id:
            pids.add(pid)
    return pids


def parse_proc_stat_identity(stat_line: str) -> tuple[int, int]:
    open_paren = stat_line.find("(")
    close_paren = stat_line.rfind(")")
    if open_paren <= 0 or close_paren <= open_paren:
        raise VramQueryError("/proc PID stat row has invalid command delimiters")
    fields = stat_line[close_paren + 1 :].split()
    if len(fields) < 3:
        raise VramQueryError("/proc PID stat row is missing process-group fields")
    pid = _parse_positive_int(stat_line[:open_paren], "/proc PID")
    pgrp = _parse_positive_int(fields[2], "/proc process group")
    return pid, pgrp


def _query_nvidia_smi(arguments: list[str]) -> str:
    command = ["nvidia-smi", *arguments]
    try:
        return subprocess.check_output(
            command,
            text=True,
            stderr=subprocess.STDOUT,
            timeout=NVIDIA_SMI_QUERY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise VramQueryError(
            f"nvidia-smi query timed out after {NVIDIA_SMI_QUERY_TIMEOUT_SECONDS:g}s for {arguments!r}"
        ) from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "output", None)
        suffix = f": {str(detail).strip()}" if detail and str(detail).strip() else ""
        raise VramQueryError(f"nvidia-smi query failed for {arguments!r}{suffix}") from exc


def _normalize_nvidia_value(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1].strip()
    if not normalized:
        raise VramQueryError("nvidia-smi returned an empty value")
    return normalized


def _parse_nonnegative_int(value: str, field: str) -> int:
    normalized = _normalize_nvidia_value(value)
    try:
        parsed = int(normalized)
    except ValueError as exc:
        raise VramQueryError(f"{field} must be a non-negative integer, got {value.strip()!r}") from exc
    if parsed < 0:
        raise VramQueryError(f"{field} must be a non-negative integer")
    return parsed


def _parse_positive_int(value: str, field: str) -> int:
    parsed = _parse_nonnegative_int(value, field)
    if parsed == 0:
        raise VramQueryError(f"{field} must be a positive integer")
    return parsed


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
