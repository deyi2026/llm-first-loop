import { useEffect, useRef } from "react";

/**
 * Keep a non-modal popover dismissible without every component reimplementing
 * document listeners.  Pointer dismissal is capture-phase so nested controls do
 * not need to coordinate propagation; events inside the bound root are ignored.
 */
export function useDismissibleLayer<T extends HTMLElement>(
  open: boolean,
  onDismiss: () => void
) {
  const rootRef = useRef<T>(null);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (!rootRef.current?.contains(target)) onDismiss();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onDismiss();
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onDismiss]);

  return rootRef;
}
