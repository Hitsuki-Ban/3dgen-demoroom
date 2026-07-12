import pytest
import shlex
from datetime import datetime, timezone
from urllib.error import HTTPError

from bench_harness.runpod import (
    DEFAULT_ALLOWED_CUDA_VERSIONS,
    DEFAULT_GPU_TYPE_IDS,
    DEFAULT_MAX_RUNTIME_MIN,
    DEFAULT_MIN_BALANCE_USD,
    MODEL_RUNNER_PATHS,
    MODEL_WEIGHT_ENVS,
    RUNPOD_TELEMETRY_ROOT,
    R2Credentials,
    RunPodApiError,
    RunPodClient,
    RunPodBalanceCheck,
    RunPodLaunchConfig,
    build_balance_query,
    build_cloud_run_command,
    build_create_pod_request,
    build_pod_payload,
    build_terminate_after,
    parse_create_pod_response,
    parse_client_balance,
    request_json,
)


def make_r2_credentials() -> R2Credentials:
    return R2Credentials(
        endpoint="https://example.r2.cloudflarestorage.com",
        access_key_id="access-key",
        secret_access_key="secret-key",
    )


def make_launch_config(*, startup_poll_seconds: float = 0) -> RunPodLaunchConfig:
    return RunPodLaunchConfig(
        name="3dgen-triposg-test",
        image_name="ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc",
        model_id="triposg",
        s3_target="s3://3dgen-runs/runs/triposg/test/20260711T000000Z",
        max_runtime_min=90,
        gpu_type_ids=("NVIDIA GeForce RTX 4090",),
        allowed_cuda_versions=("12.8",),
        r2_credentials=make_r2_credentials(),
        network_volume_id="volume-123",
        data_center_id="EU-RO-1",
        startup_timeout_min=10,
        startup_poll_seconds=startup_poll_seconds,
    )


def graphql_create_response(pod_id: str = "pod-123") -> dict[str, object]:
    return {"data": {"podFindAndDeployOnDemand": {"id": pod_id, "desiredStatus": "RUNNING"}}}


def graphql_response_for(body: dict[str, object] | None, *, balance: float = 20.0) -> dict[str, object]:
    assert body is not None
    query = body["query"]
    assert isinstance(query, str)
    if "CurrentUserBalance" in query:
        return {"data": {"myself": {"clientBalance": balance}}}
    if "CreateBenchmarkPod" in query:
        return graphql_create_response()
    raise AssertionError(query)


def payload_env(payload: dict[str, object]) -> dict[str, str]:
    raw_env = payload["env"]
    assert isinstance(raw_env, list)
    return {item["key"]: item["value"] for item in raw_env}


class FakeOwnershipCoordinator:
    def __init__(
        self,
        *,
        handoff_error: BaseException | None = None,
        cleanup_claimed: bool = True,
        cleanup_error: BaseException | None = None,
    ) -> None:
        self.events = []
        self.handoff_error = handoff_error
        self.cleanup_claimed = cleanup_claimed
        self.cleanup_error = cleanup_error

    def initialize(self, target, lifecycle_token, env) -> None:
        self.events.append(("initialize", target, lifecycle_token, env))

    def handoff(self, target, pod_id, lifecycle_token, env, *, timeout_seconds, poll_seconds) -> None:
        assert timeout_seconds == 60.0
        assert poll_seconds == 1.0
        self.events.append(("handoff", target, pod_id, lifecycle_token, env))
        if self.handoff_error is not None:
            raise self.handoff_error

    def claim_cleanup(self, target, pod_id, lifecycle_token, env) -> bool:
        self.events.append(("claim_cleanup", target, pod_id, lifecycle_token, env))
        if self.cleanup_error is not None:
            raise self.cleanup_error
        return self.cleanup_claimed


