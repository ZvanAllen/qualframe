"""Locate a unique verbatim quote without rewriting text or choosing between repeats."""

from dataclasses import dataclass


@dataclass(frozen=True)
class QuoteAnchor:
    start: int | None
    end: int | None
    match_count: int


def anchor_exact_quote(source: str, quote: str) -> QuoteAnchor:
    if not quote.strip():
        return QuoteAnchor(None, None, 0)
    first = source.find(quote)
    if first < 0:
        return QuoteAnchor(None, None, 0)
    # Stop after a second match, including overlapping occurrences. Two means
    # two or more: enough to reject ambiguity without enumerating huge sources.
    if source.find(quote, first + 1) >= 0:
        return QuoteAnchor(None, None, 2)
    return QuoteAnchor(first, first + len(quote), 1)
