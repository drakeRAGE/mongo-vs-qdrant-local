# Contributing

This repository is a **measured study**, not a product. Changes should preserve that.

## Rules

- Do not assume a winner in docs or plot titles.
- Headline comparisons are **iso-recall**, not iso-config.
- Never commit secrets, `.env`, Hugging Face tokens, or `compose/mongo/pwfile`.
- Do not commit `data/embeddings/`, `data/docker/`, or ground-truth `.npy` files.
- After new trials, run `python -m src.runners.study analyze` so `docs/07-results.md` and `experiments/plots/` stay generated from JSONL.
- After harness changes, run `python -m pytest tests -q`. These tests cover recall alignment, percentiles, filters, host gates, and analyze empty-state. They do not replace E0 or a scale cell.
- Run one engine at a time (`scripts/one_engine.ps1`).

## Adding a scale cell

1. `python -m src.runners.study prepare --max-docs N` (extends the frozen prefix).
2. Qdrant, then Mongo, each with `--min-n` / `--max-n` for the new slice.
3. `python -m src.runners.study analyze`.
4. Discard any trial that tripped the pagefile or dual-engine host gate.
