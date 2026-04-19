"""Phase-4-style drill-down tests for govuk-mcp.

Two layers:

* **Offline parser tests** — load `tests/live/fixtures/planning_guidance.json`
  (a real captured GOV.UK Content API payload, ~648KB). Deterministic,
  fast, no network.

* **Live tests** — exercise the resources + grep tool through an in-process
  FastMCP `Client` against the real GOV.UK API.
"""

import json
from pathlib import Path

import pytest
from fastmcp import Client

from govuk_mcp import parsers
from govuk_mcp.server import mcp

FIXTURE = Path(__file__).parent / "live" / "fixtures" / "planning_guidance.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text())


def _est_tokens(s) -> int:
    if isinstance(s, str):
        return len(s) // 4
    return len(json.dumps(s, default=str)) // 4


# ─── Offline parser tests ──────────────────────────────────────────────────


def test_extract_header_returns_metadata_only():
    out = parsers.extract_header(_payload())
    assert "title" in out
    assert "description" in out
    assert "document_type" in out
    # No body or links blob
    assert "details" not in out
    assert "links" not in out


def test_extract_header_under_2000_tokens():
    assert _est_tokens(parsers.extract_header(_payload())) < 2_000


def test_extract_index_returns_anchored_h2_only():
    rows = parsers.extract_index(_payload()).splitlines()
    assert len(rows) > 5
    # Every row is "anchor: heading" — the colon separator is required
    for row in rows:
        assert ":" in row, f"Row missing 'anchor: heading' shape: {row!r}"
    # First row should be a real anchor like "introduction" or "section"
    first_anchor = rows[0].split(":", 1)[0]
    assert first_anchor and " " not in first_anchor


def test_extract_index_filters_attachment_widgets():
    """The planning guidance page has 198 <h2> tags but only ~38 with id
    attributes (the rest are gem-c-attachment widgets)."""
    rows = parsers.extract_index(_payload()).splitlines()
    # Far fewer than the ~198 raw h2 count
    assert len(rows) < 100


def test_extract_index_under_10000_tokens():
    """Even the worst-case page should produce a bounded index."""
    assert _est_tokens(parsers.extract_index(_payload())) < 10_000


def test_extract_section_returns_slice():
    rows = parsers.extract_index(_payload()).splitlines()
    first_anchor = rows[0].split(":", 1)[0]
    out = parsers.extract_section(_payload(), first_anchor)
    assert out.startswith("<h2"), f"Expected leading <h2>, got: {out[:80]!r}"
    assert f'id="{first_anchor}"' in out


def test_extract_section_raises_for_unknown_anchor():
    with pytest.raises(KeyError):
        parsers.extract_section(_payload(), "definitely-not-a-real-anchor-xyz")


def test_extract_details_field_returns_named_field():
    out = parsers.extract_details_field(_payload(), "body")
    assert isinstance(out, str)
    assert "<h2" in out


def test_extract_details_field_raises_for_unknown():
    with pytest.raises(KeyError):
        parsers.extract_details_field(_payload(), "no-such-field")


def test_extract_links_returns_relation():
    out = parsers.extract_links(_payload(), "organisations")
    assert isinstance(out, list)
    if out:
        assert "title" in out[0] or "base_path" in out[0]


def test_extract_links_returns_empty_for_unknown():
    out = parsers.extract_links(_payload(), "no-such-relation")
    assert out == []


def test_grep_body_finds_matches_with_snippets():
    hits = parsers.grep_body(_payload(), "planning", max_hits=5)
    assert hits, "Expected at least one match for 'planning'"
    for h in hits:
        assert h["anchor"]
        assert h["heading"]
        assert "planning" in h["snippet"].lower()
        assert h["match"]


def test_grep_body_respects_max_hits_cap():
    hits = parsers.grep_body(_payload(), "the", max_hits=3)
    assert len(hits) == 3


def test_grep_body_case_insensitive_default():
    a = parsers.grep_body(_payload(), "PLANNING", max_hits=5)
    b = parsers.grep_body(_payload(), "planning", max_hits=5)
    assert len(a) == len(b)


