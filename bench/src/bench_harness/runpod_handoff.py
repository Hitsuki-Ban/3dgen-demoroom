from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from botocore.exceptions import ClientError

from bench_harness.uploader import S3UploadConfig, create_s3_client


OWNER_OBJECT_NAME = "runpod-owner.json"
OWNER_PROTOCOL_VERSION = 1
OWNER_STATES = frozenset(
    {"launcher", "handoff_pending", "runtime", "deleting_launcher", "deleting_runtime"}
)
OWNER_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class RunPodOwnershipError(RuntimeError):
    pass


class RunPodOwnershipConflict(RunPodOwnershipError):
    pass


class RunPodHandoffTimeout(TimeoutError):
    """The launcher reclaimed cleanup ownership after an unacknowledged handoff."""


@dataclass(frozen=True)
class OwnershipRecord:
    state: str
    lifecycle_token: str
    pod_id: str | None
    transition_id: str
    updated_at: str
    etag: str


def initialize_launcher_ownership(
    target: str,
    lifecycle_token: str,
    env: Mapping[str, str],
    *,
    client: Any | None = None,
    now: Callable[[], str] | None = None,
) -> OwnershipRecord:
    require_token(lifecycle_token)
    config = S3UploadConfig.from_target(target, env)
    s3_client = client if client is not None else create_s3_client(config)
    payload = ownership_payload(
        state="launcher",
        lifecycle_token=lifecycle_token,
        pod_id=None,
        transition_id="initialize-launcher",
        updated_at=(now or utc_now)(),
    )
    try:
        response = conditional_put_json(s3_client, config, payload, {"If-None-Match": "*"})
    except BaseException as write_error:
        try:
            reconciled = read_ownership(s3_client, config)
        except BaseException:
            if isinstance(write_error, ClientError) and is_precondition_failed(write_error):
                raise RunPodOwnershipConflict(
                    f"RunPod ownership object already exists at {target}/{OWNER_OBJECT_NAME}"
                ) from write_error
            raise write_error
        if (
            reconciled.state == "launcher"
            and reconciled.lifecycle_token == lifecycle_token
            and reconciled.pod_id is None
            and reconciled.transition_id == "initialize-launcher"
        ):
            return reconciled
        if isinstance(write_error, ClientError) and is_precondition_failed(write_error):
            raise RunPodOwnershipConflict(
                f"RunPod ownership object already exists at {target}/{OWNER_OBJECT_NAME}"
            ) from write_error
        raise write_error
    return record_from_payload(payload, require_etag(response))