WAVE2_MODELS = {
    "trellis1": {
        "runner": "/opt/3dgen-runner/trellis1_runner.py",
        "env": {"TRELLIS1_WEIGHTS_PATH": "/workspace/weights/TRELLIS-image-large"},
    },
    "3dtopia-xl": {
        "runner": "/opt/3dgen-runner/3dtopia_xl_runner.py",
        "env": {"TOPIA_XL_WEIGHTS_PATH": "/workspace/weights/3DTopia-XL"},
    },
    "trellis2": {
        "runner": "/opt/3dgen-runner/trellis2_runner.py",
        "env": {"TRELLIS2_WEIGHTS_PATH": "/workspace/weights/TRELLIS.2-4B"},
    },
    "direct3d-s2": {
        "runner": "/opt/3dgen-runner/direct3d_s2_runner.py",
        "env": {"DIRECT3D_S2_WEIGHTS_PATH": "/workspace/weights/Direct3D-S2"},
    },
    "step1x-3d": {
        "runner": "/opt/3dgen-runner/step1x_3d_runner.py",
        "env": {"STEP1X_3D_WEIGHTS_PATH": "/workspace/weights/Step1X-3D"},
    },
    "pixal3d": {
        "runner": "/opt/3dgen-runner/pixal3d_runner.py",
        "env": {"PIXAL3D_WEIGHTS_PATH": "/workspace/weights/Pixal3D"},
    },
    "hunyuan3d-21": {
        "runner": "/opt/3dgen-runner/hunyuan3d_21_runner.py",
        "env": {"HUNYUAN3D_21_WEIGHTS_PATH": "/workspace/weights/Hunyuan3D-2.1"},
    },
    "sf3d": {
        "runner": "/opt/3dgen-runner/sf3d_runner.py",
        "env": {"SF3D_WEIGHTS_PATH": "/workspace/weights/stable-fast-3d"},
    },
}


def test_build_balance_query_requests_client_balance() -> None:
    check = RunPodBalanceCheck(api_key="token", min_balance_usd=10.0)

    assert check.endpoint == "https://api.runpod.io/graphql"
    assert check.headers == {"Authorization": "Bearer token"}
    assert "clientBalance" in build_balance_query()


def test_graphql_create_request_wraps_payload_in_typed_mutation() -> None:
    payload = {"name": "benchmark", "terminateAfter": "2026-07-11T02:10:00Z"}

    request = build_create_pod_request(payload)

    assert "PodFindAndDeployOnDemandInput" in request["query"]
    assert request["variables"] == {"input": payload}


def test_server_hard_termination_covers_startup_runtime_and_evidence_grace() -> None:
    deadline = build_terminate_after(
        make_launch_config(),
        now=datetime(2026, 7, 11, tzinfo=timezone.utc),
    )

    assert deadline == "2026-07-11T02:10:00Z"


def test_server_hard_termination_rejects_naive_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_terminate_after(make_launch_config(), now=datetime(2026, 7, 11))


def test_graphql_create_response_is_strict_and_surfaces_api_error() -> None:
    assert parse_create_pod_response(graphql_create_response()) == {
        "id": "pod-123",
        "desiredStatus": "RUNNING",
    }

    with pytest.raises(RuntimeError, match="no capacity"):
        parse_create_pod_response({"errors": [{"message": "no capacity"}]})


def test_parse_client_balance_rejects_under_threshold() -> None:
    response = {"data": {"myself": {"clientBalance": 7.5}}}

    with pytest.raises(RuntimeError, match="below threshold"):
        parse_client_balance(response, min_balance_usd=10.0)


def test_parse_client_balance_accepts_enough_balance() -> None:
    response = {"data": {"myself": {"clientBalance": 12.0}}}

    assert parse_client_balance(response, min_balance_usd=10.0) == 12.0


def test_build_cloud_run_command_passes_model_and_evidence_target_to_runtime() -> None:
    command = build_cloud_run_command(
        model_id="triposg",
        output_root="/work/output",
        s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
    )

    assert command.startswith("runpod ")
    assert "--input-root /opt/3dgen-tasks" in command
    assert "--output-root /work/output" in command
    assert f"--telemetry-root {RUNPOD_TELEMETRY_ROOT}" in command
    assert "bench_harness.cli upload-s3" not in command
    assert "s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z" in command


@pytest.mark.parametrize(
    "output_root",
    [RUNPOD_TELEMETRY_ROOT, "/work", f"{RUNPOD_TELEMETRY_ROOT}/tasks"],
)
def test_build_cloud_run_command_rejects_output_and_telemetry_root_overlap(
    output_root: str,
) -> None:
    with pytest.raises(ValueError, match="must not equal, contain, or be contained"):
        build_cloud_run_command(
            model_id="triposg",
            output_root=output_root,
            s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
        )


