# Debug Toolkit

The Auron debug toolkit lets backend code send temporary, request-scoped diagnostic values to the
frontend without adding persistent logs or changing the endpoint payload consumed by the
application.

Use it to inspect intermediate values, execution order, timings, and handled exceptions while
developing an HTTP request. It is not an application logging, auditing, tracing, or error-reporting
system.

## Quick start

Import the shared helper and add a diagnostic value anywhere in the backend call path of an active
HTTP request:

```python
from app.core import debug


def build_summary(records: list[Record]) -> Summary:
    debug.add(records, label="Records before summarization")
    return summarize(records)
```

Call the endpoint from the Auron frontend. A notification appears in the bottom-right corner with
the latest entry, its source location, and the number of entries captured so far. **View details**
opens the complete history, where individual entries or the full history can be copied.

The endpoint's normal JSON payload is still what frontend application code receives.

## Helpers

All helpers automatically record the calling file, function, and line.

### `debug.add(value, label=None)`

Captures one value and lets execution continue.

```python
debug.add(provider_response, label="Provider response")
```

### `debug.snapshot(**values)`

Captures several named values as one entry.

```python
debug.snapshot(
    organization_id=organization_id,
    question_count=len(questions),
    result_count=len(results),
)
```

### `debug.mark(label)`

Records that execution reached a specific point. A mark has no data payload.

```python
debug.mark("Search completed")
```

### `debug.timer(label)`

Measures a synchronous or asynchronous block and records its duration in milliseconds.

```python
with debug.timer("Build report context"):
    context = build_context(documents)

async with debug.timer("Fetch provider results"):
    results = await provider.search(questions)
```

The timer records a result even when the wrapped block raises an exception.

### `debug.exception(error, label=None)`

Captures an exception's type, message, and traceback location without changing control flow.

```python
try:
    result = await provider.execute()
except ProviderError as error:
    debug.exception(error, label="Provider request failed")
    raise
```

Calling `debug.exception()` does not raise or suppress the supplied exception. The surrounding code
still decides whether to recover or re-raise.

### `debug.stop(value, label=None)`

Captures a final value, interrupts the request, and returns that value with HTTP status `200`.

```python
debug.add(raw_documents, label="Retrieved documents")
debug.stop(filtered_documents, label="Stop after filtering")

# This line is not reached.
return generate_report(filtered_documents)
```

`debug.stop()` works by raising an internal exception that must reach FastAPI. Do not place it inside
a broad `except Exception` block that swallows or replaces exceptions. Prefer catching specific
expected exceptions; if a broad handler is unavoidable, re-raise instead of swallowing the error.

Use `debug.stop()` only for interactive development. It deliberately changes the request's normal
control flow and response status.

## Complete example

```python
from app.core import debug


async def generate_analysis(questions: list[str]) -> Analysis:
    debug.snapshot(question_count=len(questions), questions=questions)

    with debug.timer("Search"):
        documents = search(questions)

    debug.add(documents, label="Search documents")
    debug.mark("Starting analysis generation")

    try:
        return await generate_from_documents(documents)
    except GenerationError as error:
        debug.exception(error, label="Analysis generation failed")
        raise
```

## How responses are handled

When an HTTP request records at least one debug entry, the backend wraps a standard JSON response:

```json
{
  "_auron_payload": { "result": "ok" },
  "_auron_debug": [
    {
      "type": "value",
      "label": "Provider response",
      "location": {
        "file": "backend/app/modules/example/service.py",
        "function": "execute",
        "line": 42
      },
      "data": { "result": "ok" }
    }
  ]
}
```

Frontend API clients use `auronFetch` from `frontend/src/api/http.ts`. It captures the debug entries
in the in-memory debug store and returns a new `Response` containing only `_auron_payload`, so normal
callers continue to receive the original response shape and status.

Use `auronFetch` for new frontend API calls:

```typescript
import { auronFetch } from './http'

const response = await auronFetch('/example')
const payload = await response.json()
```

A direct client such as `curl`, an API client, or a backend test sees the envelope itself because it
does not run the frontend unwrapping step.

The toolkit intentionally leaves these responses unchanged:

- Responses without debug entries
- Streaming responses, including NDJSON
- Files and non-JSON responses
- Empty responses
- HTTP `204` and `304` responses

Debug entries created during those response types are not delivered to the frontend. In particular,
the toolkit never buffers an NDJSON stream to extract debug data; use the stream's existing event
contract when debugging streaming progress.

## Request scope and lifecycle

Debug entries are held in a `ContextVar` that is created for each HTTP request. Concurrent requests
have isolated histories, and the backend clears the context after both successful and failed
requests.

Calling a helper without an active HTTP request raises:

```text
RuntimeError: Auron debug helpers require an active HTTP request
```

Do not use the toolkit from startup hooks, command-line scripts, queue workers, or detached
background work. Use the appropriate logging or operational mechanism for those contexts.

The frontend history is also transient and in memory only:

- **Dismiss** hides the notification but keeps the captured entries.
- A later debug response makes a dismissed notification visible again.
- **Clear all** removes the current browser history.
- Reloading the page removes the history.

Debug entries do not create Application Events and are not stored in PostgreSQL.

## Serialization and safety

The toolkit safely serializes common Python and application values, including:

- Primitives, mappings, sequences, sets, and dataclasses
- `UUID`, `date`, `datetime`, `Decimal`, and `Enum`
- Pydantic models
- Exception type and message
- Loaded SQLAlchemy column attributes, without traversing relationships

Mapping keys containing `password`, `token`, `secret`, `authorization`, `cookie`, `api_key`, or
`apikey` are replaced with `[redacted]`. Circular references, unsupported types, and truncated data
are represented by explicit `_auron_*` markers instead of failing the request.

Current limits are:

- Maximum nesting depth: 6
- Maximum mapping or sequence items: 100
- Maximum string length: 4,000 characters
- Maximum serialized entry size: 64 KiB
- Maximum label length: 200 characters

Automatic redaction is a safety net, not permission to inspect secrets. Never pass credentials,
session tokens, raw authorization headers, cookies, password hashes, or other sensitive values to a
debug helper. Exception messages and labels can also contain sensitive data if application code puts
it there.

Debug data is returned to the client that made the request. Keep calls temporary and remove them
when they are no longer needed.

## Testing

Run the focused backend tests from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_debug.py -q
```

Run the frontend tests from `frontend/`:

```powershell
npm.cmd test
```

Backend coverage includes request interruption, helper order, middleware composition, serialization
limits, response compatibility, context cleanup, concurrent-request isolation, and separation from
Application Events. Frontend coverage includes envelope validation, response preservation, NDJSON
streaming behavior, and the transient store lifecycle.

## Implementation reference

- Backend helpers and middleware: `backend/app/core/debug.py`
- Backend registration: `backend/app/main.py`
- Frontend fetch boundary: `frontend/src/api/http.ts`
- Frontend envelope handling: `frontend/src/debug/debug-envelope.ts`
- Frontend transient store: `frontend/src/debug/debug-store.ts`
- Frontend notification: `frontend/src/debug/DebugNotification.tsx`
- Backend tests: `backend/tests/test_debug.py`
- Frontend tests: `frontend/tests/debug-toolkit.test.ts`
