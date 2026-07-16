"""govuk:// resource templates — Phase-4-style drill-down for content.

Replaces the deleted `govuk_get_content` and `govuk_get_organisation`
tools with bounded URI-addressed reads. Avoids the 270k-token blowout
the old `get_content` caused on heavy guidance pages.

Registered directly on the FastMCP server (no gateway/sub-MCP split in
this repo, so no issue-#3 concern).
"""

import json

import httpx
from fastmcp import Context, FastMCP

from . import parsers

CONTENT_API = "https://www.gov.uk/api/content"
ORG_API = "https://www.gov.uk/api/organisations"


async def _fetch_content(base_path: str, ctx: Context) -> dict:
    """Fetch a content item. Cached by ResponseCachingMiddleware at the
    server level — repeated reads of the same item cost one upstream call."""
    client: httpx.AsyncClient = ctx.lifespan_context["client"]
    clean = base_path.lstrip("/")
    resp = await client.get(f"{CONTENT_API}/{clean}")
    resp.raise_for_status()
    return resp.json()


def register_govuk_resources(mcp: FastMCP) -> None:
    """Register govuk:// resource templates."""

    @mcp.resource(
        "govuk://content/{base_path*}/header",
        name="GOV.UK content — metadata header",
        description=(
            "Metadata for a GOV.UK content item: title, description, "
            "document_type, schema_name, base_path, dates. ~1k tokens. "
            "Call this first to understand what an item is. base_path "
            "examples: 'guidance/planning-guidance-letters-...', "
            "'browse/visas-immigration', 'topic/business-tax/vat'."
        ),
        mime_type="application/json",
        annotations={"readOnlyHint": True, "idempotentHint": True},
        tags={"govuk", "content"},
    )
    async def govuk_content_header(base_path: str, ctx: Context) -> str:
        return json.dumps(parsers.extract_header(await _fetch_content(base_path, ctx)))

    @mcp.resource(
        "govuk://content/{base_path*}/index",
        name="GOV.UK content — section index",
        description=(
            "Newline-separated 'anchor: heading' rows for real <h2 id=...> "
            "sections in the body. Walk this to discover sections, then "
            "drill into specific ones via /section/{anchor}. For full-text "
            "discovery across the body, use the govuk_grep_content tool."
        ),
        mime_type="text/plain",
        annotations={"readOnlyHint": True, "idempotentHint": True},
        tags={"govuk", "content", "navigation"},
    )
    async def govuk_content_index(base_path: str, ctx: Context) -> str:
        return parsers.extract_index(await _fetch_content(base_path, ctx))

    @mcp.resource(
        "govuk://content/{base_path*}/section/{anchor}",
        name="GOV.UK content — single body section",
        description=(
            "Body HTML between <h2 id='anchor'> and the next <h2 id=...>. "
            "Use the index resource to discover available anchors."
        ),
        mime_type="text/html",
        annotations={"readOnlyHint": True, "idempotentHint": True},
        tags={"govuk", "content", "section"},
    )
    async def govuk_content_section(base_path: str, anchor: str, ctx: Context) -> str:
        return parsers.extract_section(await _fetch_content(base_path, ctx), anchor)

    @mcp.resource(
        "govuk://content/{base_path*}/details/{field}",
        name="GOV.UK content — details field",
        description=(
            "A specific field from the content item's `details` blob, e.g. "
            "'attachments', 'change_history', 'headers', 'tags'. Schema-"
            "dependent. The 'body' field is NOT served here — it can be "
            "270k+ tokens on guidance pages. Use /index + /section/{anchor} "
            "for navigable body access, or the govuk_grep_content tool for "
            "pattern search."
        ),
        mime_type="application/json",
        annotations={"readOnlyHint": True, "idempotentHint": True},
        tags={"govuk", "content", "details"},
    )
    async def govuk_content_details(base_path: str, field: str, ctx: Context) -> str:
        # The 'body' field is the entire rendered HTML of the content item.
        # Returning it via /details/{field} bypasses the drill-down design
        # this module exists to enforce. The original govuk_get_content tool
        # was deleted for exactly this reason (the 270k-token incident).
        # Force callers down the navigable path.
        if field == "body":
            raise ValueError(
                "The 'body' field is not served via /details/{field} because "
                "it can be 270k+ tokens on guidance pages. Use "
                "govuk://content/{base_path}/index to discover sections, "
                "then govuk://content/{base_path}/section/{anchor} to read "
                "one section at a time. For pattern search across the body, "
                "use the govuk_grep_content tool."
            )
        value = parsers.extract_details_field(await _fetch_content(base_path, ctx), field)
        # Non-body fields are JSON-serialised.
        return value if isinstance(value, str) else json.dumps(value)

    @mcp.resource(
        "govuk://content/{base_path*}/links/{rel}",
        name="GOV.UK content — link relation",
        description=(
            "Linked content for one relation, e.g. 'organisations', "
            "'taxons', 'related_mainstream'. Returns a list of link items "
            "with title and base_path."
        ),
        mime_type="application/json",
        annotations={"readOnlyHint": True, "idempotentHint": True},
        tags={"govuk", "content", "links"},
    )
    async def govuk_content_links(base_path: str, rel: str, ctx: Context) -> str:
        return json.dumps(parsers.extract_links(await _fetch_content(base_path, ctx), rel))

    @mcp.resource(
        "govuk://organisation/{slug}",
        name="GOV.UK organisation",
        description=(
            "Organisation profile by slug, e.g. 'hm-revenue-customs'. "
            "Companion resource for protocol-aware clients; "
            "tool-only clients use govuk_get_organisation instead."
        ),
        mime_type="application/json",
        annotations={"readOnlyHint": True, "idempotentHint": True},
        tags={"govuk", "organisation"},
    )
    async def govuk_organisation(slug: str, ctx: Context) -> str:
        client: httpx.AsyncClient = ctx.lifespan_context["client"]
        resp = await client.get(f"{ORG_API}/{slug}")
        resp.raise_for_status()
        return resp.text  # already JSON from the API
