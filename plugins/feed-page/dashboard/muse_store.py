"""Shared SQLite store for the Muse-style Feed and Ideas plugins.

One database for every profile: ``~/.hermes/muse.db`` (``Path.home()``, deliberately NOT
``HERMES_HOME`` — profiles live under ``~/.hermes/profiles/<name>`` and must all write to the
same feed). WAL mode, ``busy_timeout`` 3000 ms. Writes are tiny state changes; nothing deletes.

Imported by ``feed-page/__init__.py`` (agent tools), ``feed-page/dashboard/plugin_api.py`` and
``ideas-page/dashboard/plugin_api.py`` (the latter via importlib by absolute path).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

FEED_SOURCES = ("tool", "goal")
IDEA_STATUSES = ("proposed", "accepted", "dismissed", "done")
REACTIONS = ("up", "down")
_IDEA_ORDER = {s: i for i, s in enumerate(IDEA_STATUSES)}  # proposed, accepted, dismissed, done
_IDEA_SORT = {"proposed": 0, "accepted": 1, "done": 2, "dismissed": 3}

_DDL = (
    "CREATE TABLE IF NOT EXISTS feed_items ("
    " id TEXT PRIMARY KEY, created_at REAL, profile TEXT, session_id TEXT, title TEXT, body TEXT,"
    " icon TEXT, link_title TEXT, link_subtitle TEXT, link_status TEXT, link_url TEXT,"
    " reaction TEXT, source TEXT)",
    "CREATE TABLE IF NOT EXISTS ideas ("
    " id TEXT PRIMARY KEY, created_at REAL, updated_at REAL, profile TEXT, session_id TEXT,"
    " title TEXT, body TEXT, icon TEXT, needs_from_user TEXT, status TEXT)",
    "CREATE TABLE IF NOT EXISTS reactions (item_id TEXT PRIMARY KEY, reaction TEXT)",
    "CREATE INDEX IF NOT EXISTS feed_items_created ON feed_items(created_at)",
)


# ---------------------------------------------------------------- paths / context

def db_path() -> Path:
    override = os.environ.get("MUSE_DB_PATH")  # tests only
    return Path(override) if override else Path.home() / ".hermes" / "muse.db"


def current_profile() -> str:
    home = os.environ.get("HERMES_HOME")
    if not home:
        return "default"
    p = Path(home).expanduser().resolve()
    if p == (Path.home() / ".hermes").resolve():
        return "default"
    return p.name or "default"


def current_session_id(explicit: Optional[str] = None) -> Optional[str]:
    return explicit or os.environ.get("HERMES_SESSION_ID") or None


# ---------------------------------------------------------------- connection

def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: we manage transactions explicitly and start writes with BEGIN IMMEDIATE,
    # so a stale WAL snapshot can never turn into an un-retried SQLITE_BUSY_SNAPSHOT on upgrade.
    conn = sqlite3.connect(str(path), timeout=3.0, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
        conn.execute("PRAGMA journal_mode=WAL")
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reactions'").fetchone():
        for ddl in _DDL:
            conn.execute(ddl)
    return conn


def _begin_write(conn: sqlite3.Connection) -> None:
    """Take the write lock up front; the busy handler (3 s) waits for other writers."""
    conn.execute("BEGIN IMMEDIATE")



def _row(r: sqlite3.Row) -> Dict[str, Any]:
    return {k: r[k] for k in r.keys()}


# ---------------------------------------------------------------- feed

def feed_post(title: str, body: str, *, icon: str = "", link_title: str = "", link_subtitle: str = "",
              link_status: str = "", link_url: str = "", profile: Optional[str] = None,
              session_id: Optional[str] = None, source: str = "tool", conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    title = (title or "").strip()
    body = (body or "").strip()
    if not title:
        raise ValueError("title is required")
    if not body:
        raise ValueError("body is required")
    if source not in FEED_SOURCES:
        raise ValueError(f"source must be one of {FEED_SOURCES}")
    own = conn is None
    conn = conn or connect()
    try:
        item = {
            "id": uuid.uuid4().hex,
            "created_at": time.time(),
            "profile": profile or current_profile(),
            "session_id": current_session_id(session_id),
            "title": title[:200],
            "body": body[:2000],
            "icon": (icon or "").strip()[:8] or "📝",
            "link_title": (link_title or "").strip()[:200] or None,
            "link_subtitle": (link_subtitle or "").strip()[:300] or None,
            "link_status": (link_status or "").strip()[:60] or None,
            "link_url": (link_url or "").strip()[:2000] or None,
            "reaction": None,
            "source": source,
        }
        _begin_write(conn)
        conn.execute(
            "INSERT INTO feed_items (id, created_at, profile, session_id, title, body, icon, link_title,"
            " link_subtitle, link_status, link_url, reaction, source) VALUES"
            " (:id,:created_at,:profile,:session_id,:title,:body,:icon,:link_title,:link_subtitle,"
            ":link_status,:link_url,:reaction,:source)", item)
        conn.execute("COMMIT")
        return item
    finally:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        if own:
            conn.close()


def list_feed(limit: int = 100, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute("SELECT * FROM feed_items ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
        return [_row(r) for r in rows]
    finally:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        if own:
            conn.close()


def set_reaction(item_id: str, reaction: Optional[str], conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Persist a thumbs reaction. Stored items update their row; goal-derived (non-persisted)
    items land in ``reactions``. Returns {id, reaction, stored: 'feed_items'|'reactions'}."""
    if reaction is not None and reaction not in REACTIONS:
        raise ValueError("reaction must be 'up', 'down' or null")
    own = conn is None
    conn = conn or connect()
    try:
        _begin_write(conn)
        cur = conn.execute("UPDATE feed_items SET reaction=? WHERE id=?", (reaction, item_id))
        if cur.rowcount:
            conn.execute("COMMIT")
            return {"id": item_id, "reaction": reaction, "stored": "feed_items"}
        conn.execute("INSERT INTO reactions (item_id, reaction) VALUES (?,?)"
                     " ON CONFLICT(item_id) DO UPDATE SET reaction=excluded.reaction", (item_id, reaction))
        conn.execute("COMMIT")
        return {"id": item_id, "reaction": reaction, "stored": "reactions"}
    finally:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        if own:
            conn.close()


