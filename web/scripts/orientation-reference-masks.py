# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy==2.5.1",
#   "opencv-python-headless==5.0.0.93",
# ]
# ///

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version as distribution_version
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
from typing import Any

import cv2
import numpy as np


IMAGE_SIZE = 256
RECT_INSET = 3
GRABCUT_ITERATIONS = 5
MORPHOLOGY_KERNEL_SIZE = 3
MIN_COMPONENT_RATIO = 0.001
MAX_HOLE_RATIO = 0.0005
MIN_FOREGROUND_RATIO = 0.05
MAX_FOREGROUND_RATIO = 0.85
MAX_BORDER_FOREGROUND_RATIO = 0.005
MIN_LARGEST_COMPONENT_RATIO = 0.85
TASK_FIELDS = {"id", "prompt", "image", "seed"}
SAFE_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


class OrientationMaskError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise OrientationMaskError(f"duplicate JSON object key {key!r}")
        value[key] = item
    return value


def _read_tasks(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        raise OrientationMaskError(f"tasks JSON does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise OrientationMaskError(f"invalid tasks JSON {path}: {error}") from error
    if not isinstance(payload, list) or not payload:
        raise OrientationMaskError("tasks JSON must be a non-empty array")

    inventory: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, task in enumerate(payload):
        label = f"tasks[{index}]"
        if not isinstance(task, dict) or set(task) != TASK_FIELDS:
            actual = sorted(task) if isinstance(task, dict) else type(task).__name__
            raise OrientationMaskError(
                f"{label} must contain exactly {sorted(TASK_FIELDS)}, received {actual}"
            )
        task_id = task["id"]
        if (
            not isinstance(task_id, str)
            or not task_id
            or any(character not in SAFE_ID_CHARS for character in task_id)
        ):
            raise OrientationMaskError(f"{label}.id must match [a-z0-9-]+")
        if task_id in seen:
            raise OrientationMaskError(f"duplicate task id {task_id!r}")
        seen.add(task_id)

        image = task["image"]
        expected_image = PurePosixPath("references", f"{task_id}.png")
        if not isinstance(image, str) or PurePosixPath(image) != expected_image:
            raise OrientationMaskError(
                f"{label}.image must be exactly {expected_image.as_posix()!r}"
            )
        inventory.append((task_id, expected_image.name))
    return inventory


def _validate_reference_inventory(references: Path, inventory: list[tuple[str, str]]) -> None:
    if not references.is_dir():
        raise OrientationMaskError(f"references directory does not exist: {references}")
    expected = {filename for _, filename in inventory}
    actual = {
        entry.name
        for entry in references.iterdir()
        if entry.is_file() and entry.suffix.lower() == ".png"
    }
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise OrientationMaskError(
            f"reference inventory mismatch: missing={missing}, unknown={unknown}"
        )
    for filename in sorted(expected):
        path = references / filename
        if not path.is_file():
            raise OrientationMaskError(f"reference must be a regular PNG file: {path}")


def _remove_small_components(mask: np.ndarray) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    cleaned = np.zeros_like(mask)
    total = mask.size
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area / total >= MIN_COMPONENT_RATIO:
            cleaned[labels == label] = 1
    return cleaned


def _fill_small_holes(mask: np.ndarray) -> np.ndarray:
    background = (mask == 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(background, connectivity=8)
    filled = mask.copy()
    total = mask.size
    height, width = mask.shape
    for label in range(1, count):
        component = labels == label
        touches_border = bool(
            component[0, :].any()
            or component[height - 1, :].any()
            or component[:, 0].any()
            or component[:, width - 1].any()
        )
        area = int(stats[label, cv2.CC_STAT_AREA])
        if not touches_border and area / total < MAX_HOLE_RATIO:
            filled[component] = 1
    return filled


def _mask_metrics(mask: np.ndarray) -> dict[str, float]:
    foreground = int(np.count_nonzero(mask))
    foreground_ratio = foreground / mask.size
    border = np.concatenate((mask[0, :], mask[-1, :], mask[1:-1, 0], mask[1:-1, -1]))
    border_foreground_ratio = int(np.count_nonzero(border)) / border.size

    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    largest = max((int(stats[label, cv2.CC_STAT_AREA]) for label in range(1, count)), default=0)
    largest_component_ratio = largest / foreground if foreground else 0.0
    return {
        "foregroundRatio": foreground_ratio,
        "borderForegroundRatio": border_foreground_ratio,
        "largestComponentRatio": largest_component_ratio,
    }


def _assert_qa(task_id: str, metrics: dict[str, float]) -> None:
    foreground = metrics["foregroundRatio"]
    border = metrics["borderForegroundRatio"]
    largest = metrics["largestComponentRatio"]
    failures: list[str] = []
    if not MIN_FOREGROUND_RATIO <= foreground <= MAX_FOREGROUND_RATIO:
        failures.append(
            f"foregroundRatio={foreground:.6f} outside [{MIN_FOREGROUND_RATIO}, {MAX_FOREGROUND_RATIO}]"
        )
    if not border < MAX_BORDER_FOREGROUND_RATIO:
        failures.append(
            f"borderForegroundRatio={border:.6f} must be < {MAX_BORDER_FOREGROUND_RATIO}"
        )
    if not largest >= MIN_LARGEST_COMPONENT_RATIO:
        failures.append(
            f"largestComponentRatio={largest:.6f} must be >= {MIN_LARGEST_COMPONENT_RATIO}"
        )
    if failures:
        raise OrientationMaskError(f"reference mask QA failed for {task_id}: {'; '.join(failures)}")


def _generate_mask(source_path: Path) -> tuple[np.ndarray, dict[str, float]]:
    source_bytes = source_path.read_bytes()
    encoded = np.frombuffer(source_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise OrientationMaskError(f"reference is not a decodable PNG: {source_path}")
    if image.shape[0] < 2 * RECT_INSET + 1 or image.shape[1] < 2 * RECT_INSET + 1:
        raise OrientationMaskError(f"reference is too small for GrabCut rect inset {RECT_INSET}: {source_path}")
    resized = cv2.resize(image, (IMAGE_SIZE, IMAGE_SIZE), interpolation=cv2.INTER_AREA)

    grabcut_mask = np.zeros((IMAGE_SIZE, IMAGE_SIZE), dtype=np.uint8)
    background_model = np.zeros((1, 65), dtype=np.float64)
    foreground_model = np.zeros((1, 65), dtype=np.float64)
    rect = (
        RECT_INSET,
        RECT_INSET,
        IMAGE_SIZE - 2 * RECT_INSET,
        IMAGE_SIZE - 2 * RECT_INSET,
    )
    cv2.grabCut(
        resized,
        grabcut_mask,
        rect,
        background_model,
        foreground_model,
        GRABCUT_ITERATIONS,
        cv2.GC_INIT_WITH_RECT,
    )
    mask = np.where(
        (grabcut_mask == cv2.GC_FGD) | (grabcut_mask == cv2.GC_PR_FGD), 1, 0
    ).astype(np.uint8)
    kernel = np.ones((MORPHOLOGY_KERNEL_SIZE, MORPHOLOGY_KERNEL_SIZE), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = _remove_small_components(mask)
    mask = _fill_small_holes(mask)
    metrics = _mask_metrics(mask)
    return mask * 255, metrics


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _encode_png(mask: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", mask, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    if not ok:
        raise OrientationMaskError("OpenCV failed to encode a binary PNG mask")
    return encoded.tobytes()


def _recipe() -> dict[str, Any]:
    return {
        "version": 1,
        "imageSize": [IMAGE_SIZE, IMAGE_SIZE],
        "grabCut": {"rectInset": RECT_INSET, "iterations": GRABCUT_ITERATIONS},
        "morphology": {
            "kernelSize": MORPHOLOGY_KERNEL_SIZE,
            "operations": ["close", "open"],
        },
        "removeComponentBelowRatio": MIN_COMPONENT_RATIO,
        "fillInteriorHoleBelowRatio": MAX_HOLE_RATIO,
        "qa": {
            "foregroundRatio": [MIN_FOREGROUND_RATIO, MAX_FOREGROUND_RATIO],
            "borderForegroundRatioExclusiveMax": MAX_BORDER_FOREGROUND_RATIO,
            "largestComponentRatioMin": MIN_LARGEST_COMPONENT_RATIO,
        },
    }


def generate_reference_masks(
    *, tasks_path: Path, references: Path, output: Path, report_path: Path
) -> dict[str, Any]:
    tasks_path = tasks_path.resolve()
    references = references.resolve()
    output = output.resolve()
    report_path = report_path.resolve()
    if output == references or references in output.parents:
        raise OrientationMaskError("output must not be the references directory or its descendant")
    if report_path == output or output in report_path.parents:
        raise OrientationMaskError("report must not be inside the mask output directory")

    inventory = _read_tasks(tasks_path)
    _validate_reference_inventory(references, inventory)
    expected_output = {f"{task_id}.png" for task_id, _ in inventory}
    if output.exists():
        if not output.is_dir():
            raise OrientationMaskError(f"output exists but is not a directory: {output}")
        unknown_output = sorted(entry.name for entry in output.iterdir() if entry.name not in expected_output)
        if unknown_output:
            raise OrientationMaskError(f"mask output contains unknown files: {unknown_output}")
    if report_path.exists() and not report_path.is_file():
        raise OrientationMaskError(f"report exists but is not a regular file: {report_path}")

    staging_parent = output.parent
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="orientation-masks-", dir=staging_parent))
    records: dict[str, Any] = {}
    try:
        for task_id, filename in inventory:
            source_path = references / filename
            source_bytes = source_path.read_bytes()
            mask, metrics = _generate_mask(source_path)
            _assert_qa(task_id, metrics)
            mask_bytes = _encode_png(mask)
            (staging / f"{task_id}.png").write_bytes(mask_bytes)
            records[task_id] = {
                "sourceFile": filename,
                "maskFile": f"{task_id}.png",
                "sourceSha256": _sha256(source_bytes),
                "maskSha256": _sha256(mask_bytes),
                **metrics,
            }

        report = {
            "schemaVersion": 1,
            "recipe": _recipe(),
            "runtime": {
                "opencvVersion": distribution_version("opencv-python-headless"),
                "numpyVersion": np.__version__,
            },
            "tasks": records,
        }
        report_bytes = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        output.mkdir(parents=True, exist_ok=True)
        for filename in sorted(expected_output):
            os.replace(staging / filename, output / filename)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=report_path.parent, prefix=f".{report_path.name}."
        ) as temporary_report:
            temporary_report.write(report_bytes)
            temporary_report_path = Path(temporary_report.name)
        os.replace(temporary_report_path, report_path)
        return report
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate strict 256x256 reference foreground masks")
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    generate_reference_masks(
        tasks_path=args.tasks,
        references=args.references,
        output=args.output,
        report_path=args.report,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OrientationMaskError as error:
        print(f"orientation reference masks failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
