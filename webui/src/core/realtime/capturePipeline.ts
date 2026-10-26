// M1：麦克风采集管线（`T-M1-9`）：下混单声道 → 16k 重采样 → 定长 PCM16 分帧。
//
// - 参数来自能力档案（16k/单声道/pcm16），不散落硬编码（RTM-AUD-01、CAP-14）；
// - `flush()` 收尾：把不足一帧的余量作为一帧发出（对应流式会话 `flush()` 语义，RTM-CAP-14）；
// - 采集/播放的真实设备路径与延迟不在此验证（RTM-EVD-06）。

import { TARGET_SAMPLE_RATE, downmixToMono, StreamingPcm16Resampler } from "./resampler";

export interface CaptureOptions {
  targetRate?: number;
  /** 每帧样本数；16k 下 20ms = 320 样本。 */
  frameSamples?: number;
}

const DEFAULT_FRAME_SAMPLES = 320;

export class CapturePipeline {
  private remainder = new Int16Array(0);
  private readonly resampler = new StreamingPcm16Resampler();

  constructor(private readonly options: CaptureOptions = {}) {}

  private get targetRate(): number {
    return this.options.targetRate ?? TARGET_SAMPLE_RATE;
  }

  private get frameSamples(): number {
    return this.options.frameSamples ?? DEFAULT_FRAME_SAMPLES;
  }

  /** 输入任意采样率/声道的一段浮点样本 → 输出若干 16k 单声道 PCM16 定长帧。 */
  push(samples: Float32Array, sampleRate: number, channels = 1): Int16Array[] {
    const mono = downmixToMono(samples, channels);
    const resampled = this.resampler.push(mono, sampleRate, this.targetRate);
    return this.frame(resampled);
  }

  /** 收尾：不足一帧的余量作为最后一帧发出（不静默丢弃尾段）。 */
  flush(): Int16Array[] {
    const final = this.resampler.flush(this.targetRate);
    const complete = final.length ? this.frame(final) : [];
    const tail = this.remainder;
    this.remainder = new Int16Array(0);
    return tail.length ? [...complete, tail] : complete;
  }

  get pendingSamples(): number {
    return this.remainder.length;
  }

  private frame(pcm: Int16Array): Int16Array[] {
    const combined = new Int16Array(this.remainder.length + pcm.length);
    combined.set(this.remainder, 0);
    combined.set(pcm, this.remainder.length);
    const frames: Int16Array[] = [];
    let offset = 0;
    while (combined.length - offset >= this.frameSamples) {
      frames.push(combined.slice(offset, offset + this.frameSamples));
      offset += this.frameSamples;
    }
    this.remainder = combined.slice(offset);
    return frames;
  }
}