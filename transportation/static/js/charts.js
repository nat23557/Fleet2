document.addEventListener("DOMContentLoaded", function() {
  // 1) SELECT DOM ELEMENTS
  const modal = document.getElementById("chartModal");
  const modalContent = document.getElementById("modalChartContainer");
  const closeButton = document.getElementsByClassName("close-button")[0];

  // Retrieve data from hidden/script elements
  const months = JSON.parse(document.getElementById("months-data").textContent);
  const truckDataList = JSON.parse(document.getElementById("truck-chart-data").textContent);

  // REMOVE: no longer set modal width/height in JS; let CSS handle full-screen overlay
  // const isMobile = window.innerWidth < 768;
  // modal.style.width = isMobile ? "100%" : "90%";
  // modal.style.height = isMobile ? "100%" : "90%";
  // modal.style.margin = "auto";

  // 2) ATTACH EVENT LISTENERS TO BUTTONS
  document.querySelectorAll(".view-chart-button").forEach(button => {
    button.addEventListener("click", function(e) {
      e.preventDefault();
      openChartModal(this.dataset.chart);
    });
  });

  // 3) OPEN MODAL (ENTRY POINT)
  function openChartModal(chartType) {
    // Clear any previous chart/UI
    modalContent.innerHTML = "";

    switch (chartType) {
      case "overall":
        renderOverallMonthlyTrendsChart();
        break;
      case "expense":
        renderOverallExpenseTrendsChart();
        break;
      case "perTruck":
        renderPerTruckSelector();
        break;
      default:
        console.warn(`Unknown chart type: ${chartType}`);
    }

    // Display the modal (overlay covers entire screen via CSS)
    modal.style.display = "block";
  }

  // 4) RENDER OVERALL MONTHLY TRENDS
  function renderOverallMonthlyTrendsChart() {
    // Container with header
    const container = document.createElement("div");
    container.className = "chart-container";
    container.style.maxHeight = "700px";
    container.style.overflowY = "auto";

    const header = document.createElement("h3");
    header.textContent = "Overall Monthly Financial Trends";
    container.appendChild(header);

    modalContent.appendChild(container);

    // Canvas for Chart.js
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "600px";
    container.appendChild(canvas);

    // Get data from hidden div
    const overallData = JSON.parse(
      document.getElementById("overallChart").getAttribute("data-overall")
    );

    new Chart(canvas.getContext('2d'), {
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
        plugins: {
          title: {
            display: true,
            text: 'Overall Monthly Financial Trends'
          },
          tooltip: {
            callbacks: {
              label: context => {
                const val = context.parsed.y || 0;
                return `${context.dataset.label}: ${val.toFixed(2)}`;
              }
            }
          },
          legend: {
            onClick: function(e, legendItem, legend) {
              const index = legendItem.datasetIndex;
              const ci = legend.chart;
              ci.data.datasets[index].hidden = !ci.data.datasets[index].hidden;
              ci.update();
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            title: { display: true, text: 'Amount' }
          }
        }
      }
    });
  }

  // 5) RENDER OVERALL EXPENSE TRENDS
  function renderOverallExpenseTrendsChart() {
    const container = document.createElement("div");
    container.className = "chart-container";
    container.style.maxHeight = "700px";
    container.style.overflowY = "auto";

    const header = document.createElement("h3");
    header.textContent = "Expense Trends by Category";
    container.appendChild(header);
    modalContent.appendChild(container);

    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "600px";
    container.appendChild(canvas);

    const expenseData = JSON.parse(
      document.getElementById("expenseChart").getAttribute("data-expense")
    );

    const datasets = expenseData.map((item, index) => ({
      label: item.category,
      data: item.monthly_expense,
      borderColor: getHighContrastColor(index, expenseData.length),
      backgroundColor: 'rgba(0, 0, 0, 0)',
      tension: 0.3,
      fill: false
    }));

    new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { labels: months, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: 'Expense Trends by Category' },
          tooltip: {
            callbacks: {
              label: context => {
                const val = context.parsed.y || 0;
                return `${context.dataset.label}: ${val.toFixed(2)}`;
              }
            }
          },
          legend: {
            onClick: function(e, legendItem, legend) {
              const ci = legend.chart;
              const idx = legendItem.datasetIndex;
              ci.data.datasets[idx].hidden = !ci.data.datasets[idx].hidden;
              ci.update();
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            title: { display: true, text: 'Amount' }
          }
        },
        onClick: function(evt, activeElements) {
          if (activeElements.length > 0) {
            const element = activeElements[0];
            const datasetIndex = element.datasetIndex;
            this.data.datasets[datasetIndex].hidden = 
              !this.data.datasets[datasetIndex].hidden;
            this.update();
          }
        }
      }
    });
  }

  // 6) RENDER "PER-TRUCK" SELECTOR
  function renderPerTruckSelector() {
    const truckSelectorCard = document.createElement("div");
    truckSelectorCard.className = "truck-selector-card";

    const header = document.createElement("h3");
    header.textContent = "Select a Truck";
    truckSelectorCard.appendChild(header);

    const gridContainer = document.createElement("div");
    gridContainer.className = "truck-grid-container";

    truckDataList.forEach(truck => {
      const truckBtn = document.createElement("button");
      truckBtn.className = "truck-card cta-button";
      truckBtn.textContent = truck.truck_plate;

      truckBtn.addEventListener("click", function() {
        displayTruckCharts(truck);
      });
      gridContainer.appendChild(truckBtn);
    });

    truckSelectorCard.appendChild(gridContainer);
    modalContent.appendChild(truckSelectorCard);
  }

  // 7) DISPLAY OPTIONS FOR A SPECIFIC TRUCK
  function displayTruckCharts(truck) {
    modalContent.innerHTML = "";

    const headerCard = document.createElement("div");
    headerCard.className = "truck-selection-header";
    headerCard.innerHTML = `<h3>Truck: ${truck.truck_plate}</h3>`;
    modalContent.appendChild(headerCard);

    const selectionCard = document.createElement("div");
    selectionCard.className = "truck-chart-selection-card";

    const monthlyBtn = document.createElement("button");
    monthlyBtn.className = "cta-button truck-chart-selection-button";
    monthlyBtn.textContent = "Monthly Trends";
    monthlyBtn.addEventListener("click", () => renderTruckMonthlyChart(truck));

    const expenseBtn = document.createElement("button");
    expenseBtn.className = "cta-button truck-chart-selection-button";
    expenseBtn.textContent = "Expense Breakdown";
    expenseBtn.addEventListener("click", () => renderTruckExpenseChart(truck));

    selectionCard.appendChild(monthlyBtn);
    selectionCard.appendChild(expenseBtn);
    modalContent.appendChild(selectionCard);
  }

  // 8) PER-TRUCK MONTHLY TRENDS
  function renderTruckMonthlyChart(truck) {
    modalContent.innerHTML = "";
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "600px";
    modalContent.appendChild(canvas);

    new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: months,
        datasets: [
          {
            label: 'Monthly Revenue',
            data: truck.monthly_revenue,
            borderColor: 'rgba(2, 115, 53, 1)',
            backgroundColor: 'rgba(2, 115, 53, 0.2)',
            tension: 0.3,
            fill: false
          },
          {
            label: 'Monthly Expense',
            data: truck.monthly_expense,
            borderColor: 'rgba(255, 99, 132, 1)',
            backgroundColor: 'rgba(255, 99, 132, 0.2)',
            tension: 0.3,
            fill: false
          },
          {
            label: 'Monthly Income',
            data: truck.monthly_income,
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
        plugins: {
          title: { display: true, text: 'Truck Monthly Financial Trends' },
          tooltip: {
            callbacks: {
              label: context => {
                const val = context.parsed.y || 0;
                return `${context.dataset.label}: ${val.toFixed(2)}`;
              }
            }
          },
          legend: {
            onClick: function(e, legendItem, legend) {
              const index = legendItem.datasetIndex;
              const ci = legend.chart;
              ci.data.datasets[index].hidden = !ci.data.datasets[index].hidden;
              ci.update();
            }
          }
        },
        scales: {
          y: { beginAtZero: true, title: { display: true, text: 'Amount' } }
        }
      }
    });
  }

  // 9) PER-TRUCK EXPENSE CHART
  function renderTruckExpenseChart(truck) {
    modalContent.innerHTML = "";

    const container = document.createElement("div");
    container.className = "truck-expense-chart-container";
    container.style.maxHeight = "700px";
    container.style.overflowY = "auto";

    modalContent.appendChild(container);

    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "600px";
    container.appendChild(canvas);

    // Build datasets from each expense category
    const datasets = truck.expense_categories.map((item, index) => ({
      label: item.category,
      data: item.monthly_expense,
      borderColor: getHighContrastColor(index, truck.expense_categories.length),
      backgroundColor: 'rgba(0, 0, 0, 0)',
      tension: 0.3,
      fill: false
    }));

    const truckExpenseChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: months,
        datasets
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: `Truck Expense by Category` },
          tooltip: {
            callbacks: {
              label: context => {
                const val = context.parsed.y || 0;
                return `${context.dataset.label}: ${val.toFixed(2)}`;
              }
            }
          },
          legend: {
            onClick: function(e, legendItem, legend) {
              const idx = legendItem.datasetIndex;
              const ci = legend.chart;
              ci.data.datasets[idx].hidden = !ci.data.datasets[idx].hidden;
              ci.update();
            }
          }
        },
        scales: {
          y: { beginAtZero: true, title: { display: true, text: 'Amount' } }
        },
        onClick: function(evt, activeElements) {
          if (activeElements.length > 0) {
            const element = activeElements[0];
            const datasetIndex = element.datasetIndex;
            truckExpenseChart.data.datasets[datasetIndex].hidden =
              !truckExpenseChart.data.datasets[datasetIndex].hidden;
            truckExpenseChart.update();
          }
        }
      }
    });
  }

  // 10) CLOSE MODAL LOGIC
  closeButton.addEventListener("click", () => {
    modal.style.display = "none";
  });

  window.addEventListener("click", event => {
    if (event.target === modal) {
      modal.style.display = "none";
    }
  });

  // 11) COLOR HELPER
  function getHighContrastColor(index, total) {
    const hue = Math.round((360 / total) * index);
    return `hsl(${hue}, 100%, 40%)`;
  }
});
