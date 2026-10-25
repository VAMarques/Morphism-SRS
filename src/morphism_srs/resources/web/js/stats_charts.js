(function () {
    "use strict";

    if (window.Chart && window.Chart.defaults) {
        window.Chart.defaults.animation = false;
    }

    var forecastChart = null;
    var ratingsChart = null;
    var decayChart = null;

    function cssVar(name, fallback) {
        var val = getComputedStyle(document.documentElement).getPropertyValue(name);
        return (val && val.trim()) ? val.trim() : fallback;
    }

    window.MorphismCharts = {
        renderHeatmap: function (dailyMap) {
            var grid = document.getElementById("hm-grid");
            var summary = document.getElementById("hm-summary");
            if (!grid) return;
            grid.innerHTML = "";

            var today = new Date();
            var totalReviews = 0;
            var activeDays = 0;

            for (var i = 364; i >= 0; i--) {
                var d = new Date(today);
                d.setDate(today.getDate() - i);
                var iso = d.toISOString().slice(0, 10);
                var cnt = (dailyMap && dailyMap[iso]) ? dailyMap[iso] : 0;
                totalReviews += cnt;
                if (cnt > 0) activeDays++;

                var cell = document.createElement("div");
                var lv = "";
                if (cnt >= 40) lv = " hm-lv4";
                else if (cnt >= 20) lv = " hm-lv3";
                else if (cnt >= 5) lv = " hm-lv2";
                else if (cnt >= 1) lv = " hm-lv1";
                cell.className = "hm-cell" + lv;
                cell.title = iso + ": " + cnt + " reviews";
                grid.appendChild(cell);
            }

            if (summary) {
                summary.textContent = totalReviews + " total reviews across " + activeDays + " active days in the past year";
            }
        },

        renderBarPlots: function (forecastLabels, forecastValues, ratingCounts) {
            if (!window.Chart) return;
            var textPrimary = cssVar("--text-primary", "#cdd6f4");
            var accent = cssVar("--accent-primary", "#89b4fa");
            var danger = cssVar("--semantic-danger", "#f38ba8");
            var warning = cssVar("--semantic-warning", "#f9e2af");
            var success = cssVar("--semantic-success", "#a6e3a1");
            var info = cssVar("--semantic-info", "#89dceb");

            var fCanvas = document.getElementById("forecast-canvas");
            if (fCanvas) {
                if (forecastChart) forecastChart.destroy();
                forecastChart = new window.Chart(fCanvas, {
                    type: "bar",
                    data: {
                        labels: forecastLabels || [],
                        datasets: [{
                            label: "Upcoming Due Cards",
                            data: forecastValues || [],
                            backgroundColor: accent,
                            borderRadius: 4
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { labels: { color: textPrimary } } },
                        scales: {
                            x: { ticks: { color: textPrimary } },
                            y: { beginAtZero: true, ticks: { color: textPrimary } }
                        }
                    }
                });
            }

            var rCanvas = document.getElementById("ratings-canvas");
            if (rCanvas) {
                if (ratingsChart) ratingsChart.destroy();
                ratingsChart = new window.Chart(rCanvas, {
                    type: "bar",
                    data: {
                        labels: ["Again (1)", "Hard (2)", "Good (3)", "Easy (4)"],
                        datasets: [{
                            label: "Rating Distribution",
                            data: ratingCounts || [0, 0, 0, 0],
                            backgroundColor: [danger, warning, success, info],
                            borderRadius: 4
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { labels: { color: textPrimary } } },
                        scales: {
                            x: { ticks: { color: textPrimary } },
                            y: { beginAtZero: true, ticks: { color: textPrimary } }
                        }
                    }
                });
            }
        },

        renderDecayCurves: function (daysLabels, rMinCurve, rAvgCurve, pJointCurve) {
            if (!window.Chart) return;
            var dCanvas = document.getElementById("decay-canvas");
            if (!dCanvas) return;
            if (decayChart) decayChart.destroy();

            var textPrimary = cssVar("--text-primary", "#cdd6f4");
            var danger = cssVar("--semantic-danger", "#f38ba8");
            var accent = cssVar("--accent-primary", "#89b4fa");
            var secondary = cssVar("--accent-secondary", "#cba6f7");

            decayChart = new window.Chart(dCanvas, {
                type: "line",
                data: {
                    labels: daysLabels || [],
                    datasets: [
                        {
                            label: "Bottleneck R_min(t)",
                            data: rMinCurve || [],
                            borderColor: danger,
                            tension: 0.25,
                            fill: false
                        },
                        {
                            label: "Mean R_avg(t)",
                            data: rAvgCurve || [],
                            borderColor: accent,
                            tension: 0.25,
                            fill: false
                        },
                        {
                            label: "Joint Retrieval P(∩ A_i)",
                            data: pJointCurve || [],
                            borderColor: secondary,
                            borderDash: [5, 5],
                            tension: 0.25,
                            fill: false
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { labels: { color: textPrimary } } },
                    scales: {
                        x: { title: { display: true, text: "Days Ahead", color: textPrimary }, ticks: { color: textPrimary } },
                        y: { min: 0, max: 100, title: { display: true, text: "Retrievability (%)", color: textPrimary }, ticks: { color: textPrimary } }
                    }
                }
            });
        }
    };
})();
