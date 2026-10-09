"""feed-page backend: stored feed cards merged with goal-derived cards, plus reactions."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

_STORE_PATH = Path(__file__).resolve().parent / "muse_store.py"


def _load_store():
    name = "hermes_muse_store"
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(name, _STORE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {_STORE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


store = _load_store()
router = APIRouter()


class ReactionBody(BaseModel):
    reaction: Optional[str] = None


@router.get("/feed")
def list_feed(limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    return store.merged_feed(limit)


@router.post("/feed/{item_id}/reaction")
def react(item_id: str, body: ReactionBody) -> Dict[str, Any]:
    try:
        return store.set_reaction(item_id, body.reaction)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
