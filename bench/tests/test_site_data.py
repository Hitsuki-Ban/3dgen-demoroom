import json
import shutil
import struct
from pathlib import Path

import pytest

from bench_harness.site_data import build_site_manifest, load_model_ids, parse_expected_failures


MODELS = ("model-a", "model-b")
TASKS = ("task-a", "task-b")
FAILED_CELL = ("model-b", "task-b")


def _valid_meta(model_id: str, task_id: str) -> dict[str, object]:
    return {
        "task_id": task_id,
        "model_id": model_id,
        "model_git_commit": "commit",
        "weights_revision": "revision",
        "gpu_name": "Test GPU",
        "wall_clock_seconds": 1.5,
        "peak_vram_bytes": 1024,
        "seed": 1,
        "parameters": {},
        "retry_count": 0,
        "torch_version": "2.7.1",
        "torch_cuda_version": "12.8",
        "torch_cuda_arch_list": ["sm_89"],
        "attention_backend": "sdpa",
        "started_at": "2026-07-08T00:00:00Z",
        "finished_at": "2026-07-08T00:00:02Z",
        "license_file": "LICENSE",
    }


def _valid_failure(model_id: str, task_id: str) -> dict[str, object]:
    return {
        "status": "failed",
        "task_id": task_id,
        "model_id": model_id,
        "model_git_commit": "commit",
        "weights_revision": "revision",
        "seed": 1,
        "parameters": {},
        "retry_count": 1,
        "error_type": "RuntimeError",
        "error_message": "failed",
        "started_at": "2026-07-08T00:00:00Z",
        "finished_at": "2026-07-08T00:00:02Z",
    }


def _write_success(cell_dir: Path, model_id: str, task_id: str) -> None:
    cell_dir.mkdir(parents=True)
    json_chunk = b'{"asset":{"version":"2.0"}}'
    json_chunk += b" " * (-len(json_chunk) % 4)
    total_size = 12 + 8 + len(json_chunk)
    (cell_dir / "output.glb").write_bytes(
        struct.pack("<4sII", b"glTF", 2, total_size)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
    )
    (cell_dir / "LICENSE").write_text("license\n", encoding="utf-8")
    (cell_dir / "meta.json").write_text(json.dumps(_valid_meta(model_id, task_id)), encoding="utf-8")


