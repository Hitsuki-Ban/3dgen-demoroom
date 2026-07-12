# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy==2.5.1",
#   "opencv-python-headless==5.0.0.93",
# ]
# ///

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np


SCRIPT = Path(__file__).with_name("orientation-reference-masks.py")
SPEC = importlib.util.spec_from_file_location("orientation_reference_masks", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MASKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MASKS)


def write_tasks(path: Path, task_ids: list[str]) -> None:
    payload = [
        {
            "id": task_id,
            "prompt": f"Synthetic {task_id}",
            "image": f"references/{task_id}.png",
            "seed": 1,
        }
        for task_id in task_ids
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def synthetic_reference(path: Path) -> np.ndarray:
    size = 512
    x = np.linspace(218, 242, size, dtype=np.float32)
    background = np.tile(x, (size, 1))
    image = np.dstack((background, background, background)).astype(np.uint8)
    expected = np.zeros((size, size), dtype=np.uint8)
    polygon = np.array([[90, 130], [360, 105], [430, 220], [310, 245], [300, 410], [140, 380]])
    cv2.fillPoly(image, [polygon], (38, 72, 168))
    cv2.fillPoly(expected, [polygon], 255)
    cv2.circle(image, (125, 175), 42, (25, 145, 205), thickness=-1)
    cv2.circle(expected, (125, 175), 42, 255, thickness=-1)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    path.write_bytes(encoded.tobytes())
    return cv2.resize(expected, (256, 256), interpolation=cv2.INTER_NEAREST)


def flat_reference(path: Path) -> None:
    image = np.full((512, 512, 3), 230, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    path.write_bytes(encoded.tobytes())


class OrientationReferenceMasksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tasks = self.root / "tasks.json"
        self.references = self.root / "references"
        self.output = self.root / "masks"
        self.report = self.root / "report.json"
        self.references.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_generates_binary_mask_and_complete_qa_report(self) -> None:
        write_tasks(self.tasks, ["asymmetric-object"])
        expected = synthetic_reference(self.references / "asymmetric-object.png")
        report = MASKS.generate_reference_masks(
            tasks_path=self.tasks,
            references=self.references,
            output=self.output,
            report_path=self.report,
        )

        mask = cv2.imread(str(self.output / "asymmetric-object.png"), cv2.IMREAD_GRAYSCALE)
        self.assertIsNotNone(mask)
        self.assertEqual(mask.shape, (256, 256))
        self.assertEqual(set(np.unique(mask)), {0, 255})
        intersection = np.count_nonzero((mask > 0) & (expected > 0))
        union = np.count_nonzero((mask > 0) | (expected > 0))
        self.assertGreater(intersection / union, 0.97)

        persisted = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(persisted, report)
        self.assertEqual(report["schemaVersion"], 1)
        self.assertEqual(report["recipe"]["grabCut"], {"rectInset": 3, "iterations": 5})
        self.assertEqual(report["recipe"]["morphology"]["operations"], ["close", "open"])
        self.assertEqual(report["runtime"]["opencvVersion"], "5.0.0.93")
        self.assertEqual(report["runtime"]["numpyVersion"], "2.5.1")
        record = report["tasks"]["asymmetric-object"]
        self.assertEqual(len(record["sourceSha256"]), 64)
        self.assertEqual(len(record["maskSha256"]), 64)
        self.assertGreaterEqual(record["foregroundRatio"], 0.08)
        self.assertLessEqual(record["foregroundRatio"], 0.85)
        self.assertLess(record["borderForegroundRatio"], 0.005)
        self.assertGreaterEqual(record["largestComponentRatio"], 0.85)

    def test_cli_requires_all_four_paths(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--tasks", str(self.tasks)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--references", result.stderr)
        self.assertIn("--output", result.stderr)
        self.assertIn("--report", result.stderr)

    def test_missing_tasks_and_reference_files_fail(self) -> None:
        with self.assertRaisesRegex(MASKS.OrientationMaskError, "tasks JSON does not exist"):
            MASKS.generate_reference_masks(
                tasks_path=self.tasks,
                references=self.references,
                output=self.output,
                report_path=self.report,
            )

        write_tasks(self.tasks, ["missing"])
        with self.assertRaisesRegex(MASKS.OrientationMaskError, "missing=.*missing.png"):
            MASKS.generate_reference_masks(
                tasks_path=self.tasks,
                references=self.references,
                output=self.output,
                report_path=self.report,
            )

    def test_extra_reference_png_fails_exact_inventory(self) -> None:
        write_tasks(self.tasks, ["known"])
        synthetic_reference(self.references / "known.png")
        synthetic_reference(self.references / "extra.png")
        with self.assertRaisesRegex(MASKS.OrientationMaskError, "unknown=.*extra.png"):
            MASKS.generate_reference_masks(
                tasks_path=self.tasks,
                references=self.references,
                output=self.output,
                report_path=self.report,
            )

    def test_failed_qa_is_nonzero_and_publishes_nothing(self) -> None:
        write_tasks(self.tasks, ["flat"])
        flat_reference(self.references / "flat.png")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--tasks",
                str(self.tasks),
                "--references",
                str(self.references),
                "--output",
                str(self.output),
                "--report",
                str(self.report),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("reference mask QA failed for flat", result.stderr)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.report.exists())

    def test_duplicate_json_keys_and_schema_drift_fail(self) -> None:
        self.tasks.write_text(
            '[{"id":"duplicate","id":"duplicate","prompt":"x","image":"references/duplicate.png","seed":1}]',
            encoding="utf-8",
        )
        synthetic_reference(self.references / "duplicate.png")
        with self.assertRaisesRegex(MASKS.OrientationMaskError, "duplicate JSON object key 'id'"):
            MASKS.generate_reference_masks(
                tasks_path=self.tasks,
                references=self.references,
                output=self.output,
                report_path=self.report,
            )

        self.tasks.write_text(
            '[{"id":"duplicate","prompt":"x","image":"references/duplicate.png","seed":1,"extra":true}]',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MASKS.OrientationMaskError, "must contain exactly"):
            MASKS.generate_reference_masks(
                tasks_path=self.tasks,
                references=self.references,
                output=self.output,
                report_path=self.report,
            )


if __name__ == "__main__":
    unittest.main()
