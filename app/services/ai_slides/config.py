import os
from dataclasses import dataclass


@dataclass(frozen=True)
class StudioSettings:
    enabled: bool
    api_key: str
    models: tuple[str, ...]
    timeout: float
    calls_per_user: int
    calls_per_site: int
    native_motion: bool


def settings():
    models = [os.getenv("AI_SLIDES_PRIMARY_MODEL", ""), *os.getenv("AI_SLIDES_FALLBACK_MODELS", "").split(",")]
    return StudioSettings(
        enabled=os.getenv("AI_SLIDES_ENABLED", "false").lower() == "true",
        api_key=os.getenv("AI_SLIDES_OPENROUTER_API_KEY", "").strip(),
        models=tuple(dict.fromkeys(model.strip() for model in models if model.strip())),
        timeout=max(5, min(120, float(os.getenv("AI_SLIDES_AI_STEP_TIMEOUT_SECONDS", "85")))),
        calls_per_user=max(1, int(os.getenv("AI_SLIDES_MAX_REQUESTS_PER_USER_DAY", "8"))),
        calls_per_site=max(1, int(os.getenv("AI_SLIDES_MAX_REQUESTS_SERVER_DAY", "40"))),
        native_motion=os.getenv("AI_SLIDES_NATIVE_MOTION_ENABLED", "false").lower() == "true",
    )
