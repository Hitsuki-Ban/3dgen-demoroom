from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence, TextIO

from bench_harness.runpod import RunPodClient, format_cleanup_failure
from bench_harness.uploader import S3UploadConfig, create_s3_client, create_uploader


StartSsh = Callable[[], int]
RunModel = Callable[[Sequence[str], Path], int]
UploadOutput = Callable[[Path, str, Mapping[str, str]], None]
UploadStatus = Callable[[Path, str, Mapping[str, str]], None]
WaitForHandoff = Callable[[str, str, str, Mapping[str, str], float, float], bool]
ClaimCleanup = Callable[[str, str, str, Mapping[str, str]], bool]
TerminatePod = Callable[[str, str], None]
Now = Callable[[], str]
HANDOFF_POLL_SECONDS = 1.0


@dataclass(frozen=True)
class CloudRuntimeConfig:
    model_id: str
    output_root: Path
    s3_target: str
    runner_command: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("RunPod runtime model_id is required")
        if not self.s3_target.startswith("s3://"):
            raise ValueError("RunPod runtime S3 target must use s3://")
        if not self.runner_command:
            raise ValueError("RunPod runtime runner command is required")


def run_cloud_runtime(
    config: CloudRuntimeConfig,
    *,
    env: Mapping[str, str] | None = None,
    start_ssh: StartSsh | None = None,
    run_model: RunModel | None = None,
    upload_output: UploadOutput | None = None,
    upload_status: UploadStatus | None = None,
    wait_for_handoff: WaitForHandoff | None = None,
    claim_cleanup: ClaimCleanup | None = None,
    terminate_pod: TerminatePod | None = None,
    now: Now | None = None,
    stderr: TextIO | None = None,
) -> int:
    runtime_env = os.environ if env is None else env
    stderr_stream = sys.stderr if stderr is None else stderr
    pod_id = require_env(runtime_env, "RUNPOD_POD_ID")
    api_key = runtime_env.get("RUNPOD_API_KEY")
    start_ssh_fn = start_ssh or start_ssh_service
    run_model_fn = run_model or run_model_subprocess
    upload_output_fn = upload_output or upload_runtime_output
    upload_status_fn = upload_status or upload_runtime_status
    wait_for_handoff_fn = wait_for_handoff or wait_for_lifecycle_handoff
    claim_cleanup_fn = claim_cleanup or claim_runtime_cleanup
    terminate_pod_fn = terminate_pod or terminate_runtime_pod
    now_fn = now or utc_now

    primary_error: BaseException | None = None
    secondary_errors: list[BaseException] = []
    runtime_owns_pod = False
    run_model_allowed = False
    process_exit_code = 0
    ssh_exit_code: int | None = None
    runner_exit_code: int | None = None
    runner_output_tail: str | None = None
    lifecycle_token: str | None = None
    handoff_timeout_seconds: float | None = None
    runner_log_path = config.output_root / "runpod-runner.log"

    def record_error(error: BaseException) -> None:
        nonlocal primary_error
        if primary_error is None:
            primary_error = error
        else:
            secondary_errors.append(error)

    try:
        if not api_key:
            record_error(ValueError("RUNPOD_API_KEY is required"))
        try:
            lifecycle_token = require_env(runtime_env, "RUNPOD_LIFECYCLE_TOKEN")
            handoff_timeout_seconds = require_positive_float_env(runtime_env, "RUNPOD_HANDOFF_TIMEOUT_SECONDS")
            S3UploadConfig.from_target(config.s3_target, runtime_env)
        except BaseException as error:
            record_error(error)

        if primary_error is None:
            try:
                ssh_exit_code = start_ssh_fn()
            except BaseException as error:
                record_error(error)
            else:
                if ssh_exit_code != 0:
                    process_exit_code = ssh_exit_code

        try:
            write_startup_status(
                config,
                pod_id=pod_id,
                ssh_exit_code=ssh_exit_code,
                started_at=now_fn(),
            )
        except BaseException as error:
            record_error(error)

        try:
            upload_output_fn(config.output_root, config.s3_target, runtime_env)
        except BaseException as error:
            record_error(error)

        if ssh_exit_code == 0 and lifecycle_token is not None and handoff_timeout_seconds is not None:
            try:
                run_model_allowed = wait_for_handoff_fn(
                    config.s3_target,
                    pod_id,
                    lifecycle_token,
                    runtime_env,
                    handoff_timeout_seconds,
                    HANDOFF_POLL_SECONDS,
                )
            except BaseException as error:
                record_error(error)
            else:
                runtime_owns_pod = True
                if not run_model_allowed:
                    record_error(
                        TimeoutError(
                            f"RunPod runtime {pod_id} claimed cleanup before handoff completed"
                        )
                    )

        if runtime_owns_pod and run_model_allowed and primary_error is None and process_exit_code == 0:
            try:
                runner_exit_code = run_model_fn(config.runner_command, runner_log_path)
            except BaseException as error:
                record_error(error)
            else:
                process_exit_code = runner_exit_code
                if runner_exit_code != 0 and runner_log_path.is_file():
                    runner_output_tail = read_text_tail(runner_log_path)

        finalizing_status_written = False
        try:
            write_final_status(
                config,
                pod_id=pod_id,
                runner_exit_code=runner_exit_code,
                process_exit_code=process_exit_code,
                primary_error=primary_error,
                runner_output_tail=runner_output_tail,
                runtime_owns_pod=runtime_owns_pod,
                finished_at=now_fn(),
                final=False,
            )
        except BaseException as error:
            record_error(error)
        else:
            finalizing_status_written = True

        evidence_sweep_succeeded = False
        try:
            upload_output_fn(config.output_root, config.s3_target, runtime_env)
        except BaseException as error:
            record_error(error)
        else:
            evidence_sweep_succeeded = finalizing_status_written

        terminal_status_published = False
        if evidence_sweep_succeeded:
            try:
                write_final_status(
                    config,
                    pod_id=pod_id,
                    runner_exit_code=runner_exit_code,
                    process_exit_code=process_exit_code,
                    primary_error=primary_error,
                    runner_output_tail=runner_output_tail,
                    runtime_owns_pod=runtime_owns_pod,
                    finished_at=now_fn(),
                    final=True,
                )
                upload_status_fn(config.output_root / "runpod-status.json", config.s3_target, runtime_env)
            except BaseException as error:
                record_error(error)
            else:
                terminal_status_published = True

        if not terminal_status_published:
            try:
                write_final_status(
                    config,
                    pod_id=pod_id,
                    runner_exit_code=runner_exit_code,
                    process_exit_code=process_exit_code,
                    primary_error=primary_error,
                    runner_output_tail=runner_output_tail,
                    runtime_owns_pod=runtime_owns_pod,
                    finished_at=now_fn(),
                    final=False,
                )
                upload_status_fn(config.output_root / "runpod-status.json", config.s3_target, runtime_env)
            except BaseException as error:
                record_error(error)
    finally:
        if primary_error is not None:
            print(format_runtime_failure(pod_id, primary_error), file=stderr_stream, flush=True)
        elif process_exit_code != 0:
            print(format_runtime_exit_failure(pod_id, process_exit_code), file=stderr_stream, flush=True)
        for error in secondary_errors:
            print(format_secondary_failure(error), file=stderr_stream, flush=True)
        if runtime_owns_pod and lifecycle_token is not None:
            cleanup_claimed = False
            try:
                cleanup_claimed = claim_cleanup_fn(
                    config.s3_target,
                    pod_id,
                    lifecycle_token,
                    runtime_env,
                )
            except BaseException as cleanup_error:
                cleanup_message = format_cleanup_failure(pod_id, cleanup_error)
                print(cleanup_message, file=stderr_stream, flush=True)
                if primary_error is None and process_exit_code == 0:
                    primary_error = cleanup_error
                cleanup_claimed = True
            if cleanup_claimed:
                try:
                    if not api_key:
                        raise ValueError("RUNPOD_API_KEY is required")
                    terminate_pod_fn(pod_id, api_key)
                except BaseException as cleanup_error:
                    cleanup_message = format_cleanup_failure(pod_id, cleanup_error)
                    print(cleanup_message, file=stderr_stream, flush=True)
                    if primary_error is None and process_exit_code == 0:
                        primary_error = cleanup_error
            else:
                print(
                    f"RUNPOD_CLEANUP_SKIPPED pod_id={pod_id} owner_changed=true",
                    file=stderr_stream,
                    flush=True,
                )
        else:
            print(
                f"RUNPOD_HANDOFF_INCOMPLETE pod_id={pod_id} owner=launcher runtime_delete_skipped=true",
                file=stderr_stream,
                flush=True,
            )

    if primary_error is not None:
        raise primary_error
    return process_exit_code


