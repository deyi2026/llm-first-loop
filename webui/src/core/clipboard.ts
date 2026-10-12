export type ClipboardWriteMethod = "clipboard-api" | "exec-command";

export interface ClipboardWriteResult {
  ok: boolean;
  method?: ClipboardWriteMethod;
}

function prefersSynchronousFallback(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.matchMedia?.("(hover: none), (pointer: coarse)").matches ?? false;
  } catch {
    return false;
  }
}

function fallbackCopy(text: string): boolean {
  if (typeof document === "undefined" || !document.body) return false;
  const execCommand = document.execCommand?.bind(document);
  if (!execCommand) return false;

  const active =
    document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.readOnly = true;
  textarea.tabIndex = -1;
  textarea.setAttribute("aria-hidden", "true");
  Object.assign(textarea.style, {
    position: "fixed",
    top: "0",
    left: "0",
    width: "1px",
    height: "1px",
    padding: "0",
    border: "0",
    margin: "0",
    opacity: "0",
    pointerEvents: "none",
    fontSize: "16px",
  });

  document.body.appendChild(textarea);
  try {
    try {
      textarea.focus({ preventScroll: true });
    } catch {
      textarea.focus();
    }
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    return execCommand("copy") === true;
  } catch {
    return false;
  } finally {
    textarea.remove();
    if (active?.isConnected) {
      try {
        active.focus({ preventScroll: true });
      } catch {
        active.focus();
      }
    }
  }
}

/**
 * Mobile/domain-safe clipboard writer.
 *
 * Clipboard API is preferred, but it can be unavailable or rejected on
 * mobile Safari, non-secure origins, embedded browsers, or permission-limited
 * enterprise shells.
 *
 * On coarse-pointer/touch UIs the synchronous legacy copy path must run before
 * awaiting Clipboard API work. Safari/WebKit requires transient user activation
 * for clipboard writes; waiting for an async rejection and only then falling
 * back can lose that activation and make both paths fail.
 */
export async function writeClipboardText(text: string): Promise<ClipboardWriteResult> {
  const clipboard =
    typeof navigator !== "undefined" ? navigator.clipboard : undefined;
  const explicitlyInsecure =
    typeof window !== "undefined" && window.isSecureContext === false;
  const synchronousFirst = explicitlyInsecure || prefersSynchronousFallback();

  if (synchronousFirst) {
    if (fallbackCopy(text)) {
      return { ok: true, method: "exec-command" };
    }
    if (explicitlyInsecure) return { ok: false };
  }

  try {
    if (clipboard?.writeText) {
      await clipboard.writeText(text);
      return { ok: true, method: "clipboard-api" };
    }
  } catch {
    // Desktop/keyboard flows can still use the legacy path after rejection.
    // Touch/coarse-pointer flows already tried it synchronously while the
    // trusted user gesture was definitely active.
  }

  if (synchronousFirst) return { ok: false };
  return fallbackCopy(text)
    ? { ok: true, method: "exec-command" }
    : { ok: false };
}
