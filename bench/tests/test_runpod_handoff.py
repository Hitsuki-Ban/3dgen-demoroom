import io

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import ANY, Stubber

from bench_harness.runpod_handoff import (
    RunPodHandoffTimeout,
    RunPodOwnershipConflict,
    add_custom_headers_from_context,
    claim_cleanup,
    conditional_put_json,
    configure_conditional_put,
    handoff_to_runtime,
    initialize_launcher_ownership,
    move_custom_headers_to_context,
    read_ownership,
    transition_ownership,
    wait_for_runtime_ownership,
)
from bench_harness.uploader import S3UploadConfig


TARGET = "s3://3dgen-runs/runs/triposg/test"
POD_ID = "pod-123"
TOKEN = "token"


class FakeEvents:
    def register(self, event, callback, unique_id) -> None:
        pass

    def unregister(self, event, unique_id) -> None:
        pass


class FakeMeta:
    events = FakeEvents()


class FakeBody(io.BytesIO):
    pass


class FakeS3Client:
    meta = FakeMeta()

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.counter = 0
        self.fail_after_next_put = False
        self.before_get = None

    def put_object(self, *, Bucket, Key, Body, ContentType, custom_headers):
        object_key = (Bucket, Key)
        current = self.objects.get(object_key)
        if custom_headers.get("If-None-Match") == "*" and current is not None:
            raise client_error("PreconditionFailed", 412, "PutObject")
        expected_etag = custom_headers.get("If-Match")
        if expected_etag is not None and (current is None or current[1] != expected_etag):
            raise client_error("PreconditionFailed", 412, "PutObject")
        self.counter += 1
        etag = f'"etag-{self.counter}"'
        self.objects[object_key] = (Body, etag)
        if self.fail_after_next_put:
            self.fail_after_next_put = False
            raise OSError("response lost after committed write")
        return {"ETag": etag}

    def get_object(self, *, Bucket, Key):
        if self.before_get is not None:
            self.before_get(self)
        try:
            body, etag = self.objects[(Bucket, Key)]
        except KeyError as error:
            raise client_error("NoSuchKey", 404, "GetObject") from error
        return {"Body": FakeBody(body), "ETag": etag}


def client_error(code: str, status: int, operation: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        operation,
    )


def make_env() -> dict[str, str]:
    return {
        "R2_ENDPOINT": "https://example.r2.cloudflarestorage.com",
        "R2_ACCESS_KEY_ID": "access-key",
        "R2_SECRET_ACCESS_KEY": "secret-key",
    }


def initialize(client: FakeS3Client) -> None:
    initialize_launcher_ownership(TARGET, TOKEN, make_env(), client=client)


def move_owner(client: FakeS3Client, expected: str, next_state: str, transition_id: str) -> None:
    transition_ownership(
        TARGET,
        POD_ID,
        TOKEN,
        make_env(),
        expected_state=expected,
        next_state=next_state,
        transition_id=transition_id,
        client=client,
    )


def owner_state(client: FakeS3Client) -> str:
    config = S3UploadConfig.from_target(TARGET, make_env())
    return read_ownership(client, config).state


def test_launcher_offers_handoff_and_waits_for_runtime_ack() -> None:
    client = FakeS3Client()
    initialize(client)

    def acknowledge_pending(observed_client: FakeS3Client) -> None:
        if owner_state_without_hook(observed_client) != "handoff_pending":
            return
        observed_client.before_get = None
        move_owner(
            observed_client,
            "handoff_pending",
            "runtime",
            "acknowledge-runtime-handoff",
        )

    client.before_get = acknowledge_pending
    record = handoff_to_runtime(
        TARGET,
        POD_ID,
        TOKEN,
        make_env(),
        timeout_seconds=1,
        poll_seconds=0.1,
        client=client,
        monotonic=lambda: 0.0,
        sleep=lambda seconds: None,
    )

    assert record.state == "runtime"
    assert record.transition_id == "acknowledge-runtime-handoff"


def test_launcher_accepts_runtime_that_finishes_and_claims_cleanup_before_ack_read() -> None:
    client = FakeS3Client()
    initialize(client)

    def acknowledge_and_finish(observed_client: FakeS3Client) -> None:
        if owner_state_without_hook(observed_client) != "handoff_pending":
            return
        observed_client.before_get = None
        move_owner(
            observed_client,
            "handoff_pending",
            "runtime",
            "acknowledge-runtime-handoff",
        )
        assert claim_cleanup(
            TARGET,
            POD_ID,
            TOKEN,
            "runtime",
            make_env(),
            client=observed_client,
        ) is True

    client.before_get = acknowledge_and_finish
    record = handoff_to_runtime(
        TARGET,
        POD_ID,
        TOKEN,
        make_env(),
        timeout_seconds=1,
        poll_seconds=0.1,
        client=client,
        monotonic=lambda: 0.0,
        sleep=lambda seconds: None,
    )

    assert record.state == "deleting_runtime"
    assert record.transition_id == "claim-cleanup-runtime"


def owner_state_without_hook(client: FakeS3Client) -> str:
    callback = client.before_get
    client.before_get = None
    try:
        return owner_state(client)
    finally:
        client.before_get = callback


def test_existing_owner_object_fails_fast_before_pod_creation() -> None:
    client = FakeS3Client()
    initialize(client)

    with pytest.raises(RunPodOwnershipConflict, match="already exists"):
        initialize_launcher_ownership(TARGET, "second-token", make_env(), client=client)


