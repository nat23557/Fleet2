document.addEventListener('DOMContentLoaded', function() {
    // 1) Parse months array
    var months = JSON.parse(document.getElementById('months-data').textContent);
  
    // 2) Parse truck data
    var truckData = JSON.parse(document.getElementById('truck-chart-data').textContent);
    var container = document.getElementById('perTruckChartsContainer');
  
    truckData.forEach(function(truck) {
      // Create a wrapper div for this truck and center its content
      var truckWrapper = document.createElement('div');
      truckWrapper.className = 'truck-charts-wrapper';
      truckWrapper.style.textAlign = 'center'; // Centers headings and inline elements
  
      // Add a heading for clarity
      var heading = document.createElement('h4');
      heading.textContent = 'Truck: ' + truck.truck_plate;
      truckWrapper.appendChild(heading);
  
      // Create a container for the charts stacked vertically
      var chartPairDiv = document.createElement('div');
      chartPairDiv.className = 'chart-pair';
      chartPairDiv.style.display = 'flex';
      chartPairDiv.style.flexDirection = 'column';  // Stack charts vertically
      chartPairDiv.style.alignItems = 'center';       // Center charts horizontally
      chartPairDiv.style.gap = '20px';                // Adds spacing between charts
  
      // ---------------
      // A) First chart: Revenue, Expense, Profit
      // ---------------
      var firstChartContainer = document.createElement('div');
      firstChartContainer.className = 'chart-container';
      chartPairDiv.appendChild(firstChartContainer);
  
      // Title for the first chart
      var firstChartTitle = document.createElement('h5');
      firstChartTitle.textContent = 'Monthly Financials (Revenue, Expense, Profit)';
      firstChartContainer.appendChild(firstChartTitle);
  
      // Canvas for the first chart with increased size
      var canvas1 = document.createElement('canvas');
      canvas1.width = 600;  // increased width
      canvas1.height = 400; // increased height
      canvas1.style.display = 'block';
      canvas1.style.margin = '0 auto'; // centers the canvas element
      firstChartContainer.appendChild(canvas1);
  
      // Initialize the first chart
      var ctx1 = canvas1.getContext('2d');
      new Chart(ctx1, {
        type: 'line',
        data: {
          labels: months,
          datasets: [
            {
              label: 'Revenue',
              data: truck.monthly_revenue,
              borderColor: 'rgba(2, 115, 53, 1)',
              backgroundColor: 'rgba(2, 115, 53, 0.2)',
              tension: 0.3,
              fill: false
            },
            {
              label: 'Expense',
              data: truck.monthly_expense,
              borderColor: 'rgba(255, 99, 132, 1)',
              backgroundColor: 'rgba(255, 99, 132, 0.2)',
              tension: 0.3,
              fill: false
            },
            {
              label: 'Profit',
              data: truck.monthly_income,
              borderColor: 'rgba(54, 162, 235, 1)',
              backgroundColor: 'rgba(54, 162, 235, 0.2)',
              tension: 0.3,
              fill: false
            }
          ]
        },
        options: {
          responsive: false,
          interaction: {
            mode: 'index',
            intersect: false
          },
          plugins: {
            title: {
              display: true,
              text: 'Monthly R/E/I'
            },
            tooltip: {
              callbacks: {
                label: function(context) {
                  return context.dataset.label + ': ' + context.parsed.y.toFixed(2);
                }
              }
            },
            legend: {
              display: true
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
  
      // ---------------
      // B) Second Chart: Expense by Category + checkboxes to show/hide
      // ---------------
      var secondChartContainer = document.createElement('div');
      secondChartContainer.className = 'chart-container';
      chartPairDiv.appendChild(secondChartContainer);
  
      // Title for the second chart
      var secondChartTitle = document.createElement('h5');
      secondChartTitle.textContent = 'Expense by Category (Toggle Visibility)';
      secondChartContainer.appendChild(secondChartTitle);
  
      // A container for the dynamic checkboxes
      var filterContainer = document.createElement('div');
      filterContainer.className = 'truck-expense-filters';
      secondChartContainer.appendChild(filterContainer);
  
      // Canvas for the second chart with increased size
      var canvas2 = document.createElement('canvas');
      canvas2.width = 600;
      canvas2.height = 400;
      canvas2.style.display = 'block';
      canvas2.style.margin = '0 auto';
      secondChartContainer.appendChild(canvas2);
  
      // Build the datasets for expense categories
      var expenseDatasets = truck.expense_categories.map(function(catItem, index) {
        return {
          label: catItem.category,
          data: catItem.monthly_expense,
          borderColor: getHighContrastColor(index, truck.expense_categories.length),
          backgroundColor: 'rgba(0, 0, 0, 0)',
          tension: 0.3,
          fill: false,
          hidden: false
        };
      });
  
      var ctx2 = canvas2.getContext('2d');
      var expenseChart = new Chart(ctx2, {
        type: 'line',
        data: {
          labels: months,
          datasets: expenseDatasets
        },
        options: {
          responsive: false,
          interaction: {
            mode: 'index',
            intersect: false
          },
          plugins: {
            title: {
              display: true,
              text: 'Monthly Expenses by Category'
            },
            tooltip: {
              callbacks: {
                label: function(context) {
                  return context.dataset.label + ': ' + context.parsed.y.toFixed(2);
                }
              }
            },
            legend: {
              display: true
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
  
      // Create a checkbox for each expense dataset
      expenseDatasets.forEach(function(dataset, i) {
        var label = document.createElement('label');
        label.className = 'checkbox-label';
  
        var checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = true;
        checkbox.dataset.index = i;
  
        checkbox.addEventListener('change', function() {
          var idx = parseInt(this.dataset.index);
          expenseChart.data.datasets[idx].hidden = !this.checked;
          expenseChart.update();
        });
  
        label.appendChild(checkbox);
        label.appendChild(document.createTextNode(' ' + dataset.label));
        filterContainer.appendChild(label);
      });
  
      // Append the chart container to the truck wrapper and then to the main container
      truckWrapper.appendChild(chartPairDiv);
      container.appendChild(truckWrapper);
    });
  
    /**
     * Generates a distinct color for each dataset using HSL for better contrast.
     */
    function getHighContrastColor(index, total) {
      var hue = Math.round((360 / total) * index);
      return 'hsl(' + hue + ', 100%, 40%)';
    }
  });
  
