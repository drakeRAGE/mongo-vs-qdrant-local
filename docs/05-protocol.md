# 05 — Experimental Protocol

The independent variable is **the engine**. Everything else is frozen. This document is the runbook; `06-threats-to-validity.md` is the corresponding failure mode list.

---

## 1. Frozen factors

| Factor | Value |
|---|---|
| Hardware | Dell Inspiron 14 Plus 7440, as inventoried |
| Power | Performance plan; lid open; AC if available |
| Dataset | One corpus, one metadata schema, one ID space |
| Embeddings | One frozen `float32` memmap, L2-normalized, 384-d, `BAAI/bge-small-en-v1.5` |
| Queries | One frozen query matrix + stored permutation |
| Ground truth | Exact top-100, inner product, same matrix |
| \(k\) | 10 primary; also 50 and 100 for recall curves |
| Distance | Cosine / IP on unit vectors |
| Runtime | Both engines in Linux containers, volumes on `D:` |
| Warm-up | 50 untimed queries; then the measured window |
| Measured queries | 500 per cell (minimum 200 or the cell is invalid) |
| Repetitions | 3 trials per cell; report median of trial-level p50/p95/p99 |
| Seed | `20260912` |

---

## 2. Dataset

**Corpus.** A public English passage set large enough to reach 1M after cleaning. Preferred: BEIR / MS MARCO passage corpus via Hugging Face. Fallback: streamed Wikipedia or another documented public dump. Random Gaussian vectors are forbidden as the primary corpus (unrealistic neighborhood structure).

**Nested slices.** With the frozen seed, build prefixes

\[
10\text{K} \subset 50\text{K} \subset 100\text{K} \subset 250\text{K} \subset 500\text{K} \subset 1\text{M}.
\]

Row \(i\) in the 10K matrix is row \(i\) in every larger matrix. Ground truth for a slice is exact kNN on **that prefix only**.

**Queries.** 500 query texts embedded with the same checkpoint. Prefer official BEIR/MS MARCO queries. If unavailable, hold out query strings that are **not** rows of the 1M prefix (titles or reserved documents beyond 1M, or a documented query file). Store `queries.f32` and `query_order.npy`.

**Payload schema (identical in both engines).**

| Field | Type | Notes |
|---|---|---|
| `doc_id` | string | Stable public ID when available |
| `tenant_id` | string | 10 tenants `t00`–`t09`, **uniform** primary |
| `year` | int | 2018–2025, uniform |
| `category` | string | 8 categories, uniform |
| `token_len` | int | whitespace token count |
| `text` | string | full passage text |

Filterable (and indexed on both sides): `tenant_id`, `year`, `category`.

**Artifacts** (under `data/`, gitignored):

```text
data/raw/
data/embeddings/embeddings.f32      # (N, 384) float32 memmap
data/embeddings/queries.f32         # (Q, 384)
data/embeddings/ids.parquet
data/embeddings/payload.parquet
data/ground_truth/gt_{N}_top100.npy
data/manifests/MANIFEST.json
```

`MANIFEST.json` records model name, normalize=true, seed, timestamps, file SHA-256, software versions.

---

## 3. Engine configuration

**Phase A — iso-config (explainability).**

- \(M = 16\), `efConstruction = 200`
- Search width 64 (`hnsw_ef` / `numCandidates`)
- `limit = 10`
- No quantization

Labeled `iso_config`. Not claimed to be iso-quality.

**Phase B — iso-recall (decision-grade).**

Sweep search width \(\in \{32,64,128,256\}\) at 100K and 500K (and at 1M if the scale cell ran). For each engine pick the **smallest** width with Recall@10 ≥ 0.95. Compare latency and QPS at that point. If 0.95 is unreachable, publish the Pareto curve and do not invent a winner.

---

## 4. Clocking

Engine-only latency:

1. Query vector is already a Python `list[float]` / NumPy row in RAM.
2. Start clock immediately before the client call.
3. Stop when top-\(k\) IDs are materialized in the client.

