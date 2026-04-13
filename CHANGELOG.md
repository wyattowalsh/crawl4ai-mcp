# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- No changes yet.

---

## [0.3.1] - 2026-03-05

### Added

- Contract lock constants for the `scrape`/`crawl` cutover with canonical always-JSON envelope keys:
  `schema_version`, `tool`, `ok`, `data`, `items`, `meta`, `warnings`, `error`.
- Fixed option-group taxonomy for contract migration: `extraction`, `transformation`, `conversion`, `runtime`, `diagnostics`, `session`.
- Legacy tool migration map (for compatibility planning): `crawl_url`, `extract_data`, `take_screenshot`, `get_links`, `get_page_info`, `execute_js` -> `scrape`; `crawl_many`, `deep_crawl` -> `crawl`; `close_session` -> `session.close`; `get_artifact` -> `session.artifact.get`.

---

## [0.3.0] - 2026-03-02

### Added

- Auto-detection and installation of Playwright browsers on first server startup.
- `--setup` CLI flag for one-time browser installation (`mcp-crawl4ai --setup`).
- 3 MCP prompts: `summarize_page`, `build_extraction_schema`, `compare_pages`.
- GitHub Actions release workflow with PyPI trusted publishing.
- Enhanced README with collapsible sections, full tool signatures, mermaid architecture diagram.
- SSRF protection for private IP ranges.

### Changed

- **Package renamed to `mcp-crawl4ai`** on PyPI (CLI command remains `mcp-crawl4ai`).
- Version now derived from package metadata (`importlib.metadata`) instead of hardcoded.
- Consolidated issue templates from 10 to 5 (removed overly-granular templates).
- Bumped version to 0.3.0 for PyPI publication.

---

## [0.2.0] - 2026-03-02

### Added

- New tools: `crawl_url`, `crawl_many`, `deep_crawl`, `extract_data`, `take_screenshot`, `get_links`, `get_page_info`, `execute_js`.
- Two MCP resources: `config://server` and `crawl4ai://version`.
- Lifespan-managed `AsyncWebCrawler` singleton for efficient browser reuse across all tool calls.
- Tool annotations (readOnlyHint, destructiveHint, idempotentHint, openWorldHint) on all tools.
- HTTP transport support via `--transport http --host <host> --port <port>`.

### Changed

- Rewrote entire server with FastMCP v3 and crawl4ai's `AsyncWebCrawler`.
- Dependencies reduced from 30+ to 2 (`fastmcp>=3.0.0`, `crawl4ai>=0.8.0`).
- Minimum Python version raised to 3.13+.

### Removed

- Custom aiohttp/BeautifulSoup implementation.
- CrawlerManager, HttpClientManager, MemoryAdaptiveConcurrencyManager, DomainAwareRateLimiter, SitemapProcessor, URLFilter.
- `core/`, `models/`, `utils/` module directories (all functionality now in `server.py`).
- Pydantic v1, raw MCP SDK, aiohttp, BeautifulSoup, HTTPX, Markdownify dependencies.
- YAML configuration file support.
- Old tool names: `batch_crawl`, `extract_structured_data`, `get_page_metadata`, `save_website`, `generate_knowledge_base`.

---

## [0.1.0] - 2025-04-07

### Added

- Initial release with custom MCP SDK implementation.
- Core tools: `crawl_url`, `deep_crawl`.
- STDIO and HTTP/SSE transport support.
- Basic configuration via `config.yaml`.
