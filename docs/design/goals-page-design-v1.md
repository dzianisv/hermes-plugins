# Goals page for Hermes: a Muse-style view of what the agent is working on

Status: design draft, 2026-10-08. Owner: Alfred (Default profile). Critique: gpt-6-astra.

## The problem in one paragraph

Hermes already has goals and heartbeats per session. The agent can set its own goal with acceptance criteria, a judge audits completion, and heartbeats re-enter idle sessions. What is missing is a place to *see* it. Today the only views are the `/goal` slash command inside one chat, a small status chip in the desktop composer, and my hourly supervisor report. Den has 50+ sessions across three profiles. He cannot answer "what is the agent working on right now, what is blocked on me, what finished today" without asking me. Meta's Muse answers that with one screen.

## What Muse does (from Den's screenshots, 2026-10-08)

- A **Goals** tab in the bottom nav, next to chat, feed, ideas, library.
- Two sections on that page:
  - **Tracking** (green): things the agent is watching or carrying forward in the background. Each row is a title plus one gray line with the latest progress or the thing it needs from you ("waiting on your approval", "forward me one of their emails").
  - **Goals** (blue): the user's bigger outcomes ("buy a 2020 BMW 430i convertible under KBB").
- Each row: checkbox, title, a two-line sub-status, a three-dot menu. No timestamps. A "+" to add. "Show more" when the list is long.
- Tapping a goal opens a detail page: description, Artifacts, and an Activity log with dated entries ("Oct 6: daily search launched; first pass found no matching cars").
- The agent avatar at the top carries a status badge, "Needs approval", which is the global "something is waiting on you" signal.
- Every goal has a **side chat** of its own (the drawer lists them). The goal and the conversation are the same object.

The thing Muse gets right: the goal is the unit, not the chat. The chat is where you talk about the goal.

## What already exists (checked 2026-10-08)

