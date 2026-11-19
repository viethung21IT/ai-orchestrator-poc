from fastapi import APIRouter

from app.schemas.status import HealthResponse, RootResponse

router = APIRouter()


@router.get("/")
def read_root() -> RootResponse:
    return RootResponse(message="AI Orchestrator is running")


@router.get("/health")
def read_health() -> HealthResponse:
    return HealthResponse(status="ok")