@pytest.mark.parametrize(
    "output_root",
    [
        "/work/output/.",
        "/work/output/../runpod-telemetry",
        "//work/runpod-telemetry",
        "/work/output//task",
        "/work/output/",
    ],
)
def test_build_cloud_run_command_rejects_noncanonical_output_root(
    output_root: str,
) -> None:
    with pytest.raises(ValueError, match="canonical absolute POSIX path"):
        build_cloud_run_command(
            model_id="triposg",
            output_root=output_root,
            s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
        )


def test_build_cloud_run_command_rejects_relative_output_root() -> None:
    with pytest.raises(ValueError, match="absolute POSIX path"):
        build_cloud_run_command(
            model_id="triposg",
            output_root="outputs",
            s3_target="s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
        )


def test_build_cloud_run_command_passes_task_limit_to_runner() -> None:
    command = build_cloud_run_command(
        model_id="direct3d-s2",
        output_root="/work/output",
        s3_target="s3://3dgen-runs/runs/direct3d-s2/wave2/20260709T000000Z",
        task_limit=3,
    )

    assert "--task-limit 3" in command


def test_build_cloud_run_command_rejects_nonpositive_task_limit() -> None:
    with pytest.raises(ValueError, match="task_limit"):
        build_cloud_run_command(
            model_id="direct3d-s2",
            output_root="/work/output",
            s3_target="s3://3dgen-runs/runs/direct3d-s2/wave2/20260709T000000Z",
            task_limit=0,
        )


def test_build_cloud_run_command_passes_exact_task_ids_to_runner() -> None:
    command = build_cloud_run_command(
        model_id="trellis2",
        output_root="/work/output",
        s3_target="s3://3dgen-runs/runs/trellis2/retry/20260710T000000Z",
        task_ids=("fluffy-monster-plush", "cartoon apple"),
    )

    assert "--task-id fluffy-monster-plush" in command
    assert "--task-id 'cartoon apple'" in command


def test_build_cloud_run_command_passes_explicit_pixal3d_retry_count() -> None:
    command = build_cloud_run_command(
        model_id="pixal3d",
        output_root="/work/output",
        s3_target="s3://3dgen-runs/runs/pixal3d/wave2-retry/20260711T000000Z",
        task_ids=("ornate-treasure-chest", "old-oak-tree"),
        retry_count=1,
    )

    assert "--task-id ornate-treasure-chest" in command
    assert "--task-id old-oak-tree" in command
    assert "--retry-count 1" in command


