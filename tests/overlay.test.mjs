import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function overlay(reducedMotion = false) {
  const listeners = [], frames = [], sent = [], animations = [];
  const timers = new Map(), retiring = new Set();
  let timerId = 0;
  const line = () => ({ value: '', writes: 0, spans: [],
    get textContent() { return this.value; },
    set textContent(value) { this.value = value; this.spans = []; this.writes++; },
    replaceChildren(...children) {
      this.textContent = children.map(child => typeof child === "string" ? child : child.textContent).join("");
      this.spans = children.filter(child => typeof child !== "string");
    } });
  const english = line(), current = line();
  const previousEnglish = line(), previous = line();
  const cue = (name, top, hidden = true, left = 0, width = 280) => ({
    hidden, classList: { add() {} }, dataset: {}, style: {}, setAttribute() {},
    getBoundingClientRect: () => ({ top, bottom: top + 48, left, width }),
    animate(keyframes, options) {
      const animation = { name, keyframes, options, cancelled: false, playState: "running",
        cancel() { this.cancelled = true; this.playState = "idle"; },
        finish() { this.playState = "finished"; this.onfinish?.(); } };
      animations.push(animation); return animation;
    },
    cloneNode: () => cue("exit", top, false),
    remove() { retiring.delete(this); },
    append(node) { retiring.add(node); },
  });
  const captions = cue("captions", 40, false), live = cue("live", 93), history = cue("previous", 40, true, 120, 160);
  const video = { paused: false, seeking: false, addEventListener() {} };
  const player = { append() {}, querySelector: () => video };
  const shadow = { querySelector: selector => ({ '.live .english': english, '.current': current, '.captions': captions,
    '.live': live, '.previous': history, '.previous .english': previousEnglish, '.previous .zh': previous })[selector] };
  const context = vm.createContext({
    document: { getElementById: id => id === 'movie_player' ? player : null,
      createElement: tag => tag === "span" ? cue("fragment", 0) : ({ style: {}, attachShadow: () => shadow }) },
    CS2SubtitleStyle: { defaults: {}, apply() {} }, CS2PageContext: { read: () => ({ playing: true, title: 'test' }) },
    chrome: { storage: { local: { get: async () => ({}) }, onChanged: { addListener() {} } },
      runtime: { onMessage: { addListener: handler => listeners.push(handler) }, sendMessage: async data => sent.push(data) } },
    requestAnimationFrame: callback => frames.push(callback), matchMedia: () => ({ matches: reducedMotion }),
    setTimeout: callback => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: id => timers.delete(id), setInterval() {},
  });
  vm.runInContext(fs.readFileSync(new URL('../extension/overlay.js', import.meta.url), 'utf8'), context);
  const message = data => listeners.forEach(listener => listener(data));
  return { current, english, previous, previousEnglish, sent, animations, message, retiring, live, history,
    caption: (seq, utterance, zh, en = 'source') => message({ type: 'caption', epoch: 0, seq, utterance, en, zh }),
    expire: () => { for (const [id, callback] of timers) { timers.delete(id); callback(); } },
    paint: () => { while (frames.length) frames.shift()(); } };
}

test('new sentences retain only the immediately previous bilingual group', () => {
  const page = overlay();
  page.caption(1, 0, 'Jame没有烟。', 'Jame has no smoke.');
  page.caption(2, 1, 'NAVI选择保枪。', 'NAVI save.');
  assert.equal(page.previous.textContent, 'Jame没有烟。');
  assert.equal(page.previousEnglish.textContent, 'Jame has no smoke.');
  page.caption(3, 1, 'NAVI选择保枪，等待下一回合。', 'NAVI save for the next round.');
  assert.equal(page.previous.textContent, 'Jame没有烟。');
  page.caption(4, 2, '下一回合开始。', 'The next round begins.');
  assert.equal(page.previous.textContent, 'NAVI选择保枪，等待下一回合。');
  assert.equal(page.current.textContent, '下一回合开始。');
});

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

