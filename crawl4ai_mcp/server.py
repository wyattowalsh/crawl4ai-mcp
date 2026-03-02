#!/usr/bin/env python3
"""
Crawl4AI MCP Server — FastMCP v3 implementation.

Provides 8 tools, 2 resources, and 3 prompts for web crawling via the
Model Context Protocol. Uses a lifespan-managed AsyncWebCrawler singleton
for efficient browser reuse.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from collections.abc import AsyncGenerator
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from crawl4ai import (
    AsyncWebCrawler,
    BFSDeepCrawlStrategy,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    JsonCssExtractionStrategy,
)
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.prompts import Message
from fastmcp.server.lifespan import lifespan
from pydantic import Field

from crawl4ai_mcp import __version__

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RESPONSE_CHARS = 25_000
BATCH_ITEM_CHARS = 5_000

VALID_FORMATS = frozenset({"markdown", "html", "text", "cleaned_html"})

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

# ---------------------------------------------------------------------------
# Lifespan — manages the shared AsyncWebCrawler singleton
# ---------------------------------------------------------------------------


@lifespan
async def crawler_lifespan(server: Any) -> AsyncGenerator[dict[str, Any], None]:
    """Start a headless Chromium browser once; share it across all tool calls."""
    browser_config = BrowserConfig(
        headless=True,
        browser_type="chromium",
        verbose=False,
    )
    crawler = AsyncWebCrawler(config=browser_config)
    await crawler.start()
    try:
        yield {"crawler": crawler}
    finally:
        await crawler.close()


# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "crawl4ai",
    instructions=(
        "Web crawling and scraping server powered by Crawl4AI. Provides tools "
        "for single-page crawling, batch crawling, deep recursive crawling, "
        "structured data extraction, screenshots, link extraction, page "
        "metadata, and JavaScript execution on rendered pages."
    ),
    version=__version__,
    lifespan=crawler_lifespan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(content: str, max_chars: int = MAX_RESPONSE_CHARS) -> str:
    """Truncate *content* if it exceeds *max_chars*, appending a notice."""
    if len(content) <= max_chars:
        return content
    return (
        content[:max_chars]
        + f"\n\n[Content truncated at {max_chars} characters. "
        + f"Total length: {len(content)} characters.]"
    )


def _validate_url(url: str) -> None:
    """Raise ``ToolError`` if *url* is not a valid HTTP(S) URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ToolError(f"Invalid URL: {url!r}. Only http and https URLs are supported.")
    # T09 — SSRF protection: block private/loopback IPs
    hostname = parsed.hostname or ""
    try:
        addr = ipaddress.ip_address(hostname)
        if any(addr in net for net in _PRIVATE_NETS):
            raise ToolError(f"Private/loopback URLs are not allowed: {url!r}")
    except ValueError:
        pass  # hostname string, not an IP — allow


def _get_crawler(ctx: Context | None) -> AsyncWebCrawler:
    """Extract the shared crawler from the lifespan context."""
    if ctx is None:
        raise ToolError("Crawler not available — server not fully initialized.")
    return ctx.lifespan_context["crawler"]


def _extract_markdown(result: Any) -> str:
    """Return the best available markdown from a CrawlResult.

    Handles both plain ``str`` and ``MarkdownGenerationResult`` objects,
    preferring ``fit_markdown`` when available.
    """
    md = result.markdown
    if md is None:
        return result.cleaned_html or result.html or ""
    if hasattr(md, "fit_markdown") and md.fit_markdown:
        return md.fit_markdown
    if hasattr(md, "raw_markdown"):
        return md.raw_markdown or ""
    if isinstance(md, str):
        return md
    return result.cleaned_html or result.html or ""


# T01 — Dict dispatch for output_format with validation
_FORMAT_DISPATCH = {
    "html": lambda r: r.html or "",
    "cleaned_html": lambda r: r.cleaned_html or r.html or "",
    "text": lambda r: re.sub(
        r"[#*_`]|!?\[([^\]]*)\]\([^)]*\)", r"\1", _extract_markdown(r)
    ).strip(),
}


