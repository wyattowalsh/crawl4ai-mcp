# AGENTS.md -- crawl4ai-mcp

AI agent instructions for this project.

## Stack

- **Runtime**: Python 3.13+
- **Server framework**: FastMCP v3 (`fastmcp>=3.0.0`)
- **Crawler**: crawl4ai (`crawl4ai>=0.8.0`) -- `AsyncWebCrawler` with Playwright/Chromium
- **Package manager**: `uv` (always use `uv run` / `uv add` / `uv sync`)
- **Test runner**: pytest with pytest-asyncio (`asyncio_mode = "auto"`)
- **Linter**: ruff
- **Type checker**: ty

## Key Files

| File | Purpose |
|------|---------|
| `crawl4ai_mcp/server.py` | **All** server logic -- 8 tools, 2 resources, lifespan |
| `crawl4ai_mcp/__init__.py` | Package version only |
| `pyproject.toml` | Project config, dependencies, tool config |
| `tests/conftest.py` | Test fixtures (mock crawler, client) |
| `tests/test_server.py` | 55+ tests -- all in-memory, no browser |
| `tests/manual/` | Manual live test scripts (require browser) |
| `crawl4ai_mcp/py.typed` | PEP 561 typed package marker |
| `.github/workflows/ci.yml` | GitHub Actions CI (test + lint + typecheck + Codecov) |
| `.github/dependabot.yml` | Dependabot for pip + GitHub Actions |
| `.github/assets/img/` | Logo, icon, favicon images |
| `Dockerfile` | Container build for HTTP transport deployment |
| `.pre-commit-config.yaml` | Pre-commit hooks (ruff + pre-commit-hooks) |

## Commands

```bash
# Install
uv sync

# Install browser (first time)
crawl4ai-setup

# Run (stdio -- default for Claude Desktop / MCP clients)
crawl4ai-mcp

# Run (HTTP)
crawl4ai-mcp --transport http --port 8000

# Tests
uv run pytest

# Tests with coverage
uv run pytest --cov=crawl4ai_mcp

# Lint
uv run ruff check crawl4ai_mcp/

# Type check
uv run ty check crawl4ai_mcp/
```

## CI / Pre-commit

```bash
# Install pre-commit hooks
uv run pre-commit install

# Run pre-commit manually
uv run pre-commit run --all-files

# Build Docker image
docker build -t crawl4ai-mcp .

# Run via Docker (HTTP transport)
docker run -p 8000:8000 crawl4ai-mcp
```

## Architecture

```
FastMCP("crawl4ai")
  |-- lifespan: crawler_lifespan
  |     \-- AsyncWebCrawler singleton (headless Chromium)
  |-- 8 tools (all via ctx.lifespan_context["crawler"])
  |-- 2 resources (config://server, crawl4ai://version)
  \-- 3 prompts (summarize_page, build_extraction_schema, compare_pages)
```

## Tool Inventory

| Tool | Purpose |
|------|---------|
| `crawl_url` | Single page -> markdown/html/text |
| `crawl_many` | Batch crawl <=20 URLs concurrently |
| `deep_crawl` | BFS recursive crawl (depth 1-5, max 100 pages) |
| `extract_data` | CSS schema-based structured extraction |
| `take_screenshot` | Full-page base64 PNG |
| `get_links` | Internal + external link extraction |
| `get_page_info` | Lightweight metadata + counts |
| `execute_js` | Run JS on rendered page, return content |

## Prompt Inventory

| Prompt | Purpose |
|--------|---------|
| `summarize_page` | Crawl a URL and summarize its content |
| `build_extraction_schema` | Build a CSS schema for use with extract_data |
| `compare_pages` | Crawl and compare two pages |

## MCP Server Rules (CRITICAL)

1. **No `print()` or stdout writes** -- stdout is the MCP transport
2. **`ToolError` for expected failures** -- always visible to clients
3. **`Annotated[type, Field(description=...)]`** on every tool parameter
4. **Verbose docstrings** -- 3-5 sentences: WHAT, WHEN, WHEN NOT, RETURNS
5. **`annotations` dict on every tool** -- at minimum `readOnlyHint` and `openWorldHint`
6. **`ctx: Context | None = None`** -- every tool testable without MCP runtime
7. **Truncate responses** -- 25K chars default, 5K per batch item

## Testing

Tests use `fastmcp.Client(mcp)` for in-memory testing -- no browser or network required.
The conftest patches `AsyncWebCrawler` with `AsyncMock`. All 55+ tests should pass in <60s.
Coverage threshold: 90% (currently ~98%). Markers: `smoke`, `integration`.

## What NOT to Do

- Do not add dependencies without `uv add`
- Do not write to stdout (`print()`) in any tool or resource
- Do not create new files in `crawl4ai_mcp/` -- keep all logic in `server.py`
- Do not use `asyncio.run()` inside tools -- the server handles the event loop
- Do not hardcode URLs or test against live websites