@pytest.mark.parametrize(
    ("model_id", "task_ids", "retry_count", "message"),
    [
        ("pixal3d", ("old-oak-tree",), -1, "must not be negative"),
        ("pixal3d", (), 1, "requires exact task_ids"),
        ("trellis2", ("fluffy-monster-plush",), 1, "not supported for model"),
    ],
)
def test_build_cloud_run_command_rejects_invalid_retry_count(
    model_id: str,
    task_ids: tuple[str, ...],
    retry_count: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_cloud_run_command(
            model_id=model_id,
            output_root="/work/output",
            s3_target=f"s3://3dgen-runs/runs/{model_id}/retry/20260711T000000Z",
            task_ids=task_ids,
            retry_count=retry_count,
        )


@pytest.mark.parametrize(
    ("task_limit", "task_ids", "message"),
    [
        (1, ("fluffy-monster-plush",), "mutually exclusive"),
        (None, ("",), "empty"),
        (None, ("fluffy-monster-plush", "fluffy-monster-plush"), "duplicates"),
    ],
)
def test_build_cloud_run_command_rejects_invalid_task_selection(
    task_limit: int | None,
    task_ids: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_cloud_run_command(
            model_id="trellis2",
            output_root="/work/output",
            s3_target="s3://3dgen-runs/runs/trellis2/retry/20260710T000000Z",
            task_limit=task_limit,
            task_ids=task_ids,
        )


def test_build_cloud_run_command_rejects_task_ids_for_unsupported_runner() -> None:
    with pytest.raises(ValueError, match="not supported for model"):
        build_cloud_run_command(
            model_id="step1x-3d",
            output_root="/work/output",
            s3_target="s3://3dgen-runs/runs/step1x-3d/retry/20260710T000000Z",
            task_ids=("cartoon-apple",),
        )


def test_build_cloud_run_command_delegates_the_complete_lifecycle_to_runtime_owner() -> None:
    command = build_cloud_run_command(
        model_id="triposg",
        output_root="/work/output",
        s3_target="s3://3dgen-runs/runs/triposg/wave1/20260708T000000Z",
    )

    assert command.startswith("runpod")
    assert "--output-root /work/output" in command
    assert f"--telemetry-root {RUNPOD_TELEMETRY_ROOT}" in command
    assert "--s3-target s3://3dgen-runs/runs/triposg/wave1/20260708T000000Z" in command
    assert "-- --input-root /opt/3dgen-tasks" in command
    assert "bench_harness.cli upload-s3" not in command
    assert "https://rest.runpod.io/v1/pods/" not in command
    assert "PYTHONPATH=" not in command


def test_build_cloud_run_command_is_valid_container_entrypoint_arguments() -> None:
    command = build_cloud_run_command(
        model_id="triposg",
        output_root="/work/output",
        s3_target="s3://3dgen-runs/runs/triposg/wave1/20260708T000000Z",
    )

    assert shlex.split(command) == [
        "runpod",
        "--output-root",
        "/work/output",
        "--telemetry-root",
        RUNPOD_TELEMETRY_ROOT,
        "--s3-target",
        "s3://3dgen-runs/runs/triposg/wave1/20260708T000000Z",
        "--",
        "--input-root",
        "/opt/3dgen-tasks",
        "--output-root",
        "/work/output",
    ]


def test_build_cloud_run_command_rejects_unknown_model() -> None:
    with pytest.raises(ValueError, match="unknown model"):
        build_cloud_run_command(
            model_id="unknown",
            output_root="/work/output",
            s3_target="s3://3dgen-runs/runs/unknown",
        )


@pytest.mark.parametrize("model_id,expected", WAVE2_MODELS.items())
def test_wave2_models_have_cloud_runner_paths(model_id: str, expected: dict[str, object]) -> None:
    command = build_cloud_run_command(
        model_id=model_id,
        output_root="/work/output",
        s3_target=f"s3://3dgen-runs/runs/{model_id}/wave2/20260709T000000Z",
    )

    assert MODEL_RUNNER_PATHS[model_id] == expected["runner"]
    assert "--input-root /opt/3dgen-tasks" in command
    assert "--output-root /work/output" in command


@pytest.mark.parametrize("model_id,expected", WAVE2_MODELS.items())
def test_wave2_models_have_explicit_volume_weight_env(model_id: str, expected: dict[str, object]) -> None:
    payload = build_pod_payload(
        RunPodLaunchConfig(
            name=f"3dgen-{model_id}-wave2",
            image_name=f"ghcr.io/hitsuki-ban/3dgen-{model_id}-runtime:wave2",
            model_id=model_id,
            s3_target=f"s3://3dgen-runs/runs/{model_id}/wave2/20260709T000000Z",
            max_runtime_min=90,
            gpu_type_ids=("NVIDIA GeForce RTX 4090",),
            allowed_cuda_versions=("12.8",),
            r2_credentials=make_r2_credentials(),
            network_volume_id="volume-123",
            data_center_id="EU-RO-1",
            startup_timeout_min=10,
        ),
        runpod_api_key="token",
        lifecycle_token="handoff-token",
        terminate_after="2026-07-11T02:10:00Z",
    )

    env = payload_env(payload)
    assert MODEL_WEIGHT_ENVS[model_id] == expected["env"]
    for name, value in expected["env"].items():
        assert env[name] == value
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["TORCH_HOME"] == "/workspace/torch"
    assert env["U2NET_HOME"] == "/workspace/weights/rembg"


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
            task_limit=2,
        ),
        runpod_api_key="token",
        lifecycle_token="handoff-token",
        terminate_after="2026-07-11T02:10:00Z",
    )

    env = payload_env(payload)
    assert payload["name"] == "3dgen-triposg-wave1"
    assert payload["imageName"] == "ghcr.io/hitsuki-ban/3dgen-triposg@sha256:abc"
    assert payload["cloudType"] == "SECURE"
    assert payload["computeType"] == "GPU"
    assert payload["gpuTypeIdList"] == ["NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 4090"]
    assert payload["allowedCudaVersions"] == ["12.8"]
    assert payload["dataCenterId"] == "US-IL-1"
    assert payload["networkVolumeId"] == "volume-123"
    assert payload["volumeMountPath"] == "/workspace"
    assert "containerRegistryAuthId" not in payload
    assert "volumeInGb" not in payload
    assert env["MAX_RUNTIME_MIN"] == "90"
    assert env["RUNPOD_RUN_MODEL_ID"] == "triposg"
    assert env["RUNPOD_API_KEY"] == "token"
    assert env["RUNPOD_LIFECYCLE_TOKEN"] == "handoff-token"
    assert env["RUNPOD_HANDOFF_TIMEOUT_SECONDS"] == "600"
    assert env["HF_HOME"] == "/workspace/hf"
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["TORCH_HOME"] == "/workspace/torch"
    assert env["U2NET_HOME"] == "/workspace/weights/rembg"
    assert env["RUNPOD_INCREMENTAL_S3_TARGET"] == "s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z"
    assert env["TRIPOSG_WEIGHTS_PATH"] == "/workspace/weights/TripoSG"
    assert env["RMBG_WEIGHTS_PATH"] == "/workspace/weights/RMBG-1.4"
    assert env["R2_ENDPOINT"] == "https://example.r2.cloudflarestorage.com"
    assert env["R2_ACCESS_KEY_ID"] == "access-key"
    assert env["R2_SECRET_ACCESS_KEY"] == "secret-key"
    assert payload["dockerArgs"].startswith("runpod ")
    assert "--task-limit 2" in payload["dockerArgs"]
    assert payload["ports"] == "22/tcp"
    assert payload["startSsh"] is True
    assert payload["terminateAfter"] == "2026-07-11T02:10:00Z"


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
        lifecycle_token="handoff-token",
        terminate_after="2026-07-11T02:10:00Z",
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
            lifecycle_token="handoff-token",
            terminate_after="2026-07-11T02:10:00Z",
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
            lifecycle_token="handoff-token",
            terminate_after="2026-07-11T02:10:00Z",
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
            lifecycle_token="handoff-token",
            terminate_after="2026-07-11T02:10:00Z",
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
        lifecycle_token="handoff-token",
        terminate_after="2026-07-11T02:10:00Z",
    )

    env = payload_env(payload)
    assert env["PARTCRAFTER_WEIGHTS_PATH"] == "/workspace/weights/PartCrafter"
    assert env["RMBG_WEIGHTS_PATH"] == "/workspace/weights/RMBG-1.4"
    assert "TRIPOSG_WEIGHTS_PATH" not in env


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
    coordinator = FakeOwnershipCoordinator()

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None) -> dict[str, object]:
        calls.append((method, url, headers, body))
        if url == "https://api.runpod.io/graphql":
            return graphql_response_for(body)
        if url == "https://rest.runpod.io/v1/pods/pod-123":
            return {
                "id": "pod-123",
                "publicIp": "100.65.0.119",
                "portMappings": {"22": 22001},
                "desiredStatus": "RUNNING",
            }
        raise AssertionError(url)

    client = RunPodClient(
        api_key="token",
        request_json=fake_request,
        tcp_connect=lambda host, port, timeout: True,
        ownership_coordinator=coordinator,
        lifecycle_token_factory=lambda: "handoff-token",
        utc_now=lambda: datetime(2026, 7, 11, tzinfo=timezone.utc),
    )
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
    assert calls[1][0:2] == ("POST", "https://api.runpod.io/graphql")
    assert calls[2][0:2] == ("GET", "https://rest.runpod.io/v1/pods/pod-123")
    assert calls[0][2] == {"Authorization": "Bearer token"}
    assert calls[1][2] == {"Authorization": "Bearer token"}
    create_payload = calls[1][3]["variables"]["input"]
    create_env = payload_env(create_payload)
    assert create_env["RUNPOD_API_KEY"] == "token"
    assert create_env["RUNPOD_LIFECYCLE_TOKEN"] == "handoff-token"
    assert create_env["RUNPOD_HANDOFF_TIMEOUT_SECONDS"] == "600"
    assert create_env["R2_ENDPOINT"] == "https://example.r2.cloudflarestorage.com"
    assert create_payload["terminateAfter"] == "2026-07-11T02:10:00Z"
    assert [event[0] for event in coordinator.events] == ["initialize", "handoff"]
    assert coordinator.events[1][1:] == (
        "s3://3dgen-runs/runs/triposg/rtx-5090/20260708T000000Z",
        "pod-123",
        "handoff-token",
        make_r2_credentials().as_env(),
    )


