"""Vector embedding store for CTF writeup search using ChromaDB."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Persist directory for ChromaDB
_CHROMA_DIR = Path(__file__).parent / "chroma_db"


class EmbeddingStore:
    """ChromaDB-backed vector store for CTF writeup entries.

    Uses sentence-transformers all-MiniLM-L6-v2 for local embeddings.
    Gracefully degrades if chromadb or sentence-transformers not installed.
    """

    def __init__(self, persist_dir: Path | None = None):
        self._persist_dir = persist_dir or _CHROMA_DIR
        self._collection = None
        self._available = False
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            self._client = chromadb.PersistentClient(path=str(self._persist_dir))
            self._collection = self._client.get_or_create_collection(
                name="ctf_writeups",
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )
            self._available = True
        except Exception as e:
            logger.debug("EmbeddingStore unavailable: %s", e)

    def available(self) -> bool:
        return self._available

    def index_entry(self, entry: dict[str, Any]) -> None:
        if not self._available:
            return
        doc_id = self._entry_id(entry)
        document = self._entry_to_document(entry)
        metadata = {
            "category": entry.get("category", "misc"),
            "success": str(entry.get("success", False)),
        }
        try:
            self._collection.upsert(
                ids=[doc_id],
                documents=[document],
                metadatas=[metadata],
            )
        except Exception as e:
            logger.debug("Failed to index entry: %s", e)

    def search_similar(
        self, query: str, category: str | None = None, limit: int = 3
    ) -> list[dict[str, Any]]:
        if not self._available or self._collection is None:
            return []
        where = {"success": "True"}
        if category:
            where = {"$and": [{"success": "True"}, {"category": category}]}
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=limit,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            entries = []
            for i, doc in enumerate(results["documents"][0]):
                entries.append({
                    "document": doc,
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                })
            return entries
        except Exception as e:
            logger.debug("Embedding search failed: %s", e)
            return []

    def reindex_all(self, entries: list[dict[str, Any]]) -> int:
        if not self._available:
            logger.warning("ChromaDB not available — cannot reindex")
            return 0
        count = 0
        for entry in entries:
            self.index_entry(entry)
            count += 1
        logger.info("Reindexed %d entries", count)
        return count

    @staticmethod
    def _entry_id(entry: dict[str, Any]) -> str:
        name = entry.get("challenge", "unknown")
        cat = entry.get("category", "misc")
        return f"{cat}_{name}".replace(" ", "_").lower()[:128]

    @staticmethod
    def _entry_to_document(entry: dict[str, Any]) -> str:
        parts = [
            entry.get("challenge", ""),
            entry.get("category", ""),
        ]
        techniques = entry.get("techniques", [])
        if techniques:
            parts.append(f"techniques: {', '.join(techniques)}")
        tools = entry.get("tools_used", [])
        if tools:
            parts.append(f"tools: {', '.join(tools)}")
        commands = entry.get("commands", [])
        if commands:
            parts.append(f"commands: {' | '.join(commands[:5])}")
        return " ".join(parts)
