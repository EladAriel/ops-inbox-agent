"""Section index: ##/### chunks → cached embeddings → cosine top-k."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from openai import OpenAI

_HERE = Path(__file__).resolve().parent
_PKG_ROOT = _HERE.parent
DEFAULT_CACHE_PATH = _PKG_ROOT / ".scratch" / "knowledge_embeddings.json"

_HEADING = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    citation: str  # e.g. "access_tiers.md#Tier 2 — Sensitive"
    filename: str
    heading: str
    text: str
    embedding: Optional[List[float]] = field(default=None, repr=False)


def chunk_markdown(filename: str, body: str) -> List[Chunk]:
    """Split markdown body on ## and ### headers; skip empty bodies."""
    matches = list(_HEADING.finditer(body))
    chunks: List[Chunk] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        heading = m.group(2).strip()
        text = body[start:end].strip()
        if not text:
            continue
        chunks.append(
            Chunk(
                citation=f"{filename}#{heading}",
                filename=filename,
                heading=heading,
                text=text,
            )
        )
    return chunks


def _docs_hash(docs: dict[str, str]) -> str:
    """Stable content hash of the knowledge corpus for cache invalidation."""
    h = hashlib.sha256()
    for name in sorted(docs):
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update(docs[name].encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute cosine similarity between two numeric vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


class KnowledgeIndex:
    def __init__(self, chunks: List[Chunk]):
        self.chunks = chunks

    @classmethod
    def from_docs(
        cls,
        docs: dict[str, str],
        client: OpenAI,
        model: str,
        batch_size: int = 100,
    ) -> "KnowledgeIndex":
        """Process documents into chunks and generate embeddings in safe batches."""
        chunks: List[Chunk] = []
        for name, body in sorted(docs.items()):
            chunks.extend(chunk_markdown(name, body))

        if not chunks:
            return cls([])

        inputs = [f"{c.heading}\n\n{c.text}" for c in chunks]
        all_embeddings: List[List[float]] = []

        for i in range(0, len(inputs), batch_size):
            batch = inputs[i : i + batch_size]
            resp = client.embeddings.create(model=model, input=batch)
            sorted_data = sorted(resp.data, key=lambda x: x.index)
            all_embeddings.extend([list(item.embedding) for item in sorted_data])

        for c, emb in zip(chunks, all_embeddings):
            c.embedding = emb

        return cls(chunks)

    @classmethod
    def load_or_build(
        cls,
        docs: dict[str, str],
        client: OpenAI,
        model: str,
        cache_path: Optional[Path] = None,
        batch_size: int = 100,
    ) -> "KnowledgeIndex":
        """Load cached chunk embeddings when model+docs match; else embed and save."""
        path = Path(cache_path) if cache_path is not None else DEFAULT_CACHE_PATH
        expected_hash = _docs_hash(docs)

        if path.is_file():
            try:
                with path.open("r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                if (
                    payload.get("model") == model
                    and payload.get("docs_hash") == expected_hash
                    and isinstance(payload.get("chunks"), list)
                ):
                    chunks = [
                        Chunk(
                            citation=row["citation"],
                            filename=row["filename"],
                            heading=row["heading"],
                            text=row["text"],
                            embedding=row.get("embedding"),
                        )
                        for row in payload["chunks"]
                    ]
                    if chunks and all(c.embedding for c in chunks):
                        return cls(chunks)
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                pass

        index = cls.from_docs(docs, client, model, batch_size=batch_size)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": model,
            "docs_hash": expected_hash,
            "chunks": [
                {
                    "citation": c.citation,
                    "filename": c.filename,
                    "heading": c.heading,
                    "text": c.text,
                    "embedding": c.embedding,
                }
                for c in index.chunks
            ],
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
        return index

    def retrieve(
        self,
        query: str,
        client: OpenAI,
        model: str,
        *,
        top_k: int = 4,
        filename_filter: Optional[set[str]] = None,
    ) -> List[Chunk]:
        """Retrieve the top-k most relevant chunks using cosine similarity."""
        pool = [
            c
            for c in self.chunks
            if filename_filter is None or c.filename in filename_filter
        ]
        if not pool:
            return []

        q_resp = client.embeddings.create(model=model, input=[query])
        q = list(q_resp.data[0].embedding)
        scored = sorted(
            pool,
            key=lambda c: _cosine(q, c.embedding or []),
            reverse=True,
        )
        return scored[:top_k]
