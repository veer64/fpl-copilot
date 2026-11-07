/** The spinner words (Prompt W4, 2026-11-06): the ONLY place the list lives. Shown verbatim while an answer is being
 *  written -- one at random first, the next every ~3 s, never the same twice in a row; an empty list falls back to
 *  ["Thinking…"]. Add a phrase: add a line. */
export const SPINNER_WORDS: readonly string[] = [
  "Sadio Mané is the best football player in the world!",
  "I don't do ifs, buts and maybes. I do absolutes!",
  "Aubama who? Aubama what? Aubamebloodclaatyang!",
  "It's time to goooo!",
  "I'm tired, Robbie!",
  "When is it gonna end, Robbie?",
  "The game's gone!",
  "He's got to go, blud!",
  "Why you laughing for? I'm being serious!",
  "If my grandmother had wheels, she'd be a bike!",
  "I prefer not to speak.",
  "If I speak, I am in big trouble.",
  "Three for me, two for them. Respect!",
  "These are investments from the past!",
  "I have nussing to say.",
  "I am the Special One.",
  "Sacked in the morning!",
  "BOOM!",
  "Twice! TWICE!",
  "We do not let this slip!",
  "AGÜEROOOOOOOO!",
  "And it's LIVE!",
  "Corner taken quickly... ORIGI!",
  "Why always me?",
  "Chat shit, get banged.",
  "Stay humble, eh!",
  "This is football heritage.",
  "You have to fight for your right to party!",
  "I'm a normal guy.",
  "I will love it if we beat them!",
  "It tastes like promotion!",
  "I'm being serious, Robbie!",
  "What are we doing, Robbie?!",
  "I am José Mourinho.",
  "Six times, baby!",
  "This is what he does!",
  "THERE IS NO PASSION! THERE IS NO VISION! THERE IS NO AGGRESSION!",
  "Sometimes maybe good, sometimes maybe shit!",
  "SIUUUUUU!",
  "Calma, calma!",
];

export const FALLBACK_WORD = "Thinking…";

/** The list the spinner uses: the words, or the fallback when the list is empty. */
export function spinnerWords(): readonly string[] {
  return SPINNER_WORDS.length ? SPINNER_WORDS : [FALLBACK_WORD];
}

/** A random index other than `previous` (any index when the list has one entry). */
export function nextWordIndex(previous: number | null, n: number = spinnerWords().length): number {
  if (n <= 1) return 0;
  let i = Math.floor(Math.random() * n);
  if (i === previous) i = (i + 1 + Math.floor(Math.random() * (n - 1))) % n;
  return i;
}
