from fastapi import APIRouter, HTTPException, Request

from app.schemas.gemini import ChatResponse, ClassificationResponse, QuestionRequest, RoutingResponse
from app.services.decision_service import classify_question
from app.services.gemini_client import GeminiServiceError
from app.services.gemini_service import generate_answer
from app.services.intent_router import route_question

router = APIRouter(prefix="/api/v1", tags=["Gemini"])


@router.post("/chat")
def chat(payload: QuestionRequest, request: Request) -> ChatResponse:
    try:
        return generate_answer(payload.question, request.app.state.settings)
    except GeminiServiceError as error:
        raise HTTPException(error.status_code, error.detail) from None


@router.post("/classify")
def classify(payload: QuestionRequest, request: Request) -> ClassificationResponse:
    try:
        return classify_question(payload.question, request.app.state.settings)
    except GeminiServiceError as error:
        raise HTTPException(error.status_code, error.detail) from None


@router.post("/route")
def route(payload: QuestionRequest, request: Request) -> RoutingResponse:
    try:
        return route_question(payload.question, request.app.state.settings)
    except GeminiServiceError as error:
        raise HTTPException(error.status_code, error.detail) from None
