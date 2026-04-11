# govuk-mcp

MCP server for GOV.UK — search, content retrieval, organisation lookup, and postcode resolution.

## Tools

| Tool | Description |
|---|---|
| `govuk_search` | Full-text search across 700k+ GOV.UK pages, with format and organisation filters |
| `govuk_get_content` | Retrieve the full structured content item for any GOV.UK page by base path |
| `govuk_get_organisation` | Get details for a UK government organisation (type, parent, children, contacts) |
| `govuk_list_organisations` | Paginated list of all government organisations registered on GOV.UK |
| `govuk_lookup_postcode` | Resolve a UK postcode to local authority, region, constituency, and NHS board |

All data is sourced from official public GOV.UK APIs and postcodes.io. No API keys required.

## Usage (Claude Desktop / claude.ai)

```json
{
  "mcpServers": {
    "govuk": {
      "url": "https://govuk-mcp.fly.dev/mcp"
    }
  }
}
```
