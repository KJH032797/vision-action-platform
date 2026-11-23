const statusPanel = document.querySelector("[data-status-url]");

if (statusPanel) {
    const refreshMessage = document.querySelector("#analysis-refresh");
    const statusText = document.querySelector("#analysis-status");
    const labels = { PENDING: "대기", STARTED: "처리 중" };

    async function poll() {
        try {
            const response = await fetch(statusPanel.dataset.statusUrl, {
                headers: { Accept: "application/json" },
                cache: "no-store",
            });

            if ([401, 403, 404].includes(response.status)) {
                refreshMessage.textContent = "기록을 조회할 수 없습니다. 로그인 상태를 확인하거나 목록에서 다시 열어 주세요.";
                return;
            }
            if (!response.ok) {
                throw new Error("Status request failed");
            }

            const job = await response.json();
            if (job.status === "SUCCESS" || job.status === "FAILURE") {
                window.location.reload();
                return;
            }
            statusText.textContent = labels[job.status] ?? job.status;
            refreshMessage.textContent = "상태를 자동으로 확인하고 있습니다.";
        } catch {
            refreshMessage.textContent = "현재 상태를 읽지 못했습니다. 잠시 후 다시 확인합니다.";
        }
        window.setTimeout(poll, 1500);
    }

    window.setTimeout(poll, 500);
}