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
  decodeAudioData(data: ArrayBuffer): Promise<unknown>;
  createBufferSource(): AudioBufferSourceLike;
}
export class PlaybackOutput {
  private source: AudioBufferSourceLike | null = null;
  private playing = false;
  private decoding = false;
  private generation = 0;
  constructor(private readonly options: { playback: PlaybackQueue; audioContext: AudioContextLike }) {}
  get isPlaying(): boolean { return this.playing; }
  async playNext(): Promise<boolean> {
    if (this.playing || this.decoding) return false;
    const chunk = this.options.playback.peek();
    if (!chunk) return false;
    const generation = this.generation;
    this.decoding = true;
    let decoded: unknown;
    try { decoded = await this.options.audioContext.decodeAudioData(chunk.data); }
    catch {
      if (generation === this.generation) {
        this.options.playback.advance();
        this.decoding = false;
        void this.playNext();
      }
      return false;
    }
    if (generation !== this.generation) return false;
    this.decoding = false;
    const source = this.options.audioContext.createBufferSource();
    source.buffer = decoded;
    source.connect(this.options.audioContext.destination);
    source.onended = () => {
      if (generation !== this.generation) return;
      this.playing = false;
      this.source = null;
      this.options.playback.advance();
      void this.playNext();
    };
    this.source = source;
    this.playing = true;
    source.start();
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
