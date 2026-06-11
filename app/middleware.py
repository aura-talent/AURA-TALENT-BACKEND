"""
Middleware for logging all API requests and responses
"""
import time
import json
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse
from .logging_config import logger, log_request, log_response, log_error


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all incoming requests and outgoing responses"""
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log request
        try:
            # Get request body for POST/PUT requests
            body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                body_bytes = await request.body()
                if body_bytes:
                    try:
                        body = json.loads(body_bytes)
                    except:
                        body = body_bytes.decode()[:500]
                
                # Important: create new request with body since we consumed it
                async def receive():
                    return {"type": "http.request", "body": body_bytes}
                request._receive = receive
            
            log_request(
                method=request.method,
                path=request.url.path,
                headers=request.headers,
                body=body
            )
        except Exception as e:
            logger.error(f"Error logging request: {e}")
        
        # Process request
        try:
            response = await call_next(request)
            duration = time.time() - start_time
            
            # Log response
            log_response(
                status_code=response.status_code,
                path=request.url.path,
                duration=duration
            )
            
            return response
            
        except Exception as e:
            duration = time.time() - start_time
            log_error(e, context=f"{request.method} {request.url.path}")
            log_response(
                status_code=500,
                path=request.url.path,
                response_data={"error": str(e)},
                duration=duration
            )
            raise
