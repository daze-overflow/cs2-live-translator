const button = document.getElementById("toggle");
const state = document.getElementById("state");
const fixture = document.getElementById("fixture");
const fontSizeGroup = document.getElementById("fontSize");
const fontSizeButtons = Array.from(fontSizeGroup.querySelectorAll("button[data-size]"));
const fontSizes = fontSizeButtons.map(item => Number(item.dataset.size));
const numericKeys = ["bottom", "backgroundOpacity", "textOpacity"];
const fixedDefaults = {
  width: CS2SubtitleStyle.defaults.width,
  align: CS2SubtitleStyle.defaults.align,
};
let running = false, busy = false, polling = false;
let style = { ...CS2SubtitleStyle.defaults };

function snapFontSize(value) {
  return fontSizes.reduce((best, candidate) =>
    Math.abs(candidate - value) < Math.abs(best - value) ? candidate : best, fontSizes[0]);
}

function normalizeStyle(value) {
  const normalized = CS2SubtitleStyle.normalize({ ...(value && typeof value === "object" ? value : {}), ...fixedDefaults });
  normalized.fontSize = snapFontSize(normalized.fontSize);
  return normalized;
}

function renderFixture(status) {
  if (status?.error) {
    fixture.replaceChildren();
    return;
  }
  if (status?.teams?.length) {
    const nodes = [];
    status.teams.forEach((name, index) => {
      if (index > 0) {
        const vs = document.createElement("span");
        vs.className = "vs";
        vs.textContent = "vs";
        nodes.push(vs);
      }
      const team = document.createElement("span");
      team.className = "team";
      team.textContent = name;
      nodes.push(team);
    });
    fixture.replaceChildren(...nodes);
    return;
  }
  fixture.textContent = status?.chapter || "";
}

function show(status) {
  running = Boolean(status?.running);
  state.textContent = status?.error || (status?.starting ? (status.message || "正在准备模型…") : running ?
    (status.playing === false ? "视频已暂停" : "正在翻译当前视频") : "准备就绪");
  state.classList.toggle("error", Boolean(status?.error));
  document.body.dataset.state = status?.error ? "error" : status?.starting ? "starting" :
    running ? (status.playing === false ? "paused" : "running") : "idle";
  renderFixture(status);
  button.textContent = status?.starting ? "正在准备模型…" : running ? "停止中文字幕" : "开始中文字幕";
  button.disabled = busy || Boolean(status?.starting);
}

async function refreshStatus() {
  if (polling || busy) return;
  polling = true;
  try { show(await chrome.runtime.sendMessage({ target: "service", type: "status" })); }
  catch (error) { show({ error: error.message }); }
  finally { polling = false; }
}

function updateStyleControls() {
  const activeIndex = Math.max(0, fontSizes.indexOf(style.fontSize));
  fontSizeGroup.style.setProperty("--active", String(activeIndex));
  for (const item of fontSizeButtons) {
    item.setAttribute("aria-checked", String(Number(item.dataset.size) === style.fontSize));
  }
  for (const key of numericKeys) {
    const input = document.getElementById(key);
    input.value = style[key];
    const min = Number(input.min || 0), max = Number(input.max || 100);
    input.style.setProperty("--p", `${((style[key] - min) / (max - min)) * 100}%`);
    document.getElementById(key + "-value").value = style[key] + "%";
  }
  document.getElementById("showEnglish").checked = style.showEnglish;
}

async function saveStyle() {
  style = normalizeStyle(style);
  updateStyleControls();
  try {
    await chrome.storage.local.set({ subtitleStyle: style });
  } catch (error) {
    state.textContent = "设置未保存：" + error.message;
    state.classList.add("error");
  }
}

fontSizeGroup.addEventListener("click", event => {
  const target = event.target.closest("button[data-size]");
  if (!target) return;
  fontSizeGroup.dataset.ready = "true";
  style = normalizeStyle({ ...style, fontSize: Number(target.dataset.size) });
  saveStyle();
});

for (const key of numericKeys) {
  document.getElementById(key).addEventListener("input", event => {
    style = normalizeStyle({ ...style, [key]: Number(event.target.value) });
    saveStyle();
  });
}
document.getElementById("showEnglish").addEventListener("change", event => {
  style = normalizeStyle({ ...style, showEnglish: event.target.checked });
  saveStyle();
});
document.getElementById("reset-style").addEventListener("click", () => {
  fontSizeGroup.dataset.ready = "true";
  style = { ...CS2SubtitleStyle.defaults };
  saveStyle();
});

updateStyleControls();
chrome.storage.local.get("subtitleStyle").then(saved => {
  const next = normalizeStyle(saved.subtitleStyle);
  style = next;
  updateStyleControls();
  if (saved.subtitleStyle && ["fontSize", ...Object.keys(fixedDefaults)].some(key => saved.subtitleStyle[key] !== next[key])) {
    chrome.storage.local.set({ subtitleStyle: next }).catch(() => {});
  }
}, error => { state.textContent = "无法读取设置：" + error.message; state.classList.add("error"); })
  .finally(() => { requestAnimationFrame(() => { fontSizeGroup.dataset.ready = "true"; }); });

button.addEventListener("click", async () => {
  busy = true; button.disabled = true;
  if (!running) document.body.dataset.state = "starting";
  button.textContent = running ? "正在停止…" : "正在准备模型…";
  state.textContent = running ? "正在停止…" : "正在启动本机翻译模型…";
  try {
    show(await chrome.runtime.sendMessage({ target: "service", type: running ? "stop" : "start", names: [] }));
  } catch (error) { show({ error: error.message }); }
  finally { busy = false; button.disabled = false; }
});
refreshStatus();
const poll = setInterval(refreshStatus, 1000);
window.addEventListener("pagehide", () => clearInterval(poll));
