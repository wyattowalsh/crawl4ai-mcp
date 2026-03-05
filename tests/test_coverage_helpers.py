"""Targeted helper coverage tests for production guardrails and utilities."""

from __future__ import annotations

import json
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from mcp_crawl4ai.server import (
    ARTIFACT_CAPTURE_TEXT_MAX_CHARS,
    DEEP_CRAWL_FILTER_PATTERN_MAX_CHARS,
    ServerSettings,
    _bind_session_id,
    _build_deep_crawl_strategy,
    _capture_artifact_payload,
    _capture_result_artifacts,
    _cleanup_expired_sessions,
    _close_crawler_session,
    _enforce_artifact_retention,
    _extract_markdown,
    _extract_timing_summary,
    _get_artifact_store,
    _get_session_registry,
    _get_settings,
    _is_loopback_bind_host,
    _normalize_artifact_id,
    _normalize_capture_artifacts,
    _normalize_extraction_mode,
    _normalize_scrape_targets,
    _normalize_session_id,
    _prune_expired_artifacts,
    _purge_session_artifacts,
    _remove_artifact_entry,
    _safe_diagnostic_count,
    _sanitize_diagnostic_url,
    _validate_deep_crawl_url_filter_patterns,
    get_artifact,
)


def _artifact_store() -> dict[str, object]:
    return {
        "artifacts": {},
        "runs": {},
        "artifact_order": [],
        "session_artifacts": {},
        "session_runs": {},
        "total_bytes": 0,
        "next_artifact_index": 0,
        "next_run_index": 0,
    }


@pytest.mark.unit
def test_get_settings_prefers_context_and_loopback_variants() -> None:
    settings = ServerSettings()
    ctx = types.SimpleNamespace(lifespan_context={"settings": settings})
    assert _get_settings(ctx) is settings

    assert _is_loopback_bind_host("localhost")
    assert _is_loopback_bind_host("127.0.0.1")
    assert not _is_loopback_bind_host("0.0.0.0")
    assert not _is_loopback_bind_host("example.com")


@pytest.mark.unit
def test_registry_and_artifact_store_guards() -> None:
    with pytest.raises(ToolError, match="Session registry not available"):
        _get_session_registry(None)
    with pytest.raises(ToolError, match="Session registry not available"):
        _get_session_registry(types.SimpleNamespace(lifespan_context={}))

    with pytest.raises(ToolError, match="Artifact store not available"):
        _get_artifact_store(None)
    with pytest.raises(ToolError, match="Artifact store not available"):
        _get_artifact_store(types.SimpleNamespace(lifespan_context={}))


@pytest.mark.unit
def test_normalizers_validation_paths() -> None:
    with pytest.raises(ToolError, match="Invalid artifact_id"):
        _normalize_artifact_id("bad id")
    with pytest.raises(ToolError, match="Invalid artifact_id"):
        _normalize_artifact_id(123)  # ty: ignore[arg-type]
    assert _normalize_artifact_id("artifact-00000001") == "artifact-00000001"

    with pytest.raises(ToolError, match="Invalid capture_artifacts"):
        _normalize_capture_artifacts("pdf")  # ty: ignore[arg-type]
    with pytest.raises(ToolError, match="Invalid capture_artifacts"):
        _normalize_capture_artifacts(["pdf", "mhtml", "console", "network", "extra"])
    with pytest.raises(ToolError, match="Invalid capture_artifacts\\[0\\]"):
        _normalize_capture_artifacts(["unknown"])
    assert _normalize_capture_artifacts(["PDF", "console", "pdf"]) == ["pdf", "console"]

    with pytest.raises(ToolError, match="Invalid session_id"):
        _normalize_session_id(123)  # ty: ignore[arg-type]
    with pytest.raises(ToolError, match="Invalid session_id"):
        _normalize_session_id("bad session")


