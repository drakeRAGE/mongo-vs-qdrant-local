# 03 — Qdrant Architecture and the Comparison with MongoDB

Qdrant is the dedicated vector database in this study. This manuscript states its object model, index, memory story, and the architectural comparison that the result tables cannot show by themselves.

Primary sources: Qdrant documentation on collections, points, capacity planning, memory tiers, and HNSW configuration; Malkov & Yashunin (2018).

---

## 1. Object model

| Concept | Meaning in this study |
|---|---|
| **Collection** | Named space with one dense vector schema (size 384, distance Cosine), HNSW config, optimizer config, payload indexes. Analogous to a table / MongoDB collection, but specialized. |
| **Point** | `(id, vector, payload)`. The unit of upsert and delete. `id` is the same integer used as MongoDB `_id` and as the frozen matrix row. |
| **Vector** | One unnamed dense `float32` vector of length 384. Named vectors and sparse/multi-vectors are out of scope. |
| **Payload** | JSON metadata plus `text`. Equivalent to the MongoDB document fields used for filter and projection — not a general application database. |
| **Payload index** | Per-field index so filters do not scan every payload. Created for exactly `tenant_id`, `year`, `category`. |

A point is not a MongoDB document. Qdrant will not replace WiredTiger for transactional application state. Treating “Qdrant won p95” as “delete MongoDB” is a category error the final paper must refuse.

---

## 2. HNSW in Qdrant

Collection creation (conceptual):

```python
client.create_collection(
    collection_name="passages",
    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    hnsw_config=HnswConfigDiff(m=16, ef_construct=200),
)
```

Search:

```python
client.query_points(
    collection_name="passages",
    query=q,
    limit=10,
    search_params=SearchParams(hnsw_ef=64, exact=False),
    query_filter=Filter(...),  # optional
)
```

| Knob | Qdrant | MongoDB analog |
|---|---|---|
| Graph degree | `m` | `hnswOptions.maxEdges` |
| Build beam | `ef_construct` | `hnswOptions.numEdgeCandidates` |
| Search beam | `hnsw_ef` / `ef` | `numCandidates` |
| Exact scan | `exact=true` | not the `$vectorSearch` default |

`exact=true` is allowed at 10K for harness debug. It is forbidden as a timed primary cell at \(N \ge 100{,}000\).

Default optimizer `indexing_threshold` can delay HNSW build on tiny segments. The harness waits until collection status is green and the optimizer backlog is empty before declaring **index ready**.

---

## 3. Filtering

Qdrant applies payload filters during graph traversal (and may fall back to a filtered scan when the planner estimates that is cheaper — `full_scan_threshold`). Payload indexes on the three filter fields are mandatory so the comparison is not “indexed MongoDB filter vs unindexed Qdrant scan.”

Selectivities in E3: 100% (no filter), 50%, 10%, 1%, generated from the same payload schema as MongoDB.

---

## 4. Persistence and memory tiers

Qdrant persists WAL + segment files. On 1.19+ each structure can be placed in a memory tier:

| Tier | Behavior | Default (typical) |
|---|---|---|
| `pinned` | Heap RAM, not evicted | payload indexes, often quantized vectors |
| `cached` | mmap, pre-warmed | dense vectors, HNSW |
| `cold` | mmap, faulted on demand | payloads |

Primary cells use defaults (HNSW `cached`, no quantization). An on-disk / quantized appendix at 1M–2M is optional and must be labeled. Moving HNSW to `cold` on this NVMe still incurs random-read latency that will inflate p99; that is a different experiment.

---

## 5. Sharding and replication (conceptual only)

\[
\text{disk/RAM} \propto N \times \text{replication\_factor}
\]

A production cluster adds shard count, replication factor, and consensus. This study runs **one node, one shard, replication factor 1**. Laptop numbers do not measure horizontal scale. The capacity-planning formulas are recorded so a reader can extrapolate; they are not results.

---

## 6. Architecture comparison

```text
MongoDB path                         Qdrant path
---------------------------          --------------------------
Application document model           Point model (id+vector+payload)
WiredTiger + replica set             Custom segments + WAL
mongot / Lucene HNSW sidecar         In-process HNSW
$vectorSearch + MQL filter           query + payload filter
Index sync is eventual               Upsert ack; optimizer may still merge
Two processes minimum                One process
General-purpose ops story            Vector-specialized ops story
```

Fairness implications:

- MongoDB is asked to be a **document database plus a search engine**. Qdrant is asked to be a **search engine**. Operational “one system for everything” is a MongoDB advantage that latency tables will not show.
- Both engines run in Linux containers on the same Docker Desktop VM so virt overhead is shared.
- They never run at the same time. Compose profiles are mutually exclusive (`mongo` xor `qdrant`).
- Iso-config is not iso-quality. Headline ratios use iso-recall operating points.

---

## 7. Capacity sketch at 384-d (one replica, order-of-magnitude)

Using Qdrant’s published estimators (vectors + HNSW + ~20% headroom, excluding large text payloads):

| \(N\) | Vectors | HNSW (\(M=16\)) | Rough engine envelope |
|---:|---:|---:|---:|
| 10K | 15 MB | 1.5 MB | tens of MB |
| 100K | 154 MB | 15 MB | ~0.3 GB |
| 500K | 768 MB | 75 MB | ~1.2 GB |
| 1M | 1.54 GB | 150 MB | ~2.2 GB + payload + process |

Text payloads (`text` stored in full) add disk and, if not `cold`, RAM. MongoDB’s envelope adds WiredTiger cache + `mongot` heap on top of the same vectors. These are planning bounds, not measurements. Measurements live in `07-results.md`.
