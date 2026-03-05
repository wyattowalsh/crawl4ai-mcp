"""Tests for the Crawl4AI MCP server canonical surface."""

from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from crawl4ai import JsonCssExtractionStrategy, JsonXPathExtractionStrategy
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_crawl4ai import (
    SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION,
    SCRAPE_CRAWL_ENVELOPE_FIELDS,
)
from mcp_crawl4ai.server import (
    BATCH_ITEM_CHARS,
    MAX_RESPONSE_CHARS,
    SESSION_TTL_SECONDS_DEFAULT,
    _extract_markdown,
    _get_crawler,
    _get_max_response_chars,
    _load_settings,
    _normalize_canonical_option_groups,
    _select_content,
    _truncate,
    _validate_optional_numeric_range,
    _validate_optional_runtime_controls,
    _validate_optional_size_bound,
    _validate_optional_timeout_ms,
    _validate_url,
    main,
    mcp,
)

EXPECTED_TOOLS = sorted(["scrape", "crawl", "close_session", "get_artifact"])
EXPECTED_RESOURCES = sorted(["config://server", "crawl4ai://version"])
RETIRED_LEGACY_TOOLS = {
    "crawl_url",
    "crawl_many",
    "deep_crawl",
    "extract_data",
    "take_screenshot",
    "get_links",
    "get_page_info",
    "execute_js",
}


@pytest.mark.smoke
class TestDiscovery:
    async def test_list_tools(self, client):
        c, _ = client
        tools = await c.list_tools()
        tool_names = sorted(t.name for t in tools)
        assert tool_names == EXPECTED_TOOLS

    async def test_close_session_tool_annotations(self, client):
        c, _ = client
        tools = await c.list_tools()
        close_session_tool = next(tool for tool in tools if tool.name == "close_session")
        annotations = close_session_tool.model_dump()["annotations"]

        assert annotations["readOnlyHint"] is False
        assert annotations["destructiveHint"] is True
        assert annotations["idempotentHint"] is True
        assert annotations["openWorldHint"] is False

    async def test_retired_legacy_tools_not_registered(self, client):
        c, _ = client
        tools = await c.list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names.isdisjoint(RETIRED_LEGACY_TOOLS)

    async def test_list_resources(self, client):
        c, _ = client
        resources = await c.list_resources()
        resource_uris = sorted(str(r.uri) for r in resources)
        assert resource_uris == EXPECTED_RESOURCES


@pytest.mark.e2e
class TestE2EWorkflows:
    async def test_end_to_end_scrape_crawl_close_session_flow(self, client):
        c, _ = client

        scrape = await c.call_tool(
            "scrape",
            {
                "targets": "https://example.com",
                "options": {"session": {"session_id": "e2e-session"}},
            },
        )
        scrape_text = scrape.content[0].text if hasattr(scrape, "content") else str(scrape)
        scrape_data = json.loads(scrape_text)
        assert scrape_data["ok"] is True
        assert scrape_data["meta"]["session_id"] == "e2e-session"

        crawl = await c.call_tool(
            "crawl",
            {
                "targets": ["https://example.com", "https://example.com/next"],
                "options": {"traversal": {"mode": "list"}},
            },
        )
        crawl_text = crawl.content[0].text if hasattr(crawl, "content") else str(crawl)
        crawl_data = json.loads(crawl_text)
        assert crawl_data["ok"] is True
        assert len(crawl_data["items"]) == 2

        closed = await c.call_tool("close_session", {"session_id": "e2e-session"})
        closed_text = closed.content[0].text if hasattr(closed, "content") else str(closed)
        assert json.loads(closed_text) == {"session_id": "e2e-session", "closed": True}


