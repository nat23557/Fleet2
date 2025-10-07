// fleet_map.js - Live fleet map with geofence overlays
(function(){
  var map, markers = {}, fencesLayer = L.layerGroup();
  var rootEl;
  var baseOSM, baseEsriSat, baseEsriStreets, baseCartoLight, baseCartoDark, labelsOverlay;

  function init(){
    rootEl = document.getElementById('fleet-map');
    if(!rootEl) return;
    map = L.map('fleet-map');

    // Base layers
    // Base layers
    labelsOverlay = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {maxZoom: 19, attribution: 'Labels © Esri'});
    baseEsriSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {maxZoom: 19, attribution: 'Tiles © Esri, DigitalGlobe'});
    baseEsriStreets = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {maxZoom: 19, attribution: 'Esri Streets'});
    baseOSM = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© OpenStreetMap'});
    baseCartoLight = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {maxZoom: 19, attribution: '© Carto'});
    baseCartoDark = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {maxZoom: 19, attribution: '© Carto'});

    baseEsriSat.addTo(map); // default base
    labelsOverlay.addTo(map); // label overlay default on
    var baseMaps = { 'OSM': baseOSM, 'Esri Imagery': baseEsriSat, 'Esri Streets': baseEsriStreets, 'Light': baseCartoLight, 'Dark': baseCartoDark };
    fencesLayer.addTo(map);
    var overlays = { 'Labels': labelsOverlay, 'Geofences': fencesLayer };
    // Layers control (collapsed) still available but we will use an external toolbar
    L.control.layers(baseMaps, overlays, { position: 'topright', collapsed: true }).addTo(map);
    bindExternalToolbar();
    map.setView([8.9806, 38.7578], 6); // Ethiopia-ish default
    refresh();
    setInterval(refresh, 30000);
  }

  function popupHtml(item){
    var speed = (item.speed!=null) ? Math.round(item.speed)+' km/h' : '-';
    var eng = item.engine || '-';
    var loc = item.loc || '-';
    var updated = item.updated || item.dt_tracker || item.timestamp || '';
    var lat = (item.lat!=null) ? Number(item.lat).toFixed(6) : '-';
    var lng = (item.lng!=null) ? Number(item.lng).toFixed(6) : '-';
    var fuel1 = (item.fuel1!=null) ? item.fuel1 : '-';
    var fuel2 = (item.fuel2!=null) ? item.fuel2 : '-';
    var primaryHref = item.trip_id ? ('/trip/'+item.trip_id+'/') : ('/trucks/'+item.truck_id+'/');
    var primaryLabel = item.trip_id ? 'Open Trip' : 'Open Truck';
    var trackBtn = item.trip_id ? '<button class="cta-button" style="padding:4px 8px" data-track="'+item.trip_id+'">Track</button>' : '';
    var state = computeState(item);
    var chip = '<span class="fp-chip '+state.class+'">'+state.label+'</span>';
    var ageTxt = computeAgeText(item);
    return '<div class="fleet-popup">'
      +   '<div class="fp-head">'
      +     '<div class="fp-title">'+item.truck_plate+'</div>'
      +      chip
      +   '</div>'
      +   '<div class="fp-stats">'
      +     '<div class="stat"><span class="s-ico">🚗</span><b>'+ (speed==='-'?'-':speed.replace(' km/h','')) +'</b><small>km/h</small></div>'
      +     '<div class="stat"><span class="s-ico">⚙️</span><b>'+eng+'</b><small>engine</small></div>'
      +     '<div class="stat"><span class="s-ico">⏱</span><b>'+ageTxt+'</b><small>updated</small></div>'
      +   '</div>'
      +   '<div class="fp-grid">'
      +     '<div class="k">Driver</div><div class="v">'+(item.driver||'-')+'</div>'
      +     '<div class="k">Location</div><div class="v">'+(loc||'-')+'</div>'
      +     '<div class="k">Coords</div><div class="v">'+lat+', '+lng+'</div>'
      +     '<div class="k">Fuel</div><div class="v">1: '+fuel1+' &nbsp; 2: '+fuel2+'</div>'
      +   '</div>'
      +   '<div class="fp-actions">'
      +     '<a class="cta-button" style="padding:4px 10px" href="'+primaryHref+'">'+primaryLabel+'</a>'
      +      trackBtn
      +     '<button class="cta-button" style="padding:4px 10px" data-fences="'+item.truck_id+'">Fences</button>'
      +   '</div>'
      + '</div>';
  }

  function parseNum(v){
    var n = Number(v);
    if (!isFinite(n)) {
      try { n = Number(String(v).replace(',', '.')); } catch(e){ n = NaN; }
    }
    return n;
  }

  function truncatedPlate(plate){
    if(!plate) return '';
    if(plate.length <= 10) return plate;
    return plate.slice(-6);
  }

  function computeState(item){
    var age = item.age_seconds;
    if((age==null || isNaN(age)) && item.updated){
      try { age = Math.abs((Date.now() - Date.parse(item.updated)) / 1000); } catch(e){ age = null; }
    }
    var moving = (parseNum(item.speed) > 2);
    var stale = (age!=null && age > 20*60);
    if(moving) return {class:'chip-green', label:'MOVING'};
    if(stale) return {class:'chip-gray', label:'OFFLINE'};
    if((item.engine||'').toString().toLowerCase()==='on') return {class:'chip-amber', label:'IDLE'};
    return {class:'chip-amber', label:'IDLE'};
  }

  function markerIconHtml(item){
    var st = computeState(item);
    var plate = truncatedPlate(item.truck_plate);
    return '<div class="pin '+st.class+'">'
      + '<span class="pin-dot"></span>'
      + '<span class="pin-label">'+plate+'</span>'
      + '</div>';
  }

  function computeAgeText(item){
    var sec = item.age_seconds;
    if((sec==null || isNaN(sec)) && (item.updated || item.timestamp)){
      try{ sec = Math.abs((Date.now() - Date.parse(item.updated || item.timestamp)) / 1000); }catch(e){ sec = null; }
    }
    if(sec==null) return '-';
    if(sec < 90) return Math.round(sec)+'s';
    var m = Math.round(sec/60); if(m < 90) return m+'m';
    var h = Math.round(m/60); return h+'h';
  }

  function ensureMarker(item){
    var key = String(item.trip_id || item.truck_id || item.truck_plate || Math.random());
    var lat = parseNum(item.lat), lng = parseNum(item.lng);
    if(!isFinite(lat) || !isFinite(lng)) return; // skip invalid coordinates
    var ll = [lat, lng];
    var icon = L.divIcon({
      className:'pin-wrapper',
      html: markerIconHtml(item),
      iconSize:[64,28],
      iconAnchor:[32,28],
      popupAnchor:[0,-28]
    });
    if(!markers[key]){
      markers[key] = L.marker(ll, {icon: icon});
      markers[key].addTo(map);
    } else {
      markers[key].setLatLng(ll);
      markers[key].setIcon(icon);
    }
    markers[key].bindPopup(popupHtml(item));
  }

  function refresh(){
    var mode = (rootEl && rootEl.dataset && rootEl.dataset.mode) || 'all';
    var url = (mode === 'active') ? '/api/live/trips/' : '/trucks/status/';
    fetch(url, {credentials:'same-origin'})
      .then(function(r){return r.json()})
      .then(function(data){
        var items = (mode === 'active') ? (data && data.items) : data;
        if(!items) return;
        // Normalize truck_status shape
        if (mode !== 'active') {
          items = items.map(function(t){ return {
            trip_id: null,
            truck_id: t.id,
            truck_plate: t.plate_number,
            driver: t.driver_name || null,
            lat: parseNum(t.latitude),
            lng: parseNum(t.longitude),
            speed: parseNum(t.speed),
            engine: t.engine,
            status: t.status,
            loc: t.location || '',
            fuel1: t.fuel1, fuel2: t.fuel2,
            updated: t.timestamp,
            age_seconds: null
          }; });
        }
        // Debug: log counts and first item to help diagnose empties
        try { console.debug('Fleet items:', items.length, items[0]); } catch(e){}
        updateMarkers(items);
      })
      .catch(function(){});
  }

  function bindExternalToolbar(){
    // find toolbar near the map (inside the same section)
    var container = rootEl && rootEl.closest('.section');
    if(!container) return;
    var toolbar = container.querySelector('.map-toolbar');
    if(!toolbar) return;
    var radios = toolbar.querySelectorAll('input[name="bmap"]');
    radios.forEach(function(r){ r.addEventListener('change', onBaseChange); });
    var cb = toolbar.querySelector('input[name="labels"]');
    if(cb) cb.addEventListener('change', onLabelsToggle);
    // default selections if nothing chosen
    var anyChecked = Array.prototype.some.call(radios, function(r){ return r.checked; });
    if(!anyChecked){
      var esri = toolbar.querySelector('input[value="esri"]');
      if(esri){ esri.checked = true; onBaseChange({target: esri}); }
    }
    if(cb && !cb.checked){ labelsOverlay && map.removeLayer(labelsOverlay); }
  }

  function onBaseChange(e){
    var v = e.target.value;
    // remove all base layers
    [baseOSM, baseEsriSat, baseEsriStreets, baseCartoLight, baseCartoDark].forEach(function(l){ if(l && map.hasLayer(l)) map.removeLayer(l); });
    if(v==='osm') baseOSM.addTo(map);
    else if(v==='esri') baseEsriSat.addTo(map);
    else if(v==='streets') baseEsriStreets.addTo(map);
    else if(v==='dark') baseCartoDark.addTo(map);
    else baseCartoLight.addTo(map);
  }

  function onLabelsToggle(e){
    if(e.target.checked) labelsOverlay.addTo(map); else map.removeLayer(labelsOverlay);
  }

  function updateMarkers(items){
    var latLngs = [];
    var seen = {};
    items.forEach(function(it){
      if(it.lat!=null && it.lng!=null){ latLngs.push([it.lat, it.lng]); }
      ensureMarker(it);
      seen[String(it.trip_id || it.truck_id || it.truck_plate)] = true;
    });
    // remove markers that disappeared
    Object.keys(markers).forEach(function(k){ if(!seen[k]) { map.removeLayer(markers[k]); delete markers[k]; } });
    if(latLngs.length){ map.fitBounds(latLngs, {padding:[30,30]}); }
    // hookup popup buttons after open
    map.on('popupopen', function(e){
      var c = e.popup.getElement(); if(!c) return;
      var trackBtn = c.querySelector('[data-track]');
      var fenceBtn = c.querySelector('[data-fences]');
      if(trackBtn){ trackBtn.addEventListener('click', function(){
        var id = this.getAttribute('data-track');
        if(window.openTrackModal) window.openTrackModal(id);
      }); }
      if(fenceBtn){ fenceBtn.addEventListener('click', function(){
        var tid = this.getAttribute('data-fences');
        fetch('/geofence/'+tid+'/list/', {credentials:'same-origin'})
          .then(function(r){return r.json()}).then(function(f){ drawFences(f); });
      }); }
    });
  }

  function drawFences(list){
    fencesLayer.clearLayers();
    (list||[]).forEach(function(f){
      try{
        if(f.type==='circle'){
          L.circle([f.center[0], f.center[1]], {radius:f.radius, color:'#22c55e'}).addTo(fencesLayer);
        } else if(f.type==='rect'){
          L.rectangle([[f.sw[0], f.sw[1]],[f.ne[0], f.ne[1]]], {color:'#f59e0b'}).addTo(fencesLayer);
        } else if(f.type==='polygon'){
          L.polygon(f.points.map(function(p){return [p[0], p[1]];}), {color:'#3b82f6'}).addTo(fencesLayer);
        }
      }catch(e){}
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();
