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
_RUNNER_POISONED = False
_CANCELLATION_CLEANUP_GRACE = 0.05


def _close_runner() -> None:
    global _RUNNER_CLOSED
    with _RUNNER_LOCK:
        if not _RUNNER_CLOSED:
            if not _RUNNER_POISONED:
                _RUNNER.close()
            _RUNNER_CLOSED = True


atexit.register(_close_runner)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
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


def _runner_unavailable_error(model):
    return RuntimeError(
        "LLM async runner is unavailable after cancellation cleanup exceeded "
        f"the {_CANCELLATION_CLEANUP_GRACE:g}s grace; restart the process "
        f"before invoking model={model}"
    )


async def _run_with_cleanup_watchdog(coro, *, stop_after, forced_stop):
    loop = asyncio.get_running_loop()

    def stop_poisoned_loop():
        forced_stop.set()
        loop.stop()

    watchdog = loop.call_later(max(0.0, stop_after), stop_poisoned_loop)
    try:
        return await coro
    finally:
        watchdog.cancel()


async def _invoke_with_total_budget(
    chat_model,
    messages,
    *,
    attempts: int,
    hard_timeout: float,
    started: float,
    deadline: float,
    model: str,
    attempt_state: dict[str, int],
):
    for attempt in range(1, attempts + 1):
        attempt_state["current"] = attempt
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _timeout_error(
                model, hard_timeout, max(1, attempt - 1), attempts,
                time.monotonic() - started,
            ) from None
        timeout_scope = asyncio.timeout(remaining)
        try:
            async with timeout_scope:
                return await chat_model.ainvoke(messages)
        except Exception as exc:
            if isinstance(exc, TimeoutError) and timeout_scope.expired():
                raise _timeout_error(
                    model,
                    hard_timeout,
                    attempt,
                    attempts,
                    time.monotonic() - started,
                ) from None
            if attempt >= attempts and isinstance(exc, TimeoutError):
                raise _timeout_error(
                    model,
                    hard_timeout,
                    attempt,
                    attempts,
                    time.monotonic() - started,
                ) from None
            if attempt >= attempts or not _is_transient(exc):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _timeout_error(
                    model, hard_timeout, attempt, attempts,
                    time.monotonic() - started,
                ) from None
            wait = min(30.0, float(2 ** (attempt - 1)), remaining)
            elapsed = time.monotonic() - started
            print(
                f"[llm-guard] model={model} attempt={attempt}/{attempts} "
                f"transient={exc.__class__.__name__} elapsed={elapsed:.2f}s "
                f"remaining={remaining:.2f}s retry_in={wait:.2f}s"
            )
            await asyncio.sleep(wait)

    raise AssertionError("unreachable")


def _run_on_guard_loop(
    coro: Coroutine[Any, Any, Any],
    *,
    deadline: float,
    started: float,
    model: str,
    hard_timeout: float,
    attempts: int,
    attempt_state: dict[str, int],
):
    global _RUNNER_POISONED
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not _RUNNER_LOCK.acquire(timeout=remaining):
        coro.close()
        raise _timeout_error(
            model, hard_timeout, 1, attempts, time.monotonic() - started
        )
    try:
        if _RUNNER_CLOSED:
            coro.close()
            raise RuntimeError("LLM async runner is closed")
        if _RUNNER_POISONED:
            coro.close()
            raise _runner_unavailable_error(model)
        forced_stop = threading.Event()
        try:
            return _RUNNER.run(
                _run_with_cleanup_watchdog(
                    coro,
                    stop_after=(deadline - time.monotonic())
                    + _CANCELLATION_CLEANUP_GRACE,
                    forced_stop=forced_stop,
                )
            )
        except RuntimeError:
            if not forced_stop.is_set():
                raise
            _RUNNER_POISONED = True
            # The non-cooperative task must stay attached to the poisoned loop;
            # closing it would block. Suppress only its intentional teardown noise.
            for pending_task in asyncio.all_tasks(_RUNNER.get_loop()):
                if not pending_task.done():
                    pending_task._log_destroy_pending = False
            raise _timeout_error(
                model,
                hard_timeout,
                attempt_state["current"],
                attempts,
                time.monotonic() - started,
            ) from None
    finally:
        _RUNNER_LOCK.release()


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
    started = time.monotonic()
    deadline = started + hard_timeout
    model = _model_identifier(chat_model)
    attempt_state = {"current": 1}
    return _run_on_guard_loop(
        _invoke_with_total_budget(
            chat_model,
            messages,
            attempts=attempts,
            hard_timeout=hard_timeout,
            started=started,
            deadline=deadline,
            model=model,
            attempt_state=attempt_state,
        ),
        deadline=deadline,
        started=started,
        model=model,
        hard_timeout=hard_timeout,
        attempts=attempts,
        attempt_state=attempt_state,
    )
