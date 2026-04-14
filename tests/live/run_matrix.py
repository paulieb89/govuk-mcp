"""
Live matrix runner — calls all 5 govuk-mcp tools in-process and prints a
context-cost table.

Covers both typical and stress scenarios (count=50, per_page=50) to expose
any hidden bloat in the govuk_search / govuk_list_organisations pagination.
govuk_get_content is tested on both a citizen-facing guide and a large
publication, since the server.py comment flags that upstream returns ~200KB
of raw JSON per content item which the tool is supposed to trim.

Response bodies are written to tests/live/fixtures/ (gitignored). Only
per-tool metrics print to stdout.

Usage:
    python -m tests.live.run_matrix
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import tiktoken
from fastmcp import Client

from govuk_mcp.server import mcp

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CSV_PATH = Path(__file__).parent / "context_costs.csv"
ENCODER = tiktoken.get_encoding("cl100k_base")


def _llm_text(result: Any) -> str:
    parts = []
    for block in result.content or []:
        t = getattr(block, "text", None)
        if t is not None:
            parts.append(t)
    return "\n".join(parts)


def _write_fixture(tool: str, args: dict, result: Any) -> Path:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    args_hash = hashlib.sha256(
        json.dumps(args, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    path = FIXTURES_DIR / f"{tool}__{args_hash}.json"
    path.write_text(json.dumps({
        "tool": tool,
        "args": args,
        "is_error": result.is_error,
        "structured_content": result.structured_content,
        "content_blocks": [
            {"type": type(b).__name__, "text": getattr(b, "text", None)}
            for b in (result.content or [])
        ],
    }, indent=2, default=str))
    return path


async def _call(client: Client, tool: str, params: dict, label: str | None = None) -> dict:
    args = {"params": params}
    t0 = time.perf_counter()
    result = await client.call_tool(tool, args)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    _write_fixture(tool, args, result)
    text = _llm_text(result)
    return {
        "tool": label or tool,
        "tokens": len(ENCODER.encode(text)),
        "chars": len(text),
        "blocks": len(result.content or []),
        "ms": elapsed_ms,
        "error": result.is_error,
    }


async def main() -> None:
    rows: list[dict] = []

    async with Client(mcp) as client:
        # ---- govuk_search — default count=10 ----
        rows.append(await _call(
            client, "govuk_search",
            {"query": "universal credit"},
            label="govuk_search (count=10)",
        ))

        # ---- govuk_search — stress, count=50 ----
        rows.append(await _call(
            client, "govuk_search",
            {"query": "universal credit", "count": 50},
            label="govuk_search (count=50)",
        ))

        # ---- govuk_search — with format filter ----
        rows.append(await _call(
            client, "govuk_search",
            {"query": "VAT", "count": 20, "filter_format": "detailed_guide"},
            label="govuk_search (VAT guides)",
        ))

        # ---- govuk_get_content — typical citizen-facing guide ----
        rows.append(await _call(
            client, "govuk_get_content",
            {"base_path": "/universal-credit"},
            label="govuk_get_content (guide)",
        ))

        # ---- govuk_get_content — large publication ----
        rows.append(await _call(
            client, "govuk_get_content",
            {"base_path": "/government/publications/autumn-budget-2024"},
            label="govuk_get_content (publication)",
        ))

        # ---- govuk_get_content — HMRC manual section (often huge) ----
        rows.append(await _call(
            client, "govuk_get_content",
            {"base_path": "/hmrc-internal-manuals/vat-input-tax/vit00000"},
            label="govuk_get_content (hmrc manual)",
        ))

        # ---- govuk_get_organisation ----
        rows.append(await _call(
            client, "govuk_get_organisation",
            {"slug": "hm-revenue-customs"},
        ))

        # ---- govuk_list_organisations — default per_page=20 ----
        rows.append(await _call(
            client, "govuk_list_organisations",
            {},
            label="govuk_list_organisations (per_page=20)",
        ))

        # ---- govuk_list_organisations — stress, per_page=50 ----
        rows.append(await _call(
            client, "govuk_list_organisations",
            {"per_page": 50},
            label="govuk_list_organisations (per_page=50)",
        ))

        # ---- govuk_lookup_postcode ----
        rows.append(await _call(
            client, "govuk_lookup_postcode",
            {"postcode": "SW1A 2AA"},
        ))

    # ---- print table ----
    rows.sort(key=lambda x: x["tokens"], reverse=True)
    name_w = max(len(r["tool"]) for r in rows)
    header = f"{'tool':<{name_w}}  {'tokens':>8}  {'chars':>8}  {'blocks':>6}  {'ms':>8}  err"
    print(header)
    print("-" * len(header))
    total_tokens = 0
    total_chars = 0
    for r in rows:
        total_tokens += r["tokens"]
        total_chars += r["chars"]
        err = "x" if r["error"] else ""
        print(f"{r['tool']:<{name_w}}  {r['tokens']:>8}  {r['chars']:>8}  {r['blocks']:>6}  {r['ms']:>8}  {err}")
    print("-" * len(header))
    print(f"{'TOTAL':<{name_w}}  {total_tokens:>8}  {total_chars:>8}")
    print(f"{'% of 200k ctx':<{name_w}}  {total_tokens / 200_000 * 100:>7.1f}%")

    with CSV_PATH.open("w") as f:
        f.write("tool,tokens,chars,blocks,ms,error\n")
        for r in rows:
            f.write(f"{r['tool']},{r['tokens']},{r['chars']},{r['blocks']},{r['ms']},{int(r['error'])}\n")
    print(f"\nwrote {CSV_PATH.relative_to(Path.cwd())}")


if __name__ == "__main__":
    asyncio.run(main())
