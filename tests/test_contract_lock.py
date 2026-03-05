"""Contract lock tests for the scrape/crawl surface."""

import importlib
import importlib.metadata
from unittest.mock import Mock

import mcp_crawl4ai
from mcp_crawl4ai import (
    SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION,
    SCRAPE_CRAWL_ENVELOPE_FIELDS,
    SCRAPE_CRAWL_MIGRATION_MAP,
    SCRAPE_CRAWL_OPTION_GROUPS,
    ScrapeCrawlEnvelopeMeta,
)

RETIRED_LEGACY_TOOLS = (
    "crawl_url",
    "crawl_many",
    "deep_crawl",
    "extract_data",
    "take_screenshot",
    "get_links",
    "get_page_info",
    "execute_js",
)


def test_scrape_crawl_envelope_lock_shape() -> None:
    assert SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION == "scrape-crawl.v1"
    assert SCRAPE_CRAWL_ENVELOPE_FIELDS == (
        "schema_version",
        "tool",
        "ok",
        "data",
        "items",
        "meta",
        "warnings",
        "error",
    )


def test_scrape_crawl_option_group_lock() -> None:
    assert tuple(SCRAPE_CRAWL_OPTION_GROUPS) == (
        "extraction",
        "transformation",
        "conversion",
        "runtime",
        "diagnostics",
        "session",
        "render",
        "traversal",
    )
    assert "timeout_ms" in SCRAPE_CRAWL_OPTION_GROUPS["runtime"]
    assert "viewport_width" in SCRAPE_CRAWL_OPTION_GROUPS["render"]
    assert "mode" in SCRAPE_CRAWL_OPTION_GROUPS["traversal"]
    assert "crawl_mode" in SCRAPE_CRAWL_OPTION_GROUPS["traversal"]


def test_scrape_crawl_migration_map_lock() -> None:
    assert SCRAPE_CRAWL_MIGRATION_MAP["scrape"] == "scrape"
    assert SCRAPE_CRAWL_MIGRATION_MAP["crawl"] == "crawl"
    assert SCRAPE_CRAWL_MIGRATION_MAP["close_session"] == "session.close"
    assert SCRAPE_CRAWL_MIGRATION_MAP["get_artifact"] == "session.artifact.get"
    assert sorted(SCRAPE_CRAWL_MIGRATION_MAP) == [
        "close_session",
        "crawl",
        "get_artifact",
        "scrape",
    ]


def test_retired_legacy_tools_absent_from_migration_map() -> None:
    assert all(tool not in SCRAPE_CRAWL_MIGRATION_MAP for tool in RETIRED_LEGACY_TOOLS)


def test_scrape_crawl_meta_typed_contract_lock() -> None:
    assert "traversal_mode" in ScrapeCrawlEnvelopeMeta.__annotations__


def test_init_version_resolution_uses_metadata_lookup(monkeypatch) -> None:
    lookup = Mock(return_value="9.9.9")
    monkeypatch.setattr(importlib.metadata, "version", lookup)

    reloaded = importlib.reload(mcp_crawl4ai)

    assert reloaded.__version__ == "9.9.9"
    lookup.assert_called_once_with("mcp-crawl4ai")


def test_init_version_resolution_falls_back_when_package_missing(monkeypatch) -> None:
    def _raise_not_found(_: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    lookup = Mock(side_effect=_raise_not_found)
    monkeypatch.setattr(importlib.metadata, "version", lookup)

    reloaded = importlib.reload(mcp_crawl4ai)

    assert reloaded.__version__ == "0.0.0"
    lookup.assert_called_once_with("mcp-crawl4ai")
