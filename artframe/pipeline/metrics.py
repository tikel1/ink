"""Best-effort per-generation API metrics.

Collected via a contextvar so the provider call sites (image / text / search)
can record usage without threading a metrics object through the whole pipeline.
The backend calls start() before a generation and collect() after; if nothing
started a collector (e.g. a unit test), the record_* calls are no-ops.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field

TEXT = "text"
SEARCH = "search"
IMAGE = "image"


@dataclass
class GenMetrics:
    image_calls: int = 0
    text_calls: int = 0
    search_calls: int = 0
    text_tokens: int = 0
    retries: int = 0
    providers: set[str] = field(default_factory=set)

    def provider_str(self) -> str:
        return ",".join(sorted(self.providers)) if self.providers else ""


_current: contextvars.ContextVar[GenMetrics | None] = contextvars.ContextVar(
    "gen_metrics", default=None
)


def start() -> GenMetrics:
    """Begin collecting; returns the fresh collector (also the one collect() reads)."""
    m = GenMetrics()
    _current.set(m)
    return m


def collect() -> GenMetrics | None:
    return _current.get()


def record(kind: str, provider: str, tokens: int = 0) -> None:
    m = _current.get()
    if m is None:
        return
    if kind == IMAGE:
        m.image_calls += 1
    elif kind == SEARCH:
        m.search_calls += 1
        m.providers.add(provider)
    else:
        m.text_calls += 1
        m.providers.add(provider)
    if tokens > 0:
        m.text_tokens += tokens


def record_retry() -> None:
    m = _current.get()
    if m is not None:
        m.retries += 1