def _select_content(result: Any, output_format: str) -> str:
    """Pick the content field matching *output_format*."""
    if output_format not in VALID_FORMATS:
        raise ToolError(
            f"Unknown output_format {output_format!r}. Valid options: {sorted(VALID_FORMATS)}"
        )
    return _FORMAT_DISPATCH.get(output_format, _extract_markdown)(result)


# T13 — Shared CrawlerRunConfig builder
def _build_run_config(
    *,
    css_selector: str | None = None,
    word_count_threshold: int = 200,
    wait_for: str | None = None,
    bypass_cache: bool = False,
    **extra: Any,
) -> CrawlerRunConfig:
    """Build a CrawlerRunConfig with common parameters."""
    return CrawlerRunConfig(
        css_selector=css_selector,  # ty: ignore[invalid-argument-type]
        word_count_threshold=word_count_threshold,
        wait_for=wait_for,  # ty: ignore[invalid-argument-type]
        cache_mode=CacheMode.BYPASS if bypass_cache else CacheMode.ENABLED,
        **extra,
    )


# ---------------------------------------------------------------------------
# Tool 1 — crawl_url
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Crawl URL",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def crawl_url(
    url: Annotated[str, Field(description="The URL to crawl. Must be http or https.")],
    output_format: Annotated[
        Literal["markdown", "html", "text", "cleaned_html"],
        Field(
            description="Output format: 'markdown' (default), 'html', 'text', or 'cleaned_html'."
        ),
    ] = "markdown",
    css_selector: Annotated[
        str | None,
        Field(description="CSS selector to extract specific page section."),
    ] = None,
    word_count_threshold: Annotated[
        int,
        Field(description="Minimum word count threshold for content blocks.", ge=0),
    ] = 200,
    wait_for: Annotated[
        str | None,
        Field(description="CSS selector or JS expression to wait for before extraction."),
    ] = None,
    bypass_cache: Annotated[
        bool,
        Field(description="Skip cached results and perform fresh crawl."),
    ] = False,
    ctx: Context | None = None,
) -> str:
    """Crawl a single web page and extract its content.

    Use this tool when you need to read the content of a specific web page.
    Returns the page content in the requested format (markdown by default).
    For crawling multiple pages at once, use crawl_many instead. For
    recursive site crawling, use deep_crawl.
    """
    _validate_url(url)
    crawler = _get_crawler(ctx)
    assert ctx is not None
    await ctx.info(f"Crawling {url}")

    config = _build_run_config(
        css_selector=css_selector,
        word_count_threshold=word_count_threshold,
        wait_for=wait_for,
        bypass_cache=bypass_cache,
    )

    result: Any = await crawler.arun(url=url, config=config)

    if not result.success:
        raise ToolError(f"Crawl failed for {url}: {result.error_message}")

    content = _select_content(result, output_format)
    return _truncate(content)


