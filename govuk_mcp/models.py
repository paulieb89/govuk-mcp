"""Output models for GOV.UK MCP tool responses.

Wrapper models advertised through FastMCP tool `outputSchema`. Each Pydantic
model has descriptive `Field(...)` entries so claude.ai sees a rich schema
instead of a generic `{"result": "string"}` wrapper.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# govuk_search — Shape B (paginated search)
# ---------------------------------------------------------------------------


class GovukSearchOrganisation(BaseModel):
    """Organisation owning a search result."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Optional[str] = Field(None, description="Full organisation title, e.g. 'HM Revenue & Customs'.")
    acronym: Optional[str] = Field(None, description="Organisation acronym, e.g. 'HMRC'.")
    slug: Optional[str] = Field(None, description="Organisation slug for use with govuk_get_organisation.")


class GovukSearchResultItem(BaseModel):
    """A single GOV.UK search hit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Optional[str] = Field(None, description="Page title.")
    description: Optional[str] = Field(None, description="Short human-readable summary of the page.")
    link: Optional[str] = Field(
        None,
        description="GOV.UK relative path for the page, e.g. '/universal-credit'. Pass to govuk_get_content as base_path.",
    )
    url: Optional[str] = Field(None, description="Absolute https://www.gov.uk URL for the page.")
    format: Optional[str] = Field(
        None,
        description="Document format, e.g. 'guide', 'answer', 'transaction', 'publication', 'news_article'.",
    )
    organisations: list[GovukSearchOrganisation] = Field(
        default_factory=list,
        description="Owning organisation(s) for the page.",
    )
    public_timestamp: Optional[str] = Field(
        None,
        description="ISO-8601 timestamp for when this page was last publicly updated.",
    )


class GovukSearchResult(BaseModel):
    """A page of GOV.UK search results."""

    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(..., description="The free-text query that was searched.")
    total: int = Field(..., description="Total matching results across all pages on GOV.UK.")
    start: int = Field(..., description="Offset used for this page (zero-based).")
    count: int = Field(..., description="Max results requested for this page.")
    returned: int = Field(..., description="Number of results actually returned in this response.")
    has_more: bool = Field(
        ...,
        description=(
            "True if more results exist beyond this page. Re-call with "
            "start=start+returned to fetch the next page."
        ),
    )
    results: list[GovukSearchResultItem] = Field(
        default_factory=list,
        description=(
            "Matching pages. Use the `link` field of any result as the "
            "`base_path` input to govuk_get_content for the full item."
        ),
    )


# ---------------------------------------------------------------------------
# govuk_get_content — Shape C (single content item)
# ---------------------------------------------------------------------------


class GovukContentOrganisation(BaseModel):
    """Organisation linked to a content item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Optional[str] = Field(None, description="Organisation title.")
    base_path: Optional[str] = Field(None, description="GOV.UK base path for the organisation page.")


class GovukContentLinkItem(BaseModel):
    """A single linked content item (organisation, policy, topic, etc)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Optional[str] = Field(None, description="Title of the linked item.")
    base_path: Optional[str] = Field(None, description="GOV.UK base path for the linked item.")


class GovukContent(BaseModel):
    """A full GOV.UK content item, flattened to the most useful fields."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Optional[str] = Field(None, description="Content item title.")
    description: Optional[str] = Field(None, description="Short human-readable summary.")
    document_type: Optional[str] = Field(
        None,
        description="Specific document type, e.g. 'guide', 'answer', 'publication', 'news_article'.",
    )
    schema_name: Optional[str] = Field(
        None,
        description="GOV.UK schema name for the content type. Dictates the shape of `details`.",
    )
    base_path: Optional[str] = Field(None, description="GOV.UK base path for this content item.")
    public_updated_at: Optional[str] = Field(
        None, description="ISO-8601 timestamp for the most recent public update."
    )
    first_published_at: Optional[str] = Field(
        None, description="ISO-8601 timestamp for first publication."
    )
    publisher: Optional[str] = Field(
        None,
        description="Title of the primary publishing organisation, if one is recorded.",
    )
    organisations: list[GovukContentOrganisation] = Field(
        default_factory=list,
        description="All organisations linked to this item.",
    )
    locale: Optional[str] = Field(None, description="Content locale, usually 'en'.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Schema-specific content body (keys vary by schema_name — may "
            "include 'body', 'parts', 'summary', etc)."
        ),
    )
    links: dict[str, list[GovukContentLinkItem]] = Field(
        default_factory=dict,
        description=(
            "Related content grouped by link type (e.g. 'organisations', "
            "'policies', 'topics', 'parent', 'available_translations')."
        ),
    )


# ---------------------------------------------------------------------------
# govuk_get_organisation — Shape C (single organisation)
# ---------------------------------------------------------------------------


