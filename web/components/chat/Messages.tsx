"use client";

import { memo, useEffect, useRef, useState } from "react";
import type { Feedback } from "@/lib/api";
import { stripSourcesBlock } from "@/lib/sources";
import { Markdown } from "./Markdown";
import { PreviewCard } from "./PreviewCard";
import { SourcesRow } from "./Sources";
import { SystemMessage } from "./SystemMessage";
import { Thinking } from "./Thinking";
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

function SavedBlock({ gw, plural }: { gw: number; plural: boolean }) {
  return (
    <div className="ch-saved" data-testid="saved-block">
      <span className="ch-saved-ic" aria-hidden="true">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12l5 5L20 7" />
        </svg>
      </span>
      <div>
        <b>Saved in FPL Copilot.</b>
        <span>Make {plural ? "these changes" : "this change"} in the FPL app before the GW{gw} deadline.</span>
      </div>
    </div>
  );
}

/** The thread: user bubbles, assistant rows (markdown, the preview card, the saved block, sources, actions), the thinking
 *  row and the system messages. W8a (2026-11-12): memoised -- it re-renders only when the messages (or a countdown's clock)
 *  change, never on the page's own ticks, the music or a card reload; data-renders counts its renders for the regression
 *  test (the wrapper is display:contents, so the rows stay direct flex children of .ch-thread). */
export const MessageList = memo(function MessageList({
  msgs,
  now,
  phone,
  onYes,
  onNo,
  onRetry,
  onStartNew,
  onFeedback,
}: {
  msgs: Msg[];
  now: Date | null;
  phone: boolean;
  onYes: () => void;
  onNo: () => void;
  onRetry: (question: string) => void;
  onStartNew: () => void;
  onFeedback: (m: AssistantMsg, score: Feedback) => void;
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
  return (
    <div ref={wrap} style={{ display: "contents" }} data-testid="message-list" data-renders="0">
      {msgs.map((m, i) => {
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
        const pending = m.key === pendingKey;
        const lastPreview = msgs.slice(0, i + 1).reverse().find((x) => x.kind === "assistant" && x.preview);
        const plural = lastPreview?.kind === "assistant" && (lastPreview.preview?.changes.length ?? 1) > 1;
        const { text: shown } = stripSourcesBlock(m.text, m.sources.length > 0);
        return (
          <div className="ch-ai" key={m.key} data-testid="assistant-message" data-message-id={m.messageId ?? ""}>
            <Avatar />
            <div className="ch-md">
              {m.applied && <SavedBlock gw={m.applied.gw} plural={plural} />}
              {shown.trim() && <Markdown text={shown} />}
              {m.preview && <PreviewCard preview={m.preview} pending={pending} choice={pending ? null : choiceAfter(msgs, i)} now={now} phone={phone} onYes={onYes} onNo={onNo} />}
              <div className="ch-ans-foot">
                {m.sources.length > 0 && <SourcesRow sources={m.sources} id={`src-${m.key}`} />}
                <Actions msg={m} onFeedback={onFeedback} />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
});
