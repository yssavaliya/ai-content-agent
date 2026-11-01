from __future__ import annotations

import re
from collections.abc import Iterable

MAX_HOOK_CHARS = 140
MAX_HASHTAGS = 15
MAX_INLINE_HASHTAGS = 5
MAX_EMOJIS = 6

# Well-known quotes the model tends to reproduce or lightly reword. Matched on normalised text, so a post
# that contains one of these fragments is sent back for a rewrite. This is a guard, not a complete list:
# the creator prompt asks for original wording and the reviewer is the second line of defence.
FAMOUS_QUOTE_FRAGMENTS = (
    "be the change you wish to see",
    "the only thing we have to fear is fear itself",
    "that which does not kill us makes us stronger",
    "i think therefore i am",
    "the unexamined life is not worth living",
    "the only way to do great work is to love what you do",
    "stay hungry stay foolish",
    "float like a butterfly sting like a bee",
    "in the middle of difficulty lies opportunity",
    "you miss 100 of the shots you don t take",
    "it always seems impossible until it s done",
    "the journey of a thousand miles begins with a single step",
    "fall seven times stand up eight",
    "darkest hour is just before the dawn",
    "with great power comes great responsibility",
    "whatever you do do it well",
    "the best way to predict the future is to create it",
    "a man is but the product of his thoughts",
    "if you can dream it you can do it",
    "do what you can with what you have where you are",
    "life is what happens when you re busy making other plans",
    "the only impossible journey is the one you never begin",
    "believe you can and you re halfway there",
    "it does not matter how slowly you go as long as you do not stop",
    "those who cannot remember the past are condemned to repeat it",
    "an eye for an eye makes the whole world blind",
)

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⬆↔-↪]")
_HASHTAG = re.compile(r"(?<!\w)#\w+")


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower().replace("'", " ")).split())


def lint_caption(caption: str, hashtags: Iterable[str] | None = None) -> list[str]:
    """Deterministic checks that catch common low-quality drafts before (and in addition to) the LLM reviewer.

    Returns human-readable problems, phrased so they can be fed back to the creator as revision feedback.
    """
    problems: list[str] = []
    text = (caption or "").strip()
    if not text:
        return ["The caption is empty."]

    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(first_line) > MAX_HOOK_CHARS:
        problems.append(
            f"The first line is {len(first_line)} characters; it must be a short scroll-stopping hook (under {MAX_HOOK_CHARS})."
        )

    tags = [str(tag) for tag in (hashtags or [])]
    if len(tags) > MAX_HASHTAGS:
        problems.append(f"{len(tags)} hashtags is spam-like; use at most {MAX_HASHTAGS}.")
    inline = _HASHTAG.findall(text)
    if len(inline) > MAX_INLINE_HASHTAGS:
        problems.append(f"The caption body contains {len(inline)} hashtags; keep hashtags in the hashtags field.")

    emojis = _EMOJI.findall(text)
    if len(emojis) > MAX_EMOJIS:
        problems.append(f"The caption uses {len(emojis)} emojis; use at most {MAX_EMOJIS}.")

    normalised = _normalise(text)
    for fragment in FAMOUS_QUOTE_FRAGMENTS:
        if fragment in normalised:
            problems.append(
                f'The caption reproduces a famous quote ("{fragment}"). Write original wording that makes the point differently.'
            )
            break

    return problems