def write_startup_status(
    config: CloudRuntimeConfig,
    *,
    pod_id: str,
    ssh_exit_code: int | None,
    started_at: str,
) -> None:
    write_json(
        config.output_root / "runpod-startup.json",
        {
            "model_id": config.model_id,
            "pod_id": pod_id,
            "s3_target": config.s3_target,
            "ssh_exit_code": ssh_exit_code,
            "started_at": started_at,
            "status": "started" if ssh_exit_code == 0 else "failed",
        },
    )


def write_final_status(
    config: CloudRuntimeConfig,
    *,
    pod_id: str,
    runner_exit_code: int | None,
    process_exit_code: int,
    primary_error: BaseException | None,
    runner_output_tail: str | None,
    runtime_owns_pod: bool,
    finished_at: str,
    final: bool,
) -> None:
    failed = primary_error is not None or process_exit_code != 0
    outcome = "failed" if failed else "ok"
    status: dict[str, object] = {
        "finished_at": finished_at,
        "lifecycle_owner": "runtime" if runtime_owns_pod else "launcher",
        "model_id": config.model_id,
        "pod_id": pod_id,
        "runner_exit_code": runner_exit_code,
        "s3_target": config.s3_target,
        "outcome": outcome,
        "status": outcome if final else "finalizing",
    }
    if primary_error is not None:
        status["runtime_error_type"] = type(primary_error).__name__
        status["runtime_error_message"] = str(primary_error)
    if runner_output_tail:
        status["runner_output_tail"] = runner_output_tail
    write_json(config.output_root / "runpod-status.json", status)


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def start_ssh_service() -> int:
    Path("/run/sshd").mkdir(parents=True, exist_ok=True)
    configure_ssh_public_key(os.environ.get("PUBLIC_KEY"))
    return subprocess.run(["service", "ssh", "start"], check=False).returncode


