document.addEventListener("DOMContentLoaded", function() {
    // Get the truck id from the data attribute on the real-time-status container
    var statusContainer = document.getElementById("real-time-status");
    var truckId = statusContainer.dataset.truckId;
    
    // Initialize the Leaflet map in the 'status-map' div
    var map = L.map('status-map', { zoomControl: true }).setView([9.03, 38.74], 12);
    // Ensure proper sizing after CSS/layout settles
    map.whenReady(function(){ setTimeout(function(){ map.invalidateSize(); }, 100); });

    // Base layers
    var osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
    });
    var imagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics'
    });
    var esriStreets = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Streets &copy; Esri'
    });
    var cartoDark = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap &copy; CARTO'
    });
    osm.addTo(map);
    // Optional label overlay for imagery
    var reference = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', { attribution: 'Labels &copy; Esri' });

    var baseLayers = {
        'OSM': osm,
        'Esri Imagery': imagery,
        'Esri Streets': esriStreets,
        'Dark': cartoDark
    };
    var overlays = { 'Labels': reference };
    L.control.layers(baseLayers, overlays, { position: 'topright', collapsed: true }).addTo(map);
    L.control.scale({ position: 'bottomleft', metric: true, imperial: false }).addTo(map);
    
    // Custom icon for the truck marker with badge and bottom anchor
    var truckIconUrl = (window && window.TRUCK_ICON_URL) ? window.TRUCK_ICON_URL : '/static/images/truck_icon.png';
    function makeTruckIcon(statusText) {
        var status = (statusText || '').toLowerCase();
        var chipClass = 'truck-status-chip';
        if (status.includes('idle') || status.includes('available')) chipClass += ' status-available';
        else if (status.includes('maint')) chipClass += ' status-maintenance';
        else if (status.includes('in') || status.includes('move')) chipClass += ' status-in_use';
        return L.divIcon({
            className: 'custom-truck-icon',
            html: `<div class="truck-icon-wrapper">
                      <img class="truck-icon-img" src="${truckIconUrl}" alt="Truck" />
                      <span class="${chipClass}">${statusText || ''}</span>
                   </div>`,
            iconSize: [48, 48],
            iconAnchor: [24, 48],   // bottom center = precise anchor
            popupAnchor: [0, -52]
        });
    }

    // Define the URL to fetch the status for this truck using its ID
    var statusUrl = `/trucks/${truckId}/status/`;

    // Keep a short on-session trail
    var trailPoints = []; // {lat, lng, speed, ts}
    var trailLayer = L.layerGroup().addTo(map);
    var segmentPolys = [];
    var MAX_TRAIL_POINTS = 720; // ~1 hour at 5s polling
    var MAX_SEGMENTS = 700;
    var totalDistanceKm = 0;
    var maxSpeed = 0;
    var followTruck = true; // keep map centered by default
    var playback = { active: false, idx: 0, timer: null, speed: 1, marker: null };
    var geofences = loadGeofences(); // [{type:'circle'|'rect'|'polygon', ...}]
    var geofenceLayer = L.layerGroup().addTo(map);
    renderGeofences();
    var lastTruckStatus = null; // latest truck status for notifications

    // Function to update the truck marker's location
    function updateTruckLocation() {
        fetch(statusUrl)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    console.error("Error: " + data.error);
                } else {
                    // Parse latitude and longitude
                    var lat = parseFloat(data.latitude);
                    var lng = parseFloat(data.longitude);
                    
                    if (followTruck) {
                        // Respect current zoom; only pan
                        map.panTo([lat, lng], { animate: true });
                    }
                    // Keep latest status for notifications
                    lastTruckStatus = data || lastTruckStatus;
                    
                    // Create or update marker with latest status icon (keep marker persistent)
                    var icon = makeTruckIcon(data.status);
                    if (!window.truckMarker) {
                        window.truckMarker = L.marker([lat, lng], { icon: icon, riseOnHover: true }).addTo(map);
                        // Bind click once for popup refresh
                        window.truckMarker.on("click", function() {
                            fetch(statusUrl)
                                .then(response => response.json())
                                .then(updatedData => {
                                    updateSidePanel(updatedData);
                                    var popupContent = sidePanelHTML(updatedData);
                                    window.truckMarker.bindPopup(popupContent).openPopup();
                                })
                                .catch(error => console.error("Error updating truck status:", error));
                        });
                    } else {
                        window.truckMarker.setIcon(icon);
                        window.truckMarker.setLatLng([lat, lng]);
                        if (!map.hasLayer(window.truckMarker)) window.truckMarker.addTo(map);
                    }

                    // Apply rotation if angle is available
                    try {
                        var angle = parseFloat(data.angle || data.heading || 0) || 0;
                        var markerEl = window.truckMarker.getElement();
                        var img = markerEl ? markerEl.querySelector('.truck-icon-img') : null;
                        if (img) { img.style.transform = `rotate(${angle}deg)`; }
                        // Moving pulse state
                        var moving = (parseFloat(data.speed || 0) || 0) > 2;
                        if (markerEl) markerEl.classList.toggle('truck-moving', !!moving);
                    } catch (e) { /* ignore */ }

                    // Maintain rich trail with speed + distance
                    var now = Date.now();
                    var last = trailPoints[trailPoints.length - 1];
                    var pt = { lat, lng, speed: parseFloat(data.speed || 0) || 0, ts: now };
                    trailPoints.push(pt);
                    if (trailPoints.length > MAX_TRAIL_POINTS) trailPoints.shift();
                    if (last) {
                        var dist = haversine(last.lat, last.lng, lat, lng);
                        if (isFinite(dist)) totalDistanceKm += dist;
                        var seg = L.polyline([[last.lat, last.lng], [lat, lng]], {
                            color: speedColor(pt.speed), weight: 4, opacity: 0.85
                        }).addTo(trailLayer);
                        segmentPolys.push(seg);
                        while (segmentPolys.length > MAX_SEGMENTS) {
                            var rm = segmentPolys.shift();
                            trailLayer.removeLayer(rm);
                        }
                    }
                    if (pt.speed > maxSpeed) maxSpeed = pt.speed;
                    // Update side panel continuously without clicking
                    updateSidePanel(data);
                    checkGeofences([lat, lng]);
                }
            })
            .catch(error => {
                console.error("Error fetching truck status:", error);
            });
    }

    // Initial update on page load
    updateTruckLocation();
    // Poll every 30 seconds for new updates
    // Poll every 5 seconds for a smooth trail; adjust as needed
    setInterval(updateTruckLocation, 5000);

    // UI Controls: follow, full-screen, fit trail, recenter, locate, playback
    addControls();

    function sidePanelHTML(d) {
        return `
            <div class="popup-container">
                <h3 class="popup-title">Truck: ${d.plate_number || ''}</h3>
                <p><strong>Location:</strong> ${d.location || ''} (${d.latitude || ''}, ${d.longitude || ''})</p>
                <p><strong>Engine:</strong> ${d.engine || ''}</p>
                <p><strong>Speed:</strong> ${d.speed || 0} km/h</p>
                <p><strong>Fuel Sensor 1:</strong> ${d.fuel1 || ''}</p>
                <p><strong>Fuel Sensor 2:</strong> ${d.fuel2 || ''}</p>
                <p><strong>Heading:</strong> ${d.angle || d.heading || 0}&deg;</p>
                <p><strong>Last Updated:</strong> ${d.timestamp || ''}</p>
                <p><strong>Status:</strong> <span class="status-indicator">${d.status || ''}</span></p>
                <hr/>
                <p><strong>Session Distance:</strong> ${totalDistanceKm.toFixed(2)} km</p>
                <p><strong>Max Speed:</strong> ${maxSpeed.toFixed(1)} km/h</p>
                <div id="geofence-events"></div>
            </div>`;
    }

    function updateSidePanel(d) {
        var panel = document.getElementById('status-side-content');
        if (!panel) return;
        panel.innerHTML = sidePanelHTML(d);
    }

    // Helpers
    function speedColor(s){
        if (s <= 5) return '#2e7d32'; // green
        if (s <= 40) return '#f9a825'; // amber
        if (s <= 80) return '#ef6c00'; // orange
        return '#c62828'; // red
    }
    function haversine(lat1, lon1, lat2, lon2){
        var R = 6371; // km
        var dLat = (lat2-lat1) * Math.PI/180;
        var dLon = (lon2-lon1) * Math.PI/180;
        var a = Math.sin(dLat/2)*Math.sin(dLat/2) + Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)*Math.sin(dLon/2);
        var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
        return R * c;
    }

    function fitToTrail(){
        if (!trailPoints.length) return;
        var latlngs = trailPoints.map(p => [p.lat, p.lng]);
        map.fitBounds(latlngs, { padding: [20,20] });
    }

    function recenterOnTruck(){
        if (!window.truckMarker) return;
        map.panTo(window.truckMarker.getLatLng(), { animate: true });
    }

    function addControls(){
        var container = document.createElement('div');
        container.className = 'map-controls collapsed';
        var header = document.createElement('button');
        header.type = 'button';
        header.className = 'ctrl-toggle';
        header.innerHTML = 'Controls ▾';
        header.addEventListener('click', function(){ container.classList.toggle('collapsed'); setTimeout(function(){ map.invalidateSize(); }, 50); });
        container.appendChild(header);
        var list = document.createElement('div');
        list.className = 'ctrl-list';
        // Search bar (geocode cities/countries)
        var searchWrap = document.createElement('div');
        searchWrap.style.display = 'grid';
        searchWrap.style.gridTemplateColumns = '1fr auto';
        searchWrap.style.gap = '6px';
        var searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.placeholder = 'Search city/country…';
        searchInput.className = 'ctrl-input';
        var searchBtn = mkBtn('Go', function(){ geocode(searchInput.value); });
        var resList = document.createElement('div');
        resList.style.display = 'none';
        resList.style.maxHeight = '180px';
        resList.style.overflow = 'auto';
        resList.style.background = 'rgba(255,255,255,0.95)';
        resList.style.border = '1px solid rgba(0,0,0,.15)';
        resList.style.borderRadius = '8px';
        resList.style.padding = '4px';
        resList.style.gridColumn = '1 / span 2';
        searchWrap.appendChild(searchInput);
        searchWrap.appendChild(searchBtn);
        searchWrap.appendChild(resList);
        list.appendChild(searchWrap);
        // Follow
        var followBtn = mkBtn('Follow', function(){
            followTruck = !followTruck;
            followBtn.setAttribute('aria-pressed', followTruck ? 'true' : 'false');
            if (followTruck) recenterOnTruck();
        }, true);
        followBtn.id = 'mapFollowBtn';
        followBtn.title = 'Toggle follow truck';
        // Fullscreen
        var fsBtn = mkBtn('Fullscreen', function(){
            var block = document.getElementById('real-time-status');
            block.classList.toggle('fs');
            setTimeout(function(){ map.invalidateSize(); if (followTruck) recenterOnTruck(); }, 250);
        });
        // Fit trail
        var fitBtn = mkBtn('Fit Trail', fitToTrail);
        // Recenter
        var centerBtn = mkBtn('Center', recenterOnTruck);
        // Locate me
        var locateBtn = mkBtn('Me', function(){ map.locate({ setView: true, maxZoom: 15 }); });
        // Playback controls
        var playBtn = mkBtn('Play', function(){
            if (playback.active) { stopPlayback(); playBtn.textContent = 'Play'; return; }
            startPlayback(); playBtn.textContent = 'Stop';
        });
        var spdBtn = mkBtn('1x', function(){
            playback.speed = playback.speed === 1 ? 2 : playback.speed === 2 ? 4 : 1;
            spdBtn.textContent = playback.speed + 'x';
        });
        // Geofence add (circle)
        var fenceBtn = mkBtn('Fence C', function(){
            startAddGeofence();
        });
        // Polygon sketch controls
        var fencePolyBtn = mkBtn('Fence Poly', function(){ togglePolySketch(); });
        var finishPolyBtn = mkBtn('Finish', function(){ finishPolySketch(); });
        var undoPolyBtn = mkBtn('Undo', function(){ undoPolyVertex(); });
        var clearFenceBtn = mkBtn('ClearF', function(){ clearGeofences(); });

        [followBtn, fsBtn, fitBtn, centerBtn, locateBtn, playBtn, spdBtn, fenceBtn, fencePolyBtn, finishPolyBtn, undoPolyBtn, clearFenceBtn].forEach(b => list.appendChild(b));
        container.appendChild(list);
        document.getElementById('real-time-status').appendChild(container);

        // Nominatim geocoding search
        async function geocode(q){
            if (!q || !q.trim()) return;
            try {
                const url = 'https://nominatim.openstreetmap.org/search?format=json&limit=5&q=' + encodeURIComponent(q.trim());
                const results = await fetch(url, { headers: { 'Accept-Language': 'en' } }).then(r => r.json());
                resList.innerHTML = '';
                if (!results.length){ resList.style.display = 'none'; return; }
                results.forEach(r => {
                    const item = document.createElement('div');
                    item.textContent = r.display_name;
                    item.style.padding = '6px 8px';
                    item.style.cursor = 'pointer';
                    item.addEventListener('click', function(){
                        resList.style.display = 'none';
                        const lat = parseFloat(r.lat), lon = parseFloat(r.lon);
                        const bbox = (r.boundingbox || []).map(parseFloat);
                        map.setView([lat, lon], 12);
                        if (bbox.length === 4){
                            const sw = [bbox[0], bbox[2]]; // south, west
                            const ne = [bbox[1], bbox[3]]; // north, east
                            addRectFence(sw, ne, r.display_name.split(',')[0]);
                            try { map.fitBounds([sw, ne], { padding: [20,20] }); } catch(e){}
                        } else {
                            geofences.push({ type: 'circle', center: [lat, lon], radius: 1000, inside: false, name: r.display_name.split(',')[0] });
                            saveGeofences(); renderGeofences();
                        }
                    });
                    item.addEventListener('mouseenter', function(){ item.style.background = '#eef6f2'; });
                    item.addEventListener('mouseleave', function(){ item.style.background = 'transparent'; });
                    resList.appendChild(item);
                });
                resList.style.display = 'block';
            } catch (e) { console.warn('Geocoding failed', e); }
        }
    }

    function mkBtn(label, onClick, pressed){
        var b = document.createElement('button');
        b.className = 'ctrl-btn';
        b.type = 'button';
        b.textContent = label;
        if (pressed) b.setAttribute('aria-pressed','true');
        b.addEventListener('click', onClick);
        return b;
    }

    // Playback implementation over recorded trail
    function startPlayback(){
        if (playback.active || trailPoints.length < 2) return;
        playback.active = true;
        playback.idx = 1;
        if (playback.marker) { map.removeLayer(playback.marker); playback.marker = null; }
        var start = trailPoints[0];
        playback.marker = L.circleMarker([start.lat, start.lng], { radius: 6, color: '#2962ff', weight: 2, fillColor: '#82b1ff', fillOpacity: 0.9 }).addTo(map);
        stepPlayback();
    }
    function stepPlayback(){
        if (!playback.active) return;
        if (playback.idx >= trailPoints.length) { stopPlayback(); return; }
        var p = trailPoints[playback.idx++];
        playback.marker.setLatLng([p.lat, p.lng]);
        if (followTruck) map.panTo([p.lat, p.lng], { animate: true });
        playback.timer = setTimeout(stepPlayback, 500 / playback.speed);
    }
    function stopPlayback(){
        playback.active = false;
        if (playback.timer) clearTimeout(playback.timer);
        playback.timer = null;
    }

    // Geofence management (circles + rectangles + polygons)
    function loadGeofences(){
        try { return JSON.parse(localStorage.getItem('tfam-geofences') || '[]'); } catch(e){ return []; }
    }
    function saveGeofences(){
        localStorage.setItem('tfam-geofences', JSON.stringify(geofences));
    }
    // Sync from server so fences appear across devices
    (function syncFromServer(){
        try {
            var tid = (statusContainer && statusContainer.dataset && statusContainer.dataset.truckId) ? parseInt(statusContainer.dataset.truckId) : null;
            if (!tid) return;
            fetch('/geofence/' + tid + '/list/', { credentials: 'same-origin' })
              .then(r => r.json())
              .then(list => {
                  geofences = Array.isArray(list) ? list : [];
                  saveGeofences();
                  renderGeofences();
              }).catch(function(){});
        } catch(e){}
    })();
    function renderGeofences(){
        geofenceLayer.clearLayers();
        geofences.forEach(g => {
            if (g.type === 'circle') {
                L.circle(g.center, { radius: g.radius, color: '#00acc1', fillColor: '#00acc1', fillOpacity: 0.08 }).addTo(geofenceLayer);
            } else if (g.type === 'rect' && g.sw && g.ne) {
                L.rectangle([g.sw, g.ne], { color: '#00acc1', weight: 2, fillOpacity: 0.06 }).addTo(geofenceLayer);
            } else if (g.type === 'polygon' && Array.isArray(g.points)) {
                L.polygon(g.points, { color: '#00acc1', weight: 2, fillOpacity: 0.06 }).addTo(geofenceLayer);
            }
        });
    }
    function clearGeofences(){
        if (geofences.length) notify('disabled', { count: geofences.length });
        try {
            var tid = (statusContainer && statusContainer.dataset && statusContainer.dataset.truckId) ? parseInt(statusContainer.dataset.truckId) : null;
            if (tid) fetch('/geofence/' + tid + '/clear/', { method: 'POST', headers: { 'X-CSRFToken': getCSRF() }, credentials: 'same-origin' });
        } catch(e){}
        geofences = []; saveGeofences(); renderGeofences();
    }

    var addFenceMode = false;
    function startAddGeofence(){
        addFenceMode = true;
        alert('Click the map to set geofence center. A default 500m radius will be used.');
    }
    function addRectFence(sw, ne, name){
        var f = { type: 'rect', sw: sw, ne: ne, name: name || 'Area', inside: false };
        geofences.push(f);
        saveGeofences(); renderGeofences();
        notify('created', f);
        persistFence(f);
    }

    // Polygon sketch mode
    var sketch = { active: false, points: [], preview: null };
    function togglePolySketch(){
        sketch.active = !sketch.active;
        if (!sketch.active) { finishPolySketch(); }
        alert(sketch.active ? 'Polygon sketch: click to add vertices. Click Finish when done.' : 'Polygon sketch off');
    }
    function finishPolySketch(){
        if (sketch.points.length >= 3){
            var f = { type: 'polygon', points: sketch.points.slice(), name: 'Custom Fence', inside: false };
            geofences.push(f);
            saveGeofences(); renderGeofences();
            notify('created', f);
            persistFence(f);
        }
        if (sketch.preview) { geofenceLayer.removeLayer(sketch.preview); sketch.preview = null; }
        sketch.points = [];
        sketch.active = false;
    }
    function undoPolyVertex(){
        if (!sketch.active || !sketch.points.length) return;
        sketch.points.pop();
        drawSketchPreview();
    }
    function drawSketchPreview(){
        if (sketch.preview) { geofenceLayer.removeLayer(sketch.preview); sketch.preview = null; }
        if (sketch.points.length >= 2) {
            sketch.preview = L.polygon(sketch.points, { dashArray: '4,4', color: '#00acc1' }).addTo(geofenceLayer);
        }
    }

    map.on('click', function(e){
        if (addFenceMode){
            addFenceMode = false;
            var center = [e.latlng.lat, e.latlng.lng];
            var radius = 500; // meters
            var f = { type: 'circle', center: center, radius: radius, inside: false, name: 'Fence ' + (geofences.length+1) };
            geofences.push(f);
            saveGeofences();
            renderGeofences();
            notify('created', f);
            persistFence(f);
            return;
        }
        if (sketch.active){
            sketch.points.push([e.latlng.lat, e.latlng.lng]);
            drawSketchPreview();
        }
    });
    // Turn off follow when the user interacts with the map view
    function _disableFollow(){
        if (!followTruck) return;
        followTruck = false;
        var el = document.getElementById('mapFollowBtn');
        if (el) el.setAttribute('aria-pressed','false');
    }
    map.on('zoomstart', _disableFollow);
    map.on('dragstart', _disableFollow);

    function pointInCircle(pt, fence){
        var d = haversine(pt[0], pt[1], fence.center[0], fence.center[1]) * 1000; // m
        return d <= fence.radius;
    }
    function pointInRect(pt, fence){
        var lat = pt[0], lng = pt[1];
        var sw = fence.sw, ne = fence.ne;
        return lat >= sw[0] && lat <= ne[0] && lng >= sw[1] && lng <= ne[1];
    }
    function pointInPolygon(pt, points){
        // Ray casting
        var x = pt[1], y = pt[0];
        var inside = false;
        for (var i = 0, j = points.length - 1; i < points.length; j = i++){
            var yi = points[i][0], xi = points[i][1];
            var yj = points[j][0], xj = points[j][1];
            var intersect = ((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-12) + xi);
            if (intersect) inside = !inside;
        }
        return inside;
    }
    function checkGeofences(pt){
        var events = [];
        geofences.forEach(f => {
            var nowIn = false;
            if (f.type === 'circle') nowIn = pointInCircle(pt, f);
            else if (f.type === 'rect') nowIn = pointInRect(pt, f);
            else if (f.type === 'polygon') nowIn = pointInPolygon(pt, f.points || []);
            if (f.inside === undefined) f.inside = nowIn;
            if (nowIn !== f.inside){
                f.inside = nowIn;
                events.push((nowIn ? 'Entered ' : 'Exited ') + (f.name || 'Geofence'));
                try { notify(nowIn ? 'entered' : 'exited', f, pt); } catch(e){}
            }
        });
        if (events.length){
            saveGeofences();
            var el = document.getElementById('geofence-events');
            if (el){
                var ul = document.createElement('ul');
                events.forEach(txt => { var li = document.createElement('li'); li.textContent = txt; ul.appendChild(li); });
                el.appendChild(ul);
            }
        }
    }
    // Email notifications via server endpoint
    function getCSRF(){ var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? m[1] : ''; }
    function notify(eventType, fence, pos){
        try {
            var body = {
                event_type: eventType,
                fence: fence,
                truck_id: (statusContainer && statusContainer.dataset && statusContainer.dataset.truckId) ? parseInt(statusContainer.dataset.truckId) : undefined,
                plate_number: (lastTruckStatus && lastTruckStatus.plate_number) || undefined,
                position: pos || undefined
            };
            fetch('/geofence/event/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
                body: JSON.stringify(body),
                credentials: 'same-origin'
            }).catch(function(){});
        } catch(e){}
    }
    function persistFence(fence){
        try {
            var tid = (statusContainer && statusContainer.dataset && statusContainer.dataset.truckId) ? parseInt(statusContainer.dataset.truckId) : null;
            if (!tid) return;
            var payload = Object.assign({ type: fence.type, name: fence.name || '' }, fence);
            fetch('/geofence/' + tid + '/create/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
                body: JSON.stringify(payload),
                credentials: 'same-origin'
            }).then(r => r.json()).then(function(resp){ if (resp && resp.id) fence.id = resp.id; }).catch(function(){});
        } catch(e){}
    }
});

