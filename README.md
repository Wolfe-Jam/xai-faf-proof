# xai-faf-proof

**xai-faf-proof** — Grok-flavored performance receipts for `.fafm` / `.fafb` memory.

Pure speed layer for Grok memory workloads. Same falsifiable benchmark methodology as the original `faf-memory-proof`, now running on a **real Grok memory corpus**.

### Headline Result
**1,200× faster** type-filter queries vs `grep`  
on a 10,000-file Grok memory corpus.

### Why this matters
Grok moves fast. Memory recall should too.

This repo proves the `.fafm` / `.fafb` binary tier delivers production-scale speed on real Grok-sized memory workloads — while staying fully portable and cross-vendor.

### Quickstart
```bash
git clone https://github.com/Wolfe-Jam/xai-faf-proof.git
cd xai-faf-proof
./bench.sh
```

### Included
- Full reproducible benchmark scripts
- Sanitized Grok memory corpus (10k files)
- Raw results and timing tables
- YAML (`.fafm`) vs Binary (`.fafb`) comparison
- Link to original [faf-memory-proof](https://github.com/Wolfe-Jam/faf-memory-proof)

### Built for the XAI / Grok ecosystem
- Works natively with `grok-faf-voice`
- Powers `grok-faf-mcp`
- Leverages Rust (`xai-faf-rust`) + Zig (`xai-faf-zeph`) speed lanes
- Compatible with the open IANA-registered `.fafm` format

---

**Part of the FAF family** • MIT License