@pytest.mark.unit
async def test_close_and_bind_session_guard_paths() -> None:
    crawler_no_kill = MagicMock()
    crawler_no_kill.crawler_strategy = MagicMock(kill_session=None)
    await _close_crawler_session(crawler_no_kill, "s1")

    kill_mock = AsyncMock(side_effect=RuntimeError("boom"))
    crawler_fail = MagicMock()
    crawler_fail.crawler_strategy = MagicMock(kill_session=kill_mock)
    await _close_crawler_session(crawler_fail, "s1")
    with pytest.raises(ToolError, match="Failed to close session"):
        await _close_crawler_session(crawler_fail, "s2", raise_on_error=True)

    registry = {
        "old-session": {"last_used_at": 0.0, "uses": 1},
        "active-session": {"last_used_at": 990.0, "uses": 1},
    }
    crawler_cleanup = MagicMock()
    crawler_cleanup.crawler_strategy = MagicMock(kill_session=AsyncMock())
    expired = await _cleanup_expired_sessions(
        session_registry=registry,
        crawler=crawler_cleanup,
        now=1_000.0,
        session_ttl_seconds=60,
    )
    assert expired == ["old-session"]
    assert "old-session" not in registry

    artifact_store = _artifact_store()
    artifact_store["session_artifacts"] = {"quota-session": ["artifact-00000001"]}
    artifact_store["artifacts"] = {
        "artifact-00000001": {
            "artifact_id": "artifact-00000001",
            "session_id": "quota-session",
            "run_id": "run-00000001",
            "size_bytes": 10,
        }
    }
    quota_ctx = types.SimpleNamespace(
        lifespan_context={
            "sessions": {
                "quota-session": {"uses": 1, "last_used_at": 1_000.0, "session_max_uses": 1}
            },
            "artifacts": artifact_store,
        }
    )
    crawler_quota = MagicMock()
    crawler_quota.crawler_strategy = MagicMock(kill_session=AsyncMock())
    with patch("mcp_crawl4ai.server.time.time", return_value=1_000.0):
        with pytest.raises(ToolError, match="Session quota exceeded"):
            await _bind_session_id(
                session_id="quota-session",
                crawler=crawler_quota,
                ctx=quota_ctx,
            )


@pytest.mark.unit
def test_artifact_store_prune_and_retention_helpers() -> None:
    store = _artifact_store()
    store["artifacts"] = {
        "artifact-00000001": {
            "artifact_id": "artifact-00000001",
            "session_id": "s1",
            "run_id": "run-1",
            "size_bytes": 5,
            "expires_at": 1.0,
        },
        "artifact-00000002": {
            "artifact_id": "artifact-00000002",
            "session_id": "s1",
            "run_id": "run-1",
            "size_bytes": 7,
            "expires_at": 9_999.0,
        },
    }
    store["artifact_order"] = ["artifact-00000001", "artifact-00000002"]
    store["session_artifacts"] = {"s1": ["artifact-00000001", "artifact-00000002"]}
    store["session_runs"] = {"s1": ["run-1"]}
    store["runs"] = {"run-1": {"artifact_ids": ["artifact-00000001", "artifact-00000002"]}}
    store["total_bytes"] = 12

    _remove_artifact_entry(store, "artifact-00000001")
    assert "artifact-00000001" not in store["artifacts"]  # type: ignore[index]
    assert store["total_bytes"] == 7

    _prune_expired_artifacts(artifact_store=store, now=2.0)
    assert "artifact-00000002" in store["artifacts"]  # type: ignore[index]

    _enforce_artifact_retention(
        artifact_store=store,
        now=10_000.0,
        session_id="s1",
        artifact_max_per_session=0,
        artifact_max_total=0,
        artifact_max_total_bytes=0,
    )
    assert store["artifacts"] == {}

    store2 = _artifact_store()
    store2["artifacts"] = {
        "artifact-a": {
            "artifact_id": "artifact-a",
            "session_id": "s2",
            "run_id": "run-2",
            "size_bytes": 1,
        }
    }
    store2["artifact_order"] = ["artifact-a"]
    store2["session_artifacts"] = {"s2": ["artifact-a"]}
    store2["session_runs"] = {"s2": ["run-2"]}
    store2["runs"] = {"run-2": {"artifact_ids": ["artifact-a"]}}
    store2["total_bytes"] = 1
    _purge_session_artifacts(artifact_store=store2, session_id="s2")
    assert store2["artifacts"] == {}

    store3 = _artifact_store()
    store3["artifacts"] = {
        "artifact-00000003": {
            "artifact_id": "artifact-00000003",
            "session_id": "s3",
            "run_id": "run-3",
            "size_bytes": 1,
            "expires_at": 9_999.0,
        }
    }
    store3["artifact_order"] = [123, "artifact-00000003"]  # type: ignore[list-item]
    store3["session_artifacts"] = {"s3": [123, "artifact-00000003"]}  # type: ignore[list-item]
    store3["runs"] = {"run-3": {"artifact_ids": ["artifact-00000003"]}}
    store3["total_bytes"] = 1
    _enforce_artifact_retention(
        artifact_store=store3,
        now=1.0,
        session_id="s3",
        artifact_max_per_session=0,
        artifact_max_total=0,
        artifact_max_total_bytes=0,
    )
    assert "artifact-00000003" in store3["artifacts"]  # type: ignore[index]


