from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from fake_iri import FakeIRI
from helpers import SPEC, assert_is_error, assert_tool_error, make_config, text_of
from iri_mcp.client import client_session
from iri_mcp.config import Config
from iri_mcp.runner import IriRunner
from iri_mcp.server import build_server


@pytest.fixture
def fake() -> FakeIRI:
    return FakeIRI()


def _runner_for(fake: FakeIRI, config: Config, *, access_token: str | None = "test-token"):
    def factory():
        return client_session(
            config,
            transport=httpx.MockTransport(fake.handler),
            access_token=access_token,
        )

    return IriRunner(config, client_factory=factory)


@pytest.fixture
def make_runner(fake: FakeIRI):
    def _make(config: Config | None = None, **cfg_overrides: Any) -> IriRunner:
        return _runner_for(fake, config or make_config(**cfg_overrides))

    return _make


@pytest.fixture
def make_server(fake: FakeIRI):
    """Build a fully-registered server wired to the fake API."""

    def _make(
        config: Config | None = None, *, access_token: str | None = "test-token"
    ):
        cfg = config or make_config()
        return build_server(cfg, _runner_for(fake, cfg, access_token=access_token))

    return _make


@pytest.fixture(autouse=True)
def _quiet_http_logging():
    """Keep per-request httpx INFO chatter out of captured test output."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    yield


__all__ = [
    "SPEC",
    "assert_is_error",
    "assert_tool_error",
    "make_config",
    "text_of",
]