"""Shared hard-timeout + retry guard for LLM ``invoke`` calls.

The coding/paas endpoints stream keepalive bytes that defeat httpx's read
timeout, so a stalled call can hang indefinitely. This bounds each attempt with
a wall-clock deadline (run on a worker thread; on timeout the worker is orphaned
via ``shutdown(wait=False)`` because we cannot interrupt its blocked socket
read) and retries transient failures. Both the Zhipu (GLM) and DeepSeek model
clients use it so the agent run cannot get stuck on a single hung API call.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

_TRANSIENT_KEYWORDS = (
    "connection", "connect", "timeout", "timed out", "read", "eof", "reset",
    "unreachable", "503", "502", "api_connection_error", "rate_limit", "hang",
)


def _is_transient(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(k in text for k in _TRANSIENT_KEYWORDS)


def invoke_with_hard_timeout(chat_model, messages, *, attempts: int = 4, hard_timeout: float = 240):
    """Invoke ``chat_model.invoke(messages)`` with a per-attempt wall-clock cap
    and transient-error retry. Returns the model response.

    A worker thread runs the invoke; if it exceeds ``hard_timeout`` it is
    abandoned (``shutdown(wait=False)`` — do NOT use a ``with`` block, whose
    ``__exit__`` would ``shutdown(wait=True)`` and block on the very hung thread
    we are escaping). Orphaned threads are blocked in socket reads we cannot
    interrupt; a bounded number across retries is acceptable.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm-invoke")
        future = executor.submit(chat_model.invoke, messages)
        try:
            result = future.result(timeout=hard_timeout)
            executor.shutdown(wait=False)
            return result
        except FutureTimeout:
            executor.shutdown(wait=False)
            last_exc = TimeoutError("invoke exceeded hard timeout")
            if attempt < attempts - 1:
                wait = min(30, 2 ** attempt)
                print(f"[llm-guard] invoke hung >{hard_timeout}s; "
                      f"retry {attempt + 1}/{attempts - 1} in {wait}s")
                time.sleep(wait)
                continue
            raise
        except Exception as exc:
            executor.shutdown(wait=False)
            last_exc = exc
            if attempt < attempts - 1 and _is_transient(exc):
                wait = min(30, 2 ** attempt)
                print(f"[llm-guard] invoke failed (transient: {exc.__class__.__name__}); "
                      f"retry {attempt + 1}/{attempts - 1} in {wait}s")
                time.sleep(wait)
                continue
            raise
    raise last_exc  # pragma: no cover
