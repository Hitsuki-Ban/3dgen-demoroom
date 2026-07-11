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


def _gpu(index: int = 0, name: str = "NVIDIA GeForce RTX 4090") -> runner_utils.GpuDeviceIdentity:
    return runner_utils.GpuDeviceIdentity(
        index=index,
        uuid=f"GPU-{index + 1:08x}-2222-3333-4444-555555555555",
        name=name,
        driver_model="N/A",
        mig_mode="Disabled",
    )


def _target(
    mode: str = runner_utils.RUNPOD_EXCLUSIVE_DEVICE_VRAM_MODE,
    *,
    baseline_bytes: int = 0,
) -> runner_utils.VramMeasurementTarget:
    return runner_utils.VramMeasurementTarget(
        device=_gpu(),
        mode=mode,
        device_baseline_bytes=baseline_bytes,
    )


def _compute(
    device: runner_utils.GpuDeviceIdentity,
    pid: int,
    used_memory_mib: int,
    process_name: str = "/usr/bin/python3",
) -> runner_utils.GpuComputeProcess:
    return runner_utils.GpuComputeProcess(
        gpu_uuid=device.uuid,
        pid=pid,
        process_name=process_name,
        used_memory_mib=used_memory_mib,
    )


def test_run_with_peak_vram_records_subprocess_log_tail(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner_utils, "prepare_vram_measurement_target", lambda env: _target())
    monkeypatch.setattr(runner_utils, "query_gpu_compute_processes", lambda device: [])
    monkeypatch.setattr(runner_utils, "query_gpu_device_memory_bytes", lambda device: 1024)
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

    def fake_popen(command, *, stdout, stderr, text, env, **options):
        nonlocal captured_log, captured_options
        captured_log = stdout
        captured_options = options
        assert env["CUDA_VISIBLE_DEVICES"] == _gpu().uuid
        stdout.write("final timeout diagnostic\n")
        return FakeProcess()

    monkeypatch.setattr(runner_utils.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_utils, "prepare_vram_measurement_target", lambda env: _target())
    monkeypatch.setattr(runner_utils, "query_gpu_compute_processes", lambda device: [])
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
    monkeypatch.setattr(runner_utils, "prepare_vram_measurement_target", lambda env: _target())
    monkeypatch.setattr(runner_utils, "query_gpu_compute_processes", lambda device: [])
    monkeypatch.setattr(runner_utils, "query_gpu_device_memory_bytes", lambda device: 1024)
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


