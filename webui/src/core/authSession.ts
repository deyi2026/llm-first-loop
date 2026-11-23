// Browser login expiry is a UI fact, not authority to restart a Run or replay writes.
// Only an explicit HTTP 401 changes this state. A new full-page login resets it.
import { useSyncExternalStore } from "react";

let required = false;
const listeners = new Set<() => void>();
const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
const snapshot = () => required;

export function isAuthRequired(): boolean { return required; }
export function subscribeAuthRequired(listener: () => void): () => void { return subscribe(listener); }
export function useAuthRequired(): boolean { return useSyncExternalStore(subscribe, snapshot); }

export function reportUnauthorized(status: number): void {
  if (status !== 401 || required) return;
  required = true;
  listeners.forEach((listener) => listener());
}

export function clearAuthRequired(): void {
  if (!required) return;
  required = false;
  listeners.forEach((listener) => listener());
}
