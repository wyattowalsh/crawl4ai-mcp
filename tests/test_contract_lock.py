"""Contract lock tests for the scrape/crawl migration surface."""

from crawl4ai_mcp import (
    SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION,
    SCRAPE_CRAWL_ENVELOPE_FIELDS,
    SCRAPE_CRAWL_MIGRATION_MAP,
    SCRAPE_CRAWL_OPTION_GROUPS,
)


def test_scrape_crawl_envelope_lock_shape() -> None:
    assert SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION == "scrape-crawl.v1"
    assert SCRAPE_CRAWL_ENVELOPE_FIELDS == (
        "ok",
        "operation",
        "data",
        "error",
        "diagnostics",
        "session",
        "meta",
    )


def test_scrape_crawl_option_group_lock() -> None:
    assert tuple(SCRAPE_CRAWL_OPTION_GROUPS) == (
        "extraction",
        "transformation",
        "conversion",
        "runtime",
        "diagnostics",
        "session",
    )


def test_scrape_crawl_migration_map_lock() -> None:
    assert SCRAPE_CRAWL_MIGRATION_MAP["crawl_url"] == "scrape"
    assert SCRAPE_CRAWL_MIGRATION_MAP["crawl_many"] == "crawl"
    assert SCRAPE_CRAWL_MIGRATION_MAP["deep_crawl"] == "crawl"
    assert SCRAPE_CRAWL_MIGRATION_MAP["close_session"] == "session.close"
    assert SCRAPE_CRAWL_MIGRATION_MAP["get_artifact"] == "session.artifact.get"
