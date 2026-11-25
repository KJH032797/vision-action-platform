const comparison = document.querySelector("[data-video-comparison]");

if (comparison) {
  const original = comparison.querySelector("[data-original]");
  const overlay = comparison.querySelector("[data-overlay]");
  const message = comparison.querySelector("[data-video-message]");
  const stage = comparison.querySelector("[data-stage]");
  const divider = comparison.querySelector("[data-divider]");
  const controls = comparison.querySelector("[data-controls]");
  let comparing = Boolean(overlay);
  let playing = false;
  let animation = 0;
  let stopFrameWatch = () => {};

  function fallback(text, originalFailed = false) {
    comparing = false;
    playing = false;
    cancelAnimationFrame(animation);
    stopFrameWatch();
    original.pause();
    message.textContent = text;
    message.hidden = false;
    stage.hidden = originalFailed;
    original.controls = !originalFailed;
    original.muted = false;
    if (overlay) {
      overlay.pause();
      overlay.hidden = divider.hidden = controls.hidden = true;
    }
  }

  function originalError() {
    const source = original.dataset.sourceUrl;
    if (source) {
      delete original.dataset.sourceUrl;
      fallback("비교용 영상에 접근할 수 없어 저장된 원본을 표시합니다.");
      original.src = source;
    } else {
      fallback("이 브라우저에서 원본 코덱을 재생할 수 없거나 영상 읽기에 실패했습니다.", true);
    }
  }
  original.addEventListener("error", originalError);
  if (original.error) originalError();

  if (comparing && typeof original.requestVideoFrameCallback !== "function") {
    fallback("이 브라우저에서는 표시 프레임의 일치를 확인할 수 없어 원본만 표시합니다.");
  }

  if (comparing) {
    const wipe = comparison.querySelector("[data-wipe]");
    const play = comparison.querySelector("[data-play]");
    const timeline = comparison.querySelector("[data-timeline]");
    const time = comparison.querySelector("[data-time]");
    const videos = [original, overlay];
    // The previews share timestamps. A microsecond covers representation
    // differences without treating adjacent frames as interchangeable.
    const sameTimestamp = (a, b) => Math.abs(a - b) <= .000001;
    const displayed = new Map();
    const frameRequests = new Map();
    let alignmentCheck = 0;
    let mismatchSince = null;
    let nextCorrection = 0;

    function watchFrame(video) {
      frameRequests.set(video, video.requestVideoFrameCallback((_, frame) => {
        if (!comparing) return;
        displayed.set(video, frame.mediaTime);
        // Update before this paint. If both decoders present in the same
        // tick, the second callback restores the overlay before it is drawn.
        showAlignedFrame();
        watchFrame(video);
      }));
    }

    function queueAlignmentCheck() {
      if (!comparing || alignmentCheck) return;
      alignmentCheck = requestAnimationFrame(() => {
        alignmentCheck = 0;
        showAlignedFrame();
      });
    }

    stopFrameWatch = () => {
      cancelAnimationFrame(alignmentCheck);
      for (const [video, id] of frameRequests) video.cancelVideoFrameCallback(id);
    };

    function wipeAt(value) {
      stage.style.setProperty("--wipe", value + "%");
      wipe.setAttribute("aria-valuetext", "왼쪽 원본 " + value + "%");
    }
    wipe.addEventListener("input", () => wipeAt(wipe.value));

    function readTime() {
      const seconds = Math.floor(original.currentTime);
      time.textContent = Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
      if (document.activeElement !== timeline || !original.seeking) timeline.value = original.currentTime;
    }

    function seekTo(seconds) {
      stage.classList.add("comparison-seeking");
      mismatchSince = null;
      for (const video of videos) {
        if (Math.abs(video.currentTime - seconds) > .001) {
          displayed.delete(video);
          video.currentTime = seconds;
        }
      }
      queueAlignmentCheck();
      readTime();
    }

    function showAlignedFrame() {
      const framesReady = videos.every(video => !video.seeking && video.readyState >= 2
        && displayed.has(video));
      const aligned = framesReady && sameTimestamp(displayed.get(original), displayed.get(overlay));
      stage.classList.toggle("comparison-seeking", !aligned);
      if (!playing || aligned || !framesReady) mismatchSince = null;
      else mismatchSince ??= performance.now();
    }

    function stop() {
      playing = false;
      cancelAnimationFrame(animation);
      videos.forEach(video => video.pause());
      const originalFrame = displayed.get(original);
      if (originalFrame !== undefined && !original.seeking && !overlay.seeking
          && !sameTimestamp(originalFrame, displayed.get(overlay))) {
        // Freeze the comparison on the original's last presented frame.
        overlay.currentTime = originalFrame;
      }
      play.textContent = "재생";
    }

    function follow(now) {
      if (!playing || !comparing) return;
      // Allow the decoders to cross a frame boundary independently. Only seek
      // for a sustained mismatch, and keep the original playing during recovery.
      if (mismatchSince !== null && now - mismatchSince >= 120 && now >= nextCorrection
          && !original.seeking && !overlay.seeking) {
        displayed.delete(overlay);
        overlay.currentTime = original.currentTime;
        nextCorrection = now + 400;
        mismatchSince = null;
      }
      animation = requestAnimationFrame(follow);
    }

    async function start() {
      if (original.ended) seekTo(0);
      playing = true;
      play.textContent = "일시 정지";
      try {
        await Promise.all(videos.map(video => video.play()));
      } catch {
        // An intentional pause/seek can interrupt a pending play() request.
        if (playing && videos.some(video => video.error)) {
          if (original.error) originalError();
          else fallback("추적 영상을 재생할 수 없어 원본만 표시합니다.");
        } else if (playing) {
          stop();
          message.textContent = "재생이 중단됐습니다. 재생 버튼으로 다시 시도할 수 있습니다.";
          message.hidden = false;
        }
        return;
      }
      cancelAnimationFrame(animation);
      animation = requestAnimationFrame(follow);
    }

    function ready() {
      if (!comparing || videos.some(video => video.readyState < 1)) return;
      if (Math.abs(original.duration - overlay.duration) > .05 || !Number.isFinite(original.duration)) {
        fallback("두 영상의 길이가 달라 원본만 표시합니다.");
        return;
      }
      original.controls = false;
      timeline.max = original.duration;
      timeline.disabled = false;
      showAlignedFrame();
      overlay.hidden = divider.hidden = controls.hidden = false;
      wipeAt(wipe.value);
      readTime();
    }

    const overlayError = () => {
      if (comparing) fallback("추적 영상을 재생할 수 없어 원본만 표시합니다.");
    };
    overlay.addEventListener("error", overlayError);
    original.controls = false;
    original.muted = true;
    original.preload = "auto";
    play.addEventListener("click", () => playing ? stop() : start());
    timeline.addEventListener("input", () => seekTo(Number(timeline.value)));
    for (const video of videos) {
      video.addEventListener("loadedmetadata", ready);
      video.addEventListener("seeking", queueAlignmentCheck);
      video.addEventListener("seeked", queueAlignmentCheck);
      video.addEventListener("loadeddata", queueAlignmentCheck);
      watchFrame(video);
    }
    original.addEventListener("ended", stop);
    original.addEventListener("timeupdate", readTime);
    if (overlay.error) overlayError();
    else ready();
  }
}
