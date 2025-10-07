// trip_track_modal.js - per-trip mini track modal with route + fences
(function(){
  var modal, content, closeBtn, map, routeLayer, fencesLayer;

  function ensureModal(){
    modal = document.getElementById('trackModal');
    if(modal) return true;
    return false;
  }

  function open(tripId){
    if(!ensureModal()) return;
    modal.style.display = 'block';
    content = document.getElementById('trackMapBox');
    if(!map){
      map = L.map('trackMapBox');
      // Satellite base + labels
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {maxZoom:19, attribution:'Tiles © Esri'}).addTo(map);
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {maxZoom:19, attribution:'Labels © Esri'}).addTo(map);
      routeLayer = L.layerGroup().addTo(map);
      fencesLayer = L.layerGroup().addTo(map);
    }
    fetch('/api/trip/'+tripId+'/route/', {credentials:'same-origin'})
      .then(function(r){return r.json()})
      .then(render)
      .catch(function(){});
  }

  function render(data){
    routeLayer.clearLayers();
    fencesLayer.clearLayers();
    var latLngs = [];
    (data.route||[]).forEach(function(p){
      if(p.lat!=null && p.lng!=null){ latLngs.push([p.lat, p.lng]); }
    });
    if(latLngs.length){
      L.polyline(latLngs, {color:'#3b82f6'}).addTo(routeLayer);
      var start = latLngs[0], end = latLngs[latLngs.length-1];
      L.marker(start).addTo(routeLayer).bindTooltip('Start');
      L.marker(end).addTo(routeLayer).bindTooltip('Last');
      map.fitBounds(L.latLngBounds(latLngs), {padding:[20,20]});
    }
    (data.fences||[]).forEach(function(f){
      try{
        if(f.type==='circle') L.circle([f.center[0], f.center[1]], {radius:f.radius, color:'#22c55e'}).addTo(fencesLayer);
        else if(f.type==='rect') L.rectangle([[f.sw[0], f.sw[1]],[f.ne[0], f.ne[1]]], {color:'#f59e0b'}).addTo(fencesLayer);
        else if(f.type==='polygon') L.polygon(f.points.map(function(p){return [p[0], p[1]];}), {color:'#ef4444'}).addTo(fencesLayer);
      }catch(e){}
    });
  }

  function close(){ if(modal) modal.style.display = 'none'; }

  document.addEventListener('DOMContentLoaded', function(){
    if(!ensureModal()) return;
    closeBtn = document.getElementById('trackClose');
    if(closeBtn) closeBtn.addEventListener('click', close);
    window.openTrackModal = open; // expose for fleet_map popup button
    // add listeners to inline track buttons on cards
    document.querySelectorAll('[data-track-open]').forEach(function(btn){
      btn.addEventListener('click', function(e){ e.preventDefault(); e.stopPropagation(); open(this.getAttribute('data-track-open')); });
    });
  });
})();
