"""Optional LangSmith tracing.

Enabled purely by env vars (LANGSMITH_TRACING + LANGSMITH_API_KEY). When on,
LangGraph node execution is traced automatically and provider calls are traced
via `traced_llm_call`. When off — or when the langsmith package is missing —
every helper here degrades to a no-op, so nothing else in the app has to care.

Synthetic data only: traces leave the machine, so this stays opt-in per env.
"""

import os
from collections.abc import Callable
from typing import Any, TypeVar

from app.config import Settings, get_settings

F = TypeVar("F", bound=Callable[..., Any])

_configured = False


def configure_tracing(settings: Settings | None = None) -> bool:
    """Export LangSmith env vars for the SDK. Returns True when tracing is on."""
    global _configured
    s = settings or get_settings()
    if not (s.langsmith_tracing and s.langsmith_api_key):
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ.pop("LANGCHAIN_TRACING_V2", None)
        _configured = False
        return False
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"  # older SDK name, still honored
    os.environ["LANGSMITH_API_KEY"] = s.langsmith_api_key
    os.environ["LANGSMITH_ENDPOINT"] = s.langsmith_endpoint
    os.environ["LANGSMITH_PROJECT"] = s.langsmith_project
    _configured = True
    return True


def tracing_enabled() -> bool:
    return _configured and os.environ.get("LANGSMITH_TRACING") == "true"


def traced(name: str, run_type: str = "chain") -> Callable[[F], F]:
    """Decorator that traces a function when langsmith is available.

    Applied at import time, so it must not depend on settings being loaded yet:
    the langsmith SDK itself checks LANGSMITH_TRACING at call time.
    """

    def decorator(fn: F) -> F:
        try:
            from langsmith import traceable
        except ImportError:
            return fn
        decorated: Any = traceable(name=name, run_type=run_type)(fn)  # type: ignore[call-overload]
        return decorated  # type: ignore[no-any-return]

    return decorator


def trace_metadata(**kwargs: Any) -> dict[str, Any]:
    """Config payload for graph invocation; empty when tracing is off."""
    if not tracing_enabled():
        return {}
    return {"metadata": {k: v for k, v in kwargs.items() if v is not None}}
