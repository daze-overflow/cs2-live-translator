import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { PCMResampler } from '../extension/resampler.mjs';

test('capture timestamps follow the audio clock across callbacks without input', () => {
  const packets = [];
  let Processor;
  const context = vm.createContext({ PCMResampler, sampleRate: 48000, currentFrame: 0,
    AudioWorkletProcessor: class { constructor() { this.port = { postMessage: p => packets.push(p) }; } },
    registerProcessor: (_name, type) => { Processor = type; } });
  vm.runInContext(fs.readFileSync(new URL('../extension/worklet.js', import.meta.url), 'utf8').replace(/^import[^\n]+\n/, ''), context);
  const processor = new Processor({ processorOptions: { epoch: 1000 } });
  function render(input, blocks) {
    for (let i = 0; i < blocks; i++) {
      processor.process(input);
      context.currentFrame += 128;
    }
  }
  render([[new Float32Array(128)]], 10);
  const before = new DataView(packets.at(-1)).getFloat64(0, true);
  render([[]], 400);
  render([[new Float32Array(128)]], 10);
  const after = new DataView(packets.at(-1)).getFloat64(0, true);
  assert.ok(after - before > 1000, `missing-clock gap was hidden: ${after - before}ms`);
});
