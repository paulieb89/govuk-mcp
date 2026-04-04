"""GOV.UK MCP Server — search and content tools for the UK government's public estate."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

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
        "Tools for searching GOV.UK content, retrieving full content items, "
        "looking up government organisations, and resolving UK postcodes to "
        "local authority areas. All data is sourced from official GOV.UK APIs. "
        "Use govuk_search first to find content, then govuk_get_content to "
        "retrieve the full item by its base_path."
    ),
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _client(ctx) -> httpx.AsyncClient:
    return ctx.request_context.lifespan_state["client"]


def _handle_http_error(e: httpx.HTTPStatusError) -> str:
    status = e.response.status_code
    if status == 404:
        return json.dumps({"error": "Not found. Check the path or slug is correct."})
    if status == 429:
        return json.dumps({"error": "Rate limited by GOV.UK API. Please wait and retry."})
    return json.dumps({"error": f"GOV.UK API returned HTTP {status}."})


def _fmt_org(org: dict[str, Any]) -> dict[str, Any]:
    """Flatten a single organisation record to a concise dict."""
    return {
        "title": org.get("title"),
        "acronym": org.get("details", {}).get("acronym") or org.get("acronym"),
        "slug": org.get("details", {}).get("slug") or org.get("slug"),
        "type": org.get("details", {}).get("organisation_type") or org.get("organisation_type"),
        "state": org.get("details", {}).get("govuk_status") or org.get("organisation_state"),
        "web_url": org.get("web_url") or (
            f"https://www.gov.uk/government/organisations/{org.get('details', {}).get('slug') or org.get('slug', '')}"
        ),
        "parent_organisations": [
            p.get("title") for p in org.get("parent_organisations", [])
        ],
        "child_organisations": [
            c.get("title") for c in org.get("child_organisations", [])
        ],
    }


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


class ContentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    base_path: str = Field(
        ...,
        description=(
            "GOV.UK base path for the content item, e.g. '/universal-credit', "
            "'/check-mot-history', '/government/organisations/hm-revenue-customs'. "
            "Always starts with '/'."
        ),
        min_length=2,
        max_length=500,
    )


class OrganisationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    slug: str = Field(
        ...,
        description=(
            "Organisation slug, e.g. 'hm-revenue-customs', 'department-for-work-pensions', "
            "'companies-house', 'driver-and-vehicle-standards-agency'."
        ),
        min_length=2,
        max_length=200,
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
async def govuk_search(params: SearchInput, ctx) -> str:
    """Search GOV.UK's 700k+ content items using the official Search API.

    Returns a list of matching content items with title, description, link,
    format, owning organisation(s), and last updated timestamp.

    Use filter_format to narrow to specific content types (e.g. 'transaction'
    for citizen-facing services, 'guide' for guidance, 'publication' for
    official documents). Use filter_organisations to restrict to a department.

    Args:
        params (SearchInput): Search parameters including query, count, start,
            optional format/org filters, and optional sort order.

    Returns:
        str: JSON with keys:
            - total (int): total matching results across all pages
            - count (int): results in this response
            - start (int): offset used
            - results (list): each item has title, description, link,
              format, organisations, public_timestamp
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

    try:
        resp = await client.get(SEARCH_BASE, params=query_params)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        return _handle_http_error(e)
    except httpx.TimeoutException:
        return json.dumps({"error": "Request to GOV.UK Search API timed out."})

    raw_results = data.get("results", [])
    results = []
    for r in raw_results:
        orgs = [
            {"title": o.get("title"), "acronym": o.get("acronym"), "slug": o.get("slug")}
            for o in r.get("organisations", [])
        ]
        results.append({
            "title": r.get("title"),
            "description": r.get("description"),
            "link": r.get("link"),
            "url": f"https://www.gov.uk{r.get('link', '')}",
            "format": r.get("format"),
            "organisations": orgs,
            "public_timestamp": r.get("public_timestamp"),
        })

    return json.dumps({
        "total": data.get("total", 0),
        "count": len(results),
        "start": params.start,
        "results": results,
    }, indent=2)


