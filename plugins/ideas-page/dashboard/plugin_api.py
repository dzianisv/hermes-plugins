"""ideas-page backend: list ideas and change their status. Shares feed-page's muse_store."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_STORE_PATH = Path(os.environ.get("MUSE_PLUGINS_HOME") or (Path.home() / ".hermes")) / "plugins" / "feed-page" / "dashboard" / "muse_store.py"
_SIBLING = Path(__file__).resolve().parents[2] / "feed-page" / "dashboard" / "muse_store.py"
if not _STORE_PATH.exists() and _SIBLING.exists():
    _STORE_PATH = _SIBLING  # monorepo checkout
if not _STORE_PATH.exists():  # sibling layout fallback
    _STORE_PATH = Path(__file__).resolve().parents[2] / "feed-page" / "dashboard" / "muse_store.py"


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


class StatusBody(BaseModel):
    status: str


@router.get("/ideas")
def list_ideas() -> Dict[str, Any]:
    errors = []
    try:
        items = store.list_ideas()
    except Exception as exc:
        items, errors = [], [f"{type(exc).__name__}: {exc}"]
    return {"items": items, "errors": errors}


@router.post("/ideas/{idea_id}/status")
def set_status(idea_id: str, body: StatusBody) -> Dict[str, Any]:
    try:
        return store.set_idea_status(idea_id, body.status)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except KeyError:
        raise HTTPException(404, "unknown idea")
