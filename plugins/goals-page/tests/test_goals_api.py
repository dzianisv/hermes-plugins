"""Contract tests for the goals-page backend.

Fixtures are real ``state_meta`` rows copied read-only from this machine's state.db files
(no synthetic goals). Each test builds a throwaway WAL database, so nothing touches live
stores.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dashboard"))
import plugin_api as api  # noqa: E402

SESSIONS_DDL = (
    "CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, source TEXT, chat_id TEXT, thread_id TEXT, "
    "chat_type TEXT, profile_name TEXT, started_at REAL, last_activity_at REAL, archived INTEGER, parent_session_id TEXT)"
)
META_DDL = "CREATE TABLE state_meta (key TEXT PRIMARY KEY, value TEXT)"


def _load(name: str):
    return json.loads((HERE / name).read_text())


def make_home(tmp_path: Path, profiles: dict) -> Path:
    """profiles: {name: [ (key, value) ... ]} ; 'default' goes to home/state.db."""
    home = tmp_path / "hermes"
    for name, rows in profiles.items():
        db = home / "state.db" if name == "default" else home / "profiles" / name / "state.db"
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


def test_real_rows_roundtrip_and_cleared_is_not_done(tmp_path):
    default_rows = [(r["key"], r["value"]) for r in _load("fixture_default_rows.json")]
    cleared_rows = [(r["key"], r["value"]) for r in _load("fixture_cleared_row.json")]
    assert cleared_rows, "fixture must hold a real cleared row"
    home = make_home(tmp_path, {"default": default_rows, "product-lead-agentpod": cleared_rows})

    payload = api.build_payload(home)
    by_profile = {p["profile"]: p for p in payload["profiles"]}
    assert by_profile["default"]["count"] == len(default_rows)
    assert by_profile["default"]["error"] is None
    assert by_profile["product-lead-agentpod"]["count"] == len(cleared_rows)

    cleared = [g for g in payload["goals"] if g["status"] == "cleared"]
    assert cleared and all(g["group"] == "cleared" for g in cleared)
    assert payload["counts"].get("done", 0) == sum(1 for g in payload["goals"] if g["status"] == "done")
    # Row shape the UI relies on.
    g0 = payload["goals"][0]
    for key in ("profile", "session_id", "objective", "status", "group", "contract", "subgoals", "gates", "sub_status", "session_title"):
        assert key in g0


def test_resume_supersedes_old_blocked_signal():
    """resume() keeps last_verdict=blocked in GoalState; only an active/paused goal with a
    blocked verdict is flagged, and a done/cleared goal never is."""
    base = {"goal": "x", "last_verdict": "blocked", "last_reason": "needs user card check"}
    assert api.attention({**base, "status": "paused"}) == "needs user card check"
    assert api.attention({**base, "status": "active"}) == "needs user card check"
    assert api.attention({**base, "status": "done"}) is None
    assert api.attention({**base, "status": "cleared"}) is None
    # Verdict moved on after resume + a new turn: no longer flagged.
    assert api.attention({"goal": "x", "status": "active", "last_verdict": "continue"}) is None


def test_classify_groups_are_factual():
    assert api.classify({"status": "active"}) == "active"
    assert api.classify({"status": "active", "waiting_until": time.time() + 60}) == "waiting"
    assert api.classify({"status": "active", "waiting_on_delegations": 2}) == "waiting"
    assert api.classify({"status": "paused", "paused_reason": "judge transport failures"}) == "paused"
    assert api.classify({"status": "done"}) == "done"
    assert api.classify({"status": "cleared"}) == "cleared"


def test_per_profile_failure_is_visible_not_silent(tmp_path):
    rows = [(r["key"], r["value"]) for r in _load("fixture_default_rows.json")]
    home = make_home(tmp_path, {"default": rows, "broken": []})
    # Corrupt one profile's DB: drop the table the reader needs.
    broken = home / "profiles" / "broken" / "state.db"
    conn = sqlite3.connect(broken); conn.execute("DROP TABLE state_meta"); conn.commit(); conn.close()
    payload = api.build_payload(home)
    by_profile = {p["profile"]: p for p in payload["profiles"]}
    assert by_profile["default"]["error"] is None and by_profile["default"]["count"] == len(rows)
    assert by_profile["broken"]["error"] and by_profile["broken"]["error"].startswith("sqlite:")
    assert len(payload["goals"]) == len(rows)


def test_reader_is_read_only_and_survives_concurrent_writes(tmp_path):
    rows = [(r["key"], r["value"]) for r in _load("fixture_default_rows.json")]
    home = make_home(tmp_path, {"default": rows})
    db = home / "state.db"

    # Writes are rejected on the reader's connection.
    conn = api._ro_connect(db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO state_meta VALUES ('goal:zzz','{}')")
    conn.close()

    # A writer hammering + checkpointing while we poll: reads stay bounded and clean.
    stop = threading.Event()

    def writer():
        w = sqlite3.connect(db, timeout=5)
        i = 0
        while not stop.is_set():
            w.execute("INSERT OR REPLACE INTO state_meta VALUES (?,?)", (f"heartbeat:w{i%5}", json.dumps({"i": i})))
            w.commit()
            if i % 20 == 0:
                w.execute("PRAGMA wal_checkpoint(PASSIVE)")
            i += 1
        w.close()

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        worst = 0.0
        for _ in range(30):
            t0 = time.monotonic()
            r = api.read_profile_goals("default", db)
            worst = max(worst, time.monotonic() - t0)
            assert r["error"] is None, r["error"]
            assert len(r["goals"]) == len(rows)
    finally:
        stop.set(); t.join(timeout=5)
    assert worst < 1.0, f"read took {worst:.2f}s under write load"
