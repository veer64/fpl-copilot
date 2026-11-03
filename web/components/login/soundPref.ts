import { useSyncExternalStore } from "react";

/** The sound toggle's memory: localStorage "fpl-sound" = "1" | "0", default on. Every storage call is wrapped, so a
 *  private window or blocked storage just means the default. Read through useSyncExternalStore so the server renders
 *  "on" and the browser's stored choice applies on hydration without a setState-in-effect. */
const KEY = "fpl-sound";
const EVENT = "fpl-sound-change";

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "0";
  } catch {
    return true;
  }
}

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
