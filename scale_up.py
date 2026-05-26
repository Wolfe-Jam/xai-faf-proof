#!/usr/bin/env python3
"""Scale prototype to full memory corpus.

Pipeline:
  source: ~/.claude/projects/-Users-wolfejam/memory/*.md  (topic files only;
          MEMORY.md + MEMORY-FULL.md are indexes, excluded)
       → /PLANET-FAF/MEMORY-FAFB-PROOF/full-corpus/md/      sanitized
       → /PLANET-FAF/MEMORY-FAFB-PROOF/full-corpus/fafm/    structured YAML
       → /PLANET-FAF/MEMORY-FAFB-PROOF/full-corpus/bin/     custom binary + gz

Reports: per-tier sizes + the same 3-query bench at full scale.
"""

import os
import gzip
import json
import re
import statistics
import struct
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

import yaml

SRC_DIR = Path(os.environ.get("SRC_DIR", str(Path(__file__).resolve().parent / "pilot/md")))
WORK = Path(os.environ.get("WORK", str(Path(__file__).resolve().parent / "out")))
MD_DIR = WORK / "md"
FAFM_DIR = WORK / "fafm"
BIN_DIR = WORK / "bin"
for d in (MD_DIR, FAFM_DIR, BIN_DIR):
    d.mkdir(parents=True, exist_ok=True)

EXCLUDE = {"MEMORY.md", "MEMORY-FULL.md"}
REPEATS_WARM = 200

DATE_PATTERN = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
MD_REF_PATTERN = re.compile(r"`([a-z0-9_-]+\.md)`")

MAGIC = b"FAFM"


# ============================================================
# SANITIZE — copy .md, strip originSessionId
# ============================================================

def sanitize_md():
    n = 0
    for src in sorted(SRC_DIR.glob("*.md")):
        if src.name in EXCLUDE:
            continue
        text = src.read_text()
        # Strip any originSessionId line (top-level or indented)
        cleaned = "\n".join(ln for ln in text.splitlines()
                            if "originSessionId" not in ln)
        if not cleaned.endswith("\n"):
            cleaned += "\n"
        (MD_DIR / src.name).write_text(cleaned)
        n += 1
    return n


# ============================================================
# CONVERT — md → .fafm
# ============================================================

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
    if isinstance(fm, dict):
        if fm.get("type"):
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


def convert_one(src_path):
    content = src_path.read_text()
    fm, body = extract_frontmatter(content)
    if not isinstance(fm, dict):
        fm = {}
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
        "created": "2026-05-13T00:00:00Z",
        "last_etched": mtime.isoformat().replace("+00:00", "Z"),
        "retention": "forever",
        "memory": {"entries": [entry]},
    }

    dst = FAFM_DIR / (src_path.stem + ".fafm")
    with dst.open("w") as f:
        yaml.safe_dump(fafm, f, sort_keys=False, default_flow_style=False,
                       width=120, allow_unicode=True)
    return dst, entry


# ============================================================
# COMPILE — .fafm → .fafmbin (+gz)
# ============================================================

def _pack_str(s):
    if s is None:
        s = ""
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def _pack_str_list(items):
    if not items:
        return struct.pack("<H", 0)
    out = struct.pack("<H", len(items))
    for it in items:
        out += _pack_str(it)
    return out


def encode_fafm_binary(entries, source_text):
    header = MAGIC + struct.pack(
        "<2B H I I",
        1, 0, 0,
        zlib.crc32(source_text.encode()),
        len(entries),
    )
    body = b""
    for e in entries:
        body += _pack_str(e.get("source"))
        body += _pack_str(e.get("name") or "")
        body += _pack_str(e.get("description") or "")
        body += _pack_str(e.get("type") or "")
        body += _pack_str_list(e.get("dates") or [])
        body += _pack_str_list(e.get("related") or [])
        body += _pack_str(e.get("body") or "")
    return header + body


def decode_fafm_binary(data):
    if data[:4] != MAGIC:
        raise ValueError("bad magic")
    pos = 4
    _ma, _mi, _fl, _crc, n_entries = struct.unpack_from("<2B H I I", data, pos)
    pos += 12
    out = []

    def read_str():
        nonlocal pos
        (n,) = struct.unpack_from("<I", data, pos)
        pos += 4
        s = data[pos:pos + n].decode("utf-8")
        pos += n
        return s

    def read_list():
        nonlocal pos
        (n,) = struct.unpack_from("<H", data, pos)
        pos += 2
        return [read_str() for _ in range(n)]

    for _ in range(n_entries):
        out.append({
            "source": read_str(),
            "name": read_str(),
            "description": read_str(),
            "type": read_str(),
            "dates": read_list(),
            "related": read_list(),
            "body": read_str(),
        })
    return out


def compile_one(fafm_path, entry):
    source_text = fafm_path.read_text()
    bin_bytes = encode_fafm_binary([entry], source_text)
    bingz_bytes = gzip.compress(bin_bytes, compresslevel=9)
    stem = fafm_path.stem
    (BIN_DIR / f"{stem}.fafmbin").write_bytes(bin_bytes)
    (BIN_DIR / f"{stem}.fafmbin.gz").write_bytes(bingz_bytes)
    return len(bin_bytes), len(bingz_bytes)


