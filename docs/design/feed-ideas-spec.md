# Feed + Ideas plugin spec (Muse parity)

Reference UI (Meta Muse app):
- Feed: list of cards; each = icon, bold title, body (2-4 sentences, plain English, past tense: what happened), optional embedded link card (heading + subtitle + status pill), action row thumbs-up / thumbs-down / "Discuss", relative timestamp ("10 hr").
- Ideas: list of cards; each = emoji icon, title in first-person offer voice ("I can ...", "Want me to ...?"), body explaining context + proposed action + what is needed from the user; green check badge when accepted/done; no inline buttons, tap opens detail with Accept / Dismiss / Discuss.

Existing precedent to copy exactly: ~/.hermes/plugins/goals-page (dashboard-only plugin; manifest keys name,label,icon,tab{path,position},entry,css,api; plugin_api.py exposes FastAPI `router`, mounted at /api/plugins/<name>/; frontend dist/index.js IIFE uses window.__HERMES_PLUGINS__ SDK (React, fetchJSON, Card, Button); CSS color: inherit). Read its files first, including tests/test_plugin_api.py.

## Storage
Single shared SQLite: `~/.hermes/muse.db` (Path.home()/.hermes/muse.db — NOT HERMES_HOME, because profiles live in ~/.hermes/profiles/<p> and must write to the same DB). WAL mode, busy_timeout 3000.
Tables:
- feed_items(id TEXT PK, created_at REAL, profile TEXT, session_id TEXT, title TEXT, body TEXT, icon TEXT, link_title TEXT, link_subtitle TEXT, link_status TEXT, link_url TEXT, reaction TEXT NULL ('up'|'down'), source TEXT ('tool'|'goal'))
- ideas(id TEXT PK, created_at REAL, updated_at REAL, profile TEXT, session_id TEXT, title TEXT, body TEXT, icon TEXT, needs_from_user TEXT, status TEXT ('proposed'|'accepted'|'dismissed'|'done'))

## Agent tools (registered in plugin __init__.py via ctx.register_tool, toolset "muse")
- `feed_post(title, body, icon?, link_title?, link_subtitle?, link_status?, link_url?)` — "Post a short plain-English feed card when something notable finished (goal done, refund landed, PR merged, decision needed). Past tense, 2-4 sentences, facts only." Record profile (from HERMES_HOME basename, or 'default') and session_id (from ctx / env HERMES_SESSION_ID if available; else null).
- `idea_propose(title, body, needs_from_user, icon?)` — "Propose a proactive idea the user has not asked for yet. Title in first person offer voice ('I can ...' / 'Want me to ...?'). Body: context you already know + proposed action + exactly what you need from the user." Dedupe: if an idea with same title and status 'proposed' exists, update it instead of inserting.
Look at plugins/google_meet/__init__.py and plugins/spotify/__init__.py in ~/.hermes/hermes-agent for the register_tool pattern (schema dict, handler returning JSON string).

## Auto-feed from goals
On GET /feed, merge in synthetic items derived from goal rows with status done across ~/.hermes/state.db and ~/.hermes/profiles/*/state.db (reuse goals-page/dashboard/plugin_api.py helpers by importing via importlib from its path; if import fails, degrade and report in `errors`). Title = goal text truncated 90 chars, body = last_reason, icon "✅", source 'goal', id "goal:<profile>:<session_id>". Not persisted; reactions on them are persisted in a small `reactions(item_id PK, reaction)` table.

## API (plugin_api.py, FastAPI router)
- GET /feed?limit=100 → {items:[...sorted created_at desc], errors:[]}
- POST /feed/{id}/reaction {reaction:'up'|'down'|null}
- GET /ideas → {items:[proposed first, then accepted, done, dismissed], errors:[]}
- POST /ideas/{id}/status {status}
All writes are tiny state changes only; no deletes.

## Dashboard
manifest tabs: Hermes manifest supports ONE tab per plugin → make TWO plugin dirs sharing one python package? Simpler: two plugins `feed-page` (tab /feed, icon "Newspaper", position after:goals... use "after:sessions") and `ideas-page` (tab /ideas, icon "Lightbulb"). Both import shared store from `~/.hermes/plugins/feed-page/dashboard/muse_store.py` (ideas-page imports by absolute path via importlib). Agent tools live in feed-page/__init__.py only (register both tools there); ideas-page/__init__.py register() is a no-op.
Feed UI: cards as in reference; Discuss → link `/chat?resume=<session_id>` when session_id present; thumbs toggle calls reaction API; relative time.
Ideas UI: cards as in reference; green check badge when status accepted/done; click → detail panel with Accept / Dismiss / Discuss buttons (Accept → status accepted; Dismiss → dismissed).

## Enable
Add `- feed-page` and `- ideas-page` under plugins.enabled in ~/.hermes/config.yaml (after `- goals-page`), AND in each profile config ~/.hermes/profiles/*/config.yaml that has a plugins.enabled list (so their agents get the tools). Do not touch other keys. Report which configs you edited.

## Verify (mandatory, real output)
1. Tests: `~/.hermes/hermes-agent/venv/bin/python -m pytest ~/.hermes/plugins/feed-page/tests -q` — cover: feed_post + idea_propose handlers write rows; idea dedupe; reaction/status endpoints; goal-derived feed merge against a throwaway state.db with one real-shaped goal row copied from ~/.hermes/state.db (sqlite3 -json "file:$HOME/.hermes/state.db?mode=ro" "select key,value from state_meta where key like 'goal:%' limit 1"); concurrent writer (second connection holding a write txn) does not break GET.
2. Tool registration: `cd ~/.hermes/hermes-agent && venv/bin/python -c "from hermes_cli.plugins import discover_plugins; discover_plugins(force=True); from tools.registry import registry; print([n for n in registry.list_names() if n in ('feed_post','idea_propose')])"` (adjust API names if they differ — inspect tools/registry.py).
3. Dashboard: restart `hermes dashboard` (standalone process on :9119; find pid with `pgrep -fl "hermes dashboard"`, kill it, relaunch `~/.hermes/hermes-agent/venv/bin/hermes dashboard --skip-build --no-open` in background with persist). Get token: `curl -s http://127.0.0.1:9119/ | grep -o '__HERMES_SESSION_TOKEN__[^;]*'`; header X-Hermes-Session-Token. Verify /api/dashboard/plugins/hub lists both tabs; GET both endpoints return 200 with real goal-derived items.
4. Screenshot both pages with headless Chrome: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --no-first-run --user-data-dir=$TMPDIR/chrome-prof --window-size=1400,1100 --virtual-time-budget=10000 --screenshot=$TMPDIR/feed.png http://127.0.0.1:9119/feed (and /ideas). Open the PNGs with vision to confirm cards render with visible text.
Never use browser_navigate on loopback (blocked). Never kill "Google Chrome" user process; only your headless instance. Never kill gateways.

## Output
Report: files created, configs edited, test output (counts), tool registration output, hub JSON excerpt, absolute PNG paths, any gaps. No secrets in output.
