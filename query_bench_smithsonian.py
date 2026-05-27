#!/usr/bin/env python3
"""Smithsonian query benchmark — Lane A (grep on .md) vs Lane B (structured on .fafm) vs Lane C (binary on .fafmbin).

Three queries with ground truth computed at startup from the actual corpus:
  Q1 type=ead_component        — structured field query (binary's strength)
  Q2 mentions "American"       — literal substring query (grep's strength)
  Q3 priority=high             — structured field query (priority floor)

Times each query at COLD (first run, includes corpus load) and WARM
(median over N runs, corpus pre-loaded).

Designed for the Smithsonian EDAN corpus (~9,175 records across 6 units).
Generalizes the methodology from query_bench.py without the proto-* hardcodes.
"""

import gzip
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

import yaml

MD_DIR = Path(os.environ.get("MD_DIR", str(Path(__file__).resolve().parent / "pilot/md")))
FAFM_DIR = Path(os.environ.get("FAFM_DIR", str(Path(__file__).resolve().parent / "pilot/fafm")))
BIN_DIR = Path(os.environ.get("BIN_DIR", str(Path(__file__).resolve().parent / "pilot/bin")))
REPEATS = int(os.environ.get("REPEATS", "100"))            # in-mem lanes
REPEATS_GREP = int(os.environ.get("REPEATS_GREP", "20"))   # subprocess grep is slower per call


def stem(name):
    return name.rsplit(".", 1)[0]


def fmt_us(seconds):
    """Format a duration in microseconds (3 sig figs)."""
    us = seconds * 1_000_000
    if us >= 1000:
        return f"{us/1000:.2f} ms"
    return f"{us:.2f} µs"


# ============================================================
# LANE A — grep over .md (read every file every query)
# ============================================================

def a_load_md():
    """Read all .md files. Returns list of (name, text)."""
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted(MD_DIR.glob("*.md"))]


def a_q1_type_ead_component(corpus):
    """Q1: type=ead_component via grep on frontmatter."""
    return {stem(name) for name, text in corpus
            if re.search(r"^type:\s*ead_component\s*$", text, re.MULTILINE)}


def a_q2_substring_american(corpus):
    """Q2: substring "American" anywhere in file."""
    return {stem(name) for name, text in corpus if "American" in text}


def a_q3_priority_high(corpus):
    """Q3: priority=high via grep on frontmatter."""
    return {stem(name) for name, text in corpus
            if re.search(r"^priority:\s*high\s*$", text, re.MULTILINE)}


# ============================================================
# LANE A' — subprocess grep (real `grep` binary, apples-to-apples
# with faf-memory-proof's original baseline — includes per-call spawn cost)
# ============================================================

def a_grep_q1_type_ead_component():
    """Subprocess `grep` for `^type: ead_component$` across pilot/md/."""
    result = subprocess.run(
        ["grep", "-l", "-r", "^type: ead_component$", str(MD_DIR)],
        capture_output=True, text=True, check=False,
    )
    return {Path(line).stem for line in result.stdout.splitlines() if line}


def a_grep_q2_substring_american():
    """Subprocess `grep` for substring 'American' across pilot/md/."""
    result = subprocess.run(
        ["grep", "-l", "-r", "American", str(MD_DIR)],
        capture_output=True, text=True, check=False,
    )
    return {Path(line).stem for line in result.stdout.splitlines() if line}


def a_grep_q3_priority_high():
    """Subprocess `grep` for `^priority: high$` across pilot/md/."""
    result = subprocess.run(
        ["grep", "-l", "-r", "^priority: high$", str(MD_DIR)],
        capture_output=True, text=True, check=False,
    )
    return {Path(line).stem for line in result.stdout.splitlines() if line}


# ============================================================
# LANE B — structured query on .fafm (parse once, query in-memory)
# ============================================================

