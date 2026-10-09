"""Contract tests for feed-page / ideas-page (shared muse_store + FastAPI routers + tool handlers).

Every test points MUSE_DB_PATH at a throwaway database; the goal-merge test builds a throwaway
state.db holding a real ``goal:`` row copied read-only from this machine's ~/.hermes/state.db.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
PLUGINS_ROOT = PLUGIN.parent

SESSIONS_DDL = (
    "CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, source TEXT, chat_id TEXT, thread_id TEXT, "
    "chat_type TEXT, profile_name TEXT, started_at REAL, last_activity_at REAL, archived INTEGER, parent_session_id TEXT)"
)
META_DDL = "CREATE TABLE state_meta (key TEXT PRIMARY KEY, value TEXT)"


def _import(path: Path, name: str):
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSE_DB_PATH", str(tmp_path / "muse.db"))
    monkeypatch.setenv("MUSE_PLUGINS_HOME", str(PLUGINS_ROOT.parent))  # ~/.hermes -> real goals-page helpers
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
    store = _import(PLUGIN / "dashboard" / "muse_store.py", "hermes_muse_store")
    feed_api = _import(PLUGIN / "dashboard" / "plugin_api.py", "hermes_dashboard_plugin_feed-page")
    ideas_api = _import(PLUGINS_ROOT / "ideas-page" / "dashboard" / "plugin_api.py", "hermes_dashboard_plugin_ideas-page")
    assert feed_api.store is store and ideas_api.store is store
    app = FastAPI()
    app.include_router(feed_api.router, prefix="/api/plugins/feed-page")
    app.include_router(ideas_api.router, prefix="/api/plugins/ideas-page")
    return {"store": store, "client": TestClient(app), "tmp": tmp_path}


def make_state_home(tmp_path: Path, rows) -> Path:
    home = tmp_path / "hermes-state"
    db = home / "state.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(SESSIONS_DDL)
    conn.execute(META_DDL)
    for k, v in rows:
        conn.execute("INSERT INTO state_meta VALUES (?,?)", (k, v))
        sid = k.split(":", 1)[1]
        conn.execute("INSERT INTO sessions (id, title, source) VALUES (?,?,?)", (sid, "title " + sid[:6], "telegram"))
    conn.commit()
    conn.close()
    return home


# ---------------------------------------------------------------- tool handlers

def test_feed_post_handler_writes_row(env, monkeypatch):
    store = env["store"]
    monkeypatch.setenv("HERMES_HOME", "/Users/x/.hermes/profiles/cto")
    out = json.loads(store.handle_feed_post({
        "title": "Neon refunded every invoice in full",
        "body": "Neon support confirmed processed refunds for four invoices. The card stays until the account admin removes it.",
        "icon": "🧾", "link_title": "Neon refund ticket 01032640", "link_subtitle": "org Vibe Technologies",
        "link_status": "Initiated", "link_url": "https://example.com/t/1"}, session_id="sess-1", task_id="t1"))
    assert out["ok"] and out["profile"] == "cto" and out["session_id"] == "sess-1"
    rows = store.list_feed()
    assert len(rows) == 1
    r = rows[0]
    assert r["title"].startswith("Neon refunded") and r["source"] == "tool" and r["link_status"] == "Initiated"
    assert r["reaction"] is None and r["icon"] == "🧾"


def test_feed_post_requires_title_and_body(env):
    store = env["store"]
    assert "error" in json.loads(store.handle_feed_post({"title": "", "body": "x"}))
    assert "error" in json.loads(store.handle_feed_post({"title": "x", "body": " "}))
    assert store.list_feed() == []


def test_idea_propose_handler_writes_row_and_dedupes(env):
    store = env["store"]
    a = json.loads(store.handle_idea_propose({
        "title": "Want me to silence your noisiest senders?",
        "body": "Redfin sent 29 alerts this week. I can unsubscribe and filter them.",
        "needs_from_user": "Confirm the sender list.", "icon": "🗑️"}, session_id="s-a"))
    assert a["ok"] and a["status"] == "proposed" and a["deduped"] is False
    b = json.loads(store.handle_idea_propose({
        "title": "Want me to silence your noisiest senders?",
        "body": "Redfin sent 31 alerts this week. I can unsubscribe and filter them.",
        "needs_from_user": "Confirm the sender list."}, session_id="s-b"))
    assert b["deduped"] is True and b["id"] == a["id"]
    rows = store.list_ideas()
    assert len(rows) == 1 and rows[0]["body"].startswith("Redfin sent 31") and rows[0]["session_id"] == "s-b"
    # Once accepted, a same-title proposal is a new idea (dedupe only against status 'proposed').
    store.set_idea_status(a["id"], "accepted")
    c = json.loads(store.handle_idea_propose({"title": "Want me to silence your noisiest senders?", "body": "again", "needs_from_user": "ok"}))
    assert c["deduped"] is False and c["id"] != a["id"]
    assert len(store.list_ideas()) == 2


def test_idea_propose_requires_needs_from_user(env):
    assert "error" in json.loads(env["store"].handle_idea_propose({"title": "t", "body": "b", "needs_from_user": ""}))


# ---------------------------------------------------------------- endpoints

def test_feed_endpoints_and_reaction_toggle(env):
    store, client = env["store"], env["client"]
    item = store.feed_post("PR merged", "The PR landed on master and CI is green.")
    r = client.get("/api/plugins/feed-page/feed?limit=50")
    assert r.status_code == 200
    payload = r.json()
    assert "items" in payload and "errors" in payload
    mine = [x for x in payload["items"] if x["id"] == item["id"]]
    assert mine and mine[0]["reaction"] is None

    assert client.post(f"/api/plugins/feed-page/feed/{item['id']}/reaction", json={"reaction": "up"}).json()["stored"] == "feed_items"
    assert [x for x in client.get("/api/plugins/feed-page/feed").json()["items"] if x["id"] == item["id"]][0]["reaction"] == "up"
    assert client.post(f"/api/plugins/feed-page/feed/{item['id']}/reaction", json={"reaction": None}).status_code == 200
    assert [x for x in client.get("/api/plugins/feed-page/feed").json()["items"] if x["id"] == item["id"]][0]["reaction"] is None
    assert client.post(f"/api/plugins/feed-page/feed/{item['id']}/reaction", json={"reaction": "meh"}).status_code == 400
    assert client.get("/api/plugins/feed-page/feed?limit=0").status_code == 422


def test_ideas_endpoints_status_and_order(env):
    store, client = env["store"], env["client"]
    p1 = store.idea_propose("I can A", "body", "need")
    time.sleep(0.01)
    p2 = store.idea_propose("I can B", "body", "need")
    time.sleep(0.01)
    p3 = store.idea_propose("I can C", "body", "need")
    p4 = store.idea_propose("I can D", "body", "need")
    assert client.post(f"/api/plugins/ideas-page/ideas/{p2['id']}/status", json={"status": "accepted"}).json()["status"] == "accepted"
    assert client.post(f"/api/plugins/ideas-page/ideas/{p3['id']}/status", json={"status": "dismissed"}).status_code == 200
    assert client.post(f"/api/plugins/ideas-page/ideas/{p4['id']}/status", json={"status": "done"}).status_code == 200
    assert client.post(f"/api/plugins/ideas-page/ideas/{p1['id']}/status", json={"status": "bogus"}).status_code == 400
    assert client.post("/api/plugins/ideas-page/ideas/nope/status", json={"status": "accepted"}).status_code == 404
    r = client.get("/api/plugins/ideas-page/ideas")
    assert r.status_code == 200
    statuses = [x["status"] for x in r.json()["items"]]
    assert statuses == ["proposed", "accepted", "done", "dismissed"]
    assert r.json()["errors"] == []


# ---------------------------------------------------------------- goal-derived feed

def test_goal_done_rows_merge_into_feed_and_reactions_persist(env):
    store, client = env["store"], env["client"]
    fixture = json.loads((HERE / "fixture_done_goal_row.json").read_text())
    rows = [(r["key"], r["value"]) for r in fixture]
    assert rows and json.loads(rows[0][1])["status"] == "done", "fixture must hold a real done goal row"
    goal = json.loads(rows[0][1])
    sid = rows[0][0][len("goal:"):]
    state_home = make_state_home(env["tmp"], rows)

    errors = []
    items = store.goal_feed_items(state_home, errors)
    assert errors == []
    assert len(items) == 1
    it = items[0]
    assert it["id"] == f"goal:default:{sid}" and it["source"] == "goal" and it["icon"] == "✅"
    assert it["body"] == goal["last_reason"]
    assert len(it["title"]) <= 90 and it["title"].startswith(goal["goal"][:40])
    assert it["created_at"] == pytest.approx(goal["last_turn_at"])

    merged = store.merged_feed(100, state_home)
    assert [x["id"] for x in merged["items"]] == [it["id"]]
    assert merged["errors"] == []
    # Nothing was persisted into feed_items.
    assert store.list_feed() == []

    # Reaction on a synthetic item goes to the reactions table and shows on the next merge.
    r = client.post(f"/api/plugins/feed-page/feed/{it['id']}/reaction", json={"reaction": "down"})
    assert r.status_code == 200 and r.json()["stored"] == "reactions"
    merged = store.merged_feed(100, state_home)
    assert merged["items"][0]["reaction"] == "down"

    # Stored + goal items sort together by created_at desc.
    newer = store.feed_post("Newer card", "Posted just now.")
    merged = store.merged_feed(100, state_home)
    assert [x["id"] for x in merged["items"]] == [newer["id"], it["id"]]


def test_goal_merge_degrades_with_error_when_goals_page_missing(env, monkeypatch):
    store = env["store"]
    sys.modules.pop("hermes_goals_page_api_for_muse", None)
    monkeypatch.setenv("MUSE_PLUGINS_HOME", str(env["tmp"] / "nowhere"))
    errors = []
    assert store.goal_feed_items(None, errors) == []
    assert errors and "goals-page import failed" in errors[0]
    sys.modules.pop("hermes_goals_page_api_for_muse", None)


# ---------------------------------------------------------------- concurrency

def test_get_survives_concurrent_writer_holding_txn(env):
    store, client = env["store"], env["client"]
    item = store.feed_post("Card", "Body text.")
    store.idea_propose("I can X", "body", "need")
    db = Path(store.db_path())

    # A second connection holding an open write transaction (WAL: readers proceed).
    w = sqlite3.connect(db, timeout=5, isolation_level=None)
    w.execute("BEGIN IMMEDIATE")
    w.execute("INSERT INTO feed_items (id, created_at, title, body, source) VALUES ('held', ?, 'held', 'held', 'tool')", (time.time(),))
    try:
        t0 = time.monotonic()
        r = client.get("/api/plugins/feed-page/feed")
        r2 = client.get("/api/plugins/ideas-page/ideas")
        dt = time.monotonic() - t0
        assert r.status_code == 200 and r2.status_code == 200
        ids = [x["id"] for x in r.json()["items"]]
        assert item["id"] in ids and "held" not in ids  # uncommitted write invisible
        assert len(r2.json()["items"]) == 1
        assert dt < 2.0, f"GET took {dt:.2f}s while writer held a txn"
    finally:
        w.execute("ROLLBACK")
        w.close()

    # Writer committing continuously while we read and write; our busy handler (3 s) must absorb it.
    stop = threading.Event()

    def writer():
        c = sqlite3.connect(db, timeout=5)
        i = 0
        while not stop.is_set():
            c.execute("INSERT OR REPLACE INTO reactions VALUES (?,?)", (f"goal:x:{i % 5}", "up"))
            c.commit()
            i += 1
            time.sleep(0.002)  # a real agent commits occasionally, not in a GIL-saturating spin
        c.close()

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        for _ in range(20):
            assert client.get("/api/plugins/feed-page/feed").status_code == 200
            assert client.post(f"/api/plugins/feed-page/feed/{item['id']}/reaction", json={"reaction": "up"}).status_code == 200
    finally:
        stop.set(); t.join(timeout=5)


# ---------------------------------------------------------------- read tools

def test_read_tools_round_trip(env):
    store = env["store"]
    store.handle_feed_post({"title": "Neon refunded every invoice", "body": "All four invoices refunded."}, session_id="s-1")
    store.handle_feed_post({"title": "PR 2234 merged", "body": "Gemma 4 shipped."}, session_id="s-2")
    r = json.loads(store.handle_feed_read({"query": "refunded every invoice"}))
    assert r["ok"] and r["count"] == 1 and r["items"][0]["title"] == "Neon refunded every invoice"
    r = json.loads(store.handle_feed_read({"limit": 1}))
    assert r["count"] == 1

    a = json.loads(store.handle_idea_propose({"title": "I can X", "body": "b", "needs_from_user": "n"}))
    b = json.loads(store.handle_idea_propose({"title": "I can Y", "body": "b", "needs_from_user": "n"}))
    store.set_idea_status(b["id"], "accepted")
    r = json.loads(store.handle_ideas_read({"status": "accepted"}))
    assert r["count"] == 1 and r["items"][0]["id"] == b["id"]
    assert json.loads(store.handle_ideas_read({}))["count"] == 2

    # agent may finish or dismiss, never accept
    assert "error" in json.loads(store.handle_idea_update({"id": a["id"], "status": "accepted"}))
    u = json.loads(store.handle_idea_update({"id": b["id"], "status": "done"}))
    assert u["ok"] and u["status"] == "done"
    assert "error" in json.loads(store.handle_idea_update({"id": "nope", "status": "done"}))
