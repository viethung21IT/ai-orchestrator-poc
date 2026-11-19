from time import perf_counter

from app.core.config import Settings
from app.schemas.gemini import Intent, RoutingOutcome, RoutingResponse
from app.services.decision_service import classify_question
from app.services.gemini_client import GeminiServiceError
from app.services.gemini_service import classify_with_flash_lite


def needs_fallback(confidence: float, threshold: float) -> bool:
    return confidence < threshold


def resolve_intent(
    question: str, initial_intent: Intent, confidence: float, settings: Settings,
) -> RoutingOutcome:
    if not needs_fallback(confidence, settings.intent_confidence_threshold):
        return RoutingOutcome(final_intent=initial_intent, routing_status="accepted")
    if not settings.intent_fallback_enabled:
        return RoutingOutcome(routing_status="unconfirmed")

    try:
        intent = classify_with_flash_lite(question, settings)
    except GeminiServiceError as error:
        return RoutingOutcome(
            fallback_used=True,
            routing_status="unconfirmed",
            fallback_error_status=error.status_code,
        )

    return RoutingOutcome(final_intent=intent, fallback_used=True, routing_status="accepted")


def route_question(question: str, settings: Settings) -> RoutingResponse:
    started = perf_counter()
    # /classify can use V1, but routing always starts with the evaluated V2 prompt.
    decision_settings = settings.model_copy(update={"intent_criteria_version": "v2"})
    initial = classify_question(question, decision_settings)
    outcome = resolve_intent(question, initial.choice, initial.confidence, settings)
    return RoutingResponse(
        **outcome.model_dump(),
        initial_intent=initial.choice,
        initial_confidence=initial.confidence,
        probabilities=initial.probabilities,
        decision_model=settings.gemini_decision_model,
        fallback_model=settings.gemini_model if outcome.fallback_used else None,
        latency_ms=round((perf_counter() - started) * 1000, 2),
    )
