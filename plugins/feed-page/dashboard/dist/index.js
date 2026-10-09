(function () {
  "use strict";
  // feed-page dashboard plugin: Muse-style feed of plain-English cards.
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;

  const React = SDK.React;
  const h = React.createElement;
  const { useState, useEffect } = SDK.hooks;

  const API = "/api/plugins/feed-page/feed";
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

  function useFeed() {
    const [data, setData] = useState(null);
    const [err, setErr] = useState(null);
    const [tick, setTick] = useState(0);
    useEffect(function () {
      let alive = true;
      SDK.fetchJSON(API + "?limit=100").then(function (d) {
        if (!alive) return; setData(d); setErr(null);
      }).catch(function (e) { if (alive) setErr(String(e && e.message || e)); });
      const id = setTimeout(function () { setTick(function (t) { return t + 1; }); }, POLL_MS);
      return function () { alive = false; clearTimeout(id); };
    }, [tick]);
    return { data: data, setData: setData, err: err, refresh: function () { setTick(function (t) { return t + 1; }); } };
  }

  // Thin monoline icons (24px) like the reference action row.
  function IconThumbUp(p) {
    return h("svg", { width: 20, height: 20, viewBox: "0 0 24 24", fill: p.filled ? "currentColor" : "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" },
      h("path", { d: "M7 10v12" }), h("path", { d: "M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" }));
  }
  function IconThumbDown(p) {
    return h("svg", { width: 20, height: 20, viewBox: "0 0 24 24", fill: p.filled ? "currentColor" : "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" },
      h("path", { d: "M17 14V2" }), h("path", { d: "M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" }));
  }
  function IconChat() {
    return h("svg", { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" },
      h("path", { d: "M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" }));
  }
  function IconInfo() {
    return h("svg", { width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" },
      h("circle", { cx: 12, cy: 12, r: 10 }), h("path", { d: "M12 16v-4" }), h("path", { d: "M12 8h.01" }));
  }

  function LinkCard(p) {
    const it = p.item;
    if (!it.link_title && !it.link_subtitle) return null;
    const inner = [
      h("div", { className: "fp-link-head", key: "t" }, it.link_title || ""),
      it.link_subtitle ? h("div", { className: "fp-link-sub", key: "s" }, it.link_subtitle) : null,
      it.link_status ? h("div", { className: "fp-link-row", key: "r" },
        h("span", { className: "fp-link-label" }, it.source === "goal" ? "Goal" : "Status"),
        h("span", { className: "fp-pill" }, it.link_status)) : null,
    ];
    if (it.link_url) return h("a", { className: "fp-link fp-link-a", href: it.link_url, target: "_blank", rel: "noreferrer" }, inner);
    return h("div", { className: "fp-link" }, inner);
  }

  function FeedCard(p) {
    const it = p.item;
    const [showInfo, setShowInfo] = useState(false);
    function react(r) {
      const next = it.reaction === r ? null : r;
      p.onReact(it.id, next);
    }
    const discussHref = it.session_id ? "/chat?resume=" + encodeURIComponent(it.session_id) : null;
    return h("article", { className: "fp-card" },
      h("div", { className: "fp-icon" }, it.icon || "📝"),
      h("div", { className: "fp-main" },
        h("div", { className: "fp-title" }, it.title),
        h("div", { className: "fp-body" }, it.body),
        h(LinkCard, { item: it }),
        h("div", { className: "fp-actions" },
          h("button", { className: "fp-ab" + (it.reaction === "up" ? " fp-ab-on" : ""), title: "Helpful", "aria-label": "thumbs up", onClick: function () { react("up"); } }, h(IconThumbUp, { filled: it.reaction === "up" })),
          h("button", { className: "fp-ab" + (it.reaction === "down" ? " fp-ab-on" : ""), title: "Not helpful", "aria-label": "thumbs down", onClick: function () { react("down"); } }, h(IconThumbDown, { filled: it.reaction === "down" })),
          discussHref
            ? h("a", { className: "fp-ab fp-discuss", href: discussHref }, h(IconChat), h("span", null, "Discuss"))
            : h("span", { className: "fp-ab fp-discuss fp-ab-dis", title: "No session attached" }, h(IconChat), h("span", null, "Discuss")),
          h("span", { className: "fp-spacer" }),
          h("span", { className: "fp-when" }, ago(it.created_at)),
          h("button", { className: "fp-ab fp-info", "aria-label": "details", onClick: function () { setShowInfo(!showInfo); } }, h(IconInfo))
        ),
        showInfo ? h("div", { className: "fp-meta" },
          h("span", null, "profile " + (it.profile || "default")),
          h("span", null, "source " + it.source),
          it.session_id ? h("span", null, "session " + it.session_id) : null,
          h("span", null, new Date(Number(it.created_at) * 1000).toLocaleString())
        ) : null
      )
    );
  }

  function FeedPage() {
    const { data, setData, err, refresh } = useFeed();
    const [busy, setBusy] = useState(null);

    function onReact(id, reaction) {
      setBusy(id);
      setData(function (d) {
        if (!d) return d;
        return Object.assign({}, d, { items: d.items.map(function (x) { return x.id === id ? Object.assign({}, x, { reaction: reaction }) : x; }) });
      });
      postJSON(API + "/" + encodeURIComponent(id) + "/reaction", { reaction: reaction })
        .catch(function () { refresh(); })
        .then(function () { setBusy(null); });
    }

    const items = data ? data.items : [];
    return h("div", { className: "fp-root" },
      h("div", { className: "fp-header" },
        h("div", null,
          h("h2", null, "Feed"),
          h("div", { className: "fp-hint" }, "What the agents finished, in plain English. Cards come from feed_post and from every completed goal.")
        ),
        h("button", { className: "fp-refresh", onClick: refresh }, "Refresh")
      ),
      err ? h("div", { className: "fp-error" }, "Could not load feed: " + err) : null,
      data && data.errors && data.errors.length ? h("div", { className: "fp-error" }, "Some sources could not be read: " + data.errors.join("; ")) : null,
      h("div", { className: "fp-list" },
        items.map(function (it) { return h(FeedCard, { key: it.id, item: it, onReact: onReact, busy: busy === it.id }); }),
        data && !items.length ? h("div", { className: "fp-hint fp-empty" }, "Nothing here yet. Agents post cards with the feed_post tool; completed goals appear automatically.") : null,
        !data && !err ? h("div", { className: "fp-hint" }, "Loading…") : null
      ),
      data ? h("div", { className: "fp-foot" }, items.length + " cards · updated " + ago(data.generated_at) + " ago") : null
    );
  }

  window.__HERMES_PLUGINS__.register("feed-page", FeedPage);
})();
