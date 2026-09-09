/**
 * Browser-only session deep links.
 *
 * The URL is a navigation fact, not a second source of session truth: callers
 * must validate the requested id against the server-provided session list.
 */
export function readSessionIdFromLocation(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const value = new URL(window.location.href).searchParams.get("session")?.trim();
    return value || null;
  } catch {
    return null;
  }
}

export function buildSessionShareUrl(sessionId: string, href?: string): string {
  const base = href ?? (typeof window !== "undefined" ? window.location.href : "http://localhost/");
  const url = new URL(base);
  if (sessionId) url.searchParams.set("session", sessionId);
  else url.searchParams.delete("session");
  return url.toString();
}

export function syncSessionIdInLocation(sessionId: string | null): void {
  if (typeof window === "undefined" || typeof history === "undefined") return;
  try {
    const url = new URL(window.location.href);
    if (sessionId) url.searchParams.set("session", sessionId);
    else url.searchParams.delete("session");
    history.replaceState(history.state, "", `${url.pathname}${url.search}${url.hash}`);
  } catch {
    // Navigation metadata is fail-open; it must never block a chat session.
  }
}
