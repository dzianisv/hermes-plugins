"""feed-page: Muse-style Feed dashboard page + the ``muse`` toolset (feed_post, idea_propose).

The dashboard backend lives in dashboard/plugin_api.py; both tools and both pages share
dashboard/muse_store.py (one SQLite at ~/.hermes/muse.db for every profile).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_STORE_PATH = Path(__file__).resolve().parent / "dashboard" / "muse_store.py"


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


def register(ctx):  # noqa: D401 - Hermes plugin entry point
    store = _load_store()
    ctx.register_tool(name="feed_post", toolset="muse", schema=store.FEED_POST_SCHEMA,
                      handler=store.handle_feed_post, emoji="📰",
                      description="Post a plain-English feed card about something that finished.")
    ctx.register_tool(name="idea_propose", toolset="muse", schema=store.IDEA_PROPOSE_SCHEMA,
                      handler=store.handle_idea_propose, emoji="💡",
                      description="Propose a proactive idea for the user (first-person offer).")
    ctx.register_tool(name="feed_read", toolset="muse", schema=store.FEED_READ_SCHEMA,
                      handler=store.handle_feed_read, emoji="📰",
                      description="Read recent feed cards from all agents and completed goals.")
    ctx.register_tool(name="ideas_read", toolset="muse", schema=store.IDEAS_READ_SCHEMA,
                      handler=store.handle_ideas_read, emoji="💡",
                      description="Read proposed/accepted ideas; avoid duplicates, pick up accepted ones.")
    ctx.register_tool(name="idea_update", toolset="muse", schema=store.IDEA_UPDATE_SCHEMA,
                      handler=store.handle_idea_update, emoji="💡",
                      description="Mark an idea done or dismissed (never accepted).")
