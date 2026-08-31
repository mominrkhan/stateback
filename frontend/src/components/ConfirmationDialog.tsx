import { Dialog } from "@base-ui/react/dialog";
import { TriangleAlert, X } from "lucide-react";
import { useLayoutEffect, useRef, type ReactNode } from "react";

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

export function ConfirmationDialog({ open, title, description, confirmLabel, pending = false, pendingLabel = "Submitting command…", children, onCancel, onConfirm, confirmDisabled = false }: ConfirmationDialogProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => { if (open) heading.current?.focus(); }, [open]);
  return (
    <Dialog.Root open={open} onOpenChange={(nextOpen) => { if (!nextOpen && !pending) onCancel(); }}>
      <Dialog.Portal>
        <Dialog.Backdrop className="confirmation-dialog__backdrop" />
        <Dialog.Viewport className="confirmation-dialog__viewport">
          <Dialog.Popup className="confirmation-dialog" initialFocus={heading}>
            <header className="confirmation-dialog__header">
              <span className="confirmation-dialog__symbol" aria-hidden="true"><TriangleAlert size={18} /></span>
              <div><Dialog.Title ref={heading} tabIndex={-1}>{title}</Dialog.Title><Dialog.Description>{description}</Dialog.Description></div>
              <Dialog.Close className="icon-button" aria-label="Close dialog" disabled={pending}><X size={17} /></Dialog.Close>
            </header>
            <div className="confirmation-dialog__body">{children}</div>
            <div className="confirmation-dialog__actions">
              <Dialog.Close className="primitive-button" disabled={pending}>Cancel</Dialog.Close>
              <button type="button" className="primitive-button primitive-button--danger" disabled={pending || confirmDisabled} onClick={onConfirm}>{confirmLabel}</button>
            </div>
            <p className="confirmation-dialog__pending" role="status" aria-live="polite">{pending ? pendingLabel : ""}</p>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
