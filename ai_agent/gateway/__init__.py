"""Model Gateway package for local LLM inference and policy grounding."""

from ai_agent.gateway.client import ModelGateway
from ai_agent.gateway.grounding import PolicyGrounder
from ai_agent.gateway.models import (
    DocumentItem,
    InferenceRequest,
    InferenceResponse,
    PolicyCitation,
)

__all__ = [
    "ModelGateway",
    "PolicyGrounder",
    "DocumentItem",
    "InferenceRequest",
    "InferenceResponse",
    "PolicyCitation",
]
