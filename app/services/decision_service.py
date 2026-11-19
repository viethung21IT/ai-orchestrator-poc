from app.core.config import Settings
from app.schemas.gemini import ClassificationResponse
from app.services.gemini_client import gemini_client, invalid_response
from app.services.intent_criteria import INTENT_PROMPTS


def classify_question(question: str, settings: Settings) -> ClassificationResponse:
    instructions, criteria = INTENT_PROMPTS[settings.intent_criteria_version]
    with gemini_client(settings) as client:
        result = client.decisions.create(
            model=settings.gemini_decision_model,
            input=question,
            questions={
                "intent": {
                    "type": "choice",
                    "instructions": instructions,
                    "criteria": criteria,
                },
            },
        )
        answer = (result.answers or {}).get("intent")
        if answer is None or answer.type != "choice":
            raise invalid_response()

        return ClassificationResponse(
            choice=answer.choice,
            confidence=answer.confidence,
            probabilities=answer.probabilities,
        )
