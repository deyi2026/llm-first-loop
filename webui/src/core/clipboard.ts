export type ClipboardWriteMethod = "clipboard-api" | "exec-command";

export interface ClipboardWriteResult {
  ok: boolean;
  method?: ClipboardWriteMethod;
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
 * enterprise shells. The synchronous execCommand fallback preserves the user
 * gesture and keeps those environments usable.
 */
export async function writeClipboardText(text: string): Promise<ClipboardWriteResult> {
  const clipboard =
    typeof navigator !== "undefined" ? navigator.clipboard : undefined;
  const explicitlyInsecure =
    typeof window !== "undefined" && window.isSecureContext === false;
  if (explicitlyInsecure) {
    return fallbackCopy(text)
      ? { ok: true, method: "exec-command" }
      : { ok: false };
  }
  try {
    if (clipboard?.writeText) {
      await clipboard.writeText(text);
      return { ok: true, method: "clipboard-api" };
    }
  } catch {
    // Fall through to the synchronous legacy path.
  }
  return fallbackCopy(text)
    ? { ok: true, method: "exec-command" }
    : { ok: false };
}