def external_reactions(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Optional[str]]:
    own = conn is None
    conn = conn or connect()
    try:
        return {r["item_id"]: r["reaction"] for r in conn.execute("SELECT item_id, reaction FROM reactions")}
    finally:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        if own:
            conn.close()


# ---------------------------------------------------------------- goal-derived feed

def _load_goals_api(home: Optional[Path] = None):
    """Import goals-page/dashboard/plugin_api.py by path (not a package). Raises on failure."""
    explicit = home is not None or bool(os.environ.get("MUSE_PLUGINS_HOME"))
    home = home or Path(os.environ.get("MUSE_PLUGINS_HOME") or (Path.home() / ".hermes"))
    path = home / "plugins" / "goals-page" / "dashboard" / "plugin_api.py"
    sibling = Path(__file__).resolve().parents[2] / "goals-page" / "dashboard" / "plugin_api.py"
    if not explicit and not path.exists() and sibling.exists():
        path = sibling  # monorepo checkout: plugins/<name>/ are siblings
    name = "hermes_goals_page_api_for_muse"
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


def goal_feed_items(state_home: Optional[Path] = None, errors: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Synthetic feed cards for every goal with status 'done' across the default store and every
    profile state.db. Never persisted. ``errors`` collects degradations instead of raising."""
    errors = errors if errors is not None else []
    try:
        api = _load_goals_api()
    except Exception as exc:
        errors.append(f"goals-page import failed: {type(exc).__name__}: {exc}")
        return []
    out: List[Dict[str, Any]] = []
    try:
        for p in api.profile_dbs(state_home):
            r = api.read_profile_goals(p["profile"], p["db"])
            if r.get("error"):
                errors.append(f"{p['profile']}: {r['error']}")
            for g in r.get("goals", []):
                if g.get("status") != "done":
                    continue
                text = str(g.get("objective") or "").strip()
                title = text if len(text) <= 90 else text[:89].rstrip() + "…"
                out.append({
                    "id": f"goal:{g['profile']}:{g['session_id']}",
                    "created_at": float(g.get("last_turn_at") or g.get("created_at") or 0),
                    "profile": g["profile"],
                    "session_id": g["session_id"],
                    "title": title or "(goal)",
                    "body": str(g.get("last_reason") or "Goal completed.").strip(),
                    "icon": "✅",
                    "link_title": g.get("session_title") or None,
                    "link_subtitle": f"{g['profile']} · {g.get('turns_used', 0)}/{g.get('max_turns') or '∞'} turns",
                    "link_status": "Done",
                    "link_url": None,
                    "reaction": None,
                    "source": "goal",
                })
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"goal merge failed: {type(exc).__name__}: {exc}")
    return out


def merged_feed(limit: int = 100, state_home: Optional[Path] = None) -> Dict[str, Any]:
    errors: List[str] = []
    conn = connect()
    try:
        items = list_feed(limit, conn=conn)
        goal_items = goal_feed_items(state_home, errors)
        if goal_items:
            ext = external_reactions(conn=conn)
            for it in goal_items:
                it["reaction"] = ext.get(it["id"])
            items.extend(goal_items)
    finally:
        conn.close()
    items.sort(key=lambda x: float(x.get("created_at") or 0), reverse=True)
    return {"items": items[: int(limit)], "errors": errors, "generated_at": time.time()}


# ---------------------------------------------------------------- ideas

def idea_propose(title: str, body: str, needs_from_user: str, *, icon: str = "", profile: Optional[str] = None,
                 session_id: Optional[str] = None, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Insert a proposed idea; if one with the same title is still 'proposed', update it instead."""
    title = (title or "").strip()
    body = (body or "").strip()
    needs = (needs_from_user or "").strip()
    if not title:
        raise ValueError("title is required")
    if not body:
        raise ValueError("body is required")
    if not needs:
        raise ValueError("needs_from_user is required")
    own = conn is None
    conn = conn or connect()
    try:
        now = time.time()
        _begin_write(conn)
        existing = conn.execute("SELECT id FROM ideas WHERE title=? AND status='proposed'", (title,)).fetchone()
        icon = (icon or "").strip()[:8] or "💡"
        if existing:
            conn.execute(
                "UPDATE ideas SET updated_at=?, body=?, icon=?, needs_from_user=?, profile=?, session_id=? WHERE id=?",
                (now, body[:2000], icon, needs[:1000], profile or current_profile(), current_session_id(session_id), existing["id"]))
            conn.execute("COMMIT")
            row = conn.execute("SELECT * FROM ideas WHERE id=?", (existing["id"],)).fetchone()
            return {**_row(row), "deduped": True}
        item = {
            "id": uuid.uuid4().hex,
            "created_at": now,
            "updated_at": now,
            "profile": profile or current_profile(),
            "session_id": current_session_id(session_id),
            "title": title[:200],
            "body": body[:2000],
            "icon": icon,
            "needs_from_user": needs[:1000],
            "status": "proposed",
        }
        conn.execute(
            "INSERT INTO ideas (id, created_at, updated_at, profile, session_id, title, body, icon, needs_from_user, status)"
            " VALUES (:id,:created_at,:updated_at,:profile,:session_id,:title,:body,:icon,:needs_from_user,:status)", item)
        conn.execute("COMMIT")
        return {**item, "deduped": False}
    finally:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        if own:
            conn.close()


def list_ideas(conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own = conn is None
    conn = conn or connect()
    try:
        rows = [_row(r) for r in conn.execute("SELECT * FROM ideas")]
    finally:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        if own:
            conn.close()
    rows.sort(key=lambda r: (_IDEA_SORT.get(str(r.get("status") or ""), 9), -float(r.get("updated_at") or 0)))
    return rows


def set_idea_status(idea_id: str, status: str, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    if status not in IDEA_STATUSES:
        raise ValueError(f"status must be one of {IDEA_STATUSES}")
    own = conn is None
    conn = conn or connect()
    try:
        _begin_write(conn)
        cur = conn.execute("UPDATE ideas SET status=?, updated_at=? WHERE id=?", (status, time.time(), idea_id))
        conn.execute("COMMIT")
        if not cur.rowcount:
            raise KeyError(idea_id)
        return _row(conn.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone())
    finally:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        if own:
            conn.close()


# ---------------------------------------------------------------- agent tool handlers

FEED_POST_SCHEMA = {
    "name": "feed_post",
    "description": (
        "Post a short plain-English feed card when something notable finished (goal done, refund landed, "
        "PR merged, decision needed). Past tense, 2-4 sentences, facts only. Optional embedded link card "
        "(link_title + link_subtitle + link_status pill + link_url)."),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Bold headline, past tense, under 90 chars."},
            "body": {"type": "string", "description": "2-4 plain sentences: what happened, facts only."},
            "icon": {"type": "string", "description": "Single emoji for the card (default 📝)."},
            "link_title": {"type": "string", "description": "Heading of the optional embedded link card."},
            "link_subtitle": {"type": "string", "description": "Subtitle line of the link card."},
            "link_status": {"type": "string", "description": "Short status pill text, e.g. 'Initiated', 'Merged'."},
            "link_url": {"type": "string", "description": "URL the link card opens."},
        },
        "required": ["title", "body"],
    },
}

IDEA_PROPOSE_SCHEMA = {
    "name": "idea_propose",
    "description": (
        "Propose a proactive idea the user has not asked for yet. Title in first person offer voice "
        "('I can ...' / 'Want me to ...?'). Body: context you already know + proposed action + exactly what "
        "you need from the user. If an idea with the same title is still proposed, it is updated, not duplicated."),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "First-person offer, e.g. 'I can keep X on schedule'."},
            "body": {"type": "string", "description": "Context + proposed action + what is needed from the user."},
            "needs_from_user": {"type": "string", "description": "Exactly what the user must provide or decide."},
            "icon": {"type": "string", "description": "Single emoji for the card (default 💡)."},
        },
        "required": ["title", "body", "needs_from_user"],
    },
}


