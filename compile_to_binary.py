#!/usr/bin/env python3
"""Compile .fafm → binary tiers and bench load times.

Path 1 (generic stdlib):
  - .fafm.gz       : gzip of original .fafm YAML text
  - .jgz           : compact JSON + gzip

Path 2 (custom FAFM binary container, mirrors .fafb pattern):
  - .fafmbin       : magic + version + flags + CRC + length-prefixed sections
  - .fafmbin.gz    : same, gzipped (structure + compression combined)

Reports per-file + total sizes, compression ratios vs .md and .fafm,
plus median full-corpus load times for each tier.
"""

import os
import gzip
import json
import statistics
import struct
import time
import zlib
from pathlib import Path

import yaml

FAFM_DIR = Path(os.environ.get("FAFM_DIR", str(Path(__file__).resolve().parent / "pilot/fafm")))
MD_DIR = Path(os.environ.get("MD_DIR", str(Path(__file__).resolve().parent / "pilot/md")))
OUT_DIR = Path(os.environ.get("OUT_DIR", str(Path(__file__).resolve().parent / "pilot/bin")))
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPEATS = 200

MAGIC = b"FAFM"
VERSION_MAJOR = 1
VERSION_MINOR = 0


# ============================================================
# CUSTOM FAFM BINARY  (mirrors .fafb pattern)
# ============================================================
# Layout:
#   magic (4)         "FAFM"
#   version major (1)
#   version minor (1)
#   flags (2)
#   source crc32 (4)  CRC32 of original .fafm text
#   entry count (4)   number of entries in this file
#   <per entry>:
#     source           u32 length + UTF-8 bytes
#     name             u32 length + UTF-8 bytes
#     description      u32 length + UTF-8 bytes
#     type             u32 length + UTF-8 bytes ("" == null)
#     dates            u16 count + sequence of length-prefixed strings
#     related          u16 count + sequence of length-prefixed strings
#     body             u32 length + UTF-8 bytes

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
        VERSION_MAJOR, VERSION_MINOR,
        0,
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
    ver_major, ver_minor, flags, src_crc, entry_count = struct.unpack_from("<2B H I I", data, pos)
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
    return {"version": (ver_major, ver_minor), "flags": flags,
            "source_crc": src_crc, "entries": entries}


# ============================================================
# COMPILE — write all tiers
# ============================================================

def compile_all():
    files = sorted(FAFM_DIR.glob("proto-*.fafm"))
    sizes = []
    for f in files:
        source_text = f.read_text()
        doc = yaml.safe_load(source_text)
        entries = doc["memory"]["entries"]

        gz_bytes = gzip.compress(source_text.encode(), compresslevel=9)
        compact_json = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
        jgz_bytes = gzip.compress(compact_json.encode(), compresslevel=9)
        bin_bytes = encode_fafm_binary(entries, source_text)
        bingz_bytes = gzip.compress(bin_bytes, compresslevel=9)

        stem = f.stem
        (OUT_DIR / f"{stem}.fafm.gz").write_bytes(gz_bytes)
        (OUT_DIR / f"{stem}.jgz").write_bytes(jgz_bytes)
        (OUT_DIR / f"{stem}.fafmbin").write_bytes(bin_bytes)
        (OUT_DIR / f"{stem}.fafmbin.gz").write_bytes(bingz_bytes)

        sizes.append({
            "name": f.name,
            "fafm": len(source_text.encode()),
            "gz": len(gz_bytes),
            "jgz": len(jgz_bytes),
            "bin": len(bin_bytes),
            "bingz": len(bingz_bytes),
        })
    return sizes


# ============================================================
# BENCH — load times for each tier
# ============================================================

def load_md_corpus():
    return [p.read_text() for p in sorted(MD_DIR.glob("proto-*.md"))]


def load_fafm_corpus():
    return [yaml.safe_load(p.read_text()) for p in sorted(FAFM_DIR.glob("proto-*.fafm"))]


def load_gz_corpus():
    out = []
    for p in sorted(OUT_DIR.glob("proto-*.fafm.gz")):
        out.append(yaml.safe_load(gzip.decompress(p.read_bytes()).decode()))
    return out


def load_jgz_corpus():
    out = []
    for p in sorted(OUT_DIR.glob("proto-*.jgz")):
        out.append(json.loads(gzip.decompress(p.read_bytes()).decode()))
    return out


def load_bin_corpus():
    return [decode_fafm_binary(p.read_bytes())
            for p in sorted(OUT_DIR.glob("proto-*.fafmbin"))
            if not p.name.endswith(".gz")]


def load_bingz_corpus():
    return [decode_fafm_binary(gzip.decompress(p.read_bytes()))
            for p in sorted(OUT_DIR.glob("proto-*.fafmbin.gz"))]


def time_loader(fn, repeats=REPEATS):
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    return statistics.median(samples)


# ============================================================
# RUN
# ============================================================

def main():
    print(f"Compiling 10-memory pilot to 4 binary tiers...\n")
    sizes = compile_all()

    print(f"{'File':<42}{'fafm':>8}{'gz':>8}{'jgz':>8}{'bin':>8}{'bin.gz':>10}")
    print("-" * 84)
    tot = {"fafm": 0, "gz": 0, "jgz": 0, "bin": 0, "bingz": 0}
    for s in sizes:
        print(f"{s['name']:<42}{s['fafm']:>8}{s['gz']:>8}{s['jgz']:>8}{s['bin']:>8}{s['bingz']:>10}")
        for k in tot:
            tot[k] += s[k]
    print("-" * 84)
    print(f"{'TOTAL':<42}{tot['fafm']:>8}{tot['gz']:>8}{tot['jgz']:>8}{tot['bin']:>8}{tot['bingz']:>10}")

    md_total = sum((MD_DIR / s["name"].replace(".fafm", ".md")).stat().st_size for s in sizes) \
        if all((MD_DIR / s["name"].replace(".fafm", ".md")).exists() for s in sizes) else 28503

    print()
    print(f"Reference: .md corpus = {md_total} bytes  ·  .fafm = {tot['fafm']} (+{(tot['fafm']/md_total - 1)*100:.1f}% vs .md)")
    print()
    print("Size reduction vs .md:")
    for k in ("gz", "jgz", "bin", "bingz"):
        ratio = md_total / tot[k]
        savings = (1 - tot[k] / md_total) * 100
        print(f"  {k:>8}  {tot[k]:>8} bytes  ·  {ratio:>5.2f}× smaller  ·  -{savings:>5.1f}%")

    print()
    print(f"─── LOAD TIME (full 10-file corpus, median of {REPEATS}) ───")
    print(f"{'Tier':<24}{'Size':>10}{'Median load':>20}{'Ratio vs YAML':>18}")
    print("-" * 75)

    tiers = [
        (".md (raw)",       md_total,      load_md_corpus),
        (".fafm (YAML)",    tot["fafm"],   load_fafm_corpus),
        (".fafm.gz",        tot["gz"],     load_gz_corpus),
        (".jgz (json+gz)",  tot["jgz"],    load_jgz_corpus),
        (".fafmbin",        tot["bin"],    load_bin_corpus),
        (".fafmbin.gz",     tot["bingz"],  load_bingz_corpus),
    ]
    fafm_t = None
    for name, sz, fn in tiers:
        t = time_loader(fn)
        if name.startswith(".fafm (YAML)"):
            fafm_t = t
        ratio = (fafm_t / t) if fafm_t and fafm_t > 0 else 1.0
        print(f"{name:<24}{sz:>10}{f'{t*1000:.3f} ms':>20}{ratio:>16.2f}×")


if __name__ == "__main__":
    main()
