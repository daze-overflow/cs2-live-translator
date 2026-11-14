import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function styleModule() {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(new URL('../extension/subtitle-style.js', import.meta.url), 'utf8'), context);
  return context.CS2SubtitleStyle;
}

test('invalid stored settings cannot inject CSS or create unreadable dimensions', () => {
  const { normalize } = styleModule();
  const style = normalize({ fontSize: 999, bottom: -10, width: '100vw;display:none',
    backgroundOpacity: NaN, textOpacity: -1, align: 'left;display:none', showEnglish: 'false' });
  assert.equal(style.fontSize, 48);
  assert.equal(style.bottom, 0);
  assert.equal(style.width, 80);
  assert.equal(style.backgroundOpacity, 100);
  assert.equal(style.textOpacity, 0);
  assert.equal(style.align, 'center');
  assert.equal(style.showEnglish, true);
});

test('saved appearance maps to live overlay variables and English visibility', () => {
  const { apply } = styleModule();
  const properties = new Map(), classes = new Map();
  const target = { style: { setProperty: (key, value) => properties.set(key, value) }, dataset: {},
    classList: { toggle: (name, active) => classes.set(name, active) } };
  apply(target, { fontSize: 32, bottom: 12, width: 70, backgroundOpacity: 55,
    textOpacity: 90, align: 'right', showEnglish: false });
  assert.equal(properties.get('--font-size'), '32px');
  assert.equal(properties.get('--caption-bottom'), '12%');
  assert.equal(properties.get('--caption-width'), '70%');
  assert.equal(properties.get('--background-alpha'), '0.55');
  assert.equal(properties.get('--text-alpha'), '0.9');
  assert.equal(target.dataset.align, 'right');
  assert.equal(classes.get('hide-english'), true);
});
