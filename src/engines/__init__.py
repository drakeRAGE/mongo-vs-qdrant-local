from src.engines.base import EngineAdapter, SearchHit
from src.engines.mongodb import MongoEngine
from src.engines.qdrant_engine import QdrantEngine

__all__ = ["EngineAdapter", "SearchHit", "MongoEngine", "QdrantEngine"]


def get_engine(name: str) -> EngineAdapter:
    if name == "mongo":
        return MongoEngine()
    if name == "qdrant":
        return QdrantEngine()
    raise ValueError(f"unknown engine {name}")
