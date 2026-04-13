# Audit Report: Test Suite Coverage & Quality

Comprehensive review of the test suite across `tests/test_server.py` (1013 lines),
`tests/test_coverage_helpers.py` (382 lines), `tests/test_contract_lock.py` (101
lines), and `tests/conftest.py` (102 lines).

---

## Summary

| Category                  | Count |
|:--------------------------|:-----:|
| Coverage Gap (High)       |   3   |
| Coverage Gap (Medium)     |   5   |
| Coverage Gap (Low)        |   3   |
| Test Quality Issue        |   8   |
| Fixture Improvement       |   3   |
| Marker Consistency        |   2   |
| **Total**                 | **24**|

---

## Coverage Gaps — High

### CG-H01: Lifespan auto-setup failure path (CalledProcessError/FileNotFoundError) untested

**Server lines 293–313** — **REMEDIATED** (`TestLifespanAutoSetupFailures`)

`crawler_lifespan` has a `try/except` block that catches browser startup errors,
runs `crawl4ai-setup`, and retries. Only the *success* path was previously tested.

**Added test cases:**
- `crawl4ai-setup` returns non-zero exit code → `RuntimeError` raised
- `crawl4ai-setup` binary not found → `RuntimeError` raised
- Browser error message does not contain "browser"/"playwright"/"chromium" → original exception re-raised

### CG-H02: `_truncate` on JSON envelope produces invalid JSON — no test

**Server lines 353–365, 2263, 2582** — **REMEDIATED** (`TestTruncationJSONValidity`)

`test_truncation_via_scrape_tool` verifies that truncation occurs but does NOT
verify that the result is valid JSON. This is the #1 bug from the server audit
(H-01).

**Added test cases:**
- Verify `json.loads()` raises on truncated envelope (regression test for H-01)
- Verify notice makes result longer than `max_chars`
- Verify exact boundary behavior (at limit vs one over)

**Remaining:** Per-item truncation keeping envelope valid when items are large
(deferred — requires server-side fix first)

### CG-H03: No test for SSRF bypass via private IP after DNS resolution

**Server lines 389–400** — **REMEDIATED** (`TestSSRFEdgeCases`)

`TestSSRFProtection` had 4 tests but missed several edge cases.

**Added test cases:**
- IPv6 loopback (`::1`) blocked
- IPv6 private `fc00::1` blocked via DNS resolution
- Link-local address (`169.254.169.254`) blocked via DNS resolution
- DNS resolution failure (`OSError`) silent pass-through verified
- Mixed public/private DNS results (any private → blocked)

---

## Coverage Gaps — Medium

### CG-M01: Resource content structure never validated for `crawl4ai://version`

`TestResources.test_version_resource` checks that keys exist but doesn't verify
value types or non-empty strings. `test_config_resource_matches_registered_tools`
is more thorough but still doesn't validate nested settings structure types.

### CG-M02: `_normalize_canonical_option_groups` — unknown/extra keys not tested

The option normalization tests verify valid inputs but never test what happens
when an unknown option group key is passed (e.g. `options.unknown_group`). The
server may silently ignore it or raise — behavior is unverified.

### CG-M03: Artifact retention boundary conditions untested

`test_artifact_store_prune_and_retention_helpers` tests basic retention but
misses boundary conditions:
- Exactly at `artifact_max_per_session` limit (not over)
- Exactly at `artifact_max_total_bytes` limit
- TTL expiry at exact boundary (expires_at == now)
- Multiple sessions competing for total artifact quota

### CG-M04: `scrape` with extraction schema but empty `extracted_content`

**REMEDIATED** (`TestExtractionEmptyContent`)

The server has logic (line 2178) that sets `item["ok"] = False` when extraction
succeeds but `extracted_content` is empty. Previously untested.

### CG-M05: `crawl` deep mode with single result (data vs items envelope shape)

When deep crawl returns exactly 1 result, the envelope uses `data` instead of
`items` (audit finding L-05). No test verifies this behavior or asserts the
contract expectation.

---

## Coverage Gaps — Low

### CG-L01: `_select_content` "text" format output quality

`_select_content` with `output_format="text"` uses a fragile regex to strip
markdown. No test verifies the actual text output quality or exercises edge
cases (code blocks, tables, nested formatting).

### CG-L02: Session `max_uses` enforcement via canonical option groups

Session max_uses is tested via direct `_bind_session_id` call in
`test_coverage_helpers.py` but never through the full `scrape` tool flow with
`options.session.session_max_uses`.

### CG-L03: `crawl` with `traversal.url_filters` containing invalid regex

`_build_deep_crawl_strategy` catches `re.error` from `URLPatternFilter`. No
test verifies that invalid regex patterns in `url_filters.include/exclude`
produce a clear `ToolError`.

---

## Test Quality Issues

### TQ-01: `test_truncation_long_content` doesn't verify truncation length

**test_server.py:697–703**

The test asserts `len(truncated) < len(content)` but doesn't verify the
truncated length against `MAX_RESPONSE_CHARS`. The result could be 1 char
shorter or 1000 chars shorter — both pass. Also doesn't test that the notice
makes the result *longer* than `max_chars` (the actual bug).

### TQ-02: Mock crawler `arun_many` uses `side_effect` lambda, not `return_value`

**conftest.py:93–95**

```python
mock_crawler.arun_many = AsyncMock(
    side_effect=lambda urls, **kw: [mock_crawl_result for _ in urls]
)
```

