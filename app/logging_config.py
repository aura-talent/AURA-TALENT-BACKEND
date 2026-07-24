"""
Logging configuration for Career Ops API
Provides detailed logging for all API calls, LLM interactions, and errors
"""
import logging
import sys
from typing import Any
import json
from datetime import datetime

# Configure logging format
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL = logging.INFO

# Create formatter
formatter = logging.Formatter(
    fmt=LOG_FORMAT,
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(LOG_LEVEL)

# Remove existing handlers
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

# Console handler (stdout) - This goes to systemd journal
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(LOG_LEVEL)
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)

# File handler (optional - logs to file on disk).
# RotatingFileHandler caps total disk usage at maxBytes * (backupCount + 1)
# (50MB here) instead of growing forever — this app logs full request/
# response bodies and tracebacks on every call, which fills the VM's disk
# in days without rotation.
try:
    from logging.handlers import RotatingFileHandler

    file_handler = RotatingFileHandler(
        "/opt/career-ops-backend/app.log",
        maxBytes=10 * 1024 * 1024,  # 10MB per file
        backupCount=4,  # app.log + 4 rotated backups = 50MB max
    )
    file_handler.setLevel(LOG_LEVEL)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
except Exception as e:
    print(f"Warning: Could not create log file: {e}")

# Create logger for this app
logger = logging.getLogger("career-ops")
logger.setLevel(LOG_LEVEL)

# Try to enable Google Cloud Logging
try:
    from .cloud_logging import setup_cloud_logging
    setup_cloud_logging()
except Exception as e:
    logger.info(f"Google Cloud Logging not available: {e}")


def log_request(method: str, path: str, headers: dict, body: Any = None):
    """Log incoming API request"""
    logger.info(f"{'='*80}")
    logger.info(f"➡️  INCOMING REQUEST: {method} {path}")
    logger.info(f"Headers: {json.dumps(dict(headers), default=str, indent=2)}")
    if body:
        try:
            logger.info(f"Body: {json.dumps(body, default=str, indent=2)}")
        except:
            logger.info(f"Body: {str(body)[:500]}")
    logger.info(f"{'='*80}")


def log_response(status_code: int, path: str, response_data: Any = None, duration: float = None):
    """Log API response"""
    logger.info(f"{'='*80}")
    logger.info(f"⬅️  RESPONSE: {status_code} {path}")
    if duration:
        logger.info(f"Duration: {duration:.3f}s")
    if response_data:
        try:
            # Truncate large responses
            response_str = json.dumps(response_data, default=str, indent=2)
            if len(response_str) > 1000:
                response_str = response_str[:1000] + "... (truncated)"
            logger.info(f"Response: {response_str}")
        except:
            logger.info(f"Response: {str(response_data)[:500]}")
    logger.info(f"{'='*80}")


def log_llm_call(prompt: str, model: str, response: str = None, error: str = None):
    """Log LLM API call"""
    logger.info(f"{'='*80}")
    logger.info(f"🤖 LLM CALL: {model}")
    logger.info(f"Prompt (first 500 chars): {prompt[:500]}...")
    if response:
        logger.info(f"Response (first 500 chars): {response[:500]}...")
    if error:
        logger.error(f"Error: {error}")
    logger.info(f"{'='*80}")


def log_error(error: Exception, context: str = ""):
    """Log error with context"""
    logger.error(f"{'='*80}")
    logger.error(f"❌ ERROR in {context}")
    logger.error(f"Type: {type(error).__name__}")
    logger.error(f"Message: {str(error)}")
    import traceback
    logger.error(f"Traceback:\n{traceback.format_exc()}")
    logger.error(f"{'='*80}")


# Set logging levels for noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("google").setLevel(logging.INFO)
logging.getLogger("langchain").setLevel(logging.INFO)
