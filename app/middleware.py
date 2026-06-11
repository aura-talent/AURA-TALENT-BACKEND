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

        # Read the request body fully
        body_bytes = b""
        more_body = True
        try:
            while more_body:
                message = await receive()
                if message["type"] == "http.disconnect":
                    break
                body_bytes += message.get("body", b"")
                more_body = message.get("more_body", False)
        except Exception as e:
            logger.warning(f"Error reading request body: {e}")

        # Create a mock receive channel to feed cached body to application.
        # After replaying the body, delegate to the real receive so streaming
        # responses only see http.disconnect when the client actually leaves.
        body_sent = False
        async def logging_receive() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            return await receive()

        # Log request immediately before processing
        body_data = None
        if body_bytes:
            try:
                body_data = json.loads(body_bytes)
            except:
                body_data = body_bytes.decode("utf-8", errors="ignore")[:500]

        log_request(
            method=method,
            path=path,
            headers=headers,
            body=body_data
        )

        status_code = [200]
        async def logging_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_code[0] = message["status"]
            await send(message)

        try:
            await self.app(scope, logging_receive, logging_send)
            duration = time.time() - start_time
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

