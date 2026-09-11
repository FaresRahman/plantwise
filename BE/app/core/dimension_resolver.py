"""Shared fuzzy-match utility for resolving a user-typed value (e.g. "Line 2")
against a module's own known dimension values (e.g. line names for that
tenant). Deliberately stateless and DB-agnostic: each module fetches its own
candidate list from its own tables and calls resolve() with it — the
matching *algorithm* is shared, data ownership stays per-module, same as
every other cross-cutting convention in this codebase.

Never asks the LLM "how confident are you?" — confidence here is a
deterministic function of how many candidates plausibly match, not a
self-reported model score.
"""
from dataclasses import dataclass, field
from difflib import get_close_matches


@dataclass
class ResolveResult:
    matched: str | None
    candidates: list[str] = field(default_factory=list)
    needs_clarification: bool = False


def resolve(query: str, candidates: list[str], cutoff: float = 0.6) -> ResolveResult:
    """
    - Exact match -> resolved immediately.
    - Exactly one plausible fuzzy match -> resolved (typo/case tolerance).
    - Two or more plausible matches -> needs_clarification, caller should ask
      "did you mean X or Y?" rather than guess.
    - Zero matches -> not found; caller should say so explicitly, not guess.
    """
    if not candidates:
        return ResolveResult(matched=None)
    if query in candidates:
        return ResolveResult(matched=query, candidates=[query])

    matches = get_close_matches(query, candidates, n=3, cutoff=cutoff)
    if len(matches) == 1:
        return ResolveResult(matched=matches[0], candidates=matches)
    if len(matches) > 1:
        return ResolveResult(matched=None, candidates=matches, needs_clarification=True)
    return ResolveResult(matched=None)
