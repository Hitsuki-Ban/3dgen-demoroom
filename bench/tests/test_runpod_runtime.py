import io
import json
import sys
from pathlib import Path

import pytest

from bench_harness.runpod_runtime import CloudRuntimeConfig, run_cloud_runtime, run_model_subprocess


def make_config(tmp_path: Path) -> CloudRuntimeConfig:
    return CloudRuntimeConfig(
        model_id="triposg",
        output_root=tmp_path / "output",
        s3_target="s3://3dgen-runs/runs/triposg/test",
        runner_command=("python3", "/opt/3dgen-runner/triposg_runner.py"),
    )


def make_env() -> dict[str, str]:
    return {
        "RUNPOD_POD_ID": "pod-123",
        "RUNPOD_API_KEY": "token",
        "RUNPOD_LIFECYCLE_TOKEN": "handoff-token",
        "RUNPOD_HANDOFF_TIMEOUT_SECONDS": "600",
        "R2_ENDPOINT": "https://example.r2.cloudflarestorage.com",
        "R2_ACCESS_KEY_ID": "access-key",
        "R2_SECRET_ACCESS_KEY": "secret-key",
    }


def accept_handoff(target, pod_id, lifecycle_token, env, timeout_seconds, poll_seconds) -> bool:
    assert lifecycle_token == "handoff-token"
    assert timeout_seconds == 600
    assert poll_seconds == 1
    return True


def claim_cleanup(target, pod_id, lifecycle_token, env) -> bool:
    return True


def upload_status(status_path, target, env) -> None:
    assert status_path.is_file()


