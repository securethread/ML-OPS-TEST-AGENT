"""
Tiny but real RAG retriever for the NovaBank lab.

This is genuine retrieval: documents are tokenized, embedded as TF-IDF
vectors, and ranked by cosine similarity against the query. It is pure
Python so the lab runs fully offline with zero model downloads. Swap in
sentence-transformers / chromadb by reimplementing `Retriever` -- the agent
only depends on `.retrieve()`.

Vulnerabilities baked in here (RAG attacks):
  * NO ACCESS CONTROL / tenant isolation: every document in the corpus is
    retrievable by every user, including another customer's private record
    (rag/corpus/_crosstenant_vip.md) and an attacker-planted document
    (rag/corpus/_poisoned_support_macro.md).
  * KNOWLEDGE-BASE POISONING: retrieved text is concatenated straight into
    the prompt, so instructions hidden in a document become instructions to
    the agent (indirect prompt injection).
  * The corpus directory is writable -- see add_document() -- modelling an
    ingestion pipeline that accepts untrusted content.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import config

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class Document:
    doc_id: str
    source: str
    text: str
    vector: dict[str, float] = field(default_factory=dict)


class Retriever:
    def __init__(self, corpus_dir: Path | None = None) -> None:
        self.corpus_dir = Path(corpus_dir or config.RAG_CORPUS_DIR)
        self.documents: list[Document] = []
        self._idf: dict[str, float] = {}
        self.reload()

    # -- indexing ---------------------------------------------------------
    def reload(self) -> None:
        self.documents = []
        for path in sorted(self.corpus_dir.glob("*.md")):
            self.documents.append(
                Document(doc_id=path.stem, source=path.name, text=path.read_text())
            )
        self._build_index()

    def add_document(self, source: str, text: str) -> None:
        """Ingest a new document at runtime (models an untrusted-ingestion
        pipeline -- used to demo live knowledge-base poisoning)."""
        self.documents.append(Document(doc_id=source, source=source, text=text))
        self._build_index()

    def _build_index(self) -> None:
        n = len(self.documents) or 1
        df: Counter[str] = Counter()
        tokenized: list[list[str]] = []
        for doc in self.documents:
            toks = _tokenize(doc.text)
            tokenized.append(toks)
            for term in set(toks):
                df[term] += 1
        self._idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
        for doc, toks in zip(self.documents, tokenized):
            doc.vector = self._tfidf(toks)

    def _tfidf(self, toks: list[str]) -> dict[str, float]:
        if not toks:
            return {}
        tf = Counter(toks)
        total = len(toks)
        vec = {t: (c / total) * self._idf.get(t, 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    # -- retrieval --------------------------------------------------------
    def retrieve(self, query: str, k: int = 3) -> list[tuple[Document, float]]:
        """Return the top-k (document, score) pairs. No filtering of any kind
        -- this is where tenant isolation *should* happen and does not."""
        qvec = self._tfidf(_tokenize(query))
        scored: list[tuple[Document, float]] = []
        for doc in self.documents:
            score = sum(qvec.get(t, 0.0) * w for t, w in doc.vector.items())
            if score > 0:
                scored.append((doc, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def context_block(self, query: str, k: int = 3, min_score: float | None = None) -> str:
        if min_score is None:
            min_score = config.RAG_MIN_SCORE
        # Note: retrieve() applies NO access control. The floor below is plain
        # relevance hygiene, not isolation -- a topically-similar poisoned or
        # cross-tenant document still clears it and gets injected.
        hits = [(d, s) for d, s in self.retrieve(query, k) if s >= min_score]
        if not hits:
            return "(no relevant documents found)"
        parts = []
        for doc, score in hits:
            parts.append(f"[source: {doc.source} | score={score:.3f}]\n{doc.text.strip()}")
        return "\n\n---\n\n".join(parts)


_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever
