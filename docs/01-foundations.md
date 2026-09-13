# 01 — Foundations: Embeddings, Distance, and Vector Indexes

This manuscript is the conceptual core of the VectorDB_Proof study. It is written so a systems engineer can defend every subsequent experimental choice: why vectors are frozen, why cosine and inner product are treated as equivalent, why HNSW is the index under test, and why Approximate Nearest Neighbor (ANN) recall is not the same thing as information-retrieval quality.

Primary references: Malkov & Yashunin, *Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs* (IEEE TPAMI, 2018); Jégou, Douze & Schmid, *Product Quantization for Nearest Neighbor Search* (IEEE TPAMI, 2011); Thakur et al., *BEIR* (2021); Johnson, Douze & Jégou, *Billion-scale similarity search with GPUs* (IEEE TBD, 2019, Faiss).

---

## 1. What an embedding is

An embedding is a **fixed-length vector of real numbers** produced by a neural network. It is not a hash, not a bag-of-words histogram, and not a compressed copy of the source text. It is a point \(v \in \mathbb{R}^{D}\) in a space whose geometry was **learned** so that a chosen notion of proximity approximates a chosen notion of meaning.

Take the sentence “the catheter was inserted into the radial artery.” A 384-dimensional retrieval model maps that sentence to one point \(v \in \mathbb{R}^{384}\). Coordinate \(i\) is not a human-readable feature such as “medical” or “procedure.” It is an activation after pooling. Interpreting a single coordinate in isolation is usually meaningless; only **relative geometry** (distances and angles among many points) is operationally useful.

For almost every modern dense-retrieval checkpoint used in RAG, the last step is **L2 normalization**:

\[
\hat{v} = \frac{v}{\|v\|_2}, \qquad \|\hat{v}\|_2 = 1.
\]

Normalized vectors live on the unit hypersphere \(S^{D-1}\). On that surface the three classical ranking scores become order-equivalent:

\[
\begin{aligned}
\text{dot}(q,d) &= q \cdot d, \\
\text{cosine}(q,d) &= \frac{q \cdot d}{\|q\|\,\|d\|} = q \cdot d \quad \text{when both are unit}, \\
\|q-d\|_2^2 &= \|q\|_2^2 + \|d\|_2^2 - 2 q\cdot d = 2 - 2 q\cdot d.
\end{aligned}
\]

Maximizing cosine, maximizing inner product, and minimizing Euclidean distance therefore return the **same ranking** for unit vectors. Scores themselves are not interchangeable: a table that mixes MongoDB cosine scores with Qdrant Euclidean distances is incomparable even when the ID lists match.

**Study rule.** Generate embeddings with explicit L2 normalization. Store the normalized `float32` arrays. Configure both engines for cosine (or both for inner product). Never mix metrics across engines in a published cell.

---

## 2. How text becomes a vector

```text
raw UTF-8 text
  → tokenizer (WordPiece / BPE / Unigram)
  → token IDs, typically truncated at 512
  → transformer stack (self-attention + FFN, residual + LayerNorm)
  → token hidden states  H ∈ R^{L × d_model}
  → pooling (mean of non-padding tokens, or CLS)
  → optional linear projection to output_dim D
  → L2 normalize
  → v ∈ R^{D}
```

Three different models appear in a production RAG stack. Conflating them is the most common architectural error in vector-database discussions.

| Role | What it does | When it runs | In this study |
|---|---|---|---|
| Embedding model (bi-encoder) | text → \(\mathbb{R}^{D}\) independently | Once per document; once per query | Frozen: `BAAI/bge-small-en-v1.5`, 384-d |
| Reranker (cross-encoder) | scores the pair (query, document) | After retrieval, top-n only | Out of scope |
| LLM | generates tokens conditioned on context | After retrieval | Out of scope |

The embedding model is **not** the vector database. The LLM is **not** a search engine. Phase 1 times only storage, index build, and nearest-neighbor query execution.

`BAAI/bge-small-en-v1.5` is locked because it is Apache-2.0, 384-dimensional, well studied on BEIR-style retrieval, and CPU-reasonable on the experimental laptop. Query-side prefixes required by some E5 checkpoints are therefore avoided. The weight identifier and a content hash are recorded in `MANIFEST.json`. Switching the checkpoint mid-study would change the geometry and invalidate every recall number.

---

## 3. What dimensions mean

\(D\) is the length of the vector. It is not “more meaning” in a simple linear sense. In practice, larger trained models with larger \(D\) often retrieve better, at a cost that is linear in memory and at least linear in distance arithmetic.

Raw float32 storage, ignoring indexes, payloads, and process overhead:

\[
\text{bytes} = N \times D \times 4
\]

