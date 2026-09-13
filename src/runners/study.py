"""CLI: prepare data, run E0–E6, write JSONL/CSV."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config import (
    BATCH_INGEST,
    DIM,
    EF_SWEEP,
    EMBED,
    HNSW_EF_CONSTRUCT,
    HNSW_M,
    ISO_CONFIG_EF,
    MEASURED_QUERIES,
    MIN_MEASURED,
    PRIMARY_K,
    QUERY_TIMEOUT_MS,
    RECALL_TARGET,
    RESULTS,
    SLICES,
    TENANTS,
    CATEGORIES,
    TRIALS,
    WARMUP,
    ensure_dirs,
)
from src.embed.pipeline import load_embeddings, load_payload, load_queries, prepare_dataset
from src.engines import get_engine
from src.exact.ground_truth import available_docs, compute_ground_truth, load_ground_truth
from src.host import collect_host_snapshot, evaluate_host
from src.metrics.latency import closed_loop, percentiles, timed_search
from src.metrics.recall import recall_at_k
from src.metrics.resources import engine_stats


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _query_order(n_q: int) -> np.ndarray:
    path = EMBED / "query_order.npy"
    if path.exists():
        order = np.load(path)
        return order[:n_q]
    return np.arange(n_q)


def _filters_for(selectivity: str) -> tuple[dict[str, Any] | None, str]:
    if selectivity in {"100", "none", "unfiltered"}:
        return None, "unfiltered"
    if selectivity == "50":
        return {"year_gte": 2022}, "year>=2022"
    if selectivity == "10":
        return {"tenant_id": TENANTS[0]}, "tenant=t00"
    if selectivity == "1":
        return {"tenant_id": TENANTS[0], "category": CATEGORIES[0]}, "tenant=t00&category=health"
    raise ValueError(selectivity)


def _host_gate(engine: str) -> dict[str, Any]:
    snap = collect_host_snapshot()
    # Engine already resident: 2 GB free is rarely available on this 16 GB host.
    decision = evaluate_host(snap, expect=engine, min_free_gb=1.0)
    if not decision["host_ok"]:
        raise RuntimeError(f"host abort: {decision['reason']}")
    return {"snapshot": snap, "decision": decision}


def _run_queries(
    engine,
    queries: np.ndarray,
    k: int,
    ef: int,
    filters: dict[str, Any] | None,
    concurrency: int,
    warmup: int,
    measured: int,
) -> dict[str, Any]:
    order = _query_order(len(queries))
    warm_idx = [int(order[i % len(order)]) for i in range(warmup)]
    meas_idx = [int(order[i % len(order)]) for i in range(measured)]

    for i in warm_idx:
        timed_search(lambda q=queries[i]: engine.search(q, k, ef, filters))

    def worker(j: int):
        q = queries[meas_idx[j]]

        def _fn():
            return engine.search(q, k, ef, filters)

        hits, dt, err = timed_search(_fn, timeout_s=QUERY_TIMEOUT_MS / 1000.0)
        ids = [h.row_id for h in hits] if hits else []
        return (ids, dt, err)

    results, lats, errs, wall = closed_loop(worker, measured, concurrency)
    pred = [r if r else [] for r in results]
    errors = [e for e in errs if e]
    ok_lats = [lats[i] for i in range(len(lats)) if not errs[i]]
    qps = (measured - len(errors)) / wall if wall else 0.0
    return {
        "latencies_ms": ok_lats,
        "percentiles": percentiles(ok_lats),
        "qps": qps,
        "wall_s": wall,
        "error_rate": len(errors) / measured if measured else 1.0,
        "errors_sample": errors[:5],
        "predicted": pred,
        "query_index": meas_idx,
        "n_measured": len(ok_lats),
    }


def ensure_ingest(engine_name: str, n: int, run_id: str, results_path: Path) -> dict[str, Any] | None:
    """Reuse an already-loaded collection of size n instead of rebuilding."""
    engine = get_engine(engine_name)
    if engine.count() == n:
        print(f"reuse {engine_name} collection n={n}")
        return None
    return ingest_cell(engine_name, n, run_id, results_path)


def ingest_cell(engine_name: str, n: int, run_id: str, results_path: Path) -> dict[str, Any]:
    host = _host_gate(engine_name)
    engine = get_engine(engine_name)
    vectors = load_embeddings(n)
    payload = load_payload(n)
    engine.recreate(dim=DIM, m=HNSW_M, ef_construct=HNSW_EF_CONSTRUCT)
    rss_before = engine_stats(engine_name)
    t0 = time.perf_counter()
    ingest = engine.ingest(vectors, payload, batch_size=BATCH_INGEST)
    ready = engine.wait_ready(n)
    build_s = time.perf_counter() - t0
    rss_after = engine_stats(engine_name)
    row = {
        "run_id": run_id,
        "ts": _now(),
        "experiment": "E4",
        "cell": "ingest",
        "engine": engine_name,
        "n": n,
        "ingest": ingest,
        "ready": ready,
        "index_build_s": build_s,
        "time_to_searchable_s": ingest["ingest_ack_s"] + ready.get("wait_s", 0.0),
        "rss_before": rss_before,
        "rss_after": rss_after,
        "host": host["decision"],
        "label": "ingest_bulk",
    }
    _append_jsonl(results_path, row)
    if not ready.get("ready"):
        raise RuntimeError(f"{engine_name} index not ready after {build_s:.1f}s")
    return row


def query_cell(
    engine_name: str,
    n: int,
    ef: int,
    k: int,
    concurrency: int,
    selectivity: str,
    experiment: str,
    label: str,
    run_id: str,
    results_path: Path,
    trial: int = 1,
    skip_ingest: bool = True,
) -> dict[str, Any]:
    host = _host_gate(engine_name)
    engine = get_engine(engine_name)
    if engine.count() < n:
        ingest_cell(engine_name, n, run_id, results_path)
        engine = get_engine(engine_name)
    queries = load_queries()
    filters, filt_name = _filters_for(selectivity)
    rss = engine_stats(engine_name)
    measured = min(MEASURED_QUERIES, len(queries))
    qres = _run_queries(
        engine,
        queries,
        k=k,
        ef=ef,
        filters=filters,
        concurrency=concurrency,
        warmup=WARMUP,
        measured=measured,
    )
    truth = load_ground_truth(n)
    aligned = truth[np.asarray(qres["query_index"], dtype=np.int64)]
    rec = {}
    for kk in (10, 50, 100):
        rec[f"recall_at_{kk}"] = recall_at_k(qres["predicted"], aligned, kk)
    invalid = qres["n_measured"] < MIN_MEASURED or qres["error_rate"] > 0.01
    row = {
        "run_id": run_id,
        "ts": _now(),
        "experiment": experiment,
        "cell": label,
        "engine": engine_name,
        "n": n,
        "k": k,
        "ef": ef,
        "m": HNSW_M,
        "ef_construct": HNSW_EF_CONSTRUCT,
        "concurrency": concurrency,
        "selectivity": selectivity,
        "filter": filt_name,
        "trial": trial,
        "label": label,
        "percentiles": qres["percentiles"],
        "qps": qres["qps"],
        "wall_s": qres["wall_s"],
        "error_rate": qres["error_rate"],
        "errors_sample": qres["errors_sample"],
        "n_measured": qres["n_measured"],
        "invalid": invalid,
        **rec,
        "rss": rss,
        "host": host["decision"],
        "host_ok": host["decision"]["host_ok"],
        "swap_active": host["decision"]["swap_active"],
    }
    # Drop bulky predicted lists from the log.
    _append_jsonl(results_path, row)
    return row


def run_e0(engine_name: str, run_id: str, results_path: Path) -> dict[str, Any]:
    n = 10_000
    if available_docs() < n:
        raise RuntimeError("prepare the dataset first (need >= 10K embeddings)")
    ingest_cell(engine_name, n, run_id, results_path)
    row = query_cell(
        engine_name,
        n=n,
        ef=256,
        k=PRIMARY_K,
        concurrency=1,
        selectivity="100",
        experiment="E0",
        label="e0_high_ef",
        run_id=run_id,
        results_path=results_path,
    )
    if row.get("recall_at_10", 0) < 0.90:
        raise RuntimeError(
            f"E0 failed: Recall@10={row.get('recall_at_10')} < 0.90 — harness/index mismatch"
        )
    return row


def run_e1(engine_name: str, run_id: str, results_path: Path, max_n: int, min_n: int = 0) -> None:
    ns = [s for s in SLICES if min_n <= s <= max_n and s <= available_docs()]
    for n in ns:
        ingest_cell(engine_name, n, run_id, results_path)
        for trial in range(1, TRIALS + 1):
            query_cell(
                engine_name,
                n=n,
                ef=ISO_CONFIG_EF,
                k=PRIMARY_K,
                concurrency=1,
                selectivity="100",
                experiment="E1",
                label="e1_iso_config",
                run_id=run_id,
                results_path=results_path,
                trial=trial,
            )
        if n in {100_000, 250_000, 500_000, 1_000_000} and n <= max_n:
            for ef in EF_SWEEP:
                query_cell(
                    engine_name,
                    n=n,
                    ef=ef,
                    k=PRIMARY_K,
                    concurrency=1,
                    selectivity="100",
                    experiment="E1",
                    label="e1_iso_recall_sweep",
                    run_id=run_id,
                    results_path=results_path,
                    trial=1,
                )


def run_e2(engine_name: str, run_id: str, results_path: Path, max_n: int, min_n: int = 0) -> None:
    targets = [
        n
        for n in (100_000, 250_000, 500_000)
        if min_n <= n <= max_n and n <= available_docs()
    ]
    if not targets and available_docs() >= 10_000:
        n = min(max_n, available_docs())
        if n >= min_n:
            targets = [n]
    for n in targets:
        ensure_ingest(engine_name, n, run_id, results_path)
        for conc in (1, 4, 8):
            query_cell(
                engine_name,
                n=n,
                ef=ISO_CONFIG_EF,
                k=PRIMARY_K,
                concurrency=conc,
                selectivity="100",
                experiment="E2",
                label="e2_concurrency",
                run_id=run_id,
                results_path=results_path,
            )


def run_e3(engine_name: str, run_id: str, results_path: Path, max_n: int) -> None:
    n = 500_000 if 500_000 <= max_n else (max_n if max_n >= 10_000 else 0)
    # Prefer 500K; if the frozen set is smaller, still run filters at the largest available slice.
    n = min(n, available_docs())
    if n < 10_000:
        return
    ensure_ingest(engine_name, n, run_id, results_path)
    for sel in ("100", "50", "10", "1"):
        for conc in (1, 4):
            query_cell(
                engine_name,
                n=n,
                ef=ISO_CONFIG_EF,
                k=PRIMARY_K,
                concurrency=conc,
                selectivity=sel,
                experiment="E3",
                label="e3_filter",
                run_id=run_id,
                results_path=results_path,
            )


def run_e5(engine_name: str, run_id: str, results_path: Path, max_n: int) -> None:
    n = min(500_000, max_n, available_docs())
    if n < 10_000:
        return
    host = _host_gate(engine_name)
    engine = get_engine(engine_name)
    if engine.count() < n:
        ingest_cell(engine_name, n, run_id, results_path)
    queries = load_queries()
    filters, _ = _filters_for("100")
    # Cold: no warm-up.
    qres = _run_queries(
        get_engine(engine_name),
        queries,
        k=PRIMARY_K,
        ef=ISO_CONFIG_EF,
        filters=filters,
        concurrency=1,
        warmup=0,
        measured=min(50, len(queries)),
    )
    row = {
        "run_id": run_id,
        "ts": _now(),
        "experiment": "E5",
        "cell": "e5_cold",
        "engine": engine_name,
        "n": n,
        "ef": ISO_CONFIG_EF,
        "percentiles": qres["percentiles"],
        "qps": qres["qps"],
        "n_measured": qres["n_measured"],
        "error_rate": qres["error_rate"],
        "label": "cold_no_warmup",
        "host": host["decision"],
    }
    _append_jsonl(results_path, row)


def jsonl_to_csv(jsonl_path: Path) -> Path:
    rows = []
    if not jsonl_path.exists():
        raise FileNotFoundError(jsonl_path)
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            pct = rec.get("percentiles") or {}
            rss = rec.get("rss") or rec.get("rss_after") or {}
            rows.append(
                {
                    "run_id": rec.get("run_id"),
                    "ts": rec.get("ts"),
                    "experiment": rec.get("experiment"),
                    "cell": rec.get("cell"),
                    "label": rec.get("label"),
                    "engine": rec.get("engine"),
                    "n": rec.get("n"),
                    "ef": rec.get("ef"),
                    "k": rec.get("k"),
                    "concurrency": rec.get("concurrency"),
                    "selectivity": rec.get("selectivity"),
                    "trial": rec.get("trial"),
                    "p50_ms": pct.get("p50_ms"),
                    "p95_ms": pct.get("p95_ms"),
                    "p99_ms": pct.get("p99_ms"),
                    "qps": rec.get("qps"),
                    "recall_at_10": rec.get("recall_at_10"),
                    "recall_at_50": rec.get("recall_at_50"),
                    "recall_at_100": rec.get("recall_at_100"),
                    "error_rate": rec.get("error_rate"),
                    "n_measured": rec.get("n_measured"),
                    "invalid": rec.get("invalid"),
                    "index_build_s": rec.get("index_build_s"),
                    "time_to_searchable_s": rec.get("time_to_searchable_s"),
                    "rss_mb": rss.get("rss_mb") if isinstance(rss, dict) else None,
                    "host_ok": rec.get("host_ok"),
                }
            )
    csv_path = jsonl_path.with_suffix(".csv")
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return csv_path


def main(argv: list[str] | None = None) -> int:
    ensure_dirs()
    p = argparse.ArgumentParser(description="VectorDB_Proof study runner")
    sub = p.add_subparsers(dest="cmd", required=True)

    prep = sub.add_parser("prepare")
    prep.add_argument("--max-docs", type=int, default=100_000)
    prep.add_argument("--batch-size", type=int, default=64)

    gt = sub.add_parser("ground-truth")
    gt.add_argument("--n", type=int, required=True)

    run = sub.add_parser("run")
    run.add_argument("--engine", choices=["mongo", "qdrant"], required=True)
    run.add_argument(
        "--experiments",
        default="E0,E1,E2,E3,E4,E5,E6",
        help="Comma list of E0-E6",
    )
    run.add_argument("--max-n", type=int, default=100_000)
    run.add_argument("--min-n", type=int, default=0, help="Skip E1 slices smaller than this")
    run.add_argument("--run-id", default="")

    sub.add_parser("analyze")

    args = p.parse_args(argv)

    if args.cmd == "prepare":
        prepare_dataset(max_docs=args.max_docs, batch_size=args.batch_size)
        n = min(args.max_docs, available_docs())
        for s in SLICES:
            if s <= n:
                compute_ground_truth(s)
        return 0

    if args.cmd == "ground-truth":
        compute_ground_truth(args.n)
        return 0

    if args.cmd == "analyze":
        from src.runners.analyze import analyze_all

        analyze_all()
        return 0

    run_id = args.run_id or time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    results_path = RESULTS / f"{run_id}.jsonl"
    exps = {e.strip().upper() for e in args.experiments.split(",") if e.strip()}
    print(f"run_id={run_id} engine={args.engine} experiments={sorted(exps)} max_n={args.max_n}")

    if "E0" in exps:
        run_e0(args.engine, run_id, results_path)
    if "E1" in exps:
        run_e1(args.engine, run_id, results_path, args.max_n, min_n=getattr(args, "min_n", 0))
    if "E2" in exps:
        run_e2(args.engine, run_id, results_path, args.max_n, min_n=getattr(args, "min_n", 0))
    if "E3" in exps:
        run_e3(args.engine, run_id, results_path, args.max_n)
    if "E4" in exps:
        # Ingest metrics are recorded inside ingest_cell, already called by E1.
        for n in [100_000, 250_000, 500_000]:
            if getattr(args, "min_n", 0) <= n <= args.max_n and n <= available_docs():
                ensure_ingest(args.engine, n, run_id, results_path)
    if "E5" in exps:
        run_e5(args.engine, run_id, results_path, args.max_n)
    if "E6" in exps:
        # Resource envelopes are attached to every ingest/query cell as rss_*.
        pass

    csv = jsonl_to_csv(results_path)
    print(f"wrote {results_path} and {csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
