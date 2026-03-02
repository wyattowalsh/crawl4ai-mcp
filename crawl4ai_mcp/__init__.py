"""Crawl4AI MCP Server — Model Context Protocol server for web crawling."""

from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal, TypedDict

SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION = "scrape-crawl.v1"
SCRAPE_CRAWL_ENVELOPE_FIELDS = (
    "ok",
    "operation",
    "data",
    "error",
    "diagnostics",
    "session",
    "meta",
)
SCRAPE_CRAWL_OPTION_GROUPS: dict[str, tuple[str, ...]] = {
    "extraction": (
        "css_selector",
        "word_count_threshold",
        "schema",
        "extraction_mode",
        "url_filters",
    ),
    "transformation": ("js_code",),
    "conversion": (
        "output_format",
        "capture_artifacts",
        "viewport_width",
        "viewport_height",
    ),
    "runtime": (
        "wait_for",
        "bypass_cache",
        "max_depth",
        "max_pages",
        "crawl_mode",
        "include_external",
        "max_concurrency",
        "rate_limit_base_delay",
        "rate_limit_max_delay",
        "rate_limit_max_retries",
        "dispatcher",
        "timeout_ms",
        "max_retries",
        "retry_backoff_ms",
        "max_content_chars",
    ),
    "diagnostics": ("include_diagnostics",),
    "session": (
        "session_id",
        "session_ttl_seconds",
        "session_max_uses",
        "artifact_ttl_seconds",
        "artifact_max_per_session",
        "artifact_max_total",
        "artifact_max_total_bytes",
    ),
}
SCRAPE_CRAWL_MIGRATION_MAP: dict[str, str] = {
    "crawl_url": "scrape",
    "extract_data": "scrape",
    "take_screenshot": "scrape",
    "get_links": "scrape",
    "get_page_info": "scrape",
    "execute_js": "scrape",
    "crawl_many": "crawl",
    "deep_crawl": "crawl",
    "close_session": "session.close",
    "get_artifact": "session.artifact.get",
}

ScrapeCrawlOperation = Literal["scrape", "crawl"]
ScrapeCrawlOptionGroup = Literal[
    "extraction",
    "transformation",
    "conversion",
    "runtime",
    "diagnostics",
    "session",
]


class ScrapeCrawlError(TypedDict):
    code: str
    message: str


class ScrapeCrawlEnvelopeMeta(TypedDict):
    schema_version: str
    operation: ScrapeCrawlOperation
    legacy_tool: str | None
    option_groups: list[ScrapeCrawlOptionGroup]


class ScrapeCrawlEnvelope(TypedDict):
    ok: bool
    operation: ScrapeCrawlOperation
    data: Any | None
    error: ScrapeCrawlError | None
    diagnostics: dict[str, Any] | None
    session: dict[str, Any] | None
    meta: ScrapeCrawlEnvelopeMeta

try:
    __version__ = version("mcp-crawl4ai")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "__version__",
    "SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION",
    "SCRAPE_CRAWL_ENVELOPE_FIELDS",
    "SCRAPE_CRAWL_OPTION_GROUPS",
    "SCRAPE_CRAWL_MIGRATION_MAP",
    "ScrapeCrawlOperation",
    "ScrapeCrawlOptionGroup",
    "ScrapeCrawlError",
    "ScrapeCrawlEnvelopeMeta",
    "ScrapeCrawlEnvelope",
]
