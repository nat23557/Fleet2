document.addEventListener("DOMContentLoaded", function() {
  // Modal Elements (ensure the modal is hidden by default via inline style or CSS)
  const modal = document.getElementById("chartModal");
  const modalContent = document.getElementById("modalChartContainer");
  const closeButton = document.querySelector(".close-button");

  // Debug: Confirm elements are found
  console.log("Modal element:", modal);
  console.log("Close button:", closeButton);

  // Retrieve JSON data with try/catch to catch parsing errors
  let months, truckDataList, overallTotals, rawExpenseData;
  try {
    months = JSON.parse(document.getElementById("months-data").textContent);
    truckDataList = JSON.parse(document.getElementById("truck-chart-data").textContent);
    overallTotals = JSON.parse(document.getElementById("overall-totals-data").textContent);
    rawExpenseData = JSON.parse(document.getElementById("raw-expense-data").textContent);
  } catch (e) {
    console.error("Error parsing JSON data:", e);
    return; // Stop execution if JSON data is invalid
  }
  
  // Debug: Log parsed data
  console.log("Months data:", months);
  console.log("Truck data list:", truckDataList);
  console.log("Overall totals:", overallTotals);
  console.log("Raw expense data:", rawExpenseData);
  
  // Determine if mobile based on viewport width
  const isMobile = window.innerWidth < 768;
  
  // Attach event listeners to each view-chart button
  const chartButtons = document.querySelectorAll(".view-chart-button");
  console.log("Found chart buttons:", chartButtons.length);
  chartButtons.forEach(button => {
    button.addEventListener("click", function(e) {
      e.preventDefault();
      console.log("Chart button clicked. Data-chart:", this.dataset.chart);
      openChartModal(this.dataset.chart);
    });
  });
  
  // Open modal and initialize chart/UI based on chartType
  function openChartModal(chartType) {
    modalContent.innerHTML = "";
    console.log("Opening modal for chart type:", chartType);
    // Update condition values to match template attributes: "overall", "expense", and "perTruck"
    if (chartType === "overall") {
      renderOverallPerformanceChart();
    } else if (chartType === "expense") {
      renderOverallExpenseChart();
    } else if (chartType === "perTruck") {
      renderPerTruckSelector();
    }
    modal.style.display = "block";
  }
  
  // Render the overall monthly performance chart as a bar chart
  function renderOverallPerformanceChart() {
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = isMobile ? "400px" : "600px";
    modalContent.appendChild(canvas);
    new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: ["Revenue", "Expense", "Profit"],
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
        maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: "Overall Monthly Financials" },
          tooltip: { 
            callbacks: { label: context => context.dataset.label + ": " + context.parsed.y.toFixed(2) } 
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
          y: { beginAtZero: true, title: { display: true, text: "Amount" } }
        },
        onClick: function(evt, activeElements) {
          if (activeElements.length > 0) {
            const datasetIndex = activeElements[0].datasetIndex;
            this.data.datasets[datasetIndex].hidden = !this.data.datasets[datasetIndex].hidden;
            this.update();
          }
        }
      }
    });
  }
  
  // Render the overall expense chart with style similar to per-truck expense chart
  function renderOverallExpenseChart() {
    modalContent.innerHTML = "";
    const header = document.createElement("div");
    header.className = "truck-chart-header";
    header.innerHTML = `<h3>Overall Expense by Category</h3>`;
    modalContent.appendChild(header);
  
    const container = document.createElement("div");
    container.className = "truck-expense-chart-container";
    container.style.maxHeight = isMobile ? "400px" : "500px";
    container.style.overflowY = "auto";
    modalContent.appendChild(container);
  
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = isMobile ? "350px" : "450px";
    container.appendChild(canvas);
  
    const categoryMap = {};
    rawExpenseData.forEach(item => {
      categoryMap[item.category] = (categoryMap[item.category] || 0) + parseFloat(item.expense);
    });
    const categories = Object.keys(categoryMap);
    const expenseValues = categories.map(cat => categoryMap[cat]);
  
    new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: categories,
        datasets: [{
          label: "Expense",
          data: expenseValues,
          backgroundColor: categories.map((_, index) => getHighContrastColor(index, categories.length)),
          borderColor: categories.map((_, index) => getHighContrastColor(index, categories.length)),
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: "Overall Expense by Category" },
          tooltip: {
            callbacks: { label: context => context.dataset.label + ": " + context.parsed.y.toFixed(2) }
          },
          legend: {
            onClick: function(e, legendItem, legend) {
              const ci = legend.chart;
              ci.data.datasets[0].hidden = !ci.data.datasets[0].hidden;
              ci.update();
            }
          }
        },
        scales: {
          y: { beginAtZero: true, title: { display: true, text: "Expense Amount" } },
          x: { title: { display: true, text: "Expense Category" } }
        }
      }
    });
  }
  
  // Render the per-truck selector UI
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
        displayTruckCharts(truck);
      });
      grid.appendChild(btn);
    });
    card.appendChild(grid);
    modalContent.appendChild(card);
  }
  
  // Display truck-specific chart options with truck plate shown on top
  function displayTruckCharts(truck) {
    modalContent.innerHTML = "";
    const header = document.createElement("div");
    header.className = "truck-selection-header";
    header.innerHTML = `<h3>Truck: ${truck.truck_plate}</h3>`;
    modalContent.appendChild(header);
    const card = document.createElement("div");
    card.className = "truck-chart-selection-card";
    
    const monthlyBtn = document.createElement("button");
    monthlyBtn.className = "cta-button truck-chart-selection-button";
    monthlyBtn.textContent = "Monthly Trends";
    monthlyBtn.addEventListener("click", function() {
      renderTruckMonthlyChart(truck);
    });
    
    const expenseBtn = document.createElement("button");
    expenseBtn.className = "cta-button truck-chart-selection-button";
    expenseBtn.textContent = "Expense Breakdown";
    expenseBtn.addEventListener("click", function() {
      renderTruckExpenseChart(truck);
    });
    
    card.appendChild(monthlyBtn);
    card.appendChild(expenseBtn);
    modalContent.appendChild(card);
  }
  
  // Render a per-truck monthly trends bar chart
  function renderTruckMonthlyChart(truck) {
    modalContent.innerHTML = "";
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = isMobile ? "400px" : "600px";
    modalContent.appendChild(canvas);
  
    const monthlyRevenue = truck.monthly_revenue || [truck.total_revenue || 0];
    const monthlyExpense = truck.monthly_expense || [truck.total_expense || 0];
    const monthlyIncome  = truck.monthly_income  || [truck.income_before_tax || 0];
  
    new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: months,
        datasets: [
          {
            label: "Monthly Revenue",
            data: monthlyRevenue,
            backgroundColor: "rgba(2, 115, 53, 0.7)",
            borderColor: "rgba(2, 115, 53, 1)",
            borderWidth: 1
          },
          {
            label: "Monthly Expense",
            data: monthlyExpense,
            backgroundColor: "rgba(255, 99, 132, 0.7)",
            borderColor: "rgba(255, 99, 132, 1)",
            borderWidth: 1
          },
          {
            label: "Monthly Profit",
            data: monthlyIncome,
            backgroundColor: "rgba(54, 162, 235, 0.7)",
            borderColor: "rgba(54, 162, 235, 1)",
            borderWidth: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: "Truck Monthly Financial Trends" },
          tooltip: {
            callbacks: { label: context => context.dataset.label + ": " + context.parsed.y.toFixed(2) }
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
          y: { beginAtZero: true, title: { display: true, text: "Amount" } }
        }
      }
    });
  }
  
  // Render a per-truck expense chart by category as a bar graph with controlled height
  function renderTruckExpenseChart(truck) {
    modalContent.innerHTML = "";
    const header = document.createElement("div");
    header.className = "truck-chart-header";
    header.innerHTML = `<h3>Truck: ${truck.truck_plate} Expense Breakdown</h3>`;
    modalContent.appendChild(header);
  
    const container = document.createElement("div");
    container.className = "truck-expense-chart-container";
    container.style.maxHeight = isMobile ? "400px" : "500px";
    container.style.overflowY = "auto";
    modalContent.appendChild(container);
  
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = isMobile ? "350px" : "450px";
    container.appendChild(canvas);
  
    const truckExpenses = rawExpenseData.filter(item => item.truck_plate === truck.truck_plate);
    const expenseMap = {};
    truckExpenses.forEach(item => {
      expenseMap[item.category] = (expenseMap[item.category] || 0) + parseFloat(item.expense);
    });
    const categories = Object.keys(expenseMap);
    const expenseValues = categories.map(cat => expenseMap[cat]);
  
    new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: categories,
        datasets: [{
          label: "Expense",
          data: expenseValues,
          backgroundColor: categories.map((_, index) => getHighContrastColor(index, categories.length)),
          borderColor: categories.map((_, index) => getHighContrastColor(index, categories.length)),
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: `Truck ${truck.truck_plate} Expense by Category` },
          tooltip: {
            callbacks: { label: context => context.dataset.label + ": " + context.parsed.y.toFixed(2) }
          },
          legend: {
            onClick: function(e, legendItem, legend) {
              const ci = legend.chart;
              ci.data.datasets[0].hidden = !ci.data.datasets[0].hidden;
              ci.update();
            }
          }
        },
        scales: {
          y: { beginAtZero: true, title: { display: true, text: "Expense Amount" } },
          x: { title: { display: true, text: "Expense Category" } }
        }
      }
    });
  }
  
  // Close modal when clicking the close button or outside the modal
  closeButton.addEventListener("click", () => { modal.style.display = "none"; });
  window.addEventListener("click", event => {
    if (event.target === modal) modal.style.display = "none";
  });
  
  // Helper function to generate high-contrast HSL colors
  function getHighContrastColor(index, total) {
    let hue = Math.round((360 / total) * index);
    return `hsl(${hue}, 100%, 40%)`;
  }
});
