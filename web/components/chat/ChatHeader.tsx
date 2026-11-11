"use client";

import Link from "next/link";
import type { DeadlineEvent } from "@/lib/api";
import { AccountMenu, DeadlinePill, Logo } from "@/components/home/HomeHeader";
import { MusicButton } from "@/components/music/MusicButton";
import type { Resource } from "@/components/home/useResource";

/** The header (64px desktop / 60px phone): the phone menu button, the logo, "← Home" (desktop), the deadline pill (desktop)
 *  or its compact chip (phone) -- Home's component either way -- and Home's account dropdown. */
export function ChatHeader({ deadlines, now, onExpired, onMenu, isOwner }: { deadlines: Resource<{ events: DeadlineEvent[] }>; now: Date | null; onExpired: () => void; onMenu: () => void; isOwner?: boolean | null }) {
  return (
    <header className="ch-hdr" data-testid="chat-header">
      <button type="button" className="ch-menu-btn" onClick={onMenu} aria-label="Past chats and menu" data-testid="menu-button">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h10" />
        </svg>
      </button>
      <Logo />
      <Link href="/home" className="ch-home" data-testid="back-home">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M19 12H5M11 18l-6-6 6-6" />
        </svg>
        Home
      </Link>
      <div className="ch-grow" />
      <DeadlinePill deadlines={deadlines} now={now} onExpired={onExpired} />
      <DeadlinePill deadlines={deadlines} now={now} onExpired={onExpired} compact />
      <MusicButton />
      <AccountMenu isOwner={isOwner} />
    </header>
  );
}
