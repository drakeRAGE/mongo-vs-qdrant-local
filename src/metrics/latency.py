from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import numpy as np


def percentiles(latencies_ms: list[float]) -> dict[str, float]:
    if not latencies_ms:
        return {"p50_ms": float("nan"), "p95_ms": float("nan"), "p99_ms": float("nan")}
    arr = np.asarray(latencies_ms, dtype=np.float64)
    return {
        "p50_ms": float(np.percentile(arr, 50)),
        "p95_ms": float(np.percentile(arr, 95)),
        "p99_ms": float(np.percentile(arr, 99)),
        "mean_ms": float(np.mean(arr)),
        "n": int(arr.size),
    }


def timed_search(
    fn: Callable[[], Any],
    timeout_s: float = 2.0,
) -> tuple[Any | None, float, str | None]:
    t0 = time.perf_counter()
    try:
        result = fn()
        dt = (time.perf_counter() - t0) * 1000.0
        if dt > timeout_s * 1000.0:
            return result, dt, "timeout"
        return result, dt, None
    except Exception as exc:  # noqa: BLE001
        dt = (time.perf_counter() - t0) * 1000.0
        return None, dt, str(exc)


def closed_loop(
    worker: Callable[[int], tuple[Any | None, float, str | None]],
    n_queries: int,
    concurrency: int,
) -> tuple[list[Any | None], list[float], list[str | None], float]:
    results: list[Any | None] = [None] * n_queries
    lats: list[float] = [0.0] * n_queries
    errs: list[str | None] = [None] * n_queries
    wall0 = time.perf_counter()
    if concurrency <= 1:
        for i in range(n_queries):
            results[i], lats[i], errs[i] = worker(i)
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = {pool.submit(worker, i): i for i in range(n_queries)}
            for fut in as_completed(futs):
                i = futs[fut]
                results[i], lats[i], errs[i] = fut.result()
    wall = time.perf_counter() - wall0
    return results, lats, errs, wall
