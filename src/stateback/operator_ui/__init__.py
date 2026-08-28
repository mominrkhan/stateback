"""Packaged Operator UI assets for the local development composition."""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class SpaStaticFiles(StaticFiles):
    """Serve packaged assets and fall back to index.html for SPA routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        reserved = path in {"v1", "health"} or path.startswith(("v1/", "health/"))
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or reserved:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and not reserved:
            return await super().get_response("index.html", scope)
        return response
