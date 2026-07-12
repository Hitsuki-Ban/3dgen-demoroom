from __future__ import annotations

import json
import math
import re
import struct
from datetime import datetime
from pathlib import Path
from typing import Any


REQUIRED_META_KEYS = frozenset(
    {
        "task_id",
        "model_id",
        "model_git_commit",
        "weights_revision",
        "gpu_name",
        "wall_clock_seconds",
        "peak_vram_bytes",
        "seed",
        "parameters",
        "retry_count",
        "torch_version",
        "torch_cuda_version",
        "torch_cuda_arch_list",
        "attention_backend",
        "started_at",
        "finished_at",
        "license_file",
    }
)
OPTIONAL_META_KEYS = frozenset(
    {
        "external_weight_revisions",
        "external_code_revisions",
        "vram_measurement",
    }
)
STRING_MAP_OPTIONAL_META_KEYS = frozenset(
    {
        "external_weight_revisions",
        "external_code_revisions",
    }
)
VRAM_MEASUREMENT_KEYS = frozenset(
    {
        "schema_version",
        "method",
        "scope",
        "gpu_uuid",
        "gpu_index",
        "cuda_device_ordinal",
        "root_pid",
        "sample_interval_ms",
        "sample_count",
        "max_matched_process_count",
        "pid_namespace_verified",
        "device_baseline_bytes",
        "device_baseline_included",
        "co_resident_processes_included",
    }
)
VRAM_PROCESS_METHOD = "nvidia_smi_compute_process_mib_sampled_sum"
VRAM_PROCESS_SCOPE = "inference_process_group"
VRAM_RUNPOD_METHOD = "nvidia_smi_device_memory_mib_sampled"
VRAM_RUNPOD_SCOPE = "runpod_exclusive_device"
GPU_UUID_PATTERN = re.compile(
    r"GPU-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
REQUIRED_FAILURE_KEYS = frozenset(
    {
        "status",
        "task_id",
        "model_id",
        "model_git_commit",
        "weights_revision",
        "seed",
        "parameters",
        "retry_count",
        "error_type",
        "error_message",
        "started_at",
        "finished_at",
    }
)
OPTIONAL_FAILURE_KEYS = frozenset({"error_output_tail", "error_returncode"})


def load_run_metadata(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")

    keys = set(raw)
    missing = REQUIRED_META_KEYS - keys
    unknown = keys - REQUIRED_META_KEYS - OPTIONAL_META_KEYS
    if missing:
        raise ValueError(f"{path} missing required field(s): {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{path} contains unknown field(s): {', '.join(sorted(unknown))}")

    _require_string(raw, "task_id")
    _require_string(raw, "model_id")
    _require_string(raw, "model_git_commit")
    _require_string(raw, "weights_revision")
    _require_string(raw, "gpu_name")
    _require_number(raw, "wall_clock_seconds")
    _require_int(raw, "peak_vram_bytes")
    _require_int(raw, "seed")
    if not isinstance(raw["parameters"], dict):
        raise ValueError("parameters must be an object")
    _require_int(raw, "retry_count")
    _require_string(raw, "torch_version")
    _require_string(raw, "torch_cuda_version")
    if not isinstance(raw["torch_cuda_arch_list"], list) or not raw["torch_cuda_arch_list"] or not all(
        isinstance(item, str) and item for item in raw["torch_cuda_arch_list"]
    ):
        raise ValueError("torch_cuda_arch_list must be a non-empty string array")
    _require_string(raw, "attention_backend")
    started_at = _require_timestamp(raw, "started_at")
    finished_at = _require_timestamp(raw, "finished_at")
    if finished_at < started_at:
        raise ValueError("finished_at must not be earlier than started_at")
    _require_relative_file(raw["license_file"], "license_file")
    for field in STRING_MAP_OPTIONAL_META_KEYS:
        if field in raw:
            _require_string_map(raw[field], field)
    if "vram_measurement" in raw:
        _require_vram_measurement(raw["vram_measurement"], raw["peak_vram_bytes"])
    return raw


def load_run_failure(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")

    keys = set(raw)
    missing = REQUIRED_FAILURE_KEYS - keys
    unknown = keys - REQUIRED_FAILURE_KEYS - OPTIONAL_FAILURE_KEYS
    if missing:
        raise ValueError(f"{path} missing required field(s): {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{path} contains unknown field(s): {', '.join(sorted(unknown))}")
    if raw["status"] != "failed":
        raise ValueError("status must be 'failed'")

    for field in ("task_id", "model_id", "model_git_commit", "weights_revision", "error_type", "error_message"):
        _require_string(raw, field)
    _require_int(raw, "seed")
    if not isinstance(raw["parameters"], dict):
        raise ValueError("parameters must be an object")
    _require_int(raw, "retry_count")
    started_at = _require_timestamp(raw, "started_at")
    finished_at = _require_timestamp(raw, "finished_at")
    if finished_at < started_at:
        raise ValueError("finished_at must not be earlier than started_at")
    if "error_output_tail" in raw:
        _require_string(raw, "error_output_tail")
    if "error_returncode" in raw and (
        isinstance(raw["error_returncode"], bool) or not isinstance(raw["error_returncode"], int)
    ):
        raise ValueError("error_returncode must be an integer")
    return raw


def validate_task_output(output_dir: Path) -> dict[str, Any]:
    if not output_dir.is_dir():
        raise FileNotFoundError(f"output directory does not exist: {output_dir}")
    output_glb = output_dir / "output.glb"
    if not output_glb.is_file():
        raise FileNotFoundError(f"missing canonical GLB: {output_glb}")
    validate_glb(output_glb)
    meta = load_run_metadata(output_dir / "meta.json")
    license_file = output_dir / str(meta["license_file"])
    if not license_file.is_file():
        raise FileNotFoundError(f"missing license file declared by meta.json: {license_file}")
    resolved_output_dir = output_dir.resolve()
    resolved_license = license_file.resolve()
    if not resolved_license.is_relative_to(resolved_output_dir):
        raise ValueError(f"license file must resolve inside the task output directory: {license_file}")
    canonical_files = {
        output_glb.resolve(),
        (output_dir / "meta.json").resolve(),
        (output_dir / "failure.json").resolve(),
    }
    if resolved_license in canonical_files:
        raise ValueError(f"license file must be an independent text artifact: {license_file}")
    try:
        license_text = license_file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"license file must be UTF-8 text: {license_file}") from exc
    if not license_text.strip():
        raise ValueError(f"license file declared by meta.json is empty: {license_file}")
    return meta


def validate_failed_task_output(output_dir: Path) -> dict[str, Any]:
    if not output_dir.is_dir():
        raise FileNotFoundError(f"output directory does not exist: {output_dir}")
    return load_run_failure(output_dir / "failure.json")


def validate_glb(path: Path) -> None:
    size = path.stat().st_size
    if size < 12:
        raise ValueError(f"{path} is too small to be a GLB")
    with path.open("rb") as stream:
        magic, version, declared_size = struct.unpack("<4sII", stream.read(12))
        if magic != b"glTF":
            raise ValueError(f"{path} has invalid GLB magic")
        if version != 2:
            raise ValueError(f"{path} uses unsupported GLB version {version}")
        if declared_size != size:
            raise ValueError(f"{path} declares {declared_size} bytes but file size is {size}")

        offset = 12
        chunk_index = 0
        gltf_json: Any = None
        while offset < size:
            chunk_header = stream.read(8)
            if len(chunk_header) != 8:
                raise ValueError(f"{path} has a truncated GLB chunk header")
            chunk_length, chunk_type = struct.unpack("<II", chunk_header)
            offset += 8
            if chunk_length == 0 or chunk_length % 4 != 0:
                raise ValueError(f"{path} has an invalid GLB chunk length {chunk_length}")
            chunk_end = offset + chunk_length
            if chunk_end > size:
                raise ValueError(f"{path} has a GLB chunk outside the declared file length")
            if chunk_index == 0:
                if chunk_type != 0x4E4F534A:
                    raise ValueError(f"{path} first GLB chunk must be JSON")
                try:
                    gltf_json = json.loads(
                        stream.read(chunk_length).decode("utf-8"),
                        parse_constant=_reject_json_constant,
                    )
                except (UnicodeDecodeError, ValueError) as exc:
                    raise ValueError(f"{path} contains invalid GLB JSON") from exc
            else:
                if chunk_type == 0x4E4F534A:
                    raise ValueError(f"{path} contains more than one GLB JSON chunk")
                stream.seek(chunk_length, 1)
            offset = chunk_end
            chunk_index += 1

    if chunk_index == 0 or not isinstance(gltf_json, dict):
        raise ValueError(f"{path} is missing a GLB JSON chunk")
    asset = gltf_json.get("asset")
    if not isinstance(asset, dict) or asset.get("version") != "2.0":
        raise ValueError(f"{path} GLB JSON must declare asset.version 2.0")


def _require_string(raw: dict[str, Any], field: str) -> None:
    if not isinstance(raw[field], str) or not raw[field].strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_number(raw: dict[str, Any], field: str) -> None:
    if isinstance(raw[field], bool) or not isinstance(raw[field], int | float):
        raise ValueError(f"{field} must be a number")
    if not math.isfinite(raw[field]):
        raise ValueError(f"{field} must be finite")
    if raw[field] < 0:
        raise ValueError(f"{field} must be non-negative")


def _require_int(raw: dict[str, Any], field: str) -> None:
    if isinstance(raw[field], bool) or not isinstance(raw[field], int):
        raise ValueError(f"{field} must be an integer")
    if raw[field] < 0:
        raise ValueError(f"{field} must be non-negative")


def _require_timestamp(raw: dict[str, Any], field: str) -> datetime:
    _require_string(raw, field)
    try:
        parsed = datetime.fromisoformat(raw[field].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _require_string_map(value: Any, field: str) -> None:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and key and isinstance(item, str) and item for key, item in value.items()
    ):
        raise ValueError(f"{field} must be an object with non-empty string keys and values")


def _require_vram_measurement(value: Any, peak_vram_bytes: int) -> None:
    if not isinstance(value, dict):
        raise ValueError("vram_measurement must be an object")
    keys = set(value)
    missing = VRAM_MEASUREMENT_KEYS - keys
    unknown = keys - VRAM_MEASUREMENT_KEYS
    if missing:
        raise ValueError(f"vram_measurement missing field(s): {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"vram_measurement contains unknown field(s): {', '.join(sorted(unknown))}")

    _require_exact_int(value, "schema_version", 1)
    method = _require_nested_string(value, "method", "vram_measurement")
    scope = _require_nested_string(value, "scope", "vram_measurement")
    gpu_uuid = _require_nested_string(value, "gpu_uuid", "vram_measurement")
    if GPU_UUID_PATTERN.fullmatch(gpu_uuid) is None:
        raise ValueError("vram_measurement.gpu_uuid must be a full GPU UUID")
    gpu_index = _require_nested_int(value, "gpu_index", "vram_measurement")
    if gpu_index < 0:
        raise ValueError("vram_measurement.gpu_index must be non-negative")
    _require_exact_int(value, "cuda_device_ordinal", 0)
    root_pid = _require_nested_int(value, "root_pid", "vram_measurement")
    if root_pid <= 0:
        raise ValueError("vram_measurement.root_pid must be positive")
    _require_exact_int(value, "sample_interval_ms", 500)
    sample_count = _require_nested_int(value, "sample_count", "vram_measurement")
    if sample_count <= 0:
        raise ValueError("vram_measurement.sample_count must be positive")
    max_process_count = _require_nested_int(value, "max_matched_process_count", "vram_measurement")
    if max_process_count < 0:
        raise ValueError("vram_measurement.max_matched_process_count must be non-negative")
    pid_namespace_verified = _require_nested_bool(value, "pid_namespace_verified", "vram_measurement")
    baseline_bytes = _require_nested_int(value, "device_baseline_bytes", "vram_measurement")
    if baseline_bytes < 0:
        raise ValueError("vram_measurement.device_baseline_bytes must be non-negative")
    baseline_included = _require_nested_bool(value, "device_baseline_included", "vram_measurement")
    co_resident_included = _require_nested_bool(
        value,
        "co_resident_processes_included",
        "vram_measurement",
    )
    if peak_vram_bytes <= 0:
        raise ValueError("peak_vram_bytes must be positive when vram_measurement is present")

    if (method, scope) == (VRAM_PROCESS_METHOD, VRAM_PROCESS_SCOPE):
        if max_process_count <= 0:
            raise ValueError("process-group VRAM measurement must match at least one process")
        if not pid_namespace_verified or baseline_bytes != 0 or baseline_included or co_resident_included:
            raise ValueError("process-group VRAM measurement flags do not match its scope")
    elif (method, scope) == (VRAM_RUNPOD_METHOD, VRAM_RUNPOD_SCOPE):
        if max_process_count != 0:
            raise ValueError("RunPod exclusive-device measurement must not report matched processes")
        if pid_namespace_verified or not baseline_included or not co_resident_included:
            raise ValueError("RunPod exclusive-device VRAM measurement flags do not match its scope")
        if peak_vram_bytes <= baseline_bytes:
            raise ValueError("RunPod peak_vram_bytes must exceed device_baseline_bytes")
    else:
        raise ValueError("vram_measurement method and scope are not a supported pair")


def _require_nested_string(raw: dict[str, Any], field: str, parent: str) -> str:
    value = raw[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{parent}.{field} must be a non-empty string")
    return value


def _require_nested_int(raw: dict[str, Any], field: str, parent: str) -> int:
    value = raw[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{parent}.{field} must be an integer")
    return value


def _require_nested_bool(raw: dict[str, Any], field: str, parent: str) -> bool:
    value = raw[field]
    if not isinstance(value, bool):
        raise ValueError(f"{parent}.{field} must be a boolean")
    return value


def _require_exact_int(raw: dict[str, Any], field: str, expected: int) -> None:
    value = _require_nested_int(raw, field, "vram_measurement")
    if value != expected:
        raise ValueError(f"vram_measurement.{field} must equal {expected}")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _require_relative_file(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative file path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a relative file path inside the task output directory")