class TestScrape:
    async def test_scrape_single_target_returns_canonical_envelope(self, client):
        c, mock_crawler = client
        result = await c.call_tool("scrape", {"targets": "https://example.com"})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)

        assert data["schema_version"] == SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION
        assert data["tool"] == "scrape"
        assert data["ok"] is True
        assert data["items"] is None
        assert data["data"]["ok"] is True
        assert isinstance(data["data"]["data"], str)
        assert data["error"] is None
        assert mock_crawler.arun.await_args.kwargs["url"] == "https://example.com"

    async def test_scrape_envelope_contract_and_meta_option_groups(self, client):
        c, _ = client
        result = await c.call_tool(
            "scrape",
            {
                "targets": "https://example.com",
                "options": {
                    "conversion": {"output_format": "text"},
                    "runtime": {"timeout_ms": 30_000},
                    "diagnostics": {"include_diagnostics": True},
                },
            },
        )
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)

        assert tuple(data) == SCRAPE_CRAWL_ENVELOPE_FIELDS
        assert data["meta"]["option_groups"] == ["conversion", "diagnostics", "runtime"]
        assert data["meta"]["output_format"] == "text"
        assert data["meta"]["diagnostics"] is True
        assert data["meta"]["traversal_mode"] is None

    async def test_scrape_batch_returns_items_and_failure_envelope(
        self,
        client,
        mock_crawl_result,
        mock_failed_result,
    ):
        c, mock_crawler = client
        mock_crawler.arun_many = AsyncMock(return_value=[mock_crawl_result, mock_failed_result])
        targets = ["https://example.com", "https://fail.example.com"]

        result = await c.call_tool(
            "scrape",
            {
                "targets": targets,
                "options": {"diagnostics": {"include_diagnostics": True}},
            },
        )
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)

        assert data["ok"] is False
        assert data["data"] is None
        assert len(data["items"]) == 2
        assert data["items"][0]["ok"] is True
        assert data["items"][1]["ok"] is False
        assert "diagnostics" in data["items"][0]
        assert data["error"]["code"] == "SCRAPE_FAILED"
        assert data["warnings"]

    async def test_scrape_extraction_modes_wire_strategies(self, client, mock_crawl_result):
        c, mock_crawler = client
        schema = {
            "name": "Products",
            "baseSelector": ".product",
            "fields": [{"name": "title", "selector": "h2", "type": "text"}],
        }
        mock_crawl_result.extracted_content = '[{"title": "Item"}]'

        await c.call_tool(
            "scrape",
            {
                "targets": "https://example.com",
                "options": {"extraction": {"schema": schema}},
            },
        )
        css_config = mock_crawler.arun.await_args.kwargs["config"]
        assert isinstance(css_config.extraction_strategy, JsonCssExtractionStrategy)

        xpath_schema = {
            "name": "Products",
            "baseSelector": "//div[contains(@class, 'product')]",
            "fields": [{"name": "title", "selector": ".//h2", "type": "text"}],
        }
        await c.call_tool(
            "scrape",
            {
                "targets": "https://example.com",
                "options": {
                    "extraction": {
                        "schema": xpath_schema,
                        "extraction_mode": "xpath",
                    }
                },
            },
        )
        xpath_config = mock_crawler.arun.await_args.kwargs["config"]
        assert isinstance(xpath_config.extraction_strategy, JsonXPathExtractionStrategy)

    async def test_scrape_rejects_invalid_option_combination(self, client):
        c, _ = client
        with pytest.raises(
            ToolError,
            match=r"options\.extraction\.extraction_mode: requires options\.extraction\.schema",
        ):
            await c.call_tool(
                "scrape",
                {
                    "targets": "https://example.com",
                    "options": {"extraction": {"extraction_mode": "xpath"}},
                },
            )

    async def test_scrape_rejects_traversal_option_group(self, client):
        c, _ = client
        with pytest.raises(ToolError, match=r"options\.traversal"):
            await c.call_tool(
                "scrape",
                {
                    "targets": "https://example.com",
                    "options": {"traversal": {"mode": "list"}},
                },
            )

    async def test_scrape_rejects_targets_over_limit(self, client):
        c, _ = client
        with pytest.raises(ToolError, match="Invalid targets"):
            await c.call_tool(
                "scrape",
                {"targets": [f"https://example.com/{index}" for index in range(21)]},
            )

    async def test_scrape_runtime_controls_forwarded_to_arun(self, client):
        c, mock_crawler = client
        await c.call_tool(
            "scrape",
            {
                "targets": "https://example.com",
                "options": {
                    "runtime": {
                        "timeout_ms": 30_000,
                        "max_retries": 2,
                        "retry_backoff_ms": 200,
                        "max_content_chars": 4096,
                    }
                },
            },
        )

        arun_kwargs = mock_crawler.arun.await_args.kwargs
        assert arun_kwargs["timeout_ms"] == 30_000
        assert arun_kwargs["max_retries"] == 2
        assert arun_kwargs["retry_backoff_ms"] == 200
        assert arun_kwargs["max_content_chars"] == 4096

    async def test_scrape_capture_artifacts_requires_session_id(self, client):
        c, _ = client
        with pytest.raises(ToolError, match=r"options\.conversion\.capture_artifacts"):
            await c.call_tool(
                "scrape",
                {
                    "targets": "https://example.com",
                    "options": {"conversion": {"capture_artifacts": ["mhtml"]}},
                },
            )


