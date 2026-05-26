#!/usr/bin/env python3
"""md → .fafm converter for the AI memory-corpus profile.

Profile: see ~/.claude/projects/-Users-wolfejam/memory/fafm-memory-corpus-profile.md
Workspace: /PLANET-FAF/MEMORY-FAFB-PROOF/
"""

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SOURCE_DIR = Path(os.environ.get("SOURCE_DIR", str(Path(__file__).resolve().parent / "pilot/md")))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", str(Path(__file__).resolve().parent / "pilot/fafm")))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DATE_PATTERN = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
MD_REF_PATTERN = re.compile(r"`([a-z0-9_-]+\.md)`")
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{2,}")


def extract_frontmatter(content):
    if not content.startswith("---\n"):
        return {}, content
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, content
    fm_text = content[4:end]
    body = content[end + 5:]
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, body


def normalize_type(fm):
    if "type" in fm and fm["type"]:
        return fm["type"]
    meta = fm.get("metadata", {})
    if isinstance(meta, dict) and meta.get("type"):
        return meta["type"]
    return None


def extract_dates(body):
    return sorted(set(DATE_PATTERN.findall(body)))


def extract_related(body):
    refs = set()
    for m in WIKILINK_PATTERN.finditer(body):
        ref = m.group(1).strip()
        if not ref.endswith(".md"):
            ref += ".md"
        refs.add(ref)
    for m in MD_REF_PATTERN.finditer(body):
        refs.add(m.group(1))
    return sorted(refs)


def extract_tokens(body):
    # Strip code blocks first
    cleaned = re.sub(r"```[^`]*```", "", body, flags=re.DOTALL)
    cleaned = re.sub(r"`[^`]*`", "", cleaned)
    return sorted(set(TOKEN_PATTERN.findall(cleaned)))


def convert_one(src_path):
    content = src_path.read_text()
    fm, body = extract_frontmatter(content)
    mtime = datetime.fromtimestamp(src_path.stat().st_mtime, tz=timezone.utc)

    entry = {
        "source": src_path.name,
        "name": fm.get("name") or "",
        "description": fm.get("description") or "",
        "type": normalize_type(fm),
        "dates": extract_dates(body),
        "related": extract_related(body),
        "body": body.strip(),
    }

    fafm = {
        "version": "1.0",
        "namepoint": "@wolfejam-memory",
        "created": "2026-05-13T12:58:00Z",
        "last_etched": mtime.isoformat().replace("+00:00", "Z"),
        "retention": "forever",
        "memory": {"entries": [entry]},
    }

    dst_path = OUTPUT_DIR / (src_path.stem + ".fafm")
    with dst_path.open("w") as f:
        yaml.safe_dump(fafm, f, sort_keys=False, default_flow_style=False,
                       width=120, allow_unicode=True)
    return dst_path, len(content.encode()), dst_path.stat().st_size


def main():
    print(f"Converting {SOURCE_DIR} -> {OUTPUT_DIR}\n")
    print(f"{'Source':<45} {'MD bytes':>10} {'FAFM bytes':>12} {'Delta':>10}")
    print("-" * 80)
    md_total = 0
    fafm_total = 0
    for src in sorted(SOURCE_DIR.glob("proto-*.md")):
        _, md_bytes, fafm_bytes = convert_one(src)
        md_total += md_bytes
        fafm_total += fafm_bytes
        delta = fafm_bytes - md_bytes
        sign = "+" if delta >= 0 else ""
        print(f"{src.name:<45} {md_bytes:>10} {fafm_bytes:>12} {sign}{delta:>9}")
    print("-" * 80)
    pct = (fafm_total - md_total) / md_total * 100
    print(f"{'TOTAL':<45} {md_total:>10} {fafm_total:>12} {pct:+9.1f}%")


if __name__ == "__main__":
    main()
