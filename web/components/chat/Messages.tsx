"use client";

import { memo, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Feedback, SquadApplied } from "@/lib/api";
import type { DraftChip } from "@/lib/draft-chips";
import { REDUCED_MOTION, useMediaQuery } from "@/lib/useMediaQuery";
import { stripSourcesBlock } from "@/lib/sources";
import { Markdown } from "./Markdown";
import { PreviewCard } from "./PreviewCard";
import { SourcesRow } from "./Sources";
import { SystemMessage } from "./SystemMessage";
import { Thinking } from "./Thinking";
import { useReveal } from "./reveal";
import { choiceAfter, type AssistantMsg, type Msg } from "./types";

const COPIED_MS = 2000;
const LogoMark = ({ size }: { size: number }) => (
  <svg width={size} height={size} viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
    <path d="M14 2 L25 8.5 V19.5 L14 26 L3 19.5 V8.5 Z" />
    <path d="M9 17 L14 11 L19 17" />
  </svg>
);
const Avatar = () => (
  <span className="ch-avatar" aria-hidden="true">
    <LogoMark size={16} />
  </span>
);

function Actions({ msg, onFeedback }: { msg: AssistantMsg; onFeedback: (m: AssistantMsg, score: Feedback) => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(msg.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), COPIED_MS);
    } catch {
      /* the clipboard is unavailable here: the label stays "Copy" */
    }
  };
  const canVote = !!msg.messageId;
  return (
    <div className="ch-acts" data-testid="answer-actions">
      <button type="button" className={`ch-act${copied ? " copied" : ""}`} onClick={copy} data-testid="copy" aria-live="polite">
        {copied ? (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 12l5 5L20 7" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="9" y="9" width="11" height="11" rx="2" />
            <path d="M5 15V5a1 1 0 0 1 1-1h10" />
          </svg>
        )}
        {copied ? "Copied" : "Copy"}
      </button>
      {canVote && (
        <>
          <button type="button" className={`ch-act ic${msg.feedback === "up" ? " on" : ""}`} aria-label="Good answer" aria-pressed={msg.feedback === "up"} onClick={() => onFeedback(msg, msg.feedback === "up" ? null : "up")} data-testid="thumb-up">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M7 11v9H4v-9z" />
              <path d="M7 11l4-7c1.3 0 2.3 1 2.3 2.3V10h5.2a2 2 0 0 1 2 2.4l-1.3 6A2 2 0 0 1 17.2 20H7" />
            </svg>
          </button>
          <button type="button" className={`ch-act ic${msg.feedback === "down" ? " on" : ""}`} aria-label="Bad answer" aria-pressed={msg.feedback === "down"} onClick={() => onFeedback(msg, msg.feedback === "down" ? null : "down")} data-testid="thumb-down">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ transform: "rotate(180deg)" }}>
              <path d="M7 11v9H4v-9z" />
              <path d="M7 11l4-7c1.3 0 2.3 1 2.3 2.3V10h5.2a2 2 0 0 1 2 2.4l-1.3 6A2 2 0 0 1 17.2 20H7" />
            </svg>
          </button>
        </>
      )}
    </div>
  );
}

function SavedBlock({ applied, plural }: { applied: SquadApplied; plural: boolean }) {
  return (
    <div className="ch-saved" data-testid="saved-block" data-draft={applied.draft ? "true" : undefined}>
      <span className="ch-saved-ic" aria-hidden="true">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12l5 5L20 7" />
        </svg>
      </span>
      {applied.draft ? (
        // Prompt W11: a draft change is free and lives only here -- nothing to do in the FPL app
        <div>
          <b>{applied.kind === "rebuild" ? "Draft rebuilt from the best picks." : "Saved to your draft."}</b>
        </div>
      ) : (
        <div>
          <b>Saved in FPL Copilot.</b>
          <span>
            Make {plural ? "these changes" : "this change"} in the FPL app before the GW{applied.gw} deadline.
          </span>
        </div>
      )}
    </div>
  );
}