class TestCrawl:
    async def test_crawl_list_mode_returns_canonical_envelope(self, client):
        c, mock_crawler = client
        targets = ["https://example.com", "https://example.com/page2"]

        result = await c.call_tool(
            "crawl",
            {
                "targets": targets,
                "options": {
                    "diagnostics": {"include_diagnostics": True},
                    "traversal": {
                        "mode": "list",
                        "dispatcher": {
                            "max_concurrency": 1,
                            "rate_limit": {"base_delay": 0.2, "max_delay": 1.0, "max_retries": 4},
                        },
                    },
                },
            },
        )
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)

        assert data["schema_version"] == SCRAPE_CRAWL_CONTRACT_SCHEMA_VERSION
        assert data["tool"] == "crawl"
        assert data["ok"] is True
        assert data["data"] is None
        assert len(data["items"]) == 2
        assert data["meta"]["traversal_mode"] == "list"
        assert data["error"] is None

        dispatcher = mock_crawler.arun_many.await_args.kwargs["dispatcher"]
        assert dispatcher.semaphore_count == 1
        assert dispatcher.max_session_permit == len(targets)
        assert dispatcher.rate_limiter is not None

    async def test_crawl_envelope_contract_and_meta_option_groups(self, client):
        c, _ = client
        result = await c.call_tool(
            "crawl",
            {
                "targets": ["https://example.com", "https://example.com/page2"],
                "options": {
                    "conversion": {"output_format": "text"},
                    "runtime": {"timeout_ms": 30_000},
                    "traversal": {"mode": "list"},
                },
            },
        )
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)

        assert tuple(data) == SCRAPE_CRAWL_ENVELOPE_FIELDS
        assert data["meta"]["option_groups"] == ["conversion", "runtime", "traversal"]
        assert data["meta"]["output_format"] == "text"
        assert data["meta"]["traversal_mode"] == "list"

    async def test_crawl_deep_mode_uses_strategy_and_canonical_envelope(
        self,
        client,
        mock_crawl_result,
        mock_failed_result,
    ):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=[mock_crawl_result, mock_failed_result])

        with patch("mcp_crawl4ai.server.DFSDeepCrawlStrategy") as mock_dfs:
            mock_dfs.return_value = MagicMock()
            result = await c.call_tool(
                "crawl",
                {
                    "targets": "https://example.com",
                    "options": {
                        "diagnostics": {"include_diagnostics": True},
                        "traversal": {
                            "mode": "deep",
                            "max_depth": 3,
                            "max_pages": 4,
                            "crawl_mode": "dfs",
                            "include_external": True,
                            "url_filters": {"include": ["*/docs/*"]},
                        },
                    },
                },
            )

        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)

        assert data["tool"] == "crawl"
        assert data["ok"] is False
        assert len(data["items"]) == 2
        assert data["meta"]["traversal_mode"] == "deep"
        assert "depth" in data["items"][0]
        mock_dfs.assert_called_once()

    async def test_crawl_rejects_invalid_traversal_combinations(self, client):
        c, _ = client
        with pytest.raises(ToolError, match=r"options\.traversal"):
            await c.call_tool(
                "crawl",
                {
                    "targets": "https://example.com",
                    "options": {"traversal": {"mode": "list", "max_depth": 2}},
                },
            )

        with pytest.raises(ToolError, match=r"options\.traversal\.dispatcher"):
            await c.call_tool(
                "crawl",
                {
                    "targets": "https://example.com",
                    "options": {
                        "traversal": {"mode": "deep", "dispatcher": {"max_concurrency": 1}}
                    },
                },
            )

        with pytest.raises(ToolError, match=r"requires exactly one URL"):
            await c.call_tool(
                "crawl",
                {
                    "targets": ["https://example.com", "https://example.com/page2"],
                    "options": {"traversal": {"mode": "deep"}},
                },
            )

    async def test_crawl_rejects_rate_limit_retries_without_delay_config(self, client):
        c, _ = client
        with pytest.raises(ToolError, match="rate_limit_max_retries"):
            await c.call_tool(
                "crawl",
                {
                    "targets": ["https://example.com", "https://example.com/page2"],
                    "options": {
                        "traversal": {
                            "mode": "list",
                            "rate_limit_max_retries": 2,
                        }
                    },
                },
            )


