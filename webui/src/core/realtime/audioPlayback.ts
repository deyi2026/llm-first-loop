import type { PlaybackQueue } from "./playbackQueue";

export interface AudioBufferSourceLike {
  buffer: unknown;
  onended: (() => void) | null;
  connect(destination: unknown): void;
  start(when?: number): void;
  stop(): void;
}
export interface AudioContextLike {
  destination: unknown;
  state?: string;
  resume?(): Promise<void>;
  decodeAudioData(data: ArrayBuffer): Promise<unknown>;
  createBufferSource(): AudioBufferSourceLike;
}
export interface PlaybackOutputCallbacks {
  onPlaybackStart?: () => void;
  onPlaybackEnd?: () => void;
  onPlaybackError?: () => void;
}
export class PlaybackOutput {
  private source: AudioBufferSourceLike | null = null;
  private playing = false;
  private decoding = false;
  private generation = 0;
  constructor(private readonly options: {
    playback: PlaybackQueue;
    audioContext: AudioContextLike;
    callbacks?: PlaybackOutputCallbacks;
  }) {}
  get isPlaying(): boolean { return this.playing; }
  async playNext(): Promise<boolean> {
    if (this.playing || this.decoding) return false;
    const chunk = this.options.playback.peek();
    if (!chunk) return false;
    const generation = this.generation;
    this.decoding = true;
    let decoded: unknown;
    try {
      // Mobile browsers may suspend an AudioContext while the LLM is thinking.
      // Resume it again when the user-authorized voice reply actually arrives.
      if (this.options.audioContext.state && this.options.audioContext.state !== "running") {
        if (!this.options.audioContext.resume) throw new Error("AudioContext is suspended and cannot resume");
        await this.options.audioContext.resume();
        if (this.options.audioContext.state && this.options.audioContext.state !== "running") {
          throw new Error("AudioContext did not resume");
        }
      }
      decoded = await this.options.audioContext.decodeAudioData(chunk.data);
    }
    catch {
      if (generation === this.generation) {
        this.options.playback.advance();
        this.decoding = false;
        this.options.callbacks?.onPlaybackError?.();
        void this.playNext();
      }
      return false;
    }
    if (generation !== this.generation) { this.decoding = false; return false; }
    this.decoding = false;
    const source = this.options.audioContext.createBufferSource();
    source.buffer = decoded;
    source.connect(this.options.audioContext.destination);
    source.onended = () => {
      if (generation !== this.generation) return;
      this.playing = false;
      this.source = null;
      const next = this.options.playback.advance();
      if (!next) this.options.callbacks?.onPlaybackEnd?.();
      void this.playNext();
    };
    this.source = source;
    try {
      source.start();
      this.playing = true;
      this.options.callbacks?.onPlaybackStart?.();
    } catch {
      this.playing = false;
      this.source = null;
      this.options.playback.advance();
      this.options.callbacks?.onPlaybackError?.();
      void this.playNext();
      return false;
    }
    return true;
  }
  stop(): boolean {
    const stopped = this.playing || this.decoding;
    this.generation++;
    if (this.source) {
      this.source.onended = null;
      this.source.stop();
      this.source = null;
    }
    this.playing = false;
    this.decoding = false;
    return stopped;
  }
}
