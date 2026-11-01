from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from ..redaction import redact
from .buffer import BUFFER_GRAPHQL_URL, GET_ORGANIZATIONS_QUERY

POSTS_QUERY = """
query GetPosts($input: PostsInput!, $first: Int) {
  posts(first: $first, input: $input) {
    edges {
      node {
        id
        status
        dueAt
        sentAt
        shareMode
        text
        channelId
      }
    }
    pageInfo {
      hasNextPage
    }
  }
}
"""


class BufferStatusError(RuntimeError):
    pass


@dataclass(frozen=True)
class BufferPost:
    id: str
    status: str
    share_mode: str
    due_at: str | None
    sent_at: str | None
    text: str


@dataclass
class BufferStatus:
    channel_id: str
    posts: list[BufferPost]
    has_more: bool = False
    by_status: Counter = field(default_factory=Counter)

    @property
    def waiting(self) -> list[BufferPost]:
        """Posts that were accepted but have not gone out yet."""
        return [p for p in self.posts if p.status.lower() in {"scheduled", "buffer", "draft", "needs_approval"}]

    @property
    def waiting_without_time(self) -> list[BufferPost]:
        return [p for p in self.waiting if not p.due_at]


def _graphql(token: str, query: str, variables: dict[str, Any] | None, post: Callable = requests.post) -> dict[str, Any]:
    try:
        response = post(
            BUFFER_GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise BufferStatusError(f"Buffer request failed: {redact(str(exc), token)}") from None
    if response.status_code >= 400:
        raise BufferStatusError(f"Buffer HTTP error ({response.status_code}): {redact(response.text[:300], token)}")
    payload = response.json()
    if payload.get("errors"):
        message = "; ".join(e.get("message", "unknown error") for e in payload["errors"])
        raise BufferStatusError(f"Buffer GraphQL error: {message}")
    return payload.get("data") or {}


def fetch_status(token: str, channel_id: str, limit: int = 50, post: Callable = requests.post) -> BufferStatus:
    """Read-only: the posts Buffer holds for one channel. Never creates, edits or deletes anything."""
    orgs = (_graphql(token, GET_ORGANIZATIONS_QUERY, None, post).get("account") or {}).get("organizations") or []
    if not orgs:
        raise BufferStatusError("The Buffer token can see no organisations")
    last_error: Exception | None = None
    for org in orgs:
        try:
            data = _graphql(
                token,
                POSTS_QUERY,
                {"input": {"organizationId": org["id"], "filter": {"channelIds": [channel_id]}}, "first": limit},
                post,
            )
        except BufferStatusError as exc:
            last_error = exc
            continue
        results = data.get("posts") or {}
        posts = [
            BufferPost(
                id=str(node.get("id")),
                status=str(node.get("status")),
                share_mode=str(node.get("shareMode")),
                due_at=node.get("dueAt"),
                sent_at=node.get("sentAt"),
                text=" ".join(str(node.get("text") or "").split()),
            )
            for node in (edge.get("node") or {} for edge in results.get("edges") or [])
        ]
        status = BufferStatus(channel_id, posts, bool((results.get("pageInfo") or {}).get("hasNextPage")))
        status.by_status = Counter(p.status for p in posts)
        return status
    raise BufferStatusError(str(last_error) if last_error else "no organisation returned posts")


def render(status: BufferStatus, markdown: bool = False) -> str:
    counts = ", ".join(f"{name}: {count}" for name, count in sorted(status.by_status.items())) or "no posts"
    waiting, untimed = status.waiting, status.waiting_without_time
    lines = [
        f"Posts Buffer holds for this channel: {len(status.posts)}{'+' if status.has_more else ''} ({counts})",
        f"Waiting to be sent: {len(waiting)}, of which with no send time (dueAt empty): {len(untimed)}",
    ]
    if untimed:
        lines.append(
            "Posts with no send time are not stuck behind a date: they sit in the queue until a posting-schedule "
            "slot opens, so if the channel has no schedule slots they never go out."
        )
    header = ["| Status | Share mode | Due at | Sent at | Text |", "| --- | --- | --- | --- | --- |"]
    rows = [
        f"| {p.status} | {p.share_mode} | {p.due_at or '-'} | {p.sent_at or '-'} | {p.text[:60].replace('|', '/')} |"
        for p in status.posts[:30]
    ]
    if markdown:
        return "\n".join(lines + [""] + header + rows)
    return "\n".join(lines + [""] + [f"{p.status:<10} {p.share_mode:<14} due={p.due_at or '-'} sent={p.sent_at or '-'}  {p.text[:50]}" for p in status.posts[:30]])
