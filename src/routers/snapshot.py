"""Macro market snapshot."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi import Path as PathParam

from ..queries import snapshot as qry

router = APIRouter()


@router.get("/api/snapshot/latest")
def snapshot_latest():
    """Latest macro market snapshot (PNG + top-3 mover narratives).

    Returns metadata + the PNG filename so the frontend can render the image
    from the static-mounted snapshots directory.
    """
    return qry.get_latest_snapshot() or qry.empty_snapshot(None)


@router.get("/api/snapshot/{date_str}")
def snapshot_detail(date_str: str = PathParam(..., pattern=r"^\d{8}$")):
    """Specific snapshot by date (YYYYMMDD)."""
    return qry.get_snapshot_by_date(date_str) or qry.empty_snapshot(date_str)
