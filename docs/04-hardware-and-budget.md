# 04 — Experimental Apparatus and Memory Budget

Every size, concurrency, and “practical \(N\)” claim in this study is derived from one inventoried machine, not from a generic “16 GB laptop” stereotype.

Inventory date: 12 September 2026.

---

## 1. Hardware

| Item | Measurement |
|---|---|
| System | Dell Inspiron 14 Plus 7440 |
| OS | Windows 11 Home Single Language, build 26200, 64-bit |
| CPU | Intel Core Ultra 7 155H (Meteor Lake, Family 6 Model 170 Stepping 4) |
| Cores / threads | 16 cores / 22 threads (P-cores + E-cores + low-power E-cores) |
| Caches | 18 MB L2, 24 MB L3 |
| Reported max clock | 3800 MHz |
| RAM | 16,597,598,208 bytes physical (~15.46 GiB visible) |
| DRAM | LPDDR5-7500, eight 2 GB ranks, **soldered, not expandable** |
| Pagefile | `D:\pagefile.sys`, 34,816 MB allocated |
| Disk | SK hynix PVC10 1024 GB NVMe |
| Free space at inventory | `C:` ~137 GB, `D:` ~172 GB |
| iGPU | Intel Arc Graphics, driver 32.0.101.8509; AdapterRAM ~2 GB |
| NPU | Intel AI Boost `PCI VEN_8086 DEV_7D1D`, driver 32.0.100.4724, status OK |
| Hypervisor | Present (Docker Desktop / WSL2) |
| Docker | 29.6.2 installed; engine was **not running** at inventory |
| WSL2 | Ubuntu (default, stopped), docker-desktop (stopped) |
| Python | 3.10.11 (`C:\Users\Interloop12\AppData\Local\Programs\Python\Python310`) |
| Node | v20.20.0 (unused in Phase 1) |
| Native `mongod` | Not installed |

At inventory, **~2.3 GiB RAM was free**. Windows 11 idle typically holds 4–6 GiB. That is the binding constraint.

### Shared-memory accelerators

The user-facing “8 GB Intel GPU” and “8 GB NPU” figures are **not discrete VRAM**. They are slices of the same 16 GB system memory. They cannot be added to Qdrant or `mongot` budgets. The NPU (Intel AI Boost) is out of scope for the core database study. Embeddings are generated once on CPU.

### Heterogeneous CPU

Docker and HNSW build do not run on 16 identical cores. P-cores, E-cores, and LP-E-cores have different frequencies and SIMD behavior. High-concurrency cells are noisier than they would be on a Xeon with a uniform uncore. This is reported qualitatively; we do not pin containers to P-cores in Phase 1 (pinning would be a different experiment).

---

## 2. What is not the limiter

Disk is not the limiter. 1 TB NVMe with >170 GB free on `D:` holds 1M × 384-d float32 (~1.5 GB), payloads, two engine volumes (not simultaneously hot), and result artifacts.

The pagefile **is** a threat. If a timed window incurs hard page faults, latency is fiction. `scripts/check_host.py` aborts when commit charge or pagefile usage indicates swap activity. Trials that trip this mid-run are discarded.

---

## 3. RAM budget (proposed operating envelope)

| Consumer | Allocation |
|---|---|
| Windows 11 + desktop + harness | ~5–6 GiB |
| Docker Desktop WSL2 VM cap | **10 GiB RAM, 16 CPUs** (leave headroom) |
| One engine inside that VM | whatever remains after containerd / VPN |
| The other engine | **down** |

Rules:

1. MongoDB (`mongod` + `mongot`) and Qdrant never share the box during a timed run.
2. Project data and Docker bind mounts live on `D:`.
3. Close browsers and other Docker stacks before a run. `check_host.py` snapshots processes.
4. 5 million float32 384-d vectors are **not** a primary condition (~7.7 GB raw vectors before indexes and OS).

---

## 4. Practical \(N\) at 384-d, one engine

| \(N\) | Raw vectors | + HNSW \(M=16\) | Verdict on this machine |
|---:|---:|---:|---|
| 10,000 | 15 MB | ~17 MB | Trivial. Harness / exact-vs-ANN check. |
| 50,000 | 77 MB | ~84 MB | Comfortable. |
| 100,000 | 154 MB | ~169 MB | Comfortable. Likely both “good enough.” |
| 250,000 | 384 MB | ~422 MB | First place two-process overhead may show. |
| 500,000 | 768 MB | ~843 MB | Comfortable **one engine at a time**. |
| 1,000,000 | 1.54 GB | ~1.69 GB | Feasible, tight. **Primary ceiling.** |
| 2,000,000 | 3.07 GB | ~3.4 GB | Appendix only (quantize / on-disk). Discard if swapping. |
| 5,000,000 | 7.68 GB | ~8.4 GB | Not primary. Would fight Windows + Docker. |

Plus: full-text payload, WiredTiger cache, `mongot` heap, Python harness, Docker VM overhead. The 1M cell is the first that can honestly stress 16 GB.

---

## 5. Host guardrails

`scripts/check_host.py` must pass before every trial:

- Docker engine reachable
- Exactly one study profile up (`mongo` xor `qdrant`), never both
- Host available RAM above a floor (default 2.0 GiB)
- Pagefile current usage not rising through a configured threshold during the probe
- Optional: CPU steal / Defender full-scan heuristics

`scripts/one_engine.ps1` brings one Compose profile up and the other down.

Docker Desktop memory should be capped at 10 GB in the Docker Desktop UI (WSL2 `memory=` in `.wslconfig` is documented in `README.md`). The harness cannot reliably set that cap from inside a container; the operator must apply it once.
