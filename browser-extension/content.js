(function startSubtitleOverlay() {
  "use strict";

  const core = globalThis.Yt2NotionSubtitleCore;
  const HOST_ID = "yt2notion-subtitle-host";
  let subtitlePackage = null;
  let settings = { enabled: true, fontScale: 1, bottomOffset: 9 };
  let activeCueId = null;
  let currentVideoId;
  let host = null;
  let sourceLine = null;
  let translatedLine = null;

  function createOverlay() {
    host = document.getElementById(HOST_ID);
    if (host) return;
    host = document.createElement("div");
    host.id = HOST_ID;
    const shadow = host.attachShadow({ mode: "open" });
    shadow.innerHTML = `
      <style>
        :host { all: initial; position: fixed; inset: 0; z-index: 2147483646; pointer-events: none; }
        .wrap { position: absolute; left: 50%; bottom: var(--subtitle-bottom, 9%); width: min(92vw, 1100px);
          transform: translateX(-50%); text-align: center; opacity: 0; transition: opacity 90ms linear; }
        .wrap.visible { opacity: 1; }
        .line { display: table; max-width: 100%; margin: 4px auto; padding: .18em .5em; border-radius: .28em;
          color: #fff; background: rgba(6, 9, 15, .78); box-decoration-break: clone; -webkit-box-decoration-break: clone;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: calc(24px * var(--subtitle-scale, 1));
          font-weight: 650; line-height: 1.32; letter-spacing: .005em; text-shadow: 0 1px 3px #000; }
        .translated { color: #ffe08a; font-weight: 700; }
        @media (max-width: 720px) { .line { font-size: calc(18px * var(--subtitle-scale, 1)); } }
      </style>
      <div class="wrap" aria-live="off">
        <div class="line source"></div>
        <div class="line translated"></div>
      </div>`;
    sourceLine = shadow.querySelector(".source");
    translatedLine = shadow.querySelector(".translated");
    document.documentElement.appendChild(host);
    applySettings();
  }

  function applySettings() {
    if (!host) return;
    host.style.setProperty("--subtitle-scale", String(settings.fontScale || 1));
    host.style.setProperty("--subtitle-bottom", `${settings.bottomOffset || 9}%`);
  }

  function placeOverlay() {
    createOverlay();
    const parent = document.fullscreenElement || document.documentElement;
    if (host.parentNode !== parent) parent.appendChild(host);
  }

  function hide() {
    if (!host || !host.shadowRoot) return;
    host.shadowRoot.querySelector(".wrap").classList.remove("visible");
    activeCueId = null;
  }

  function render() {
    const video = document.querySelector("video.html5-main-video, video");
    if (!video || !subtitlePackage || !settings.enabled) {
      hide();
      return;
    }
    const cue = core.findCue(subtitlePackage.cues, video.currentTime * 1000);
    if (!cue) {
      hide();
      return;
    }
    if (cue.id !== activeCueId) {
      sourceLine.textContent = cue.source_text;
      translatedLine.textContent = cue.translated_text;
      activeCueId = cue.id;
    }
    host.shadowRoot.querySelector(".wrap").classList.add("visible");
  }

  async function loadForCurrentVideo() {
    const nextVideoId = core.videoIdFromUrl(location.href);
    if (nextVideoId === currentVideoId) return;
    currentVideoId = nextVideoId;
    const stored = await chrome.storage.local.get(["subtitlePackages", "subtitleSettings"]);
    if (
      nextVideoId !== currentVideoId ||
      nextVideoId !== core.videoIdFromUrl(location.href)
    ) return;
    settings = { ...settings, ...(stored.subtitleSettings || {}) };
    applySettings();
    subtitlePackage = nextVideoId ? (stored.subtitlePackages || {})[nextVideoId] || null : null;
    hide();
  }

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes.subtitleSettings) {
      settings = { ...settings, ...(changes.subtitleSettings.newValue || {}) };
      applySettings();
    }
    if (changes.subtitlePackages) {
      subtitlePackage = currentVideoId
        ? (changes.subtitlePackages.newValue || {})[currentVideoId] || null
        : null;
      hide();
    }
  });

  document.addEventListener("fullscreenchange", placeOverlay);
  document.addEventListener("yt-navigate-finish", loadForCurrentVideo);
  createOverlay();
  loadForCurrentVideo();
  setInterval(() => {
    const nextVideoId = core.videoIdFromUrl(location.href);
    if (nextVideoId !== currentVideoId) loadForCurrentVideo();
    placeOverlay();
    render();
  }, 100);
})();