@pytest.mark.integration
class TestSessionAndArtifacts:
    async def test_session_creation_and_reuse(self, client):
        c, mock_crawler = client

        await c.call_tool(
            "scrape",
            {
                "targets": "https://example.com",
                "options": {"session": {"session_id": "workflow-1"}},
            },
        )
        await c.call_tool(
            "scrape",
            {
                "targets": "https://example.com/page2",
                "options": {"session": {"session_id": "workflow-1"}},
            },
        )

        first_config = mock_crawler.arun.await_args_list[0].kwargs["config"]
        second_config = mock_crawler.arun.await_args_list[1].kwargs["config"]
        assert first_config.session_id == "workflow-1"
        assert second_config.session_id == "workflow-1"

    async def test_session_expiry_and_close(self, client):
        c, mock_crawler = client
        mock_crawler.crawler_strategy = MagicMock()
        mock_crawler.crawler_strategy.kill_session = AsyncMock()

        with patch(
            "mcp_crawl4ai.server.time.time",
            side_effect=[1000.0, 1000.0 + SESSION_TTL_SECONDS_DEFAULT + 1],
        ):
            await c.call_tool(
                "scrape",
                {
                    "targets": "https://example.com",
                    "options": {"session": {"session_id": "ttl-session"}},
                },
            )
            await c.call_tool(
                "scrape",
                {
                    "targets": "https://example.com/next",
                    "options": {"session": {"session_id": "ttl-session"}},
                },
            )

        mock_crawler.crawler_strategy.kill_session.assert_awaited_once_with("ttl-session")

        await c.call_tool(
            "scrape",
            {
                "targets": "https://example.com",
                "options": {"session": {"session_id": "cleanup-session"}},
            },
        )
        closed = await c.call_tool("close_session", {"session_id": "cleanup-session"})
        closed_text = closed.content[0].text if hasattr(closed, "content") else str(closed)
        assert json.loads(closed_text) == {"session_id": "cleanup-session", "closed": True}

    async def test_close_session_is_idempotent_on_missing_or_close_errors(self, client):
        c, mock_crawler = client
        mock_crawler.crawler_strategy = MagicMock()
        mock_crawler.crawler_strategy.kill_session = AsyncMock(
            side_effect=RuntimeError("already gone")
        )

        await c.call_tool(
            "scrape",
            {
                "targets": "https://example.com",
                "options": {"session": {"session_id": "idempotent-session"}},
            },
        )
        first_close = await c.call_tool("close_session", {"session_id": "idempotent-session"})
        first_close_text = (
            first_close.content[0].text if hasattr(first_close, "content") else str(first_close)
        )
        assert json.loads(first_close_text) == {"session_id": "idempotent-session", "closed": True}

        second_close = await c.call_tool("close_session", {"session_id": "idempotent-session"})
        second_close_text = (
            second_close.content[0].text if hasattr(second_close, "content") else str(second_close)
        )
        assert json.loads(second_close_text) == {
            "session_id": "idempotent-session",
            "closed": False,
        }

    async def test_capture_and_retrieve_artifacts_with_redaction(
        self,
        client,
        mock_crawl_result,
    ):
        c, mock_crawler = client
        mock_crawl_result.mhtml = "mhtml-blob"
        mock_crawl_result.console_messages = [{"level": "info", "text": "loaded"}]
        mock_crawl_result.network_requests = [
            {
                "url": "https://example.com/api",
                "headers": {
                    "cookie": "secret-cookie",
                    "authorization": "secret-token",
                },
                "status": 200,
            }
        ]
        mock_crawler.arun = AsyncMock(return_value=mock_crawl_result)

        result = await c.call_tool(
            "scrape",
            {
                "targets": "https://example.com",
                "options": {
                    "session": {"session_id": "artifact-session"},
                    "conversion": {"capture_artifacts": ["mhtml", "console", "network"]},
                },
            },
        )
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)

        run = data["data"]["run"]
        assert run["session_id"] == "artifact-session"
        artifacts = run["artifacts"]
        assert {item["artifact_type"] for item in artifacts} == {"mhtml", "console", "network"}
        network_artifact_id = next(
            item["artifact_id"] for item in artifacts if item["artifact_type"] == "network"
        )
        assert not network_artifact_id.startswith("artifact-")

        with_content_result = await c.call_tool(
            "get_artifact",
            {
                "session_id": "artifact-session",
                "artifact_id": network_artifact_id,
                "include_content": True,
            },
        )
        with_content_text = (
            with_content_result.content[0].text
            if hasattr(with_content_result, "content")
            else str(with_content_result)
        )
        with_content = json.loads(with_content_text)
        artifact_blob = json.dumps(with_content).lower()
        assert "cookie" not in artifact_blob
        assert "authorization" not in artifact_blob
        assert "secret-token" not in artifact_blob
        assert "secret-cookie" not in artifact_blob

    @pytest.mark.parametrize(
        ("tool_name", "payload"),
        [
            (
                "scrape",
                {
                    "targets": "https://example.com",
                    "options": {"session": {"session_id": "bad session"}},
                },
            ),
            ("close_session", {"session_id": "###"}),
        ],
    )
    async def test_invalid_session_id_raises_tool_error(self, client, tool_name, payload):
        c, _ = client
        with pytest.raises(ToolError, match="Invalid session_id"):
            await c.call_tool(tool_name, payload)


