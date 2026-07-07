import pytest

from bench_harness.runpod import RunPodBalanceCheck, build_balance_query, parse_client_balance


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
