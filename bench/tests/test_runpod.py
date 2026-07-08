import pytest
import os
import shutil
import subprocess
from urllib.error import HTTPError

from bench_harness.runpod import (
    DEFAULT_ALLOWED_CUDA_VERSIONS,
    DEFAULT_GPU_TYPE_IDS,
    DEFAULT_MAX_RUNTIME_MIN,
    DEFAULT_MIN_BALANCE_USD,
    R2Credentials,
    RunPodApiError,
    RunPodClient,
    RunPodBalanceCheck,
    RunPodLaunchConfig,
    build_balance_query,
    build_cloud_run_command,
    build_pod_payload,
    parse_client_balance,
    request_json,
)


def make_r2_credentials() -> R2Credentials:
    return R2Credentials(
        endpoint="https://example.r2.cloudflarestorage.com",
        access_key_id="access-key",
        secret_access_key="secret-key",
    )


def test_build_balance_query_requests_client_balance() -> None:
    check = RunPodBalanceCheck(api_key="token", min_balance_usd=10.0)

    assert check.endpoint == "https://api.runpod.io/graphql"
    assert check.headers == {"Authorization": "Bearer token"}
    assert "clientBalance" in build_balance_query()


def test_parse_client_balance_rejects_under_threshold() -> None:
    response = {"data": {"myself": {"clientBalance": 7.5}}}

    with pytest.raises(RuntimeError, match="below threshold"):
        parse_client_balance(response, min_balance_usd=10.0)


def test_parse_client_balance_accepts_enough_balance() -> None:
    response = {"data": {"myself": {"clientBalance": 12.0}}}

    assert parse_client_balance(response, min_balance_usd=10.0) == 12.0


def test_build_cloud_run_command_runs_model_then_uploads_to_s3() -> None:
    command = build_cloud_run_command(
        model_id="triposg",
        output_root="/work/output",
        s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
    )

    assert "python3 /opt/3dgen-runner/triposg_runner.py" in command
    assert "--input-root /opt/3dgen-tasks" in command
    assert "--output-root /work/output" in command
    assert "python3 -m bench_harness.cli upload-s3" in command
    assert "s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z" in command


def test_build_cloud_run_command_uploads_status_even_when_runner_fails() -> None:
    command = build_cloud_run_command(
        model_id="triposg",
        output_root="/work/output",
        s3_target="s3://3dgen-runs/runs/triposg/wave1/20260708T000000Z",
    )

    assert "mkdir -p /run/sshd" in command
    assert "service ssh start" in command
    assert "ssh_exit_code=$?" in command
    assert command.index("service ssh start") < command.index("python3 /opt/3dgen-runner/triposg_runner.py")
    assert "runner_exit_code=$?" in command
    assert "runpod-status.json" in command
    assert "upload_exit_code=$?" in command
    assert "status_exit_code=$?" in command
    assert "bench_harness.cli upload-s3" in command
    assert command.index("runner_exit_code=$?") < command.index("bench_harness.cli upload-s3")
    assert "https://rest.runpod.io/v1/pods/" in command
    assert 'if [ "$upload_exit_code" -ne 0 ]; then exit "$upload_exit_code"; fi' in command
    assert 'if [ "$status_exit_code" -ne 0 ]; then exit "$status_exit_code"; fi' in command
    assert "exit \"$runner_exit_code\"" in command
    assert "&& PYTHONPATH=/opt/bench/src" not in command


