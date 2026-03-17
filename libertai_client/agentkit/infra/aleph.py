import asyncio
from dataclasses import dataclass
from ipaddress import IPv6Interface
from typing import Any

from aiohttp import ClientSession
from aleph.sdk.chains.ethereum import ETHAccount
from aleph.sdk.client.authenticated_http import (
    AlephHttpClient,
    AuthenticatedAlephHttpClient,
)
from aleph.sdk.conf import settings
from aleph.sdk.query.filters import MessageFilter
from aleph_message.models import (
    Chain,
    InstanceMessage,
    ItemHash,
    MessageType,
    Payment,
    PaymentType,
    StoreMessage,
)
from aleph_message.models.execution.environment import (
    HostRequirements,
    HypervisorType,
    NodeRequirements,
)

from libertai_client.agentkit.chain.constants import (
    ALEPH_API_URLS,
    ALEPH_CREDITS_DECIMALS,
    LIBERTAI_API_BASE,
)

ALEPH_API_URL = "https://api2.aleph.im"
ALEPH_CHANNEL = "libertai-agentkit"

PATH_EXECUTIONS_LIST = "/about/executions/list"
PATH_INSTANCE_NOTIFY = "/control/allocation/notify"


@dataclass
class CRNInfo:
    url: str
    hash: str
    receiver_address: str


DEFAULT_CRN = CRNInfo(
    url="https://crn10.leviathan.so",
    hash="dc3d1d194a990b5c54380c3c0439562fefa42f5a46807cba1c500ec3affecf04",
    receiver_address="0xf0c0ddf11a0dCE6618B5DF8d9fAE3D95e72E04a9",
)


def get_aleph_account(private_key: str) -> ETHAccount:
    key_bytes = bytes.fromhex(private_key.removeprefix("0x"))
    return ETHAccount(key_bytes, chain=Chain.BASE)


def get_user_ssh_pubkey() -> str | None:
    from pathlib import Path

    ssh_dir = Path.home() / ".ssh"
    for name in ["id_ed25519.pub", "id_rsa.pub", "id_ecdsa.pub"]:
        path = ssh_dir / name
        if path.exists():
            return path.read_text().strip()
    return None


@dataclass
class ExistingResources:
    instance_hashes: list[str]

    @property
    def has_any(self) -> bool:
        return bool(self.instance_hashes)

    @property
    def summary(self) -> str:
        if self.instance_hashes:
            n = len(self.instance_hashes)
            return f"{n} instance{'s' if n > 1 else ''}"
        return "none"


async def check_existing_resources(account: ETHAccount) -> ExistingResources:
    async with AlephHttpClient(api_server=ALEPH_API_URL) as client:
        msgs = await client.get_messages(
            message_filter=MessageFilter(
                message_types=[MessageType.instance],
                addresses=[account.get_address()],
                channels=[ALEPH_CHANNEL],
            )
        )
        instance_hashes = [m.item_hash for m in msgs.messages]
    return ExistingResources(instance_hashes=instance_hashes)


async def delete_existing_resources(
    account: ETHAccount, resources: ExistingResources
) -> None:
    if resources.instance_hashes:
        async with AuthenticatedAlephHttpClient(
            account=account, api_server=ALEPH_API_URL
        ) as client:
            for h in resources.instance_hashes:
                await client.forget(
                    hashes=[h],
                    reason="Cleanup before redeployment",
                    channel=ALEPH_CHANNEL,
                )


