import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import RequestTooLarge


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope.get("headers", [])).get(b"content-length")
        if length:
            try:
                if int(length) > self.max_bytes:
                    await self._reject(scope, send)
                    return
            except ValueError:
                pass
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLarge:
            await self._reject(scope, send)

    @staticmethod
    async def _reject(scope: Scope, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "success": False,
                "error": {"code": "request_too_large", "message": "The request body is too large."},
                "processing_time_ms": 0,
            },
        )

        async def empty_receive() -> Message:
            return {"type": "http.disconnect"}

        await response(scope, receive=empty_receive, send=send)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = dict(scope.get("headers", [])).get(b"x-request-id", b"").decode()[:128]
        request_id = request_id or str(uuid.uuid4())
        started = time.perf_counter()

        async def add_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
            await send(message)

        await self.app(scope, receive, add_headers)
