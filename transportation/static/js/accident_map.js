document.addEventListener("DOMContentLoaded", function() {
    var mapElement = document.getElementById("accident-map");

    if (mapElement && mapElement.dataset.lat && mapElement.dataset.lng) {
        var lat = parseFloat(mapElement.dataset.lat);
        var lng = parseFloat(mapElement.dataset.lng);

        var map = L.map('accident-map').setView([lat, lng], 15);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(map);

        L.marker([lat, lng])
            .addTo(map)
            .bindPopup("<b>Accident Location</b><br>" + mapElement.dataset.location)
            .openPopup();
    }
});
