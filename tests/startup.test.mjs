import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function service({ warm = false, foreign = false } = {}) {
  let listener, removed, port, captures = 0, connections = 0, status = { running: false };
  const chrome = { runtime: {
    id: 'test-id', getURL: path => 'chrome-extension://test-id/' + path,
    onMessage: { addListener: callback => { listener = callback; } },
    connectNative: () => {
      connections++;
      const messages = [], disconnects = [];
      port = { disconnected: false, onMessage: { addListener: f => messages.push(f) },
        onDisconnect: { addListener: f => disconnects.push(f) }, postMessage() {},
        disconnect() { this.disconnected = true; disconnects.forEach(f => f()); },
        emit: message => messages.forEach(f => f(message)) };
      return port;
    },
    sendMessage: async message => {
      if (message.type === 'start') { captures++; status = { running: true, tabId: 9 }; }
      if (message.type === 'stop') status = { running: false };
      return status;
    },
  }, offscreen: { hasDocument: async () => true },
  tabs: { query: async () => [{ id: 9, url: 'https://www.youtube.com/watch?v=replay' }],
    sendMessage: async () => {}, onRemoved: { addListener: callback => { removed = callback; } } },
  scripting: { executeScript: async () => [{ result: { playing: true, title: 'MOUZ vs PARIVISION | ', chapter: '' } }] },
  tabCapture: { getMediaStreamId: async () => 'stream' } };
  const context = vm.createContext({ chrome, setTimeout, clearTimeout, AbortSignal,
    fetch: async url => {
      if (url.includes('local-config.json')) return { json: async () => ({ port: 8765, token: 'test-only' }) };
      if (!warm) throw new Error('offline');
      return { ok: true, json: async () => ({ ready: true, app_id: foreign ? 'other-app' : 'cs2-live-translator' }) };
    } });
  vm.runInContext(fs.readFileSync(new URL('../extension/service.js', import.meta.url), 'utf8'), context);
  return {
    chrome, get captures() { return captures; }, get connections() { return connections; },
    get port() { return port; },
    send: (type, sender = { url: chrome.runtime.getURL('popup.html') }) => new Promise(resolve =>
      listener({ target: 'service', type, names: [] }, sender, resolve)),
    ready: () => { warm = true; port.emit({ type: 'ready' }); },
    fail: message => port.emit({ type: 'error', message }),
    removed: () => removed(9),
  };
}

const tick = () => new Promise(resolve => setImmediate(resolve));

test('cold Start waits for the native host and exposes loading when popup is reopened', async t => {
  const page = service();
  t.after(() => page.port?.disconnect());
  const start = page.send('start');
  await tick();
  assert.equal((await page.send('status')).starting, true);
  assert.equal(page.captures, 0);
  page.ready();
  assert.equal((await start).running, true);
  assert.equal(page.captures, 1);
});

test('warm Start reuses ready backend without starting a host', async () => {
  const page = service({ warm: true });
  assert.equal((await page.send('start')).running, true);
  assert.equal(page.connections, 0);
});

test('two Start requests share one native load and one capture', async t => {
  const page = service();
  t.after(() => page.port?.disconnect());
  const first = page.send('start'), second = page.send('start');
  await tick();
  assert.equal(page.connections, 1);
  page.ready();
  assert.equal((await first).running, true);
  assert.equal((await second).running, true);
  assert.equal(page.captures, 1);
  await page.send('stop');
  assert.equal(page.port.disconnected, true);
});

test('failed native load is visible and a later click can retry', async t => {
  const page = service();
  t.after(() => page.port?.disconnect());
  const first = page.send('start');
  await tick();
  page.fail('模型启动失败');
  assert.match((await first).error, /模型启动失败/);
  const second = page.send('start');
  await tick();
  page.ready();
  assert.equal((await second).running, true);
});

test('missing host gives a one-time repair message and resets loading state', async () => {
  const page = service();
  const start = page.send('start');
  await tick();
  page.chrome.runtime.lastError = { message: 'Specified native messaging host not found.' };
  page.port.disconnect();
  delete page.chrome.runtime.lastError;
  assert.match((await start).error, /启动组件/);
  assert.equal((await page.send('status')).starting, false);
});

test('closing the captured tab releases the owned native connection', async t => {
  const page = service();
  t.after(() => page.port?.disconnect());
  const start = page.send('start');
  await tick(); page.ready(); await start;
  page.removed(); await tick();
  assert.equal(page.port.disconnected, true);
});

test('a web content script cannot request a native backend launch', async () => {
  const page = service();
  const result = await page.send('start', { tab: { id: 9 }, url: 'https://www.youtube.com/watch?v=replay' });
  assert.match(result.error, /扩展/);
  assert.equal(page.connections, 0);
});

test('an unrelated port listener is not accepted as a ready translation backend', async () => {
  const page = service({ warm: true, foreign: true });
  const result = await page.send('start');
  assert.match(result.error, /其他程序/);
  assert.equal(page.captures, 0);
});
