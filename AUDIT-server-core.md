# Audit Report: Server Core Logic (`mcp_crawl4ai/server.py`)

Exhaustive review of the 4099-line monolithic MCP server file covering all tools,
resources, prompts, lifespan management, validation helpers, state management,
and response formatting.

---

## Summary

| Severity     | Count |
|:-------------|:-----:|
| High         |   4   |
| Medium       |   9   |
| Low          |   9   |
| Enhancement  |   7   |
| **Total**    | **29**|

---

## High

### H-01: `_truncate` on JSON envelopes produces invalid JSON

**Lines 353–362, 2263, 2582**

Both `scrape` and `crawl` serialize their envelope to JSON, then pass the result
through `_truncate()`. If the serialized JSON exceeds `max_chars`, it is sliced
mid-string and a plain-text notice is appended:

```python
content[:bounded_max_chars]
    + "\n\n[Content truncated at ..."
```

This produces **invalid JSON** that will break any client parsing the response.
The truncation notice also makes the returned string longer than `max_chars`
(by ~80 characters), potentially exceeding MCP transport limits.

**Fix:** Truncate individual content fields *before* serialization (which is
partially done via per-item truncation), and either skip envelope-level
truncation or return a valid error envelope when the response is too large.

**Confidence:** Validated — code path is deterministic and reproducible by
sending any request with content exceeding `max_response_chars`.

### H-02: SSRF TOCTOU via DNS rebinding

**Lines 365–400**

URL validation resolves DNS and checks the result against private IP ranges,
but the actual HTTP request happens later inside `crawl4ai`. An attacker can
serve a public IP during validation and a private IP during the subsequent
connection (DNS rebinding). This is a known pattern for SSRF bypass.

**Mitigate:** Pass resolved addresses to the crawler or validate at connection
time (requires upstream crawl4ai support), or re-resolve and check just before
the request.

**Confidence:** Hypothesis — exploitability depends on whether crawl4ai's
underlying HTTP client caches DNS results. Requires empirical validation with a
DNS rebinding test server.

### H-03: Deep crawl discovered URLs bypass SSRF validation

**Lines 2451–2482, 3113–3186**

Only seed URLs passed in `targets` go through `_validate_url`. During deep
crawl traversal, `crawl4ai` discovers and follows links autonomously. These
discovered URLs are never checked against private IP ranges by this server.

If the seed page contains links to internal services (e.g.
`http://169.254.169.254/metadata`), the crawler will follow them, potentially
leaking cloud metadata or internal service data.

**Fix:** Either configure crawl4ai's URL filtering to reject private IPs, or
add a filter chain that blocks private-network patterns for all deep crawl
operations.

**Confidence:** Hypothesis — exploitability depends on whether crawl4ai
internally filters private IPs during link following. Requires verification of
upstream crawl4ai deep-crawl URL handling behavior.

### H-04: `socket.getaddrinfo` blocks the async event loop

**Line 386**

`_validate_url` calls `socket.getaddrinfo(hostname, None)` synchronously inside
an `async` tool handler. Under concurrent requests, this blocks the entire
event loop during DNS resolution, causing latency spikes for all in-flight
requests.

**Fix:** Use `asyncio.get_event_loop().getaddrinfo()` or make `_validate_url`
async and await the lookup.

**Confidence:** Validated — `socket.getaddrinfo` is definitively synchronous;
blocking is observable under concurrent load via event loop stall metrics.

---

## Medium

### M-01: `assert ctx is not None` silently bypassed under `-O`

**Lines 2104, 2382, 2690, 2944, 3289, 3441, 3545, 3604, 3649, 3760, 3823, 3895**

Multiple tools guard context access with bare `assert`. Python's `-O` flag
strips all `assert` statements, turning these into no-ops that will produce
`AttributeError` on `ctx.info()` calls instead of clean error messages.

**Fix:** Replace with `if ctx is None: raise ToolError(...)`.

### M-02: Silent pass-through on DNS resolution failure

**Lines 387–388**

