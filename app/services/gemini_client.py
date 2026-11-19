from contextlib import contextmanager

import httpx
import httpx2
from google import genai
from google.genai import errors, types
from google.genai._interactions import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
)

from app.core.config import Settings


class GeminiServiceError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def invalid_response() -> GeminiServiceError:
    return GeminiServiceError(502, "Gemini returned an empty or invalid response.")


def _provider_error(status: int, body: object) -> GeminiServiceError:
    if status == 429:
        return GeminiServiceError(429, "Gemini rate limit or quota exceeded.")
    if status in (408, 504):
        return GeminiServiceError(504, "Gemini request timed out.")
    if status == 404:
        return GeminiServiceError(503, "The configured Gemini model is unavailable.")
    if status == 400 and isinstance(body, dict):
        error = body.get("error", body)
        details = error.get("details", []) if isinstance(error, dict) else []
        if isinstance(details, list) and any(
            isinstance(detail, dict) and detail.get("reason") == "API_KEY_INVALID"
            for detail in details
        ):
            return GeminiServiceError(503, "Gemini API key is invalid.")
    if status in (401, 403):
        return GeminiServiceError(503, "Gemini API key is invalid or lacks access.")
    if status == 503:
        return GeminiServiceError(503, "Gemini is temporarily unavailable.")
    return GeminiServiceError(502, "Gemini could not complete the request.")


@contextmanager
def gemini_client(settings: Settings):
    key = settings.gemini_api_key
    if key is None or not key.get_secret_value().strip():
        raise GeminiServiceError(503, "Gemini API key is not configured.")

    try:
        with genai.Client(
            api_key=key.get_secret_value().strip(),
            enterprise=False,
            http_options=types.HttpOptions(
                api_version="v1beta",
                timeout=30_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        ) as client:
            yield client
    except errors.APIError as error:
        raise _provider_error(error.code, error.details) from None
    except APIStatusError as error:
        raise _provider_error(error.status_code, error.body) from None
    except (APITimeoutError, httpx.TimeoutException, httpx2.TimeoutException, TimeoutError):
        raise GeminiServiceError(504, "Gemini request timed out.") from None
    except (APIConnectionError, httpx.RequestError, httpx2.RequestError):
        raise GeminiServiceError(503, "Could not connect to Gemini.") from None
    except (APIResponseValidationError, ValueError):
        raise invalid_response() from None
