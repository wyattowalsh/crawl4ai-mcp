# Documentation Accuracy Audit — mcp-crawl4ai

**Date**: 2026-04-13
**Scope**: README.md, AGENTS.md, CHANGELOG.md, .github/CONTRIBUTING.md, docs/content/docs/*.mdx, cross-referenced against `mcp_crawl4ai/server.py` and `pyproject.toml`.

---

## Summary

| Impact | Count |
|--------|-------|
| High   | 5     |
| Medium | 10    |
| Low    | 8     |
| **Total** | **23** |

---

## High Impact

### DOC-H01: AGENTS.md claims "11 tools" — actual canonical count is 4

**File**: `AGENTS.md:19`
**Text**: `server.py` — **All** server logic -- 11 tools, 2 resources, 3 prompts

**Actual**: The server registers **4 canonical tools** (`scrape`, `crawl`, `close_session`, `get_artifact`) via `@mcp.tool()`. There are 8 additional retired/legacy tool functions marked `pragma: no cover - retired legacy surface`, but these are dead code and not part of the canonical surface.

**Correction**: Change "11 tools" to "4 tools" (or "4 canonical tools + 8 retired legacy stubs").

### DOC-H02: README and multiple docs claim "Only 2 runtime dependencies" — actual count is 3

**Files**: `README.md:40`, `README.md:255`, `features.mdx:58`, `architecture.mdx:11` (implied)
**Text**: "Only 2 runtime dependencies — fastmcp and crawl4ai"

**Actual**: `pyproject.toml:20-24` lists **3 dependencies**:
```
fastmcp>=3.0.0
crawl4ai>=0.8.0
pydantic-settings>=2.0
```

`pydantic-settings` is used by `ServerSettings(BaseSettings)` at `server.py:160` for environment-variable-based configuration. It is a runtime dependency, not dev-only.

**Correction**: "Only 3 runtime dependencies — fastmcp, crawl4ai, and pydantic-settings" everywhere.

### DOC-H03: README Environment Variables section says "No environment variables are required" — misleading; env vars DO exist

**File**: `README.md:276`
**Text**: "No environment variables are required. The server uses sensible defaults for all configuration."

**Actual**: The server supports a comprehensive `MCP_CRAWL4AI_*` environment variable namespace via `pydantic-settings`:
- `MCP_CRAWL4AI_DEFAULTS__MAX_RESPONSE_CHARS`
- `MCP_CRAWL4AI_DEFAULTS__BATCH_ITEM_CHARS`
- `MCP_CRAWL4AI_DEFAULTS__CRAWL_MANY_DEFAULT_MAX_CONCURRENCY`
- `MCP_CRAWL4AI_LIMITS__CRAWL_MANY_HARD_MAX_CONCURRENCY`
- `MCP_CRAWL4AI_POLICIES__SESSION_TTL_SECONDS_DEFAULT`
- `MCP_CRAWL4AI_CAPABILITIES__BROWSER_HEADLESS`
- `MCP_CRAWL4AI_CAPABILITIES__BROWSER_TYPE`
- And more via nested delimiter `__`

The `docs/content/docs/index.mdx:100` and `prd.mdx:952` actually reference these env vars in Docker examples, contradicting the README.

**Correction**: Document the supported environment variables or at minimum say "No environment variables are required; the server uses sensible defaults. Optional tuning is available via `MCP_CRAWL4AI_*` environment variables."

### DOC-H04: docs/content/docs/index.mdx has severely stale content from pre-rewrite era

**File**: `docs/content/docs/index.mdx`

Multiple claims that do not match the current codebase:

| Line | Claim | Actual |
|------|-------|--------|
| 26 | "Deep crawling, sitemap parsing" | Sitemap parsing was removed in v0.2.0 (CHANGELOG:69) |
| 27 | "adaptive concurrency management" | No adaptive concurrency; uses fixed `SemaphoreDispatcher` |
| 36-37 | "Memory-adaptive concurrency, connection pooling" | Neither exists; single browser singleton |
| 41 | "Pydantic v2, modular design" | Correct on Pydantic v2, but "modular design" is misleading — it's a single-file server |
| 46 | "Respects robots.txt, identifiable User-Agent, rate limiting, and caching" | No robots.txt enforcement exists in server code; rate limiting is dispatcher-level only for batch crawls |
| 104-119 | Development setup tab: "python -m venv venv" and "pip install -e ." | Project uses `uv`, not venv/pip |
| 162-179 | Python client example uses `MCPClient("http://...")` | This API does not exist in `fastmcp` — the correct class is `fastmcp.Client` with different usage |
| 192-202 | Architecture lists "Core Engine", "Extraction Pipeline", "Resource Manager" | None of these exist as named components; server is a flat single module |
| 218 | "property-based testing" | No property-based testing (hypothesis) is used; tests use standard pytest assertions |

**Correction**: Rewrite `index.mdx` to match the canonical architecture described in README.md and architecture.mdx.

### DOC-H05: CONTRIBUTING.md (.github/) has stale feature claims and wrong MCP resource URI scheme

**File**: `.github/CONTRIBUTING.md`

| Line | Claim | Actual |
|------|-------|--------|
| 42 | "Flexible web crawling (single URL, deep crawl)" | Correct |
| 46 | "Authenticated site access" | No authenticated site access feature exists in the server |
| 165 | "Streaming: Use `$/result/chunk` for large responses" | No streaming/chunking protocol is implemented |
| 171 | "URI Structure: Use `crawl://` scheme consistently" | Actual resource URIs are `config://server` and `crawl4ai://version` — neither uses `crawl://` |

**Correction**: Remove "Authenticated site access" from features list. Remove streaming checklist item or mark as aspirational. Fix URI scheme reference.

---

## Medium Impact

### DOC-M01: CHANGELOG v0.2.0 lists 8 tools — actual canonical surface has 4

**File**: `CHANGELOG.md:53`
**Text**: "New tools: crawl_url, crawl_many, deep_crawl, extract_data, take_screenshot, get_links, get_page_info, execute_js."

**Actual**: These 8 tools were added in v0.2.0 but subsequently retired in v0.3.1 in favor of the canonical 4 (`scrape`, `crawl`, `close_session`, `get_artifact`). The CHANGELOG does not mention this retirement.

**Correction**: Add a "Deprecated" or "Retired" subsection to v0.3.1 listing the 8 legacy tools replaced by the canonical surface.

### DOC-M02: CHANGELOG v0.3.1 lists "session.close" and "session.artifact.get" — these are not actual tool names

**File**: `CHANGELOG.md:25`
**Text**: "`close_session` -> `session.close`; `get_artifact` -> `session.artifact.get`"

**Actual**: The actual tool names are `close_session` and `get_artifact` (unchanged). The migration map implies they were renamed to dot-notation names, which is incorrect.

**Correction**: Clarify that the migration map shows *conceptual grouping*, not actual renames. The tool names remain `close_session` and `get_artifact`.

### DOC-M03: features.mdx mentions only CSS extraction — server also supports XPath

**File**: `docs/content/docs/features.mdx:73`
**Text**: "Extract specific data using CSS selector schemas with JsonCssExtractionStrategy"

**Actual**: Server supports both `css` and `xpath` extraction modes (`VALID_EXTRACTION_MODES = frozenset({"css", "xpath"})` at `server.py:57`), using both `JsonCssExtractionStrategy` and `JsonXPathExtractionStrategy`.

**Correction**: "Extract specific data using CSS or XPath schemas with JsonCssExtractionStrategy / JsonXPathExtractionStrategy."

### DOC-M04: Roadmap v0.2.0 lists "Canonical tool surface: scrape, crawl, close_session, get_artifact" — these were added in v0.3.1

**File**: `docs/content/docs/roadmap.mdx:40`

The canonical 4-tool surface was introduced in v0.3.1 (per CHANGELOG). The v0.2.0 release had the 8 legacy tools. The roadmap incorrectly attributes canonical tools to v0.2.0.

**Correction**: Move the canonical tool listing to a v0.3.x entry or add a v0.3.1 milestone.

### DOC-M05: Roadmap "Future Enhancements" lists "Additional deep crawl strategies beyond BFS" — DFS already exists

**File**: `docs/content/docs/roadmap.mdx:57`
**Text**: "Additional deep crawl strategies beyond BFS"

**Actual**: The server already supports both BFS (`BFSDeepCrawlStrategy`) and DFS (`DFSDeepCrawlStrategy`) via `options.traversal.crawl_mode` (`server.py:3113`).

**Correction**: Remove from future enhancements or reword to "Additional deep crawl strategies beyond BFS/DFS."

### DOC-M06: PRD lists tools that don't exist in the current codebase

**File**: `docs/content/docs/prd.mdx:171-209`

PRD lists: `extract_structured_data`, `save_website`, `get_page_metadata`, `generate_knowledge_base`, `batch_crawl`, `search`. None of these exist as canonical tools. The PRD also lists resources `crawl://results/{session_id}`, `crawl://schemas/{schema_name}`, `crawl://images/{image_id}` — none exist.

**Mitigated by**: The PRD has a callout at line 39: "Historical/archival note: this PRD is retained for background context and should not be treated as the current implementation contract."

**Correction**: The callout is adequate but could be strengthened. Consider adding a "Current Status" column to the tool table showing which PRD tools map to which canonical tools.

### DOC-M07: PRD badge shows "Python 3.14+" — actual requirement is Python 3.13+

**File**: `docs/content/docs/prd.mdx:31`
**Text**: `python-3.14+-blue.svg`

**Actual**: `pyproject.toml:6` says `requires-python = ">=3.13"`.

**Correction**: Change badge to "Python 3.13+".

### DOC-M08: docs/content/docs/index.mdx Python client example is non-functional

**File**: `docs/content/docs/index.mdx:161-179`

The example shows:
```python
from fastmcp import MCPClient
client = MCPClient("http://localhost:8000")
tools = client.list_tools()
result = client.call_tool("scrape", {...})
```

**Actual**: `fastmcp` exports `Client` (not `MCPClient`), and the API is:
```python
from fastmcp import Client
async with Client(mcp) as client:
    tools = await client.list_tools()
    result = await client.call_tool("scrape", {...})
```

The synchronous usage shown doesn't work. The client is also async-only.

**Correction**: Replace with working async example or a `curl` HTTP example for HTTP transport.

### DOC-M09: Server contains ~1200 lines of dead legacy tool code not mentioned in any docs

**File**: `mcp_crawl4ai/server.py:2590–3786`

The server contains 8 unregistered legacy tool functions (`crawl_url`, `crawl_many`, `deep_crawl`, `extract_data`, `take_screenshot`, `get_links`, `get_page_info`, `execute_js`) marked `pragma: no cover - retired legacy surface`. These are regular Python functions — NOT decorated with `@mcp.tool()` — so they are **not** callable by MCP clients. However, their presence is not documented anywhere, and they inflate the server module to ~4100 lines.

**Correction**: Either (a) document the legacy code's existence and planned removal timeline, or (b) remove the dead code from the server module.

### DOC-M10: api-reference.mdx `render` option group only lists fields generically

**File**: `docs/content/docs/api-reference.mdx:140`
**Text**: `render` | `viewport_width`, `viewport_height`

**Actual**: The `RenderOptions` model at `server.py:644-645` has both:
```python
viewport_width: int | None = Field(default=None, ge=320, le=3840)
viewport_height: int | None = Field(default=None, ge=240, le=2160)
```

The doc is correct on field names but does not document the value constraints.

**Correction**: Add range constraints to the render option group documentation.

---

## Low Impact

### DOC-L01: CONTRIBUTING.md (docs site) says "Node.js 18+" for docs — actual requirement unverified

**File**: `docs/content/docs/contributing.mdx:23`
**Text**: "Node.js 18+ (for documentation website)"

This may be correct but should be verified against `docs/package.json` engine requirements.

### DOC-L02: AGENTS.md coverage claim "~98%" is likely stale

**File**: `AGENTS.md:120`
**Text**: "Coverage threshold: 90% (currently ~98%)."

Coverage changes with each code modification. The claim should either be removed or updated after each release.

**Correction**: Change to "Coverage threshold: 90%." and remove the specific percentage.

### DOC-L03: README MCP Inspector command may need `--` separator

**File**: `README.md:166`
**Text**: `npx @modelcontextprotocol/inspector uv --directory . run mcp-crawl4ai`

The `--directory .` flag is for `uv`, not for the inspector. Depending on npx argument parsing, this may need `--` before the uv command.

**Correction**: Verify the command works as-is. If not, add `--` separator.

### DOC-L04: CHANGELOG v0.1.0 mentions "HTTP/SSE transport" — v0.2.0 says SSE was removed

**File**: `CHANGELOG.md:82`
**Text**: "STDIO and HTTP/SSE transport support"

v0.2.0 changed to "HTTP transport support via `--transport http`" with no mention of SSE. The current codebase uses Streamable HTTP (via FastMCP), not SSE.

**Correction**: This is historical and accurate for v0.1.0. No change needed, but could add a note that SSE was replaced.

### DOC-L05: features.mdx comparison table lists "Dependency Count: 2" — should be 3

**File**: `docs/content/docs/features.mdx:139`

Same issue as DOC-H02.

**Correction**: Change to "3".

### DOC-L06: Multiple docs reference `--host 127.0.0.1` but don't mention Docker's `0.0.0.0` difference

**Files**: `README.md:131`, `api-reference.mdx:21`, `features.mdx:106`

The CLI defaults to `127.0.0.1` but the Dockerfile uses `0.0.0.0`. This inconsistency is documented only in the server's stderr warning.

**Correction**: Add a note to the Docker section that the default bind address differs.

### DOC-L07: AGENTS.md says "keep all logic in server.py" — `__init__.py` also has non-trivial logic

**File**: `AGENTS.md:126`
**Text**: "Do not create new files in `mcp_crawl4ai/` -- keep all logic in `server.py`"

**Actual**: `__init__.py` contains version resolution logic and the `SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION` constant. While minor, it contradicts the absolutism of "all logic in server.py."

**Correction**: Rephrase to "Keep tool/resource/prompt logic in `server.py`."

### DOC-L08: docs/content/docs/index.mdx uses `nextra-theme-docs` and `nextra/components` imports — docs site uses Fumadocs

**File**: `docs/content/docs/index.mdx:6-7`
```
import { Tabs, Tab } from 'nextra-theme-docs'
import { Callout } from 'nextra/components'
```

Other docs files import from `fumadocs-ui/components`. The index.mdx appears to use an older framework's imports.

**Correction**: Update imports to use Fumadocs components (`fumadocs-ui/components/tabs`, `fumadocs-ui/components/callout`).

---

## Cross-Document Consistency Matrix

| Fact | README | AGENTS.md | api-reference.mdx | features.mdx | architecture.mdx | index.mdx | CHANGELOG |
|------|--------|-----------|-------------------|-------------|-----------------|-----------|-----------|
| Tool count | 4 | **11** | 4 | (implied 4) | 4 | (not stated) | 8 (v0.2.0) |
| Dependency count | **2** | (not stated) | (not stated) | **2** | (implied 2) | (not stated) | 2 (v0.2.0) |
| Tool names | correct | correct | correct | (not listed) | correct | (not listed) | stale for v0.2.0 |
| Resource URIs | correct | correct | correct | (not listed) | correct | (not listed) | correct |
| Prompt count | 3 | 3 | 3 | (not stated) | 3 | (not stated) | 3 |
| Python version | 3.13+ | 3.13+ | (not stated) | (not stated) | (not stated) | (not stated) | 3.13+ |
| Env vars exist | **"No"** | (not stated) | (not stated) | (not stated) | (not stated) | Yes (Docker example) | (not stated) |

**Bold** = incorrect or inconsistent.

---

## Prioritized Correction Roadmap

### Immediate (blocks user trust)
1. **DOC-H01**: Fix AGENTS.md tool count (11 → 4)
2. **DOC-H02**: Fix dependency count across all docs (2 → 3)
3. **DOC-H03**: Document environment variables in README
4. **DOC-H04**: Rewrite index.mdx to match current architecture

### Short-term (next docs update)
5. **DOC-H05**: Remove stale CONTRIBUTING.md feature claims
6. **DOC-M01**: Add legacy tool retirement to CHANGELOG
7. **DOC-M02**: Clarify migration map naming
8. **DOC-M03**: Add XPath to features.mdx extraction description
9. **DOC-M04**: Fix roadmap version attribution
10. **DOC-M05**: Remove DFS from "future" list
11. **DOC-M08**: Fix Python client example
12. **DOC-M09**: Document legacy code existence or remove dead code

### Low priority
13. Fix remaining Low items (L01–L08)
14. Add "Current Status" column to PRD tool table