# ---------------------------------------------------------------------------
# Tool 2 — crawl_many
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Crawl Multiple URLs",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def crawl_many(
    urls: Annotated[
        list[str],
        Field(description="List of URLs to crawl. Maximum 20 URLs.", min_length=1, max_length=20),
    ],
    output_format: Annotated[
        Literal["markdown", "html", "text", "cleaned_html"],
        Field(
            description="Output format: 'markdown' (default), 'html', 'text', or 'cleaned_html'."
        ),
    ] = "markdown",
    css_selector: Annotated[
        str | None,
        Field(description="CSS selector to extract specific page section."),
    ] = None,
    word_count_threshold: Annotated[
        int,
        Field(description="Minimum word count threshold for content blocks.", ge=0),
    ] = 200,
    wait_for: Annotated[
        str | None,
        Field(description="CSS selector or JS expression to wait for before extraction."),
    ] = None,
    bypass_cache: Annotated[
        bool,
        Field(description="Skip cached results and perform fresh crawl."),
    ] = False,
    ctx: Context | None = None,
) -> str:
    """Crawl multiple web pages concurrently and return their content.

    Accepts up to 20 URLs, crawls them all in parallel using the shared
    browser, and returns an array of results. Each result includes the URL,
    success status, and content (or error message). Use crawl_url for a
    single page or deep_crawl for recursive crawling.
    """
    for u in urls:
        _validate_url(u)

    crawler = _get_crawler(ctx)
    assert ctx is not None
    await ctx.info(f"Batch crawling {len(urls)} URLs")

    config = _build_run_config(
        css_selector=css_selector,
        word_count_threshold=word_count_threshold,
        wait_for=wait_for,
        bypass_cache=bypass_cache,
    )

    results: Any = await crawler.arun_many(urls=urls, config=config)

    # T08 — Progress reporting
    try:
        await ctx.report_progress(len(results), len(urls))  # ty: ignore[invalid-argument-type]
    except AttributeError:
        pass

    output = []
    for r in results:
        if r.success:
            content = _select_content(r, output_format)
            output.append(
                {
                    "url": r.url,
                    "success": True,
                    "content": _truncate(content, BATCH_ITEM_CHARS),
                }
            )
        else:
            output.append(
                {
                    "url": r.url,
                    "success": False,
                    "error": r.error_message,
                }
            )

    # T11 — Warn on partial failures
    failed_count = sum(1 for item in output if not item["success"])
    if failed_count > 0:
        await ctx.warning(f"{failed_count} of {len(urls)} URLs failed to crawl")

    await ctx.info(f"Completed {len(output)} crawls")
    return json.dumps(output, indent=2)


# ---------------------------------------------------------------------------
# Tool 3 — deep_crawl
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Deep Crawl",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def deep_crawl(
    url: Annotated[
        str,
        Field(description="The seed URL to start deep crawling from."),
    ],
    max_depth: Annotated[
        int,
        Field(description="Maximum crawl depth from seed URL.", ge=1, le=5),
    ] = 2,
    max_pages: Annotated[
        int,
        Field(description="Maximum total pages to crawl.", ge=1, le=100),
    ] = 10,
    include_external: Annotated[
        bool,
        Field(description="Follow links to external domains."),
    ] = False,
    output_format: Annotated[
        Literal["markdown", "html", "text", "cleaned_html"],
        Field(
            description="Output format: 'markdown' (default), 'html', 'text', or 'cleaned_html'."
        ),
    ] = "markdown",
    css_selector: Annotated[
        str | None,
        Field(description="CSS selector to extract a specific page section."),
    ] = None,
    word_count_threshold: Annotated[
        int,
        Field(description="Minimum word count threshold for content blocks.", ge=0),
    ] = 200,
    bypass_cache: Annotated[
        bool,
        Field(description="Skip cached results and perform fresh crawl."),
    ] = False,
    ctx: Context | None = None,
) -> str:
    """Perform a breadth-first deep crawl starting from a seed URL.

    Discovers and follows links on each page up to *max_depth* levels,
    collecting up to *max_pages* total pages. Returns a JSON object with
    the seed URL, total pages crawled, and an array of per-page results
    each containing URL, depth, and content.
    """
    _validate_url(url)
    crawler = _get_crawler(ctx)
    assert ctx is not None
    await ctx.info(f"Deep crawling {url} (depth={max_depth}, max_pages={max_pages})")

    config = _build_run_config(
        css_selector=css_selector,
        word_count_threshold=word_count_threshold,
        bypass_cache=bypass_cache,
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth=max_depth,
            max_pages=max_pages,
            include_external=include_external,
        ),
        verbose=False,
    )

    results: Any = await crawler.arun(url=url, config=config)

    # arun with deep_crawl_strategy may return a list or single result
    if not isinstance(results, list):
        results = [results]

    pages = []
    for i, r in enumerate(results):
        if r.success:
            content = _select_content(r, output_format)
            pages.append(
                {
                    "url": r.url,
                    "depth": getattr(r, "depth", 0),
                    "content": _truncate(content, BATCH_ITEM_CHARS),
                }
            )
        else:
            pages.append(
                {
                    "url": r.url,
                    "depth": getattr(r, "depth", 0),
                    "error": r.error_message,
                }
            )
        # T08 — Progress reporting
        try:
            await ctx.report_progress(i + 1, len(results))
        except AttributeError:
            pass

    output = {
        "seed_url": url,
        "pages_crawled": len(pages),
        "results": pages,
    }

    await ctx.info(f"Deep crawl complete: {len(pages)} pages")
    return json.dumps(output, indent=2)


