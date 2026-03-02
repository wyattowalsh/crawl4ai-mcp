# Manual / Live Tests

These tests require a running browser (Playwright/Chromium) and network access.

## Prerequisites

```bash
uv sync
crawl4ai-setup   # install browser
```

## Run

```bash
uv run python tests/manual/test_live.py
```

## What it exercises

| Component | Test |
|-----------|------|
| `crawl_url` | Crawl example.com, verify markdown output |
| `crawl_many` | Batch crawl 2 URLs |
| `get_page_info` | Metadata extraction |
| `get_links` | Link categorization |
| `take_screenshot` | Base64 PNG capture |
| `config://server` | Server config resource |
| `crawl4ai://version` | Version resource |
| `summarize_page` | Prompt template |

## Expected

All tools respond without errors and return non-empty content.
