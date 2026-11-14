(() => {
  if (document.getElementById("cs2-local-subtitles")) return;
  const host = document.createElement("div");
  host.id = "cs2-local-subtitles";
  host.style.cssText = "position:absolute;inset:0;z-index:2147483646;pointer-events:none";
  const shadow = host.attachShadow({ mode: "closed" });
  shadow.innerHTML = `<style>
    .captions{position:absolute;left:50%;transform:translateX(-50%);bottom:var(--caption-bottom,22%);
      width:var(--caption-width,80%);max-width:calc(100% - 16px);text-align:center;
      color:rgba(255,255,255,var(--text-alpha,1));font:600 var(--font-size,24px)/1.4 'Microsoft YaHei',sans-serif;
      text-shadow:0 1px 2px rgba(0,0,0,var(--text-alpha,1))}
    .line{display:table;margin:4px auto;background:rgba(0,0,0,var(--background-alpha,1));padding:3px 10px;border-radius:3px;
      max-width:100%;box-sizing:border-box;overflow-wrap:anywhere}.english{font-size:.72em;font-weight:400;color:inherit}
    .captions[data-align=left] .line{margin-left:0;margin-right:auto;text-align:left}
    .captions[data-align=right] .line{margin-left:auto;margin-right:0;text-align:right}
    .line:empty,.hide-english .english{display:none}
  </style><div class="captions" aria-live="off"><div class="line english"></div><div class="line current"></div></div>`;
  const english = shadow.querySelector(".english");
  const current = shadow.querySelector(".current");
  const captions = shadow.querySelector(".captions");
  CS2SubtitleStyle.apply(captions, CS2SubtitleStyle.defaults);
  chrome.storage.local.get("subtitleStyle").then(saved => CS2SubtitleStyle.apply(captions, saved.subtitleStyle));
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.subtitleStyle) CS2SubtitleStyle.apply(captions, changes.subtitleStyle.newValue);
  });
  const player = document.getElementById("movie_player");
  if (!player) return;
  player.append(host);
  const video = player.querySelector("video");
  let seq = 0, epoch = 0, clearTimer, utterance = null, fade;
  function clear() {
    clearTimeout(clearTimer); fade?.cancel(); utterance = null;
    current.textContent = ""; english.textContent = "";
  }
  let lastMedia = JSON.stringify(CS2PageContext.read());
  function reportMedia() {
    const media = CS2PageContext.read();
    const state = JSON.stringify(media);
    if (state === lastMedia) return;
    lastMedia = state;
    clear();
    chrome.runtime.sendMessage({ target: "service", type: "media-state", ...media }).catch(() => {});
  }
  for (const event of ["pause", "playing", "seeking", "seeked", "loadedmetadata"]) video?.addEventListener(event, reportMedia);
  setInterval(reportMedia, 1000);
  chrome.runtime.onMessage.addListener(message => {
    if (message.type === "capture-status" && !message.running) {
      clear(); seq = 0; epoch = 0;
    }
    if (message.type === "clear") { clear(); epoch = message.epoch; }
    if (message.type !== "caption" || message.seq <= seq || message.epoch !== epoch || video?.paused || video?.seeking) return;
    seq = message.seq;
    const en = message.en || message.text;
    if (english.textContent !== en || current.textContent !== message.zh) {
      english.textContent = en;
      current.textContent = message.zh;
      if (utterance !== message.utterance && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
        fade?.cancel();
        fade = captions.animate([{ opacity: .65 }, { opacity: 1 }], { duration: 120, easing: "ease-out" });
      }
    }
    utterance = message.utterance;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (seq !== message.seq || epoch !== message.epoch || current.textContent !== message.zh) return;
      chrome.runtime.sendMessage({ target: "service", type: "displayed", seq,
        displayed_ms: Date.now(), source_progress_ms: message.source_progress_ms,
        server_sent_ms: message.server_sent_ms }).catch(() => {});
    }));
    clearTimeout(clearTimer);
    clearTimer = setTimeout(clear, 6500);
  });
})();