/* Add these styles to your CSS */
const style = document.createElement("style");
style.innerHTML = `
    .ctrl-input { padding: 6px 8px; border: 1px solid rgba(0,0,0,.15); border-radius: 8px; background: rgba(255,255,255,0.95); }
    .leaflet-marker-icon.truck-moving .truck-icon-img { animation: truckPulse 1.2s infinite ease-in-out; }
    @keyframes truckPulse { 0% { transform: scale(1); } 50% { transform: scale(1.06); } 100% { transform: scale(1); } }

    .custom-truck-icon img {
        width: 50px;
        height: 50px;
        border-radius: 8px;
        filter: drop-shadow(2px 2px 5px rgba(0, 0, 0, 0.3));
    }

    .popup-title {
        font-size: 16px;
        font-weight: bold;
        color: #333;
        margin-bottom: 5px;
    }

    .popup-container p {
        font-size: 14px;
        margin: 4px 0;
        color: #555;
    }

    .status-indicator {
        font-weight: bold;
        color: green;
    }/* Default styling for popup container */
.popup-container {
  max-width: 400px; /* Default maximum width */
  max-height: 300px; /* Maximum height before overflow */
  padding: 10px;
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  overflow-y: auto; /* Enable vertical scrolling for overflowing content */
}

/* Adjust popup width and height for small devices */
@media (max-width: 480px) {
  .popup-container {
    max-width: 90%;  /* Use 90% of the viewport width */
    max-height: 250px; /* Adjusted maximum height for smaller screens */
  }
}

/* Additional styling for popup elements */
.popup-title {
  font-size: 16px;
  font-weight: bold;
  color: #333;
  margin-bottom: 5px;
}

.popup-container p {
  font-size: 14px;
  margin: 4px 0;
  color: #555;
}

.status-indicator {
  font-weight: bold;
  color: green;
}

`;
document.head.appendChild(style);
