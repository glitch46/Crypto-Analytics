/* Crypto Analytics — Expo-mode runway
 * Single-page stacked full-screen tabs. Wheel / arrows scroll between them,
 * double-click expands a tab fullscreen.
 *
 * Exactly ONE dashboard is mounted in the DOM at a time (the active tab), so
 * the per-tab inline scripts never collide on element IDs. The neighbors' HTML
 * is prefetched in the background so switching is instant; charts are destroyed
 * and the slot cleared the moment you leave a tab.
 */
(function () {
  "use strict";

  var TABS = [
    { id: "home", label: "Home", src: null, dir: "" },
    { id: "alts", label: "BTC / Alt", src: "Alt-Outperformance/index.html", dir: "Alt-Outperformance" },
    { id: "indicators", label: "Indicators", src: "Trading-Indicators/index.html", dir: "Trading-Indicators" },
    { id: "options", label: "Options", src: "Crypto-Dashboard/index.html", dir: "Crypto-Dashboard" },
    { id: "backtest", label: "Backtest", src: "Backtest-Dashboard/index.html", dir: "Backtest-Dashboard" },
    { id: "strategy", label: "Strategy", src: "Strategy-Tester/index.html", dir: "Strategy-Tester" },
    { id: "situation", label: "Situation", src: "Situation-Monitor/index.html", dir: "Situation-Monitor" },
    { id: "demo", label: "Demo", src: null, dir: "" }
  ];

  var MARK = '<svg viewBox="0 0 32 32" fill="none">'
    + '<circle cx="16" cy="16" r="14.5" stroke="#0051FF" stroke-width="2.5"/>'
    + '<path d="M9 21.5 L14.5 15.5 L18.5 19 L24 12" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
    + "</svg>";

  var body = document.body;
  var tabs = [];
  var active = 0;
  var fsTab = null;

  /* ---------------- fixed chrome ---------------- */
  var nav = document.createElement("nav");
  nav.className = "top-nav";
  nav.innerHTML = '<a class="brand" href="#home">' + MARK + "<span>Crypto Analytics</span></a>"
    + '<div class="top-nav-links">'
    + TABS.map(function (t) { return '<a data-tab="' + t.id + '" href="#' + t.id + '">' + t.label + "</a>"; }).join("")
    + "</div>";
  body.appendChild(nav);

  var up = document.createElement("button");
  up.className = "nav-arrow top"; up.title = "Previous tab"; up.innerHTML = "&#8593;";
  var down = document.createElement("button");
  down.className = "nav-arrow bottom"; down.title = "Next tab"; down.innerHTML = "&#8595;";
  up.addEventListener("click", function () { goto(active - 1); });
  down.addEventListener("click", function () { goto(active + 1); });
  body.appendChild(up); body.appendChild(down);

  var close = document.createElement("button");
  close.className = "fs-close"; close.title = "Exit fullscreen (Esc)"; close.innerHTML = "&#10005;";
  close.addEventListener("click", exitFullscreen);
  body.appendChild(close);

  var hint = document.createElement("div");
  hint.className = "tab-hint";
  hint.textContent = "Scroll to move · click a tab above to jump & expand";
  body.appendChild(hint);
  setTimeout(function () { hint.style.opacity = "0"; }, 9000);

  /* ---------------- collect tabs ---------------- */
  document.querySelectorAll(".tab").forEach(function (el) {
    var def = TABS.find(function (t) { return t.id === el.dataset.tab; });
    if (!def) return;
    tabs.push({
      id: def.id, label: def.label, src: def.src, dir: def.dir,
      el: el, slot: el.querySelector(".tab-slot"),
      state: def.src === null ? "loaded" : "stub",   // static tabs (home/demo) always present
      html: null, promise: null
    });
  });

  /* ---------------- content injection ---------------- */
  /* Rewrite a dashboard's relative data paths to root-relative so its fetches
     work from the runway URL (which never changes). */
  function rewrite(code, dir) {
    code = code.replace(/\.\.\/Crypto-Dashboard\/data\//g, "Crypto-Dashboard/data/");
    code = code.replace(/(['"])data\//g, "$1" + dir + "/data/");
    return code;
  }

  function destroyChartsIn(root) {
    if (!window.Chart) return;
    var charts = [];
    if (Chart.instances) charts = Object.values(Chart.instances);          // Chart.js v4
    else if (Chart.registry && typeof Chart.registry.getAll === "function") charts = Chart.registry.getAll();
    charts.forEach(function (c) {
      try { if (c.canvas && root.contains(c.canvas)) c.destroy(); } catch (e) {}
    });
  }

  function runScripts(code) {
    new Function("window", "document", "globalThis", code).call(window, window, document, globalThis);
  }

  /* Parse the fetched page, inject its <main> into the tab, run its scripts. */
  function inject(t) {
    var doc = new DOMParser().parseFromString(t.html, "text/html");
    var main = doc.querySelector("main.page");
    t.slot.innerHTML = "";
    if (main) t.slot.appendChild(main);
    t.slot.querySelectorAll("[data-aos]").forEach(function (el) { el.classList.add("aos-animate"); });
    var code = Array.prototype.slice.call(doc.querySelectorAll("script:not([src])"))
      .map(function (s) { return s.textContent; })
      .map(function (c) { return rewrite(c, t.dir); })
      .join("\n;\n");
    try { runScripts(code); } catch (e) { console.error("run failed", t.id, e); }
    t.state = "loaded";
  }

  /* Prefetch a tab's HTML (background). state: stub -> loading -> cached. */
  function preload(i) {
    if (i < 0 || i >= tabs.length) return Promise.resolve();
    var t = tabs[i];
    if (t.id === "home" || t.state === "cached" || t.state === "loaded" || t.promise) return Promise.resolve();
    t.state = "loading";
    t.promise = fetch(t.src, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })
      .then(function (html) { t.html = html; t.state = "cached"; })
      .catch(function () { t.state = "stub"; t.promise = null; });
    return t.promise;
  }

  /* Mount the active tab (or home/demo). Unloads whatever was mounted before. */
  function activate(i) {
    tabs.forEach(function (t, idx) { if (idx !== i && t.state === "loaded" && t.src) unload(t); });
    var t = tabs[i];
    if (!t || t.id === "home" || t.id === "demo") return;
    if (t.state === "cached") inject(t);
    else if (t.state === "stub") preload(i).then(function () { if (t.state === "cached") inject(t); });
    preload(i - 1);
    preload(i + 1);
  }

  function unload(t) {
    destroyChartsIn(t.el);
    t.slot.innerHTML = "";
    t.state = "cached";
  }

  /* ---------------- navigation ---------------- */
  function goto(i) {
    i = Math.max(0, Math.min(tabs.length - 1, i));
    tabs[i].el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /* ---------------- fullscreen ---------------- */
  function setFullscreen(tab) {
    if (fsTab) return;
    fsTab = tab;
    body.classList.add("fs");
    tab.el.classList.add("fullscreen");
    tab.el.scrollTop = 0;
  }
  function exitFullscreen() {
    if (!fsTab) return;
    fsTab.el.classList.remove("fullscreen");
    fsTab = null;
    body.classList.remove("fs");
    window.scrollTo({ top: active * window.innerHeight, behavior: "auto" });
  }

  /* ---------------- active tracking + lifecycle ---------------- */
  var ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      ticking = false;
      var i = Math.max(0, Math.min(tabs.length - 1, Math.round(window.scrollY / window.innerHeight)));
      /* Demo tab swaps the crypto-particle field for the gondola scene */
      var pc = document.getElementById("particle-backdrop");
      if (pc) pc.style.display = tabs[i].id === "demo" ? "none" : "";
      if (i !== active) {
        active = i;
        tabs.forEach(function (t, idx) { t.el.classList.toggle("active", idx === i); });
        document.querySelectorAll(".top-nav-links a").forEach(function (a) {
          a.classList.toggle("active", a.dataset.tab === tabs[i].id);
        });
        activate(i);
      }
      up.disabled = active <= 0;
      down.disabled = active >= tabs.length - 1;
    });
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);

  /* ---------------- interactions ---------------- */
  document.addEventListener("dblclick", function (e) {
    if (fsTab) { exitFullscreen(); return; }
    var tabEl = e.target && e.target.closest ? e.target.closest(".tab") : null;
    if (!tabEl) return;
    var tab = tabs.find(function (t) { return t.el === tabEl; });
    if (tab) setFullscreen(tab);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") exitFullscreen();
  });

  /* in-tab anchor links (home cards, brand) jump to the matching tab.
     Top-nav links also auto-expand (zoom in) the target after the scroll. */
  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (!a || e.defaultPrevented) return;
    var id = a.getAttribute("href").slice(1);
    var idx = tabs.findIndex(function (t) { return t.id === id; });
    if (idx < 0) return;
    e.preventDefault();
    var fromNav = !!a.closest(".top-nav");
    goto(idx);
    if (fromNav) {
      var dist = Math.abs(idx - active);
      var wait = Math.min(1200, 350 + dist * 160);   // let the smooth scroll land
      setTimeout(function () { if (tabs[idx]) setFullscreen(tabs[idx]); }, wait);
    }
  });

  /* initial state: home is active, prefetch the first dashboard */
  tabs.forEach(function (t, i) { t.el.classList.toggle("active", i === 0); });
  up.disabled = true;
  preload(1);
})();