def handle_feed_post(args: Dict[str, Any], session_id: str = "", **_: Any) -> str:
    try:
        item = feed_post(
            args.get("title", ""), args.get("body", ""), icon=args.get("icon", ""),
            link_title=args.get("link_title", ""), link_subtitle=args.get("link_subtitle", ""),
            link_status=args.get("link_status", ""), link_url=args.get("link_url", ""),
            session_id=session_id or None)
        return json.dumps({"ok": True, "id": item["id"], "profile": item["profile"], "session_id": item["session_id"]})
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


def handle_idea_propose(args: Dict[str, Any], session_id: str = "", **_: Any) -> str:
    try:
        item = idea_propose(
            args.get("title", ""), args.get("body", ""), args.get("needs_from_user", ""),
            icon=args.get("icon", ""), session_id=session_id or None)
        return json.dumps({"ok": True, "id": item["id"], "status": item["status"], "deduped": item["deduped"],
                           "profile": item["profile"]})
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


FEED_READ_SCHEMA = {
    "name": "feed_read",
    "description": "Read the shared Feed (recent cards from all agents + completed goals). Use to see what other agents reported and the user's thumbs up/down.",
    "parameters": {"type": "object", "properties": {
        "limit": {"type": "integer", "description": "Max cards (default 30)."},
        "profile": {"type": "string", "description": "Only cards from this profile (optional)."},
        "query": {"type": "string", "description": "Case-insensitive substring filter on title/body (optional)."},
    }},
}

