# xai-faf-proof

**Performance receipts for the `.fafm` / `.fafb` structured AI memory tier — measured on real public-domain corpora.**

Same falsifiable methodology as the original [`faf-memory-proof`](https://github.com/Wolfe-Jam/faf-memory-proof) (412× type-filter speedup, 492 files, May 2026). This repo scales it to two real-world corpora: Smithsonian Open Access (9,175 records, CC0 public-domain) and a Claude persistent memory corpus (674 records, real-world frontmatter).

### Headline Result

**Prep once. Query forever.**

| Lens | Smithsonian (9,175 records) | Claude memory (674 records) |
|---|---|---|
| **Per-query peak** vs `grep` | **436 ×** | **1,399 ×** |
| **Amortized at N=100** (incl. cold load) | 13.1 × | 20.4 × |
| **Breakeven** | 7.4 queries | 4.7 queries |

→ Visual receipt card: [RESULTS.html](./RESULTS.html)

### Why this matters

Memory systems get queried thousands of times per session. Every query in the structured tier costs microseconds; every `grep` call costs ~100 ms+. After single-digit queries, the structured tier is winning — and the gap grows with usage.

For an AI agent that touches memory on every reasoning turn, that's the difference between sub-millisecond recall and a perceptible delay — for the life of the corpus.

### Quickstart

```bash
git clone https://github.com/Wolfe-Jam/xai-faf-proof.git
cd xai-faf-proof
python3 query_bench_smithsonian.py   # runs against the 10-file pilot
python3 proof_amortized.py           # the amortized "prep once, query forever" receipt
```

### Reproducible benchmark

- **Corpus** — 10-file sanitized Smithsonian sample committed in [`pilot/md/`](./pilot/md). Full 9,175-record corpus regeneratable via [`scripts/convert_edan_to_faf.py`](./scripts/convert_edan_to_faf.py) against the Smithsonian Open Access S3 bucket (no API key required).
- **Baselines** — Three lanes per query: subprocess `grep -E -r` (apples-to-apples with the original 412× baseline), in-memory Python regex (optimistic baseline), structured tier (`.fafm` / `.jgz`).
- **Query class** — Q1 type-filter (structured tier's strength), Q2 substring (grep's strength). Ground truth verified identical across all lanes.
- **Methodology** — Median of 100 individual timings for per-query peak; cumulative wall-clock of N=100 for amortized cost.
- **Receipt detail** — full numbers + breakeven math in [RESULTS.html](./RESULTS.html).

### Included

- [`scripts/convert_edan_to_faf.py`](./scripts/convert_edan_to_faf.py) — EDAN/JSONL → FAF `.md` adapter for Smithsonian Open Access
- [`convert_md_to_fafm.py`](./convert_md_to_fafm.py) — `.md` → `.fafm` (YAML structured)
- [`compile_to_binary.py`](./compile_to_binary.py) — `.fafm` → `.fafb` binary tier
- [`query_bench_smithsonian.py`](./query_bench_smithsonian.py) — Smithsonian-corpus bench
- [`query_bench_claude_memory.py`](./query_bench_claude_memory.py) — Claude-memory-corpus bench
- [`proof_amortized.py`](./proof_amortized.py) — "prep once, query forever" amortized proof
- [`pilot/`](./pilot) — 10-file sanitized Smithsonian sample, ready to run
- [`RESULTS.html`](./RESULTS.html) — visual receipt card

### Cross-vendor and ecosystem

The `.fafm` / `.fafb` format is IANA-registered (`application/vnd.fafm+yaml`) and works with:

- [`grok-faf-mcp`](https://www.npmjs.com/package/grok-faf-mcp) — Grok-side MCP integration
- [`grok-faf-voice`](https://pypi.org/project/grok-faf-voice/) — voice memory profile (VML)
- [`claude-faf-mcp`](https://www.npmjs.com/package/claude-faf-mcp) — Claude-side MCP integration
- `xai-faf-rust`, `xai-faf-zeph`, `xai-faf-zig` — performance lanes (Foundry / ZEPH)

### Sister repo

- [`faf-memory-proof`](https://github.com/Wolfe-Jam/faf-memory-proof) — the original 412× receipt this methodology builds on. Same query class, same baseline, scaled to ~18× the corpus size.

---

**License**: MIT  
**Part of the FAF family** — [faf.one](https://faf.one)
