import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AgentConfig(BaseModel):
    agent_id: str


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    cancelled = "cancelled"  # Still active but stopping at the end of the period
    inactive = "inactive"


# TODO: Unify in libertai-utils
class GetAgentResponse(BaseModel):
    id: UUID
    instance_hash: str | None
    name: str
    user_address: str
    monthly_cost: float
    paid_until: datetime
    instance_ip: str | None = None
    subscription_status: SubscriptionStatus
    subscription_id: UUID | None = None
