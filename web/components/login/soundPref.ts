import { useSyncExternalStore } from "react";

/** The mute button's memory: localStorage "fpl-sound" = "1" (sound on, the default) | "0" (muted; never auto-start).
 *  Every storage call is wrapped, so a private window or blocked storage just means the default. Read through
 *  useSyncExternalStore so the server renders "on" and the browser's stored choice applies on hydration without a
 *  setState-in-effect. */
const KEY = "fpl-sound";
const EVENT = "fpl-sound-change";

/** The stored choice right now (true = sound on). Also used as the last word before any automatic play(): on the
 *  hydration render the hook still shows the server's default, and a remembered mute must win even then. */
export function readSoundPref(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "0";
  } catch {
    return true;
  }
}

const read = readSoundPref;

function subscribe(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener(EVENT, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(EVENT, cb);
  };
}

export function useSoundPref(): boolean {
  return useSyncExternalStore(subscribe, read, () => true);
}

export function setSoundPref(on: boolean) {
  try {
    window.localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* no storage: the choice lasts for this page only */
  }
  window.dispatchEvent(new Event(EVENT));
}
