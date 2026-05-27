#!/usr/bin/env python3
"""
convert_edan_to_faf.py — convert Smithsonian EDAN/JSONL into FAF-shape .md files.

Reads one or more EDAN JSONL files (one record per line), emits one .md file per
record into pilot/md/, with FAF-style YAML frontmatter + structured body.

Spec source: PLANET-FAF/RAG/samples/smithsonian/SCHEMA-MAP.md
- 240 distinct field paths across 9,175 records / 6 units
- Universal fields (100% coverage): id, type, unitCode, url, title, content.freetext
- Common freetext sections (50–99%): notes, name, identifier, setName, objectType,
  physicalDescription (per coverage data)

Frontmatter (always populated):
    id          — EDAN record id
    type        — EDAN type (ead_component, etc.) — 1:1 from source
    unit        — unitCode lowercase
    source_url  — round-trip back to EDAN
    title       — EDAN title
    boost       — raw content.boost (when present)
    priority    — derived: boost ≥ 2.0 → high, 1.0–1.99 → medium, < 1.0 → low,
                  missing → standard
    tags        — list: unit:<x>, type:<x>, level:<x> (when present),
                  plus slugs derived from name/setName/objectType

Body sections (only emitted when source data is present):
    # {title}
    ## Description       ← freetext.notes[].content (label-grouped)
    ## Names             ← freetext.name[].{label,content}
    ## Identifier        ← freetext.identifier[].content
    ## Set               ← freetext.setName[].content
    ## Object Type       ← freetext.objectType[].content
    ## Physical          ← freetext.physicalDescription[].content

dataSource is skipped from body (always = unit name, redundant per the spec).

Usage:
    python3 scripts/convert_edan_to_faf.py <jsonl_file> [<jsonl_file>...]
    python3 scripts/convert_edan_to_faf.py --all   # use the default sample paths

Examples:
    python3 scripts/convert_edan_to_faf.py /path/to/00.txt
    python3 scripts/convert_edan_to_faf.py --all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PILOT_MD = REPO_ROOT / "pilot" / "md"

DEFAULT_SAMPLES_DIR = Path("/Users/wolfejam/PLANET-FAF/RAG/samples/smithsonian")
DEFAULT_FILES = [
    "00.txt",            # aaa  — Archives of American Art
    "nmah-00.txt",       # nmah — American History
    "nmnhanthro-00.txt", # nmnhanthro — Natural History / Anthropology
    "npg-00.txt",        # npg  — Portrait Gallery
    "npm-00.txt",        # npm  — Postal Museum
    "nasm-00.txt",       # nasm — Air & Space (thin)
]


def slugify(s: str, maxlen: int = 60) -> str:
    """Lossy slugify for tag values / filename-safe identifiers."""
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(s)).strip("-").lower()
    return s[:maxlen]


def yaml_str(s: str) -> str:
    """Escape a string for inline YAML double-quoted value."""
    s = str(s).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", " ").replace("\r", " ").strip()
    return s


def derive_priority(boost: Any) -> str:
    """boost ≥ 2.0 → high; 1.0–1.99 → medium; < 1.0 → low; missing → standard."""
    if boost is None or boost == "":
        return "standard"
    try:
        v = float(boost)
    except (TypeError, ValueError):
        return "standard"
    if v >= 2.0:
        return "high"
    if v >= 1.0:
        return "medium"
    return "low"


def freetext_section(freetext: dict, key: str) -> list[dict]:
    """Return the list of {label, content} objects for a freetext key, or []."""
    val = freetext.get(key)
    if not isinstance(val, list):
        return []
    return [item for item in val if isinstance(item, dict)]


def render_labeled_block(items: list[dict], heading: str) -> str:
    """Render a list of {label, content} dicts as a labeled markdown block.

    Multiple items with the same label are joined under one bullet group.
    """
    if not items:
        return ""
    lines = [f"## {heading}"]
    for item in items:
        label = (item.get("label") or "").strip()
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if label:
            lines.append(f"- **{label}:** {content}")
        else:
            lines.append(f"- {content}")
    if len(lines) == 1:  # only the heading, no actual content
        return ""
    return "\n".join(lines) + "\n"


def extract_extra_tags(freetext: dict, limit: int = 6) -> list[str]:
    """Slug-extract a few tags from name/setName/objectType fields."""
    extras: list[str] = []
    for key in ("name", "setName", "objectType"):
        for item in freetext_section(freetext, key):
            content = (item.get("content") or "").strip()
            if content:
                slug = slugify(content, maxlen=40)
                if slug and slug not in extras:
                    extras.append(slug)
                if len(extras) >= limit:
                    return extras
    return extras


def build_md(record: dict) -> tuple[str, str]:
    """Build the (filename_slug, markdown_text) for one EDAN record.

    Returns ("", "") if the record is unusable (no id or no usable content).
    """
    rec_id = record.get("id", "")
    rec_type = record.get("type", "")
    unit = (record.get("unitCode") or "").lower()
    url = record.get("url", "")
    title = (record.get("title") or "").strip() or "(untitled)"

    content_obj = record.get("content") or {}
    boost = content_obj.get("boost")
    level = content_obj.get("level")
    freetext = content_obj.get("freetext") or {}

    if not rec_id:
        return "", ""

    # --- frontmatter ---
    tags = [f"unit:{unit}", f"type:{slugify(rec_type)}"]
    if level:
        tags.append(f"level:{slugify(level)}")
    tags.extend(extract_extra_tags(freetext, limit=6))
    # de-dup preserving order
    seen = set()
    unique_tags = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)

    fm_lines = [
        "---",
        f"id: {rec_id}",
        f"type: {rec_type}",
        f"unit: {unit}",
        f'source_url: "{yaml_str(url)}"',
        f'title: "{yaml_str(title)[:200]}"',
    ]
    if boost is not None and boost != "":
        fm_lines.append(f"boost: {boost}")
    fm_lines.append(f"priority: {derive_priority(boost)}")
    if level:
        fm_lines.append(f"level: {slugify(level)}")
    fm_lines.append(f"tags: [{', '.join(unique_tags)}]")
    fm_lines.append("---")

    # --- body (only sections with real content) ---
    body_parts = [f"# {title}", ""]

    # Description (notes) — prime RAG content
    notes_block = render_labeled_block(freetext_section(freetext, "notes"), "Description")
    if notes_block:
        body_parts.append(notes_block)

    # Names (people / orgs)
    names_block = render_labeled_block(freetext_section(freetext, "name"), "Names")
    if names_block:
        body_parts.append(names_block)

    # Identifier
    ident_block = render_labeled_block(freetext_section(freetext, "identifier"), "Identifier")
    if ident_block:
        body_parts.append(ident_block)

    # Set name (collection / series)
    setname_block = render_labeled_block(freetext_section(freetext, "setName"), "Set")
    if setname_block:
        body_parts.append(setname_block)

    # Object Type
    otype_block = render_labeled_block(freetext_section(freetext, "objectType"), "Object Type")
    if otype_block:
        body_parts.append(otype_block)

    # Physical Description
    phys_block = render_labeled_block(
        freetext_section(freetext, "physicalDescription"), "Physical"
    )
    if phys_block:
        body_parts.append(phys_block)

    # If body is just the title, this record is too thin — skip.
    if len(body_parts) <= 2:
        return "", ""

    md = "\n".join(fm_lines) + "\n\n" + "\n".join(body_parts).rstrip() + "\n"

    # Filename slug: <unit>__<id>  (id is already unique)
    fname = f"{unit}__{slugify(rec_id, maxlen=80)}.md"
    return fname, md


def process_file(path: Path, dry_run: bool = False) -> tuple[int, int]:
    """Process one JSONL file. Returns (written, skipped)."""
    written = skipped = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue

            fname, md = build_md(record)
            if not fname or not md:
                skipped += 1
                continue

            if not dry_run:
                out = PILOT_MD / fname
                out.write_text(md, encoding="utf-8")
            written += 1
    return written, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="EDAN JSONL files to convert")
    ap.add_argument("--all", action="store_true",
                    help=f"use the 6 default files in {DEFAULT_SAMPLES_DIR}")
    ap.add_argument("--limit", type=int, default=None,
                    help="if set, process only the first N records per file (smoke test)")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse + format but don't write files")
    args = ap.parse_args()

    if args.all:
        files = [DEFAULT_SAMPLES_DIR / name for name in DEFAULT_FILES]
    elif args.files:
        files = [Path(f) for f in args.files]
    else:
        ap.error("specify file paths or --all")

    PILOT_MD.mkdir(parents=True, exist_ok=True)

    total_written = total_skipped = 0
    for path in files:
        if not path.exists():
            print(f"  ⚠ skipping (not found): {path}", file=sys.stderr)
            continue

        # --limit: process subset by truncating file iteration in process_file
        if args.limit:
            # Write a temp file with first N lines and process that — quick smoke pattern
            with path.open("r", encoding="utf-8") as f:
                head_lines = [next(f, None) for _ in range(args.limit)]
            head_lines = [l for l in head_lines if l]
            tmp = path.with_suffix(".smoketest.tmp")
            tmp.write_text("".join(head_lines), encoding="utf-8")
            written, skipped = process_file(tmp, dry_run=args.dry_run)
            tmp.unlink()
        else:
            written, skipped = process_file(path, dry_run=args.dry_run)

        unit_hint = path.stem.split("-")[0] if "-" in path.stem else path.stem
        print(f"  {unit_hint:20s}  {written:>6} wrote   {skipped:>4} skipped", file=sys.stderr)
        total_written += written
        total_skipped += skipped

    print("", file=sys.stderr)
    action = "(dry-run) would write" if args.dry_run else "wrote"
    print(f"✓ {action} {total_written:,} files to {PILOT_MD.relative_to(REPO_ROOT)}/  "
          f"({total_skipped:,} skipped)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
