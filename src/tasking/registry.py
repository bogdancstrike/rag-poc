"""Task dispatch registry.

Domain modules register their handlers at import time with @register().
The consumer calls dispatch() to route a task dict to the correct handler.
tasking/ never imports from domain modules — registration is push-based.
"""
from typing import Callable

_HANDLERS: dict[str, Callable] = {}


def register(task_type: str):
    """Decorator: ``@register("my_task_type")`` registers a handler function."""
    def decorator(fn: Callable) -> Callable:
        _HANDLERS[task_type] = fn
        return fn
    return decorator


def dispatch(task: dict) -> None:
    """Route a task dict to its registered handler. Raises KeyError if unknown."""
    task_type = task.get("task_type", "")
    handler = _HANDLERS.get(task_type)
    if handler is None:
        raise KeyError(f"No handler registered for task_type={task_type!r}")
    handler(task)


def registered_types() -> list[str]:
    return list(_HANDLERS.keys())
