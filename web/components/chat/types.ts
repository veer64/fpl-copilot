import type { Feedback, Source, SquadApplied, SquadPreview } from "@/lib/api";

/** The thread as the page holds it (Prompt W4): the stored rows plus the client-only system messages and the thinking row. */
export type UserMsg = { kind: "user"; key: string; text: string; at: string | null };
export type AssistantMsg = {
  kind: "assistant";
  key: string;
  messageId: string | null;
  text: string;
  at: string | null;
  sources: Source[];
  preview: SquadPreview | null;
  applied: SquadApplied | null;
  feedback: Feedback;
};
export type SystemMsg =
  | { kind: "system"; key: string; variant: "limit"; resetAt: string }
  | { kind: "system"; key: string; variant: "rate"; untilMs: number }
  | { kind: "system"; key: string; variant: "team"; threadId: string | null }
  | { kind: "system"; key: string; variant: "error"; question: string; why: string };
/** `resumed` (W7b): the answer was in flight when the page loaded (a pending row from the server) -- "Still working on this
 *  answer…" and the page re-reads the thread until it lands. */
export type ThinkingMsg = { kind: "thinking"; key: string; startedAt: number; resumed?: boolean; question?: string };
export type Msg = UserMsg | AssistantMsg | SystemMsg | ThinkingMsg;

export type Context = { kind: "team"; teamId: number } | { kind: "general" };

/** A preview is pending when it is the thread's LATEST preview and no user message follows it (C3: expiry changes nothing). */
export function pendingPreview(msgs: Msg[]): { msg: AssistantMsg; preview: SquadPreview } | null {
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i];
    if (m.kind === "user") return null;
    if (m.kind === "assistant" && m.preview) return { msg: m, preview: m.preview };
  }
  return null;
}

/** The user's reply to a preview: the next user message after it, as the card's "You chose …" line. */
export function choiceAfter(msgs: Msg[], index: number): string | null {
  for (let i = index + 1; i < msgs.length; i++) {
    const m = msgs[i];
    if (m.kind === "user") {
      const t = m.text.trim();
      if (/^yes\b/i.test(t)) return "Yes, apply";
      if (/^no\b/i.test(t)) return "No, keep it";
      return t.length > 40 ? `${t.slice(0, 39).trimEnd()}…` : t;
    }
  }
  return null;
}

let seq = 0;
export function key(prefix: string): string {
  seq += 1;
  return `${prefix}-${Date.now().toString(36)}-${seq}`;
}