/** Prompt W11: a draft chat's chips under an answer -- in the user's voice; the guide chip opens the guide, the others send. */
function DraftChips({ chips, onChip, testId }: { chips: DraftChip[]; onChip: (c: DraftChip) => void; testId: string }) {
  if (!chips.length) return null;
  return (
    <div className="dr-chips" role="list" aria-label="Suggested questions" data-testid={testId}>
      {chips.map((c) => (
        <button type="button" role="listitem" className={`dr-chip${c.action === "guide" ? " guide" : ""}`} key={c.text} onClick={() => onChip(c)} data-testid="draft-chip" data-action={c.action ?? "send"}>
          {c.text}
        </button>
      ))}
    </div>
  );
}

/** Prompt W10: one assistant answer. A fresh answer (`reveal`, set only on the reply that just arrived in this tab) writes
 *  itself out (reveal.ts) unless the reader prefers reduced motion; while it does, the growing text is aria-hidden and a
 *  visually hidden copy carries the whole answer, so a screen reader meets it once, complete. The preview card, Sources,
 *  Copy and the thumbs appear when the text is done (Copy always copies msg.text, the whole answer). */
function AnswerRow({
  m,
  msgs,
  i,
  pending,
  now,
  phone,
  onYes,
  onNo,
  onFeedback,
  chips,
  onChip,
}: {
  m: AssistantMsg;
  msgs: Msg[];
  i: number;
  pending: boolean;
  now: Date | null;
  phone: boolean;
  onYes: (messageId: string | null) => void; // X1: the preview's own answer id
  onNo: (messageId: string | null) => void;
  onFeedback: (m: AssistantMsg, score: Feedback) => void;
  /** Prompt W11: the draft chips under THIS answer (shown once it has finished writing itself out, like Copy and the thumbs) */
  chips?: DraftChip[] | null;
  onChip?: (c: DraftChip) => void;
}) {
  const reduced = useMediaQuery(REDUCED_MOTION);
  const { text: full } = stripSourcesBlock(m.text, m.sources.length > 0);
  const animate = !!m.reveal && !reduced && full.trim().length > 0;
  const { shown, done } = useReveal(full, animate);
  const srCopy: ReactNode = useMemo(() => <Markdown text={full} />, [full]);
  const lastPreview = msgs.slice(0, i + 1).reverse().find((x) => x.kind === "assistant" && x.preview);
  const plural = lastPreview?.kind === "assistant" && (lastPreview.preview?.changes.length ?? 1) > 1;
  return (
    <div className="ch-ai" data-testid="assistant-message" data-message-id={m.messageId ?? ""} data-revealing={!done}>
      <Avatar />
      <div className="ch-md">
        {m.applied && <SavedBlock applied={m.applied} plural={plural} />}
        {done ? (
          full.trim() && srCopy
        ) : (
          <>
            <div aria-hidden="true" data-testid="answer-typing">
              <Markdown text={shown} />
            </div>
            <div className="sr-only" data-testid="answer-sr">
              {srCopy}
            </div>
          </>
        )}
        {done && m.preview && <PreviewCard preview={m.preview} pending={pending} choice={pending ? null : choiceAfter(msgs, i)} now={now} phone={phone} onYes={() => onYes(m.messageId ?? null)} onNo={() => onNo(m.messageId ?? null)} />}
        {done && !m.opening && (
          <div className="ch-ans-foot">
            {m.sources.length > 0 && <SourcesRow sources={m.sources} id={`src-${m.key}`} />}
            <Actions msg={m} onFeedback={onFeedback} />
          </div>
        )}
        {done && chips && onChip && <DraftChips chips={chips} onChip={onChip} testId={m.opening ? "opening-chips" : "answer-chips"} />}
      </div>
    </div>
  );
}

/** The thread: user bubbles, assistant rows (markdown, the preview card, the saved block, sources, actions), the thinking
 *  row and the system messages. W8a (2026-11-12): memoised -- it re-renders only when the messages (or a countdown's clock)
 *  change, never on the page's own ticks, the music or a card reload; data-renders counts its renders for the regression
 *  test (the wrapper is display:contents, so the turns stay direct flex children of .ch-thread). W10: the rows are grouped
 *  in turns (a user message and what follows it); the LAST turn is at least the scroll box's height (--ch-turn-min, set
 *  by the page), so the page can put the latest question at the top of the box and the answer grows below it without
 *  the view moving -- the blank space under a short answer is that minimum. */
