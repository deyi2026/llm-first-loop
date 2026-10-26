// M1：本地 TTS 播放输出接线（`T-M1-12`）：`PlaybackQueue` 分片 → `AudioBufferSourceNode`。
//
// - 播放按 `response_id` 排队（由 `PlaybackQueue` 承担）；分片自然结束后**自动接续**下一段；
// - 下行二进制为**无头 16k 单声道 PCM16**：播放前包 WAV 头再 `decodeAudioData`（不猜格式）；
// - **本地立即停播**：`stop()` 直接停源，**不等服务端确认**（D27、RTM-PLY-02）；
// - autoplay 被拒/解码失败：**降级为不播放并如实回调**（分片不重试轰炸；文本已在对话中保留）；
// - `AudioContext` 注入，jsdom 下可用 fake 验证接线；真实扬声器与延迟不在此验证（RTM-EVD-06）。

import { TARGET_SAMPLE_RATE } from "./resampler";
import type { PlaybackChunk, PlaybackQueue } from "./playbackQueue";

export interface AudioBufferSourceLike {
  buffer: unknown;
  onended: (() => void) | null;
  connect(destination: unknown): void;
  start(when?: number): void;
  stop(): void;
}

export interface AudioContextLike {
  destination: unknown;
  decodeAudioData(data: ArrayBuffer): Promise<unknown>;
  createBufferSource(): AudioBufferSourceLike;
  /** 浏览器 AudioContext 原生字段；fake 可不提供（缺省视为未挂起）。 */
  state?: string;
  /** 87aa41fd2 语义移植：autoplay 策略下挂起的 context 靠用户手势 resume 才能出声。 */
  resume?(): Promise<void>;
  /** 释放底层上下文（浏览器原生 `close()`；fake 可不提供 = 无需释放）。 */
  close?(): Promise<void>;
}

/** 无头 16k 单声道 PCM16 → WAV（与服务端 `pcm16_to_wav` 同构，供 `decodeAudioData`）。 */
export function pcm16ToWav(pcm: ArrayBuffer): ArrayBuffer {
  const bytes = new Uint8Array(pcm);
  const header = new ArrayBuffer(44);
  const view = new DataView(header);
  const writeAscii = (offset: number, text: string): void => {
    for (let i = 0; i < text.length; i += 1) {
      view.setUint8(offset + i, text.charCodeAt(i));
    }
  };
  writeAscii(0, "RIFF");
  view.setUint32(4, 36 + bytes.length, true);
  writeAscii(8, "WAVE");
  writeAscii(12, "fmt ");
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, TARGET_SAMPLE_RATE, true);
  view.setUint32(28, TARGET_SAMPLE_RATE * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeAscii(36, "data");
  view.setUint32(40, bytes.length, true);
  const out = new Uint8Array(44 + bytes.length);
  out.set(new Uint8Array(header), 0);
  out.set(bytes, 44);
  return out.buffer;
}

export class PlaybackOutput {
  private source: AudioBufferSourceLike | null = null;
  private playing = false;

  constructor(
    private readonly options: {
      playback: PlaybackQueue;
      audioContext: AudioContextLike;
      /** 播放降级（autoplay 被拒/解码失败）：携带分片归属 `responseId`，由上层按回复去重提示。 */
      onError?: (error: unknown, responseId: string) => void;
      /** 87aa41fd2 语义移植：实际出声/全部播完的可见状态钩子（驱动 playbackState）。 */
      onStart?: () => void;
      onEnd?: () => void;
    },
  ) {}

  get isPlaying(): boolean {
    return this.playing;
  }

  /** 播放当前分片；无分片返回 false（不静默伪造播放）。 */
  async playNext(): Promise<boolean> {
    if (this.playing) {
      return true; // 已在播：等待自然结束自动接续，不重启
    }
    const chunk = this.options.playback.peek();
    if (chunk === null) {
      return false;
    }
    if (this.options.audioContext.state === "suspended") {
      // 87aa41fd2 语义移植：挂起 context 先尝试一次 resume()（用户手势后的合成请求
      // 常因此恢复出声）；resume 不可用/仍挂起才如实降级（分片保留，不报错轰炸）。
      try {
        await this.options.audioContext.resume?.();
      } catch {
        /* resume 失败走既有降级路径 */
      }
      if (this.options.audioContext.state === "suspended") {
        this.options.onError?.(new Error("audio_context_suspended"), chunk.responseId);
        return false;
      }
    }
    try {
      const data = this.prepareData(chunk);
      const decoded = await this.options.audioContext.decodeAudioData(data);
      const source = this.options.audioContext.createBufferSource();
      source.buffer = decoded;
      source.connect(this.options.audioContext.destination);
      source.onended = (): void => {
        this.playing = false;
        this.source = null;
        const next = this.options.playback.advance();
        if (next !== null) {
          void this.playNext();
        } else {
          this.options.onEnd?.();
        }
      };
      source.start();
      this.source = source;
      this.playing = true;
      this.options.onStart?.();
      return true;
    } catch (error) {
      // 解码失败：丢弃该分片（避免同一分片反复失败重试），保留文本并如实回调。
      this.options.playback.advance();
      this.options.onError?.(error, chunk.responseId);
      return false;
    }
  }

  private prepareData(chunk: PlaybackChunk): ArrayBuffer {
    return chunk.format === "pcm16" ? pcm16ToWav(chunk.data) : chunk.data;
  }

  /** 本地立即停播（客户端开口打断；不等服务端确认）。 */
  stop(): boolean {
    if (this.source === null) {
      return false;
    }
    this.source.stop();
    this.source.onended = null;
    this.source = null;
    this.playing = false;
    return true;
  }

  /**
   * 释放底层 `AudioContext`（disable/卸载时调用）：先停当前播放（断开 onended
   * 接续链），再 close；close 的 reject（已关闭/不支持等）与同步抛出均吞掉——
   * teardown 不因释放失败中断，也不改变其它错误路径。
   */
  dispose(): void {
    this.stop();
    try {
      void this.options.audioContext.close?.().catch(() => undefined);
    } catch {
      /* 同步抛出（极端注入）同样吞掉：释放尽力而为 */
    }
  }
}