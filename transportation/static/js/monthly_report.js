document.addEventListener("DOMContentLoaded", function() {
  console.log("Script loaded");

  // Modal Elements
  const modal = document.getElementById("chartModal");
  const modalContent = document.getElementById("modalChartContainer");
  const closeButton = document.getElementsByClassName("close-button")[0];

  // Retrieve JSON data
  const months = JSON.parse(document.getElementById("months-data").textContent);
  const truckDataList = JSON.parse(document.getElementById("truck-chart-data").textContent);
  const overallTotals = JSON.parse(document.getElementById("overall-totals-data").textContent);
  const rawExpenseData = JSON.parse(document.getElementById("raw-expense-data").textContent);

  // Pop-up button events
  const chartButtons = document.querySelectorAll(".view-chart-button");
  chartButtons.forEach(button => {
    button.addEventListener("click", function(e) {
      e.preventDefault();
      openChartModal(this.dataset.chart);
    });
  });

  function openChartModal(chartType) {
    console.log("Opening modal for:", chartType);
    modalContent.innerHTML = "";
    if (chartType === "overallPerformance") {
      renderOverallPerformanceChart();
    } else if (chartType === "expenseCategory") {
      renderExpenseCategoryChart();
    } else if (chartType === "perTruck") {
      renderPerTruckSelector();
    }
    // Temporary debug styling
    modal.style.border = "5px solid red";
    modal.style.display = "block";
    console.log("Modal display set to:", modal.style.display);
  }

  function renderOverallPerformanceChart() {
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    modalContent.appendChild(canvas);
    new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: ["Revenue", "Expense", "Income"],
        datasets: [{
          label: "Overall Financials",
          data: [
            parseFloat(overallTotals.total_revenue || 0),
            parseFloat(overallTotals.total_expense || 0),
            parseFloat(overallTotals.income_before_tax || 0)
          ],
          backgroundColor: [
            "rgba(2, 115, 53, 0.7)",
            "rgba(255, 99, 132, 0.7)",
            "rgba(54, 162, 235, 0.7)"
          ],
          borderColor: [
            "rgba(2, 115, 53, 1)",
            "rgba(255, 99, 132, 1)",
            "rgba(54, 162, 235, 1)"
          ],
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 2,
        scales: {
          y: { beginAtZero: true, title: { display: true, text: "Amount" } }
        },
        plugins: {
          title: { display: true, text: "Overall Financial Summary" },
          tooltip: { callbacks: { label: context => context.dataset.label + ": " + context.parsed.y.toFixed(2) } }
        }
      }
    });
  }

  // Updated renderExpenseCategoryChart function
  function renderExpenseCategoryChart() {
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    modalContent.appendChild(canvas);

    // Aggregate overall expense per category (summing across all trucks)
    const categoryMap = {};
    rawExpenseData.forEach(item => {
      categoryMap[item.category] = (categoryMap[item.category] || 0) + parseFloat(item.expense);
    });
    const categories = Object.keys(categoryMap);

    new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: ["Expense Amount"], // Single label since each dataset represents a category
        datasets: categories.map((cat, index) => ({
          label: cat,
          data: [categoryMap[cat]],
          backgroundColor: getHighContrastColor(index, categories.length),
          borderColor: getHighContrastColor(index, categories.length),
          borderWidth: 1
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 2,
        scales: {
          y: { beginAtZero: true, title: { display: true, text: "Expense Amount" } }
        },
        plugins: {
          title: { display: true, text: "Expense per Category" },
          tooltip: { callbacks: { label: context => context.dataset.label + ": " + context.parsed.y.toFixed(2) } },
          legend: {
            onClick: function(e, legendItem, legend) {
              const index = legendItem.datasetIndex;
              const ci = legend.chart;
              ci.data.datasets[index].hidden = !ci.data.datasets[index].hidden;
              ci.update();
            }
          }
        },
        onClick: function(evt, activeElements) {
          if (activeElements.length > 0) {
            const element = activeElements[0];
            const datasetIndex = element.datasetIndex;
            this.data.datasets[datasetIndex].hidden = !this.data.datasets[datasetIndex].hidden;
            this.update();
          }
        }
      }
    });
  }

  function renderPerTruckSelector() {
    const card = document.createElement("div");
    card.className = "truck-selector-card";
    const header = document.createElement("h3");
    header.textContent = "Select a Truck";
    card.appendChild(header);
    const grid = document.createElement("div");
    grid.className = "truck-grid-container";
    truckDataList.forEach((truck, index) => {
      const btn = document.createElement("button");
      btn.className = "truck-card cta-button";
      btn.textContent = truck.truck_plate;
      btn.dataset.truckIndex = index;
      btn.addEventListener("click", function() {
        renderPerTruckOptions(truck);
      });
      grid.appendChild(btn);
    });
    card.appendChild(grid);
    modalContent.appendChild(card);
  }

  function renderPerTruckOptions(truck) {
    modalContent.innerHTML = "";
    const header = document.createElement("div");
    header.className = "truck-selection-header";
    header.innerHTML = `<h3>Truck: ${truck.truck_plate}</h3>`;
    modalContent.appendChild(header);
    const card = document.createElement("div");
    card.className = "truck-chart-selection-card";
    const overallBtn = document.createElement("button");
    overallBtn.className = "cta-button truck-chart-selection-button";
    overallBtn.textContent = "Overall Performance";
    overallBtn.addEventListener("click", function() {
      renderTruckOverallChart(truck);
    });
    const expenseBtn = document.createElement("button");
    expenseBtn.className = "cta-button truck-chart-selection-button";
    expenseBtn.textContent = "Expense Breakdown";
    expenseBtn.addEventListener("click", function() {
      renderTruckExpenseChart(truck);
    });
    card.appendChild(overallBtn);
    card.appendChild(expenseBtn);
    modalContent.appendChild(card);
  }

  function renderTruckOverallChart(truck) {
    modalContent.innerHTML = "";
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    modalContent.appendChild(canvas);
    new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: ["Revenue", "Expense", "Income"],
        datasets: [{
          label: truck.truck_plate,
          data: [
            parseFloat(truck.total_revenue || 0),
            parseFloat(truck.total_expense || 0),
            parseFloat(truck.income_before_tax || 0)
          ],
          backgroundColor: [
            "rgba(2, 115, 53, 0.7)",
            "rgba(255, 99, 132, 0.7)",
            "rgba(54, 162, 235, 0.7)"
          ],
          borderColor: [
            "rgba(2, 115, 53, 1)",
            "rgba(255, 99, 132, 1)",
            "rgba(54, 162, 235, 1)"
          ],
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 2,
        scales: {
          y: { beginAtZero: true, title: { display: true, text: "Amount" } }
        },
        plugins: {
          title: { display: true, text: "Truck Overall Performance" },
          tooltip: { callbacks: { label: context => context.dataset.label + ": " + context.parsed.y.toFixed(2) } }
        }
      }
    });
  }

  function renderTruckExpenseChart(truck) {
    modalContent.innerHTML = "";
    const container = document.createElement("div");
    container.className = "truck-expense-chart-container";
    modalContent.appendChild(container);
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    container.appendChild(canvas);
    const datasets = truck.expense_categories.map((item, index) => ({
      label: item.category,
      data: item.monthly_expense,
      borderColor: getHighContrastColor(index, truck.expense_categories.length),
      backgroundColor: 'rgba(0, 0, 0, 0)',
      tension: 0.3,
      fill: false,
      hidden: false
    }));
    new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: months,
        datasets: datasets
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 2,
        plugins: {
          title: { display: true, text: "Truck Expense Breakdown" },
          tooltip: {
            callbacks: {
              label: context => context.dataset.label + ": " + context.parsed.y.toFixed(2)
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
            title: { display: true, text: "Amount" }
          }
        },
        onClick: function(evt, activeElements) {
          if (activeElements.length > 0) {
            const element = activeElements[0];
            const datasetIndex = element.datasetIndex;
            this.data.datasets[datasetIndex].hidden = !this.data.datasets[datasetIndex].hidden;
            this.update();
          }
        }
      }
    });
  }

  // Close modal when clicking close button or outside modal
  closeButton.addEventListener("click", () => { modal.style.display = "none"; });
  window.addEventListener("click", event => { if (event.target === modal) modal.style.display = "none"; });

  // Helper function to generate distinct HSL colors
  function getHighContrastColor(index, total) {
    let hue = Math.round((360 / total) * index);
    return `hsl(${hue}, 100%, 40%)`;
  }
});
