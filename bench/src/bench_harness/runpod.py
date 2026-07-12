from __future__ import annotations

import json
import secrets
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from shlex import quote
from typing import Any, Callable, Mapping, Optional, Union
from urllib.error import HTTPError
from urllib.request import Request, urlopen


RUNPOD_GRAPHQL_ENDPOINT = "https://api.runpod.io/graphql"
RUNPOD_REST_ENDPOINT = "https://rest.runpod.io/v1"
RUNPOD_USER_AGENT = "3dgen-demoroom-bench-harness/0.1"
DEFAULT_MIN_BALANCE_USD = 5.0
DEFAULT_MAX_RUNTIME_MIN = 90
DEFAULT_GPU_TYPE_IDS = ("NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 4090")
DEFAULT_ALLOWED_CUDA_VERSIONS = ("12.8",)
RUNPOD_HANDOFF_ACK_TIMEOUT_SECONDS = 60.0
RUNPOD_EVIDENCE_GRACE_MIN = 30
RUNPOD_TERMINATE_ATTEMPTS = 3
RUNPOD_TERMINATE_RETRY_SECONDS = 1.0
RUNPOD_VOLUME_MOUNT_PATH = "/workspace"
RUNPOD_WEIGHT_ROOT = f"{RUNPOD_VOLUME_MOUNT_PATH}/weights"
RUNPOD_HF_HOME = f"{RUNPOD_VOLUME_MOUNT_PATH}/hf"
RUNPOD_TORCH_HOME = f"{RUNPOD_VOLUME_MOUNT_PATH}/torch"
RUNPOD_U2NET_HOME = f"{RUNPOD_WEIGHT_ROOT}/rembg"
RUNPOD_TELEMETRY_ROOT = "/work/runpod-telemetry"
REQUIRED_R2_ENV_VARS = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
MODEL_RUNNER_PATHS = {
    "triposg": "/opt/3dgen-runner/triposg_runner.py",
    "partcrafter": "/opt/3dgen-runner/partcrafter_runner.py",
    "trellis1": "/opt/3dgen-runner/trellis1_runner.py",
    "3dtopia-xl": "/opt/3dgen-runner/3dtopia_xl_runner.py",
    "trellis2": "/opt/3dgen-runner/trellis2_runner.py",
    "direct3d-s2": "/opt/3dgen-runner/direct3d_s2_runner.py",
    "step1x-3d": "/opt/3dgen-runner/step1x_3d_runner.py",
    "pixal3d": "/opt/3dgen-runner/pixal3d_runner.py",
    "hunyuan3d-21": "/opt/3dgen-runner/hunyuan3d_21_runner.py",
    "sf3d": "/opt/3dgen-runner/sf3d_runner.py",
}
TASK_ID_MODEL_IDS = frozenset({"pixal3d", "trellis2"})
MODEL_WEIGHT_ENVS = {
    "triposg": {
        "TRIPOSG_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/TripoSG",
        "RMBG_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/RMBG-1.4",
    },
    "partcrafter": {
        "PARTCRAFTER_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/PartCrafter",
        "RMBG_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/RMBG-1.4",
    },
    "trellis1": {
        "TRELLIS1_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/TRELLIS-image-large",
    },
    "3dtopia-xl": {
        "TOPIA_XL_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/3DTopia-XL",
    },
    "trellis2": {
        "TRELLIS2_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/TRELLIS.2-4B",
    },
    "direct3d-s2": {
        "DIRECT3D_S2_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/Direct3D-S2",
    },
    "step1x-3d": {
        "STEP1X_3D_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/Step1X-3D",
    },
    "pixal3d": {
        "PIXAL3D_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/Pixal3D",
    },
    "hunyuan3d-21": {
        "HUNYUAN3D_21_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/Hunyuan3D-2.1",
    },
    "sf3d": {
        "SF3D_WEIGHTS_PATH": f"{RUNPOD_WEIGHT_ROOT}/stable-fast-3d",
    },
}

JsonResponse = Union[dict[str, object], list[object]]
RequestJson = Callable[[str, str, dict[str, str], Optional[dict[str, object]]], JsonResponse]
TcpConnect = Callable[[str, int, float], bool]
LifecycleTokenFactory = Callable[[], str]
UtcNow = Callable[[], datetime]


