from __future__ import annotations

import numpy as np


def recall_at_k(
    predicted: list[list[int]],
    truth: np.ndarray,
    k: int,
) -> float:
    if not predicted:
        return float("nan")
    hits = 0.0
    n = 0
    for i, pred in enumerate(predicted):
        gold = set(int(x) for x in truth[i, :k].tolist())
        got = set(int(x) for x in pred[:k])
        if not gold:
            continue
        hits += len(gold & got) / float(k)
        n += 1
    return hits / n if n else float("nan")