class TestErrorHandling:
    async def test_scrape_invalid_url(self, client):
        c, _ = client
        with pytest.raises(ToolError, match="Invalid URL"):
            await c.call_tool("scrape", {"targets": "ftp://bad.example.com"})

    async def test_scrape_failed_crawl_returns_error_envelope(self, client, mock_failed_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=mock_failed_result)
        result = await c.call_tool("scrape", {"targets": "https://fail.example.com"})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)
        assert data["ok"] is False
        assert data["error"]["code"] == "SCRAPE_FAILED"


@pytest.mark.unit
class TestURLValidation:
    def test_valid_http_url(self):
        _validate_url("http://example.com")

    def test_valid_https_url(self):
        _validate_url("https://example.com/path?query=1")

    def test_invalid_ftp_url(self):
        with pytest.raises(ToolError, match="Invalid URL"):
            _validate_url("ftp://example.com")

    def test_invalid_javascript_url(self):
        with pytest.raises(ToolError, match="Invalid URL"):
            _validate_url("javascript:alert(1)")

    def test_empty_url(self):
        with pytest.raises(ToolError, match="Invalid URL"):
            _validate_url("")


class TestResources:
    async def test_config_resource_matches_registered_tools(self, client):
        c, _ = client
        contents = await c.read_resource("config://server")
        text = contents[0].text if hasattr(contents[0], "text") else str(contents[0])
        data = json.loads(text)

        tools = await c.list_tools()
        listed_tools = sorted(t.name for t in tools)

        assert data["name"] == "crawl4ai"
        assert sorted(data["tools"]) == EXPECTED_TOOLS
        assert sorted(data["tools"]) == listed_tools
        assert "settings" in data
        assert "defaults" in data["settings"]
        assert "limits" in data["settings"]
        assert "policies" in data["settings"]
        assert "capabilities" in data["settings"]
        assert data["max_response_chars"] == MAX_RESPONSE_CHARS

    async def test_version_resource(self, client):
        c, _ = client
        contents = await c.read_resource("crawl4ai://version")
        text = contents[0].text if hasattr(contents[0], "text") else str(contents[0])
        data = json.loads(text)
        assert "server_version" in data
        assert "crawl4ai_version" in data
        assert "fastmcp_version" in data


