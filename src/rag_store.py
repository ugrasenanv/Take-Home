from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass
class RAGChunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any]


class VectorRAGStore:
    """Simple local vector store using TF-IDF for deterministic offline retrieval."""

    def __init__(self, base_path: str = "data/vector_store") -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.base_path / "chunks.json"
        self.chunks: list[RAGChunk] = []
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
        self.matrix = None
        if self.meta_path.exists():
            raw = json.loads(self.meta_path.read_text())
            self.chunks = [RAGChunk(**item) for item in raw]
            if self.chunks:
                self.matrix = self.vectorizer.fit_transform([c.text for c in self.chunks])

    @staticmethod
    def _sanitize_text(text: str) -> str:
        cleaned = re.sub(r"ignore previous instructions|system prompt|tool override", "[redacted]", text, flags=re.I)
        return cleaned.strip()

    def _persist(self) -> None:
        self.meta_path.write_text(
            json.dumps([{"chunk_id": c.chunk_id, "text": c.text, "metadata": c.metadata} for c in self.chunks], indent=2)
        )

    def index_dataframe(self, frame: pd.DataFrame, version: str = "v1") -> int:
        new_chunks: list[RAGChunk] = []
        for idx, row in frame.iterrows():
            text = self._sanitize_text(
                f"Return {row['return_id']} | Product {row['product_name']} | Category {row['category']} | "
                f"Reason {row['reason_text']} | Refund {row['refund_status']} | Date {row['return_date']}"
            )
            metadata = {
                "return_id": row["return_id"],
                "product_name": row["product_name"],
                "category": row["category"],
                "country": row["country"],
                "version": version,
            }
            new_chunks.append(RAGChunk(chunk_id=f"{version}-{idx}", text=text, metadata=metadata))

        self.chunks = new_chunks
        self.matrix = self.vectorizer.fit_transform([c.text for c in self.chunks]) if self.chunks else None
        self._persist()
        return len(self.chunks)

    def search(self, query: str, top_k: int = 5, metadata_filter: dict[str, Any] | None = None) -> list[RAGChunk]:
        if not self.chunks or self.matrix is None:
            return []
        safe_query = self._sanitize_text(query)
        qv = self.vectorizer.transform([safe_query])
        scores = (self.matrix @ qv.T).toarray().flatten()
        order = np.argsort(scores)[::-1]

        results: list[RAGChunk] = []
        for idx in order:
            chunk = self.chunks[int(idx)]
            if metadata_filter:
                if any(chunk.metadata.get(k) != v for k, v in metadata_filter.items()):
                    continue
            results.append(chunk)
            if len(results) >= top_k:
                break
        return results
