#!/usr/bin/env python3
"""Query harness — Lane A (grep on .md) vs Lane B (structured on .fafm).

Three queries with verified ground truth:
  Q1 type=feedback   — structured field query   GT = {01, 06, 10}
  Q2 mentions ZEPH   — literal keyword query    GT = {03, 04}
  Q3 dated 2026-05-13 — structured field query  GT = {03, 04, 05, 09}

Times each query at COLD (first run) and WARM (median over N runs).
"""

import os
import re
import statistics
import sys
import time
from pathlib import Path

import yaml

MD_DIR = Path(os.environ.get("MD_DIR", str(Path(__file__).resolve().parent / "pilot/md")))
FAFM_DIR = Path(os.environ.get("FAFM_DIR", str(Path(__file__).resolve().parent / "pilot/fafm")))
REPEATS = 1000

GROUND_TRUTH = {
    "Q1: type=feedback": {"proto-01-feedback-tier-symbols",
                          "proto-06-complementary-no-disputes",
                          "proto-10-no-timelines"},
    "Q2: mentions ZEPH": {"proto-03-rom-defines-ram-executes",
                          "proto-04-mcp-family"},
    "Q3: dated 2026-05-13": {"proto-03-rom-defines-ram-executes",
                             "proto-04-mcp-family",
                             "proto-05-runtime-stack",
                             "proto-09-wins-banned"},
}


def stem(name):
    return name.rsplit(".", 1)[0]


# ============================================================
# LANE A — grep over .md (no cache, no parse, scan every query)
# ============================================================

def a_load_md():
    """Read all .md files from disk. Returns list of (name, text)."""
    return [(p.name, p.read_text()) for p in sorted(MD_DIR.glob("proto-*.md"))]


def a_q1_type_feedback(corpus):
    return {stem(name) for name, text in corpus
            if re.search(r"^type:\s*feedback", text, re.MULTILINE)}


def a_q2_zeph(corpus):
    return {stem(name) for name, text in corpus if "ZEPH" in text}


def a_q3_date(corpus):
    return {stem(name) for name, text in corpus if "2026-05-13" in text}


# ============================================================
# LANE B — structured query on .fafm (load + parse once, in-memory thereafter)
# ============================================================

def b_load_fafm():
    """Parse all .fafm into entry list. Returns list of (source_stem, entry_dict)."""
    out = []
    for p in sorted(FAFM_DIR.glob("proto-*.fafm")):
        doc = yaml.safe_load(p.read_text())
        for e in doc["memory"]["entries"]:
            out.append((stem(e["source"]), e))
    return out


def b_q1_type_feedback(entries):
    return {name for name, e in entries if e.get("type") == "feedback"}


def b_q2_zeph(entries):
    """Body substring + related-link match. Body_tokens deferred to .fafb tier."""
    out = set()
    for name, e in entries:
        body = e.get("body") or ""
        if "ZEPH" in body:
            out.add(name)
            continue
        if any("zeph" in (r or "").lower() for r in (e.get("related") or [])):
            out.add(name)
    return out


def b_q3_date(entries):
    return {name for name, e in entries if "2026-05-13" in (e.get("dates") or [])}


# ============================================================
# HARNESS
# ============================================================

def time_cold(fn):
    t0 = time.perf_counter()
    result = fn()
    return time.perf_counter() - t0, result


def time_warm(fn, repeats=REPEATS):
    samples = []
    result = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = fn()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    return statistics.median(samples), samples[0], samples[-1], result


def fmt_us(seconds):
    return f"{seconds * 1_000_000:>10.2f} µs"


def fmt_ms(seconds):
    return f"{seconds * 1000:>10.3f} ms"


def precision_recall(predicted, truth):
    if not predicted:
        return 0.0, 0.0
    tp = len(predicted & truth)
    p = tp / len(predicted)
    r = tp / len(truth) if truth else 1.0
    return p, r


