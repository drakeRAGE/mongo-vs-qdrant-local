from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import pandas as pd


@dataclass
class SearchHit:
    row_id: int
    score: float


class EngineAdapter(Protocol):
    name: str

    def recreate(
        self,
        dim: int,
        m: int,
        ef_construct: int,
    ) -> None: ...

    def ingest(
        self,
        vectors: np.ndarray,
        payload: pd.DataFrame,
        batch_size: int,
    ) -> dict[str, Any]: ...

    def wait_ready(self, expected_count: int, timeout_s: float = 1800.0) -> dict[str, Any]: ...

    def search(
        self,
        query: np.ndarray,
        k: int,
        ef: int,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]: ...

    def count(self) -> int: ...

    def drop(self) -> None: ...