def test_build_cloud_run_command_has_valid_bash_syntax(tmp_path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available")
    script_path = tmp_path / "runpod-command.sh"
    script_path.write_text(
        build_cloud_run_command(
            model_id="triposg",
            output_root="/work/output",
            s3_target="s3://3dgen-runs/runs/triposg/wave1/20260708T000000Z",
        ),
        encoding="utf-8",
        newline="\n",
    )

    bash_script_path = str(script_path)
    if os.name == "nt" and bash.lower().endswith("bash.exe"):
        bash_script_path = subprocess.check_output(
            ["wsl", "wslpath", "-a", script_path.as_posix()],
            text=True,
        ).strip()

    subprocess.run([bash, "-n", bash_script_path], check=True)


def test_build_cloud_run_command_rejects_unknown_model() -> None:
    with pytest.raises(ValueError, match="unknown model"):
        build_cloud_run_command(
            model_id="unknown",
            output_root="/work/output",
            s3_target="s3://3dgen-runs/runs/unknown",
        )


def test_build_pod_payload_uses_on_demand_gpu_priority_and_runtime_env() -> None:
    payload = build_pod_payload(
        RunPodLaunchConfig(
            name="3dgen-triposg-wave1",
            image_name="ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc",
            model_id="triposg",
            s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
            max_runtime_min=90,
            gpu_type_ids=("NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 4090"),
            allowed_cuda_versions=("12.8",),
            r2_credentials=make_r2_credentials(),
            network_volume_id="volume-123",
            data_center_id="US-IL-1",
            startup_timeout_min=10,
        ),
        runpod_api_key="token",
    )

    assert payload["name"] == "3dgen-triposg-wave1"
    assert payload["imageName"] == "ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc"
    assert payload["cloudType"] == "SECURE"
    assert payload["computeType"] == "GPU"
    assert payload["gpuTypeIds"] == ["NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 4090"]
    assert payload["gpuTypePriority"] == "custom"
    assert payload["allowedCudaVersions"] == ["12.8"]
    assert payload["interruptible"] is False
    assert payload["dataCenterIds"] == ["US-IL-1"]
    assert payload["dataCenterPriority"] == "custom"
    assert payload["networkVolumeId"] == "volume-123"
    assert payload["volumeMountPath"] == "/workspace"
    assert "containerRegistryAuthId" not in payload
    assert "volumeInGb" not in payload
    assert payload["env"]["MAX_RUNTIME_MIN"] == "90"
    assert payload["env"]["RUNPOD_RUN_MODEL_ID"] == "triposg"
    assert payload["env"]["RUNPOD_API_KEY"] == "token"
    assert payload["env"]["HF_HOME"] == "/workspace/hf"
    assert payload["env"]["HF_HUB_OFFLINE"] == "1"
    assert payload["env"]["TRANSFORMERS_OFFLINE"] == "1"
    assert payload["env"]["TRIPOSG_WEIGHTS_PATH"] == "/workspace/weights/TripoSG"
    assert payload["env"]["RMBG_WEIGHTS_PATH"] == "/workspace/weights/RMBG-1.4"
    assert payload["env"]["R2_ENDPOINT"] == "https://example.r2.cloudflarestorage.com"
    assert payload["env"]["R2_ACCESS_KEY_ID"] == "access-key"
    assert payload["env"]["R2_SECRET_ACCESS_KEY"] == "secret-key"
    assert payload["dockerEntrypoint"] == ["bash", "-lc"]
    assert "bench_harness.cli upload-s3" in payload["dockerStartCmd"][0]


def test_build_pod_payload_uses_container_registry_auth_id_when_provided() -> None:
    payload = build_pod_payload(
        RunPodLaunchConfig(
            name="3dgen-triposg-wave1",
            image_name="ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc",
            model_id="triposg",
            s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
            max_runtime_min=90,
            gpu_type_ids=("NVIDIA GeForce RTX 5090",),
            allowed_cuda_versions=("12.8",),
            r2_credentials=make_r2_credentials(),
            container_registry_auth_id="cmrc1l2gc00847uotrnjn2des",
            network_volume_id="volume-123",
            data_center_id="US-IL-1",
            startup_timeout_min=10,
        ),
        runpod_api_key="token",
    )

    assert payload["containerRegistryAuthId"] == "cmrc1l2gc00847uotrnjn2des"


def test_build_pod_payload_rejects_empty_container_registry_auth_id() -> None:
    with pytest.raises(ValueError, match="container_registry_auth_id"):
        build_pod_payload(
            RunPodLaunchConfig(
                name="3dgen-triposg-wave1",
                image_name="ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc",
                model_id="triposg",
                s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
                max_runtime_min=90,
                gpu_type_ids=("NVIDIA GeForce RTX 5090",),
                allowed_cuda_versions=("12.8",),
                r2_credentials=make_r2_credentials(),
                container_registry_auth_id=" ",
                network_volume_id="volume-123",
                data_center_id="US-IL-1",
                startup_timeout_min=10,
            ),
            runpod_api_key="token",
        )


def test_build_pod_payload_rejects_empty_network_volume_id() -> None:
    with pytest.raises(ValueError, match="network_volume_id"):
        build_pod_payload(
            RunPodLaunchConfig(
                name="3dgen-triposg-wave1",
                image_name="ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc",
                model_id="triposg",
                s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
                max_runtime_min=90,
                gpu_type_ids=("NVIDIA GeForce RTX 5090",),
                allowed_cuda_versions=("12.8",),
                r2_credentials=make_r2_credentials(),
                network_volume_id=" ",
                data_center_id="US-IL-1",
                startup_timeout_min=10,
            ),
            runpod_api_key="token",
        )


def test_build_pod_payload_rejects_empty_data_center_id() -> None:
    with pytest.raises(ValueError, match="data_center_id"):
        build_pod_payload(
            RunPodLaunchConfig(
                name="3dgen-triposg-wave1",
                image_name="ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc",
                model_id="triposg",
                s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
                max_runtime_min=90,
                gpu_type_ids=("NVIDIA GeForce RTX 5090",),
                allowed_cuda_versions=("12.8",),
                r2_credentials=make_r2_credentials(),
                network_volume_id="volume-123",
                data_center_id=" ",
                startup_timeout_min=10,
            ),
            runpod_api_key="token",
        )


def test_build_pod_payload_uses_partcrafter_volume_weight_paths() -> None:
    payload = build_pod_payload(
        RunPodLaunchConfig(
            name="3dgen-partcrafter-wave1",
            image_name="ghcr.io/hitsuki-ban/3dgen-partcrafter@sha256:abc",
            model_id="partcrafter",
            s3_target="s3://3dgen-runs/runs/partcrafter/rtx-5090/20260708T000000Z",
            max_runtime_min=90,
            gpu_type_ids=("NVIDIA GeForce RTX 5090",),
            allowed_cuda_versions=("12.8",),
            r2_credentials=make_r2_credentials(),
            network_volume_id="volume-123",
            data_center_id="US-IL-1",
            startup_timeout_min=10,
        ),
        runpod_api_key="token",
    )

    assert payload["env"]["PARTCRAFTER_WEIGHTS_PATH"] == "/workspace/weights/PartCrafter"
    assert payload["env"]["RMBG_WEIGHTS_PATH"] == "/workspace/weights/RMBG-1.4"
    assert "TRIPOSG_WEIGHTS_PATH" not in payload["env"]


def test_r2_credentials_are_loaded_from_explicit_env() -> None:
    credentials = R2Credentials.from_env(
        {
            "R2_ENDPOINT": "https://example.r2.cloudflarestorage.com",
            "R2_ACCESS_KEY_ID": "access-key",
            "R2_SECRET_ACCESS_KEY": "secret-key",
        }
    )

    assert credentials == make_r2_credentials()


def test_r2_credentials_fail_fast_when_env_is_missing() -> None:
    with pytest.raises(ValueError, match="R2_SECRET_ACCESS_KEY"):
        R2Credentials.from_env(
            {
                "R2_ENDPOINT": "https://example.r2.cloudflarestorage.com",
                "R2_ACCESS_KEY_ID": "access-key",
            }
        )


def test_cloud_launcher_defaults_are_issue_25_values() -> None:
    assert DEFAULT_MIN_BALANCE_USD == 5.0
    assert DEFAULT_MAX_RUNTIME_MIN == 90
    assert DEFAULT_GPU_TYPE_IDS == ("NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 4090")
    assert DEFAULT_ALLOWED_CUDA_VERSIONS == ("12.8",)


def test_runpod_client_checks_balance_before_creating_pod() -> None:
    calls = []

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None) -> dict[str, object]:
        calls.append((method, url, headers, body))
        if url == "https://api.runpod.io/graphql":
            return {"data": {"myself": {"clientBalance": 20.0}}}
        if url == "https://rest.runpod.io/v1/pods":
            return {"id": "pod-123", "desiredStatus": "RUNNING"}
        if url == "https://rest.runpod.io/v1/pods/pod-123":
            return {
                "id": "pod-123",
                "publicIp": "100.65.0.119",
                "portMappings": {"22": 22001},
                "desiredStatus": "RUNNING",
            }
        raise AssertionError(url)

    client = RunPodClient(api_key="token", request_json=fake_request, tcp_connect=lambda host, port, timeout: True)
    pod = client.launch_pod(
        RunPodLaunchConfig(
            name="3dgen-triposg-wave1",
            image_name="ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc",
            model_id="triposg",
            s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
            max_runtime_min=90,
            gpu_type_ids=("NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 4090"),
            allowed_cuda_versions=("12.8",),
            r2_credentials=make_r2_credentials(),
            network_volume_id="volume-123",
            data_center_id="US-IL-1",
            startup_timeout_min=10,
            startup_poll_seconds=0,
        ),
        min_balance_usd=5.0,
    )

    assert pod == {
        "id": "pod-123",
        "publicIp": "100.65.0.119",
        "portMappings": {"22": 22001},
        "desiredStatus": "RUNNING",
    }
    assert calls[0][0:2] == ("POST", "https://api.runpod.io/graphql")
    assert calls[1][0:2] == ("POST", "https://rest.runpod.io/v1/pods")
    assert calls[2][0:2] == ("GET", "https://rest.runpod.io/v1/pods/pod-123")
    assert calls[0][2] == {"Authorization": "Bearer token"}
    assert calls[1][2] == {"Authorization": "Bearer token"}
    assert calls[1][3]["env"]["RUNPOD_API_KEY"] == "token"
    assert calls[1][3]["env"]["R2_ENDPOINT"] == "https://example.r2.cloudflarestorage.com"


