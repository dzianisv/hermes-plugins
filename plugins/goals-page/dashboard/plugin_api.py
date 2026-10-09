"""goals-page backend: read-only aggregate of per-session goals across local profiles.

Reads ``state_meta`` rows ``goal:<session_id>`` from the default store and every
``~/.hermes/profiles/<name>/state.db`` the user allows. Every open is read-only (SQLite
``?mode=ro`` URI); nothing here can write. Per-profile failures are reported in the
payload instead of being swallowed into an empty list.

Design: https://app.notion.com/p/3f3ac25eb49f81028008ec3a19e80edf
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

_CACHE_TTL = 5.0
_cache: Dict[str, Any] = {"at": 0.0, "payload": None}
_cache_lock = threading.Lock()


# ---------------------------------------------------------------- discovery

def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def profile_dbs(home: Optional[Path] = None, allow: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Profiles whose state.db we may read. ``allow`` is an explicit allowlist of names;
    ``None`` means default + every directory under profiles/."""
    home = home or hermes_home()
    out = [{"profile": "default", "db": home / "state.db"}]
    profiles_dir = home / "profiles"
    if profiles_dir.is_dir():
        for p in sorted(profiles_dir.iterdir()):
            if p.is_dir() and (p / "state.db").exists():
                out.append({"profile": p.name, "db": p / "state.db"})
    if allow is not None:
        allowed = set(allow)
        out = [o for o in out if o["profile"] in allowed]
    return out


# ---------------------------------------------------------------- read model

def _ro_connect(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=1.0, check_same_thread=False)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def classify(goal: Dict[str, Any]) -> str:
    """Factual group, no intent inference (critique: Active / Waiting / Paused / Done).

    ``cleared`` is NOT done: compression copies and manual clears both produce it."""
    status = goal.get("status")
    if status == "done":
        return "done"
    if status == "cleared":
        return "cleared"
    if status == "paused":
        return "paused"
    if status == "active":
        if goal.get("waiting_on_pid") or goal.get("waiting_on_session") \
                or float(goal.get("waiting_until") or 0) > 0 \
                or int(goal.get("waiting_on_delegations") or 0) > 0:
            return "waiting"
        return "active"
    return "other"


def attention(goal: Dict[str, Any]) -> Optional[str]:
    """Soft 'may need attention' signal with evidence; never a certainty.

    Only an active/paused goal whose LAST verdict is blocked and that has not been resumed
    since counts. ``resume()`` keeps the old verdict, so a blocked verdict older than the last
    turn is treated as superseded."""
    if goal.get("status") not in ("active", "paused"):
        return None
    if goal.get("last_verdict") != "blocked":
        return None
    return goal.get("last_reason") or "judge: blocked"


def sub_status(goal: Dict[str, Any]) -> str:
    for key in ("waiting_reason", "paused_reason", "last_reason"):
        v = goal.get(key)
        if v:
            return str(v).strip().splitlines()[0][:160]
    return ""


