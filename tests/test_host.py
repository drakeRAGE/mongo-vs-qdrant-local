from __future__ import annotations

from src.host import _parse_mem, evaluate_host


def _snap(**overrides):
    base = {
        "docker_ok": True,
        "mongo_up": False,
        "qdrant_up": False,
        "free_ram_gb": 4.0,
        "swap_percent": 0.0,
        "cpu_percent": 10.0,
    }
    base.update(overrides)
    return base


def test_dual_engine_is_hard_abort():
    decision = evaluate_host(_snap(mongo_up=True, qdrant_up=True), expect="mongo", min_free_gb=1.0)
    assert decision["host_ok"] is False
    assert "both_engines_up" in decision["reason"]


def test_swap_fifty_percent_aborts():
    decision = evaluate_host(_snap(swap_percent=50), expect="none", min_free_gb=2.0)
    assert decision["host_ok"] is False
    assert "swap_active" in decision["reason"]


def test_low_ram_is_warning_when_engine_already_up():
    decision = evaluate_host(
        _snap(qdrant_up=True, free_ram_gb=0.4),
        expect="qdrant",
        min_free_gb=1.0,
    )
    assert decision["host_ok"] is True
    assert any("free_ram" in w for w in decision["warnings"])


def test_low_ram_aborts_when_no_engine_expected():
    decision = evaluate_host(_snap(free_ram_gb=0.4), expect="none", min_free_gb=2.0)
    assert decision["host_ok"] is False


def test_parse_docker_stats_mem():
    assert _parse_mem("1.5GiB") == 1.5 * 1024.0
    assert _parse_mem("512MiB") == 512.0
    assert _parse_mem("256.0KiB") == 256.0 / 1024.0
