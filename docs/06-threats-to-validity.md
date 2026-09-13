# 06 — Threats to Validity and Unfair Comparisons

A faster number that answers a different question is not a result. This manuscript lists the ways this study can lie, and the controls that exist in the harness.

---

## 1. Internal validity (did we measure the engine?)

| Threat | Control |
|---|---|
| Different embeddings, IDs, filters, or \(k\) | Single frozen artifact store; both adapters read the same memmap and parquet |
| Both engines up | `check_host.py` aborts; compose profiles are xor |
| One native, one Docker | Both containerized |
| `insertMany` ack vs searchable | Separate metrics; query cells start only after READY/green |
| Iso-config sold as iso-quality | Explicit labels; headline ratios use iso-recall |
| Cold mixed with warm | Warm is primary; E5 is labeled cold |
| First query after start in p50 | 50 warm-up queries discarded |
| \(n < 200\) measured queries | Target 500; cell marked invalid below 200 |
| Background Update / Defender / browser | Process snapshot; abort on extreme CPU |
| Pagefile / hard faults | Discard trial |
| Exact in one engine, ANN in the other | `exact=true` forbidden in timed primary cells except E0 debug |
| Post-filter vs pre-filter | Only in-stage / in-query filters |
| Unindexed filter field on one side | Same three payload indexes / filter fields |
| Unstored query permutation | `query_order.npy` |
| Changing \(M\) or quantization mid-ladder | New experiment id |
| QPS from a single thread sold as capacity | E2 is the concurrency experiment |
| Atlas-only features | Not invoked |
| Floating preview images | Pin tags/digests in compose |

Ground truth is Faiss `IndexFlatIP` or batched NumPy on the frozen memmap. Engine A is never truth for engine B.

---

## 2. Construct validity (is this “MongoDB vs a vector DB”?)

MongoDB is a document database plus a Lucene sidecar. Qdrant is a vector engine. p95 does not measure:

- transactional multi-document updates;
- the value of keeping vectors next to application documents;
- Atlas Search Nodes or Qdrant clustering;
- operational familiarity.

The results chapter must include a qualitative ops paragraph so the paper does not collapse into QPS-only.

BSON array storage vs packed `float32` is a real MongoDB cost. We do not hide it, and we do not “fix” it with a binary field unless Qdrant is similarly handicapped.

`numCandidates` is not guaranteed to equal `hnsw_ef` in visited nodes. That is why iso-recall exists.

---

## 3. External validity (does this generalize?)

This is **one** Windows 11 Home laptop, Meteor Lake, 16 GB LPDDR5, Docker Desktop WSL2, Community `mongot` **preview**, single node, 384-d BGE-small, uniform metadata, closed-loop clients.

It does not generalize to:

- Atlas dedicated Search Nodes or Qdrant Cloud;
- 1536-d API embeddings;
- highly skewed (Zipf) tenants;
- write-heavy production ingest with deletes and updates;
- NUMA servers with 128 GB RAM;
- filtered search where the filter is not one of the three indexed fields.

Nested prefixes reduce one surprise (1M-only artifacts) but do not make MS MARCO representative of legal, medical, or code corpora.

---

## 4. Statistical validity

Three trials × median of trial percentiles is a **stability check**, not a confidence interval. We do not publish p-values. If two engines differ by <10% on p95 at 100K, the protocol calls that **operationally irrelevant** unless RSS or error rate tells a different story.

Query count 500 is enough to stabilize p50 and usually p95; p99 remains noisy. p99 is a detector (GC, compaction, page faults), not a precise ranking statistic.

---

## 5. Preview-software threat

Self-managed Community vector search is a public preview. Behavior, knobs, and resource use can change between image digests. Every run records image IDs in the trial JSON. Comparing a blog post from a different `mongot` build to these numbers is invalid.

---

## 6. Operator threat

The same human/agent must not “help” one engine by raising Docker RAM, disabling Windows Defender for one profile only, or running MongoDB after a reboot and Qdrant after three hours of thermal soak without noting it. Trials should be interleaved or run in a documented order (`mongo` ladder, then `qdrant` ladder, host snapshot each time). Thermal throttling on a 155H thin-and-light is a real threat; lid-open + AC is required.

---

## 7. How a reader should reject a cell

Reject a published cell if any of the following is true:

- `host_ok` is false
- `swap_active` is true
- `both_engines_up` is true
- `n_measured < 200`
- `error_rate > 0.01`
- `index_ready` is false when queries ran
- `recall_at_10` is missing on a cell that claims quality
- search mode is exact on one side only
- embeddings SHA does not match `MANIFEST.json`
