from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from bench_harness.meta import validate_failed_task_output, validate_task_output
from bench_harness.tasks import load_tasks


def load_model_ids(path: Path) -> tuple[str, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path} must contain a non-empty JSON array")
    if not all(isinstance(item, str) and item and _is_safe_id(item) for item in raw):
        raise ValueError(f"{path} model IDs must match [a-z0-9-]+")
    if len(raw) != len(set(raw)):
        raise ValueError(f"{path} contains duplicate model IDs")
    return tuple(raw)


def parse_expected_failures(values: Iterable[str]) -> frozenset[tuple[str, str]]:
    parsed: set[tuple[str, str]] = set()
    for value in values:
        parts = value.split("/")
        if len(parts) != 2 or not all(parts) or not all(_is_safe_id(part) for part in parts):
            raise ValueError(f"expected failure must be MODEL_ID/TASK_ID, received: {value}")
        cell = (parts[0], parts[1])
        if cell in parsed:
            raise ValueError(f"duplicate expected failure: {value}")
        parsed.add(cell)
    return frozenset(parsed)


def build_site_manifest(
    *,
    runs_root: Path,
    tasks_json: Path,
    model_registry: Path,
    output_path: Path,
    expected_failures: frozenset[tuple[str, str]],
    generated_at: str,
    allow_partial: bool,
) -> dict[str, Any]:
    if not runs_root.is_dir():
        raise FileNotFoundError(f"site-data root does not exist: {runs_root}")

    model_ids = load_model_ids(model_registry)
    task_ids = tuple(task.id for task in load_tasks(tasks_json))
    known_models = set(model_ids)
    known_tasks = set(task_ids)
    unknown_expected = expected_failures - {(model_id, task_id) for model_id in model_ids for task_id in task_ids}
    if unknown_expected:
        formatted = ", ".join(f"{model}/{task}" for model, task in sorted(unknown_expected))
        raise ValueError(f"expected failure references unknown cell(s): {formatted}")

    _validate_directory_members(runs_root, known_models, "model")
    entries: list[dict[str, Any]] = []
    present_cells: set[tuple[str, str]] = set()
    actual_failures: set[tuple[str, str]] = set()

    for model_id in model_ids:
        model_dir = runs_root / model_id
        if not model_dir.is_dir():
            if allow_partial:
                continue
            raise ValueError(f"missing site-data model directory: {model_id}")
        _validate_directory_members(model_dir, known_tasks, f"task under {model_id}")

        for task_id in task_ids:
            task_dir = model_dir / task_id
            if not task_dir.is_dir():
                if allow_partial:
                    continue
                raise ValueError(f"missing site-data cell: {model_id}/{task_id}")
            present_cells.add((model_id, task_id))
            entries.append(_load_cell(task_dir, model_id, task_id, actual_failures))

    if not entries:
        raise ValueError("site-data snapshot contains no cells")

    expected_present_failures = set(expected_failures) & present_cells
    if actual_failures != expected_present_failures:
        expected = _format_cells(expected_present_failures)
        actual = _format_cells(actual_failures)
        raise ValueError(f"failure matrix mismatch: expected [{expected}], received [{actual}]")

    manifest = {"generatedAt": generated_at, "partial": allow_partial, "entries": entries}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def _load_cell(
    task_dir: Path,
    model_id: str,
    task_id: str,
    actual_failures: set[tuple[str, str]],
) -> dict[str, Any]:
    meta_path = task_dir / "meta.json"
    glb_path = task_dir / "output.glb"
    failure_path = task_dir / "failure.json"
    has_meta = meta_path.is_file()
    has_glb = glb_path.is_file()
    has_failure = failure_path.is_file()
    cell = f"{model_id}/{task_id}"

    if has_failure:
        if has_meta or has_glb:
            raise ValueError(f"site-data cell must be exclusively success or failed: {cell}")
        failure = validate_failed_task_output(task_dir)
        _validate_payload_ids(failure, model_id, task_id, failure_path)
        actual_failures.add((model_id, task_id))
        return {
            "status": "failed",
            "taskId": task_id,
            "modelId": model_id,
            "failure": {
                "errorType": failure["error_type"],
                "retryCount": failure["retry_count"],
                "startedAt": failure["started_at"],
                "finishedAt": failure["finished_at"],
            },
        }

    if not has_meta or not has_glb:
        raise ValueError(
            f"incomplete success cell {cell}: meta.json={has_meta} output.glb={has_glb} failure.json={has_failure}"
        )
    meta = validate_task_output(task_dir)
    _validate_payload_ids(meta, model_id, task_id, meta_path)
    return {
        "status": "success",
        "taskId": task_id,
        "modelId": model_id,
        "glbUrl": f"/run-assets/{model_id}/{task_id}/output.glb",
        "glbSizeBytes": glb_path.stat().st_size,
        "metrics": {
            "wallClockSeconds": meta["wall_clock_seconds"],
            "peakVramBytes": meta["peak_vram_bytes"],
            "gpuName": meta["gpu_name"],
        },
        "meta": meta,
    }


def _validate_directory_members(root: Path, expected: set[str], label: str) -> None:
    for entry in root.iterdir():
        if not entry.is_dir():
            raise ValueError(f"unexpected file in {root}: {entry.name}")
        if entry.name not in expected:
            raise ValueError(f"unknown {label} directory: {entry.name}")


def _validate_payload_ids(payload: dict[str, Any], model_id: str, task_id: str, path: Path) -> None:
    if payload["model_id"] != model_id or payload["task_id"] != task_id:
        raise ValueError(
            f"{path} ID mismatch: expected {model_id}/{task_id}, "
            f"received {payload['model_id']}/{payload['task_id']}"
        )


def _is_safe_id(value: str) -> bool:
    return all(character.isascii() and (character.islower() or character.isdigit() or character == "-") for character in value)


def _format_cells(cells: Iterable[tuple[str, str]]) -> str:
    return ", ".join(f"{model}/{task}" for model, task in sorted(cells))
