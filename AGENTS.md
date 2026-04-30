# AGENTS.md — govuk-mcp

AI agent instructions for working in this repo. See `/home/bch/dev/ops/OPS.md` for credentials, fleet overview, and release tooling.

## Repo shape

Single `server.py`. Tools: govuk_search, govuk_get_content, govuk_get_section, govuk_grep_content, govuk_get_organisation, govuk_list_organisations, govuk_lookup_postcode.

## Deploy

Auto-deploy on push to main via GitHub Actions (`.github/workflows/fly-deploy.yml`).
Manual: `fly deploy --ha=false`

Single instance, lhr region. App name: `govuk-mcp`. Fly.io account: articat1066@gmail.com.

## Version bump

1. Update `version` in `pyproject.toml`
2. Update version string in the `smithery_server_card` route in `server.py`
3. Commit, tag `vX.Y.Z`, push + push tags
4. GitHub Actions publishes to PyPI and deploys to Fly automatically on tag
5. Cut a new Glama release

## Standard routes (must always be present)

- `/.well-known/mcp/server-card.json` — Smithery metadata
- `/.well-known/glama.json` — Glama maintainer claim
- `/health` — Fly health check

Verify after deploy:
```bash
curl https://govuk-mcp.fly.dev/.well-known/mcp/server-card.json
curl https://govuk-mcp.fly.dev/.well-known/glama.json
curl https://govuk-mcp.fly.dev/health
```

## README badge order

```
PyPI → SafeSkill → Glama card → Smithery
```

## Do not

- Do not use `FASTMCP_PORT` — the server reads `PORT` env var only
- Do not set `internal_port` in fly.toml to anything other than 8080
- Do not commit API keys — all secrets are in Fly secrets (`fly secrets list`)
