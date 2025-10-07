// map_combined.js

document.addEventListener("DOMContentLoaded", function() {
    console.log("map_combined.js: DOMContentLoaded event fired.");
  
    // 1) Read route points from the global window object
    var points = window.routePoints || [];
    console.log("map_combined.js: routePoints =>", points);
  
    // 2) Sort points by timestamp (if available)
    points.sort(function(a, b) {
      var tA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
      var tB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
      return tA - tB;
    });
  
    // 3) Initialize the Leaflet map on #route-map, store it globally as window.map
    console.log("map_combined.js: Initializing the Leaflet map...");
    window.map = L.map("route-map").setView([0, 0], 5);
  
    // 4) Add tile layers (using Esri imagery and labels)
    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: 'Tiles © Esri, DigitalGlobe, Earthstar Geographics',
        maxZoom: 19
      }
    ).addTo(window.map);
  
    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: 'Labels © Esri',
        maxZoom: 19
      }
    ).addTo(window.map);
  
    // 5) Create a divIcon with a "3D" style wrapper for your car/truck image.
    var carIcon = L.divIcon({
      className: "custom-car-icon",
      html: `
        <div class="truck-icon-wrapper">
          <img src="/static/images/truck_icon.png" alt="Truck" class="truck-icon-img">
        </div>
      `,
      iconSize: [48, 48],
      iconAnchor: [24, 48],
      popupAnchor: [0, -48]
    });
  
    // 6) Build arrays for polyline and bounding
    var allLatLngs = [];
    var lineLatLngs = [];
    var lastIndex = points.length - 1;
  
    points.forEach(function(pt, index) {
      if (!pt.lat || !pt.lng) return;
      var lat = parseFloat(pt.lat);
      var lng = parseFloat(pt.lng);
      var isLast = (index === lastIndex);
  
      allLatLngs.push([lat, lng]);
  
      // For intermediate points, add a circle marker
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
  
    // If last point is valid, place the "car" icon
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
  
    // Draw a polyline (excluding the final point) if at least two intermediate points exist.
    if (lineLatLngs.length > 1) {
      L.polyline(lineLatLngs, {
        color: "blue",
        weight: 3
      }).addTo(window.map);
    }
  
    // Fit map bounds to all valid points
    if (allLatLngs.length > 1) {
      window.map.fitBounds(allLatLngs);
    } else if (allLatLngs.length === 1) {
      window.map.setView(allLatLngs[0], 14);
    }
  
    // 7) Wait a bit, then capture the map using leaflet-image
    setTimeout(function() {
      if (typeof leafletImage === "undefined") {
        console.warn("leaflet-image not found. Did you include the script?");
        return;
      }
      if (!window.map) {
        console.error("No map found on window.map, cannot capture.");
        return;
      }
      console.log("map_combined.js: Attempting to capture the map...");
      leafletImage(window.map, function(err, canvas) {
        if (err) {
          console.error("Error capturing the map:", err);
          return;
        }
        var mapDataUrl = canvas.toDataURL("image/png");
        var hiddenInput = document.getElementById("mapDataUrl");
        if (hiddenInput) {
          hiddenInput.value = mapDataUrl;
          console.log("Map captured successfully! Base64 data placed in #mapDataUrl.");
        } else {
          console.warn("Hidden input #mapDataUrl not found in DOM.");
        }
      });
    }, 3000); // Adjust the delay as needed
  });
  