@pytest.mark.unit
def test_capture_payload_and_result_artifacts() -> None:
    result = MagicMock()
    result.url = "https://example.com/x?token=secret"
    result.mhtml = "MHTML"
    result.pdf = b"%PDF"
    result.console_messages = [{"level": "info", "text": "ok"}]
    result.network_requests = [{"url": "https://example.com/api?key=secret"}]

    pdf_payload = _capture_artifact_payload(result=result, artifact_type="pdf")
    assert pdf_payload is not None and pdf_payload["content_type"] == "application/pdf"
    assert _capture_artifact_payload(result=result, artifact_type="unknown") is None

    result.console_messages = "not-a-list"
    assert _capture_artifact_payload(result=result, artifact_type="console") is None
    result.console_messages = [{"level": "info"}]
    result.network_requests = "not-a-list"
    assert _capture_artifact_payload(result=result, artifact_type="network") is None
    result.network_requests = [{"url": "https://example.com/api"}]

    store = _artifact_store()
    run_payload = _capture_result_artifacts(
        artifact_store=store,
        result=result,
        capture_artifacts=["mhtml", "pdf", "console", "network"],
        session_id="s3",
        requested_url="https://example.com/path?secret=1",
        artifact_ttl_seconds=5,
        artifact_max_per_session=10,
        artifact_max_total=10,
        artifact_max_total_bytes=10_000,
    )
    assert run_payload["session_id"] == "s3"
    assert run_payload["artifacts"]
    serialized = json.dumps(run_payload)
    assert "secret=1" not in serialized
    assert int(store["total_bytes"]) <= ARTIFACT_CAPTURE_TEXT_MAX_CHARS * 4


@pytest.mark.unit
def test_diagnostics_and_extraction_helpers() -> None:
    fake = MagicMock()
    fake.cleaned_html = "<div>fallback</div>"
    fake.html = "<html>fallback</html>"
    fake.markdown = MagicMock(fit_markdown="", raw_markdown="")
    assert _extract_markdown(fake) == ""

    assert _sanitize_diagnostic_url("not-a-url") is None
    assert _sanitize_diagnostic_url("https://example.com/path?q=1") == "https://example.com/path"
    assert _safe_diagnostic_count(None) == 0
    assert _safe_diagnostic_count(True) == 0
    assert _safe_diagnostic_count([1, 2, 3]) == 3
    assert _safe_diagnostic_count(-5) == 0

    timing_obj = MagicMock()
    timing_obj.timing = {"total_ms": 12, "fetch_ms": -1, "parse_ms": 3}
    timing_obj.duration_ms = 20
    summary = _extract_timing_summary(timing_obj)
    assert summary["total_ms"] == 12
    assert summary["parse_ms"] == 3
    assert summary["duration_ms"] == 20

    with pytest.raises(ToolError, match="Invalid extraction_mode"):
        _normalize_extraction_mode(12)  # ty: ignore[arg-type]
    with pytest.raises(ToolError, match="Invalid extraction_mode"):
        _normalize_extraction_mode("json")


