document.addEventListener("DOMContentLoaded", function() {
    function initializeMap(mapId, latFieldId, lngFieldId, locationFieldId) {
        var map = L.map(mapId).setView([9.03, 38.74], 10); // Default location: Addis Ababa

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(map);

        var marker = L.marker([9.03, 38.74], { draggable: true }).addTo(map);

        marker.on('dragend', function (e) {
            var lat = e.target.getLatLng().lat;
            var lng = e.target.getLatLng().lng;
            
            document.getElementById(latFieldId).value = lat;
            document.getElementById(lngFieldId).value = lng;

            fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`)
                .then(response => response.json())
                .then(data => {
                    if (data.display_name) {
                        document.getElementById(locationFieldId).value = data.display_name;
                    }
                })
                .catch(error => console.error("Error fetching location name:", error));
        });
    }

    // Initialize maps for start and end locations
    initializeMap('start-map', 'id_start_latitude', 'id_start_longitude', 'id_start_location');
    initializeMap('end-map', 'id_end_latitude', 'id_end_longitude', 'id_end_location');
});
