"""Local-only guard for the app.

The app can start pipeline runs and write config files, so a web page in
another browser tab must not be able to call it. Two checks:

- the Host header must be 127.0.0.1 or localhost (blocks DNS rebinding);
- every request that changes something carries the token the server put into
  the page it served (X-Pattom-Token), which another site cannot read.
"""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def new_token() -> str:
    return secrets.token_urlsafe(24)


class LocalGuard(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "the app only answers on 127.0.0.1"}, status_code=403)
        if request.method not in SAFE_METHODS and not secrets.compare_digest(
                request.headers.get("x-pattom-token", ""), self.token):
            return JSONResponse({"detail": "missing or wrong app token; reload the page"}, status_code=403)
        return await call_next(request)
