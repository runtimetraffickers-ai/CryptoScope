// Show initial ETL progress and refresh any charts that failed before data existed.
(function () {
    const banner = document.getElementById("etl-init-status");
    if (!banner) return;

    let rebuilding = false;
    async function checkETL() {
        try {
            const response = await fetch("/api/etl/status", { cache: "no-store" });
            if (!response.ok) return;
            const state = await response.json();

            if (state.status === "running" || state.status === "waiting") {
                rebuilding = true;
                banner.hidden = false;
                banner.textContent = "Historical database is being rebuilt automatically. " +
                    "Charts and analysis will appear when the download finishes.";
            } else if (state.status === "failed") {
                rebuilding = true;
                banner.hidden = false;
                banner.textContent = "Historical data download failed. " +
                    "Check the server logs; the dashboard will retry automatically.";
            } else if (state.status === "ready") {
                banner.hidden = true;
                if (rebuilding) {
                    window.location.reload();
                }
            } else {
                banner.hidden = true;
            }
        } catch (error) {
            console.warn("ETL status unavailable:", error);
        }
    }

    checkETL();
    setInterval(checkETL, 10000);
})();
