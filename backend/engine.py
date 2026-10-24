"""Deterministic content-based recommendations for the reviewed public catalog."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping, Sequence

WORDS = re.compile(r"[a-z0-9]{3,}", re.I)
STOP = frozenset(("the", "and", "for", "from", "that", "with", "into", "your", "this", "film", "story", "their", "they", "have", "after", "before", "about", "where", "when", "there", "more", "than", "only"))


def _tokens(movie: Mapping[str, Any]) -> set[str]:
    return {w for w in WORDS.findall(str(movie.get("title", "")) + " " + str(movie.get("synopsis", ""))) if w not in STOP}


def _genres(movie: Mapping[str, Any]) -> set[str]:
    return {str(x).strip().casefold() for x in movie.get("genres", []) if str(x).strip()}


def recommend(movies: Sequence[Mapping[str, Any]], saved_ids: Sequence[str] = (), limit: int = 8) -> list[dict[str, Any]]:
    """Return scored films, excluding saved titles. No external API or user tracking."""
    limit = max(0, min(int(limit), 24))
    by_id = {str(m.get("id")): m for m in movies if isinstance(m, Mapping) and m.get("id")}
    seeds = [by_id[s] for s in list(dict.fromkeys(saved_ids))[:50] if s in by_id]
    excluded = {str(m.get("id")) for m in seeds}
    preferred_genres = Counter(g for m in seeds for g in _genres(m))
    seed_tokens: set[str] = set().union(*(_tokens(m) for m in seeds)) if seeds else set()
    seed_years = [m["year"] for m in seeds if isinstance(m.get("year"), int)]
    ranked = []
    for movie in by_id.values():
        if str(movie["id"]) in excluded:
            continue
        genres = _genres(movie)
        words = _tokens(movie)
        year = movie.get("year")
        if seeds:
            genre_score = sum(preferred_genres.get(g, 0) for g in genres) * 5.0
            word_score = len(words & seed_tokens) * 0.25
            year_score = max((max(0, 8 - abs(year - y)) / 8 for y in seed_years), default=0) if isinstance(year, int) else 0
            score = genre_score + word_score + year_score
            common = sorted((g for g in genres if g in preferred_genres), key=lambda g: (-preferred_genres[g], g))
            reason = ("Matches your " + ", ".join(common[:2]) + " interests") if common else "Explore something different"
        else:
            score = (year if isinstance(year, int) else 0) / 1000
            reason = "Discover something new"
        ranked.append((score, str(movie.get("title", "")).casefold(), str(movie["id"]), movie, reason))
    ranked.sort(key=lambda x: (-x[0], x[1], x[2]))
    output: list[dict[str, Any]] = []
    genre_usage = Counter()
    # Re-rank lightly for variety instead of returning only one genre.
    pool = ranked[:max(50, limit * 8)]
    while pool and len(output) < limit:
        best = max(range(len(pool)), key=lambda i: (pool[i][0] - sum(genre_usage[g] for g in _genres(pool[i][3])) * 0.45, -i))
        _, _, movie_id, movie, reason = pool.pop(best)
        for genre in _genres(movie):
            genre_usage[genre] += 1
        output.append({"id": movie_id, "reason": reason, "score": round(float(_), 3)})
    return output
