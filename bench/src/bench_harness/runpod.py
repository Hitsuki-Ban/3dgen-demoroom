from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RUNPOD_GRAPHQL_ENDPOINT = "https://api.runpod.io/graphql"


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
