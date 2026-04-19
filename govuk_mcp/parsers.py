"""Pure-function parsers for GOV.UK Content API payloads.

No HTTP, no FastMCP, no Pydantic — testable offline against the
committed fixture (`tests/live/fixtures/planning_guidance.json`).

The Content API returns a typed envelope:

    {
      title, description, document_type, schema_name, base_path,
      first_published_at, public_updated_at, ...,
      details: {
        body: "<html>...</html>",   # the big one
        attachments, change_history, headers, tags, ...
      },
      links: { organisations, taxons, related_mainstream, ... }
    }

These helpers slice that envelope into bounded views so an LLM can
navigate without context blowout. The biggest field, `details.body`, is
HTML with `<h2 id="...">` section anchors; `extract_index` returns the
anchor map and `extract_section` returns one section between consecutive
anchors.

`<h2>` tags without an `id` attribute are filtered — they're attachment
widgets and other structural noise, not navigable section headings.
"""

import re
from typing import Any

_HEADING_WITH_ID = re.compile(
    r'<h2\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</h2>',
    re.DOTALL | re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")

_HEADER_FIELDS = (
    "title",
    "description",
    "document_type",
    "schema_name",
    "base_path",
    "first_published_at",
    "public_updated_at",
    "updated_at",
    "phase",
    "locale",
    "withdrawn_notice",
)


def extract_header(payload: dict) -> dict:
    """Return only the metadata fields, no details/links blobs."""
    return {k: payload[k] for k in _HEADER_FIELDS if k in payload}


def extract_index(payload: dict) -> str:
    """Return one 'anchor: heading_text' row per real `<h2 id="...">` in
    `details.body`, document order. Filters out attachment widgets and
    other id-less h2s."""
    body = payload.get("details", {}).get("body", "")
    rows = []
    for anchor, raw in _HEADING_WITH_ID.findall(body):
        text = _TAG.sub("", raw).strip()
        rows.append(f"{anchor}: {text}")
    return "\n".join(rows)


def extract_section(payload: dict, anchor: str) -> str:
    """Return the body slice from `<h2 id="anchor">` up to the next
    `<h2 id="...">`. Raise KeyError if no such anchor exists."""
    body = payload.get("details", {}).get("body", "")
    pattern = re.compile(
        rf'<h2\b[^>]*\bid="{re.escape(anchor)}"[^>]*>',
        re.IGNORECASE,
    )
    m = pattern.search(body)
    if not m:
        raise KeyError(f"No <h2 id={anchor!r}> in body")
    rest = body[m.end():]
    next_m = _HEADING_WITH_ID.search(rest)
    end = m.end() + next_m.start() if next_m else len(body)
    return body[m.start():end]


def extract_details_field(payload: dict, field: str) -> Any:
    """Return one named field from `details`. Raise KeyError if absent."""
    details = payload.get("details", {})
    if field not in details:
        raise KeyError(f"No details field {field!r}")
    return details[field]


def extract_links(payload: dict, rel: str) -> list:
    """Return one named link relation. Empty list if absent."""
    return payload.get("links", {}).get(rel, [])


def grep_body(
    payload: dict,
    pattern: str,
    *,
    case_insensitive: bool = True,
    max_hits: int = 25,
) -> list[dict]:
    """Find h2 sections whose text content matches pattern.

    Returns up to `max_hits` items, each `{anchor, heading, snippet, match}`.
    Snippet is ~200 chars centred on the first match in that section.

    Pattern is regex; if it doesn't compile, falls back to literal substring.
    """
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        rx = re.compile(pattern, flags)
    except re.error:
        rx = re.compile(re.escape(pattern), flags)

    body = payload.get("details", {}).get("body", "")
    matches = list(_HEADING_WITH_ID.finditer(body))
    hits: list[dict] = []
    for i, m in enumerate(matches):
        section_start = m.start()
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section_html = body[section_start:section_end]
        section_text = _TAG.sub(" ", section_html)
        match = rx.search(section_text)
        if not match:
            continue
        anchor = m.group(1)
        heading = _TAG.sub("", m.group(2)).strip()
        snip_start = max(0, match.start() - 100)
        snip_end = min(len(section_text), match.end() + 100)
        snippet = _WHITESPACE.sub(" ", section_text[snip_start:snip_end].strip())
        hits.append({
            "anchor": anchor,
            "heading": heading,
            "snippet": snippet,
            "match": match.group(0),
        })
        if len(hits) >= max_hits:
            break
    return hits
