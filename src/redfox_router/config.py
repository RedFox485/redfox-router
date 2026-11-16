"""Backend and logical-model configuration for the router (v0).

Backends are OpenAI-compatible endpoints we have verified today (2026-11-15).
A *logical model* is what a client asks for; the router maps it to a priority
list of (backend, upstream_model_id) and rotates on failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import secrets


@dataclass
class Backend:
    id: str
    name: str
    base_url: str
    env_var: str
    key_slug: str
    # Assumed free-tier limits, used only to label estimates when a provider
    # does not return rate-limit headers. -1 = unknown.
    assumed_rpm: int = -1
    assumed_rpd: int = -1
    exposes_headers: bool = False
    notes: str = ""

    def api_key(self) -> str | None:
        return secrets.resolve(self.env_var, self.key_slug)


BACKENDS: dict[str, Backend] = {
    "tokenharbor": Backend(
        id="tokenharbor",
        name="TokenHarbor (Koda, free)",
        base_url="https://tokenharbor.ai/v1",
        env_var="TOKENHARBOR_KODA_API_KEY",
        key_slug="tokenharbor-koda",
        assumed_rpm=-1, assumed_rpd=-1, exposes_headers=False,
        notes="Serves deepseek-v4.1-flash:free and other :free models. No quota headers.",
    ),
    "beatapi": Backend(
        id="beatapi",
        name="BeatAPI (Koda, free)",
        base_url="https://api.beatapi.io/v1",
        env_var="BEAT_API_KEY",
        key_slug="beatapi",
        assumed_rpm=1, assumed_rpd=-1, exposes_headers=False,
        notes="~1 req/min before first top-up. Route sparingly.",
    ),
    "routeway": Backend(
        id="routeway",
        name="Routeway (Koda, free)",
        base_url="https://api.routeway.ai/v1",
        env_var="ROUTEWAY_KODA_API_KEY",
        key_slug="routeway-koda",
        assumed_rpm=5, assumed_rpd=200, exposes_headers=True,
        notes="Returns x-ratelimit-* headers. Quota is SHARED across keys (account bucket).",
    ),
}


@dataclass
class LogicalModel:
    id: str
    display_name: str
    context: int
    output: int
    # priority-ordered (backend_id, upstream_model_id)
    chain: list[tuple[str, str]] = field(default_factory=list)


LOGICAL_MODELS: dict[str, LogicalModel] = {
    "deepseek-flash-v41-free": LogicalModel(
        id="deepseek-flash-v41-free",
        display_name="RedFox Router: DeepSeek Flash V4.1 FREE",
        context=262144, output=32768,
        chain=[
            ("tokenharbor", "deepseek-v4.1-flash:free"),
            ("beatapi", "deepseek-v4.1-flash"),
        ],
    ),
    "gemma-4-26b-free": LogicalModel(
        id="gemma-4-26b-free",
        display_name="RedFox Router: Gemma 4 26B FREE (Routeway)",
        context=131072, output=16384,
        chain=[
            ("routeway", "gemma-4-26b-a4b-it-chimerax:free"),
        ],
    ),
}


def backend_for(logical_id: str) -> list[tuple[Backend, str]]:
    """Resolve a logical model id to its (Backend, upstream_model_id) chain."""
    lm = LOGICAL_MODELS.get(logical_id)
    if lm is None:
        return []
    out = []
    for bid, model in lm.chain:
        b = BACKENDS.get(bid)
        if b is not None:
            out.append((b, model))
    return out
