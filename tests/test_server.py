"""Tests for the Crawl4AI MCP server (FastMCP v3 implementation).

Uses fastmcp.Client for in-memory testing — no real browser or network access.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from crawl4ai_mcp.server import (
    MAX_RESPONSE_CHARS,
    _extract_markdown,
    _get_crawler,
    _select_content,
    _truncate,
    _validate_url,
)

# =========================================================================
# 1. Discovery tests
# =========================================================================


EXPECTED_TOOLS = sorted(
    [
        "crawl_url",
        "crawl_many",
        "deep_crawl",
        "extract_data",
        "take_screenshot",
        "get_links",
        "get_page_info",
        "execute_js",
    ]
)

EXPECTED_RESOURCES = sorted(
    [
        "config://server",
        "crawl4ai://version",
    ]
)


@pytest.mark.smoke
class TestDiscovery:
    async def test_list_tools(self, client):
        c, _ = client
        tools = await c.list_tools()
        tool_names = sorted(t.name for t in tools)
        assert tool_names == EXPECTED_TOOLS

    async def test_list_resources(self, client):
        c, _ = client
        resources = await c.list_resources()
        resource_uris = sorted(str(r.uri) for r in resources)
        assert resource_uris == EXPECTED_RESOURCES


# =========================================================================
# 2. Happy path tests — one per tool
# =========================================================================


class TestCrawlUrl:
    async def test_crawl_url(self, client):
        c, _ = client
        result = await c.call_tool("crawl_url", {"url": "https://example.com"})
        # The tool returns a string (markdown content), not JSON
        assert result is not None
        text = result.content[0].text if hasattr(result, "content") else str(result)
        assert "Example" in text or "markdown" in text.lower() or len(text) > 0


class TestCrawlMany:
    async def test_crawl_many(self, client):
        c, mock_crawler = client
        urls = ["https://example.com", "https://example.com/page2"]
        result = await c.call_tool("crawl_many", {"urls": urls})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)
        assert isinstance(data, list)
        assert len(data) == 2
        for item in data:
            assert "url" in item
            assert item["success"] is True


class TestDeepCrawl:
    async def test_deep_crawl(self, client, mock_crawl_result):
        c, mock_crawler = client
        # deep_crawl calls crawler.arun which may return a list
        mock_crawler.arun = AsyncMock(return_value=[mock_crawl_result])
        result = await c.call_tool("deep_crawl", {"url": "https://example.com"})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)
        assert data["seed_url"] == "https://example.com"
        assert data["pages_crawled"] >= 1
        assert isinstance(data["results"], list)


class TestExtractData:
    async def test_extract_data(self, client):
        c, _ = client
        schema = {
            "name": "Products",
            "baseSelector": ".product",
            "fields": [
                {"name": "title", "selector": "h2", "type": "text"},
            ],
        }
        result = await c.call_tool("extract_data", {"url": "https://example.com", "schema": schema})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        assert "Item" in text


class TestTakeScreenshot:
    async def test_take_screenshot(self, client):
        c, _ = client
        result = await c.call_tool("take_screenshot", {"url": "https://example.com"})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)
        assert "screenshot_base64" in data
        assert data["screenshot_base64"] == "base64data"
        assert data["url"] == "https://example.com"


class TestGetLinks:
    async def test_get_links(self, client):
        c, _ = client
        result = await c.call_tool("get_links", {"url": "https://example.com"})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)
        assert "internal_links" in data
        assert "external_links" in data
        assert data["total_internal"] == 2
        assert data["total_external"] == 1


class TestGetPageInfo:
    async def test_get_page_info(self, client):
        c, _ = client
        result = await c.call_tool("get_page_info", {"url": "https://example.com"})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)
        assert data["title"] == "Example"
        assert data["description"] == "Test page"
        assert "links_count" in data
        assert "media_count" in data
        assert data["metadata"]["language"] == "en"


class TestExecuteJs:
    async def test_execute_js(self, client):
        c, _ = client
        result = await c.call_tool(
            "execute_js",
            {"url": "https://example.com", "js_code": "document.title"},
        )
        text = result.content[0].text if hasattr(result, "content") else str(result)
        # Returns markdown content
        assert len(text) > 0


# =========================================================================
# 3. Error handling tests
# =========================================================================


class TestErrorHandling:
    async def test_crawl_url_invalid_url(self, client):
        c, _ = client
        with pytest.raises(ToolError, match="Invalid URL"):
            await c.call_tool("crawl_url", {"url": "ftp://bad.example.com"})

    async def test_crawl_url_not_a_url(self, client):
        c, _ = client
        with pytest.raises(ToolError, match="Invalid URL"):
            await c.call_tool("crawl_url", {"url": "not-a-url"})

    async def test_crawl_url_failed_crawl(self, client, mock_failed_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=mock_failed_result)
        with pytest.raises(ToolError, match="Crawl failed"):
            await c.call_tool("crawl_url", {"url": "https://fail.example.com"})

    async def test_extract_data_empty_result(self, client, mock_crawl_result):
        c, mock_crawler = client
        mock_crawl_result.extracted_content = None
        mock_crawler.arun = AsyncMock(return_value=mock_crawl_result)
        schema = {
            "name": "Items",
            "baseSelector": ".item",
            "fields": [{"name": "title", "selector": "h2", "type": "text"}],
        }
        with pytest.raises(ToolError, match="No data extracted"):
            await c.call_tool("extract_data", {"url": "https://example.com", "schema": schema})

    async def test_take_screenshot_no_data(self, client, mock_crawl_result):
        c, mock_crawler = client
        mock_crawl_result.screenshot = None
        mock_crawler.arun = AsyncMock(return_value=mock_crawl_result)
        with pytest.raises(ToolError, match="No screenshot data"):
            await c.call_tool("take_screenshot", {"url": "https://example.com"})


# =========================================================================
# 4. URL validation tests
# =========================================================================


class TestURLValidation:
    def test_valid_http_url(self):
        _validate_url("http://example.com")

    def test_valid_https_url(self):
        _validate_url("https://example.com")

    def test_invalid_ftp_url(self):
        with pytest.raises(ToolError, match="Invalid URL"):
            _validate_url("ftp://example.com")

    def test_invalid_javascript_url(self):
        with pytest.raises(ToolError, match="Invalid URL"):
            _validate_url("javascript:alert(1)")

    def test_empty_url(self):
        with pytest.raises(ToolError, match="Invalid URL"):
            _validate_url("")


# =========================================================================
# 5. Resource tests
# =========================================================================


class TestResources:
    async def test_config_resource(self, client):
        c, _ = client
        contents = await c.read_resource("config://server")
        text = contents[0].text if hasattr(contents[0], "text") else str(contents[0])
        data = json.loads(text)
        assert data["name"] == "crawl4ai"
        assert "version" in data
        assert sorted(data["tools"]) == EXPECTED_TOOLS

    async def test_version_resource(self, client):
        c, _ = client
        contents = await c.read_resource("crawl4ai://version")
        text = contents[0].text if hasattr(contents[0], "text") else str(contents[0])
        data = json.loads(text)
        assert "server_version" in data
        assert "crawl4ai_version" in data
        assert "fastmcp_version" in data


# =========================================================================
# 6. Truncation test
# =========================================================================


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

    async def test_truncation_via_tool(self, client, mock_crawl_result):
        """Provide content exceeding MAX_RESPONSE_CHARS, verify truncation notice."""
        c, mock_crawler = client
        long_markdown = MagicMock()
        long_markdown.fit_markdown = "B" * (MAX_RESPONSE_CHARS + 10_000)
        long_markdown.raw_markdown = long_markdown.fit_markdown
        mock_crawl_result.markdown = long_markdown
        mock_crawler.arun = AsyncMock(return_value=mock_crawl_result)

        result = await c.call_tool("crawl_url", {"url": "https://example.com"})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        assert "truncated" in text.lower()


# =========================================================================
# 7. Output format variant tests
# =========================================================================


class TestOutputFormats:
    async def test_crawl_url_html_format(self, client, mock_crawl_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=mock_crawl_result)
        result = await c.call_tool(
            "crawl_url", {"url": "https://example.com", "output_format": "html"}
        )
        text = result.content[0].text if hasattr(result, "content") else str(result)
        # mock_crawl_result.html = "<html><body><h1>Example</h1></body></html>"
        assert "<" in text and ">" in text  # HTML tags present

    async def test_crawl_url_cleaned_html_format(self, client, mock_crawl_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=mock_crawl_result)
        result = await c.call_tool(
            "crawl_url", {"url": "https://example.com", "output_format": "cleaned_html"}
        )
        text = result.content[0].text if hasattr(result, "content") else str(result)
        assert len(text) > 0

    async def test_crawl_url_text_format(self, client, mock_crawl_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=mock_crawl_result)
        result = await c.call_tool(
            "crawl_url", {"url": "https://example.com", "output_format": "text"}
        )
        text = result.content[0].text if hasattr(result, "content") else str(result)
        assert len(text) > 0

    async def test_crawl_url_invalid_format(self, client):
        c, _ = client
        with pytest.raises(ToolError):
            await c.call_tool("crawl_url", {"url": "https://example.com", "output_format": "xml"})


# =========================================================================
# 8. crawl_many partial failures
# =========================================================================


class TestCrawlManyPartialFailure:
    async def test_crawl_many_partial_failure(self, client, mock_crawl_result, mock_failed_result):
        c, mock_crawler = client
        # Return one success and one failure
        mock_crawler.arun_many = AsyncMock(return_value=[mock_crawl_result, mock_failed_result])
        urls = ["https://example.com", "https://fail.example.com"]
        result = await c.call_tool("crawl_many", {"urls": urls})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)
        assert isinstance(data, list)
        assert len(data) == 2
        successes = [d for d in data if d["success"] is True]
        failures = [d for d in data if d["success"] is False]
        assert len(successes) == 1
        assert len(failures) == 1
        assert "error" in failures[0]


# =========================================================================
# 9. deep_crawl non-list result branch
# =========================================================================


class TestDeepCrawlNonList:
    async def test_deep_crawl_single_result(self, client, mock_crawl_result):
        """deep_crawl wraps a single (non-list) arun result into a list."""
        c, mock_crawler = client
        # Return a single result, not a list — exercises the isinstance branch
        mock_crawler.arun = AsyncMock(return_value=mock_crawl_result)
        result = await c.call_tool("deep_crawl", {"url": "https://example.com"})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)
        assert data["seed_url"] == "https://example.com"
        assert data["pages_crawled"] == 1
        assert len(data["results"]) == 1


# =========================================================================
# 10. deep_crawl with include_external
# =========================================================================


class TestDeepCrawlIncludeExternal:
    async def test_deep_crawl_include_external(self, client, mock_crawl_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=[mock_crawl_result])

        with patch("crawl4ai_mcp.server.BFSDeepCrawlStrategy") as mock_bfs:
            mock_bfs.return_value = MagicMock()
            await c.call_tool(
                "deep_crawl",
                {"url": "https://example.com", "include_external": True},
            )
            # Verify BFSDeepCrawlStrategy was called with include_external=True
            mock_bfs.assert_called_once()
            call_kwargs = mock_bfs.call_args.kwargs
            assert call_kwargs.get("include_external") is True


# =========================================================================
# 11. execute_js output content assertion
# =========================================================================


class TestExecuteJsContent:
    async def test_execute_js_returns_page_content(self, client, mock_crawl_result):
        c, mock_crawler = client
        # Set a specific fit_markdown value to verify it's returned
        mock_crawl_result.markdown.fit_markdown = "JavaScript executed content here."
        mock_crawler.arun = AsyncMock(return_value=mock_crawl_result)
        result = await c.call_tool(
            "execute_js",
            {"url": "https://example.com", "js_code": "document.title"},
        )
        text = result.content[0].text if hasattr(result, "content") else str(result)
        assert "JavaScript executed content here." in text

    async def test_execute_js_failed_crawl(self, client, mock_failed_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=mock_failed_result)
        with pytest.raises(ToolError, match="JS execution failed"):
            await c.call_tool(
                "execute_js",
                {"url": "https://example.com", "js_code": "document.title"},
            )


# =========================================================================
# 12. _extract_markdown fallback paths
# =========================================================================


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

    def test_extract_markdown_prefers_fit_over_raw(self):
        result = MagicMock()
        md = MagicMock()
        md.fit_markdown = "fit content"
        md.raw_markdown = "raw content"
        result.markdown = md
        assert _extract_markdown(result) == "fit content"

    def test_extract_markdown_falls_to_raw_when_fit_empty(self):
        result = MagicMock()
        md = MagicMock()
        md.fit_markdown = ""  # empty — falsy
        md.raw_markdown = "raw content"
        result.markdown = md
        assert _extract_markdown(result) == "raw content"


# =========================================================================
# 13. SSRF validation
# =========================================================================


class TestSSRFProtection:
    def test_private_ip_loopback(self):
        with pytest.raises(ToolError, match="Private/loopback"):
            _validate_url("http://127.0.0.1/foo")

    def test_private_ip_10_range(self):
        with pytest.raises(ToolError, match="Private/loopback"):
            _validate_url("http://10.0.0.1/admin")

    def test_private_ip_192_range(self):
        with pytest.raises(ToolError, match="Private/loopback"):
            _validate_url("http://192.168.1.1/config")


# =========================================================================
# 14. Helper edge cases
# =========================================================================


class TestHelperEdgeCases:
    def test_get_crawler_no_context(self):
        with pytest.raises(ToolError, match="Crawler not available"):
            _get_crawler(None)

    def test_extract_markdown_unknown_object_fallback(self):
        """Non-str markdown with no fit/raw attrs falls back to cleaned_html."""
        result = MagicMock()
        md = MagicMock(spec=[])  # spec=[] removes all attrs
        result.markdown = md
        result.cleaned_html = "<p>fallback</p>"
        result.html = "<html>raw</html>"
        assert _extract_markdown(result) == "<p>fallback</p>"

    def test_select_content_invalid_format(self):
        result = MagicMock()
        with pytest.raises(ToolError, match="Unknown output_format"):
            _select_content(result, "xml")


# =========================================================================
# 15. Failed crawl paths (per-tool)
# =========================================================================


class TestFailedCrawlPaths:
    async def test_extract_data_failed_crawl(self, client, mock_failed_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=mock_failed_result)
        schema = {
            "name": "Items",
            "baseSelector": ".item",
            "fields": [{"name": "title", "selector": "h2", "type": "text"}],
        }
        with pytest.raises(ToolError, match="Extraction failed"):
            await c.call_tool("extract_data", {"url": "https://example.com", "schema": schema})

    async def test_screenshot_failed_crawl(self, client, mock_failed_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=mock_failed_result)
        with pytest.raises(ToolError, match="Screenshot failed"):
            await c.call_tool("take_screenshot", {"url": "https://example.com"})

    async def test_get_links_failed_crawl(self, client, mock_failed_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=mock_failed_result)
        with pytest.raises(ToolError, match="Link extraction failed"):
            await c.call_tool("get_links", {"url": "https://example.com"})

    async def test_get_page_info_failed_crawl(self, client, mock_failed_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=mock_failed_result)
        with pytest.raises(ToolError, match="Page inspection failed"):
            await c.call_tool("get_page_info", {"url": "https://example.com"})

    async def test_deep_crawl_mixed_results(self, client, mock_crawl_result, mock_failed_result):
        c, mock_crawler = client
        mock_crawler.arun = AsyncMock(return_value=[mock_crawl_result, mock_failed_result])
        result = await c.call_tool("deep_crawl", {"url": "https://example.com"})
        text = result.content[0].text if hasattr(result, "content") else str(result)
        data = json.loads(text)
        assert data["pages_crawled"] == 2
        has_error = any("error" in p for p in data["results"])
        assert has_error


# =========================================================================
# 16. Prompt tests
# =========================================================================


class TestPrompts:
    async def test_summarize_page_prompt(self, client):
        c, _ = client
        prompt = await c.get_prompt("summarize_page", {"url": "https://example.com"})
        assert len(prompt.messages) == 1
        assert "crawl_url" in prompt.messages[0].content.text
        assert "https://example.com" in prompt.messages[0].content.text

    async def test_build_extraction_schema_prompt(self, client):
        c, _ = client
        prompt = await c.get_prompt(
            "build_extraction_schema",
            {"url": "https://example.com", "data_type": "products"},
        )
        assert len(prompt.messages) == 1
        assert "extract_data" in prompt.messages[0].content.text
        assert "products" in prompt.messages[0].content.text

    async def test_compare_pages_prompt(self, client):
        c, _ = client
        prompt = await c.get_prompt(
            "compare_pages",
            {"url1": "https://a.com", "url2": "https://b.com"},
        )
        assert len(prompt.messages) == 1
        text = prompt.messages[0].content.text
        assert "https://a.com" in text
        assert "https://b.com" in text


# =========================================================================
# 17. Entrypoint tests
# =========================================================================


class TestMain:
    def test_main_stdio(self):
        from crawl4ai_mcp.server import main
        from crawl4ai_mcp.server import mcp as _mcp

        with (
            patch("sys.argv", ["crawl4ai-mcp"]),
            patch.object(_mcp, "run") as mock_run,
        ):
            main()
            mock_run.assert_called_once_with()

    def test_main_http(self):
        from crawl4ai_mcp.server import main
        from crawl4ai_mcp.server import mcp as _mcp

        with (
            patch(
                "sys.argv",
                ["crawl4ai-mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "9000"],
            ),
            patch.object(_mcp, "run") as mock_run,
        ):
            main()
            mock_run.assert_called_once_with(transport="http", host="0.0.0.0", port=9000)


# =========================================================================
# 18. Smoke tests
# =========================================================================


class TestSmoke:
    @pytest.mark.smoke
    def test_server_import(self):
        from crawl4ai_mcp.server import mcp as _mcp

        assert _mcp.name == "crawl4ai"
