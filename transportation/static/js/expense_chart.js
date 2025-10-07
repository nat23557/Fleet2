document.addEventListener('DOMContentLoaded', function () {
    var expenseCanvas = document.getElementById('expenseChart');
    var expenseData = JSON.parse(expenseCanvas.getAttribute('data-expense'));
    var months = JSON.parse(document.getElementById('months-data').textContent);
  
    // Create the chart
    var ctxExpense = expenseCanvas.getContext('2d');
  
    // We'll keep the dataset objects here for direct reference
    var datasets = expenseData.map(function (categoryItem, index) {
      return {
        label: categoryItem.category,
        data: categoryItem.monthly_expense,
        borderColor: getHighContrastColor(index, expenseData.length),
        backgroundColor: 'rgba(0, 0, 0, 0)',
        tension: 0.3,
        fill: false,
        hidden: false // we'll hide/show via checkboxes
      };
    });
  
    var expenseChart = new Chart(ctxExpense, {
      type: 'line',
      data: {
        labels: months,
        datasets: datasets
      },
      options: {
        responsive: true,
        interaction: {
          mode: 'index',
          intersect: false
        },
        plugins: {
          title: {
            display: true,
            text: 'Expense Trends by Category'
          },
          tooltip: {
            callbacks: {
              label: function (context) {
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
  
    // Dynamically create a checkbox for each dataset
    var filterContainer = document.getElementById('expenseFilters');
    datasets.forEach(function(dataset, i) {
      var label = document.createElement('label');
      label.style.display = 'inline-block';
      label.style.marginRight = '15px';
  
      var checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = true; // all visible by default
      checkbox.dataset.index = i; // store dataset index
  
      checkbox.addEventListener('change', function() {
        var idx = parseInt(this.dataset.index);
        // Toggle the "hidden" property on the dataset
        expenseChart.data.datasets[idx].hidden = !this.checked;
        expenseChart.update();
      });
  
      label.appendChild(checkbox);
      label.appendChild(document.createTextNode(' ' + dataset.label));
      filterContainer.appendChild(label);
    });
  
    /**
     * Example function to generate a distinct color for each category using HSL.
     * This ensures high contrast when there are 15+ categories.
     */
    function getHighContrastColor(index, total) {
      let hue = Math.round((360 / total) * index);
      return `hsl(${hue}, 100%, 40%)`;
    }
  });
  