@pytest.mark.unit
def test_deep_crawl_filter_validation_and_target_normalization() -> None:
    with pytest.raises(ToolError, match="Invalid url_filters.include"):
        _validate_deep_crawl_url_filter_patterns("x", param_name="url_filters.include")  # ty: ignore[arg-type]
    with pytest.raises(ToolError, match="Invalid url_filters.include\\[0\\]"):
        _validate_deep_crawl_url_filter_patterns([1], param_name="url_filters.include")
    with pytest.raises(ToolError, match="Invalid url_filters.include\\[0\\]"):
        _validate_deep_crawl_url_filter_patterns([" "], param_name="url_filters.include")
    with pytest.raises(ToolError, match="Invalid url_filters.include\\[0\\]"):
        _validate_deep_crawl_url_filter_patterns(
            ["a" * (DEEP_CRAWL_FILTER_PATTERN_MAX_CHARS + 1)],
            param_name="url_filters.include",
        )
    with pytest.raises(ToolError, match="Invalid url_filters.include\\[0\\]"):
        _validate_deep_crawl_url_filter_patterns(["a\nb"], param_name="url_filters.include")
    assert _validate_deep_crawl_url_filter_patterns(
        [" /docs/* "], param_name="url_filters.include"
    ) == ["/docs/*"]

    with pytest.raises(ToolError, match="Invalid crawl_mode"):
        _build_deep_crawl_strategy(
            crawl_mode=123,  # ty: ignore[arg-type]
            max_depth=1,
            max_pages=1,
            include_external=False,
        )
    with pytest.raises(ToolError, match="Invalid crawl_mode"):
        _build_deep_crawl_strategy(
            crawl_mode="invalid",
            max_depth=1,
            max_pages=1,
            include_external=False,
        )

    with pytest.raises(ToolError, match="Invalid targets"):
        _normalize_scrape_targets(1)  # ty: ignore[arg-type]
    with pytest.raises(ToolError, match="Invalid targets\\[0\\]"):
        _normalize_scrape_targets([""])
    with pytest.raises(ToolError, match="Invalid targets\\[0\\]"):
        _normalize_scrape_targets([123])  # ty: ignore[list-item]


@pytest.mark.integration
async def test_get_artifact_error_paths() -> None:
    bad_store_ctx = types.SimpleNamespace(lifespan_context={"artifacts": []})
    with pytest.raises(ToolError, match="Artifact store not available"):
        await get_artifact("sess-1", "artifact-1", ctx=bad_store_ctx)

    empty_store_ctx = types.SimpleNamespace(lifespan_context={"artifacts": _artifact_store()})
    with pytest.raises(ToolError, match="Artifact not found or expired"):
        await get_artifact("sess-1", "artifact-1", ctx=empty_store_ctx)

    wrong_owner_store = _artifact_store()
    wrong_owner_store["artifacts"] = {
        "artifact-00000001": {
            "artifact_id": "artifact-00000001",
            "session_id": "different-session",
            "run_id": "run-1",
            "size_bytes": 1,
            "content_type": "text/plain",
            "encoding": "utf-8",
            "created_at": 1,
            "expires_at": 9_999_999_999,
            "content": "x",
        }
    }
    owner_ctx = types.SimpleNamespace(lifespan_context={"artifacts": wrong_owner_store})
    with pytest.raises(ToolError, match="Artifact not found or expired"):
        await get_artifact("sess-1", "artifact-00000001", ctx=owner_ctx)
