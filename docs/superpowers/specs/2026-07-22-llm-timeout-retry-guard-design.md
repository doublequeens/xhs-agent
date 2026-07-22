# LLM Timeout and Retry Guard Design

## Context

The GLM and DeepSeek wrappers currently run synchronous `invoke()` calls in a
new `ThreadPoolExecutor` for every retry. A hard timeout abandons the executor
without stopping its running request, then immediately starts another request.
This can leave four provider requests active at once, multiply the configured
timeout into a 16- or 32-minute node delay, and keep the Python process alive
while orphaned executor threads finish.

Provider SDK retries add a second retry layer. The final timeout also re-raises
the empty `concurrent.futures.TimeoutError`, so the run registry records only
`TimeoutError:` without the configured budget or attempt count.

## Goals

- Treat `hard_timeout` as one wall-clock budget for the complete guarded call.
- Cancel the active provider coroutine when that total budget expires.
- Never start a retry while a previous request is still active.
- Keep one retry owner and one bounded exponential-backoff policy.
- Preserve existing model selection, prompts, JSON parsing, tool handling, and
  DeepSeek reasoning-quality settings.
- Emit actionable timeout and retry diagnostics without logging prompt content
  or credentials.

## Non-goals

- Changing workflow topology or bypassing any QA/review node.
- Changing DeepSeek model selection, thinking mode, or reasoning effort.
- Splitting large angle/novelty payloads into batches.
- Adding live provider tests to the default offline test suite.
- Repairing unrelated integration tests that import the removed
  `src.editorial_carousel.strategy` module.

## Selected approach

`invoke_with_hard_timeout` remains the synchronous interface used by the model
wrappers, but it executes `chat_model.ainvoke(messages)` under an asyncio total
deadline. The current workflow calls model wrappers from synchronous LangGraph
nodes, so the guard owns a short-lived event loop for the guarded operation.

The deadline is calculated once, before the first attempt. Each retry receives
only the remaining budget. A timeout cancels the active coroutine and exits
immediately with a descriptive built-in `TimeoutError`; it does not create a
new attempt after the budget is exhausted. Fast transient failures may retry
sequentially while time remains.

The provider clients set SDK retries to zero so that retry count, backoff, and
elapsed-time accounting remain visible in the guard. GLM returns to non-streaming
mode because workflow nodes require a complete JSON response and do not expose
partial chunks. DeepSeek also uses the guard's cancellation boundary while
retaining its current model and thinking configuration.

## Interface and timing semantics

The public helper keeps its current call shape:

```python
invoke_with_hard_timeout(
    chat_model,
    messages,
    *,
    attempts=4,
    hard_timeout=240,
)
```

`attempts` is the maximum number of sequential attempts for fast transient
errors. `hard_timeout` is the maximum elapsed time for all attempts, backoff,
and response collection combined.

The guard validates that `attempts >= 1` and `hard_timeout > 0`. Invalid policy
values fail before contacting a provider.

For each attempt:

1. Calculate the remaining total budget.
2. Run `chat_model.ainvoke(messages)` with that remaining timeout.
3. Return immediately on success.
4. On a transient exception, log metadata and sleep for exponential backoff,
   capped by the remaining budget.
5. On cancellation timeout, raise a descriptive `TimeoutError` and do not retry.
6. On a non-transient exception, re-raise it without retrying.

If transient retries consume the budget, the guard raises the same descriptive
timeout rather than a stale provider error.

## Cancellation and event-loop boundary

The supported production callers are synchronous. If the synchronous helper is
called from a thread that already has a running asyncio event loop, it fails
fast with a clear usage error rather than nesting `asyncio.run()` or creating an
uncancellable worker thread. Async workflow callers should use a dedicated async
guard in a future change; no current production node needs that interface.

Cancellation is cooperative through the provider's async HTTP client. This
removes the executor-orphan failure mode and lets HTTP resources close through
normal async context cleanup.

## Provider configuration

### GLM

- Keep `GLM-5.2` and the Coding Plan base URL.
- Set `streaming=False` because nodes consume only completed JSON.
- Set SDK `max_retries=0`.
- Keep the SDK request timeout no greater than the guard's configured GLM total
  budget so the transport cannot outlive the guard by design.

### DeepSeek

- Keep `deepseek-v4-pro`, thinking enabled, and `reasoning_effort="high"`.
- Set SDK `max_retries=0`.
- Set the SDK request timeout no greater than the configured 480-second total
  guard budget.

## Diagnostics

Guard diagnostics include:

- provider/model identifier when available;
- current attempt and maximum attempts;
- elapsed seconds and remaining total budget;
- exception class for transient failures;
- configured total timeout in the final exception.

Diagnostics never include messages, generated content, API keys, headers, or
full provider exception bodies.

## Testing strategy

Offline regression tests use small async fake models and real guard behavior:

- a never-completing coroutine is cancelled at the total deadline;
- maximum simultaneous active calls remains one;
- a hard timeout produces one provider attempt, even when `attempts=4`;
- transient failures retry sequentially and can eventually succeed;
- non-transient failures are not retried;
- backoff and retries cannot exceed the total budget;
- invalid timing policy values fail before provider invocation;
- timeout messages contain the total budget and attempt count;
- GLM and DeepSeek clients disable SDK retries and use bounded timeouts;
- GLM does not enable streaming.

The focused model tests and full offline suite run after implementation. The
existing two integration collection errors caused by imports of the removed
`src.editorial_carousel.strategy` module are recorded separately and do not
change the acceptance result for this branch.

## Acceptance criteria

- No `ThreadPoolExecutor` or orphan worker remains in the LLM guard.
- A hard timeout cannot create overlapping provider calls.
- One guarded invocation cannot exceed its total budget except for small event
  loop scheduling and cleanup overhead.
- Provider SDK retry counts are zero.
- Timeout errors in the run registry carry an actionable message.
- Existing model factory/cache behavior continues to pass its focused tests.
- No production workflow, content contract, checkpoint, or publishing behavior
  changes outside the model-call boundary.
