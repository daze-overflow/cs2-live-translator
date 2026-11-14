// Small causal low-pass FIR. Input playback remains on a separate, untouched audio branch.
export class PCMResampler {
  constructor(sourceRate, targetRate = 16000, packetSize = 320) {
    this.ratio = targetRate / sourceRate;
    this.phase = 0;
    this.frames = 0;
    this.index = 0;
    this.used = 0;
    this.ring = new Float32Array(64);
    this.packet = new Int16Array(packetSize);
    this.kernel = new Float64Array(64);
    const cutoff = Math.min(0.45, 0.45 * this.ratio);
    let sum = 0;
    for (let i = 0; i < 64; i++) {
      const x = i - 31.5;
      const value = Math.sin(2 * Math.PI * cutoff * x) / (Math.PI * x);
      this.kernel[i] = value * (0.54 - 0.46 * Math.cos(2 * Math.PI * i / 63));
      sum += this.kernel[i];
    }
    for (let i = 0; i < 64; i++) this.kernel[i] /= sum;
  }

  push(input) {
    const ready = [];
    for (const sample of input) {
      this.ring[this.index] = sample;
      this.index = (this.index + 1) & 63;
      this.frames++;
      this.phase += this.ratio;
      if (this.phase + 1e-10 < 1) continue;
      this.phase -= 1;
      let value = 0;
      for (let i = 0; i < 64; i++) value += this.ring[(this.index - 1 - i) & 63] * this.kernel[i];
      this.packet[this.used++] = Math.round(Math.max(-1, Math.min(1, value)) * 32767);
      if (this.used === this.packet.length) {
        ready.push({ samples: this.packet, sourceFrame: this.frames - 31.5 });
        this.packet = new Int16Array(this.packet.length);
        this.used = 0;
      }
    }
    return ready;
  }
}
