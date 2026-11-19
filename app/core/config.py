from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


IntentCriteriaVersion = Literal["v1", "v2"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_decision_model: str = "gemini-decision-1"
    intent_criteria_version: IntentCriteriaVersion = "v2"
    intent_confidence_threshold: float = Field(default=0.7, ge=0, le=1)
    intent_fallback_enabled: bool = True
