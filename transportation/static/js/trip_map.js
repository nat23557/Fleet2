document.addEventListener("DOMContentLoaded", function() {
  // 1) Get the route points from the global window object.
  var points = window.routePoints || [];

  // 2) Sort points by timestamp ascending so the last item has the latest time.
  //    If timestamp is missing/invalid, we treat as 0, which sorts them first.
  points.sort(function(a, b) {
    var tA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
    var tB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
    return tA - tB;
  });

  // 3) Initialize the Leaflet map and store it globally as window.map
  window.map = L.map("route-map", { zoomControl: true }).setView([0, 0], 6);

  // 4) Base layers + control
  var osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors', maxZoom: 19 });
  var imagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { attribution: 'Imagery © Esri, Maxar', maxZoom: 19 });
  var streets = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', { attribution: 'Streets © Esri', maxZoom: 19 });
  var labels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', { attribution: 'Labels © Esri', maxZoom: 19 });
  osm.addTo(window.map);
  L.control.layers({ 'OSM': osm, 'Imagery': imagery, 'Streets': streets }, { 'Labels': labels }, { position: 'topright' }).addTo(window.map);
  L.control.scale({ metric: true, imperial: false }).addTo(window.map);

  // 5) Create a divIcon with a "3D" style wrapper for your car/truck image.
  var carIcon = L.divIcon({
    className: "custom-car-icon", // We'll style this in CSS
    html: `
      <div class="car-icon-wrapper">
        <img src="/static/images/truck_icon.png" alt="Truck" class="car-icon-img">
      </div>
    `,
    iconSize: [48, 48],   // total size of the icon container
    iconAnchor: [24, 48], // tip of the icon (bottom center)
    popupAnchor: [0, -48] // popup above the icon
  });

  // 6) We'll store all coords for bounding the map
  var allLatLngs = [];

  // 7) Identify the last (latest) point
  var lastIndex = points.length - 1;

  // 8) Build an array for the polyline that excludes the last point
  var lineLatLngs = [];

  points.forEach(function(pt, index) {
    if (!pt.lat || !pt.lng) return; // Skip invalid coords

    var lat = parseFloat(pt.lat);
    var lng = parseFloat(pt.lng);
    var isLast = (index === lastIndex);

    // Keep track of all coordinates for final map fit
    allLatLngs.push([lat, lng]);

    // Place circle markers for everything except the last point
    if (!isLast) {
      lineLatLngs.push([lat, lng]);

      var circle = L.circleMarker([lat, lng], {
        radius: 6,
        color: "#0066ff",
        fillColor: "#3399ff",
        fillOpacity: 0.9
      }).addTo(window.map);

      circle.bindPopup(`
        <strong>${pt.loc || "Intermediate Point"}</strong><br>
        ${pt.timestamp || ""}
      `);
    }
  });

  // 9) If we have a valid last point, place the car icon
  if (points[lastIndex] && points.length > 0) {
    var finalPoint = points[lastIndex];
    if (finalPoint.lat && finalPoint.lng) {
      var lat = parseFloat(finalPoint.lat);
      var lng = parseFloat(finalPoint.lng);

      var lastMarker = L.marker([lat, lng], { icon: carIcon }).addTo(window.map);
      lastMarker.bindPopup(`
        <strong>${finalPoint.loc || "Last Point"}</strong><br>
        ${finalPoint.timestamp || ""}
      `);
    }
  }

  // 10) Draw a polyline from the first point up to the second‐to‐last point
  //     (lineLatLngs now excludes the final point).
  //     Only do this if we have at least 2 intermediate points.
  if (lineLatLngs.length > 1) {
    L.polyline(lineLatLngs, {
      color: "blue",
      weight: 3
    }).addTo(window.map);
  }

  // 11) Fit map based on ALL points (intermediate + last).
  if (allLatLngs.length > 1) {
    window.map.fitBounds(allLatLngs);
  } else if (allLatLngs.length === 1) {
    // If exactly one point overall, center on it
    window.map.setView(allLatLngs[0], 14);
  }
});
