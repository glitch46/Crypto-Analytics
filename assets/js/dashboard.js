/* Crypto Analytics — shared chrome: preloader, fixed header/nav, scroll reveal,
 * and PJAX-style navigation so switching tabs does NOT reload the page.
 * Keeping the document alive means the ambient particle backdrop (particles.js)
 * never stops playing between tabs. */
(function () {
  "use strict";

  var DASHBOARDS = [
    { id: "home", label: "Home", href: "index.html" },
    { id: "alts", label: "BTC / Alt", href: "Alt-Outperformance/index.html" },
    { id: "indicators", label: "Indicators", href: "Trading-Indicators/index.html" },
    { id: "options", label: "Options", href: "Crypto-Dashboard/index.html" },
    { id: "backtest", label: "Backtest", href: "Backtest-Dashboard/index.html" },
    { id: "strategy", label: "Strategy", href: "Strategy-Tester/index.html" },
    { id: "situation", label: "Situation", href: "Situation-Monitor/index.html" }
  ];

  var KNOWN_DIRS = ["Trading-Indicators", "Alt-Outperformance", "Crypto-Dashboard", "Backtest-Dashboard", "Strategy-Tester", "Situation-Monitor"];
  var DIR_TO_ID = {
    "Trading-Indicators": "indicators",
    "Alt-Outperformance": "alts",
    "Crypto-Dashboard": "options",
    "Backtest-Dashboard": "backtest",
    "Strategy-Tester": "strategy",
    "Situation-Monitor": "situation"
  };
  var P = KNOWN_DIRS.some(function (d) { return location.pathname.indexOf("/" + d + "/") !== -1; }) ? "../" : "";

  var MARK = '<svg viewBox="0 0 34 34" fill="none" aria-hidden="true">'
    + '<circle cx="17" cy="17" r="15.5" stroke="#0051FF" stroke-width="2"/>'
    + '<circle cx="17" cy="17" r="15.5" stroke="#f43737" stroke-width="1.5" stroke-dasharray="4 5"/>'
    + '<path d="M9 21.5L14 15.5L18 19.5L25 11" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
    + '<circle cx="25" cy="11" r="2.4" fill="#0051FF"/>'
    + "</svg>";

  /* ---------------- Preloader ---------------- */
  var pre = document.createElement("div");
  pre.className = "preloader";
  pre.innerHTML = '<div class="preloader_spin">'
    + '<svg viewBox="0 0 34 34" fill="none">'
    + '<g class="ring">'
    + '<circle cx="17" cy="17" r="15" stroke="#0051FF" stroke-width="2" stroke-dasharray="20 75"/>'
    + '<circle cx="17" cy="17" r="10" stroke="#f43737" stroke-width="2" stroke-dasharray="12 51"/>'
    + "</g>"
    + "</svg></div>";
  document.body.appendChild(pre);

  function hidePreloader() {
    pre.classList.add("loaded");
    setTimeout(function () { if (pre.parentNode) pre.parentNode.removeChild(pre); }, 600);
  }
  if (document.readyState === "complete") hidePreloader();
  else window.addEventListener("load", hidePreloader);
  setTimeout(hidePreloader, 3500); // safety net

  /* ---------------- Fixed header ---------------- */
  function activeIdFor(url) {
    var u = url || location.href;
    for (var d in DIR_TO_ID) {
      if (u.indexOf("/" + d + "/") !== -1) return DIR_TO_ID[d];
    }
    return "home";
  }

  var header = document.createElement("header");
  header.className = "site-header";
  var nav = DASHBOARDS.map(function (d) {
    var cls = d.id === activeIdFor() ? "active" : "";
    return '<a data-id="' + d.id + '" class="' + cls + '" href="' + P + d.href + '">' + d.label + "</a>";
  }).join("");
  header.innerHTML = '<div class="_container">'
    + '<a class="brand" href="' + P + 'index.html">' + MARK
    + '<span>Crypto Analytics<span class="brand-sub" style="display:block;">Market Intelligence</span></span></a>'
    + '<nav class="main-nav">' + nav + "</nav>"
    + "</div>";
  document.body.insertBefore(header, document.body.firstChild);

  /* ---------------- Scroll reveal (re-armable after PJAX swaps) ---------------- */
  function armReveal() {
    var reveals = document.querySelectorAll("[data-aos]:not(.aos-animate)");
    if (!reveals.length) return;
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) { e.target.classList.add("aos-animate"); io.unobserve(e.target); }
        });
      }, { threshold: 0.12 });
      reveals.forEach(function (el) { io.observe(el); });
    } else {
      reveals.forEach(function (el) { el.classList.add("aos-animate"); });
    }
  }
  armReveal();

  /* ---------------- Page padding for fixed header ---------------- */
  function fixPadding() {
    document.querySelectorAll("main.page").forEach(function (m) {
      var num = parseFloat(window.getComputedStyle(m).paddingTop);
      if (num >= 140) m.style.paddingTop = "150px";
    });
  }
  fixPadding();

  /* ---------------- PJAX navigation (keeps canvas + header alive) ---------------- */
  function destroyCharts() {
    if (window.Chart && Chart.registry) {
      Chart.registry.getAll().forEach(function (c) { try { c.destroy(); } catch (e) {} });
    }
  }

  async function loadPage(url) {
    var res = await fetch(url, { credentials: "same-origin", headers: { "Accept": "text/html" } });
    if (!res.ok) throw new Error("HTTP " + res.status);
    var html = await res.text();
    var doc = new DOMParser().parseFromString(html, "text/html");
    var main = doc.querySelector("main.page");
    if (!main) throw new Error("no main.page in " + url);

    destroyCharts();
    var cur = document.querySelector("main.page");
    cur.className = main.className;
    cur.innerHTML = main.innerHTML;
    if (doc.title) document.title = doc.title;
    history.pushState({}, "", url);

    /* Run the new page's inline scripts in a function scope so top-level
       const/let never collide with the previous page's declarations. */
    var scripts = Array.prototype.slice.call(doc.querySelectorAll("script:not([src])"));
    scripts.forEach(function (s) {
      try { new Function("window", "document", "globalThis", s.textContent)(); }
      catch (e) { console.error("inline script failed on " + url, e); }
    });

    window.scrollTo(0, 0);
    armReveal();
    fixPadding();
    document.querySelectorAll(".main-nav a").forEach(function (a) {
      a.classList.toggle("active", a.dataset.id === activeIdFor(url));
    });
  }

  function installPJAX() {
    document.addEventListener("click", function (e) {
      var a = e.target && e.target.closest ? e.target.closest("a") : null;
      if (!a || e.defaultPrevented || e.button !== 0) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      var href = a.getAttribute("href");
      if (!href || href.charAt(0) === "#") return;
      if (/^(javascript:|mailto:|tel:|data:|ftp:|https?:|file:)/i.test(href)) return;
      if (/^(https?:)?\/\//i.test(href)) return; // absolute URLs → let browser handle
      try {
        var url = new URL(a.href, location.href);
        if (url.origin !== location.origin) return;
      } catch (err) { return; }
      e.preventDefault();
      loadPage(a.href).catch(function () { location.href = a.href; }); // safe fallback
    });

    window.addEventListener("popstate", function () {
      loadPage(location.href).catch(function () { location.reload(); });
    });
  }
  installPJAX();
})();
