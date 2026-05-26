#!/usr/bin/env python3
"""Query harness V2 — Lane A (grep on .md) vs Lane B (custom .fafmbin binary).

Drops the PyYAML tax from Lane B's cold-start by loading from .fafmbin instead
of .fafm. Apples-to-apples comparison at the binary tier.
"""

import os
import re
import statistics
import struct
import time
import zlib
from pathlib import Path

MD_DIR = Path(os.environ.get("MD_DIR", str(Path(__file__).resolve().parent / "pilot/md")))
BIN_DIR = Path(os.environ.get("BIN_DIR", str(Path(__file__).resolve().parent / "pilot/bin")))
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

MAGIC = b"FAFM"


def stem(name):
    return name.rsplit(".", 1)[0]


# ============================================================
# LANE A — grep on .md
# ============================================================

def a_load_md():
    return [(p.name, p.read_text()) for p in sorted(MD_DIR.glob("proto-*.md"))]


def a_q1_type_feedback(corpus):
    return {stem(name) for name, text in corpus
            if re.search(r"^type:\s*feedback", text, re.MULTILINE)}


def a_q2_zeph(corpus):
    return {stem(name) for name, text in corpus if "ZEPH" in text}


def a_q3_date(corpus):
    return {stem(name) for name, text in corpus if "2026-05-13" in text}


# ============================================================
# LANE B — custom .fafmbin binary decode
# ============================================================

def decode_fafm_binary(data):
    if data[:4] != MAGIC:
        raise ValueError("bad magic")
    pos = 4
    _ver_maj, _ver_min, _flags, _crc, entry_count = struct.unpack_from("<2B H I I", data, pos)
    pos += 12
    entries = []

    def read_str():
        nonlocal pos
        (n,) = struct.unpack_from("<I", data, pos)
        pos += 4
        s = data[pos:pos + n].decode("utf-8")
        pos += n
        return s

    def read_str_list():
        nonlocal pos
        (n,) = struct.unpack_from("<H", data, pos)
        pos += 2
        return [read_str() for _ in range(n)]

    for _ in range(entry_count):
        entries.append({
            "source": read_str(),
            "name": read_str(),
            "description": read_str(),
            "type": read_str(),
            "dates": read_str_list(),
            "related": read_str_list(),
            "body": read_str(),
        })
    return entries


def b_load_bin():
    out = []
    for p in sorted(BIN_DIR.glob("proto-*.fafmbin")):
        if p.name.endswith(".gz"):
            continue
        for e in decode_fafm_binary(p.read_bytes()):
            out.append((stem(e["source"]), e))
    return out


def b_q1_type_feedback(entries):
    return {name for name, e in entries if e.get("type") == "feedback"}