When `socket.getaddrinfo` raises `OSError`, `_validate_url` returns without
error, allowing URLs with unresolvable hostnames through. These will fail later
at crawl time with a generic crawl4ai error instead of a clear SSRF-context
`ToolError`.

**Recommendation:** Raise `ToolError("Unable to resolve hostname: ...")` or log
a warning.

### M-03: No upper bound on `url_filters` pattern list length

**Lines 3083–3110**

`_validate_deep_crawl_url_filter_patterns` validates individual patterns but
imposes no limit on list length. An attacker could send thousands of regex
patterns, causing excessive `FilterChain` compilation time.

**Fix:** Add a `max_patterns` guard (e.g. 50).

### M-04: Unbounded recursion in `_sanitize_artifact_value`

**Lines 1365–1394**

Deeply nested dicts/lists in artifact payloads recurse without a depth guard.
Malicious or malformed crawl results with extreme nesting can hit Python's
recursion limit.

**Fix:** Add a `max_depth` parameter with a default (e.g. 20).

### M-05: `_next_opaque_artifact_id` has no termination guard

**Lines 1412–1418**

The `while True` loop generates random IDs until a unique one is found. If the
artifacts dict is corrupted or extremely large, this could loop indefinitely.

**Fix:** Add a max-attempt counter (e.g. 1000) and raise if exhausted.

### M-06: `_extract_markdown` uses direct attribute access without safety

**Line 1766**

`result.markdown` is accessed directly. If `result` lacks a `markdown` attribute
(possible with crawl4ai API changes), this raises `AttributeError` instead of
gracefully falling back.

**Fix:** Use `getattr(result, "markdown", None)`.

### M-07: `_get_max_response_chars` / `_get_batch_item_chars` ignore lifespan context

**Lines 195–206**

These helpers call `_get_settings()` without passing `ctx`, so they always use
the process-level settings cache rather than the lifespan-context settings
object. If settings differ between calls (e.g. reloaded), the stale cache is
used for truncation decisions throughout all tool calls.

**Fix:** Accept an optional `ctx` parameter and forward it to `_get_settings`.

### M-08: No session registry size limit

Session registry (`session_registry: dict[str, dict[str, int | float]]`) has no
maximum entry count. A malicious client could create unlimited sessions by
generating unique `session_id` values on each request, growing memory without
bound until the server OOMs.

**Fix:** Add a `max_sessions` policy with a configurable default (e.g. 100)
and reject new sessions when the limit is reached.

### M-09: Redundant double-validation of runtime controls

**Lines 2118–2123 (scrape), 2396–2401 (crawl)**

Runtime options (timeout_ms, max_retries, etc.) are already validated by
Pydantic `Field(ge=..., le=...)` inside `CanonicalRuntimeOptions` during
`_normalize_canonical_option_groups`. Then `_validate_optional_runtime_controls`
re-validates the same values. The second pass is harmless but wastes cycles and
adds confusion about which layer is authoritative.

---

## Low

### L-01: ~1200 lines of retired legacy tool code

**Lines 2590–3786**

Seven legacy tools (`crawl_url`, `crawl_many`, `deep_crawl`, `extract_data`,
`take_screenshot`, `get_links`, `get_page_info`, `execute_js`) are defined as
plain `async def` functions (not registered with `@mcp.tool()`) and marked
`pragma: no cover`. They consume ~30% of the file but are never exposed.

**Recommendation:** Move to a `_legacy.py` module or delete entirely if no
external callers depend on them.

### L-02: `_FORMAT_DISPATCH` text conversion is fragile

**Lines 1782–1784**

The "text" format uses a simplistic regex to strip markdown characters:
`re.sub(r"[#*_`]|!?\[([^\]]*)\]\([^)]*\)", r"\1", ...)`. This fails on:
- Nested formatting (`**_bold italic_**`)
- Code blocks (triple backticks)
- Tables, blockquotes
- HTML entities within markdown

### L-03: `compare_pages` prompt lacks URL validation

**Lines 4029–4047**