Includes client serialization of 384 floats. Excludes embedding and LLM. Timeouts > 2000 ms count as errors.

**QPS** = completed queries / wall time of the measured window, per concurrency level. Closed-loop (N client threads, each waits) is primary.

**Index build time** = last ingest acknowledgement → index READY / collection green + no optimizer backlog.

**Ingestion throughput** = rows / wall time of bulk upsert (batch size frozen at 256). Separate from time-to-searchable.

---

## 5. Experiments

| ID | Name | Conditions |
|---|---|---|
| E0 | Harness validation | 10K; high search width; Recall@10 must be \(\approx 1.0\) vs exact; abort otherwise |
| E1 | Scale ladder | Warm, concurrency=1, no filter; \(N \in \{10,50,100,250,500,1000\}\times 10^3\); iso-config then iso-recall at 100K and 500K |
| E2 | Concurrency | 100K and 500K; clients \(\in \{1,4,8\}\); iso-recall settings |
| E3 | Filtered ANN | 500K; selectivity 100/50/10/1%; concurrency 1 and 4 |
| E4 | Ingestion | Bulk + time-to-searchable at 100K and 500K |
| E5 | Cold start | 500K; restart container; first 50 queries reported separately |
| E6 | Resource envelopes | Peak RSS, disk, CPU during build and query at each \(N\) |

E7 (768-d, quantized 2M) is optional and out of the default runner.

---

## 6. Selectivity construction

For a target selectivity \(s\), build a predicate whose expected fraction of the slice is \(s\), using only indexed fields:

- 100%: no filter
- 50%: `year >= 2022` (four of eight years, if years are uniform 2018–2025)
- 10%: one `tenant_id` (1/10)
- 1%: one `tenant_id` **and** one `category` (1/10 × 1/8 = 1.25%, recorded as the 1% cell; exact fraction is written into the trial JSON)

The same predicate object is applied to both engines.

---

## 7. Host procedure (every trial)

1. `python scripts/check_host.py --expect <mongo|qdrant>`
2. If the other profile is up, `scripts/one_engine.ps1 <mongo|qdrant>`
3. Snapshot Docker stats and pagefile
4. Run the cell
5. Snapshot again
6. Discard the trial if pagefile-active, dual-engine, or error rate exceeds 1%

Results: `experiments/results/<run_id>.jsonl` plus a rolled-up CSV.

---

## 8. Questions the dataset must answer

1. Largest \(N\) at which MongoDB stays under p95 50 ms at Recall@10 ≥ 0.95, concurrency 1, unfiltered.
2. Same for Qdrant.
3. Iso-recall p95 and QPS ratios at 100K, 500K, 1M.
4. Whether concurrency=8 changes the ranking.
5. Whether 1% selectivity changes the ranking.
6. Whether time-to-searchable differs after bulk insert.
7. Whether MongoDB’s two-process RSS forces paging earlier.
8. Below which \(N\) the difference is operationally irrelevant.
9. Which metrics moved and which stayed flat.

Discussion thresholds (not pass/fail trophies): interactive ≈ p95 < 50 ms and p99 < 100 ms.

---

## 9. What would be interesting (no predetermined winner)

- Both interactive through 1M at Recall@10 ≥ 0.95 → dedicated DB not required for latency on this box; choose on ops/document-model grounds.
- Crossover at 250K or 500K on p95 or RSS → measured local boundary.
- Unfiltered kNN similar, 1% filter diverges → value is filtered ANN, not raw kNN.
- One engine wins ingest-ack, the other wins time-to-searchable → “ingest throughput” must never be a single number.
- Iso-config favors A, iso-recall favors B → default-vs-default blog comparisons are misleading.
- 1M pages one process model and not the other → boundary is RAM architecture.
- Recall@10 never reaches 0.95 at usable latency → the knobs/preview build are the story.

5M is not expected to decide anything on this laptop.
