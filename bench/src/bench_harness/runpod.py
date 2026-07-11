from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from shlex import quote
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen


RUNPOD_GRAPHQL_ENDPOINT = "https://api.runpod.io/graphql"
RUNPOD_REST_ENDPOINT = "https://rest.runpod.io/v1"
RUNPOD_USER_AGENT = "3dgen-demoroom-bench-harness/0.1"
DEFAULT_MIN_BALANCE_USD = 5.0
DEFAULT_MAX_RUNTIME_MIN = 90
DEFAULT_GPU_TYPE_IDS = ("NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 4090")
DEFAULT_ALLOWED_CUDA_VERSIONS = ("12.8",)
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

JsonResponse = dict[str, object] | list[object]
RequestJson = Callable[[str, str, dict[str, str], dict[str, object] | None], JsonResponse]
TcpConnect = Callable[[str, int, float], bool]


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
        created_pod = self._request_json(
            "POST",
            f"{RUNPOD_REST_ENDPOINT}/pods",
            self.headers,
            build_pod_payload(config, runpod_api_key=self.api_key),
        )
        return self.wait_for_startup(
            parse_pod_id(created_pod),
            timeout_seconds=config.startup_timeout_min * 60,
            poll_seconds=config.startup_poll_seconds,
        )

    def terminate_pod(self, pod_id: str) -> JsonResponse:
        if not pod_id.strip():
            raise ValueError("RunPod pod_id is required")
        return self._request_json("DELETE", f"{RUNPOD_REST_ENDPOINT}/pods/{pod_id}", self.headers, None)

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
                self.terminate_pod(pod_id)
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


def parse_client_balance(response: dict[str, Any], min_balance_usd: float) -> float:
    try:
        balance = response["data"]["myself"]["clientBalance"]
    except KeyError as exc:
        raise ValueError("RunPod balance response missing data.myself.clientBalance") from exc
    if isinstance(balance, bool) or not isinstance(balance, int | float):
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


