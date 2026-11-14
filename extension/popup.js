const button = document.getElementById("toggle");
const state = document.getElementById("state");
const names = document.getElementById("names");
const preview = document.getElementById("style-preview");
const saveState = document.getElementById("save-state");
const numericKeys = ["fontSize", "bottom", "width", "backgroundOpacity", "textOpacity"];
let running = false, busy = false, polling = false;
let style = { ...CS2SubtitleStyle.defaults };

document.getElementById("version").textContent = "v" + chrome.runtime.getManifest().version;

function show(status) {
  running = Boolean(status?.running);
  state.textContent = status?.error || (status?.starting ? status.message : running ?
    (status.playing === false ? "视频已暂停 · 等待播放" : "正在翻译当前视频") : "点击开始，自动加载本机翻译");
  state.classList.toggle("error", Boolean(status?.error));
  const source = { title: "标题", chapter: "章节", manual: "补充队名", speech: "解说" }[status?.teamSource];
  document.getElementById("fixture").textContent = status?.teams?.length ?
    status.teams.join(" vs ") + (source ? ` · 来自${source}` : "") :
    status?.chapter || "自动读取标题和章节对阵，或从解说识别队伍";
  button.textContent = status?.starting ? "正在准备模型…" : running ? "停止中文字幕" : "开始中文字幕";
  button.disabled = busy || Boolean(status?.starting);
  const age = status?.progressAgeMs;
  document.getElementById("metrics").textContent = age == null ? "尚无处理计时。播放并开始字幕后显示。" :
    `处理进度落后 ${Math.round(age)}ms · 翻译 ${Math.round(status.translationMs)}ms${status.missedFinals ? " · 检测到处理遗漏" : ""}。这是处理进度，不是完整语音到屏幕延迟。`;
}

async function refreshStatus() {
  if (polling || busy) return;
  polling = true;
  try { show(await chrome.runtime.sendMessage({ target: "service", type: "status" })); }
  catch (error) { show({ error: error.message }); }
  finally { polling = false; }
}

function updateStyleControls() {
  for (const key of numericKeys) {
    document.getElementById(key).value = style[key];
    document.getElementById(key + "-value").value = style[key] + (key === "fontSize" ? "px" : "%");
  }
  document.getElementById("align").value = style.align;
  document.getElementById("showEnglish").checked = style.showEnglish;
  CS2SubtitleStyle.apply(preview, style);
}

async function saveStyle() {
  updateStyleControls();
  try {
    await chrome.storage.local.set({ subtitleStyle: style });
    saveState.textContent = "已保存，当前字幕即时生效。0% 为完全透明。";
  } catch (error) { saveState.textContent = "设置未保存：" + error.message; }
}

for (const key of numericKeys) document.getElementById(key).addEventListener("input", event => {
  style = CS2SubtitleStyle.normalize({ ...style, [key]: Number(event.target.value) });
  saveStyle();
});
document.getElementById("align").addEventListener("change", event => {
  style = { ...style, align: event.target.value }; saveStyle();
});
document.getElementById("showEnglish").addEventListener("change", event => {
  style = { ...style, showEnglish: event.target.checked }; saveStyle();
});
document.getElementById("reset-style").addEventListener("click", () => {
  style = { ...CS2SubtitleStyle.defaults }; saveStyle();
});

function updateNamesCount() {
  const count = names.value.split(/\n|,|，/).map(name => name.trim()).filter(Boolean).length;
  document.getElementById("names-count").textContent = count ? `（${count} 个）` : "（可选）";
}
names.addEventListener("input", () => {
  updateNamesCount();
  chrome.storage.local.set({ names: names.value }).catch(error => { saveState.textContent = "名称未保存：" + error.message; });
});
updateStyleControls();
chrome.storage.local.get(["names", "subtitleStyle"]).then(saved => {
  names.value = saved.names || "";
  style = CS2SubtitleStyle.normalize(saved.subtitleStyle);
  updateNamesCount(); updateStyleControls();
}, error => { saveState.textContent = "无法读取设置：" + error.message; });

button.addEventListener("click", async () => {
  busy = true; button.disabled = true;
  button.textContent = running ? "正在停止…" : "正在准备模型…";
  state.textContent = running ? "正在停止…" : "正在自动启动本机翻译模型，请稍候…";
  try {
    await chrome.storage.local.set({ names: names.value });
    show(await chrome.runtime.sendMessage({ target: "service", type: running ? "stop" : "start",
      names: names.value.split(/\n|,|，/).map(name => name.trim()).filter(Boolean) }));
  } catch (error) { show({ error: error.message }); }
  finally { busy = false; button.disabled = false; }
});
refreshStatus();
const poll = setInterval(refreshStatus, 1000);
window.addEventListener("pagehide", () => clearInterval(poll));
