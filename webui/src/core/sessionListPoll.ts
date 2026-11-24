import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { fetchSessionJobsResult, fetchSessionScheduleResult, type ReadListResult } from "./api";
import { isAuthRequired, subscribeAuthRequired, useAuthRequired } from "./authSession";

type Snapshot<T> = { items: T[]; stale: boolean };
type Listener<T> = (snapshot: Snapshot<T>) => void;
type Reader<T> = (sessionId: string, signal: AbortSignal) => Promise<ReadListResult<T>>;
type Subscription = { unsubscribe: () => void; setIntervalMs: (ms: number) => void };
const EMPTY = { items: [], stale: false } as Snapshot<never>;
const READ_TIMEOUT_MS = 10000;

// One visible-tab read lifecycle per exact session and list type. This is
// presentation state only, never an execution receipt or an authorization cache.
export function createSessionListPoller<T>(read: Reader<T>) {
  function createEntry(sessionId: string, onEmpty: () => void) {
    const listeners = new Map<Listener<T>, number>();
    let snapshot: Snapshot<T> = EMPTY;
    let timer: number | undefined;
    let intervalMs = Infinity;
    let pending: { controller: AbortController; timeout: number; promise: Promise<void> } | undefined;

    function publish(next: Snapshot<T>) {
      snapshot = next;
      listeners.forEach((_ms, listener) => listener(next));
    }

    function invalidate() {
      const old = pending;
      pending = undefined;
      if (old) { window.clearTimeout(old.timeout); old.controller.abort(); }
    }

    function refresh(afterMutation = false): Promise<void> {
      if (!listeners.size || isAuthRequired()) return Promise.resolve();
      // A pre-mutation response must never overwrite a post-mutation refresh.
      if (afterMutation) invalidate();
      if (pending) return pending.promise;
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), READ_TIMEOUT_MS);
      const request = {
        controller,
        timeout,
        promise: Promise.resolve().then(() => controller.signal.aborted
          ? { ok: false, items: [], status: 0 }
          : read(sessionId, controller.signal)).then(
          result => {
            if (pending?.controller !== controller || !listeners.size || isAuthRequired()) return;
            publish(result.ok && !controller.signal.aborted
              ? { items: result.items, stale: false }
              : { ...snapshot, stale: true });
          },
          () => {
            if (pending?.controller === controller && listeners.size && !isAuthRequired()) {
              publish({ ...snapshot, stale: true });
            }
          },
        ).finally(() => {
          window.clearTimeout(timeout);
          if (pending?.controller === controller) pending = undefined;
        }),
      };
      pending = request;
      return request.promise;
    }

    function pollVisible() {
      if (!document.hidden) void refresh();
    }

    function reschedule() {
      const next = Math.min(...listeners.values());
      if (next === intervalMs) return;
      const faster = next < intervalMs;
      intervalMs = next;
      window.clearInterval(timer);
      timer = listeners.size ? window.setInterval(pollVisible, next) : undefined;
      if (faster) pollVisible();
    }

    const offAuth = subscribeAuthRequired(() => {
      invalidate();
      publish(EMPTY);
      if (!isAuthRequired()) pollVisible();
    });
    document.addEventListener("visibilitychange", pollVisible);

    return {
      refresh,
      subscribe(listener: Listener<T>, ms: number): Subscription {
        listeners.set(listener, ms);
        listener(snapshot);
        reschedule();
        return {
          setIntervalMs(next) {
            if (!listeners.has(listener)) return;
            listeners.set(listener, next);
            reschedule();
          },
          unsubscribe() {
            if (!listeners.delete(listener)) return;
            reschedule();
            if (listeners.size) return;
            invalidate();
            offAuth();
            document.removeEventListener("visibilitychange", pollVisible);
            onEmpty();
          },
        };
      },
    };
  }

  const entries = new Map<string, ReturnType<typeof createEntry>>();
  return {
    subscribe(sessionId: string, listener: Listener<T>, intervalMs: number): Subscription {
      let entry = entries.get(sessionId);
      if (!entry) {
        entry = createEntry(sessionId, () => entries.delete(sessionId));
        entries.set(sessionId, entry);
      }
      return entry.subscribe(listener, intervalMs);
    },
    refresh(sessionId: string, afterMutation = false): Promise<void> {
      return entries.get(sessionId)?.refresh(afterMutation) ?? Promise.resolve();
    },
  };
}

type Poller<T> = ReturnType<typeof createSessionListPoller<T>>;
export const sessionJobs = createSessionListPoller(fetchSessionJobsResult);
export const sessionSchedule = createSessionListPoller(fetchSessionScheduleResult);

export function useSessionList<T>(
  poller: Poller<T>, sessionId: string | null, enabled: boolean, intervalMs: number,
) {
  const authRequired = useAuthRequired();
  const [state, setState] = useState<{ sessionId: string; snapshot: Snapshot<T> } | null>(null);
  const subscription = useRef<Subscription | null>(null);
  const interval = useRef(intervalMs);
  interval.current = intervalMs;
  useLayoutEffect(() => {
    if (!enabled || !sessionId) { setState(null); return; }
    const sub = poller.subscribe(sessionId, snapshot => setState({ sessionId, snapshot }), interval.current);
    subscription.current = sub;
    return () => {
      sub.unsubscribe();
      subscription.current = null;
    };
  }, [poller, sessionId, enabled]);
  useEffect(() => {
    subscription.current?.setIntervalMs(intervalMs);
  }, [intervalMs]);
  const refresh = useCallback((afterMutation = false) => {
    return sessionId ? poller.refresh(sessionId, afterMutation) : Promise.resolve();
  }, [poller, sessionId]);
  const snapshot = enabled && !authRequired && state?.sessionId === sessionId ? state.snapshot : EMPTY;
  return { ...snapshot, refresh };
}
