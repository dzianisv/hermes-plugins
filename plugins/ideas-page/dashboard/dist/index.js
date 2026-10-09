(function () {
  "use strict";
  // ideas-page dashboard plugin: Muse-style list of proactive ideas with Accept / Dismiss / Discuss.
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const h = React.createElement;
  const { useState, useEffect } = SDK.hooks;
  const C = SDK.components || {};
  const Card = C.Card || (function (p) { return h("div", { className: "ip-card-fallback " + (p.className || "") }, p.children); });

  const API = "/api/plugins/ideas-page/ideas";
  const POLL_MS = 15000;

  function ago(ts) {
    if (!ts) return "";
    const s = Math.max(0, Date.now() / 1000 - Number(ts));
    if (s < 60) return "now";
    if (s < 3600) return Math.round(s / 60) + " min";
    if (s < 86400) return Math.round(s / 3600) + " hr";
    if (s < 86400 * 30) return Math.round(s / 86400) + " d";
    return Math.round(s / (86400 * 30)) + " mo";
  }

  function postJSON(url, body) {
    return SDK.fetchJSON(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }

  function useIdeas() {
    const [data, setData] = useState(null);
    const [err, setErr] = useState(null);
    const [tick, setTick] = useState(0);
    useEffect(function () {
      let alive = true;
      SDK.fetchJSON(API).then(function (d) {
        if (!alive) return; setData(d); setErr(null);
      }).catch(function (e) { if (alive) setErr(String(e && e.message || e)); });
      const id = setTimeout(function () { setTick(function (t) { return t + 1; }); }, POLL_MS);
      return function () { alive = false; clearTimeout(id); };
    }, [tick]);
    return { data: data, setData: setData, err: err, refresh: function () { setTick(function (t) { return t + 1; }); } };
  }

  function CheckBadge() {
    return h("span", { className: "ip-check", title: "Accepted" },
      h("svg", { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none", stroke: "#fff", strokeWidth: 3, strokeLinecap: "round", strokeLinejoin: "round" },
        h("path", { d: "M20 6 9 17l-5-5" })));
  }

  const STATUS_LABEL = { proposed: "Proposed", accepted: "Accepted", done: "Done", dismissed: "Dismissed" };

  function IdeaRow(p) {
    const it = p.idea;
    const done = it.status === "accepted" || it.status === "done";
    return h("div", { className: "ip-row" + (p.selected ? " ip-row-sel" : "") + (it.status === "dismissed" ? " ip-row-dim" : ""), onClick: function () { p.onSelect(it); } },
      h("div", { className: "ip-icon" }, it.icon || "💡"),
      h("div", { className: "ip-main" },
        h("div", { className: "ip-title-row" },
          h("div", { className: "ip-title" }, it.title),
          done ? h(CheckBadge) : null
        ),
        h("div", { className: "ip-body" }, it.body),
        h("div", { className: "ip-meta" },
          h("span", { className: "ip-chip ip-chip-" + it.status }, STATUS_LABEL[it.status] || it.status),
          h("span", { className: "ip-when" }, it.profile || "default"),
          h("span", { className: "ip-when" }, ago(it.updated_at || it.created_at))
        )
      )
    );
  }

  function Detail(p) {
    const it = p.idea;
    if (!it) return h(Card, { className: "ip-detail" }, h("div", { className: "ip-detail-in ip-hint ip-empty" }, "Select an idea to accept, dismiss or discuss it."));
    const discussHref = it.session_id ? "/chat?resume=" + encodeURIComponent(it.session_id) : "/chat";
    const done = it.status === "accepted" || it.status === "done";
    return h(Card, { className: "ip-detail" }, h("div", { className: "ip-detail-in" },
      h("div", { className: "ip-detail-head" },
        h("div", { className: "ip-icon ip-icon-lg" }, it.icon || "💡"),
        h("div", null,
          h("h3", null, it.title),
          h("div", { className: "ip-meta" },
            h("span", { className: "ip-chip ip-chip-" + it.status }, STATUS_LABEL[it.status] || it.status),
            done ? h(CheckBadge) : null,
            h("span", { className: "ip-when" }, it.profile || "default")
          )
        )
      ),
      h("h4", null, "Why"),
      h("div", { className: "ip-text" }, it.body),
      h("h4", null, "Needs from you"),
      h("div", { className: "ip-text ip-needs" }, it.needs_from_user || "—"),
      h("div", { className: "ip-btns" },
        h("button", { className: "ip-btn ip-btn-accept", disabled: done || p.busy, onClick: function () { p.onStatus(it.id, "accepted"); } }, done ? "Accepted" : "Accept"),
        h("button", { className: "ip-btn ip-btn-dismiss", disabled: it.status === "dismissed" || p.busy, onClick: function () { p.onStatus(it.id, "dismissed"); } }, it.status === "dismissed" ? "Dismissed" : "Dismiss"),
        h("a", { className: "ip-btn ip-btn-discuss", href: discussHref }, "Discuss")
      ),
      it.status === "accepted" ? h("button", { className: "ip-link", onClick: function () { p.onStatus(it.id, "done"); } }, "Mark done") : null,
      it.status === "dismissed" ? h("button", { className: "ip-link", onClick: function () { p.onStatus(it.id, "proposed"); } }, "Restore to proposed") : null,
      h("div", { className: "ip-kv" }, h("span", null, "Proposed"), h("span", null, new Date(Number(it.created_at) * 1000).toLocaleString())),
      h("div", { className: "ip-kv" }, h("span", null, "Updated"), h("span", null, new Date(Number(it.updated_at) * 1000).toLocaleString())),
      it.session_id ? h("div", { className: "ip-kv" }, h("span", null, "Session"), h("code", null, it.session_id)) : null
    ));
  }

  function IdeasPage() {
    const { data, setData, err, refresh } = useIdeas();
    const [selectedId, setSelectedId] = useState(null);
    const [busy, setBusy] = useState(false);
    const [showClosed, setShowClosed] = useState(false);

    const items = data ? data.items : [];
    const selected = items.find(function (x) { return x.id === selectedId; }) || null;

    // Deep link: /ideas?select=<id> opens that idea's detail on load.
    useEffect(function () {
      if (!data || selectedId) return;
      const want = new URLSearchParams(window.location.search).get("select");
      if (want && data.items.some(function (x) { return x.id === want; })) setSelectedId(want);
    }, [data]);

    function onStatus(id, status) {
      setBusy(true);
      postJSON(API + "/" + encodeURIComponent(id) + "/status", { status: status })
        .then(function (row) {
          setData(function (d) {
            if (!d) return d;
            return Object.assign({}, d, { items: d.items.map(function (x) { return x.id === id ? Object.assign({}, x, row) : x; }) });
          });
        })
        .catch(function () { refresh(); })
        .then(function () { setBusy(false); });
    }

    const open = items.filter(function (x) { return x.status === "proposed" || x.status === "accepted"; });
    const closed = items.filter(function (x) { return x.status === "done" || x.status === "dismissed"; });

    return h("div", { className: "ip-root" },
      h("div", { className: "ip-header" },
        h("div", null,
          h("h2", null, "Ideas"),
          h("div", { className: "ip-hint" }, "Things the agents offer to do that you have not asked for yet. Accept to green-light, dismiss to hide, discuss to open the session.")
        ),
        h("button", { className: "ip-refresh", onClick: refresh }, "Refresh")
      ),
      err ? h("div", { className: "ip-error" }, "Could not load ideas: " + err) : null,
      data && data.errors && data.errors.length ? h("div", { className: "ip-error" }, data.errors.join("; ")) : null,
      h("div", { className: "ip-cols" },
        h("div", { className: "ip-list" },
          open.map(function (it) { return h(IdeaRow, { key: it.id, idea: it, selected: selected && selected.id === it.id, onSelect: function (x) { setSelectedId(x.id); } }); }),
          data && !open.length ? h("div", { className: "ip-hint ip-empty"}, "No open ideas. Agents add them with the idea_propose tool.") : null,
          closed.length ? h("button", { className: "ip-link", onClick: function () { setShowClosed(!showClosed); } }, (showClosed ? "Hide " : "Show ") + closed.length + " done / dismissed") : null,
          showClosed ? closed.map(function (it) { return h(IdeaRow, { key: it.id, idea: it, selected: selected && selected.id === it.id, onSelect: function (x) { setSelectedId(x.id); } }); }) : null,
          !data && !err ? h("div", { className: "ip-hint" }, "Loading…") : null
        ),
        h(Detail, { idea: selected, onStatus: onStatus, busy: busy })
      )
    );
  }

  window.__HERMES_PLUGINS__.register("ideas-page", IdeasPage);
})();