Hermes upstream (`NousResearch/hermes-agent`, main):
- `hermes_cli/goals.py`: `GoalState` per session in `state_meta` under `goal:<session_id>`, with status (`active | paused | done | cleared`), `last_verdict`, `last_reason`, `contract` (outcome + verification), `waiting_*` fields, `source` (`user | agent`).
- `hermes_cli/heartbeat.py`: `HeartbeatState` under `heartbeat:<session_id>`.
- Desktop app: `apps/desktop/src/store/goals.ts` tracks the goal of the *active* session only, by parsing `/goal` text output. `session-control-goal.tsx` renders a chip in the composer. That is the whole UI. There is no cross-session list, no history, no "waiting on you" view.
- Dashboard plugin system: a plugin ships `dashboard/manifest.json` with `tab`, `entry`, and an optional `api` (FastAPI router mounted at `/api/plugins/<id>/`). `hermes-achievements` and `kanban` are working examples.
- Desktop plugin SDK: a single ESM `plugin.js` under `~/.hermes/desktop-plugins/<id>/` can register a full page (`ROUTES_AREA` + `SIDEBAR_NAV_AREA`), call the gateway RPC, and call its own `/api/plugins/<id>` backend via `ctx.rest`.
- Open PRs touching goals: 15 (ours #134448 among them). None adds a goals page. #107583 adds a crash-recovery control to the existing desktop goal card.

OpenClaw (`openclaw/openclaw`, docs/tools/goal.md): one durable goal per session, `/goal start|pause|resume|block|complete|clear`, three model tools (`get_goal`, `create_goal`, `update_goal`), a context line injected every turn, status in the TUI footer and a "Goal composer" in the Control UI. Also per-session. No cross-session goals page, no tracking/goal split, no activity log per goal.

Conclusion: nobody has the Muse view. The data is already in Hermes. This is a read-mostly UI plugin plus a small backend, not a new goal engine.

## Scope

In:
1. A **Goals page** in the Hermes desktop app and dashboard, listing goals across *all sessions of all profiles on this machine*.
2. The **Tracking / Goals** split, derived from data we already have (rule below), no new user burden.
3. A **detail view** per goal: objective, acceptance criteria, verification, status, the judge's last verdict and reason, an **Activity** log built from the goal's own history, and a link that opens the owning session.
4. A **Needs you** signal: a count of goals waiting on the user, in the sidebar nav row.
5. The minimal backend to serve this fast: one endpoint that reads every profile's `state.db`.

Out (for now): creating goals from the page, editing contracts from the page, mobile app, pushing a Telegram digest from the page (the supervisor cron already does that), changing how goals are judged or how heartbeats fire.

## Design

### Where it lives

A Hermes plugin named `goals-page`, structured like `hermes-achievements`:

```
~/.hermes/plugins/goals-page/
  plugin.yaml                 # name, version, description, no hooks needed
  __init__.py                 # register(ctx): nothing to hook; presence enables the backend
  dashboard/manifest.json     # tab: /goals, entry: dist/index.js, api: plugin_api.py
  dashboard/plugin_api.py     # FastAPI router: GET /goals, GET /goals/{profile}/{session_id}
  dashboard/src/              # TS source; dist/ is built
~/.hermes/desktop-plugins/goals-page/plugin.js   # desktop page + sidebar row; calls ctx.rest
```

Why a plugin and not a core change: Den wants it now and the upstream review queue is long (15 open goal PRs). A plugin ships today, hot-reloads, and can be upstreamed later as a bundled plugin if it proves useful. It also keeps the goal engine untouched.

### Data: one read model

`GET /api/plugins/goals-page/goals` returns a list of goal rows, one per `goal:<sid>` key, across every profile's `state.db` (default plus `~/.hermes/profiles/*/state.db`). Each row:

```
{
  profile, session_id, session_title, origin (platform, chat_id, thread_id),
  objective, status,                      # from GoalState
  section: "tracking" | "goals" | "done", # derived, rule below
  needs_user: bool, needs_user_reason,    # derived
  sub_status,                             # one line, rule below
  contract: {outcome, verification}, source, turns_used, max_turns,
  last_verdict, last_reason, waiting_reason, waiting_until,
  created_at, last_turn_at, last_activity_at,
  heartbeat: {interval, last_fired_at, enabled} | null
}
```

Reading is cheap: it is one `SELECT key, value FROM state_meta WHERE key LIKE 'goal:%'` per profile plus a join to `sessions` for title and origin. Open the DBs read-only (`?mode=ro`) so the page can never corrupt a live gateway's store. Cache for 5 seconds.

### Section rule (Tracking vs Goals vs Done)

Muse decides this by the kind of goal. We do not have that field, so we derive:

- **Done**: `status in (done, cleared)`. Shown in a collapsed "Completed" list, newest first, last 7 days.
- **Tracking**: active or paused goals that are *waiting*: `waiting_*` set, or `last_verdict == "blocked"`, or `paused_reason` set, or the session has an active heartbeat and the goal's `last_verdict == "wait"`. Also any goal whose owning session is a cron/background session. These are the "the agent is carrying this, nothing to do right now" rows. Green.
- **Goals**: everything else that is active: the agent is working on it or should be. Blue.

This is a heuristic and it will be wrong sometimes. The detail view shows the raw status so the user can tell. If the heuristic proves bad, the fix is a `kind` field on `GoalState` upstream, not more rules here.

### Needs you

`needs_user = true` when the judge's last verdict is `blocked` and the reason names the user, or `waiting_reason` mentions approval, permission, login, decision, or the last assistant message in that session ends with a question to the user and no user reply followed. The sidebar nav row shows the count as a badge: "Goals · 7". This is the Muse "Needs approval" signal, moved to where the Hermes app already puts counts.

The word-matching part is weak. The strong signal we should add later is a `waiting_on: "user"` value in `GoalState`, which the judge already has enough information to set. That is a one-line upstream change and it is listed under follow-ups.

### Sub-status line

One line, in this priority: `needs_user_reason` → `waiting_reason` → judge `last_reason` → first line of the last assistant message. Trimmed to 140 characters. This is what Muse shows under each title and it is the most useful thing on the page.

### Detail view and Activity

`GET /goals/{profile}/{session_id}` returns the row plus an `activity` list. Activity is built from the session's messages, not from a new log:

- `goal(create)` tool call → "Goal set" with the acceptance criteria.
- Each judge verdict change (we store only the last one, so the backend scans assistant messages for `goal(complete)` calls and their results, plus heartbeat ticks) → "Judge: continue / blocked / done — reason".
- Tool calls that produced artifacts (files written, PRs opened, commits) → "Artifact: PR #123" with the link. Detected from the tool result text with the same regexes the supervisor script already uses.
- User messages in the session → "You: …" (first line).
- Supervisor pushes (messages starting with `[supervisor:`) → "Supervisor: …".

Entries are dated. Oldest first, newest at the bottom, same as Muse. A "Open session" button navigates to the chat (`host.navigate('/chat/<sid>')` in desktop; the dashboard links to its session view).

### Desktop plugin (plugin.js)

- Registers `ROUTES_AREA` `/goals` and a `SIDEBAR_NAV_AREA` row "Goals" with codicon `target`, below Artifacts.
- Page uses `useQuery` with `refetchInterval: 10_000` against `ctx.rest('/goals')`.
- Layout, top to bottom: header "Goals" with a profile filter (All / default / agentpod / vibebrowser), then **Needs you** (if any), **Goals**, **Tracking**, **Completed (7 days)**. Each row: status dot, title, sub-status, profile chip, "⋮" with "Open session" and "Copy session id". Click row → detail drawer on the right.
- Uses the SDK components (`StatusDot`, `Badge`, `ScrollArea`, `EmptyState`) and theme vars only.

### Dashboard tab

Same component tree, built to `dist/index.js` with the plugin build the achievements plugin uses, so the web dashboard gets the same page. If the dashboard build chain turns out to be heavy, ship the desktop plugin first and the dashboard tab second; both read the same endpoint.

## What this does not change

- How goals are created, judged, or completed. The `goal` tool, the judge, `/goal`, and the heartbeat loop are untouched.
- The supervisor cron. It keeps running and keeps pushing sessions. The page is the pull view; the cron is the push.
- Any gateway. The backend is mounted only in the gateway that runs the dashboard (default), and it reads other profiles' DBs read-only.

## Acceptance criteria

1. Open the desktop app, click "Goals" in the sidebar: a page lists every goal from all three goal-enabled profiles, grouped Needs you / Goals / Tracking / Completed, each with a one-line sub-status. Verified against the same rows in `state_meta` by a script that diffs the two.
2. Click a goal: the detail shows objective, acceptance criteria, verification, status, last verdict + reason, and an Activity list with at least the "Goal set" entry and every user message, dated. "Open session" lands in the right chat.
3. The sidebar badge count equals the number of rows with `needs_user = true`, and for the current known cases (Neon refund waiting on Den's card check, Gemma 4 PR waiting on review) the classification is right.
4. Backend endpoint answers in under 300 ms warm with 60 goals across three DBs; read-only open proven by `PRAGMA query_only` in the connection.
5. Plugin loads with no error toast; `hermes plugins list` shows it enabled; a gateway restart is not required for the desktop page (hot reload) and is required once for the backend, done last.
6. Contract tests: section rule, needs-user rule, sub-status priority, and activity extraction, each with real rows copied from today's `state.db` files (no synthetic rows).

## Follow-ups (not in this change)

- Upstream: `GoalState.kind` (`tracking | goal`) and `waiting_on: user | process | time | delegation`, set by the judge. Both remove heuristics here.
- Create a goal from the page (becomes `/goal` in the chosen session via gateway RPC).
- A Telegram "Needs you" digest is already the supervisor cron; if the page proves the classification, the cron should read the same endpoint instead of its own script.
- Mobile: Hermes has no mobile app; the dashboard tab is the phone path.

## Open questions for the critic

1. Is deriving Tracking/Goals good enough to ship, or should we add `kind` upstream first and wait?
2. Is a desktop plugin plus a dashboard tab one artifact too many for v1? The dashboard reaches the phone, which is where Den took the Muse screenshots.
3. Activity reconstructed from messages vs. a proper append-only `goal_events` table: the table is cleaner but needs the judge to write to it, which is a core change.
4. Reading other profiles' SQLite files from the default gateway: safe enough read-only, or should each gateway expose its own endpoint and the page fan out?
