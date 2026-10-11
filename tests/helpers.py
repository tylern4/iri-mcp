"""Shared test utilities: fixture-agnostic assertions and the canonical job spec.

These live outside ``conftest.py`` so test modules can import them directly
(and so ruff can classify them as first-party alongside ``fake_iri``).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from iri_mcp.config import Config


def make_config(**overrides: Any) -> Config:
    """Hermetic config: no ambient env, tiny wait interval for fast tests."""
    base = {"wait_interval": 0.01}
    base.update(overrides)
    return Config.load([], environ={}).model_copy(update=base)


def text_of(result: Any) -> str:
    """Concatenate the text content of a CallToolResult for assertions."""
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts)


def assert_is_error(result: Any, *needles: str) -> str:
    """Assert an in-process tool result is an error result containing needles."""
    assert result.is_error, "expected tool to fail, but it succeeded"
    text = text_of(result)
    for needle in needles:
        assert needle in text, f"expected {needle!r} in error text:\n{text}"
    return text


def assert_tool_error(exc: ToolError, *needles: str) -> str:
    """Assert a raised ToolError carries each needle in its message."""
    text = str(exc)
    for needle in needles:
        assert needle in text, f"expected {needle!r} in error text:\n{text}"
    return text


SPEC: dict[str, Any] = {
    "name": "hello",
    "executable": "/bin/echo",
    "arguments": ["hello iri"],
    "directory": "/pscratch/sd/e/elvis/tmp",
    "stdout_path": "/pscratch/sd/e/elvis/tmp/hello.out",
    "stderr_path": "/pscratch/sd/e/elvis/tmp/hello.err",
    "account": "m0000",
    "queue_name": "debug",
    "duration": 60,
    "node_count": 1,
    "processes_per_node": 1,
}


__all__ = ["SPEC", "assert_is_error", "assert_tool_error", "make_config", "text_of"]