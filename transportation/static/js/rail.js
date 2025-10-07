// Edge‑Peek Rail: zero‑to‑one sidebar with peek, pin, ripple, and recents
(function(){
  const LS_PIN = 'tfam-rail-pinned';
  const LS_RECENTS = 'tfam-rail-recents';
  const body = document.body;
  const rail = document.getElementById('app-rail');
  const edge = document.getElementById('edge-activator');
  const btnHamburger = document.getElementById('railHamburger');
  const btnClose = document.getElementById('railClose');
  const btnPin = document.getElementById('railPin');
  const recentsEl = document.getElementById('rail-recents');

  if (!rail) return;

  // Compute dynamic header/footer heights so the rail sits between them
  function updateChromeOffsets(){
    const header = document.querySelector('.header');
    const footer = document.querySelector('.footer');
    const hh = header ? header.offsetHeight : 0;
    const fh = footer ? footer.offsetHeight : 0;
    document.documentElement.style.setProperty('--header-h', hh + 'px');
    document.documentElement.style.setProperty('--footer-h', fh + 'px');
  }
  updateChromeOffsets();
  window.addEventListener('resize', updateChromeOffsets);
  window.addEventListener('orientationchange', updateChromeOffsets);
  window.addEventListener('load', updateChromeOffsets);

  let isPeek = false;
  // Default to expanded on desktop if no saved preference
  const savedPin = localStorage.getItem(LS_PIN);
  let pinned = (savedPin === '1') || (savedPin === null && window.matchMedia('(min-width: 1024px)').matches);

  function open(peek=false){
    isPeek = peek;
    body.classList.add('rail-open');
    rail.setAttribute('aria-expanded','true');
  }
  function close(force=false){
    if (pinned && !force) return; // keep open if pinned
    isPeek = false;
    body.classList.remove('rail-open');
    rail.setAttribute('aria-expanded','false');
  }
  function toggle(){
    if (body.classList.contains('rail-open')) close(true); else open(false);
  }

  // Persisted pin state
  function applyPinState(){
    if (pinned){
      open(false);
      btnPin && btnPin.setAttribute('aria-pressed','true');
    } else {
      btnPin && btnPin.setAttribute('aria-pressed','false');
      // On mobile, start closed; on desktop, collapsed is CSS default
      if (window.matchMedia('(max-width: 1023px)').matches){
        close(true);
      }
    }
  }
  applyPinState();

  // Controls
  btnHamburger && btnHamburger.addEventListener('click', toggle);
  btnClose && btnClose.addEventListener('click', function(){ close(true); });
  btnPin && btnPin.addEventListener('click', function(){
    pinned = !pinned;
    localStorage.setItem(LS_PIN, pinned ? '1' : '0');
    applyPinState();
  });

  // Edge hover/press to peek (mobile first)
  if (edge){
    // Mouse hover peek
    edge.addEventListener('pointerenter', function(){ if (!pinned) open(true); });
    rail.addEventListener('pointerleave', function(e){
      // If pointer leaves rail to the right, close peek
      if (!pinned && isPeek) close();
    });
    // Tap/press peek on touch
    let pressTimer;
    edge.addEventListener('pointerdown', function(){
      if (pinned) return;
      clearTimeout(pressTimer);
      pressTimer = setTimeout(function(){ open(true); }, 180);
    });
    window.addEventListener('pointerup', function(){
      clearTimeout(pressTimer);
      if (!pinned && isPeek) close();
    });
  }

  // ESC closes when not pinned
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape') close(true);
  });

  // Ripple spotlight: track mouse position
  rail.addEventListener('mousemove', function(ev){
    const t = ev.target.closest('.rail-item');
    if (!t) return;
    const rect = t.getBoundingClientRect();
    const mx = (ev.clientX - rect.left) + 'px';
    const my = (ev.clientY - rect.top) + 'px';
    t.style.setProperty('--mx', mx);
    t.style.setProperty('--my', my);
  });

  // Recents: keep last 6 unique by url
  function loadRecents(){
    try { return JSON.parse(localStorage.getItem(LS_RECENTS) || '[]'); } catch(e){ return []; }
  }
  function saveRecents(list){
    localStorage.setItem(LS_RECENTS, JSON.stringify(list.slice(0,6)));
  }
  function recordRecent(type, label, url, icon){
    const list = loadRecents().filter(x => x.url !== url);
    list.unshift({ type, label, url, icon, ts: Date.now() });
    saveRecents(list);
  }
  function renderRecents(){
    if (!recentsEl) return;
    const list = loadRecents();
    recentsEl.innerHTML = '';
    if (!list.length){
      const empty = document.createElement('div');
      empty.className = 'rail-recent';
      empty.textContent = 'No recent items yet';
      recentsEl.appendChild(empty);
      return;
    }
    list.forEach(item => {
      const a = document.createElement('a');
      a.className = 'rail-recent';
      a.href = item.url;
      a.title = item.label;
      a.innerHTML = `<span class="rec-ico">${item.icon || '📄'}</span><span class="rec-label">${item.label}</span>`;
      recentsEl.appendChild(a);
    });
  }

  // Heuristic: record Truck detail visits if present
  function detectTruckDetail(){
    // Known container on truck_detail.html
    const status = document.getElementById('real-time-status');
    if (!status || !status.dataset || !status.dataset.truckId) return;
    const plateAttr = status.dataset.truckPlate;
    const plateFromHeader = (document.querySelector('.detail-title')?.textContent || '').split(':').slice(1).join(':').trim();
    const label = plateAttr || plateFromHeader || ('Truck #' + status.dataset.truckId);
    recordRecent('truck', label, window.location.pathname, '🚚');
  }

  // Initial run
  try { detectTruckDetail(); } catch(e) {}
  renderRecents();

  // Highlight current route
  try {
    const cur = location.pathname.replace(/\/$/,'');
    rail.querySelectorAll('.rail-nav a').forEach(a => {
      const href = a.getAttribute('href') || '';
      const path = href.replace(/\/$/,'');
      if (path && cur === path) a.setAttribute('aria-current','page');
    });
  } catch(e){}

  // Re-render recents when user navigates within SPA-like contexts (not common in Django but cheap)
  document.addEventListener('visibilitychange', function(){ if (!document.hidden) renderRecents(); });
})();
