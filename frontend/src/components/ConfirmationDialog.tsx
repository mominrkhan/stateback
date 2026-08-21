import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";

const FOCUSABLE = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export interface ConfirmationDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  pending?: boolean;
  pendingLabel?: string;
  children: ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
  confirmDisabled?: boolean;
}

export function ConfirmationDialog({
  open,
  title,
  description,
  confirmLabel,
  pending = false,
  pendingLabel = "Submitting command…",
  children,
  onCancel,
  onConfirm,
  confirmDisabled = false,
}: ConfirmationDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    headingRef.current?.focus();
    return () => restoreFocusRef.current?.focus();
  }, [open]);

  if (!open) return null;

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && !pending) {
      event.preventDefault();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (focusable.length === 0) {
      event.preventDefault();
      headingRef.current?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="confirmation-dialog__backdrop">
      <div
        ref={panelRef}
        className="confirmation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onKeyDown={handleKeyDown}
      >
        <header className="confirmation-dialog__header">
          <h2 ref={headingRef} id={titleId} tabIndex={-1}>{title}</h2>
          <p id={descriptionId}>{description}</p>
        </header>
        <div className="confirmation-dialog__body">{children}</div>
        <div className="confirmation-dialog__actions">
          <button type="button" className="primitive-button" disabled={pending} onClick={onCancel}>Cancel</button>
          <button
            type="button"
            className="primitive-button primitive-button--danger"
            disabled={pending || confirmDisabled}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
        <p className="confirmation-dialog__pending" role="status" aria-live="polite">
          {pending ? pendingLabel : ""}
        </p>
      </div>
    </div>
  );
}
