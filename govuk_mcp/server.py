"""GOV.UK MCP Server — search and content tools for the UK government's public estate."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from fastmcp import Context, FastMCP
from fastmcp.server.middleware.caching import (
    CallToolSettings,
    ReadResourceSettings,
    ResponseCachingMiddleware,
)
from fastmcp.server.transforms import ResourcesAsTools
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from govuk_mcp.models import (
    GovukLocalAuthority,
    GovukOrganisation,
    GovukOrganisationsList,
    GovukPostcode,
    GovukSearchOrganisation,
    GovukSearchResult,
    GovukSearchResultItem,
    GrepContentInput,
    GrepContentResult,
    GrepHit,
)
from govuk_mcp.resources import register_govuk_resources
from govuk_mcp import parsers

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEARCH_BASE = "https://www.gov.uk/api/search.json"
CONTENT_BASE = "https://www.gov.uk/api/content"
ORGANISATIONS_BASE = "https://www.gov.uk/api/organisations"
LOCATIONS_BASE = "https://api.postcodes.io"  # public, no key required

TIMEOUT = 15.0
MAX_COUNT = 50

DOCUMENT_FORMATS = [
    "guide", "answer", "transaction", "smart_answer", "simple_smart_answer",
    "place", "local_transaction", "special_route", "calendar", "calculator",
    "licence", "completed_transaction", "help_page", "manual", "manual_section",
    "organisation", "finder", "taxon", "topic", "mainstream_browse_page",
    "travel_advice", "news_article", "speech", "press_release", "publication",
    "consultation", "statistics_announcement", "statistical_data_set",
    "fatality_notice", "world_news_article", "detailed_guide", "hmrc_manual",
    "hmrc_manual_section", "document_collection",
]


# ---------------------------------------------------------------------------
# HTTP Client (lifespan-managed)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(server: FastMCP):
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(TIMEOUT),
        headers={"Accept": "application/json", "User-Agent": "govuk-mcp/1.0"},
        follow_redirects=True,
    ) as client:
        yield {"client": client}


mcp = FastMCP(
    "govuk_mcp",
    instructions=(
        "Tools for searching GOV.UK and resolving UK postcodes to local authority areas. "
        "All data is sourced from official GOV.UK APIs. "
        "Use govuk_search first to find content; then read it via the drill-down "
        "resources govuk://content/{base_path}/{header,index,section/{anchor},details/{field},links/{rel}}. "
        "For content discovery, use govuk_grep_content. "
        "Look up an organisation by slug via govuk://organisation/{slug} or browse all via govuk_list_organisations. "
        "Use govuk_lookup_postcode to resolve a UK postcode to administrative geography."
    ),
    lifespan=lifespan,
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok", "server": "govuk-mcp"})


@mcp.custom_route("/.well-known/glama.json", methods=["GET"])
async def glama_connector_manifest(request):
    return JSONResponse({
        "$schema": "https://glama.ai/mcp/schemas/connector.json",
        "maintainers": [{"email": "paulboucherat@gmail.com"}],
    })


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _client(ctx: Context) -> httpx.AsyncClient:
    return ctx.lifespan_context["client"]


def _fmt_org(org: dict[str, Any]) -> GovukOrganisation:
    """Flatten a single organisation record to a GovukOrganisation model."""
    details = org.get("details") or {}
    slug = details.get("slug") or org.get("slug") or ""
    contacts = details.get("contact_details") or org.get("contact_details")
    return GovukOrganisation(
        title=org.get("title"),
        acronym=details.get("acronym") or org.get("acronym"),
        slug=slug or None,
        type=details.get("organisation_type") or org.get("organisation_type"),
        state=details.get("govuk_status") or org.get("organisation_state"),
        web_url=org.get("web_url")
        or (f"https://www.gov.uk/government/organisations/{slug}" if slug else None),
        parent_organisations=[
            p.get("title") for p in org.get("parent_organisations", []) if p.get("title")
        ],
        child_organisations=[
            c.get("title") for c in org.get("child_organisations", []) if c.get("title")
        ],
        contact_details=contacts if contacts else None,
    )


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

class SearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        ...,
        description="Free-text search query, e.g. 'universal credit eligibility' or 'MOT check'",
        min_length=1,
        max_length=500,
    )
    count: int = Field(
        default=10,
        description="Number of results to return (1–50)",
        ge=1,
        le=MAX_COUNT,
    )
    start: int = Field(
        default=0,
        description="Offset for pagination, e.g. 10 for the second page of 10 results",
        ge=0,
    )
    filter_format: Optional[str] = Field(
        default=None,
        description=(
            "Filter by document format. Common values: 'guide', 'answer', 'transaction', "
            "'publication', 'news_article', 'detailed_guide', 'hmrc_manual_section', "
            "'travel_advice', 'organisation'. Leave blank to search all types."
        ),
    )
    filter_organisations: Optional[str] = Field(
        default=None,
        description=(
            "Filter by organisation slug, e.g. 'hm-revenue-customs', "
            "'department-for-work-pensions', 'driver-and-vehicle-standards-agency'."
        ),
    )
    order: Optional[str] = Field(
        default=None,
        description="Sort order. Use '-public_timestamp' for newest-first (default relevance).",
    )


class OrganisationsListInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    page: int = Field(default=1, description="Page number (1-based)", ge=1)
    per_page: int = Field(default=20, description="Results per page (1–50)", ge=1, le=50)


class PostcodeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    postcode: str = Field(
        ...,
        description="UK postcode, e.g. 'SW1A 2AA' or 'NG1 1AA'. Spaces optional.",
        min_length=5,
        max_length=8,
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="govuk_search",
    annotations={
        "title": "Search GOV.UK",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def govuk_search(params: SearchInput, ctx: Context) -> GovukSearchResult:
    """Search GOV.UK's 700k+ content items using the official Search API.

    Returns a list of matching content items with title, description, link,
    format, owning organisation(s), and last updated timestamp.

    Use filter_format to narrow to specific content types (e.g. 'transaction'
    for citizen-facing services, 'guide' for guidance, 'publication' for
    official documents). Use filter_organisations to restrict to a department.

    Args:
        params: SearchInput with query, count, start, optional format/org
            filters, and optional sort order.
    """
    client = _client(ctx)

    query_params: dict[str, Any] = {
        "q": params.query,
        "count": params.count,
        "start": params.start,
        "fields[]": ["title", "description", "link", "format", "organisations", "public_timestamp"],
    }
    if params.filter_format:
        query_params["filter_document_type"] = params.filter_format
    if params.filter_organisations:
        query_params["filter_organisations"] = params.filter_organisations
    if params.order:
        query_params["order"] = params.order

    resp = await client.get(SEARCH_BASE, params=query_params)
    resp.raise_for_status()
    data = resp.json()

    raw_results = data.get("results", [])
    results: list[GovukSearchResultItem] = []
    for r in raw_results:
        orgs = [
            GovukSearchOrganisation(
                title=o.get("title"),
                acronym=o.get("acronym"),
                slug=o.get("slug"),
            )
            for o in r.get("organisations", [])
        ]
        link = r.get("link") or ""
        base = link.lstrip("/")
        results.append(
            GovukSearchResultItem(
                title=r.get("title"),
                description=r.get("description"),
                link=link or None,
                url=f"https://www.gov.uk{link}" if link else None,
                format=r.get("format"),
                organisations=orgs,
                public_timestamp=r.get("public_timestamp"),
                next_steps=({
                    "header": f"govuk://content/{base}/header",
                    "index": f"govuk://content/{base}/index",
                    "section_template": f"govuk://content/{base}/section/{{anchor}}",
                    "details_template": f"govuk://content/{base}/details/{{field}}",
                    "links_template": f"govuk://content/{base}/links/{{rel}}",
                    "grep_tool": f"govuk_grep_content(base_path={base!r}, pattern=...)",
                } if link else {}),
            )
        )

    total = data.get("total", 0) or 0
    returned = len(results)
    has_more = (params.start + returned) < total if isinstance(total, int) else returned == params.count

    return GovukSearchResult(
        query=params.query,
        total=total,
        start=params.start,
        count=params.count,
        returned=returned,
        has_more=has_more,
        results=results,
    )


@mcp.tool(
    name="govuk_grep_content",
    annotations={
        "title": "Search within a GOV.UK content body",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def govuk_grep_content(params: GrepContentInput, ctx: Context) -> GrepContentResult:
    """Find body sections in a GOV.UK content item matching a pattern.

    Returns a list of `{anchor, heading, snippet, match}` hits — small per-section
    snippets centred on the match — so the LLM can decide which full sections to
    read via `govuk://content/{base_path}/section/{anchor}`.

    Use this when answering content-based questions ("what does this guide say
    about X?", "find the bit about eligibility") rather than navigating by
    section number (which uses the index resource).

    Pattern is regex; if it doesn't compile, falls back to literal substring.
    """
    client = _client(ctx)
    clean = params.base_path.lstrip("/")
    resp = await client.get(f"{CONTENT_BASE}/{clean}")
    resp.raise_for_status()
    payload = resp.json()

    hits = parsers.grep_body(
        payload,
        params.pattern,
        case_insensitive=params.case_insensitive,
        max_hits=params.max_hits,
    )
    return GrepContentResult(
        base_path=clean,
        pattern=params.pattern,
        hits=[GrepHit(**h) for h in hits],
        truncated=len(hits) >= params.max_hits,
    )


@mcp.tool(
    name="govuk_list_organisations",
    annotations={
        "title": "List GOV.UK Organisations",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def govuk_list_organisations(
    params: OrganisationsListInput, ctx: Context
) -> GovukOrganisationsList:
    """List all UK government organisations registered on GOV.UK.

    Returns a paginated list of organisations including their slug, acronym,
    type, and status. Use this to browse the full government structure or
    discover slugs for use with govuk_get_organisation or govuk_search filters.

    Args:
        params: OrganisationsListInput with 1-based page and per_page (1–50).
    """
    client = _client(ctx)

    resp = await client.get(
        ORGANISATIONS_BASE,
        params={"page": params.page, "per_page": params.per_page},
    )
    resp.raise_for_status()
    data = resp.json()

    orgs = [_fmt_org(o) for o in data.get("results", [])]

    total = data.get("total")
    total_pages = data.get("pages")
    returned = len(orgs)
    if isinstance(total, int):
        has_more = (params.page * params.per_page) < total
    elif isinstance(total_pages, int):
        has_more = params.page < total_pages
    else:
        has_more = returned == params.per_page

    return GovukOrganisationsList(
        page=params.page,
        per_page=params.per_page,
        total=total if isinstance(total, int) else None,
        total_pages=total_pages if isinstance(total_pages, int) else None,
        returned=returned,
        has_more=has_more,
        organisations=orgs,
    )


@mcp.tool(
    name="govuk_lookup_postcode",
    annotations={
        "title": "Look Up UK Postcode",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def govuk_lookup_postcode(params: PostcodeInput, ctx: Context) -> GovukPostcode:
    """Look up a UK postcode to retrieve its local authority, region, constituency,
    and other administrative geography.

    Useful for determining which council area, parliamentary constituency, or
    NHS region a postcode falls within. Commonly used to direct users to the
    correct local service on GOV.UK (e.g. council tax, planning, waste).

    Uses the postcodes.io public API (no key required).

    Args:
        params: PostcodeInput with a UK postcode (e.g. 'NG1 1AA', 'SW1A 2AA').
    """
    client = _client(ctx)
    postcode = params.postcode.replace(" ", "").upper()
    url = f"{LOCATIONS_BASE}/postcodes/{postcode}"

    resp = await client.get(url)
    resp.raise_for_status()
    data = resp.json().get("result", {}) or {}

    codes = data.get("codes", {}) or {}

    return GovukPostcode(
        postcode=data.get("postcode"),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        country=data.get("country"),
        region=data.get("region"),
        parliamentary_constituency=data.get("parliamentary_constituency"),
        parliamentary_constituency_2025=data.get("parliamentary_constituency_2025"),
        local_authority=GovukLocalAuthority(
            name=data.get("admin_district"),
            code=codes.get("admin_district"),
        ),
        admin_county=data.get("admin_county"),
        nhs_integrated_care_board=data.get("integrated_care_board"),
        codes=codes,
    )


# ---------------------------------------------------------------------------
# Resources + transforms + caching (after tool registrations above)
# ---------------------------------------------------------------------------

# govuk:// resource templates — header, index, section, details, links,
# organisation. Replace the deleted govuk_get_content / govuk_get_organisation
# tools with bounded URI-addressed reads.
register_govuk_resources(mcp)

# Tool-only client coverage (Apps, ChatGPT, Ledgerhall proxy clients) —
# auto-generates list_resources + read_resource tools that route through the
# server's middleware chain. Without this, tool-only clients can't reach the
# new govuk:// resources.
mcp.add_transform(ResourcesAsTools(mcp))

# Response caching for resources/read AND tools/call. Every surface here is
# read-only/idempotent, GOV.UK content is stable enough that 1h is the right
# TTL. In-memory only (single Fly machine).
mcp.add_middleware(ResponseCachingMiddleware(
    read_resource_settings=ReadResourceSettings(ttl=3600),
    call_tool_settings=CallToolSettings(ttl=3600),
))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    mcp.run(transport="http", host="0.0.0.0", port=8000, stateless_http=True)


if __name__ == "__main__":
    main()