def test_create_response_loss_still_sends_server_hard_termination_deadline() -> None:
    create_error = OSError("GraphQL response lost after pod creation")
    calls = []
    coordinator = FakeOwnershipCoordinator()

    def fake_request(method, url, headers, body):
        calls.append((method, url, headers, body))
        if "CurrentUserBalance" in body["query"]:
            return graphql_response_for(body)
        if "CreateBenchmarkPod" in body["query"]:
            raise create_error
        raise AssertionError(body)

    client = RunPodClient(
        api_key="token",
        request_json=fake_request,
        ownership_coordinator=coordinator,
        lifecycle_token_factory=lambda: "handoff-token",
        utc_now=lambda: datetime(2026, 7, 11, tzinfo=timezone.utc),
    )

    with pytest.raises(OSError) as caught:
        client.launch_pod(make_launch_config(), min_balance_usd=5.0)

    assert caught.value is create_error
    create_payload = calls[1][3]["variables"]["input"]
    assert create_payload["terminateAfter"] == "2026-07-11T02:10:00Z"
    assert [event[0] for event in coordinator.events] == ["initialize"]


def test_runpod_client_waits_for_ssh_port_before_startup_ready() -> None:
    calls = []
    tcp_checks = []
    coordinator = FakeOwnershipCoordinator()

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None) -> dict[str, object]:
        calls.append((method, url, headers, body))
        if url == "https://api.runpod.io/graphql":
            return graphql_response_for(body)
        if url == "https://rest.runpod.io/v1/pods/pod-123":
            return {"id": "pod-123", "publicIp": "203.0.113.10", "portMappings": {"22": 22001}}
        raise AssertionError(url)

    def fake_tcp_connect(host: str, port: int, timeout_seconds: float) -> bool:
        tcp_checks.append((host, port, timeout_seconds))
        return len(tcp_checks) > 1

    client = RunPodClient(
        api_key="token",
        request_json=fake_request,
        tcp_connect=fake_tcp_connect,
        ownership_coordinator=coordinator,
        lifecycle_token_factory=lambda: "handoff-token",
    )
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
    assert [event[0] for event in coordinator.events] == ["initialize", "handoff"]


