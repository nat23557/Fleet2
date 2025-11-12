
document.addEventListener('DOMContentLoaded', function () {
  // Rotation removed: only show a notice on small portrait viewports
  const pageRoot = document.getElementById('page-rotate-root');
  const viewport = document.getElementById('stock-levels-viewport');
  const filtersBtn = document.getElementById('filters-btn');
  const filtersEl = document.getElementById('stock-filters');
  const alertEl = document.getElementById('orientation-alert');
  let alertTimer = null;
  let filtersCollapse = null;
  try {
    if (filtersEl && window.bootstrap) {
      filtersCollapse = new bootstrap.Collapse(filtersEl, { toggle: false });
    }
  } catch {}

  function handleOrientation() {
    const target = pageRoot || viewport;
    if (target) {
      // Ensure no rotate classes/styles remain
      target.classList.remove('rotate');
      target.style.removeProperty('--rotate-scale');
    }
    const isPortrait = window.matchMedia('(orientation: portrait)').matches;
    const vw = Math.max(document.documentElement.clientWidth || 0, window.innerWidth || 0);
    const showNotice = vw < 768 && isPortrait;

    if (!alertEl) return;

    // clear any pending timer
    if (alertTimer) { clearTimeout(alertTimer); alertTimer = null; }

    if (showNotice && !localStorage.getItem('stockLevelsAlertDismissed')) {
      alertEl.classList.remove('d-none');
      // Auto-dismiss after 5 seconds
      alertTimer = setTimeout(() => {
        try {
          if (window.bootstrap && bootstrap.Alert) {
            bootstrap.Alert.getOrCreateInstance(alertEl).close();
          } else {
            alertEl.classList.add('d-none');
          }
        } catch {}
        // Remember dismissal to avoid flicker on resize
        localStorage.setItem('stockLevelsAlertDismissed', 'true');
      }, 5000);
    } else {
      alertEl.classList.add('d-none');
    }
  }

  if (filtersBtn && filtersCollapse) {
    filtersBtn.addEventListener('click', () => filtersCollapse.toggle());
  }

  if (filtersEl) {
    filtersEl.addEventListener('shown.bs.collapse', () => {
      if (filtersBtn) {
        filtersBtn.textContent = 'Hide Filters';
        filtersBtn.setAttribute('aria-expanded', 'true');
      }
    });
    filtersEl.addEventListener('hidden.bs.collapse', () => {
      if (filtersBtn) {
        filtersBtn.textContent = 'Show Filters';
        filtersBtn.setAttribute('aria-expanded', 'false');
      }
    });
  }

  if (alertEl) {
    // Persist manual close
    alertEl.addEventListener('closed.bs.alert', () => {
      localStorage.setItem('stockLevelsAlertDismissed', 'true');
    });
  }

  window.addEventListener('resize', handleOrientation);
  window.addEventListener('orientationchange', handleOrientation);
  handleOrientation();
});
