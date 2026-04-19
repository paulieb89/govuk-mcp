# Canonical audit — govuk-mcp — 2026-04-19

Run via the BOUCH MCP canonical audit prompt
(`bouch-pages/docs/mcp-canonical-audit-prompt.md`).

## 1. Per-surface verdicts

No resource templates currently registered. The repo exposes only five tools via `govuk_mcp/server.py:209-457`.

| Surface | Type | Verdict | Notes |
|---|---|---|---|
| `govuk_search` | tool | ✅ canonical | Verb surface, bounded, paginated by `count`/`start` (`server.py:219-288`). Live at `query="tax", count=50`: ~5.8k tokens. Explicit JSON Accept header set on shared client (`server.py:54-60`). |
| `govuk_get_content` | tool | 🔴 anti-pattern | Fetch-by-identifier as a tool (`server.py:291-355`). Returns raw details + all link groups (`models.py:105-149`). **Live measurement on `/guidance/planning-guidance-letters-to-chief-planning-officers`: ~270,721 tokens.** Repo already knows this is the danger surface (`tests/live/run_matrix.py:5-9`). |
| `govuk_get_organisation` | tool | 🟡 improvement | Bounded (~66 tokens on `hm-revenue-customs`), well-described, but noun-by-identifier (`server.py:358-390`) — fits a resource template better. |
| `govuk_list_organisations` | tool | ✅ canonical | Browse/list verb with explicit pagination (`server.py:393-444`). Live at `per_page=50`: ~1.5k tokens. |
| `govuk_lookup_postcode` | tool | 🟡 improvement | Small (~343 tokens), bounded, but still fetch-by-identifier (`server.py:447-495`). Could stay a tool if you want explicit normalisation/validation, also fits a resource template cleanly. |

## 2. Specific improvements

- 🔴 **`govuk_get_content`**: replace single mega-tool with resource templates keyed by base path; the current shape (`server.py:301-355`, `models.py:136-149`) can return hundreds of thousands of tokens for a normal search-discovered page.
- 🔴 **`govuk_get_content`**: don't keep "full document" as the primary navigation primitive; add structural drill-down instead of forcing the caller to absorb details wholesale.
- 🟡 **`govuk_get_organisation`**: convert to a resource template such as `govuk://organisation/{slug}` (`server.py:368`).
- 🟡 **`govuk_lookup_postcode`**: consider a resource template variant for pure read access; keep tool only if normalisation/validation semantics matter.
- 🟡 **Add `ResponseCachingMiddleware`** at the server level; every exposed surface is `readOnlyHint=True`, `idempotentHint=True` (`server.py:209-455`), no caching middleware registered anywhere.
- 🟡 **Add `ResourcesAsTools`** at the fleet gateway once resources exist — instead of hand-writing `get_*` tool duplicates.
- ✅ Keep the shared HTTP client pattern; explicit JSON content negotiation already correct (`server.py:56-60`).

## 3. Missing primitives

- `govuk://content/{base_path*}/header` — bounded metadata/header resource for a content item
- `govuk://content/{base_path*}/details/{field}` (or small explicit sub-resources) — current details blob has no drill-down primitive
- `govuk://content/{base_path*}/links/{rel}` — linked content currently bundled whole instead of navigable by relation
- A search-within-content verb for very large guides/manual collections; without it the only path from `govuk_search` to "read the page" is the 270k-token mega-read
- `govuk://organisation/{slug}` — bounded noun resource replacing `govuk_get_organisation`
- A postcode resource template if the fleet wants canonical noun access for lookup results
- `ResourcesAsTools` at the gateway, paired with the new resources, so ChatGPT/Apps-style tool-only clients can still reach them

## Filed as

paulieb89/govuk-mcp#1 (P1)
