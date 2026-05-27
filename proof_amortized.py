#!/usr/bin/env python3
"""Amortized proof — "prep once, query forever" measured on real corpora.

Runs N real queries against each lane, end-to-end wall-clock. No
extrapolation. Shows total cost per lane including one-time prep / cold load,
and the crossover point where the structured tier overtakes grep.

Two corpora measured side-by-side:
  - Claude memory  (/tmp/claude-mem-pilot/    — 674 records)
  - Smithsonian    (~/FAF/xai-faf-proof/pilot/ — 9,175 records)

Output: total wall-clock per lane × N queries, breakeven crossover.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Native .fafmbin decoder (custom binary format — no JSON parse step)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compile_to_binary import decode_fafm_binary  # noqa: E402


def fmt(seconds: float) -> str:
    if seconds >= 1.0:
        return f"{seconds:.2f} s"
    if seconds >= 0.001:
        return f"{seconds*1000:.2f} ms"
    return f"{seconds*1_000_000:.2f} µs"


def run_grep_n(md_dir: Path, pattern: str, n: int) -> float:
    """Run N actual subprocess grep calls. Returns total elapsed seconds."""
    t0 = time.perf_counter()
    for _ in range(n):
        subprocess.run(
            ["grep", "-l", "-r", "-E", pattern, str(md_dir)],
            capture_output=True, text=True, check=False,
        )
    return time.perf_counter() - t0


def load_jgz_corpus(bin_dir: Path) -> tuple[float, list[tuple[str, dict]]]:
    """Cold load .jgz corpus into memory. Returns (load_seconds, entries)."""
    t0 = time.perf_counter()
    entries = []
    for p in sorted(bin_dir.glob("*.jgz")):
        doc = json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))
        for e in doc["memory"]["entries"]:
            entries.append((e["source"].rsplit(".", 1)[0], e))
    return time.perf_counter() - t0, entries


def load_fafmbin_corpus(bin_dir: Path) -> tuple[float, list[tuple[str, dict]]]:
    """Cold load native .fafmbin corpus — fastest possible (no JSON parse)."""
    t0 = time.perf_counter()
    entries = []
    for p in sorted(bin_dir.glob("*.fafmbin")):
        # Skip .fafmbin.gz files (filtered by extension)
        if p.suffix != ".fafmbin":
            continue
        doc = decode_fafm_binary(p.read_bytes())
        for e in doc["entries"]:
            entries.append((e["source"].rsplit(".", 1)[0], e))
    return time.perf_counter() - t0, entries


def run_structured_n(entries: list, type_value: str, n: int) -> float:
    """Run N queries against pre-loaded structured corpus. Returns total seconds."""
    t0 = time.perf_counter()
    for _ in range(n):
        _result = {name for name, e in entries if e.get("type") == type_value}
    return time.perf_counter() - t0


def prove_one_corpus(label: str, md_dir: Path, bin_dir: Path,
                     grep_pattern: str, structured_type: str, n: int) -> dict:
    """Run the full amortization proof for one corpus."""
    print(f"\n  ── Corpus: {label} ──")
    md_count = len(list(md_dir.glob("*.md")))
    bin_count = len(list(bin_dir.glob("*.jgz")))
    print(f"     records: {md_count:,} .md  ·  {bin_count:,} .jgz")
    print(f"     query:   type={structured_type}  (n={n} queries per lane)")
    print()

    # Lane A: subprocess grep × N
    print(f"     [Lane A] running {n} subprocess grep calls...", end="", flush=True)
    t_grep = run_grep_n(md_dir, grep_pattern, n)
    print(f"  ✓ {fmt(t_grep):>10}  ({fmt(t_grep/n)} per call)")

    # Lane C: cold load .jgz once + N structured queries
    print(f"     [Lane C] cold loading .jgz corpus...      ", end="", flush=True)
    t_load_c, entries_c = load_jgz_corpus(bin_dir)
    print(f"  ✓ {fmt(t_load_c):>10}  ({len(entries_c):,} entries)")

    print(f"     [Lane C] running {n} structured queries...", end="", flush=True)
    t_query_c = run_structured_n(entries_c, structured_type, n)
    print(f"  ✓ {fmt(t_query_c):>10}  ({fmt(t_query_c/n)} per query)")

    # Lane D: native .fafmbin — fastest possible
    print(f"     [Lane D] cold loading .fafmbin (native)...", end="", flush=True)
    t_load_d, entries_d = load_fafmbin_corpus(bin_dir)
    print(f"  ✓ {fmt(t_load_d):>10}  ({len(entries_d):,} entries)")

    print(f"     [Lane D] running {n} structured queries...", end="", flush=True)
    t_query_d = run_structured_n(entries_d, structured_type, n)
    print(f"  ✓ {fmt(t_query_d):>10}  ({fmt(t_query_d/n)} per query)")

    # Lane C metrics (.jgz)
    t_total_c = t_load_c + t_query_c
    speedup_amortized_c = t_grep / t_total_c if t_total_c > 0 else float("inf")
    speedup_per_query_c = (t_grep / n) / (t_query_c / n) if t_query_c > 0 else float("inf")
    grep_per = t_grep / n
    q_per_c = t_query_c / n
    breakeven_c = t_load_c / (grep_per - q_per_c) if grep_per > q_per_c else float("inf")

    # Lane D metrics (.fafmbin native)
    t_total_d = t_load_d + t_query_d
    speedup_amortized_d = t_grep / t_total_d if t_total_d > 0 else float("inf")
    speedup_per_query_d = (t_grep / n) / (t_query_d / n) if t_query_d > 0 else float("inf")
    q_per_d = t_query_d / n
    breakeven_d = t_load_d / (grep_per - q_per_d) if grep_per > q_per_d else float("inf")

    print()
    print(f"     ── Result ──")
    print(f"     Lane A   total ({n} grep calls):                  {fmt(t_grep):>12}")
    print(f"     Lane C   total (.jgz   load + {n} queries):       {fmt(t_total_c):>12}")
    print(f"     Lane D   total (.fafmbin native load + {n}):       {fmt(t_total_d):>12}")
    print(f"     ─────────────────────────────────────────────────────────")
    print(f"     Lane C — Amortized speedup vs grep:           {speedup_amortized_c:>10.1f}×")
    print(f"     Lane C — Per-query speedup (after load):      {speedup_per_query_c:>10.1f}×")
    print(f"     Lane C — Breakeven:                           {breakeven_c:>10.1f} queries")
    print(f"     ─────────────────────────────────────────────────────────")
    print(f"     Lane D — Amortized speedup vs grep:           {speedup_amortized_d:>10.1f}×  (FASTEST possible)")
    print(f"     Lane D — Per-query speedup (after load):      {speedup_per_query_d:>10.1f}×")
    print(f"     Lane D — Breakeven:                           {breakeven_d:>10.1f} queries")
    print()

    return {
        "label": label,
        "n": n,
        "t_grep_total": t_grep,
        "lane_c": {"load": t_load_c, "query_total": t_query_c,
                   "amortized": speedup_amortized_c, "per_query": speedup_per_query_c,
                   "breakeven": breakeven_c},
        "lane_d": {"load": t_load_d, "query_total": t_query_d,
                   "amortized": speedup_amortized_d, "per_query": speedup_per_query_d,
                   "breakeven": breakeven_d},
    }


def main():
    n = int(os.environ.get("N", "100"))

    print()
    print("  ╔══════════════════════════════════════════════════════════════════╗")
    print("  ║   AMORTIZED PROOF — 'Prep once, query forever'                   ║")
    print("  ║   N = {0:<5} real queries per lane per corpus                       ║".format(n))
    print("  ╚══════════════════════════════════════════════════════════════════╝")

    results = []

    # Corpus 1: Claude memory
    cm_md = Path("/tmp/claude-mem-pilot/md")
    cm_bin = Path("/tmp/claude-mem-pilot/bin")
    if cm_md.exists() and cm_bin.exists():
        r = prove_one_corpus(
            "Claude memory (real-world frontmatter)",
            cm_md, cm_bin,
            grep_pattern=r"^[[:space:]]*type:[[:space:]]*feedback[[:space:]]*$",
            structured_type="feedback",
            n=n,
        )
        results.append(r)
    else:
        print("  ⚠ Claude memory pilot not found at /tmp/claude-mem-pilot — skipping")

    # Corpus 2: Smithsonian
    sm_md = Path(__file__).resolve().parent / "pilot/md"
    sm_bin = Path(__file__).resolve().parent / "pilot/bin"
    if sm_md.exists() and sm_bin.exists() and list(sm_md.glob("*.md")):
        r = prove_one_corpus(
            "Smithsonian Open Access (9,175 EDAN records)",
            sm_md, sm_bin,
            grep_pattern=r"^type: ead_component$",
            structured_type="ead_component",
            n=n,
        )
        results.append(r)
    else:
        print("  ⚠ Smithsonian pilot not found at ./pilot — skipping")

    # Final comparison table
    print()
    print("  ╔══════════════════════════════════════════════════════════════════╗")
    print("  ║   RESULTS — measured, not extrapolated                           ║")
    print("  ╚══════════════════════════════════════════════════════════════════╝")
    print()
    print(f"  {'Corpus':<45} {'Lane':<6} {'Amortized':>12} {'Per-query':>12} {'Breakeven':>11}")
    print(f"  {'':45} {'':<6} {'(N='+str(n)+')':>12} {'(peak)':>12} {'(queries)':>11}")
    print("  " + "-" * 93)
    for r in results:
        c = r['lane_c']; d = r['lane_d']
        print(f"  {r['label']:<45} {'C (.jgz)':<6}    {c['amortized']:>9.1f}× {c['per_query']:>10.1f}× {c['breakeven']:>10.1f}")
        print(f"  {'':<45} {'D (bin)':<6}    {d['amortized']:>9.1f}× {d['per_query']:>10.1f}× {d['breakeven']:>10.1f}")
    print()
    print(f"  ON-OFF speed (amortized, N={n}): the realistic measurement including cold load.")
    print(f"  FASTEST POSSIBLE (per-query peak): the asymptote — what a hot service delivers.")
    print(f"  Lane C  = .jgz (gzipped JSON, parsed at load)")
    print(f"  Lane D  = .fafmbin (native custom binary, no JSON parse — the FASTEST tier)")
    print()


if __name__ == "__main__":
    main()
