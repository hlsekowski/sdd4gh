"""Shared ports (structural protocols, no logic).

The model-client port lives here because both sdd4gh services and qnagym
adapters depend on the same structural contract. sdd4gh owns it so the
framework stays installable without qnagym.
"""

from __future__ import annotations

from typing import Any, Protocol


class ModelClientProtocol(Protocol):
    """Port for an OpenAI-compatible model client.

    Implemented by qnagym's adapters/client.py; accepted by injection in
    sdd4gh services that need model output.
    """

    def chat_json(self, messages: list[dict[str, Any]]) -> dict[str, Any]: ...


__all__ = ["ModelClientProtocol"]