class RunPodApiError(RuntimeError):
    def __init__(
        self,
        *,
        method: str,
        url: str,
        status_code: int,
        reason: str,
        response_body: str,
    ) -> None:
        self.method = method
        self.url = url
        self.status_code = status_code
        self.reason = reason
        self.response_body = response_body
        message = f"RunPod API request failed: {method} {url} returned HTTP {status_code} {reason}"
        if response_body:
            message = f"{message}: {response_body}"
        super().__init__(message)


@dataclass(frozen=True)
class RunPodBalanceCheck:
    api_key: str
    min_balance_usd: float

    @property
    def endpoint(self) -> str:
        return RUNPOD_GRAPHQL_ENDPOINT

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}


@dataclass(frozen=True)
class RunPodOwnershipCoordinator:
    def initialize(self, target: str, lifecycle_token: str, env: Mapping[str, str]) -> None:
        from bench_harness.runpod_handoff import initialize_launcher_ownership

        initialize_launcher_ownership(target, lifecycle_token, env)

    def handoff(
        self,
        target: str,
        pod_id: str,
        lifecycle_token: str,
        env: Mapping[str, str],
        *,
        timeout_seconds: float,
        poll_seconds: float,
    ) -> None:
        from bench_harness.runpod_handoff import handoff_to_runtime

        handoff_to_runtime(
            target,
            pod_id,
            lifecycle_token,
            env,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )

    def claim_cleanup(
        self,
        target: str,
        pod_id: str,
        lifecycle_token: str,
        env: Mapping[str, str],
    ) -> bool:
        from bench_harness.runpod_handoff import claim_cleanup

        return claim_cleanup(target, pod_id, lifecycle_token, "launcher", env)


@dataclass(frozen=True)
class R2Credentials:
    endpoint: str
    access_key_id: str
    secret_access_key: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> R2Credentials:
        missing = [name for name in REQUIRED_R2_ENV_VARS if not env.get(name)]
        if missing:
            raise ValueError(f"missing required R2 environment variable(s): {', '.join(missing)}")
        return cls(
            endpoint=env["R2_ENDPOINT"],
            access_key_id=env["R2_ACCESS_KEY_ID"],
            secret_access_key=env["R2_SECRET_ACCESS_KEY"],
        )

    def as_env(self) -> dict[str, str]:
        return {
            "R2_ENDPOINT": self.endpoint,
            "R2_ACCESS_KEY_ID": self.access_key_id,
            "R2_SECRET_ACCESS_KEY": self.secret_access_key,
        }


@dataclass(frozen=True)
class RunPodLaunchConfig:
    name: str
    image_name: str
    model_id: str
    s3_target: str
    max_runtime_min: int
    gpu_type_ids: tuple[str, ...]
    allowed_cuda_versions: tuple[str, ...]
    r2_credentials: R2Credentials
    network_volume_id: str
    data_center_id: str
    startup_timeout_min: int
    task_limit: int | None = None
    task_ids: tuple[str, ...] = ()
    retry_count: int = 0
    startup_poll_seconds: float = 15.0
    container_registry_auth_id: str | None = None
    container_disk_gb: int = 80
    output_root: str = "/work/output"