test('new phrases roll up and interrupt an in-progress text reveal', () => {
  const page = overlay();
  page.caption(1, 0, 'Jame没有烟。');
  page.caption(2, 0, 'Jame没有烟雾弹。');
  const fragments = page.animations.filter(animation => animation.name === 'fragment');
  assert(fragments.length > 0);
  page.caption(3, 1, 'NAVI选择保枪。');
  assert(fragments.every(animation => animation.cancelled));
  assert.deepEqual(page.animations.filter(a => a.name !== 'fragment').map(a => a.name), ['live', 'previous', 'live']);
  assert.equal(page.animations[0].cancelled, true);
  assert.equal(page.previous.textContent, 'Jame没有烟雾弹。');
});

test('a longer final keeps the shared prefix and reveals only its changed text within 150ms', () => {
  const page = overlay();
  page.caption(1, 0, 'Jame守住B点。', 'Jame holds B.');
  page.animations[0].finish();
  page.caption(2, 0, 'Jame守住B点，等队友从中路赶来回防。', 'Jame holds B and waits for a teammate to rotate from mid.');
  assert.equal(page.current.spans.map(node => node.textContent).join(""), '，等队友从中路赶来回防。');
  assert.equal(page.english.spans.map(node => node.textContent).join(""), ' and waits for a teammate to rotate from mid.');
  const fragments = page.animations.filter(animation => animation.name === 'fragment');
  assert(fragments.length > 2);
  assert(fragments.every(({options}) => (options.delay ?? 0) + options.duration <= 150));
  assert(fragments.some(({options}) => options.delay > 0));
  assert.equal(page.history.hidden, true);
});

test('a replacement in the middle keeps its unchanged ending outside the reveal', () => {
  const page = overlay();
  page.caption(1, 0, 'Jame用烟守住B点。', 'Jame uses smoke to hold B.');
  page.caption(2, 0, 'Jame用闪光守住B点。', 'Jame uses a flash to hold B.');
  assert.equal(page.current.spans.map(node => node.textContent).join(""), '闪光');
  assert.equal(page.english.spans.map(node => node.textContent).join(""), 'a flash');
  assert.equal(page.current.textContent, 'Jame用闪光守住B点。');
});

test('rapid updates retire one temporary layer at a time and remove it on finish', () => {
  const page = overlay();
  for (let i = 1; i <= 4; i++) page.caption(i, i, `字幕 ${i}`);
  assert.equal(page.retiring.size, 1);
  const [exiting] = page.retiring;
  assert.equal(exiting.style.left, '120px');
  assert.equal(exiting.style.width, '160px');
  page.animations.filter(animation => animation.name === 'exit').at(-1).finish();
  assert.equal(page.retiring.size, 0);
  assert.equal(page.previous.textContent, '字幕 3');
  assert.equal(page.current.textContent, '字幕 4');
});

test('idle subtitles fade out and a new cue cancels the pending disappearance', () => {
  const page = overlay();
  page.caption(1, 0, '字幕一。');
  page.expire();
  const fading = page.animations.at(-1);
  assert.equal(fading.name, 'captions');
  page.caption(2, 1, '字幕二。');
  assert.equal(fading.cancelled, true);
  page.expire();
  page.animations.at(-1).finish();
  assert.equal(page.history.hidden, true);
  assert.equal(page.live.hidden, true);
});

test('seek/clear cancels easing and cannot acknowledge an erased caption', () => {
  const page = overlay();
  page.caption(1, 0, '旧字幕');
  page.caption(2, 1, '另一句旧字幕');
  page.caption(3, 2, '跳转前最后一句');
  page.message({ type: 'clear', epoch: 1 });
  page.paint();
  assert.equal(page.current.textContent, '');
  assert.equal(page.previous.textContent, '');
  assert.equal(page.retiring.size, 0);
  assert.equal(page.sent.length, 0);
  assert.equal(page.animations[0].cancelled, true);
  page.caption(4, 3, '过期字幕');
  assert.equal(page.current.textContent, '');
});

test('reduced motion renders the text without easing', () => {
  const page = overlay(true);
  page.caption(1, 0, '正常字幕');
  page.caption(2, 1, '下一句');
  page.caption(3, 1, '下一句已完成。');
  assert.equal(page.previous.textContent, '正常字幕');
  assert.equal(page.current.textContent, '下一句已完成。');
  assert.equal(page.animations.length, 0);
});
