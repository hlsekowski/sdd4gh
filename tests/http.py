"""HTTP mocking utilities for tests."""

from __future__ import annotations

from typing import Any, Protocol
from unittest.mock import MagicMock


class ModelClientProtocol(Protocol):
    """Structural stand-in for the model client port.

    sdd4gh does not own the model client; framework services accept it by
    injection. Declaring the protocol locally keeps the test helper free
    of a qnagym import while preserving the same structural contract.
    """

    def chat_json(self, messages: list[dict[str, Any]]) -> dict[str, Any]: ...


def model_client(response: dict[str, Any]) -> ModelClientProtocol:
    """Create a mock model client that returns the given response."""
    mock = MagicMock(spec=ModelClientProtocol)
    mock.chat_json.return_value = response
    return mock


def model_client_sequence(responses: list[dict[str, Any]]) -> ModelClientProtocol:
    """Create a mock model client that returns a sequence of responses."""
    mock = MagicMock(spec=ModelClientProtocol)
    mock.chat_json.side_effect = responses
    return mock
