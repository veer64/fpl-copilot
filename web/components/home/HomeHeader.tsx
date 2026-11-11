"use client";

import { useEffect, useRef, useState } from "react";
import { useClerk, useUser } from "@clerk/nextjs";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DeleteAccountDialog } from "@/components/account/DeleteAccountDialog";
import { api, type DeadlineEvent, type Me } from "@/lib/api";
import { countdown, countdownShort, formatDeadline, initials, nextEvent } from "@/lib/time";
import { useResource, type Resource } from "./useResource";
import { ErrorBox } from "./ErrorBox";

/** The header: logo + name, the deadline pill (desktop; on narrow screens it moves below the header as a band; the Chat
 *  page's phone header shows the same component's `compact` variant -- Prompt W4), the account button with the dropdown
 *  (avatar, name, email, Sign out, a divider, Delete account -- Prompt W5: the ONE menu Home, Chat, About and Privacy import). */

export function Logo() {
  return (
    <a href="/home" className="hm-brand" aria-label="FPL Copilot home">
      {/* eslint-disable-next-line @next/next/no-img-element -- the 28px logo, as on the login page */}
      <img src="/logo.svg" alt="" width={28} height={28} />
      <span>FPL Copilot</span>
    </a>
  );
}

export function DeadlinePill({
  deadlines,
  now,
  onExpired,
  band = false,
  compact = false,
}: {
  deadlines: Resource<{ events: DeadlineEvent[] }>;
  now: Date | null;
  onExpired: () => void;
  band?: boolean;
  /** the phone chip: "GW10 6h 12m" from the same data (Prompt W4) */
  compact?: boolean;
}) {
  const next = deadlines.status === "ready" && now ? nextEvent(deadlines.data.events, now) : null;
  const expired = deadlines.status === "ready" && now !== null && next === null;
  const asked = useRef(false);
  useEffect(() => {
    if (expired && !asked.current) {
      asked.current = true;
      onExpired(); // every deadline we know has passed: ask the backend for the next ones
    }
    if (!expired) asked.current = false;
  }, [expired, onExpired]);

  const cls = band ? "hm-pill hm-pill-band" : compact ? "hm-pill hm-pill-compact" : "hm-pill";
  if (compact) {
    if (!next) {
      return (
        <span className={cls} role="status" aria-label="Next deadline" aria-busy={deadlines.status !== "error"} data-testid="deadline-chip">
          <span className="hm-dot hm-pulse" aria-hidden="true" />
          <span className="hm-gw">{deadlines.status === "error" ? "GW?" : "GW"}</span>
          <span className="hm-in">…</span>
        </span>
      );
    }
    return (
      <span className={cls} role="status" aria-label={`GW${next.gw} deadline ${countdown(next.deadline_time, now!)}`} data-testid="deadline-chip" data-gw={next.gw} data-deadline={next.deadline_time}>
        <span className="hm-dot hm-pulse" aria-hidden="true" />
        <span className="hm-gw">GW{next.gw}</span>
        <span className="hm-in">{countdownShort(next.deadline_time, now!)}</span>
      </span>
    );
  }
  if (deadlines.status === "error") {
    return (
      <div className={cls} role="status" aria-label="Next deadline" data-testid={band ? "deadline-band" : "deadline-pill"}>
        <span className="hm-dot" aria-hidden="true" style={{ background: "#FF8A7A", boxShadow: "none" }} />
        <span className="hm-when">Deadline unavailable</span>
        <button type="button" className="hm-btn-t" onClick={onExpired}>
          Retry
        </button>
      </div>
    );
  }
  if (!next) {
    return (
      <div className={cls} role="status" aria-label="Next deadline" aria-busy="true" data-testid={band ? "deadline-band" : "deadline-pill"}>
        <span className="hm-dot hm-pulse" aria-hidden="true" />
        <span className="hm-gw">DEADLINE</span>
        <span className="hm-when">…</span>
      </div>
    );
  }
  return (
    <div className={cls} role="status" aria-label="Next deadline" data-testid={band ? "deadline-band" : "deadline-pill"} data-gw={next.gw} data-deadline={next.deadline_time}>
      <span className="hm-dot hm-pulse" aria-hidden="true" />
      <span className="hm-gw">{band ? `GW${next.gw}` : `GW${next.gw} DEADLINE`}</span>
      <span className="hm-when hm-nw">{formatDeadline(next.deadline_time)}</span>
      {!band && <span className="hm-sep" aria-hidden="true" />}
      <span className="hm-in">{countdown(next.deadline_time, now!)}</span>
    </div>
  );
}

