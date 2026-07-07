from __future__ import annotations

import json
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


def load_run_metadata(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")

    keys = set(raw)
    missing = REQUIRED_META_KEYS - keys
    unknown = keys - REQUIRED_META_KEYS
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
    if not isinstance(raw["torch_cuda_arch_list"], list) or not all(
        isinstance(item, str) and item for item in raw["torch_cuda_arch_list"]
    ):
        raise ValueError("torch_cuda_arch_list must be a non-empty string array")
    _require_string(raw, "attention_backend")
    _require_string(raw, "started_at")
    _require_string(raw, "finished_at")
    _require_relative_file(raw["license_file"], "license_file")
    return raw


def validate_task_output(output_dir: Path) -> dict[str, Any]:
    if not output_dir.is_dir():
        raise FileNotFoundError(f"output directory does not exist: {output_dir}")
    output_glb = output_dir / "output.glb"
    if not output_glb.is_file():
        raise FileNotFoundError(f"missing canonical GLB: {output_glb}")
    meta = load_run_metadata(output_dir / "meta.json")
    license_file = output_dir / str(meta["license_file"])
    if not license_file.is_file():
        raise FileNotFoundError(f"missing license file declared by meta.json: {license_file}")
    return meta


def _require_string(raw: dict[str, Any], field: str) -> None:
    if not isinstance(raw[field], str) or not raw[field].strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_number(raw: dict[str, Any], field: str) -> None:
    if isinstance(raw[field], bool) or not isinstance(raw[field], int | float):
        raise ValueError(f"{field} must be a number")
    if raw[field] < 0:
        raise ValueError(f"{field} must be non-negative")


def _require_int(raw: dict[str, Any], field: str) -> None:
    if isinstance(raw[field], bool) or not isinstance(raw[field], int):
        raise ValueError(f"{field} must be an integer")
    if raw[field] < 0:
        raise ValueError(f"{field} must be non-negative")


def _require_relative_file(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty relative file path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a relative file path inside the task output directory")
