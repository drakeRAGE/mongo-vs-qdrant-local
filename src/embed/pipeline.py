from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

from src.config import (
    CATEGORIES,
    DIM,
    EMBED,
    GT,
    MANIFESTS,
    MODEL_NAME,
    N_QUERIES,
    NORMALIZE,
    RAW,
    SEED,
    SLICES,
    TENANTS,
    YEARS,
    ensure_dirs,
)


def _sha256(path: Path, nbytes: int = 1_048_576) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(nbytes)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _assign_payload(n: int, texts: list[str], doc_ids: list[str]) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    tenants = rng.choice(TENANTS, size=n, replace=True)
    years = rng.choice(YEARS, size=n, replace=True)
    cats = rng.choice(CATEGORIES, size=n, replace=True)
    token_len = np.array([len(t.split()) for t in texts], dtype=np.int32)
    return pd.DataFrame(
        {
            "row_id": np.arange(n, dtype=np.int64),
            "doc_id": doc_ids,
            "tenant_id": tenants,
            "year": years.astype(np.int32),
            "category": cats,
            "token_len": token_len,
            "text": texts,
        }
    )


def _try_hf_corpus(max_docs: int) -> tuple[list[str], list[str], str] | None:
    try:
        from datasets import load_dataset
    except Exception:
        return None

    candidates = [
        ("Tevatron/msmarco-passage-corpus", None, "train", "docid", "text"),
        ("BeIR/msmarco", "corpus", "corpus", "_id", "text"),
        ("wikimedia/wikipedia", "20231101.simple", "train", "id", "text"),
    ]
    for name, config, split, id_field, text_field in candidates:
        try:
            kwargs = {"split": split, "streaming": True}
            if config:
                ds = load_dataset(name, config, **kwargs)
            else:
                ds = load_dataset(name, **kwargs)
            texts: list[str] = []
            ids: list[str] = []
            for row in tqdm(ds, desc=f"download {name}", total=max_docs):
                text = (row.get(text_field) or "").strip()
                if len(text) < 40:
                    continue
                if text_field != "text" and row.get("title"):
                    text = f"{row['title']}. {text}"
                doc_id = str(row.get(id_field) or len(ids))
                ids.append(doc_id)
                texts.append(text[:4000])
                if len(texts) >= max_docs:
                    break
            if len(texts) >= min(max_docs, 10_000):
                return texts, ids, name
        except Exception as exc:  # noqa: BLE001
            print(f"corpus source {name} failed: {exc}", file=sys.stderr)
            continue
    return None


def _try_hf_queries(n: int) -> list[str] | None:
    try:
        from datasets import load_dataset
    except Exception:
        return None
    for name, config, split, field in [
        ("BeIR/msmarco", "queries", "queries", "text"),
        ("Tevatron/msmarco-passage", None, "train", "query"),
    ]:
        try:
            kwargs = {"split": split, "streaming": True}
            ds = load_dataset(name, config, **kwargs) if config else load_dataset(name, **kwargs)
            out: list[str] = []
            for row in ds:
                if name.startswith("Tevatron") and "query" in row:
                    q = row["query"]
                    if isinstance(q, dict):
                        q = q.get("text") or ""
                else:
                    q = row.get(field) or row.get("text") or ""
                q = str(q).strip()
                if len(q) < 8:
                    continue
                out.append(q[:512])
                if len(out) >= n:
                    return out
        except Exception as exc:  # noqa: BLE001
            print(f"query source {name} failed: {exc}", file=sys.stderr)
            continue
    return None


def _synthetic_corpus(n: int) -> tuple[list[str], list[str], str]:
    """Last-resort public-domain-style passages. Documented as fallback only."""
    rng = np.random.default_rng(SEED)
    templates = [
        "A clinical note describes {topic} observed during {setting} in {year}.",
        "Engineering log: {topic} failed under {setting} with residual error {n}.",
        "Legal memorandum regarding {topic} as applied to {setting} contract {n}.",
        "Research abstract on {topic} using a {setting} protocol, trial {n}.",
        "Travel report from {setting} discussing {topic} and local regulation {n}.",
    ]
    topics = [
        "radial artery catheterization",
        "vector index memory layout",
        "lease termination clauses",
        "ocean current pressure",
        "transformer attention pooling",
        "municipal bond issuance",
        "knee ligament rehabilitation",
        "distributed write-ahead logs",
    ]
    settings = [
        "an urban teaching hospital",
        "a single-node replica set",
        "a coastal research vessel",
        "a county appeals court",
        "a laptop with sixteen gigabytes",
        "a randomized controlled trial",
    ]
    texts, ids = [], []
    for i in range(n):
        t = templates[i % len(templates)].format(
            topic=topics[int(rng.integers(0, len(topics)))],
            setting=settings[int(rng.integers(0, len(settings)))],
            year=int(rng.choice(YEARS)),
            n=i,
        )
        extra = " ".join(
            topics[int(rng.integers(0, len(topics)))] for _ in range(8)
        )
        texts.append(f"{t} {extra}. Passage identifier {i}.")
        ids.append(f"syn-{i:08d}")
    return texts, ids, "synthetic-seed-20260912"


