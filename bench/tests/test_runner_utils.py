import json
import os
import signal
import sys
import time
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


def test_run_with_peak_vram_timeout_kills_waits_and_exposes_log_tail(monkeypatch, tmp_path: Path) -> None:
    events: list[str] = []
    captured_log = None
    captured_options = None

    class FakeProcess:
        pid = 12345
        returncode = None

        def poll(self):
            return None

        def kill(self) -> None:
            events.append("kill")

        def wait(self) -> int:
            events.append("wait")
            self.returncode = -9
            return self.returncode

    def fake_popen(command, *, stdout, stderr, text, **options):
        nonlocal captured_log, captured_options
        captured_log = stdout
        captured_options = options
        stdout.write("final timeout diagnostic\n")
        return FakeProcess()

    monkeypatch.setattr(runner_utils.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_utils, "query_gpu_memory_mib", lambda: 0)
    monkeypatch.setattr(runner_utils.time, "monotonic", lambda: 0.0)
    if os.name == "posix":
        monkeypatch.setattr(
            runner_utils.os,
            "killpg",
            lambda process_group_id, sent_signal: events.append(
                f"killpg:{process_group_id}:{sent_signal}"
            ),
        )
    log_path = tmp_path / "infer.log"
    command = ["python", "inference.py"]

    with pytest.raises(runner_utils.RunnerTimeoutError) as exc_info:
        runner_utils.run_with_peak_vram(
            command,
            timeout_seconds=0,
            timeout_label="unit",
            log_path=log_path,
        )

    if os.name == "posix":
        assert captured_options == {"start_new_session": True}
        assert events == [f"killpg:12345:{signal.SIGKILL}", "wait"]
    else:
        assert os.name == "nt"
        assert captured_options == {"creationflags": runner_utils.subprocess.CREATE_NEW_PROCESS_GROUP}
        assert events == ["kill", "wait"]
    assert captured_log is not None
    assert captured_log.closed
    assert exc_info.value.command == command
    assert exc_info.value.output_tail == "final timeout diagnostic"
    assert log_path.read_text(encoding="utf-8") == "final timeout diagnostic\n"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups are required for this test")
def test_run_with_peak_vram_timeout_stops_grandchild_process_group(monkeypatch, tmp_path: Path) -> None:
    heartbeat_path = tmp_path / "grandchild-heartbeat.txt"
    log_path = tmp_path / "infer.log"
    child_code = (
        "import os, sys, time\n"
        "with open(sys.argv[1], 'a', encoding='utf-8', buffering=1) as handle:\n"
        "    handle.write(f'{os.getpid()}:{os.getpgrp()}\\n')\n"
        "    handle.flush()\n"
        "    while True:\n"
        "        handle.write('tick\\n')\n"
        "        handle.flush()\n"
        "        time.sleep(0.05)\n"
    )
    wrapper_code = (
        "import subprocess, sys, time\n"
        f"child_code = {child_code!r}\n"
        "child = subprocess.Popen([sys.executable, '-c', child_code, sys.argv[1]])\n"
        "print(f'grandchild={child.pid}', flush=True)\n"
        "while True:\n"
        "    time.sleep(1)\n"
    )
    monkeypatch.setattr(runner_utils, "query_gpu_memory_mib", lambda: 0)
    child_process_group_id = None

    try:
        with pytest.raises(runner_utils.RunnerTimeoutError) as exc_info:
            runner_utils.run_with_peak_vram(
                [sys.executable, "-c", wrapper_code, str(heartbeat_path)],
                timeout_seconds=0.6,
                timeout_label="process-group-test",
                log_path=log_path,
            )

        heartbeat_before = heartbeat_path.read_text(encoding="utf-8")
        heartbeat_lines = heartbeat_before.splitlines()
        assert len(heartbeat_lines) >= 2
        _, child_process_group = heartbeat_lines[0].split(":", maxsplit=1)
        child_process_group_id = int(child_process_group)
        assert child_process_group_id != os.getpgrp()
        assert "grandchild=" in exc_info.value.output_tail

        time.sleep(0.3)

        assert heartbeat_path.read_text(encoding="utf-8") == heartbeat_before
    finally:
        if child_process_group_id is not None and child_process_group_id != os.getpgrp():
            try:
                os.killpg(child_process_group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass


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
        output_tail="torch.OutOfMemoryError: CUDA out of memory",
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
    assert failure["error_output_tail"] == "torch.OutOfMemoryError: CUDA out of memory"
    assert (tmp_path / "out" / "infer.log").read_text(encoding="utf-8") == (
        "torch.OutOfMemoryError: CUDA out of memory\n"
    )


def test_select_tasks_runs_only_requested_ids_in_requested_order() -> None:
    tasks = [
        runner_utils.TaskDefinition(id="a", prompt="a", image="a.png", seed=1),
        runner_utils.TaskDefinition(id="b", prompt="b", image="b.png", seed=2),
    ]

    selected = runner_utils.select_tasks(tasks, task_ids=["b", "a"], task_limit=None)

    assert [task.id for task in selected] == ["b", "a"]


@pytest.mark.parametrize(
    ("error", "attempt_index", "max_attempts", "expected"),
    [
        (RuntimeError("retryable"), 0, 2, True),
        (RuntimeError("last attempt"), 1, 2, False),
        (TimeoutError("pod termination requested"), 0, 2, False),
        (
            runner_utils.RunnerTimeoutError(
                command=["python", "inference.py"],
                timeout_label="unit",
                output_tail="timeout diagnostic",
            ),
            0,
            2,
            False,
        ),
    ],
)
def test_should_retry_task_error(
    error: Exception,
    attempt_index: int,
    max_attempts: int,
    expected: bool,
) -> None:
    assert runner_utils.should_retry_task_error(error, attempt_index, max_attempts) is expected


def test_timeout_remains_primary_when_incremental_evidence_upload_fails(monkeypatch, tmp_path: Path) -> None:
    timeout_error = runner_utils.RunnerTimeoutError(command=["python", "infer.py"], timeout_label="unit")
    upload_error = OSError("R2 task upload failed")

    def fail_upload(task_output_dir, task_id, env):
        raise upload_error

    with pytest.raises(runner_utils.RunnerTimeoutError) as caught:
        runner_utils.upload_task_increment_then_raise_timeout(
            tmp_path,
            "task-1",
            {},
            timeout_error,
            upload=fail_upload,
        )

    assert caught.value is timeout_error
    assert caught.value.__cause__ is upload_error


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
