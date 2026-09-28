import { afterEach, describe, expect, it, vi } from "vitest";
import { writeClipboardText } from "./clipboard";

const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const originalSecureContext = Object.getOwnPropertyDescriptor(window, "isSecureContext");
const originalExecCommand = Object.getOwnPropertyDescriptor(document, "execCommand");

function setClipboard(value: unknown) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value,
  });
}

function setSecureContext(value: boolean | undefined) {
  Object.defineProperty(window, "isSecureContext", {
    configurable: true,
    value,
  });
}

function setExecCommand(fn: ((command: string) => boolean) | undefined) {
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: fn,
  });
}

function restoreProperty(
  target: object,
  key: PropertyKey,
  descriptor: PropertyDescriptor | undefined
) {
  if (descriptor) {
    Object.defineProperty(target, key, descriptor);
  } else {
    delete (target as Record<PropertyKey, unknown>)[key];
  }
}

afterEach(() => {
  restoreProperty(navigator, "clipboard", originalClipboard);
  restoreProperty(window, "isSecureContext", originalSecureContext);
  restoreProperty(document, "execCommand", originalExecCommand);
  document.querySelectorAll("textarea[aria-hidden='true']").forEach((node) => node.remove());
});

describe("writeClipboardText", () => {
  it("uses Clipboard API when it is available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const execCommand = vi.fn(() => true);
    setSecureContext(true);
    setClipboard({ writeText });
    setExecCommand(execCommand);

    await expect(writeClipboardText("hello")).resolves.toEqual({
      ok: true,
      method: "clipboard-api",
    });
    expect(writeText).toHaveBeenCalledWith("hello");
    expect(execCommand).not.toHaveBeenCalled();
  });

  it("uses synchronous fallback on explicitly insecure domain origins", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const execCommand = vi.fn(() => true);
    setSecureContext(false);
    setClipboard({ writeText });
    setExecCommand(execCommand);

    await expect(writeClipboardText("domain copy")).resolves.toEqual({
      ok: true,
      method: "exec-command",
    });
    expect(writeText).not.toHaveBeenCalled();
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea[aria-hidden='true']")).toBeNull();
  });

  it("falls back when Clipboard API rejects", async () => {
    const writeText = vi.fn().mockRejectedValue(new DOMException("denied"));
    const execCommand = vi.fn(() => true);
    setSecureContext(true);
    setClipboard({ writeText });
    setExecCommand(execCommand);

    await expect(writeClipboardText("fallback")).resolves.toEqual({
      ok: true,
      method: "exec-command",
    });
    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("restores the previously focused input after fallback copy", async () => {
    setSecureContext(false);
    setClipboard(undefined);
    setExecCommand(() => true);
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    expect(document.activeElement).toBe(input);

    await expect(writeClipboardText("keep-focus")).resolves.toEqual({
      ok: true,
      method: "exec-command",
    });
    expect(document.activeElement).toBe(input);
    input.remove();
  });

  it("reports failure when neither path can copy", async () => {
    setSecureContext(false);
    setClipboard(undefined);
    setExecCommand(() => false);

    await expect(writeClipboardText("cannot-copy")).resolves.toEqual({ ok: false });
  });
});
