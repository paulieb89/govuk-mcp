# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

govuk-mcp is an MCP server exposing UK government data through **7 read-only tools** and **6 resource templates**. All external APIs are public and require no authentication.

### Tools

| Tool | What it does |
|------|--------------|
| `govuk_search` | Full-text search across GOV.UK's 700k+ content items |
| `govuk_grep_content` | Regex/substring search within a specific GOV.UK page body |
| `govuk_get_content` | Page metadata + navigable section index by base_path |
| `govuk_get_section` | Body HTML for a single named section (anchor) of a page |
| `govuk_get_organisation` | Full organisation profile by slug |
| `govuk_list_organisations` | Paginated list of all UK government organisations |
| `govuk_lookup_postcode` | Resolve a UK postcode to local authority, region, constituency |

`govuk_get_content`, `govuk_get_section`, and `govuk_get_organisation` are **named companion tools** (lesson 35 pattern) — they serve tool-only clients (ChatGPT, Ledgerhall proxy) with clean `dict`/Pydantic returns. Protocol-aware clients (Claude, Cursor) can use the equivalent `govuk://` resources directly.

### Resources (govuk:// URI templates)

For protocol-aware clients. Same underlying data as the companion tools, but URI-addressed and bounded.

| URI template | Returns |
|---|---|
| `govuk://content/{base_path*}/header` | Page metadata (title, doc type, dates) |
| `govuk://content/{base_path*}/index` | Section anchor:heading list |
| `govuk://content/{base_path*}/section/{anchor}` | Bounded HTML for one section |
| `govuk://content/{base_path*}/details/{field}` | Schema-specific details field (body, attachments, etc.) |
| `govuk://content/{base_path*}/links/{rel}` | Related content by link type |
| `govuk://organisation/{slug}` | Organisation profile |

## Commands

```bash
uv sync --group dev   # Install dependencies including dev/test tools
uv run govuk-mcp      # Run server on http://localhost:8000/mcp
fly deploy            # Deploy to Fly.io (https://govuk-mcp.fly.dev/mcp)
```

```bash
# Run live matrix test (calls all 9 cases in-process, prints token table)
uv run python -m tests.live.run_matrix
```

## Architecture

```
govuk_mcp/
  server.py     — FastMCP instance, lifespan, input models, all 7 tools
  resources.py  — govuk:// resource template registrations
  parsers.py    — Pure-function HTML extraction (extract_header, extract_index, extract_section, grep_body)
  models.py     — Output Pydantic models (GovukSearchResult, GovukOrganisation, GovukPostcode, ...)
```

### Key patterns

- **Lifespan-managed httpx client** — single `AsyncClient` per process, injected via `ctx.lifespan_context["client"]`
- **`_client(ctx)`** — typed accessor for the shared client
- **`_fmt_org(org)`** — normalises GOV.UK Organisations API response → `GovukOrganisation`
- **Parsers are pure functions** — take raw Content API payload dict, no HTTP, offline-testable
- **Input models use `extra="forbid"`** — rejects hallucinated parameters from tool-only clients
- **Tools return Pydantic models or dicts** — FastMCP auto-generates outputSchema and structuredContent
- **Resources return `str`** — MCP resource contract; complex data serialised via `json.dumps()`

### Middleware / transforms

```python
register_govuk_resources(mcp)   # govuk:// resource templates (protocol-aware clients)

mcp.add_middleware(ResponseCachingMiddleware(
    read_resource_settings=ReadResourceSettings(ttl=3600),
    call_tool_settings=CallToolSettings(ttl=3600),
))
```

`ResourcesAsTools` is intentionally **not used** — it double-encodes resource `str` returns as `{"result": "..."}`, breaking tool-only clients (lesson 34). Named companion tools are the correct pattern (lesson 35).

## External APIs

| API | Base URL | Auth |
|-----|----------|------|
| GOV.UK Search | `https://www.gov.uk/api/search.json` | None |
| GOV.UK Content | `https://www.gov.uk/api/content` | None |
| GOV.UK Organisations | `https://www.gov.uk/api/organisations` | None |
| postcodes.io | `https://api.postcodes.io` | None |

## Deployment

Fly.io, London region (lhr), shared-cpu-1x/256MB. Always-on (min 1 machine). Config in `fly.toml`.

Secrets: none required (all APIs are public).
