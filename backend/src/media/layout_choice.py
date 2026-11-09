"""User-chosen vertical layout, read by the renderer instead of auto-detection.

The choice lives in ``tasks.source_metadata["layout"]``. ``process_task`` binds it
to a ContextVar for the duration of the run (``asyncio.to_thread`` copies the
context), so the planner does not need a new argument through every layer.
``auto`` is the default and leaves the existing behaviour byte-identical.

``custom`` is a layout the user drew; its spec is copied into
``source_metadata["layout_spec"]`` when the task is created, so later edits to
the saved layout never change a run that already started.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Optional

VALID_LAYOUTS = {
    "auto", "reaction_top", "reaction_bottom", "reaction_dynamic", "stack", "speaker",
    "custom",
}

_forced_layout: ContextVar[str] = ContextVar("forced_layout", default="auto")
_layout_spec: ContextVar[Optional[Dict[str, Any]]] = ContextVar("layout_spec", default=None)


def normalize_layout(value: Any) -> str:
    return value if isinstance(value, str) and value in VALID_LAYOUTS else "auto"


def current_layout() -> str:
    return _forced_layout.get()


def current_layout_spec() -> Optional[Dict[str, Any]]:
    return _layout_spec.get()


def bind_layout(value: Optional[Any], spec: Optional[Any] = None) -> str:
    """Set the layout for the current task context; always overwrites, so a
    job never inherits the previous job's choice. ``custom`` without a valid
    spec falls back to ``auto``."""
    chosen = normalize_layout(value)
    normalized: Optional[Dict[str, Any]] = None
    if chosen == "custom":
        from .custom_layout import normalize_layout_spec

        try:
            normalized = normalize_layout_spec(spec)
        except ValueError:
            chosen = "auto"
    _forced_layout.set(chosen)
    _layout_spec.set(normalized)
    return chosen


@contextmanager
def forced_layout(value: Optional[Any], spec: Optional[Any] = None) -> Iterator[None]:
    layout_token, spec_token = _forced_layout.get(), _layout_spec.get()
    bind_layout(value, spec)
    try:
        yield
    finally:
        _forced_layout.set(layout_token)
        _layout_spec.set(spec_token)
