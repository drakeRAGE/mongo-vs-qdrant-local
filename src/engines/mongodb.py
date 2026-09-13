from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

from src.config import (
    DIM,
    MONGO_COLL,
    MONGO_DB,
    MONGO_INDEX,
    MONGO_URI,
    QUERY_TIMEOUT_MS,
)
from src.engines.base import SearchHit


class MongoEngine:
    name = "mongo"

    def __init__(self, uri: str = MONGO_URI) -> None:
        self.client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        self.col = self.client[MONGO_DB][MONGO_COLL]

    def recreate(self, dim: int = DIM, m: int = 16, ef_construct: int = 200) -> None:
        self.client[MONGO_DB].drop_collection(MONGO_COLL)
        self.col = self.client[MONGO_DB][MONGO_COLL]
        # Collection is created on first insert; index created after ingest.

        self._index_def = {
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": dim,
                    "similarity": "cosine",
                    "quantization": "none",
                    "indexingMethod": "hnsw",
                    "hnswOptions": {
                        "maxEdges": m,
                        "numEdgeCandidates": ef_construct,
                    },
                },
                {"type": "filter", "path": "tenant_id"},
                {"type": "filter", "path": "year"},
                {"type": "filter", "path": "category"},
            ]
        }

    def ingest(
        self,
        vectors: np.ndarray,
        payload: pd.DataFrame,
        batch_size: int = 256,
    ) -> dict[str, Any]:
        n = len(vectors)
        t0 = time.perf_counter()
        batch: list[dict[str, Any]] = []
        inserted = 0
        for i in range(n):
            row = payload.iloc[i]
            batch.append(
                {
                    "_id": int(row["row_id"]),
                    "doc_id": str(row["doc_id"]),
                    "embedding": vectors[i].astype(float).tolist(),
                    "tenant_id": str(row["tenant_id"]),
                    "year": int(row["year"]),
                    "category": str(row["category"]),
                    "token_len": int(row["token_len"]),
                }
            )
            if len(batch) >= batch_size:
                self.col.insert_many(batch, ordered=False)
                inserted += len(batch)
                batch = []
        if batch:
            self.col.insert_many(batch, ordered=False)
            inserted += len(batch)
        ack_s = time.perf_counter() - t0

        t_idx = time.perf_counter()
        existing = [ix["name"] for ix in self.col.list_search_indexes()]
        if MONGO_INDEX in existing:
            self.col.drop_search_index(MONGO_INDEX)
            time.sleep(1)
        model = SearchIndexModel(
            definition=self._index_def,
            name=MONGO_INDEX,
            type="vectorSearch",
        )
        self.col.create_search_index(model=model)
        return {
            "inserted": inserted,
            "ingest_ack_s": ack_s,
            "index_submit_s": time.perf_counter() - t_idx,
            "docs_per_s": inserted / ack_s if ack_s else 0.0,
        }

    def _index_status(self) -> dict[str, Any] | None:
        for ix in self.col.list_search_indexes():
            if ix.get("name") == MONGO_INDEX:
                return dict(ix)
        return None

    def _is_ready(self, status: dict[str, Any] | None) -> bool:
        if not status:
            return False
        state = str(status.get("status") or status.get("queryable") or "").lower()
        if status.get("queryable") is True:
            return True
        if state in {"ready", "steading", "true"}:
            return True
        # Some mongot builds report status.ready
        inner = status.get("status")
        if isinstance(inner, dict) and inner.get("ready"):
            return True
        return False

    def wait_ready(self, expected_count: int, timeout_s: float = 3600.0) -> dict[str, Any]:
        t0 = time.perf_counter()
        last: dict[str, Any] | None = None
        while time.perf_counter() - t0 < timeout_s:
            last = self._index_status()
            count = self.col.estimated_document_count()
            if count >= expected_count and self._is_ready(last):
                # Probe query to confirm mongot serves vectors.
                try:
                    probe_q = [0.0] * DIM
                    probe_q[0] = 1.0
                    probe = self.col.aggregate(
                        [
                            {
                                "$vectorSearch": {
                                    "index": MONGO_INDEX,
                                    "path": "embedding",
                                    "queryVector": probe_q,
                                    "numCandidates": 8,
                                    "limit": 1,
                                }
                            },
                            {"$limit": 1},
                        ]
                    )
                    list(probe)
                    return {
                        "ready": True,
                        "wait_s": time.perf_counter() - t0,
                        "count": count,
                        "index_status": last,
                    }
                except Exception:
                    pass
            time.sleep(2.0)
        return {
            "ready": False,
            "wait_s": time.perf_counter() - t0,
            "count": self.col.estimated_document_count(),
            "index_status": last,
        }

    def _filter(self, filters: dict[str, Any] | None) -> dict[str, Any] | None:
        if not filters:
            return None
        out: dict[str, Any] = {}
        if "tenant_id" in filters:
            out["tenant_id"] = filters["tenant_id"]
        if "category" in filters:
            out["category"] = filters["category"]
        if "year_gte" in filters:
            out["year"] = {"$gte": int(filters["year_gte"])}
        elif "year" in filters:
            out["year"] = int(filters["year"])
        return out or None

    def search(
        self,
        query: np.ndarray,
        k: int,
        ef: int,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        stage: dict[str, Any] = {
            "index": MONGO_INDEX,
            "path": "embedding",
            "queryVector": query.astype(float).tolist(),
            "numCandidates": max(int(ef), k),
            "limit": int(k),
        }
        flt = self._filter(filters)
        if flt:
            stage["filter"] = flt
        cursor = self.col.aggregate(
            [
                {"$vectorSearch": stage},
                {
                    "$project": {
                        "_id": 1,
                        "score": {"$meta": "vectorSearchScore"},
                    }
                },
            ],
            maxTimeMS=QUERY_TIMEOUT_MS,
        )
        hits = []
        for doc in cursor:
            hits.append(SearchHit(row_id=int(doc["_id"]), score=float(doc.get("score") or 0.0)))
        return hits

    def count(self) -> int:
        return int(self.col.estimated_document_count())

    def drop(self) -> None:
        self.client[MONGO_DB].drop_collection(MONGO_COLL)
