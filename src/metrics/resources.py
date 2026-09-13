from __future__ import annotations

from typing import Any

from src.config import MONGO_CONTAINERS, QDRANT_CONTAINERS
from src.host import docker_stats


def engine_stats(engine: str) -> dict[str, Any]:
    names = MONGO_CONTAINERS if engine == "mongo" else QDRANT_CONTAINERS
    raw = docker_stats(names)
    rss = 0.0
    cpu = 0.0
    for _name, st in raw.items():
        if isinstance(st, dict) and "rss_mb" in st:
            rss += float(st["rss_mb"])
            cpu += float(st.get("cpu_percent") or 0.0)
    return {"containers": raw, "rss_mb": rss, "cpu_percent": cpu}