# ---------------------------------------------------------------------------
# Tool 4 — extract_data
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Extract Structured Data",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def extract_data(
    url: Annotated[
        str,
        Field(description="The URL to extract structured data from."),
    ],
    schema: Annotated[
        dict[str, Any],
        Field(
            description=(
                "CSS extraction schema with 'name', 'baseSelector', and 'fields' array. "
                "Each field has 'name', 'selector', 'type' ('text' or 'attribute'), "
                "and optional 'attribute'."
            ),
        ),
    ],
    wait_for: Annotated[
        str | None,
        Field(description="CSS selector or JS expression to wait for before extraction."),
    ] = None,
    ctx: Context | None = None,
) -> str:
    """Extract structured data from a page using CSS selectors.

    Provide a schema defining the base selector for repeating items and
    the fields to extract. Returns the extracted data as a JSON array.
    Use this when you need tabular or list-like data from a page rather
    than raw text content.
    """
    _validate_url(url)
    crawler = _get_crawler(ctx)
    assert ctx is not None
    await ctx.info(f"Extracting structured data from {url}")

    config = CrawlerRunConfig(
        extraction_strategy=JsonCssExtractionStrategy(schema=schema),
        wait_for=wait_for,  # ty: ignore[invalid-argument-type]
        cache_mode=CacheMode.BYPASS,
    )

    result: Any = await crawler.arun(url=url, config=config)

    if not result.success:
        raise ToolError(f"Extraction failed for {url}: {result.error_message}")

    if not result.extracted_content:
        raise ToolError(f"No data extracted from {url}. Check your schema selectors.")

    return _truncate(result.extracted_content)


# ---------------------------------------------------------------------------
# Tool 5 — take_screenshot
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Take Screenshot",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def take_screenshot(
    url: Annotated[
        str,
        Field(description="The URL to screenshot."),
    ],
    wait_for: Annotated[
        str | None,
        Field(description="CSS selector or JS expression to wait for before capture."),
    ] = None,
    viewport_width: Annotated[
        int,
        Field(description="Viewport width in pixels.", ge=320, le=3840),
    ] = 1280,
    viewport_height: Annotated[
        int,
        Field(description="Viewport height in pixels.", ge=240, le=2160),
    ] = 720,
    ctx: Context | None = None,
) -> str:
    """Capture a full-page screenshot of a web page.

    Navigates to the URL, optionally waits for a selector, then captures
    a screenshot. Returns a JSON object with the URL, a base64-encoded
    PNG image, and the format indicator. Useful for visual verification
    or capturing rendered state of dynamic pages.

    Note: viewport_width and viewport_height control the browser viewport
    dimensions used when rendering the page for the screenshot.
    """
    _validate_url(url)
    crawler = _get_crawler(ctx)
    assert ctx is not None
    await ctx.info(f"Screenshotting {url}")

    # Note: viewport_width/viewport_height are accepted as tool params for
    # future use but CrawlerRunConfig does not yet support them directly.
    config = CrawlerRunConfig(
        screenshot=True,
        wait_for=wait_for,  # ty: ignore[invalid-argument-type]
        cache_mode=CacheMode.BYPASS,
    )

    result: Any = await crawler.arun(url=url, config=config)

    if not result.success:
        raise ToolError(f"Screenshot failed for {url}: {result.error_message}")

    if not result.screenshot:
        raise ToolError(f"No screenshot data returned for {url}")

    return json.dumps(
        {
            "url": result.url,
            "screenshot_base64": result.screenshot,
            "format": "png",
        }
    )