| \(N\) | 384-d | 768-d | 1536-d |
|---:|---:|---:|---:|
| 10,000 | 15.4 MB | 30.7 MB | 61.4 MB |
| 100,000 | 154 MB | 307 MB | 614 MB |
| 500,000 | 768 MB | 1.54 GB | 3.07 GB |
| 1,000,000 | 1.54 GB | 3.07 GB | 6.14 GB |
| 5,000,000 | 7.68 GB | 15.4 GB | 30.7 GB |

HNSW graph memory is roughly \(N \times 2M \times 4 \times 1.2\) bytes. At \(M=16\) that is about 150 bytes per vector — secondary to 384-d payloads, dominant only at tiny \(D\).

This machine has 16 GB of soldered LPDDR5. The core ladder is therefore locked at **384-d**. A 768-d appendix is permitted at \(N \le 500{,}000\). 1536-d is not a primary condition.

---

## 4. Why semantically similar texts have nearby vectors

A bi-encoder is trained with a contrastive or InfoNCE-style objective. A query embedding is pulled toward embeddings of relevant passages and pushed away from in-batch or mined negatives. After training, the geometry **implements** that similarity. Two texts are nearby because the optimizer placed them nearby, not because English has a built-in 384-dimensional coordinate system.

Two evaluation questions must stay separate:

1. **Index recall (ANN).** Overlap between the engine’s top-\(k\) and the exact top-\(k\) of the *same* frozen vectors. This measures the index, not the model.
2. **Retrieval quality (IR).** nDCG@10 / Recall@100 against human qrels. This measures the embedding model (and, secondarily, index recall).

A drop in nDCG is not evidence that MongoDB or Qdrant is “worse at search” if ANN recall is the actual cause. Conversely, Recall@10 = 0.99 with poor nDCG blames the checkpoint or the corpus, not the engine.

---

## 5. Worked example (3-d, then 384-d)

Unit vectors:

```text
q  = [0.00, 0.80, 0.60]     "blood pressure in the arm"
d1 = [0.10, 0.82, 0.56]     "radial artery systolic reading"
d2 = [0.05, 0.20, 0.98]     "ocean current pressure"
d3 = [0.90, 0.40, 0.17]     "arm of a chair"
```

| Pair | Dot / cosine | \(\|q-d\|_2^2\) |
|---|---:|---:|
| \(q,d_1\) | 0.992 | 0.016 |
| \(q,d_2\) | 0.748 | 0.504 |
| \(q,d_3\) | 0.422 | 1.156 |

Ranking is \(d_1 \succ d_2 \succ d_3\) under all three metrics. In 384 dimensions the arithmetic is identical; visualization is not. The database’s job is: given \(q\) and \(N\) document vectors, return the top-\(k\) largest dots **without** a full scan when \(N\) makes a scan too expensive.

---

## 6. When each distance metric is appropriate

- **Cosine.** Default for text embeddings that encode *direction*. Use when vectors may be unnormalized, or when the engine should normalize internally.
- **Inner product (dot / IP).** Default when vectors are already L2-normalized, or when magnitude is semantically meaningful (some two-tower recommenders). Fastest of the three in IP indexes.
- **Euclidean (L2).** Default for unnormalized vectors, many vision embeddings, and clustering. On unit vectors it ranks like cosine; the score scale differs.

This study uses **cosine / IP on unit vectors**. Ground truth is Faiss `IndexFlatIP` (or batched NumPy `queries @ docs.T`) on the frozen memmap.

---

## 7. What a vector database does

A vector database is a **storage + index + query-execution** system for high-dimensional nearest-neighbor search, usually with metadata filters. It does not create meaning and it does not write answers.

| Component | Responsibility |
|---|---|
| Embedding model | text → \(\mathbb{R}^{D}\) |
| Vector database | store `(id, vector, payload)`, build ANN, answer `kNN(q, filter)` |
| Document / relational DB | documents, transactions, scalar indexes; MongoDB is this *plus* a search sidecar |
| Application | orchestration, auth, chunking, prompts |
| LLM | conditional generation from retrieved context |

```text
User query
  → application
  → embedding model  → q ∈ R^D
  → vector search engine
       1. optional metadata filter
       2. ANN walk (HNSW) or exact scan
       3. top-k ids + scores
  → fetch document text
  → (optional rerank)
  → LLM
  → response
```

Phase 1 clocks **only** the engine call: start after \(q\) is in process memory, stop when top-\(k\) IDs are in the client. Embedding latency is published once as a constant and excluded from QPS. LLM latency is excluded.

---

## 8. Why B-trees are the wrong index for this workload

A B-tree or LSM tree on a scalar field answers range and equality predicates. Nearest neighbor in high dimension has no single sort key that preserves neighborhoods. This is the operational content of the curse of dimensionality: volume concentrates in the shell, pairwise distances concentrate, and space-partitioning trees visit a fraction of the data that approaches a scan.