def main():
    t_start = time.perf_counter()
    print("─" * 72)
    print("  FAF memory proof — query benchmark  (Lane A grep vs Lane B structured)")
    print("─" * 72)
    print("  Lane A: grep on plain .md memory files  (the status quo)")
    print("  Lane B: structured queries on the same data in .fafm form")
    print(f"  Pilot:  10 sanitized memory entries · {REPEATS} warm repeats per query")
    print()
    print("  → Watch the WARM table's 'B vs A' column — that's the speedup.")
    print("  → Should take ~8–15 seconds. Safe to walk away; total time prints at the end.")
    print("─" * 72)
    print()
    print(f"Lane A: grep on .md  ({sum(p.stat().st_size for p in MD_DIR.glob('proto-*.md'))} bytes total)")
    print(f"Lane B: structured on .fafm  ({sum(p.stat().st_size for p in FAFM_DIR.glob('proto-*.fafm'))} bytes total)")
    print()

    # ---------- COLD: first-query-of-session cost ----------
    print("─── COLD (one-shot — includes disk + parse) ───")
    print(f"{'':22}{'Lane A (grep .md)':>22}{'Lane B (.fafm parse)':>26}")
    print("-" * 70)

    cold_load_a, corpus = time_cold(a_load_md)
    cold_load_b, entries = time_cold(b_load_fafm)
    print(f"{'corpus load':22}{fmt_ms(cold_load_a):>22}{fmt_ms(cold_load_b):>26}")

    cold_q1_a, ra = time_cold(lambda: a_q1_type_feedback(corpus))
    cold_q1_b, rb = time_cold(lambda: b_q1_type_feedback(entries))
    print(f"{'Q1 type=feedback':22}{fmt_us(cold_q1_a):>22}{fmt_us(cold_q1_b):>26}")

    cold_q2_a, _ = time_cold(lambda: a_q2_zeph(corpus))
    cold_q2_b, _ = time_cold(lambda: b_q2_zeph(entries))
    print(f"{'Q2 mentions ZEPH':22}{fmt_us(cold_q2_a):>22}{fmt_us(cold_q2_b):>26}")

    cold_q3_a, _ = time_cold(lambda: a_q3_date(corpus))
    cold_q3_b, _ = time_cold(lambda: b_q3_date(entries))
    print(f"{'Q3 dated 2026-05-13':22}{fmt_us(cold_q3_a):>22}{fmt_us(cold_q3_b):>26}")

    # ---------- WARM: in-memory query cost (corpus already loaded) ----------
    print()
    print("─── WARM (median of N — query only, corpus pre-loaded) ───")
    print(f"{'':22}{'Lane A':>22}{'Lane B':>26}{'B vs A':>15}")
    print("-" * 85)

    warm_ratios = {}
    for label, fn_a, fn_b in [
        ("Q1 type=feedback", lambda: a_q1_type_feedback(corpus), lambda: b_q1_type_feedback(entries)),
        ("Q2 mentions ZEPH", lambda: a_q2_zeph(corpus), lambda: b_q2_zeph(entries)),
        ("Q3 dated 2026-05-13", lambda: a_q3_date(corpus), lambda: b_q3_date(entries)),
    ]:
        med_a, _, _, _ = time_warm(fn_a)
        med_b, _, _, _ = time_warm(fn_b)
        ratio = med_a / med_b if med_b > 0 else float("inf")
        warm_ratios[label] = ratio
        print(f"{label:22}{fmt_us(med_a):>22}{fmt_us(med_b):>26}{ratio:>13.1f}×")

    # ---------- ACCURACY ----------
    print()
    print("─── ACCURACY (precision / recall vs ground truth) ───")
    print(f"{'':22}{'Lane A P/R':>20}{'Lane B P/R':>20}{'GT size':>12}")
    print("-" * 75)

    for label, fn_a, fn_b in [
        ("Q1 type=feedback", lambda: a_q1_type_feedback(corpus), lambda: b_q1_type_feedback(entries)),
        ("Q2 mentions ZEPH", lambda: a_q2_zeph(corpus), lambda: b_q2_zeph(entries)),
        ("Q3 dated 2026-05-13", lambda: a_q3_date(corpus), lambda: b_q3_date(entries)),
    ]:
        truth = GROUND_TRUTH[f"Q{label[1]}: " + label[3:]]
        pa, ra_ = precision_recall(fn_a(), truth)
        pb, rb_ = precision_recall(fn_b(), truth)
        print(f"{label:22}{f'{pa:.2f} / {ra_:.2f}':>20}{f'{pb:.2f} / {rb_:.2f}':>20}{len(truth):>12}")

    # ---------- Summary (so you know what you just measured) ----------
    elapsed = time.perf_counter() - t_start
    q1_ratio = warm_ratios.get("Q1 type=feedback", 0.0)
    print()
    print("─" * 72)
    print(f"  ✓ Done in {elapsed:.1f}s.")
    print(f"  On this pilot, structured .fafm queries were {q1_ratio:.0f}× faster than grep")
    print(f"  on a type-filter (Q1). Q2 (substring) is grep's natural strength — by design.")
    print(f"  Full 492-file run lands at 412× — see RECEIPT.md for methodology.")
    print()
    print(f"  Next:  python3 query_bench_binary.py   ← the .fafmbin tier")
    print("─" * 72)


if __name__ == "__main__":
    main()
