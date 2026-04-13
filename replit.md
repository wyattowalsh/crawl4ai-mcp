# MCP-Crawl4AI on Replit

## Overview
This is an MCP (Model Context Protocol) server for web crawling, built on FastMCP v3 and Crawl4AI. It exposes web crawling tools, resources, and prompts through the MCP protocol with a headless Chromium browser.

## Architecture
- **Language**: Python 3.13
- **Package manager**: uv (via Nix system package)
- **Virtual environment**: `.venv313/` (Python 3.13 venv)
- **Main package**: `mcp_crawl4ai/` — MCP server implementation
- **Entry point**: `mcp_crawl4ai/server.py` → `main()`

## Running on Replit
The server runs via the "Start application" workflow:
```
LD_LIBRARY_PATH=/nix/store/24w3s75aa2lrvvxsybficn8y3zxd27kp-mesa-libgbm-25.1.0/lib:$LD_LIBRARY_PATH .venv313/bin/python -m mcp_crawl4ai.server --transport http --host 0.0.0.0 --port 8000
```

The `LD_LIBRARY_PATH` is required because Chromium (used by Playwright) needs `libgbm.so.1` from Mesa, which is installed via Nix but not on the default library path.

### Transport
The server runs in HTTP transport mode on port 8000. The MCP endpoint is:
```
http://0.0.0.0:8000/mcp
```

## Dependencies
### System (via Nix)
- `uv` — Python package manager
- `libxml2`, `libxslt`, `pkg-config` — for lxml
- `nss`, `nspr`, `atk`, `cups`, `at-spi2-atk`, `libdrm`, `libxkbcommon` — Playwright browser deps
- `xorg.libXcomposite`, `xorg.libXdamage`, `xorg.libXfixes`, `xorg.libXrandr` — Playwright browser deps
- `mesa`, `pango`, `cairo`, `alsa-lib` — Playwright browser deps
- `dbus`, `glib`, `expat`, `xorg.libXcursor`, `xorg.libXi`, `xorg.libXtst` — Playwright browser deps
- `xorg.libX11`, `xorg.libXext`, `xorg.libXrender`, `libGL`, `gdk-pixbuf`, `gtk3` — Playwright browser deps
- `at-spi2-core`, `xorg.libxcb`, `systemd` — Playwright browser deps

### Python (via uv in `.venv313/`)
- `fastmcp>=3.0.0`
- `crawl4ai>=0.8.0`
- `pydantic-settings>=2.0`

## Playwright Browsers
Chromium is downloaded and stored in `.cache/ms-playwright/`. The browser was installed with:
```
.venv313/bin/python -m patchright install chromium
```

## MCP Tools
- `scrape` — Single-page web scraping
- `crawl` — Multi-page/deep crawling
- `close_session` — Session lifecycle management
- `get_artifact` — Retrieve captured artifacts (MHTML, PDF, console, network logs)

## MCP Resources
- Server configuration
- Version info

## MCP Prompts
- Summarize page
- Extract schema
- Compare pages
