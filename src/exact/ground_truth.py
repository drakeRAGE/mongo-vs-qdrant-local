from __future__ import annotations

from pathlib import Path

import numpy as np

from src.config import DIM, EMBED, GT, GT_K, ensure_dirs
from src.embed.pipeline import load_embeddings, load_queries


def _flat_ip(docs: np.ndarray, queries: np.ndarray, k: int) -> np.ndarray:
    """Exact top-k by inner product. Batched to keep the score matrix small."""
    try:
        import faiss  # type: ignore

        index = faiss.IndexFlatIP(docs.shape[1])
        index.add(np.ascontiguousarray(docs))
        _scores, labels = index.search(np.ascontiguousarray(queries), k)
        return labels.astype(np.int64)
    except Exception:
        pass

    qn, _ = queries.shape
    n = docs.shape[0]
    k = min(k, n)
    out = np.empty((qn, k), dtype=np.int64)
    # 32 queries × N × 4 bytes: 32 * 1e6 * 4 = 128 MB at 1M.
    batch = 32
    docs_t = np.ascontiguousarray(docs.T)
    for start in range(0, qn, batch):
        q = queries[start : start + batch]
        scores = q @ docs_t
        # argpartition then sort the k window
        part = np.argpartition(-scores, kth=k - 1, axis=1)[:, :k]
        row = np.arange(q.shape[0])[:, None]
        top_scores = scores[row, part]
        order = np.argsort(-top_scores, axis=1)
        out[start : start + batch] = part[row, order]
    return out


def compute_ground_truth(n: int, k: int = GT_K) -> Path:
    ensure_dirs()
    path = GT / f"gt_{n}_top{k}.npy"
    if path.exists():
        print(f"ground truth already present {path.name}")
        return path
    docs = load_embeddings(n)
    queries = load_queries()
    labels = _flat_ip(docs, queries, k)
    np.save(path, labels)
    return path


def load_ground_truth(n: int, k: int = GT_K) -> np.ndarray:
    path = GT / f"gt_{n}_top{k}.npy"
    if not path.exists():
        compute_ground_truth(n, k)
    return np.load(path)


def available_docs() -> int:
    path = EMBED / "embeddings.f32"
    if not path.exists():
        return 0
    return path.stat().st_size // (DIM * 4)