def read_profile_goals(profile: str, db_path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {"profile": profile, "db": str(db_path), "goals": [], "error": None, "read_at": time.time()}
    if not db_path.exists():
        result["error"] = "state.db not found"
        return result
    conn = None
    try:
        conn = _ro_connect(db_path)
        rows = conn.execute("SELECT key, value FROM state_meta WHERE key LIKE 'goal:%'").fetchall()
        sids = [r["key"][len("goal:"):] for r in rows]
        sess: Dict[str, sqlite3.Row] = {}
        if sids:
            for chunk_start in range(0, len(sids), 400):
                chunk = sids[chunk_start:chunk_start + 400]
                q = ",".join("?" * len(chunk))
                for s in conn.execute(
                    f"SELECT id, title, source, chat_id, thread_id, chat_type, profile_name, "
                    f"started_at, last_activity_at, archived, parent_session_id "
                    f"FROM sessions WHERE id IN ({q})", chunk):
                    sess[s["id"]] = s
        hb: Dict[str, Any] = {}
        for r in conn.execute("SELECT key, value FROM state_meta WHERE key LIKE 'heartbeat:%'"):
            try:
                hb[r["key"][len("heartbeat:"):]] = json.loads(r["value"])
            except Exception:
                hb[r["key"][len("heartbeat:"):]] = {"raw": r["value"]}
        for r in rows:
            sid = r["key"][len("goal:"):]
            try:
                g = json.loads(r["value"])
            except Exception as exc:
                result["goals"].append({"profile": profile, "session_id": sid, "parse_error": str(exc), "group": "other"})
                continue
            s = sess.get(sid)
            row = {
                "profile": profile,
                "session_id": sid,
                "session_title": (s["title"] if s else None),
                "session_source": (s["source"] if s else None),
                "chat_id": (s["chat_id"] if s else None),
                "thread_id": (s["thread_id"] if s else None),
                "archived": bool(s["archived"]) if s and s["archived"] is not None else False,
                "parent_session_id": (s["parent_session_id"] if s else None),
                "session_started_at": (s["started_at"] if s else None),
                "session_last_activity_at": (s["last_activity_at"] if s else None),
                "objective": g.get("goal", ""),
                "status": g.get("status"),
                "source": g.get("source", "user"),
                "turns_used": g.get("turns_used", 0),
                "max_turns": g.get("max_turns"),
                "created_at": g.get("created_at"),
                "last_turn_at": g.get("last_turn_at"),
                "last_verdict": g.get("last_verdict"),
                "last_reason": g.get("last_reason"),
                "paused_reason": g.get("paused_reason"),
                "waiting_reason": g.get("waiting_reason"),
                "waiting_until": g.get("waiting_until"),
                "waiting_on_pid": g.get("waiting_on_pid"),
                "waiting_on_session": g.get("waiting_on_session"),
                "waiting_on_delegations": g.get("waiting_on_delegations"),
                "contract": g.get("contract") or {},
                "subgoals": g.get("subgoals") or [],
                "gates": g.get("gates") or [],
                "heartbeat": hb.get(sid),
                "group": classify(g),
                "attention": attention(g),
                "sub_status": sub_status(g),
            }
            result["goals"].append(row)
    except sqlite3.Error as exc:
        result["error"] = f"sqlite: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return result


def build_payload(home: Optional[Path] = None, allow: Optional[List[str]] = None) -> Dict[str, Any]:
    profiles = []
    goals: List[Dict[str, Any]] = []
    for p in profile_dbs(home, allow):
        r = read_profile_goals(p["profile"], p["db"])
        profiles.append({"profile": r["profile"], "db": r["db"], "error": r["error"], "count": len(r["goals"]), "read_at": r["read_at"]})
        goals.extend(r["goals"])

    def sort_key(g: Dict[str, Any]) -> float:
        return float(g.get("last_turn_at") or g.get("created_at") or 0)

    goals.sort(key=sort_key, reverse=True)
    counts: Dict[str, int] = {}
    for g in goals:
        counts[g["group"]] = counts.get(g["group"], 0) + 1
    return {
        "generated_at": time.time(),
        "profiles": profiles,
        "counts": counts,
        "attention_count": sum(1 for g in goals if g.get("attention")),
        "goals": goals,
    }


# ---------------------------------------------------------------- routes

@router.get("/goals")
def list_goals(fresh: bool = Query(False), profile: Optional[str] = Query(None)) -> Dict[str, Any]:
    now = time.monotonic()
    with _cache_lock:
        cached = _cache["payload"]
        if cached is not None and not fresh and now - _cache["at"] < _CACHE_TTL:
            payload = cached
        else:
            payload = build_payload()
            _cache["payload"], _cache["at"] = payload, now
    if profile:
        payload = dict(payload)
        payload["goals"] = [g for g in payload["goals"] if g["profile"] == profile]
    return payload


@router.get("/goals/{profile}/{session_id}")
def get_goal(profile: str, session_id: str) -> Dict[str, Any]:
    dbs = {p["profile"]: p["db"] for p in profile_dbs()}
    if profile not in dbs:
        raise HTTPException(404, "unknown profile")
    r = read_profile_goals(profile, dbs[profile])
    if r["error"]:
        raise HTTPException(503, r["error"])
    for g in r["goals"]:
        if g["session_id"] == session_id:
            return g
    raise HTTPException(404, "no goal for session")
