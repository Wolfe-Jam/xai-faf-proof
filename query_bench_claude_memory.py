#!/usr/bin/env python3
"""Claude-memory query benchmark — same methodology as query_bench_smithsonian.py,
adapted for the original `~/.claude/projects/-Users-wolfejam/memory/` corpus
shape (frontmatter has nested `metadata.type` field rather than top-level type).

Queries (chosen to mirror faf-memory-proof's original 412× run):
  Q1 type=feedback (under metadata:)      — structured field filter
  Q2 substring "ZEPH"                     — substring query (grep's strength)

Run AFTER staging /tmp/claude-mem-pilot/{md,fafm,bin}/ from the Claude memory
dir + running convert_md_to_fafm.py + compile_to_binary.py against it.
"""

import gzip
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

import yaml

MD_DIR = Path(os.environ.get("MD_DIR", "/tmp/claude-mem-pilot/md"))
FAFM_DIR = Path(os.environ.get("FAFM_DIR", "/tmp/claude-mem-pilot/fafm"))
BIN_DIR = Path(os.environ.get("BIN_DIR", "/tmp/claude-mem-pilot/bin"))
REPEATS = int(os.environ.get("REPEATS", "100"))
REPEATS_GREP = int(os.environ.get("REPEATS_GREP", "20"))


def stem(name):
    return name.rsplit(".", 1)[0]


def fmt_us(seconds):
    us = seconds * 1_000_000
    if us >= 1000:
        return f"{us/1000:.2f} ms"
    return f"{us:.2f} µs"


# ============================================================
# LANE A — subprocess grep
# Note: Claude memory frontmatter uses `metadata:` with nested `  type: X`,
# so the grep pattern includes the 2-space indent.
# ============================================================

def a_grep_q1_type_feedback():
    """grep for `type: feedback` — matches BOTH frontmatter shapes:
       top-level (older files: `type: feedback`) AND nested under metadata
       (newer files: `  type: feedback` with 2-space indent).
    """
    result = subprocess.run(
        ["grep", "-l", "-r", "-E", r"^[[:space:]]*type:[[:space:]]*feedback[[:space:]]*$", str(MD_DIR)],
        capture_output=True, text=True, check=False,
    )
    return {Path(line).stem for line in result.stdout.splitlines() if line}


def a_grep_q2_substring_zeph():
    result = subprocess.run(
        ["grep", "-l", "-r", "ZEPH", str(MD_DIR)],
        capture_output=True, text=True, check=False,
    )
    return {Path(line).stem for line in result.stdout.splitlines() if line}


# ============================================================
# LANE A' — in-mem Python regex
# ============================================================

def a_load_md():
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted(MD_DIR.glob("*.md"))]


def a_q1_type_feedback(corpus):
    """Match both top-level and metadata-nested type field."""
    return {stem(name) for name, text in corpus
            if re.search(r"^\s*type:\s*feedback\s*$", text, re.MULTILINE)}


def a_q2_substring_zeph(corpus):
    return {stem(name) for name, text in corpus if "ZEPH" in text}


# ============================================================
# LANE B — structured query on .fafm
# ============================================================

def b_load_fafm():
    out = []
    for p in sorted(FAFM_DIR.glob("*.fafm")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        for e in doc["memory"]["entries"]:
            out.append((stem(e["source"]), e))
    return out


def b_q1_type_feedback(entries):
    return {name for name, e in entries if e.get("type") == "feedback"}


def b_q2_substring_zeph(entries):
    return {name for name, e in entries if "ZEPH" in (e.get("body") or "")}


# ============================================================
# LANE C — .jgz (gzipped JSON) binary tier
# ============================================================

def c_load_fafmbin():
    out = []
    for p in sorted(BIN_DIR.glob("*.jgz")):
        doc = json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))
        for e in doc["memory"]["entries"]:
            out.append((stem(e["source"]), e))
    return out


def c_q1_type_feedback(entries):
    return {name for name, e in entries if e.get("type") == "feedback"}