def test_runpod_client_waits_for_ssh_port_before_startup_ready() -> None:
    calls = []
    tcp_checks = []

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None) -> dict[str, object]:
        calls.append((method, url, headers, body))
        if url == "https://api.runpod.io/graphql":
            return {"data": {"myself": {"clientBalance": 20.0}}}
        if url == "https://rest.runpod.io/v1/pods":
            return {"id": "pod-123", "desiredStatus": "RUNNING"}
        if url == "https://rest.runpod.io/v1/pods/pod-123":
            return {"id": "pod-123", "publicIp": "203.0.113.10", "portMappings": {"22": 22001}}
        raise AssertionError(url)

    def fake_tcp_connect(host: str, port: int, timeout_seconds: float) -> bool:
        tcp_checks.append((host, port, timeout_seconds))
        return len(tcp_checks) > 1

    client = RunPodClient(api_key="token", request_json=fake_request, tcp_connect=fake_tcp_connect)
    pod = client.launch_pod(
        RunPodLaunchConfig(
            name="3dgen-triposg-wave1",
            image_name="ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc",
            model_id="triposg",
            s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
            max_runtime_min=90,
            gpu_type_ids=("NVIDIA GeForce RTX 4090",),
            allowed_cuda_versions=("12.8",),
            r2_credentials=make_r2_credentials(),
            network_volume_id="volume-123",
            data_center_id="EU-RO-1",
            startup_timeout_min=10,
            startup_poll_seconds=0,
        ),
        min_balance_usd=5.0,
    )

    assert pod == {"id": "pod-123", "publicIp": "203.0.113.10", "portMappings": {"22": 22001}}
    assert tcp_checks == [("203.0.113.10", 22001, 5.0), ("203.0.113.10", 22001, 5.0)]
    assert [call[0:2] for call in calls].count(("GET", "https://rest.runpod.io/v1/pods/pod-123")) == 2


