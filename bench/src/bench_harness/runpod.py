from __future__ import annotations

import json
from dataclasses import dataclass
from shlex import quote
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen


RUNPOD_GRAPHQL_ENDPOINT = "https://api.runpod.io/graphql"
RUNPOD_REST_ENDPOINT = "https://rest.runpod.io/v1"
DEFAULT_MIN_BALANCE_USD = 5.0
DEFAULT_MAX_RUNTIME_MIN = 90
DEFAULT_GPU_TYPE_IDS = ("NVIDIA GeForce RTX 5090", "NVIDIA GeForce RTX 4090")
DEFAULT_ALLOWED_CUDA_VERSIONS = ("12.8",)
REQUIRED_R2_ENV_VARS = ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
MODEL_RUNNER_PATHS = {
    "triposg": "/opt/3dgen-runner/triposg_runner.py",
    "partcrafter": "/opt/3dgen-runner/partcrafter_runner.py",
}

RequestJson = Callable[[str, str, dict[str, str], dict[str, object] | None], dict[str, object]]


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
    container_disk_gb: int = 80
    volume_gb: int = 120
    output_root: str = "/work/output"


@dataclass(frozen=True)
class RunPodClient:
    api_key: str
    request_json: RequestJson | None = None

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key.strip():
            raise ValueError("RunPod API key is required")
        return {"Authorization": f"Bearer {self.api_key}"}

    def launch_pod(self, config: RunPodLaunchConfig, min_balance_usd: float) -> dict[str, object]:
        if min_balance_usd <= 0:
            raise ValueError("RunPod minimum balance must be positive")
        balance_response = self._request_json(
            "POST",
            RUNPOD_GRAPHQL_ENDPOINT,
            self.headers,
            {"query": build_balance_query()},
        )
        parse_client_balance(balance_response, min_balance_usd=min_balance_usd)
        return self._request_json(
            "POST",
            f"{RUNPOD_REST_ENDPOINT}/pods",
            self.headers,
            build_pod_payload(config, runpod_api_key=self.api_key),
        )

    def terminate_pod(self, pod_id: str) -> dict[str, object]:
        if not pod_id.strip():
            raise ValueError("RunPod pod_id is required")
        return self._request_json("DELETE", f"{RUNPOD_REST_ENDPOINT}/pods/{pod_id}", self.headers, None)

    def get_pod(self, pod_id: str) -> dict[str, object]:
        if not pod_id.strip():
            raise ValueError("RunPod pod_id is required")
        return self._request_json("GET", f"{RUNPOD_REST_ENDPOINT}/pods/{pod_id}", self.headers, None)

    def list_pods(self) -> dict[str, object]:
        return self._request_json("GET", f"{RUNPOD_REST_ENDPOINT}/pods", self.headers, None)

    def _request_json(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, object] | None,
    ) -> dict[str, object]:
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


def build_cloud_run_command(model_id: str, output_root: str, s3_target: str) -> str:
    try:
        runner_path = MODEL_RUNNER_PATHS[model_id]
    except KeyError as exc:
        raise ValueError(f"unknown model for RunPod cloud run: {model_id}") from exc
    if not s3_target.startswith("s3://"):
        raise ValueError("RunPod cloud run S3 target must use s3://")
    run_command = (
        f"python3 {quote(runner_path)} "
        f"--input-root {quote('/opt/3dgen-tasks')} "
        f"--output-root {quote(output_root)}"
    )
    upload_command = (
        "PYTHONPATH=/opt/bench/src "
        f"python3 -m bench_harness.cli upload-s3 {quote(output_root)} {quote(s3_target)}"
    )
    return f"{run_command} && {upload_command}"


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
    command = build_cloud_run_command(config.model_id, config.output_root, config.s3_target)
    return {
        "name": config.name,
        "imageName": config.image_name,
        "cloudType": "SECURE",
        "computeType": "GPU",
        "gpuTypeIds": list(config.gpu_type_ids),
        "gpuTypePriority": "custom",
        "gpuCount": 1,
        "allowedCudaVersions": list(config.allowed_cuda_versions),
        "interruptible": False,
        "containerDiskInGb": config.container_disk_gb,
        "volumeInGb": config.volume_gb,
        "dockerEntrypoint": ["bash", "-lc"],
        "dockerStartCmd": [command],
        "env": {
            "MAX_RUNTIME_MIN": str(config.max_runtime_min),
            "RUNPOD_RUN_MODEL_ID": config.model_id,
            "RUNPOD_S3_TARGET": config.s3_target,
            "RUNPOD_API_KEY": runpod_api_key,
            **config.r2_credentials.as_env(),
        },
    }


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, object] | None,
) -> dict[str, object]:
    request_headers = dict(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    with urlopen(request, timeout=60) as response:
        raw = response.read().decode("utf-8")
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("RunPod API response must be a JSON object")
    return parsed
