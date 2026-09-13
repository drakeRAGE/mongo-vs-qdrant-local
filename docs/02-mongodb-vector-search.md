# 02 — MongoDB Vector Search: Generations, Architecture, and Local Topology

This manuscript records how MongoDB actually performs vector search as of the 8.2 Community + `mongot` public preview, and which generation this study uses. Using the wrong API (`knnBeta`, application-side array scan, or Atlas-only stages) would invalidate the comparison with Qdrant.

Primary sources: MongoDB 8.2 release notes (2025-09-16); *Supercharge Self-Managed Apps With Search And Vector Search Capabilities*; MongoDB Search self-managed installation (Docker); *Known Limitations for Self-managed mongot*; `$vectorSearch` and `knnBeta` operator documentation.

---

## 1. Three generations (do not mix them)

### Generation A — DIY float arrays (always available)

Store `embedding: [Number]` on a document. WiredTiger treats the field as a BSON array. There is no HNSW. Similarity requires an application scan or a `$function` / client-side loop.

This is a legitimate **exact-scan baseline** at 10K–50K. It is not MongoDB Vector Search. The study may use an external Faiss/NumPy flat index as ground truth instead of asking `mongod` to scan arrays.

### Generation B — Atlas Search `knnBeta` / `knnVector` (deprecated)

Lucene kNN via the `$search` stage, field type `knnVector`, operator `knnBeta`. Deprecated. Incompatible with `vectorSearch`-type indexes. Old blog posts still show this path. **This study does not use it.**

### Generation C — `$vectorSearch` + `vectorSearch` index (current)

This is the study target. Documents live in `mongod` (WiredTiger). The vector index lives in `mongot` (Lucene HNSW). Queries use the `$vectorSearch` aggregation stage. Self-managed Community Edition gained this path in MongoDB **8.2** as a **public preview**. Pin image digests. Do not treat preview software as a production SLA.

---

## 2. Process architecture

```text
[Python harness]
      |
      | mongodb://admin@localhost:27017/?replicaSet=rs0
      v
[mongod 8.2+ Community]
   WiredTiger documents
   single-node replica set rs0
      |  replica-set / change-stream sync
      v
[mongot Community Search]
   Lucene HNSW + filter fields
   gRPC :27028   metrics :9946
      ^
      | $vectorSearch executed against mongot
```

Facts that follow from this split:

1. **Two processes minimum.** RSS is `mongod` + `mongot`, not one heap. On a 16 GB laptop this is an architectural cost, not a misconfiguration.
2. **Replica set required.** Standalone `mongod` cannot feed `mongot`.
3. **Sync is asynchronous.** `insertMany` acknowledgement is not “searchable.” Time-to-searchable is a first-class metric.
4. **`mongot` is Linux-only.** Native Windows and native macOS binaries are not published. On this Windows 11 host the only supported local method is a Linux container via Docker Desktop / WSL2.
5. **Community sharded search is out of scope.** This study is one replica-set member and one `mongot`.

---

## 3. Local packagings

| Packaging | What it is | Use in this study |
|---|---|---|
| `mongodb/mongodb-community-server` + `mongodb/mongodb-community-search` | Two containers, real process split | **Primary** |
| `mongodb/mongodb-atlas-local` | Dev image bundling `mongod` + `mongot` | Fallback only; document the deviation |
| Atlas dedicated / Flex cluster | Managed cloud | Out of scope (network confound) |
| Native Windows `mongod` | No `mongot` | Cannot run Generation C |

Primary compose profile: `mongo`. Images are pinned in `compose/docker-compose.yml`. Volumes bind to `D:\VectorDB_Proof\data\docker\` so `C:` and the pagefile are isolated.

`mongod` is configured with:

```yaml
setParameter:
  searchIndexManagementHostAndPort: mongot:27028
  mongotHost: mongot:27028
  skipAuthenticationToSearchIndexManagementServer: false
  useGrpcForSearch: true
replication:
  replSetName: rs0
