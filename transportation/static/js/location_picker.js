document.addEventListener("DOMContentLoaded", function() {
    var map = L.map('map').setView([9.145, 40.4897], 6); // Default Ethiopia view

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    var marker;

    function updateLocation(lat, lng) {
        document.getElementById("id_location").value = lat + ", " + lng;
        document.getElementById("id_latitude").value = lat;
        document.getElementById("id_longitude").value = lng;
    }

    map.on('click', function(e) {
        if (marker) {
            map.removeLayer(marker);
        }
        marker = L.marker(e.latlng).addTo(map);
        updateLocation(e.latlng.lat, e.latlng.lng);
    });
});
