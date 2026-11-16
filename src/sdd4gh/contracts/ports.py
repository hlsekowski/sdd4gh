"""Shared ports (structural protocols, no logic).

The model-client port lives here so a consuming application and the
framework's own services depend on the same structural contract. The
framework declares the port; the application supplies the implementation.
"""

from __future__ import annotations

from typing import Any, Protocol


class ModelClientProtocol(Protocol):
    """Port for an OpenAI-compatible model client.

    Implemented by the consuming application and accepted by injection in
    framework services that need model output.
    """

    def chat_json(self, messages: list[dict[str, Any]]) -> dict[str, Any]: ...


__all__ = ["ModelClientProtocol"]
