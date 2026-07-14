"""Registry of supported agent runtime integrations."""
from __future__ import annotations

from .claude_code import INTEGRATION as CLAUDE_CODE
from .codex import INTEGRATION as CODEX
from .common import RuntimeIntegration
from .opencode import INTEGRATION as OPENCODE

_INTEGRATIONS = {
    integration.name: integration
    for integration in (CLAUDE_CODE, CODEX, OPENCODE)
}
SUPPORTED_RUNTIMES = tuple(_INTEGRATIONS)


def get_runtime_integration(name: str) -> RuntimeIntegration:
    """Return the registered integration for ``name``."""
    try:
        return _INTEGRATIONS[name]
    except KeyError as exc:
        raise RuntimeError(
            f"Unsupported runtime {name!r}. Expected one of: {', '.join(SUPPORTED_RUNTIMES)}"
        ) from exc


__all__ = ["SUPPORTED_RUNTIMES", "RuntimeIntegration", "get_runtime_integration"]
