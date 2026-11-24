import { fetchSubmissionStatus, type SubmissionReceipt } from "./chat";

// No resend, no overlapping status requests, and no unbounded polling.
export function watchSubmission(
  submissionId: string,
  sessionId: string | null,
  signal: AbortSignal,
  onWaiting: () => void,
  onReceipt: (receipt: SubmissionReceipt) => void,
  onExhausted: () => void,
): () => void {
  const controller = new AbortController();
  let timer: number | undefined;
  let attempts = 0;
  const stop = () => {
    controller.abort();
    if (timer !== undefined) window.clearTimeout(timer);
    signal.removeEventListener("abort", stop);
  };
  const probe = async () => {
    if (controller.signal.aborted) return;
    onWaiting();
    const receipt = await fetchSubmissionStatus(submissionId, sessionId, controller.signal);
    if (controller.signal.aborted) return;
    if (receipt) {
      stop();
      onReceipt(receipt);
    } else if (++attempts < 6) {
      timer = window.setTimeout(() => void probe(), 5000);
    } else {
      stop();
      onExhausted();
    }
  };
  signal.addEventListener("abort", stop, { once: true });
  if (signal.aborted) stop();
  else timer = window.setTimeout(() => void probe(), 10000);
  return stop;
}

export function newSubmissionId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, "0")).join("");
}
