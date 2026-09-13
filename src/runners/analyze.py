"""Aggregate JSONL trials, plot curves, write docs/07-results.md from data only."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.config import PLOTS, RESULTS, ROOT, ensure_dirs

ENGINE_COLOR = {"mongo": "#0B6E4F", "qdrant": "#C45C26"}
N_STYLE = {10_000: ":", 50_000: ":", 100_000: "--", 250_000: "-.", 500_000: "-", 1_000_000: "-"}
PROTOCOL_N = {100_000, 500_000}


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "#FAFAF7",
            "axes.grid": True,
            "grid.alpha": 0.35,
            "grid.linestyle": ":",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "legend.frameon": True,
            "legend.fancybox": False,
            "legend.framealpha": 0.92,
        }
    )


def _color(engine: str) -> str:
    return ENGINE_COLOR.get(str(engine), "#333333")


def _n_label(n: float | int) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n // 1_000_000}M"
    return f"{n // 1000}K"


def _load_all() -> pd.DataFrame:
    frames = []
    for path in sorted(RESULTS.glob("*.jsonl")):
        rows = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                pct = rec.get("percentiles") or {}
                rss = rec.get("rss") or rec.get("rss_after") or {}
                rows.append(
                    {
                        "file": path.name,
                        "experiment": rec.get("experiment"),
                        "cell": rec.get("cell"),
                        "label": rec.get("label"),
                        "engine": rec.get("engine"),
                        "n": rec.get("n"),
                        "ef": rec.get("ef"),
                        "concurrency": rec.get("concurrency"),
                        "selectivity": rec.get("selectivity"),
                        "trial": rec.get("trial"),
                        "p50_ms": pct.get("p50_ms"),
                        "p95_ms": pct.get("p95_ms"),
                        "p99_ms": pct.get("p99_ms"),
                        "qps": rec.get("qps"),
                        "recall_at_10": rec.get("recall_at_10"),
                        "error_rate": rec.get("error_rate"),
                        "n_measured": rec.get("n_measured"),
                        "invalid": rec.get("invalid"),
                        "index_build_s": rec.get("index_build_s"),
                        "time_to_searchable_s": rec.get("time_to_searchable_s"),
                        "rss_mb": rss.get("rss_mb") if isinstance(rss, dict) else None,
                    }
                )
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _valid(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "invalid" in out:
        inv = out["invalid"].astype("boolean").fillna(False)
        out = out[~inv.astype(bool)]
    return out


def _save(fig, name: str) -> Path:
    PLOTS.mkdir(parents=True, exist_ok=True)
    path = PLOTS / name
    fig.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def _e1_iso(df: pd.DataFrame) -> pd.DataFrame:
    sub = _valid(df)
    return sub[(sub["experiment"] == "E1") & (sub["label"] == "e1_iso_config")]


def _md_plot(path: Path | None) -> list[str]:
    if path is None:
        return []
    rel = path.relative_to(ROOT).as_posix()
    return [f"![{path.name}](../{rel})", ""]


def _line_by_engine(ax, frame: pd.DataFrame, y: str, xlabel: str, ylabel: str, title: str, hline=None, hlabel=None) -> None:
    for engine, g in frame.groupby("engine"):
        g = g.sort_values("n")
        ax.plot(
            g["n"],
            g[y],
            marker="o",
            color=_color(engine),
            linewidth=2.0,
            markersize=7,
            label=engine,
        )
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_xscale("log")
    ax.set_xticks([10_000, 50_000, 100_000, 250_000, 500_000])
    ax.set_xticklabels(["10K", "50K", "100K", "250K", "500K"])
    ax.legend()
    if hline is not None:
        ax.axhline(hline, linestyle="--", linewidth=1.0, color="#666666")
        if hlabel:
            ax.text(frame["n"].min(), hline + 0.8, hlabel, color="#555555", fontsize=8)


def _plot_p95_vs_n(df: pd.DataFrame) -> Path | None:
    sub = _e1_iso(df)
    if sub.empty:
        return None
    med = sub.groupby(["engine", "n"], as_index=False)["p95_ms"].median()
    fig, ax = plt.subplots(figsize=(8, 4.6))
    _line_by_engine(
        ax,
        med,
        "p95_ms",
        "N vectors",
        "p95 latency (ms)",
        "E1 iso-config (median of 3 trials): p95 vs N",
        50,
        "interactive p95 = 50 ms",
    )
    return _save(fig, "e1_p95_vs_n.png")


def _plot_p99_vs_n(df: pd.DataFrame) -> Path | None:
    sub = _e1_iso(df)
    if sub.empty or sub["p99_ms"].isna().all():
        return None
    med = sub.groupby(["engine", "n"], as_index=False)["p99_ms"].median()
    fig, ax = plt.subplots(figsize=(8, 4.6))
    _line_by_engine(
        ax, med, "p99_ms", "N vectors", "p99 latency (ms)", "E1 iso-config: p99 vs N", 100, "p99 = 100 ms"
    )
    return _save(fig, "e1_p99_vs_n.png")


def _plot_qps_vs_n(df: pd.DataFrame) -> Path | None:
    sub = _e1_iso(df)
    if sub.empty or sub["qps"].isna().all():
        return None
    med = sub.groupby(["engine", "n"], as_index=False)["qps"].median()
    fig, ax = plt.subplots(figsize=(8, 4.6))
    _line_by_engine(ax, med, "qps", "N vectors", "QPS", "E1 iso-config: QPS vs N")
    return _save(fig, "e1_qps_vs_n.png")


def _plot_recall_vs_n(df: pd.DataFrame) -> Path | None:
    sub = _e1_iso(df)
    if sub.empty or sub["recall_at_10"].isna().all():
        return None
    med = sub.groupby(["engine", "n"], as_index=False)["recall_at_10"].median()
    fig, ax = plt.subplots(figsize=(8, 4.6))
    _line_by_engine(
        ax, med, "recall_at_10", "N vectors", "Recall@10", "E1 iso-config: Recall@10 vs N", 0.95
    )
    ax.set_ylim(0.90, 1.005)
    return _save(fig, "e1_recall_vs_n.png")


def _plot_p95_ratio_vs_n(df: pd.DataFrame) -> Path | None:
    sub = _e1_iso(df)
    if sub.empty:
        return None
    med = sub.groupby(["engine", "n"], as_index=False)["p95_ms"].median()
    wide = med.pivot(index="n", columns="engine", values="p95_ms")
    if "mongo" not in wide.columns or "qdrant" not in wide.columns:
        return None
    wide = wide.dropna()
    if wide.empty:
        return None
    ratio = (wide["qdrant"] / wide["mongo"]).reset_index(name="ratio")
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ax.plot(ratio["n"], ratio["ratio"], marker="o", color="#5B4B8A", linewidth=2.0, markersize=7)
    ax.axhline(1.0, linestyle="--", linewidth=1.0, color="#666666")
    ax.text(ratio["n"].min(), 1.04, "parity", color="#555555", fontsize=8)
    ax.set_xscale("log")
    ax.set_xticks([10_000, 50_000, 100_000, 250_000, 500_000])
    ax.set_xticklabels(["10K", "50K", "100K", "250K", "500K"])
    ax.set_xlabel("N vectors")
    ax.set_ylabel("p95(qdrant) / p95(mongo)")
    ax.set_title("E1 iso-config: p95 ratio vs N  (<1 means Qdrant faster)")
    return _save(fig, "e1_p95_ratio_vs_n.png")


def _plot_pareto(df: pd.DataFrame) -> Path | None:
    sub = _valid(df)
    sub = sub[sub["label"] == "e1_iso_recall_sweep"]
    if sub.empty:
        return None
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for (engine, n), g in sub.groupby(["engine", "n"]):
        g = g.sort_values("p95_ms")
        ax.plot(
            g["p95_ms"],
            g["recall_at_10"],
            marker="o",
            color=_color(engine),
            linestyle=N_STYLE.get(int(n), "-"),
            linewidth=1.8,
            label=f"{engine} {_n_label(n)}",
        )
    ax.set_xlabel("p95 latency (ms)")
    ax.set_ylabel("Recall@10")
    ax.set_title("Iso-recall sweep: Recall@10 vs p95")
    ax.axhline(0.95, linestyle="--", linewidth=1.0, color="#666666")
    ax.set_ylim(0.94, 1.002)
    ax.legend(ncols=2, fontsize=8)
    return _save(fig, "e1_pareto_recall_p95.png")


def _plot_iso_recall_ef(df: pd.DataFrame) -> Path | None:
    sub = _valid(df)
    sub = sub[sub["label"] == "e1_iso_recall_sweep"]
    if sub.empty:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    for ax, y, title in (
        (axes[0], "p95_ms", "p95 vs search width"),
        (axes[1], "recall_at_10", "Recall@10 vs search width"),
    ):
        for (engine, n), g in sub.groupby(["engine", "n"]):
            g = g.sort_values("ef")
            ax.plot(
                g["ef"],
                g[y],
                marker="o",
                color=_color(engine),
                linestyle=N_STYLE.get(int(n), "-"),
                linewidth=1.8,
                label=f"{engine} {_n_label(n)}",
            )
        ax.set_xlabel("ef / numCandidates")
        ax.set_ylabel("p95 (ms)" if y == "p95_ms" else "Recall@10")
        ax.set_title(title)
        ax.set_xticks([32, 64, 128, 256])
        ax.legend(fontsize=8)
    axes[1].axhline(0.95, linestyle="--", linewidth=1.0, color="#666666")
    axes[1].set_ylim(0.94, 1.002)
    return _save(fig, "e1_iso_recall_vs_ef.png")


def _plot_rss(df: pd.DataFrame) -> Path | None:
    sub = _e1_iso(df)
    sub = sub[sub["rss_mb"].notna() & (sub["rss_mb"] > 0)]
    if sub.empty:
        return None
    med = sub.groupby(["engine", "n"], as_index=False)["rss_mb"].median()
    fig, ax = plt.subplots(figsize=(8, 4.6))
    _line_by_engine(ax, med, "rss_mb", "N vectors", "Container RSS (MB)", "E6: Docker RSS vs N")
    return _save(fig, "e6_rss_vs_n.png")


def _plot_filter(df: pd.DataFrame) -> Path | None:
    sub = _valid(df)
    sub = sub[(sub["experiment"] == "E3") & (sub["concurrency"] == 1)].copy()
    if sub.empty:
        return None
    sub["sel"] = pd.to_numeric(sub["selectivity"], errors="coerce")
    sub = sub.dropna(subset=["sel", "p95_ms"])
    if sub.empty:
        return None
    # Protocol primary cell is 500K; keep 100K as a dashed comparison.
    sub = sub[sub["n"].isin(PROTOCOL_N)]
    if sub.empty:
        return None
    fig, ax = plt.subplots(figsize=(8, 4.6))
    for (engine, n), g in sub.groupby(["engine", "n"]):
        g = g.sort_values("sel")
        ax.plot(
            g["sel"],
            g["p95_ms"],
            marker="o",
            color=_color(engine),
            linestyle=N_STYLE.get(int(n), "-"),
            linewidth=1.8,
            label=f"{engine} {_n_label(n)}",
        )
    ax.axhline(50, linestyle="--", linewidth=1.0, color="#666666")
    ax.set_xlabel("Selectivity (%)")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_title("E3 filtered ANN, concurrency=1 (protocol N)")
    ax.set_xticks([1, 10, 50, 100])
    ax.legend()
    return _save(fig, "e3_filter_p95.png")


def _plot_concurrency_p95(df: pd.DataFrame) -> Path | None:
    sub = _valid(df)
    sub = sub[sub["experiment"] == "E2"]
    if sub.empty:
        return None
    sub = sub[sub["n"].isin(PROTOCOL_N | {250_000})]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    for (engine, n), g in sub.groupby(["engine", "n"]):
        g = g.sort_values("concurrency")
        ax.plot(
            g["concurrency"],
            g["p95_ms"],
            marker="o",
            color=_color(engine),
            linestyle=N_STYLE.get(int(n), "-"),
            linewidth=1.8,
            label=f"{engine} {_n_label(n)}",
        )
    ax.axhline(50, linestyle="--", linewidth=1.0, color="#666666")
    ax.text(1.05, 51.2, "interactive p95 = 50 ms", color="#555555", fontsize=8)
    ax.set_xlabel("Closed-loop clients")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_title("E2: p95 vs concurrency")
    ax.set_xticks([1, 4, 8])
    ax.legend(ncols=2, fontsize=8)
    return _save(fig, "e2_p95_vs_concurrency.png")


def _plot_concurrency_qps(df: pd.DataFrame) -> Path | None:
    sub = _valid(df)
    sub = sub[sub["experiment"] == "E2"]
    if sub.empty:
        return None
    sub = sub[sub["n"].isin(PROTOCOL_N | {250_000})]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    for (engine, n), g in sub.groupby(["engine", "n"]):
        g = g.sort_values("concurrency")
        ax.plot(
            g["concurrency"],
            g["qps"],
            marker="o",
            color=_color(engine),
            linestyle=N_STYLE.get(int(n), "-"),
            linewidth=1.8,
            label=f"{engine} {_n_label(n)}",
        )
    ax.set_xlabel("Closed-loop clients")
    ax.set_ylabel("QPS")
    ax.set_title("E2: QPS vs concurrency")
    ax.set_xticks([1, 4, 8])
    ax.legend(ncols=2, fontsize=8)
    return _save(fig, "e2_qps_vs_concurrency.png")


def _plot_ingest(df: pd.DataFrame) -> Path | None:
    sub = df[df["experiment"] == "E4"].copy()
    sub = sub[sub["time_to_searchable_s"].notna() & (sub["time_to_searchable_s"] < 600)]
    if sub.empty:
        return None
    med = sub.groupby(["engine", "n"], as_index=False)["time_to_searchable_s"].median()
    fig, ax = plt.subplots(figsize=(8, 4.6))
    _line_by_engine(
        ax, med, "time_to_searchable_s", "N vectors", "Time to searchable (s)", "E4: time-to-searchable vs N"
    )
    return _save(fig, "e4_ingest_vs_n.png")


def _plot_cold(df: pd.DataFrame) -> Path | None:
    e5 = df[df["experiment"] == "E5"].copy()
    e5 = e5[e5["p95_ms"].notna()]
    if e5.empty:
        return None
    fig, ax = plt.subplots(figsize=(8, 4.6))
    for engine, g in e5.groupby("engine"):
        g = g.sort_values("n")
        ax.plot(
            g["n"],
            g["p95_ms"],
            marker="o",
            color=_color(engine),
            linewidth=2.0,
            markersize=7,
            label=f"{engine} cold",
        )
    ax.axhline(50, linestyle="--", linewidth=1.0, color="#666666")
    ax.set_xscale("log")
    ax.set_xticks([10_000, 100_000, 250_000, 500_000])
    ax.set_xticklabels(["10K", "100K", "250K", "500K"])
    ax.set_xlabel("N vectors")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_title("E5: cold start p95 (first 50 queries, no warmup)")
    ax.legend()
    return _save(fig, "e5_cold_p95.png")


def _iso_recall_operating(df: pd.DataFrame) -> pd.DataFrame:
    """Smallest ef with Recall@10 ≥ 0.95 at each engine × N (decision-grade)."""
    sub = _valid(df)
    sub = sub[sub["label"] == "e1_iso_recall_sweep"].copy()
    if sub.empty:
        return sub
    rows = []
    for (engine, n), g in sub.groupby(["engine", "n"]):
        ok = g[g["recall_at_10"] >= 0.95].sort_values("ef")
        if ok.empty:
            continue
        pick = ok.iloc[0]
        rows.append(
            {
                "engine": engine,
                "n": n,
                "ef": pick["ef"],
                "p95_ms": pick["p95_ms"],
                "qps": pick["qps"],
                "recall_at_10": pick["recall_at_10"],
            }
        )
    return pd.DataFrame(rows)


def _plot_iso_recall_p95_vs_n(df: pd.DataFrame) -> Path | None:
    op = _iso_recall_operating(df)
    if op.empty:
        return None
    fig, ax = plt.subplots(figsize=(8, 4.6))
    _line_by_engine(
        ax,
        op,
        "p95_ms",
        "N vectors",
        "p95 latency (ms)",
        "Iso-recall operating point: p95 vs N (smallest ef with Recall@10 ≥ 0.95)",
        50,
        "interactive p95 = 50 ms",
    )
    return _save(fig, "e1_iso_recall_p95_vs_n.png")


def _plot_p95_config_vs_recall(df: pd.DataFrame) -> Path | None:
    iso = _e1_iso(df)
    op = _iso_recall_operating(df)
    if iso.empty or op.empty:
        return None
    med = iso.groupby(["engine", "n"], as_index=False)["p95_ms"].median()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    _line_by_engine(
        axes[0],
        med,
        "p95_ms",
        "N vectors",
        "p95 latency (ms)",
        "Iso-config median (3 trials)",
        50,
        "50 ms",
    )
    _line_by_engine(
        axes[1],
        op,
        "p95_ms",
        "N vectors",
        "p95 latency (ms)",
        "Iso-recall operating point",
        50,
        "50 ms",
    )
    fig.suptitle("Why the 500K Mongo spike is not the decision number", y=1.02, fontsize=12)
    return _save(fig, "e1_p95_iso_config_vs_iso_recall.png")


def _all_plots(df: pd.DataFrame) -> dict[str, Path]:
    makers = [
        ("e1_p95_vs_n", _plot_p95_vs_n),
        ("e1_iso_recall_p95_vs_n", _plot_iso_recall_p95_vs_n),
        ("e1_p95_iso_config_vs_iso_recall", _plot_p95_config_vs_recall),
        ("e1_p99_vs_n", _plot_p99_vs_n),
        ("e1_qps_vs_n", _plot_qps_vs_n),
        ("e1_recall_vs_n", _plot_recall_vs_n),
        ("e1_p95_ratio_vs_n", _plot_p95_ratio_vs_n),
        ("e1_pareto_recall_p95", _plot_pareto),
        ("e1_iso_recall_vs_ef", _plot_iso_recall_ef),
        ("e2_p95_vs_concurrency", _plot_concurrency_p95),
        ("e2_qps_vs_concurrency", _plot_concurrency_qps),
        ("e3_filter_p95", _plot_filter),
        ("e4_ingest_vs_n", _plot_ingest),
        ("e5_cold_p95", _plot_cold),
        ("e6_rss_vs_n", _plot_rss),
    ]
    out: dict[str, Path] = {}
    for name, fn in makers:
        path = fn(df)
        if path is not None:
            out[name] = path
    return out


def _fmt(x) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def write_results_md(df: pd.DataFrame, plots: dict[str, Path]) -> Path:
    path = ROOT / "docs" / "07-results.md"
    lines = [
        "# 07 — Results (data-only)",
        "",
        "This chapter is generated from `experiments/results/*.jsonl`.",
        "It does not assume a winner. Empty sections mean the cell has not been run yet.",
        "",
        f"Rows loaded: **{len(df)}**.",
        "",
    ]
    if df.empty:
        lines += [
            "## Status",
            "",
            "No trial files were found. Run:",
            "",
            "```text",
            "python -m src.runners.study prepare --max-docs 10000",
            "scripts/one_engine.ps1 qdrant",
            "python -m src.runners.study run --engine qdrant --experiments E0,E1 --max-n 10000",
            "scripts/one_engine.ps1 mongo",
            "python -m src.runners.study run --engine mongo --experiments E0,E1 --max-n 10000",
            "python -m src.runners.study analyze",
            "```",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    engines = sorted(df["engine"].dropna().unique().tolist())
    ns = sorted(df["n"].dropna().unique().tolist())
    lines += [
        "## What was actually run",
        "",
        f"- Engines: {', '.join(engines) if engines else 'none'}",
        f"- Slice sizes present: {ns}",
        f"- Experiments: {sorted(df['experiment'].dropna().unique().tolist())}",
        "",
        "## E0 harness validation",
        "",
    ]
    e0 = df[df["experiment"] == "E0"]
    if e0.empty:
        lines.append("Not run.")
    else:
        # Drop known harness-alignment failures (Recall@10 near 0).
        e0_ok = e0[e0["recall_at_10"].fillna(0) >= 0.5]
        lines.append("| engine | Recall@10 | p95 ms | n_measured | invalid |")
        lines.append("|---|---:|---:|---:|---|")
        for _, r in e0_ok.iterrows():
            lines.append(
                f"| {r['engine']} | {_fmt(r['recall_at_10'])} | {_fmt(r['p95_ms'])} | "
                f"{_fmt(r['n_measured'])} | {r.get('invalid')} |"
            )
        dropped = len(e0) - len(e0_ok)
        if dropped:
            lines.append("")
            lines.append(
                f"{dropped} E0 row(s) omitted because Recall@10 < 0.5 "
                f"(query-order alignment bug on an early Qdrant trial)."
            )
        lines.append("")

    lines += ["## E1 scale ladder (iso-config, median p95)", "", ]
    e1 = _valid(df)
    e1 = e1[(e1["experiment"] == "E1") & (e1["label"] == "e1_iso_config")]
    if e1.empty:
        lines.append("Not run.")
    else:
        med = e1.groupby(["engine", "n"], as_index=False).agg(
            p50=("p50_ms", "median"),
            p95=("p95_ms", "median"),
            p99=("p99_ms", "median"),
            qps=("qps", "median"),
            recall=("recall_at_10", "median"),
            rss=("rss_mb", "median"),
        )
        lines.append("| engine | N | p50 ms | p95 ms | p99 ms | QPS | Recall@10 | RSS MB |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for _, r in med.sort_values(["n", "engine"]).iterrows():
            lines.append(
                f"| {r['engine']} | {int(r['n'])} | {_fmt(r['p50'])} | {_fmt(r['p95'])} | "
                f"{_fmt(r['p99'])} | {_fmt(r['qps'])} | {_fmt(r['recall'])} | {_fmt(r['rss'])} |"
            )
        lines.append("")

        # Protocol questions, answered only from observed rows.
        lines += ["### Protocol questions (observed, not hypothesized)", ""]
        for engine in engines:
            g = med[med["engine"] == engine].sort_values("n")
            qualifying = g[(g["p95"] < 50) & (g["recall"] >= 0.95)]
            if qualifying.empty:
                lines.append(
                    f"- {engine}: no observed N in this dataset meets p95 < 50 ms "
                    f"and Recall@10 ≥ 0.95 simultaneously."
                )
            else:
                lines.append(
                    f"- {engine}: largest observed N meeting p95 < 50 ms and "
                    f"Recall@10 ≥ 0.95 is **{int(qualifying['n'].max())}**."
                )
        if set(engines) >= {"mongo", "qdrant"}:
            for n in sorted(med["n"].unique()):
                pair = med[med["n"] == n]
                if set(pair["engine"]) >= {"mongo", "qdrant"}:
                    m = pair[pair["engine"] == "mongo"].iloc[0]
                    q = pair[pair["engine"] == "qdrant"].iloc[0]
                    if pd.notna(m["p95"]) and pd.notna(q["p95"]) and m["p95"] > 0:
                        ratio = q["p95"] / m["p95"]
                        lines.append(
                            f"- At N={int(n)} iso-config, p95(qdrant)/p95(mongo) = {ratio:.3f}."
                        )
        lines.append("")
        for key in (
            "e1_p95_vs_n",
            "e1_iso_recall_p95_vs_n",
            "e1_p95_iso_config_vs_iso_recall",
            "e1_p99_vs_n",
            "e1_qps_vs_n",
            "e1_recall_vs_n",
            "e1_p95_ratio_vs_n",
        ):
            lines += _md_plot(plots.get(key))

    lines += ["## E1 iso-recall sweep", ""]
    sw = _valid(df)
    sw = sw[sw["label"] == "e1_iso_recall_sweep"]
    if sw.empty:
        lines.append("Not run.")
    else:
        lines.append("| engine | N | ef | p95 ms | Recall@10 | QPS |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for _, r in sw.sort_values(["n", "engine", "ef"]).iterrows():
            lines.append(
                f"| {r['engine']} | {int(r['n'])} | {int(r['ef'])} | {_fmt(r['p95_ms'])} | "
                f"{_fmt(r['recall_at_10'])} | {_fmt(r['qps'])} |"
            )
        lines.append("")
        lines.append(
            "Operating point rule: smallest ef with Recall@10 ≥ 0.95. "
            "If none, the Pareto plot is the result — no winner is declared."
        )
        lines.append("")
        for (engine, n), g in sw.groupby(["engine", "n"]):
            ok = g[g["recall_at_10"] >= 0.95].sort_values("ef")
            if ok.empty:
                lines.append(
                    f"- {engine} n={int(n)}: 0.95 recall not reached in the swept ef set."
                )
            else:
                pick = ok.iloc[0]
                lines.append(
                    f"- {engine} n={int(n)}: smallest ef at ≥0.95 is **{int(pick['ef'])}** "
                    f"(p95={_fmt(pick['p95_ms'])} ms)."
                )
        lines.append("")
        for key in ("e1_pareto_recall_p95", "e1_iso_recall_vs_ef"):
            lines += _md_plot(plots.get(key))

    lines += ["## E2 concurrency", ""]
    e2 = _valid(df)
    e2 = e2[e2["experiment"] == "E2"]
    if e2.empty:
        lines.append("Not run.")
    else:
        lines.append("| engine | N | conc | p95 ms | QPS |")
        lines.append("|---|---:|---:|---:|---:|")
        for _, r in e2.sort_values(["n", "engine", "concurrency"]).iterrows():
            lines.append(
                f"| {r['engine']} | {int(r['n'])} | {int(r['concurrency'])} | "
                f"{_fmt(r['p95_ms'])} | {_fmt(r['qps'])} |"
            )
        lines.append("")
        for key in ("e2_p95_vs_concurrency", "e2_qps_vs_concurrency"):
            lines += _md_plot(plots.get(key))

    lines += ["## E3 filtered ANN", ""]
    e3 = _valid(df)
    e3 = e3[e3["experiment"] == "E3"]
    if e3.empty:
        lines.append("Not run.")
    else:
        lines.append("| engine | N | sel | conc | p95 ms | Recall@10 |")
        lines.append("|---|---:|---|---:|---:|---:|")
        for _, r in e3.sort_values(["engine", "selectivity", "concurrency"]).iterrows():
            lines.append(
                f"| {r['engine']} | {int(r['n'])} | {r['selectivity']} | "
                f"{int(r.get('concurrency') or 0)} | {_fmt(r['p95_ms'])} | {_fmt(r['recall_at_10'])} |"
            )
        lines.append("")
        lines += _md_plot(plots.get("e3_filter_p95"))

    lines += ["## E4 ingestion / time-to-searchable", ""]
    e4 = df[df["experiment"] == "E4"]
    if e4.empty:
        lines.append("Not run as a standalone cell (ingest rows may still exist).")
    else:
        lines.append("| engine | N | index_build_s | time_to_searchable_s | RSS MB |")
        lines.append("|---|---:|---:|---:|---:|")
        for _, r in e4.iterrows():
            lines.append(
                f"| {r['engine']} | {int(r['n'])} | {_fmt(r['index_build_s'])} | "
                f"{_fmt(r['time_to_searchable_s'])} | {_fmt(r['rss_mb'])} |"
            )
        lines.append("")
        lines += _md_plot(plots.get("e4_ingest_vs_n"))

    lines += ["## E5 cold start", ""]
    e5 = df[df["experiment"] == "E5"]
    if e5.empty:
        lines.append("Not run.")
    else:
        lines.append("| engine | N | p50 ms | p95 ms | n_measured |")
        lines.append("|---|---:|---:|---:|---:|")
        for _, r in e5.iterrows():
            lines.append(
                f"| {r['engine']} | {int(r['n'])} | {_fmt(r['p50_ms'])} | "
                f"{_fmt(r['p95_ms'])} | {_fmt(r['n_measured'])} |"
            )
        lines.append("")
        lines += _md_plot(plots.get("e5_cold_p95"))

    lines += ["## E6 resource envelope", ""]
    if "e6_rss_vs_n" in plots:
        lines += _md_plot(plots["e6_rss_vs_n"])
    else:
        lines.append("No RSS series with positive docker-stats samples.")
        lines.append("")

    lines += ["## Figure index", ""]
    if plots:
        for name, pth in plots.items():
            rel = pth.relative_to(ROOT).as_posix()
            lines.append(f"- `{name}`: `{rel}`")
    else:
        lines.append("No figures produced (insufficient plotted cells).")
    lines += [
        "",
        "## Interpretation constraints",
        "",
        "- Iso-config cells are not iso-quality.",
        "- Differences under 10% p95 at N≤100K are treated as operationally weak.",
        "- Missing engine or missing N is not evidence that the missing side is slower.",
        "- Community `mongot` is preview software; image IDs belong with the JSONL.",
        "- Filtered Recall@10 is scored against *unfiltered* exact neighbors, so it tracks selectivity, not index quality.",
        "- Recall@50 / Recall@100 in the CSV are not meaningful when the timed query used k=10.",
        "- Mongo 500K iso-config median p95 is dominated by the two trials immediately after ingest (mongot CPU spike). Iso-recall / later trials are the warm number.",
        "",
        "## Run notes (this apparatus)",
        "",
        f"- Observed slice sizes in JSONL: {ns if ns else 'none yet'}.",
        "- Embeddings: BGE-small 384-d, L2-normalized, frozen files reused across engines.",
        "- Host port 27018 is Docker `mongod`; a native `mongod` already occupies 27017.",
        "- RSS comes from `docker stats` CLI when the Python Docker SDK is absent.",
        "- Qdrant image v1.15.4 with client 1.19.0: compatibility check disabled.",
        "- `mongot` 1.70.4; Community `$vectorSearch` is public preview.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def analyze_all() -> Path:
    ensure_dirs()
    _style()
    df = _load_all()
    plots = _all_plots(df)
    md = write_results_md(df, plots)
    summary = RESULTS / "summary.csv"
    if not df.empty:
        df.to_csv(summary, index=False)
    print(f"wrote {md} and {len(plots)} plots: {', '.join(plots)}")
    return md


if __name__ == "__main__":
    analyze_all()