def _write_failure(cell_dir: Path, model_id: str, task_id: str) -> None:
    cell_dir.mkdir(parents=True)
    (cell_dir / "failure.json").write_text(
        json.dumps(_valid_failure(model_id, task_id)), encoding="utf-8"
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    runs_root = tmp_path / "site-data"
    tasks_json = tmp_path / "tasks.json"
    model_registry = tmp_path / "models.json"
    output_path = tmp_path / "manifest.json"
    tasks_json.write_text(
        json.dumps(
            [
                {"id": task_id, "prompt": task_id, "image": f"references/{task_id}.png", "seed": 1}
                for task_id in TASKS
            ]
        ),
        encoding="utf-8",
    )
    model_registry.write_text(json.dumps(MODELS), encoding="utf-8")
    for model_id in MODELS:
        for task_id in TASKS:
            cell_dir = runs_root / model_id / task_id
            if (model_id, task_id) == FAILED_CELL:
                _write_failure(cell_dir, model_id, task_id)
            else:
                _write_success(cell_dir, model_id, task_id)
    return runs_root, tasks_json, model_registry, output_path


def _build(tmp_path: Path) -> dict[str, object]:
    runs_root, tasks_json, model_registry, output_path = _fixture(tmp_path)
    return build_site_manifest(
        runs_root=runs_root,
        tasks_json=tasks_json,
        model_registry=model_registry,
        output_path=output_path,
        expected_failures=frozenset({FAILED_CELL}),
        generated_at="2026-07-11T00:00:00Z",
        allow_partial=False,
    )


def test_build_site_manifest_emits_complete_stable_union(tmp_path: Path) -> None:
    manifest = _build(tmp_path)

    assert manifest["partial"] is False
    entries = manifest["entries"]
    assert [(entry["modelId"], entry["taskId"]) for entry in entries] == [
        ("model-a", "task-a"),
        ("model-a", "task-b"),
        ("model-b", "task-a"),
        ("model-b", "task-b"),
    ]
    assert [entry["status"] for entry in entries] == ["success", "success", "success", "failed"]
    assert entries[-1]["failure"] == {
        "errorType": "RuntimeError",
        "retryCount": 1,
        "startedAt": "2026-07-08T00:00:00Z",
        "finishedAt": "2026-07-08T00:00:02Z",
    }


def test_build_site_manifest_rejects_missing_cell(tmp_path: Path) -> None:
    runs_root, tasks_json, model_registry, output_path = _fixture(tmp_path)
    shutil.rmtree(runs_root / "model-a" / "task-a")

    with pytest.raises(ValueError, match="missing site-data cell: model-a/task-a"):
        build_site_manifest(
            runs_root=runs_root,
            tasks_json=tasks_json,
            model_registry=model_registry,
            output_path=output_path,
            expected_failures=frozenset({FAILED_CELL}),
            generated_at="2026-07-11T00:00:00Z",
            allow_partial=False,
        )


def test_build_site_manifest_allows_explicit_valid_partial_snapshot(tmp_path: Path) -> None:
    runs_root, tasks_json, model_registry, output_path = _fixture(tmp_path)
    shutil.rmtree(runs_root / "model-a" / "task-a")
    shutil.rmtree(runs_root / "model-b")

    manifest = build_site_manifest(
        runs_root=runs_root,
        tasks_json=tasks_json,
        model_registry=model_registry,
        output_path=output_path,
        expected_failures=frozenset({FAILED_CELL}),
        generated_at="2026-07-11T00:00:00Z",
        allow_partial=True,
    )

    assert manifest["partial"] is True
    assert [(entry["modelId"], entry["taskId"]) for entry in manifest["entries"]] == [
        ("model-a", "task-b")
    ]


def test_build_site_manifest_partial_mode_rejects_empty_snapshot(tmp_path: Path) -> None:
    runs_root, tasks_json, model_registry, output_path = _fixture(tmp_path)
    shutil.rmtree(runs_root)
    runs_root.mkdir()

    with pytest.raises(ValueError, match="contains no cells"):
        build_site_manifest(
            runs_root=runs_root,
            tasks_json=tasks_json,
            model_registry=model_registry,
            output_path=output_path,
            expected_failures=frozenset({FAILED_CELL}),
            generated_at="2026-07-11T00:00:00Z",
            allow_partial=True,
        )


def test_build_site_manifest_partial_mode_rejects_present_failure_mismatch(tmp_path: Path) -> None:
    runs_root, tasks_json, model_registry, output_path = _fixture(tmp_path)

    with pytest.raises(ValueError, match="failure matrix mismatch"):
        build_site_manifest(
            runs_root=runs_root,
            tasks_json=tasks_json,
            model_registry=model_registry,
            output_path=output_path,
            expected_failures=frozenset(),
            generated_at="2026-07-11T00:00:00Z",
            allow_partial=True,
        )


def test_build_site_manifest_rejects_unknown_model(tmp_path: Path) -> None:
    runs_root, tasks_json, model_registry, output_path = _fixture(tmp_path)
    (runs_root / "unknown-model").mkdir()

    with pytest.raises(ValueError, match="unknown model directory: unknown-model"):
        build_site_manifest(
            runs_root=runs_root,
            tasks_json=tasks_json,
            model_registry=model_registry,
            output_path=output_path,
            expected_failures=frozenset({FAILED_CELL}),
            generated_at="2026-07-11T00:00:00Z",
            allow_partial=False,
        )


def test_build_site_manifest_rejects_success_and_failure_in_same_cell(tmp_path: Path) -> None:
    runs_root, tasks_json, model_registry, output_path = _fixture(tmp_path)
    failure_cell = runs_root / "model-b" / "task-b"
    _write_success(tmp_path / "success-copy", "model-b", "task-b")
    shutil.copy2(tmp_path / "success-copy" / "output.glb", failure_cell / "output.glb")
    (failure_cell / "meta.json").write_text(
        json.dumps(_valid_meta("model-b", "task-b")), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="exclusively success or failed"):
        build_site_manifest(
            runs_root=runs_root,
            tasks_json=tasks_json,
            model_registry=model_registry,
            output_path=output_path,
            expected_failures=frozenset({FAILED_CELL}),
            generated_at="2026-07-11T00:00:00Z",
            allow_partial=False,
        )


def test_build_site_manifest_rejects_payload_id_mismatch(tmp_path: Path) -> None:
    runs_root, tasks_json, model_registry, output_path = _fixture(tmp_path)
    meta_path = runs_root / "model-a" / "task-a" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["task_id"] = "task-b"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(ValueError, match="ID mismatch"):
        build_site_manifest(
            runs_root=runs_root,
            tasks_json=tasks_json,
            model_registry=model_registry,
            output_path=output_path,
            expected_failures=frozenset({FAILED_CELL}),
            generated_at="2026-07-11T00:00:00Z",
            allow_partial=False,
        )


def test_build_site_manifest_rejects_failure_matrix_mismatch(tmp_path: Path) -> None:
    runs_root, tasks_json, model_registry, output_path = _fixture(tmp_path)

    with pytest.raises(ValueError, match="failure matrix mismatch"):
        build_site_manifest(
            runs_root=runs_root,
            tasks_json=tasks_json,
            model_registry=model_registry,
            output_path=output_path,
            expected_failures=frozenset(),
            generated_at="2026-07-11T00:00:00Z",
            allow_partial=False,
        )


def test_repository_registry_defines_275_unique_cells() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    model_ids = load_model_ids(repo_root / "web" / "src" / "data" / "model-registry.json")
    task_ids = tuple(item["id"] for item in json.loads((repo_root / "tasks" / "tasks.json").read_text()))

    assert len(model_ids) == len(set(model_ids)) == 11
    assert len(task_ids) == len(set(task_ids)) == 25
    assert len({(model_id, task_id) for model_id in model_ids for task_id in task_ids}) == 275


def test_repository_snapshot_contract_is_274_successes_and_one_failure(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    tasks_json = repo_root / "tasks" / "tasks.json"
    model_registry = repo_root / "web" / "src" / "data" / "model-registry.json"
    model_ids = load_model_ids(model_registry)
    task_ids = tuple(item["id"] for item in json.loads(tasks_json.read_text(encoding="utf-8")))
    failure_cell = ("partcrafter", "chrome-espresso-machine")
    runs_root = tmp_path / "site-data"

    for model_id in model_ids:
        for task_id in task_ids:
            cell_dir = runs_root / model_id / task_id
            if (model_id, task_id) == failure_cell:
                _write_failure(cell_dir, model_id, task_id)
            else:
                _write_success(cell_dir, model_id, task_id)

    manifest = build_site_manifest(
        runs_root=runs_root,
        tasks_json=tasks_json,
        model_registry=model_registry,
        output_path=tmp_path / "manifest.json",
        expected_failures=frozenset({failure_cell}),
        generated_at="2026-07-11T00:00:00Z",
        allow_partial=False,
    )

    assert len(manifest["entries"]) == 275
    assert sum(entry["status"] == "success" for entry in manifest["entries"]) == 274
    assert [
        (entry["modelId"], entry["taskId"])
        for entry in manifest["entries"]
        if entry["status"] == "failed"
    ] == [failure_cell]


def test_parse_expected_failures_rejects_invalid_or_duplicate_cells() -> None:
    assert parse_expected_failures(["model-a/task-a"]) == frozenset({("model-a", "task-a")})
    with pytest.raises(ValueError, match="MODEL_ID/TASK_ID"):
        parse_expected_failures(["model-a"])
    with pytest.raises(ValueError, match="duplicate expected failure"):
        parse_expected_failures(["model-a/task-a", "model-a/task-a"])
