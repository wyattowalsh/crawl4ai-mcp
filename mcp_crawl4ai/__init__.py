"""Crawl4AI MCP Server — Model Context Protocol server for web crawling."""

from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal, TypedDict

SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION = "scrape-crawl.v1"
SCRAPE_CRAWL_ENVELOPE_FIELDS = (
    "schema_version",
    "tool",
    "ok",
    "data",
    "items",
    "meta",
    "warnings",
    "error",
)
SCRAPE_CRAWL_OPTION_GROUPS: dict[str, tuple[str, ...]] = {
    "extraction": (
        "css_selector",
        "word_count_threshold",
        "schema",
        "extraction_mode",
    ),
    "transformation": ("js_code",),
    "conversion": (
        "output_format",
        "capture_artifacts",
    ),
    "runtime": (
        "wait_for",
        "bypass_cache",
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
    "render": (
        "viewport_width",
        "viewport_height",
    ),
    "traversal": (
        "mode",
        "max_depth",
        "max_pages",
        "crawl_mode",
        "include_external",
        "url_filters",
        "max_concurrency",
        "rate_limit_base_delay",
        "rate_limit_max_delay",
        "rate_limit_max_retries",
        "dispatcher",
    ),
}
SCRAPE_CRAWL_MIGRATION_MAP: dict[str, str] = {
    "scrape": "scrape",
    "crawl": "crawl",
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
    "render",
    "traversal",
]


class ScrapeCrawlError(TypedDict):
    code: str
    message: str


class ScrapeCrawlEnvelopeMeta(TypedDict):
    target_count: int
    option_groups: list[ScrapeCrawlOptionGroup]
    output_format: str
    diagnostics: bool
    session_id: str | None
    extraction_mode: str | None
    traversal_mode: str | None


class ScrapeCrawlEnvelope(TypedDict):
    schema_version: str
    tool: str
    ok: bool
    data: Any | None
    items: list[Any] | None
    meta: ScrapeCrawlEnvelopeMeta
    warnings: list[str]
    error: ScrapeCrawlError | None


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