class GovukOrganisation(BaseModel):
    """A UK government organisation record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Optional[str] = Field(None, description="Full organisation title.")
    acronym: Optional[str] = Field(None, description="Organisation acronym, if set.")
    slug: Optional[str] = Field(
        None,
        description="Organisation slug, e.g. 'hm-revenue-customs'. Usable with govuk_search filters.",
    )
    type: Optional[str] = Field(
        None,
        description=(
            "Organisation type, e.g. 'ministerial_department', 'executive_agency', "
            "'non_ministerial_department', 'public_corporation'."
        ),
    )
    state: Optional[str] = Field(
        None,
        description="GOV.UK status, e.g. 'live', 'closed', 'transitioning'.",
    )
    web_url: Optional[str] = Field(None, description="Absolute https://www.gov.uk URL for the organisation page.")
    parent_organisations: list[str] = Field(
        default_factory=list,
        description="Titles of parent organisations this body reports into.",
    )
    child_organisations: list[str] = Field(
        default_factory=list,
        description="Titles of child organisations / agencies under this body.",
    )
    contact_details: Optional[dict[str, Any]] = Field(
        None,
        description="Contact details block from GOV.UK (phone, email, address) when available.",
    )


# ---------------------------------------------------------------------------
# govuk_list_organisations — Shape B (paginated list)
# ---------------------------------------------------------------------------


class GovukOrganisationsList(BaseModel):
    """A page of UK government organisations."""

    model_config = ConfigDict(str_strip_whitespace=True)

    page: int = Field(..., description="1-based page number requested.")
    per_page: int = Field(..., description="Max organisations requested per page.")
    total: Optional[int] = Field(
        None,
        description="Total number of organisations across all pages, if reported by GOV.UK.",
    )
    total_pages: Optional[int] = Field(
        None,
        description="Total number of pages available, if reported by GOV.UK.",
    )
    returned: int = Field(..., description="Number of organisations returned in this response.")
    has_more: bool = Field(
        ...,
        description=(
            "True if more organisations exist beyond this page. Re-call with "
            "page=page+1 to fetch the next page."
        ),
    )
    organisations: list[GovukOrganisation] = Field(
        default_factory=list,
        description="Organisations on this page, in the order returned by GOV.UK.",
    )


# ---------------------------------------------------------------------------
# govuk_lookup_postcode — Shape C (single postcode)
# ---------------------------------------------------------------------------


class GovukLocalAuthority(BaseModel):
    """Local authority covering a postcode."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: Optional[str] = Field(None, description="Local authority / council name.")
    code: Optional[str] = Field(None, description="GSS code for the local authority.")


class GovukPostcode(BaseModel):
    """UK postcode lookup result with administrative geography."""

    model_config = ConfigDict(str_strip_whitespace=True)

    postcode: Optional[str] = Field(None, description="Canonicalised postcode as returned by postcodes.io.")
    latitude: Optional[float] = Field(None, description="Latitude in decimal degrees (WGS84).")
    longitude: Optional[float] = Field(None, description="Longitude in decimal degrees (WGS84).")
    country: Optional[str] = Field(None, description="Country, e.g. 'England', 'Scotland', 'Wales', 'Northern Ireland'.")
    region: Optional[str] = Field(None, description="ONS region, e.g. 'East Midlands'.")
    parliamentary_constituency: Optional[str] = Field(
        None, description="Parliamentary constituency (pre-2025 boundary)."
    )
    parliamentary_constituency_2025: Optional[str] = Field(
        None, description="Parliamentary constituency under the 2025 boundaries."
    )
    local_authority: GovukLocalAuthority = Field(
        default_factory=GovukLocalAuthority,
        description="Local authority / council covering the postcode.",
    )
    admin_county: Optional[str] = Field(
        None, description="Administrative county, where applicable (null in unitary areas)."
    )
    nhs_integrated_care_board: Optional[str] = Field(
        None, description="NHS Integrated Care Board, where available."
    )
    codes: dict[str, Any] = Field(
        default_factory=dict,
        description="GSS codes for all administrative geographies covering this postcode.",
    )


# ---------------------------------------------------------------------------
# Phase-4 drill-down: govuk_grep_content
# ---------------------------------------------------------------------------


class GrepContentInput(BaseModel):
    """Input schema for govuk_grep_content."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    base_path: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description=(
            "GOV.UK base_path of a content item, e.g. 'guidance/planning-"
            "guidance-letters-to-chief-planning-officers' (leading slash "
            "optional). Use govuk_search to discover base_paths."
        ),
    )
    pattern: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description=(
            "Regex pattern (or plain substring) to search within the body. "
            "If the pattern doesn't compile as regex, falls back to literal "
            "substring match."
        ),
    )
    case_insensitive: bool = Field(True, description="Default true.")
    max_hits: int = Field(25, ge=1, le=100, description="Cap on returned hits.")


class GrepHit(BaseModel):
    """A single section match from govuk_grep_content."""

    anchor: str = Field(..., description="HTML anchor id of the containing <h2> section")
    heading: str = Field(..., description="Plain-text heading of the containing <h2>")
    snippet: str = Field(..., description="~200 chars of context around the match")
    match: str = Field(..., description="The exact text that matched the pattern")


class GrepContentResult(BaseModel):
    """Output schema for govuk_grep_content."""

    base_path: str = Field(..., description="The content item that was searched")
    pattern: str = Field(..., description="The pattern that was searched for")
    hits: list[GrepHit] = Field(..., description="Matching sections in document order")
    truncated: bool = Field(..., description="True if hit count reached max_hits and more matches may exist")
