"""External API for the s0ma self-model.

Provides optional REST (FastAPI) and MCP server endpoints for external
tools, monitoring dashboards, and Claude Code integration.

This package requires optional dependencies:
    pip install s0ma-core[api]   # for REST API (FastAPI + uvicorn)
    pip install s0ma-core[mcp]   # for MCP server

The core framework (lifecycle, self-model, verifiers) has zero runtime
dependencies. This package is additive — importing it without the
optional dependencies raises ImportError with a helpful message.
"""

from __future__ import annotations

from s0ma.api.query_engine import QueryEngine

__all__ = ["create_app", "create_mcp_server", "QueryEngine"]


def create_app(*args: object, **kwargs: object) -> object:
    """Create a FastAPI application with self-model endpoints.

    This is a convenience re-export. The actual implementation lives in
    ``s0ma.api.rest.create_app()``.

    Raises:
        ImportError: If FastAPI is not installed.
    """
    from s0ma.api.rest import create_app as _create_app

    return _create_app(*args, **kwargs)


def create_mcp_server(*args: object, **kwargs: object) -> object:
    """Create an MCP server with self-model tools.

    This is a convenience re-export. The actual implementation lives in
    ``s0ma.api.mcp_server.create_mcp_server()``.

    Raises:
        ImportError: If the MCP SDK is not installed.
    """
    from s0ma.api.mcp_server import create_mcp_server as _create_mcp_server

    return _create_mcp_server(*args, **kwargs)  # type: ignore[arg-type]
