#!/usr/bin/env python3
"""
Crawl4AI MCP Server — FastMCP v3 implementation.

Provides MCP tools, resources, and prompts for web crawling via the
Model Context Protocol. Uses a lifespan-managed AsyncWebCrawler singleton
for efficient browser reuse.
"""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import re
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import AsyncGenerator
from typing import Annotated, Any, Literal, NoReturn, cast
from urllib.parse import urlparse

from crawl4ai import (
    AsyncWebCrawler,
    BFSDeepCrawlStrategy,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    DFSDeepCrawlStrategy,
    FilterChain,
    JsonCssExtractionStrategy,
    JsonXPathExtractionStrategy,
    RateLimiter,
    SemaphoreDispatcher,
    URLPatternFilter,
)
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.prompts import Message
from fastmcp.server.lifespan import lifespan
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_crawl4ai import SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION, __version__

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RESPONSE_CHARS = 25_000
BATCH_ITEM_CHARS = 5_000

VALID_FORMATS = frozenset({"markdown", "html", "text", "cleaned_html"})
VALID_EXTRACTION_MODES = frozenset({"css", "xpath"})

RUNTIME_TIMEOUT_MS_MIN = 1
RUNTIME_TIMEOUT_MS_MAX = 300_000
RUNTIME_SIZE_BOUND_MIN = 1
RUNTIME_SIZE_BOUND_MAX = 5_000_000
RUNTIME_RETRY_COUNT_MIN = 0
RUNTIME_RETRY_COUNT_MAX = 10
RUNTIME_BACKOFF_MS_MIN = 0
RUNTIME_BACKOFF_MS_MAX = 60_000

CRAWL_MANY_DEFAULT_MAX_CONCURRENCY = 5
CRAWL_MANY_HARD_MAX_CONCURRENCY = 20
CRAWL_MANY_RATE_DELAY_MIN = 0.0
CRAWL_MANY_RATE_DELAY_MAX = 60.0
CRAWL_MANY_RATE_RETRIES_MIN = 0
CRAWL_MANY_RATE_RETRIES_MAX = 10
CRAWL_MANY_DEFAULT_RATE_LIMIT_BASE_DELAY = 1.0
CRAWL_MANY_DEFAULT_RATE_LIMIT_MAX_DELAY = 3.0
CRAWL_MANY_DEFAULT_RATE_LIMIT_MAX_RETRIES = 3
SCRAPE_TARGETS_MAX_ITEMS = 20
DEEP_CRAWL_FILTER_PATTERN_MAX_CHARS = 512
DIAGNOSTIC_URL_MAX_CHARS = 512
DIAGNOSTIC_COUNT_MAX = 100_000

SESSION_ID_MAX_CHARS = 64
SESSION_TTL_SECONDS_MIN = 60
SESSION_TTL_SECONDS_MAX = 3_600
SESSION_TTL_SECONDS_DEFAULT = 900
SESSION_MAX_USES_MIN = 1
SESSION_MAX_USES_MAX = 500
SESSION_MAX_USES_DEFAULT = 100
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

ARTIFACT_CAPTURE_TYPES = frozenset({"mhtml", "pdf", "console", "network"})
ARTIFACT_CAPTURE_MAX_TYPES = 4
ARTIFACT_CAPTURE_LIST_MAX_ITEMS = 200
ARTIFACT_CAPTURE_TEXT_MAX_CHARS = 100_000
ARTIFACT_ID_MAX_CHARS = 128
ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ARTIFACT_TTL_SECONDS_MIN = 1
ARTIFACT_TTL_SECONDS_MAX = 86_400
ARTIFACT_TTL_SECONDS_DEFAULT = 900
ARTIFACT_MAX_PER_SESSION_MIN = 1
ARTIFACT_MAX_PER_SESSION_MAX = 100
ARTIFACT_MAX_PER_SESSION_DEFAULT = 25
ARTIFACT_MAX_TOTAL_MIN = 1
ARTIFACT_MAX_TOTAL_MAX = 1_000
ARTIFACT_MAX_TOTAL_DEFAULT = 250
ARTIFACT_MAX_TOTAL_BYTES_MIN = 1_024
ARTIFACT_MAX_TOTAL_BYTES_MAX = 50_000_000
ARTIFACT_MAX_TOTAL_BYTES_DEFAULT = 5_000_000
SENSITIVE_ARTIFACT_KEYS = frozenset(
    {
        "cookie",
        "cookies",
        "set-cookie",
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "access_token",
        "refresh_token",
        "token",
    }
)


class DefaultsConfig(BaseModel):
    """Runtime defaults configurable via environment variables."""

    max_response_chars: int | None = Field(default=None, ge=1)
    batch_item_chars: int | None = Field(default=None, ge=1)
    crawl_many_default_max_concurrency: int | None = Field(default=None, ge=1)
    crawl_many_default_rate_limit_base_delay: float | None = Field(default=None, ge=0.0)
    crawl_many_default_rate_limit_max_delay: float | None = Field(default=None, ge=0.0)
    crawl_many_default_rate_limit_max_retries: int | None = Field(default=None, ge=0)


class LimitsConfig(BaseModel):
    """Hard limits configurable via environment variables."""

    crawl_many_hard_max_concurrency: int | None = Field(default=None, ge=1)


class PoliciesConfig(BaseModel):
    """Session and artifact retention policies."""

    session_ttl_seconds_default: int | None = Field(default=None, ge=1)
    session_max_uses_default: int | None = Field(default=None, ge=1)
    artifact_ttl_seconds_default: int | None = Field(default=None, ge=1)
    artifact_max_per_session_default: int | None = Field(default=None, ge=1)
    artifact_max_total_default: int | None = Field(default=None, ge=1)
    artifact_max_total_bytes_default: int | None = Field(default=None, ge=1)


class CapabilitiesConfig(BaseModel):
    """Capability toggles and browser engine defaults."""

    browser_headless: bool | None = None
    browser_type: str | None = None


class ServerSettings(BaseSettings):
    """Top-level server settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="MCP_CRAWL4AI_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    policies: PoliciesConfig = Field(default_factory=PoliciesConfig)
    capabilities: CapabilitiesConfig = Field(default_factory=CapabilitiesConfig)


_SETTINGS: ServerSettings | None = None  # AUDIT: L-07 — module-global lacks synchronization


def _load_settings(*, reload: bool = False) -> ServerSettings:
    """Load settings once per process unless explicitly reloaded."""
    global _SETTINGS
    if reload or _SETTINGS is None:
        _SETTINGS = ServerSettings()
    return _SETTINGS


def _get_settings(ctx: Context | None = None) -> ServerSettings:
    """Return settings from lifespan context when available, else process cache."""
    if ctx is not None:
        settings = ctx.lifespan_context.get("settings")
        if isinstance(settings, ServerSettings):
            return settings
    return _load_settings()


def _get_max_response_chars() -> int:  # AUDIT: M-07 — ignores lifespan ctx; always uses process-level settings cache
    """Resolve the default response truncation limit."""
    configured = _get_settings().defaults.max_response_chars
    resolved = MAX_RESPONSE_CHARS if configured is None else configured
    return max(1, resolved)


def _get_batch_item_chars() -> int:  # AUDIT: M-07 — ignores lifespan ctx; always uses process-level settings cache
    """Resolve the default per-item truncation limit."""
    configured = _get_settings().defaults.batch_item_chars
    resolved = BATCH_ITEM_CHARS if configured is None else configured
    return max(1, resolved)


def _get_crawl_many_hard_max_concurrency() -> int:
    """Resolve the crawl_many hard max concurrency limit."""
    configured = _get_settings().limits.crawl_many_hard_max_concurrency
    resolved = CRAWL_MANY_HARD_MAX_CONCURRENCY if configured is None else configured
    return max(1, resolved)


def _get_crawl_many_default_max_concurrency() -> int:
    """Resolve the crawl_many default concurrency limit."""
    configured = _get_settings().defaults.crawl_many_default_max_concurrency
    resolved = CRAWL_MANY_DEFAULT_MAX_CONCURRENCY if configured is None else configured
    return max(1, min(resolved, _get_crawl_many_hard_max_concurrency()))


def _get_crawl_many_default_rate_limit_base_delay() -> float:
    """Resolve the crawl_many default rate-limit base delay."""
    configured = _get_settings().defaults.crawl_many_default_rate_limit_base_delay
    resolved = CRAWL_MANY_DEFAULT_RATE_LIMIT_BASE_DELAY if configured is None else configured
    return max(CRAWL_MANY_RATE_DELAY_MIN, min(resolved, CRAWL_MANY_RATE_DELAY_MAX))


def _get_crawl_many_default_rate_limit_max_delay() -> float:
    """Resolve the crawl_many default rate-limit max delay."""
    configured = _get_settings().defaults.crawl_many_default_rate_limit_max_delay
    resolved = CRAWL_MANY_DEFAULT_RATE_LIMIT_MAX_DELAY if configured is None else configured
    return max(CRAWL_MANY_RATE_DELAY_MIN, min(resolved, CRAWL_MANY_RATE_DELAY_MAX))


def _get_crawl_many_default_rate_limit_max_retries() -> int:
    """Resolve the crawl_many default rate-limit retry count."""
    configured = _get_settings().defaults.crawl_many_default_rate_limit_max_retries
    resolved = CRAWL_MANY_DEFAULT_RATE_LIMIT_MAX_RETRIES if configured is None else configured
    return max(CRAWL_MANY_RATE_RETRIES_MIN, min(resolved, CRAWL_MANY_RATE_RETRIES_MAX))


def _get_browser_headless() -> bool:
    """Resolve browser headless capability."""
    configured = _get_settings().capabilities.browser_headless
    return True if configured is None else configured


def _get_browser_type() -> str:
    """Resolve browser type capability."""
    configured = _get_settings().capabilities.browser_type
    if not isinstance(configured, str) or not configured.strip():
        return "chromium"
    return configured.strip().lower()


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
    settings = _load_settings(reload=True)
    browser_config = BrowserConfig(
        headless=_get_browser_headless(),
        browser_type=_get_browser_type(),
        verbose=False,
    )
    crawler = AsyncWebCrawler(config=browser_config)
    session_registry: dict[str, dict[str, int | float]] = {}  # AUDIT: M-08 — no max session count; unbounded memory growth
    artifact_store: dict[str, Any] = {
        "artifacts": {},
        "runs": {},
        "artifact_order": [],
        "session_artifacts": {},
        "session_runs": {},
        "total_bytes": 0,
        "next_artifact_index": 0,
        "next_run_index": 0,
    }
    try:
        await crawler.start()
    except Exception as e:
        error_msg = str(e).lower()
        if "browser" in error_msg or "playwright" in error_msg or "chromium" in error_msg:
            # Try auto-installing browsers
            try:
                subprocess.run(
                    ["crawl4ai-setup"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                await crawler.start()  # retry after setup
            except (subprocess.CalledProcessError, FileNotFoundError) as setup_err:
                raise RuntimeError(
                    "Playwright browsers not installed. Run: crawl4ai-setup\n"
                    f"Auto-setup failed: {setup_err}"
                ) from e
        else:
            raise
    try:
        yield {
            "crawler": crawler,
            "sessions": session_registry,
            "artifacts": artifact_store,
            "settings": settings,
        }
    finally:
        kill_session = getattr(getattr(crawler, "crawler_strategy", None), "kill_session", None)
        if callable(kill_session):
            for session_id in list(session_registry):
                try:
                    await cast(Any, kill_session)(session_id)
                except Exception:
                    pass
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


def _truncate(content: str, max_chars: int | None = None) -> str:  # AUDIT: H-01 — truncating serialized JSON envelopes here produces invalid JSON; notice also exceeds max_chars budget
    """Truncate *content* if it exceeds *max_chars*, appending a notice."""
    bounded_max_chars = _get_max_response_chars() if max_chars is None else max_chars
    if len(content) <= bounded_max_chars:
        return content
    return (
        content[:bounded_max_chars]
        + f"\n\n[Content truncated at {bounded_max_chars} characters. "
        + f"Total length: {len(content)} characters.]"
    )


def _validate_url(url: str) -> None:  # AUDIT: H-02 — SSRF TOCTOU via DNS rebinding; H-04 — socket.getaddrinfo blocks the async event loop
    """Raise ``ToolError`` if *url* is not a valid HTTP(S) URL."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ToolError(f"Invalid URL: {url!r}. Only http and https URLs are supported.")
    # T09 — SSRF protection: block private/loopback IPs
    hostname = parsed.hostname or ""
    normalized_hostname = hostname.rstrip(".").lower()
    if normalized_hostname == "localhost" or normalized_hostname.endswith(".localhost"):
        raise ToolError(f"Private/loopback URLs are not allowed: {url!r}")

    def _is_disallowed_address(raw_host: str) -> bool:
        host_value = raw_host.split("%", 1)[0]
        addr = ipaddress.ip_address(host_value)
        return any(addr in net for net in _PRIVATE_NETS) or not addr.is_global

    try:
        if _is_disallowed_address(hostname):
            raise ToolError(f"Private/loopback URLs are not allowed: {url!r}")
    except ValueError:
        try:
            resolved_addrs = socket.getaddrinfo(hostname, None)
        except OSError:  # AUDIT: M-02 — silent pass-through on DNS resolution failure allows unresolvable hostnames
            return
        for resolved in resolved_addrs:
            sockaddr = resolved[4]
            if not isinstance(sockaddr, tuple) or not sockaddr:
                continue
            resolved_host = sockaddr[0]
            if isinstance(resolved_host, str):
                try:
                    if _is_disallowed_address(resolved_host):
                        raise ToolError(f"Private/loopback URLs are not allowed: {url!r}")
                except ValueError:
                    continue


def _is_loopback_bind_host(host: str) -> bool:
    """Return ``True`` when *host* is a loopback bind target."""
    stripped_host = host.strip()
    normalized_host = stripped_host.rstrip(".").lower()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(stripped_host).is_loopback
    except ValueError:
        return False


def _raise_runtime_validation_error(param_name: str, value: Any, expected: str) -> NoReturn:
    """Raise a consistent ``ToolError`` for runtime guardrail violations."""
    raise ToolError(f"Invalid {param_name}: {value!r}. Expected {expected}.")