def c_q2_substring_zeph(entries):
    return {name for name, e in entries if "ZEPH" in (e.get("body") or "")}


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
    print("  ║   query_bench_claude_memory — apples-to-apples with original 412×║")
    print("  ║   Corpus: 674 .md files (Claude persistent memory dir)            ║")
    print("  ╚══════════════════════════════════════════════════════════════════╝")
    print()
    print(f"  Corpus:  {MD_DIR}")
    print(f"           {len(list(MD_DIR.glob('*.md'))):,} .md  ·  "
          f"{len(list(FAFM_DIR.glob('*.fafm'))):,} .fafm  ·  "
          f"{len(list(BIN_DIR.glob('*.jgz'))):,} .jgz")
    print(f"  Repeats: {REPEATS} (warm)  ·  {REPEATS_GREP} (subprocess grep)")
    print()

    print("─── COLD LOAD ───")
    t0 = time.perf_counter(); md_corpus = a_load_md(); md_load = time.perf_counter() - t0
    print(f"  Lane A' — .md   load: {fmt_us(md_load):>12}")
    t0 = time.perf_counter(); fafm_corpus = b_load_fafm(); fafm_load = time.perf_counter() - t0
    print(f"  Lane B  — .fafm load: {fmt_us(fafm_load):>12}")
    t0 = time.perf_counter(); bin_corpus = c_load_fafmbin(); bin_load = time.perf_counter() - t0
    print(f"  Lane C  — .jgz  load: {fmt_us(bin_load):>12}")
    print()

    gt_q1 = a_q1_type_feedback(md_corpus)
    gt_q2 = a_q2_substring_zeph(md_corpus)
    print("─── GROUND TRUTH ───")
    print(f"  Q1 type=feedback        : {len(gt_q1):,} matches")
    print(f"  Q2 'ZEPH' substring     : {len(gt_q2):,} matches")
    print()

    print(f"─── WARM bench ({REPEATS} repeats in-mem, {REPEATS_GREP} for subprocess grep) ───")
    print()

    for label, fn_grep, fn_regex, fn_b, fn_c, gt in [
        ("Q1 type=feedback",
         a_grep_q1_type_feedback,
         a_q1_type_feedback, b_q1_type_feedback, c_q1_type_feedback, gt_q1),
        ("Q2 'ZEPH' substring",
         a_grep_q2_substring_zeph,
         a_q2_substring_zeph, b_q2_substring_zeph, c_q2_substring_zeph, gt_q2),
    ]:
        print(f"  ── {label} ──  (ground truth: {len(gt):,} matches)")
        t_grep = time_op(fn_grep, repeats=REPEATS_GREP); ok_grep = "✓" if fn_grep() == gt else "✗"
        t_regex = time_op(fn_regex, md_corpus); ok_regex = "✓" if fn_regex(md_corpus) == gt else "✗"
        t_b = time_op(fn_b, fafm_corpus); ok_b = "✓" if fn_b(fafm_corpus) == gt else "✗"
        t_c = time_op(fn_c, bin_corpus); ok_c = "✓" if fn_c(bin_corpus) == gt else "✗"

        rb_grep = t_grep / t_b if t_b > 0 else float("inf")
        rc_grep = t_grep / t_c if t_c > 0 else float("inf")
        rb_regex = t_regex / t_b if t_b > 0 else float("inf")
        rc_regex = t_regex / t_c if t_c > 0 else float("inf")

        print(f"    Lane A  subprocess grep:    {fmt_us(t_grep):>12}  {ok_grep}")
        print(f"    Lane A' in-mem regex:       {fmt_us(t_regex):>12}  {ok_regex}")
        print(f"    Lane B  .fafm structured:   {fmt_us(t_b):>12}  {ok_b}")
        print(f"    Lane C  .jgz binary tier:   {fmt_us(t_c):>12}  {ok_c}")
        print(f"    Speedup vs grep:     B = {rb_grep:>7.1f}×   C = {rc_grep:>7.1f}×")
        print(f"    Speedup vs regex:    B = {rb_regex:>7.1f}×   C = {rc_regex:>7.1f}×")
        print()


if __name__ == "__main__":
    main()
