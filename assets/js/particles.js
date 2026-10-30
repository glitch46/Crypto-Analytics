/*! ============================================================================
 *  Crypto Analytics — Ambient Particle Backdrop  (v1.1)
 *  ----------------------------------------------------------------------------
 *  Self-contained, dependency-free. Drop it into ANY page with a single tag:
 *
 *      <script src="assets/js/particles.js"></script>
 *
 *  It creates its own fixed, full-viewport <canvas> positioned behind your UI
 *  (z-index: -1, pointer-events: none) so the dashboard stays fully readable
 *  and never blocked. No HTML, CSS or UI is added beyond the canvas.
 *
 *  OVERLAY BEHIND AN EXISTING LAYOUT
 *  --------------------------------
 *  Nothing to do. The canvas is fixed/inset:0 with z-index:-1, so it sits
 *  behind every element that has a stacking context above it. If a page uses a
 *  very high z-index background layer, just raise the canvas above it
 *  (set canvas.style.zIndex = <n>) and make sure your dashboard content has a
 *  higher z-index (position:relative; z-index:1 on <main>).
 *
 *  DRIVING IT WITH REAL PRICE MOMENTUM (later)
 *  -------------------------------------------
 *  One of:
 *    ParticleBackdrop.setMomentum(0.6)                       // -1 .. 1, manual
 *    ParticleBackdrop.setMomentumSource(function () {        // polled each frame
 *      const chg = (btc.now - btc.prev) / btc.prev;          // e.g. fractional move
 *      return Math.max(-1, Math.min(1, chg * 40));           // +/-2.5% -> +/-1
 *    });
 *  Positive momentum = upward drift + higher density + sparse green accents.
 *  Until a source is supplied, a gentle simulated random-walk runs by default.
 *
 *  PERFORMANCE
 *  -----------
 *  Pre-allocated object pool (no per-frame allocation), single clearRect per
 *  frame, integer font-size cache, color-grouped draw passes, DPR capped at 2,
 *  and an rAF loop that self-pauses when the tab is hidden. Tuned for 2k-4k
 *  particles at 60fps on a typical desktop.
 * ========================================================================== */