def _validate_optional_numeric_range(
    value: int | float | None,
    *,
    param_name: str,
    minimum: int | float,
    maximum: int | float,
) -> int | float | None:
    """Validate an optional numeric value against an inclusive range."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _raise_runtime_validation_error(
            param_name,
            value,
            f"a number between {minimum} and {maximum} (inclusive)",
        )
    if value < minimum or value > maximum:
        _raise_runtime_validation_error(
            param_name,
            value,
            f"a number between {minimum} and {maximum} (inclusive)",
        )
    return value


def _validate_optional_timeout_ms(
    timeout_ms: int | None,
    *,
    param_name: str = "timeout_ms",
) -> int | None:
    """Validate an optional timeout value in milliseconds."""
    validated = _validate_optional_numeric_range(
        timeout_ms,
        param_name=param_name,
        minimum=RUNTIME_TIMEOUT_MS_MIN,
        maximum=RUNTIME_TIMEOUT_MS_MAX,
    )
    if validated is None:
        return None
    if not isinstance(validated, int):
        _raise_runtime_validation_error(
            param_name,
            validated,
            f"an integer between {RUNTIME_TIMEOUT_MS_MIN} and {RUNTIME_TIMEOUT_MS_MAX} (inclusive)",
        )
    return validated


def _validate_optional_size_bound(
    size: int | None,
    *,
    param_name: str,
    minimum: int = RUNTIME_SIZE_BOUND_MIN,
    maximum: int = RUNTIME_SIZE_BOUND_MAX,
) -> int | None:
    """Validate an optional runtime size/control bound."""
    validated = _validate_optional_numeric_range(
        size,
        param_name=param_name,
        minimum=minimum,
        maximum=maximum,
    )
    if validated is None:
        return None
    if not isinstance(validated, int):
        _raise_runtime_validation_error(
            param_name,
            validated,
            f"an integer between {minimum} and {maximum} (inclusive)",
        )
    return validated


def _validate_optional_runtime_controls(
    *,
    timeout_ms: int | None = None,
    max_retries: int | None = None,
    retry_backoff_ms: int | None = None,
    max_content_chars: int | None = None,
) -> dict[str, int]:
    """Validate optional runtime controls and return only provided values."""
    validated_controls: dict[str, int] = {}

    validated_timeout = _validate_optional_timeout_ms(timeout_ms)
    if validated_timeout is not None:
        validated_controls["timeout_ms"] = validated_timeout

    validated_retries = _validate_optional_size_bound(
        max_retries,
        param_name="max_retries",
        minimum=RUNTIME_RETRY_COUNT_MIN,
        maximum=RUNTIME_RETRY_COUNT_MAX,
    )
    if validated_retries is not None:
        validated_controls["max_retries"] = validated_retries

    validated_backoff = _validate_optional_size_bound(
        retry_backoff_ms,
        param_name="retry_backoff_ms",
        minimum=RUNTIME_BACKOFF_MS_MIN,
        maximum=RUNTIME_BACKOFF_MS_MAX,
    )
    if validated_backoff is not None:
        validated_controls["retry_backoff_ms"] = validated_backoff

    validated_max_content = _validate_optional_size_bound(
        max_content_chars,
        param_name="max_content_chars",
    )
    if validated_max_content is not None:
        validated_controls["max_content_chars"] = validated_max_content

    return validated_controls


class CanonicalExtractionOptions(BaseModel):
    """Shared extraction options for canonical scrape/crawl operations."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    css_selector: str | None = None
    word_count_threshold: int | None = Field(default=None, ge=0)
    extraction_schema: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        serialization_alias="schema",
    )
    extraction_mode: Literal["css", "xpath"] | None = None


class CanonicalTransformationOptions(BaseModel):
    """Shared transformation options for canonical scrape/crawl operations."""

    model_config = ConfigDict(extra="forbid")

    js_code: str | None = None


class CanonicalConversionOptions(BaseModel):
    """Shared conversion options for canonical scrape/crawl operations."""

    model_config = ConfigDict(extra="forbid")

    output_format: Literal["markdown", "html", "text", "cleaned_html"] | None = None
    capture_artifacts: list[str] | None = None


class CanonicalRuntimeOptions(BaseModel):
    """Shared runtime options for canonical scrape/crawl operations."""

    model_config = ConfigDict(extra="forbid")

    wait_for: str | None = None
    bypass_cache: bool | None = None
    timeout_ms: int | None = Field(
        default=None, ge=RUNTIME_TIMEOUT_MS_MIN, le=RUNTIME_TIMEOUT_MS_MAX
    )
    max_retries: int | None = Field(
        default=None,
        ge=RUNTIME_RETRY_COUNT_MIN,
        le=RUNTIME_RETRY_COUNT_MAX,
    )
    retry_backoff_ms: int | None = Field(
        default=None,
        ge=RUNTIME_BACKOFF_MS_MIN,
        le=RUNTIME_BACKOFF_MS_MAX,
    )
    max_content_chars: int | None = Field(
        default=None,
        ge=RUNTIME_SIZE_BOUND_MIN,
        le=RUNTIME_SIZE_BOUND_MAX,
    )


class CanonicalDiagnosticsOptions(BaseModel):
    """Shared diagnostics options for canonical scrape/crawl operations."""

    model_config = ConfigDict(extra="forbid")

    include_diagnostics: bool | None = None


class CanonicalSessionOptions(BaseModel):
    """Shared session options for canonical scrape/crawl operations."""

    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    session_ttl_seconds: int | None = Field(
        default=None,
        ge=SESSION_TTL_SECONDS_MIN,
        le=SESSION_TTL_SECONDS_MAX,
    )
    session_max_uses: int | None = Field(
        default=None,
        ge=SESSION_MAX_USES_MIN,
        le=SESSION_MAX_USES_MAX,
    )
    artifact_ttl_seconds: int | None = Field(
        default=None,
        ge=ARTIFACT_TTL_SECONDS_MIN,
        le=ARTIFACT_TTL_SECONDS_MAX,
    )
    artifact_max_per_session: int | None = Field(
        default=None,
        ge=ARTIFACT_MAX_PER_SESSION_MIN,
        le=ARTIFACT_MAX_PER_SESSION_MAX,
    )
    artifact_max_total: int | None = Field(
        default=None,
        ge=ARTIFACT_MAX_TOTAL_MIN,
        le=ARTIFACT_MAX_TOTAL_MAX,
    )
    artifact_max_total_bytes: int | None = Field(
        default=None,
        ge=ARTIFACT_MAX_TOTAL_BYTES_MIN,
        le=ARTIFACT_MAX_TOTAL_BYTES_MAX,
    )


class CanonicalRenderOptions(BaseModel):
    """Shared rendering options for canonical scrape/crawl operations."""

    model_config = ConfigDict(extra="forbid")

    viewport_width: int | None = Field(default=None, ge=320, le=3840)
    viewport_height: int | None = Field(default=None, ge=240, le=2160)


class CanonicalRateLimitOptions(BaseModel):
    """Rate-limit options supported by traversal dispatchers."""

    model_config = ConfigDict(extra="forbid")

    base_delay: float | None = Field(
        default=None,
        ge=CRAWL_MANY_RATE_DELAY_MIN,
        le=CRAWL_MANY_RATE_DELAY_MAX,
    )
    max_delay: float | None = Field(
        default=None,
        ge=CRAWL_MANY_RATE_DELAY_MIN,
        le=CRAWL_MANY_RATE_DELAY_MAX,
    )
    max_retries: int | None = Field(
        default=None,
        ge=CRAWL_MANY_RATE_RETRIES_MIN,
        le=CRAWL_MANY_RATE_RETRIES_MAX,
    )


class CanonicalDispatcherOptions(BaseModel):
    """Dispatcher options supported by traversal controls."""

    model_config = ConfigDict(extra="forbid")

    max_concurrency: int | None = Field(default=None, ge=1, le=CRAWL_MANY_HARD_MAX_CONCURRENCY)
    rate_limit_base_delay: float | None = Field(
        default=None,
        ge=CRAWL_MANY_RATE_DELAY_MIN,
        le=CRAWL_MANY_RATE_DELAY_MAX,
    )
    rate_limit_max_delay: float | None = Field(
        default=None,
        ge=CRAWL_MANY_RATE_DELAY_MIN,
        le=CRAWL_MANY_RATE_DELAY_MAX,
    )
    rate_limit_max_retries: int | None = Field(
        default=None,
        ge=CRAWL_MANY_RATE_RETRIES_MIN,
        le=CRAWL_MANY_RATE_RETRIES_MAX,
    )
    rate_limit: CanonicalRateLimitOptions | None = None


class CanonicalTraversalOptions(BaseModel):
    """Traversal options for canonical crawl operations."""

    model_config = ConfigDict(extra="forbid")

    mode: str | None = None
    max_depth: int | None = Field(default=None, ge=1, le=5)
    max_pages: int | None = Field(default=None, ge=1, le=100)
    crawl_mode: str | None = None
    include_external: bool | None = None
    url_filters: dict[str, Any] | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=CRAWL_MANY_HARD_MAX_CONCURRENCY)
    rate_limit_base_delay: float | None = Field(
        default=None,
        ge=CRAWL_MANY_RATE_DELAY_MIN,
        le=CRAWL_MANY_RATE_DELAY_MAX,
    )
    rate_limit_max_delay: float | None = Field(
        default=None,
        ge=CRAWL_MANY_RATE_DELAY_MIN,
        le=CRAWL_MANY_RATE_DELAY_MAX,
    )
    rate_limit_max_retries: int | None = Field(
        default=None,
        ge=CRAWL_MANY_RATE_RETRIES_MIN,
        le=CRAWL_MANY_RATE_RETRIES_MAX,
    )
    dispatcher: CanonicalDispatcherOptions | None = None


class CanonicalOptionGroups(BaseModel):
    """Sparse canonical option-group payload from user input."""

    model_config = ConfigDict(extra="forbid")

    extraction: CanonicalExtractionOptions | None = None
    transformation: CanonicalTransformationOptions | None = None
    conversion: CanonicalConversionOptions | None = None
    runtime: CanonicalRuntimeOptions | None = None
    diagnostics: CanonicalDiagnosticsOptions | None = None
    session: CanonicalSessionOptions | None = None
    render: CanonicalRenderOptions | None = None
    traversal: CanonicalTraversalOptions | None = None


class CanonicalNormalizedOptionGroups(BaseModel):
    """Bounded canonical option-groups used by internal scrape/crawl logic."""

    model_config = ConfigDict(extra="forbid")

    extraction: CanonicalExtractionOptions = Field(default_factory=CanonicalExtractionOptions)
    transformation: CanonicalTransformationOptions = Field(
        default_factory=CanonicalTransformationOptions
    )
    conversion: CanonicalConversionOptions = Field(default_factory=CanonicalConversionOptions)
    runtime: CanonicalRuntimeOptions = Field(default_factory=CanonicalRuntimeOptions)
    diagnostics: CanonicalDiagnosticsOptions = Field(default_factory=CanonicalDiagnosticsOptions)
    session: CanonicalSessionOptions = Field(default_factory=CanonicalSessionOptions)
    render: CanonicalRenderOptions = Field(default_factory=CanonicalRenderOptions)
    traversal: CanonicalTraversalOptions = Field(default_factory=CanonicalTraversalOptions)


def _raise_model_validation_tool_error(param_name: str, error: ValidationError) -> NoReturn:
    """Raise a ``ToolError`` from a Pydantic validation error."""
    details = error.errors(include_url=False)
    if details:
        first = details[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        message = str(first.get("msg", "Invalid value"))
        suffix = f".{location}" if location else ""
        raise ToolError(f"Invalid {param_name}{suffix}: {message}.")
    raise ToolError(f"Invalid {param_name}: {error}.")


def _normalize_canonical_url_filters(
    url_filters: dict[str, Any] | None,
    *,
    param_name: str = "traversal.url_filters",
) -> dict[str, list[str]] | None:
    """Normalize optional canonical URL filters."""
    if url_filters is None:
        return None
    if not isinstance(url_filters, dict):
        _raise_runtime_validation_error(
            param_name,
            url_filters,
            "an object with optional 'include' and 'exclude' list values",
        )

    unknown_keys = sorted(set(url_filters) - {"include", "exclude"})
    if unknown_keys:
        _raise_runtime_validation_error(
            param_name,
            url_filters,
            "an object with optional 'include' and 'exclude' list values",
        )

    normalized: dict[str, list[str]] = {}
    if "include" in url_filters:
        normalized["include"] = _validate_deep_crawl_url_filter_patterns(
            url_filters["include"],
            param_name=f"{param_name}.include",
        )
    if "exclude" in url_filters:
        normalized["exclude"] = _validate_deep_crawl_url_filter_patterns(
            url_filters["exclude"],
            param_name=f"{param_name}.exclude",
        )
    return normalized


def _normalize_optional_crawl_mode(
    crawl_mode: str | None,
    *,
    param_name: str = "traversal.crawl_mode",
) -> str | None:
    """Normalize an optional crawl mode."""
    if crawl_mode is None:
        return None
    if not isinstance(crawl_mode, str):
        _raise_runtime_validation_error(param_name, crawl_mode, "one of ['bfs', 'dfs']")
    normalized_mode = crawl_mode.strip().lower()
    if normalized_mode not in {"bfs", "dfs"}:
        _raise_runtime_validation_error(param_name, crawl_mode, "one of ['bfs', 'dfs']")
    return normalized_mode


def _normalize_optional_traversal_mode(
    mode: str | None,
    *,
    param_name: str = "traversal.mode",
) -> str | None:
    """Normalize an optional canonical traversal mode."""
    if mode is None:
        return None
    if not isinstance(mode, str):
        _raise_runtime_validation_error(param_name, mode, "one of ['list', 'deep']")
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"list", "deep"}:
        _raise_runtime_validation_error(param_name, mode, "one of ['list', 'deep']")
    return normalized_mode


