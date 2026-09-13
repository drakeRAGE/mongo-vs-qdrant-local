from __future__ import annotations

import subprocess
from typing import Any

import psutil

from src.config import MONGO_CONTAINERS, QDRANT_CONTAINERS


def _running_names() -> set[str]:
    try:
        import docker

        client = docker.from_env()
        return {c.name for c in client.containers.list() if c.status == "running"}
    except Exception:
        try:
            out = subprocess.check_output(
                ["docker", "ps", "--format", "{{.Names}}"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return {line.strip() for line in out.splitlines() if line.strip()}
        except Exception:
            return set()


def _docker_reachable() -> bool:
    try:
        subprocess.check_output(
            ["docker", "info"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        return True
    except Exception:
        return False


def _image_ids(names: tuple[str, ...]) -> dict[str, str]:
    ids: dict[str, str] = {}
    try:
        import docker

        client = docker.from_env()
        for name in names:
            try:
                c = client.containers.get(name)
                ids[name] = c.image.id
            except Exception:
                continue
    except Exception:
        return ids
    return ids


def collect_host_snapshot() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    running = _running_names()
    mongo_up = any(n in running for n in MONGO_CONTAINERS)
    qdrant_up = any(n in running for n in QDRANT_CONTAINERS)
    swap = psutil.swap_memory()
    # Windows: psutil.swap_memory().used is pagefile-ish committed usage.
    pagefile_mb = int(swap.used / (1024 * 1024))
    pagefile_peak_mb = int(getattr(swap, "sin", 0) / (1024 * 1024))
    cpu = psutil.cpu_percent(interval=0.3)
    procs = []
    for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
        try:
            info = p.info
            rss = info.get("memory_info")
            procs.append(
                {
                    "name": info.get("name"),
                    "cpu": info.get("cpu_percent"),
                    "rss_mb": round((rss.rss / (1024 * 1024)) if rss else 0, 1),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    top = sorted(procs, key=lambda x: x["rss_mb"], reverse=True)[:12]
    return {
        "docker_ok": _docker_reachable(),
        "free_ram_gb": vm.available / (1024**3),
        "used_ram_gb": vm.used / (1024**3),
        "total_ram_gb": vm.total / (1024**3),
        "ram_percent": vm.percent,
        "pagefile_mb": pagefile_mb,
        "pagefile_peak_mb": pagefile_peak_mb,
        "swap_percent": swap.percent,
        "cpu_percent": cpu,
        "mongo_up": mongo_up,
        "qdrant_up": qdrant_up,
        "running_study_containers": sorted(
            n for n in running if n.startswith("vectordb-")
        ),
        "mongo_images": _image_ids(MONGO_CONTAINERS),
        "qdrant_images": _image_ids(QDRANT_CONTAINERS),
        "top_rss": top,
    }


def evaluate_host(
    snap: dict[str, Any],
    expect: str = "none",
    min_free_gb: float = 2.0,
) -> dict[str, Any]:
    warnings: list[str] = []
    reasons: list[str] = []

    if not snap["docker_ok"]:
        reasons.append("docker_engine_unreachable")
    if snap["mongo_up"] and snap["qdrant_up"]:
        reasons.append("both_engines_up")
    if expect == "mongo" and not snap["mongo_up"]:
        reasons.append("mongo_not_running")
    if expect == "qdrant" and not snap["qdrant_up"]:
        reasons.append("qdrant_not_running")
    if expect == "none" and (snap["mongo_up"] or snap["qdrant_up"]):
        warnings.append("an_engine_is_running")
    if expect == "mongo" and snap["qdrant_up"]:
        reasons.append("qdrant_still_up")
    if expect == "qdrant" and snap["mongo_up"]:
        reasons.append("mongo_still_up")
    if snap["free_ram_gb"] < min_free_gb:
        if expect in {"mongo", "qdrant"}:
            warnings.append(f"free_ram_below_{min_free_gb}gb")
        else:
            reasons.append(f"free_ram_below_{min_free_gb}gb")
    if snap["swap_percent"] >= 50:
        reasons.append("swap_active")
    elif snap["swap_percent"] >= 25:
        warnings.append("swap_elevated")
    if snap["cpu_percent"] >= 90:
        warnings.append("cpu_saturated_before_trial")

    return {
        "host_ok": not reasons,
        "reason": ";".join(reasons) if reasons else "ok",
        "warnings": warnings,
        "both_engines_up": bool(snap["mongo_up"] and snap["qdrant_up"]),
        "swap_active": snap["swap_percent"] >= 40,
    }


def _parse_mem(text: str) -> float:
    text = text.strip().upper().replace("I", "")
    num = "".join(ch for ch in text if ch.isdigit() or ch == ".")
    if not num:
        return 0.0
    val = float(num)
    if "G" in text:
        return val * 1024.0
    if "K" in text:
        return val / 1024.0
    return val


def docker_stats(names: tuple[str, ...]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    try:
        out = subprocess.check_output(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            name, mem, cpu = parts[0], parts[1], parts[2]
            if name not in names:
                continue
            used = mem.split("/")[0].strip()
            stats[name] = {
                "rss_mb": round(_parse_mem(used), 1),
                "cpu_percent": float(cpu.strip().replace("%", "") or 0.0),
                "status": "running",
            }
    except Exception as exc:  # noqa: BLE001
        stats["_error"] = str(exc)
    return stats
