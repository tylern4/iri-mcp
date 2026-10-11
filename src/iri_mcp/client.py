"""AsyncClient factory.

Production uses a plain ``AsyncClient`` bound to the configured base URL with a
fresh client per operation (cheap to create; the IRI API has no session state we
rely on). Tests inject an ``httpx.MockTransport`` and test token this way.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from iri_client import AsyncClient

from .config import Config


@asynccontextmanager
async def client_session(
    config: Config,
    *,
    transport: httpx.BaseTransport | None = None,
    access_token: str | None = None,
) -> AsyncIterator[AsyncClient]:
    """Yield a fresh ``AsyncClient`` for one IRI operation."""
    client = AsyncClient(
        api_base_url=config.api_base_url,
        wait_interval=config.wait_interval,
        transport=transport,
        access_token=access_token,
    )
    try:
        yield client
    finally:
        await client.close()


__all__ = ["client_session"]