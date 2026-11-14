let stream, context, socket, processor, source, mute;
let status = { running: false };
let stopping = false;

function notify(message) {
  return chrome.runtime.sendMessage({ ...message, target: "service", tabId: status.tabId }).catch(() => {});
}

async function stop(error = "") {
  if (stopping) return;
  stopping = true;
  const oldTab = status.tabId;
  processor?.disconnect();
  source?.disconnect();
  mute?.disconnect();
  stream?.getTracks().forEach(track => track.stop());
  if (context && context.state !== "closed") await context.close();
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "finish" }));
  socket?.close();
  stream = context = socket = processor = source = mute = null;
  status = { running: false, tabId: oldTab, error };
  await notify({ type: "capture-status", running: false, error });
  stopping = false;
}

async function start(message) {
  status = { running: true, tabId: message.tabId, chapter: message.chapter, playing: message.playing !== false };
  try {
    socket = new WebSocket(`ws://127.0.0.1:${message.config.port}/audio?token=${encodeURIComponent(message.config.token)}`);
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("本地服务连接超时。")), 5000);
      socket.onopen = () => socket.send(JSON.stringify({ type: "hello", names: message.names, title: message.title }));
      socket.onerror = () => { clearTimeout(timeout); reject(new Error("无法连接本地服务。")); };
      socket.onmessage = event => {
        const data = JSON.parse(event.data);
        if (data.type === "ready") {
          status.teams = data.teams;
          status.teamSource = data.team_source;
          clearTimeout(timeout); resolve();
        }
        if (data.type === "error") { clearTimeout(timeout); reject(new Error(data.message)); }
      };
    });
    socket.onmessage = event => {
      const data = JSON.parse(event.data);
      if (data.type === "caption") {
        status.progressAgeMs = data.progress_age_ms;
        status.translationMs = data.translation_ms;
        status.missedFinals = data.missed_finals;
        status.teams = data.teams;
        status.teamSource = data.team_source;
        notify({ ...data, type: "caption" });
      } else if (data.type === "clear") {
        status.teams = data.teams;
        status.teamSource = data.team_source;
        notify(data);
      }
      else if (data.type === "error") stop(data.message);
    };
    socket.onclose = () => { if (!stopping && status.running) stop("本地连接已断开，请重新开始。"); };
    stream = await navigator.mediaDevices.getUserMedia({ audio: { mandatory: {
      chromeMediaSource: "tab", chromeMediaSourceId: message.streamId
    } }, video: false });
    context = new AudioContext();
    source = context.createMediaStreamSource(stream);
    source.connect(context.destination);
    await context.audioWorklet.addModule(chrome.runtime.getURL("worklet.js"));
    processor = new AudioWorkletNode(context, "cs2-capture", { processorOptions: {
      epoch: Date.now() - context.currentTime * 1000
    } });
    context.onstatechange = () => {
      if (context?.state === "running") processor?.port.postMessage({ epoch: Date.now() - context.currentTime * 1000 });
    };
    mute = context.createGain();
    mute.gain.value = 0;
    source.connect(processor).connect(mute).connect(context.destination);
    processor.port.onmessage = event => {
      if (!status.playing) return;
      if (socket?.readyState === WebSocket.OPEN) {
        if (socket.bufferedAmount > 32000) {
          status.error = "音频处理积压，当前未达到延迟目标。";
        }
        socket.send(event.data);
      }
    };
    stream.getAudioTracks()[0].onended = () => stop();
    await context.resume();
    await notify({ type: "capture-status", running: true });
    return status;
  } catch (error) {
    await stop(error.message);
    throw error;
  }
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.target !== "offscreen") return false;
  (async () => {
    if (message.type === "status") return status;
    if (message.type === "start") return start(message);
    if (message.type === "stop") { await stop(); return status; }
    if (message.type === "media-state" && status.running && message.tabId === status.tabId) {
      status.playing = message.playing;
      status.chapter = message.chapter;
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "reset", title: message.title }));
      return status;
    }
    if (message.type === "displayed" && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
      return {};
    }
  })().then(respond, error => respond({ error: error.message }));
  return true;
});
