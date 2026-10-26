import type { MediaStreamLike, WorkletPortLike } from "./micCapture";

// Connect the selected microphone to a real audio graph. The worklet is bundled
// as an asset, so production and Vite development use the same capture code.
export async function createBrowserCapturePort(stream: MediaStreamLike): Promise<WorkletPortLike> {
  const context = new AudioContext();
  let source: MediaStreamAudioSourceNode | null = null;
  let node: AudioWorkletNode | null = null;
  try {
    await context.resume();
    await context.audioWorklet.addModule(new URL("./captureWorklet.js", import.meta.url).href);
    source = context.createMediaStreamSource(stream as MediaStream);
    node = new AudioWorkletNode(context, "lfl-pcm-capture");
    source.connect(node);
    // The processor outputs silence; connecting it keeps the capture graph alive.
    node.connect(context.destination);
    const port = node.port;
    let handler: WorkletPortLike["onmessage"] = null;
    port.onmessage = (event) => handler?.({ data: event.data });
    return {
      get onmessage() { return handler; },
      set onmessage(value) { handler = value; },
      close() {
        handler = null;
        port.onmessage = null;
        port.close();
        source?.disconnect();
        node?.disconnect();
        void context.close();
      },
    };
  } catch (error) {
    source?.disconnect();
    node?.disconnect();
    await context.close();
    throw error;
  }
}
