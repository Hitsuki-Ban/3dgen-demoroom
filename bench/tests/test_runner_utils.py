import json
import sys
from pathlib import Path

import pytest

from bench_harness.tasks import TaskDefinition


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_PATH = REPO_ROOT / "models" / "common"
sys.path.insert(0, str(COMMON_PATH))

import runner_utils  # noqa: E402


def test_run_with_peak_vram_records_subprocess_log_tail(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner_utils, "query_gpu_memory_mib", lambda: 0)
    log_path = tmp_path / "infer.log"

    with pytest.raises(runner_utils.RunnerSubprocessError) as exc_info:
        runner_utils.run_with_peak_vram(
            [
                sys.executable,
                "-c",
                "import sys; print('stdout line'); print('stderr line', file=sys.stderr); sys.exit(7)",
            ],
            timeout_seconds=5,
            timeout_label="unit",
            log_path=log_path,
        )

    assert exc_info.value.returncode == 7
    assert "stdout line" in exc_info.value.output_tail
    assert "stderr line" in exc_info.value.output_tail
    assert "stdout line" in log_path.read_text(encoding="utf-8")


def test_write_task_failure_includes_subprocess_diagnostics(tmp_path: Path) -> None:
    task = TaskDefinition(
        id="cartoon-apple",
        prompt="A stylized cartoon red apple",
        image="references/cartoon-apple.png",
        seed=20260708,
    )
    error = runner_utils.RunnerSubprocessError(
        returncode=7,
        command=["python", "inference.py"],
        output_tail="ModuleNotFoundError: No module named 'onnxruntime'",
    )

    runner_utils.write_task_failure(
        task=task,
        task_output_dir=tmp_path / "out",
        model_id="3dtopia-xl",
        model_git_commit="commit",
        weights_revision="revision",
        parameters={"seed": 20260708},
        error=error,
        retry_count=1,
        started_at="2026-07-09T00:00:00Z",
        finished_at="2026-07-09T00:00:02Z",
    )

    failure = json.loads((tmp_path / "out" / "failure.json").read_text(encoding="utf-8"))
    assert failure["error_type"] == "RunnerSubprocessError"
    assert failure["error_returncode"] == 7
    assert failure["error_output_tail"] == "ModuleNotFoundError: No module named 'onnxruntime'"


def test_select_tasks_runs_only_requested_ids_in_requested_order() -> None:
    tasks = [
        runner_utils.TaskDefinition(id="a", prompt="a", image="a.png", seed=1),
        runner_utils.TaskDefinition(id="b", prompt="b", image="b.png", seed=2),
    ]

    selected = runner_utils.select_tasks(tasks, task_ids=["b", "a"], task_limit=None)

    assert [task.id for task in selected] == ["b", "a"]


@pytest.mark.parametrize(
    ("task_ids", "task_limit", "message"),
    [
        (["missing"], None, "unknown --task-id"),
        (["a"], 1, "mutually exclusive"),
        (["a", "a"], None, "duplicates"),
        ([""], None, "must not be empty"),
        ([], 0, "positive integer"),
    ],
)
def test_select_tasks_rejects_invalid_selection(
    task_ids: list[str],
    task_limit: int | None,
    message: str,
) -> None:
    tasks = [runner_utils.TaskDefinition(id="a", prompt="a", image="a.png", seed=1)]

    with pytest.raises(ValueError, match=message):
        runner_utils.select_tasks(tasks, task_ids=task_ids, task_limit=task_limit)