def configure_ssh_public_key(public_key: str | None, *, ssh_dir: Path = Path("/root/.ssh")) -> None:
    if not public_key:
        return
    ssh_dir.mkdir(parents=True, exist_ok=True)
    authorized_keys = ssh_dir / "authorized_keys"
    with authorized_keys.open("a", encoding="utf-8") as handle:
        handle.write(public_key)
        handle.write("\n")
    ssh_dir.chmod(0o700)
    authorized_keys.chmod(0o600)


def run_model_subprocess(command: Sequence[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", buffering=1) as log_handle:
        return subprocess.run(
            list(command),
            check=False,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        ).returncode


def upload_runtime_output(source_dir: Path, target: str, env: Mapping[str, str]) -> None:
    create_uploader("s3", target, env=env).upload_run(source_dir)


def upload_runtime_status(status_path: Path, target: str, env: Mapping[str, str]) -> None:
    if not status_path.is_file():
        raise FileNotFoundError(f"RunPod status file does not exist: {status_path}")
    config = S3UploadConfig.from_target(target, env)
    create_s3_client(config).upload_file(
        str(status_path),
        config.bucket,
        "/".join(part for part in (config.prefix, status_path.name) if part),
    )


def wait_for_lifecycle_handoff(
    target: str,
    pod_id: str,
    lifecycle_token: str,
    env: Mapping[str, str],
    timeout_seconds: float,
    poll_seconds: float,
) -> bool:
    from bench_harness.runpod_handoff import wait_for_runtime_ownership

    return wait_for_runtime_ownership(
        target,
        pod_id,
        lifecycle_token,
        env,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
    )


def claim_runtime_cleanup(
    target: str,
    pod_id: str,
    lifecycle_token: str,
    env: Mapping[str, str],
) -> bool:
    from bench_harness.runpod_handoff import claim_cleanup

    return claim_cleanup(target, pod_id, lifecycle_token, "runtime", env)


def terminate_runtime_pod(pod_id: str, api_key: str) -> None:
    RunPodClient(api_key=api_key).terminate_pod(pod_id)


def format_secondary_failure(error: BaseException) -> str:
    return f"RUNPOD_SECONDARY_FAILURE error={type(error).__name__}: {error}"


def format_runtime_failure(pod_id: str, error: BaseException) -> str:
    return f"RUNPOD_RUNTIME_FAILED pod_id={pod_id} error={type(error).__name__}: {error}"


def format_runtime_exit_failure(pod_id: str, exit_code: int) -> str:
    return f"RUNPOD_RUNTIME_FAILED pod_id={pod_id} exit_code={exit_code}"


def read_text_tail(path: Path, max_bytes: int = 12000) -> str:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes), os.SEEK_SET)
        return handle.read().decode("utf-8", errors="replace").strip()


def require_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


def require_positive_float_env(env: Mapping[str, str], name: str) -> float:
    raw_value = require_env(env, name)
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m bench_harness.runpod_runtime")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--s3-target", required=True)
    parser.add_argument("runner_command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    runner_command = tuple(args.runner_command)
    if runner_command[:1] == ("--",):
        runner_command = runner_command[1:]
    if not runner_command:
        parser.error("runner command is required after --")
    exit_code = run_cloud_runtime(
        CloudRuntimeConfig(
            model_id=args.model_id,
            output_root=args.output_root,
            s3_target=args.s3_target,
            runner_command=runner_command,
        )
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