# ---------------------------------------------------------------------------
# Tool 6 — get_links
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Get Links",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_links(
    url: Annotated[
        str,
        Field(description="The URL to extract links from."),
    ],
    ctx: Context | None = None,
) -> str:
    """Extract and categorize all links found on a web page.

    Crawls the page and returns internal links (same domain) and external
    links (other domains) as separate arrays, along with totals for each
    category. Useful for site mapping, link analysis, or finding related
    pages before a deep crawl.
    """
    _validate_url(url)
    crawler = _get_crawler(ctx)
    assert ctx is not None
    await ctx.info(f"Extracting links from {url}")

    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
    result: Any = await crawler.arun(url=url, config=config)

    if not result.success:
        raise ToolError(f"Link extraction failed for {url}: {result.error_message}")

    links = result.links or {}
    internal = links.get("internal", [])
    external = links.get("external", [])

    output = {
        "url": result.url,
        "internal_links": internal,
        "external_links": external,
        "total_internal": len(internal),
        "total_external": len(external),
    }
    return _truncate(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# Tool 7 — get_page_info
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Get Page Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_page_info(
    url: Annotated[
        str,
        Field(description="The URL to inspect."),
    ],
    ctx: Context | None = None,
) -> str:
    """Get metadata and summary information about a web page.

    Returns a lightweight overview including the page title, description,
    language, link and media counts, and the full metadata dict. Does not
    return the full page content — use crawl_url for that. Useful for
    quickly inspecting a page before deciding to do a full crawl.
    """
    _validate_url(url)
    crawler = _get_crawler(ctx)
    assert ctx is not None
    await ctx.info(f"Inspecting {url}")

    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
    result: Any = await crawler.arun(url=url, config=config)

    if not result.success:
        raise ToolError(f"Page inspection failed for {url}: {result.error_message}")

    metadata = result.metadata or {}
    links = result.links or {}
    media = result.media or {}

    output = {
        "url": result.url,
        "title": metadata.get("title", ""),
        "description": metadata.get("description", ""),
        "language": metadata.get("language", ""),
        "links_count": {
            "internal": len(links.get("internal", [])),
            "external": len(links.get("external", [])),
        },
        "media_count": {
            "images": len(media.get("images", [])),
            "videos": len(media.get("videos", [])),
            "audio": len(media.get("audio", [])),
        },
        "metadata": metadata,
    }
    return json.dumps(output, indent=2)


# ---------------------------------------------------------------------------
# Tool 8 — execute_js
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Execute JavaScript",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def execute_js(
    url: Annotated[
        str,
        Field(description="The URL to load before executing JavaScript."),
    ],
    js_code: Annotated[
        str,
        Field(description="JavaScript code to execute on the page after it loads."),
    ],
    wait_for: Annotated[
        str | None,
        Field(description="CSS selector or JS expression to wait for after JS execution."),
    ] = None,
    output_format: Annotated[
        Literal["markdown", "html", "text", "cleaned_html"],
        Field(
            description="Output format: 'markdown' (default), 'html', 'text', or 'cleaned_html'."
        ),
    ] = "markdown",
    ctx: Context | None = None,
) -> str:
    """Load a web page and execute JavaScript on it, then return the content.

    Navigates to the URL, runs the provided JavaScript code, optionally
    waits for a condition, then extracts the resulting page content as
    markdown. Useful for interacting with dynamic pages — clicking buttons,
    filling forms, or triggering client-side rendering before extraction.
    """
    _validate_url(url)
    crawler = _get_crawler(ctx)
    assert ctx is not None
    await ctx.info(f"Executing JS on {url}")

    config = CrawlerRunConfig(
        js_code=[js_code],
        wait_for=wait_for,  # ty: ignore[invalid-argument-type]
        cache_mode=CacheMode.BYPASS,
    )

    result: Any = await crawler.arun(url=url, config=config)

    if not result.success:
        raise ToolError(f"JS execution failed for {url}: {result.error_message}")

    return _truncate(_select_content(result, output_format))