def test_gpu_inventory_requires_explicit_full_uuid_for_multiple_devices() -> None:
    devices = runner_utils.parse_gpu_inventory(
        "0, GPU-11111111-2222-3333-4444-555555555555, NVIDIA GeForce RTX 4090, N/A, Disabled\n"
        "1, GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee, NVIDIA RTX 5090, N/A, Disabled\n"
    )

    with pytest.raises(runner_utils.VramConfigurationError, match="BENCH_GPU_UUID is required"):
        runner_utils.select_target_gpu(devices, None)
    with pytest.raises(runner_utils.VramConfigurationError, match="exactly match"):
        runner_utils.select_target_gpu(devices, "GPU-aaaaaaaa")

    selected = runner_utils.select_target_gpu(
        devices,
        "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )
    assert selected.index == 1
    assert selected.name == "NVIDIA RTX 5090"


def test_prepare_vram_target_binds_runpod_exclusive_device_and_baseline(monkeypatch) -> None:
    device = _gpu(index=1, name="NVIDIA RTX 5090")
    monkeypatch.setattr(runner_utils, "query_gpu_inventory", lambda: [_gpu(), device])
    monkeypatch.setattr(runner_utils, "query_gpu_compute_processes", lambda selected: [])
    monkeypatch.setattr(runner_utils, "query_gpu_device_memory_bytes", lambda selected: 256 * 1024 * 1024)

    target = runner_utils.prepare_vram_measurement_target(
        {
            "BENCH_VRAM_MEASUREMENT_MODE": "runpod_exclusive_device",
            "BENCH_GPU_UUID": device.uuid,
            "RUNPOD_POD_ID": "pod-123",
        }
    )

    assert target.device is device
    assert target.device_baseline_bytes == 256 * 1024 * 1024


def test_prepare_vram_target_rejects_missing_mode_before_query(monkeypatch) -> None:
    monkeypatch.setattr(
        runner_utils,
        "query_gpu_inventory",
        lambda: pytest.fail("GPU query must not run before required mode validation"),
    )

    with pytest.raises(runner_utils.VramConfigurationError, match="BENCH_VRAM_MEASUREMENT_MODE"):
        runner_utils.prepare_vram_measurement_target({})


def test_prepare_process_target_requires_explicit_host_pid_namespace_before_query(monkeypatch) -> None:
    monkeypatch.setattr(
        runner_utils,
        "query_gpu_inventory",
        lambda: pytest.fail("GPU query must not run before PID namespace validation"),
    )

    with pytest.raises(runner_utils.VramConfigurationError, match="BENCH_PID_NAMESPACE"):
        runner_utils.prepare_vram_measurement_target(
            {"BENCH_VRAM_MEASUREMENT_MODE": "process_group"}
        )


def test_prepare_vram_target_rejects_wsl_before_gpu_query(monkeypatch) -> None:
    monkeypatch.setattr(runner_utils.platform, "release", lambda: "6.6.87.2-microsoft-standard-WSL2")
    monkeypatch.setattr(
        runner_utils,
        "query_gpu_inventory",
        lambda: pytest.fail("GPU query must not run for unsupported WSL telemetry"),
    )

    with pytest.raises(runner_utils.VramConfigurationError, match="WSL"):
        runner_utils.prepare_vram_measurement_target(
            {
                "BENCH_VRAM_MEASUREMENT_MODE": "runpod_exclusive_device",
                "RUNPOD_POD_ID": "pod-123",
            }
        )


def test_prepare_vram_target_rejects_default_or_custom_mps_control_pid_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pipe_directory = tmp_path / "nvidia-mps"
    pipe_directory.mkdir()
    (pipe_directory / "nvidia-cuda-mps-control.pid").write_text("1234\n", encoding="utf-8")

    monkeypatch.setattr(runner_utils, "DEFAULT_MPS_PIPE_DIRECTORY", pipe_directory)
    with pytest.raises(runner_utils.VramConfigurationError, match="MPS control PID file"):
        runner_utils.prepare_vram_measurement_target(
            {
                "BENCH_VRAM_MEASUREMENT_MODE": "runpod_exclusive_device",
                "RUNPOD_POD_ID": "pod-123",
            }
        )

    with pytest.raises(runner_utils.VramConfigurationError, match="MPS control PID file"):
        runner_utils.prepare_vram_measurement_target(
            {
                "BENCH_VRAM_MEASUREMENT_MODE": "runpod_exclusive_device",
                "RUNPOD_POD_ID": "pod-123",
                "CUDA_MPS_PIPE_DIRECTORY": str(pipe_directory),
            }
        )


def test_prepare_vram_target_rejects_wddm(monkeypatch) -> None:
    wddm_device = runner_utils.GpuDeviceIdentity(
        index=0,
        uuid="GPU-11111111-2222-3333-4444-555555555555",
        name="NVIDIA GeForce RTX 4070 Ti",
        driver_model="WDDM",
        mig_mode="N/A",
    )
    monkeypatch.setattr(runner_utils, "query_gpu_inventory", lambda: [wddm_device])

    with pytest.raises(runner_utils.VramConfigurationError, match="WDDM"):
        runner_utils.prepare_vram_measurement_target(
            {
                "BENCH_VRAM_MEASUREMENT_MODE": "runpod_exclusive_device",
                "RUNPOD_POD_ID": "pod-123",
            }
        )


def test_process_group_sampler_sums_processes_per_sample_then_tracks_peak(monkeypatch) -> None:
    device = _gpu()
    target = runner_utils.VramMeasurementTarget(
        device=device,
        mode=runner_utils.PROCESS_GROUP_VRAM_MODE,
        device_baseline_bytes=0,
    )
    samples = iter(
        [
            [
                _compute(device, 100, 100),
                _compute(device, 101, 200),
            ],
            [
                _compute(device, 100, 150),
                _compute(device, 101, 250),
            ],
        ]
    )
    monkeypatch.setattr(runner_utils, "query_process_group_pids", lambda root_pid: {100, 101})
    monkeypatch.setattr(runner_utils, "query_gpu_compute_processes", lambda selected: next(samples))
    sampler = runner_utils._PeakVramSampler(target, root_pid=100)

    sampler.sample()
    sampler.sample()
    measurement = sampler.finish()

    assert measurement.peak_vram_bytes == 400 * 1024 * 1024
    assert measurement.max_matched_process_count == 2
    assert measurement.sample_count == 2
    assert measurement.device is device
    assert measurement.pid_namespace_verified is True


def test_process_group_sampler_excludes_co_resident_process_memory(monkeypatch) -> None:
    device = _gpu()
    target = runner_utils.VramMeasurementTarget(
        device=device,
        mode=runner_utils.PROCESS_GROUP_VRAM_MODE,
        device_baseline_bytes=0,
    )
    monkeypatch.setattr(runner_utils, "query_process_group_pids", lambda root_pid: {100, 101})
    monkeypatch.setattr(
        runner_utils,
        "query_gpu_compute_processes",
        lambda selected: [
            _compute(device, 100, 100),
            _compute(device, 999, 900),
        ],
    )

    sampler = runner_utils._PeakVramSampler(target, root_pid=100)
    sampler.sample()
    measurement = sampler.finish()

    assert measurement.peak_vram_bytes == 100 * 1024 * 1024
    assert measurement.max_matched_process_count == 1
    assert measurement.pid_namespace_verified is True


def test_preexisting_process_policy_allows_process_scope_but_rejects_runpod_device_scope() -> None:
    processes = [_compute(_gpu(), 999, 900)]

    runner_utils.validate_preexisting_compute_processes(
        runner_utils.PROCESS_GROUP_VRAM_MODE,
        processes,
    )
    with pytest.raises(runner_utils.VramProcessScopeError, match="not idle"):
        runner_utils.validate_preexisting_compute_processes(
            runner_utils.RUNPOD_EXCLUSIVE_DEVICE_VRAM_MODE,
            processes,
        )


def test_compute_process_parser_rejects_unavailable_memory() -> None:
    with pytest.raises(runner_utils.VramQueryError, match="used memory"):
        runner_utils.parse_gpu_compute_processes(
            "GPU-11111111-2222-3333-4444-555555555555, 1234, /usr/bin/python3, [N/A]\n",
            "GPU-11111111-2222-3333-4444-555555555555",
        )


def test_sampler_rejects_mps_server_even_for_runpod_device_scope(monkeypatch) -> None:
    device = _gpu()
    monkeypatch.setattr(
        runner_utils,
        "query_gpu_compute_processes",
        lambda selected: [_compute(device, 900, 400, "/usr/bin/nvidia-cuda-mps-server")],
    )

    with pytest.raises(runner_utils.VramConfigurationError, match="nvidia-cuda-mps-server"):
        runner_utils._PeakVramSampler(_target(), root_pid=100).sample()


def test_process_group_query_reads_proc_stat_with_complex_command(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    fixtures = [
        (100, "python worker", 100),
        (101, "worker ) helper", 100),
        (200, "unrelated", 200),
    ]
    for pid, command, process_group in fixtures:
        process_dir = proc_root / str(pid)
        process_dir.mkdir()
        (process_dir / "stat").write_text(
            f"{pid} ({command}) S 1 {process_group}\n",
            encoding="utf-8",
        )

    assert runner_utils.query_process_group_pids(100, proc_root) == {100, 101}


def test_query_failure_kills_inference_process_group(monkeypatch) -> None:
    events: list[str] = []

    class FakeProcess:
        pid = 4321
        returncode = None

        def poll(self):
            return self.returncode

    process = FakeProcess()

    def fake_popen(command, **options):
        assert options["env"]["CUDA_VISIBLE_DEVICES"] == _gpu().uuid
        return process

    def kill_and_wait(current_process) -> None:
        events.append("kill-and-wait")
        current_process.returncode = -9

    monkeypatch.setattr(runner_utils, "prepare_vram_measurement_target", lambda env: _target("process_group"))
    monkeypatch.setattr(runner_utils.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_utils, "query_process_group_pids", lambda root_pid: {4321})
    monkeypatch.setattr(
        runner_utils,
        "query_gpu_compute_processes",
        lambda device: (_ for _ in ()).throw(runner_utils.VramQueryError("nvidia-smi failed")),
    )
    monkeypatch.setattr(runner_utils, "_kill_process_group_and_wait", kill_and_wait)

    with pytest.raises(runner_utils.VramQueryError, match="nvidia-smi failed"):
        runner_utils.run_with_peak_vram(
            ["python", "inference.py"],
            timeout_seconds=5,
            timeout_label="unit",
        )

    assert events == ["kill-and-wait"]


def test_finish_failure_cleans_process_group_after_root_process_exits(monkeypatch) -> None:
    events: list[str] = []

    class FakeProcess:
        pid = 4321
        returncode = 0

        def poll(self):
            return self.returncode

    monkeypatch.setattr(runner_utils, "prepare_vram_measurement_target", lambda env: _target("process_group"))
    monkeypatch.setattr(runner_utils.subprocess, "Popen", lambda command, **options: FakeProcess())
    monkeypatch.setattr(
        runner_utils,
        "_kill_process_group_and_wait",
        lambda process: events.append(f"cleanup:{process.pid}"),
    )

    with pytest.raises(runner_utils.VramQueryError, match="before any VRAM sample"):
        runner_utils.run_with_peak_vram(
            ["python", "inference.py"],
            timeout_seconds=5,
            timeout_label="unit",
        )

    assert events == ["cleanup:4321"]


def test_nvidia_smi_query_timeout_is_bounded_and_normalized(monkeypatch) -> None:
    def timeout(command, **options):
        assert options["timeout"] == runner_utils.NVIDIA_SMI_QUERY_TIMEOUT_SECONDS
        raise runner_utils.subprocess.TimeoutExpired(command, options["timeout"])

    monkeypatch.setattr(runner_utils.subprocess, "check_output", timeout)

    with pytest.raises(runner_utils.VramQueryError, match="timed out after 10s"):
        runner_utils._query_nvidia_smi(["--query-gpu=uuid"])


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
        (runner_utils.VramQueryError("nvidia-smi failed"), 0, 2, False),
    ],
)
def test_should_retry_task_error(
    error: Exception,
    attempt_index: int,
    max_attempts: int,
    expected: bool,
) -> None:
    assert runner_utils.should_retry_task_error(error, attempt_index, max_attempts) is expected


@pytest.mark.parametrize(
    "primary_error",
    [
        runner_utils.RunnerTimeoutError(command=["python", "infer.py"], timeout_label="unit"),
        runner_utils.VramQueryError("nvidia-smi failed"),
    ],
)
def test_fatal_error_remains_primary_when_incremental_evidence_upload_fails(
    tmp_path: Path,
    primary_error: Exception,
) -> None:
    upload_error = OSError("R2 task upload failed")

    def fail_upload(task_output_dir, task_id, env):
        raise upload_error

    with pytest.raises(type(primary_error)) as caught:
        runner_utils.upload_task_increment_then_raise(
            tmp_path,
            "task-1",
            {},
            primary_error,
            upload=fail_upload,
        )

    assert caught.value is primary_error
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