def test_timeout_evidence_and_final_status_are_persisted_before_termination(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    events: list[str] = []
    upload_count = 0

    def start_ssh() -> int:
        events.append("ssh")
        return 0

    def wait_for_handoff(target, pod_id, lifecycle_token, env, timeout_seconds, poll_seconds) -> bool:
        events.append("handoff")
        return True

    def run_model(command, log_path) -> int:
        assert tuple(command) == config.runner_command
        events.append("failure_write")
        task_dir = config.output_root / "task-1"
        task_dir.mkdir(parents=True)
        (task_dir / "failure.json").write_text('{"status":"failed"}\n', encoding="utf-8")
        log_path.write_text("MAX_RUNTIME_MIN exceeded\n", encoding="utf-8")
        events.append("task_upload")
        return 124

    def upload_output(source_dir, target, env) -> None:
        nonlocal upload_count
        upload_count += 1
        if upload_count == 1:
            assert (source_dir / "runpod-startup.json").is_file()
            assert not (source_dir / "runpod-status.json").exists()
            events.append("startup_upload")
        else:
            assert (source_dir / "task-1" / "failure.json").is_file()
            status = json.loads((source_dir / "runpod-status.json").read_text(encoding="utf-8"))
            assert status["status"] == "finalizing"
            assert status["outcome"] == "failed"
            assert status["runner_output_tail"] == "MAX_RUNTIME_MIN exceeded"
            events.append("final_upload")

    def upload_final_status(status_path, target, env) -> None:
        events.append("status_upload")

    def claim_runtime_cleanup(target, pod_id, lifecycle_token, env) -> bool:
        events.append("claim_cleanup")
        return True

    def terminate_pod(pod_id: str, api_key: str) -> None:
        assert (config.output_root / "task-1" / "failure.json").is_file()
        assert (config.output_root / "runpod-status.json").is_file()
        events.append("terminate")

    exit_code = run_cloud_runtime(
        config,
        env=make_env(),
        start_ssh=start_ssh,
        run_model=run_model,
        upload_output=upload_output,
        upload_status=upload_final_status,
        wait_for_handoff=wait_for_handoff,
        claim_cleanup=claim_runtime_cleanup,
        terminate_pod=terminate_pod,
        now=iter(("2026-07-11T00:00:00Z", "2026-07-11T00:01:00Z", "2026-07-11T00:01:01Z")).__next__,
    )

    assert exit_code == 124
    assert events == [
        "ssh",
        "startup_upload",
        "handoff",
        "failure_write",
        "task_upload",
        "final_upload",
        "status_upload",
        "claim_cleanup",
        "terminate",
    ]


def test_final_status_upload_error_leaves_remote_status_finalizing_and_still_terminates(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    events: list[str] = []
    status_upload_error = OSError("R2 status upload failed")
    remote_statuses: list[dict[str, object]] = []
    upload_count = 0
    stderr = io.StringIO()

    def upload_output(source_dir, target, env) -> None:
        nonlocal upload_count
        upload_count += 1
        events.append(f"upload-{upload_count}")
        status_path = source_dir / "runpod-status.json"
        if status_path.is_file():
            remote_statuses.append(json.loads(status_path.read_text(encoding="utf-8")))

    def fail_status_upload(status_path, target, env) -> None:
        events.append("status-upload")
        raise status_upload_error

    def terminate_pod(pod_id: str, api_key: str) -> None:
        events.append("terminate")

    with pytest.raises(OSError) as caught:
        run_cloud_runtime(
            config,
            env=make_env(),
            start_ssh=lambda: 0,
            run_model=lambda command, log_path: 0,
            upload_output=upload_output,
            upload_status=fail_status_upload,
            wait_for_handoff=accept_handoff,
            claim_cleanup=claim_cleanup,
            terminate_pod=terminate_pod,
            stderr=stderr,
        )

    assert caught.value is status_upload_error
    assert events == ["upload-1", "upload-2", "status-upload", "status-upload", "terminate"]
    assert remote_statuses[-1]["status"] == "finalizing"
    assert "RUNPOD_RUNTIME_FAILED pod_id=pod-123 error=OSError: R2 status upload failed" in stderr.getvalue()


def test_termination_error_does_not_hide_runner_exit_code(tmp_path: Path) -> None:
    stderr = io.StringIO()

    def terminate_pod(pod_id: str, api_key: str) -> None:
        raise RuntimeError("delete failed")

    exit_code = run_cloud_runtime(
        make_config(tmp_path),
        env=make_env(),
        start_ssh=lambda: 0,
        run_model=lambda command, log_path: 23,
        upload_output=lambda source_dir, target, env: None,
        upload_status=upload_status,
        wait_for_handoff=accept_handoff,
        claim_cleanup=claim_cleanup,
        terminate_pod=terminate_pod,
        stderr=stderr,
    )

    assert exit_code == 23
    report = stderr.getvalue()
    assert "RUNPOD_CLEANUP_FAILED pod_id=pod-123" in report
    assert 'manual="runpodctl pod delete pod-123"' in report


def test_termination_error_is_reported_without_hiding_evidence_error(tmp_path: Path) -> None:
    evidence_error = OSError("R2 final sweep failed")
    upload_count = 0
    stderr = io.StringIO()

    def upload_output(source_dir, target, env) -> None:
        nonlocal upload_count
        upload_count += 1
        if upload_count == 2:
            raise evidence_error

    def terminate_pod(pod_id: str, api_key: str) -> None:
        raise RuntimeError("delete failed")

    with pytest.raises(OSError) as caught:
        run_cloud_runtime(
            make_config(tmp_path),
            env=make_env(),
            start_ssh=lambda: 0,
            run_model=lambda command, log_path: 0,
            upload_output=upload_output,
            upload_status=upload_status,
            wait_for_handoff=accept_handoff,
            claim_cleanup=claim_cleanup,
            terminate_pod=terminate_pod,
            stderr=stderr,
        )

    assert caught.value is evidence_error
    assert "RUNPOD_RUNTIME_FAILED pod_id=pod-123 error=OSError: R2 final sweep failed" in stderr.getvalue()
    assert "RUNPOD_CLEANUP_FAILED pod_id=pod-123" in stderr.getvalue()


def test_runtime_without_handoff_never_attempts_delete(tmp_path: Path) -> None:
    stderr = io.StringIO()

    def reject_handoff(target, pod_id, lifecycle_token, env, timeout_seconds, poll_seconds) -> None:
        raise TimeoutError("launcher retained ownership")

    def unexpected_delete(pod_id: str, api_key: str) -> None:
        raise AssertionError("runtime without ownership must not delete")

    with pytest.raises(TimeoutError, match="launcher retained ownership"):
        run_cloud_runtime(
            make_config(tmp_path),
            env=make_env(),
            start_ssh=lambda: 0,
            run_model=lambda command, log_path: 0,
            upload_output=lambda source_dir, target, env: None,
            upload_status=upload_status,
            wait_for_handoff=reject_handoff,
            claim_cleanup=lambda target, pod_id, token, env: (_ for _ in ()).throw(
                AssertionError("runtime without ownership must not claim cleanup")
            ),
            terminate_pod=unexpected_delete,
            stderr=stderr,
        )

    assert "RUNPOD_HANDOFF_INCOMPLETE pod_id=pod-123" in stderr.getvalue()


def test_runtime_timeout_cleanup_owner_skips_model_and_deletes(tmp_path: Path) -> None:
    events: list[str] = []

    def unexpected_model(command, log_path) -> int:
        raise AssertionError("cleanup-only runtime must not run the model")

    with pytest.raises(TimeoutError, match="claimed cleanup"):
        run_cloud_runtime(
            make_config(tmp_path),
            env=make_env(),
            start_ssh=lambda: 0,
            run_model=unexpected_model,
            upload_output=lambda source_dir, target, env: None,
            upload_status=upload_status,
            wait_for_handoff=lambda target, pod_id, token, env, timeout, poll: False,
            claim_cleanup=lambda target, pod_id, token, env: True,
            terminate_pod=lambda pod_id, api_key: events.append("terminate"),
        )

    assert events == ["terminate"]


def test_runtime_claim_marker_outage_still_deletes_confirmed_owner(tmp_path: Path) -> None:
    claim_error = OSError("R2 claim marker unavailable")
    events: list[str] = []
    stderr = io.StringIO()

    with pytest.raises(OSError) as caught:
        run_cloud_runtime(
            make_config(tmp_path),
            env=make_env(),
            start_ssh=lambda: 0,
            run_model=lambda command, log_path: 0,
            upload_output=lambda source_dir, target, env: None,
            upload_status=upload_status,
            wait_for_handoff=accept_handoff,
            claim_cleanup=lambda target, pod_id, token, env: (_ for _ in ()).throw(claim_error),
            terminate_pod=lambda pod_id, api_key: events.append("terminate"),
            stderr=stderr,
        )

    assert caught.value is claim_error
    assert events == ["terminate"]
    assert "RUNPOD_CLEANUP_FAILED pod_id=pod-123" in stderr.getvalue()


def test_shared_r2_outage_does_not_hide_evidence_error_or_block_confirmed_owner_delete(
    tmp_path: Path,
) -> None:
    evidence_error = OSError("R2 unavailable during final evidence sweep")
    claim_error = OSError("R2 unavailable during cleanup marker")
    upload_count = 0
    events: list[str] = []
    stderr = io.StringIO()

    def upload_output(source_dir, target, env) -> None:
        nonlocal upload_count
        upload_count += 1
        if upload_count == 2:
            raise evidence_error

    with pytest.raises(OSError) as caught:
        run_cloud_runtime(
            make_config(tmp_path),
            env=make_env(),
            start_ssh=lambda: 0,
            run_model=lambda command, log_path: 0,
            upload_output=upload_output,
            upload_status=lambda status_path, target, env: (_ for _ in ()).throw(evidence_error),
            wait_for_handoff=accept_handoff,
            claim_cleanup=lambda target, pod_id, token, env: (_ for _ in ()).throw(claim_error),
            terminate_pod=lambda pod_id, api_key: events.append("terminate"),
            stderr=stderr,
        )

    assert caught.value is evidence_error
    assert events == ["terminate"]
    report = stderr.getvalue()
    assert "RUNPOD_RUNTIME_FAILED pod_id=pod-123 error=OSError: R2 unavailable during final evidence sweep" in report
    assert "RUNPOD_CLEANUP_FAILED pod_id=pod-123 error=OSError: R2 unavailable during cleanup marker" in report


def test_failed_runner_never_publishes_terminal_failed_before_evidence_sweep_finishes(
    tmp_path: Path,
) -> None:
    sweep_error = OSError("partial evidence sweep")
    upload_count = 0
    remote_statuses: list[dict[str, object]] = []

    def upload_output(source_dir, target, env) -> None:
        nonlocal upload_count
        upload_count += 1
        status_path = source_dir / "runpod-status.json"
        if status_path.is_file():
            remote_statuses.append(json.loads(status_path.read_text(encoding="utf-8")))
        if upload_count == 2:
            raise sweep_error

    def upload_finalizing_status(status_path, target, env) -> None:
        remote_statuses.append(json.loads(status_path.read_text(encoding="utf-8")))

    with pytest.raises(OSError) as caught:
        run_cloud_runtime(
            make_config(tmp_path),
            env=make_env(),
            start_ssh=lambda: 0,
            run_model=lambda command, log_path: 23,
            upload_output=upload_output,
            upload_status=upload_finalizing_status,
            wait_for_handoff=accept_handoff,
            claim_cleanup=claim_cleanup,
            terminate_pod=lambda pod_id, api_key: None,
        )

    assert caught.value is sweep_error
    assert remote_statuses
    assert all(status["status"] == "finalizing" for status in remote_statuses)
    assert all(status["outcome"] == "failed" for status in remote_statuses)


def test_successful_run_claims_cleanup_after_final_status_upload(tmp_path: Path) -> None:
    events: list[str] = []

    def upload_output(source_dir, target, env) -> None:
        events.append("upload")

    def upload_final_status(status_path, target, env) -> None:
        assert json.loads(status_path.read_text(encoding="utf-8"))["status"] == "ok"
        events.append("status")

    def claim_runtime_cleanup(target, pod_id, lifecycle_token, env) -> bool:
        events.append("claim")
        return True

    def terminate_pod(pod_id: str, api_key: str) -> None:
        events.append("terminate")

    assert (
        run_cloud_runtime(
            make_config(tmp_path),
            env=make_env(),
            start_ssh=lambda: 0,
            run_model=lambda command, log_path: 0,
            upload_output=upload_output,
            upload_status=upload_final_status,
            wait_for_handoff=accept_handoff,
            claim_cleanup=claim_runtime_cleanup,
            terminate_pod=terminate_pod,
        )
        == 0
    )
    assert events == ["upload", "upload", "status", "claim", "terminate"]


def test_runtime_that_loses_cleanup_cas_never_deletes(tmp_path: Path) -> None:
    stderr = io.StringIO()

    def unexpected_delete(pod_id: str, api_key: str) -> None:
        raise AssertionError("runtime that lost cleanup CAS must not delete")

    assert (
        run_cloud_runtime(
            make_config(tmp_path),
            env=make_env(),
            start_ssh=lambda: 0,
            run_model=lambda command, log_path: 0,
            upload_output=lambda source_dir, target, env: None,
            upload_status=upload_status,
            wait_for_handoff=accept_handoff,
            claim_cleanup=lambda target, pod_id, token, env: False,
            terminate_pod=unexpected_delete,
            stderr=stderr,
        )
        == 0
    )
    assert "RUNPOD_CLEANUP_SKIPPED pod_id=pod-123 owner_changed=true" in stderr.getvalue()


def test_run_model_subprocess_persists_batch_level_timeout_traceback(tmp_path: Path) -> None:
    log_path = tmp_path / "runner.log"

    exit_code = run_model_subprocess(
        [sys.executable, "-c", "import sys; print('MAX_RUNTIME_MIN exceeded', file=sys.stderr); raise SystemExit(1)"],
        log_path,
    )

    assert exit_code == 1
    assert "MAX_RUNTIME_MIN exceeded" in log_path.read_text(encoding="utf-8")
