(() => {
  if (document.getElementById("cs2-local-subtitles")) return;
  const host = document.createElement("div");
  host.id = "cs2-local-subtitles";
  host.style.cssText = "position:absolute;inset:0;z-index:2147483646;pointer-events:none;overflow:hidden;container-type:inline-size";
  const shadow = host.attachShadow({ mode: "closed" });
  shadow.innerHTML = `<style>
    .captions{position:absolute;left:50%;transform:translateX(-50%);bottom:var(--caption-bottom,22%);
      display:grid;grid-template-columns:minmax(0,1fr);justify-items:center;
      width:min(var(--caption-width,80%),34em,calc(100% - 16px));text-align:center;
      color:rgba(255,255,255,var(--text-alpha,1));
      font:700 clamp(14px,4.4cqw,var(--font-size,24px))/1.3 'Microsoft YaHei UI','Microsoft YaHei',sans-serif;
      letter-spacing:.02em;line-break:strict;
      text-shadow:0 1px 2px rgba(0,0,0,calc(var(--text-alpha,1)*.9)),0 0 8px rgba(0,0,0,calc(var(--text-alpha,1)*.5))}
    .stack{display:grid;grid-template-columns:minmax(0,1fr);gap:.3em;width:max-content;max-width:100%;
      box-sizing:border-box;padding:.32em .7em .38em;border-radius:.42em;overflow:clip;
      background:rgba(8,10,13,var(--background-alpha,1));
      box-shadow:0 0 0 1px rgba(255,255,255,calc(var(--background-alpha,1)*.07)),0 6px 20px rgba(0,0,0,calc(var(--background-alpha,1)*.35))}
    .cue{min-width:0;overflow-wrap:anywhere}
    .previous{opacity:.55;font-size:.8em}
    .zh{text-wrap:balance}
    .current{text-wrap:pretty}
    .english{font:400 .62em/1.25 'Segoe UI',system-ui,sans-serif;letter-spacing:0;color:rgba(214,220,227,var(--text-alpha,1))}
    .exiting{position:absolute}
    .captions[data-align=left]{justify-items:start;text-align:left}
    .captions[data-align=right]{justify-items:end;text-align:right}
    .stack:has(.live[hidden]),.cue[hidden],.english:empty,.hide-english .english{display:none}
    @container (max-width: 450px) {
      .captions{bottom:min(var(--caption-bottom,22%),max(0px,calc(100% - 10em)))}
      .stack{padding:3px 8px 4px}
      .current,.zh{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
      .current{-webkit-line-clamp:3}
      .english{overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
    }
  </style><div class="captions" aria-live="off" lang="zh-CN">
    <div class="stack">
      <div class="cue previous" hidden><div class="english" lang="en"></div><div class="zh"></div></div>
      <div class="cue live" hidden><div class="english" lang="en"></div><div class="current"></div></div>
    </div>
  </div>`;
  const current = shadow.querySelector(".current");
  const captions = shadow.querySelector(".captions");
  const live = shadow.querySelector(".live");
  const english = shadow.querySelector(".live .english");
  const previous = shadow.querySelector(".previous");
  const previousEnglish = shadow.querySelector(".previous .english");
  const previousChinese = shadow.querySelector(".previous .zh");
  CS2SubtitleStyle.apply(captions, CS2SubtitleStyle.defaults);
  chrome.storage.local.get("subtitleStyle").then(saved => CS2SubtitleStyle.apply(captions, saved.subtitleStyle));
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.subtitleStyle) CS2SubtitleStyle.apply(captions, changes.subtitleStyle.newValue);
  });
  const player = document.getElementById("movie_player");
  if (!player) return;
  player.append(host);
  const video = player.querySelector("video");
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const easeOut = "cubic-bezier(.23,1,.32,1)";
  const graphemes = new Intl.Segmenter("zh", { granularity: "grapheme" });
  const words = new Intl.Segmenter("en", { granularity: "word" });
  let reveals = [];
  let seq = 0, epoch = 0, clearTimer, utterance = null, enter, roll, exit, idleFade;

  function setText(line, text) {
    if (line.textContent !== text) line.textContent = text;
  }

  function finishReveal() {
    for (const animation of reveals) {
      if (animation.playState === "running" || animation.pending) animation.cancel();
    }
    reveals = [];
  }

  function revealText(line, text, segmenter) {
    const old = line.textContent;
    if (old === text) return;
    if (motion.matches) return setText(line, text);
    const parts = value => Array.from(segmenter.segment(value), item => item.segment);
    const before = parts(old);
    const after = parts(text);
    const common = Math.min(before.length, after.length);
    let start = 0, end = 0;
    while (start < common && before[start] === after[start]) start++;
    while (start + end < common && before.at(-end - 1) === after.at(-end - 1)) end++;
    // A final period belongs with the growing tail, even when the draft used it too.
    if (end && after.slice(-end).every(part => /^[\p{P}\s]+$/u.test(part))) end = 0;
    const changed = after.slice(start, after.length - end);
    if (!changed.length) return setText(line, text);
    const step = Math.ceil(changed.length / Math.min(4, Math.ceil(changed.length / 3)));
    const fragments = [];
    for (let index = 0; index < changed.length; index += step) {
      const span = document.createElement("span");
      span.textContent = changed.slice(index, index + step).join("");
      fragments.push(span);
    }
    line.replaceChildren(after.slice(0, start).join(""), ...fragments, after.slice(after.length - end).join(""));
    for (const [index, span] of fragments.entries()) {
      reveals.push(span.animate([{ opacity: index === 0 ? .25 : 0 }, { opacity: 1 }],
        { delay: index * 22, duration: 78, easing: easeOut, fill: "backwards" }));
    }
  }

  function revise(en, zh) {
    finishReveal();
    // Keep the start of an expanding centered line close to its reading position.
    const anchor = (line, text) => {
      const prefix = line.textContent.replace(/[。.!?！？,，、]+$/u, "");
      if (motion.matches || line.textContent === text || captions.dataset.align !== "center" ||
          !prefix || !text.startsWith(prefix)) return null;
      const range = document.createRange();
      range.selectNodeContents(line);
      return { range, left: range.getClientRects()[0]?.left };
    };
    const anchorEn = anchor(english, en);
    const anchorZh = anchor(current, zh);
    revealText(english, en, words);
    revealText(current, zh, graphemes);
    for (const [line, origin] of [[english, anchorEn], [current, anchorZh]]) {
      if (origin?.left == null) continue;
      origin.range.selectNodeContents(line);
      const shift = origin.left - origin.range.getClientRects()[0]?.left;
      if (!Number.isFinite(shift) || Math.abs(shift) < 2) continue;
      const offset = Math.max(-28, Math.min(28, shift));
      reveals.push(line.animate([{ transform: `translateX(${offset}px)` }, { transform: "translateX(0)" }],
        { duration: 144, easing: easeOut }));
    }
  }

  function cancelMotion() {
    finishReveal();
    enter?.cancel();
    roll?.cancel();
    idleFade?.cancel();
    exit?.remove();
    enter = roll = idleFade = exit = null;
  }

  function clear() {
    clearTimeout(clearTimer);
    cancelMotion();
    utterance = null;
    live.hidden = previous.hidden = true;
    for (const line of [current, english, previousChinese, previousEnglish]) setText(line, "");
  }

  function expire() {
    if (motion.matches || live.hidden) return clear();
    idleFade = captions.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 180, easing: "ease-out" });
    idleFade.onfinish = clear;
  }

  function showNext(en, zh) {
    const moving = !motion.matches && !live.hidden;
    const liveBefore = moving ? live.getBoundingClientRect() : null;
    const oldestBefore = moving && !previous.hidden ? previous.getBoundingClientRect() : null;
    cancelMotion();
    if (oldestBefore) {
      exit = previous.cloneNode(true);
      exit.classList.add("exiting");
      exit.setAttribute("aria-hidden", "true");
    }
    previous.hidden = live.hidden;
    setText(previousEnglish, english.textContent);
    setText(previousChinese, current.textContent);
    live.hidden = false;
    setText(english, en);
    setText(current, zh);
    if (motion.matches) return;

    const lift = liveBefore ? liveBefore.top - previous.getBoundingClientRect().top : 0;
    const liveTop = liveBefore ? live.getBoundingClientRect().top : 0;
    const offset = liveBefore ? Math.max(4, liveBefore.bottom - liveTop + 5) : 4;
    if (exit) {
      const retiring = exit;
      const bounds = captions.getBoundingClientRect();
      retiring.style.top = `${oldestBefore.top - bounds.top}px`;
      retiring.style.left = `${oldestBefore.left - bounds.left}px`;
      retiring.style.width = `${oldestBefore.width}px`;
      captions.append(retiring);
      retiring.animate([{ opacity: .55 }, { opacity: 0, transform: "translateY(-6px)" }],
        { duration: 120, easing: easeOut }).onfinish = () => {
          retiring.remove();
          if (exit === retiring) exit = null;
        };
    }
    if (liveBefore) {
      roll = previous.animate([{ opacity: 1, transform: `translateY(${lift}px)` },
        { opacity: .55, transform: "translateY(0)" }], { duration: 180, easing: easeOut });
    }
    enter = live.animate([{ opacity: .3, transform: `translateY(${offset}px)` },
      { opacity: 1, transform: "translateY(0)" }], { duration: 180, easing: easeOut });
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
    const en = message.en || message.text || "";
    if (live.hidden || utterance !== message.utterance) {
      showNext(en, message.zh);
    } else {
      idleFade?.cancel();
      if (current.textContent !== message.zh || english.textContent !== en) {
        revise(en, message.zh);
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
    clearTimer = setTimeout(expire, 6500);
  });
})();
