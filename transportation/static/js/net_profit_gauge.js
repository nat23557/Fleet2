// net_profit_gauge.js
function initNetProfitGauge(canvasId, netProfitMargin) {
    // Assuming a gauge library like Canvas Gauges is used.
    // The following example uses a hypothetical DonutGauge constructor.
    var gauge = new DonutGauge({
        renderTo: canvasId,
        width: 300,
        height: 300,
        glow: true,
        units: "%",
        title: "Net Profit Margin",
        value: netProfitMargin,
        minValue: 0,
        maxValue: 100,
        majorTicks: ["0", "20", "40", "60", "80", "100"],
        minorTicks: 2,
        strokeTicks: true,
        highlights: [
            { from: 0, to: 40, color: "rgba(255,0,0,0.75)" },
            { from: 40, to: 70, color: "rgba(255,255,0,0.75)" },
            { from: 70, to: 100, color: "rgba(0,255,0,0.75)" }
        ],
        animation: {
            delay: 10,
            duration: 2000,
            fn: "linear"
        }
    });
    gauge.draw();
}