The `side_effect` is synchronous, not async. `AsyncMock` with a sync
`side_effect` works but diverges from real behavior — real `arun_many` is a
coroutine that returns an async iterable. This could mask bugs related to
async iteration.

### TQ-03: Hardcoded string constants instead of server constant references

Multiple tests use hardcoded strings that should reference server constants:
- `"scrape-crawl.v1"` appears in `test_contract_lock.py:29` — should verify
  against `SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION` (it does, but the expected
  value is a raw string that could drift)
- `EXPECTED_TOOLS` list in `test_server.py:40` is manually maintained
- `RETIRED_LEGACY_TOOLS` is duplicated between `test_server.py:42` and
  `test_contract_lock.py:16`

### TQ-04: E2E test depends on mock, not real crawling

**test_server.py:87–117**

`TestE2EWorkflows` is marked `@pytest.mark.e2e` but uses the same mocked
`client` fixture as unit tests. It tests the MCP protocol flow but not actual
crawling. The marker is misleading — this is an integration test, not e2e.

### TQ-05: `test_scrape_batch_returns_items_and_failure_envelope` overwrites mock

**test_server.py:165**

```python
mock_crawler.arun_many = AsyncMock(return_value=[mock_crawl_result, mock_failed_result])
```

This replaces the `arun_many` set in `conftest.py` but the side_effect vs
return_value semantics differ. The test works but the pattern is fragile.

### TQ-06: `test_capture_and_retrieve_artifacts_with_redaction` assertion is too broad

**test_server.py:586–590**

The test dumps the entire artifact JSON and checks that sensitive substrings
are absent. This works but could produce false positives — e.g. if "cookie"
legitimately appears in page content, the test would fail even though redaction
is correct.

### TQ-07: `_make_crawl_result` always provides all fields

**conftest.py:13–67**

The mock result always has `markdown`, `html`, `cleaned_html`, `screenshot`,
`extracted_content`, etc. No test exercises the code path where `result`
has `None` for optional fields like `markdown` (except the dedicated
`TestExtractMarkdownFallbacks`). This means most tool-level tests never
exercise the defensive fallback code.

### TQ-08: Contract lock test verifies exact field order with `tuple(data)`

**test_server.py:152, 347**

```python
assert tuple(data) == SCRAPE_CRAWL_ENVELOPE_FIELDS
```

This converts dict keys to tuple, asserting exact insertion order. While Python
3.7+ dicts are ordered, this is fragile if serialization changes or if a
middleware reorders keys. Consider using `set(data.keys()) == set(...)` for
shape verification and a separate test for order if order is contractual.

---

## Fixture Improvements

### FI-01: No fixture for failed lifespan / uninitialized context

All tests use the `client` fixture which provides a fully initialized lifespan
context. No fixture exists for testing tool behavior when the lifespan context
is missing or partially initialized (e.g. crawler available but session_registry
missing).

### FI-02: `mock_crawl_result` is mutable and shared across tests

**conftest.py:70–73**

The `mock_crawl_result` fixture returns a new `MagicMock` per test, but tests
that modify it (e.g. `test_capture_and_retrieve_artifacts_with_redaction`
setting `mock_crawl_result.mhtml = "mhtml-blob"`) could leak state if
fixture scope changes.

### FI-03: No parameterized fixtures for output formats

Tests for `output_format` (markdown, html, text, cleaned_html) are ad-hoc.
A `@pytest.fixture(params=["markdown", "html", "text", "cleaned_html"])`
would ensure systematic coverage of all format branches.

---

## Marker Consistency

### MC-01: Missing markers on most test classes

Only `TestDiscovery` (`smoke`), `TestE2EWorkflows` (`e2e`),
`TestSessionAndArtifacts` (`integration`), `TestHelperEdgeCases` (`unit`),
`TestRuntimeGuardrailHelpers` (`unit`), `TestCanonicalOptionNormalization`
(none), and `TestURLValidation` (`unit`) have markers. The remaining 8
classes (`TestScrape`, `TestCrawl`, `TestErrorHandling`, `TestResources`,
`TestSettings`, `TestTruncation`, `TestExtractMarkdownFallbacks`,
`TestPrompts`, `TestPyprojectScripts`, `TestMain`, `TestSetupFlag`,
`TestBrowserAutoDetection`, `TestSmoke`) lack markers entirely.

**Recommendation:** Add `@pytest.mark.integration` to tool-level tests that
use the `client` fixture, `@pytest.mark.unit` to pure-logic tests.

### MC-02: `TestE2EWorkflows` should be `integration`, not `e2e`

As noted in TQ-04, these tests use mocked crawlers and run entirely in-memory.
They test MCP protocol flows, not end-to-end system behavior. Marking them
`e2e` is misleading for CI filtering.

---

## Files Reviewed

- `tests/test_server.py` (1013 lines) — complete
- `tests/test_coverage_helpers.py` (382 lines) — complete
- `tests/test_contract_lock.py` (101 lines) — complete
- `tests/conftest.py` (102 lines) — complete
- `mcp_crawl4ai/server.py` (4099 lines) — cross-referenced for coverage gaps

## Methodology

Each test was traced against the server code to verify:
- What code path is actually exercised
- Whether assertions verify behavior or just structure
- Whether mocks faithfully represent real behavior
- Whether edge cases and failure paths are covered
- Whether markers correctly categorize test intent
