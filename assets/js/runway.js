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
    { id: "situation", label: "Situation", src: "Situation-Monitor/index.html", dir: "Situation-Monitor" }
  ];

  var MARK = '<svg viewBox="0 0 32 32" fill="none">'
    + '<circle cx="16" cy="16" r="14.5" stroke="#0051FF" stroke-width="2.5"/>'
    + '<path d="M9 21.5 L14.5 15.5 L18.5 19 L24 12" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
    + "</svg>";

  var body = document.body;
  var tabs = [];
  var active = 0;
  var fsTab = null;
  var navigationToken = 0;

  /* A DOM-based perspective ribbon inspired by Expo Mode. Dashboard content
     remains real HTML and becomes interactive when a section is expanded. */
  // Preview labels describe the actual dashboards. Numeric values below are
  // filled from their existing JSON snapshots, never fabricated market data.
  var previews = {
    alts: { title: "BTC / Alt Outperformance", summary: "Relative strength across the crypto market", labels: ["7D leader vs BTC", "7D laggard vs BTC", "Assets in snapshot"], panels: ["Top Outperformers vs BTC", "Worst Underperformers vs BTC"], detail: "7 / 14 / 30-day relative returns" },
    indicators: { title: "Trading Indicators", summary: "Spot liquidity, flow and positioning", labels: ["Depth windows", "Spot venues", "CFTC updates"], values: ["2.5%–25%", "Up to 5", "Weekly"], panels: ["Orderbook Balance Over Time", "Spot CVD by Exchange"], detail: "Depth, flow and positioning context" },
    options: { title: "Options Intelligence", summary: "Open interest, strikes and expiries", labels: ["BTC spot", "Options open interest", "Put / call ratio"], panels: ["30-Day Open Interest Momentum", "Max Pain Strike Map"], detail: "BTC & ETH · Deribit options" },
    backtest: { title: "Skew Backtest", summary: "Historical options positioning and outcomes", labels: ["BTC skew follow", "Months analyzed", "Puts > calls"], panels: ["Skew vs Price Change", "Max Pain Deviations"], detail: "Historical expiry snapshots" },
    strategy: { title: "Strategy Tester", summary: "Test an idea against historical BTC prices", labels: ["Latest BTC close", "Price observations", "Last price date"], panels: ["BTC Price History", "90-Day Strategy Candlestick View"], detail: "Momentum, seasonal and custom sizing" },
    situation: { title: "The Situation", summary: "Macro conditions and market stress", labels: ["WTI crude", "Brent crude", "VIX"], panels: ["Oil Price History", "Credit Spread Monitor"], detail: "Oil, yields, credit and equities" }
  };
  var world = document.createElement("div");
  world.className = "expo-world";
  world.setAttribute("role", "region");
  world.setAttribute("aria-label", "Dashboard overview");
  world.innerHTML = '<div class="expo-horizon"></div><div class="expo-track">' + TABS.filter(function (t) { return t.src; }).reverse().map(function (t) {
    var p = previews[t.id];
    var number = TABS.findIndex(function (entry) { return entry.id === t.id; });
    return '<div class="expo-tile expo-' + t.id + '" data-expo-id="' + t.id + '" role="button" tabindex="0" aria-label="Open ' + p.title + ' dashboard"><div class="expo-tile-header"><span>CRYPTO ANALYTICS / ' + String(number).padStart(2, "0") + '</span><span>MARKET INTELLIGENCE</span></div>'
      + '<div class="expo-tile-copy"><span class="expo-tile-kicker">' + p.summary + '</span><strong>' + p.title + '</strong></div>'
      + '<div class="expo-page-preview"><div class="expo-preview-bar"><span>PAGE PREVIEW · BTC</span><span data-preview-time>' + (p.values ? 'DASHBOARD FEATURES' : 'LOADING SNAPSHOT') + '</span></div>'
      + '<div class="expo-preview-stats">' + p.labels.map(function (label, i) { return '<div><span>' + label + '</span><strong data-preview-value="' + i + '">' + (p.values ? p.values[i] : '—') + '</strong></div>'; }).join("") + '</div>'
      + '<div class="expo-preview-panels">' + p.panels.map(function (label, i) {
        var chart = i === 0 && (t.id === "alts" || t.id === "strategy")
          ? '<svg class="expo-preview-chart" data-preview-chart viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true"><polyline fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke"></polyline></svg>' : "";
        return '<div><strong>' + label + '</strong>' + chart + '<span>' + (i ? p.detail : (t.id === "alts" ? '7D leader · relative trend' : t.id === "strategy" ? 'Recent BTC closing prices' : 'Open the dashboard for full details')) + '</span></div>';
      }).join("") + '</div></div></div>';
  }).join("") + '</div>';
  body.appendChild(world);
  var track = world.querySelector(".expo-track");

  function updatePerspective() {
    // Home fits all six previews; scrolling forward returns to the closer view.
    var progress = Math.max(0, Math.min(TABS.length - 1, window.scrollY / window.innerHeight));
    body.classList.toggle("overview", progress < 0.1);
    track.style.setProperty("--expo-travel", (Math.max(0, progress - 1) * 420).toFixed(2) + "px");
  }

  var previewRequests = {};
  function previewJSON(path) {
    if (!previewRequests[path]) previewRequests[path] = fetch(path, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
    return previewRequests[path];
  }
  function showPreview(id, values, updated) {
    var tile = world.querySelector('.expo-tile[data-expo-id="' + id + '"]');
    if (!tile) return;
    values.forEach(function (value, i) {
      var el = tile.querySelector('[data-preview-value="' + i + '"]');
      if (el) el.textContent = value == null ? "—" : String(value);
    });
    var time = tile.querySelector("[data-preview-time]");
    if (time) time.textContent = updated ? "UPDATED " + updated : "SNAPSHOT UNAVAILABLE";
  }
  function money(value, compact) {
    if (typeof value !== "number" || !isFinite(value)) return "—";
    if (compact && Math.abs(value) >= 1e9) return "$" + (value / 1e9).toFixed(2) + "B";
    return "$" + value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  function percent(value) { return typeof value === "number" && isFinite(value) ? (value * 100).toFixed(1) + "%" : "—"; }
  function showPreviewChart(id, values) {
    var line = world.querySelector('.expo-tile[data-expo-id="' + id + '"] [data-preview-chart] polyline');
    values = values.filter(function (v) { return typeof v === "number" && isFinite(v); });
    if (!line || values.length < 2) return;
    var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    var range = max - min || 1;
    line.setAttribute("points", values.map(function (v, i) {
      return (i * 100 / (values.length - 1)).toFixed(1) + "," + (26 - (v - min) / range * 24).toFixed(1);
    }).join(" "));
  }
  function loadPreviews() {
    var meta = previewJSON("Crypto-Dashboard/data/metadata.json");
    Promise.all([previewJSON("Alt-Outperformance/data/alt_performance.json"), previewJSON("Alt-Outperformance/data/metadata.json")]).then(function (results) {
      var coins = (results[0].alts || []).filter(function (coin) { return typeof coin.relative_7d === "number" && isFinite(coin.relative_7d); });
      coins.sort(function (a, b) { return b.relative_7d - a.relative_7d; });
      function relative(coin) { return coin ? coin.symbol + " " + (coin.relative_7d >= 0 ? "+" : "") + coin.relative_7d.toFixed(1) + " pp" : "—"; }
      showPreview("alts", [relative(coins[0]), relative(coins[coins.length - 1]), coins.length], results[1].last_updated);
      showPreviewChart("alts", ((coins[0] || {}).daily_relative || []).slice(-8).map(function (row) { return row.relative_pct; }));
    }).catch(function () { showPreview("alts", [], null); });
    Promise.all([previewJSON("Crypto-Dashboard/data/options_snapshot.json"), meta]).then(function (results) {
      var btc = results[0].BTC || {};
      showPreview("options", [money(btc.spot_price), money(btc.total_oi, true), typeof btc.put_call_ratio === "number" ? btc.put_call_ratio.toFixed(2) : "—"], results[1].last_updated);
    }).catch(function () { showPreview("options", [], null); });
    Promise.all([previewJSON("Crypto-Dashboard/data/backtest.json"), meta]).then(function (results) {
      var summary = ((results[0].BTC || {}).summary || {});
      showPreview("backtest", [percent(summary.win_rate), summary.months, summary.puts_over_calls], results[1].last_updated);
    }).catch(function () { showPreview("backtest", [], null); });
    Promise.all([previewJSON("Crypto-Dashboard/data/strategy_signals.json"), meta]).then(function (results) {
      var prices = results[0].prices || [], last = prices[prices.length - 1] || {};
      showPreview("strategy", [money(last.close), prices.length, last.date], results[1].last_updated);
      showPreviewChart("strategy", prices.slice(-30).map(function (row) { return row.close; }));
    }).catch(function () { showPreview("strategy", [], null); });
    previewJSON("Situation-Monitor/data/situation.json").then(function (data) {
      var kpis = data.kpis || {};
      showPreview("situation", [money((kpis.wti || {}).current), money((kpis.brent || {}).current), (kpis.vix || {}).current], (data.metadata || {}).last_updated);
    }).catch(function () { showPreview("situation", [], null); });
  }
  loadPreviews();

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
      state: def.src === null ? "loaded" : "stub",   // home is always present
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

  /* A dashboard whose init is still awaiting when the user scrolls away will
     throw on its (now removed) elements — harmless. Keep the console clean. */
  window.addEventListener("unhandledrejection", function (e) {
    var m = e.reason && (e.reason.message || String(e.reason));
    if (m && /getElementById|querySelector|appendChild|textContent|innerHTML/.test(m)) {
      e.preventDefault();
    }
  });

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
    if (t.id === "home" || t.state === "cached" || t.state === "loaded") return Promise.resolve();
    if (t.promise) return t.promise;
    t.state = "loading";
    t.promise = fetch(t.src, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })
      .then(function (html) { t.html = html; t.state = "cached"; })
      .catch(function () { t.state = "stub"; t.promise = null; });
    return t.promise;
  }

  /* Mount the active tab (or home). Unloads whatever was mounted before. */
  function activate(i) {
    tabs.forEach(function (t, idx) { if (idx !== i && t.state === "loaded" && t.src) unload(t); });
    var t = tabs[i];
    if (!t || t.id === "home") return;
    if (t.state === "cached") inject(t);
    else if (t.state !== "loaded") preload(i).then(function () { if (active === i && t.state === "cached") inject(t); });
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

  function goAndExpand(idx) {
    if (fsTab) exitFullscreen();
    var token = ++navigationToken;
    goto(idx);
    // Home is the overview, not a seventh dashboard to expand.
    if (idx === 0) return;
    var started = performance.now();
    function expandWhenArrived(now) {
      if (token !== navigationToken) return;
      if (Math.abs(window.scrollY - tabs[idx].el.offsetTop) < 3 || now - started > 2500) {
        active = idx;
        tabs.forEach(function (t, index) { t.el.classList.toggle("active", index === idx); });
        activate(idx);
        setFullscreen(tabs[idx]);
      } else requestAnimationFrame(expandWhenArrived);
    }
    requestAnimationFrame(expandWhenArrived);
  }

  /* ---------------- fullscreen ---------------- */
  function setFullscreen(tab) {
    if (fsTab) return;
    fsTab = tab;
    body.classList.add("fs");
    world.setAttribute("aria-hidden", "true");
    world.inert = true;
    tab.el.classList.add("fullscreen");
    tab.el.scrollTop = 0;
    // Charts are initially mounted in a hidden overview; resize after reveal.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        if (!window.Chart || !Chart.instances) return;
        Object.values(Chart.instances).forEach(function (chart) {
          if (chart.canvas && tab.el.contains(chart.canvas)) chart.resize();
        });
      });
    });
  }
  function exitFullscreen() {
    if (!fsTab) return;
    fsTab.el.classList.remove("fullscreen");
    fsTab = null;
    body.classList.remove("fs");
    world.removeAttribute("aria-hidden");
    world.inert = false;
    window.scrollTo({ top: tabs[active].el.offsetTop, behavior: "instant" });
  }

  /* ---------------- active tracking + lifecycle ---------------- */
  var ticking = false;
  function onScroll() {
    if (ticking || fsTab) return;
    ticking = true;
    requestAnimationFrame(function () {
      ticking = false;
      if (fsTab) return;
      updatePerspective();
      var i = Math.max(0, Math.min(tabs.length - 1, Math.round(window.scrollY / window.innerHeight)));
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
    var tile = e.target && e.target.closest ? e.target.closest(".expo-tile") : null;
    if (tile) {
      var index = tabs.findIndex(function (t) { return t.id === tile.dataset.expoId; });
      if (index >= 0) goAndExpand(index);
      return;
    }
    var tabEl = e.target && e.target.closest ? e.target.closest(".tab") : null;
    if (!tabEl) return;
    var tab = tabs.find(function (t) { return t.el === tabEl; });
    if (tab) setFullscreen(tab);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { exitFullscreen(); return; }
    if (!fsTab && (e.key === "Enter" || e.key === " ")) {
      var tile = e.target && e.target.closest ? e.target.closest(".expo-tile") : null;
      var index = tile ? tabs.findIndex(function (t) { return t.id === tile.dataset.expoId; }) : -1;
      if (index >= 0) { e.preventDefault(); goAndExpand(index); }
    }
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
    if (fromNav) {
      goAndExpand(idx);
    } else goto(idx);
  });

  /* initial state: home is active, prefetch the first dashboard */
  tabs.forEach(function (t, i) { t.el.classList.toggle("active", i === 0); });
  up.disabled = true;
  updatePerspective();
  preload(1);
})();
