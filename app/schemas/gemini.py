from math import isclose
from typing import Annotated, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Intent = Literal["kpi", "rag", "graph", "hybrid_graph_rag", "hybrid_kpi_rag", "other"]
Probability = Annotated[float, Field(ge=0, le=1, strict=True)]


class QuestionRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChatResponse(BaseModel):
    answer: str
    model: str


class ClassificationResponse(BaseModel):
    choice: Intent
    confidence: Probability
    probabilities: dict[Intent, Probability]

    @model_validator(mode="after")
    def validate_probabilities(self) -> Self:
        if set(self.probabilities) != set(get_args(Intent)):
            raise ValueError("Missing intent probabilities")
        if not isclose(sum(self.probabilities.values()), 1.0, abs_tol=0.0001):
            raise ValueError("Probabilities must sum to 1")
        selected = self.probabilities[self.choice]
        if selected != max(self.probabilities.values()):
            raise ValueError("Choice must be a most probable intent")
        if not isclose(self.confidence, selected, abs_tol=0.0001):
            raise ValueError("Confidence must match the choice probability")
        return self


class FallbackClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent


class RoutingOutcome(BaseModel):
    final_intent: Intent | None = None
    fallback_used: bool = False
    routing_status: Literal["accepted", "unconfirmed"]
    fallback_error_status: int | None = None


class RoutingResponse(RoutingOutcome):
    initial_intent: Intent
    initial_confidence: Probability
    probabilities: dict[Intent, Probability]
    decision_model: str
    fallback_model: str | None
    latency_ms: float
