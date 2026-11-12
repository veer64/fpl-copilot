/** Prompt W11 (O2, O3): EVERY chip a draft chat shows, in one file so the owner can edit the wording. Chips are in the
 *  user's voice. A chip with action "guide" opens the "Enter it in FPL" guide and sends nothing; every other chip under an
 *  answer sends its text as the user's message (the empty state's chips fill the box, as on every chat). Draft chats never
 *  show the Team or General chips. */

export type DraftChip = { text: string; action?: "guide" };

/** O2: under the opening message (while no question has been asked yet). */
export const OPENING_CHIPS: DraftChip[] = [
  { text: "Why these players?" },
  { text: "Suggest some changes" },
  { text: "I want to swap a player" },
  { text: "How do I enter this in FPL?", action: "guide" },
];

export const OPENING_MESSAGE =
  "Here's your starting 15, built from our predictions. Does it sound good to you? Suggest any changes you'd like, or ask me why I picked a player.";

export type DraftChipFacts = { captain: string | null; left: number | null; over: number | null };

/** O3: the draft's own suggestions -- a new draft chat's empty state, and the row under the latest answer. */
export function draftChips(f: DraftChipFacts): DraftChip[] {
  const out: DraftChip[] = [];
  if (f.captain) out.push({ text: `Why ${f.captain} as captain?` });
  out.push({ text: "Who's the weakest pick?" });
  out.push({ text: "Is my bench good enough?" });
  if (f.over !== null && f.over > 0) out.push({ text: "How do I get my draft back under £100.0m?" });
  else if (f.left !== null && f.left > 0) out.push({ text: `How would you spend the £${f.left.toFixed(1)}m left?` });
  out.push({ text: "Suggest some changes" });
  out.push({ text: "How do I enter this in FPL?", action: "guide" });
  return out;
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
