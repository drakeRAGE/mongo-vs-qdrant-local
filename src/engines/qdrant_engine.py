from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from src.config import QDRANT_COLLECTION, QDRANT_URL, QUERY_TIMEOUT_MS
from src.engines.base import SearchHit


class QdrantEngine:
    name = "qdrant"

    def __init__(self, url: str = QDRANT_URL) -> None:
        self.client = QdrantClient(url=url, timeout=60, check_compatibility=False)
        self.collection = QDRANT_COLLECTION

    def recreate(self, dim: int = 384, m: int = 16, ef_construct: int = 200) -> None:
        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection in existing:
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
            hnsw_config=qm.HnswConfigDiff(m=m, ef_construct=ef_construct),
            optimizers_config=qm.OptimizersConfigDiff(indexing_threshold=10000),
        )
        for field, schema in (
            ("tenant_id", qm.PayloadSchemaType.KEYWORD),
            ("year", qm.PayloadSchemaType.INTEGER),
            ("category", qm.PayloadSchemaType.KEYWORD),
        ):
            self.client.create_payload_index(
                collection_name=self.collection,
                field_name=field,
                field_schema=schema,
            )

    def ingest(
        self,
        vectors: np.ndarray,
        payload: pd.DataFrame,
        batch_size: int = 256,
    ) -> dict[str, Any]:
        n = len(vectors)
        t0 = time.perf_counter()
        inserted = 0
        for start in range(0, n, batch_size):
            end = min(start + batch_size, n)
            points = []
            for i in range(start, end):
                row = payload.iloc[i]
                points.append(
                    qm.PointStruct(
                        id=int(row["row_id"]),
                        vector=vectors[i].astype(float).tolist(),
                        payload={
                            "doc_id": str(row["doc_id"]),
                            "tenant_id": str(row["tenant_id"]),
                            "year": int(row["year"]),
                            "category": str(row["category"]),
                            "token_len": int(row["token_len"]),
                        },
                    )
                )
            self.client.upsert(collection_name=self.collection, points=points, wait=True)
            inserted += len(points)
        ack_s = time.perf_counter() - t0
        return {
            "inserted": inserted,
            "ingest_ack_s": ack_s,
            "index_submit_s": 0.0,
            "docs_per_s": inserted / ack_s if ack_s else 0.0,
        }

    def wait_ready(self, expected_count: int, timeout_s: float = 3600.0) -> dict[str, Any]:
        t0 = time.perf_counter()
        last = None
        while time.perf_counter() - t0 < timeout_s:
            info = self.client.get_collection(self.collection)
            last = {
                "status": str(info.status),
                "points": info.points_count,
                "indexed": getattr(info, "indexed_vectors_count", None),
            }
            status_ok = str(info.status).lower().endswith("green") or str(info.status) == "green"
            # http models may use CollectionStatus.GREEN
            if info.points_count >= expected_count and status_ok:
                return {
                    "ready": True,
                    "wait_s": time.perf_counter() - t0,
                    "count": info.points_count,
                    "index_status": last,
                }
            time.sleep(1.0)
        return {
            "ready": False,
            "wait_s": time.perf_counter() - t0,
            "count": last.get("points") if last else 0,
            "index_status": last,
        }

    def _filter(self, filters: dict[str, Any] | None) -> qm.Filter | None:
        if not filters:
            return None
        must: list[qm.FieldCondition] = []
        if "tenant_id" in filters:
            must.append(
                qm.FieldCondition(
                    key="tenant_id",
                    match=qm.MatchValue(value=str(filters["tenant_id"])),
                )
            )
        if "category" in filters:
            must.append(
                qm.FieldCondition(
                    key="category",
                    match=qm.MatchValue(value=str(filters["category"])),
                )
            )
        if "year_gte" in filters:
            must.append(
                qm.FieldCondition(
                    key="year",
                    range=qm.Range(gte=int(filters["year_gte"])),
                )
            )
        elif "year" in filters:
            must.append(
                qm.FieldCondition(
                    key="year",
                    match=qm.MatchValue(value=int(filters["year"])),
                )
            )
        return qm.Filter(must=must) if must else None

    def search(
        self,
        query: np.ndarray,
        k: int,
        ef: int,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        res = self.client.query_points(
            collection_name=self.collection,
            query=query.astype(float).tolist(),
            limit=int(k),
            search_params=qm.SearchParams(hnsw_ef=int(ef), exact=False),
            query_filter=self._filter(filters),
            timeout=max(QUERY_TIMEOUT_MS // 1000, 2),
        )
        hits = []
        for p in res.points:
            hits.append(SearchHit(row_id=int(p.id), score=float(p.score)))
        return hits

    def count(self) -> int:
        info = self.client.get_collection(self.collection)
        return int(info.points_count or 0)

    def drop(self) -> None:
        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection in existing:
            self.client.delete_collection(self.collection)
