from __future__ import annotations

import math

from src.metrics.latency import closed_loop, percentiles, timed_search


def test_percentiles_on_known_list():
    xs = [float(i) for i in range(1, 101)]
    pct = percentiles(xs)
    assert pct["n"] == 100
    assert pct["p50_ms"] == 50.5
    assert pct["p95_ms"] == 95.05
    assert pct["p99_ms"] == 99.01


def test_empty_percentiles_are_nan():
    pct = percentiles([])
    assert math.isnan(pct["p50_ms"])
    assert math.isnan(pct["p95_ms"])


def test_timed_search_records_timeout_flag():
    hits, dt, err = timed_search(lambda: ["ok"], timeout_s=0.0)
    assert hits == ["ok"]
    assert err == "timeout"
    assert dt >= 0.0


def test_closed_loop_preserves_index_at_concurrency_4():
    def worker(i: int):
        return (i, float(i), None)

    results, lats, errs, wall = closed_loop(worker, 20, concurrency=4)
    assert results == list(range(20))
    assert lats == [float(i) for i in range(20)]
    assert all(e is None for e in errs)
    assert wall >= 0.0