def build_cloud_run_command(
    model_id: str,
    output_root: str,
    s3_target: str,
    *,
    task_limit: int | None = None,
    task_ids: tuple[str, ...] = (),
    retry_count: int = 0,
) -> str:
    try:
        runner_path = MODEL_RUNNER_PATHS[model_id]
    except KeyError as exc:
        raise ValueError(f"unknown model for RunPod cloud run: {model_id}") from exc
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
    quoted_model_id = quote(model_id)
    run_command = (
        f"python3 {quote(runner_path)} "
        f"--input-root {quote('/opt/3dgen-tasks')} "
        f"--output-root {quoted_output_root}"
    )
    if task_limit is not None:
        run_command = f"{run_command} --task-limit {task_limit}"
    for task_id in task_ids:
        run_command = f"{run_command} --task-id {quote(task_id)}"
    if retry_count > 0:
        run_command = f"{run_command} --retry-count {retry_count}"
    ssh_command = (
        "mkdir -p /run/sshd\n"
        "if [ -n \"${PUBLIC_KEY:-}\" ]; then\n"
        "  mkdir -p /root/.ssh\n"
        "  printf '%s\\n' \"$PUBLIC_KEY\" >> /root/.ssh/authorized_keys\n"
        "  chmod 700 /root/.ssh\n"
        "  chmod 600 /root/.ssh/authorized_keys\n"
        "fi\n"
        "service ssh start\n"
        "ssh_exit_code=$?"
    )
    startup_status_command = (
        "python3 - "
        f"{quoted_telemetry_root} {quoted_model_id} {quoted_s3_target} "
        '"$ssh_exit_code" <<\'PY_RUNPOD_STARTUP\'\n'
        "from __future__ import annotations\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from datetime import datetime, timezone\n"
        "from pathlib import Path\n"
        "\n"
        "telemetry_root = Path(sys.argv[1])\n"
        "model_id = sys.argv[2]\n"
        "s3_target = sys.argv[3]\n"
        "ssh_exit_code = int(sys.argv[4])\n"
        "telemetry_root.mkdir(parents=True, exist_ok=True)\n"
        "status = {\n"
        "    'model_id': model_id,\n"
        "    'pod_id': os.environ.get('RUNPOD_POD_ID'),\n"
        "    's3_target': s3_target,\n"
        "    'ssh_exit_code': ssh_exit_code,\n"
        "    'started_at': datetime.now(timezone.utc).isoformat(),\n"
        "    'status': 'started',\n"
        "}\n"
        "(telemetry_root / 'runpod-startup.json').write_text(json.dumps(status, indent=2, sort_keys=True) + '\\n', encoding='utf-8')\n"
        "PY_RUNPOD_STARTUP"
    )
    startup_upload_command = (
        "PYTHONPATH=/opt/bench/src "
        f"python3 -m bench_harness.cli upload-s3 {quoted_telemetry_root} {quoted_s3_target}"
    )
    status_command = (
        "python3 - "
        f"{quoted_telemetry_root} {quoted_model_id} {quoted_s3_target} "
        '"$runner_exit_code" <<\'PY_RUNPOD_STATUS\'\n'
        "from __future__ import annotations\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from datetime import datetime, timezone\n"
        "from pathlib import Path\n"
        "\n"
        "telemetry_root = Path(sys.argv[1])\n"
        "model_id = sys.argv[2]\n"
        "s3_target = sys.argv[3]\n"
        "runner_exit_code = int(sys.argv[4])\n"
        "telemetry_root.mkdir(parents=True, exist_ok=True)\n"
        "status = {\n"
        "    'finished_at': datetime.now(timezone.utc).isoformat(),\n"
        "    'model_id': model_id,\n"
        "    'pod_id': os.environ.get('RUNPOD_POD_ID'),\n"
        "    'runner_exit_code': runner_exit_code,\n"
        "    'self_termination_configured': bool(os.environ.get('RUNPOD_POD_ID') and os.environ.get('RUNPOD_API_KEY')),\n"
        "    's3_target': s3_target,\n"
        "    'status': 'ok' if runner_exit_code == 0 else 'failed',\n"
        "}\n"
        "(telemetry_root / 'runpod-status.json').write_text(json.dumps(status, indent=2, sort_keys=True) + '\\n', encoding='utf-8')\n"
        "PY_RUNPOD_STATUS"
    )
    upload_command = (
        "PYTHONPATH=/opt/bench/src "
        f"python3 -m bench_harness.cli upload-s3 {quoted_telemetry_root} {quoted_s3_target}"
    )
    terminate_command = (
        "python3 - <<'PY_RUNPOD_TERMINATE'\n"
        "from __future__ import annotations\n"
        "import os\n"
        "import urllib.request\n"
        "\n"
        "pod_id = os.environ.get('RUNPOD_POD_ID')\n"
        "api_key = os.environ.get('RUNPOD_API_KEY')\n"
        "if not pod_id or not api_key:\n"
        "    print('RunPod self-termination warning: RUNPOD_POD_ID or RUNPOD_API_KEY is missing', flush=True)\n"
        "else:\n"
        "    request = urllib.request.Request(\n"
        "        f'https://rest.runpod.io/v1/pods/{pod_id}',\n"
        "        method='DELETE',\n"
        "        headers={\n"
        "            'Authorization': f'Bearer {api_key}',\n"
        "            'User-Agent': '3dgen-demoroom-bench-harness/0.1',\n"
        "        },\n"
        "    )\n"
        "    try:\n"
        "        urllib.request.urlopen(request, timeout=30).read()\n"
        "    except Exception as exc:\n"
        "        print(f'RunPod self-termination warning: {exc}', flush=True)\n"
        "PY_RUNPOD_TERMINATE"
    )
    return (
        "set +e\n"
        "runner_exit_code=0\n"
        f"{ssh_command}\n"
        f"{startup_status_command}\n"
        "startup_status_exit_code=$?\n"
        f"{startup_upload_command}\n"
        "startup_upload_exit_code=$?\n"
        "if [ \"$ssh_exit_code\" -ne 0 ]; then\n"
        "  runner_exit_code=\"$ssh_exit_code\"\n"
        "elif [ \"$startup_status_exit_code\" -ne 0 ]; then\n"
        "  runner_exit_code=\"$startup_status_exit_code\"\n"
        "elif [ \"$startup_upload_exit_code\" -ne 0 ]; then\n"
        "  runner_exit_code=\"$startup_upload_exit_code\"\n"
        "else\n"
        f"  {run_command}\n"
        "  runner_exit_code=$?\n"
        "fi\n"
        f"{status_command}\n"
        "status_exit_code=$?\n"
        f"{upload_command}\n"
        "upload_exit_code=$?\n"
        f"{terminate_command}\n"
        'if [ "$upload_exit_code" -ne 0 ]; then exit "$upload_exit_code"; fi\n'
        'if [ "$status_exit_code" -ne 0 ]; then exit "$status_exit_code"; fi\n'
        'exit "$runner_exit_code"'
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


def build_pod_payload(config: RunPodLaunchConfig, *, runpod_api_key: str) -> dict[str, Any]:
    if not config.name.strip():
        raise ValueError("RunPod pod name is required")
    if not config.image_name.strip():
        raise ValueError("RunPod image name is required")
    if not runpod_api_key.strip():
        raise ValueError("RunPod API key is required for pod self-termination")
    if config.max_runtime_min <= 0:
        raise ValueError("RunPod max_runtime_min must be positive")
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
    payload: dict[str, Any] = {
        "name": config.name,
        "imageName": config.image_name,
        "cloudType": "SECURE",
        "computeType": "GPU",
        "gpuTypeIds": list(config.gpu_type_ids),
        "gpuTypePriority": "custom",
        "dataCenterIds": [config.data_center_id],
        "dataCenterPriority": "custom",
        "gpuCount": 1,
        "allowedCudaVersions": list(config.allowed_cuda_versions),
        "interruptible": False,
        "containerDiskInGb": config.container_disk_gb,
        "networkVolumeId": config.network_volume_id,
        "volumeMountPath": RUNPOD_VOLUME_MOUNT_PATH,
        "dockerEntrypoint": ["bash", "-lc"],
        "dockerStartCmd": [command],
        "env": {
            "MAX_RUNTIME_MIN": str(config.max_runtime_min),
            "RUNPOD_RUN_MODEL_ID": config.model_id,
            "RUNPOD_S3_TARGET": config.s3_target,
            "RUNPOD_INCREMENTAL_S3_TARGET": config.s3_target,
            "RUNPOD_API_KEY": runpod_api_key,
            **build_model_weight_env(config.model_id),
            **config.r2_credentials.as_env(),
        },
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
    if not isinstance(parsed, dict | list):
        raise ValueError("RunPod API response must be a JSON object or array")
    return parsed