def _normalize_canonical_option_groups(
    *,
    operation: Literal["scrape", "crawl"],
    options: dict[str, Any] | None,
) -> CanonicalNormalizedOptionGroups:
    """Normalize canonical scrape/crawl option-groups into bounded internal config."""
    if not isinstance(operation, str):
        _raise_runtime_validation_error("operation", operation, "one of ['scrape', 'crawl']")
    normalized_operation = operation.strip().lower()
    if normalized_operation not in {"scrape", "crawl"}:
        _raise_runtime_validation_error("operation", operation, "one of ['scrape', 'crawl']")

    raw_options: dict[str, Any] = {} if options is None else options
    if not isinstance(raw_options, dict):
        _raise_runtime_validation_error("options", options, "an object")

    try:
        parsed = CanonicalOptionGroups.model_validate(raw_options)
    except ValidationError as error:
        _raise_model_validation_tool_error("options", error)

    extraction_values: dict[str, Any] = {}
    if parsed.extraction is not None:
        extraction_values = parsed.extraction.model_dump(exclude_none=True, by_alias=True)
        if "extraction_mode" in extraction_values:
            extraction_values["extraction_mode"] = _normalize_extraction_mode(
                cast(str, extraction_values["extraction_mode"])
            )

    transformation_values = (
        parsed.transformation.model_dump(exclude_none=True) if parsed.transformation else {}
    )

    conversion_values: dict[str, Any] = (
        parsed.conversion.model_dump(exclude_none=True) if parsed.conversion else {}
    )
    if "capture_artifacts" in conversion_values:
        conversion_values["capture_artifacts"] = _normalize_capture_artifacts(
            cast(list[str], conversion_values["capture_artifacts"])
        )

    runtime_values: dict[str, Any] = {}
    if parsed.runtime is not None:
        runtime_values = parsed.runtime.model_dump(exclude_none=True)
        validated_controls = _validate_optional_runtime_controls(
            timeout_ms=cast(int | None, runtime_values.get("timeout_ms")),
            max_retries=cast(int | None, runtime_values.get("max_retries")),
            retry_backoff_ms=cast(int | None, runtime_values.get("retry_backoff_ms")),
            max_content_chars=cast(int | None, runtime_values.get("max_content_chars")),
        )
        runtime_values = {
            "wait_for": runtime_values.get("wait_for"),
            "bypass_cache": runtime_values.get("bypass_cache"),
            **validated_controls,
        }
        runtime_values = {k: v for k, v in runtime_values.items() if v is not None}

    diagnostics_values = (
        parsed.diagnostics.model_dump(exclude_none=True) if parsed.diagnostics else {}
    )

    session_values: dict[str, Any] = (
        parsed.session.model_dump(exclude_none=True) if parsed.session else {}
    )
    if "session_id" in session_values:
        session_values["session_id"] = _normalize_session_id(
            cast(str, session_values["session_id"])
        )

    render_values = parsed.render.model_dump(exclude_none=True) if parsed.render else {}

    traversal_values: dict[str, Any] = (
        parsed.traversal.model_dump(exclude_none=True) if parsed.traversal else {}
    )
    dispatcher_values = (
        parsed.traversal.dispatcher.model_dump(exclude_none=True)
        if parsed.traversal and parsed.traversal.dispatcher is not None
        else {}
    )
    nested_rate_limit = (
        dispatcher_values.get("rate_limit") if isinstance(dispatcher_values, dict) else None
    )
    nested_rate_limit_dict = nested_rate_limit if isinstance(nested_rate_limit, dict) else {}

    requested_max_concurrency = (
        traversal_values.get("max_concurrency")
        if "max_concurrency" in traversal_values
        else dispatcher_values.get("max_concurrency")
        if isinstance(dispatcher_values, dict)
        else None
    )
    requested_rate_limit_base_delay = (
        traversal_values.get("rate_limit_base_delay")
        if "rate_limit_base_delay" in traversal_values
        else dispatcher_values.get(
            "rate_limit_base_delay", nested_rate_limit_dict.get("base_delay")
        )
        if isinstance(dispatcher_values, dict)
        else None
    )
    requested_rate_limit_max_delay = (
        traversal_values.get("rate_limit_max_delay")
        if "rate_limit_max_delay" in traversal_values
        else dispatcher_values.get("rate_limit_max_delay", nested_rate_limit_dict.get("max_delay"))
        if isinstance(dispatcher_values, dict)
        else None
    )
    requested_rate_limit_max_retries = (
        traversal_values.get("rate_limit_max_retries")
        if "rate_limit_max_retries" in traversal_values
        else dispatcher_values.get(
            "rate_limit_max_retries", nested_rate_limit_dict.get("max_retries")
        )
        if isinstance(dispatcher_values, dict)
        else None
    )

    normalized_max_concurrency = _validate_optional_size_bound(
        cast(int | None, requested_max_concurrency),
        param_name="traversal.max_concurrency",
        minimum=1,
        maximum=_get_crawl_many_hard_max_concurrency(),
    )
    normalized_rate_limit_base_delay = _validate_optional_numeric_range(
        cast(float | None, requested_rate_limit_base_delay),
        param_name="traversal.rate_limit_base_delay",
        minimum=CRAWL_MANY_RATE_DELAY_MIN,
        maximum=CRAWL_MANY_RATE_DELAY_MAX,
    )
    normalized_rate_limit_max_delay = _validate_optional_numeric_range(
        cast(float | None, requested_rate_limit_max_delay),
        param_name="traversal.rate_limit_max_delay",
        minimum=CRAWL_MANY_RATE_DELAY_MIN,
        maximum=CRAWL_MANY_RATE_DELAY_MAX,
    )
    normalized_rate_limit_max_retries = _validate_optional_size_bound(
        cast(int | None, requested_rate_limit_max_retries),
        param_name="traversal.rate_limit_max_retries",
        minimum=CRAWL_MANY_RATE_RETRIES_MIN,
        maximum=CRAWL_MANY_RATE_RETRIES_MAX,
    )
    if (
        normalized_rate_limit_base_delay is not None
        and normalized_rate_limit_max_delay is not None
        and normalized_rate_limit_max_delay < normalized_rate_limit_base_delay
    ):
        raise ToolError(
            "Invalid traversal.rate_limit_max_delay: must be greater than or equal to traversal.rate_limit_base_delay."
        )

    if traversal_values:
        traversal_values["mode"] = _normalize_optional_traversal_mode(
            cast(str | None, traversal_values.get("mode"))
        )
        traversal_values["crawl_mode"] = _normalize_optional_crawl_mode(
            cast(str | None, traversal_values.get("crawl_mode"))
        )
        traversal_values["url_filters"] = _normalize_canonical_url_filters(
            cast(dict[str, Any] | None, traversal_values.get("url_filters")),
            param_name="traversal.url_filters",
        )
        traversal_values["max_concurrency"] = normalized_max_concurrency
        traversal_values["rate_limit_base_delay"] = normalized_rate_limit_base_delay
        traversal_values["rate_limit_max_delay"] = normalized_rate_limit_max_delay
        traversal_values["rate_limit_max_retries"] = normalized_rate_limit_max_retries

        normalized_dispatcher_values = {
            "max_concurrency": normalized_max_concurrency,
            "rate_limit_base_delay": normalized_rate_limit_base_delay,
            "rate_limit_max_delay": normalized_rate_limit_max_delay,
            "rate_limit_max_retries": normalized_rate_limit_max_retries,
        }
        normalized_dispatcher_values = {
            key: value for key, value in normalized_dispatcher_values.items() if value is not None
        }
        if normalized_dispatcher_values:
            traversal_values["dispatcher"] = normalized_dispatcher_values
        else:
            traversal_values.pop("dispatcher", None)

        traversal_values = {k: v for k, v in traversal_values.items() if v is not None}

    if normalized_operation == "scrape":
        has_traversal_controls = (
            any(
                value is not None
                for value in (
                    parsed.traversal.max_depth,
                    parsed.traversal.max_pages,
                    parsed.traversal.mode,
                    parsed.traversal.crawl_mode,
                    parsed.traversal.include_external,
                    parsed.traversal.url_filters,
                    requested_max_concurrency,
                    requested_rate_limit_base_delay,
                    requested_rate_limit_max_delay,
                    requested_rate_limit_max_retries,
                    parsed.traversal.dispatcher,
                )
            )
            if parsed.traversal is not None
            else False
        )
        if has_traversal_controls:
            raise ToolError(
                "Invalid options.traversal: traversal controls are only valid for operation='crawl'."
            )

    normalized_session_id = cast(str | None, session_values.get("session_id"))
    normalized_capture_artifacts = cast(
        list[str] | None, conversion_values.get("capture_artifacts")
    )
    if normalized_capture_artifacts and normalized_session_id is None:
        raise ToolError(
            "Invalid options.conversion.capture_artifacts: requires options.session.session_id."
        )

    try:
        return CanonicalNormalizedOptionGroups(
            extraction=CanonicalExtractionOptions.model_validate(extraction_values),
            transformation=CanonicalTransformationOptions.model_validate(transformation_values),
            conversion=CanonicalConversionOptions.model_validate(conversion_values),
            runtime=CanonicalRuntimeOptions.model_validate(runtime_values),
            diagnostics=CanonicalDiagnosticsOptions.model_validate(diagnostics_values),
            session=CanonicalSessionOptions.model_validate(session_values),
            render=CanonicalRenderOptions.model_validate(render_values),
            traversal=CanonicalTraversalOptions.model_validate(traversal_values),
        )
    except ValidationError as error:
        _raise_model_validation_tool_error("options", error)


def _get_crawler(ctx: Context | None) -> AsyncWebCrawler:
    """Extract the shared crawler from the lifespan context."""
    if ctx is None:
        raise ToolError("Crawler not available — server not fully initialized.")
    return ctx.lifespan_context["crawler"]


def _get_session_registry(ctx: Context | None) -> dict[str, dict[str, int | float]]:
    """Extract the shared session registry from the lifespan context."""
    if ctx is None:
        raise ToolError("Session registry not available — server not fully initialized.")
    registry = ctx.lifespan_context.get("sessions")
    if not isinstance(registry, dict):
        raise ToolError("Session registry not available — server not fully initialized.")
    return cast(dict[str, dict[str, int | float]], registry)


def _get_session_ttl_seconds() -> int:
    """Return the bounded default session TTL."""
    configured = _get_settings().policies.session_ttl_seconds_default
    resolved = SESSION_TTL_SECONDS_DEFAULT if configured is None else configured
    return max(SESSION_TTL_SECONDS_MIN, min(resolved, SESSION_TTL_SECONDS_MAX))


def _get_session_usage_limit() -> int:
    """Return the bounded default per-session usage limit."""
    configured = _get_settings().policies.session_max_uses_default
    resolved = SESSION_MAX_USES_DEFAULT if configured is None else configured
    return max(SESSION_MAX_USES_MIN, min(resolved, SESSION_MAX_USES_MAX))


def _get_artifact_store_optional(ctx: Context | None) -> dict[str, Any] | None:
    """Return the artifact store when available."""
    if ctx is None:
        return None
    store = ctx.lifespan_context.get("artifacts")
    return cast(dict[str, Any], store) if isinstance(store, dict) else None


def _get_artifact_store(ctx: Context | None) -> dict[str, Any]:
    """Extract the shared artifact store from lifespan context."""
    artifact_store = _get_artifact_store_optional(ctx)
    if artifact_store is None:
        raise ToolError("Artifact store not available — server not fully initialized.")
    return artifact_store


def _get_artifact_ttl_seconds() -> int:
    """Return bounded artifact retention TTL in seconds."""
    configured = _get_settings().policies.artifact_ttl_seconds_default
    resolved = ARTIFACT_TTL_SECONDS_DEFAULT if configured is None else configured
    return max(ARTIFACT_TTL_SECONDS_MIN, min(resolved, ARTIFACT_TTL_SECONDS_MAX))


def _get_artifact_max_per_session() -> int:
    """Return bounded per-session artifact retention count."""
    configured = _get_settings().policies.artifact_max_per_session_default
    resolved = ARTIFACT_MAX_PER_SESSION_DEFAULT if configured is None else configured
    return max(
        ARTIFACT_MAX_PER_SESSION_MIN,
        min(resolved, ARTIFACT_MAX_PER_SESSION_MAX),
    )


def _get_artifact_max_total() -> int:
    """Return bounded global artifact retention count."""
    configured = _get_settings().policies.artifact_max_total_default
    resolved = ARTIFACT_MAX_TOTAL_DEFAULT if configured is None else configured
    return max(ARTIFACT_MAX_TOTAL_MIN, min(resolved, ARTIFACT_MAX_TOTAL_MAX))


def _get_artifact_max_total_bytes() -> int:
    """Return bounded global artifact byte budget."""
    configured = _get_settings().policies.artifact_max_total_bytes_default
    resolved = ARTIFACT_MAX_TOTAL_BYTES_DEFAULT if configured is None else configured
    return max(
        ARTIFACT_MAX_TOTAL_BYTES_MIN,
        min(resolved, ARTIFACT_MAX_TOTAL_BYTES_MAX),
    )


def _normalize_artifact_id(artifact_id: str) -> str:
    """Normalize and validate artifact identifiers."""
    if not isinstance(artifact_id, str):
        _raise_runtime_validation_error(
            "artifact_id",
            artifact_id,
            (
                f"a non-empty string up to {ARTIFACT_ID_MAX_CHARS} characters containing letters, "
                "numbers, '.', '_', ':', or '-'"
            ),
        )
    normalized_artifact_id = artifact_id.strip()
    if (
        not normalized_artifact_id
        or len(normalized_artifact_id) > ARTIFACT_ID_MAX_CHARS
        or ARTIFACT_ID_PATTERN.fullmatch(normalized_artifact_id) is None
    ):
        _raise_runtime_validation_error(
            "artifact_id",
            artifact_id,
            (
                f"a non-empty string up to {ARTIFACT_ID_MAX_CHARS} characters containing letters, "
                "numbers, '.', '_', ':', or '-'"
            ),
        )
    return normalized_artifact_id


def _normalize_capture_artifacts(capture_artifacts: list[str] | None) -> list[str]:
    """Normalize and validate requested artifact capture types."""
    if capture_artifacts is None:
        return []
    if not isinstance(capture_artifacts, list):
        _raise_runtime_validation_error(
            "capture_artifacts",
            capture_artifacts,
            f"a list containing up to {ARTIFACT_CAPTURE_MAX_TYPES} artifact types",
        )
    if len(capture_artifacts) > ARTIFACT_CAPTURE_MAX_TYPES:
        _raise_runtime_validation_error(
            "capture_artifacts",
            capture_artifacts,
            f"a list containing up to {ARTIFACT_CAPTURE_MAX_TYPES} artifact types",
        )

    normalized: list[str] = []
    for index, raw_value in enumerate(capture_artifacts):
        if not isinstance(raw_value, str):
            _raise_runtime_validation_error(
                f"capture_artifacts[{index}]",
                raw_value,
                f"one of {sorted(ARTIFACT_CAPTURE_TYPES)}",
            )
        artifact_type = raw_value.strip().lower()
        if artifact_type not in ARTIFACT_CAPTURE_TYPES:
            _raise_runtime_validation_error(
                f"capture_artifacts[{index}]",
                raw_value,
                f"one of {sorted(ARTIFACT_CAPTURE_TYPES)}",
            )
        if artifact_type not in normalized:
            normalized.append(artifact_type)
    return normalized


def _normalize_session_id(session_id: str | None) -> str | None:
    """Normalize and validate an optional session identifier."""
    if session_id is None:
        return None
    if not isinstance(session_id, str):
        _raise_runtime_validation_error(
            "session_id",
            session_id,
            (
                f"a non-empty string up to {SESSION_ID_MAX_CHARS} characters containing letters, "
                "numbers, '.', '_', ':', or '-'"
            ),
        )

    normalized_session_id = session_id.strip()
    if (
        not normalized_session_id
        or len(normalized_session_id) > SESSION_ID_MAX_CHARS
        or SESSION_ID_PATTERN.fullmatch(normalized_session_id) is None
    ):
        _raise_runtime_validation_error(
            "session_id",
            session_id,
            (
                f"a non-empty string up to {SESSION_ID_MAX_CHARS} characters containing letters, "
                "numbers, '.', '_', ':', or '-'"
            ),
        )
    return normalized_session_id


async def _close_crawler_session(
    crawler: AsyncWebCrawler,
    session_id: str,
    *,
    raise_on_error: bool = False,
) -> None:
    """Best-effort close for an underlying crawler session."""
    kill_session = getattr(getattr(crawler, "crawler_strategy", None), "kill_session", None)
    if not callable(kill_session):
        return
    try:
        await cast(Any, kill_session)(session_id)
    except Exception as e:
        if raise_on_error:
            raise ToolError(f"Failed to close session {session_id!r}: {e}") from e


async def _cleanup_expired_sessions(
    *,
    session_registry: dict[str, dict[str, int | float]],
    crawler: AsyncWebCrawler,
    now: float,
    session_ttl_seconds: int | None = None,
) -> list[str]:
    """Close and forget sessions whose TTL has expired."""
    ttl_seconds = _get_session_ttl_seconds() if session_ttl_seconds is None else session_ttl_seconds
    expired_session_ids: list[str] = []
    for existing_session_id, state in session_registry.items():
        last_used_at = state.get("last_used_at")
        state_ttl = state.get("session_ttl_seconds")
        effective_ttl = (
            int(state_ttl)
            if isinstance(state_ttl, (int, float)) and not isinstance(state_ttl, bool)
            else ttl_seconds
        )
        if isinstance(last_used_at, (int, float)) and now - float(last_used_at) > effective_ttl:
            expired_session_ids.append(existing_session_id)

    for expired_session_id in expired_session_ids:
        session_registry.pop(expired_session_id, None)
        await _close_crawler_session(crawler, expired_session_id)
    return expired_session_ids


