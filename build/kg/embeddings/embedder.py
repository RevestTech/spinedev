"""Embedding pipeline for spine_kg — lazy, cached, provider-agnostic.

STORY-6.7.1 (lazy + cached) and STORY-6.7.2 (default local + org bundle
override). Vectors stored in ``spine_kg.kg_node_embedding`` (V2 schema,
``vector(768)``). DB I/O via subprocess ``psql`` (no psycopg dep).
Providers behind :class:`EmbeddingProvider` so LangChain
``MultiVectorRetriever`` can swap in later. Optional ML/SDK deps are
imported lazily inside provider ``__init__``. See ``embedder_README.md``
for dimension handling and the provider comparison table.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import subprocess
from collections import Counter
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

SCHEMA_DIMENSIONS = 768  # spine_kg.kg_node_embedding.embedding is vector(768).
_DEFAULT_LOCAL_MODEL = "all-MiniLM-L6-v2"
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# ─── Provider abstraction ─────────────────────────────────────────────


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turns text into fixed-dim float vectors."""
    model_name: str
    dimensions: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def embed_one(self, text: str) -> list[float]: ...


def _fit_dim(vec: list[float], target: int = SCHEMA_DIMENSIONS) -> list[float]:
    """Right-pad zeros or truncate so ``vec`` has exactly ``target`` dims."""
    n = len(vec)
    if n == target:
        return vec
    if n < target:
        return vec + [0.0] * (target - n)
    logger.warning("embedding_dim_truncated", extra={"got": n, "want": target})
    return vec[:target]


