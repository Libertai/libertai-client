import time

import httpx

from libertai_client.agentkit.chain.constants import (
    BASE_RPC_URL,
    USDC_ADDRESS,
    USDC_DECIMALS,
)

# keccak256("balanceOf(address)")[:4]
_BALANCE_OF_SELECTOR = "0x70a08231"


def get_usdc_balance(address: str) -> float:
    padded = address.lower().removeprefix("0x").zfill(64)
    data = _BALANCE_OF_SELECTOR + padded

    resp = httpx.post(
        BASE_RPC_URL,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": USDC_ADDRESS, "data": data}, "latest"],
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload or "result" not in payload:
        error = payload.get("error", {})
        msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        raise RuntimeError(f"Error fetching USDC balance: {msg or 'missing result in JSON-RPC response'}")
    try:
        raw = int(payload["result"], 16)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Error parsing USDC balance from JSON-RPC response") from exc
    return raw / (10**USDC_DECIMALS)


def wait_for_usdc_funding(
    address: str,
    min_amount: float,
    poll_interval: int = 10,
    timeout: int = 600,
) -> float:
    deadline = time.time() + timeout
    while time.time() < deadline:
        balance = get_usdc_balance(address)
        if balance >= min_amount:
            return balance
        time.sleep(poll_interval)
    raise TimeoutError(f"USDC funding not received after {timeout}s")