def test_runpod_client_reports_pod_disappearing_before_startup(monkeypatch) -> None:
    calls = []

    def fake_sleep(seconds: float) -> None:
        calls.append(("SLEEP", seconds, {}, None))

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None) -> dict[str, object]:
        calls.append((method, url, headers, body))
        if url == "https://api.runpod.io/graphql":
            return {"data": {"myself": {"clientBalance": 20.0}}}
        if method == "POST" and url == "https://rest.runpod.io/v1/pods":
            return {"id": "pod-123", "desiredStatus": "RUNNING"}
        if method == "GET" and url == "https://rest.runpod.io/v1/pods/pod-123":
            get_count = [call[0:2] for call in calls].count(("GET", "https://rest.runpod.io/v1/pods/pod-123"))
            if get_count == 1:
                return {"id": "pod-123", "publicIp": "203.0.113.10", "portMappings": {"22": 22001}}
            raise RunPodApiError(
                method="GET",
                url=url,
                status_code=404,
                reason="Not Found",
                response_body='{"error":"pod not found","status":404}',
            )
        raise AssertionError((method, url))

    monkeypatch.setattr("bench_harness.runpod.time.sleep", fake_sleep)

    client = RunPodClient(
        api_key="token",
        request_json=fake_request,
        tcp_connect=lambda host, port, timeout_seconds: False,
    )

    with pytest.raises(RuntimeError, match="disappeared before startup"):
        client.launch_pod(
            RunPodLaunchConfig(
                name="3dgen-triposg-wave1",
                image_name="ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc",
                model_id="triposg",
                s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
                max_runtime_min=90,
                gpu_type_ids=("NVIDIA GeForce RTX 4090",),
                allowed_cuda_versions=("12.8",),
                r2_credentials=make_r2_credentials(),
                network_volume_id="volume-123",
                data_center_id="EU-RO-1",
                startup_timeout_min=10,
                startup_poll_seconds=15,
            ),
            min_balance_usd=5.0,
        )

    assert [call[0:2] for call in calls] == [
        ("POST", "https://api.runpod.io/graphql"),
        ("POST", "https://rest.runpod.io/v1/pods"),
        ("GET", "https://rest.runpod.io/v1/pods/pod-123"),
        ("SLEEP", 15),
        ("GET", "https://rest.runpod.io/v1/pods/pod-123"),
    ]