export const MessageList = memo(function MessageList({
  msgs,
  now,
  phone,
  onYes,
  onNo,
  onRetry,
  onStartNew,
  onFeedback,
  draft = null,
}: {
  msgs: Msg[];
  now: Date | null;
  phone: boolean;
  onYes: (messageId: string | null) => void; // X1: the preview's own answer id
  onNo: (messageId: string | null) => void;
  onRetry: (question: string) => void;
  onStartNew: () => void;
  onFeedback: (m: AssistantMsg, score: Feedback) => void;
  /** Prompt W11: a draft chat's chips -- O2's under the opening message while no question has been asked, else the unused O3
   *  chips under the LATEST answer (never under a pending preview, whose next step is Yes / No) */
  draft?: { opening: DraftChip[]; answer: DraftChip[]; onChip: (c: DraftChip) => void } | null;
}) {
  // the render counter lives on the DOM node and is bumped after each commit (an effect with no deps), never during render
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = wrap.current;
    if (el) el.dataset.renders = String(Number(el.dataset.renders ?? "0") + 1);
  });
  // the latest preview with no user message after it is the pending one; every earlier preview is answered
  let pendingKey: string | null = null;
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i];
    if (m.kind === "user") break;
    if (m.kind === "assistant" && m.preview) {
      pendingKey = m.key;
      break;
    }
  }
  const rowOf = (m: Msg, i: number): ReactNode => {
    if (m.kind === "user") return <div className="ch-user" key={m.key} data-testid="user-message">{m.text}</div>;
    if (m.kind === "thinking")
      return (
        <div className="ch-ai center" key={m.key}>
          <Avatar />
          <Thinking startedAt={m.startedAt} resumed={m.resumed} />
        </div>
      );
    if (m.kind === "system")
      return (
        <div className="ch-ai" key={m.key}>
          <Avatar />
          <SystemMessage msg={m} now={now} onRetry={onRetry} onStartNew={onStartNew} />
        </div>
      );
    return (
      <AnswerRow
        key={m.key}
        m={m}
        msgs={msgs}
        i={i}
        pending={m.key === pendingKey}
        now={now}
        phone={phone}
        onYes={onYes}
        onNo={onNo}
        onFeedback={onFeedback}
        chips={m.key === chipsKey ? chipsFor : null}
        onChip={draft?.onChip}
      />
    );
  };
  // Prompt W11: which answer carries the draft chips (one row at most)
  let chipsKey: string | null = null;
  let chipsFor: DraftChip[] | null = null;
  if (draft) {
    const asked = msgs.some((m) => m.kind === "user");
    const lastMsg = msgs[msgs.length - 1];
    if (!asked && msgs[0]?.kind === "assistant" && msgs[0].opening) {
      chipsKey = msgs[0].key;
      chipsFor = draft.opening;
    } else if (lastMsg?.kind === "assistant" && !lastMsg.opening && lastMsg.key !== pendingKey) {
      chipsKey = lastMsg.key;
      chipsFor = draft.answer;
    }
  }
  // turns: a user message starts one; anything before the first user message is a leading group of its own
  const turns: { key: string; rows: ReactNode[] }[] = [];
  msgs.forEach((m, i) => {
    if (m.kind === "user" || turns.length === 0) turns.push({ key: m.key, rows: [] });
    turns[turns.length - 1].rows.push(rowOf(m, i));
  });
  const lastIsTurn = msgs.some((m) => m.kind === "user");
  return (
    <div ref={wrap} style={{ display: "contents" }} data-testid="message-list" data-renders="0">
      {turns.map((t, n) => {
        const last = n === turns.length - 1 && lastIsTurn;
        return (
          <div className={`ch-turn${last ? " last" : ""}`} key={t.key} data-testid="turn" data-last={last || undefined}>
            {t.rows}
          </div>
        );
      })}
    </div>
  );
});