(function (global) {
  "use strict";

  var CONFIG = {
    maxParticles: 3600,          // hard cap == object-pool size
    baseCount: 2000,             // density at momentum 0
    densityGain: 1200,           // added particles at momentum +1
    densityLoss: 700,            // removed particles at momentum -1
    driftPerMomentum: 0.85,      // px/frame of upward drift per +1 momentum
    swayAmp: 0.35,               // gentle horizontal sway
    minAlpha: 0.25,              // opacity floor (raised for visibility)
    maxAlpha: 0.6,               // opacity ceiling (raised for visibility)
    fadeSpeed: 0.035,            // alpha ease toward target
    sizeMin: 12,                 // font px (raised so glyphs are readable)
    sizeMax: 17,
    clusterEvery: 26,            // avg seconds between big-BTC clusters
    clusterParticles: 22,        // particles that form one big BTC symbol
    clusterGather: 1.8,          // seconds to coalesce
    clusterHold: 3.2,            // seconds to linger
    clusterDissolve: 2.2,        // seconds to dissolve
    clusterAlpha: 0.35,          // low contrast on purpose, but visible
    clusterSizeMin: 22,
    clusterSizeMax: 30,
    goldChance: 0.12,            // sparse gold accents
    accentChance: 0.07           // green/red tied to momentum direction
  };

  /* Glyph set: single chars plus short decimal strings. */
  var GLYPHS = ["$", "₿", "↑", "↓",
    "0.23", "1.47", "-0.08", "0.91", "3.12", "-0.54",
    "2.08", "0.77", "-1.20", "0.05", "4.66", "-0.31"];

  /* Colors as plain "r,g,b" strings; alpha applied via globalAlpha. */
  var WHITE = "255,255,255";
  var GRAY = "205,210,220";
  var GOLD = "212,175,55";   // #d4af37
  var GREEN = "0,210,106";
  var RED = "244,55,55";

  /* ------------------------------------------------------------------ state */
  var canvas = null, ctx = null;
  var w = 0, h = 0, dpr = 1;
  var pool = [];                 // fixed-size object pool
  var clusters = [];             // occasional big-BTC clusters
  var clusterTimer = 8 + Math.random() * 10;

  var momentum = 0;              // smoothed, in [-1, 1]
  var momentumSource = null;     // optional fn() -> [-1, 1], polled each frame
  var manualMomentum = 0;        // set via setMomentum()
  var useManual = false;
  var simMomentum = 0;           // default simulated walk

  var last = 0, t = 0;
  var rng = mulberry32(seedFromStorage());
  var fontCache = {};
  var rafId = null;
  var running = false;

  /* --------------------------------------------------------------- helpers */
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var x = Math.imul(a ^ (a >>> 15), 1 | a);
      x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
      return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
    };
  }
  function seedFromStorage() {
    try {
      var s = sessionStorage.getItem("ca_particle_seed");
      if (s) return parseInt(s, 10) || 1;
      s = (Math.random() * 2147483647) | 0;
      sessionStorage.setItem("ca_particle_seed", String(s));
      return s;
    } catch (e) { return (Math.random() * 2147483647) | 0; }
  }
  function saveMomentum() {
    try { sessionStorage.setItem("ca_momentum", String(momentum)); } catch (e) {}
  }
  function restoreMomentum() {
    try {
      var m = parseFloat(sessionStorage.getItem("ca_momentum"));
      if (isFinite(m)) momentum = Math.max(-1, Math.min(1, m));
    } catch (e) {}
  }
  function rand(a, b) { return a + rng() * (b - a); }
  function rint(a, b) { return Math.floor(rand(a, b + 1)); }
  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
  function fontFor(sz) {
    if (!fontCache[sz]) fontCache[sz] = sz + 'px "Montserrat", "Plus Jakarta Sans", system-ui, sans-serif';
    return fontCache[sz];
  }

  /* --------------------------------------------------------------- particles */
  function makeParticle() {
    return {
      live: false, x: 0, y: 0, vx: 0, baseVy: 0, size: 10, char: "$",
      color: 0, alpha: 0, target: 0, baseTarget: 0, life: 0, phase: 0,
      cluster: null, ax: 0, ay: 0
    };
  }

  function pickChar() { return GLYPHS[rint(0, GLYPHS.length - 1)]; }

  function pickColor() {
    var r = rng();
    if (r < CONFIG.goldChance) return 2;                  // gold
    if (r < CONFIG.goldChance + CONFIG.accentChance) {    // green/red by momentum
      return momentum >= 0 ? 3 : 4;
    }
    return rng() < 0.35 ? 1 : 0;                          // white / light gray
  }

  function spawn(p) {
    p.live = true;
    p.x = rng() * w;
    p.y = rng() * h;                                      // spread across viewport
    p.size = rint(CONFIG.sizeMin, CONFIG.sizeMax);
    p.char = pickChar();
    p.color = pickColor();
    p.phase = rng() * Math.PI * 2;
    p.life = 6 + rng() * 16;                              // seconds
    p.vx = (rng() - 0.5) * 0.4;
    p.baseVy = -(0.06 + rng() * 0.12);                    // gentle base upward float
    p.baseTarget = CONFIG.minAlpha + rng() * (CONFIG.maxAlpha - CONFIG.minAlpha);
    p.target = p.baseTarget;
    p.alpha = 0;                                          // fade in
    p.cluster = null;
  }

  /* ------------------------------------------------------------- clusters */
  function spawnCluster() {
    var members = [];
    for (var i = 0; i < pool.length && members.length < CONFIG.clusterParticles; i++) {
      var p = pool[i];
      if (!p.live && !p.cluster) members.push(p);
    }
    if (members.length < 4) return;
    var cx = rand(w * 0.2, w * 0.8);
    var cy = rand(h * 0.2, h * 0.75);
    var spread = rand(16, 30);
    members.forEach(function (p) {
      p.live = true;
      p.cluster = true;
      p.size = rint(CONFIG.clusterSizeMin, CONFIG.clusterSizeMax);
      p.char = "₿";
      p.color = 2;                                        // soft gold BTC symbol
      p.ax = cx + (rng() - 0.5) * spread * 2;
      p.ay = cy + (rng() - 0.5) * spread * 0.8;
      p.vx = (rng() - 0.5) * 0.3;
      p.baseVy = (rng() - 0.5) * 0.2;
      p.alpha = 0;
      p.target = 0;
    });
    clusters.push({ members: members, age: 0 });
  }

  function updateClusters(dt) {
    for (var ci = clusters.length - 1; ci >= 0; ci--) {
      var c = clusters[ci];
      c.age += dt / 60;                                    // seconds
      var gather = CONFIG.clusterGather;
      var holdEnd = gather + CONFIG.clusterHold;
      var dissolveEnd = holdEnd + CONFIG.clusterDissolve;
      var target = CONFIG.clusterAlpha;

      if (c.age >= dissolveEnd) {                         // done — hand back to pool
        c.members.forEach(function (p) {
          p.target = 0; p.life = 0.4; p.cluster = null;   // fade out via main loop
        });
        clusters.splice(ci, 1);
        continue;
      }
      if (c.age >= holdEnd) {                             // dissolving
        var k = (c.age - holdEnd) / CONFIG.clusterDissolve;
        target = CONFIG.clusterAlpha * (1 - k);
        c.members.forEach(function (p) {
          p.vx += (rng() - 0.5) * 0.02;
          p.baseVy += (rng() - 0.5) * 0.02;
        });
      } else if (c.age >= gather) {                       // holding
        target = CONFIG.clusterAlpha;
      } else {                                            // gathering (ramp in)
        target = CONFIG.clusterAlpha * Math.min(1, c.age / gather);
      }

      var driftY = -momentum * CONFIG.driftPerMomentum * 0.4;
      c.members.forEach(function (p) {
        var f = 0.045;
        p.x += (p.ax - p.x) * f + p.vx * dt;
        p.y += (p.ay - p.y) * f + (p.baseVy + driftY) * dt;
        p.ax += driftY * dt * 0.5;                        // whole glyph drifts with momentum
        p.target = target;
        p.alpha += (target - p.alpha) * CONFIG.fadeSpeed;
      });
    }
  }

  /* ------------------------------------------------------------- density */
  function targetCount() {
    var c = momentum >= 0
      ? CONFIG.baseCount + momentum * CONFIG.densityGain
      : CONFIG.baseCount + momentum * CONFIG.densityLoss;
    return Math.round(clamp(c, CONFIG.baseCount - CONFIG.densityLoss, CONFIG.maxParticles));
  }

  function adjustDensity() {
    var want = targetCount();
    var norm = 0;
    for (var i = 0; i < pool.length; i++) if (pool[i].live && !pool[i].cluster) norm++;
    var diff = want - norm;
    if (diff > 0) {                                       // need more — spawn a few
      var n = Math.min(diff, 3);
      for (var s = 0; s < n; s++) {
        for (var k = 0; k < pool.length; k++) {
          if (!pool[k].live) { spawn(pool[k]); break; }
        }
      }
    } else if (diff < 0) {                                // too many — ease some out
      var fade = Math.min(-diff, 2);
      for (var f = 0; f < fade; f++) {
        for (var j = 0; j < pool.length; j++) {
          var p = pool[j];
          if (p.live && !p.cluster && p.alpha > 0.02 && p.life > 1) {
            p.life = Math.min(p.life, 0.6);
            p.target = 0;
            break;
          }
        }
      }
    }
  }

  /* ------------------------------------------------------------- frame */
  function frame(now) {
    rafId = requestAnimationFrame(frame);
    if (document.hidden) { last = now; return; }

    var dt = Math.min((now - last) / 16.667, 2.5);        // normalize to 60fps
    last = now;
    t = now / 1000;

    /* momentum: source fn > manual value > simulated walk */
    var target = momentumSource
      ? clamp(momentumSource(), -1, 1)
      : (useManual ? manualMomentum : simMomentum);
    if (!momentumSource && !useManual) {
      simMomentum += (rng() - 0.5) * 0.02;                // gentle random walk
      simMomentum *= 0.999;                               // mean-reverting
      simMomentum = clamp(simMomentum, -0.55, 0.55);
    }
    momentum += (target - momentum) * 0.02;               // smooth

    /* rare big-BTC cluster */
    clusterTimer -= dt / 60;                              // seconds
    if (clusterTimer <= 0) { spawnCluster(); clusterTimer = CONFIG.clusterEvery + rng() * 14; }

    adjustDensity();
    updateClusters(dt);

    var driftY = -momentum * CONFIG.driftPerMomentum;     // positive = upward

    /* update — reuses pool objects, zero per-frame allocation */
    for (var i = 0; i < pool.length; i++) {
      var p = pool[i];
      if (p.cluster) continue;                            // handled by updateClusters
      if (!p.live) continue;                              // free slot
      p.life -= dt / 60;                                  // seconds at 60fps-normalized dt

      if (p.life <= 0) {
        p.target = 0;
      } else {
        /* gentle twinkle */
        p.target = p.baseTarget * (0.72 + 0.28 * Math.sin(t * 1.6 + p.phase));
      }
      p.alpha += (p.target - p.alpha) * CONFIG.fadeSpeed;

      p.x += (p.vx + Math.sin(t * 0.5 + p.phase) * CONFIG.swayAmp * 0.02) * dt;
      p.y += (p.baseVy + driftY) * dt;

      if (p.alpha <= 0.001 && p.life <= 0) {
        p.live = false;                                   // fully faded → available
      } else if (p.y < -30 || p.y > h + 30 || p.x < -40 || p.x > w + 40) {
        spawn(p);                                         // recycle offscreen
      }
    }

    /* draw — color-grouped passes, cached fonts, globalAlpha per particle */
    ctx.clearRect(0, 0, w, h);
    var COLORS = [WHITE, GRAY, GOLD, GREEN, RED];
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (var c = 0; c < COLORS.length; c++) {
      ctx.fillStyle = "rgb(" + COLORS[c] + ")";
      for (var j = 0; j < pool.length; j++) {
        var q = pool[j];
        if (!q.live || q.cluster || q.color !== c || q.alpha <= 0.005) continue;
        ctx.globalAlpha = q.alpha;
        ctx.font = fontFor(q.size);
        ctx.fillText(q.char, q.x, q.y);
      }
    }
    ctx.globalAlpha = 1;
  }

  /* -------------------------------------------------------------- lifecycle */
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = window.innerWidth;
    h = window.innerHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    /* keep particles inside the new viewport */
    for (var i = 0; i < pool.length; i++) {
      var p = pool[i];
      p.x = Math.min(Math.max(p.x, -40), w + 40);
      p.y = Math.min(Math.max(p.y, -30), h + 30);
    }
  }

  function buildPool() {
    for (var i = 0; i < CONFIG.maxParticles; i++) pool.push(makeParticle());
    var c = momentum >= 0
      ? CONFIG.baseCount + momentum * CONFIG.densityGain
      : CONFIG.baseCount + momentum * CONFIG.densityLoss;
    var start = Math.round(clamp(c, CONFIG.baseCount - CONFIG.densityLoss, CONFIG.maxParticles));
    for (var k = 0; k < pool.length; k++) {
      if (k < start) spawn(pool[k]);
    }
  }

  function init() {
    if (running) return;
    running = true;
    restoreMomentum();
    canvas = document.createElement("canvas");
    canvas.id = "particle-backdrop";
    canvas.setAttribute("aria-hidden", "true");
    canvas.style.cssText =
      "position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;pointer-events:none;";
    document.body.appendChild(canvas);
    ctx = canvas.getContext("2d");
    resize();                                             // sets w/h BEFORE pool spawn
    buildPool();
    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("pagehide", saveMomentum);
    last = performance.now();
    rafId = requestAnimationFrame(frame);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  /* ------------------------------------------------------------ public API */
  global.ParticleBackdrop = {
    /** Set momentum manually. @param {number} v in [-1, 1] */
    setMomentum: function (v) {
      momentumSource = null;
      useManual = true;
      manualMomentum = clamp(v, -1, 1);
    },
    /** Poll momentum each frame from a function returning [-1, 1]. */
    setMomentumSource: function (fn) {
      momentumSource = typeof fn === "function" ? fn : null;
      if (momentumSource) useManual = false;
    },
    /** Current smoothed momentum in [-1, 1]. */
    getMomentum: function () { return momentum; },
    /** Pause / resume the render loop (e.g. while a modal is open). */
    setPaused: function (v) {
      if (v && running) { cancelAnimationFrame(rafId); running = false; }
      else if (!v && !running) { running = true; last = performance.now(); rafId = requestAnimationFrame(frame); }
    },
    /** Debug counters — not part of the public API contract. */
    _debug: function () {
      var live = 0, vis = 0;
      for (var i = 0; i < pool.length; i++) {
        if (pool[i].live) { live++; if (pool[i].alpha > 0.005) vis++; }
      }
      return { pool: pool.length, live: live, visible: vis, momentum: momentum, clusters: clusters.length };
    }
  };
})(window);