def b_load_fafm():
    """Parse all .fafm into a flat list of (source_stem, entry_dict)."""
    out = []
    for p in sorted(FAFM_DIR.glob("*.fafm")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        for e in doc["memory"]["entries"]:
            out.append((stem(e["source"]), e))
    return out


def b_q1_type_ead_component(entries):
    return {name for name, e in entries if e.get("type") == "ead_component"}


def b_q2_substring_american(entries):
    """Same substring search but on the body field of the structured entry."""
    out = set()
    for name, e in entries:
        body = e.get("body") or ""
        if "American" in body:
            out.add(name)
    return out


def b_q3_priority_high(entries):
    """Priority isn't in the entry dict the FAFM converter emits — need to
    read it from the source .md frontmatter or recompute from the .fafm file.

    For this benchmark we re-extract priority from the original .md frontmatter
    so Lane B works on the structured FAFM data alone. To avoid coupling, we
    parse priority from the body's `priority: <x>` line if it's there, OR fall
    back to grep on the source .md file.

    Simpler: load the priority once at .fafm-load time. We add a side-cache
    keyed by source. This pre-parse is part of Lane B's "loaded once" model.
    """
    # Note: priority should be in the .fafm if the converter preserved it.
    # The current convert_md_to_fafm.py drops priority. So Lane B Q3 returns
    # empty for now — flagged as known limitation. Lane A and Lane C handle it.
    return set()


# ============================================================
# LANE C — binary tier (.fafmbin) — same query, decode-as-needed
# ============================================================

def c_load_fafmbin():
    """Decode all .fafmbin into a flat list of (source_stem, entry_dict).

    For this bench, we round-trip via the .fafm content (decode = re-parse).
    The actual .fafmbin format encoding is in compile_to_binary.py; we read
    the .jgz (gzipped JSON) variant here as it's the fastest structured read.
    """
    out = []
    import json
    for p in sorted(BIN_DIR.glob("*.jgz")):
        doc = json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))
        for e in doc["memory"]["entries"]:
            out.append((stem(e["source"]), e))
    return out


def c_q1_type_ead_component(entries):
    return {name for name, e in entries if e.get("type") == "ead_component"}


def c_q2_substring_american(entries):
    out = set()
    for name, e in entries:
        body = e.get("body") or ""
        if "American" in body:
            out.add(name)
    return out


def c_q3_priority_high(entries):
    """Same caveat as Lane B."""
    return set()


# ============================================================
# Harness
# ============================================================

def time_op(fn, *args, repeats=None):
    if repeats is None:
        repeats = REPEATS
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn(*args)
        samples.append(time.perf_counter() - t0)
    return statistics.median(samples)


