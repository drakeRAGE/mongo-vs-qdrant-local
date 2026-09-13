"""Abort a trial when the host is in an unfair or invalid state.

Exit codes:
  0  host is acceptable for the requested engine
  2  hard abort (dual engine, swap, Docker down, RAM floor)
  3  usage / unexpected error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.host import collect_host_snapshot, evaluate_host  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-flight checks for a VectorDB_Proof trial.")
    parser.add_argument(
        "--expect",
        choices=["mongo", "qdrant", "none"],
        default="none",
        help="Which compose profile should be running (xor).",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=None,
        help="Default 2.0 GB if no engine is expected, 1.0 GB if an engine is already up.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    snap = collect_host_snapshot()
    min_free = args.min_free_gb
    if min_free is None:
        min_free = 1.0 if args.expect in {"mongo", "qdrant"} else 2.0
    decision = evaluate_host(snap, expect=args.expect, min_free_gb=min_free)
    payload = {"snapshot": snap, "decision": decision}
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"host_ok={decision['host_ok']} reason={decision['reason']}")
        print(
            f"free_ram_gb={snap['free_ram_gb']:.2f} "
            f"pagefile_mb={snap['pagefile_mb']} "
            f"mongo_up={snap['mongo_up']} qdrant_up={snap['qdrant_up']}"
        )
        if decision["warnings"]:
            for w in decision["warnings"]:
                print(f"warning: {w}")
    return 0 if decision["host_ok"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"check_host error: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
