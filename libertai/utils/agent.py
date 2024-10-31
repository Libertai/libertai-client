from libertai.interfaces.agent import AgentConfig


def parse_agent_config_env(env: dict[str, str | None]) -> AgentConfig:
    agent_id = env.get("LIBERTAI_AGENT_ID", None)
    agent_secret = env.get("LIBERTAI_AGENT_SECRET", None)

    if agent_id is None or agent_secret is None:
        raise EnvironmentError(
            f"Missing {'LIBERTAI_AGENT_ID' if agent_id is None else 'LIBERTAI_AGENT_SECRET'} variable in your project's .env.libertai")

    return AgentConfig(id=agent_id, secret=agent_secret)