@mcp.tool(
    name="govuk_get_content",
    annotations={
        "title": "Get GOV.UK Content Item",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def govuk_get_content(params: ContentInput, ctx) -> str:
    """Retrieve the full content item for a GOV.UK page by its base path.

    Returns the complete structured content including title, description,
    body text (where available), document type, publishing organisation,
    links to related content, and metadata.

    Use govuk_search first to discover base paths, then this tool to read
    the full content. Particularly useful for reading guides, publications,
    travel advice, and HMRC manuals in full.

    Args:
        params (ContentInput): base_path of the content item (e.g. '/universal-credit').

    Returns:
        str: JSON content item. Key fields:
            - title (str)
            - description (str)
            - document_type (str)
            - schema_name (str)
            - public_updated_at (str)
            - details (dict): contains body, parts, or other schema-specific content
            - links (dict): related organisations, policies, topics, etc.
    """
    client = _client(ctx)

    path = params.base_path if params.base_path.startswith("/") else f"/{params.base_path}"
    url = f"{CONTENT_BASE}{path}"

    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        return _handle_http_error(e)
    except httpx.TimeoutException:
        return json.dumps({"error": "Request to GOV.UK Content API timed out."})

    # Extract the most useful fields rather than dumping 200KB of raw JSON
    orgs = [
        {"title": o.get("title"), "base_path": o.get("base_path")}
        for o in data.get("links", {}).get("organisations", [])
    ]
    primary_pub = data.get("links", {}).get("primary_publishing_organisation", [])
    publisher = primary_pub[0].get("title") if primary_pub else None

    output = {
        "title": data.get("title"),
        "description": data.get("description"),
        "document_type": data.get("document_type"),
        "schema_name": data.get("schema_name"),
        "base_path": data.get("base_path"),
        "public_updated_at": data.get("public_updated_at"),
        "first_published_at": data.get("first_published_at"),
        "publisher": publisher,
        "organisations": orgs,
        "locale": data.get("locale"),
        "details": data.get("details", {}),
        "links": {
            k: [{"title": i.get("title"), "base_path": i.get("base_path")} for i in v]
            for k, v in data.get("links", {}).items()
            if isinstance(v, list) and v and isinstance(v[0], dict)
        },
    }

    return json.dumps(output, indent=2, ensure_ascii=False)


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
async def govuk_get_organisation(params: OrganisationInput, ctx) -> str:
    """Retrieve details for a specific UK government organisation by slug.

    Returns the organisation's full name, acronym, type (ministerial_department,
    executive_agency, non_ministerial_department, etc.), status (live/closed),
    parent departments, and child bodies.

    Useful for understanding departmental structure, finding which agencies sit
    under a department, or resolving an acronym to a full organisation record.

    Args:
        params (OrganisationInput): Organisation slug (e.g. 'hm-revenue-customs').

    Returns:
        str: JSON with fields:
            - title, acronym, slug, type, state, web_url
            - parent_organisations (list of titles)
            - child_organisations (list of titles)
            - contact_details (if available)
    """
    client = _client(ctx)

    url = f"{ORGANISATIONS_BASE}/{params.slug}"

    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        return _handle_http_error(e)
    except httpx.TimeoutException:
        return json.dumps({"error": "Request timed out."})

    result = _fmt_org(data)

    # Add contact details if present
    contacts = data.get("details", {}).get("contact_details") or data.get("contact_details")
    if contacts:
        result["contact_details"] = contacts

    return json.dumps(result, indent=2, ensure_ascii=False)


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
async def govuk_list_organisations(params: OrganisationsListInput, ctx) -> str:
    """List all UK government organisations registered on GOV.UK.

    Returns a paginated list of organisations including their slug, acronym,
    type, and status. Use this to browse the full government structure or
    discover slugs for use with govuk_get_organisation or govuk_search filters.

    Args:
        params (OrganisationsListInput): page (1-based) and per_page (1–50).

    Returns:
        str: JSON with fields:
            - total (int): total number of organisations
            - page (int), per_page (int), total_pages (int)
            - organisations (list): each with title, acronym, slug, type, state
    """
    client = _client(ctx)

    try:
        resp = await client.get(
            ORGANISATIONS_BASE,
            params={"page": params.page, "per_page": params.per_page},
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        return _handle_http_error(e)
    except httpx.TimeoutException:
        return json.dumps({"error": "Request timed out."})

    orgs = [_fmt_org(o) for o in data.get("results", [])]

    return json.dumps({
        "total": data.get("total"),
        "page": params.page,
        "per_page": params.per_page,
        "total_pages": data.get("pages"),
        "organisations": orgs,
    }, indent=2, ensure_ascii=False)


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
async def govuk_lookup_postcode(params: PostcodeInput, ctx) -> str:
    """Look up a UK postcode to retrieve its local authority, region, constituency,
    and other administrative geography.

    Useful for determining which council area, parliamentary constituency, or
    NHS region a postcode falls within. Commonly used to direct users to the
    correct local service on GOV.UK (e.g. council tax, planning, waste).

    Uses the postcodes.io public API (no key required).

    Args:
        params (PostcodeInput): UK postcode (e.g. 'NG1 1AA', 'SW1A 2AA').

    Returns:
        str: JSON with fields:
            - postcode (str)
            - local_authority (dict): name and code
            - region (str)
            - country (str)
            - parliamentary_constituency (str)
            - nhs_integrated_care_board (str, if available)
            - latitude, longitude
            - codes (dict): GSS codes for all geographies
    """
    client = _client(ctx)
    postcode = params.postcode.replace(" ", "").upper()
    url = f"{LOCATIONS_BASE}/postcodes/{postcode}"

    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json().get("result", {})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return json.dumps({"error": f"Postcode '{params.postcode}' not found or invalid."})
        return _handle_http_error(e)
    except httpx.TimeoutException:
        return json.dumps({"error": "Postcode lookup timed out."})

    return json.dumps({
        "postcode": data.get("postcode"),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "country": data.get("country"),
        "region": data.get("region"),
        "parliamentary_constituency": data.get("parliamentary_constituency"),
        "parliamentary_constituency_2025": data.get("parliamentary_constituency_2025"),
        "local_authority": {
            "name": data.get("admin_district"),
            "code": data.get("codes", {}).get("admin_district"),
        },
        "admin_county": data.get("admin_county"),
        "nhs_integrated_care_board": data.get("integrated_care_board"),
        "codes": data.get("codes", {}),
    }, indent=2)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    mcp.run(transport="streamable-http", port=8000, host="0.0.0.0")


if __name__ == "__main__":
    main()
