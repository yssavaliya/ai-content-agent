from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from ..database.connection import DatabaseConnection

_URL = re.compile(r"https?://\S+")
_HASHTAG = re.compile(r"#\w+")
_NON_WORD = re.compile(r"[^\w\s]", flags=re.UNICODE)


@dataclass(frozen=True)
class SimilarCaption:
    score: float
    caption: str
    creator_output_id: int


def normalize(text: str) -> str:
    """Lower-case, drop URLs, hashtags, emoji and punctuation, collapse whitespace."""
    text = _HASHTAG.sub(" ", _URL.sub(" ", text.lower()))
    return " ".join(_NON_WORD.sub(" ", text).split())


def _shingles(words: list[str], size: int = 3) -> set[tuple[str, ...]]:
    if len(words) < size:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def similarity(a: str, b: str) -> float:
    """0..1 similarity: the larger of character-sequence ratio and word 3-gram overlap."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    sa, sb = _shingles(na.split()), _shingles(nb.split())
    jaccard = len(sa & sb) / len(sa | sb) if sa | sb else 0.0
    return max(ratio, jaccard)


def find_similar_caption(
    db: DatabaseConnection,
    caption: str,
    threshold: float = 0.85,
    exclude_id: int | None = None,
    lookback: int = 300,
) -> SimilarCaption | None:
    """Most similar earlier caption at or above ``threshold`` (None when the caption is original)."""
    rows = db.fetch_all(
        "SELECT id, caption FROM creator_outputs WHERE (? IS NULL OR id != ?) ORDER BY id DESC LIMIT ?",
        (exclude_id, exclude_id, lookback),
    )
    best: SimilarCaption | None = None
    for row in rows:
        score = similarity(caption, row["caption"])
        if score >= threshold and (best is None or score > best.score):
            best = SimilarCaption(score=score, caption=row["caption"], creator_output_id=int(row["id"]))
    return best
