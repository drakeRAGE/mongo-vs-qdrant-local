"""Recall must be aligned to the measured query order, not file order."""

from __future__ import annotations

import math

import numpy as np

from src.metrics.recall import recall_at_k


def test_perfect_overlap():
    truth = np.array([[0, 1, 2, 3], [4, 5, 6, 7]])
    pred = [[0, 1, 2], [4, 5, 6]]
    assert recall_at_k(pred, truth, 3) == 1.0


def test_shuffled_query_order_without_align_is_zero():
    truth = np.array([[0, 1, 2], [10, 11, 12]])
    pred = [[10, 11, 12], [0, 1, 2]]
    assert recall_at_k(pred, truth, 3) == 0.0


def test_shuffled_query_order_with_align_is_one():
    truth = np.array([[0, 1, 2], [10, 11, 12]])
    query_index = [1, 0]
    pred = [[10, 11, 12], [0, 1, 2]]
    aligned = truth[np.asarray(query_index, dtype=np.int64)]
    assert recall_at_k(pred, aligned, 3) == 1.0


def test_empty_predictions_are_nan():
    assert math.isnan(recall_at_k([], np.zeros((0, 3), dtype=np.int64), 3))
