from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
EMBED = DATA / "embeddings"
GT = DATA / "ground_truth"
MANIFESTS = DATA / "manifests"
DOCKER_DATA = DATA / "docker"
RESULTS = ROOT / "experiments" / "results"
PLOTS = ROOT / "experiments" / "plots"
CONFIGS = ROOT / "experiments" / "configs"

SEED = 20260912
MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384
NORMALIZE = True
SLICES = (10_000, 50_000, 100_000, 250_000, 500_000, 1_000_000)
PRIMARY_K = 10
GT_K = 100
N_QUERIES = 500
WARMUP = 50
MEASURED_QUERIES = 500
MIN_MEASURED = 200
BATCH_INGEST = 256
HNSW_M = 16
HNSW_EF_CONSTRUCT = 200
ISO_CONFIG_EF = 64
EF_SWEEP = (32, 64, 128, 256)
RECALL_TARGET = 0.95
QUERY_TIMEOUT_MS = 2000
TRIALS = 3
TENANTS = [f"t{i:02d}" for i in range(10)]
YEARS = list(range(2018, 2026))
CATEGORIES = [
    "health",
    "finance",
    "science",
    "legal",
    "sports",
    "tech",
    "travel",
    "education",
]

# Host 27017 is occupied by a native mongod on this machine; Docker maps 27018.
MONGO_URI = "mongodb://127.0.0.1:27018/?directConnection=true"
MONGO_DB = "vectordb"
MONGO_COLL = "passages"
MONGO_INDEX = "vector_index"
QDRANT_URL = "http://127.0.0.1:6333"
QDRANT_COLLECTION = "passages"

MONGO_CONTAINERS = ("vectordb-mongod", "vectordb-mongot", "vectordb-atlas-local")
QDRANT_CONTAINERS = ("vectordb-qdrant",)

COMPOSE_FILE = ROOT / "compose" / "docker-compose.yml"
COMPOSE_PROJECT = "vectordb-proof"


def ensure_dirs() -> None:
    for path in (RAW, EMBED, GT, MANIFESTS, DOCKER_DATA, RESULTS, PLOTS, CONFIGS):
        path.mkdir(parents=True, exist_ok=True)
    (DOCKER_DATA / "mongod").mkdir(parents=True, exist_ok=True)
    (DOCKER_DATA / "mongot").mkdir(parents=True, exist_ok=True)
    (DOCKER_DATA / "qdrant").mkdir(parents=True, exist_ok=True)