def test_runpod_client_retains_ownership_when_runtime_handoff_cas_fails() -> None:
    calls = []
    handoff_error = OSError("R2 handoff publish failed")
    coordinator = FakeOwnershipCoordinator(handoff_error=handoff_error)

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None):
        calls.append((method, url))
        if url == "https://api.runpod.io/graphql":
            return graphql_response_for(body)
        if method == "GET" and url == "https://rest.runpod.io/v1/pods/pod-123":
            return {"id": "pod-123", "publicIp": "203.0.113.10", "portMappings": {"22": 22001}}
        if method == "DELETE" and url == "https://rest.runpod.io/v1/pods/pod-123":
            return {}
        raise AssertionError((method, url))

    client = RunPodClient(
        api_key="token",
        request_json=fake_request,
        tcp_connect=lambda host, port, timeout: True,
        ownership_coordinator=coordinator,
        lifecycle_token_factory=lambda: "handoff-token",
    )

    with pytest.raises(OSError) as caught:
        client.launch_pod(make_launch_config(), min_balance_usd=5.0)

    assert caught.value is handoff_error
    assert calls[-1] == ("DELETE", "https://rest.runpod.io/v1/pods/pod-123")
    assert [event[0] for event in coordinator.events] == ["initialize", "handoff", "claim_cleanup"]