def handoff_to_runtime(
    target: str,
    pod_id: str,
    lifecycle_token: str,
    env: Mapping[str, str],
    *,
    timeout_seconds: float = 60.0,
    poll_seconds: float = 1.0,
    client: Any | None = None,
    now: Callable[[], str] | None = None,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> OwnershipRecord:
    if timeout_seconds <= 0:
        raise ValueError("RunPod handoff timeout_seconds must be positive")
    if poll_seconds <= 0:
        raise ValueError("RunPod handoff poll_seconds must be positive")
    config = S3UploadConfig.from_target(target, env)
    s3_client = client if client is not None else create_s3_client(config)
    transition_ownership(
        target,
        pod_id,
        lifecycle_token,
        env,
        expected_state="launcher",
        next_state="handoff_pending",
        transition_id="offer-handoff-to-runtime",
        client=s3_client,
        now=now,
    )
    monotonic_fn = monotonic or time.monotonic
    sleep_fn = sleep or time.sleep
    deadline = monotonic_fn() + timeout_seconds

    while True:
        current = read_ownership(s3_client, config)
        validate_identity(current, pod_id, lifecycle_token)
        if current.state == "runtime":
            return current
        if current.state == "deleting_runtime":
            if current.transition_id == "claim-cleanup-runtime":
                return current
            raise RunPodOwnershipConflict(
                f"RunPod runtime {pod_id} claimed cleanup before acknowledging handoff"
            )
        if current.state != "handoff_pending":
            raise RunPodOwnershipConflict(
                f"RunPod launcher {pod_id} cannot complete handoff from state {current.state}"
            )
        if monotonic_fn() >= deadline:
            try:
                transition_ownership(
                    target,
                    pod_id,
                    lifecycle_token,
                    env,
                    expected_state="handoff_pending",
                    next_state="deleting_launcher",
                    transition_id="reclaim-unacknowledged-handoff",
                    client=s3_client,
                    now=now,
                    current=current,
                )
            except RunPodOwnershipConflict:
                continue
            raise RunPodHandoffTimeout(
                f"RunPod runtime {pod_id} did not acknowledge ownership within {timeout_seconds:.1f}s"
            )
        sleep_fn(poll_seconds)


def claim_cleanup(
    target: str,
    pod_id: str,
    lifecycle_token: str,
    owner: str,
    env: Mapping[str, str],
    *,
    client: Any | None = None,
    now: Callable[[], str] | None = None,
) -> bool:
    if owner not in {"launcher", "runtime"}:
        raise ValueError("RunPod cleanup owner must be launcher or runtime")
    require_identity(pod_id, lifecycle_token)
    config = S3UploadConfig.from_target(target, env)
    s3_client = client if client is not None else create_s3_client(config)
    current = read_ownership(s3_client, config)
    validate_identity(current, pod_id, lifecycle_token)
    deleting_state = f"deleting_{owner}"
    if current.state == deleting_state:
        return True
    if current.state != owner:
        return False
    transition_ownership(
        target,
        pod_id,
        lifecycle_token,
        env,
        expected_state=owner,
        next_state=deleting_state,
        transition_id=f"claim-cleanup-{owner}",
        client=s3_client,
        now=now,
        current=current,
    )
    return True


def wait_for_runtime_ownership(
    target: str,
    pod_id: str,
    lifecycle_token: str,
    env: Mapping[str, str],
    *,
    timeout_seconds: float,
    poll_seconds: float,
    client: Any | None = None,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> bool:
    require_identity(pod_id, lifecycle_token)
    if timeout_seconds <= 0:
        raise ValueError("RunPod ownership timeout_seconds must be positive")
    if poll_seconds <= 0:
        raise ValueError("RunPod ownership poll_seconds must be positive")
    config = S3UploadConfig.from_target(target, env)
    s3_client = client if client is not None else create_s3_client(config)
    monotonic_fn = monotonic or time.monotonic
    sleep_fn = sleep or time.sleep
    deadline = monotonic_fn() + timeout_seconds

    while True:
        current = read_ownership(s3_client, config)
        validate_identity(current, pod_id, lifecycle_token)
        if current.state == "runtime":
            return True
        if current.state == "deleting_runtime":
            return False
        if current.state == "handoff_pending":
            try:
                transition_ownership(
                    target,
                    pod_id,
                    lifecycle_token,
                    env,
                    expected_state="handoff_pending",
                    next_state="runtime",
                    transition_id="acknowledge-runtime-handoff",
                    client=s3_client,
                    current=current,
                )
            except RunPodOwnershipConflict:
                continue
            return True
        if current.state != "launcher":
            raise RunPodOwnershipConflict(
                f"RunPod runtime {pod_id} cannot acquire ownership from state {current.state}"
            )
        if monotonic_fn() >= deadline:
            try:
                transition_ownership(
                    target,
                    pod_id,
                    lifecycle_token,
                    env,
                    expected_state="launcher",
                    next_state="deleting_runtime",
                    transition_id="runtime-timeout-cleanup",
                    client=s3_client,
                    current=current,
                )
            except RunPodOwnershipConflict:
                continue
            return False
        sleep_fn(poll_seconds)


def transition_ownership(
    target: str,
    pod_id: str,
    lifecycle_token: str,
    env: Mapping[str, str],
    *,
    expected_state: str,
    next_state: str,
    transition_id: str,
    client: Any | None = None,
    now: Callable[[], str] | None = None,
    current: OwnershipRecord | None = None,
) -> OwnershipRecord:
    if expected_state not in OWNER_STATES or next_state not in OWNER_STATES:
        raise ValueError("RunPod ownership transition uses an unknown state")
    require_identity(pod_id, lifecycle_token)
    config = S3UploadConfig.from_target(target, env)
    s3_client = client if client is not None else create_s3_client(config)
    observed = current if current is not None else read_ownership(s3_client, config)
    validate_identity(observed, pod_id, lifecycle_token)
    if observed.state == next_state and observed.transition_id == transition_id:
        return observed
    if observed.state != expected_state:
        raise RunPodOwnershipConflict(
            f"RunPod ownership transition expected {expected_state}, observed {observed.state} for pod {pod_id}"
        )
    payload = ownership_payload(
        state=next_state,
        lifecycle_token=lifecycle_token,
        pod_id=pod_id,
        transition_id=transition_id,
        updated_at=(now or utc_now)(),
    )
    try:
        response = conditional_put_json(s3_client, config, payload, {"If-Match": observed.etag})
    except BaseException as write_error:
        try:
            reconciled = read_ownership(s3_client, config)
        except BaseException:
            raise write_error
        validate_identity(reconciled, pod_id, lifecycle_token)
        if reconciled.state == next_state and reconciled.transition_id == transition_id:
            return reconciled
        if isinstance(write_error, ClientError) and is_precondition_failed(write_error):
            raise RunPodOwnershipConflict(
                f"RunPod ownership transition lost CAS for pod {pod_id}: {observed.state} -> {next_state}"
            ) from write_error
        raise write_error
    return record_from_payload(payload, require_etag(response))


def read_ownership(client: Any, config: S3UploadConfig) -> OwnershipRecord:
    try:
        response = client.get_object(Bucket=config.bucket, Key=ownership_object_key(config))
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in OWNER_NOT_FOUND_CODES:
            raise RunPodOwnershipError("RunPod ownership object is missing") from error
        raise
    body = response["Body"]
    try:
        raw = body.read()
    finally:
        body.close()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("RunPod ownership object must contain a JSON object")
    return record_from_payload(payload, require_etag(response))


def conditional_put_json(
    client: Any,
    config: S3UploadConfig,
    payload: dict[str, object],
    custom_headers: dict[str, str],
) -> dict[str, object]:
    configure_conditional_put(client)
    return client.put_object(
        Bucket=config.bucket,
        Key=ownership_object_key(config),
        Body=(json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"),
        ContentType="application/json",
        custom_headers=custom_headers,
    )


def configure_conditional_put(client: Any) -> None:
    events = client.meta.events
    parameter_event = "before-parameter-build.s3.PutObject"
    call_event = "before-call.s3.PutObject"
    parameter_hook_id = "3dgen-runpod-owner-parameters"
    call_hook_id = "3dgen-runpod-owner-headers"
    events.register(parameter_event, move_custom_headers_to_context, unique_id=parameter_hook_id)
    events.register(call_event, add_custom_headers_from_context, unique_id=call_hook_id)


def move_custom_headers_to_context(params: dict[str, object], context: dict[str, object], **kwargs: object) -> None:
    custom_headers = params.pop("custom_headers", None)
    if custom_headers is not None:
        context["runpod_owner_custom_headers"] = custom_headers


def add_custom_headers_from_context(
    params: dict[str, object], context: dict[str, object], **kwargs: object
) -> None:
    custom_headers = context.get("runpod_owner_custom_headers")
    if custom_headers is not None:
        params["headers"].update(custom_headers)


def ownership_payload(
    *,
    state: str,
    lifecycle_token: str,
    pod_id: str | None,
    transition_id: str,
    updated_at: str,
) -> dict[str, object]:
    return {
        "lifecycle_token": lifecycle_token,
        "pod_id": pod_id,
        "protocol_version": OWNER_PROTOCOL_VERSION,
        "state": state,
        "transition_id": transition_id,
        "updated_at": updated_at,
    }


def record_from_payload(payload: dict[str, object], etag: str) -> OwnershipRecord:
    expected_keys = frozenset(
        {"lifecycle_token", "pod_id", "protocol_version", "state", "transition_id", "updated_at"}
    )
    if frozenset(payload) != expected_keys:
        raise ValueError("RunPod ownership object has invalid fields")
    if payload["protocol_version"] != OWNER_PROTOCOL_VERSION:
        raise ValueError("RunPod ownership object uses an unsupported protocol version")
    state = payload["state"]
    if not isinstance(state, str) or state not in OWNER_STATES:
        raise ValueError("RunPod ownership object has invalid state")
    lifecycle_token = payload["lifecycle_token"]
    if not isinstance(lifecycle_token, str) or not lifecycle_token:
        raise ValueError("RunPod ownership object has invalid lifecycle_token")
    pod_id = payload["pod_id"]
    if pod_id is not None and (not isinstance(pod_id, str) or not pod_id):
        raise ValueError("RunPod ownership object has invalid pod_id")
    transition_id = payload["transition_id"]
    if not isinstance(transition_id, str) or not transition_id:
        raise ValueError("RunPod ownership object has invalid transition_id")
    updated_at = payload["updated_at"]
    if not isinstance(updated_at, str) or not updated_at:
        raise ValueError("RunPod ownership object has invalid updated_at")
    return OwnershipRecord(
        state=state,
        lifecycle_token=lifecycle_token,
        pod_id=pod_id,
        transition_id=transition_id,
        updated_at=updated_at,
        etag=etag,
    )


def validate_identity(record: OwnershipRecord, pod_id: str, lifecycle_token: str) -> None:
    if record.lifecycle_token != lifecycle_token:
        raise RunPodOwnershipConflict("RunPod ownership token does not match this launch")
    if record.pod_id not in {None, pod_id}:
        raise RunPodOwnershipConflict(
            f"RunPod ownership object belongs to pod {record.pod_id}, not {pod_id}"
        )


def ownership_object_key(config: S3UploadConfig) -> str:
    return "/".join(part for part in (config.prefix, OWNER_OBJECT_NAME) if part)


def require_identity(pod_id: str, lifecycle_token: str) -> None:
    if not pod_id.strip():
        raise ValueError("RunPod ownership pod_id is required")
    require_token(lifecycle_token)


def require_token(lifecycle_token: str) -> None:
    if not lifecycle_token.strip():
        raise ValueError("RunPod lifecycle token is required")


def require_etag(response: Mapping[str, object]) -> str:
    etag = response.get("ETag")
    if not isinstance(etag, str) or not etag:
        raise ValueError("R2 ownership response is missing ETag")
    return etag


def is_precondition_failed(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code == "PreconditionFailed" or status == 412


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