@dataclass(frozen=True)
class RunPodClient:
    api_key: str
    request_json: RequestJson | None = None
    tcp_connect: TcpConnect | None = None
    ownership_coordinator: RunPodOwnershipCoordinator | None = None
    lifecycle_token_factory: LifecycleTokenFactory | None = None
    utc_now: UtcNow | None = None

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key.strip():
            raise ValueError("RunPod API key is required")
        return {"Authorization": f"Bearer {self.api_key}"}

    def launch_pod(self, config: RunPodLaunchConfig, min_balance_usd: float) -> JsonResponse:
        if min_balance_usd <= 0:
            raise ValueError("RunPod minimum balance must be positive")
        if config.startup_timeout_min <= 0:
            raise ValueError("RunPod startup_timeout_min must be positive")
        if config.startup_poll_seconds < 0:
            raise ValueError("RunPod startup_poll_seconds must not be negative")
        balance_response = self._request_json(
            "POST",
            RUNPOD_GRAPHQL_ENDPOINT,
            self.headers,
            {"query": build_balance_query()},
        )
        parse_client_balance(balance_response, min_balance_usd=min_balance_usd)
        token_factory = self.lifecycle_token_factory or create_lifecycle_token
        lifecycle_token = token_factory()
        if not isinstance(lifecycle_token, str) or not lifecycle_token.strip():
            raise ValueError("RunPod lifecycle token factory returned an empty token")
        coordinator = self.ownership_coordinator or RunPodOwnershipCoordinator()
        ownership_env = config.r2_credentials.as_env()
        coordinator.initialize(config.s3_target, lifecycle_token, ownership_env)
        now_fn = self.utc_now or utc_now
        terminate_after = build_terminate_after(config, now=now_fn())
        create_response = self._request_json(
            "POST",
            RUNPOD_GRAPHQL_ENDPOINT,
            self.headers,
            build_create_pod_request(
                build_pod_payload(
                    config,
                    runpod_api_key=self.api_key,
                    lifecycle_token=lifecycle_token,
                    terminate_after=terminate_after,
                )
            ),
        )
        created_pod = parse_create_pod_response(create_response)
        pod_id = parse_pod_id(created_pod)
        handed_off = False
        handoff_started = False
        launcher_cleanup_already_claimed = False
        startup_error: BaseException | None = None
        try:
            pod = self.wait_for_startup(
                pod_id,
                timeout_seconds=config.startup_timeout_min * 60,
                poll_seconds=config.startup_poll_seconds,
            )
            handoff_started = True
            coordinator.handoff(
                config.s3_target,
                pod_id,
                lifecycle_token,
                ownership_env,
                timeout_seconds=RUNPOD_HANDOFF_ACK_TIMEOUT_SECONDS,
                poll_seconds=1.0,
            )
            handed_off = True
            return pod
        except BaseException as error:
            startup_error = error
            if handoff_started:
                from bench_harness.runpod_handoff import RunPodHandoffTimeout

                launcher_cleanup_already_claimed = isinstance(error, RunPodHandoffTimeout)
            raise
        finally:
            if not handed_off:
                cleanup_claimed = False
                try:
                    cleanup_claimed = coordinator.claim_cleanup(
                        config.s3_target,
                        pod_id,
                        lifecycle_token,
                        ownership_env,
                    )
                except BaseException as cleanup_error:
                    message = format_cleanup_failure(pod_id, cleanup_error)
                    print(message, file=sys.stderr, flush=True)
                    cleanup_claimed = launcher_cleanup_already_claimed
                if cleanup_claimed:
                    try:
                        self.terminate_pod(pod_id)
                    except BaseException as cleanup_error:
                        message = format_cleanup_failure(pod_id, cleanup_error)
                        print(message, file=sys.stderr, flush=True)
                        if startup_error is None:
                            raise
                else:
                    print(
                        f"RUNPOD_CLEANUP_SKIPPED pod_id={pod_id} "
                        f"owner_changed_or_uncertain=true terminate_after={terminate_after}",
                        file=sys.stderr,
                        flush=True,
                    )

    def terminate_pod(self, pod_id: str) -> JsonResponse:
        if not pod_id.strip():
            raise ValueError("RunPod pod_id is required")
        last_error: Exception | None = None
        for attempt in range(RUNPOD_TERMINATE_ATTEMPTS):
            try:
                return self._request_json(
                    "DELETE",
                    f"{RUNPOD_REST_ENDPOINT}/pods/{pod_id}",
                    self.headers,
                    None,
                )
            except RunPodApiError as error:
                if error.status_code == 404:
                    return {}
                last_error = error
            except Exception as error:
                last_error = error
            if attempt + 1 < RUNPOD_TERMINATE_ATTEMPTS:
                time.sleep(RUNPOD_TERMINATE_RETRY_SECONDS)
        if last_error is None:
            raise AssertionError("RunPod termination retry loop completed without a result")
        raise last_error

    def get_pod(self, pod_id: str) -> JsonResponse:
        if not pod_id.strip():
            raise ValueError("RunPod pod_id is required")
        return self._request_json("GET", f"{RUNPOD_REST_ENDPOINT}/pods/{pod_id}", self.headers, None)

    def list_pods(self) -> JsonResponse:
        return self._request_json("GET", f"{RUNPOD_REST_ENDPOINT}/pods", self.headers, None)

    def wait_for_startup(self, pod_id: str, *, timeout_seconds: float, poll_seconds: float) -> dict[str, object]:
        deadline = time.monotonic() + timeout_seconds
        last_pod: dict[str, object] | None = None
        while True:
            try:
                pod = self.get_pod(pod_id)
            except RunPodApiError as exc:
                if exc.status_code == 404:
                    last_state = format_startup_state(last_pod)
                    raise RuntimeError(
                        f"RunPod pod {pod_id} disappeared before startup became ready{last_state}"
                    ) from exc
                raise
            if not isinstance(pod, dict):
                raise ValueError("RunPod get pod response must be a JSON object")
            last_pod = pod
            tcp_connect = self.tcp_connect or can_connect_tcp
            if pod_is_startup_ready(pod, tcp_connect=tcp_connect):
                return pod
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"RunPod pod {pod_id} did not expose a reachable SSH port within {timeout_seconds / 60:.1f} minutes"
                )
            time.sleep(poll_seconds)

    def _request_json(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, object] | None,
    ) -> JsonResponse:
        if self.request_json is not None:
            return self.request_json(method, url, headers, body)
        return request_json(method, url, headers, body)