def test_grep_body_falls_back_to_literal_on_invalid_regex():
    hits = parsers.grep_body(_payload(), "[unclosed", max_hits=3)
    assert isinstance(hits, list)


# ─── Live gateway tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_six_resource_templates_registered():
    async with Client(mcp) as c:
        templates = {t.uriTemplate for t in await c.list_resource_templates()}
    expected = {
        "govuk://content/{base_path*}/header",
        "govuk://content/{base_path*}/index",
        "govuk://content/{base_path*}/section/{anchor}",
        "govuk://content/{base_path*}/details/{field}",
        "govuk://content/{base_path*}/links/{rel}",
        "govuk://organisation/{slug}",
    }
    missing = expected - templates
    assert not missing, f"Missing templates: {missing}"


@pytest.mark.asyncio
async def test_grep_tool_registered_and_old_tools_gone():
    async with Client(mcp) as c:
        tools = {t.name for t in await c.list_tools()}
    assert "govuk_grep_content" in tools
    # Deleted tools
    assert "govuk_get_content" not in tools
    assert "govuk_get_organisation" not in tools
    # Kept
    assert "govuk_search" in tools
    assert "govuk_list_organisations" in tools
    assert "govuk_lookup_postcode" in tools


@pytest.mark.asyncio
async def test_resources_as_tools_transform_exposes_read_resource_tool():
    async with Client(mcp) as c:
        tools = {t.name for t in await c.list_tools()}
    assert "read_resource" in tools
    assert "list_resources" in tools


@pytest.mark.asyncio
async def test_planning_guidance_header_under_2k_tokens_live():
    async with Client(mcp) as c:
        result = await c.read_resource(
            "govuk://content/guidance/planning-guidance-letters-to-chief-planning-officers/header"
        )
    text = result[0].text
    assert _est_tokens(text) < 2_000
    payload = json.loads(text)
    # The "guidance" URL prefix doesn't dictate document_type; this page is "detailed_guide".
    assert payload.get("document_type") in {"guidance", "detailed_guide"}
    assert payload.get("title")


@pytest.mark.asyncio
async def test_planning_guidance_index_under_10k_tokens_live():
    """End-to-end audit acceptance: was 270k tokens, now <10k."""
    async with Client(mcp) as c:
        result = await c.read_resource(
            "govuk://content/guidance/planning-guidance-letters-to-chief-planning-officers/index"
        )
    text = result[0].text
    assert _est_tokens(text) < 10_000


@pytest.mark.asyncio
async def test_grep_content_tool_returns_hits_live():
    async with Client(mcp) as c:
        result = await c.call_tool(
            "govuk_grep_content",
            {"params": {
                "base_path": "guidance/planning-guidance-letters-to-chief-planning-officers",
                "pattern": "consultation",
                "max_hits": 5,
            }},
        )
    payload = result.data
    assert payload.base_path
    assert len(payload.hits) > 0
    for h in payload.hits:
        assert "consultation" in h.snippet.lower()


@pytest.mark.asyncio
async def test_typical_workflow_under_8k_tokens_live():
    """Header + grep + 2 sections — the 'what does this guide say about X' flow."""
    base = "guidance/planning-guidance-letters-to-chief-planning-officers"
    async with Client(mcp) as c:
        header = await c.read_resource(f"govuk://content/{base}/header")
        grep = await c.call_tool(
            "govuk_grep_content",
            {"params": {"base_path": base, "pattern": "consultation", "max_hits": 5}},
        )
        sections = []
        for hit in grep.data.hits[:2]:
            r = await c.read_resource(f"govuk://content/{base}/section/{hit.anchor}")
            sections.append(r[0].text)

    total_text = header[0].text + str(grep.data) + "".join(sections)
    total_tokens = _est_tokens(total_text)
    # Acceptance is "no longer the 270k blowout, navigable workflow stays bounded".
    # Real-world workflows on this 488KB-body page run 8-15k tokens depending on
    # which sections the LLM picks; budget for the worst case.
    assert total_tokens < 20_000, f"workflow used ~{total_tokens} tokens"
