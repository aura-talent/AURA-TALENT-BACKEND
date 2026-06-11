import time
import json
from starlette.types import ASGIApp, Scope, Receive, Send, Message
from .logging_config import logger, log_request, log_response, log_error


class LoggingMiddleware:
    """ASGI Middleware to log all incoming requests and outgoing responses without blocking StreamingResponse"""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        method = scope["method"]
        path = scope["path"]
        
        # Extract headers safely
        headers = {}
        for k, v in scope.get("headers", []):
            try:
                headers[k.decode("utf-8").lower()] = v.decode("utf-8")
            except:
                pass

        body_bytes = b""

        # Wrap receive to read body bytes as they are consumed by the app
        async def logging_receive() -> Message:
            nonlocal body_bytes
            message = await receive()
            if message["type"] == "http.request":
                body_bytes += message.get("body", b"")
            return message

        status_code = [200]

        # Wrap send to intercept response status code
        async def logging_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_code[0] = message["status"]
            await send(message)

        try:
            await self.app(scope, logging_receive, logging_send)
            
            # Request body logging (safely parse json or truncate string)
            body_data = None
            if body_bytes:
                try:
                    body_data = json.loads(body_bytes)
                except:
                    body_data = body_bytes.decode("utf-8", errors="ignore")[:500]

            duration = time.time() - start_time
            log_request(
                method=method,
                path=path,
                headers=headers,
                body=body_data
            )
            log_response(
                status_code=status_code[0],
                path=path,
                duration=duration
            )
        except Exception as e:
            duration = time.time() - start_time
            log_error(e, context=f"{method} {path}")
            log_response(
                status_code=500,
                path=path,
                response_data={"error": str(e)},
                duration=duration
            )
            raise
