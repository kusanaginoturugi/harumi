from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

from harumi.config import get_embed_model


def _post_embed(input_text: str) -> tuple[list[float], str]:
    model = get_embed_model()
    payload = json.dumps({"model": model, "input": input_text}).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))
    embeddings = data.get("embeddings") or []
    if not embeddings:
        raise RuntimeError("Ollama embedding response did not include embeddings")
    return list(embeddings[0]), model


def embed_text(input_text: str) -> tuple[list[float], str]:
    return _post_embed(input_text)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
