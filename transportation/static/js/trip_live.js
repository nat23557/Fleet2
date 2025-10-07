// trip_live.js - lightweight live GPS refresh for trips
(function(){
  function fmtAge(sec){
    if (sec == null) return '-';
    if (sec < 90) return sec + 's';
    var m = Math.round(sec/60);
    if (m < 90) return m + 'm';
    var h = Math.round(m/60);
    return h + 'h';
  }

  function updateList(items){
    items.forEach(function(it){
      var node = document.querySelector('[data-trip="'+it.trip_id+'"]');
      if(!node) return;
      var loc = node.querySelector('.live-loc');
      var spd = node.querySelector('.live-speed');
      var eng = node.querySelector('.live-engine');
      var upd = node.querySelector('.live-updated');
      if(loc) loc.textContent = it.loc || '-';
      if(spd) spd.textContent = it.speed != null ? (Math.round(it.speed) + ' km/h') : '-';
      if(eng) eng.textContent = it.engine || '-';
      if(upd) upd.textContent = fmtAge(it.age_seconds);
      // badge color if stale
      var badge = node.querySelector('.badge');
      if (badge && typeof it.age_seconds === 'number') {
        var stale = it.age_seconds > 10*60; // 10 minutes
        badge.classList.toggle('red', stale);
        badge.classList.toggle('amber', !stale);
        badge.classList.toggle('pulse', !stale);
        badge.textContent = stale ? 'Stale' : 'Live';
      }
    });
  }

  function refresh(){
    fetch('/api/live/trips/', { credentials: 'same-origin' })
      .then(function(r){ return r.json(); })
      .then(function(data){ if(data && data.items) updateList(data.items); })
      .catch(function(){});
  }

  document.addEventListener('DOMContentLoaded', function(){
    if (!document.querySelector('[data-trip]')) return; // page without trip items
    refresh();
    setInterval(refresh, 30000);
  });
})();

