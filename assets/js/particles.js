/* Ambient market backdrop. Include this script once on any dashboard page.
 * The fixed, pointer-transparent canvas sits behind the UI; keep content cards
 * opaque. Wire real BTC momentum later with ParticleBackdrop.setMomentum(-1..1)
 * or ParticleBackdrop.setMomentumSource(function () { return value; }).
 */
(function (window) {
  "use strict";
  if (window.ParticleBackdrop) return;

  var glyphs = ["$", "₿", "↑", "↓", "0.23", "1.47", "-0.08", "0.91", "3.12", "-0.54", "2.08", "0.77", "-1.20", "0.05"];
  var colors = ["#e7e9ed", "#c5cbd1", "#d4af37", "#7bb99b", "#c88f8f"];
  var sizes = [10, 12, 14];
  var maxCount = 3200;
  var particles = [], sprites = [];
  var canvas, ctx, atlas, shapePoints = [];
  var width = 0, height = 0, dpr = 1, frameId = 0, lastTime = 0;
  var momentum = 0, simulated = 0, manual = null, source = null;
  var cluster = null, clusterTimer = 24 + Math.random() * 18;
  var frames = 0, activeCount = 0, running = false;
  var motionPreference = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

  function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
  function random(min, max) { return min + Math.random() * (max - min); }

  // Cache glyphs once; the animation loop uses drawImage instead of thousands of
  // expensive text layout calls. The atlas is independent of viewport dimensions.
  function buildAtlas() {
    atlas = document.createElement("canvas");
    atlas.width = glyphs.length * 64;
    atlas.height = colors.length * sizes.length * 32;
    var a = atlas.getContext("2d");
    a.textAlign = "center";
    a.textBaseline = "middle";
    for (var c = 0; c < colors.length; c++) {
      a.fillStyle = colors[c];
      for (var s = 0; s < sizes.length; s++) {
        a.font = sizes[s] + 'px "Montserrat", system-ui, sans-serif';
        for (var g = 0; g < glyphs.length; g++) {
          a.fillText(glyphs[g], g * 64 + 32, (c * sizes.length + s) * 32 + 16);
          var sw = Math.min(64, Math.ceil(a.measureText(glyphs[g]).width) + 6);
          var sh = sizes[s] + 8;
          sprites[(c * sizes.length + s) * glyphs.length + g] = {
            x: g * 64 + Math.floor((64 - sw) / 2),
            y: (c * sizes.length + s) * 32 + Math.floor((32 - sh) / 2),
            w: sw, h: sh
          };
        }
      }
    }

    // Sample a Bitcoin glyph once for the rare particle-formation effect.
    var mask = document.createElement("canvas");
    mask.width = 96;
    mask.height = 128;
    var m = mask.getContext("2d", { willReadFrequently: true });
    m.fillStyle = "#fff";
    m.textAlign = "center";
    m.textBaseline = "middle";
    m.font = '100px "Montserrat", system-ui, sans-serif';
    m.fillText("₿", 48, 64);
    var pixels = m.getImageData(0, 0, 96, 128).data;
    for (var y = 16; y < 112; y += 5) {
      for (var x = 12; x < 84; x += 5) {
        if (pixels[(y * 96 + x) * 4 + 3] > 100) shapePoints.push([x - 48, y - 64]);
      }
    }
  }

  function chooseColor() {
    var r = Math.random();
    if (r < 0.06) return 2;
    if (r < 0.09 && Math.abs(momentum) > 0.08) return momentum > 0 ? 3 : 4;
    return Math.random() < 0.35 ? 1 : 0;
  }

  function reset(p, initial) {
    p.live = true;
    p.cluster = false;
    p.x = Math.random() * width;
    p.y = Math.random() * height;
    p.vx = random(-4, 4);
    p.vy = random(-2, 2);
    p.glyph = Math.floor(Math.random() * glyphs.length);
    p.color = chooseColor();
    p.size = Math.floor(Math.random() * sizes.length);
    p.sprite = sprites[(p.color * sizes.length + p.size) * glyphs.length + p.glyph];
    p.opacity = random(0.15, 0.45);
    p.life = random(16, 35);
    p.age = initial ? random(1, 8) : 0;
  }

  function resize() {
    var oldWidth = width, oldHeight = height;
    width = window.innerWidth;
    height = window.innerHeight;
    dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (oldWidth && oldHeight) {
      for (var i = 0; i < particles.length; i++) {
        particles[i].x *= width / oldWidth;
        particles[i].y *= height / oldHeight;
      }
      if (cluster) { cluster.x *= width / oldWidth; cluster.y *= height / oldHeight; }
    }
  }

  function targetCount() {
    // Keep 2,000–2,800 on a desktop; scale down on small screens to avoid a
    // dense wall of overlapping text and unnecessary mobile rendering work.
    var viewportScale = Math.min(1, Math.max(0.42, Math.sqrt(width * height / (1440 * 900))));
    return Math.round((2400 + momentum * 400) * viewportScale);
  }

  function startCluster() {
    if (!shapePoints.length || width < 200 || height < 200) return;
    var members = [], i;
    for (i = 0; i < particles.length && members.length < 28; i++) {
      if (particles[i].live && !particles[i].cluster) members.push(particles[i]);
    }
    if (members.length < 12) return;
    cluster = { x: random(width * 0.18, width * 0.82), y: random(height * 0.2, height * 0.8), age: 0, members: members };
    for (i = 0; i < members.length; i++) {
      var p = members[i];
      var point = shapePoints[Math.floor(i * shapePoints.length / members.length)];
      p.cluster = true;
      p.targetX = cluster.x + point[0];
      p.targetY = cluster.y + point[1];
      p.startX = cluster.x + random(-85, 85);
      p.startY = cluster.y + random(-75, 75);
      p.x = p.startX;
      p.y = p.startY;
      p.color = Math.random() < 0.25 ? 2 : 0;
      p.sprite = sprites[(p.color * sizes.length + p.size) * glyphs.length + p.glyph];
    }
  }

  function updateCluster(dt) {
    if (!cluster) return;
    cluster.age += dt;
    var age = cluster.age;
    var members = cluster.members;
    for (var i = 0; i < members.length; i++) {
      var p = members[i];
      if (age < 3) {
        var t = age / 3;
        t = t * t * (3 - 2 * t);
        p.x = p.startX + (p.targetX - p.startX) * t;
        p.y = p.startY + (p.targetY - p.startY) * t;
      } else if (age > 6) {
        p.x += p.vx * dt;
        p.y += (p.vy - momentum * 12) * dt;
      }
    }
    if (age >= 9) {
      for (var j = 0; j < members.length; j++) {
        members[j].cluster = false;
        members[j].age = 0;
        members[j].life = random(16, 35);
      }
      cluster = null;
    }
  }

  function frame(now) {
    if (!running) return;
    frameId = requestAnimationFrame(frame);
    if (document.hidden) { lastTime = now; return; }
    var dt = Math.min(Math.max((now - lastTime) / 1000, 0), 0.05);
    lastTime = now;
    var reduced = motionPreference && motionPreference.matches;
    var target = manual === null ? simulated : manual;
    if (source) {
      try { var value = Number(source()); if (Number.isFinite(value)) target = clamp(value, -1, 1); } catch (e) { /* keep last momentum */ }
    } else if (manual === null && !reduced) {
      simulated = clamp(simulated + random(-0.015, 0.015) * dt, -0.45, 0.45);
      target = simulated;
    }
    momentum += (target - momentum) * Math.min(1, dt * 1.2);
    if (!reduced) {
      clusterTimer -= dt;
      if (clusterTimer <= 0 && !cluster) { startCluster(); clusterTimer = random(38, 65); }
      updateCluster(dt);
    }

    var desired = targetCount();
    activeCount = 0;
    ctx.clearRect(0, 0, width, height);
    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      // Pool slots outside the density target fade out instead of disappearing.
      if (i >= desired && !p.cluster) {
        if (p.live) { p.age = Math.max(p.age, p.life - 2); p.age += reduced ? 0 : dt; if (p.age >= p.life) p.live = false; }
      } else if (!p.live) {
        reset(p, false);
      }
      if (!p.live) continue;
      activeCount++;
      if (!reduced && !p.cluster) {
        p.age += dt;
        p.x += p.vx * dt;
        p.y += (p.vy - momentum * 20) * dt;
        if (p.age >= p.life || p.x < -40 || p.x > width + 40 || p.y < -30 || p.y > height + 30) reset(p, false);
      }
      var fade = p.cluster ? Math.min(1, cluster.age / 2, (9 - cluster.age) / 3) : Math.min(1, p.age / 2, (p.life - p.age) / 2);
      ctx.globalAlpha = p.opacity * clamp(fade, 0, 1);
      var sprite = p.sprite;
      ctx.drawImage(atlas, sprite.x, sprite.y, sprite.w, sprite.h, p.x - sprite.w / 2, p.y - sprite.h / 2, sprite.w, sprite.h);
    }
    // A faint larger glyph emerges from the clustered characters, then dissolves.
    if (cluster) {
      var clusterFade = clamp(Math.min((cluster.age - 2) / 1.5, (9 - cluster.age) / 3), 0, 1);
      ctx.globalAlpha = 0.12 * clusterFade;
      ctx.font = '90px "Montserrat", system-ui, sans-serif';
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#d4af37";
      ctx.fillText("₿", cluster.x, cluster.y);
    }
    ctx.globalAlpha = 1;
    frames++;
  }

  function init() {
    canvas = document.createElement("canvas");
    canvas.id = "particle-backdrop";
    canvas.setAttribute("aria-hidden", "true");
    // The shared chart stylesheet caps canvas height; explicitly exempt the
    // backdrop so its visible CSS box fills the entire viewport on every page.
    canvas.style.cssText = "position:fixed;inset:0;width:100%;height:100%;max-width:none;max-height:none;z-index:-1;pointer-events:none;";
    document.body.appendChild(canvas);
    ctx = canvas.getContext("2d");
    if (!ctx) return;
    resize();
    buildAtlas();
    for (var i = 0; i < maxCount; i++) { var p = {}; if (i < targetCount()) reset(p, true); else p.live = false; particles.push(p); }
    window.addEventListener("resize", resize, { passive: true });
    document.addEventListener("visibilitychange", function () { lastTime = performance.now(); });
    running = true;
    lastTime = performance.now();
    frameId = requestAnimationFrame(frame);
  }

  window.ParticleBackdrop = {
    setMomentum: function (value) { if (Number.isFinite(Number(value))) { source = null; manual = clamp(Number(value), -1, 1); } },
    setMomentumSource: function (fn) { source = typeof fn === "function" ? fn : null; manual = null; },
    getMomentum: function () { return momentum; },
    setPaused: function (paused) {
      if (paused && running) { running = false; cancelAnimationFrame(frameId); }
      else if (!paused && !running && ctx) { running = true; lastTime = performance.now(); frameId = requestAnimationFrame(frame); }
    },
    getStats: function () { return { activeCount: activeCount, targetCount: targetCount(), frames: frames, clusterActive: !!cluster }; }
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})(window);
