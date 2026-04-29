"""
Live matrix runner — calls all 7 govuk-mcp tools in-process and prints a
context-cost table. Response bodies are written to tests/live/fixtures/.

Usage:
    python -m tests.live.run_matrix
"""

from __future__ import annotations

import asyncio

from fastmcp import Client

from govuk_mcp.server import mcp
from tests.live.runner import Case, find_first, print_table, run, write_csv

CASES: list[Case] = [
    # ---- search (existing tools use {"params": {...}} shape) ----
    Case("govuk_search", {"params": {"query": "universal credit"}}),
    Case(
        "govuk_search",
        {"params": {"query": "universal credit", "count": 50}},
        label="govuk_search (count=50)",
    ),
    Case(
        "govuk_search",
        {"params": {"query": "VAT", "count": 20, "filter_format": "detailed_guide"}},
        label="govuk_search (VAT guides)",
    ),

    # ---- content drill-down (new companion tools — flat args) ----
    # Use a detailed guidance page that has proper <h2 id="..."> sections.
    Case(
        "govuk_get_content",
        {"base_path": "/guidance/register-for-vat"},
        chain=lambda p: (
            {"base_path": "/guidance/register-for-vat", "anchor": p["sections"][0]["anchor"]}
            if p.get("sections")
            else {}
        ),
    ),
    Case("govuk_get_section"),  # args injected by chain above

    # ---- grep ----
    Case("govuk_grep_content", {"params": {"base_path": "/guidance/register-for-vat", "pattern": "register"}}),

    # ---- organisations ----
    Case(
        "govuk_list_organisations",
        {"params": {}},
        chain=lambda p: {
            "slug": next(
                (o["slug"] for o in (p.get("organisations") or []) if o.get("slug")),
                "hm-revenue-customs",
            )
        },
    ),
    Case("govuk_get_organisation"),  # args injected by chain above

    # ---- postcode ----
    Case("govuk_lookup_postcode", {"params": {"postcode": "SW1A 2AA"}}),
]


async def main() -> None:
    async with Client(mcp) as client:
        rows = await run(client, CASES)

    print_table(rows)
    write_csv(rows)


if __name__ == "__main__":
    asyncio.run(main())