def test_runpod_client_terminates_pod_when_startup_watchdog_expires(monkeypatch) -> None:
    calls = []
    clock = iter([0.0, 0.0, 601.0])

    def fake_monotonic() -> float:
        return next(clock)

    def fake_sleep(seconds: float) -> None:
        calls.append(("SLEEP", seconds, {}, None))

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None) -> dict[str, object]:
        calls.append((method, url, headers, body))
        if url == "https://api.runpod.io/graphql":
            return {"data": {"myself": {"clientBalance": 20.0}}}
        if method == "POST" and url == "https://rest.runpod.io/v1/pods":
            return {"id": "pod-123", "desiredStatus": "RUNNING"}
        if method == "GET" and url == "https://rest.runpod.io/v1/pods/pod-123":
            return {"id": "pod-123", "publicIp": "", "desiredStatus": "RUNNING"}
        if method == "DELETE" and url == "https://rest.runpod.io/v1/pods/pod-123":
            return {}
        raise AssertionError((method, url))

    monkeypatch.setattr("bench_harness.runpod.time.monotonic", fake_monotonic)
    monkeypatch.setattr("bench_harness.runpod.time.sleep", fake_sleep)

    client = RunPodClient(api_key="token", request_json=fake_request)

    with pytest.raises(TimeoutError, match="reachable SSH port"):
        client.launch_pod(
            RunPodLaunchConfig(
                name="3dgen-triposg-wave1",
                image_name="ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc",
                model_id="triposg",
                s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
                max_runtime_min=90,
                gpu_type_ids=("NVIDIA GeForce RTX 5090",),
                allowed_cuda_versions=("12.8",),
                r2_credentials=make_r2_credentials(),
                network_volume_id="volume-123",
                data_center_id="US-IL-1",
                startup_timeout_min=10,
                startup_poll_seconds=15,
            ),
            min_balance_usd=5.0,
        )

    assert calls[-1][0:2] == ("DELETE", "https://rest.runpod.io/v1/pods/pod-123")


def test_runpod_client_terminates_pod_idempotently() -> None:
    calls = []

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None) -> dict[str, object]:
        calls.append((method, url, headers, body))
        return {"id": "pod-123", "deleted": True}

    client = RunPodClient(api_key="token", request_json=fake_request)

    assert client.terminate_pod("pod-123") == {"id": "pod-123", "deleted": True}
    assert calls == [
        ("DELETE", "https://rest.runpod.io/v1/pods/pod-123", {"Authorization": "Bearer token"}, None)
    ]


def test_request_json_accepts_runpod_list_response(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            pass

        def read(self) -> bytes:
            return b"[]"

    def fake_urlopen(request, timeout: int):
        return FakeResponse()

    monkeypatch.setattr("bench_harness.runpod.urlopen", fake_urlopen)

    assert request_json("GET", "https://rest.runpod.io/v1/pods", {"Authorization": "Bearer token"}, None) == []


def test_request_json_includes_runpod_error_body(monkeypatch) -> None:
    class FakeErrorBody:
        def read(self) -> bytes:
            return b'{"error":"create pod: There are no instances currently available","status":500}\n'

        def close(self) -> None:
            pass

    def fake_urlopen(request, timeout: int):
        raise HTTPError(
            url=request.full_url,
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=FakeErrorBody(),
        )

    monkeypatch.setattr("bench_harness.runpod.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="There are no instances currently available"):
        request_json("POST", "https://rest.runpod.io/v1/pods", {"Authorization": "Bearer token"}, {})


def test_request_json_sends_harness_user_agent(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            pass

        def read(self) -> bytes:
            return b"{}"

    def fake_urlopen(request, timeout: int):
        captured["user_agent"] = request.get_header("User-agent")
        return FakeResponse()

    monkeypatch.setattr("bench_harness.runpod.urlopen", fake_urlopen)

    request_json("POST", "https://api.runpod.io/graphql", {"Authorization": "Bearer token"}, {"query": "{}"})

    assert captured["user_agent"] == "3dgen-demoroom-bench-harness/0.1"
