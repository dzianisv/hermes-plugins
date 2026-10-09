(function () {
  "use strict";
  // goals-page dashboard plugin: current goals across all local profiles.
  // Design: https://app.notion.com/p/3f3ac25eb49f81028008ec3a19e80edf
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const h = React.createElement;
  const { useState, useEffect, useMemo } = SDK.hooks;
  const C = SDK.components || {};
  const Card = C.Card || (function (p) { return h("div", { className: "gp-card " + (p.className || "") }, p.children); });
  const Button = C.Button || (function (p) { return h("button", p, p.children); });

  const API = "/api/plugins/goals-page/goals";
  const POLL_MS = 10000;

  const GROUPS = [
    { key: "active", label: "Active", color: "#3b82f6", hint: "The agent is working on it. The judge re-checks after every turn." },
    { key: "waiting", label: "Waiting", color: "#22c55e", hint: "Parked on a process, timer or delegation. Resumes on its own." },
    { key: "paused", label: "Paused", color: "#f59e0b", hint: "Stopped by the judge (blocked, budget) or by /goal pause." },
    { key: "done", label: "Done", color: "#8b5cf6", hint: "Completed and audited. Only status=done counts." },
  ];

  function ago(ts) {
    if (!ts) return "";
    const s = Math.max(0, Date.now() / 1000 - Number(ts));
    if (s < 90) return "just now";
    if (s < 3600) return Math.round(s / 60) + "m ago";
    if (s < 86400) return Math.round(s / 3600) + "h ago";
    return Math.round(s / 86400) + "d ago";
  }

  function fmt(ts) {
    if (!ts) return "";
    try { return new Date(Number(ts) * 1000).toLocaleString(); } catch (e) { return ""; }
  }

  function useGoals() {
    const [data, setData] = useState(null);
    const [err, setErr] = useState(null);
    const [tick, setTick] = useState(0);
    useEffect(function () {
      let alive = true;
      SDK.fetchJSON(API + (tick ? "?fresh=1" : "")).then(function (d) {
        if (!alive) return; setData(d); setErr(null);
      }).catch(function (e) { if (alive) setErr(String(e && e.message || e)); });
      const id = setTimeout(function () { setTick(function (t) { return t + 1; }); }, POLL_MS);
      return function () { alive = false; clearTimeout(id); };
    }, [tick]);
    return { data: data, err: err, refresh: function () { setTick(function (t) { return t + 1; }); } };
  }

  function Dot(p) {
    return h("span", { className: "gp-dot", style: { background: p.color } });
  }

  function Chip(p) {
    return h("span", { className: "gp-chip " + (p.className || "") }, p.children);
  }

  function Row(p) {
    const g = p.goal;
    const title = g.objective || "(no objective)";
    const sub = g.attention ? "Needs attention: " + g.attention : g.sub_status;
    return h("div", { className: "gp-row" + (p.selected ? " gp-row-sel" : ""), onClick: function () { p.onSelect(g); } },
      h(Dot, { color: p.color }),
      h("div", { className: "gp-row-main" },
        h("div", { className: "gp-title" }, title),
        sub ? h("div", { className: "gp-sub" + (g.attention ? " gp-sub-attn" : "") }, sub) : null,
        h("div", { className: "gp-meta" },
          h(Chip, null, g.profile),
          g.source === "agent" ? h(Chip, null, "agent") : null,
          g.last_verdict ? h(Chip, { className: "gp-chip-" + g.last_verdict }, g.last_verdict) : null,
          h("span", { className: "gp-when" }, ago(g.last_turn_at || g.created_at)),
          g.max_turns ? h("span", { className: "gp-when" }, g.turns_used + "/" + g.max_turns + " turns") : null
        )
      )
    );
  }

  function Detail(p) {
    const g = p.goal;
    if (!g) return h(Card, { className: "gp-detail gp-empty" }, h("div", { className: "gp-hint" }, "Select a goal to see its contract, status and session."));
    const c = g.contract || {};
    const sessionUrl = "/chat?resume=" + encodeURIComponent(g.session_id);
    return h(Card, { className: "gp-detail" },
      h("div", { className: "gp-detail-head" },
        h("h3", null, g.objective),
        h("div", { className: "gp-meta" },
          h(Chip, null, g.profile), h(Chip, null, "status: " + g.status),
          g.last_verdict ? h(Chip, { className: "gp-chip-" + g.last_verdict }, "judge: " + g.last_verdict) : null
        )
      ),
      g.attention ? h("div", { className: "gp-attn-box" }, h("b", null, "May need attention. "), g.attention, h("div", { className: "gp-hint" }, "Evidence: last judge verdict is blocked and the goal has not been resumed since.")) : null,
      section("Acceptance criteria", c.outcome),
      section("Verification", c.verification),
      g.subgoals && g.subgoals.length ? h("div", { className: "gp-section" }, h("h4", null, "Subgoals"), h("ul", null, g.subgoals.map(function (s, i) { return h("li", { key: i }, s); }))) : null,
      g.gates && g.gates.length ? h("div", { className: "gp-section" }, h("h4", null, "Gates"), h("ul", null, g.gates.map(function (gt, i) { return h("li", { key: i }, h("code", null, gt.cmd || JSON.stringify(gt))); }))) : null,
      section("Latest judge reason", g.last_reason),
      section("Waiting reason", g.waiting_reason),
      section("Paused reason", g.paused_reason),
      h("div", { className: "gp-section" },
        h("h4", null, "Session"),
        h("div", { className: "gp-kv" }, h("span", null, "Title"), h("span", null, g.session_title || "—")),
        h("div", { className: "gp-kv" }, h("span", null, "Session id"), h("code", null, g.session_id)),
        h("div", { className: "gp-kv" }, h("span", null, "Source"), h("span", null, (g.session_source || "—") + (g.chat_id ? " · chat " + g.chat_id : ""))),
        h("div", { className: "gp-kv" }, h("span", null, "Goal set"), h("span", null, fmt(g.created_at))),
        h("div", { className: "gp-kv" }, h("span", null, "Last turn"), h("span", null, fmt(g.last_turn_at))),
        g.heartbeat ? h("div", { className: "gp-kv" }, h("span", null, "Heartbeat"), h("span", null, JSON.stringify(g.heartbeat).slice(0, 160))) : null,
        g.profile === "default"
          ? h("a", { className: "gp-btn", href: sessionUrl }, "Open session")
          : h("div", { className: "gp-hint" }, "This session belongs to profile \"" + g.profile + "\". Open it from that profile's dashboard or with: hermes --resume " + g.session_id + " -p " + g.profile)
      )
    );
  }

  function section(title, body) {
    if (!body) return null;
    return h("div", { className: "gp-section" }, h("h4", null, title), h("div", { className: "gp-body" }, String(body)));
  }

  function GoalsPage() {
    const { data, err, refresh } = useGoals();
    const [profile, setProfile] = useState("all");
    const [selected, setSelected] = useState(null);
    const [showDone, setShowDone] = useState(false);

    const profiles = useMemo(function () {
      if (!data) return [];
      return data.profiles.filter(function (p) { return p.count > 0 || p.error; });
    }, [data]);

    const goals = useMemo(function () {
      if (!data) return [];
      return data.goals.filter(function (g) { return profile === "all" || g.profile === profile; });
    }, [data, profile]);

    const attention = goals.filter(function (g) { return g.attention; });

    // Deep link: /goals?select=<session_id> selects that goal on load.
    useEffect(function () {
      if (!data || selected) return;
      const want = new URLSearchParams(window.location.search).get("select");
      if (!want) return;
      const hit = data.goals.find(function (g) { return g.session_id === want; });
      if (hit) setSelected(hit);
    }, [data]);

    return h("div", { className: "gp-root" },
      h("div", { className: "gp-header" },
        h("div", null,
          h("h2", null, "Goals"),
          h("div", { className: "gp-hint" }, "One goal per session, across every profile on this machine. Read-only view of what the agents are working toward.")
        ),
        h("div", { className: "gp-controls" },
          h("select", { value: profile, onChange: function (e) { setProfile(e.target.value); } },
            h("option", { value: "all" }, "All profiles"),
            profiles.map(function (p) { return h("option", { key: p.profile, value: p.profile }, p.profile + " (" + p.count + ")"); })
          ),
          h(Button, { onClick: refresh, className: "gp-btn" }, "Refresh")
        )
      ),
      err ? h("div", { className: "gp-error" }, "Could not load goals: " + err) : null,
      data && data.profiles.some(function (p) { return p.error; })
        ? h("div", { className: "gp-error" }, "Some profiles could not be read: " + data.profiles.filter(function (p) { return p.error; }).map(function (p) { return p.profile + " (" + p.error + ")"; }).join(", "))
        : null,
      h("div", { className: "gp-cols" },
        h("div", { className: "gp-list" },
          attention.length ? h("div", { className: "gp-group" },
            h("div", { className: "gp-group-head" }, h(Dot, { color: "#ef4444" }), h("span", null, "May need attention"), h(Chip, null, attention.length)),
            h("div", { className: "gp-hint" }, "Last judge verdict is blocked. Open the session to see what is asked."),
            attention.map(function (g) { return h(Row, { key: g.profile + g.session_id, goal: g, color: "#ef4444", selected: selected === g, onSelect: setSelected }); })
          ) : null,
          GROUPS.map(function (grp) {
            let rows = goals.filter(function (g) { return g.group === grp.key && !g.attention; });
            if (grp.key === "done" && !showDone) rows = rows.slice(0, 5);
            const total = goals.filter(function (g) { return g.group === grp.key && !g.attention; }).length;
            if (!total) return null;
            return h("div", { className: "gp-group", key: grp.key },
              h("div", { className: "gp-group-head" }, h(Dot, { color: grp.color }), h("span", null, grp.label), h(Chip, null, total)),
              h("div", { className: "gp-hint" }, grp.hint),
              rows.map(function (g) { return h(Row, { key: g.profile + g.session_id, goal: g, color: grp.color, selected: selected === g, onSelect: setSelected }); }),
              grp.key === "done" && total > 5 ? h("button", { className: "gp-link", onClick: function () { setShowDone(!showDone); } }, showDone ? "Show less" : "Show all " + total) : null
            );
          }),
          data && !goals.length ? h("div", { className: "gp-hint" }, "No goals yet. Agents set one with the goal tool; you can set one with /goal.") : null,
          data ? h("div", { className: "gp-foot" }, "Updated " + ago(data.generated_at) + " · " + data.goals.length + " goals · cleared (not completed): " + (data.counts.cleared || 0)) : h("div", { className: "gp-hint" }, "Loading…")
        ),
        h(Detail, { goal: selected })
      )
    );
  }

  window.__HERMES_PLUGINS__.register("goals-page", GoalsPage);
})();