class TestSettings:
    def test_settings_default_parity(self):
        _load_settings(reload=True)
        assert _get_max_response_chars() == MAX_RESPONSE_CHARS
        assert BATCH_ITEM_CHARS > 0

    def test_settings_supports_nested_env_overrides(self):
        with patch.dict("os.environ", {"MCP_CRAWL4AI_DEFAULTS__MAX_RESPONSE_CHARS": "1234"}):
            settings = _load_settings(reload=True)
            assert settings.defaults.max_response_chars == 1234
            assert _get_max_response_chars() == 1234
        _load_settings(reload=True)


class TestTruncation:
    def test_truncation_short_content(self):
        content = "Short content"
        assert _truncate(content) == content

    def test_truncation_long_content(self):
        content = "A" * (MAX_RESPONSE_CHARS + 5000)
        truncated = _truncate(content)
        assert len(truncated) < len(content)
        assert truncated.startswith("A" * 100)
        assert "truncated" in truncated.lower()
        assert str(len(content)) in truncated

    async def test_truncation_via_scrape_tool(self, client, mock_crawl_result):
        c, mock_crawler = client
        long_markdown = MagicMock()
        long_markdown.fit_markdown = "B" * (MAX_RESPONSE_CHARS + 10_000)
        long_markdown.raw_markdown = long_markdown.fit_markdown
        mock_crawl_result.markdown = long_markdown
        mock_crawler.arun = AsyncMock(return_value=mock_crawl_result)

        result = await c.call_tool("scrape", {"targets": "https://example.com"})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        assert text.startswith("{")
        assert "content truncated" in text.lower()


class TestExtractMarkdownFallbacks:
    def test_extract_markdown_none_returns_cleaned_html(self):
        result = MagicMock()
        result.markdown = None
        result.cleaned_html = "<div>clean</div>"
        result.html = "<html>raw</html>"
        assert _extract_markdown(result) == "<div>clean</div>"

    def test_extract_markdown_string_returns_string(self):
        result = MagicMock()
        result.markdown = "# plain string markdown"
        assert _extract_markdown(result) == "# plain string markdown"


class TestSSRFProtection:
    def test_localhost_hostname(self):
        with pytest.raises(ToolError, match="Private/loopback"):
            _validate_url("http://localhost/foo")

    def test_private_ip_loopback(self):
        with pytest.raises(ToolError, match="Private/loopback"):
            _validate_url("http://127.0.0.1/foo")

    def test_hostname_resolve_blocks_non_global_addresses(self):
        with patch(
            "mcp_crawl4ai.server.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("127.0.0.1", 80))],
        ):
            with pytest.raises(ToolError, match="Private/loopback"):
                _validate_url("http://example.com/foo")

    def test_hostname_resolve_allows_global_addresses(self):
        with patch(
            "mcp_crawl4ai.server.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 80))],
        ) as mock_getaddrinfo:
            _validate_url("http://example.com/foo")
        mock_getaddrinfo.assert_called_once()


@pytest.mark.unit
class TestHelperEdgeCases:
    def test_get_crawler_no_context(self):
        with pytest.raises(ToolError, match="Crawler not available"):
            _get_crawler(None)

    def test_select_content_invalid_format(self):
        result = MagicMock()
        with pytest.raises(ToolError, match="Unknown output_format"):
            _select_content(result, "xml")


