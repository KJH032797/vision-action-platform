const form = document.querySelector("#analysis-upload");
if (form) {
    const camera = document.querySelector("#camera-field");
    const filePanel = document.querySelector("#video-field");
    const image = document.querySelector("#preview-image");
    const placeholder = document.querySelector("#preview-placeholder");
    const power = document.querySelector("#camera-power");
    const message = document.querySelector("#preview-status");
    const submit = document.querySelector("#analysis-start");
    const result = document.querySelector("#camera-analysis");
    const resultStatus = document.querySelector("#camera-analysis-status");
    const findings = document.querySelector("#camera-findings");
    const detail = document.querySelector("#camera-result-link");
    const csrf = form.elements.csrfmiddlewaretoken.value;
    const storageKey = "vision-action-camera";
    let urls = null;
    let job = null;
    let state = "";
    let recording = false;
    let requesting = false;
    let watchingJob = false;
    let imageUrl = "";
    let closeAfterRecording = false;

    const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
    const cameraSelected = () => form.elements.input_type.value === "IP_WEBCAM";
    function remember() {
        try {
            if (urls || job) sessionStorage.setItem(storageKey, JSON.stringify({urls, job}));
            else sessionStorage.removeItem(storageKey);
        } catch { /* Storage may be disabled. */ }
    }

    async function request(url, options = {}) {
        const response = await fetch(url, {
            cache: "no-store", signal: AbortSignal.timeout(5000), ...options,
        });
        if (response.redirected) throw new Error("로그인이 필요합니다.");
        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            throw new Error(body.message || "요청을 처리하지 못했습니다.");
        }
        return response;
    }
    const post = (url, body) => request(url, {method:"POST", body, headers:{"X-CSRFToken":csrf}});

    function controls() {
        const live = cameraSelected();
        filePanel.hidden = live;
        camera.hidden = !live;
        form.elements.video.disabled = live;
        form.elements.video.required = !live;
        power.textContent = urls ? "카메라 끄기" : "카메라 켜기";
        power.disabled = requesting || recording || state === "STOPPING";
        submit.disabled = live && (state !== "LIVE" || recording || requesting || watchingJob);
        form.querySelectorAll('input[name="input_type"]').forEach((radio) => {
            radio.disabled = recording || requesting;
        });
    }

    function clearCamera() {
        urls = null;
        state = "";
        recording = false;
        closeAfterRecording = false;
        if (imageUrl) URL.revokeObjectURL(imageUrl);
        imageUrl = "";
        image.removeAttribute("src");
        image.hidden = true;
        placeholder.hidden = false;
        remember();
        controls();
    }

    async function watchCamera(current) {
        watchFrames(current);
        let heartbeatAt = 0;
        let statusAt = 0;
        let failures = 0;
        while (urls === current) {
            try {
                const now = performance.now();
                if (now >= heartbeatAt && state !== "STOPPING") {
                    try { await post(current.heartbeat); } catch { /* Status handles expiry. */ }
                    heartbeatAt = now + 3000;
                }
                if (now >= statusAt) {
                    const update = await (await request(current.status)).json();
                    if (urls !== current) return;
                    state = update.state;
                    recording = update.recording;
                    if (state === "CLOSED" || state === "FAILED") {
                        clearCamera();
                        message.textContent = update.message || "카메라가 꺼졌습니다.";
                        return;
                    }
                    message.textContent = {
                        REQUESTED:"카메라 연결 대기 중…", CONNECTING:"카메라 연결 중…",
                        LIVE:recording ? "영상 수집 중 · 미리보기를 계속 표시합니다." : "카메라 켜짐",
                        STOPPING:"카메라 연결 종료 중…",
                    }[state] || "";
                    controls();
                    statusAt = now + 750;
                    if (closeAfterRecording && !recording) await turnOff();
                }
                failures = 0;
            } catch (error) {
                if (urls !== current) return;
                message.textContent = error.message;
                if (++failures >= 3) { clearCamera(); return; }
            }
            await sleep(250);
        }
    }

    async function watchFrames(current) {
        const interval = 80; // 12.5 browser polls/sec, independent of video encoding.
        let version = "";
        while (urls === current) {
            if (document.hidden || state !== "LIVE" || !cameraSelected()) {
                await sleep(250);
                continue;
            }

            const started = performance.now();
            try {
                // One JPEG request at a time. A 304 keeps the current image.
                const headers = version ? {"If-None-Match": version} : {};
                const response = await fetch(current.frame, {
                    cache: "no-store", headers, signal: AbortSignal.timeout(1500),
                });
                if (response.status === 200 && !response.redirected) {
                    const blob = await response.blob();
                    if (urls === current && !document.hidden && state === "LIVE" && cameraSelected()) {
                        const next = URL.createObjectURL(blob);
                        image.src = next;
                        image.hidden = false;
                        placeholder.hidden = true;
                        if (imageUrl) URL.revokeObjectURL(imageUrl);
                        imageUrl = next;
                        version = response.headers.get("ETag") || "";
                    }
                } else if (response.redirected || response.status >= 400) {
                    await sleep(500);
                }
            } catch {
                // The control loop reports session and connection errors.
                await sleep(300);
            }
            await sleep(Math.max(0, interval - (performance.now() - started)));
        }
    }

    async function turnOff() {
        if (!urls || requesting) return;
        requesting = true;
        controls();
        try {
            await post(urls.close);
            state = "STOPPING";
        } catch (error) {
            message.textContent = error.message;
        } finally {
            requesting = false;
            controls();
        }
    }

    power.addEventListener("click", async () => {
        if (urls) { await turnOff(); return; }
        requesting = true;
        controls();
        try {
            const data = await (await post(power.dataset.url)).json();
            urls = data.urls;
            state = "REQUESTED";
            remember();
            watchCamera(urls);
        } catch (error) {
            message.textContent = error.message;
        } finally {
            requesting = false;
            controls();
        }
    });

    function renderResult(data) {
        const terminal = data.status === "SUCCESS" || data.status === "FAILURE";
        const phases = {CAPTURING:"영상 수집 중", ANALYZING:"AI 분석 중"};
        resultStatus.textContent = data.status === "SUCCESS" ? "완료" :
            data.status === "FAILURE" ? "실패" : data.status === "PENDING" ?
            (data.phase === "ANALYZING" ? "AI 분석 대기" : "영상 수집 대기") :
            phases[data.phase] || "처리 중";
        if (!terminal) return false;
        const lines = [];
        if (data.error_message) lines.push(data.error_message);
        if (data.result_status === "NO_PERSON") lines.push("영상에서 사람이 검출되지 않았습니다.");
        if (data.result_status === "NO_TRACKS") lines.push("사람에게 추적 번호를 부여하지 못했습니다.");
        for (const item of data.predictions) {
            const confidence = item.status === "INSUFFICIENT_DURATION" ? "관측 구간 부족 (최소 4초)" :
                item.confidence === null ? "유효 자세 부족" : "신뢰도 " + item.confidence.toFixed(3);
            lines.push("Track " + item.track_id + " · " + item.action_label + " · " + confidence);
        }
        findings.replaceChildren(...lines.map((line) => {
            const li = document.createElement("li");
            li.textContent = line;
            return li;
        }));
        return true;
    }

    async function watchJob(current) {
        watchingJob = true;
        result.hidden = false;
        detail.href = current.detail;
        controls();
        let failures = 0;
        while (job === current) {
            try {
                const data = await (await request(current.url, {headers:{Accept:"application/json"}})).json();
                if (renderResult(data)) break;
                failures = 0;
            } catch (error) {
                resultStatus.textContent = error.message;
                if (++failures >= 4) break;
            }
            await sleep(500);
        }
        watchingJob = false;
        controls();
    }

    form.addEventListener("submit", async (event) => {
        if (!cameraSelected()) return;
        event.preventDefault();
        if (!urls || submit.disabled) return;
        const payload = new URLSearchParams({title:form.elements.title.value, memo:form.elements.memo.value});
        // Lock the UI before the network request so a fast second click cannot stop capture.
        requesting = true;
        controls();
        try {
            job = await (await post(urls.record, payload)).json();
            recording = true;
            findings.replaceChildren();
            resultStatus.textContent = "영상 수집 대기";
            remember();
            watchJob(job);
        } catch (error) {
            message.textContent = error.message;
        } finally {
            requesting = false;
            controls();
        }
    });

    form.addEventListener("change", (event) => {
        if (event.target.name !== "input_type") return;
        if (!cameraSelected() && urls) {
            closeAfterRecording = true;
            if (!recording) turnOff();
        }
        controls();
    });

    try {
        const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
        if (saved) {
            urls = saved.urls;
            job = saved.job;
            if (urls) {
                form.querySelector('input[value="IP_WEBCAM"]').checked = true;
                watchCamera(urls);
            }
            if (job) watchJob(job);
        }
    } catch { /* A malformed or unavailable session cache is ignored. */ }
    controls();
}
