import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function overlay(reducedMotion = false) {
  const listeners = [], frames = [], sent = [], animations = [];
  const line = () => ({ value: '', writes: 0,
    get textContent() { return this.value; },
    set textContent(value) { this.value = value; this.writes++; } });
  const english = line(), current = line();
  const captions = { animate: () => {
    const animation = { cancelled: false, cancel() { this.cancelled = true; } };
    animations.push(animation); return animation;
  } };
  const video = { paused: false, seeking: false, addEventListener() {} };
  const player = { append() {}, querySelector: () => video };
  const shadow = { querySelector: selector => ({ '.english': english, '.current': current, '.captions': captions })[selector] };
  const context = vm.createContext({
    document: { getElementById: id => id === 'movie_player' ? player : null,
      createElement: () => ({ style: {}, attachShadow: () => shadow }) },
    CS2SubtitleStyle: { defaults: {}, apply() {} }, CS2PageContext: { read: () => ({ playing: true, title: 'test' }) },
    chrome: { storage: { local: { get: async () => ({}) }, onChanged: { addListener() {} } },
      runtime: { onMessage: { addListener: handler => listeners.push(handler) }, sendMessage: async data => sent.push(data) } },
    requestAnimationFrame: callback => frames.push(callback), matchMedia: () => ({ matches: reducedMotion }),
    setTimeout() {}, clearTimeout() {}, setInterval() {},
  });
  vm.runInContext(fs.readFileSync(new URL('../extension/overlay.js', import.meta.url), 'utf8'), context);
  const message = data => listeners.forEach(listener => listener(data));
  return { current, english, sent, animations, message,
    caption: (seq, utterance, zh, en = 'source') => message({ type: 'caption', epoch: 0, seq, utterance, en, zh }),
    paint: () => { while (frames.length) frames.shift()(); } };
}

test('identical revisions do not rewrite the text but the displayed latest sequence is acknowledged', () => {
  const page = overlay();
  page.caption(1, 0, 'Jame没有烟。');
  page.caption(2, 0, 'Jame没有烟。');
  page.paint();
  assert.equal(page.current.writes, 1);
  assert.equal(page.english.writes, 1);
  assert.equal(page.sent.length, 1);
  assert.equal(page.sent[0].seq, 2);
});

test('a new phrase eases in once, corrections within it do not blink again', () => {
  const page = overlay();
  page.caption(1, 0, 'Jame没有烟。');
  page.caption(2, 0, 'Jame没有烟雾弹。');
  assert.equal(page.animations.length, 1);
  page.caption(3, 1, 'NAVI选择保枪。');
  assert.equal(page.animations.length, 2);
  assert.equal(page.animations[0].cancelled, true);
});

test('seek/clear cancels easing and cannot acknowledge an erased caption', () => {
  const page = overlay();
  page.caption(1, 0, '旧字幕');
  page.message({ type: 'clear', epoch: 1 });
  page.paint();
  assert.equal(page.current.textContent, '');
  assert.equal(page.sent.length, 0);
  assert.equal(page.animations[0].cancelled, true);
  page.caption(2, 1, '过期字幕');
  assert.equal(page.current.textContent, '');
});

test('reduced motion renders the text without easing', () => {
  const page = overlay(true);
  page.caption(1, 0, '正常字幕');
  assert.equal(page.current.textContent, '正常字幕');
  assert.equal(page.animations.length, 0);
});
