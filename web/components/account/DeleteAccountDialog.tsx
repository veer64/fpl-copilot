"use client";

import { useRouter } from "next/navigation";
import { useAuth, useClerk } from "@clerk/nextjs";
import { ApiError, api } from "@/lib/api";
import { CONTACT_EMAIL, ConfirmDelete } from "./ConfirmDelete";

/** Delete account (Prompt W5, the brief's flow): confirm -> deleting -> DELETE /me -> the "deleted" note is queued for the
 *  Login page (sessionStorage, shown once) -> Clerk sign-out -> /login. A failed delete shows the brief's alert and "Try
 *  again"; the one case where the sign-in is gone but our rows stayed (HTTP 500) shows the server's own sentence
 *  (checkpoint C3). */

export const DELETED_FLAG = "fpl.account.deleted";
export const DELETE_ITEMS = ["Your account", "Your FPL teams", "Saved squads", "Chats", "Feedback"];

export function deleteAccountError(err: unknown) {
  if (err instanceof ApiError && err.status === 500 && err.detail) return err.detail;
  return (
    <>
      Couldn’t delete your account — try again, or email{" "}
      <a href={`mailto:${CONTACT_EMAIL}`} className="hm-del-link">
        {CONTACT_EMAIL}
      </a>
      .
    </>
  );
}

export function DeleteAccountDialog({ open, onClose, returnTo }: { open: boolean; onClose: () => void; returnTo?: React.RefObject<HTMLElement | null> }) {
  const router = useRouter();
  const { getToken } = useAuth();
  const { signOut } = useClerk();
  const confirm = async () => {
    await api.deleteAccount(getToken);
    try {
      window.sessionStorage.setItem(DELETED_FLAG, "1");
    } catch {
      /* private mode: the note is simply not shown */
    }
    try {
      await signOut({ redirectUrl: "/login" });
    } catch {
      router.replace("/login"); // the Clerk user is already gone: the session cannot be ended server-side
    }
    await new Promise(() => undefined); // the page is leaving: keep the "Deleting…" state until it does
  };
  return (
    <ConfirmDelete
      open={open}
      onClose={onClose}
      title="Delete your account?"
      intro="This removes:"
      items={DELETE_ITEMS}
      warning="This can’t be undone."
      confirmLabel="Delete my account"
      busyLabel="Deleting…"
      errorFor={deleteAccountError}
      onConfirm={confirm}
      returnTo={returnTo}
      testId="delete-account"
    />
  );
}
