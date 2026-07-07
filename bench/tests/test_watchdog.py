import pytest

from bench_harness.watchdog import (
    build_runpod_terminate_request,
    parse_max_runtime_minutes,
)


def test_parse_max_runtime_minutes_uses_specified_default() -> None:
    assert parse_max_runtime_minutes({}) == 60


def test_parse_max_runtime_minutes_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match="MAX_RUNTIME_MIN"):
        parse_max_runtime_minutes({"MAX_RUNTIME_MIN": "0"})


def test_build_runpod_terminate_request_requires_api_key_when_running_on_runpod() -> None:
    with pytest.raises(ValueError, match="RUNPOD_API_KEY"):
        build_runpod_terminate_request({"RUNPOD_POD_ID": "abc123"})


def test_build_runpod_terminate_request_uses_rest_delete_endpoint() -> None:
    request = build_runpod_terminate_request(
        {"RUNPOD_POD_ID": "abc123", "RUNPOD_API_KEY": "secret-token"}
    )

    assert request.method == "DELETE"
    assert request.url == "https://rest.runpod.io/v1/pods/abc123"
    assert request.headers == {"Authorization": "Bearer secret-token"}