```

`mongot` authenticates to the replica set as `mongotUser` with the built-in `searchCoordinator` role and a password file (no trailing newline).

---

## 4. How embeddings are stored

Each study document in `vectordb.passages` has:

```javascript
{
  _id: NumberLong,          // integer id, aligned with the frozen matrix row
  doc_id: String,
  embedding: [Number],      // 384 float64-in-BSON; source is float32 memmap
  tenant_id: String,
  year: NumberInt,
  category: String,
  token_len: NumberInt,
  text: String
}
```

BSON arrays of doubles are larger on the wire and on disk than a packed `float32` memmap. That overhead is part of MongoDB’s real cost and is not “cheated away” by storing binData unless both engines get an equivalent packed representation. Qdrant stores packed vectors natively. This asymmetry is reported, not hidden.

---

## 5. Vector index definition

```javascript
db.passages.createSearchIndex(
  "vector_index",
  "vectorSearch",
  {
    fields: [
      {
        type: "vector",
        path: "embedding",
        numDimensions: 384,
        similarity: "cosine",
        quantization: "none",
        indexingMethod: "hnsw",
        hnswOptions: {
          maxEdges: 16,              // M
          numEdgeCandidates: 200     // efConstruction
        }
      },
      { type: "filter", path: "tenant_id" },
      { type: "filter", path: "year" },
      { type: "filter", path: "category" }
    ]
  }
)
```

`similarity` must match the frozen geometry (cosine on unit vectors). Filter paths must be declared here; an undeclared field cannot be used inside `$vectorSearch.filter` without falling into unsupported or post-filter behavior.

Index state is polled until `READY` / queryable. That poll interval is included in **index build time** and **time-to-searchable**, never in query p50.

---

## 6. How a query is executed

```javascript
db.passages.aggregate([
  {
    $vectorSearch: {
      index: "vector_index",
      path: "embedding",
      queryVector: q,          // 384 floats
      numCandidates: 64,       // analog of efSearch
      limit: 10,
      filter: {                // optional MQL prefilter
        tenant_id: "t00",
        year: { $gte: 2022 }
      }
    }
  },
  { $project: { _id: 1, score: { $meta: "vectorSearchScore" } } }
])
```

`numCandidates / limit` is the overrequest ratio. MongoDB’s own guidance for many workloads is 5–10×. Iso-config uses `numCandidates=64` at `limit=10` (6.4×). Iso-recall sweeps `{32, 64, 128, 256}`.

**Approximate vs exact.** `$vectorSearch` with HNSW is ANN. Exact neighbors are computed **outside** MongoDB on the frozen matrix. We do not ask `mongot` for a full scan and then treat that as truth.

**Filtering.** Only the filter inside `$vectorSearch` is used (Lucene-side prefilter on declared fields). A `$match` after `$vectorSearch` is a different experiment (post-filter) and is forbidden in Phase 1 cells.

**Quantization.** Self-managed `mongot` documents parity with Atlas for scalar/binary options. Enabling it is an appendix, not a primary cell.

---

## 7. Limitations that affect this study

| Limitation | Consequence |
|---|---|
| Public preview on Community 8.2+ | Pin digests; expect API drift |
| No native Windows `mongot` | Docker/WSL2 only; adds virt overhead to *both* engines if Qdrant is also containerized |
| Two-process RSS | MongoDB hits the 16 GB cliff earlier than a single-process engine of equal graph size |
| Eventual search visibility | Ingest-ack ≠ searchable |
| `$rerank` Atlas-only | Not used |
| `nestedRoot` Atlas-only | Not used |
| Automated Voyage embedding | Not used; embeddings are frozen in the application |
| Community sharded `mongot` | Not measured; no horizontal-scale claims |
| `atlas-local` is a dev image | Fallback only |

---

## 8. What “MongoDB vector search” means in result tables

Unless a cell is explicitly labeled otherwise, **MongoDB** means:

- Generation C `$vectorSearch`
- Community `mongod` 8.2.x + Community `mongot` in two Docker containers
- HNSW, cosine, 384-d, `M=16`, `efConstruction=200`
- Filter fields `tenant_id`, `year`, `category` declared on the index
- One replica-set member, one `mongot`, host Windows 11 + Docker Desktop

It does not mean Atlas Search Nodes, does not mean `knnBeta`, and does not mean a native Windows binary.
