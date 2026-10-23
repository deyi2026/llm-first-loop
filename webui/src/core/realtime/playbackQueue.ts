// M1（T-M1-9 / T-M1-12）：本地播放队列与**客户端停播优先**（RTM-PLY-01/02/07、D27）。
//
// 语义：
// - 音频按 `response_id` 归并排队；旧代次（`connection_epoch`）不得更新当前播放；
// - **客户端开口打断**：本地立即停播（**不等服务端确认**）；
// - 本模块为纯逻辑（可 vitest 验证）；真实扬声器与停播延迟不在此验证（RTM-EVD-06、PRF-02）。

export interface PlaybackChunk {
  responseId: string;
  connectionEpoch: number;
  data: ArrayBuffer;
}

export interface PlaybackSnapshot {
  playing: boolean;
  currentResponseId: string | null;
  queued: number;
  stoppedReason: string | null;
}

export class PlaybackQueue {
  private readonly queue: PlaybackChunk[] = [];
  private current: PlaybackChunk | null = null;
  private stoppedReason: string | null = null;

  constructor(private readonly epochProvider: () => number) {}

  /** 入队一段本地 TTS 音频；旧代次直接拒绝（不得更新当前会话）。 */
  enqueue(chunk: PlaybackChunk): boolean {
    if (chunk.connectionEpoch < this.epochProvider()) {
      return false;
    }
    if (this.current === null) {
      this.current = chunk;
      this.stoppedReason = null;
      return true;
    }
    this.queue.push(chunk);
    return true;
  }

  /** 当前播放分片结束：推进到下一段（同 `response_id` 连续播放）。 */
  advance(): PlaybackChunk | null {
    this.current = this.queue.shift() ?? null;
    return this.current;
  }

  /**
   * 客户端打断：**本地立即停播**。
   * - 指定 `responseId` 时仅停该回复；
   * - 缺省停全部（用户开口的自然语义）；
   * 返回是否确实停止了在播内容（区分「本就在停」与「已停止」）。
   */
  interrupt(responseId?: string): boolean {
    const target = responseId ?? this.current?.responseId;
    if (target === undefined) {
      return false;
    }
    const stoppedCurrent = this.current !== null && (responseId === undefined || this.current.responseId === target);
    this.queue.splice(
      0,
      this.queue.length,
      ...this.queue.filter((chunk) => chunk.responseId !== target),
    );
    if (stoppedCurrent) {
      this.current = null;
      this.stoppedReason = responseId === undefined ? "user_barge_in" : "reply_cancel";
    }
    return stoppedCurrent;
  }

  clear(): void {
    this.queue.length = 0;
    this.current = null;
    this.stoppedReason = "cleared";
  }

  snapshot(): PlaybackSnapshot {
    return {
      playing: this.current !== null,
      currentResponseId: this.current?.responseId ?? null,
      queued: this.queue.length,
      stoppedReason: this.stoppedReason,
    };
  }
}