"""Manual live test — requires crawl4ai-setup (browser installed).

Run: uv run python tests/manual/test_live.py
"""

from __future__ import annotations

import asyncio
import json

from fastmcp import Client

from mcp_crawl4ai.server import mcp


async def main() -> None:
    async with Client(mcp) as c:
        tools = await c.list_tools()
        resources = await c.list_resources()
        prompts = await c.list_prompts()
        print(f"Tools ({len(tools)}): {sorted(t.name for t in tools)}")
        print(f"Resources ({len(resources)}): {sorted(str(r.uri) for r in resources)}")
        print(f"Prompts ({len(prompts)}): {sorted(p.name for p in prompts)}")
        print()

        config = await c.read_resource("config://server")
        print(f"config://server → {config[0].text[:200]}")
        version = await c.read_resource("crawl4ai://version")
        print(f"crawl4ai://version → {version[0].text}")
        print()

        scrape_result = await c.call_tool("scrape", {"targets": "https://example.com"})
        scrape_data = json.loads(scrape_result.content[0].text)
        print(f"scrape → ok={scrape_data['ok']}, url={scrape_data['data']['url']}")
        print()

        crawl_result = await c.call_tool(
            "crawl",
            {
                "targets": ["https://example.com", "https://httpbin.org/get"],
                "options": {"traversal": {"mode": "list"}},
            },
        )
        crawl_data = json.loads(crawl_result.content[0].text)
        item_count = len(crawl_data.get("items") or [])
        print(f"crawl → ok={crawl_data['ok']}, items={item_count}")
        print()

        prompt = await c.get_prompt("summarize_page", {"url": "https://example.com"})
        print(f"summarize_page prompt → {prompt.messages[0].content.text}")

    print("\n✅ Manual live test completed")


if __name__ == "__main__":
    asyncio.run(main())