@pytest.mark.parametrize(
    ("failure_mode", "expected_type", "message"),
    [
        ("http", RunPodApiError, "Internal Server Error"),
        ("json", ValueError, "JSON object"),
        ("tcp", LookupError, "tcp probe failed"),
    ],
)
def test_runpod_client_terminates_known_pod_on_every_startup_poll_failure(
    failure_mode: str,
    expected_type: type[BaseException],
    message: str,
) -> None:
    calls = []
    coordinator = FakeOwnershipCoordinator()

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None):
        calls.append((method, url, headers, body))
        if url == "https://api.runpod.io/graphql":
            return graphql_response_for(body)
        if method == "GET" and url == "https://rest.runpod.io/v1/pods/pod-123":
            if failure_mode == "http":
                raise RunPodApiError(
                    method="GET",
                    url=url,
                    status_code=500,
                    reason="Internal Server Error",
                    response_body='{"error":"temporary failure"}',
                )
            if failure_mode == "json":
                return []
            return {"id": "pod-123", "publicIp": "203.0.113.10", "portMappings": {"22": 22001}}
        if method == "DELETE" and url == "https://rest.runpod.io/v1/pods/pod-123":
            return {}
        raise AssertionError((method, url))

    def fake_tcp_connect(host: str, port: int, timeout_seconds: float) -> bool:
        if failure_mode == "tcp":
            raise LookupError("tcp probe failed")
        return True

    client = RunPodClient(
        api_key="token",
        request_json=fake_request,
        tcp_connect=fake_tcp_connect,
        ownership_coordinator=coordinator,
        lifecycle_token_factory=lambda: "handoff-token",
    )

    with pytest.raises(expected_type, match=message):
        client.launch_pod(make_launch_config(), min_balance_usd=5.0)

    assert [call[0:2] for call in calls][-1] == ("DELETE", "https://rest.runpod.io/v1/pods/pod-123")
    assert [call[0:2] for call in calls].count(("DELETE", "https://rest.runpod.io/v1/pods/pod-123")) == 1
    assert [event[0] for event in coordinator.events] == ["initialize", "claim_cleanup"]


def test_runpod_client_preserves_startup_error_when_termination_fails(capsys) -> None:
    primary_error = RunPodApiError(
        method="GET",
        url="https://rest.runpod.io/v1/pods/pod-123",
        status_code=500,
        reason="Internal Server Error",
        response_body='{"error":"temporary failure"}',
    )

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None):
        if url == "https://api.runpod.io/graphql":
            return graphql_response_for(body)
        if method == "GET" and url == "https://rest.runpod.io/v1/pods/pod-123":
            raise primary_error
        if method == "DELETE" and url == "https://rest.runpod.io/v1/pods/pod-123":
            raise RuntimeError("delete failed")
        raise AssertionError((method, url))

    client = RunPodClient(
        api_key="token",
        request_json=fake_request,
        ownership_coordinator=FakeOwnershipCoordinator(),
        lifecycle_token_factory=lambda: "handoff-token",
    )

    with pytest.raises(RunPodApiError) as caught:
        client.launch_pod(make_launch_config(), min_balance_usd=5.0)

    assert caught.value is primary_error
    report = capsys.readouterr().err
    assert "RUNPOD_CLEANUP_FAILED pod_id=pod-123" in report
    assert 'manual="runpodctl pod delete pod-123"' in report


def test_launcher_never_deletes_after_cleanup_cas_reports_owner_changed(capsys) -> None:
    coordinator = FakeOwnershipCoordinator(cleanup_claimed=False)

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None):
        if url == "https://api.runpod.io/graphql":
            return graphql_response_for(body)
        if method == "GET" and url == "https://rest.runpod.io/v1/pods/pod-123":
            raise RuntimeError("poll failed after runtime won ownership")
        if method == "DELETE":
            raise AssertionError("launcher that lost cleanup CAS must not delete")
        raise AssertionError((method, url))

    client = RunPodClient(
        api_key="token",
        request_json=fake_request,
        ownership_coordinator=coordinator,
        lifecycle_token_factory=lambda: "handoff-token",
    )

    with pytest.raises(RuntimeError, match="poll failed"):
        client.launch_pod(make_launch_config(), min_balance_usd=5.0)

    assert "RUNPOD_CLEANUP_SKIPPED pod_id=pod-123 owner_changed_or_uncertain=true" in capsys.readouterr().err


