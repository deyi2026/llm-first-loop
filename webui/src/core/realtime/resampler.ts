// M1（T-M1-9）：浏览器采集音频 → 16k 单声道 PCM16 重采样（RTM-AUD-01、CAP-14）。
//
// 本模块为**纯算法**（可 vitest 验证）。真实麦克风采集、`AudioWorklet` 与真实端到端延迟
// 不在此验证——浏览器链路未接通时相关条目一律 **未验收**（RTM-EVD-06）。

export const TARGET_SAMPLE_RATE = 16000;

/** 浮点样本（[-1,1]）→ PCM16，溢出夹紧（不环绕）。 */
export function floatToPcm16(sample: number): number {
  const clamped = Math.max(-1, Math.min(1, sample));
  return Math.round(clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff);
}

/** 线性插值重采样：任意输入采样率 → 目标采样率（默认 16k）的 PCM16。 */
export function resampleToPcm16(
  input: Float32Array,
  inputRate: number,
  targetRate: number = TARGET_SAMPLE_RATE,
): Int16Array {
  if (!Number.isFinite(inputRate) || !Number.isFinite(targetRate) || inputRate <= 0 || targetRate <= 0) {
    throw new Error("sample rates must be positive finite numbers");
  }
  if (input.length === 0) {
    return new Int16Array(0);
  }
  const ratio = inputRate / targetRate;
  const outLength = Math.max(1, Math.round(input.length / ratio));
  const out = new Int16Array(outLength);
  for (let i = 0; i < outLength; i += 1) {
    const srcPos = i * ratio;
    const i0 = Math.min(Math.floor(srcPos), input.length - 1);
    const i1 = Math.min(i0 + 1, input.length - 1);
    const frac = srcPos - i0;
    const sample = input[i0] * (1 - frac) + input[i1] * frac;
    out[i] = floatToPcm16(sample);
  }
  return out;
}

/** 单声道下混：交错多声道 → 单声道（均值），供 16k 单声道 PCM16 前置（CAP-14）。 */
export function downmixToMono(input: Float32Array, channels: number): Float32Array {
  if (!Number.isInteger(channels) || channels < 1) {
    throw new Error("channels must be a positive integer");
  }
  if (channels === 1) {
    return input;
  }
  const frames = Math.floor(input.length / channels);
  const out = new Float32Array(frames);
  for (let f = 0; f < frames; f += 1) {
    let sum = 0;
    for (let c = 0; c < channels; c += 1) {
      sum += input[f * channels + c];
    }
    out[f] = sum / channels;
  }
  return out;
}

/** Continuous linear interpolation across AudioWorklet chunk boundaries.
 * Independent Math.round(chunk.length / ratio) calls accumulate clock drift.
 */
export class StreamingPcm16Resampler {
  private received = 0;
  private emitted = 0;
  private previousSample = 0;
  private sourceRate: number | null = null;

  push(input: Float32Array, inputRate: number, outputRate = TARGET_SAMPLE_RATE): Int16Array {
    if (!Number.isFinite(inputRate) || !Number.isFinite(outputRate) || inputRate <= 0 || outputRate <= 0) {
      throw new Error("sample rates must be positive finite numbers");
    }
    if (this.sourceRate !== null && this.sourceRate !== inputRate) {
      throw new Error("input sample rate changed within one capture");
    }
    this.sourceRate = inputRate;
    if (!input.length) return new Int16Array(0);
    const first = this.received;
    const last = first + input.length - 1;
    const ratio = inputRate / outputRate;
    const result: number[] = [];
    while (this.emitted * ratio <= last) {
      const position = this.emitted * ratio;
      const leftIndex = Math.floor(position);
      const fraction = position - leftIndex;
      // Defer an interpolation until its right-hand sample arrives.
      if (fraction > 0 && leftIndex + 1 > last) break;
      const left = leftIndex < first ? this.previousSample : input[leftIndex - first];
      const right = leftIndex + 1 <= last ? input[leftIndex + 1 - first] : left;
      result.push(floatToPcm16(left + (right - left) * fraction));
      this.emitted++;
    }
    this.received += input.length;
    this.previousSample = input[input.length - 1];
    return Int16Array.from(result);
  }

  /** Finish an incomplete interpolation by holding only the final physical sample. */
  flush(targetRate = TARGET_SAMPLE_RATE): Int16Array {
    const result: number[] = [];
    if (this.sourceRate !== null) {
      // Compute from the absolute output count, not repeatedly added floating
      // fractions (44100 Hz would otherwise drift by one sample per second).
      const expected = Math.ceil((this.received * targetRate) / this.sourceRate);
      while (this.emitted < expected) {
        result.push(floatToPcm16(this.previousSample));
        this.emitted++;
      }
    }
    this.received = 0;
    this.emitted = 0;
    this.previousSample = 0;
    this.sourceRate = null;
    return Int16Array.from(result);
  }
}