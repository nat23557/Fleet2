// trip_route_map.js
// Animated route playback + live polling on Trip Detail page

(function() {
  function $(id) { return document.getElementById(id); }

  function haversine(lat1, lon1, lat2, lon2) {
    var R = 6371; // km
    var dLat = (lat2 - lat1) * Math.PI / 180;
    var dLon = (lon2 - lon1) * Math.PI / 180;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
    var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }

  function bearing(lat1, lon1, lat2, lon2) {
    var φ1 = lat1 * Math.PI / 180;
    var φ2 = lat2 * Math.PI / 180;
    var Δλ = (lon2 - lon1) * Math.PI / 180;
    var y = Math.sin(Δλ) * Math.cos(φ2);
    var x = Math.cos(φ1) * Math.cos(φ2) * Math.cos(Δλ) - Math.sin(φ1) * Math.sin(φ2);
    var θ = Math.atan2(y, x);
    var brng = (θ * 180 / Math.PI + 360) % 360; // in degrees
    return brng;
  }

  function parseTimestamp(ts) {
    if (!ts && ts !== 0) return null;
    var str = String(ts).trim();
    if (!str) return null;
    if (str.indexOf('T') === -1 && str.indexOf(' ') !== -1) {
      str = str.replace(' ', 'T');
    }
    var tzPattern = /[zZ]$|[+\-]\d{2}:?\d{2}$/;
    if (!tzPattern.test(str)) {
      str = str + 'Z';
    }
    var parsed = Date.parse(str);
    if (!isFinite(parsed)) return null;
    return parsed;
  }

  function lerp(a, b, t) { return a + (b - a) * t; }

  function cleanPoints(raw) {
    // Filter invalid entries and normalize types
    var out = [];
    (raw || []).forEach(function(p, i) {
      var lat = parseFloat(p.lat);
      var lng = parseFloat(p.lng);
      if (!isFinite(lat) || !isFinite(lng)) return;
      out.push({
        lat: lat,
        lng: lng,
        loc: p.loc || '',
        timestamp: p.timestamp || null,
        _i: i
      });
    });
    // Sort by timestamp if present; preserve original order as stable tiebreaker
    out.sort(function(a, b) {
      var ta = parseTimestamp(a.timestamp);
      var tb = parseTimestamp(b.timestamp);
      if (ta != null && tb != null) {
        if (ta !== tb) return ta - tb;
      } else if (ta != null && tb == null) {
        return -1; // timestamped first
      } else if (ta == null && tb != null) {
        return 1;  // timestamped first
      }
      return a._i - b._i;
    });
    // Drop consecutive duplicates within ~1 meter
    var filtered = [];
    var lastLat = null, lastLng = null;
    for (var k = 0; k < out.length; k++) {
      var p = out[k];
      if (lastLat !== null) {
        if (Math.abs(p.lat - lastLat) < 1e-5 && Math.abs(p.lng - lastLng) < 1e-5) continue;
      }
      filtered.push({ lat: p.lat, lng: p.lng, loc: p.loc, timestamp: p.timestamp });
      lastLat = p.lat; lastLng = p.lng;
    }
    return filtered;
  }

  function buildSegments(points) {
    var segs = [];
    for (var i = 0; i < points.length - 1; i++) {
      var a = points[i], b = points[i + 1];
      var distKm = haversine(a.lat, a.lng, b.lat, b.lng);
      var dtMs = 0;
      if (a.timestamp && b.timestamp) {
        var ta = parseTimestamp(a.timestamp);
        var tb = parseTimestamp(b.timestamp);
        if (ta != null && tb != null) {
          dtMs = Math.max(0, tb - ta);
        }
      }
      // Fallback duration if timestamps missing or identical: scale by distance (1000ms per ~250m)
      if (!dtMs || dtMs === 0) {
        dtMs = Math.max(400, Math.min(8000, (distKm * 1000) / 0.25 * 1000));
      }
      segs.push({
        a: a, b: b,
        distKm: distKm,
        dtMs: dtMs
      });
    }
    return segs;
  }

  function createTruckIcon() {
    var truckUrl = (window && window.TRUCK_ICON_URL) ? window.TRUCK_ICON_URL : '/static/images/truck_icon.png';
    return L.divIcon({
      className: 'custom-car-icon',
      html: '\n        <div class="truck-icon-wrapper">\n' +
            '  <img src="' + truckUrl + '" alt="Truck" class="truck-icon-img" />\n' +
            '</div>\n',
      iconSize: [48, 48],
      iconAnchor: [24, 48],
      popupAnchor: [0, -48]
    });
  }

  function addControls(map, api) {
    var container = document.createElement('div');
    container.className = 'map-controls';
    container.style.position = 'absolute';
    container.style.top = '10px';
    container.style.right = '10px';
    container.style.zIndex = 1000;
    container.style.display = 'grid';
    container.style.gridAutoFlow = 'column';
    container.style.gap = '6px';

    function btn(label, onClick) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.style.padding = '6px 10px';
      b.style.borderRadius = '6px';
      b.style.border = '1px solid rgba(0,0,0,.15)';
      b.style.background = 'rgba(255,255,255,0.95)';
      b.style.cursor = 'pointer';
      b.addEventListener('click', onClick);
      return b;
    }

    var play = btn('Play', function(){ api.play(); });
    var pause = btn('Pause', function(){ api.pause(); });
    var fit = btn('Fit', function(){ api.fit(); });
    var live = btn('Live', function(){ api.toggleLive(); });

    var sp1 = btn('1x', function(){ api.setSpeed(1); });
    var sp2 = btn('2x', function(){ api.setSpeed(2); });
    var sp4 = btn('4x', function(){ api.setSpeed(4); });

    container.appendChild(play);
    container.appendChild(pause);
    container.appendChild(sp1);
    container.appendChild(sp2);
    container.appendChild(sp4);
    container.appendChild(fit);
    container.appendChild(live);

    var mapEl = $('route-map');
    if (mapEl && mapEl.parentNode) mapEl.parentNode.appendChild(container);
  }

  document.addEventListener('DOMContentLoaded', function() {
    var mapEl = $('route-map');
    if (!mapEl) return;

    var tripId = mapEl.getAttribute('data-trip-id') || (window.TRIP_ID != null ? String(window.TRIP_ID) : null);
    var initial = cleanPoints(window.routePoints || []);

    // Map init
    var map = L.map('route-map', { zoomControl: true });
    // base layer(s)
    var osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    var imagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { attribution: 'Imagery &copy; Esri' });
    var labels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', { attribution: 'Labels &copy; Esri' });
    L.control.layers({ OSM: osm, 'Esri Imagery': imagery }, { Labels: labels }, { collapsed: true, position: 'topright' }).addTo(map);
    L.control.scale({ position: 'bottomleft', metric: true, imperial: false }).addTo(map);

    var routeLatLngs = initial.map(function(p){ return [p.lat, p.lng]; });
    var routeLine = L.polyline(routeLatLngs, { color: '#1d4ed8', weight: 4, opacity: 0.9, className: 'route-animated' }).addTo(map);
    var startMarker = null, endMarker = null;

    function refreshEndpoints() {
      if (startMarker) { startMarker.remove(); startMarker = null; }
      if (endMarker) { endMarker.remove(); endMarker = null; }
      if (!routeLatLngs.length) return;
      var s = routeLatLngs[0];
      var e = routeLatLngs[routeLatLngs.length - 1];
      startMarker = L.circleMarker(s, { radius: 6, color: '#16a34a', fillColor: '#22c55e', fillOpacity: 0.9 }).addTo(map).bindPopup('Start');
      endMarker = L.circleMarker(e, { radius: 6, color: '#dc2626', fillColor: '#ef4444', fillOpacity: 0.9 }).addTo(map).bindPopup('Current');
    }
    refreshEndpoints();

    function fitToRoute() {
      if (routeLatLngs.length >= 2) {
        map.fitBounds(routeLatLngs, { padding: [20, 20] });
      } else if (routeLatLngs.length === 1) {
        map.setView(routeLatLngs[0], 14);
      } else {
        map.setView([9.03, 38.74], 6); // default to Addis area if nothing yet
      }
    }
    fitToRoute();

    // Moving truck marker
    var truckIcon = createTruckIcon();
    var truckMarker = null;
    if (routeLatLngs.length) {
      truckMarker = L.marker(routeLatLngs[routeLatLngs.length - 1], { icon: truckIcon, riseOnHover: true }).addTo(map);
    }

    // Animation engine
    var segments = buildSegments(initial);
    var rafId = null;
    var playing = false;
    var liveMode = true;
    var speedFactor = 1; // 1x
    var curSegIdx = 0;
    var curSegStartTime = 0;

    function setMarkerBearing(angle) {
      if (!truckMarker) return;
      var el = truckMarker.getElement();
      if (!el) return;
      var img = el.querySelector('.truck-icon-img');
      if (!img) return;
      img.style.transform = 'rotate(' + angle + 'deg)';
      img.style.transition = 'transform 0.08s linear';
    }

    function startFrom(idx) {
      if (segments.length === 0 || idx >= segments.length) return;
      curSegIdx = Math.max(0, idx);
      curSegStartTime = performance.now();
    }

    function step(now) {
      if (!playing) return;
      if (segments.length === 0) {
        cancelAnimationFrame(rafId); rafId = null; playing = false; return;
      }
      var seg = segments[curSegIdx];
      if (!seg) { playing = false; return; }
      var elapsed = now - curSegStartTime;
      var duration = seg.dtMs / speedFactor;
      var t = Math.max(0, Math.min(1, elapsed / duration));
      var lat = lerp(seg.a.lat, seg.b.lat, t);
      var lng = lerp(seg.a.lng, seg.b.lng, t);

      if (!truckMarker) truckMarker = L.marker([lat, lng], { icon: truckIcon, riseOnHover: true }).addTo(map);
      truckMarker.setLatLng([lat, lng]);
      // Auto-pan if marker is out of view
      try {
        if (!map.getBounds().pad(-0.2).contains([lat, lng])) {
          map.panTo([lat, lng], { animate: true });
        }
      } catch (e) {}
      // update bearing smoothly
      var brg = bearing(seg.a.lat, seg.a.lng, seg.b.lat, seg.b.lng);
      setMarkerBearing(brg);

      if (t >= 1) {
        // move to next segment
        curSegIdx += 1;
        curSegStartTime = now;
        if (curSegIdx >= segments.length) {
          // End reached
          playing = false; rafId = null;
          return;
        }
      }
      rafId = requestAnimationFrame(step);
    }

    function play() {
      if (playing) return;
      playing = true;
      if (!rafId) rafId = requestAnimationFrame(function(ts){ curSegStartTime = ts; step(ts); });
    }
    function pause() {
      playing = false;
      if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    }
    function setSpeed(f) {
      speedFactor = Math.max(0.25, Math.min(16, f || 1));
    }
    function toggleLive() { liveMode = !liveMode; }

    // Live route polling; extend line + segments when new points are available
    function fetchRouteAndExtend() {
      if (!tripId) return;
      fetch('/api/trip/' + tripId + '/route/', { credentials: 'same-origin' })
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(data){
          if (!data || !Array.isArray(data.route)) return;
          var latest = cleanPoints(data.route);
          if (latest.length < routeLatLngs.length) {
            // Replace with authoritative server route
            routeLatLngs = latest.map(function(p){ return [p.lat, p.lng]; });
          } else if (latest.length === routeLatLngs.length) {
            var nl = latest.length;
            if (nl) {
              var a = latest[nl-1];
              var b = routeLatLngs[nl-1] || [];
              if (!b.length || Math.abs(a.lat - b[0]) > 1e-6 || Math.abs(a.lng - b[1]) > 1e-6) {
                routeLatLngs[nl-1] = [a.lat, a.lng];
              } else {
                return; // no visible change
              }
            } else { return; }
          } else {
            var addPts = latest.slice(routeLatLngs.length);
            addPts.forEach(function(p){ routeLatLngs.push([p.lat, p.lng]); });
          }
          routeLine.setLatLngs(routeLatLngs);
          refreshEndpoints();
          if (truckMarker) truckMarker.setLatLng(routeLatLngs[routeLatLngs.length - 1]);
          else truckMarker = L.marker(routeLatLngs[routeLatLngs.length - 1], { icon: truckIcon, riseOnHover: true }).addTo(map);

          // Extend segments so playback can continue into new points
          var moreSegs = buildSegments(latest);
          segments = moreSegs;
          // If in live mode and playback is off due to end reached, auto continue from last-1 segment
          if (liveMode && !playing) {
            startFrom(Math.max(0, segments.length - 2));
            play();
          }
        })
        .catch(function(){ /* ignore */ });
    }

    var pollTimer = setInterval(function(){ if (liveMode) fetchRouteAndExtend(); }, 15000);

    // public controls API
    addControls(map, {
      play: play,
      pause: pause,
      setSpeed: setSpeed,
      toggleLive: toggleLive,
      fit: fitToRoute
    });

    // If we have at least two points, prep animation starting from segment 0 but leave paused by default
    if (segments.length > 0) startFrom(0);

    // Initial capture for PDF embedding (if present)
    setTimeout(function() {
      try {
        if (typeof leafletImage !== 'function' || !map) return;
        leafletImage(map, function(err, canvas){
          if (err) return;
          var input = document.getElementById('mapDataUrl');
          if (input) input.value = canvas.toDataURL('image/png');
        });
      } catch (e) { /* no-op */ }
    }, 2500);
  });
})();