def test_launcher_cleanup_cas_outage_defers_to_server_deadline_without_racing_runtime(capsys) -> None:
    startup_error = RuntimeError("startup poll failed")
    coordinator = FakeOwnershipCoordinator(cleanup_error=OSError("R2 unavailable"))

    def fake_request(method, url, headers, body):
        if url == "https://api.runpod.io/graphql":
            return graphql_response_for(body)
        if method == "GET":
            raise startup_error
        if method == "DELETE":
            raise AssertionError("launcher without cleanup CAS must not race runtime cleanup")
        raise AssertionError((method, url))

    client = RunPodClient(
        api_key="token",
        request_json=fake_request,
        ownership_coordinator=coordinator,
        lifecycle_token_factory=lambda: "handoff-token",
        utc_now=lambda: datetime(2026, 7, 11, tzinfo=timezone.utc),
    )

    with pytest.raises(RuntimeError) as caught:
        client.launch_pod(make_launch_config(), min_balance_usd=5.0)

    assert caught.value is startup_error
    report = capsys.readouterr().err
    assert "RUNPOD_CLEANUP_FAILED pod_id=pod-123" in report
    assert "owner_changed_or_uncertain=true terminate_after=2026-07-11T02:10:00Z" in report


def test_runpod_client_reports_pod_disappearing_before_startup(monkeypatch) -> None:
    calls = []

    def fake_sleep(seconds: float) -> None:
        calls.append(("SLEEP", seconds, {}, None))

    def fake_request(method: str, url: str, headers: dict[str, str], body: dict[str, object] | None) -> dict[str, object]:
        calls.append((method, url, headers, body))
        if url == "https://api.runpod.io/graphql":
            return graphql_response_for(body)
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
        if method == "DELETE" and url == "https://rest.runpod.io/v1/pods/pod-123":
            return {}
        raise AssertionError((method, url))

    monkeypatch.setattr("bench_harness.runpod.time.sleep", fake_sleep)

    client = RunPodClient(
        api_key="token",
        request_json=fake_request,
        tcp_connect=lambda host, port, timeout_seconds: False,
        ownership_coordinator=FakeOwnershipCoordinator(),
        lifecycle_token_factory=lambda: "handoff-token",
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
        ("POST", "https://api.runpod.io/graphql"),
        ("GET", "https://rest.runpod.io/v1/pods/pod-123"),
        ("SLEEP", 15),
        ("GET", "https://rest.runpod.io/v1/pods/pod-123"),
        ("DELETE", "https://rest.runpod.io/v1/pods/pod-123"),
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
            return graphql_response_for(body)
        if method == "GET" and url == "https://rest.runpod.io/v1/pods/pod-123":
            return {"id": "pod-123", "publicIp": "", "desiredStatus": "RUNNING"}
        if method == "DELETE" and url == "https://rest.runpod.io/v1/pods/pod-123":
            return {}
        raise AssertionError((method, url))

    monkeypatch.setattr("bench_harness.runpod.time.monotonic", fake_monotonic)
    monkeypatch.setattr("bench_harness.runpod.time.sleep", fake_sleep)

    client = RunPodClient(
        api_key="token",
        request_json=fake_request,
        ownership_coordinator=FakeOwnershipCoordinator(),
        lifecycle_token_factory=lambda: "handoff-token",
    )

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


def test_runpod_client_retries_delete_transport_failures(monkeypatch) -> None:
    attempts = 0
    sleeps = []

    def fake_request(method, url, headers, body):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("delete response lost")
        return {}

    monkeypatch.setattr("bench_harness.runpod.time.sleep", sleeps.append)

    assert RunPodClient(api_key="token", request_json=fake_request).terminate_pod("pod-123") == {}
    assert attempts == 3
    assert sleeps == [1.0, 1.0]


def test_runpod_client_treats_not_found_after_delete_response_loss_as_terminated(monkeypatch) -> None:
    attempts = 0

    def fake_request(method, url, headers, body):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("delete response lost")
        raise RunPodApiError(
            method="DELETE",
            url=url,
            status_code=404,
            reason="Not Found",
            response_body='{"error":"pod not found"}',
        )

    monkeypatch.setattr("bench_harness.runpod.time.sleep", lambda seconds: None)

    assert RunPodClient(api_key="token", request_json=fake_request).terminate_pod("pod-123") == {}
    assert attempts == 2


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


def test_request_json_accepts_empty_runpod_delete_response(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            pass

        def read(self) -> bytes:
            return b""

    monkeypatch.setattr("bench_harness.runpod.urlopen", lambda request, timeout: FakeResponse())

    assert request_json(
        "DELETE",
        "https://rest.runpod.io/v1/pods/pod-123",
        {"Authorization": "Bearer token"},
        None,
    ) == {}


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