def b_q2_zeph(entries):
    out = set()
    for name, e in entries:
        if "ZEPH" in (e.get("body") or ""):
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
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    return statistics.median(samples)


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
    md_size = sum(p.stat().st_size for p in MD_DIR.glob('proto-*.md'))
    bin_files = [p for p in BIN_DIR.glob('proto-*.fafmbin') if not p.name.endswith('.gz')]
    bin_size = sum(p.stat().st_size for p in bin_files)

    t_start = time.perf_counter()
    print("─" * 72)
    print("  FAF memory proof — binary tier benchmark  (Lane A grep vs Lane B .fafmbin)")
    print("─" * 72)
    print("  Lane A: grep on plain .md memory files  (the status quo)")
    print("  Lane B: structured queries on the .fafmbin compiled binary tier")
    print(f"  Pilot:  10 sanitized memory entries · {REPEATS} warm repeats per query")
    print()
    print("  → Watch the WARM table's 'B vs A' column — that's the speedup.")
    print("  → Should take ~3–8 seconds. Safe to walk away; total time prints at the end.")
    print("─" * 72)
    print()
    print(f"Lane A:  grep on .md       ({md_size} bytes)")
    print(f"Lane B:  decode .fafmbin   ({bin_size} bytes)")
    print()

    print("─── COLD (one-shot — corpus load + first query) ───")
    print(f"{'':22}{'Lane A (grep .md)':>22}{'Lane B (.fafmbin)':>25}")
    print("-" * 70)

    cold_load_a, corpus = time_cold(a_load_md)
    cold_load_b, entries = time_cold(b_load_bin)
    print(f"{'corpus load':22}{fmt_ms(cold_load_a):>22}{fmt_ms(cold_load_b):>25}")

    for label, fn_a, fn_b in [
        ("Q1 type=feedback", lambda: a_q1_type_feedback(corpus), lambda: b_q1_type_feedback(entries)),
        ("Q2 mentions ZEPH", lambda: a_q2_zeph(corpus), lambda: b_q2_zeph(entries)),
        ("Q3 dated 2026-05-13", lambda: a_q3_date(corpus), lambda: b_q3_date(entries)),
    ]:
        cold_a, _ = time_cold(fn_a)
        cold_b, _ = time_cold(fn_b)
        print(f"{label:22}{fmt_us(cold_a):>22}{fmt_us(cold_b):>25}")

    print()
    print("─── WARM (median of N — query only, corpus pre-loaded) ───")
    print(f"{'':22}{'Lane A':>22}{'Lane B':>25}{'B vs A':>15}")
    print("-" * 85)

    warm_ratios = {}
    for label, fn_a, fn_b in [
        ("Q1 type=feedback", lambda: a_q1_type_feedback(corpus), lambda: b_q1_type_feedback(entries)),
        ("Q2 mentions ZEPH", lambda: a_q2_zeph(corpus), lambda: b_q2_zeph(entries)),
        ("Q3 dated 2026-05-13", lambda: a_q3_date(corpus), lambda: b_q3_date(entries)),
    ]:
        med_a = time_warm(fn_a)
        med_b = time_warm(fn_b)
        ratio = med_a / med_b if med_b > 0 else float("inf")
        warm_ratios[label] = ratio
        print(f"{label:22}{fmt_us(med_a):>22}{fmt_us(med_b):>25}{ratio:>13.1f}×")

    print()
    print("─── ACCURACY ───")
    print(f"{'':22}{'Lane A P/R':>20}{'Lane B P/R':>20}{'GT size':>12}")
    print("-" * 75)

    for label, fn_a, fn_b, gt_key in [
        ("Q1 type=feedback", lambda: a_q1_type_feedback(corpus),
         lambda: b_q1_type_feedback(entries), "Q1: type=feedback"),
        ("Q2 mentions ZEPH", lambda: a_q2_zeph(corpus),
         lambda: b_q2_zeph(entries), "Q2: mentions ZEPH"),
        ("Q3 dated 2026-05-13", lambda: a_q3_date(corpus),
         lambda: b_q3_date(entries), "Q3: dated 2026-05-13"),
    ]:
        truth = GROUND_TRUTH[gt_key]
        pa, ra_ = precision_recall(fn_a(), truth)
        pb, rb_ = precision_recall(fn_b(), truth)
        print(f"{label:22}{f'{pa:.2f} / {ra_:.2f}':>20}{f'{pb:.2f} / {rb_:.2f}':>20}{len(truth):>12}")

    # ---------- Summary (so you know what you just measured) ----------
    elapsed = time.perf_counter() - t_start
    q1_ratio = warm_ratios.get("Q1 type=feedback", 0.0)
    print()
    print("─" * 72)
    print(f"  ✓ Done in {elapsed:.1f}s.")
    print(f"  On this pilot, structured .fafmbin queries were {q1_ratio:.0f}× faster than grep")
    print(f"  on a type-filter (Q1). Q2 (substring) is grep's natural strength — by design.")
    print(f"  Full 492-file run lands at 412× — see RECEIPT.md for methodology.")
    print()
    print(f"  Next:  cat RECEIPT.md   ← the full headline + methodology")
    print("─" * 72)


if __name__ == "__main__":
    main()