async def _bind_session_id(
    *,
    session_id: str | None,
    crawler: AsyncWebCrawler,
    ctx: Context | None,
    session_ttl_seconds: int | None = None,
    session_max_uses: int | None = None,
) -> str | None:
    """Resolve an optional session ID while enforcing TTL and usage quotas."""
    normalized_session_id = _normalize_session_id(session_id)
    if normalized_session_id is None:
        return None

    session_registry = _get_session_registry(ctx)
    now = time.time()
    expired_session_ids = await _cleanup_expired_sessions(
        session_registry=session_registry,
        crawler=crawler,
        now=now,
        session_ttl_seconds=session_ttl_seconds,
    )
    artifact_store = _get_artifact_store_optional(ctx)
    if artifact_store is not None:
        for expired_session_id in expired_session_ids:
            _purge_session_artifacts(artifact_store=artifact_store, session_id=expired_session_id)

    state = session_registry.get(normalized_session_id)
    if state is None:
        state = {"created_at": now, "last_used_at": now, "uses": 0}
        session_registry[normalized_session_id] = state

    if session_ttl_seconds is not None:
        state["session_ttl_seconds"] = session_ttl_seconds
    effective_session_max_uses = (
        _get_session_usage_limit() if session_max_uses is None else session_max_uses
    )
    if session_max_uses is not None:
        state["session_max_uses"] = session_max_uses
    state_max_uses = state.get("session_max_uses")
    if isinstance(state_max_uses, (int, float)) and not isinstance(state_max_uses, bool):
        effective_session_max_uses = int(state_max_uses)

    current_uses = state.get("uses", 0)
    uses = int(current_uses) if isinstance(current_uses, (int, float)) else 0
    if uses >= effective_session_max_uses:
        session_registry.pop(normalized_session_id, None)
        if artifact_store is not None:
            _purge_session_artifacts(
                artifact_store=artifact_store,
                session_id=normalized_session_id,
            )
        await _close_crawler_session(crawler, normalized_session_id)
        raise ToolError(
            f"Session quota exceeded for session_id {normalized_session_id!r}. "
            "Use a new session_id or close stale sessions."
        )

    state["uses"] = uses + 1
    state["last_used_at"] = now
    return normalized_session_id


def _is_sensitive_artifact_key(key: str) -> bool:
    """Return True when a key indicates sensitive auth/cookie data."""
    normalized_key = key.strip().lower()
    return (
        normalized_key in SENSITIVE_ARTIFACT_KEYS
        or "cookie" in normalized_key
        or "authorization" in normalized_key
        or "token" in normalized_key
        or "api_key" in normalized_key
        or "apikey" in normalized_key
    )