# ============================================================
# RUN PIPELINE
# ============================================================

def run_pipeline():
    print("[1/3] Sanitizing .md files...")
    t0 = time.time()
    n_md = sanitize_md()
    print(f"      {n_md} files → {MD_DIR}  ({time.time()-t0:.1f}s)")

    print("\n[2/3] Converting .md → .fafm...")
    t0 = time.time()
    converted = []
    for src in sorted(MD_DIR.glob("*.md")):
        try:
            dst, entry = convert_one(src)
            converted.append((dst, entry))
        except Exception as e:
            print(f"      SKIP {src.name}: {e}")
    print(f"      {len(converted)} files → {FAFM_DIR}  ({time.time()-t0:.1f}s)")

    print("\n[3/3] Compiling .fafm → .fafmbin (+ .gz)...")
    t0 = time.time()
    bin_total = 0
    bingz_total = 0
    for fafm_path, entry in converted:
        bs, gs = compile_one(fafm_path, entry)
        bin_total += bs
        bingz_total += gs
    print(f"      {len(converted)} files × 2 → {BIN_DIR}  ({time.time()-t0:.1f}s)")

    return len(converted)


def report_sizes(n):
    md_total = sum(p.stat().st_size for p in MD_DIR.glob("*.md"))
    fafm_total = sum(p.stat().st_size for p in FAFM_DIR.glob("*.fafm"))
    bin_total = sum(p.stat().st_size for p in BIN_DIR.glob("*.fafmbin") if not p.name.endswith(".gz"))
    bingz_total = sum(p.stat().st_size for p in BIN_DIR.glob("*.fafmbin.gz"))

    def fmt(b):
        return f"{b/1024:.1f} KB ({b:,} B)"

    print(f"\n─── CORPUS SIZE ({n} memories) ───")
    print(f"  .md (sanitized):  {fmt(md_total)}")
    print(f"  .fafm (YAML):     {fmt(fafm_total)}  ({(fafm_total/md_total - 1)*100:+.1f}% vs md)")
    print(f"  .fafmbin (raw):   {fmt(bin_total)}  ({(bin_total/md_total - 1)*100:+.1f}% vs md)")
    print(f"  .fafmbin.gz:      {fmt(bingz_total)}  ({md_total/bingz_total:.2f}× smaller than md)")
    return md_total, fafm_total, bin_total, bingz_total


# ============================================================
# QUERY BENCH AT SCALE
# ============================================================

def load_md_full():
    return [(p.name, p.read_text()) for p in sorted(MD_DIR.glob("*.md"))]


def load_bin_full():
    out = []
    for p in sorted(BIN_DIR.glob("*.fafmbin")):
        if p.name.endswith(".gz"):
            continue
        for e in decode_fafm_binary(p.read_bytes()):
            out.append((p.stem, e))
    return out


def time_warm(fn, repeats=REPEATS_WARM):
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    return statistics.median(samples)


def time_cold(fn):
    t0 = time.perf_counter()
    r = fn()
    return time.perf_counter() - t0, r


def run_bench():
    print(f"\n─── QUERY BENCH (full corpus, {REPEATS_WARM} warm repeats) ───")

    # COLD
    cold_a, corpus_md = time_cold(load_md_full)
    cold_b, corpus_bin = time_cold(load_bin_full)
    print(f"\n  Cold corpus load:")
    print(f"    Lane A (.md read):       {cold_a*1000:>8.2f} ms")
    print(f"    Lane B (.fafmbin decode):{cold_b*1000:>8.2f} ms   ({cold_a/cold_b:.2f}× faster)")

    queries = [
        ("Q1 type=feedback",
         lambda: {n for n, t in corpus_md if re.search(r"^type:\s*feedback", t, re.MULTILINE)},
         lambda: {n for n, e in corpus_bin if e.get("type") == "feedback"}),
        ("Q2 mentions ZEPH",
         lambda: {n for n, t in corpus_md if "ZEPH" in t},
         lambda: {n for n, e in corpus_bin if "ZEPH" in (e.get("body") or "")}),
        ("Q3 dated 2026-05-13",
         lambda: {n for n, t in corpus_md if "2026-05-13" in t},
         lambda: {n for n, e in corpus_bin if "2026-05-13" in (e.get("dates") or [])}),
    ]

    print(f"\n  Warm (median):")
    print(f"    {'':22}{'Lane A':>14}{'Lane B':>14}{'B vs A':>14}{'A hits':>10}{'B hits':>10}")
    for label, fa, fb in queries:
        ma = time_warm(fa)
        mb = time_warm(fb)
        ra = ma / mb if mb > 0 else float("inf")
        a_hits = len(fa())
        b_hits = len(fb())
        print(f"    {label:22}{ma*1000:>10.3f} ms{mb*1000:>10.3f} ms{ra:>13.1f}×{a_hits:>10}{b_hits:>10}")


def main():
    n = run_pipeline()
    report_sizes(n)
    run_bench()


if __name__ == "__main__":
    main()
