// One in-flight read for both the Lane Board and Coordination Channel.
// The response is a read-only snapshot; do not cache across polling ticks.
import { api } from "./api";
import { isAuthRequired } from "./authSession";

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
  inFlight = pending.finally(() => { inFlight = null; });
  return inFlight as Promise<T | null>;
}
