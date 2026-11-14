import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function overlay() {
  let title = 'PVISION vs. Natus Vincere', chapter = '', interval;
  const sent = [], handlers = {};
  const line = { textContent: '' };
  const video = { paused: false, seeking: false, addEventListener: (event, handler) => { handlers[event] = handler; } };
  const shadow = { querySelector: () => line };
  const player = { append: () => {}, querySelector: () => video };
  const context = vm.createContext({
    URL, location: { href: 'https://www.youtube.com/watch?v=live-id' },
    document: { title: '(5) old notification title - YouTube',
      querySelector: selector => selector === 'h1.ytd-watch-metadata' ? { textContent: title } :
        selector === '.ytp-chapter-title-content' ? { textContent: chapter } : video,
      getElementById: id => id === 'movie_player' ? player : null,
      createElement: () => ({ style: {}, attachShadow: () => shadow }) },
    CS2SubtitleStyle: { defaults: {}, apply: () => {} },
    chrome: { storage: { local: { get: async () => ({}) }, onChanged: { addListener: () => {} } },
      runtime: { sendMessage: async message => sent.push(message), onMessage: { addListener: () => {} } } },
    setInterval: callback => { interval = callback; }, clearTimeout() {},
  });
  const shared = new URL('../extension/page-context.js', import.meta.url);
  if (fs.existsSync(shared)) vm.runInContext(fs.readFileSync(shared, 'utf8'), context);
  vm.runInContext(fs.readFileSync(new URL('../extension/overlay.js', import.meta.url), 'utf8'), context);
  return { context, sent, handlers, tick: () => interval?.(),
    title: value => { title = value; }, chapter: value => { chapter = value; } };
}

test('a playing title/chapter change refreshes context without needing a pause', () => {
  const page = overlay();
  page.tick();
  assert.equal(page.sent.length, 0);
  page.title('Liquid vs TYLOO');
  page.tick();
  assert.equal(page.sent.length, 1);
  assert.equal(page.sent[0].title, 'Liquid vs TYLOO | ');
  page.tick();
  assert.equal(page.sent.length, 1);
  page.chapter('FURIA vs Vitality - Map 1');
  page.tick();
  assert.equal(page.sent.length, 2);
  assert.match(page.sent[1].title, /FURIA vs Vitality/);
});

test('YouTube notification title counts do not reset recognition', () => {
  const page = overlay();
  page.context.document.title = '(199) newer notification title - YouTube';
  page.tick();
  assert.equal(page.sent.length, 0);
});

test('an older injected tab cannot reset the currently captured tab', async () => {
  let listener;
  const sent = [];
  const context = vm.createContext({ chrome: {
    runtime: { onMessage: { addListener: callback => { listener = callback; } },
      sendMessage: async message => sent.push(message) },
    tabs: { onRemoved: { addListener() {} } },
  } });
  vm.runInContext(fs.readFileSync(new URL('../extension/service.js', import.meta.url), 'utf8'), context);
  await new Promise(resolve => listener({ target: 'service', type: 'media-state', playing: true }, { tab: { id: 7 } }, resolve));
  assert.equal(sent[0].tabId, 7);
  let offscreenListener, resets = 0;
  const offscreen = vm.createContext({ chrome: { runtime: { onMessage: { addListener: callback => { offscreenListener = callback; } } } },
    WebSocket: { OPEN: 1 } });
  vm.runInContext(fs.readFileSync(new URL('../extension/offscreen.js', import.meta.url), 'utf8'), offscreen);
  vm.runInContext('status = { running: true, tabId: 8 }; socket = { readyState: 1, send: () => reset() };',
    Object.assign(offscreen, { reset: () => { resets++; } }));
  await new Promise(resolve => offscreenListener({ ...sent[0], target: 'offscreen' }, {}, resolve));
  assert.equal(resets, 0);
});
