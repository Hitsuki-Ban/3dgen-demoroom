from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


DEFAULT_MAX_RUNTIME_MIN = 60


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]


def parse_max_runtime_minutes(env: Mapping[str, str]) -> int:
    raw_value = env.get("MAX_RUNTIME_MIN")
    if raw_value is None:
        return DEFAULT_MAX_RUNTIME_MIN
    try:
        minutes = int(raw_value)
    except ValueError as exc:
        raise ValueError("MAX_RUNTIME_MIN must be a positive integer") from exc
    if minutes <= 0:
        raise ValueError("MAX_RUNTIME_MIN must be a positive integer")
    return minutes


def build_runpod_terminate_request(env: Mapping[str, str]) -> HttpRequest | None:
    pod_id = env.get("RUNPOD_POD_ID")
    if not pod_id:
        return None
    api_key = env.get("RUNPOD_API_KEY")
    if not api_key:
        raise ValueError("RUNPOD_API_KEY is required when RUNPOD_POD_ID is set")
    return HttpRequest(
        method="DELETE",
        url=f"https://rest.runpod.io/v1/pods/{pod_id}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