class LocalEmbeddingProvider:
    """Local via ``sentence-transformers`` if installed; else a deterministic
    hashed-BoW fallback so CI without ML deps still exercises the pipeline."""

    def __init__(self, model_name: str = _DEFAULT_LOCAL_MODEL) -> None:
        self.model_name, self.dimensions = model_name, SCHEMA_DIMENSIONS
        self._st: Any = None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._st = SentenceTransformer(model_name)
            logger.info("local_embedder_ready", extra={"model": model_name,
                "native_dim": int(self._st.get_sentence_embedding_dimension())})
        except Exception as exc:  # noqa: BLE001 — fall back, don't crash
            logger.info("local_embedder_fallback",
                        extra={"model": model_name, "reason": str(exc)[:200]})

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._st is not None:
            return [_fit_dim(list(v)) for v in
                    self._st.encode(texts, normalize_embeddings=True).tolist()]
        return [self._fallback(t) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def _fallback(self, text: str) -> list[float]:
        """Deterministic hashed BoW; L2-normalised, 768-dim, sign-trick."""
        toks = _TOKEN.findall(text.lower())
        if not toks:
            return [0.0] * SCHEMA_DIMENSIONS
        vec = [0.0] * SCHEMA_DIMENSIONS
        for tok, c in Counter(toks).items():
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            sign = 1.0 if (h >> 16) & 1 else -1.0
            vec[h % SCHEMA_DIMENSIONS] += sign * (1.0 + math.log(c))
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


class AnthropicEmbeddingProvider:
    """Anthropic embeddings via the ``anthropic`` SDK + API key."""

    def __init__(self, model_name: str = "claude-embed-v1") -> None:
        self.model_name, self.dimensions = model_name, SCHEMA_DIMENSIONS
        try:
            import anthropic  # type: ignore
            self._client = anthropic.Anthropic()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"AnthropicEmbeddingProvider unavailable: {exc}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            r = self._client.embeddings.create(model=self.model_name, input=t)
            vec = list(r.data[0].embedding) if hasattr(r, "data") \
                else list(r["data"][0]["embedding"])
            out.append(_fit_dim(vec))
        return out

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class OpenAIEmbeddingProvider:
    """OpenAI embeddings (``text-embedding-3-small`` by default)."""

    def __init__(self, model_name: str = "text-embedding-3-small") -> None:
        self.model_name, self.dimensions = model_name, SCHEMA_DIMENSIONS
        try:
            from openai import OpenAI  # type: ignore
            self._client = OpenAI()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OpenAIEmbeddingProvider unavailable: {exc}") from exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = self._client.embeddings.create(model=self.model_name, input=texts)
        return [_fit_dim(list(item.embedding)) for item in r.data]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


def select_provider(bundle: dict[str, Any] | None = None) -> EmbeddingProvider:
    """Env > org bundle > local default. ``SPINE_EMBEDDING_PROVIDER`` overrides."""
    cfg = ((bundle or {}).get("embedding") or {}) if isinstance(bundle, dict) else {}
    pid = (os.environ.get("SPINE_EMBEDDING_PROVIDER")
           or cfg.get("provider") or "local").lower()
    mid = cfg.get("model_id") or None
    if pid == "anthropic":
        return AnthropicEmbeddingProvider(mid or "claude-embed-v1")
    if pid == "openai":
        return OpenAIEmbeddingProvider(mid or "text-embedding-3-small")
    return LocalEmbeddingProvider(mid or _DEFAULT_LOCAL_MODEL)


# ─── EmbedderRunner — lazy cache + cosine search via psql ─────────────


def _vec_literal(vec: list[float]) -> str:
    """pgvector literal ``'[0.1,0.2,...]'`` (cast to ``::vector`` at use)."""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def _q(v: object) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


class EmbedderRunner:
    """Lazy embed + cache helper. Cosine search yields ``(node_id, distance)``."""

    def __init__(self, provider: EmbeddingProvider, db_url: str | None = None) -> None:
        self.provider = provider
        self._db_url = db_url or os.environ.get("SPINE_DB_URL") or os.environ.get("DATABASE_URL", "")
        if not self._db_url:
            raise RuntimeError("EmbedderRunner: SPINE_DB_URL / DATABASE_URL not set")

    def _psql(self, sql: str) -> str:
        try:
            r = subprocess.run(["psql", self._db_url, "-At", "-F", "\x1f",
                                "-v", "ON_ERROR_STOP=1", "-c", sql],
                               capture_output=True, text=True, timeout=30)
        except FileNotFoundError as e:
            # psql binary not on PATH; route layer maps RuntimeError → 503.
            raise RuntimeError("psql binary not available in this environment "
                               "(install postgresql-client or wire embedder "
                               "to asyncpg per Wave 4 backlog)") from e
        if r.returncode != 0:
            raise RuntimeError(f"psql failed: {r.stderr.strip()}")
        return r.stdout

    def embed_node(self, node_id: int, text: str) -> int:
        """Lazily embed one node; skip if text_hash unchanged. Returns 1/0."""
        th = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = self._psql(f"SELECT text_hash FROM spine_kg.kg_node_embedding "
                              f"WHERE node_id = {int(node_id)};").strip()
        if existing and existing.split("\x1f")[0].strip() == th:
            return 0
        self._upsert([(int(node_id), _fit_dim(self.provider.embed_one(text)), th)])
        return 1

    def embed_batch(self, node_ids_and_texts: list[tuple[int, str]]) -> int:
        """Cold-start batch embed; returns count of (re)inserted rows."""
        if not node_ids_and_texts:
            return 0
        vecs = self.provider.embed([t for _, t in node_ids_and_texts])
        rows = [(int(nid), _fit_dim(v),
                 hashlib.sha256(txt.encode("utf-8")).hexdigest())
                for (nid, txt), v in zip(node_ids_and_texts, vecs, strict=False)]
        self._upsert(rows)
        return len(rows)

    def _upsert(self, rows: list[tuple[int, list[float], str]]) -> None:
        if not rows:
            return
        vs = ",".join(f"({nid}, {_q(self.provider.model_name)}, "
                      f"{_q(_vec_literal(vec))}::vector, {_q(th)})"
                      for nid, vec, th in rows)
        self._psql("INSERT INTO spine_kg.kg_node_embedding "
                   "(node_id, model, embedding, text_hash) VALUES " + vs +
                   " ON CONFLICT (node_id) DO UPDATE SET "
                   "embedding = EXCLUDED.embedding, model = EXCLUDED.model, "
                   "text_hash = EXCLUDED.text_hash, created_at = now();")

    def get_embedding(self, node_id: int) -> list[float] | None:
        """Fetch a cached embedding; ``None`` if not yet embedded."""
        out = self._psql(f"SELECT embedding::text FROM spine_kg.kg_node_embedding "
                         f"WHERE node_id = {int(node_id)};").strip()
        raw = out.split("\x1f")[0].strip() if out else ""
        if not (raw.startswith("[") and raw.endswith("]")):
            return None
        try:
            return [float(x) for x in raw[1:-1].split(",") if x]
        except ValueError:
            return None

    def cosine_search(self, query_embedding: list[float], limit: int = 50,
                      repo: str | None = None,
                      type_filter: list[str] | None = None) -> list[tuple[int, float]]:
        """Pgvector cosine search; returns ``[(node_id, distance), ...]`` asc."""
        qv = _q(_vec_literal(_fit_dim(query_embedding)))
        where = ["(n.valid_to IS NULL OR n.valid_to > NOW())"]
        if repo:
            where.append(f"n.repo = {_q(repo)}")
        if type_filter:
            safe = [t for t in type_filter if t.replace("_", "").isalnum()]
            if safe:
                where.append("n.type IN (" + ",".join(_q(t) for t in safe) + ")")
        sql = ("SELECT e.node_id, (e.embedding <=> " + qv + "::vector) AS dist "
               "FROM spine_kg.kg_node_embedding e "
               "JOIN spine_kg.kg_node n ON n.id = e.node_id "
               "WHERE " + " AND ".join(where) +
               " ORDER BY e.embedding <=> " + qv + f"::vector LIMIT {int(limit)};")
        results: list[tuple[int, float]] = []
        for ln in (l for l in self._psql(sql).splitlines() if l):
            parts = ln.split("\x1f")
            if len(parts) < 2:
                continue
            try:
                results.append((int(parts[0]), float(parts[1])))
            except ValueError:
                continue
        return results
