"""Minimal in-process event emitter for notification side effects.

Kept intentionally tiny to match this codebase's preference for plain
functions over frameworks (see app/employer/services/wlc.py). Routers emit
named events after a DB write; app/services/notifications.py subscribes to
them at import time and turns each into an email via BackgroundTasks.

This is NOT a message queue — it's synchronous, in-memory, single-process.
Handlers are expected to be fire-and-forget coroutines scheduled by the
caller (via FastAPI's BackgroundTasks), not executed by emit() itself.
"""

from collections import defaultdict
from typing import Awaitable, Callable

from ..logging_config import logger

Handler = Callable[..., Awaitable[None]]

_handlers: dict[str, list[Handler]] = defaultdict(list)


def on(event_name: str):
    """Decorator to register a handler for an event name."""

    def register(fn: Handler) -> Handler:
        _handlers[event_name].append(fn)
        return fn

    return register


async def emit(event_name: str, **payload) -> None:
    """Run every handler registered for event_name with payload as kwargs.

    Never raises — each handler is isolated so one failing notification
    doesn't block the others or bubble up into the caller's request/task.
    """
    for handler in _handlers.get(event_name, []):
        try:
            await handler(**payload)
        except Exception as exc:
            logger.error(
                f"❌ Event handler error: event={event_name} "
                f"handler={handler.__name__} — {type(exc).__name__}: {exc}"
            )