def main():
    print()
    print("  ╔══════════════════════════════════════════════════════════════════╗")
    print("  ║   xai-faf-proof — Smithsonian corpus query benchmark             ║")
    print("  ║   Lane A (grep .md)  vs  Lane B (.fafm)  vs  Lane C (.fafmbin)   ║")
    print("  ╚══════════════════════════════════════════════════════════════════╝")
    print()

    print(f"  Corpus:  {MD_DIR}")
    md_count = len(list(MD_DIR.glob("*.md")))
    fafm_count = len(list(FAFM_DIR.glob("*.fafm")))
    bin_count = len(list(BIN_DIR.glob("*.jgz")))
    print(f"           {md_count:,} .md  ·  {fafm_count:,} .fafm  ·  {bin_count:,} .jgz")
    print(f"  Repeats: {REPEATS} (warm)")
    print()

    # ---------- Load once (Lane B and C are "loaded once" benchmarks) ----------
    print("─── COLD LOAD (one-shot, corpus → memory) ───")
    t0 = time.perf_counter()
    md_corpus = a_load_md()
    md_load = time.perf_counter() - t0
    print(f"  Lane A — .md   load: {fmt_us(md_load):>10}  ({md_count} files)")

    t0 = time.perf_counter()
    fafm_corpus = b_load_fafm()
    fafm_load = time.perf_counter() - t0
    print(f"  Lane B — .fafm load: {fmt_us(fafm_load):>10}  ({len(fafm_corpus)} entries)")

    t0 = time.perf_counter()
    bin_corpus = c_load_fafmbin()
    bin_load = time.perf_counter() - t0
    print(f"  Lane C — .jgz  load: {fmt_us(bin_load):>10}  ({len(bin_corpus)} entries)")
    print()

    # ---------- Compute ground truth ----------
    gt_q1 = a_q1_type_ead_component(md_corpus)
    gt_q2 = a_q2_substring_american(md_corpus)
    gt_q3 = a_q3_priority_high(md_corpus)
    print("─── GROUND TRUTH (from Lane A grep) ───")
    print(f"  Q1 type=ead_component : {len(gt_q1):,} matches")
    print(f"  Q2 'American' substr  : {len(gt_q2):,} matches")
    print(f"  Q3 priority=high      : {len(gt_q3):,} matches")
    print()

    # ---------- WARM bench (corpus pre-loaded) ----------
    print(f"─── WARM bench ({REPEATS} repeats in-mem, {REPEATS_GREP} for subprocess grep) ───")
    print()

    queries = [
        ("Q1 type=ead_component",
         a_grep_q1_type_ead_component,
         a_q1_type_ead_component, b_q1_type_ead_component, c_q1_type_ead_component, gt_q1),
        ("Q2 'American' substring",
         a_grep_q2_substring_american,
         a_q2_substring_american, b_q2_substring_american, c_q2_substring_american, gt_q2),
    ]

    for label, fn_grep, fn_regex, fn_b, fn_c, gt in queries:
        print(f"  ── {label} ──  (ground truth: {len(gt):,} matches)")

        # Subprocess grep (apples-to-apples with original faf-memory-proof baseline)
        t_grep = time_op(fn_grep, repeats=REPEATS_GREP)
        result_grep = fn_grep()
        ok_grep = "✓" if result_grep == gt else "✗"

        # In-mem Python regex (optimistic baseline — corpus already loaded)
        t_regex = time_op(fn_regex, md_corpus)
        result_regex = fn_regex(md_corpus)
        ok_regex = "✓" if result_regex == gt else "✗"

        # Lane B — structured query on .fafm (parsed once, queried in-mem)
        t_b = time_op(fn_b, fafm_corpus)
        ok_b = "✓" if fn_b(fafm_corpus) == gt else "✗"

        # Lane C — structured query on .jgz (gzipped JSON, decoded once)
        t_c = time_op(fn_c, bin_corpus)
        ok_c = "✓" if fn_c(bin_corpus) == gt else "✗"

        # Speedups vs both baselines
        rb_grep = t_grep / t_b if t_b > 0 else float("inf")
        rc_grep = t_grep / t_c if t_c > 0 else float("inf")
        rb_regex = t_regex / t_b if t_b > 0 else float("inf")
        rc_regex = t_regex / t_c if t_c > 0 else float("inf")

        print(f"    Lane A  subprocess grep:    {fmt_us(t_grep):>12}  {ok_grep}    (per-call grep + spawn)")
        print(f"    Lane A' in-mem regex:       {fmt_us(t_regex):>12}  {ok_regex}    (pre-loaded text + re.search)")
        print(f"    Lane B  .fafm structured:   {fmt_us(t_b):>12}  {ok_b}    (parsed-once, in-mem .get)")
        print(f"    Lane C  .jgz binary tier:   {fmt_us(t_c):>12}  {ok_c}    (gzipped JSON, decoded-once)")
        print(f"    Speedup vs grep:     B = {rb_grep:>7.1f}×   C = {rc_grep:>7.1f}×")
        print(f"    Speedup vs regex:    B = {rb_regex:>7.1f}×   C = {rc_regex:>7.1f}×")
        print()

    print("  Notes:")
    print("    Lane A (subprocess grep)  — apples-to-apples with faf-memory-proof's 412× baseline.")
    print("    Lane A' (in-mem regex)    — optimistic baseline; corpus already loaded into Python.")
    print("    Q1 (type-filter)          — structured tiers' natural strength.")
    print("    Q2 (substring)            — grep's natural strength; structured loses or ties.")
    print("    Q3 (priority)             — pending: convert_md_to_fafm.py doesn't carry priority.")
    print()


if __name__ == "__main__":
    main()
