import pytest

from bench_harness.runpod import (
    DEFAULT_ALLOWED_CUDA_VERSIONS,
    DEFAULT_GPU_TYPE_IDS,
    DEFAULT_MAX_RUNTIME_MIN,
    DEFAULT_MIN_BALANCE_USD,
    R2Credentials,
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
    assert "containerRegistryAuthId" not in payload
    assert payload["env"]["MAX_RUNTIME_MIN"] == "90"
    assert payload["env"]["RUNPOD_RUN_MODEL_ID"] == "triposg"
    assert payload["env"]["RUNPOD_API_KEY"] == "token"
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
            ),
            runpod_api_key="token",
        )


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
        raise AssertionError(url)

    client = RunPodClient(api_key="token", request_json=fake_request)
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
        ),
        min_balance_usd=5.0,
    )

    assert pod == {"id": "pod-123", "desiredStatus": "RUNNING"}
    assert calls[0][0:2] == ("POST", "https://api.runpod.io/graphql")
    assert calls[1][0:2] == ("POST", "https://rest.runpod.io/v1/pods")
    assert calls[0][2] == {"Authorization": "Bearer token"}
    assert calls[1][2] == {"Authorization": "Bearer token"}
    assert calls[1][3]["env"]["RUNPOD_API_KEY"] == "token"
    assert calls[1][3]["env"]["R2_ENDPOINT"] == "https://example.r2.cloudflarestorage.com"


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
