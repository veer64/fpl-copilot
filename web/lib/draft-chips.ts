/** Prompt W11 (O2, O3): EVERY chip a draft chat shows, in one file so the owner can edit the wording. Chips are in the
 *  user's voice. A chip with action "guide" opens the "Enter it in FPL" guide and sends nothing; a chip with action "explain"
 *  (Prompt W11e E2) is answered at once by the server from the draft's own squad explanation -- no model call, $0 -- and
 *  stored as the chat's next turn; every other chip under an answer sends its text as the user's message (the empty
 *  state's chips fill the box, as on every chat). Draft chats never show the Team or General chips. */

export type DraftChip = { text: string; action?: "guide" | "explain" };

/** O2: under the opening message (while no question has been asked yet). */
export const OPENING_CHIPS: DraftChip[] = [
  { text: "Why these players?", action: "explain" },
  { text: "Suggest some changes" },
  { text: "I want to swap a player" },
  { text: "How do I enter this in FPL?", action: "guide" },
];

export const OPENING_MESSAGE =
  "Here's your starting 15, built from our predictions. Does it sound good to you? Suggest any changes you'd like, or ask me why I picked a player.";

export type DraftChipFacts = { captain: string | null; left: number | null; over: number | null };

/** The owner (checkpoint 2): the "spend the money left" chip only when at least this much is left (£m). */
export const SPEND_CHIP_MIN = 0.5;

/** O3: the draft's own suggestions -- a new draft chat's empty state, and the row under the latest answer. */
export function draftChips(f: DraftChipFacts): DraftChip[] {
  const out: DraftChip[] = [];
  if (f.captain) out.push({ text: `Why ${f.captain} as captain?` });
  out.push({ text: "Who's the weakest pick?" });
  out.push({ text: "Is my bench good enough?" });
  if (f.over !== null && f.over > 0) out.push({ text: "How do I get my draft back under £100.0m?" });
  else if (f.left !== null && f.left >= SPEND_CHIP_MIN) out.push({ text: `How would you spend the £${f.left.toFixed(1)}m left?` });
  out.push({ text: "Suggest some changes" });
  out.push({ text: "How do I enter this in FPL?", action: "guide" });
  return out;
}

/** Prompt W11h H3: the owner's follow-up that every code-built answer (the summary, the walkthrough, the captain answer) ends
 *  with -- the same text as draft_tools.EXPLAIN_FOLLOW_UP (Tests/test_drafts.py h3 checks that they match). */
export const EXPLAIN_FOLLOW_UP = "Which player would you like me to go into, or is there anyone you'd like to bring in?";

/** W11h H3: the chips that answer that follow-up, first in the row under such an answer. */
export const FOLLOW_UP_CHIPS: DraftChip[] = [{ text: "Explain one player" }, { text: "Bring someone in" }];

/** The row under the latest answer: the follow-up's chips first when that answer ends with the owner's follow-up. */
export function answerChips(f: DraftChipFacts, lastAnswer: string | null): DraftChip[] {
  const base = draftChips(f);
  return lastAnswer && lastAnswer.trimEnd().endsWith(EXPLAIN_FOLLOW_UP) ? [...FOLLOW_UP_CHIPS, ...base] : base;
}

/** How many chips the row under the latest answer shows at most. */
export const ANSWER_CHIPS_MAX = 4;

function norm(s: string): string {
  return s.replace(/[’']/g, "'").replace(/\s+/g, " ").trim().toLowerCase();
}

/** The owner's rule (checkpoint 1): never show a chip already used in this chat -- a chip is used once its text was sent
 *  (or, for the guide chip, once the guide was opened from a chip). */
export function unusedChips(chips: DraftChip[], sent: string[], guideOpened: boolean, max = ANSWER_CHIPS_MAX): DraftChip[] {
  const used = new Set(sent.map(norm));
  return chips.filter((c) => (c.action === "guide" ? !guideOpened : !used.has(norm(c.text)))).slice(0, max);
}
