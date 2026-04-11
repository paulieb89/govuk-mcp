# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

govuk-mcp is an MCP (Model Context Protocol) server that exposes UK government data through 5 read-only tools: `govuk_search`, `govuk_get_content`, `govuk_get_organisation`, `govuk_list_organisations`, and `govuk_lookup_postcode`. All external APIs are public and require no authentication.

## Commands

```bash
pip install -e .       # Install in editable mode
govuk-mcp              # Run server on http://localhost:8000/mcp
fly deploy             # Deploy to Fly.io (https://govuk-mcp.fly.dev/mcp)
```

There are no tests, linting, or type-checking configured yet.

## Architecture

The entire server lives in a single file: `govuk_mcp/server.py` (536 lines). It uses:

- **FastMCP 2.0+** as the MCP framework (`@mcp.tool()` decorators)
- **httpx** async client for all outbound HTTP, managed via a FastMCP lifespan context manager
- **Pydantic** models for input validation (`ConfigDict(extra="forbid", str_strip_whitespace=True)`)

### Code structure within govuk_mcp/server.py

1. **Constants** (lines ~14-34) — API base URLs, timeout (15s), document format whitelist
2. **Lifespan** (lines ~41-61) — `httpx.AsyncClient` created once and shared via `lifespan_state["client"]`
3. **Helpers** (lines ~68-98) — `_client(ctx)` extracts the HTTP client from context; `_handle_http_error` maps status codes; `_fmt_org` flattens organisation records
4. **Input models** (lines ~105-191) — 5 Pydantic models with field descriptions that auto-generate MCP tool parameter hints
5. **Tools** (lines ~197-525) — 5 async tool functions, each returning JSON strings
6. **Entrypoint** (lines ~531-536) — `main()` runs streamable-http transport on port 8000

### Key pattern

Every tool follows the same structure: validate input via Pydantic model -> get shared httpx client from context -> make API call -> handle errors (404/429/timeout) -> extract/flatten relevant fields -> return `json.dumps()`.

## Package structure

`pyproject.toml` declares the entry point as `govuk_mcp.server:main` and the build target as `packages = ["govuk_mcp"]`. The Dockerfile copies `govuk_mcp/` into the container image.

## External APIs

| API | Base URL | Auth |
|-----|----------|------|
| GOV.UK Search | `https://www.gov.uk/api/search.json` | None |
| GOV.UK Content | `https://www.gov.uk/api/content{path}` | None |
| GOV.UK Organisations | `https://www.gov.uk/api/organisations` | None |
| postcodes.io | `https://api.postcodes.io` | None |

## Deployment

Fly.io, London region (lhr), shared-cpu-1x/256MB. Auto-scales to zero when idle. Config in `fly.toml`.
