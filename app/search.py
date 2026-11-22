"""Shared retrieval code for GET /search and the future assist workflow."""

import re

from sqlmodel import Session

from app.constants import MAX_SNIPPET_LENGTH, SEARCH_STOPWORDS
from app.db.database import query_search
from app.schemas import SearchParams, SearchResponse, SearchResult


class SearchQueryError(ValueError):
    """The query has no searchable keywords after normalization."""


def build_match_query(query: str) -> str:
    terms = dict.fromkeys(
        term for term in re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        if term.casefold() not in SEARCH_STOPWORDS
    )
    if not terms:
        raise SearchQueryError("Search query must contain at least one non-stopword keyword")
    return " OR ".join(f'"{term}"' for term in terms)


def search_incidents(session: Session, params: SearchParams) -> SearchResponse:
    """Return filtered BM25 hits; callers share the same validated contract."""
    rows, total = query_search(session, build_match_query(params.q), params)
    results = []
    for row in rows:
        snippet = row["snippet"]
        if len(snippet) > MAX_SNIPPET_LENGTH:
            snippet = snippet[:MAX_SNIPPET_LENGTH - 1].rstrip() + "…"
        results.append(SearchResult(
            id=row["id"], title=row["title"], snippet=snippet, score=row["score"],
        ))
    return SearchResponse(results=results, total=total)
