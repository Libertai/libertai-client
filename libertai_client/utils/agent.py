from base64 import b32encode, b16decode

from libertai_client.interfaces.agent import AgentConfig


def parse_agent_config_env(env: dict[str, str | None]) -> AgentConfig:
    agent_id = env.get("LIBERTAI_AGENT_ID", None)
    agent_secret = env.get("LIBERTAI_AGENT_SECRET", None)

    if agent_id is None or agent_secret is None:
        raise EnvironmentError(
            f"Missing {'LIBERTAI_AGENT_ID' if agent_id is None else 'LIBERTAI_AGENT_SECRET'} variable in your project's .env.libertai")

    return AgentConfig(id=agent_id, secret=agent_secret)

def get_vm_host_url(item_hash: str) -> str:
    # From aleph-client
    hash_base32 = b32encode(b16decode(item_hash.upper())).strip(b"=").lower().decode()
    return f"https://{hash_base32}.aleph.sh"