def test_lost_initialization_response_is_reconciled_without_stranding_target() -> None:
    client = FakeS3Client()
    client.fail_after_next_put = True

    record = initialize_launcher_ownership(TARGET, TOKEN, make_env(), client=client)

    assert record.state == "launcher"
    assert record.lifecycle_token == TOKEN
    assert record.transition_id == "initialize-launcher"


def test_runtime_timeout_cas_wins_before_launcher_offer() -> None:
    client = FakeS3Client()
    initialize(client)

    should_run = wait_for_runtime_ownership(
        TARGET,
        POD_ID,
        TOKEN,
        make_env(),
        timeout_seconds=1,
        poll_seconds=0.1,
        client=client,
        monotonic=iter((0.0, 2.0)).__next__,
        sleep=lambda seconds: None,
    )

    assert should_run is False
    assert owner_state(client) == "deleting_runtime"
    with pytest.raises(RunPodOwnershipConflict, match="expected launcher"):
        handoff_to_runtime(TARGET, POD_ID, TOKEN, make_env(), client=client)


def test_runtime_ack_cas_wins_after_launcher_offer() -> None:
    client = FakeS3Client()
    initialize(client)
    move_owner(client, "launcher", "handoff_pending", "offer-handoff-to-runtime")

    assert wait_for_runtime_ownership(
        TARGET,
        POD_ID,
        TOKEN,
        make_env(),
        timeout_seconds=1,
        poll_seconds=0.1,
        client=client,
    ) is True
    assert owner_state(client) == "runtime"


def test_launcher_reclaims_unacknowledged_offer_before_runtime_ack() -> None:
    client = FakeS3Client()
    initialize(client)

    with pytest.raises(RunPodHandoffTimeout, match="did not acknowledge"):
        handoff_to_runtime(
            TARGET,
            POD_ID,
            TOKEN,
            make_env(),
            timeout_seconds=1,
            poll_seconds=0.1,
            client=client,
            monotonic=iter((0.0, 2.0)).__next__,
            sleep=lambda seconds: None,
        )

    assert owner_state(client) == "deleting_launcher"
    with pytest.raises(RunPodOwnershipConflict, match="deleting_launcher"):
        wait_for_runtime_ownership(
            TARGET,
            POD_ID,
            TOKEN,
            make_env(),
            timeout_seconds=1,
            poll_seconds=0.1,
            client=client,
        )


def test_runtime_restart_in_deleting_state_retries_cleanup_without_model_ownership() -> None:
    client = FakeS3Client()
    initialize(client)
    move_owner(client, "launcher", "deleting_runtime", "runtime-timeout-cleanup")

    assert wait_for_runtime_ownership(
        TARGET,
        POD_ID,
        TOKEN,
        make_env(),
        timeout_seconds=1,
        poll_seconds=0.1,
        client=client,
    ) is False


def test_only_current_owner_can_claim_cleanup() -> None:
    client = FakeS3Client()
    initialize(client)
    move_owner(client, "launcher", "handoff_pending", "offer-handoff-to-runtime")
    move_owner(client, "handoff_pending", "runtime", "acknowledge-runtime-handoff")

    assert claim_cleanup(TARGET, POD_ID, TOKEN, "launcher", make_env(), client=client) is False
    assert claim_cleanup(TARGET, POD_ID, TOKEN, "runtime", make_env(), client=client) is True
    assert owner_state(client) == "deleting_runtime"


def test_lost_ack_response_is_reconciled_from_strongly_consistent_owner_object() -> None:
    client = FakeS3Client()
    initialize(client)
    move_owner(client, "launcher", "handoff_pending", "offer-handoff-to-runtime")
    client.fail_after_next_put = True

    assert wait_for_runtime_ownership(
        TARGET,
        POD_ID,
        TOKEN,
        make_env(),
        timeout_seconds=1,
        poll_seconds=0.1,
        client=client,
    ) is True
    assert owner_state(client) == "runtime"


def test_owner_token_mismatch_never_allows_cleanup() -> None:
    client = FakeS3Client()
    initialize(client)

    with pytest.raises(RunPodOwnershipConflict, match="token"):
        claim_cleanup(TARGET, POD_ID, "wrong-token", "launcher", make_env(), client=client)


def test_boto3_event_hooks_move_per_request_conditional_headers() -> None:
    params = {"custom_headers": {"If-Match": '"etag-1"'}}
    context = {}
    move_custom_headers_to_context(params, context)
    request = {"headers": {}}
    add_custom_headers_from_context(request, context)

    assert "custom_headers" not in params
    assert request["headers"] == {"If-Match": '"etag-1"'}


def test_conditional_put_is_accepted_by_real_botocore_parameter_validation() -> None:
    client = boto3.client(
        "s3",
        endpoint_url="https://example.r2.cloudflarestorage.com",
        aws_access_key_id="access-key",
        aws_secret_access_key="secret-key",
        region_name="auto",
    )
    config = S3UploadConfig.from_target(TARGET, make_env())
    payload = {
        "lifecycle_token": TOKEN,
        "pod_id": None,
        "protocol_version": 1,
        "state": "launcher",
        "transition_id": "initialize-launcher",
        "updated_at": "2026-07-11T00:00:00Z",
    }

    configure_conditional_put(client)
    with Stubber(client) as stubber:
        stubber.add_response(
            "put_object",
            {"ETag": '"etag-1"'},
            {
                "Bucket": "3dgen-runs",
                "Key": "runs/triposg/test/runpod-owner.json",
                "Body": ANY,
                "ContentType": "application/json",
                "custom_headers": {"If-None-Match": "*"},
            },
        )
        response = conditional_put_json(client, config, payload, {"If-None-Match": "*"})

    assert response["ETag"] == '"etag-1"'
