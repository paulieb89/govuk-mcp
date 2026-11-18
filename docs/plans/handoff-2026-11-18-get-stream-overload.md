---
status: landed
repo: govuk-mcp
date: 2026-11-18
supersedes: none
sessions: one Claude Code session, 2026-11-18 (fleet README tests → govuk overload → 0.3.2)
---

# Handoff: held GET /mcp streams saturated prod (0.3.2)

## Purpose and scope

Find and fix why prod sat at its connection limit, and document local mode
honestly. Shape A of the fleet handoff template
([uk-due-diligence-mcp/docs/plans/TEMPLATE-handoff.md](https://github.com/paulieb89/uk-due-diligence-mcp/blob/main/docs/plans/TEMPLATE-handoff.md)).
Changes: [CHANGELOG 0.3.2](../../CHANGELOG.md), PRs #9 (fix), #10 (release), #5 (README).

## What shipped

- **0.3.2, tag `v0.3.2` → `7ab39ce`**, released 2026-11-18 ~18:37 UTC via `release.yml`.
  Rollback image recorded before release: Fly v42,
  `registry.fly.io/govuk-mcp:deployment-01M7GZJMPJAPYB0JMF5WRS2XJY`.
- Checks: prod `GET /mcp` → 405 in 0.1 s; server card = PyPI = Fly v43 = 0.3.2;
  7 tools; `govuk_lookup_postcode` works directly and through uk-business-mcp.
- `fly_app_concurrency`: 40–50 (hard limit 50) for 26 h+ before; no series after.
  Confirmed "no series" means zero, not missing data: three held test connections
  read exactly 3. Fly omits the series at zero and keeps the last non-zero value
  for ~5 min.
- README: one `## Connect` section; local stdio marked unsupported, and the
  "VS Code (local)" badge removed (#5).

## Root cause

`_HttpGuard` answered `GET /mcp` with 200 and held the stream open with nothing
sent. **Clients**, mostly Claude Code (12,839 connections in govuk's metrics), open
that optional stream and keep it, so each one held a connection slot. A 90 s log
sample showed 17 held GETs from 10 IPs against 37 POSTs.

**Not the proxy:** uk-business-mcp made 0–13 `gov_` calls per half-hour while govuk
sat at its limit all day, and the saturation predates the proxy's FastMCP 4
release. Symptoms were Fly "could not find a good candidate … load balancing"
errors, `/health` 14–30 s, and client timeouts. They never appeared as app-level
5xx, because the edge rejected the requests before they reached the app.

## Decisions

1. **Remove the shim and stay on FastMCP 3.2.4 for this release.** 3.2.4's native
   stateless handling already returns 405. Bumping FastMCP in the same release
   would have made it impossible to say which change fixed the overload.
2. **Document local mode as unsupported** rather than ship broken commands: the
   `govuk-mcp` console script starts HTTP, not stdio (#8).

## Gotchas

- With the guard in place, a `TestClient` GET test **hangs** on the held stream
  instead of failing. Run it under `timeout`.
- `fly logs --no-tail` returns only the last ~100 lines (≈5 min), which is too
  short to show that intermittent errors have stopped. Use metrics.

## Open issues

#11 · #8 · #6

## Recommended next step

FastMCP 4.1.8 (#11), with DD and legal (uk-due-diligence-mcp #49, uk-legal-mcp
#116), so the fleet runs one patch. Then a stdio entry point (#8, copying
uk-legal-mcp's `main_stdio`) and re-enable the README's local section.

## Re-verify

```bash
curl -sS -m 10 -o /dev/null -w '%{http_code}\n' -H 'Accept: text/event-stream' https://govuk-mcp.fly.dev/mcp   # 405
curl -s https://govuk-mcp.fly.dev/.well-known/mcp/server-card.json
# Fly Prometheus (Authorization: FlyV1 <fly auth token>): fly_app_concurrency{app="govuk-mcp"}
```
