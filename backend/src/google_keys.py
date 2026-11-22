"""Spare Google API keys for when one runs out of quota.

``GOOGLE_API_KEY`` is the first key; ``GOOGLE_API_KEYS`` (comma separated) adds
more. When Gemini answers 429 the next key takes over at once and stays in use
for later calls. With no spare keys nothing changes.

Quota belongs to the Google Cloud project, so spare keys only help when they
come from different projects or accounts.
"""

import logging
import os
import re
from typing import Any, Dict, List

from pydantic_ai.exceptions import ModelHTTPError

from .config import get_config

logger = logging.getLogger(__name__)

_current = 0


def all_keys() -> List[str]:
    keys = [get_config().google_api_key or ""]
    keys += re.split(r"[,\s]+", os.getenv("GOOGLE_API_KEYS", ""))
    unique: List[str] = []
    for key in (k.strip() for k in keys):
        if key and key not in unique:
            unique.append(key)
    return unique


def _is_gemini(agent: Any) -> bool:
    model = getattr(agent, "model", None)
    return type(model).__name__ == "GoogleModel" and getattr(model, "system", "") in ("google", "google-gla")


def spare_count(agent: Any) -> int:
    return len(all_keys()) - 1 if _is_gemini(agent) else 0


def is_quota_error(error: BaseException) -> bool:
    current, seen = error, set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ModelHTTPError):
            return current.status_code == 429
        current = current.__cause__
    return False


def advance() -> None:
    global _current
    keys = all_keys()
    if keys:
        _current = (_current + 1) % len(keys)
        logger.warning("Google key out of quota; switching to key %s of %s", _current + 1, len(keys))


def run_kwargs(agent: Any) -> Dict[str, Any]:
    """Extra ``agent.run`` arguments: the model on the key currently in use."""
    if spare_count(agent) < 1:
        return {}
    keys = all_keys()
    index = _current % len(keys)
    if index == 0:
        return {}  # the agent's own model already uses the first key
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    base = agent.model
    return {
        "model": GoogleModel(
            base.model_name,
            provider=GoogleProvider(api_key=keys[index]),
            settings=getattr(base, "settings", None),
        )
    }