def _sanitize_artifact_value(value: Any, *, field_name: str | None = None) -> Any:  # AUDIT: M-04 — unbounded recursion; deeply nested payloads can hit recursion limit
    """Recursively sanitize and bound artifact payload values."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_name = str(key)
            if _is_sensitive_artifact_key(key_name):
                continue
            sanitized_item = _sanitize_artifact_value(item, field_name=key_name)
            if sanitized_item is not None:
                sanitized[key_name] = sanitized_item
        return sanitized

    if isinstance(value, (list, tuple, set)):
        return [
            _sanitize_artifact_value(item, field_name=field_name)
            for item in list(value)[:ARTIFACT_CAPTURE_LIST_MAX_ITEMS]
        ]

    if isinstance(value, str):
        if field_name is not None and "url" in field_name.lower():
            safe_url = _sanitize_diagnostic_url(value)
            if safe_url is not None:
                return safe_url
        return value[:ARTIFACT_CAPTURE_TEXT_MAX_CHARS]

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    return str(value)[:ARTIFACT_CAPTURE_TEXT_MAX_CHARS]


def _truncate_artifact_content(content: str) -> str:
    """Apply bounded artifact content truncation."""
    return content[:ARTIFACT_CAPTURE_TEXT_MAX_CHARS]


def _next_artifact_store_id(
    artifact_store: dict[str, Any], *, counter_key: str, prefix: str
) -> str:
    """Generate a monotonic identifier backed by artifact store counters."""
    raw_value = artifact_store.get(counter_key, 0)
    index = int(raw_value) + 1 if isinstance(raw_value, (int, float)) else 1
    artifact_store[counter_key] = index
    return f"{prefix}-{index:08d}"


def _next_opaque_artifact_id(artifact_store: dict[str, Any]) -> str:  # AUDIT: M-05 — while True loop has no termination guard
    """Generate a non-enumerable artifact identifier."""
    artifacts = artifact_store.get("artifacts")
    while True:
        artifact_id = f"a-{secrets.token_urlsafe(12)}"
        if not isinstance(artifacts, dict) or artifact_id not in artifacts:
            return artifact_id


def _artifact_metadata_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    """Return safe artifact metadata without content."""
    return {
        "artifact_id": artifact.get("artifact_id"),
        "run_id": artifact.get("run_id"),
        "session_id": artifact.get("session_id"),
        "artifact_type": artifact.get("artifact_type"),
        "content_type": artifact.get("content_type"),
        "encoding": artifact.get("encoding"),
        "size_bytes": artifact.get("size_bytes"),
        "item_count": artifact.get("item_count"),
        "created_at": artifact.get("created_at"),
        "expires_at": artifact.get("expires_at"),
    }


def _remove_artifact_entry(artifact_store: dict[str, Any], artifact_id: str) -> None:
    """Remove one artifact and clean up all related indexes."""
    artifacts = artifact_store.get("artifacts")
    if not isinstance(artifacts, dict):
        return
    artifact = artifacts.pop(artifact_id, None)
    if not isinstance(artifact, dict):
        return

    order = artifact_store.get("artifact_order")
    if isinstance(order, list):
        artifact_store["artifact_order"] = [item for item in order if item != artifact_id]

    size_bytes = artifact.get("size_bytes")
    if isinstance(size_bytes, (int, float)):
        total_bytes = artifact_store.get("total_bytes", 0)
        if isinstance(total_bytes, (int, float)):
            artifact_store["total_bytes"] = max(0, int(total_bytes) - int(size_bytes))

    session_id = artifact.get("session_id")
    session_artifacts = artifact_store.get("session_artifacts")
    if isinstance(session_id, str) and isinstance(session_artifacts, dict):
        scoped_ids = session_artifacts.get(session_id)
        if isinstance(scoped_ids, list):
            remaining_ids = [item for item in scoped_ids if item != artifact_id]
            if remaining_ids:
                session_artifacts[session_id] = remaining_ids
            else:
                session_artifacts.pop(session_id, None)

    run_id = artifact.get("run_id")
    runs = artifact_store.get("runs")
    if isinstance(run_id, str) and isinstance(runs, dict):
        run_record = runs.get(run_id)
        if isinstance(run_record, dict):
            run_artifacts = run_record.get("artifact_ids")
            if isinstance(run_artifacts, list):
                run_record["artifact_ids"] = [item for item in run_artifacts if item != artifact_id]


def _purge_session_artifacts(*, artifact_store: dict[str, Any], session_id: str) -> None:
    """Remove all artifact/run records tied to a session."""
    session_artifacts = artifact_store.get("session_artifacts")
    if isinstance(session_artifacts, dict):
        artifact_ids = session_artifacts.pop(session_id, [])
        if isinstance(artifact_ids, list):
            for artifact_id in list(artifact_ids):
                if isinstance(artifact_id, str):
                    _remove_artifact_entry(artifact_store, artifact_id)

    session_runs = artifact_store.get("session_runs")
    runs = artifact_store.get("runs")
    if isinstance(session_runs, dict):
        run_ids = session_runs.pop(session_id, [])
        if isinstance(run_ids, list) and isinstance(runs, dict):
            for run_id in run_ids:
                if isinstance(run_id, str):
                    runs.pop(run_id, None)


def _prune_expired_artifacts(*, artifact_store: dict[str, Any], now: float) -> None:
    """Drop artifacts past their expiration deadline."""
    artifacts = artifact_store.get("artifacts")
    if not isinstance(artifacts, dict):
        return

    expired_artifact_ids = []
    for artifact_id, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            continue
        expires_at = artifact.get("expires_at")
        if isinstance(expires_at, (int, float)) and now > float(expires_at):
            expired_artifact_ids.append(artifact_id)

    for artifact_id in expired_artifact_ids:
        _remove_artifact_entry(artifact_store, artifact_id)


def _enforce_artifact_retention(
    *,
    artifact_store: dict[str, Any],
    now: float,
    session_id: str | None = None,
    artifact_max_per_session: int | None = None,
    artifact_max_total: int | None = None,
    artifact_max_total_bytes: int | None = None,
) -> None:
    """Enforce TTL, count, and byte-budget artifact retention limits."""
    _prune_expired_artifacts(artifact_store=artifact_store, now=now)

    session_artifacts = artifact_store.get("session_artifacts")
    if session_id is not None and isinstance(session_artifacts, dict):
        max_per_session = (
            _get_artifact_max_per_session()
            if artifact_max_per_session is None
            else artifact_max_per_session
        )
        scoped_ids = session_artifacts.get(session_id)
        while isinstance(scoped_ids, list) and len(scoped_ids) > max_per_session:
            oldest_id = scoped_ids[0]
            if not isinstance(oldest_id, str):
                break
            _remove_artifact_entry(artifact_store, oldest_id)
            scoped_ids = session_artifacts.get(session_id)

    artifact_order = artifact_store.get("artifact_order")
    max_total = _get_artifact_max_total() if artifact_max_total is None else artifact_max_total
    while isinstance(artifact_order, list) and len(artifact_order) > max_total:
        oldest_id = artifact_order[0]
        if not isinstance(oldest_id, str):
            break
        _remove_artifact_entry(artifact_store, oldest_id)
        artifact_order = artifact_store.get("artifact_order")

    artifact_order = artifact_store.get("artifact_order")
    max_total_bytes = (
        _get_artifact_max_total_bytes()
        if artifact_max_total_bytes is None
        else artifact_max_total_bytes
    )
    total_bytes = artifact_store.get("total_bytes", 0)
    while (
        isinstance(artifact_order, list)
        and artifact_order
        and isinstance(total_bytes, (int, float))
        and int(total_bytes) > max_total_bytes
    ):
        oldest_id = artifact_order[0]
        if not isinstance(oldest_id, str):
            break
        _remove_artifact_entry(artifact_store, oldest_id)
        artifact_order = artifact_store.get("artifact_order")
        total_bytes = artifact_store.get("total_bytes", 0)


def _capture_artifact_payload(*, result: Any, artifact_type: str) -> dict[str, Any] | None:
    """Extract and sanitize one artifact payload from a crawl result."""
    if artifact_type == "mhtml":
        source = getattr(result, "mhtml", None)
        if isinstance(source, (bytes, bytearray)):
            return {
                "content": base64.b64encode(bytes(source)).decode("ascii"),
                "content_type": "multipart/related",
                "encoding": "base64",
                "item_count": None,
            }
        if isinstance(source, str):
            return {
                "content": source,
                "content_type": "multipart/related",
                "encoding": "utf-8",
                "item_count": None,
            }
        return None

    if artifact_type == "pdf":
        source = getattr(result, "pdf", None)
        if isinstance(source, (bytes, bytearray)):
            return {
                "content": base64.b64encode(bytes(source)).decode("ascii"),
                "content_type": "application/pdf",
                "encoding": "base64",
                "item_count": None,
            }
        if isinstance(source, str):
            return {
                "content": source,
                "content_type": "application/pdf",
                "encoding": "utf-8",
                "item_count": None,
            }
        return None

    if artifact_type == "console":
        source = getattr(result, "console_messages", None)
        if not isinstance(source, (list, tuple)):
            return None
        sanitized_source = _sanitize_artifact_value(source)
        return {
            "content": json.dumps(sanitized_source, ensure_ascii=False),
            "content_type": "application/json",
            "encoding": "utf-8",
            "item_count": _safe_diagnostic_count(source),
        }

    if artifact_type == "network":
        source = getattr(result, "network_requests", None)
        if not isinstance(source, (list, tuple)):
            return None
        sanitized_source = _sanitize_artifact_value(source)
        return {
            "content": json.dumps(sanitized_source, ensure_ascii=False),
            "content_type": "application/json",
            "encoding": "utf-8",
            "item_count": _safe_diagnostic_count(source),
        }

    return None


def _capture_result_artifacts(
    *,
    artifact_store: dict[str, Any],
    result: Any,
    capture_artifacts: list[str],
    session_id: str,
    requested_url: str,
    artifact_ttl_seconds: int | None = None,
    artifact_max_per_session: int | None = None,
    artifact_max_total: int | None = None,
    artifact_max_total_bytes: int | None = None,
) -> dict[str, Any]:
    """Capture selected artifacts and return run-level metadata payload."""
    now = time.time()
    _enforce_artifact_retention(
        artifact_store=artifact_store,
        now=now,
        session_id=session_id,
        artifact_max_per_session=artifact_max_per_session,
        artifact_max_total=artifact_max_total,
        artifact_max_total_bytes=artifact_max_total_bytes,
    )
    effective_artifact_ttl = (
        _get_artifact_ttl_seconds() if artifact_ttl_seconds is None else artifact_ttl_seconds
    )

    run_id = _next_artifact_store_id(
        artifact_store,
        counter_key="next_run_index",
        prefix="run",
    )
    run_record: dict[str, Any] = {
        "run_id": run_id,
        "session_id": session_id,
        "requested_url": _sanitize_diagnostic_url(requested_url),
        "result_url": _sanitize_diagnostic_url(getattr(result, "url", None)),
        "created_at": now,
        "artifact_ids": [],
    }

    runs = artifact_store.get("runs")
    if isinstance(runs, dict):
        runs[run_id] = run_record

    session_runs = artifact_store.get("session_runs")
    if isinstance(session_runs, dict):
        run_ids = session_runs.get(session_id)
        if not isinstance(run_ids, list):
            run_ids = []
        run_ids.append(run_id)
        session_runs[session_id] = run_ids

    for artifact_type in capture_artifacts:
        captured_payload = _capture_artifact_payload(result=result, artifact_type=artifact_type)
        if captured_payload is None:
            continue

        content = _truncate_artifact_content(str(captured_payload["content"]))
        size_bytes = len(content.encode("utf-8"))
        artifact_id = _next_opaque_artifact_id(artifact_store)
        artifact_record = {
            "artifact_id": artifact_id,
            "run_id": run_id,
            "session_id": session_id,
            "artifact_type": artifact_type,
            "content_type": captured_payload["content_type"],
            "encoding": captured_payload["encoding"],
            "size_bytes": size_bytes,
            "item_count": captured_payload["item_count"],
            "created_at": now,
            "expires_at": now + effective_artifact_ttl,
            "content": content,
        }

        artifacts = artifact_store.get("artifacts")
        if isinstance(artifacts, dict):
            artifacts[artifact_id] = artifact_record
        run_record["artifact_ids"].append(artifact_id)

        session_artifacts = artifact_store.get("session_artifacts")
        if isinstance(session_artifacts, dict):
            artifact_ids = session_artifacts.get(session_id)
            if not isinstance(artifact_ids, list):
                artifact_ids = []
            artifact_ids.append(artifact_id)
            session_artifacts[session_id] = artifact_ids

        order = artifact_store.get("artifact_order")
        if isinstance(order, list):
            order.append(artifact_id)

        total_bytes = artifact_store.get("total_bytes", 0)
        if isinstance(total_bytes, (int, float)):
            artifact_store["total_bytes"] = int(total_bytes) + size_bytes

        _enforce_artifact_retention(
            artifact_store=artifact_store,
            now=now,
            session_id=session_id,
            artifact_max_per_session=artifact_max_per_session,
            artifact_max_total=artifact_max_total,
            artifact_max_total_bytes=artifact_max_total_bytes,
        )

    artifacts = artifact_store.get("artifacts")
    artifact_ids = run_record.get("artifact_ids")
    run_artifacts = []
    if isinstance(artifacts, dict) and isinstance(artifact_ids, list):
        for artifact_id in artifact_ids:
            artifact = artifacts.get(artifact_id)
            if isinstance(artifact, dict):
                run_artifacts.append(_artifact_metadata_payload(artifact))

    return {
        "run_id": run_id,
        "session_id": session_id,
        "created_at": now,
        "requested_url": run_record["requested_url"],
        "result_url": run_record["result_url"],
        "artifacts": run_artifacts,
    }


def _extract_markdown(result: Any) -> str:
    """Return the best available markdown from a CrawlResult.

    Handles both plain ``str`` and ``MarkdownGenerationResult`` objects,
    preferring ``fit_markdown`` when available.
    """
    md = result.markdown  # AUDIT: M-06 — direct attribute access; use getattr for safety against API changes
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
    "text": lambda r: re.sub(  # AUDIT: L-02 — fragile markdown-to-text regex; fails on nested formatting, code blocks, tables
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


def _sanitize_diagnostic_url(url: Any) -> str | None:
    """Return a bounded, query-stripped URL safe for diagnostics."""
    if not isinstance(url, str) or not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None

    # Sentinel: 🛡️ Security Fix
    # Do not use parsed.netloc directly as it includes basic auth credentials.
    # Use hostname and port to strip out any potential username/password leak.
    netloc = parsed.hostname or ""

    # Re-wrap IPv6 addresses in brackets
    if ":" in netloc and not netloc.startswith("["):
        netloc = f"[{netloc}]"

    try:
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
    except ValueError:
        pass  # Ignore invalid ports

    safe_url = f"{parsed.scheme}://{netloc}{parsed.path or ''}"
    return safe_url[:DIAGNOSTIC_URL_MAX_CHARS]


def _safe_diagnostic_count(value: Any) -> int:
    """Return a bounded count for list/dict/int values."""
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (list, tuple, set, dict)):
        return min(len(value), DIAGNOSTIC_COUNT_MAX)
    if isinstance(value, (int, float)):
        return min(max(int(value), 0), DIAGNOSTIC_COUNT_MAX)
    return 0


def _extract_timing_summary(result: Any) -> dict[str, int | float]:
    """Extract a bounded timing summary from known timing fields."""
    summary: dict[str, int | float] = {}
    timing = getattr(result, "timing", None)
    if isinstance(timing, dict):
        for key in ("total_ms", "fetch_ms", "render_ms", "parse_ms", "dispatch_ms", "queue_ms"):
            value = timing.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                summary[key] = value

    for attr_name in ("duration_ms", "response_time_ms", "total_ms"):
        if attr_name in summary:
            continue
        value = getattr(result, attr_name, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            summary[attr_name] = value

    return summary


def _build_dispatch_summary(dispatcher: SemaphoreDispatcher | None) -> dict[str, int | bool]:
    """Build a bounded dispatcher summary for diagnostics payloads."""
    if dispatcher is None:
        return {}
    return {
        "max_concurrency": _safe_diagnostic_count(getattr(dispatcher, "semaphore_count", None)),
        "max_session_permit": _safe_diagnostic_count(
            getattr(dispatcher, "max_session_permit", None)
        ),
        "rate_limit_enabled": getattr(dispatcher, "rate_limiter", None) is not None,
    }


def _extract_result_diagnostics(
    *,
    result: Any,
    requested_url: str,
    dispatch_summary: dict[str, int | bool] | None = None,
) -> dict[str, Any]:
    """Extract bounded, redacted diagnostics metadata from a crawl result."""
    status_code = getattr(result, "status_code", None)
    safe_status_code = (
        status_code
        if isinstance(status_code, int)
        and not isinstance(status_code, bool)
        and 100 <= status_code <= 599
        else None
    )

    requested_safe_url = _sanitize_diagnostic_url(requested_url)
    final_safe_url = _sanitize_diagnostic_url(getattr(result, "url", None))
    redirected_url = (
        final_safe_url if final_safe_url and final_safe_url != requested_safe_url else None
    )

    metadata = getattr(result, "metadata", None)
    console_source = (
        getattr(result, "console_messages", None)
        if getattr(result, "console_messages", None) is not None
        else metadata.get("console_count")
        if isinstance(metadata, dict)
        else None
    )
    network_source = (
        getattr(result, "network_requests", None)
        if getattr(result, "network_requests", None) is not None
        else metadata.get("network_count")
        if isinstance(metadata, dict)
        else None
    )

    return {
        "status_code": safe_status_code,
        "redirected_url": redirected_url,
        "timing": _extract_timing_summary(result),
        "dispatch": dispatch_summary or {},
        "console_count": _safe_diagnostic_count(console_source),
        "network_count": _safe_diagnostic_count(network_source),
    }


def _get_result_url(result: Any, fallback_url: str) -> str:
    """Return a best-effort URL from result with a safe fallback."""
    result_url = getattr(result, "url", None)
    return result_url if isinstance(result_url, str) and result_url else fallback_url


def _normalize_extraction_mode(extraction_mode: str) -> str:
    """Normalize and validate extraction mode."""
    if not isinstance(extraction_mode, str):
        raise ToolError(
            f"Invalid extraction_mode: {extraction_mode!r}. "
            f"Valid options: {sorted(VALID_EXTRACTION_MODES)}"
        )
    mode = extraction_mode.strip().lower()
    if mode not in VALID_EXTRACTION_MODES:
        raise ToolError(
            f"Invalid extraction_mode: {extraction_mode!r}. "
            f"Valid options: {sorted(VALID_EXTRACTION_MODES)}"
        )
    return mode


def _validate_xpath_schema(schema: dict[str, Any]) -> None:
    """Validate minimal XPath schema requirements."""
    base_selector = schema.get("baseSelector")
    if not isinstance(base_selector, str) or not base_selector.strip():
        raise ToolError(
            "Invalid xpath schema: 'baseSelector' must be a non-empty XPath selector string."
        )

    fields = schema.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ToolError("Invalid xpath schema: 'fields' must be a non-empty list.")

    for index, field in enumerate(fields):
        if not isinstance(field, dict):
            raise ToolError(f"Invalid xpath schema field at index {index}: expected an object.")
        if not isinstance(field.get("name"), str) or not field["name"].strip():
            raise ToolError(
                f"Invalid xpath schema field at index {index}: 'name' must be a non-empty string."
            )
        if not isinstance(field.get("selector"), str) or not field["selector"].strip():
            raise ToolError(
                f"Invalid xpath schema field at index {index}: "
                "'selector' must be a non-empty XPath selector string."
            )
        if field.get("type") == "attribute":
            attribute = field.get("attribute")
            if not isinstance(attribute, str) or not attribute.strip():
                raise ToolError(
                    f"Invalid xpath schema field at index {index}: "
                    "'attribute' must be a non-empty string when type is 'attribute'."
                )


def _build_extraction_strategy(schema: dict[str, Any], extraction_mode: str) -> Any:
    """Build extraction strategy for CSS or XPath schemas."""
    mode = _normalize_extraction_mode(extraction_mode)
    if mode == "xpath":
        _validate_xpath_schema(schema)
        return JsonXPathExtractionStrategy(schema=schema)
    return JsonCssExtractionStrategy(schema=schema)


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
# Tool 1 — scrape
# ---------------------------------------------------------------------------


def _normalize_scrape_targets(targets: str | list[str]) -> list[str]:
    """Normalize scrape targets into a bounded list of URL strings."""
    if isinstance(targets, str):
        normalized_targets = [targets]
    elif isinstance(targets, list):
        normalized_targets = targets
    else:
        _raise_runtime_validation_error(
            "targets",
            targets,
            "a URL string or a list containing 1 to 20 URL strings",
        )

    if not normalized_targets or len(normalized_targets) > SCRAPE_TARGETS_MAX_ITEMS:
        _raise_runtime_validation_error(
            "targets",
            targets,
            f"a URL string or a list containing 1 to {SCRAPE_TARGETS_MAX_ITEMS} URL strings",
        )

    validated_targets: list[str] = []
    for index, target in enumerate(normalized_targets):
        if not isinstance(target, str):
            _raise_runtime_validation_error(
                f"targets[{index}]",
                target,
                "a non-empty http/https URL string",
            )
        normalized_target = target.strip()
        if not normalized_target:
            _raise_runtime_validation_error(
                f"targets[{index}]",
                target,
                "a non-empty http/https URL string",
            )
        _validate_url(normalized_target)
        validated_targets.append(normalized_target)
    return validated_targets


@mcp.tool(
    annotations={
        "title": "Scrape",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def scrape(
    targets: Annotated[
        str | list[str],
        Field(
            description=(
                "One URL string or a list of URLs to scrape. "
                f"Lists must contain between 1 and {SCRAPE_TARGETS_MAX_ITEMS} URLs."
            )
        ),
    ],
    options: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Canonical option groups: extraction, transformation, conversion, runtime, "
                "diagnostics, session, and render."
            )
        ),
    ] = None,
    ctx: Context | None = None,
) -> str:
    """Scrape one or many pages with a single canonical contract.

    Use this tool for both single-page and batch scraping with shared option groups and
    predictable JSON output. Do not use it for recursive traversal controls; those belong
    to the canonical crawl contract. The tool always returns the same envelope shape with
    data/items, bounded diagnostics, warnings, and a structured error object.
    """
    normalized_targets = _normalize_scrape_targets(targets)
    normalized_options = _normalize_canonical_option_groups(operation="scrape", options=options)
    provided_option_groups = (
        sorted(key for key in options if key in CanonicalOptionGroups.model_fields)
        if isinstance(options, dict)
        else []
    )

    extraction_options = normalized_options.extraction
    transformation_options = normalized_options.transformation
    conversion_options = normalized_options.conversion
    runtime_options = normalized_options.runtime
    diagnostics_options = normalized_options.diagnostics
    session_options = normalized_options.session
    render_options = normalized_options.render

    extraction_schema = extraction_options.extraction_schema
    if extraction_schema is None and extraction_options.extraction_mode is not None:
        raise ToolError(
            "Invalid options.extraction.extraction_mode: requires options.extraction.schema."
        )
    extraction_mode = (
        extraction_options.extraction_mode
        if extraction_options.extraction_mode is not None
        else "css"
    )
    extraction_strategy = (
        _build_extraction_strategy(extraction_schema, extraction_mode)
        if extraction_schema is not None
        else None
    )

    normalized_capture_artifacts = _normalize_capture_artifacts(
        conversion_options.capture_artifacts
    )
    include_diagnostics = bool(diagnostics_options.include_diagnostics)
    output_format = conversion_options.output_format or "markdown"

    crawler = _get_crawler(ctx)
    assert ctx is not None  # AUDIT: M-01 — bare assert stripped under -O; replace with if/raise ToolError
    await ctx.info(f"Scraping {len(normalized_targets)} target(s)")
    normalized_session_id = await _bind_session_id(
        session_id=session_options.session_id,
        crawler=crawler,
        ctx=ctx,
        session_ttl_seconds=session_options.session_ttl_seconds,
        session_max_uses=session_options.session_max_uses,
    )
    if normalized_capture_artifacts and normalized_session_id is None:  # AUDIT: L-06 — duplicate check; already validated in _normalize_canonical_option_groups
        raise ToolError(
            "Invalid options.conversion.capture_artifacts: requires options.session.session_id."
        )

    runtime_controls = _validate_optional_runtime_controls(  # AUDIT: M-09 — redundant double-validation; Pydantic models already enforce ranges
        timeout_ms=runtime_options.timeout_ms,
        max_retries=runtime_options.max_retries,
        retry_backoff_ms=runtime_options.retry_backoff_ms,
        max_content_chars=runtime_options.max_content_chars,
    )
    if render_options.viewport_width is not None:
        runtime_controls["viewport_width"] = render_options.viewport_width
    if render_options.viewport_height is not None:
        runtime_controls["viewport_height"] = render_options.viewport_height

    config = _build_run_config(
        css_selector=extraction_options.css_selector,
        word_count_threshold=(
            extraction_options.word_count_threshold
            if extraction_options.word_count_threshold is not None
            else 200
        ),
        wait_for=runtime_options.wait_for,
        bypass_cache=bool(runtime_options.bypass_cache),
        session_id=normalized_session_id,
        extraction_strategy=extraction_strategy,
        js_code=(
            [transformation_options.js_code] if transformation_options.js_code is not None else None
        ),
    )
    if render_options.viewport_width is not None:
        config.viewport_width = render_options.viewport_width
    if render_options.viewport_height is not None:
        config.viewport_height = render_options.viewport_height

    dispatch_summary: dict[str, int | bool] | None = None
    if len(normalized_targets) == 1:
        results: list[Any] = [
            await crawler.arun(
                url=normalized_targets[0],
                config=config,
                **runtime_controls,  # ty: ignore[invalid-argument-type]
            )
        ]
    else:
        dispatcher = _build_crawl_many_dispatcher(batch_size=len(normalized_targets))
        if include_diagnostics:
            dispatch_summary = _build_dispatch_summary(dispatcher)
        arun_many_results = await crawler.arun_many(
            urls=normalized_targets,
            config=config,
            dispatcher=dispatcher,
            **runtime_controls,
        )
        results = list(cast(Any, arun_many_results))

    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    failed_count = 0
    for index, result in enumerate(results):
        requested_target = normalized_targets[index] if index < len(normalized_targets) else ""
        result_url = _get_result_url(result, requested_target)
        item: dict[str, Any] = {
            "target": requested_target,
            "url": result_url,
            "ok": bool(getattr(result, "success", False)),
        }

        if item["ok"]:
            if extraction_schema is not None:
                extracted_content = getattr(result, "extracted_content", None)
                if not extracted_content:
                    item["ok"] = False
                    item["error"] = "No data extracted. Check options.extraction.schema selectors."
                else:
                    truncate_limit = (
                        None if len(normalized_targets) == 1 else _get_batch_item_chars()
                    )
                    item["data"] = _truncate(str(extracted_content), truncate_limit)
            else:
                selected_content = _select_content(result, output_format)
                truncate_limit = None if len(normalized_targets) == 1 else _get_batch_item_chars()
                item["data"] = _truncate(selected_content, truncate_limit)

        if not item["ok"]:
            failed_count += 1
            if "error" not in item:
                item["error"] = str(getattr(result, "error_message", "Scrape failed"))
        elif normalized_capture_artifacts:
            assert normalized_session_id is not None
            artifact_store = _get_artifact_store(ctx)
            item["run"] = _capture_result_artifacts(
                artifact_store=artifact_store,
                result=result,
                capture_artifacts=normalized_capture_artifacts,
                session_id=normalized_session_id,
                requested_url=requested_target,
                artifact_ttl_seconds=session_options.artifact_ttl_seconds,
                artifact_max_per_session=session_options.artifact_max_per_session,
                artifact_max_total=session_options.artifact_max_total,
                artifact_max_total_bytes=session_options.artifact_max_total_bytes,
            )

        if include_diagnostics:
            item["diagnostics"] = _extract_result_diagnostics(
                result=result,
                requested_url=requested_target or result_url,
                dispatch_summary=dispatch_summary,
            )

        items.append(item)

    ok = failed_count == 0
    if failed_count > 0:
        warning_message = (
            f"{failed_count} of {len(normalized_targets)} target(s) failed during scrape."
        )
        warnings.append(warning_message)
        await ctx.warning(warning_message)

    envelope: dict[str, Any] = {
        "schema_version": SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION,
        "tool": "scrape",
        "ok": ok,
        "data": items[0] if len(normalized_targets) == 1 else None,
        "items": items if len(normalized_targets) > 1 else None,
        "meta": {
            "target_count": len(normalized_targets),
            "option_groups": provided_option_groups,
            "output_format": output_format,
            "diagnostics": include_diagnostics,
            "session_id": normalized_session_id,
            "extraction_mode": extraction_mode if extraction_schema is not None else None,
            "traversal_mode": None,
        },
        "warnings": warnings,
        "error": (
            None
            if ok
            else {
                "code": "SCRAPE_FAILED",
                "message": (
                    items[0]["error"]
                    if len(normalized_targets) == 1
                    else f"{failed_count} targets failed"
                ),
            }
        ),
    }
    return _truncate(json.dumps(envelope, indent=2))  # AUDIT: H-01 — truncating serialized JSON produces invalid JSON


# ---------------------------------------------------------------------------
# Tool 2 — crawl (canonical)
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Crawl",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def crawl(
    targets: Annotated[
        str | list[str],
        Field(
            description=(
                "One URL string or a list of URLs to crawl. "
                f"Lists must contain between 1 and {SCRAPE_TARGETS_MAX_ITEMS} URLs."
            )
        ),
    ],
    options: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Canonical option groups: extraction, transformation, conversion, runtime, "
                "diagnostics, session, render, and traversal."
            )
        ),
    ] = None,
    ctx: Context | None = None,
) -> str:
    """Crawl pages with canonical traversal controls and envelope output.

    Use list traversal for bounded URL batches and deep traversal for recursive
    discovery from one seed URL. The tool applies shared scrape/crawl option
    groups plus traversal controls and always returns the canonical JSON envelope.
    """
    normalized_targets = _normalize_scrape_targets(targets)
    normalized_options = _normalize_canonical_option_groups(operation="crawl", options=options)
    provided_option_groups = (
        sorted(key for key in options if key in CanonicalOptionGroups.model_fields)
        if isinstance(options, dict)
        else []
    )

    extraction_options = normalized_options.extraction
    transformation_options = normalized_options.transformation
    conversion_options = normalized_options.conversion
    runtime_options = normalized_options.runtime
    diagnostics_options = normalized_options.diagnostics
    session_options = normalized_options.session
    render_options = normalized_options.render
    traversal_options = normalized_options.traversal

    traversal_mode = traversal_options.mode or "list"
    has_deep_controls = any(
        value is not None
        for value in (
            traversal_options.max_depth,
            traversal_options.max_pages,
            traversal_options.crawl_mode,
            traversal_options.include_external,
            traversal_options.url_filters,
        )
    )
    has_dispatcher_controls = any(
        value is not None
        for value in (
            traversal_options.max_concurrency,
            traversal_options.rate_limit_base_delay,
            traversal_options.rate_limit_max_delay,
            traversal_options.rate_limit_max_retries,
            traversal_options.dispatcher,
        )
    )

    if traversal_mode == "list" and has_deep_controls:
        raise ToolError(
            "Invalid options.traversal: max_depth/max_pages/crawl_mode/include_external/url_filters "
            "require options.traversal.mode='deep'."
        )
    if traversal_mode == "deep" and has_dispatcher_controls:
        raise ToolError(
            "Invalid options.traversal.dispatcher: dispatcher controls are only valid when "
            "options.traversal.mode='list'."
        )
    if traversal_mode == "deep" and len(normalized_targets) != 1:
        raise ToolError("Invalid targets: options.traversal.mode='deep' requires exactly one URL.")

    extraction_schema = extraction_options.extraction_schema
    if extraction_schema is None and extraction_options.extraction_mode is not None:
        raise ToolError(
            "Invalid options.extraction.extraction_mode: requires options.extraction.schema."
        )
    extraction_mode = (
        extraction_options.extraction_mode
        if extraction_options.extraction_mode is not None
        else "css"
    )
    extraction_strategy = (
        _build_extraction_strategy(extraction_schema, extraction_mode)
        if extraction_schema is not None
        else None
    )

    normalized_capture_artifacts = _normalize_capture_artifacts(
        conversion_options.capture_artifacts
    )
    include_diagnostics = bool(diagnostics_options.include_diagnostics)
    output_format = conversion_options.output_format or "markdown"

    crawler = _get_crawler(ctx)
    assert ctx is not None  # AUDIT: M-01 — bare assert stripped under -O; replace with if/raise ToolError
    await ctx.info(f"Crawling {len(normalized_targets)} target(s) in {traversal_mode} mode")
    normalized_session_id = await _bind_session_id(
        session_id=session_options.session_id,
        crawler=crawler,
        ctx=ctx,
        session_ttl_seconds=session_options.session_ttl_seconds,
        session_max_uses=session_options.session_max_uses,
    )
    if normalized_capture_artifacts and normalized_session_id is None:  # AUDIT: L-06 — duplicate check; already validated in _normalize_canonical_option_groups
        raise ToolError(
            "Invalid options.conversion.capture_artifacts: requires options.session.session_id."
        )

    runtime_controls = _validate_optional_runtime_controls(  # AUDIT: M-09 — redundant double-validation; Pydantic models already enforce ranges
        timeout_ms=runtime_options.timeout_ms,
        max_retries=runtime_options.max_retries,
        retry_backoff_ms=runtime_options.retry_backoff_ms,
        max_content_chars=runtime_options.max_content_chars,
    )
    if render_options.viewport_width is not None:
        runtime_controls["viewport_width"] = render_options.viewport_width
    if render_options.viewport_height is not None:
        runtime_controls["viewport_height"] = render_options.viewport_height

    word_count_threshold = (
        extraction_options.word_count_threshold
        if extraction_options.word_count_threshold is not None
        else 200
    )
    js_code = (
        [transformation_options.js_code] if transformation_options.js_code is not None else None
    )

    config = _build_run_config(
        css_selector=extraction_options.css_selector,
        word_count_threshold=word_count_threshold,
        wait_for=runtime_options.wait_for,
        bypass_cache=bool(runtime_options.bypass_cache),
        session_id=normalized_session_id,
        extraction_strategy=extraction_strategy,
        js_code=js_code,
    )
    if render_options.viewport_width is not None:
        config.viewport_width = render_options.viewport_width
    if render_options.viewport_height is not None:
        config.viewport_height = render_options.viewport_height

    dispatch_summary: dict[str, int | bool] | None = None
    results: list[Any]
    requested_targets: list[str]
    if traversal_mode == "list":
        dispatcher = _build_crawl_many_dispatcher(
            batch_size=len(normalized_targets),
            max_concurrency=traversal_options.max_concurrency,
            rate_limit_base_delay=traversal_options.rate_limit_base_delay,
            rate_limit_max_delay=traversal_options.rate_limit_max_delay,
            rate_limit_max_retries=traversal_options.rate_limit_max_retries,
        )
        if include_diagnostics:
            dispatch_summary = _build_dispatch_summary(dispatcher)
        arun_many_results = await crawler.arun_many(
            urls=normalized_targets,
            config=config,
            dispatcher=dispatcher,
            **runtime_controls,
        )
        results = list(cast(Any, arun_many_results))
        requested_targets = normalized_targets
    else:
        deep_config = _build_run_config(
            css_selector=extraction_options.css_selector,
            word_count_threshold=word_count_threshold,
            wait_for=runtime_options.wait_for,
            bypass_cache=bool(runtime_options.bypass_cache),
            session_id=normalized_session_id,
            extraction_strategy=extraction_strategy,
            js_code=js_code,
            deep_crawl_strategy=_build_deep_crawl_strategy(
                crawl_mode=traversal_options.crawl_mode or "bfs",
                max_depth=traversal_options.max_depth or 2,
                max_pages=traversal_options.max_pages or 10,
                include_external=bool(traversal_options.include_external),
                url_filters=traversal_options.url_filters,
            ),
            verbose=False,
        )
        if render_options.viewport_width is not None:
            deep_config.viewport_width = render_options.viewport_width
        if render_options.viewport_height is not None:
            deep_config.viewport_height = render_options.viewport_height

        deep_results: Any = await crawler.arun(  # AUDIT: H-03 — discovered URLs during deep crawl bypass _validate_url SSRF checks
            url=normalized_targets[0],
            config=deep_config,
            **runtime_controls,  # ty: ignore[invalid-argument-type]
        )
        results = (
            list(cast(Any, deep_results)) if isinstance(deep_results, list) else [deep_results]
        )
        requested_targets = [normalized_targets[0] for _ in results]

    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    failed_count = 0
    for index, result in enumerate(results):
        requested_target = requested_targets[index] if index < len(requested_targets) else ""
        result_url = _get_result_url(result, requested_target)
        item: dict[str, Any] = {
            "target": requested_target,
            "url": result_url,
            "ok": bool(getattr(result, "success", False)),
        }
        if traversal_mode == "deep":
            result_depth = getattr(result, "depth", None)
            item["depth"] = (
                result_depth
                if isinstance(result_depth, int)
                and not isinstance(result_depth, bool)
                and result_depth >= 0
                else 0
            )

        if item["ok"]:
            truncate_limit = (
                None
                if traversal_mode == "list" and len(normalized_targets) == 1
                else _get_batch_item_chars()
            )
            if extraction_schema is not None:
                extracted_content = getattr(result, "extracted_content", None)
                if not extracted_content:
                    item["ok"] = False
                    item["error"] = "No data extracted. Check options.extraction.schema selectors."
                else:
                    item["data"] = _truncate(str(extracted_content), truncate_limit)
            else:
                selected_content = _select_content(result, output_format)
                item["data"] = _truncate(selected_content, truncate_limit)

        if not item["ok"]:
            failed_count += 1
            if "error" not in item:
                item["error"] = str(getattr(result, "error_message", "Crawl failed"))
        elif normalized_capture_artifacts:
            assert normalized_session_id is not None
            artifact_store = _get_artifact_store(ctx)
            item["run"] = _capture_result_artifacts(
                artifact_store=artifact_store,
                result=result,
                capture_artifacts=normalized_capture_artifacts,
                session_id=normalized_session_id,
                requested_url=requested_target,
                artifact_ttl_seconds=session_options.artifact_ttl_seconds,
                artifact_max_per_session=session_options.artifact_max_per_session,
                artifact_max_total=session_options.artifact_max_total,
                artifact_max_total_bytes=session_options.artifact_max_total_bytes,
            )

        if include_diagnostics:
            item["diagnostics"] = _extract_result_diagnostics(
                result=result,
                requested_url=requested_target or result_url,
                dispatch_summary=dispatch_summary,
            )

        items.append(item)

    ok = failed_count == 0
    if failed_count > 0:
        total_scope = len(items)
        warning_message = f"{failed_count} of {total_scope} page(s) failed during crawl."
        warnings.append(warning_message)
        await ctx.warning(warning_message)

    envelope: dict[str, Any] = {
        "schema_version": SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION,
        "tool": "crawl",
        "ok": ok,
        "data": items[0] if len(items) == 1 else None,  # AUDIT: L-05 — deep crawl single-result returns data instead of items array
        "items": items if len(items) > 1 else None,
        "meta": {
            "target_count": len(normalized_targets),
            "option_groups": provided_option_groups,
            "output_format": output_format,
            "diagnostics": include_diagnostics,
            "session_id": normalized_session_id,
            "extraction_mode": extraction_mode if extraction_schema is not None else None,
            "traversal_mode": traversal_mode,
        },
        "warnings": warnings,
        "error": (
            None
            if ok
            else {
                "code": "CRAWL_FAILED",
                "message": items[0]["error"] if len(items) == 1 else f"{failed_count} pages failed",
            }
        ),
    }
    return _truncate(json.dumps(envelope, indent=2))  # AUDIT: H-01 — truncating serialized JSON produces invalid JSON


# ---------------------------------------------------------------------------
# Legacy (retired) — crawl_url
# ---------------------------------------------------------------------------


async def crawl_url(  # pragma: no cover - retired legacy surface  # AUDIT: L-01 — ~1200 lines of dead legacy tool code (crawl_url through execute_js)
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
    session_id: Annotated[
        str | None,
        Field(
            description=(
                "Optional session ID to reuse browser state across related requests. "
                "Must be 1-64 characters: letters, numbers, '.', '_', ':', or '-'."
            )
        ),
    ] = None,
    timeout_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawl timeout in milliseconds. "
                f"Must be between {RUNTIME_TIMEOUT_MS_MIN} and {RUNTIME_TIMEOUT_MS_MAX}."
            )
        ),
    ] = None,
    max_retries: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry count for transient crawl failures. "
                f"Must be between {RUNTIME_RETRY_COUNT_MIN} and {RUNTIME_RETRY_COUNT_MAX}."
            )
        ),
    ] = None,
    retry_backoff_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry backoff in milliseconds between attempts. "
                f"Must be between {RUNTIME_BACKOFF_MS_MIN} and {RUNTIME_BACKOFF_MS_MAX}."
            )
        ),
    ] = None,
    max_content_chars: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawler-side max extracted content length. "
                f"Must be between {RUNTIME_SIZE_BOUND_MIN} and {RUNTIME_SIZE_BOUND_MAX}."
            )
        ),
    ] = None,
    include_diagnostics: Annotated[
        bool,
        Field(
            description=(
                "Include bounded diagnostics metadata (status code, redirected URL, "
                "timing summary, and console/network counts)."
            )
        ),
    ] = False,
    capture_artifacts: Annotated[
        list[str] | None,
        Field(
            description=(
                "Optional artifact types to persist for this run. Supported values: "
                "'mhtml', 'pdf', 'console', 'network'. Requires session_id. "
                "When enabled, response includes run/artifact metadata."
            )
        ),
    ] = None,
    ctx: Context | None = None,
) -> str:
    """Crawl a single web page and extract its content.

    Use this tool when you need to read the content of a specific web page.
    Returns the page content in the requested format (markdown by default).
    For crawling multiple pages at once, use crawl_many instead. For
    recursive site crawling, use deep_crawl.
    """
    _validate_url(url)
    normalized_capture_artifacts = _normalize_capture_artifacts(capture_artifacts)
    crawler = _get_crawler(ctx)
    assert ctx is not None
    await ctx.info(f"Crawling {url}")
    normalized_session_id = await _bind_session_id(session_id=session_id, crawler=crawler, ctx=ctx)
    if normalized_capture_artifacts and normalized_session_id is None:
        raise ToolError("capture_artifacts requires a valid session_id.")

    config = _build_run_config(
        css_selector=css_selector,
        word_count_threshold=word_count_threshold,
        wait_for=wait_for,
        bypass_cache=bypass_cache,
        session_id=normalized_session_id,
    )
    runtime_controls = _validate_optional_runtime_controls(
        timeout_ms=timeout_ms,
        max_retries=max_retries,
        retry_backoff_ms=retry_backoff_ms,
        max_content_chars=max_content_chars,
    )

    result: Any = await crawler.arun(
        url=url,
        config=config,
        **runtime_controls,  # ty: ignore[invalid-argument-type]
    )

    if not result.success:
        raise ToolError(f"Crawl failed for {url}: {result.error_message}")

    run_payload: dict[str, Any] | None = None
    if normalized_capture_artifacts:
        assert normalized_session_id is not None
        artifact_store = _get_artifact_store(ctx)
        run_payload = _capture_result_artifacts(
            artifact_store=artifact_store,
            result=result,
            capture_artifacts=normalized_capture_artifacts,
            session_id=normalized_session_id,
            requested_url=url,
        )

    content = _truncate(_select_content(result, output_format))
    if not include_diagnostics and run_payload is None:
        return content

    payload = {
        "url": _get_result_url(result, url),
        "success": True,
        "content": content,
    }
    if include_diagnostics:
        payload["diagnostics"] = _extract_result_diagnostics(result=result, requested_url=url)
    if run_payload is not None:
        payload["run"] = run_payload
    return json.dumps(payload, indent=2)


def _build_crawl_many_dispatcher(
    *,
    batch_size: int,
    max_concurrency: int | None = None,
    rate_limit_base_delay: float | None = None,
    rate_limit_max_delay: float | None = None,
    rate_limit_max_retries: int | None = None,
) -> SemaphoreDispatcher:
    """Build a bounded dispatcher for ``crawl_many`` requests."""
    if (
        rate_limit_max_retries is not None
        and rate_limit_base_delay is None
        and rate_limit_max_delay is None
    ):
        raise ToolError(
            "rate_limit_max_retries requires rate_limit_base_delay or rate_limit_max_delay."
        )
    hard_max_concurrency = _get_crawl_many_hard_max_concurrency()
    bounded_batch_size = max(1, min(batch_size, hard_max_concurrency))
    requested_concurrency = (
        _get_crawl_many_default_max_concurrency() if max_concurrency is None else max_concurrency
    )
    bounded_concurrency = max(1, min(requested_concurrency, bounded_batch_size))

    rate_limiter: RateLimiter | None = None
    if rate_limit_base_delay is not None or rate_limit_max_delay is not None:
        base_delay = (
            _get_crawl_many_default_rate_limit_base_delay()
            if rate_limit_base_delay is None
            else rate_limit_base_delay
        )
        max_delay = (
            _get_crawl_many_default_rate_limit_max_delay()
            if rate_limit_max_delay is None
            else rate_limit_max_delay
        )
        max_retries = (
            _get_crawl_many_default_rate_limit_max_retries()
            if rate_limit_max_retries is None
            else rate_limit_max_retries
        )
        if max_delay < base_delay:
            raise ToolError(
                "rate_limit_max_delay must be greater than or equal to rate_limit_base_delay."
            )

        rate_limiter = RateLimiter(
            base_delay=(base_delay, max_delay),
            max_delay=max_delay,
            max_retries=max_retries,
        )

    return SemaphoreDispatcher(
        semaphore_count=bounded_concurrency,
        max_session_permit=bounded_batch_size,
        rate_limiter=rate_limiter,
    )


# ---------------------------------------------------------------------------
# Legacy (retired) — crawl_many
# ---------------------------------------------------------------------------


async def crawl_many(  # pragma: no cover - retired legacy surface
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
    max_concurrency: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawl concurrency cap. Automatically bounded by URL batch size "
                f"and hard limit ({CRAWL_MANY_HARD_MAX_CONCURRENCY})."
            ),
            ge=1,
            le=CRAWL_MANY_HARD_MAX_CONCURRENCY,
        ),
    ] = None,
    rate_limit_base_delay: Annotated[
        float | None,
        Field(
            description=(
                "Optional minimum rate-limit delay in seconds for retries. "
                "Enable with rate_limit_base_delay and/or rate_limit_max_delay."
            ),
            ge=CRAWL_MANY_RATE_DELAY_MIN,
            le=CRAWL_MANY_RATE_DELAY_MAX,
        ),
    ] = None,
    rate_limit_max_delay: Annotated[
        float | None,
        Field(
            description="Optional maximum rate-limit delay in seconds for retries.",
            ge=CRAWL_MANY_RATE_DELAY_MIN,
            le=CRAWL_MANY_RATE_DELAY_MAX,
        ),
    ] = None,
    rate_limit_max_retries: Annotated[
        int | None,
        Field(
            description="Rate-limit retry count when rate limiting is enabled.",
            ge=CRAWL_MANY_RATE_RETRIES_MIN,
            le=CRAWL_MANY_RATE_RETRIES_MAX,
        ),
    ] = None,
    dispatcher: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Optional dispatcher config object. Supports: max_concurrency, "
                "rate_limit_base_delay, rate_limit_max_delay, rate_limit_max_retries, "
                "or nested rate_limit with base_delay/max_delay/max_retries."
            )
        ),
    ] = None,
    timeout_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawl timeout in milliseconds. "
                f"Must be between {RUNTIME_TIMEOUT_MS_MIN} and {RUNTIME_TIMEOUT_MS_MAX}."
            )
        ),
    ] = None,
    max_retries: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry count for transient crawl failures. "
                f"Must be between {RUNTIME_RETRY_COUNT_MIN} and {RUNTIME_RETRY_COUNT_MAX}."
            )
        ),
    ] = None,
    retry_backoff_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry backoff in milliseconds between attempts. "
                f"Must be between {RUNTIME_BACKOFF_MS_MIN} and {RUNTIME_BACKOFF_MS_MAX}."
            )
        ),
    ] = None,
    max_content_chars: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawler-side max extracted content length. "
                f"Must be between {RUNTIME_SIZE_BOUND_MIN} and {RUNTIME_SIZE_BOUND_MAX}."
            )
        ),
    ] = None,
    include_diagnostics: Annotated[
        bool,
        Field(
            description=(
                "Include bounded diagnostics metadata (status code, redirected URL, timing "
                "summary, and console/network counts) per URL."
            )
        ),
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
    runtime_controls = _validate_optional_runtime_controls(
        timeout_ms=timeout_ms,
        max_retries=max_retries,
        retry_backoff_ms=retry_backoff_ms,
        max_content_chars=max_content_chars,
    )

    dispatcher_config: dict[str, Any] = {}
    if dispatcher is not None:
        if not isinstance(dispatcher, dict):
            _raise_runtime_validation_error("dispatcher", dispatcher, "an object")
        dispatcher_config = dispatcher

    nested_rate_limit = dispatcher_config.get("rate_limit")
    if nested_rate_limit is not None and not isinstance(nested_rate_limit, dict):
        _raise_runtime_validation_error("dispatcher.rate_limit", nested_rate_limit, "an object")

    nested_rate_limit_base_delay = (
        nested_rate_limit.get("base_delay") if isinstance(nested_rate_limit, dict) else None
    )
    nested_rate_limit_max_delay = (
        nested_rate_limit.get("max_delay") if isinstance(nested_rate_limit, dict) else None
    )
    nested_rate_limit_max_retries = (
        nested_rate_limit.get("max_retries") if isinstance(nested_rate_limit, dict) else None
    )

    requested_max_concurrency = (
        max_concurrency if max_concurrency is not None else dispatcher_config.get("max_concurrency")
    )
    requested_rate_limit_base_delay = (
        rate_limit_base_delay
        if rate_limit_base_delay is not None
        else dispatcher_config.get("rate_limit_base_delay", nested_rate_limit_base_delay)
    )
    requested_rate_limit_max_delay = (
        rate_limit_max_delay
        if rate_limit_max_delay is not None
        else dispatcher_config.get("rate_limit_max_delay", nested_rate_limit_max_delay)
    )
    requested_rate_limit_max_retries = (
        rate_limit_max_retries
        if rate_limit_max_retries is not None
        else dispatcher_config.get("rate_limit_max_retries", nested_rate_limit_max_retries)
    )

    hard_max_concurrency = _get_crawl_many_hard_max_concurrency()
    validated_max_concurrency = _validate_optional_size_bound(
        requested_max_concurrency,
        param_name="max_concurrency",
        minimum=1,
        maximum=hard_max_concurrency,
    )
    validated_rate_limit_base_delay = _validate_optional_numeric_range(
        requested_rate_limit_base_delay,
        param_name="rate_limit_base_delay",
        minimum=CRAWL_MANY_RATE_DELAY_MIN,
        maximum=CRAWL_MANY_RATE_DELAY_MAX,
    )
    validated_rate_limit_max_delay = _validate_optional_numeric_range(
        requested_rate_limit_max_delay,
        param_name="rate_limit_max_delay",
        minimum=CRAWL_MANY_RATE_DELAY_MIN,
        maximum=CRAWL_MANY_RATE_DELAY_MAX,
    )
    validated_rate_limit_max_retries = _validate_optional_size_bound(
        requested_rate_limit_max_retries,
        param_name="rate_limit_max_retries",
        minimum=CRAWL_MANY_RATE_RETRIES_MIN,
        maximum=CRAWL_MANY_RATE_RETRIES_MAX,
    )

    dispatcher_instance = _build_crawl_many_dispatcher(
        batch_size=len(urls),
        max_concurrency=validated_max_concurrency,
        rate_limit_base_delay=validated_rate_limit_base_delay,
        rate_limit_max_delay=validated_rate_limit_max_delay,
        rate_limit_max_retries=validated_rate_limit_max_retries,
    )

    results: Any = await crawler.arun_many(
        urls=urls,
        config=config,
        dispatcher=dispatcher_instance,
        **runtime_controls,
    )

    # T08 — Progress reporting
    try:
        await ctx.report_progress(len(results), len(urls))  # ty: ignore[invalid-argument-type]
    except AttributeError:
        pass

    output = []
    dispatch_summary = _build_dispatch_summary(dispatcher_instance) if include_diagnostics else None
    for i, r in enumerate(cast(Any, results)):
        requested_url = urls[i] if i < len(urls) else ""
        result_url = _get_result_url(r, requested_url)
        if r.success:
            content = _select_content(r, output_format)
            item: dict[str, Any] = {
                "url": result_url,
                "success": True,
                "content": _truncate(content, _get_batch_item_chars()),
            }
        else:
            item = {
                "url": result_url,
                "success": False,
                "error": r.error_message,  # AUDIT: L-09 — unguarded access; error_message may be None
            }

        if include_diagnostics:
            item["diagnostics"] = _extract_result_diagnostics(
                result=r,
                requested_url=requested_url or result_url,
                dispatch_summary=dispatch_summary,
            )

        output.append(item)

    # T11 — Warn on partial failures
    failed_count = sum(1 for item in output if not item["success"])
    if failed_count > 0:
        await ctx.warning(f"{failed_count} of {len(urls)} URLs failed to crawl")

    await ctx.info(f"Completed {len(output)} crawls")
    return json.dumps(output, indent=2)


def _validate_deep_crawl_url_filter_patterns(  # AUDIT: M-03 — no upper bound on pattern list length
    raw_patterns: Any,
    *,
    param_name: str,
) -> list[str]:
    """Validate deep crawl URL filter patterns and return cleaned values."""
    if not isinstance(raw_patterns, list):
        _raise_runtime_validation_error(param_name, raw_patterns, "a list of string patterns")

    validated_patterns: list[str] = []
    for index, pattern in enumerate(raw_patterns):
        item_param_name = f"{param_name}[{index}]"
        if not isinstance(pattern, str):
            _raise_runtime_validation_error(item_param_name, pattern, "a non-empty string pattern")
        normalized_pattern = pattern.strip()
        if not normalized_pattern:
            _raise_runtime_validation_error(item_param_name, pattern, "a non-empty string pattern")
        if len(normalized_pattern) > DEEP_CRAWL_FILTER_PATTERN_MAX_CHARS:
            _raise_runtime_validation_error(
                item_param_name,
                pattern,
                f"a pattern up to {DEEP_CRAWL_FILTER_PATTERN_MAX_CHARS} characters",
            )
        if any(ord(char) < 32 for char in normalized_pattern):
            _raise_runtime_validation_error(item_param_name, pattern, "a printable string pattern")
        validated_patterns.append(normalized_pattern)

    return validated_patterns


def _build_deep_crawl_strategy(
    *,
    crawl_mode: str,
    max_depth: int,
    max_pages: int,
    include_external: bool,
    url_filters: dict[str, Any] | None = None,
) -> Any:
    """Build a deep crawl strategy with optional traversal mode and URL filters."""
    if not isinstance(crawl_mode, str):
        _raise_runtime_validation_error("crawl_mode", crawl_mode, "one of ['bfs', 'dfs']")

    normalized_mode = crawl_mode.strip().lower()
    strategy_cls = {
        "bfs": BFSDeepCrawlStrategy,
        "dfs": DFSDeepCrawlStrategy,
    }.get(normalized_mode)
    if strategy_cls is None:
        _raise_runtime_validation_error("crawl_mode", crawl_mode, "one of ['bfs', 'dfs']")

    include_patterns: list[str] = []
    exclude_patterns: list[str] = []
    if url_filters is not None:
        if not isinstance(url_filters, dict):
            _raise_runtime_validation_error(
                "url_filters",
                url_filters,
                "an object with optional 'include' and 'exclude' keys",
            )

        unknown_keys = sorted(set(url_filters) - {"include", "exclude"})
        if unknown_keys:
            _raise_runtime_validation_error(
                "url_filters",
                url_filters,
                "an object with optional 'include' and 'exclude' keys",
            )

        if "include" in url_filters:
            include_patterns = _validate_deep_crawl_url_filter_patterns(
                url_filters["include"],
                param_name="url_filters.include",
            )
        if "exclude" in url_filters:
            exclude_patterns = _validate_deep_crawl_url_filter_patterns(
                url_filters["exclude"],
                param_name="url_filters.exclude",
            )

    filter_chain: FilterChain | None = None
    if include_patterns or exclude_patterns:
        try:
            filter_chain = FilterChain(
                filters=[
                    *([URLPatternFilter(cast(Any, include_patterns))] if include_patterns else []),
                    *(
                        [URLPatternFilter(cast(Any, exclude_patterns), reverse=True)]
                        if exclude_patterns
                        else []
                    ),
                ]
            )
        except re.error as e:
            raise ToolError(f"Invalid url_filters pattern: {e}") from e

    strategy_kwargs: dict[str, Any] = {
        "max_depth": max_depth,
        "max_pages": max_pages,
        "include_external": include_external,
    }
    if filter_chain is not None:
        strategy_kwargs["filter_chain"] = filter_chain

    return strategy_cls(**strategy_kwargs)


# ---------------------------------------------------------------------------
# Legacy (retired) — deep_crawl
# ---------------------------------------------------------------------------


async def deep_crawl(  # pragma: no cover - retired legacy surface
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
    crawl_mode: Annotated[
        str,
        Field(description="Traversal strategy: 'bfs' (default) or 'dfs'."),
    ] = "bfs",
    url_filters: Annotated[
        Any | None,
        Field(
            description=(
                "Optional frontier URL filters with include/exclude pattern lists. "
                "Example: {'include': ['*/docs/*'], 'exclude': ['*/archive/*']}."
            )
        ),
    ] = None,
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
    timeout_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawl timeout in milliseconds. "
                f"Must be between {RUNTIME_TIMEOUT_MS_MIN} and {RUNTIME_TIMEOUT_MS_MAX}."
            )
        ),
    ] = None,
    max_retries: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry count for transient crawl failures. "
                f"Must be between {RUNTIME_RETRY_COUNT_MIN} and {RUNTIME_RETRY_COUNT_MAX}."
            )
        ),
    ] = None,
    retry_backoff_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry backoff in milliseconds between attempts. "
                f"Must be between {RUNTIME_BACKOFF_MS_MIN} and {RUNTIME_BACKOFF_MS_MAX}."
            )
        ),
    ] = None,
    max_content_chars: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawler-side max extracted content length. "
                f"Must be between {RUNTIME_SIZE_BOUND_MIN} and {RUNTIME_SIZE_BOUND_MAX}."
            )
        ),
    ] = None,
    ctx: Context | None = None,
) -> str:
    """Perform a deep crawl starting from a seed URL.

    Discovers and follows links on each page up to *max_depth* levels while
    collecting up to *max_pages* total pages. Supports BFS (default) and DFS
    traversal plus optional include/exclude frontier URL patterns. Returns a
    JSON object with the seed URL, total pages crawled, and per-page results.
    """
    _validate_url(url)
    crawler = _get_crawler(ctx)
    assert ctx is not None
    await ctx.info(f"Deep crawling {url} (depth={max_depth}, max_pages={max_pages})")

    config = _build_run_config(
        css_selector=css_selector,
        word_count_threshold=word_count_threshold,
        bypass_cache=bypass_cache,
        deep_crawl_strategy=_build_deep_crawl_strategy(
            crawl_mode=crawl_mode,
            max_depth=max_depth,
            max_pages=max_pages,
            include_external=include_external,
            url_filters=url_filters,
        ),
        verbose=False,
    )
    runtime_controls = _validate_optional_runtime_controls(
        timeout_ms=timeout_ms,
        max_retries=max_retries,
        retry_backoff_ms=retry_backoff_ms,
        max_content_chars=max_content_chars,
    )

    results: Any = await crawler.arun(
        url=url,
        config=config,
        **runtime_controls,  # ty: ignore[invalid-argument-type]
    )

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
                    "content": _truncate(content, _get_batch_item_chars()),
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
# Legacy (retired) — extract_data
# ---------------------------------------------------------------------------


async def extract_data(  # pragma: no cover - retired legacy surface
    url: Annotated[
        str,
        Field(description="The URL to extract structured data from."),
    ],
    schema: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Extraction schema with 'name', 'baseSelector', and 'fields' array. "
                "Each field has 'name', 'selector', 'type' ('text' or 'attribute'), "
                "and optional 'attribute'."
            ),
        ),
    ],
    extraction_mode: Annotated[
        str,
        Field(description="Extraction mode: 'css' (default) or 'xpath'."),
    ] = "css",
    wait_for: Annotated[
        str | None,
        Field(description="CSS selector or JS expression to wait for before extraction."),
    ] = None,
    session_id: Annotated[
        str | None,
        Field(
            description=(
                "Optional session ID to reuse browser state across related requests. "
                "Must be 1-64 characters: letters, numbers, '.', '_', ':', or '-'."
            )
        ),
    ] = None,
    timeout_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawl timeout in milliseconds. "
                f"Must be between {RUNTIME_TIMEOUT_MS_MIN} and {RUNTIME_TIMEOUT_MS_MAX}."
            )
        ),
    ] = None,
    max_retries: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry count for transient crawl failures. "
                f"Must be between {RUNTIME_RETRY_COUNT_MIN} and {RUNTIME_RETRY_COUNT_MAX}."
            )
        ),
    ] = None,
    retry_backoff_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry backoff in milliseconds between attempts. "
                f"Must be between {RUNTIME_BACKOFF_MS_MIN} and {RUNTIME_BACKOFF_MS_MAX}."
            )
        ),
    ] = None,
    max_content_chars: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawler-side max extracted content length. "
                f"Must be between {RUNTIME_SIZE_BOUND_MIN} and {RUNTIME_SIZE_BOUND_MAX}."
            )
        ),
    ] = None,
    ctx: Context | None = None,
) -> str:
    """Extract structured data from a page using CSS or XPath selectors.

    Provide a schema defining the base selector for repeating items and
    the fields to extract. Returns the extracted data as a JSON array.
    Use this when you need tabular or list-like data from a page rather
    than raw text content. The default extraction mode is CSS.
    """
    _validate_url(url)
    crawler = _get_crawler(ctx)
    assert ctx is not None
    await ctx.info(f"Extracting structured data from {url}")
    normalized_session_id = await _bind_session_id(session_id=session_id, crawler=crawler, ctx=ctx)

    config = CrawlerRunConfig(
        extraction_strategy=_build_extraction_strategy(schema, extraction_mode),
        wait_for=wait_for,  # ty: ignore[invalid-argument-type]
        cache_mode=CacheMode.BYPASS,
        session_id=cast(Any, normalized_session_id),
    )
    runtime_controls = _validate_optional_runtime_controls(
        timeout_ms=timeout_ms,
        max_retries=max_retries,
        retry_backoff_ms=retry_backoff_ms,
        max_content_chars=max_content_chars,
    )

    result: Any = await crawler.arun(
        url=url,
        config=config,
        **runtime_controls,  # ty: ignore[invalid-argument-type]
    )

    if not result.success:
        raise ToolError(f"Extraction failed for {url}: {result.error_message}")

    if not result.extracted_content:
        raise ToolError(f"No data extracted from {url}. Check your schema selectors.")

    return _truncate(result.extracted_content)


# ---------------------------------------------------------------------------
# Legacy (retired) — take_screenshot
# ---------------------------------------------------------------------------


async def take_screenshot(  # pragma: no cover - retired legacy surface
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
    timeout_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawl timeout in milliseconds. "
                f"Must be between {RUNTIME_TIMEOUT_MS_MIN} and {RUNTIME_TIMEOUT_MS_MAX}."
            )
        ),
    ] = None,
    max_retries: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry count for transient crawl failures. "
                f"Must be between {RUNTIME_RETRY_COUNT_MIN} and {RUNTIME_RETRY_COUNT_MAX}."
            )
        ),
    ] = None,
    retry_backoff_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry backoff in milliseconds between attempts. "
                f"Must be between {RUNTIME_BACKOFF_MS_MIN} and {RUNTIME_BACKOFF_MS_MAX}."
            )
        ),
    ] = None,
    max_content_chars: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawler-side max extracted content length. "
                f"Must be between {RUNTIME_SIZE_BOUND_MIN} and {RUNTIME_SIZE_BOUND_MAX}."
            )
        ),
    ] = None,
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
    # future use but CrawlerRunConfig does not yet support them directly.  # AUDIT: L-08 — viewport params accepted but unused
    config = CrawlerRunConfig(
        screenshot=True,
        wait_for=wait_for,  # ty: ignore[invalid-argument-type]
        cache_mode=CacheMode.BYPASS,
    )
    runtime_controls = _validate_optional_runtime_controls(
        timeout_ms=timeout_ms,
        max_retries=max_retries,
        retry_backoff_ms=retry_backoff_ms,
        max_content_chars=max_content_chars,
    )

    result: Any = await crawler.arun(
        url=url,
        config=config,
        **runtime_controls,  # ty: ignore[invalid-argument-type]
    )

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
# Legacy (retired) — get_links
# ---------------------------------------------------------------------------


async def get_links(  # pragma: no cover - retired legacy surface
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
# Legacy (retired) — get_page_info
# ---------------------------------------------------------------------------


async def get_page_info(  # pragma: no cover - retired legacy surface
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
# Legacy (retired) — execute_js
# ---------------------------------------------------------------------------


async def execute_js(  # pragma: no cover - retired legacy surface
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
    session_id: Annotated[
        str | None,
        Field(
            description=(
                "Optional session ID to reuse browser state across related requests. "
                "Must be 1-64 characters: letters, numbers, '.', '_', ':', or '-'."
            )
        ),
    ] = None,
    timeout_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawl timeout in milliseconds. "
                f"Must be between {RUNTIME_TIMEOUT_MS_MIN} and {RUNTIME_TIMEOUT_MS_MAX}."
            )
        ),
    ] = None,
    max_retries: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry count for transient crawl failures. "
                f"Must be between {RUNTIME_RETRY_COUNT_MIN} and {RUNTIME_RETRY_COUNT_MAX}."
            )
        ),
    ] = None,
    retry_backoff_ms: Annotated[
        int | None,
        Field(
            description=(
                "Optional retry backoff in milliseconds between attempts. "
                f"Must be between {RUNTIME_BACKOFF_MS_MIN} and {RUNTIME_BACKOFF_MS_MAX}."
            )
        ),
    ] = None,
    max_content_chars: Annotated[
        int | None,
        Field(
            description=(
                "Optional crawler-side max extracted content length. "
                f"Must be between {RUNTIME_SIZE_BOUND_MIN} and {RUNTIME_SIZE_BOUND_MAX}."
            )
        ),
    ] = None,
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
    normalized_session_id = await _bind_session_id(session_id=session_id, crawler=crawler, ctx=ctx)

    config = CrawlerRunConfig(
        js_code=[js_code],
        wait_for=wait_for,  # ty: ignore[invalid-argument-type]
        cache_mode=CacheMode.BYPASS,
        session_id=cast(Any, normalized_session_id),
    )
    runtime_controls = _validate_optional_runtime_controls(
        timeout_ms=timeout_ms,
        max_retries=max_retries,
        retry_backoff_ms=retry_backoff_ms,
        max_content_chars=max_content_chars,
    )

    result: Any = await crawler.arun(
        url=url,
        config=config,
        **runtime_controls,  # ty: ignore[invalid-argument-type]
    )

    if not result.success:
        raise ToolError(f"JS execution failed for {url}: {result.error_message}")

    return _truncate(_select_content(result, output_format))


# ---------------------------------------------------------------------------
# Tool 9 — close_session
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Close Session",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def close_session(
    session_id: Annotated[
        str,
        Field(
            description=(
                "Session ID to close and remove from server session tracking. "
                "Must match the format accepted by session-aware crawl tools."
            )
        ),
    ],
    ctx: Context | None = None,
) -> str:
    """Close a stateful crawl session and release associated browser resources.

    Use this tool when you are done with a workflow that used session-aware
    crawling calls. It is safe to call repeatedly; if the session is already
    gone, the tool returns closed=false. This tool only affects the named
    session and does not impact other active sessions.
    """
    crawler = _get_crawler(ctx)
    assert ctx is not None  # AUDIT: M-01 — bare assert stripped under -O
    normalized_session_id = _normalize_session_id(session_id)
    assert normalized_session_id is not None  # AUDIT: M-01 — bare assert stripped under -O
    session_registry = _get_session_registry(ctx)
    artifact_store = _get_artifact_store(ctx)

    was_active = normalized_session_id in session_registry
    session_registry.pop(normalized_session_id, None)
    _purge_session_artifacts(artifact_store=artifact_store, session_id=normalized_session_id)
    await _close_crawler_session(crawler, normalized_session_id, raise_on_error=False)
    await ctx.info(f"Closed session {normalized_session_id}")

    return json.dumps(
        {
            "session_id": normalized_session_id,
            "closed": was_active,
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Tool 10 — get_artifact
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations={
        "title": "Get Artifact",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def get_artifact(
    session_id: Annotated[
        str,
        Field(
            description=(
                "Session ID that owns the artifact. Must match the session_id used "
                "when capture_artifacts was enabled on scrape or crawl."
            )
        ),
    ],
    artifact_id: Annotated[
        str,
        Field(
            description=(
                "Artifact identifier returned by scrape/crawl run metadata when "
                "capture_artifacts was enabled."
            )
        ),
    ],
    include_content: Annotated[
        bool,
        Field(
            description=(
                "Return artifact content in addition to metadata. Defaults to false "
                "to avoid large payloads."
            )
        ),
    ] = False,
    ctx: Context | None = None,
) -> str:
    """Retrieve metadata or content for a previously captured artifact.

    Use this tool after calling scrape or crawl with capture_artifacts enabled and a
    session_id. The tool validates session ownership and applies retention
    cleanup before resolving the artifact. By default only metadata is returned;
    set include_content=true to fetch bounded artifact content.
    """
    assert ctx is not None  # AUDIT: M-01 — bare assert stripped under -O
    normalized_session_id = _normalize_session_id(session_id)
    assert normalized_session_id is not None  # AUDIT: M-01 — bare assert stripped under -O
    normalized_artifact_id = _normalize_artifact_id(artifact_id)
    artifact_store = _get_artifact_store(ctx)
    _enforce_artifact_retention(
        artifact_store=artifact_store,
        now=time.time(),
        session_id=normalized_session_id,
    )

    artifacts = artifact_store.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ToolError("Artifact store not available — server not fully initialized.")
    artifact = artifacts.get(normalized_artifact_id)
    if not isinstance(artifact, dict) or artifact.get("session_id") != normalized_session_id:
        raise ToolError("Artifact not found or expired.")

    artifact_payload = _artifact_metadata_payload(artifact)
    if include_content:
        artifact_payload["content"] = _truncate(str(artifact.get("content", "")))
    return json.dumps({"artifact": artifact_payload}, indent=2)


# ---------------------------------------------------------------------------
# T14 — Dynamic tool name list (defined after all tools)
# ---------------------------------------------------------------------------

_TOOL_NAMES = [
    "scrape",
    "crawl",
    "close_session",
    "get_artifact",
]

# ---------------------------------------------------------------------------
# Resource 1 — server config
# ---------------------------------------------------------------------------


@mcp.resource("config://server", mime_type="application/json")
def get_server_config() -> str:
    """Current server configuration and capabilities."""  # AUDIT: L-04 — exposes internal settings details (limits, retention, capabilities)
    settings = _load_settings()
    return json.dumps(
        {
            "name": "crawl4ai",
            "version": __version__,
            "tools": _TOOL_NAMES,
            "max_response_chars": _get_max_response_chars(),
            "browser_config": {
                "headless": _get_browser_headless(),
                "browser_type": _get_browser_type(),
            },
            "settings": {
                "defaults": settings.defaults.model_dump(exclude_none=True),
                "limits": settings.limits.model_dump(exclude_none=True),
                "policies": settings.policies.model_dump(exclude_none=True),
                "capabilities": settings.capabilities.model_dump(exclude_none=True),
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

    Generates a prompt that instructs the LLM to use scrape to fetch
    the page and then summarize it with the specified focus.
    """
    return [
        Message(
            role="user",
            content=(f"Use the scrape tool with targets set to {url}, then summarize its {focus}."),
        )
    ]


