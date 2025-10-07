// map_capture.js

document.addEventListener("DOMContentLoaded", function() {
    // Wait a few seconds for the map to fully render tiles
    setTimeout(function() {
      if (window.map) {
        // Use leaflet-image to capture the existing map
        leafletImage(window.map, function(err, canvas) {
          if (err) {
            console.error("Error capturing the map:", err);
            return;
          }
          // Convert canvas to data URL
          const mapDataUrl = canvas.toDataURL("image/png");
          // Store it in a hidden input
          const hiddenInput = document.getElementById("mapDataUrl");
          if (hiddenInput) {
            hiddenInput.value = mapDataUrl;
            console.log("Map captured successfully!");
          } else {
            console.warn("Hidden input #mapDataUrl not found.");
          }
        });
      } else {
        console.error("window.map is not defined. Make sure trip_map.js ran first.");
      }
    }, 3000); // Adjust as needed
  });
  