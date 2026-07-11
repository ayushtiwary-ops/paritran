"""InLegalBERT semantic retrieval index (SPEC 6.7).

SemanticIndex embeds every corpus text once at construction with
law-ai/InLegalBERT loaded from a LOCAL directory only (never the network):
mean-pooled last_hidden_state, truncation at 256 tokens, unit-normalized
vectors, cosine ranking. Model directory resolution mirrors
``paritran.api.main.resolve_model_dir``: it accepts either a flat model
directory (config.json at the root) or a HuggingFace hub-cache layout
(refs/main naming a snapshots/<sha> directory).

torch and transformers are imported lazily inside SemanticIndex so that
importing this module never requires them; tests skip cleanly when either
the libraries or the local weights are absent.

Numeric truth rule: every cosine reported here is computed by the real
model over the real corpus. Nothing is stubbed or canned.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

MAX_LENGTH = 256  # SPEC 6.7: truncation 256
DEFAULT_BATCH_SIZE = 8

# Host-machine fallback: the standard HF hub cache location for InLegalBERT.
DEFAULT_HUB_CACHE = (
    Path.home() / ".cache" / "huggingface" / "hub" / "models--law-ai--InLegalBERT"
)

ENV_VARS = ("INLEGALBERT_LOCAL_DIR", "INLEGALBERT_PATH")


def _resolve_hub_layout(base: Path) -> Path | None:
    """Same acceptance logic as paritran.api.main.resolve_model_dir."""
    if (base / "config.json").is_file():
        return base
    ref = base / "refs" / "main"
    if ref.is_file():
        snapshot = base / "snapshots" / ref.read_text().strip()
        if (snapshot / "config.json").is_file():
            return snapshot
    snapshots = (
        sorted((base / "snapshots").glob("*/config.json"))
        if (base / "snapshots").is_dir()
        else []
    )
    return snapshots[0].parent if snapshots else None


def resolve_model_dir(explicit: str | Path | None = None) -> Path | None:
    """Resolve the local InLegalBERT weights directory, or None.

    Search order: the explicit argument, then INLEGALBERT_LOCAL_DIR, then
    INLEGALBERT_PATH, then the default HF hub cache path. Each candidate is
    accepted as either a flat model dir or a hub-cache layout.
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    for var in ENV_VARS:
        value = os.environ.get(var)
        if value:
            candidates.append(Path(value))
    candidates.append(DEFAULT_HUB_CACHE)
    for base in candidates:
        if base.is_dir():
            resolved = _resolve_hub_layout(base)
            if resolved is not None:
                return resolved
    return None


class SemanticIndex:
    """Cosine ranking over precomputed InLegalBERT corpus embeddings."""

    def __init__(
        self,
        corpus: Mapping[str, str],
        model_dir: str | Path | None = None,
        max_length: int = MAX_LENGTH,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        if not corpus:
            raise ValueError("SemanticIndex needs a non-empty corpus")
        import torch  # lazy: keeps module importable without torch
        from transformers import AutoModel, AutoTokenizer

        resolved = resolve_model_dir(model_dir)
        if resolved is None:
            raise FileNotFoundError(
                "InLegalBERT weights not found locally. Set INLEGALBERT_LOCAL_DIR "
                "(or INLEGALBERT_PATH) to a flat model directory or a HF hub-cache "
                f"directory; default fallback is {DEFAULT_HUB_CACHE}."
            )
        self._torch = torch
        self.model_dir = resolved
        self.max_length = max_length
        self.batch_size = batch_size
        # local_files_only: this class must never touch the network.
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(resolved), local_files_only=True
        )
        self.model = AutoModel.from_pretrained(str(resolved), local_files_only=True)
        self.model.eval()
        self.ids: list[str] = list(corpus)
        # Embeddings precomputed once at construction (SPEC 6.7).
        self._doc_matrix = self.embed([corpus[i] for i in self.ids])

    def embed(self, texts: list[str]):
        """Unit-normalized mean-pooled last_hidden_state embeddings.

        Returns a (len(texts), hidden) float tensor; every row has L2 norm 1.
        Mean pooling is attention-mask weighted so padding never contributes.
        """
        torch = self._torch
        chunks = []
        with torch.no_grad():
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start : start + self.batch_size]
                encoded = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                hidden = self.model(**encoded).last_hidden_state  # (b, t, h)
                mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                summed = (hidden * mask).sum(dim=1)
                counts = mask.sum(dim=1).clamp(min=1e-9)
                mean = summed / counts
                chunks.append(torch.nn.functional.normalize(mean, p=2, dim=1))
        return torch.cat(chunks, dim=0)

    def cosines(self, text: str) -> dict[str, float]:
        """Cosine similarity of ``text`` against every corpus document."""
        query = self.embed([text])[0]
        sims = self._doc_matrix @ query
        return {doc_id: float(sim) for doc_id, sim in zip(self.ids, sims)}

    def rank(self, text: str) -> list[tuple[float, str]]:
        """(cosine, doc_id) pairs sorted descending, prototype tie order."""
        return sorted(((sc, k) for k, sc in self.cosines(text).items()), reverse=True)
