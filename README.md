# govuk-mcp

[![govuk-mcp MCP server](https://glama.ai/mcp/servers/paulieb89/govuk-mcp/badges/card.svg)](https://glama.ai/mcp/servers/paulieb89/govuk-mcp)
[![smithery badge](https://smithery.ai/badge/bouch/govuk)](https://smithery.ai/servers/bouch/govuk)

MCP server for GOV.UK — search, content retrieval, organisation lookup, and postcode resolution.

## Tools

| Tool | Description |
|---|---|
| `govuk_search` | Full-text search across 700k+ GOV.UK pages, with format and organisation filters |
| `govuk_get_content` | Page metadata and navigable section index for any GOV.UK page by base path |
| `govuk_get_section` | Body HTML for a single named section (anchor) of a GOV.UK page |
| `govuk_grep_content` | Regex/substring search within the body of a specific GOV.UK page |
| `govuk_get_organisation` | Get details for a UK government organisation (type, parent, children, contacts) |
| `govuk_list_organisations` | Paginated list of all government organisations registered on GOV.UK |
| `govuk_lookup_postcode` | Resolve a UK postcode to local authority, region, constituency, and NHS board |

All data is sourced from official public GOV.UK APIs and postcodes.io. No API keys required.

## Resources

For protocol-aware clients (Claude, Cursor, Inspector), the server also exposes `govuk://` resource templates:

| URI | Returns |
|-----|---------|
| `govuk://content/{base_path*}/header` | Page metadata (title, doc type, dates) |
| `govuk://content/{base_path*}/index` | Section anchor:heading list |
| `govuk://content/{base_path*}/section/{anchor}` | Bounded HTML for one section |
| `govuk://content/{base_path*}/details/{field}` | Schema-specific details field |
| `govuk://content/{base_path*}/links/{rel}` | Related content by link type |
| `govuk://organisation/{slug}` | Organisation profile |

## Quick start

### Remote (no install)

Point any MCP client at the hosted server:

```json
{
  "mcpServers": {
    "govuk": {
      "type": "http",
      "url": "https://govuk-mcp.fly.dev/mcp"
    }
  }
}
```

### Local (pip install)

```bash
pip install govuk-mcp
govuk-mcp
# MCP endpoint: http://localhost:8000/mcp
```

### Local (Claude Desktop)

```bash
fastmcp install claude-desktop govuk-mcp
```

## APIs used

| API | Base URL | Auth |
|-----|----------|------|
| GOV.UK Search | `https://www.gov.uk/api/search.json` | None |
| GOV.UK Content | `https://www.gov.uk/api/content{path}` | None |
| GOV.UK Organisations | `https://www.gov.uk/api/organisations` | None |
| postcodes.io | `https://api.postcodes.io` | None |

## License

MIT
