// dashboard.js - lightweight animations and auto-highlights
(function () {
  function easeOutQuad(t) { return t * (2 - t); }

  function parseNumber(text) {
    if (!text) return 0;
    var n = parseFloat(String(text).replace(/,/g, '').trim());
    return isNaN(n) ? 0 : n;
  }

  function countUp(el) {
    var targetStr = (el.getAttribute('data-target') || el.textContent || '0').trim();
    var decimals = parseInt(el.getAttribute('data-decimals') || '0', 10);
    var target = parseNumber(targetStr);
    var duration = 900; // ms
    var start = 0;
    var startTs = null;

    function step(ts) {
      if (!startTs) startTs = ts;
      var p = Math.min((ts - startTs) / duration, 1);
      var v = start + (target - start) * easeOutQuad(p);
      el.textContent = v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function countTo(el, target, decimals) {
    decimals = parseInt(decimals != null ? decimals : (el.getAttribute('data-decimals') || '0'), 10);
    var start = parseNumber(el.textContent);
    var duration = 700;
    var startTs = null;
    function step(ts) {
      if (!startTs) startTs = ts;
      var p = Math.min((ts - startTs) / duration, 1);
      var v = start + (target - start) * easeOutQuad(p);
      el.textContent = v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function rotateHighlights(container) {
    var items = Array.prototype.slice.call(container.querySelectorAll('.highlight-item'));
    if (!items.length) return;
    var idx = 0, timer = null, stopped = false;

    function show(i) {
      items.forEach(function (n, j) { n.classList.toggle('visible', j === i); });
    }
    function next() {
      idx = (idx + 1) % items.length;
      show(idx);
    }
    function start() {
      if (timer) clearInterval(timer);
      timer = setInterval(next, 5000);
    }
    function stop() {
      if (timer) clearInterval(timer);
      stopped = true;
    }

    // First render
    show(0);
    start();

    // Pause on user interaction
    ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach(function (evt) {
      window.addEventListener(evt, function () { if (!stopped) stop(); }, { once: true, passive: true });
    });
  }

  function autopilotSpotlight() {
    var sections = Array.prototype.slice.call(document.querySelectorAll('.dashboard .section'));
    if (!sections.length) return;
    var i = 0;
    var rounds = 0;
    var interval = setInterval(function () {
      sections.forEach(function (s, j) { if (j === i) s.classList.add('spotlight'); else s.classList.remove('spotlight'); });
      i = (i + 1) % sections.length;
      rounds++;
      if (rounds > sections.length * 2) { // run two cycles then stop
        sections.forEach(function (s) { s.classList.remove('spotlight'); });
        clearInterval(interval);
      }
    }, 2200);

    // Stop on user interaction
    ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach(function (evt) {
      window.addEventListener(evt, function () {
        clearInterval(interval);
        sections.forEach(function (s) { s.classList.remove('spotlight'); });
      }, { once: true, passive: true });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    // Animate KPI numbers
    document.querySelectorAll('.kpi-value[data-countup]').forEach(countUp);

    // Rotate highlight messages
    var highlights = document.querySelector('.highlights');
    if (highlights) rotateHighlights(highlights);

    // Spotlight sections briefly on load
    autopilotSpotlight();

    // Reveal-on-scroll for cards and list items
    try {
      var io = new IntersectionObserver(function(entries){
        entries.forEach(function(ent){ if(ent.isIntersecting){ ent.target.classList.add('revealed'); io.unobserve(ent.target); } });
      }, { rootMargin: '0px 0px -10% 0px', threshold: 0.05 });
      document.querySelectorAll('[data-reveal]').forEach(function(el){ io.observe(el); });
    } catch(e) {}

    // Live refresh for KPIs
    function refreshKPIs() {
      fetch('/dashboard/data/', { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (data) {
          Object.keys(data).forEach(function (key) {
            var nodes = document.querySelectorAll('[data-kpi="' + key + '"]');
            nodes.forEach(function (el) {
              var decimals = (key.indexOf('revenue') === 0 || key.indexOf('income') === 0) ? 2 : parseInt(el.getAttribute('data-decimals') || '0', 10);
              countTo(el, parseFloat(data[key]) || 0, decimals);
              if (key.endsWith('_change_pct')) {
                // Toggle up/down classes for delta pills
                el.classList.toggle('delta-up', (parseFloat(data[key]) || 0) >= 0);
                el.classList.toggle('delta-down', (parseFloat(data[key]) || 0) < 0);
                el.textContent = ((parseFloat(data[key]) || 0) >= 0 ? '+' : '') + (parseFloat(data[key]) || 0).toFixed(1) + '%';
              }
            });
          });
        })
        .catch(function () { /* ignore for dev */ });
    }

    // Initial delayed refresh then periodic
    setTimeout(refreshKPIs, 3000);
    setInterval(refreshKPIs, 45000);
  });
})();
