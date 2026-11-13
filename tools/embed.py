"""Model embedding (kemiripan makna) lewat Ollama: dipakai Bandingkan test case.
Jauh lebih ringan dari AI chat: ratusan test case selesai dalam sekitar satu menit di laptop tanpa GPU."""
from typing import Callable, List, Optional

from tools.ai_config import ollama_settings

DEFAULT_MODEL = "nomic-embed-text"
PREFIX = "clustering: "  # nomic-embed-text memakai awalan tugas


def model_name() -> str:
    try:
        return ollama_settings().get("embedding_model") or DEFAULT_MODEL
    except Exception:
        return DEFAULT_MODEL


def available(models: Optional[List[dict]]) -> bool:
    name = model_name()
    have = {m["name"] for m in models or []}
    return name in have or f"{name}:latest" in have


def make() -> Callable[[List[str]], List[List[float]]]:
    from tools import ai_source
    client = ai_source.client(timeout=600)
    name = model_name()

    def embed(texts: List[str]) -> List[List[float]]:
        items = [PREFIX + t for t in texts]
        try:
            resp = client.embed(model=name, input=items)
            vecs = resp["embeddings"]
        except AttributeError:  # pustaka ollama lama: satu teks per panggilan
            vecs = [client.embeddings(model=name, prompt=t)["embedding"] for t in items]
        return [list(v) for v in vecs]
    return embed
