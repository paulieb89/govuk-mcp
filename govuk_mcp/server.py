"""GOV.UK MCP Server — search and content tools for the UK government's public estate."""

from __future__ import annotations

import functools
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any, Optional

import httpx
from fastmcp import Context, FastMCP
from fastmcp.server.middleware.caching import (
    CallToolSettings,
    ReadResourceSettings,
    ResponseCachingMiddleware,
)
from pydantic import Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter as PromCounter, Histogram, generate_latest
from starlette.responses import JSONResponse, Response

from govuk_mcp.models import (
    GovukLocalAuthority,
    GovukOrganisation,
    GovukOrganisationsList,
    GovukPostcode,
    GovukSearchOrganisation,
    GovukSearchResult,
    GovukSearchResultItem,
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

TRANSPORT = os.getenv("FASTMCP_TRANSPORT", "http")
REGION = os.getenv("FLY_REGION", "local")

tool_calls_total = PromCounter(
    "govuk_tool_calls_total",
    "Count of MCP tool invocations.",
    labelnames=["tool", "transport", "region", "status"],
)
tool_duration_seconds = Histogram(
    "govuk_tool_duration_seconds",
    "Tool invocation latency in seconds.",
    labelnames=["tool", "transport", "region"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def _timed_tool(fn):
    tool_name = fn.__name__

    @functools.wraps(fn)
    async def wrapped(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            result = await fn(*args, **kwargs)
            tool_calls_total.labels(tool_name, TRANSPORT, REGION, "ok").inc()
            return result
        except BaseException:
            tool_calls_total.labels(tool_name, TRANSPORT, REGION, "error").inc()
            raise
        finally:
            tool_duration_seconds.labels(tool_name, TRANSPORT, REGION).observe(
                time.perf_counter() - t0
            )

    return wrapped


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
        "Use govuk_search to find content, then govuk_get_content for page metadata and section list, "
        "govuk_get_section to read a specific section, govuk_grep_content to search within a page body. "
        "Use govuk_list_organisations to browse all government organisations and discover slugs, "
        "then govuk_get_organisation for a full profile. "
        "Use govuk_lookup_postcode to resolve a UK postcode to administrative geography."
    ),
    lifespan=lifespan,
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok", "server": "govuk-mcp"})


@mcp.custom_route("/metrics", methods=["GET"])
async def metrics_endpoint(request):
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"])
async def smithery_server_card(request):
    return JSONResponse({"serverInfo": {"name": "govuk-mcp", "version": "0.2.2"}})


@mcp.custom_route("/.well-known/glama.json", methods=["GET"])
async def glama_connector_manifest(request):
    return JSONResponse({
        "$schema": "https://glama.ai/mcp/schemas/connector.json",
        "maintainers": [{"email": "paul@bouch.dev"}],
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
@_timed_tool
async def govuk_search(
    query: Annotated[str, Field(description="Free-text search query, e.g. 'universal credit eligibility' or 'MOT check'", min_length=1, max_length=500)],
    ctx: Context,
    count: Annotated[int, Field(description="Number of results to return (1–50)", ge=1, le=MAX_COUNT)] = 10,
    start: Annotated[int, Field(description="Offset for pagination, e.g. 10 for the second page of 10 results", ge=0)] = 0,
    filter_format: Annotated[Optional[str], Field(description="Filter by document format. Common values: 'guide', 'answer', 'transaction', 'publication', 'news_article', 'detailed_guide', 'hmrc_manual_section', 'travel_advice', 'organisation'. Leave blank to search all types.")] = None,
    filter_organisations: Annotated[Optional[str], Field(description="Filter by organisation slug, e.g. 'hm-revenue-customs', 'department-for-work-pensions', 'driver-and-vehicle-standards-agency'.")] = None,
    order: Annotated[Optional[str], Field(description="Sort order. Use '-public_timestamp' for newest-first (default relevance).")] = None,
) -> GovukSearchResult:
    """Search GOV.UK's 700k+ content items using the official Search API.

    Returns a list of matching content items with title, description, link,
    format, owning organisation(s), and last updated timestamp.

    Use filter_format to narrow to specific content types (e.g. 'transaction'
    for citizen-facing services, 'guide' for guidance, 'publication' for
    official documents). Use filter_organisations to restrict to a department.
    """
    client = _client(ctx)

    query_params: dict[str, Any] = {
        "q": query,
        "count": count,
        "start": start,
        "fields[]": ["title", "description", "link", "format", "organisations", "public_timestamp"],
    }
    if filter_format:
        query_params["filter_document_type"] = filter_format
    if filter_organisations:
        query_params["filter_organisations"] = filter_organisations
    if order:
        query_params["order"] = order

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
                    "get_content": f"govuk_get_content(base_path={base!r})",
                    "grep": f"govuk_grep_content(base_path={base!r}, pattern=...)",
                } if link else {}),
            )
        )

    total = data.get("total", 0) or 0
    returned = len(results)
    has_more = (start + returned) < total if isinstance(total, int) else returned == count

    return GovukSearchResult(
        query=query,
        total=total,
        start=start,
        count=count,
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
@_timed_tool
async def govuk_grep_content(
    base_path: Annotated[str, Field(description="GOV.UK base_path, e.g. '/guidance/register-for-vat' or '/universal-credit'", min_length=1, max_length=500)],
    pattern: Annotated[str, Field(description="Regex or literal substring to search for within the page body, e.g. 'payment' or 'eligible.*income'", min_length=1, max_length=200)],
    ctx: Context,
    case_insensitive: Annotated[bool, Field(description="If true (default), match case-insensitively")] = True,
    max_hits: Annotated[int, Field(description="Maximum number of matching sections to return (1–100)", ge=1, le=100)] = 25,
) -> GrepContentResult:
    """Find body sections in a GOV.UK content item matching a pattern.

    Returns a list of `{anchor, heading, snippet, match}` hits — small per-section
    snippets centred on the match — so the LLM can decide which full sections to
    read via govuk_get_section.

    Use this when answering content-based questions ("what does this guide say
    about X?", "find the bit about eligibility") rather than navigating by
    section number.

    Pattern is regex; if it doesn't compile, falls back to literal substring.
    """
    client = _client(ctx)
    clean = base_path.lstrip("/")
    resp = await client.get(f"{CONTENT_BASE}/{clean}")
    resp.raise_for_status()
    payload = resp.json()

    hits = parsers.grep_body(
        payload,
        pattern,
        case_insensitive=case_insensitive,
        max_hits=max_hits,
    )
    return GrepContentResult(
        base_path=clean,
        pattern=pattern,
        hits=[GrepHit(**h) for h in hits],
        truncated=len(hits) >= max_hits,
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
@_timed_tool
async def govuk_list_organisations(
    ctx: Context,
    page: Annotated[int, Field(description="Page number (1-based)", ge=1)] = 1,
    per_page: Annotated[int, Field(description="Results per page (1–50)", ge=1, le=50)] = 20,
) -> GovukOrganisationsList:
    """List all UK government organisations registered on GOV.UK.

    Returns a paginated list of organisations including their slug, acronym,
    type, and status. Use this to browse the full government structure or
    discover slugs for use with govuk_get_organisation or govuk_search filters.
    """
    client = _client(ctx)

    resp = await client.get(
        ORGANISATIONS_BASE,
        params={"page": page, "per_page": per_page},
    )
    resp.raise_for_status()
    data = resp.json()

    orgs = [_fmt_org(o) for o in data.get("results", [])]

    total = data.get("total")
    total_pages = data.get("pages")
    returned = len(orgs)
    if isinstance(total, int):
        has_more = (page * per_page) < total
    elif isinstance(total_pages, int):
        has_more = page < total_pages
    else:
        has_more = returned == per_page

    return GovukOrganisationsList(
        page=page,
        per_page=per_page,
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
@_timed_tool
async def govuk_lookup_postcode(
    postcode: Annotated[str, Field(description="UK postcode, e.g. 'SW1A 2AA' or 'NG1 1AA'. Spaces optional.", min_length=5, max_length=8)],
    ctx: Context,
) -> GovukPostcode:
    """Look up a UK postcode to retrieve its local authority, region, constituency,
    and other administrative geography.

    Useful for determining which council area, parliamentary constituency, or
    NHS region a postcode falls within. Commonly used to direct users to the
    correct local service on GOV.UK (e.g. council tax, planning, waste).

    Uses the postcodes.io public API (no key required).
    """
    client = _client(ctx)
    postcode = postcode.replace(" ", "").upper()
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


@mcp.tool(
    name="govuk_get_content",
    annotations={
        "title": "Get GOV.UK Page",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@_timed_tool
async def govuk_get_content(
    base_path: Annotated[str, Field(description="GOV.UK base_path, e.g. '/universal-credit' or 'universal-credit'", min_length=1, max_length=500)],
    ctx: Context,
) -> dict:
    """Get metadata and navigable section index for a GOV.UK page.

    Returns the page title, document type, publication dates, and a list of
    sections with their anchor IDs and headings. Use govuk_get_section to
    read the body of a specific section, or govuk_grep_content to search
    within the page body.
    """
    path = base_path.lstrip("/")
    client = _client(ctx)
    resp = await client.get(f"{CONTENT_BASE}/{path}")
    resp.raise_for_status()
    payload = resp.json()
    header = parsers.extract_header(payload)
    raw_index = parsers.extract_index(payload)
    sections = []
    for line in raw_index.strip().splitlines():
        if ":" in line:
            anchor, _, heading = line.partition(":")
            sections.append({"anchor": anchor.strip(), "heading": heading.strip()})
    return {**header, "sections": sections}


@mcp.tool(
    name="govuk_get_section",
    annotations={
        "title": "Get GOV.UK Page Section",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@_timed_tool
async def govuk_get_section(
    base_path: Annotated[str, Field(description="GOV.UK base_path, e.g. '/universal-credit'", min_length=1, max_length=500)],
    anchor: Annotated[str, Field(description="Section anchor ID from govuk_get_content sections list", min_length=1, max_length=200)],
    ctx: Context,
) -> dict:
    """Get the HTML content of one named section of a GOV.UK page.

    Use govuk_get_content first to get the list of available section anchors,
    then call this with the anchor of the section you want to read.
    """
    path = base_path.lstrip("/")
    client = _client(ctx)
    resp = await client.get(f"{CONTENT_BASE}/{path}")
    resp.raise_for_status()
    payload = resp.json()
    try:
        html = parsers.extract_section(payload, anchor)
    except KeyError:
        raise ValueError(
            f"Section '{anchor}' not found in '{base_path}'. "
            "Use govuk_get_content to list available anchors."
        )
    return {"base_path": base_path, "anchor": anchor, "content": html}


@mcp.tool(
    name="govuk_get_organisation",
    annotations={
        "title": "Get GOV.UK Organisation",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
@_timed_tool
async def govuk_get_organisation(
    slug: Annotated[str, Field(description="Organisation slug, e.g. 'hm-revenue-customs'. Find slugs via govuk_list_organisations.", min_length=1, max_length=200)],
    ctx: Context,
) -> GovukOrganisation:
    """Get the profile of a UK government organisation by its slug.

    Returns name, acronym, type, status, web URL, and parent/child organisations.
    Use govuk_list_organisations to browse all organisations and discover slugs.
    """
    client = _client(ctx)
    resp = await client.get(f"{ORGANISATIONS_BASE}/{slug}")
    resp.raise_for_status()
    return _fmt_org(resp.json())


# ---------------------------------------------------------------------------
# Resources + caching (after tool registrations above)
# ---------------------------------------------------------------------------

# govuk:// resource templates for protocol-aware clients (Claude Desktop,
# Cursor, Claude Code). Tool-only clients (ChatGPT, proxy bridge) use the
# named companion tools above (govuk_get_content, govuk_get_section,
# govuk_get_organisation) instead.
register_govuk_resources(mcp)

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
    port = int(os.environ.get("PORT", "8080"))
    mcp.run(transport="http", host="0.0.0.0", port=port, stateless_http=True)


if __name__ == "__main__":
    main()