Exact search costs \(\Theta(ND)\) multiply-adds per query. A well-vectorized 1M × 384 inner-product scan is a few hundred million FLOPs — a few milliseconds to tens of milliseconds if the working set is resident and the kernel is BLAS/SIMD. It degrades under concurrency, under filters that destroy sequential access, and at larger \(D\).

You therefore choose:

- **Exact:** scan, or an inverted file that still scans the probed lists completely.
- **Approximate:** a graph or partition index that visits \(o(N)\) candidates and accepts missed neighbors.

“Just store a float array in MongoDB or PostgreSQL” is correct at small \(N\). It becomes the wrong *index* long before it becomes the wrong *store*.

---

## 9. ANN, HNSW, IVF, quantization

**Recall@K** for an index, against exact neighbors \(G\) of the same vectors:

\[
\mathrm{Recall}@K = \frac{|G \cap R|}{|G|}
\]

averaged over the query set. This is the primary quality metric of the study.

### HNSW

Hierarchical Navigable Small World graphs (Malkov & Yashunin, 2018) are the dominant in-memory ANN index in this study. Both Qdrant and Lucene-based `mongot` implement this family.

- Each vector is a graph node.
- Layer 0 is a dense neighborhood graph; higher layers are sparse highways.
- A node’s maximum layer is sampled from a geometric distribution.
- Insert: descend greedily from the entry point, then run a bounded beam search of width `efConstruction` and connect to `M` neighbors (layer 0 often uses \(2M\)).
- Search: greedy descent, then beam search of width `efSearch` (Qdrant `hnsw_ef`) or MongoDB `numCandidates`.
- Memory: \(\approx N \times 2M \times 4 \times 1.2\) bytes plus the vectors.

The study’s iso-config cell uses \(M=16\), `efConstruction=200`. Search width starts at 64 and is swept in \(\{32,64,128,256\}\).

HNSW implementations are **not** bitwise equivalent. Lucene HNSW and Qdrant HNSW can differ in neighbor-selection heuristics, layer assignment, concurrency, and how filters interact with traversal. Iso-config is therefore labeled **explainability**, not **iso-quality**. Decision-grade comparison is **iso-recall**: the smallest search width that reaches Recall@10 ≥ 0.95.

### IVF

Inverted File indexes cluster vectors into `nlist` coarse centroids. A query probes `nprobe` lists and scans those vectors (often with PQ residuals). IVF is the classic Faiss/Milvus path. **This study is not IVF versus HNSW.** Both engines under test are HNSW-family. IVF is documented so a reader does not import the wrong taxonomy from Faiss tutorials.

### Quantization

Quantization stores a compressed stand-in for scoring and optionally rescores survivors in higher precision.

| Method | Typical size vs float32 | Role |
|---|---|---|
| Scalar / int8 | ~4× smaller | Common first step |
| Binary / 1-bit | ~32× smaller | Needs rescore for high recall |
| Product quantization | codebook-dependent | Classic Faiss, not the default here |

Quantization is how a 2M-point appendix becomes conceivable on 16 GB. It is **not** in the primary iso-precision ladder unless both engines are tuned to the same recall target.

---

## 10. Why a dedicated vector database exists

MongoDB is not assumed to be bad. A general-purpose document store with a competent HNSW sidecar is a strong default when:

- vectors are a feature of documents you already store;
- \(N\) is modest (tens of thousands to low hundreds of thousands at 384-d);
- query QPS is modest;
- you want one operations story and transactional document updates;
- you can accept a replica set plus `mongot`.

A purpose-built engine becomes interesting when:

- \(N \times D\) plus HNSW no longer fit next to the operational database;
- you need high QPS or tight p99 with concurrent filters;
- you want vector-specific memory tiers, quantization, and payload-index planning without carrying WiredTiger + a replica set + Lucene;
- time-to-searchable under continuous ingest dominates operations.

The crossover is a **surface** over \(N\), \(D\), concurrency, filter selectivity, ingest pattern, and RAM — not a single headline integer. This repository exists to measure that surface on one inventoried laptop, not to prove a predetermined winner.

---

## 11. Metrics used later in the protocol

Definitions are restated in `05-protocol.md`. The conceptual point here is *why* each exists.

- **p50 / p95 / p99** exist because interactive systems fail in the tail. A 4 ms mean with an 80 ms p99 is a failed RAG retriever.
- **QPS** exists because the reciprocal of single-thread p50 is not capacity.
- **Recall@K** exists because a faster wrong index is not a better index.
- **Time-to-searchable** exists because `insertMany` acknowledgement is not “the vector is in HNSW.”
- **RSS and page faults** exist because this machine’s cliff is RAM, not disk.

Mean-only latency tables are rejected by this protocol.
