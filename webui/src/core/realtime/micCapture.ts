import type { CapturePipeline } from "./capturePipeline";

export interface MediaStreamTrackLike { stop(): void; }
export interface MediaStreamLike { getTracks(): MediaStreamTrackLike[]; }
export interface MediaDevicesLike {
  getUserMedia(constraints: { audio: unknown }): Promise<MediaStreamLike>;
}
export interface WorkletPortLike {
  onmessage: ((event: { data: { samples: Float32Array; sampleRate: number; channels?: number } }) => void) | null;
  close(): void;
}
export interface MicCaptureOptions {
  mediaDevices: MediaDevicesLike;
  pipeline: CapturePipeline;
  onFrame: (frame: Int16Array) => void;
  createPort: (stream: MediaStreamLike) => WorkletPortLike | Promise<WorkletPortLike>;
  constraints?: { audio: unknown };
}

export class MicCapture {
  private stream: MediaStreamLike | null = null;
  private port: WorkletPortLike | null = null;
  private pressed = false;
  private generation = 0;

  constructor(private readonly options: MicCaptureOptions) {}
  get micEnabled(): boolean { return this.stream !== null && this.port !== null; }
  get pressedDown(): boolean { return this.pressed; }

  async press(): Promise<boolean> {
    if (this.pressed) return this.micEnabled;
    this.pressed = true;
    const generation = ++this.generation;
    let stream: MediaStreamLike | null = null;
    let port: WorkletPortLike | null = null;
    const active = () => this.pressed && this.generation === generation;
    try {
      stream = await this.options.mediaDevices.getUserMedia(this.options.constraints ?? { audio: true });
      if (!active()) {
        for (const track of stream.getTracks()) track.stop();
        return false;
      }
      port = await this.options.createPort(stream);
      if (!active()) {
        port.close();
        for (const track of stream.getTracks()) track.stop();
        return false;
      }
      this.stream = stream;
      this.port = port;
      port.onmessage = (event) => this.handleSamples(event.data);
      return true;
    } catch {
      port?.close();
      for (const track of stream?.getTracks() ?? []) track.stop();
      if (generation === this.generation) this.pressed = false;
      return false;
    }
  }

  release(): void {
    this.pressed = false;
    this.generation++;
    this.stopStream();
    for (const frame of this.options.pipeline.flush()) this.options.onFrame(frame);
  }
  cancel(): void {
    this.pressed = false;
    this.generation++;
    this.stopStream();
    this.options.pipeline.flush(); // Discard the cancelled tail before another press.
  }
  onBlur(): void { if (this.pressed) this.release(); }
  handleSamples(data: { samples: Float32Array; sampleRate: number; channels?: number }): void {
    if (!this.pressed || this.stream === null) return;
    for (const frame of this.options.pipeline.push(data.samples, data.sampleRate, data.channels ?? 1)) {
      this.options.onFrame(frame);
    }
  }
  private stopStream(): void {
    if (this.port) {
      this.port.onmessage = null;
      this.port.close();
      this.port = null;
    }
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream = null;
  }
}
