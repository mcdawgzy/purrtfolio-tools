"""Health + site metadata."""
from __future__ import annotations

import time

from fastapi import APIRouter

from ..config import META_CACHE_TTL
from ..queries import meta as qry

router = APIRouter()

# Server-side cache for /api/meta (changes only on quarterly ingestion)
_meta_cache: dict | None = None
_meta_cache_time: float = 0.0


@router.get("/api/health")
def health():
    return qry.health()


@router.get("/api/meta")
def meta():
    """Site metadata (counts, quarters, last update). Cached for 5 min since
    this only changes on quarterly ingestion runs."""
    global _meta_cache, _meta_cache_time
    now = time.time()
    if _meta_cache is not None and (now - _meta_cache_time) < META_CACHE_TTL:
        return _meta_cache
    result = qry.get_meta()
    _meta_cache = result
    _meta_cache_time = now
    return result