def _embed(texts: list[str], batch_size: int = 64) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME)
    vecs = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=NORMALIZE,
    )
    if vecs.dtype != np.float32:
        vecs = vecs.astype(np.float32)
    if vecs.shape[1] != DIM:
        raise ValueError(f"expected dim {DIM}, got {vecs.shape}")
    return vecs


def prepare_dataset(max_docs: int = 1_000_000, batch_size: int = 64) -> Path:
    """Download, slice, embed, and write MANIFEST.json. Extends existing prefixes."""
    ensure_dirs()
    max_docs = min(max(max_docs, min(SLICES)), max(SLICES))
    emb_path = EMBED / "embeddings.f32"
    q_path = EMBED / "queries.f32"
    payload_path = EMBED / "payload.parquet"
    ids_path = EMBED / "ids.parquet"
    manifest_path = MANIFESTS / "MANIFEST.json"

    n_existing = 0
    if emb_path.exists():
        existing = np.memmap(emb_path, dtype=np.float32, mode="r")
        n_existing = int(existing.size // DIM)
        del existing
        if n_existing >= max_docs and q_path.exists() and payload_path.exists():
            print(f"embeddings already present n={n_existing}, skipping encode")
            return manifest_path

    source = _try_hf_corpus(max_docs)
    if source is None:
        print("Hugging Face corpus unavailable; using documented synthetic fallback")
        source = _synthetic_corpus(max_docs)
    texts, doc_ids, corpus_name = source
    n = len(texts)
    payload = _assign_payload(n, texts, doc_ids)
    payload.to_parquet(payload_path, index=False)
    payload[["row_id", "doc_id"]].to_parquet(ids_path, index=False)
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "corpus_source.txt").write_text(corpus_name, encoding="utf-8")

    if 0 < n_existing < n:
        print(f"extending embeddings {n_existing} -> {n} (prefix kept)")
        old = np.memmap(emb_path, dtype=np.float32, mode="r").reshape(n_existing, DIM)
        prefix = np.array(old[:n_existing], dtype=np.float32)
        del old
        extra = _embed(texts[n_existing:], batch_size=batch_size)
        tmp_path = EMBED / "embeddings.f32.tmp"
        mm = np.memmap(tmp_path, dtype=np.float32, mode="w+", shape=(n, DIM))
        mm[:n_existing] = prefix
        mm[n_existing:] = extra
        mm.flush()
        del mm, extra, prefix
        if emb_path.exists():
            emb_path.unlink()
        tmp_path.replace(emb_path)
    else:
        print(f"embedding {n} passages with {MODEL_NAME}")
        doc_vecs = _embed(texts, batch_size=batch_size)
        mm = np.memmap(emb_path, dtype=np.float32, mode="w+", shape=(n, DIM))
        mm[:] = doc_vecs
        mm.flush()
        del mm, doc_vecs

    n_queries = N_QUERIES
    if q_path.exists() and (EMBED / "query_order.npy").exists():
        print("keeping frozen query embeddings")
        n_queries = int(np.memmap(q_path, dtype=np.float32, mode="r").size // DIM)
    else:
        queries = _try_hf_queries(N_QUERIES)
        if queries is None:
            rng = np.random.default_rng(SEED)
            idx = rng.choice(n, size=min(N_QUERIES, n), replace=False)
            queries = [f"explain or retrieve: {texts[int(i)][:240]}" for i in idx]
        print(f"embedding {len(queries)} queries")
        q_vecs = _embed(queries, batch_size=batch_size)
        qmm = np.memmap(q_path, dtype=np.float32, mode="w+", shape=(len(queries), DIM))
        qmm[:] = q_vecs
        qmm.flush()
        order = np.arange(len(queries), dtype=np.int64)
        rng = np.random.default_rng(SEED)
        rng.shuffle(order)
        np.save(EMBED / "query_order.npy", order)
        (EMBED / "queries.jsonl").write_text(
            "\n".join(json.dumps({"i": i, "text": t}) for i, t in enumerate(queries)),
            encoding="utf-8",
        )
        n_queries = len(queries)

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "model_name": MODEL_NAME,
        "normalize": NORMALIZE,
        "dim": DIM,
        "seed": SEED,
        "n_docs": n,
        "n_queries": n_queries,
        "corpus_name": corpus_name,
        "slices": [s for s in SLICES if s <= n],
        "embeddings_sha256": _sha256(emb_path),
        "queries_sha256": _sha256(q_path),
        "python": sys.version,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {manifest_path}")
    return manifest_path


def load_embeddings(n: int) -> np.ndarray:
    path = EMBED / "embeddings.f32"
    mm = np.memmap(path, dtype=np.float32, mode="r")
    total = mm.size // DIM
    if n > total:
        raise ValueError(f"requested n={n} but embeddings only have {total}")
    return np.asarray(mm.reshape(total, DIM)[:n])


def load_queries() -> np.ndarray:
    path = EMBED / "queries.f32"
    mm = np.memmap(path, dtype=np.float32, mode="r")
    q = mm.size // DIM
    return np.asarray(mm.reshape(q, DIM))


def load_payload(n: int) -> pd.DataFrame:
    df = pd.read_parquet(EMBED / "payload.parquet")
    return df.iloc[:n].copy()
