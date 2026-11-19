from fastapi import FastAPI

from app.api.gemini_routes import router as gemini_router
from app.api.routes import router
from app.core.config import Settings

app = FastAPI(
    title="AI Orchestrator",
    description="AI Orchestrator Proof of Concept",
    version="0.1.0",
)
app.state.settings = Settings()
app.include_router(router)
app.include_router(gemini_router)
