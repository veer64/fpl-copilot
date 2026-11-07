"use client";

import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import { MESSAGE_MAX } from "@/lib/api";

const COUNTER_FROM = 1800;
const MAX_HEIGHT = 160;

/** The pinned chat box: multi-line, grows to 160px, Enter sends and Shift+Enter adds a line, maxlength 2,000 with the amber
 *  counter from 1,800; disabled (dim border, grey send) with the state's own text; the FROM HOME tag when the question was
 *  prefilled; the footer line in one grey. */
export function Composer({
  value,
  onChange,
  onSend,
  disabledText,
  placeholder,
  prefilled,
  prefilledNote,
  textareaRef,
  onTyping,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  disabledText: string | null;
  placeholder: string;
  prefilled: boolean;
  prefilledNote: string;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onTyping?: () => void;
  ariaLabel: string;
}) {
  const own = useRef<HTMLTextAreaElement | null>(null);
  const setRef = (el: HTMLTextAreaElement | null) => {
    own.current = el;
    textareaRef.current = el;
  };
  useLayoutEffect(() => {
    const el = own.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(MAX_HEIGHT, el.scrollHeight)}px`;
  }, [value]);
  useEffect(() => {
    if (prefilled) own.current?.focus();
  }, [prefilled]);
  const off = disabledText !== null;
  const canSend = !off && value.trim().length > 0;
  const n = value.length;
  return (
    <div className="ch-composer" data-testid="composer">
      <div className="ch-composer-in">
        <div className={`ch-box${off ? " off" : prefilled ? " prefilled" : ""}`} data-testid="chat-box" data-disabled={off}>
          {prefilled && !off && (
            <span className="ch-box-tag" data-testid="from-home-tag">
              <span className="ch-from-home">FROM HOME</span>
              <span>{prefilledNote}</span>
            </span>
          )}
          <div className="ch-box-row">
            <label htmlFor="composer" className="ch-sr">
              {ariaLabel}
            </label>
            <textarea
              id="composer"
              ref={setRef}
              rows={1}
              maxLength={MESSAGE_MAX}
              placeholder={off ? disabledText ?? "" : placeholder}
              value={off ? "" : value}
              disabled={off}
              data-testid="chat-input"
              onChange={(e) => {
                onChange(e.target.value.slice(0, MESSAGE_MAX));
                onTyping?.();
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  if (canSend) onSend();
                }
              }}
            />
            <div className="ch-box-side">
              {!off && n >= COUNTER_FROM && (
                <span className="ch-count" data-testid="char-counter">
                  {n.toLocaleString("en-GB")} / {MESSAGE_MAX.toLocaleString("en-GB")}
                </span>
              )}
              <button type="button" className="ch-send" aria-label={off ? "Send (disabled)" : "Send"} disabled={!canSend} onClick={onSend} data-testid="send">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 19V5M5 12l7-7 7 7" />
                </svg>
              </button>
            </div>
          </div>
        </div>
        <span className="ch-foot" data-testid="footer-line">
          <span className="desk">ENTER TO SEND · SHIFT + ENTER FOR A NEW LINE · SPINNER WORDS NEED ELITE BALL KNOWLEDGE</span>
          <span className="phone">SPINNER WORDS NEED ELITE BALL KNOWLEDGE</span>
        </span>
      </div>
    </div>
  );
}
