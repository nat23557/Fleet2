document.addEventListener("DOMContentLoaded", function() {
    // Function to fetch and update truck status
    function updateTruckStatus() {
        // Read the truck id from a data attribute on the real-time container
        const realTimeElem = document.getElementById("real-time-status");
        const truckId = realTimeElem.dataset.truckId;
        // Build the URL for the status endpoint; adjust the URL path as needed
        const url = `/trucks/${truckId}/status/`;

        fetch(url)
            .then(response => response.json())
            .then(data => {
                const statusContent = document.getElementById("status-content");
                if (data.error) {
                    statusContent.innerHTML = `<p class="text-muted">${data.error}</p>`;
                } else {
                    statusContent.innerHTML = `
                        <p><strong>Location:</strong> ${data.location} (${data.latitude}, ${data.longitude})</p>
                        <p><strong>Engine:</strong> ${data.engine}</p>
                        <p><strong>Speed:</strong> ${data.speed} km/h</p>
                        <p><strong>Fuel Sensor 1:</strong> ${data.fuel_1}</p>
                        <p><strong>Fuel Sensor 2:</strong> ${data.fuel_2}</p>
                        <p><strong>Updated at:</strong> ${data.timestamp}</p>
                    `;
                }
            })
            .catch(error => {
                console.error("Error updating truck status:", error);
            });
    }

    // Initial update on page load
    updateTruckStatus();
    // Update every 30 seconds
    setInterval(updateTruckStatus, 30000);
});