const noMe = () => Promise.resolve<Me | null>(null);

/** The account menu. `isOwner` (Prompt W5): a page that already read /me passes it; otherwise the menu reads /me once on
 *  mount. "Delete account" stays disabled until the answer is known (checkpoint C2), then is enabled -- or disabled with the
 *  owner note for user 1. The confirm dialog is the shared ConfirmDelete; focus returns to the account button. */
export function AccountMenu({ isOwner }: { isOwner?: boolean | null }) {
  const { user, isLoaded } = useUser();
  const { signOut } = useClerk();
  const [me] = useResource<Me | null>(isOwner === undefined ? api.me : noMe);
  const [del, setDel] = useState(false);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const name = user?.fullName || user?.firstName || null;
  const email = user?.primaryEmailAddress?.emailAddress ?? null;
  const ini = isLoaded ? initials(name, email) : "";
  const owner: boolean | null = isOwner !== undefined ? isOwner : me.status === "ready" && me.data ? me.data.is_owner : null;
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger ref={trigger} className="hm-acct" aria-label="Account menu" data-testid="account-menu">
          <span className="hm-avatar" aria-hidden="true">
            {ini}
          </span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" sideOffset={8} className="hm-menu hm-menu-in hm-pop" aria-label="Account" data-testid="account-popup">
          <span className="hm-br hm-tl" aria-hidden="true" />
          <span className="hm-br hm-brr" aria-hidden="true" />
          <div className="hm-menu-who">
            <span className="hm-avatar lg" aria-hidden="true">
              {ini}
            </span>
            <div>
              <span className="hm-menu-name" data-testid="account-name">
                {name ?? "FPL manager"}
              </span>
              <span className="hm-menu-email" data-testid="account-email">
                {email ?? ""}
              </span>
            </div>
          </div>
          <DropdownMenuSeparator className="hm-menu-hr" />
          <DropdownMenuItem className="hm-mi" onClick={() => void signOut({ redirectUrl: "/login" })} data-testid="sign-out">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <path d="M16 17l5-5-5-5M21 12H9" />
            </svg>
            <span>Sign out</span>
          </DropdownMenuItem>
          <DropdownMenuSeparator className="hm-menu-hr hm-menu-hr-2" data-testid="menu-divider" />
          <DropdownMenuItem
            className="hm-mi hm-mi-del"
            disabled={owner !== false}
            aria-describedby={owner ? "owner-note" : undefined}
            onClick={() => setDel(true)}
            data-testid="delete-account"
            data-owner={owner === null ? "unknown" : owner}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
            </svg>
            <span>Delete account</span>
          </DropdownMenuItem>
          {owner && (
            <span id="owner-note" className="hm-owner-note" data-testid="owner-note">
              The owner account can’t be deleted here.
            </span>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <DeleteAccountDialog open={del} onClose={() => setDel(false)} returnTo={trigger as React.RefObject<HTMLElement | null>} />
    </>
  );
}

export function HomeHeader({ deadlines, now, onExpired }: { deadlines: Resource<{ events: DeadlineEvent[] }>; now: Date | null; onExpired: () => void }) {
  return (
    <header className="hm-hdr">
      <Logo />
      <DeadlinePill deadlines={deadlines} now={now} onExpired={onExpired} />
      <AccountMenu />
    </header>
  );
}

export { ErrorBox };