The `compare_pages` prompt accepts raw URL strings and interpolates them into
the prompt message without any validation. While prompts are user-facing
instructions (not direct tool invocations), malicious URLs could inject
instructions into the LLM prompt.

### L-04: `get_server_config` resource exposes internal settings

**Lines 3935–3956**

The `config://server` resource returns internal configuration details including
hard limits, retention policies, and capability settings. This could help an
attacker probe for weaknesses.

### L-05: `crawl` envelope `data`/`items` inconsistency on single-result deep crawl

**Lines 2561–2562**

When a deep crawl returns exactly one result, `data` is set and `items` is
`None`. But for deep crawls, the user likely expects an items array regardless
of count. The behavior differs from the `scrape` tool where single-target
always uses `data`.

### L-06: Capture artifacts validated twice for session_id requirement

**Lines 1049–1052, 2113–2116**

`_normalize_canonical_option_groups` already validates that `capture_artifacts`
requires `session_id`. The same check is repeated in the `scrape` tool at line
2113. The tool-level check is dead code.

### L-07: `_SETTINGS` global lacks synchronization

**Line 175**

`_SETTINGS: ServerSettings | None = None` is a module-global. While the GIL
protects simple assignment and this is a single-process async server, the
pattern is fragile if the architecture ever evolves.

### L-08: `take_screenshot` viewport params are accepted but unused

**Lines 3548–3554**

The legacy `take_screenshot` tool accepts `viewport_width` and
`viewport_height` parameters with a comment noting they're "for future use."
The parameters are validated but never passed to `CrawlerRunConfig`, so they
have no effect.

### L-09: `crawl_many` legacy tool accesses `r.error_message` without guard

**Line 3062**

On failure (`r.success == False`), the code accesses `r.error_message` directly.
If `error_message` is `None` or missing, this produces `"None"` in the output
instead of a meaningful error.

---

## Enhancement Opportunities

### E-01: Decompose the monolithic 4100-line file

Split into logical modules:
- `server.py` — FastMCP instance, lifespan, entry point
- `tools/scrape.py`, `tools/crawl.py` — canonical tool implementations
- `validation.py` — URL validation, SSRF checks, parameter validators
- `models.py` — Pydantic option group models
- `artifacts.py` — artifact store, capture, retention logic
- `helpers.py` — truncation, content extraction, diagnostics

### E-02: Add structured logging

Replace `ctx.info()`/`ctx.warning()` with Python `logging` module for
server-side observability. MCP context notifications are client-facing; the
server has no internal logging for debugging, monitoring, or alerting.

### E-03: Make `_validate_url` async

Convert to `async def` to use `asyncio.get_event_loop().getaddrinfo()` and
avoid blocking the event loop (addresses H-04).

### E-04: Add MCP server-level rate limiting

The server accepts unlimited concurrent requests. While individual crawl
operations have concurrency limits, a malicious client can still exhaust
resources by sending thousands of requests.

### E-05: Replace `assert` with explicit error handling

All tool functions use `assert ctx is not None`. Replace with proper
conditional checks that raise `ToolError` for safer production behavior
(addresses M-01).

### E-06: Add health check endpoint / resource

No mechanism exists for monitoring the server's health (browser status,
session count, artifact memory usage). A `health://status` resource could
expose operational metrics.

### E-07: Truncate content fields before JSON serialization

Rather than truncating the final serialized envelope (which corrupts JSON),
apply truncation to individual `data`/`content` fields before building the
envelope dict and serializing (addresses H-01).

---

## Files Reviewed

- `mcp_crawl4ai/server.py` (4099 lines) — complete line-by-line review
- `mcp_crawl4ai/__init__.py` (128 lines) — contract constants and types
- `pyproject.toml` (lines 20–24) — dependency declarations

## Methodology

Each function, class, and code path was traced for:
- Correctness (does it do what it claims?)
- Safety (input validation, error handling, resource cleanup)
- Performance (blocking calls, unnecessary work)
- Consistency (envelope shape, error formats, naming)
- Maintainability (code size, duplication, coupling)
