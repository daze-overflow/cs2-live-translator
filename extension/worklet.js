import { PCMResampler } from "./resampler.mjs";

class CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.resampler = new PCMResampler(sampleRate);
    this.epoch = options.processorOptions.epoch;
    this.port.onmessage = event => { this.epoch = event.data.epoch; };
  }
  process(inputs) {
    const channels = inputs[0];
    if (!channels?.length) return true;
    const mono = new Float32Array(channels[0].length);
    for (const channel of channels) {
      for (let i = 0; i < mono.length; i++) mono[i] += channel[i] / channels.length;
    }
    const inputStart = this.resampler.frames;
    for (const packet of this.resampler.push(mono)) {
      const buffer = new ArrayBuffer(8 + packet.samples.byteLength);
      new DataView(buffer).setFloat64(0, this.epoch + (currentFrame + packet.sourceFrame - inputStart) / sampleRate * 1000, true);
      new Int16Array(buffer, 8).set(packet.samples);
      this.port.postMessage(buffer, [buffer]);
    }
    return true;
  }
}
registerProcessor("cs2-capture", CaptureProcessor);