IDEAS_READ_SCHEMA = {
    "name": "ideas_read",
    "description": "Read Ideas proposed to the user (status proposed/accepted/dismissed/done). Check before proposing a duplicate, and pick up ideas the user accepted.",
    "parameters": {"type": "object", "properties": {
        "status": {"type": "string", "description": "Filter: proposed|accepted|dismissed|done (optional, default all)."},
        "profile": {"type": "string", "description": "Only ideas from this profile (optional)."},
        "query": {"type": "string", "description": "Case-insensitive substring filter on title/body (optional)."},
    }},
}

IDEA_UPDATE_SCHEMA = {
    "name": "idea_update",
    "description": "Set an idea's status (done when you finished an accepted idea; dismissed when it no longer applies). Do not set accepted — only the user does.",
    "parameters": {"type": "object", "properties": {
        "id": {"type": "string", "description": "Idea id from ideas_read."},
        "status": {"type": "string", "description": "done|dismissed|proposed"},
    }, "required": ["id", "status"]},
}


def _match(item: Dict[str, Any], query: str) -> bool:
    q = (query or "").lower()
    return not q or q in str(item.get("title") or "").lower() or q in str(item.get("body") or "").lower()


def handle_feed_read(args: Dict[str, Any], **_: Any) -> str:
    try:
        limit = int(args.get("limit") or 30)
        res = merged_feed(limit=max(limit * 3, 100))
        items = [i for i in res["items"] if (not args.get("profile") or i.get("profile") == args["profile"])
                 and _match(i, args.get("query", ""))][:limit]
        return json.dumps({"ok": True, "count": len(items), "items": items, "errors": res.get("errors", [])}, default=str)
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


def handle_ideas_read(args: Dict[str, Any], **_: Any) -> str:
    try:
        st = args.get("status")
        items = [i for i in list_ideas() if (not st or i.get("status") == st)
                 and (not args.get("profile") or i.get("profile") == args["profile"])
                 and _match(i, args.get("query", ""))]
        return json.dumps({"ok": True, "count": len(items), "items": items}, default=str)
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


def handle_idea_update(args: Dict[str, Any], **_: Any) -> str:
    try:
        status = args.get("status", "")
        if status == "accepted":
            return json.dumps({"error": "only the user can accept an idea"})
        item = set_idea_status(args.get("id", ""), status)
        return json.dumps({"ok": True, "id": item["id"], "status": item["status"]})
    except KeyError as exc:
        return json.dumps({"error": f"idea not found: {exc}"})
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
