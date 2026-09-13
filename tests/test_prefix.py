from __future__ import annotations

import numpy as np

from src.config import SLICES
from src.exact.ground_truth import _flat_ip


def test_protocol_slices_are_strictly_increasing():
    assert SLICES == tuple(sorted(SLICES))
    assert SLICES == (10_000, 50_000, 100_000, 250_000, 500_000, 1_000_000)


def test_ground_truth_on_a_prefix_only_sees_that_prefix():
    rng = np.random.default_rng(20260912)
    docs = rng.normal(size=(40, 6)).astype(np.float32)
    docs /= np.linalg.norm(docs, axis=1, keepdims=True)
    queries = docs[:3]
    labels_small = _flat_ip(docs[:10], queries, k=5)
    assert labels_small.max() < 10
    labels_full = _flat_ip(docs, queries, k=5)
    # Neighbors on the prefix are not required to match the full-corpus kNN.
    assert labels_full.shape == labels_small.shape
