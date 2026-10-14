/* MECSR Intel: tiny client script: theme toggle, card filters, archive search. */
(function () {
  "use strict";
  var root = document.documentElement;
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  var saved = store("mecsr-intel-theme");
  if (saved === "dark" || saved === "light") root.setAttribute("data-theme", saved);
  document.addEventListener("DOMContentLoaded", function () {
    var tbtn = document.querySelector(".theme-toggle");
    if (tbtn) tbtn.addEventListener("click", function () {
      var cur = root.getAttribute("data-theme") ||
        (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      var next = cur === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next); store("mecsr-intel-theme", next);
    });

    /* ---- card filters (stream chips + text search) ---- */
    var chips = Array.prototype.slice.call(document.querySelectorAll("[data-filter]"));
    var box = document.querySelector(".tools .search");
    var items = Array.prototype.slice.call(document.querySelectorAll("[data-stream]"));
    var active = "all";
    function apply() {
      var q = box ? box.value.trim().toLowerCase() : "";
      items.forEach(function (el) {
        var okS = active === "all" || el.getAttribute("data-stream") === active;
        var okQ = !q || (el.getAttribute("data-text") || el.textContent.toLowerCase()).indexOf(q) !== -1;
        el.classList.toggle("hidden", !(okS && okQ));
      });
      Array.prototype.forEach.call(document.querySelectorAll("[data-group]"), function (g) {
        var any = g.querySelector("[data-stream]:not(.hidden)");
        g.classList.toggle("hidden", !any);
      });
    }
    chips.forEach(function (c) {
      c.addEventListener("click", function () {
        active = c.getAttribute("data-filter");
        chips.forEach(function (o) { o.setAttribute("aria-pressed", o === c ? "true" : "false"); });
        apply();
      });
    });
    if (box) box.addEventListener("input", apply);

    /* ---- archive search over every finding ---- */
    var as = document.getElementById("archive-search");
    if (as) {
      var out = document.getElementById("archive-results"), data = null, loading = false;
      function esc(s) { return String(s || "").replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
      function render(q) {
        if (!data) return;
        if (q.length < 2) { out.innerHTML = '<p class="note">Type at least two letters: a mall, company, country or topic.</p>'; return; }
        var words = q.toLowerCase().split(/\s+/).filter(Boolean), hits = [];
        for (var i = 0; i < data.length && hits.length < 200; i++) {
          var r = data[i], hay = (r.t + " " + r.s + " " + r.c + " " + r.e + " " + r.o).toLowerCase();
          if (words.every(function (w) { return hay.indexOf(w) !== -1; })) hits.push(r);
        }
        if (!hits.length) { out.innerHTML = '<p class="note">No findings match “' + esc(q) + '”.</p>'; return; }
        out.innerHTML = '<p class="note">' + hits.length + (hits.length === 200 ? "+" : "") + ' findings</p>' + hits.map(function (r) {
          return '<div class="hit"><div class="row"><span class="when">' + esc(r.d) + '</span><span class="chip"><span class="dot d-' + esc(r.k) + '"></span>' + esc(r.n) + '</span>' +
            (r.c ? '<span class="chip">' + esc(r.c) + '</span>' : '') + '</div><div><a href="' + esc(r.p) + '"><b>' + esc(r.t) + '</b></a></div>' +
            '<div class="note">' + esc(r.s) + '</div>' + (r.u ? '<div class="srcs"><a href="' + esc(r.u) + '" target="_blank" rel="noopener">' + esc(r.o || "Source") + ' ↗</a></div>' : '') + '</div>';
        }).join("");
      }
      as.addEventListener("input", function () {
        var q = as.value.trim();
        if (!data && !loading) {
          loading = true; out.innerHTML = '<p class="note">Loading the archive…</p>';
          fetch(as.getAttribute("data-src")).then(function (r) { return r.json(); })
            .then(function (j) { data = j; render(as.value.trim()); })
            .catch(function () { out.innerHTML = '<p class="note">The archive index could not be loaded. Open the site from its web address rather than from disk.</p>'; });
        } else render(q);
      });
    }
  });
})();