@pytest.mark.unit
class TestRuntimeGuardrailHelpers:
    def test_optional_timeout_accepts_none(self):
        assert _validate_optional_timeout_ms(None) is None

    def test_optional_timeout_rejects_float(self):
        with pytest.raises(ToolError, match="Invalid timeout_ms"):
            _validate_optional_timeout_ms(500.5)  # ty: ignore[invalid-argument-type]

    def test_optional_size_bound_rejects_zero(self):
        with pytest.raises(ToolError, match="Invalid max_content_chars"):
            _validate_optional_size_bound(0, param_name="max_content_chars")

    def test_optional_numeric_range_rejects_bool(self):
        with pytest.raises(ToolError, match="Invalid max_concurrency"):
            _validate_optional_numeric_range(
                True,
                param_name="max_concurrency",
                minimum=1,
                maximum=8,
            )

    def test_optional_runtime_controls_returns_only_passed_values(self):
        assert _validate_optional_runtime_controls(
            timeout_ms=30_000,
            max_retries=2,
        ) == {"timeout_ms": 30_000, "max_retries": 2}


@pytest.mark.unit
class TestCanonicalOptionNormalization:
    def test_normalize_sparse_crawl_options(self):
        normalized = _normalize_canonical_option_groups(
            operation="crawl",
            options={
                "conversion": {"capture_artifacts": ["PDF", "console", "pdf"]},
                "runtime": {"timeout_ms": 30_000, "max_retries": 2},
                "session": {"session_id": "  crawl-session  "},
                "traversal": {
                    "mode": " DEEP ",
                    "crawl_mode": " DFS ",
                    "url_filters": {"include": [" */docs/* "]},
                    "dispatcher": {
                        "max_concurrency": 3,
                        "rate_limit": {"base_delay": 0.5, "max_delay": 1.5, "max_retries": 4},
                    },
                },
            },
        )

        assert normalized.session.session_id == "crawl-session"
        assert normalized.conversion.capture_artifacts == ["pdf", "console"]
        assert normalized.runtime.timeout_ms == 30_000
        assert normalized.runtime.max_retries == 2
        assert normalized.traversal.mode == "deep"
        assert normalized.traversal.crawl_mode == "dfs"
        assert normalized.traversal.url_filters == {"include": ["*/docs/*"]}
        assert normalized.traversal.max_concurrency == 3
        assert normalized.traversal.rate_limit_base_delay == 0.5
        assert normalized.traversal.rate_limit_max_delay == 1.5
        assert normalized.traversal.rate_limit_max_retries == 4
        assert normalized.traversal.dispatcher is not None
        assert normalized.traversal.dispatcher.max_concurrency == 3
        assert normalized.traversal.dispatcher.rate_limit_base_delay == 0.5
        assert normalized.traversal.dispatcher.rate_limit_max_delay == 1.5
        assert normalized.traversal.dispatcher.rate_limit_max_retries == 4

    def test_normalize_crawl_dispatcher_precedence(self):
        normalized = _normalize_canonical_option_groups(
            operation="crawl",
            options={
                "traversal": {
                    "mode": "list",
                    "max_concurrency": 4,
                    "rate_limit_base_delay": 0.4,
                    "dispatcher": {
                        "max_concurrency": 1,
                        "rate_limit": {"base_delay": 0.2, "max_delay": 1.0, "max_retries": 2},
                    },
                }
            },
        )

        assert normalized.traversal.max_concurrency == 4
        assert normalized.traversal.rate_limit_base_delay == 0.4
        assert normalized.traversal.rate_limit_max_delay == 1.0
        assert normalized.traversal.rate_limit_max_retries == 2
        assert normalized.traversal.dispatcher is not None
        assert normalized.traversal.dispatcher.max_concurrency == 4
        assert normalized.traversal.dispatcher.rate_limit_base_delay == 0.4
        assert normalized.traversal.dispatcher.rate_limit_max_delay == 1.0
        assert normalized.traversal.dispatcher.rate_limit_max_retries == 2


