let activeTabId = null;
let startingTask = null, startupStatus = null, nativePort = null;

async function offscreen(message) {
  return chrome.runtime.sendMessage({ ...message, target: "offscreen" });
}

function releaseLocalService() {
  const port = nativePort;
  nativePort = null;
  port?.disconnect();
}

async function ensureLocalService(config) {
  try {
    const health = await fetch(`http://127.0.0.1:${config.port}/health`, { signal: AbortSignal.timeout(2500) });
    if (health.ok) {
      const data = await health.json();
      if (data.app_id === "cs2-live-translator" && data.ready === true) return config.port;
    }
  } catch { /* Let the native host locate or start the service. */ }
  return new Promise((resolve, reject) => {
    const port = chrome.runtime.connectNative("com.cs2.live_translator");
    nativePort = port;
    const fail = message => { clearTimeout(timer); reject(new Error(message)); };
    const timer = setTimeout(() => {
      fail("本机模型加载超时，请确认插电后重试。"); releaseLocalService();
    }, 125000);
    port.onMessage.addListener(message => {
      if (message.type === "progress") startupStatus.message = message.message;
      if (message.type === "ready") {
        const port = message.port ?? config.port;
        if (port !== config.port && port !== 18765) {
          fail("本机启动器返回了无效的字幕端口。");
          return;
        }
        clearTimeout(timer);
        resolve(port);
      }
      if (message.type === "error") fail(message.message);
    });
    port.onDisconnect.addListener(() => {
      const error = chrome.runtime.lastError?.message || "本机翻译连接已断开，请点击重试。";
      if (nativePort === port) nativePort = null;
      fail(/not found|forbidden|permission|native host has exited|failed to start/i.test(error) ?
        "本机启动组件未就绪，请运行一次 install-launcher.cmd 后重试。" : error);
    });
    port.postMessage({ type: "start" });
  });
}

async function start(names) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!/^https:\/\/(www\.)?youtube\.com\/(watch|live)/.test(tab.url || "")) {
    throw new Error("请先打开 YouTube 的直播或视频页面。");
  }
  if (await chrome.offscreen.hasDocument()) {
    const status = await offscreen({ type: "status" });
    if (status?.running) return status;
  }
  activeTabId = tab.id;
  startupStatus = { starting: true, running: false, message: "正在准备本机翻译模型，请稍候…" };
  const config = await (await fetch(chrome.runtime.getURL("local-config.json"))).json();
  config.port = await ensureLocalService(config);
  startupStatus.message = "模型已就绪，正在连接当前视频…";
  if (!(await chrome.offscreen.hasDocument())) {
    await chrome.offscreen.createDocument({ url: "offscreen.html", reasons: ["USER_MEDIA"],
      justification: "Capture the user-selected YouTube audio for local subtitles." });
  }
  await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["subtitle-style.js", "page-context.js", "overlay.js"] });
  const [{ result: media }] = await chrome.scripting.executeScript({ target: { tabId: tab.id },
    func: () => CS2PageContext.read() });
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
  activeTabId = tab.id;
  const result = await offscreen({ type: "start", streamId, tabId: tab.id,
    title: media.title, chapter: media.chapter, playing: media.playing, names, config });
  if (result?.error) throw new Error(result.error);
  startupStatus = null;
  return result;
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.target !== "service") return false;
  (async () => {
    if (message.type === "start") {
      if (sender.tab || sender.url !== chrome.runtime.getURL("popup.html")) throw new Error("请从扩展弹窗点击开始字幕。");
      if (!startingTask) startingTask = start(message.names || []).catch(async error => {
        if (await chrome.offscreen.hasDocument()) await offscreen({ type: "stop" }).catch(() => {});
        releaseLocalService();
        startupStatus = { starting: false, running: false, error: error.message };
        throw error;
      }).finally(() => { startingTask = null; });
      return startingTask;
    }
    if (message.type === "stop") {
      const result = (await chrome.offscreen.hasDocument()) ? await offscreen({ type: "stop" }) : { running: false };
      releaseLocalService(); startupStatus = null;
      return result;
    }
    if (message.type === "status") {
      if (startupStatus) return startupStatus;
      return (await chrome.offscreen.hasDocument()) ? offscreen({ type: "status" }) : { running: false };
    }
    if (message.type === "displayed") return offscreen(message);
    if (message.type === "media-state") return offscreen({ ...message, tabId: sender.tab?.id });
    if (message.type === "caption" || message.type === "capture-status" || message.type === "clear") {
      const tabId = message.tabId || activeTabId;
      if (tabId != null) await chrome.tabs.sendMessage(tabId, message).catch(() => {});
      if (message.type === "capture-status" && !message.running) releaseLocalService();
      return {};
    }
  })().then(respond, error => respond({ error: error.message }));
  return true;
});

chrome.tabs.onRemoved.addListener(tabId => {
  if (tabId === activeTabId) offscreen({ type: "stop" }).catch(() => {}).finally(releaseLocalService);
});
