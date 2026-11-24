const statusPanel = document.querySelector("[data-status-url]");

if (statusPanel) {
    const refreshMessage = document.querySelector("#analysis-refresh");
    const statusText = document.querySelector("#analysis-status");
    const badge = document.querySelector("#job-header-status .badge");
    const phases = { CONNECTING: "카메라 연결 중", CAPTURING: "영상 수집 중", ANALYZING: "AI 분석 중" };

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
            const label = job.status === "PENDING" ? "대기" : phases[job.phase] || "처리 중";
            if (statusText.textContent.trim() !== label) statusText.textContent = label;
            if (badge && job.status === "STARTED") {
                badge.classList.replace("pending", "started");
                badge.textContent = "처리 중";
            }
            refreshMessage.textContent = "상태를 자동으로 확인하고 있습니다.";
        } catch {
            refreshMessage.textContent = "현재 상태를 읽지 못했습니다. 잠시 후 다시 확인합니다.";
        }
        window.setTimeout(poll, 1500);
    }

    window.setTimeout(poll, 500);
}
