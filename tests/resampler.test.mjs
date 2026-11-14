import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PCMResampler } from '../extension/resampler.mjs';

function render(rate, frequency) {
  const filter = new PCMResampler(rate);
  const packets = [];
  for (let offset = 0; offset < rate; offset += 128) {
    const input = Float32Array.from({ length: Math.min(128, rate - offset) }, (_, i) =>
      0.5 * Math.sin(2 * Math.PI * frequency * (offset + i) / rate));
    packets.push(...filter.push(input));
  }
  return packets;
}

test('48kHz and 44.1kHz audio retain one-second timing and 20ms packets', () => {
  for (const rate of [48000, 44100]) {
    const packets = render(rate, 1000);
    assert.equal(packets.length, 50);
    assert.ok(packets.every(p => p.samples.length === 320));
    assert.ok(Math.abs(packets.at(-1).sourceFrame / rate - 1) < 0.002);
  }
});

test('high game sound frequencies are attenuated instead of aliasing into speech', () => {
  const rms = packets => {
    const values = packets.slice(1).flatMap(p => [...p.samples]);
    return Math.sqrt(values.reduce((sum, v) => sum + v * v, 0) / values.length);
  };
  assert.ok(rms(render(48000, 12000)) < rms(render(48000, 1000)) * 0.03);
});
