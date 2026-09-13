from __future__ import annotations

import pandas as pd

from src.runners.analyze import _iso_recall_operating, write_results_md


def test_empty_results_do_not_name_a_winner(tmp_path, monkeypatch):
    import src.runners.analyze as analyze

    monkeypatch.setattr(analyze, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    path = write_results_md(pd.DataFrame(), {})
    text = path.read_text(encoding="utf-8")
    assert "does not assume a winner" in text
    assert "No trial files were found" in text
    assert "Qdrant wins" not in text
    assert "MongoDB wins" not in text


def test_iso_recall_operating_point_picks_smallest_ef():
    df = pd.DataFrame(
        [
            {
                "label": "e1_iso_recall_sweep",
                "engine": "mongo",
                "n": 100_000,
                "ef": 64,
                "p95_ms": 18.0,
                "qps": 70.0,
                "recall_at_10": 0.99,
                "invalid": False,
            },
            {
                "label": "e1_iso_recall_sweep",
                "engine": "mongo",
                "n": 100_000,
                "ef": 32,
                "p95_ms": 14.0,
                "qps": 80.0,
                "recall_at_10": 0.96,
                "invalid": False,
            },
        ]
    )
    op = _iso_recall_operating(df)
    assert len(op) == 1
    assert int(op.iloc[0]["ef"]) == 32
    assert float(op.iloc[0]["p95_ms"]) == 14.0


def test_missing_engine_is_not_filled_in():
    df = pd.DataFrame(
        [
            {
                "label": "e1_iso_recall_sweep",
                "engine": "qdrant",
                "n": 500_000,
                "ef": 32,
                "p95_ms": 31.0,
                "qps": 70.0,
                "recall_at_10": 0.99,
                "invalid": False,
            }
        ]
    )
    op = _iso_recall_operating(df)
    assert set(op["engine"]) == {"qdrant"}
    assert "mongo" not in set(op["engine"])
