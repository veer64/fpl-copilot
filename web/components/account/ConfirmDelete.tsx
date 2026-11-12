"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer";
import { NARROW, useMediaQuery } from "@/lib/useMediaQuery";

/** The destructive confirm (Prompt W5, delete-account-states 03-05 / 07): a Dialog on desktop, a bottom sheet on the phone.
 *  Title with the coral warning icon, an intro, an optional "This removes:" list, the red warning line, an inline alert
 *  (role="alert") after a failure, Cancel + the red action (busy: spinner + the busy label, aria-busy, nothing can close it;
 *  after an error the action reads "Try again"). Focus starts on Cancel; Esc / Cancel / outside click close; focus returns
 *  to `returnTo` when given (the account button), else to the opener. Shared by Delete account, Delete chat and Remove team. */

const Trash = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
  </svg>
);
const Spin = () => (
  <svg className="hm-del-spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3a9 9 0 1 0 9 9" />
  </svg>
);
const Cross = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
);

export type ConfirmDeleteProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  intro: ReactNode;
  items?: string[];
  warning?: string;
  confirmLabel: string;
  cancelLabel?: string; // W9: "Stay" on the guest confirm
  busyLabel: string;
  /** the inline alert for a failed attempt; `err` is what onConfirm rejected with */
  errorFor: (err: unknown) => ReactNode;
  /** resolves when the delete is done (the caller navigates or closes), rejects on failure (the alert shows) */
  onConfirm: () => Promise<void>;
  /** where focus goes when the dialog closes (the account button); else the opener */
  returnTo?: React.RefObject<HTMLElement | null>;
  testId: string;
  /** Prompt W11: "alertdialog" for the Delete draft confirm (the brief); default: the dialog's own role */
  role?: "alertdialog";
};

function Body({ title, intro, items, warning, confirmLabel, cancelLabel, busyLabel, busy, error, onCancel, onConfirm, cancelRef, phone }: {
  title: string;
  intro: ReactNode;
  items?: string[];
  warning?: string;
  confirmLabel: string;
  cancelLabel?: string;
  busyLabel: string;
  busy: boolean;
  error: ReactNode | null;
  onCancel: () => void;
  onConfirm: () => void;
  cancelRef: React.RefObject<HTMLButtonElement | null>;
  phone: boolean;
}) {
  const TitleTag = phone ? DrawerTitle : DialogTitle;
  return (
    <div className={`hm-del${phone ? " phone" : ""}`} data-testid="confirm-body" data-busy={busy} data-error={!!error}>
      {!phone && (
        <>
          <span className="hm-br hm-tl hm-br-red" aria-hidden="true" />
          <span className="hm-br hm-brr hm-br-red" aria-hidden="true" />
        </>
      )}
      {phone && <span className="hm-del-handle" aria-hidden="true" />}
      <div className="hm-del-head">
        <span className="hm-del-ic" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3l9 16H3z" />
            <path d="M12 10v4M12 17h.01" />
          </svg>
        </span>
        <div>
          <TitleTag className="hm-del-title" data-testid="confirm-title">
            {title}
          </TitleTag>
          <span className="hm-del-intro" data-testid="confirm-intro">
            {intro}
          </span>
        </div>
      </div>
      {items && items.length > 0 && (
        <ul className="hm-del-list" data-testid="confirm-list">
          {items.map((it) => (
            <li key={it}>
              <span aria-hidden="true">
                <Cross />
              </span>
              {it}
            </li>
          ))}
        </ul>
      )}
      {warning && (
        <span className="hm-del-warn" data-testid="confirm-warning">
          {warning}
        </span>
      )}
      {error && (
        <div role="alert" className="hm-del-alert" data-testid="confirm-error">
          {error}
        </div>
      )}
      <div className="hm-del-acts">
        <button type="button" className="hm-del-cancel" ref={cancelRef} onClick={onCancel} disabled={busy} data-testid="confirm-cancel">
          {cancelLabel ?? "Cancel"}
        </button>
        <button type="button" className="hm-btn-d" onClick={onConfirm} disabled={busy} aria-busy={busy || undefined} data-testid="confirm-delete">
          {busy ? (
            <>
              <Spin />
              {busyLabel}
            </>
          ) : (
            <>
              <Trash />
              {error ? "Try again" : confirmLabel}
            </>
          )}
        </button>
      </div>
    </div>
  );
}

export function ConfirmDelete(props: ConfirmDeleteProps) {
  const { open, onClose, onConfirm, errorFor, returnTo, testId, role } = props;
  const narrow = useMediaQuery(NARROW);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ReactNode | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- a closed dialog forgets its last attempt
      setError(null);
      setBusy(false);
    }
  }, [open]);

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(errorFor(err));
      setBusy(false);
      window.requestAnimationFrame(() => cancelRef.current?.focus());
    }
  };
  const change = (next: boolean) => {
    if (!next && !busy) onClose();
  };
  const body = <Body {...props} busy={busy} error={error} onCancel={() => change(false)} onConfirm={confirm} cancelRef={cancelRef} phone={narrow} />;

  if (narrow) {
    return (
      <Drawer open={open} onOpenChange={change} swipeDirection="down">
        <DrawerContent className="hm-del-sheet" initialFocus={cancelRef} finalFocus={returnTo} data-testid={`${testId}-sheet`} aria-busy={busy || undefined} {...(role ? { role } : {})}>
          {body}
        </DrawerContent>
      </Drawer>
    );
  }
  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogContent className="hm-del-dialog hm-pop" showCloseButton={false} initialFocus={cancelRef} finalFocus={returnTo} data-testid={`${testId}-dialog`} aria-busy={busy || undefined} {...(role ? { role } : {})}>
        {body}
      </DialogContent>
    </Dialog>
  );
}

export const CONTACT_EMAIL = "veersanghavi8@gmail.com";
