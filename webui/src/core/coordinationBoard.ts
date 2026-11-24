// One in-flight read for both the Lane Board and Coordination Channel.
// The response is a read-only snapshot; do not cache across polling ticks.
import { api } from "./api";
import { isAuthRequired, subscribeAuthRequired } from "./authSession";

let inFlight: Promise<Record<string, unknown> | null> | null = null;

export function fetchCoordinationBoard<T extends object>(): Promise<T | null> {
  if (isAuthRequired()) return Promise.resolve(null);
  if (inFlight) return inFlight as Promise<T | null>;
  const pending = (async (): Promise<Record<string, unknown> | null> => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const { status, data } = await api<Record<string, unknown>>(
        "/api/v1/coordination/board", { signal: controller.signal }
      );
      return status === 200 && data !== null && typeof data === "object" && !Array.isArray(data)
        ? data : null;
    } finally {
      window.clearTimeout(timeout);
    }
  })();
  const tracked = pending.finally(() => { if (inFlight === tracked) inFlight = null; });
  inFlight = tracked;
  return inFlight as Promise<T | null>;
}

// A single visible-tab polling lifecycle for all mounted Board consumers.
// The snapshot exists only while subscribed; it is not an execution receipt.
type Snapshot = Record<string, unknown> | null;
const listeners = new Set<(value: Snapshot) => void>();
let latest: Snapshot | undefined;
let timer: number | undefined;
let epoch = 0;
let refresh: Promise<void> | undefined;
let unsubscribeAuth: (() => void) | undefined;

function publish(value: Snapshot): void {
  latest = value;
  listeners.forEach(listener => listener(value));
}

export function refreshCoordinationBoard(): Promise<void> {
  if (!listeners.size) return Promise.resolve();
  if (refresh) return refresh;
  const owner = epoch;
  const pending = fetchCoordinationBoard<Record<string, unknown>>().then(
    value => { if (owner === epoch && listeners.size) publish(isAuthRequired() ? null : value); },
    () => { if (owner === epoch && listeners.size) publish(null); },
  );
  refresh = pending.finally(() => { if (owner === epoch) refresh = undefined; });
  return refresh;
}

function pollVisible(): void {
  if (!document.hidden && !isAuthRequired()) void refreshCoordinationBoard();
}

export function subscribeCoordinationBoard<T extends object>(listener: (value: T | null) => void): () => void {
  const receive = (value: Snapshot) => listener(value as T | null);
  listeners.add(receive);
  if (listeners.size === 1) {
    timer = window.setInterval(pollVisible, 10000);
    document.addEventListener("visibilitychange", pollVisible);
    unsubscribeAuth = subscribeAuthRequired(() => {
      // A login boundary invalidates old responses and the shared snapshot.
      epoch++;
      refresh = undefined;
      inFlight = null;
      latest = undefined;
      if (isAuthRequired()) publish(null);
      else pollVisible();
    });
    if (isAuthRequired()) publish(null);
    else pollVisible();
  } else if (latest !== undefined) {
    receive(isAuthRequired() ? null : latest);
  }
  return () => {
    if (!listeners.delete(receive)) return;
    if (listeners.size) return;
    epoch++;
    latest = undefined;
    refresh = undefined;
    window.clearInterval(timer);
    timer = undefined;
    document.removeEventListener("visibilitychange", pollVisible);
    unsubscribeAuth?.();
    unsubscribeAuth = undefined;
  };
}
