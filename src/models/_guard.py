"""Cancellable total-timeout and retry guard for synchronous LLM callers."""
from __future__ import annotations

import atexit
import asyncio
import threading
import time
from typing import Any, Coroutine

_TRANSIENT_KEYWORDS = (
    "connection", "connect", "timeout", "timed out", "read", "eof", "reset",
    "unreachable", "503", "502", "api_connection_error", "rate_limit", "hang",
)
_RUNNER = asyncio.Runner()
_RUNNER_LOCK = threading.Lock()
_RUNNER_CLOSED = False


def _close_runner() -> None:
    global _RUNNER_CLOSED
    with _RUNNER_LOCK:
        if not _RUNNER_CLOSED:
            _RUNNER.close()
            _RUNNER_CLOSED = True


atexit.register(_close_runner)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, ConnectionError):
        return True
    text = str(exc).lower()
    return any(keyword in text for keyword in _TRANSIENT_KEYWORDS)


def _model_identifier(chat_model: Any) -> str:
    identifier = getattr(chat_model, "model_name", None) or getattr(
        chat_model, "model", None
    )
    return str(identifier or chat_model.__class__.__name__)


def _timeout_error(model, hard_timeout, attempt, attempts, elapsed):
    return TimeoutError(
        "LLM invoke exceeded total hard timeout "
        f"(budget={hard_timeout:g}s, elapsed={elapsed:.2f}s, "
        f"attempt={attempt}/{attempts}, model={model})"
    )


async def _invoke_with_total_budget(
    chat_model, messages, *, attempts: int, hard_timeout: float
):
    started = time.monotonic()
    deadline = started + hard_timeout
    model = _model_identifier(chat_model)
    last_exc = None

    for attempt in range(1, attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _timeout_error(
                model, hard_timeout, max(1, attempt - 1), attempts,
                time.monotonic() - started,
            ) from last_exc
        try:
            async with asyncio.timeout(remaining):
                return await chat_model.ainvoke(messages)
        except TimeoutError as exc:
            raise _timeout_error(
                model, hard_timeout, attempt, attempts, time.monotonic() - started
            ) from exc
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_transient(exc):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _timeout_error(
                    model, hard_timeout, attempt, attempts,
                    time.monotonic() - started,
                ) from exc
            wait = min(30.0, float(2 ** (attempt - 1)), remaining)
            elapsed = time.monotonic() - started
            print(
                f"[llm-guard] model={model} attempt={attempt}/{attempts} "
                f"transient={exc.__class__.__name__} elapsed={elapsed:.2f}s "
                f"remaining={remaining:.2f}s retry_in={wait:.2f}s"
            )
            await asyncio.sleep(wait)

    raise AssertionError("unreachable")


def _run_on_guard_loop(coro: Coroutine[Any, Any, Any]):
    with _RUNNER_LOCK:
        if _RUNNER_CLOSED:
            coro.close()
            raise RuntimeError("LLM async runner is closed")
        return _RUNNER.run(coro)


def invoke_with_hard_timeout(
    chat_model, messages, *, attempts: int = 4, hard_timeout: float = 240
):
    """Invoke an async chat model within one cancellable wall-clock budget."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if hard_timeout <= 0:
        raise ValueError("hard_timeout must be greater than 0")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "invoke_with_hard_timeout cannot run inside a running asyncio event loop"
        )
    return _run_on_guard_loop(
        _invoke_with_total_budget(
            chat_model, messages, attempts=attempts, hard_timeout=hard_timeout
        )
    )