class TestPrompts:
    async def test_summarize_page_prompt(self, client):
        c, _ = client
        prompt = await c.get_prompt("summarize_page", {"url": "https://example.com"})
        text = prompt.messages[0].content.text
        assert len(prompt.messages) == 1
        assert "scrape" in text
        assert "https://example.com" in text

    async def test_build_extraction_schema_prompt(self, client):
        c, _ = client
        prompt = await c.get_prompt(
            "build_extraction_schema",
            {"url": "https://example.com", "data_type": "products"},
        )
        text = prompt.messages[0].content.text
        assert len(prompt.messages) == 1
        assert "options.extraction.schema" in text
        assert "products" in text

    async def test_compare_pages_prompt(self, client):
        c, _ = client
        prompt = await c.get_prompt(
            "compare_pages",
            {"url1": "https://a.com", "url2": "https://b.com"},
        )
        text = prompt.messages[0].content.text
        assert len(prompt.messages) == 1
        assert "scrape" in text
        assert "https://a.com" in text
        assert "https://b.com" in text


class TestMain:
    def test_main_stdio(self):
        from mcp_crawl4ai.server import mcp as _mcp

        with (
            patch("sys.argv", ["mcp-crawl4ai"]),
            patch.object(_mcp, "run") as mock_run,
        ):
            main()
            mock_run.assert_called_once_with()

    def test_main_http(self):
        from mcp_crawl4ai.server import mcp as _mcp

        with (
            patch(
                "sys.argv",
                ["mcp-crawl4ai", "--transport", "http", "--host", "0.0.0.0", "--port", "9000"],
            ),
            patch.object(_mcp, "run") as mock_run,
            patch("sys.stderr", new_callable=io.StringIO) as mock_stderr,
        ):
            main()
            mock_run.assert_called_once_with(transport="http", host="0.0.0.0", port=9000)
            assert "non-loopback host" in mock_stderr.getvalue()
            assert "reverse proxy" in mock_stderr.getvalue()

    def test_main_http_loopback_no_warning(self):
        from mcp_crawl4ai.server import mcp as _mcp

        with (
            patch(
                "sys.argv",
                ["mcp-crawl4ai", "--transport", "http", "--host", "127.0.0.1", "--port", "9000"],
            ),
            patch.object(_mcp, "run") as mock_run,
            patch("sys.stderr", new_callable=io.StringIO) as mock_stderr,
        ):
            main()
            mock_run.assert_called_once_with(transport="http", host="127.0.0.1", port=9000)
            assert mock_stderr.getvalue() == ""


class TestSetupFlag:
    def test_setup_flag_runs_setup(self, mocker):
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=0, stderr="")
        mocker.patch("sys.argv", ["mcp-crawl4ai", "--setup"])

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        mock_run.assert_called_once_with(
            ["crawl4ai-setup"],
            capture_output=True,
            text=True,
        )

    def test_setup_flag_failure(self, mocker):
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=1, stderr="Error")
        mocker.patch("sys.argv", ["mcp-crawl4ai", "--setup"])

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1


class TestBrowserAutoDetection:
    async def test_auto_install_on_browser_error(self, mock_crawl_result):
        mock_crawler = AsyncMock()
        mock_crawler.start = AsyncMock(
            side_effect=[Exception("playwright chromium browser not found"), None]
        )
        mock_crawler.close = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=mock_crawl_result)

        with (
            patch("mcp_crawl4ai.server.AsyncWebCrawler", return_value=mock_crawler),
            patch("mcp_crawl4ai.server.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            async with Client(mcp) as c:
                tools = await c.list_tools()
                assert len(tools) > 0
            mock_run.assert_called_once_with(
                ["crawl4ai-setup"],
                check=True,
                capture_output=True,
                text=True,
            )


class TestSmoke:
    @pytest.mark.smoke
    def test_server_import(self):
        from mcp_crawl4ai.server import mcp as _mcp

        assert _mcp.name == "crawl4ai"
