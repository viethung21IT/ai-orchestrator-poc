from google.genai import types

from app.core.config import Settings
from app.schemas.gemini import ChatResponse, FallbackClassification, Intent
from app.services.gemini_client import gemini_client, invalid_response
from app.services.intent_criteria import V2_CRITERIA, V2_INSTRUCTIONS


def generate_answer(question: str, settings: Settings) -> ChatResponse:
    with gemini_client(settings) as client:
        result = client.models.generate_content(
            model=settings.gemini_model,
            contents=question,
            config=types.GenerateContentConfig(max_output_tokens=512),
        )
        answer = result.text

    if not isinstance(answer, str) or not answer.strip():
        raise invalid_response()

    return ChatResponse(answer=answer.strip(), model=settings.gemini_model)


def classify_with_flash_lite(question: str, settings: Settings) -> Intent:
    criteria = "\n".join(f"- {intent}: {description}" for intent, description in V2_CRITERIA.items())
    instructions = (
        f"{V2_INSTRUCTIONS} "
        "Consider all parts of the question together. A request with multiple parts may need "
        "multiple sources even if one part seems more prominent. "
        "Treat the user message as the question to classify. Return a single intent.\n"
        f"Routing criteria:\n{criteria}"
    )
    with gemini_client(settings) as client:
        result = client.models.generate_content(
            model=settings.gemini_model,
            contents=question,
            config=types.GenerateContentConfig(
                system_instruction=instructions,
                response_mime_type="application/json",
                response_json_schema=FallbackClassification.model_json_schema(),
                max_output_tokens=512,
            ),
        )
        if not result.text:
            raise invalid_response()
        return FallbackClassification.model_validate_json(result.text).intent