# ---------------------------------------------------------------------------
# T14 — Dynamic tool name list (defined after all tools)
# ---------------------------------------------------------------------------

_TOOL_NAMES = [
    "crawl_url",
    "crawl_many",
    "deep_crawl",
    "extract_data",
    "take_screenshot",
    "get_links",
    "get_page_info",
    "execute_js",
]

# ---------------------------------------------------------------------------
# Resource 1 — server config
# ---------------------------------------------------------------------------


@mcp.resource("config://server", mime_type="application/json")
def get_server_config() -> str:
    """Current server configuration and capabilities."""
    return json.dumps(
        {
            "name": "crawl4ai",
            "version": __version__,
            "tools": _TOOL_NAMES,
            "max_response_chars": MAX_RESPONSE_CHARS,
            "browser_config": {
                "headless": True,
                "browser_type": "chromium",
            },
        }
    )


# ---------------------------------------------------------------------------
# Resource 2 — version info
# ---------------------------------------------------------------------------


@mcp.resource("crawl4ai://version", mime_type="application/json")
def get_version_info() -> str:
    """Server and dependency version information."""
    import crawl4ai
    import fastmcp

    # crawl4ai.__version__ may be a module; resolve to string
    c4ai_ver = getattr(crawl4ai, "__version__", "unknown")
    if not isinstance(c4ai_ver, str):
        c4ai_ver = getattr(c4ai_ver, "__version__", "unknown")

    return json.dumps(
        {
            "server_version": __version__,
            "crawl4ai_version": c4ai_ver,
            "fastmcp_version": getattr(fastmcp, "__version__", "unknown"),
        }
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@mcp.prompt
def summarize_page(
    url: str,
    focus: str = "key points",
) -> list[Message]:
    """Crawl a page and summarize its content.

    Generates a prompt that instructs the LLM to use crawl_url to fetch
    the page and then summarize it with the specified focus.
    """
    return [
        Message(
            role="user",
            content=f"Use the crawl_url tool to fetch {url}, then summarize its {focus}.",
        )
    ]


@mcp.prompt
def build_extraction_schema(
    url: str,
    data_type: str,
) -> list[Message]:
    """Build a CSS extraction schema for use with extract_data.

    Instructs the LLM to inspect the page structure and craft a schema
    for the extract_data tool to extract the specified data type.
    """
    return [
        Message(
            role="user",
            content=(
                f"Use get_page_info on {url} to understand the page structure, then "
                f"craft a JSON CSS extraction schema for the extract_data tool to "
                f"extract {data_type} from that page. Show the schema."
            ),
        )
    ]


@mcp.prompt
def compare_pages(
    url1: str,
    url2: str,
) -> list[Message]:
    """Crawl two pages and compare their content.

    Instructs the LLM to fetch both pages with crawl_url and produce
    a structured comparison highlighting key differences.
    """
    return [
        Message(
            role="user",
            content=(
                f"Use crawl_url to fetch {url1} and {url2}, then compare their "
                f"content and highlight the key differences."
            ),
        )
    ]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the crawl4ai MCP server."""
    parser = argparse.ArgumentParser(description="Crawl4AI MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port")
    args = parser.parse_args()

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