def build_balance_query() -> str:
    return "query CurrentUserBalance { myself { clientBalance } }"


def build_create_pod_query() -> str:
    return (
        "mutation CreateBenchmarkPod($input: PodFindAndDeployOnDemandInput!) { "
        "podFindAndDeployOnDemand(input: $input) { id desiredStatus } }"
    )


def build_create_pod_request(payload: dict[str, Any]) -> dict[str, object]:
    return {"query": build_create_pod_query(), "variables": {"input": payload}}


def build_terminate_after(config: RunPodLaunchConfig, *, now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("RunPod hard-termination clock must be timezone-aware")
    lifetime_minutes = config.startup_timeout_min + config.max_runtime_min + RUNPOD_EVIDENCE_GRACE_MIN
    deadline = now.astimezone(timezone.utc) + timedelta(minutes=lifetime_minutes)
    return deadline.isoformat(timespec="seconds").replace("+00:00", "Z")


def create_lifecycle_token() -> str:
    return secrets.token_urlsafe(32)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_client_balance(response: dict[str, Any], min_balance_usd: float) -> float:
    try:
        balance = response["data"]["myself"]["clientBalance"]
    except KeyError as exc:
        raise ValueError("RunPod balance response missing data.myself.clientBalance") from exc
    if isinstance(balance, bool) or not isinstance(balance, (int, float)):
        raise ValueError("RunPod clientBalance must be numeric")
    balance = float(balance)
    if balance < min_balance_usd:
        raise RuntimeError(f"RunPod balance {balance:.2f} USD is below threshold {min_balance_usd:.2f} USD")
    return balance


def parse_pod_id(response: JsonResponse) -> str:
    if not isinstance(response, dict):
        raise ValueError("RunPod create pod response must be a JSON object")
    pod_id = response.get("id")
    if not isinstance(pod_id, str) or not pod_id.strip():
        raise ValueError("RunPod create pod response missing id")
    return pod_id


def parse_create_pod_response(response: JsonResponse) -> dict[str, object]:
    if not isinstance(response, dict):
        raise ValueError("RunPod create pod GraphQL response must be a JSON object")
    errors = response.get("errors")
    if errors is not None:
        if not isinstance(errors, list) or not errors:
            raise ValueError("RunPod create pod GraphQL errors must be a non-empty array")
        first_error = errors[0]
        if not isinstance(first_error, dict) or not isinstance(first_error.get("message"), str):
            raise ValueError("RunPod create pod GraphQL error is missing message")
        raise RuntimeError(f"RunPod create pod GraphQL error: {first_error['message']}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise ValueError("RunPod create pod GraphQL response missing data")
    pod = data.get("podFindAndDeployOnDemand")
    if not isinstance(pod, dict):
        raise ValueError("RunPod create pod GraphQL response missing podFindAndDeployOnDemand")
    return pod


def pod_has_public_ip(response: dict[str, object]) -> bool:
    public_ip = response.get("publicIp")
    return isinstance(public_ip, str) and bool(public_ip.strip())


def pod_ssh_port(response: dict[str, object]) -> int | None:
    port_mappings = response.get("portMappings")
    if not isinstance(port_mappings, dict):
        return None
    raw_port = port_mappings.get("22")
    if isinstance(raw_port, bool) or not isinstance(raw_port, int):
        return None
    return raw_port


def can_connect_tcp(host: str, port: int, timeout_seconds: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def pod_is_startup_ready(response: dict[str, object], *, tcp_connect: TcpConnect) -> bool:
    public_ip = response.get("publicIp")
    if not isinstance(public_ip, str) or not public_ip.strip():
        return False
    ssh_port = pod_ssh_port(response)
    if ssh_port is None:
        return False
    return tcp_connect(public_ip, ssh_port, 5.0)


def format_startup_state(response: dict[str, object] | None) -> str:
    if response is None:
        return ""
    parts = []
    pod_id = response.get("id")
    if isinstance(pod_id, str) and pod_id.strip():
        parts.append(f"id={pod_id}")
    desired_status = response.get("desiredStatus")
    if isinstance(desired_status, str) and desired_status.strip():
        parts.append(f"desiredStatus={desired_status}")
    public_ip = response.get("publicIp")
    if isinstance(public_ip, str) and public_ip.strip():
        parts.append(f"publicIp={public_ip}")
    ssh_port = pod_ssh_port(response)
    if ssh_port is not None:
        parts.append(f"sshPort={ssh_port}")
    runtime = response.get("runtime")
    if runtime is not None:
        parts.append(f"runtime={runtime}")
    uptime = response.get("uptime")
    if uptime is not None:
        parts.append(f"uptime={uptime}")
    if not parts:
        return ""
    return f" (last observed: {', '.join(parts)})"


def format_cleanup_failure(pod_id: str, error: BaseException) -> str:
    return (
        f"RUNPOD_CLEANUP_FAILED pod_id={pod_id} error={type(error).__name__}: {error} "
        f'manual="runpodctl pod delete {pod_id}"'
    )


def build_cloud_run_command(
    model_id: str,
    output_root: str,
    s3_target: str,
    *,
    task_limit: int | None = None,
    task_ids: tuple[str, ...] = (),
    retry_count: int = 0,
) -> str:
    if model_id not in MODEL_RUNNER_PATHS:
        raise ValueError(f"unknown model for RunPod cloud run: {model_id}")
    if not s3_target.startswith("s3://"):
        raise ValueError("RunPod cloud run S3 target must use s3://")
    if task_limit is not None and task_limit <= 0:
        raise ValueError("RunPod cloud run task_limit must be positive")
    if task_limit is not None and task_ids:
        raise ValueError("RunPod cloud run task_limit and task_ids are mutually exclusive")
    if any(not task_id.strip() for task_id in task_ids):
        raise ValueError("RunPod cloud run task_ids must not contain empty values")
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("RunPod cloud run task_ids must not contain duplicates")
    if task_ids and model_id not in TASK_ID_MODEL_IDS:
        raise ValueError(f"RunPod cloud run task_ids are not supported for model: {model_id}")
    if retry_count < 0:
        raise ValueError("RunPod cloud run retry_count must not be negative")
    if retry_count > 0 and not task_ids:
        raise ValueError("RunPod cloud run retry_count requires exact task_ids")
    if retry_count > 0 and model_id != "pixal3d":
        raise ValueError(f"RunPod cloud run retry_count is not supported for model: {model_id}")
    output_path = PurePosixPath(output_root)
    telemetry_path = PurePosixPath(RUNPOD_TELEMETRY_ROOT)
    if not output_path.is_absolute():
        raise ValueError("RunPod cloud run output_root must be an absolute POSIX path")
    raw_path_parts = output_root.split("/")
    if output_root.startswith("//") or any(
        part in {"", ".", ".."} for part in raw_path_parts[1:]
    ):
        raise ValueError(
            "RunPod cloud run output_root must be a canonical absolute POSIX path "
            "without '.', '..', or repeated/trailing slashes"
        )
    if (
        output_path == telemetry_path
        or output_path in telemetry_path.parents
        or telemetry_path in output_path.parents
    ):
        raise ValueError(
            "RunPod cloud run output_root must not equal, contain, or be contained by the telemetry root"
        )
    quoted_output_root = quote(output_root)
    quoted_telemetry_root = quote(RUNPOD_TELEMETRY_ROOT)
    quoted_s3_target = quote(s3_target)
    run_command = f"--input-root {quote('/opt/3dgen-tasks')} --output-root {quoted_output_root}"
    if task_limit is not None:
        run_command = f"{run_command} --task-limit {task_limit}"
    for task_id in task_ids:
        run_command = f"{run_command} --task-id {quote(task_id)}"
    if retry_count > 0:
        run_command = f"{run_command} --retry-count {retry_count}"
    return (
        f"runpod --output-root {quoted_output_root} "
        f"--telemetry-root {quoted_telemetry_root} "
        f"--s3-target {quoted_s3_target} -- {run_command}"
    )


def build_model_weight_env(model_id: str) -> dict[str, str]:
    try:
        weight_env = MODEL_WEIGHT_ENVS[model_id]
    except KeyError as exc:
        raise ValueError(f"unknown model for RunPod cloud run: {model_id}") from exc
    return {
        "HF_HOME": RUNPOD_HF_HOME,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TORCH_HOME": RUNPOD_TORCH_HOME,
        "U2NET_HOME": RUNPOD_U2NET_HOME,
        **weight_env,
    }


def build_pod_payload(
    config: RunPodLaunchConfig,
    *,
    runpod_api_key: str,
    lifecycle_token: str,
    terminate_after: str,
) -> dict[str, Any]:
    if not config.name.strip():
        raise ValueError("RunPod pod name is required")
    if not config.image_name.strip():
        raise ValueError("RunPod image name is required")
    if not runpod_api_key.strip():
        raise ValueError("RunPod API key is required for pod self-termination")
    if not lifecycle_token.strip():
        raise ValueError("RunPod lifecycle token is required")
    if not terminate_after.strip():
        raise ValueError("RunPod terminate_after is required")
    if config.max_runtime_min <= 0:
        raise ValueError("RunPod max_runtime_min must be positive")
    if config.startup_timeout_min <= 0:
        raise ValueError("RunPod startup_timeout_min must be positive")
    if not config.gpu_type_ids:
        raise ValueError("RunPod gpu_type_ids must not be empty")
    if not config.allowed_cuda_versions:
        raise ValueError("RunPod allowed_cuda_versions must not be empty")
    if not config.network_volume_id.strip():
        raise ValueError("RunPod network_volume_id is required")
    if not config.data_center_id.strip():
        raise ValueError("RunPod data_center_id is required")
    if config.container_registry_auth_id is not None and not config.container_registry_auth_id.strip():
        raise ValueError("RunPod container_registry_auth_id must not be empty")
    command = build_cloud_run_command(
        config.model_id,
        config.output_root,
        config.s3_target,
        task_limit=config.task_limit,
        task_ids=config.task_ids,
        retry_count=config.retry_count,
    )
    runtime_env = {
        "MAX_RUNTIME_MIN": str(config.max_runtime_min),
        "RUNPOD_RUN_MODEL_ID": config.model_id,
        "RUNPOD_S3_TARGET": config.s3_target,
        "RUNPOD_INCREMENTAL_S3_TARGET": config.s3_target,
        "RUNPOD_API_KEY": runpod_api_key,
        "RUNPOD_LIFECYCLE_TOKEN": lifecycle_token,
        "RUNPOD_HANDOFF_TIMEOUT_SECONDS": str(config.startup_timeout_min * 60),
        **build_model_weight_env(config.model_id),
        **config.r2_credentials.as_env(),
    }
    payload: dict[str, Any] = {
        "name": config.name,
        "imageName": config.image_name,
        "cloudType": "SECURE",
        "computeType": "GPU",
        "gpuTypeIdList": list(config.gpu_type_ids),
        "dataCenterId": config.data_center_id,
        "gpuCount": 1,
        "allowedCudaVersions": list(config.allowed_cuda_versions),
        "containerDiskInGb": config.container_disk_gb,
        "networkVolumeId": config.network_volume_id,
        "volumeMountPath": RUNPOD_VOLUME_MOUNT_PATH,
        "dockerArgs": command,
        "env": [{"key": key, "value": value} for key, value in runtime_env.items()],
        "ports": "22/tcp",
        "startSsh": True,
        "terminateAfter": terminate_after,
    }
    if config.container_registry_auth_id is not None:
        payload["containerRegistryAuthId"] = config.container_registry_auth_id
    return payload


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, object] | None,
) -> JsonResponse:
    request_headers = dict(headers)
    request_headers["User-Agent"] = RUNPOD_USER_AGENT
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace").strip()
        raise RunPodApiError(
            method=method,
            url=url,
            status_code=exc.code,
            reason=exc.reason,
            response_body=error_body,
        ) from exc
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, (dict, list)):
        raise ValueError("RunPod API response must be a JSON object or array")
    return parsed