@mcp.prompt
def build_extraction_schema(
    url: str,
    data_type: str,
) -> list[Message]:
    """Build a CSS extraction schema for use with scrape.

    Instructs the LLM to inspect the page structure and craft a schema
    for scrape options.extraction.schema to extract the specified data type.
    """
    return [
        Message(
            role="user",
            content=(
                f"Use scrape on {url} to inspect page structure, then craft a JSON CSS "
                f"schema for options.extraction.schema that extracts {data_type}. "
                "Show the schema and an example scrape call using it."
            ),
        )
    ]


@mcp.prompt
def compare_pages(  # AUDIT: L-03 — prompt URLs not validated; potential prompt injection vector
    url1: str,
    url2: str,
) -> list[Message]:
    """Crawl two pages and compare their content.

    Instructs the LLM to fetch both pages with scrape and produce
    a structured comparison highlighting key differences.
    """
    return [
        Message(
            role="user",
            content=(
                f"Use scrape with targets [{url1}, {url2}] to fetch both pages, then "
                "compare their content and highlight the key differences."
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
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Install Playwright browsers and exit.",
    )
    args = parser.parse_args()

    if args.setup:
        result = subprocess.run(
            ["crawl4ai-setup"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("Browser setup complete.")  # noqa: T201 — OK for CLI mode, not MCP
        else:
            print(f"Setup failed: {result.stderr}", file=sys.stderr)  # noqa: T201
        sys.exit(result.returncode)

    if args.transport == "http":
        if not _is_loopback_bind_host(args.host):
            print(  # noqa: T201 — CLI safety warning for public HTTP bind
                "WARNING: HTTP transport is bound to a non-loopback host. "
                "Run behind a reverse proxy with TLS, authentication, and rate limits.",
                file=sys.stderr,
            )
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
