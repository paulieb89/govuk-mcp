# govuk-mcp

MCP server for GOV.UK — search, content retrieval, organisation lookup, and postcode resolution. Deployed on Fly.io using FastMCP's streamable HTTP transport.

## Tools

| Tool | Description |
|---|---|
| `govuk_search` | Full-text search across 700k+ GOV.UK pages, with format and organisation filters |
| `govuk_get_content` | Retrieve the full structured content item for any GOV.UK page by base path |
| `govuk_get_organisation` | Get details for a UK government organisation (type, parent, children, contacts) |
| `govuk_list_organisations` | Paginated list of all government organisations registered on GOV.UK |
| `govuk_lookup_postcode` | Resolve a UK postcode to local authority, region, constituency, and NHS board |

## APIs used

- `https://www.gov.uk/api/search.json` — GOV.UK Search API (public, no auth)
- `https://www.gov.uk/api/content{path}` — GOV.UK Content API (public, no auth)
- `https://www.gov.uk/api/organisations` — GOV.UK Organisations API (public, no auth)
- `https://api.postcodes.io` — postcodes.io (public, no auth)

## Development

```bash
pip install -e .
govuk-mcp
# MCP endpoint: http://localhost:8000/mcp
```

## Deployment

```bash
fly launch --no-deploy     # first time only
fly deploy
```

MCP endpoint: `https://govuk-mcp.fly.dev/mcp`

## Usage example (Claude Desktop / claude.ai)

```json
{
  "mcpServers": {
    "govuk": {
      "url": "https://govuk-mcp.fly.dev/mcp"
    }
  }
}
```
