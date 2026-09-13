from __future__ import annotations

import numpy as np

from src.exact.ground_truth import _flat_ip


def test_inner_product_top1_is_the_same_row():
    rng = np.random.default_rng(20260912)
    docs = rng.normal(size=(32, 8)).astype(np.float32)
    docs /= np.linalg.norm(docs, axis=1, keepdims=True)
    labels = _flat_ip(docs, docs[:5], k=1)
    assert labels.shape == (5, 1)
    assert np.array_equal(labels[:, 0], np.arange(5))


def test_top_k_is_sorted_by_score():
    docs = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    q = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    labels = _flat_ip(docs, q, k=2)
    assert labels[0, 0] == 0
    assert labels[0, 1] == 1
