document.addEventListener('DOMContentLoaded', function () { 
    // Retrieve overall monthly data from canvas attribute.
    var overallCanvas = document.getElementById('overallChart');
    var overallData = JSON.parse(overallCanvas.getAttribute('data-overall'));
    
    // Retrieve months from the script tag
    var months = JSON.parse(document.getElementById('months-data').textContent);
    
    // Style the container and the canvas for responsiveness.
    var container = overallCanvas.parentElement;
    container.style.width = "80%";
    container.style.overflowX = "auto";
    // Set the canvas to fill the container's width and a fixed height (in pixels)
    overallCanvas.style.width = "70%";
    overallCanvas.style.height = "400px";
    
    // Create overall monthly line chart.
    var ctxOverall = overallCanvas.getContext('2d');
    var overallChart = new Chart(ctxOverall, {
        type: 'line',
        data: {
            labels: months,
            datasets: [
                {
                    label: 'Revenue',
                    data: overallData.total_revenue,
                    borderColor: 'rgba(2, 115, 53, 1)',
                    backgroundColor: 'rgba(2, 115, 53, 0.2)',
                    tension: 0.3,
                    fill: false
                },
                {
                    label: 'Expense',
                    data: overallData.total_expense,
                    borderColor: 'rgba(255, 99, 132, 1)',
                    backgroundColor: 'rgba(255, 99, 132, 0.2)',
                    tension: 0.3,
                    fill: false
                },
                {
                    label: 'Income',
                    data: overallData.income_before_tax,
                    borderColor: 'rgba(54, 162, 235, 1)',
                    backgroundColor: 'rgba(54, 162, 235, 0.2)',
                    tension: 0.3,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                title: {
                    display: true,
                    text: 'Overall Monthly Financial Trends'
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return context.dataset.label + ': ' + context.parsed.y.toFixed(2);
                        }
                    }
                },
                legend: {
                    display: true,
                    onClick: function(e, legendItem, legend) {
                        const index = legendItem.datasetIndex;
                        const ci = legend.chart;
                        ci.toggleDataVisibility(index);
                        ci.update();
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Amount'
                    }
                }
            }
        }
    });
});