async def create_instance(
    account: ETHAccount,
    crn: CRNInfo,
    vcpus: int = 2,
    memory: int = 4096,
    ssh_pubkey: str | None = None,
) -> InstanceMessage:
    async with AuthenticatedAlephHttpClient(
        account=account, api_server=ALEPH_API_URL
    ) as client:
        rootfs = settings.DEBIAN_12_QEMU_ROOTFS_ID
        rootfs_message: StoreMessage = await client.get_message(
            item_hash=rootfs, message_type=StoreMessage
        )
        rootfs_size = (
            rootfs_message.content.size
            if rootfs_message.content.size is not None
            else settings.DEFAULT_ROOTFS_SIZE
        )
        ssh_keys = [ssh_pubkey] if ssh_pubkey else []
        instance_message, _status = await client.create_instance(
            rootfs=rootfs,
            rootfs_size=rootfs_size,
            hypervisor=HypervisorType.qemu,
            payment=Payment(
                chain=Chain.BASE,
                type=PaymentType.credit,
                receiver=crn.receiver_address,
            ),
            requirements=HostRequirements(
                node=NodeRequirements(node_hash=ItemHash(crn.hash))
            ),
            channel=ALEPH_CHANNEL,
            address=account.get_address(),
            ssh_keys=ssh_keys,
            metadata={"name": "libertai-agentkit"},
            vcpus=vcpus,
            memory=memory,
            sync=True,
        )
        return instance_message


async def notify_allocation(
    crn: CRNInfo, instance_hash: str, max_retries: int = 5, retry_delay: int = 3
) -> None:
    for attempt in range(max_retries):
        async with ClientSession() as session:
            async with session.post(
                f"{crn.url}{PATH_INSTANCE_NOTIFY}",
                json={"instance": instance_hash},
            ) as resp:
                if resp.ok:
                    return
                error = await resp.text()
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                raise ValueError(f"Allocation failed: {error}")


async def fetch_instance_ip(crn: CRNInfo, instance_hash: str) -> str:
    async with ClientSession() as session:
        async with session.get(f"{crn.url}{PATH_EXECUTIONS_LIST}") as resp:
            resp.raise_for_status()
            executions = await resp.json()
            if instance_hash not in executions:
                return ""
            interface = IPv6Interface(executions[instance_hash]["networking"]["ipv6"])
            return str(interface.ip + 1)


async def wait_for_instance(
    crn: CRNInfo, instance_hash: str, max_attempts: int = 30, interval: int = 10
) -> str:
    for attempt in range(max_attempts):
        ip = await fetch_instance_ip(crn, instance_hash)
        if ip:
            return ip
        if attempt < max_attempts - 1:
            await asyncio.sleep(interval)
    raise TimeoutError(
        f"Instance {instance_hash} did not get an IP after {max_attempts} attempts"
    )


async def get_credits_info(address: str) -> dict:
    for base_url in ALEPH_API_URLS:
        try:
            async with ClientSession() as session:
                async with session.get(
                    f"{base_url}/api/v0/addresses/{address}/balance"
                ) as balance_resp:
                    if not balance_resp.ok:
                        continue
                    balance_data = await balance_resp.json()
                async with session.get(
                    f"{base_url}/api/v0/costs",
                    params={
                        "include_details": "0",
                        "include_size": "true",
                        "address": address,
                    },
                ) as costs_resp:
                    if not costs_resp.ok:
                        continue
                    costs_data = await costs_resp.json()

            def to_usd(credits: float) -> float:
                return credits / (10**ALEPH_CREDITS_DECIMALS)
            balance_usd = to_usd(balance_data["credit_balance"])
            cost_per_second_usd = to_usd(costs_data["summary"]["total_cost_credit"])
            cost_per_day_usd = cost_per_second_usd * 86400
            runway_days = (
                balance_usd / cost_per_day_usd if cost_per_day_usd > 0 else None
            )
            return {
                "balance_usd": balance_usd,
                "cost_per_day_usd": cost_per_day_usd,
                "runway_days": runway_days,
            }
        except Exception:
            continue
    raise RuntimeError("Failed to fetch credits info from all Aleph API endpoints")


async def buy_credits(
    payment_client: Any, address: str, amount: float
) -> dict:
    """Buy Aleph credits via x402 payment. payment_client is an httpx.AsyncClient from libertai_x402."""
    resp = await payment_client.post(
        f"{LIBERTAI_API_BASE}/libertai/aleph-credits",
        json={"address": address, "amount": amount},
    )
    if resp.status_code >= 400 and resp.status_code != 402:
        raise RuntimeError(f"Buy credits failed: {resp.status_code} {resp.text}")
    return resp.json()
